"""Tests for the pure isaac_audio_sensors core package."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import isaac_audio_sensors
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.config import (
    build_scene_snapshot,
    load_audio_config,
    validate_audio_config,
)
from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.math_utils import (
    basis_from_quaternion,
    euler_deg_from_quaternion,
    quaternion_from_euler_deg,
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
    Pose3D,
)


def test_core_package_imports_and_exposes_version():
    assert isaac_audio_sensors.__version__ == "1.0.0"


def test_version_surfaces_match_final_release():
    root = Path(__file__).resolve().parents[1]
    expected = "1.0.0"
    kit_manifest_expected = "1.0.0"
    assert f'version = "{expected}"' in (root / "pyproject.toml").read_text()
    extension_manifest = (
        root / "exts/isaac_audio_sensors.omni/config/extension.toml"
    ).read_text()
    assert f'version = "{kit_manifest_expected}"' in extension_manifest
    assert "Python package release" in extension_manifest
    assert expected in extension_manifest
    assert f'version: "{expected}"' in (root / "CITATION.cff").read_text()
    assert f"package version: `{expected}`" in (
        root / "docs/versioning.md"
    ).read_text()
    assert f"Kit extension manifest version: `{kit_manifest_expected}`" in (
        root / "docs/versioning.md"
    ).read_text()
    assert f"## {expected} - 2026-05-24" in (root / "CHANGELOG.md").read_text()


def test_package_module_version_entrypoint_reports_final_release():
    result = subprocess.run(
        [sys.executable, "-m", "isaac_audio_sensors", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "1.0.0"


def test_config_validation_accepts_demo_config():
    config = load_audio_config("configs/isaac_audio_sensors_demo.toml")
    scene = build_scene_snapshot(config, timestamp_ms=1234)

    assert config.default_backend == "tdoa_synthetic"
    assert sorted(config.arrays) == ["rig_front", "rig_stereo"]
    assert scene.stage_id == "demo_audio_lab_single_source"


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


def test_euler_quaternion_helpers_round_trip_and_match_yaw_helper():
    assert quaternion_from_euler_deg(yaw_deg=90.0) == pytest.approx(
        quaternion_from_yaw_deg(90.0),
        abs=1e-12,
    )
    assert euler_deg_from_quaternion(quaternion_from_yaw_deg(90.0)) == pytest.approx(
        (0.0, 0.0, 90.0),
        abs=1e-9,
    )

    quat = quaternion_from_euler_deg(roll_deg=10.0, pitch_deg=-20.0, yaw_deg=135.0)
    assert euler_deg_from_quaternion(quat) == pytest.approx(
        (10.0, -20.0, 135.0),
        abs=1e-9,
    )

    forward, _, _ = basis_from_quaternion(quaternion_from_euler_deg(yaw_deg=180.0))
    assert forward == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


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
    assert empty.schema_version == "ias.audio_sensor_frame.v1"
    assert empty.frame_name == "empty"
    assert empty.units["position"] == "m"
    assert empty.provenance == "synthetic/core"
    assert single.detections == (first,)
    assert len(multi.detections) == 2


def test_frame_contract_serializes_and_round_trips():
    frame = AudioSensorFrame(
        frame_id="frame_1",
        frame_name="demo/frame_1",
        timestamp_ms=50,
        start_time_s=0.05,
        end_time_s=0.10,
        sample_rate_hz=48_000,
        frame_index=2,
        backend_id="geometry_only",
        array_id="rig_front",
        array_pose=Pose3D(position_m=(1.0, 2.0, 0.0)),
        max_events=1,
        detections=(
            AudioDetection(
                detection_id="det_1",
                source_id="speaker",
                class_label="Speech",
                detection_mode="scheduled_known_source",
                timestamp_ms=50,
                ground_truth_bearing_deg=45.0,
                source_distance_m=3.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=45.0,
                    candidate_bearing_deg=(45.0,),
                    bearing_confidence=0.9,
                ),
                source_pose=Pose3D(position_m=(3.0, 4.0, 0.0)),
            ),
        ),
    )

    payload = frame_to_trace_dict(frame)
    json.dumps(payload)
    rebuilt = frame_from_trace_dict(payload)

    assert payload["schema_version"] == "ias.audio_sensor_frame.v1"
    assert payload["array_pose"]["position_m"] == [1.0, 2.0, 0.0]
    assert payload["detections"][0]["source_pose"]["position_m"] == [3.0, 4.0, 0.0]
    assert rebuilt == frame


def test_audio_sensor_frame_v1_schema_required_keys_match_trace_contract():
    frame = AudioSensorFrame(
        frame_id="contract",
        timestamp_ms=10,
        start_time_s=0.0,
        end_time_s=0.1,
        sample_rate_hz=48_000,
        frame_index=0,
        backend_id="geometry_only",
        array_id="rig_front",
        array_pose=Pose3D(position_m=(0.0, 0.0, 0.0)),
        max_events=1,
        detections=(
            AudioDetection(
                detection_id="det_1",
                source_id="speaker",
                class_label="Speech",
                detection_mode="scheduled_known_source",
                timestamp_ms=10,
                ground_truth_bearing_deg=0.0,
                source_distance_m=1.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=0.0,
                    candidate_bearing_deg=(0.0,),
                    bearing_confidence=1.0,
                ),
                source_pose=Pose3D(position_m=(1.0, 0.0, 0.0)),
            ),
        ),
    )
    payload = frame_to_trace_dict(frame)
    schema = isaac_audio_sensors.audio_sensor_frame_json_schema()

    expected_top_level = {
        "schema_version",
        "frame_id",
        "frame_name",
        "timestamp_ms",
        "start_time_s",
        "end_time_s",
        "sample_rate_hz",
        "frame_index",
        "backend_id",
        "array_id",
        "array_pose",
        "coordinate_convention",
        "units",
        "provenance",
        "max_events",
        "detections",
        "aggregate_per_mic_rms",
        "waveform_paths",
        "diagnostics",
    }
    expected_detection = {
        "detection_id",
        "source_id",
        "class_label",
        "detection_mode",
        "timestamp_ms",
        "ground_truth_bearing_deg",
        "source_distance_m",
        "doa",
        "source_pose",
        "per_mic_delay_s",
        "per_mic_rms",
        "audio_asset_path",
        "diagnostics",
    }
    expected_doa = {
        "estimated_bearing_deg",
        "candidate_bearing_deg",
        "bearing_sector",
        "bearing_confidence",
        "ambiguity_class",
        "ambiguity_reason",
    }
    expected_pose = {
        "position_m",
        "orientation_xyzw",
        "frame",
        "coordinate_convention",
    }

    assert set(schema["required"]) == expected_top_level
    assert set(payload) == expected_top_level
    detection_schema = schema["properties"]["detections"]["items"]
    assert set(detection_schema["required"]) == expected_detection
    assert set(payload["detections"][0]) == expected_detection
    assert set(detection_schema["properties"]["doa"]["required"]) == expected_doa
    assert set(payload["detections"][0]["doa"]) == expected_doa
    assert set(payload["array_pose"]) == expected_pose
    assert set(payload["detections"][0]["source_pose"]) == expected_pose


def test_schema_file_exists_and_is_json():
    schema_path = Path("docs/schemas/audio_sensor_frame.v1.schema.json")
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "ias.audio_sensor_frame.v1"
    )
    assert "array_pose" in schema["required"]
    assert "source_pose" in schema["properties"]["detections"]["items"]["required"]


def test_trace_examples_use_public_schema_shape():
    schema = json.loads(
        Path("docs/schemas/audio_sensor_frame.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    required = set(schema["required"])
    trace_paths = sorted(Path("examples/traces").glob("*.json"))

    assert trace_paths
    for trace_path in trace_paths:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        assert required <= set(payload)
        assert payload["schema_version"] == "ias.audio_sensor_frame.v1"
        if payload["max_events"] is not None:
            assert len(payload["detections"]) <= payload["max_events"]


def test_public_files_use_neutral_demo_names():
    assert Path("configs/isaac_audio_sensors_demo.toml").exists()
    assert Path("examples/isaac_sim/live_audio_lab.py").exists()

    checked_roots = [
        Path("README.md"),
        Path("CHANGELOG.md"),
        Path("Makefile"),
        Path("configs"),
        Path("docs"),
        Path("examples"),
    ]
    public_files: list[Path] = []
    for root in checked_roots:
        if root.is_file():
            public_files.append(root)
        else:
            public_files.extend(
                path
                for path in root.rglob("*")
                if path.suffix in {".md", ".py", ".toml"}
            )

    forbidden = (
        "Phase " + "5.5",
        "phase" + "55",
        "phase_5" + "_5",
    )
    project_token = "Squad" + "Bot"
    project_token_allowed_paths = {
        "CHANGELOG.md",
        "README.md",
        "docs/README.md",
        "docs/api_freeze_0_1.md",
        "docs/isaac_lab.md",
        "docs/limitations.md",
        "docs/open_source_release_checklist.md",
        "docs/v1_scope.md",
        "docs/validation.md",
        "docs/versioning.md",
    }
    forbidden_project_context = (
        "release gate",
        "validation before releasing",
        "validation is not required",
        "does not promise",
    )
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        assert not any(term in text for term in forbidden), path
        if project_token in text:
            assert path.as_posix() in project_token_allowed_paths, path
            assert any(phrase in text for phrase in forbidden_project_context), path


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


def test_max_events_limits_detections_in_deterministic_order():
    config = load_audio_config("configs/isaac_audio_sensors_demo.toml")
    scene = build_scene_snapshot(config, timestamp_ms=500)
    sensor = scene.array_by_id("rig_front")
    frame = GeometryBackend().simulate(
        scene,
        sensor,
        AudioTimeWindow(
            start_time_s=0.5,
            end_time_s=0.75,
            timestamp_ms=500,
            sample_rate_hz=sensor.sample_rate_hz,
            frame_index=0,
            max_events=1,
        ),
    )

    assert frame.max_events == 1
    assert len(frame.detections) == 1
    assert frame.detections[0].source_id == "speaker_front_right"
