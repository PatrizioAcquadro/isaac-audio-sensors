from __future__ import annotations

from copy import deepcopy

import pytest

from isaac_audio_sensors.core.config import build_scene_snapshot, validate_audio_config
from isaac_audio_sensors.core.effects import MotionEffectsConfig
from isaac_audio_sensors.core.exceptions import ConfigValidationError


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


def test_config_parses_motion_defaults_and_values():
    default = validate_audio_config(_raw_config()).effects.motion
    assert default == MotionEffectsConfig(
        derive_velocity_from_poses=False,
        teleport_speed_threshold_mps=50.0,
        stale_time_s=0.5,
        smoothing_alpha=None,
    )

    raw = _raw_config()
    raw["audio"]["effects"] = {
        "motion": {
            "derive_velocity_from_poses": True,
            "teleport_speed_threshold_mps": 75,
            "stale_time_s": 1,
            "smoothing_alpha": 0.5,
        }
    }
    assert validate_audio_config(raw).effects.motion == MotionEffectsConfig(
        derive_velocity_from_poses=True,
        teleport_speed_threshold_mps=75.0,
        stale_time_s=1.0,
        smoothing_alpha=0.5,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unknown", 1),
        ("derive_velocity_from_poses", 1),
        ("teleport_speed_threshold_mps", True),
        ("stale_time_s", float("inf")),
        ("smoothing_alpha", 1.0001),
    ],
)
def test_config_rejects_invalid_motion_values(field, value):
    raw = _raw_config()
    motion = {"derive_velocity_from_poses": True, field: value}
    raw["audio"]["effects"] = {"motion": motion}

    with pytest.raises(ConfigValidationError, match=f"audio.effects.motion.*{field}"):
        validate_audio_config(raw)


def test_motion_config_rejects_source_array_id_collision():
    raw = _raw_config()
    raw["sources"] = [
        {
            "source_id": "rig",
            "prim_path": "/World/Speaker",
            "class_label": "Speech",
        }
    ]
    raw["audio"]["effects"] = {"motion": {"derive_velocity_from_poses": True}}

    with pytest.raises(ConfigValidationError, match="collisions.*rig"):
        validate_audio_config(raw)


def test_config_rejects_duplicate_microphone_ids():
    raw = _raw_config()
    raw["arrays"]["rig"]["microphones"][1]["mic_id"] = "left"

    with pytest.raises(ValueError, match="Duplicate microphone id"):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("directivity", "orientation", "message"),
    (
        ("unsupported", [0.0, 0.0, 0.0, 1.0], "directivity"),
        ("cardioid", None, "orientation_world_quat"),
    ),
)
def test_config_rejects_invalid_or_unoriented_source_directivity(
    directivity,
    orientation,
    message,
):
    raw = _raw_config()
    source = {
        "source_id": "speaker",
        "prim_path": "/World/Speaker",
        "class_label": "Speech",
        "position_world": [2.0, 0.0, 0.0],
        "directivity": directivity,
    }
    if orientation is not None:
        source["orientation_world_quat"] = orientation
    raw["sources"] = [source]

    with pytest.raises(ValueError, match=message):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("directivity", "orientation", "message"),
    (
        ("unsupported", [0.0, 0.0, 0.0, 1.0], "directivity"),
        ("figure_eight", None, "relative_orientation_quat"),
    ),
)
def test_config_rejects_invalid_or_unoriented_microphone_directivity(
    directivity,
    orientation,
    message,
):
    raw = _raw_config()
    microphone = raw["arrays"]["rig"]["microphones"][0]
    microphone["directivity"] = directivity
    if orientation is not None:
        microphone["relative_orientation_quat"] = orientation

    with pytest.raises(ValueError, match=message):
        validate_audio_config(raw)


@pytest.mark.parametrize("entity", ("source", "microphone"))
def test_config_rejects_boolean_nominal_gain(entity: str) -> None:
    raw = _raw_config()
    if entity == "source":
        raw["sources"] = [
            {
                "source_id": "speaker",
                "prim_path": "/World/Speaker",
                "class_label": "Speech",
                "position_world": [2.0, 0.0, 0.0],
                "gain_db": True,
            }
        ]
    else:
        raw["arrays"]["rig"]["microphones"][0]["gain_db"] = True

    with pytest.raises(ValueError, match="gain_db"):
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


def test_runtime_profile_defaults_to_waveform_fidelity():
    config = validate_audio_config(_raw_config())

    assert config.runtime_profile == "waveform_fidelity"


@pytest.mark.parametrize("profile", ("training_features", "waveform_fidelity"))
def test_known_runtime_profiles_are_accepted(profile):
    raw = _raw_config()
    raw["audio"]["runtime_profile"] = profile

    assert validate_audio_config(raw).runtime_profile == profile


def test_unknown_runtime_profile_fails_closed():
    raw = _raw_config()
    raw["audio"]["runtime_profile"] = "automatic"

    with pytest.raises(ConfigValidationError, match="audio.runtime_profile"):
        validate_audio_config(raw)


def test_training_profile_rejects_waveform_export():
    raw = _raw_config()
    raw["audio"].update(
        runtime_profile="training_features",
        write_waveforms=True,
    )

    with pytest.raises(ConfigValidationError, match="incompatible.*write_waveforms"):
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
