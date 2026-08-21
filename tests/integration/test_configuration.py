# ruff: noqa: F403, F405

from isaac_audio_sensors.kit.sensor_session import SensorSession

from ._kit_ui_support import *


def test_kit_resolves_relative_validation_paths_against_repo(monkeypatch):
    monkeypatch.delenv(OUTPUT_ROOT_ENV_VAR, raising=False)
    repo = Path(__file__).resolve().parents[2]
    root = (repo / "build" / "validation" / "isaac_audio_sensors").resolve()

    assert _gui_output_root() == root
    assert _resolve_gui_output_path("gui_manual_binding.json") == (
        root / "gui_manual_binding.json"
    )
    assert _resolve_gui_output_path("manual/binding.json") == (
        root / "manual" / "binding.json"
    )


def test_live_ux_observes_orientation_without_controller_private_method(monkeypatch):
    live_ux = _load_live_ux_script(monkeypatch)
    controller = ExtensionController()
    controller.state.array_yaw_deg = 90.0

    observed = live_ux._observed_config_state(controller)

    assert observed["array_orientation_world_quat"] == pytest.approx(
        quaternion_from_yaw_deg(90.0)
    )


def test_extension_controller_config_paths_use_output_root_env(
    monkeypatch,
    tmp_path,
):
    output_root = tmp_path / "ias_outputs"
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(output_root))
    controller = ExtensionController()
    controller.state.source_prim_path = "/World/Oven/SpeakerA"
    controller.state.object_prim_path = "/World/Oven"
    controller.state.object_label = "Oven"
    controller.state.source_attached_to_object = True
    controller.state.attached_object_prim_path = "/World/Oven"
    controller.state.source_local_offset_x_m = 0.25
    controller.state.source_local_offset_y_m = 0.5
    controller.state.source_local_offset_z_m = 0.75

    controller.state.config_export_path = "gui_manual_binding.json"
    path = controller.export_config_summary()

    assert path == output_root / "gui_manual_binding.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["source"]["prim_path"] == "/World/Oven/SpeakerA"
    assert summary["object_binding"] == {
        "attached": True,
        "attached_object_prim_path": "/World/Oven",
        "selected_object_label": "Oven",
        "selected_object_prim_path": "/World/Oven",
        "source_local_offset_m": [0.25, 0.5, 0.75],
    }
    assert summary["lifecycle"]["writer_path"] == str(
        output_root / "extension_trace.frames.jsonl"
    )

    imported = ExtensionController()
    imported.state.config_import_path = "gui_manual_binding.json"
    assert imported.import_config_summary() == path
    assert imported.state.config_import_path == "gui_manual_binding.json"
    assert imported.state.array_prim_path == "/World/Rig/AudioArray"
    assert imported.state.source_prim_path == "/World/Oven/SpeakerA"
    assert imported.state.object_prim_path == "/World/Oven"
    assert imported.state.source_attached_to_object is True
    assert imported.state.attached_object_prim_path == "/World/Oven"
    assert imported.state.source_local_offset_x_m == 0.25
    assert imported.state.source_local_offset_y_m == 0.5
    assert imported.state.source_local_offset_z_m == 0.75

    controller.state.config_export_path = "manual/binding.json"
    assert controller.export_config_summary() == output_root / "manual" / "binding.json"

    absolute_path = tmp_path / "absolute_binding.json"
    controller.state.config_export_path = str(absolute_path)
    assert controller.export_config_summary() == absolute_path


