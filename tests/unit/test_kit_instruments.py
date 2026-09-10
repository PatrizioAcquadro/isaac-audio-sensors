from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from isaac_audio_sensors.core.types import DoaEstimate
from isaac_audio_sensors.kit.instruments import (
    OBSERVATION_HISTORY_LIMIT,
    append_observation_history,
    compass_unit_xy,
    compass_view_model,
    meter_fraction,
    meter_view_models,
    perception_status_text,
    record_observation_events,
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


def test_compass_groups_simultaneous_events_and_unresolved_candidates():
    view = compass_view_model(
        (
            DoaEstimate(estimated_bearing_deg=45, estimated_elevation_deg=20),
            DoaEstimate(
                estimated_bearing_deg=None,
                candidate_bearing_deg=(90, 270),
                candidate_elevation_deg=(-30, 30),
                ambiguity_class="front_back",
                ambiguity_reason="stereo",
            ),
            None,
        )
    )
    assert [(n.bearing_deg, n.is_primary, n.event_index) for n in view.needles] == [
        (45, True, 0),
        (90, False, 1),
        (270, False, 1),
    ]
    assert "elevation 20.0 deg" in view.event_rows[0]
    assert "elevation alternatives -30.0, 30.0 deg" in view.event_rows[1]
    assert "front_back: stereo" in view.event_rows[1]
    assert "DOA unavailable" in view.event_rows[2]
    assert compass_view_model(()).needles == ()


@pytest.mark.parametrize(
    "active, localization, complete, expected",
    [
        (False, {"status": "no_events"}, True, "Activity: inactive"),
        (
            True,
            {"status": "unavailable", "reason": "insufficient_context"},
            False,
            "Localization: warm-up",
        ),
        (
            True,
            {"status": "unavailable", "reason": "unsupported_geometry"},
            True,
            "unsupported_geometry",
        ),
        (None, {"status": "disabled"}, True, "Localization: disabled"),
    ],
)
def test_perception_status_preserves_availability(
    active, localization, complete, expected
):
    frame = SimpleNamespace(
        sample_rate_hz=16000,
        max_observations=0,
        observations=(),
        diagnostics={
            "perception": {
                "activity_detected": active,
                "localization": localization,
                "truncated_observation_count": 2,
                "doa_context": {
                    "complete": complete,
                    "available_duration_s": 0.1,
                    "required_duration_s": 0.75,
                },
            }
        },
    )
    text = perception_status_text(frame)
    assert expected in text
    assert "Capacity: 0 | Truncated: 2" in text
    assert "16000 Hz" in text and "not a response-delay measurement" in text
    assert "No sensor frame" in perception_status_text(None)


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


def _frame(
    observations,
    frame_id="frame_001",
    producer_id="analytic_acoustics",
    timestamp_ms=1000,
):
    return SimpleNamespace(
        frame_id=frame_id,
        producer_id=producer_id,
        timestamp_ms=timestamp_ms,
        observations=tuple(observations),
    )


def _observation(
    *,
    observation_id="observation_a",
    origin="signal_derived",
    detector_id="fake_activity",
    detection_score=2.0,
    bearing=90.0,
    sector="right",
    confidence=0.8,
):
    return SimpleNamespace(
        observation_id=observation_id,
        origin=origin,
        detector_id=detector_id,
        detection_score=detection_score,
        doa=DoaEstimate(estimated_bearing_deg=bearing, bearing_confidence=confidence),
    )


def test_record_observation_events_flattens_frame_observations():
    events = record_observation_events(
        _frame([_observation(), _observation(observation_id="observation_b")])
    )
    assert len(events) == 2
    assert events[0]["frame_id"] == "frame_001"
    assert events[0]["producer_id"] == "analytic_acoustics"
    assert "bearing 90.0 deg" in events[0]["text"]


def test_append_observation_history_trims_to_limit():
    history: list[dict] = []
    for index in range(OBSERVATION_HISTORY_LIMIT + 10):
        append_observation_history(
            history,
            _frame([_observation()], frame_id=f"frame_{index}", timestamp_ms=index),
        )
    assert len(history) == OBSERVATION_HISTORY_LIMIT
    assert history[-1]["frame_id"] == f"frame_{OBSERVATION_HISTORY_LIMIT + 9}"
    assert history[0]["frame_id"] == "frame_10"


def test_timeline_rows_newest_first():
    history = [
        {"timestamp_ms": 1000, "text": "Event 1: bearing 90.0 deg"},
        {"timestamp_ms": 2000, "text": "Event 1: DOA unavailable"},
    ]
    rows = timeline_rows(history)
    assert "DOA unavailable" in rows[0]
    assert "90.0 deg" in rows[1]
    assert len(timeline_rows(history, max_rows=1)) == 1
    assert timeline_rows([]) == ()


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
        compass_view_model((DoaEstimate(estimated_bearing_deg=0),)), size=size
    )
    assert clear.shape == (size, size, 4)
    assert clear.dtype == np.uint8
    pixel = needle_pixel(clear, 0.0)
    assert int(pixel[1]) > int(pixel[0])  # green needle
    off_pixel = needle_pixel(clear, 180.0)
    assert int(off_pixel[1]) < 100  # background away from the needle

    multiple = render_compass_rgba(
        compass_view_model(
            (
                DoaEstimate(estimated_bearing_deg=0),
                DoaEstimate(estimated_bearing_deg=90),
            )
        ),
        size=size,
    )
    assert not np.array_equal(needle_pixel(multiple, 0), needle_pixel(multiple, 90))
    assert render_compass_rgba(compass_view_model(()), size=size).shape == (
        size,
        size,
        4,
    )


def test_compass_distinguishes_unavailable_confidence_from_zero():
    missing = compass_view_model((DoaEstimate(estimated_bearing_deg=20),))
    zero = compass_view_model(
        (DoaEstimate(estimated_bearing_deg=20, bearing_confidence=0),)
    )
    assert "confidence N/A" in missing.summary
    assert "confidence 0.00" in zero.summary
    assert missing.needles == zero.needles
