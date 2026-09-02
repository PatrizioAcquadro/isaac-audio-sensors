import json

from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import (
    _FakePrim,
    _FakeStage,
    _install_fake_kit_update_stream,
)


def test_extension_controller_authors_runs_overlays_and_exports(tmp_path):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")
    controller.state.latest_frame_export_path = str(tmp_path / "latest.json")
    controller.state.config_export_path = str(tmp_path / "binding.json")

    array_record = controller.author_array(stage=stage)
    source_record = controller.author_source(stage=stage)
    discovered = controller.refresh_discovery(stage=stage)
    sensor = controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()
    latest_path = controller.export_latest_frame()
    config_path = controller.export_config_summary()
    imported = ExtensionController()
    imported_path = imported.import_config_summary(config_path)

    assert array_record is not None
    assert source_record is not None
    assert stage.GetPrimAtPath("/World/Sources/SpeakerA").attributes[
        "xformOp:translate"
    ] == (2.0, 0.0, 0.0)
    assert stage.GetPrimAtPath("/World/Sources/SpeakerA").attributes[
        "ias:position_world"
    ] == (2.0, 0.0, 0.0)
    assert {item.id for item in discovered} == {"rig_front", "speaker_a"}
    assert sensor is not None
    assert frame is not None
    assert controller.state.latest_detection_count == 1
    assert controller.state.latest_bearing_deg is not None
    assert abs(controller.state.latest_bearing_deg) <= 1e-6
    assert controller.state.latest_sector is not None
    assert controller.state.latest_overlay_primitive_count >= 4
    assert latest_path == tmp_path / "latest.json"
    assert config_path == tmp_path / "binding.json"
    assert json.loads(latest_path.read_text(encoding="utf-8"))["backend_id"] == (
        "analytic_acoustics"
    )
    trace_lines = (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(trace_lines) == 1
    summary = json.loads(config_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == "ias.omni_extension_binding.v5"
    assert summary["environment"]["mode"] == "manual_free_field"
    assert summary["environment"]["resolved"]["kind"] == "free_field"
    assert summary["array"]["prim_path"] == "/World/Rig/AudioArray"
    assert summary["source"]["prim_path"] == "/World/Sources/SpeakerA"
    assert summary["source"]["position_world"] == [2.0, 0.0, 0.0]
    assert summary["latest_frame"]["source_prim_path"] == "/World/Sources/SpeakerA"
    assert summary["latest_frame"]["source_position_m"] == [2.0, 0.0, 0.0]
    assert summary["lifecycle"]["writer_path"].endswith("frames.jsonl")
    assert summary["recording"]["package_jsonl"]["path"].endswith("frames.jsonl")
    assert summary["recording"]["replicator"]["enabled"] is False
    assert summary["overlay"]["primitive_count"] == (
        controller.state.latest_overlay_primitive_count
    )
    assert imported_path == config_path
    assert imported.state.array_prim_path == "/World/Rig/AudioArray"
    assert imported.state.source_prim_path == "/World/Sources/SpeakerA"
    assert imported.state.source_position_x_m == 2.0
    assert imported.state.source_position_y_m == 0.0
    assert imported.state.source_position_z_m == 0.0
    assert imported.state.jsonl_trace_path.endswith("frames.jsonl")
    assert imported.state.environment_anchor_prim_path == ""
    assert imported.state.environment_resolution_mode == "manual_free_field"
    assert imported.state.analytic_max_order == 0


def test_extension_controller_auto_update_refreshes_live_frame_state_and_rms(
    monkeypatch,
    tmp_path,
):
    stream = _install_fake_kit_update_stream(monkeypatch)
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (2.0, 0.0, 0.0)},
    )
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            oven,
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.update_period_s = 0.01
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None

    stream.trigger()
    first_position = controller.state.latest_source_position_m
    first_bearing = controller.state.latest_bearing_deg
    first_sector = controller.state.latest_sector
    first_rms = dict(controller.state.latest_aggregate_rms)

    oven.attributes["xformOp:translate"] = (0.0, 2.0, 0.0)
    stream.trigger()

    assert first_position == (2.0, 0.0, 0.0)
    assert first_sector == "straight"
    assert controller.state.latest_source_position_m == (0.0, 2.0, 0.0)
    assert controller.state.latest_bearing_deg != first_bearing
    assert controller.state.latest_sector == "right"
    assert controller.state.latest_aggregate_rms != first_rms
    assert controller.state.detection_history


