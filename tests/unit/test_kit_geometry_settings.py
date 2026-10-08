"""Operating settings retain native defaults and reject corrupt saved input."""

import json
from dataclasses import asdict

import pytest

from isaac_audio_sensors.isaac.acoustic_scene import (
    GeometryAcousticsConfig,
    PRADiffuseConfig,
    SteamNLOSConfig,
)
from isaac_audio_sensors.kit.controller import ExtensionController
from isaac_audio_sensors.kit.geometry_settings import (
    GeometrySettings,
    config_from_state,
    geometry_settings,
    parse_geometry_settings,
)


def test_native_defaults_and_optional_components():
    state = GeometrySettings(
        geometry_library_path="steam", geometry_specular_library_path="pra"
    )
    assert config_from_state(state) == GeometryAcousticsConfig("steam", "pra")
    state.geometry_nlos_enabled = state.geometry_diffuse_enabled = True
    config = config_from_state(state)
    assert config.nlos == SteamNLOSConfig()
    assert config.diffuse == PRADiffuseConfig()
    assert asdict(parse_geometry_settings(geometry_settings(state))) == asdict(state)


@pytest.mark.parametrize(
    "payload",
    [
        {"nlos_enabled": "false"},
        {"diffuse_rays": True},
        {"max_delay_s": float("nan")},
        {"roots": "relative"},
        {"frame_samples": 123},
        {"diffuse_rays": 0},
        {"unknown": 1},
    ],
)
def test_invalid_saved_settings(payload):
    with pytest.raises((TypeError, ValueError)):
        parse_geometry_settings(payload)


def test_binding_roundtrip_and_legacy_defaults(tmp_path):
    controller = ExtensionController()
    state = controller.state
    state.environment_resolution_mode = "manual_free_field"
    state.geometry_library_path = "/native/steam.so"
    state.geometry_specular_library_path = "/native/pra.so"
    state.geometry_nlos_enabled = True
    state.geometry_nlos_probe_spacing_m = 0.5
    path = tmp_path / "binding.json"
    assert controller.export_config_summary(path)
    other = ExtensionController()
    assert other.import_config_summary(path), other.state.error_message
    assert geometry_settings(other.state) == geometry_settings(state)
    payload = controller.config_summary_dict()
    payload.pop("geometry_acoustics")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert other.import_config_summary(path), other.state.error_message
    assert geometry_settings(other.state) == geometry_settings(GeometrySettings())
    payload["geometry_acoustics"] = {"nlos_enabled": "false"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert other.import_config_summary(path) is None
    assert geometry_settings(other.state) == geometry_settings(GeometrySettings())