def test_extension_controller_profile_config_roundtrip_legacy_and_errors(tmp_path):
    controller = ExtensionController()
    controller.state.config_export_path = str(tmp_path / "profiles_config.json")
    controller.state.object_prim_path = "/World/Oven"
    controller.state.object_label = "Oven"
    controller.state.source_prim_path = "/World/Oven/SpeakerA"
    controller.state.source_attached_to_object = True
    controller.state.attached_object_prim_path = "/World/Oven"
    controller.state.selected_profile_id = "oven_stove"
    controller.state.applied_source_profile = {
        "profile_id": "oven_stove",
        "source_id": "oven_source",
        "class_label": "Appliance",
        "audio_asset_path": "generated://pulse",
    }

    config_path = controller.export_config_summary()
    assert config_path == tmp_path / "profiles_config.json"
    summary = json.loads(config_path.read_text(encoding="utf-8"))
    assert summary["source"]["directivity"] == "omni"
    assert summary["sound_profiles"]["selected_profile_id"] == "oven_stove"
    assert summary["sound_profiles"]["object_profile_mappings"]["oven"] == (
        "oven_stove"
    )
    assert summary["sound_profiles"]["applied_source_profile"]["profile_id"] == (
        "oven_stove"
    )

    imported = ExtensionController()
    assert imported.import_config_summary(config_path) == config_path
    assert imported.state.selected_profile_id == "oven_stove"
    assert tuple(profile.profile_id for profile in imported.state.profile_library) == (
        "door_knock",
        "footsteps_movement",
        "oven_stove",
        "sink_water",
        "speech_generic",
    )
    assert imported.state.object_profile_mappings["oven"] == "oven_stove"
    assert imported.state.applied_source_profile["source_id"] == "oven_source"

    legacy = dict(summary)
    legacy.pop("sound_profiles")
    legacy_path = tmp_path / "legacy_config.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_imported = ExtensionController()
    assert legacy_imported.import_config_summary(legacy_path) == legacy_path
    assert legacy_imported.state.selected_profile_id == "speech_generic"

    unknown = dict(summary)
    unknown["sound_profiles"] = dict(summary["sound_profiles"])
    unknown["sound_profiles"]["selected_profile_id"] = "missing_profile"
    unknown_path = tmp_path / "unknown_profile.json"
    unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
    unknown_imported = ExtensionController()
    assert unknown_imported.import_config_summary(unknown_path) is None
    assert unknown_imported.state.error_message is not None
    assert "Unknown selected sound profile id" in unknown_imported.state.error_message

    missing_mapping = dict(summary)
    missing_mapping["sound_profiles"] = dict(summary["sound_profiles"])
    missing_mapping["sound_profiles"].pop("object_profile_mappings")
    missing_mapping_path = tmp_path / "missing_mapping.json"
    missing_mapping_path.write_text(json.dumps(missing_mapping), encoding="utf-8")
    missing_mapping_imported = ExtensionController()
    assert missing_mapping_imported.import_config_summary(missing_mapping_path) is None
    assert missing_mapping_imported.state.error_message is not None
    assert "object_profile_mappings is required" in (
        missing_mapping_imported.state.error_message
    )


def test_extension_controller_rig_profile_select_apply_and_config_roundtrip(
    tmp_path,
):
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "geometry_only"
    controller.state.config_export_path = str(tmp_path / "binding.json")

    assert controller.author_array(stage=stage) is not None
    profile = controller.select_rig_profile("quad_cross_120mm")
    assert profile is not None
    assert controller.apply_selected_rig_profile(stage=stage) is not None
    array_prim = stage.GetPrimAtPath("/World/Rig/AudioArray")
    assert array_prim is not None
    assert array_prim.attributes["ias:rig_profile_id"] == "quad_cross_120mm"
    assert array_prim.attributes["ias:layout_name"] == "quad_cross"
    assert array_prim.attributes["ias:sample_rate_hz"] == 48_000
    assert array_prim.attributes["ias:microphone_ids"] == (
        "front",
        "right",
        "rear",
        "left",
    )
    assert array_prim.attributes["ias:microphone_relative_offsets_m"][0] == (
        0.06,
        0.0,
        0.0,
    )
    front_mic = stage.GetPrimAtPath("/World/Rig/AudioArray/front")
    assert front_mic is not None
    assert front_mic.attributes["ias:gain_db"] == 0.0
    assert front_mic.attributes["ias:relative_position_m"] == (0.06, 0.0, 0.0)
    assert controller.state.applied_array_rig_profile["profile_id"] == (
        "quad_cross_120mm"
    )
    assert controller.state.array_local_offset_z_m == pytest.approx(0.0)
    assert controller.state.layout_name == "quad_cross"

    assert controller.select_rig_profile("stereo_y_100mm") is not None
    assert controller.apply_selected_rig_profile(stage=stage) is not None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/front") is None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/rear") is None
    left_mic = stage.GetPrimAtPath("/World/Rig/AudioArray/left")
    assert left_mic is not None
    assert left_mic.attributes["ias:relative_position_m"] == (0.0, -0.05, 0.0)
    assert controller.state.array_local_offset_x_m == pytest.approx(0.0)

    controller.state.array_position_x_m = 1.0
    controller.state.array_position_y_m = 2.0
    controller.state.array_yaw_deg = 90.0
    path = controller.export_config_summary()
    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["array"]["position_world"] == [1.0, 2.0, 0.0]
    rig_section = payload["microphone_rig_profiles"]
    assert rig_section["selected_rig_profile_id"] == "stereo_y_100mm"
    assert len(rig_section["rig_library"]) == 2
    assert payload["array_binding"]["attached"] is False
    assert payload["array_binding"]["array_local_offset_m"] == [0.0, 0.0, 0.0]

    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert imported.state.selected_rig_profile_id == "stereo_y_100mm"
    assert {item.profile_id for item in imported.state.rig_profile_library} == {
        "quad_cross_120mm",
        "stereo_y_100mm",
    }
    assert imported.state.array_position_x_m == pytest.approx(1.0)
    assert imported.state.array_position_y_m == pytest.approx(2.0)
    assert imported.state.array_yaw_deg == pytest.approx(90.0)
    assert imported.state.array_local_offset_x_m == pytest.approx(0.0)
    assert imported.state.applied_array_rig_profile["profile_id"] == ("stereo_y_100mm")

    legacy_payload = {
        "schema_version": "ias.omni_extension_binding.v1",
        "backend": "geometry_only",
        "array": {"prim_path": "/World/Rig/AudioArray", "array_id": "legacy_rig"},
        "source": {"prim_path": "/World/Sources/SpeakerA"},
    }
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    legacy = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert legacy.import_config_summary(legacy_path) == legacy_path
    assert legacy.state.error_message is None
    assert legacy.state.array_id == "legacy_rig"
    assert legacy.state.array_attached_to_object is False
    assert [item.profile_id for item in legacy.state.rig_profile_library] == [
        item.profile_id for item in default_microphone_rig_profiles()
    ]


