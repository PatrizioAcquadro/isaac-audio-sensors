from __future__ import annotations

import json
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import isaac_audio_sensors.kit.recording_workflow as recording_workflow_module
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.kit.controller import ExtensionController
from isaac_audio_sensors.kit.state import (
    CurrentStageContext,
    ExtensionUiState,
)
from isaac_audio_sensors.kit.validation import ValidationReport
from isaac_audio_sensors.kit.workflow import (
    GUIDED_STAGE_ORDER,
    SAFE_PRESET_LIBRARY,
    SAFE_PRESETS,
    GuidedStage,
    GuidedWorkflow,
    StageStatus,
)
from isaac_audio_sensors.recording.serialization import read_dataset_manifest
from isaac_audio_sensors.recording.validate import Finding, validate_dataset


class _FakeStage:
    def GetPrimAtPath(self, _path: object) -> object:
        return object()


def _controller(stage_box: dict[str, object | None]) -> ExtensionController:
    return ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage_box["stage"], ())
    )


class _FakeSensor:
    def __init__(self, frames: list[AudioSensorFrame]) -> None:
        self.frames = list(frames)
        self.latest_frame: AudioSensorFrame | None = None
        self.latest_debug_primitives: tuple[object, ...] = ()
        self.backend = "tdoa_synthetic"
        self.array_id = "rig_front"
        self.array_prim_path = "/World/Rig/AudioArray"
        self.source_prim_path: str | None = None
        self.stage = _FakeStage()
        self.latest_array_spec = None
        self.latest_scene = None
        self.debug_drawer = None
        self.running = False
        self.reset_listeners: list[Any] = []

    def start(self, *, subscribe_to_update_stream: bool = False) -> _FakeSensor:
        del subscribe_to_update_stream
        self.running = True
        return self

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.running = False

    def reset(self) -> None:
        self.latest_frame = None
        for listener in tuple(self.reset_listeners):
            listener()

    def add_reset_listener(self, listener: Any) -> None:
        self.reset_listeners.append(listener)

    def update(self, *, force: bool = False) -> AudioSensorFrame:
        del force
        if not self.frames:
            assert self.latest_frame is not None
            return self.latest_frame
        self.latest_frame = self.frames.pop(0)
        return self.latest_frame


def _frame(
    index: int,
    *,
    waveform_path: Path | None = None,
    sample_rate_hz: int = 8_000,
) -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id=f"guided_frame_{index:03d}",
        timestamp_ms=index * 10,
        backend_id="tdoa_synthetic",
        array_id="rig_front",
        start_time_s=index / 100.0,
        end_time_s=index / 100.0 + 0.001,
        sample_rate_hz=sample_rate_hz,
        frame_index=index,
        aggregate_per_mic_rms={
            "front": 0.1,
            "right": 0.2,
            "rear": 0.3,
            "left": 0.4,
        },
        waveform_paths=(() if waveform_path is None else (str(waveform_path),)),
        diagnostics={"window_sample_count": 8},
    )


