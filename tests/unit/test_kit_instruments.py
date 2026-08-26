from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np

from isaac_audio_sensors.kit.instruments import (
    COLOR_CLEAR,
    COLOR_OCCLUDED,
    COLOR_UNKNOWN,
    DETECTION_HISTORY_LIMIT,
    append_detection_history,
    compass_unit_xy,
    compass_view_model,
    meter_fraction,
    meter_view_models,
    record_detection_events,
    render_compass_rgba,
    rms_db,
    timeline_rows,
)


def test_compass_unit_xy_maps_clockwise_bearings_with_forward_up():
    assert compass_unit_xy(0.0) == (0.0, 1.0)
    x, y = compass_unit_xy(90.0)
    assert math.isclose(x, 1.0, abs_tol=1e-9)
    assert math.isclose(y, 0.0, abs_tol=1e-9)
    x, y = compass_unit_xy(180.0)
    assert math.isclose(x, 0.0, abs_tol=1e-9)
    assert math.isclose(y, -1.0, abs_tol=1e-9)
    x, y = compass_unit_xy(270.0)
    assert math.isclose(x, -1.0, abs_tol=1e-9)
    assert math.isclose(y, 0.0, abs_tol=1e-9)


def test_compass_view_model_primary_candidates_and_colors():
    view_model = compass_view_model(
        bearing_deg=45.0,
        candidate_bearings=(45.0, 315.0),
        sector="straight_right",
        confidence=0.75,
        occluded=False,
    )
    assert len(view_model.needles) == 2
    assert view_model.needles[0].is_primary
    assert view_model.needles[0].bearing_deg == 45.0
    assert not view_model.needles[1].is_primary
    assert view_model.needles[1].bearing_deg == 315.0
    assert view_model.sector_center_deg == 45.0
    assert view_model.color_rgba == COLOR_CLEAR
    assert "bearing 45.0 deg" in view_model.summary
    assert "sector straight_right" in view_model.summary
    assert "confidence 0.75" in view_model.summary
    assert "clear" in view_model.summary

    occluded = compass_view_model(bearing_deg=10.0, occluded=True)
    assert occluded.color_rgba == COLOR_OCCLUDED
    assert "occluded" in occluded.summary


def test_compass_view_model_without_bearing_reports_no_needles():
    view_model = compass_view_model(bearing_deg=None, sector=None)
    assert view_model.needles == ()
    assert view_model.summary == "no bearing"
    assert view_model.color_rgba == COLOR_UNKNOWN
    assert view_model.confidence == 0.0


def test_compass_view_model_clamps_confidence():
    assert compass_view_model(bearing_deg=0.0, confidence=7.0).confidence == 1.0
    assert compass_view_model(bearing_deg=0.0, confidence=-3.0).confidence == 0.0


def test_rms_db_and_meter_fraction_mapping():
    assert rms_db(1.0) == 0.0
    assert math.isclose(rms_db(0.001) or 0.0, -60.0, abs_tol=1e-9)
    assert rms_db(0.0) is None
    assert rms_db(-1.0) is None
    assert meter_fraction(0.0) == 1.0
    assert meter_fraction(-60.0) == 0.0
    assert meter_fraction(-30.0) == 0.5
    assert meter_fraction(None) == 0.0
    assert meter_fraction(12.0) == 1.0


def test_meter_view_models_order_and_text():
    meters = meter_view_models(
        {"left": 0.2, "front": 0.24, "rear": 0.18, "right": 0.22, "aux": 0.1}
    )
    assert [meter.mic_id for meter in meters] == [
        "front",
        "right",
        "rear",
        "left",
        "aux",
    ]
    assert all("dB" in meter.text for meter in meters)
    assert meters[0].fraction == max(meter.fraction for meter in meters)

    silent = meter_view_models({"front": 0.0})
    assert silent[0].db is None
    assert silent[0].fraction == 0.0
    assert "silent" in silent[0].text

    assert meter_view_models({"front": float("nan")}) == ()


