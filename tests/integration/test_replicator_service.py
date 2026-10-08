import json
import sys
from pathlib import Path

import pytest

from isaac_audio_sensors.isaac.replicator import PAYLOAD_SCHEMA_VERSION
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.constants import OUTPUT_ROOT_ENV_VAR
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import (
    _FakePrim,
    _FakeStage,
    _FakeUI,
    _install_fake_kit_update_stream,
    _install_fake_replicator,
)


def test_extension_controller_auto_update_skips_duplicate_replicator_writes(
    monkeypatch,
    tmp_path,
):
    _install_fake_replicator(monkeypatch)
    stream = _install_fake_kit_update_stream(monkeypatch, timeline_time_s=0.0)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.update_period_s = 10.0
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    assert controller.start_replicator() is not None

    stream.trigger()
    stream.trigger()

    assert controller.state.replicator_write_count == 1
    assert len((tmp_path / "frames.jsonl").read_text().splitlines()) == 1

    source = stage.GetPrimAtPath("/World/Sources/SpeakerA")
    assert source is not None
    source.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    forced = controller.update_sensor()

    assert forced is not None
    assert controller.state.replicator_write_count == 2
    assert len((tmp_path / "frames.jsonl").read_text().splitlines()) == 2


def test_extension_controller_replicator_lifecycle_and_payload(
    monkeypatch,
    tmp_path,
):
    _install_fake_replicator(monkeypatch)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.ext_id = "test.ext"
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    status = controller.start_replicator()
    warmup = controller.update_sensor()
    frame = controller.update_sensor()
    flushed = controller.flush_replicator()
    stopped = controller.stop_replicator()

    assert status is not None
    assert status["writer_registered"] is True
    assert status["annotator_registered"] is False
    assert status["annotator_status"] == "metadata_only"
    assert frame is not None
    assert warmup is not None
    assert warmup.observations == ()
    assert len(frame.observations) == 1
    assert frame.observations[0].origin.value == "signal_derived"
    assert frame.observations[0].detector_id == "auditok"
    assert flushed is not None
    assert flushed["flushed"] is True
    assert stopped is not None
    assert stopped["stopped"] is True
    assert controller.state.replicator_write_count == 2
    payload_path = Path(controller.state.replicator_latest_write_path or "")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PAYLOAD_SCHEMA_VERSION
    assert payload["replicator"]["annotator_name"] == (
        controller.state.replicator_annotator_name
    )
    assert payload["summary"]["producer_id"] == "analytic_acoustics"
    assert payload["summary"]["observation_count"] == 1
    assert payload["frame"]["observations"][0]["origin"] == "signal_derived"
    assert payload["frame"]["observations"][0]["detector_id"] == "auditok"
    assert payload["metadata"]["extension_id"] == "test.ext"
    assert (tmp_path / "replicator" / "audio_sensor_frames.jsonl").exists()


def test_extension_controller_writer_and_replicator_paths_use_output_root_env(
    monkeypatch,
    tmp_path,
):
    output_root = tmp_path / "ias_outputs"
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(output_root))
    _install_fake_replicator(monkeypatch)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = "manual/frames.jsonl"
    controller.state.replicator_output_dir = "manual/replicator"

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    status = controller.start_replicator()
    frame = controller.update_sensor()

    assert status is not None
    assert status["output_dir"] == str(output_root / "manual" / "replicator")
    assert frame is not None
    assert (output_root / "manual" / "frames.jsonl").exists()
    assert (
        output_root / "manual" / "replicator" / "audio_sensor_frames.jsonl"
    ).exists()


def test_extension_controller_replicator_missing_runtime_is_readable(tmp_path):
    controller = ExtensionController()
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    status = controller.start_replicator()

    assert status is None
    assert controller.state.error_message is not None
    assert "Replicator start failed" in controller.state.error_message
    assert "omni.replicator.core" in controller.state.error_message
    assert controller.state.replicator_enabled is False
    assert controller.state.replicator_recording is False


@pytest.fixture
def running_replicator_sensor(monkeypatch, tmp_path):
    _install_fake_replicator(monkeypatch)
    stream = _install_fake_kit_update_stream(monkeypatch, timeline_time_s=0.0)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.update_period_s = 0.1
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_output_dir = str(tmp_path / "replicator")
    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    yield controller, stream
    controller.on_shutdown()