def _waveform(path: Path, index: int) -> Path:
    samples = np.arange(32, dtype=np.float32).reshape(4, 8)
    samples = samples / np.float32(64.0) + np.float32(index / 128.0)
    pcm = np.clip(np.rint(samples.T * 32767.0), -32768, 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(4)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(pcm.tobytes())
    return path


def _run_ready_controller(
    monkeypatch: pytest.MonkeyPatch,
    frames: list[AudioSensorFrame],
) -> tuple[ExtensionController, _FakeSensor]:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    assert controller.guided_apply_preset("xvf3800_quad_demo") is not None
    controller.state.sample_rate_hz = 8_000
    controller.state.update_period_s = 0.001
    assert controller.guided_advance()
    assert controller.guided_validate().ok
    sensor = _FakeSensor(frames)
    monkeypatch.setattr(
        controller._sensor_session, "_build_sensor", lambda _stage: sensor
    )
    assert controller.guided_start_run() is sensor
    return controller, sensor


def test_stage_machine_enforces_order_and_records_blocked_transitions() -> None:
    state = ExtensionUiState()
    changes: list[tuple[GuidedStage, StageStatus]] = []
    workflow = GuidedWorkflow(
        state,
        on_change=lambda: changes.append(
            (workflow.current_stage, workflow.current_status)
        ),
    )

    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.current_status is StageStatus.IN_PROGRESS
    assert workflow.goto(GuidedStage.VALIDATE) is False
    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.status(GuidedStage.VALIDATE) is StageStatus.BLOCKED
    assert workflow.findings_for_stage(GuidedStage.VALIDATE)[0].field == (
        "guided_stage"
    )

    applied: list[str] = []
    workflow.apply_preset(
        SAFE_PRESETS[0].preset_id,
        lambda preset: applied.append(preset.preset_id),
        stage_present=True,
    )
    assert applied == [SAFE_PRESETS[0].preset_id]
    assert workflow.status(GuidedStage.SETUP) is StageStatus.COMPLETE
    assert workflow.advance() is True
    assert state.guided_stage == "validate"
    assert workflow.back() is True
    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.goto(GuidedStage.EXPORT) is False
    assert workflow.status(GuidedStage.EXPORT) is StageStatus.BLOCKED
    assert len(changes) == 5


def test_stage_machine_can_progress_in_order_after_each_stage_completes() -> None:
    workflow = GuidedWorkflow(ExtensionUiState())
    workflow.apply_preset(
        SAFE_PRESETS[0].preset_id,
        lambda _preset: None,
        stage_present=True,
    )
    assert workflow.advance()
    workflow.record_validation(ValidationReport())

    for expected in GUIDED_STAGE_ORDER[2:]:
        assert workflow.advance()
        assert workflow.current_stage is expected
        assert workflow.mark_complete(expected)


@pytest.mark.parametrize("preset", SAFE_PRESETS, ids=lambda preset: preset.preset_id)
def test_each_safe_preset_drives_controller_to_validator_clean_state(
    preset: Any,
) -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)

    assert controller.guided_apply_preset(preset.preset_id) is preset
    assert controller.guided_workflow.status(GuidedStage.SETUP) is StageStatus.COMPLETE
    assert controller.guided_advance()
    assert controller.guided_validate().ok


def test_xvf3800_preset_matches_demo_config_claims() -> None:
    preset = SAFE_PRESET_LIBRARY["xvf3800_quad_demo"]

    assert preset.values["backend"] == "tdoa_synthetic"
    assert preset.values["sample_rate_hz"] == 48000
    assert preset.values["layout_name"] == "quad_front"
    assert preset.values["array_prim_path"] == "/World/Rig/AudioArray"
    assert preset.values["source_id"] == "speaker_front_right"
    assert preset.values["source_prim_path"] == ("/World/Sources/SpeakerFrontRight")
    assert preset.values["source_position_world"] == (4.0, 2.0, 0.0)


@pytest.mark.parametrize(
    ("field", "bad_value", "check_id", "action_label"),
    (
        ("backend", "not_a_backend", "backend_supported", "Use safe backend"),
        (
            "source_prim_path",
            "World/Source",
            "source_prim_path_absolute",
            "Fix path",
        ),
    ),
)
def test_invalid_field_maps_to_recovery_and_unblocks(
    field: str,
    bad_value: object,
    check_id: str,
    action_label: str,
) -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    controller.guided_apply_preset("xvf3800_quad_demo")
    controller.guided_advance()
    setattr(controller.state, field, bad_value)

    report = controller.guided_validate()

    finding = next(item for item in report.findings if item.check_id == check_id)
    issues = controller.guided_workflow.issues_for_field(field)
    assert [issue.finding for issue in issues] == [
        item for item in report.findings if item.field == field
    ]
    action = controller.guided_workflow.recovery_action(finding)
    assert action.label == action_label
    action()
    assert controller.guided_validate().ok


def test_absent_stage_has_open_stage_recovery() -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    controller.guided_apply_preset("minimal_single_source")
    controller.guided_advance()
    stage_box["stage"] = None

    report = controller.guided_validate()
    finding = next(item for item in report.findings if item.check_id == "stage_present")
    assert controller.guided_workflow.issues_for_field("stage")[0].finding is finding
    action = controller.guided_workflow.recovery_action(finding)
    assert action.label == "Open stage"

    stage_box["stage"] = _FakeStage()
    action()
    assert controller.guided_validate().ok


