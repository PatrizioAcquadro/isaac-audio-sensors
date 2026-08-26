"""Immutable audio-effects configuration records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True, kw_only=True)
class FrequencyResponsePointConfig:
    frequency_hz: float | None = None
    magnitude_db: float | None = None
    phase_deg: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelResponseMicConfig:
    gain_db: float | None = None
    delay_s: float | None = None
    polarity: int | None = None
    frequency_response: tuple[FrequencyResponsePointConfig, ...] | None = None

    def __post_init__(self) -> None:
        if self.frequency_response is not None:
            object.__setattr__(
                self,
                "frequency_response",
                tuple(self.frequency_response),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelResponseConfig:
    enabled: bool = False
    microphones: Mapping[str, ChannelResponseMicConfig] | None = None

    def __post_init__(self) -> None:
        if self.microphones is not None:
            object.__setattr__(
                self, "microphones", MappingProxyType(dict(self.microphones))
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseSpectrumPointConfig:
    freq_hz: float | None = None
    level_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseLevelSpecConfig:
    level_db: float | None = None
    spectrum: tuple[NoiseSpectrumPointConfig, ...] | None = None

    def __post_init__(self) -> None:
        if self.spectrum is not None:
            object.__setattr__(self, "spectrum", tuple(self.spectrum))


@dataclass(frozen=True, slots=True, kw_only=True)
class SelfNoiseConfig:
    default: NoiseLevelSpecConfig | None = None
    microphones: Mapping[str, NoiseLevelSpecConfig] | None = None

    def __post_init__(self) -> None:
        if self.microphones is not None:
            object.__setattr__(
                self, "microphones", MappingProxyType(dict(self.microphones))
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AmbientNoiseConfig:
    level_db: float | None = None
    spectrum: tuple[NoiseSpectrumPointConfig, ...] | None = None
    coherent_fraction: float | None = None

    def __post_init__(self) -> None:
        if self.spectrum is not None:
            object.__setattr__(self, "spectrum", tuple(self.spectrum))


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseConfig:
    enabled: bool = False
    seed: int | None = None
    self_noise: SelfNoiseConfig | None = None
    ambient: AmbientNoiseConfig | None = None
    clock_jitter_std_s: float | Mapping[str, float] | None = None
    clock_drift_ppm: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        for name in ("clock_jitter_std_s", "clock_drift_ppm"):
            value = getattr(self, name)
            if isinstance(value, Mapping):
                object.__setattr__(self, name, MappingProxyType(dict(value)))


@dataclass(frozen=True, slots=True, kw_only=True)
class AgcConfig:
    enabled: bool = False
    target_rms_dbfs: float | None = None
    attack_time_s: float | None = None
    release_time_s: float | None = None
    gain_floor_db: float | None = None
    gain_ceiling_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ElectronicsConfig:
    enabled: bool = False
    full_scale: float | None = None
    bit_depth: int | None = None
    dither_enabled: bool | None = None
    agc: AgcConfig | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityFrequencyPointConfig:
    freq_hz: float | None = None
    gain_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityPatternConfig:
    family: str | None = None
    frequency_points: tuple[DirectivityFrequencyPointConfig, ...] | None = None

    def __post_init__(self) -> None:
        if self.frequency_points is not None:
            object.__setattr__(self, "frequency_points", tuple(self.frequency_points))


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityPatternSetConfig:
    default: DirectivityPatternConfig | None = None
    overrides: Mapping[str, DirectivityPatternConfig] | None = None

    def __post_init__(self) -> None:
        if self.overrides is not None:
            object.__setattr__(
                self, "overrides", MappingProxyType(dict(self.overrides))
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityConfig:
    enabled: bool = False
    source_patterns: DirectivityPatternSetConfig | None = None
    mic_patterns: DirectivityPatternSetConfig | None = None
    mode: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MotionEffectsConfig:
    derive_velocity_from_poses: bool = False
    teleport_speed_threshold_mps: float = 50.0
    stale_time_s: float = 0.5
    smoothing_alpha: float | None = None
    segments_per_window: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectsConfig:
    channel_response: ChannelResponseConfig = ChannelResponseConfig()
    noise: NoiseConfig = NoiseConfig()
    electronics: ElectronicsConfig = ElectronicsConfig()
    directivity: DirectivityConfig = DirectivityConfig()
    motion: MotionEffectsConfig = MotionEffectsConfig()

    @property
    def all_disabled(self) -> bool:
        return not any(
            (
                self.channel_response.enabled,
                self.noise.enabled,
                self.electronics.enabled,
                self.directivity.enabled,
                self.motion.derive_velocity_from_poses,
            )
        )


__all__ = [
    "AgcConfig",
    "AmbientNoiseConfig",
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
]
