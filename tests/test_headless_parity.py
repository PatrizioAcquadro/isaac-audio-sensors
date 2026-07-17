from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import isaac_audio_sensors.cli as cli_module
from isaac_audio_sensors.core.dataset import SessionRecorder
from isaac_audio_sensors.core.dataset_manifest import (
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
    Pose3D,
)
from isaac_audio_sensors.isaac.extension_ui.controller import ExtensionController
from isaac_audio_sensors.isaac.extension_ui.state import (
    AuthoredMetadataSummary,
    CurrentStageContext,
    DiscoveredPrimSummary,
)
from isaac_audio_sensors.isaac.extension_ui.workflow import (
    GUIDED_STAGE_ORDER,
    SAFE_PRESETS,
)
from isaac_audio_sensors.isaac.headless_workflow import HeadlessGuidedSession
from scripts.compare_gui_headless_sessions import (
    compare_sessions,
)
from scripts.compare_gui_headless_sessions import (
    main as compare_main,
)


class _FakeStage:
    def GetPrimAtPath(self, _path: str) -> object:
        return object()


class _FakeSensor:
    def __init__(self, frames: list[AudioSensorFrame]) -> None:
        self.frames = list(frames)
        self.latest_frame: AudioSensorFrame | None = None
        self.latest_debug_primitives: tuple[object, ...] = ()
        self.backend = "geometry_only"
        self.array_id = "minimal_array"
        self.array_prim_path = "/World/AudioArray"
        self.source_prim_path: str | None = None
        self.stage = _FakeStage()
        self._latest_sensor = None
        self.debug_drawer = None
        self.running = False

    def start(self, *, subscribe_to_update_stream: bool = False) -> _FakeSensor:
        del subscribe_to_update_stream
        self.running = True
        return self

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.running = False

    def update(self, *, force: bool = False) -> AudioSensorFrame:
        del force
        if self.frames:
            self.latest_frame = self.frames.pop(0)
        assert self.latest_frame is not None
        return self.latest_frame


def _frame(index: int, *, diagnostic_path: str | None = None) -> AudioSensorFrame:
    timestamp = index * 10
    detection = AudioDetection(
        detection_id=f"detection_{index:03d}",
        source_id="source",
        class_label="Speech",
        detection_mode="scheduled_known_source",
        timestamp_ms=timestamp,
        ground_truth_bearing_deg=0.0,
        source_distance_m=2.0,
        doa=DoaEstimate(
            estimated_bearing_deg=0.0,
            candidate_bearing_deg=(0.0,),
            bearing_confidence=1.0,
        ),
        source_pose=Pose3D(position_m=(2.0, 0.0, 0.0)),
        per_mic_rms={"center": 0.5},
    )
    diagnostics: dict[str, Any] = {"window_sample_count": 8}
    if diagnostic_path is not None:
        diagnostics["capture_path"] = diagnostic_path
    return AudioSensorFrame(
        frame_id=f"guided_frame_{index:03d}",
        timestamp_ms=timestamp,
        backend_id="geometry_only",
        array_id="minimal_array",
        start_time_s=index / 100.0,
        end_time_s=index / 100.0 + 0.001,
        sample_rate_hz=8_000,
        frame_index=index,
        detections=(detection,),
        aggregate_per_mic_rms={"center": 0.5},
        diagnostics=diagnostics,
    )


def _controller_with_sensor(frame_count: int) -> ExtensionController:
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(_FakeStage(), ())
    )
    sensor = _FakeSensor([_frame(index) for index in range(frame_count)])
    controller._build_sensor = lambda _stage: sensor  # type: ignore[method-assign]
    return controller


