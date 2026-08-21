"""Tests for fundamental audio sensor data contracts."""

from __future__ import annotations

import pytest

from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
)


def test_specs_accept_optional_world_velocity():
    source = _source(velocity_world_mps=(-10.0, 0.0, 0.0))
    static_source = _source(source_id="static", prim_path="/World/Static")
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
    )

    assert source.velocity_world_mps == (-10.0, 0.0, 0.0)
    assert static_source.velocity_world_mps is None
    assert array.velocity_world_mps is None

    with pytest.raises(ValueError, match="velocity_world_mps"):
        _source(source_id="short", velocity_world_mps=(1.0, 0.0))
    with pytest.raises(ValueError, match="velocity_world_mps"):
        _source(source_id="nan", velocity_world_mps=(float("nan"), 0.0, 0.0))


def test_audio_time_window_requires_positive_duration():
    window = AudioTimeWindow(
        start_time_s=1.0,
        end_time_s=1.5,
        timestamp_ms=1500,
        sample_rate_hz=48_000,
    )
    assert window.start_time_s == 1.0

    with pytest.raises(ValueError, match="end must be after start"):
        AudioTimeWindow(
            start_time_s=1.0,
            end_time_s=1.0,
            timestamp_ms=1000,
            sample_rate_hz=48_000,
        )


def test_doa_estimate_validates_optional_elevation_fields():
    doa = DoaEstimate(
        estimated_bearing_deg=90.0,
        bearing_confidence=0.5,
        estimated_elevation_deg=30.0,
        candidate_elevation_deg=(30.0,),
    )
    default = DoaEstimate(estimated_bearing_deg=None, bearing_confidence=0.0)

    assert doa.estimated_elevation_deg == pytest.approx(30.0)
    assert doa.candidate_elevation_deg == pytest.approx((30.0,))
    assert default.estimated_elevation_deg is None
    assert default.candidate_elevation_deg == ()

    with pytest.raises(ValueError, match="estimated_elevation_deg"):
        DoaEstimate(
            estimated_bearing_deg=0.0,
            bearing_confidence=0.0,
            estimated_elevation_deg=120.0,
        )
    with pytest.raises(ValueError, match="candidate_elevation_deg"):
        DoaEstimate(
            estimated_bearing_deg=0.0,
            bearing_confidence=0.0,
            candidate_elevation_deg=(-95.0,),
        )


def test_audio_detection_validates_ground_truth_elevation():
    detection = _detection(ground_truth_elevation_deg=-45.0)
    assert detection.ground_truth_elevation_deg == pytest.approx(-45.0)

    with pytest.raises(ValueError, match="ground_truth_elevation_deg"):
        _detection(ground_truth_elevation_deg=91.0)


def test_audio_sensor_frame_allows_empty_single_and_multiple_detections():
    first = _detection(detection_id="det_1")
    second = _detection(
        detection_id="det_2",
        source_id=None,
        class_label=None,
        detection_mode="manual_annotation",
    )

    empty = AudioSensorFrame(
        frame_id="empty",
        timestamp_ms=1,
        backend_id="geometry_only",
        array_id="array",
    )
    single = AudioSensorFrame(
        frame_id="single",
        timestamp_ms=1,
        backend_id="geometry_only",
        array_id="array",
        detections=(first,),
    )
    multi = AudioSensorFrame(
        frame_id="multi",
        timestamp_ms=1,
        backend_id="geometry_only",
        array_id="array",
        detections=(first, second),
    )

    assert empty.detections == ()
    assert empty.schema_version == "ias.audio_sensor_frame.v1"
    assert empty.units["position"] == "m"
    assert single.detections == (first,)
    assert len(multi.detections) == 2


def test_detection_mode_rejects_unknown_value():
    with pytest.raises(ValueError, match="detection_mode"):
        _detection(detection_mode="learned_detector")


def _source(
    *,
    source_id: str = "mover",
    prim_path: str = "/World/Mover",
    velocity_world_mps=None,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=prim_path,
        class_label="Vehicle",
        audio_asset_path=None,
        position_world=(5.0, 0.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        velocity_world_mps=velocity_world_mps,
    )


def _detection(**overrides) -> AudioDetection:
    values = {
        "detection_id": "det",
        "source_id": "src",
        "class_label": "Speech",
        "detection_mode": "scheduled_known_source",
        "timestamp_ms": 0,
        "ground_truth_bearing_deg": 0.0,
        "source_distance_m": 1.0,
        "doa": DoaEstimate(estimated_bearing_deg=None, bearing_confidence=0.0),
    }
    values.update(overrides)
    return AudioDetection(**values)
