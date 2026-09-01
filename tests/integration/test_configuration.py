import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.kit import ExtensionController
from isaac_audio_sensors.kit.constants import OUTPUT_ROOT_ENV_VAR
from isaac_audio_sensors.kit.paths import _gui_output_root, _resolve_gui_output_path
from isaac_audio_sensors.kit.sensor_session import SensorSession
from isaac_audio_sensors.kit.state import CurrentStageContext
from tests.kit_helpers import _FakePrim, _FakeStage


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


def test_extension_controller_profile_config_roundtrip_omissions_and_errors(tmp_path):
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

    omitted = dict(summary)
    omitted.pop("sound_profiles")
    omitted_path = tmp_path / "omitted_profiles_config.json"
    omitted_path.write_text(json.dumps(omitted), encoding="utf-8")
    omitted_imported = ExtensionController()
    assert omitted_imported.import_config_summary(omitted_path) == omitted_path
    assert omitted_imported.state.selected_profile_id == "speech_generic"

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


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda payload: payload["source"].__setitem__("directivity", "unsupported"),
            "source.directivity",
        ),
        (
            lambda payload: payload["source"].__setitem__("directivity", "cardioid"),
            "source.orientation_world_quat",
        ),
        (
            lambda payload: payload["sound_profiles"]["profile_library"][0].__setitem__(
                "directivity", "unsupported"
            ),
            "SoundProfile.directivity",
        ),
    ),
)
def test_config_import_rejects_directivity_before_mutating_state(
    tmp_path,
    mutate,
    message,
):
    controller = ExtensionController()
    payload = controller.config_summary_dict()
    payload["array"]["array_id"] = "must_not_apply"
    mutate(payload)
    path = tmp_path / "invalid_directivity.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller.import_config_summary(path) is None
    assert controller.state.array_id == "rig_front"
    assert message in str(controller.state.error_message)


def test_config_import_rejects_boolean_gain_before_mutating_state(tmp_path) -> None:
    controller = ExtensionController()
    payload = controller.config_summary_dict()
    payload["array"]["array_id"] = "must_not_apply"
    payload["sound_profiles"]["profile_library"][0]["gain_db"] = True
    path = tmp_path / "invalid_gain.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller.import_config_summary(path) is None
    assert controller.state.array_id == "rig_front"
    assert "gain_db" in str(controller.state.error_message)


@pytest.mark.parametrize(
    ("environment", "message"),
    (
        (
            {
                "mode": "unsupported",
                "anchor_prim_path": None,
                "containment_tolerance_m": 0.001,
                "resolved": None,
            },
            "not supported",
        ),
        (
            {
                "mode": "anchor",
                "anchor_prim_path": None,
                "containment_tolerance_m": 0.001,
                "resolved": None,
            },
            "absolute environment prim path",
        ),
        (
            {
                "mode": "auto",
                "anchor_prim_path": None,
                "containment_tolerance_m": -0.001,
                "resolved": None,
            },
            "finite and non-negative",
        ),
    ),
)
def test_binding_v3_rejects_invalid_environment_resolution_before_mutation(
    tmp_path,
    environment,
    message,
) -> None:
    controller = ExtensionController()
    payload = controller.config_summary_dict()
    payload["array"]["array_id"] = "must_not_apply"
    payload["environment"] = environment
    path = tmp_path / "invalid_environment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller.import_config_summary(path) is None
    assert controller.state.array_id == "rig_front"
    assert message in str(controller.state.error_message)


def test_config_roundtrip_preserves_non_omni_source_orientation(tmp_path) -> None:
    controller = ExtensionController()
    controller.state.source_directivity = DirectivityPattern.FIGURE_EIGHT
    controller.state.source_orientation_world_quat = (0.0, 0.0, 1.0, 0.0)
    path = tmp_path / "directional.json"

    assert controller.export_config_summary(path) == path
    imported = ExtensionController()
    assert imported.import_config_summary(path) == path
    assert imported.state.source_directivity is DirectivityPattern.FIGURE_EIGHT
    assert imported.state.source_orientation_world_quat == (0.0, 0.0, 1.0, 0.0)


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
    controller.state.environment_resolution_mode = "manual_free_field"
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
    assert front_mic.attributes["ias:directivity"] == "omni"
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
        "schema_version": "ias.omni_extension_binding.v2",
        "backend": "geometry_only",
        "array": {"prim_path": "/World/Rig/AudioArray", "array_id": "legacy_rig"},
        "source": {"prim_path": "/World/Sources/SpeakerA"},
    }
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    legacy = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    assert legacy.import_config_summary(legacy_path) is None
    assert legacy.state.error_message is not None
    assert "ias.omni_extension_binding.v3" in legacy.state.error_message
    assert "v2 has no compatibility path" in legacy.state.error_message
    assert legacy.state.array_id == "rig_front"


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
    controller.state.environment_resolution_mode = "manual_free_field"
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
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.waveform_enabled = True
    controller.state.waveform_dir = "wavs"
    controller.state.waveform_mode = "session"

    assert controller.author_array(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    sensor = controller.sensor
    assert sensor is not None
    assert sensor.waveform_sink is sink

    assert sensor.environment.kind == "free_field"

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


def test_kit_session_accepts_analytic_occlusion() -> None:
    stage = _FakeStage(
        (_FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),)
    )
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage, ())
    )
    controller.state.backend = "analytic_acoustics"
    controller.state.environment_resolution_mode = "manual_free_field"
    controller.state.occlusion_enabled = True

    assert controller.author_array(stage=stage) is not None
    assert controller.start_sensor(stage=stage) is not None
    sensor = controller.sensor
    assert sensor is not None
    assert sensor.backend == "analytic_acoustics"
    assert sensor.occlusion_enabled is True
    controller.close_sensor()