def _write_guided_config(path: Path) -> Path:
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(_FakeStage(), ())
    )
    assert controller.guided_apply_preset("minimal_single_source") is not None
    controller.state.sample_rate_hz = 8_000
    controller.state.update_period_s = 0.001
    controller.state.guided_dataset_id = "headless_parity"
    controller.state.guided_shard_max_frames = 2
    controller.state.guided_record_aligned = False
    controller.state.guided_scene_id = "scene_a"
    controller.state.guided_environment_id = "environment_a"
    controller.state.guided_split_group = "scene_a"
    controller.state.guided_session_seed = 17
    controller.state.guided_split_enabled = False
    assert controller.export_config_summary(path) == path
    return path


@pytest.mark.parametrize(
    "preset_id",
    [None, *(preset.preset_id for preset in SAFE_PRESETS)],
    ids=["defaults", *(preset.preset_id for preset in SAFE_PRESETS)],
)
def test_config_summary_roundtrip_is_byte_identical(
    tmp_path: Path,
    preset_id: str | None,
) -> None:
    stage = _FakeStage()
    original = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    if preset_id is not None:
        assert original.guided_apply_preset(preset_id) is not None
    first = tmp_path / f"{preset_id or 'defaults'}-first.json"
    second = tmp_path / f"{preset_id or 'defaults'}-second.json"

    assert original.export_config_summary(first) == first
    restored = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert restored.import_config_summary(first) == first
    assert restored.export_config_summary(second) == second

    assert second.read_bytes() == first.read_bytes()