def test_guided_run_observes_frame_then_stop_regresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, sensor = _run_ready_controller(monkeypatch, [_frame(0)])

    started = controller.guided_run_status
    assert started.configured is True
    assert started.running is True
    assert started.frame_count == 0
    assert controller.guided_workflow.status(GuidedStage.RUN) is (
        StageStatus.IN_PROGRESS
    )

    assert controller.update_sensor() is not None

    observed = controller.guided_run_status
    assert observed.frame_count == 1
    assert observed.last_timestamp_ms == 0
    assert controller.guided_workflow.status(GuidedStage.RUN) is StageStatus.COMPLETE

    controller.guided_stop_run()

    assert sensor.running is False
    assert controller.guided_run_status.stopped is True
    assert controller.guided_workflow.status(GuidedStage.RUN) is (StageStatus.BLOCKED)
    assert controller.guided_workflow.findings_for_stage(GuidedStage.RUN)


def test_guided_inspect_gates_summarizes_and_requires_user_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    gated = _controller(stage_box)
    assert gated.guided_mark_inspected() is False
    assert gated.guided_workflow.status(GuidedStage.INSPECT) is StageStatus.BLOCKED

    controller, _sensor = _run_ready_controller(monkeypatch, [_frame(0)])
    controller.update_sensor()
    assert controller.guided_advance()

    summary = controller.guided_inspect_summary()

    assert summary == {
        "latest_frame_id": "guided_frame_000",
        "latest_timestamp_ms": 0,
        "detection_count": 0,
        "backend": "tdoa_synthetic",
        "capability_generation": 2,
    }
    assert controller.guided_workflow.status(GuidedStage.INSPECT) is (
        StageStatus.IN_PROGRESS
    )
    assert controller.guided_mark_inspected()
    assert controller.guided_workflow.status(GuidedStage.INSPECT) is (
        StageStatus.COMPLETE
    )


def _enter_record_stage(controller: ExtensionController) -> None:
    assert controller.update_sensor() is not None
    assert controller.guided_workflow.status(GuidedStage.RUN) is StageStatus.COMPLETE
    assert controller.guided_advance()
    assert controller.guided_mark_inspected()
    assert controller.guided_advance()
    assert controller.guided_workflow.current_stage is GuidedStage.RECORD


def test_guided_recording_end_to_end_validates_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    waveform_paths = [
        _waveform(tmp_path / "waveforms" / f"frame_{index}.wav", index)
        for index in range(1, 4)
    ]
    controller, _sensor = _run_ready_controller(
        monkeypatch,
        [
            _frame(0),
            *[
                _frame(index, waveform_path=waveform_paths[index - 1])
                for index in range(1, 4)
            ],
        ],
    )
    _enter_record_stage(controller)
    session = tmp_path / "session"

    assert (
        controller.guided_start_recording(
            session,
            "guided_test",
            2,
            False,
            scene_id="scene_a",
            environment_id="environment_a",
            split_group="scene_a",
            session_seed=17,
        )
        is not None
    )
    for _ in range(3):
        assert controller.update_sensor() is not None

    active = controller.guided_recording_status
    assert active.frames == 3
    assert active.dropped_frames == 0
    assert active.shards_promoted == 1
    assert active.bytes_written > 0
    assert active.current_episode == "episode_00000"

    assert controller.guided_stop_recording() is not None

    report = validate_dataset(session)
    final = controller.guided_recording_status
    assert report.status in {"passed", "passed_with_warnings"}
    assert final.frames == 3
    assert final.shards_promoted == 2
    assert final.validation_status == report.status
    assert controller.guided_workflow.status(GuidedStage.RECORD) is (
        StageStatus.COMPLETE
    )


