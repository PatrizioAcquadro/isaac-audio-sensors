"""Public facade for audio-effects configuration parsing."""

from __future__ import annotations

from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.config.channel_response import (
    parse_channel_response,
)
from isaac_audio_sensors.core.effects.config.common import mapping, reject_unknown
from isaac_audio_sensors.core.effects.config.electronics import parse_electronics
from isaac_audio_sensors.core.effects.config.motion import parse_motion
from isaac_audio_sensors.core.effects.config.noise import parse_noise


def parse_effects_config(raw: object) -> EffectsConfig:
    """Parse ``[audio.effects.*]`` mappings into immutable records."""

    if raw is None:
        return EffectsConfig()
    effects = mapping(raw, "audio.effects")
    reject_unknown(
        effects,
        {"channel_response", "noise", "electronics", "motion"},
        "audio.effects",
    )
    return EffectsConfig(
        channel_response=parse_channel_response(effects.get("channel_response")),
        noise=parse_noise(effects.get("noise")),
        electronics=parse_electronics(effects.get("electronics")),
        motion=parse_motion(effects.get("motion")),
    )


__all__ = ["parse_effects_config"]