def test_extension_controller_object_local_offset_and_config_roundtrip(tmp_path):
    oven = _FakePrim(
        "/World/Oven",
        "Xform",
        {"xformOp:translate": (1.0, 0.0, 0.0)},
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
    controller.state.backend = "geometry_only"
    controller.state.config_export_path = str(tmp_path / "binding.json")
    controller.state.source_local_offset_x_m = 0.0
    controller.state.source_local_offset_y_m = 1.0
    controller.state.source_local_offset_z_m = 0.25

    assert controller.author_array(stage=stage) is not None
    assert controller.use_selected_as_object(
        stage=stage,
        selected_paths=("/World/Oven",),
    )
    assert controller.attach_source_to_object(stage=stage) is not None
    assert controller.start_sensor(stage=stage, subscribe_to_update_stream=False)
    frame = controller.update_sensor()
    assert frame is not None
    assert frame.detections[0].source_pose.position_m == (1.0, 1.0, 0.25)

    path = controller.export_config_summary()
    assert path == tmp_path / "binding.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["object_binding"] == {
        "attached": True,
        "attached_object_prim_path": "/World/Oven",
        "selected_object_label": "Oven",
        "selected_object_prim_path": "/World/Oven",
        "source_local_offset_m": [0.0, 1.0, 0.25],
    }
    assert summary["source"]["prim_path"] == "/World/Oven/SpeakerA"
    assert summary["source"]["local_offset_m"] == [0.0, 1.0, 0.25]
    assert any(
        item["prim_path"] == "/World/Oven/SpeakerA"
        for item in summary["authored_metadata"]
    )

    imported = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert imported.import_config_summary(path) == path
    assert imported.state.object_prim_path == "/World/Oven"
    assert imported.state.object_label == "Oven"
    assert imported.state.source_attached_to_object is True
    assert imported.state.attached_object_prim_path == "/World/Oven"
    assert imported.state.source_prim_path == "/World/Oven/SpeakerA"
    assert imported.state.source_local_offset_x_m == 0.0
    assert imported.state.source_local_offset_y_m == 1.0
    assert imported.state.source_local_offset_z_m == 0.25
    assert imported.state.error_message is None