def test_guided_recording_marks_sensor_and_detected_simulator_resets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    recorded = (
        _frame(5, waveform_path=_waveform(tmp_path / "reset/5.wav", 5)),
        _frame(6, waveform_path=_waveform(tmp_path / "reset/6.wav", 6)),
        _frame(0, waveform_path=_waveform(tmp_path / "reset/0.wav", 0)),
    )
    controller, sensor = _run_ready_controller(
        monkeypatch,
        [_frame(0), *recorded],
    )
    _enter_record_stage(controller)
    session = tmp_path / "reset_session"
    assert (
        controller.guided_start_recording(
            session,
            "guided_reset_test",
            8,
            False,
            scene_id="scene_a",
            environment_id="environment_a",
            split_group="scene_a",
            session_seed=17,
        )
        is not None
    )

    assert controller.update_sensor() is recorded[0]
    sensor.reset()
    assert controller.update_sensor() is recorded[1]
    assert controller.update_sensor() is recorded[2]
    assert controller.guided_recording_status.reset_count == 2
    assert controller.guided_stop_recording() is not None

    manifest = read_dataset_manifest(session / "manifest.json")
    assert [episode.environment_id for episode in manifest.episodes] == [
        "environment_a",
        "environment_a_reset_00001",
        "environment_a_reset_00002",
    ]
    assert [len(episode.reset_markers) for episode in manifest.episodes] == [1, 1, 1]
    assert [episode.reset_markers[0].frame_index for episode in manifest.episodes] == [
        0,
        1,
        2,
    ]
    assert validate_dataset(session).status in {"passed", "passed_with_warnings"}


def test_equal_frame_identity_after_sensor_reset_is_not_a_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = _frame(5, waveform_path=_waveform(tmp_path / "equal/before.wav", 5))
    after = _frame(5, waveform_path=_waveform(tmp_path / "equal/after.wav", 6))
    controller, sensor = _run_ready_controller(
        monkeypatch,
        [_frame(0), before, after],
    )
    _enter_record_stage(controller)
    session = tmp_path / "equal_identity_session"
    assert (
        controller.guided_start_recording(
            session,
            "guided_equal_identity_reset",
            8,
            False,
        )
        is not None
    )

    assert controller.update_sensor() is before
    sensor.reset()
    assert controller.update_sensor() is after
    assert controller.guided_recording_status.frames == 2
    assert controller.guided_recording_status.reset_count == 1
    assert controller.guided_stop_recording() is not None

    manifest = read_dataset_manifest(session / "manifest.json")
    assert len(manifest.episodes) == 2
    assert [len(episode.reset_markers) for episode in manifest.episodes] == [1, 1]
    assert manifest.episodes[1].reset_markers[0].frame_index == 1
    assert validate_dataset(session).status in {"passed", "passed_with_warnings"}