def test_fully_populated_config_summary_roundtrip_is_byte_identical(
    tmp_path: Path,
) -> None:
    stage = _FakeStage()
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    state = controller.state
    state.guided_mode_enabled = False
    state.guided_preset_id = "minimal_single_source"
    state.guided_dataset_id = "perturbed_dataset"
    state.guided_shard_max_frames = 13
    state.guided_record_aligned = True
    state.guided_scene_id = "perturbed_scene"
    state.guided_environment_id = "perturbed_environment"
    state.guided_split_group = "perturbed_group"
    state.guided_session_seed = 41
    state.guided_split_enabled = False
    state.guided_split_train_ratio = 0.6
    state.guided_split_validation_ratio = 0.3
    state.guided_split_test_ratio = 0.1
    state.backend = "geometry_only"
    state.array_prim_path = "/World/PerturbedArray"
    state.array_id = "perturbed_array"
    state.layout_name = "mono"
    state.sample_rate_hz = 16_000
    state.array_position_x_m = 1.0
    state.array_position_y_m = 2.0
    state.array_position_z_m = 3.0
    state.array_roll_deg = 10.0
    state.array_pitch_deg = 20.0
    state.array_yaw_deg = 30.0
    state.array_attached_to_object = True
    state.attached_array_object_prim_path = "/World/PerturbedObject"
    state.array_local_offset_x_m = 0.1
    state.array_local_offset_y_m = 0.2
    state.array_local_offset_z_m = 0.3
    state.array_local_roll_deg = 4.0
    state.array_local_pitch_deg = 5.0
    state.array_local_yaw_deg = 6.0
    state.selected_rig_profile_id = "unitree_head_stereo"
    state.applied_array_rig_profile = {"profile_id": "unitree_head_stereo"}
    state.source_prim_path = "/World/PerturbedObject/Source"
    state.source_id = "perturbed_source"
    state.source_class_label = "Alarm"
    state.audio_asset_path = "generated://pulse"
    state.source_position_x_m = 4.0
    state.source_position_y_m = 5.0
    state.source_position_z_m = 6.0
    state.source_start_time_s = 0.25
    state.source_duration_s = 2.5
    state.source_gain_db = -3.0
    state.source_directivity = "cardioid"
    state.selected_profile_id = "door_knock"
    state.applied_source_profile = {"profile_id": "door_knock"}
    state.object_prim_path = "/World/PerturbedObject"
    state.object_label = "Perturbed Object"
    state.source_attached_to_object = True
    state.attached_object_prim_path = "/World/PerturbedObject"
    state.source_local_offset_x_m = 0.4
    state.source_local_offset_y_m = 0.5
    state.source_local_offset_z_m = 0.6
    state.robot_base_prim_path = "/World/Robot"
    state.discovery_roots_text = "/World, /Environment"
    state.selected_prim_paths = ("/World/PerturbedObject",)
    state.discovered_arrays = (
        DiscoveredPrimSummary("array", "/World/PerturbedArray", ("explicit",)),
    )
    state.discovered_sources = (
        DiscoveredPrimSummary("source", state.source_prim_path, ("metadata",)),
    )
    state.discovered_objects = (
        DiscoveredPrimSummary("object", state.object_prim_path, ("selected",)),
    )
    state.update_period_s = 0.025
    state.max_events = 3
    state.ambiguity_policy = "front"
    state.debug_overlay_enabled = False
    state.occlusion_enabled = True
    state.trace_enabled = True
    state.jsonl_trace_path = str(tmp_path / "trace.jsonl")
    state.waveform_enabled = True
    state.waveform_dir = str(tmp_path / "waveforms")
    state.waveform_mode = "session"
    state.follow_viewport_selection = True
    state.live_sync_array_pose = True
    state.live_sync_source_pose = True
    state.usd_debug_enabled = True
    state.usd_debug_root = "/World/PerturbedDebug"
    state.room_anchor_prim_path = "/World/Room"
    state.room_out_of_bounds = "clip"
    state.latest_room_summary = {"room_id": "room", "dimensions_m": [3, 4, 5]}
    state.replicator_enabled = True
    state.replicator_output_dir = str(tmp_path / "replicator")
    state.replicator_writer_name = "PerturbedWriter"
    state.replicator_annotator_name = "PerturbedAnnotator"
    state.replicator_recording = True
    state.replicator_write_count = 7
    state.replicator_flush_count = 2
    state.replicator_latest_write_path = str(tmp_path / "write.json")
    state.replicator_latest_jsonl_path = str(tmp_path / "records.jsonl")
    state.replicator_latest_error = "located error"
    state.replicator_output_artifacts = (str(tmp_path / "artifact"),)
    state.replicator_status_message = "perturbed status"
    state.authored_metadata = (
        AuthoredMetadataSummary(
            "source",
            state.source_prim_path,
            state.source_id,
            {"ias:gain_db": -3.0},
        ),
    )
    state.latest_frame_id = "latest_frame"
    state.latest_backend = "geometry_only"
    state.latest_detection_count = 2
    state.latest_source_prim_path = state.source_prim_path
    state.latest_source_position_m = (4.0, 5.0, 6.0)
    state.latest_bearing_deg = 45.0
    state.latest_sector = "right"
    state.latest_array_prim_path = state.array_prim_path
    state.latest_array_position_m = (1.0, 2.0, 3.0)
    state.latest_array_orientation_xyzw = (0.0, 0.0, 0.0, 1.0)
    state.latest_mic_world_positions = {"center": (1.0, 2.0, 3.0)}
    state.latest_overlay_primitive_count = 1
    state.latest_overlay_labels = ("source:perturbed",)
    state.latest_overlay_status = "drawn"
    state.latest_overlay_error = "overlay warning"
    controller._imported_overlay_primitives = (
        {
            "kind": "source",
            "label": "source:perturbed",
            "points_world": [[4.0, 5.0, 6.0]],
            "color_rgba": [1.0, 0.5, 0.0, 1.0],
            "radius_m": 0.1,
            "metadata": {"source_id": state.source_id},
        },
    )
    first = tmp_path / "full-first.json"
    second = tmp_path / "full-second.json"

    assert controller.export_config_summary(first) == first
    restored = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert restored.import_config_summary(first) == first
    assert restored.export_config_summary(second) == second

    assert second.read_bytes() == first.read_bytes()


