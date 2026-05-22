"""Tests for the pure isaac_audio_sensors core package."""

from __future__ import annotations

import pytest

import isaac_audio_sensors
from isaac_audio_sensors.core.config import (
    build_scene_snapshot,
    load_audio_config,
    validate_audio_config,
)
from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.core.math_utils import (
    basis_from_quaternion,
    quaternion_from_yaw_deg,
)
from isaac_audio_sensors.core.microphone_array import (
    arbitrary_microphone_array,
    create_microphone_array,
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    AudioTimeWindow,
    DoaEstimate,
)


def test_core_package_imports_and_exposes_version():
    assert isaac_audio_sensors.__version__ == "0.1.0"


def test_config_validation_accepts_phase55_config():
    config = load_audio_config("configs/isaac_audio_sensors_phase55.toml")
    scene = build_scene_snapshot(config, timestamp_ms=1234)

    assert config.default_backend == "tdoa_synthetic"
    assert sorted(config.arrays) == ["rig_front", "rig_stereo"]
    assert scene.stage_id == "phase55_audio_lab_single_source"


def test_config_validation_rejects_duplicate_microphone_ids():
    raw = {
        "scene": {"scene_id": "bad", "stage_units": "meters", "up_axis": "z"},
        "audio": {"default_backend": "geometry_only"},
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig/AudioArray",
                "microphones": [
                    {"mic_id": "dup", "relative_position_m": [0.0, 0.0, 0.0]},
                    {"mic_id": "dup", "relative_position_m": [0.1, 0.0, 0.0]},
                ],
            }
        },
    }

    with pytest.raises(ValueError, match="Duplicate microphone id"):
        validate_audio_config(raw)


def test_config_validation_rejects_tdoa_with_one_microphone():
    raw = {
        "scene": {"scene_id": "bad", "stage_units": "meters", "up_axis": "z"},
        "audio": {"default_backend": "tdoa_synthetic"},
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig/AudioArray",
                "microphones": [
                    {"mic_id": "center", "relative_position_m": [0.0, 0.0, 0.0]},
                ],
            }
        },
    }

    with pytest.raises(ValueError, match="requires at least two microphones"):
        validate_audio_config(raw)


def test_config_validation_requires_explicit_two_mic_ambiguity_policy():
    raw = {
        "scene": {"scene_id": "bad", "stage_units": "meters", "up_axis": "z"},
        "audio": {"default_backend": "tdoa_synthetic"},
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig/AudioArray",
                "microphones": [
                    {"mic_id": "left", "relative_position_m": [0.0, -0.08, 0.0]},
                    {"mic_id": "right", "relative_position_m": [0.0, 0.08, 0.0]},
                ],
            }
        },
    }

    with pytest.raises(ValueError, match="ambiguity policy"):
        validate_audio_config(raw)


def test_coordinate_quaternion_and_time_conventions():
    forward, right, up = basis_from_quaternion((0.0, 0.0, 0.0, 1.0))
    assert forward == pytest.approx((1.0, 0.0, 0.0))
    assert right == pytest.approx((0.0, 1.0, 0.0))
    assert up == pytest.approx((0.0, 0.0, 1.0))

    yaw_forward, yaw_right, _ = basis_from_quaternion(quaternion_from_yaw_deg(90.0))
    assert yaw_forward == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
    assert yaw_right == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)

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


def test_microphone_layouts_cover_one_two_four_and_arbitrary_n():
    assert len(microphone_layout("mono")) == 1
    assert len(microphone_layout("stereo_y")) == 2
    assert len(microphone_layout("quad_front")) == 4

    array = arbitrary_microphone_array(
        array_id="arb",
        prim_path="/World/Arb",
        relative_positions_m=(
            ("a", (0.0, 0.0, 0.0)),
            ("b", (0.1, 0.0, 0.0)),
            ("c", (0.0, 0.1, 0.0)),
            ("d", (-0.1, 0.0, 0.0)),
            ("e", (0.0, -0.1, 0.0)),
        ),
    )
    assert len(array.microphones) == 5
    assert microphone_world_positions(array)["b"] == pytest.approx((0.1, 0.0, 0.0))

    with pytest.raises(ValueError, match="Unknown microphone layout"):
        microphone_layout("missing")


def test_microphone_array_world_positions_respect_yaw():
    array = create_microphone_array(
        array_id="rotated",
        prim_path="/World/Rotated",
        layout_name="stereo_y",
        orientation_world_quat=quaternion_from_yaw_deg(90.0),
    )

    assert array.coordinate_convention == COORDINATE_CONVENTION
    positions = microphone_world_positions(array)
    assert positions["left"] == pytest.approx((0.08, 0.0, 0.0), abs=1e-9)
    assert positions["right"] == pytest.approx((-0.08, 0.0, 0.0), abs=1e-9)


def test_frame_shapes_allow_empty_single_and_multiple_detections():
    doa = DoaEstimate(
        estimated_bearing_deg=90.0,
        candidate_bearing_deg=(90.0,),
        bearing_confidence=0.8,
    )
    first = AudioDetection(
        detection_id="det_1",
        source_id="src_1",
        class_label="Speech",
        detection_mode="scheduled_known_source",
        timestamp_ms=1,
        ground_truth_bearing_deg=90.0,
        source_distance_m=2.0,
        doa=doa,
    )
    second = AudioDetection(
        detection_id="det_2",
        source_id=None,
        class_label=None,
        detection_mode="manual_annotation",
        timestamp_ms=1,
        ground_truth_bearing_deg=None,
        source_distance_m=None,
        doa=DoaEstimate(estimated_bearing_deg=None, bearing_confidence=0.0),
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
    assert single.detections == (first,)
    assert len(multi.detections) == 2


def test_detection_mode_validation_rejects_unknown_mode():
    with pytest.raises(ValueError, match="detection_mode"):
        AudioDetection(
            detection_id="det_bad",
            source_id=None,
            class_label=None,
            detection_mode="learned_detector",
            timestamp_ms=1,
            ground_truth_bearing_deg=None,
            source_distance_m=None,
            doa=DoaEstimate(estimated_bearing_deg=None, bearing_confidence=0.0),
        )