def test_extension_controller_waveform_settings_flow_to_sensor_and_config(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(OUTPUT_ROOT_ENV_VAR, str(tmp_path))
    sink = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        SensorSession,
        "_waveform_sink_or_none",
        lambda _controller, _array_id: sink,
    )
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "tdoa_synthetic"
    controller.state.waveform_enabled = True
    controller.state.waveform_dir = "wavs"
    controller.state.waveform_mode = "session"

    assert controller.author_array(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    sensor = controller.sensor
    assert sensor is not None
    assert sensor.waveform_sink is sink

    assert sensor.room is None  # default shoebox only applies to room_acoustics

    controller.state.config_export_path = str(tmp_path / "config.json")
    assert controller.export_config_summary() is not None

    restored = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    restored.state.config_import_path = str(tmp_path / "config.json")
    assert restored.import_config_summary() is not None
    assert restored.state.waveform_enabled is True
    assert restored.state.waveform_dir == "wavs"
    assert restored.state.waveform_mode == "session"


def test_kit_config_roundtrips_edited_widget_state(tmp_path, monkeypatch):
    omni = ModuleType("omni")
    omni_ui = _FakeUI()
    omni.ui = omni_ui
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.ui", omni_ui)
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0, 0, 0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.config_export_path = str(tmp_path / "binding.json")
    assert controller.build_ui_if_available() is not None
    window = controller._lifecycle._ui_window
    assert window is not None

    window._string_fields["source_id"].model.set_value("edited_source")
    window._string_fields["array_prim_path"].model.set_value("/World/EditedArray")
    window._string_fields["source_prim_path"].model.set_value("/World/EditedSource")
    window._string_fields["object_prim_path"].model.set_value("/World/EditedObject")
    window._string_fields["jsonl_trace_path"].model.set_value(
        str(tmp_path / "edited.frames.jsonl")
    )
    window._string_fields["replicator_output_dir"].model.set_value(
        str(tmp_path / "replicator")
    )
    window._float_fields["source_duration_s"].model.set_value("60.0")
    window._float_fields["source_position_x_m"].model.set_value("0.0")
    window._float_fields["source_position_y_m"].model.set_value("2.0")
    window._float_fields["source_position_z_m"].model.set_value("0.5")
    window._float_fields["source_local_offset_x_m"].model.set_value("0.25")
    window._float_fields["source_local_offset_y_m"].model.set_value("0.5")
    window._float_fields["source_local_offset_z_m"].model.set_value("0.75")
    window._int_fields["sample_rate_hz"].model.set_value("44100")
    backend_widget, backend_choices = window._combo_fields["backend"]
    backend_widget.model.set_value(backend_choices.index("geometry_only"))
    layout_widget, layout_choices = window._combo_fields["layout_name"]
    layout_widget.model.set_value(layout_choices.index("mono"))
    ambiguity_widget, ambiguity_choices = window._combo_fields["ambiguity_policy"]
    ambiguity_widget.model.set_value(len(ambiguity_choices) - 1)
    window._bool_fields["debug_overlay_enabled"].model.set_value(False)
    window._bool_fields["occlusion_enabled"].model.set_value(True)
    window._bool_fields["trace_enabled"].model.set_value(True)
    window._bool_fields["replicator_enabled"].model.set_value(True)
    window.sync_state_from_widgets()

    assert controller.state.source_id == "edited_source"
    assert controller.state.source_duration_s == 60.0
    assert controller.state.source_position_y_m == 2.0
    assert controller.state.source_local_offset_z_m == 0.75
    assert controller.state.object_prim_path == "/World/EditedObject"
    assert controller.state.sample_rate_hz == 44100
    assert controller.state.backend == "geometry_only"
    assert controller.state.layout_name == "mono"
    assert controller.state.debug_overlay_enabled is False
    assert controller.state.occlusion_enabled is True
    assert controller.state.replicator_enabled is True

    path = controller.export_config_summary()
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["array"]["sample_rate_hz"] == 44100
    assert summary["array"]["prim_path"] == "/World/EditedArray"
    assert summary["array"]["layout_name"] == "mono"
    assert summary["source"]["source_id"] == "edited_source"
    assert summary["source"]["prim_path"] == "/World/EditedSource"
    assert summary["source"]["duration_s"] == 60.0
    assert summary["source"]["position_world"] == [0.0, 2.0, 0.5]
    assert summary["source"]["local_offset_m"] == [0.25, 0.5, 0.75]
    assert summary["object_binding"]["selected_object_prim_path"] == (
        "/World/EditedObject"
    )
    assert summary["object_binding"]["source_local_offset_m"] == [0.25, 0.5, 0.75]
    assert summary["backend"] == "geometry_only"
    assert summary["lifecycle"]["debug_overlay_enabled"] is False
    assert summary["lifecycle"]["occlusion_enabled"] is True
    assert summary["recording"]["package_jsonl"]["enabled"] is True
    assert summary["recording"]["replicator"]["enabled"] is True

    imported = ExtensionController()
    assert imported.build_ui_if_available() is not None
    imported_window = imported._lifecycle._ui_window
    assert imported_window is not None
    assert imported.import_config_summary(path) == path
    imported_window.push_state_to_widgets()
    imported_window.sync_state_from_widgets()

    assert imported.state.backend == "geometry_only"
    assert imported.state.layout_name == "mono"
    assert imported.state.source_id == "edited_source"
    assert imported.state.source_duration_s == 60.0
    assert imported.state.source_position_x_m == 0.0
    assert imported.state.source_position_y_m == 2.0
    assert imported.state.source_position_z_m == 0.5
    assert imported.state.source_local_offset_x_m == 0.25
    assert imported.state.source_local_offset_y_m == 0.5
    assert imported.state.source_local_offset_z_m == 0.75
    assert imported.state.sample_rate_hz == 44100
    assert imported.state.array_prim_path == "/World/EditedArray"
    assert imported.state.source_prim_path == "/World/EditedSource"
    assert imported.state.object_prim_path == "/World/EditedObject"
    assert imported.state.debug_overlay_enabled is False
    assert imported.state.occlusion_enabled is True
    assert imported.state.trace_enabled is True
    assert imported.state.replicator_enabled is True
    imported_backend_widget, _ = imported_window._combo_fields["backend"]
    imported_layout_widget, _ = imported_window._combo_fields["layout_name"]
    assert imported_backend_widget.model.value == backend_choices.index("geometry_only")
    assert imported_layout_widget.model.value == layout_choices.index("mono")
