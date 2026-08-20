"""Configuration tests for the Stage 1 runtime-profile vocabulary."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from isaac_audio_sensors.core.config import load_audio_config, validate_audio_config
from isaac_audio_sensors.core.constants import (
    DEFAULT_RUNTIME_PROFILE,
    RUNTIME_PROFILES,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


def test_runtime_profile_defaults_to_current_waveform_behavior():
    raw = _minimal_raw_config()

    config = validate_audio_config(raw)

    assert DEFAULT_RUNTIME_PROFILE == "waveform_fidelity"
    assert config.runtime_profile == DEFAULT_RUNTIME_PROFILE


@pytest.mark.parametrize("profile", RUNTIME_PROFILES)
def test_known_runtime_profiles_are_accepted(profile):
    raw = _minimal_raw_config()
    raw["audio"]["runtime_profile"] = profile

    assert validate_audio_config(raw).runtime_profile == profile


def test_unknown_runtime_profile_fails_closed():
    raw = _minimal_raw_config()
    raw["audio"]["runtime_profile"] = "automatic"

    with pytest.raises(ConfigValidationError, match="audio.runtime_profile"):
        validate_audio_config(raw)


def test_training_profile_rejects_explicit_waveform_export():
    raw = _minimal_raw_config()
    raw["audio"].update(
        runtime_profile="training_features",
        write_waveforms=True,
    )

    with pytest.raises(ConfigValidationError, match="incompatible.*write_waveforms"):
        validate_audio_config(raw)


def test_demo_config_retains_existing_validated_results():
    config = load_audio_config(Path("examples/configs/isaac_audio_sensors_demo.toml"))

    assert config.runtime_profile == "waveform_fidelity"
    assert config.scene_id == "demo_audio_lab_single_source"
    assert config.default_backend == "tdoa_synthetic"
    assert config.sample_rate_hz == 48_000
    assert config.speed_of_sound_mps == 343.0
    assert config.write_waveforms is False
    assert config.waveform_dir is None
    assert config.tdoa_ambiguity_policy == "none"
    assert tuple(config.arrays) == ("rig_front", "rig_stereo")
    assert tuple(source.source_id for source in config.sources) == (
        "speaker_front_right",
        "speaker_left",
    )


def _minimal_raw_config() -> dict:
    raw = {
        "scene": {"scene_id": "runtime_profile_fixture"},
        "audio": {"default_backend": "geometry_only"},
        "arrays": {
            "array": {
                "prim_path": "/World/Array",
                "microphones": [
                    {"mic_id": "mic0", "relative_position_m": [0.0, 0.0, 0.0]}
                ],
            }
        },
    }
    return deepcopy(raw)
