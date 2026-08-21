from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
    Pose3D,
)
from isaac_audio_sensors.kit.controller import ExtensionController
from isaac_audio_sensors.kit.headless import HeadlessGuidedSession
from isaac_audio_sensors.kit.state import CurrentStageContext
from isaac_audio_sensors.kit.workflow import GUIDED_STAGE_ORDER


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


def _frame(index: int) -> AudioSensorFrame:
    timestamp = index * 10
    return AudioSensorFrame(
        frame_id=f"guided_frame_{index:03d}",
        timestamp_ms=timestamp,
        backend_id="geometry_only",
        array_id="minimal_array",
        start_time_s=index / 100.0,
        end_time_s=index / 100.0 + 0.001,
        sample_rate_hz=8_000,
        frame_index=index,
        detections=(
            AudioDetection(
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
            ),
        ),
        aggregate_per_mic_rms={"center": 0.5},
        diagnostics={"window_sample_count": 8},
    )


def _controller_with_sensor(frame_count: int) -> ExtensionController:
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(_FakeStage(), ())
    )
    sensor = _FakeSensor([_frame(index) for index in range(frame_count)])
    controller._sensor_session._build_sensor = lambda _stage: sensor
    return controller


def _write_guided_config(path: Path) -> Path:
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(_FakeStage(), ())
    )
    assert controller.guided_apply_preset("minimal_single_source") is not None
    controller.state.sample_rate_hz = 8_000
    controller.state.update_period_s = 0.001
    controller.state.guided_dataset_id = "headless_workflow"
    controller.state.guided_shard_max_frames = 2
    controller.state.guided_record_aligned = False
    controller.state.guided_scene_id = "scene_a"
    controller.state.guided_environment_id = "environment_a"
    controller.state.guided_split_group = "scene_a"
    controller.state.guided_session_seed = 17
    controller.state.guided_split_enabled = False
    assert controller.export_config_summary(path) == path
    return path


def test_headless_session_drives_all_stages_and_exports_valid_session(
    tmp_path: Path,
) -> None:
    config = _write_guided_config(tmp_path / "config.json")
    session = HeadlessGuidedSession(controller=_controller_with_sensor(4))

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