def test_headless_session_drives_all_stages_and_exports_valid_session(
    tmp_path: Path,
) -> None:
    config = _write_guided_config(tmp_path / "config.json")
    controller = _controller_with_sensor(4)
    session = HeadlessGuidedSession(controller=controller)

    summary = session.run_from_config(
        config,
        session_dir=tmp_path / "session",
        export_dir=tmp_path / "export",
        frames=3,
    )

    assert summary["status"] == "passed"
    assert summary["stages_passed"] == [stage.value for stage in GUIDED_STAGE_ORDER]
    assert summary["recording_stats"]["frames"] == 3
    assert summary["recording_stats"]["validation_status"] in {
        "passed",
        "passed_with_warnings",
    }
    assert summary["validator_report"]["status"] in {
        "passed",
        "passed_with_warnings",
    }
    assert Path(summary["export_path"]).is_dir()


def test_guided_cli_success_and_outside_isaac_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_guided_config(tmp_path / "config.json")

    failed = cli_module.main(
        [
            "guided",
            "run-headless",
            str(config),
            "--session-dir",
            str(tmp_path / "no-stage-session"),
            "--export-dir",
            str(tmp_path / "no-stage-export"),
            "--frames",
            "1",
            "--json",
            "-",
        ]
    )
    failure_payload = json.loads(capsys.readouterr().out)
    assert failed == 1
    assert failure_payload["status"] == "failed"
    assert failure_payload["error"].startswith("setup:")
    assert "no USD stage" in failure_payload["error"]

    class _SuccessfulSession:
        def run_from_config(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "status": "passed",
                "recording_stats": {"frames": 2},
                "export_path": str(tmp_path / "export"),
            }

    monkeypatch.setattr(cli_module, "HeadlessGuidedSession", _SuccessfulSession)
    passed = cli_module.main(
        [
            "guided",
            "run-headless",
            str(config),
            "--session-dir",
            str(tmp_path / "session"),
            "--export-dir",
            str(tmp_path / "export"),
            "--seconds",
            "0.1",
            "--json",
            "-",
        ]
    )
    success_payload = json.loads(capsys.readouterr().out)
    assert passed == 0
    assert success_payload["status"] == "passed"


def _make_session(
    root: Path,
    *,
    dataset_id: str,
    creation_timestamp_ms: int,
    tool_name: str = "gui_tool",
    device_id: str = "device_a",
) -> None:
    configuration = {
        "backend_id": "geometry_only",
        "channel_order": ["center"],
        "dataset_id": dataset_id,
        "dtype": "float32",
        "hop_sample_count": 4,
        "runtime_profile": "waveform_fidelity",
        "sample_rate_hz": 8_000,
        "session_seed": 11,
        "shard_episode_aligned": False,
        "shard_max_frames": 2,
        "split_grouping_key": "scene_id",
        "window_sample_count": 4,
    }
    recorder = SessionRecorder(
        root,
        configuration,
        creation=CreationProvenance(
            tool_name=tool_name,
            tool_version="different-runtime-version",
            backend_id="geometry_only",
            estimator_id="geometry_only",
        ),
        device=DeviceProvenance(
            device_id=device_id,
            device_type="simulator",
            platform="test",
            compute_device="cpu",
        ),
        license="CC0-1.0",
        source="parity test",
        coordinate_frames=("world", "array"),
        time_base="simulation_time",
        creation_timestamp_ms=creation_timestamp_ms,
    )
    recorder.begin_episode("scene_a", "environment_a", "scene_a", seed=7)
    for index in range(3):
        audio = np.arange(4, dtype=np.float32).reshape(1, 4) + index
        assert recorder.append_frame(_frame(index), audio, index * 10).accepted
    recorder.end_episode()
    recorder.finalize()


def _first_frame_path(root: Path) -> Path:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return root / next(
        asset["path"]
        for asset in manifest["shards"][0]["assets"]
        if asset["kind"] == "frame_trace_jsonl"
    )


