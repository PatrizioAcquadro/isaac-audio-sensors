from __future__ import annotations

from copy import deepcopy

import pytest

from isaac_audio_sensors.core.config import build_scene_snapshot, validate_audio_config


def test_config_parses_source_velocity_and_builds_scene():
    raw = _raw_config()
    raw["sources"] = [
        {
            "source_id": "mover",
            "prim_path": "/World/Mover",
            "class_label": "Vehicle",
            "velocity_world_mps": [-10.0, 0.0, 0.0],
            "loop_count": 2,
        },
        {
            "source_id": "static",
            "prim_path": "/World/Static",
            "class_label": "Speech",
        },
    ]

    config = validate_audio_config(raw)
    scene = build_scene_snapshot(config, timestamp_ms=1234)
    by_id = {source.source_id: source for source in config.sources}

    assert scene.stage_id == "fixture"
    assert by_id["mover"].velocity_world_mps == (-10.0, 0.0, 0.0)
    assert by_id["mover"].loop_count == 2
    assert by_id["static"].velocity_world_mps is None
    assert by_id["static"].loop_count == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stage_units", "centimeters", "stage_units"),
        ("up_axis", "y", "up_axis"),
    ],
)
def test_config_validates_fixed_scene_conventions(field, value, message):
    raw = _raw_config()
    raw["scene"][field] = value

    with pytest.raises(ValueError, match=message):
        validate_audio_config(raw)


def test_config_does_not_store_fixed_scene_or_lab_configuration():
    raw = _raw_config()
    raw["scene"].update(stage_units="meters", up_axis="z")
    config = validate_audio_config(raw)

    assert not hasattr(config, "stage_units")
    assert not hasattr(config, "up_axis")
    assert not hasattr(config, "lab")


def test_config_rejects_duplicate_microphone_ids():
    raw = _raw_config()
    raw["arrays"]["rig"]["microphones"][1]["mic_id"] = "left"

    with pytest.raises(ValueError, match="Duplicate microphone id"):
        validate_audio_config(raw)


def test_tdoa_config_requires_two_microphones():
    raw = _raw_config()
    raw["audio"]["default_backend"] = "tdoa_synthetic"
    raw["arrays"]["rig"]["microphones"] = raw["arrays"]["rig"]["microphones"][:1]

    with pytest.raises(ValueError, match="requires at least two microphones"):
        validate_audio_config(raw)


def test_two_microphone_tdoa_config_requires_explicit_ambiguity_policy():
    raw = _raw_config()
    raw["audio"]["default_backend"] = "tdoa_synthetic"

    with pytest.raises(ValueError, match="ambiguity policy"):
        validate_audio_config(raw)


def _raw_config() -> dict:
    return deepcopy(
        {
            "scene": {"scene_id": "fixture"},
            "audio": {"default_backend": "geometry_only"},
            "arrays": {
                "rig": {
                    "prim_path": "/World/Rig/AudioArray",
                    "microphones": [
                        {
                            "mic_id": "left",
                            "relative_position_m": [0.0, -0.08, 0.0],
                        },
                        {
                            "mic_id": "right",
                            "relative_position_m": [0.0, 0.08, 0.0],
                        },
                    ],
                }
            },
        }
    )