def test_isaac_post_reset_lifecycle_resets_sensor_and_notifies_recorder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    callbacks: list[Any] = []
    deregistered: list[int] = []
    post_reset = object()
    simulation = SimpleNamespace(
        IsaacEvents=SimpleNamespace(POST_RESET=post_reset),
        SimulationManager=SimpleNamespace(
            register_callback=lambda callback, *, event: (
                callbacks.append((callback, event)) or 41
            ),
            deregister_callback=deregistered.append,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.simulation_manager",
        simulation,
    )
    frames = (
        _frame(5, waveform_path=_waveform(tmp_path / "lifecycle/5.wav", 5)),
        _frame(6, waveform_path=_waveform(tmp_path / "lifecycle/6.wav", 6)),
    )
    controller, sensor = _run_ready_controller(
        monkeypatch,
        [_frame(0), *frames],
    )
    _enter_record_stage(controller)
    session = tmp_path / "lifecycle_session"
    assert (
        controller.guided_start_recording(
            session,
            "guided_lifecycle_reset",
            8,
            False,
        )
        is not None
    )
    assert controller.update_sensor() is frames[0]

    controller._lifecycle._register_simulation_reset_callback()
    assert callbacks[0][1] is post_reset
    callbacks[0][0](object())
    assert sensor.latest_frame is None
    assert controller.update_sensor() is frames[1]
    assert controller.guided_recording_status.reset_count == 1
    assert controller.guided_stop_recording() is not None
    controller._lifecycle._unregister_simulation_reset_callback()

    manifest = read_dataset_manifest(session / "manifest.json")
    assert len(manifest.episodes) == 2
    assert len(manifest.episodes[1].reset_markers) == 1
    assert deregistered == [41]


def test_guided_recording_cancellation_finalizes_incomplete_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, _sensor = _run_ready_controller(
        monkeypatch,
        [_frame(0), _frame(1), _frame(2)],
    )
    _enter_record_stage(controller)
    session = tmp_path / "cancelled"
    assert (
        controller.guided_start_recording(
            session,
            "cancelled_test",
            1,
            False,
        )
        is not None
    )
    controller.update_sensor()
    controller.update_sensor()

    manifest = controller.guided_cancel_recording()

    assert manifest is not None
    assert manifest.completion_state == "incomplete"
    assert (session / "manifest.json").is_file()
    status = controller.guided_recording_status
    assert status.cancelled is True
    assert status.active is False
    assert controller.guided_workflow.status(GuidedStage.RECORD) is (
        StageStatus.BLOCKED
    )
    finding = controller.guided_workflow.findings_for_stage(GuidedStage.RECORD)[0]
    assert finding.message == "recording cancelled"
    recovery = controller.guided_workflow.recovery_action(finding)
    assert recovery.label == "Start new recording"

    recovery()

    assert controller.guided_recording_status.active is True
    retry_root = Path(controller.guided_recording_status.session_dir or "")
    assert retry_root != session
    assert retry_root.name == "cancelled_retry_1"
    controller.guided_cancel_recording()


def test_failed_dataset_validation_blocks_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, _sensor = _run_ready_controller(
        monkeypatch,
        [_frame(0), _frame(1)],
    )
    _enter_record_stage(controller)
    session = tmp_path / "failed_validation"
    assert (
        controller.guided_start_recording(
            session,
            "failed_test",
            2,
            False,
        )
        is not None
    )
    controller.update_sensor()
    planted = Finding(
        "checksum_mismatch",
        "error",
        "shard shard_00000 file audio.wav",
        "planted checksum mismatch",
    )
    monkeypatch.setattr(
        recording_workflow_module,
        "validate_dataset",
        lambda _root: SimpleNamespace(
            status="failed",
            findings=(planted,),
            error_count=1,
            warning_count=0,
        ),
    )

    assert controller.guided_stop_recording() is not None

    assert controller.guided_recording_status.validation_status == "failed"
    assert controller.guided_workflow.status(GuidedStage.RECORD) is (
        StageStatus.BLOCKED
    )
    mapped = controller.guided_workflow.findings_for_stage(GuidedStage.RECORD)
    assert mapped[0].check_id == "dataset_checksum_mismatch"
    assert mapped[0].field == "guided_session_dir"


def _finalized_guided_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    groups: tuple[str, ...] = ("scene_a",),
) -> tuple[ExtensionController, Path]:
    waveform_paths = [
        _waveform(tmp_path / "export_waveforms" / f"frame_{index}.wav", index)
        for index in range(1, len(groups) + 1)
    ]
    controller, _sensor = _run_ready_controller(
        monkeypatch,
        [
            _frame(0),
            *(
                _frame(index, waveform_path=waveform_paths[index - 1])
                for index in range(1, len(groups) + 1)
            ),
        ],
    )
    _enter_record_stage(controller)
    session = tmp_path / "recorded_session"
    recorder = controller.guided_start_recording(
        session,
        "export_test",
        8,
        len(groups) > 1,
        scene_id=groups[0],
        environment_id=f"environment_{groups[0]}",
        split_group=groups[0],
        session_seed=23,
    )
    assert recorder is not None
    for index, group in enumerate(groups):
        if index:
            recorder.end_episode()
            recorder.begin_episode(
                group,
                f"environment_{group}",
                group,
                seed=23 + index,
            )
        assert controller.update_sensor() is not None
    assert controller.guided_stop_recording() is not None
    assert validate_dataset(session).status in {"passed", "passed_with_warnings"}
    return controller, session


