"""Pure NumPy channel-effects configuration and processing."""

from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import (
    AgcConfig,
    AmbientNoiseConfig,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    ElectronicsConfig,
    FrequencyResponsePointConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
    UnsupportedEffectError,
)

__all__ = [
    "AgcConfig",
    "AmbientNoiseConfig",
    "ChannelEffectsChain",
    "ChannelResponseConfig",
    "ChannelResponseMicConfig",
    "DirectivityConfig",
    "DirectivityFrequencyPointConfig",
    "DirectivityPatternConfig",
    "DirectivityPatternSetConfig",
    "EffectsConfig",
    "ElectronicsConfig",
    "FrequencyResponsePointConfig",
    "MotionEffectsConfig",
    "NoiseConfig",
    "NoiseLevelSpecConfig",
    "NoiseSpectrumPointConfig",
    "SelfNoiseConfig",
    "UnsupportedEffectError",
]