def _frame(detections, frame_id="frame_001", backend_id="tdoa_synthetic"):
    return SimpleNamespace(
        frame_id=frame_id,
        backend_id=backend_id,
        detections=tuple(detections),
    )


def _detection(
    *,
    timestamp_ms=1000,
    source_id="speaker_a",
    class_label="speech_generic",
    bearing=90.0,
    sector="right",
    confidence=0.8,
    occluded=False,
):
    return SimpleNamespace(
        timestamp_ms=timestamp_ms,
        source_id=source_id,
        class_label=class_label,
        occluded=occluded,
        source_distance_m=2.0,
        doa=SimpleNamespace(
            estimated_bearing_deg=bearing,
            bearing_sector=sector,
            bearing_confidence=confidence,
        ),
    )


def test_record_detection_events_flattens_frame_detections():
    events = record_detection_events(_frame([_detection(), _detection(occluded=True)]))
    assert len(events) == 2
    assert events[0]["frame_id"] == "frame_001"
    assert events[0]["backend"] == "tdoa_synthetic"
    assert events[0]["bearing_deg"] == 90.0
    assert events[0]["sector"] == "right"
    assert events[0]["occluded"] is False
    assert events[1]["occluded"] is True


def test_append_detection_history_trims_to_limit():
    history: list[dict] = []
    for index in range(DETECTION_HISTORY_LIMIT + 10):
        append_detection_history(
            history,
            _frame([_detection(timestamp_ms=index)], frame_id=f"frame_{index}"),
        )
    assert len(history) == DETECTION_HISTORY_LIMIT
    assert history[-1]["frame_id"] == f"frame_{DETECTION_HISTORY_LIMIT + 9}"
    assert history[0]["frame_id"] == "frame_10"


def test_timeline_rows_newest_first_with_occlusion_marker():
    history = [
        {
            "timestamp_ms": 1000,
            "class_label": "speech_generic",
            "bearing_deg": 90.0,
            "sector": "right",
            "occluded": False,
        },
        {
            "timestamp_ms": 2000,
            "class_label": None,
            "source_id": "oven",
            "bearing_deg": None,
            "sector": None,
            "occluded": True,
        },
    ]
    rows = timeline_rows(history, max_rows=12)
    assert len(rows) == 2
    assert "oven" in rows[0].text
    assert "ambiguous" in rows[0].text
    assert "occluded" in rows[0].text
    assert rows[0].occluded is True
    assert "speech_generic" in rows[1].text
    assert "90.0 deg" in rows[1].text
    assert "clear" in rows[1].text

    assert len(timeline_rows(history, max_rows=1)) == 1
    assert timeline_rows([], max_rows=12) == ()


def test_render_compass_rgba_draws_needle_toward_bearing():
    size = 96
    center = (size - 1) / 2.0
    ring_radius = size * 0.46

    def needle_pixel(image, bearing_deg):
        unit_x, unit_y = compass_unit_xy(bearing_deg)
        px = int(round(center + unit_x * ring_radius * 0.5))
        py = int(round(center - unit_y * ring_radius * 0.5))
        return image[py, px]

    clear = render_compass_rgba(
        compass_view_model(bearing_deg=0.0, occluded=False), size=size
    )
    assert clear.shape == (size, size, 4)
    assert clear.dtype == np.uint8
    pixel = needle_pixel(clear, 0.0)
    assert int(pixel[1]) > int(pixel[0])  # green needle
    off_pixel = needle_pixel(clear, 180.0)
    assert int(off_pixel[1]) < 100  # background away from the needle

    occluded = render_compass_rgba(
        compass_view_model(bearing_deg=90.0, occluded=True), size=size
    )
    pixel = needle_pixel(occluded, 90.0)
    assert int(pixel[0]) > int(pixel[1])  # red needle

    empty = render_compass_rgba(compass_view_model(bearing_deg=None), size=size)
    assert empty.shape == (size, size, 4)