@pytest.mark.parametrize("automatic", [True, False])
def test_replicator_repeated_stop_restart_preserves_acquisition(
    running_replicator_sensor, tmp_path, automatic
):
    controller, stream = running_replicator_sensor
    sensor = controller.sensor
    subscription = controller._lifecycle._controller_update_subscription

    def capture():
        stream.timeline_clock.time_s += 0.2
        if automatic:
            stream.trigger()
        else:
            assert controller.update_sensor() is not None
        assert controller.sensor is sensor
        assert controller.state.sensor_running is True
        assert controller.state.error_message is None
        assert controller._lifecycle._controller_update_subscription is subscription
        assert sensor.latest_frame is not None
        return sensor.latest_frame

    capture()
    for _ in range(3):
        started = controller.start_replicator()
        assert started["enabled"] is True
        assert started["started"] is True
        written = capture()
        assert controller.state.replicator_write_count == 1
        stopped = controller.stop_replicator()
        assert stopped["enabled"] is False
        assert stopped["started"] is False
        assert stopped["stopped"] is True
        assert controller.state.replicator_recording is False
        assert sensor.latest_frame is written
        assert Path(stopped["latest_write_path"]).is_file()
        assert stopped["output_artifacts"]
        manifest = json.loads(
            (
                tmp_path / "replicator" / "audio_sensor_replicator_manifest.json"
            ).read_text()
        )
        assert manifest["started"] is False
        assert manifest["stopped"] is True
        output = Path(stopped["latest_jsonl_path"])
        recorded = output.read_bytes()
        assert controller.stop_replicator() == stopped
        for _ in range(3):
            continued = capture()
            assert continued.timestamp_ms > written.timestamp_ms
            assert controller.state.replicator_write_count == 1
            assert output.read_bytes() == recorded
        assert controller.state.replicator_output_dir == started["output_dir"]
    assert len((tmp_path / "frames.jsonl").read_text().splitlines()) == 13


def test_replicator_idle_stop_disables_frame_dispatch(running_replicator_sensor):
    controller, stream = running_replicator_sensor
    controller.state.replicator_enabled = True
    stopped = controller.stop_replicator()
    assert stopped["enabled"] is False
    assert stopped["started"] is False
    assert controller.stop_replicator() == stopped
    stream.trigger()
    assert controller.state.sensor_running is True
    assert controller.state.error_message is None


def test_replicator_gui_stop_synchronizes_enable(
    running_replicator_sensor, monkeypatch
):
    controller, stream = running_replicator_sensor
    ui = _FakeUI()
    monkeypatch.setattr(sys.modules["omni"], "ui", ui, raising=False)
    monkeypatch.setitem(sys.modules, "omni.ui", ui)
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    window._action(controller.start_replicator)()
    assert window._bool_fields["replicator_enabled"].model.as_bool is True
    stream.trigger()
    window._action(controller.stop_replicator)()
    assert window._bool_fields["replicator_enabled"].model.as_bool is False
    # Another action reads widgets again; the stale checkbox must not re-enable writes.
    window._action(controller.update_sensor)()
    assert controller.state.replicator_enabled is False
    assert controller.state.replicator_write_count == 1
    assert controller.state.sensor_running is True
    assert controller.state.error_message is None


def test_failed_replicator_restart_preserves_acquisition(
    running_replicator_sensor, monkeypatch
):
    controller, stream = running_replicator_sensor
    assert controller.start_replicator() is not None
    stream.trigger()
    old_recorder = controller.replicator_recorder

    def fail_start(_recorder):
        raise RuntimeError("writer initialization failed")

    monkeypatch.setattr(type(old_recorder), "start", fail_start)
    assert controller.start_replicator() is None
    assert controller.state.replicator_enabled is False
    assert controller.state.replicator_recording is False
    assert old_recorder.status.started is False
    assert "writer initialization failed" in controller.state.error_message
    stream.timeline_clock.time_s += 0.2
    stream.trigger()
    assert controller.state.sensor_running is True
    assert controller.state.error_message is None
    assert controller.sensor.latest_frame is not None


def test_failed_replicator_stop_disables_frame_dispatch(
    running_replicator_sensor, monkeypatch
):
    controller, stream = running_replicator_sensor
    assert controller.start_replicator() is not None
    stream.trigger()

    def fail_stop():
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(controller.replicator_recorder, "stop", fail_stop)
    assert controller.stop_replicator() is None
    assert controller.state.replicator_enabled is False
    assert controller.state.replicator_recording is False
    assert "manifest write failed" in controller.state.error_message
    stream.timeline_clock.time_s += 0.2
    stream.trigger()
    assert controller.state.sensor_running is True
    assert controller.state.replicator_write_count == 1
    assert controller.state.error_message is None


def test_enabled_replicator_without_start_still_reports_error(
    running_replicator_sensor,
):
    controller, _stream = running_replicator_sensor
    controller.state.replicator_enabled = True
    assert controller.update_sensor() is None
    assert controller.state.sensor_running is False
    assert "Replicator recording is enabled but not started" in (
        controller.state.error_message
    )