def test_guided_export_validates_relocated_copy_and_inventory_without_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, session = _finalized_guided_controller(monkeypatch, tmp_path)
    destination = tmp_path / "portable" / "exported_session"

    assert controller.guided_export(destination) == destination

    assert session.is_dir()
    assert validate_dataset(destination).status in {"passed", "passed_with_warnings"}
    assert not any(path.is_symlink() for path in destination.rglob("*"))
    status = controller.guided_export_status
    assert status.validation_status in {"passed", "passed_with_warnings"}
    assert status.split_status == "skipped_single_group"
    assert status.note == "Split skipped: the session contains one group."
    assert controller.guided_workflow.status(GuidedStage.EXPORT) is (
        StageStatus.COMPLETE
    )

    manifest = read_dataset_manifest(destination / "manifest.json")
    inventory = controller.guided_output_inventory()
    expected = {
        (asset.path, asset.kind, asset.sha256)
        for shard in manifest.shards
        for asset in shard.assets
    }
    assert {
        (entry["path"], entry["kind"], entry["sha256"]) for entry in inventory
    } == expected
    for entry in inventory:
        shard_id, filename = entry["path"].split("/")[1:]
        marker = json.loads(
            (destination / "shards" / shard_id / "shard.complete.json").read_text(
                encoding="utf-8"
            )
        )
        marker_entry = next(
            item for item in marker["files"] if item["path"] == filename
        )
        assert entry["bytes"] == marker_entry["bytes"]
        assert entry["sha256"] == marker_entry["sha256"]
    assert status.inventory_entries == len(inventory)
    assert status.inventory_bytes == sum(entry["bytes"] for entry in inventory)


def test_guided_export_rejects_destination_inside_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, session = _finalized_guided_controller(monkeypatch, tmp_path)
    destination = session / "nested_export"

    assert controller.guided_export(destination) is None
    assert not destination.exists()
    finding = controller.guided_workflow.findings_for_stage(GuidedStage.EXPORT)[0]
    assert finding.check_id == "guided_export_destination_inside_session"
    assert finding.field == "guided_export_dir"


def test_guided_export_rejects_unwritable_destination_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, _session = _finalized_guided_controller(monkeypatch, tmp_path)
    parent = tmp_path / "locked"
    parent.mkdir()
    parent.chmod(0o500)
    destination = parent / "exported_session"
    try:
        assert controller.guided_export(destination) is None
    finally:
        parent.chmod(0o700)
    assert not destination.exists()
    finding = controller.guided_workflow.findings_for_stage(GuidedStage.EXPORT)[0]
    assert finding.check_id == "guided_export_destination_unwritable"
    assert finding.field == "guided_export_dir"


def test_guided_export_applies_two_group_split_with_zero_test_ratio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, _session = _finalized_guided_controller(
        monkeypatch,
        tmp_path,
        groups=("scene_a", "scene_b"),
    )
    controller.state.guided_split_train_ratio = 0.5
    controller.state.guided_split_validation_ratio = 0.5
    controller.state.guided_split_test_ratio = 0.0
    destination = tmp_path / "two_group_export"

    assert controller.guided_export(destination) == destination

    manifest = read_dataset_manifest(destination / "manifest.json")
    assert controller.guided_export_status.split_status == "applied"
    assert {split.name for split in manifest.splits} == {"train", "validation"}
    assert {group for split in manifest.splits for group in split.group_ids} == {
        "scene_a",
        "scene_b",
    }
    assert validate_dataset(destination).status in {"passed", "passed_with_warnings"}


def test_guided_export_surfaces_impossible_default_ratios_for_two_groups(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    controller, _session = _finalized_guided_controller(
        monkeypatch,
        tmp_path,
        groups=("scene_a", "scene_b"),
    )
    destination = tmp_path / "impossible_split_export"

    assert controller.guided_export(destination) is None

    assert not destination.exists()
    finding = controller.guided_workflow.findings_for_stage(GuidedStage.EXPORT)[0]
    assert finding.check_id == "guided_export_split_impossible"
    assert finding.field == "guided_split_ratios"
    assert "Adjust split ratios" in (controller.guided_export_status.note or "")
    recovery = controller.guided_workflow.recovery_action(finding)
    assert recovery.label == "Adjust ratios"
    assert callable(recovery)
