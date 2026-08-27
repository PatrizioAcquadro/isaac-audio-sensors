"""Pure NumPy channel-effects configuration and processing."""

from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import (
    AgcConfig,
    AmbientNoiseConfig,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    ElectronicsConfig,
    FrequencyResponsePointConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
    validate_motion_effects_config,
)

__all__ = [
    "AgcConfig",
    "AmbientNoiseConfig",
    "ChannelEffectsChain",
    "ChannelResponseConfig",
    "ChannelResponseMicConfig",
    "EffectsConfig",
    "ElectronicsConfig",
    "FrequencyResponsePointConfig",
    "MotionEffectsConfig",
    "NoiseConfig",
    "NoiseLevelSpecConfig",
    "NoiseSpectrumPointConfig",
    "SelfNoiseConfig",
    "UnsupportedEffectError",
    "parse_effects_config",
    "validate_effects_config",
    "validate_motion_effects_config",
]