def test_extension_controller_attached_source_outside_world_is_captured(tmp_path):
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/Kitchen",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/Kitchen/Refrigerator",
                "Xform",
                {"xformOp:translate": (2.0, 0.0, 0.0)},
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.jsonl_trace_path = str(tmp_path / "frames.jsonl")

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/Kitchen/Refrigerator",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.state.source_prim_path == "/Kitchen/Refrigerator/SpeakerA"

    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()

    assert frame is not None
    assert frame.detections[0].source_id == "speaker_a"
    assert frame.detections[0].source_pose.position_m == (2.0, 0.0, 0.0)


def test_extension_controller_authors_persistent_usd_debug_geometry(tmp_path):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.usd_debug_enabled = True
    controller.state.trace_enabled = False

    assert controller.author_array(stage=stage) is not None
    assert controller.author_source(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    assert controller.update_sensor(force=True) is not None

    paths = controller.state.latest_usd_debug_prim_paths
    assert paths
    assert all(path.startswith("/World/IasAudioDebug/") for path in paths)
    kinds = {stage.GetPrimAtPath(path).type_name for path in paths}
    assert "Sphere" in kinds
    assert "BasisCurves" in kinds
    assert stage.GetPrimAtPath("/World/IasAudioDebug") is not None

    controller.state.usd_debug_enabled = False
    assert controller.update_sensor(force=True) is not None
    assert controller.state.latest_usd_debug_prim_paths == ()
    assert stage.GetPrimAtPath("/World/IasAudioDebug") is None


def test_extension_controller_unconfigured_environment_fails_closed():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    assert controller.author_array(stage=stage) is not None
    assert controller.configure_sensor(stage=stage) is None
    assert controller.sensor is None
    assert "Select an acoustic environment mode" in str(controller.state.error_message)


def test_extension_controller_unconfigured_environment_blocks_restart():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    assert controller.author_array(stage=stage) is not None
    assert controller.configure_sensor(stage=stage) is not None
    controller.stop_sensor()

    controller.state.environment_resolution_mode = "unconfigured"

    assert controller.start_sensor(stage=stage) is None
    assert not controller.state.sensor_running
    assert "Select an acoustic environment mode" in str(controller.state.error_message)


def test_extension_controller_environment_anchors_to_designated_prim():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Environment",
                "Xform",
                {
                    "ias:environment_min_world": (-2.0, -3.0, 0.0),
                    "ias:environment_max_world": (6.0, 3.0, 3.0),
                    "ias:material": "carpet",
                },
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "anchor"
    controller.state.environment_anchor_prim_path = "/World/Environment"
    controller.state.analytic_max_order = 2
    assert controller.author_array(stage=stage) is not None
    assert controller.configure_sensor(stage=stage) is not None
    environment = controller.sensor.environment
    assert environment is not None
    assert environment.dimensions_m == (8.0, 6.0, 3.0)
    assert environment.world_pose.position_m == (-2.0, -3.0, 0.0)
    assert controller.sensor.environment_resolution_cfg.anchor_prim_path == (
        "/World/Environment"
    )
    assert environment.surfaces[0].absorption == 0.30
    summary = controller.state.latest_environment_summary
    assert summary is not None
    assert summary["absorption_provenance"] == "semantic:carpet"
    assert summary["analytic_acoustics"]["max_order"] == 2


def test_extension_controller_auto_resolves_marked_environment():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Room",
                "Xform",
                {
                    "ias:environment_kind": "shoebox",
                    "ias:environment_id": "room_a",
                    "ias:environment_priority": 3,
                    "ias:environment_min_world": (-2.0, -2.0, -1.0),
                    "ias:environment_max_world": (2.0, 2.0, 2.0),
                },
            ),
        )
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "auto"
    assert controller.author_array(stage=stage) is not None

    assert controller.configure_sensor(stage=stage) is not None

    assert controller.sensor.environment.environment_id == "room_a"
    summary = controller.state.latest_environment_summary
    assert summary is not None
    assert summary["mode"] == "auto"
    assert summary["selected_prim_path"] == "/World/Room"
    assert summary["priority"] == 3


def test_extension_controller_environment_anchor_missing_prim_records_error():
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "anchor"
    controller.state.environment_anchor_prim_path = "/World/MissingEnvironment"
    assert controller.author_array(stage=stage) is not None

    assert controller.configure_sensor(stage=stage) is None

    assert controller.sensor is None
    assert controller.state.error_message is not None
    assert "/World/MissingEnvironment" in controller.state.error_message
