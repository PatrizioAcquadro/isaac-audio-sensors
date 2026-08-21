"""Effects parsing and active-stage validation contracts."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.effects.config import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    ElectronicsConfig,
    NoiseConfig,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.exceptions import ConfigValidationError


def _validate(config: EffectsConfig) -> None:
    validate_effects_config(
        config,
        microphone_orders=(("front", "right"),),
        sample_rate_hz=48_000,
        backend_id="room_acoustics",
        runtime_profile="waveform_fidelity",
        sample_count=256,
    )


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"unknown": {}},
        {"noise": {"enabled": 1}},
        {"motion": {"enabled": True}},
        {"electronics": {"agc": []}},
    ],
)
def test_parser_rejects_wrong_shapes_unknown_keys_and_structural_types(raw):
    with pytest.raises(ConfigValidationError):
        parse_effects_config(raw)


def test_normalization_copies_mutable_mappings():
    microphones = {"front": ChannelResponseMicConfig(gain_db=-3.0)}
    config = ChannelResponseConfig(enabled=True, microphones=microphones)
    microphones["right"] = ChannelResponseMicConfig(gain_db=6.0)

    assert tuple(config.microphones or ()) == ("front",)


def test_disabled_stage_ranges_are_semantically_inactive():
    _validate(
        EffectsConfig(
            channel_response=ChannelResponseConfig(
                microphones={"front": ChannelResponseMicConfig(delay_s=math.inf)}
            ),
            noise=NoiseConfig(seed=2**80, clock_jitter_std_s=1.0),
            electronics=ElectronicsConfig(full_scale=-1.0, bit_depth=2),
        )
    )


@pytest.mark.parametrize(
    "config",
    [
        EffectsConfig(
            noise=NoiseConfig(enabled=True, seed=2**80, clock_jitter_std_s=1e-6)
        ),
        EffectsConfig(
            electronics=ElectronicsConfig(
                enabled=True,
                full_scale=-1.0,
                bit_depth=16,
            )
        ),
        EffectsConfig(
            channel_response=ChannelResponseConfig(
                enabled=True,
                microphones={"front": ChannelResponseMicConfig(delay_s=math.inf)},
            )
        ),
    ],
)
def test_active_stage_ranges_fail(config):
    with pytest.raises(ConfigValidationError):
        _validate(config)
