from __future__ import annotations

from copy import deepcopy

import pytest

from isaac_audio_sensors.core.config import (
    build_scene_snapshot,
    load_audio_config,
    validate_audio_config,
)
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


@pytest.mark.parametrize(
    ("environment", "kind", "surface_count"),
    (
        ({"environment_id": "free", "kind": "free_field"}, "free_field", 0),
        (
            {
                "environment_id": "half",
                "kind": "half_space",
                "absorption": 0.2,
            },
            "half_space",
            1,
        ),
        (
            {
                "environment_id": "box",
                "kind": "shoebox",
                "dimensions_m": [6.0, 5.0, 3.0],
                "position_world": [1.0, 2.0, 0.5],
                "orientation_world_quat": [0.0, 0.0, 0.70710678, 0.70710678],
            },
            "shoebox",
            6,
        ),
        (
            {
                "environment_id": "prism",
                "kind": "polygon_prism",
                "floor_vertices_local_m": [
                    [0.0, 0.0, 0.0],
                    [4.0, 0.0, 0.0],
                    [4.0, 2.0, 0.0],
                    [0.0, 2.0, 0.0],
                ],
                "height_m": 3.0,
            },
            "polygon_prism",
            6,
        ),
        (
            {
                "environment_id": "surfaces",
                "kind": "surface_set",
                "surfaces": [
                    {
                        "surface_id": "floor",
                        "role": "floor",
                        "vertices_local_m": [
                            [0.0, 0.0, 0.0],
                            [2.0, 0.0, 0.0],
                            [0.0, 2.0, 0.0],
                        ],
                        "absorption": 0.4,
                    }
                ],
            },
            "surface_set",
            1,
        ),
    ),
)
def test_config_parses_all_environment_topologies(
    environment,
    kind,
    surface_count,
) -> None:
    raw = _raw_config()
    raw["environment"] = environment

    config = validate_audio_config(raw)
    scene = build_scene_snapshot(config, timestamp_ms=9)

    assert config.environment is not None
    assert config.environment.kind == kind
    assert len(config.environment.surfaces) == surface_count
    assert scene.environment == config.environment


def test_config_parses_room_acoustics_solver_settings() -> None:
    raw = _raw_config()
    raw["audio"]["default_backend"] = "room_acoustics"
    raw["audio"]["tdoa_ambiguity_policy"] = "none"
    raw["audio"]["room_acoustics"] = {
        "max_order": 4,
        "air_absorption": True,
        "ray_tracing": True,
    }
    raw["environment"] = {
        "environment_id": "box",
        "kind": "shoebox",
        "dimensions_m": [6.0, 5.0, 3.0],
    }

    config = validate_audio_config(raw)

    assert config.room_acoustics_max_order == 4
    assert config.room_acoustics_air_absorption is True
    assert config.room_acoustics_ray_tracing is True


@pytest.mark.parametrize(
    ("settings", "message"),
    (
        ({"max_order": True}, "max_order"),
        ({"max_order": -1}, "max_order"),
        ({"air_absorption": 1}, "air_absorption"),
        ({"ray_tracing": "yes"}, "ray_tracing"),
        ({"unknown": 1}, "unknown keys"),
    ),
)
def test_config_rejects_invalid_room_acoustics_solver_settings(
    settings,
    message,
) -> None:
    raw = _raw_config()
    raw["audio"]["room_acoustics"] = settings

    with pytest.raises(ConfigValidationError, match=message):
        validate_audio_config(raw)


def test_config_rejects_removed_room_table_and_environment_legacy_keys() -> None:
    raw = _raw_config()
    raw["room"] = {"room_id": "legacy", "dimensions_m": [4.0, 4.0, 3.0]}
    with pytest.raises(ConfigValidationError, match=r"\[room\] was removed"):
        validate_audio_config(raw)

    raw = _raw_config()
    raw["environment"] = {
        "environment_id": "box",
        "kind": "shoebox",
        "dimensions_m": [4.0, 4.0, 3.0],
        "out_of_bounds": "clamp",
    }
    with pytest.raises(ConfigValidationError, match="unknown keys.*out_of_bounds"):
        validate_audio_config(raw)


def test_room_backend_rejects_reserved_r8_topology() -> None:
    raw = _raw_config()
    raw["audio"]["default_backend"] = "room_acoustics"
    raw["audio"]["tdoa_ambiguity_policy"] = "none"
    raw["environment"] = {"environment_id": "free", "kind": "free_field"}

    with pytest.raises(ConfigValidationError, match="kind='shoebox'.*R7.1"):
        validate_audio_config(raw)


def test_toml_surface_set_and_nested_solver_table_round_trip(tmp_path) -> None:
    path = tmp_path / "surface_set.toml"
    path.write_text(
        """
[scene]
scene_id = "toml_surface_set"

[audio]
default_backend = "geometry_only"

[audio.room_acoustics]
max_order = 2
air_absorption = true
ray_tracing = false

[arrays.rig]
prim_path = "/World/Rig"

[[arrays.rig.microphones]]
mic_id = "left"
relative_position_m = [0.0, -0.05, 0.0]

[[arrays.rig.microphones]]
mic_id = "right"
relative_position_m = [0.0, 0.05, 0.0]

[environment]
environment_id = "open"
kind = "surface_set"

[[environment.surfaces]]
surface_id = "floor"
role = "floor"
vertices_local_m = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]]
absorption = 0.3
""",
        encoding="utf-8",
    )

    config = load_audio_config(path)

    assert config.environment is not None
    assert config.environment.kind == "surface_set"
    assert config.room_acoustics_max_order == 2
    assert config.room_acoustics_air_absorption is True
    assert config.room_acoustics_ray_tracing is False


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