def _mutate_first_record(root: Path, mutate: Any) -> None:
    path = _first_frame_path(root)
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    mutate(record)
    lines[0] = json.dumps(record, separators=(",", ":"), sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_semantic_diff_equal_sessions_exit_zero_and_normalizes_provenance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    left = tmp_path / "gui"
    right = tmp_path / "headless"
    _make_session(
        left,
        dataset_id="gui_dataset",
        creation_timestamp_ms=100,
        tool_name="gui_tool",
        device_id="gui_device",
    )
    _make_session(
        right,
        dataset_id="headless_dataset",
        creation_timestamp_ms=200,
        tool_name="headless_tool",
        device_id="headless_device",
    )
    for root in (left, right):
        config_path = root / "config" / "session_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["session_root"] = str(root)
        config_path.write_text(json.dumps(config), encoding="utf-8")
    _mutate_first_record(
        left,
        lambda record: record["frame"]["diagnostics"].update(
            {"capture_path": "/tmp/gui/capture.wav"}
        ),
    )
    _mutate_first_record(
        right,
        lambda record: record["frame"]["diagnostics"].update(
            {"capture_path": "/var/headless/capture.wav"}
        ),
    )

    report = compare_sessions(left, right)

    assert report["equal"] is True
    assert report["differences"] == []
    assert compare_main([str(left), str(right), "--json", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []


@pytest.mark.parametrize(
    ("mutate", "expected_name"),
    (
        (
            lambda record: record["frame"].__setitem__("timestamp_ms", 999),
            "timestamp_mismatch",
        ),
        (
            lambda record: record.__setitem__(
                "audio_end_sample", record["audio_end_sample"] + 1
            ),
            "audio_range_mismatch",
        ),
        (
            lambda record: record["frame"]["detections"][0].__setitem__(
                "class_label", "Perturbed"
            ),
            "detection_mismatch",
        ),
    ),
)
def test_semantic_diff_names_timestamp_range_and_detection_changes(
    tmp_path: Path,
    mutate: Any,
    expected_name: str,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _make_session(left, dataset_id="same", creation_timestamp_ms=100)
    _make_session(right, dataset_id="same", creation_timestamp_ms=100)
    _mutate_first_record(right, mutate)

    report = compare_sessions(left, right)

    assert report["equal"] is False
    assert expected_name in {item["name"] for item in report["differences"]}
    assert (
        compare_main(
            [str(left), str(right), "--json", str(tmp_path / "diff.json")]
        )
        == 1
    )


def _run_fake_gui(
    controller: ExtensionController,
    config: Path,
    session: Path,
    export: Path,
    frames: int,
) -> None:
    assert controller.guided_apply_preset("minimal_single_source") is not None
    assert controller.import_config_summary(config) == config
    assert controller.guided_advance()
    assert controller.guided_validate().ok
    assert controller.guided_start_run() is not None
    assert controller.update_sensor() is not None
    assert controller.guided_advance()
    assert controller.guided_mark_inspected()
    assert controller.guided_advance()
    state = controller.state
    assert controller.guided_start_recording(
        session,
        state.guided_dataset_id,
        state.guided_shard_max_frames,
        state.guided_record_aligned,
        scene_id=state.guided_scene_id,
        environment_id=state.guided_environment_id,
        split_group=state.guided_split_group,
        session_seed=state.guided_session_seed,
    ) is not None
    for _ in range(frames):
        assert controller.update_sensor() is not None
    assert controller.guided_stop_recording() is not None
    assert controller.guided_export(export) == export
    controller.guided_stop_run()


def test_fake_gui_and_headless_sessions_are_semantically_equal(tmp_path: Path) -> None:
    config = _write_guided_config(tmp_path / "config.json")
    gui_controller = _controller_with_sensor(4)
    _run_fake_gui(
        gui_controller,
        config,
        tmp_path / "gui-session",
        tmp_path / "gui-export",
        3,
    )
    headless_controller = _controller_with_sensor(4)
    summary = HeadlessGuidedSession(controller=headless_controller).run_from_config(
        config,
        session_dir=tmp_path / "headless-session",
        export_dir=tmp_path / "headless-export",
        frames=3,
    )

    report = compare_sessions(tmp_path / "gui-export", summary["export_path"])

    assert report["equal"] is True
    assert report["differences"] == []
