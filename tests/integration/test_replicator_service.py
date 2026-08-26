import json
from pathlib import Path

from isaac_audio_sensors.isaac.replicator import PAYLOAD_SCHEMA_VERSION
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.constants import OUTPUT_ROOT_ENV_VAR
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import (
    _FakePrim,
    _FakeStage,
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
    controller.state.backend = "tdoa_synthetic"
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
    assert controller.state.latest_sector == "right"
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
    controller.state.backend = "geometry_only"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.replicator_enabled = True
    controller.state.replicator_output_dir = str(tmp_path / "replicator")

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    status = controller.start_replicator()
    frame = controller.update_sensor()
    flushed = controller.flush_replicator()
    stopped = controller.stop_replicator()

    assert status is not None
    assert status["writer_registered"] is True
    assert status["annotator_registered"] is True
    assert frame is not None
    assert flushed is not None
    assert flushed["flushed"] is True
    assert stopped is not None
    assert stopped["stopped"] is True
    assert controller.state.replicator_write_count == 1
    payload_path = Path(controller.state.replicator_latest_write_path or "")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PAYLOAD_SCHEMA_VERSION
    assert payload["summary"]["backend_id"] == "geometry_only"
    assert payload["summary"]["detection_count"] == 1
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
    controller.state.backend = "geometry_only"
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
