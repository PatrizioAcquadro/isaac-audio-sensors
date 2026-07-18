"""Immutable configuration and fail-closed validation for audio effects."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import Any

from isaac_audio_sensors.core.exceptions import ConfigValidationError


class UnsupportedEffectError(ConfigValidationError):
    """Raised when a configured effect cannot be represented by a backend."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FrequencyResponsePointConfig:
    """One configured magnitude-response point."""

    frequency_hz: float | None = None
    magnitude_db: float | None = None
    phase_deg: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelResponseMicConfig:
    """Deterministic response settings for one exact microphone id."""

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
    """Per-microphone channel-response stage configuration."""

    enabled: bool = False
    microphones: Mapping[str, ChannelResponseMicConfig] | None = None

    def __post_init__(self) -> None:
        if self.microphones is not None:
            object.__setattr__(
                self,
                "microphones",
                MappingProxyType(dict(self.microphones)),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseSpectrumPointConfig:
    """One relative spectral-noise magnitude point."""

    freq_hz: float | None = None
    level_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseLevelSpecConfig:
    """Absolute full-band RMS level and optional relative spectrum."""

    level_db: float | None = None
    spectrum: tuple[NoiseSpectrumPointConfig, ...] | None = None

    def __post_init__(self) -> None:
        if self.spectrum is not None:
            object.__setattr__(self, "spectrum", tuple(self.spectrum))


@dataclass(frozen=True, slots=True, kw_only=True)
class SelfNoiseConfig:
    """Self-noise defaults and exact per-microphone overrides."""

    default: NoiseLevelSpecConfig | None = None
    microphones: Mapping[str, NoiseLevelSpecConfig] | None = None

    def __post_init__(self) -> None:
        if self.microphones is not None:
            object.__setattr__(
                self,
                "microphones",
                MappingProxyType(dict(self.microphones)),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AmbientNoiseConfig:
    """Ambient-noise level, spectrum, and common power fraction."""

    level_db: float | None = None
    spectrum: tuple[NoiseSpectrumPointConfig, ...] | None = None
    coherent_fraction: float | None = None

    def __post_init__(self) -> None:
        if self.spectrum is not None:
            object.__setattr__(self, "spectrum", tuple(self.spectrum))


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiseConfig:
    """Frozen S3.4 seeded-noise configuration."""

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
    """Stateless per-window automatic-gain-control configuration."""

    enabled: bool = False
    target_rms_dbfs: float | None = None
    attack_time_s: float | None = None
    release_time_s: float | None = None
    gain_floor_db: float | None = None
    gain_ceiling_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ElectronicsConfig:
    """Float-domain clipping, quantization, dither, and optional AGC."""

    enabled: bool = False
    full_scale: float | None = None
    bit_depth: int | None = None
    dither_enabled: bool | None = None
    agc: AgcConfig | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityFrequencyPointConfig:
    """One relative waveform-directivity magnitude point."""

    freq_hz: float | None = None
    gain_db: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityPatternConfig:
    """One signed first-order polar family and optional frequency response."""

    family: str | None = None
    frequency_points: tuple[DirectivityFrequencyPointConfig, ...] | None = None

    def __post_init__(self) -> None:
        if self.frequency_points is not None:
            object.__setattr__(self, "frequency_points", tuple(self.frequency_points))


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityPatternSetConfig:
    """Default pattern plus exact entity-id overrides."""

    default: DirectivityPatternConfig | None = None
    overrides: Mapping[str, DirectivityPatternConfig] | None = None

    def __post_init__(self) -> None:
        if self.overrides is not None:
            object.__setattr__(
                self,
                "overrides",
                MappingProxyType(dict(self.overrides)),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityConfig:
    """Frozen S3.6 source/microphone waveform-directivity configuration."""

    enabled: bool = False
    source_patterns: DirectivityPatternSetConfig | None = None
    mic_patterns: DirectivityPatternSetConfig | None = None
    mode: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MotionEffectsConfig:
    """Pose-derived linear-velocity policy configuration."""

    derive_velocity_from_poses: bool = False
    teleport_speed_threshold_mps: float = 50.0
    stale_time_s: float = 0.5
    smoothing_alpha: float | None = None
    segments_per_window: int = 1

    @property
    def enabled(self) -> bool:
        """Compatibility view of the motion activation bit."""

        return self.derive_velocity_from_poses


class _LegacyEnabledMotionEffectsConfig(MotionEffectsConfig):
    """Parser marker so the removed ``enabled`` key fails during validation."""

    __slots__ = ()

    @property
    def enabled(self) -> bool:
        return True


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectsConfig:
    """All effect stages, normalized so absent tables are disabled records."""

    channel_response: ChannelResponseConfig = ChannelResponseConfig()
    noise: NoiseConfig = NoiseConfig()
    electronics: ElectronicsConfig = ElectronicsConfig()
    directivity: DirectivityConfig = DirectivityConfig()
    motion: MotionEffectsConfig = MotionEffectsConfig()

    @property
    def all_disabled(self) -> bool:
        """Return whether the hard compatibility fast path applies."""

        return not any(
            (
                self.channel_response.enabled,
                self.noise.enabled,
                self.electronics.enabled,
                self.directivity.enabled,
                self.motion.enabled,
            )
        )


def parse_effects_config(raw: object) -> EffectsConfig:
    """Parse ``[audio.effects.*]`` mappings into immutable records."""

    if raw is None:
        return EffectsConfig()
    effects = _mapping(raw, "audio.effects")
    _reject_unknown(
        effects,
        {"channel_response", "noise", "electronics", "directivity", "motion"},
        "audio.effects",
    )
    return EffectsConfig(
        channel_response=_parse_channel_response(effects.get("channel_response")),
        noise=_parse_noise(effects.get("noise")),
        electronics=_parse_electronics(effects.get("electronics")),
        directivity=_parse_directivity(effects.get("directivity")),
        motion=_parse_motion(effects.get("motion")),
    )


def validate_effects_config(
    config: EffectsConfig,
    *,
    microphone_orders: Sequence[Sequence[str]],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None = None,
    microphone_self_noise_db: Mapping[str, float | None] | None = None,
    source_ids: Sequence[str] | None = None,
    source_orientations: Mapping[str, tuple[float, float, float, float] | None]
    | None = None,
    microphone_orientations: Mapping[str, tuple[float, float, float, float] | None]
    | None = None,
) -> None:
    """Validate effects against arrays and a concrete backend/profile envelope."""

    if not isinstance(config, EffectsConfig):
        raise ConfigValidationError(
            "audio.effects must normalize to EffectsConfig; received "
            f"{type(config).__name__} for backend {backend_id!r}, profile "
            f"{runtime_profile!r}."
        )
    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        raise ConfigValidationError(
            "audio.effects sample_rate_hz must be a positive integer; received "
            f"{sample_rate_hz!r} for backend {backend_id!r}, profile "
            f"{runtime_profile!r}."
        )
    orders = tuple(tuple(order) for order in microphone_orders)
    if not orders or any(not order for order in orders):
        raise ConfigValidationError(
            "audio.effects requires a selected non-empty microphone array; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    for order in orders:
        if len(set(order)) != len(order):
            raise ConfigValidationError(
                "audio.effects selected array contains duplicate microphone ids "
                f"after normalization: {order!r}; backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )

    response = config.channel_response
    if type(response.enabled) is not bool:
        raise ConfigValidationError(
            "audio.effects.channel_response.enabled must be a bool; received "
            f"{response.enabled!r}."
        )
    microphones = response.microphones
    if microphones is not None:
        if not isinstance(microphones, Mapping):
            raise ConfigValidationError(
                "audio.effects.channel_response.microphones must be a mapping; "
                f"received {type(microphones).__name__}."
            )
        configured_ids = tuple(microphones)
        _validate_microphone_order(configured_ids, orders, backend_id, runtime_profile)
        for mic_id, mic_config in microphones.items():
            _validate_mic_config(
                mic_id,
                mic_config,
                sample_rate_hz=sample_rate_hz,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
                sample_count=sample_count,
            )

    _validate_noise_config(
        config.noise,
        orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
        microphone_self_noise_db=microphone_self_noise_db,
    )
    _validate_electronics_config(
        config.electronics,
        noise=config.noise,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
    )
    from isaac_audio_sensors.core.effects.directivity import (
        validate_directivity_config,
    )

    validate_directivity_config(
        config.directivity,
        microphone_orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        source_ids=source_ids,
        source_orientations=source_orientations,
        microphone_orientations=microphone_orientations,
    )
    validate_motion_effects_config(config.motion)

    segments = config.motion.segments_per_window
    if segments > 1:
        if not config.motion.derive_velocity_from_poses:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires "
                "derive_velocity_from_poses=true."
            )
        if backend_id not in {"room_acoustics", "room_acoustics_srp"}:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 is unsupported by "
                f"backend {backend_id!r}; use room_acoustics or "
                "room_acoustics_srp."
            )
        if runtime_profile != "waveform_fidelity":
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires runtime "
                "profile 'waveform_fidelity'."
            )
        if sample_count is not None and segments > sample_count:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window must be no greater "
                f"than window_sample_count={sample_count}; received {segments}."
            )

    if response.enabled:
        for mic_id, mic_config in (microphones or {}).items():
            if mic_config.frequency_response is not None and (
                backend_id in {"geometry_only", "tdoa_synthetic"}
                or runtime_profile != "waveform_fidelity"
            ):
                raise UnsupportedEffectError(
                    "audio.effects.channel_response.microphones."
                    f"{mic_id}.frequency_response is waveform-only and unsupported "
                    f"by backend {backend_id!r} at profile {runtime_profile!r}; "
                    "supported envelope is metadata gain/delay/polarity on L0/L1 "
                    "or magnitude response on an L2/L3 waveform backend."
                )


def _parse_channel_response(raw: object) -> ChannelResponseConfig:
    if raw is None:
        return ChannelResponseConfig()
    table = _mapping(raw, "audio.effects.channel_response")
    _reject_unknown(table, {"enabled", "microphones"}, "audio.effects.channel_response")
    enabled = _bool(
        table.get("enabled", False),
        "audio.effects.channel_response.enabled",
    )
    raw_microphones = table.get("microphones")
    if raw_microphones is None:
        microphones = None
    else:
        microphone_table = _mapping(
            raw_microphones, "audio.effects.channel_response.microphones"
        )
        normalized_ids = tuple(str(raw_mic_id) for raw_mic_id in microphone_table)
        if len(set(normalized_ids)) != len(normalized_ids):
            duplicate = next(
                mic_id
                for index, mic_id in enumerate(normalized_ids)
                if mic_id in normalized_ids[:index]
            )
            raise ConfigValidationError(
                "audio.effects.channel_response.microphones contains duplicate "
                f"id {duplicate!r} after normalization."
            )
        normalized: dict[str, ChannelResponseMicConfig] = {}
        for raw_mic_id, raw_mic in microphone_table.items():
            mic_id = str(raw_mic_id)
            if not isinstance(raw_mic_id, str) or not mic_id:
                raise ConfigValidationError(
                    "audio.effects.channel_response.microphones ids must be exact "
                    f"non-empty MicrophoneSpec.mic_id strings; received {raw_mic_id!r}."
                )
            normalized[mic_id] = _parse_mic_config(mic_id, raw_mic)
        microphones = MappingProxyType(normalized)
    return ChannelResponseConfig(enabled=enabled, microphones=microphones)


def _parse_noise(raw: object) -> NoiseConfig:
    if raw is None:
        return NoiseConfig()
    table_name = "audio.effects.noise"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {
            "enabled",
            "seed",
            "self_noise",
            "ambient",
            "clock_jitter_std_s",
            "clock_drift_ppm",
        },
        table_name,
    )
    seed = table.get("seed")
    if seed is not None and (type(seed) is not int or not -(2**63) <= seed < 2**63):
        raise ConfigValidationError(
            f"{table_name}.seed must be an exact integer in "
            f"[-2**63, 2**63 - 1]; received {seed!r}."
        )
    jitter = table.get("clock_jitter_std_s")
    if isinstance(jitter, Mapping):
        jitter = _parse_number_mapping(
            jitter,
            f"{table_name}.clock_jitter_std_s",
        )
    elif jitter is not None:
        jitter = _number(jitter, f"{table_name}.clock_jitter_std_s")
    drift_raw = table.get("clock_drift_ppm")
    drift = (
        None
        if drift_raw is None
        else _parse_number_mapping(drift_raw, f"{table_name}.clock_drift_ppm")
    )
    return NoiseConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        seed=seed,
        self_noise=_parse_self_noise(table.get("self_noise")),
        ambient=_parse_ambient_noise(table.get("ambient")),
        clock_jitter_std_s=jitter,
        clock_drift_ppm=drift,
    )


def _parse_electronics(raw: object) -> ElectronicsConfig:
    if raw is None:
        return ElectronicsConfig()
    table_name = "audio.effects.electronics"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"enabled", "full_scale", "bit_depth", "dither_enabled", "agc"},
        table_name,
    )
    bit_depth = table.get("bit_depth")
    if bit_depth is not None and type(bit_depth) is not int:
        raise ConfigValidationError(
            f"{table_name}.bit_depth must be an exact integer in [8, 32]; "
            f"received {bit_depth!r}."
        )
    dither = table.get("dither_enabled")
    if dither is not None:
        dither = _bool(dither, f"{table_name}.dither_enabled")
    return ElectronicsConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        full_scale=(
            None
            if "full_scale" not in table
            else _number(table["full_scale"], f"{table_name}.full_scale")
        ),
        bit_depth=bit_depth,
        dither_enabled=dither,
        agc=_parse_agc(table.get("agc")),
    )


def _parse_directivity(raw: object) -> DirectivityConfig:
    if raw is None:
        return DirectivityConfig()
    table_name = "audio.effects.directivity"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"enabled", "source_patterns", "mic_patterns", "mode"},
        table_name,
    )
    mode = table.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise UnsupportedEffectError(
            f"{table_name}.mode must be exactly 'per_pair_direct_path' or None; "
            f"received {mode!r}."
        )
    return DirectivityConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        source_patterns=_parse_directivity_pattern_set(
            table.get("source_patterns"),
            table=f"{table_name}.source_patterns",
            entity_label="AudioSourceSpec.source_id",
        ),
        mic_patterns=_parse_directivity_pattern_set(
            table.get("mic_patterns"),
            table=f"{table_name}.mic_patterns",
            entity_label="MicrophoneSpec.mic_id",
        ),
        mode=mode,
    )


def _parse_directivity_pattern_set(
    raw: object,
    *,
    table: str,
    entity_label: str,
) -> DirectivityPatternSetConfig | None:
    if raw is None:
        return None
    values = _mapping(raw, table)
    _reject_unknown(values, {"default", "overrides"}, table)
    overrides_raw = values.get("overrides")
    overrides: Mapping[str, DirectivityPatternConfig] | None = None
    if overrides_raw is not None:
        override_table = _mapping(overrides_raw, f"{table}.overrides")
        normalized_ids = tuple(str(raw_id) for raw_id in override_table)
        if len(set(normalized_ids)) != len(normalized_ids):
            duplicate = next(
                entity_id
                for index, entity_id in enumerate(normalized_ids)
                if entity_id in normalized_ids[:index]
            )
            raise ConfigValidationError(
                f"{table}.overrides contains duplicate id {duplicate!r} "
                "after normalization."
            )
        parsed_overrides: dict[str, DirectivityPatternConfig] = {}
        for raw_id, raw_pattern in override_table.items():
            entity_id = str(raw_id)
            if not isinstance(raw_id, str) or not entity_id:
                raise ConfigValidationError(
                    f"{table}.overrides ids must be exact non-empty {entity_label} "
                    f"strings; received {raw_id!r}."
                )
            parsed_overrides[entity_id] = _parse_directivity_pattern(
                raw_pattern,
                table=f"{table}.overrides.{entity_id}",
            )
        overrides = MappingProxyType(parsed_overrides)
    default_raw = values.get("default")
    return DirectivityPatternSetConfig(
        default=(
            None
            if default_raw is None
            else _parse_directivity_pattern(default_raw, table=f"{table}.default")
        ),
        overrides=overrides,
    )


def _parse_directivity_pattern(
    raw: object,
    *,
    table: str,
) -> DirectivityPatternConfig:
    values = _mapping(raw, table)
    _reject_unknown(values, {"family", "frequency_points"}, table)
    family = values.get("family")
    if family is not None and not isinstance(family, str):
        raise ConfigValidationError(
            f"{table}.family must be an exact case-sensitive string; received "
            f"{family!r}."
        )
    raw_points = values.get("frequency_points")
    points: tuple[DirectivityFrequencyPointConfig, ...] | None = None
    if raw_points is not None:
        if not isinstance(raw_points, (list, tuple)):
            raise ConfigValidationError(
                f"{table}.frequency_points must be a sequence of tables; "
                f"received {type(raw_points).__name__}."
            )
        parsed: list[DirectivityFrequencyPointConfig] = []
        for index, raw_point in enumerate(raw_points):
            point_table_name = f"{table}.frequency_points[{index}]"
            point = _mapping(raw_point, point_table_name)
            _reject_unknown(point, {"freq_hz", "gain_db"}, point_table_name)
            parsed.append(
                DirectivityFrequencyPointConfig(
                    freq_hz=_optional_float(
                        point.get("freq_hz"), f"{point_table_name}.freq_hz"
                    ),
                    gain_db=_optional_float(
                        point.get("gain_db"), f"{point_table_name}.gain_db"
                    ),
                )
            )
        points = tuple(parsed)
    return DirectivityPatternConfig(family=family, frequency_points=points)


def _parse_agc(raw: object) -> AgcConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.electronics.agc"
    table = _mapping(raw, table_name)
    fields = {
        "enabled",
        "target_rms_dbfs",
        "attack_time_s",
        "release_time_s",
        "gain_floor_db",
        "gain_ceiling_db",
    }
    _reject_unknown(table, fields, table_name)
    return AgcConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        target_rms_dbfs=_optional_float(
            table.get("target_rms_dbfs"), f"{table_name}.target_rms_dbfs"
        ),
        attack_time_s=_optional_float(
            table.get("attack_time_s"), f"{table_name}.attack_time_s"
        ),
        release_time_s=_optional_float(
            table.get("release_time_s"), f"{table_name}.release_time_s"
        ),
        gain_floor_db=_optional_float(
            table.get("gain_floor_db"), f"{table_name}.gain_floor_db"
        ),
        gain_ceiling_db=_optional_float(
            table.get("gain_ceiling_db"), f"{table_name}.gain_ceiling_db"
        ),
    )


def _parse_self_noise(raw: object) -> SelfNoiseConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.noise.self_noise"
    table = _mapping(raw, table_name)
    _reject_unknown(table, {"default", "microphones"}, table_name)
    microphones_raw = table.get("microphones")
    microphones: Mapping[str, NoiseLevelSpecConfig] | None = None
    if microphones_raw is not None:
        mic_table = _mapping(microphones_raw, f"{table_name}.microphones")
        microphones = _parse_mic_mapping(
            mic_table,
            table=f"{table_name}.microphones",
            value_parser=_parse_noise_level,
        )
    default_raw = table.get("default")
    return SelfNoiseConfig(
        default=(
            None
            if default_raw is None
            else _parse_noise_level(default_raw, f"{table_name}.default")
        ),
        microphones=microphones,
    )


def _parse_ambient_noise(raw: object) -> AmbientNoiseConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.noise.ambient"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"level_db", "spectrum", "coherent_fraction"},
        table_name,
    )
    return AmbientNoiseConfig(
        level_db=(
            None
            if "level_db" not in table
            else _absolute_level(table["level_db"], f"{table_name}.level_db")
        ),
        spectrum=_parse_noise_spectrum(table.get("spectrum"), table_name),
        coherent_fraction=(
            None
            if "coherent_fraction" not in table
            else _number(
                table["coherent_fraction"],
                f"{table_name}.coherent_fraction",
            )
        ),
    )


def _parse_noise_level(raw: object, table_name: str) -> NoiseLevelSpecConfig:
    table = _mapping(raw, table_name)
    _reject_unknown(table, {"level_db", "spectrum"}, table_name)
    return NoiseLevelSpecConfig(
        level_db=(
            None
            if "level_db" not in table
            else _absolute_level(table["level_db"], f"{table_name}.level_db")
        ),
        spectrum=_parse_noise_spectrum(table.get("spectrum"), table_name),
    )


def _parse_noise_spectrum(
    raw: object,
    table_name: str,
) -> tuple[NoiseSpectrumPointConfig, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise ConfigValidationError(
            f"{table_name}.spectrum must be a sequence of tables; received "
            f"{type(raw).__name__}."
        )
    points: list[NoiseSpectrumPointConfig] = []
    for index, raw_point in enumerate(raw):
        point_name = f"{table_name}.spectrum[{index}]"
        point = _mapping(raw_point, point_name)
        _reject_unknown(point, {"freq_hz", "level_db"}, point_name)
        points.append(
            NoiseSpectrumPointConfig(
                freq_hz=(
                    None
                    if "freq_hz" not in point
                    else _number(point["freq_hz"], f"{point_name}.freq_hz")
                ),
                level_db=(
                    None
                    if "level_db" not in point
                    else _number(point["level_db"], f"{point_name}.level_db")
                ),
            )
        )
    return tuple(points)


def _parse_number_mapping(raw: Mapping[Any, Any], table: str) -> Mapping[str, float]:
    return _parse_mic_mapping(raw, table=table, value_parser=_number)


def _parse_mic_mapping(
    raw: Mapping[Any, Any],
    *,
    table: str,
    value_parser: Any,
) -> Mapping[str, Any]:
    normalized_ids = tuple(str(raw_id) for raw_id in raw)
    if len(set(normalized_ids)) != len(normalized_ids):
        duplicate = next(
            mic_id
            for index, mic_id in enumerate(normalized_ids)
            if mic_id in normalized_ids[:index]
        )
        raise ConfigValidationError(
            f"{table} contains duplicate id {duplicate!r} after normalization."
        )
    values: dict[str, Any] = {}
    for raw_id, raw_value in raw.items():
        mic_id = str(raw_id)
        if not isinstance(raw_id, str) or not mic_id:
            raise ConfigValidationError(
                f"{table} ids must be exact non-empty MicrophoneSpec.mic_id "
                f"strings; received {raw_id!r}."
            )
        values[mic_id] = value_parser(raw_value, f"{table}.{mic_id}")
    return MappingProxyType(values)


def _parse_motion(raw: object) -> MotionEffectsConfig:
    if raw is None:
        return MotionEffectsConfig()
    table_name = "audio.effects.motion"
    table = _mapping(raw, table_name)
    if set(table) == {"enabled"} and table["enabled"] is True:
        return _LegacyEnabledMotionEffectsConfig()
    _reject_unknown(
        table,
        {
            "derive_velocity_from_poses",
            "teleport_speed_threshold_mps",
            "stale_time_s",
            "smoothing_alpha",
            "segments_per_window",
        },
        table_name,
    )
    return MotionEffectsConfig(
        derive_velocity_from_poses=_bool(
            table.get("derive_velocity_from_poses", False),
            f"{table_name}.derive_velocity_from_poses",
        ),
        teleport_speed_threshold_mps=_bounded_optional_float(
            table.get("teleport_speed_threshold_mps", 50.0),
            f"{table_name}.teleport_speed_threshold_mps",
            upper=100.0,
            optional=False,
        ),
        stale_time_s=_bounded_optional_float(
            table.get("stale_time_s", 0.5),
            f"{table_name}.stale_time_s",
            upper=60.0,
            optional=False,
        ),
        smoothing_alpha=_bounded_optional_float(
            table.get("smoothing_alpha"),
            f"{table_name}.smoothing_alpha",
            upper=1.0,
            optional=True,
        ),
        segments_per_window=table.get("segments_per_window", 1),
    )


def _parse_mic_config(mic_id: str, raw: object) -> ChannelResponseMicConfig:
    table_name = f"audio.effects.channel_response.microphones.{mic_id}"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"gain_db", "delay_s", "polarity", "frequency_response"},
        table_name,
    )
    response = table.get("frequency_response")
    points: tuple[FrequencyResponsePointConfig, ...] | None = None
    if response is not None:
        if not isinstance(response, (list, tuple)):
            raise ConfigValidationError(
                f"{table_name}.frequency_response must be a sequence of tables; "
                f"received {type(response).__name__}."
            )
        parsed: list[FrequencyResponsePointConfig] = []
        for index, raw_point in enumerate(response):
            point_table = _mapping(
                raw_point, f"{table_name}.frequency_response[{index}]"
            )
            _reject_unknown(
                point_table,
                {"frequency_hz", "magnitude_db", "phase_deg"},
                f"{table_name}.frequency_response[{index}]",
            )
            parsed.append(
                FrequencyResponsePointConfig(
                    frequency_hz=_optional_float(
                        point_table.get("frequency_hz"),
                        f"{table_name}.frequency_response[{index}].frequency_hz",
                    ),
                    magnitude_db=_optional_float(
                        point_table.get("magnitude_db"),
                        f"{table_name}.frequency_response[{index}].magnitude_db",
                    ),
                    phase_deg=_optional_float(
                        point_table.get("phase_deg"),
                        f"{table_name}.frequency_response[{index}].phase_deg",
                    ),
                )
            )
        points = tuple(parsed)
    polarity = table.get("polarity")
    if polarity is not None and (type(polarity) is not int or polarity not in {-1, 1}):
        raise ConfigValidationError(
            f"{table_name}.polarity must be exactly -1 or 1; received {polarity!r}."
        )
    return ChannelResponseMicConfig(
        gain_db=_optional_float(table.get("gain_db"), f"{table_name}.gain_db"),
        delay_s=_optional_float(table.get("delay_s"), f"{table_name}.delay_s"),
        polarity=polarity,
        frequency_response=points,
    )


def _parse_reserved(
    raw: object,
    *,
    table: str,
    record: type[Any],
    fields: tuple[str, ...],
) -> Any:
    if raw is None:
        return record()
    values = _mapping(raw, table)
    _reject_unknown(values, {"enabled", *fields}, table)
    kwargs = {name: _freeze(values[name]) for name in fields if name in values}
    kwargs["enabled"] = _bool(values.get("enabled", False), f"{table}.enabled")
    return record(**kwargs)


def _validate_mic_config(
    mic_id: str,
    config: ChannelResponseMicConfig,
    *,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
) -> None:
    table = f"audio.effects.channel_response.microphones.{mic_id}"
    if not isinstance(config, ChannelResponseMicConfig):
        raise ConfigValidationError(
            f"{table} must be ChannelResponseMicConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    for field_name, value in (("gain_db", config.gain_db), ("delay_s", config.delay_s)):
        if value is not None and not math.isfinite(float(value)):
            raise ConfigValidationError(
                f"{table}.{field_name} must be finite; received {value!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
    if config.polarity is not None and (
        type(config.polarity) is not int or config.polarity not in {-1, 1}
    ):
        raise ConfigValidationError(
            f"{table}.polarity must be exactly -1 or 1; received "
            f"{config.polarity!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.delay_s is not None and sample_count is not None:
        shifted_samples = math.ceil(abs(float(config.delay_s) * sample_rate_hz))
        if sample_count <= 0 or shifted_samples >= sample_count:
            raise ConfigValidationError(
                f"{table}.delay_s={config.delay_s!r} leaves no non-empty valid "
                f"region in a {sample_count}-sample window at {sample_rate_hz} Hz; "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
    points = config.frequency_response
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.frequency_response requires at least two points; received "
            f"{len(points)}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.frequency_response[{index}]"
        if point.frequency_hz is None or not math.isfinite(float(point.frequency_hz)):
            raise ConfigValidationError(
                f"{prefix}.frequency_hz must be finite and positive; received "
                f"{point.frequency_hz!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        frequency = float(point.frequency_hz)
        if frequency <= 0.0 or frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.frequency_hz={frequency!r} must be positive and strictly "
                f"increasing; backend={backend_id!r}, profile={runtime_profile!r}."
            )
        if point.magnitude_db is None or not math.isfinite(float(point.magnitude_db)):
            raise ConfigValidationError(
                f"{prefix}.magnitude_db must be finite; received "
                f"{point.magnitude_db!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        if point.phase_deg is not None:
            raise UnsupportedEffectError(
                f"{prefix}.phase_deg={point.phase_deg!r} is unsupported by the "
                "S3.3 magnitude-only linear-phase FIR; use delay_s for a supported "
                f"linear phase offset, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        previous = frequency
    nyquist = sample_rate_hz / 2.0
    if previous > nyquist:
        raise ConfigValidationError(
            f"{table}.frequency_response highest frequency {previous!r} exceeds "
            f"Nyquist {nyquist!r} at {sample_rate_hz} Hz; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


def _validate_microphone_order(
    configured_ids: tuple[str, ...],
    orders: tuple[tuple[str, ...], ...],
    backend_id: str,
    runtime_profile: str,
) -> None:
    known = {mic_id for order in orders for mic_id in order}
    unknown = tuple(mic_id for mic_id in configured_ids if mic_id not in known)
    if unknown:
        raise ConfigValidationError(
            "audio.effects.channel_response.microphones contains unknown exact "
            f"MicrophoneSpec.mic_id values {unknown!r}; configured order "
            f"{configured_ids!r}, available arrays {orders!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if configured_ids and not any(
        configured_ids == tuple(mic_id for mic_id in order if mic_id in configured_ids)
        and set(configured_ids).issubset(order)
        for order in orders
    ):
        raise ConfigValidationError(
            "audio.effects.channel_response.microphones order mismatch: configured "
            f"{configured_ids!r}, available array orders {orders!r}; backend="
            f"{backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_noise_config(
    config: NoiseConfig,
    *,
    orders: tuple[tuple[str, ...], ...],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
    microphone_self_noise_db: Mapping[str, float | None] | None,
) -> None:
    table = "audio.effects.noise"
    if not isinstance(config, NoiseConfig):
        raise ConfigValidationError(
            f"{table} must normalize to NoiseConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if config.seed is not None and (
        type(config.seed) is not int or not -(2**63) <= config.seed < 2**63
    ):
        raise ConfigValidationError(
            f"{table}.seed must be an exact integer in "
            f"[-2**63, 2**63 - 1]; received {config.seed!r}, "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and all(
        value is None
        for value in (
            config.self_noise,
            config.ambient,
            config.clock_jitter_std_s,
            config.clock_drift_ppm,
        )
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true has no configured noise contribution for "
            f"backend {backend_id!r}, profile {runtime_profile!r}."
        )

    selected_ids = tuple(dict.fromkeys(mic_id for order in orders for mic_id in order))
    self_noise = config.self_noise
    nonzero_stochastic = False
    if self_noise is not None:
        if not isinstance(self_noise, SelfNoiseConfig):
            raise ConfigValidationError(
                f"{table}.self_noise must be SelfNoiseConfig; received "
                f"{type(self_noise).__name__}."
            )
        if self_noise.default is not None:
            _validate_noise_level_spec(
                self_noise.default,
                table=f"{table}.self_noise.default",
                sample_rate_hz=sample_rate_hz,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )
        microphones = self_noise.microphones
        if microphones is not None:
            if not isinstance(microphones, Mapping):
                raise ConfigValidationError(
                    f"{table}.self_noise.microphones must be a mapping; received "
                    f"{type(microphones).__name__}."
                )
            _validate_effect_mapping_order(
                tuple(microphones),
                orders,
                table=f"{table}.self_noise.microphones",
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )
            for mic_id, level in microphones.items():
                _validate_noise_level_spec(
                    level,
                    table=f"{table}.self_noise.microphones.{mic_id}",
                    sample_rate_hz=sample_rate_hz,
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                )
        for mic_id in selected_ids:
            resolved = (microphones or {}).get(mic_id, self_noise.default)
            if resolved is not None and resolved.level_db != -math.inf:
                nonzero_stochastic = True
            elif (
                resolved is None
                and microphone_self_noise_db is not None
                and microphone_self_noise_db.get(mic_id) is not None
            ):
                metadata_level = microphone_self_noise_db[mic_id]
                _validate_absolute_level(
                    metadata_level,
                    field=(
                        f"{table}.self_noise MicrophoneSpec.self_noise_db "
                        f"fallback for {mic_id}"
                    ),
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                )
                if metadata_level != -math.inf:
                    nonzero_stochastic = True

    ambient = config.ambient
    if ambient is not None:
        if not isinstance(ambient, AmbientNoiseConfig):
            raise ConfigValidationError(
                f"{table}.ambient must be AmbientNoiseConfig; received "
                f"{type(ambient).__name__}."
            )
        _validate_noise_level_spec(
            NoiseLevelSpecConfig(
                level_db=ambient.level_db,
                spectrum=ambient.spectrum,
            ),
            table=f"{table}.ambient",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        coherent = (
            0.0 if ambient.coherent_fraction is None else ambient.coherent_fraction
        )
        _validate_finite_range(
            coherent,
            field=f"{table}.ambient.coherent_fraction",
            lower=0.0,
            upper=1.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        if ambient.level_db != -math.inf:
            nonzero_stochastic = True

    jitter = config.clock_jitter_std_s
    if isinstance(jitter, Mapping):
        _validate_effect_mapping_order(
            tuple(jitter),
            orders,
            table=f"{table}.clock_jitter_std_s",
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        jitter_values = tuple(jitter.items())
    elif jitter is None:
        jitter_values = ()
    elif isinstance(jitter, bool) or not isinstance(jitter, Real):
        raise ConfigValidationError(
            f"{table}.clock_jitter_std_s must be a scalar number or exact "
            f"per-microphone mapping; received {jitter!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    else:
        jitter_values = tuple((mic_id, jitter) for mic_id in selected_ids)
    for mic_id, value in jitter_values:
        _validate_finite_range(
            value,
            field=f"{table}.clock_jitter_std_s.{mic_id}",
            lower=0.0,
            upper=0.25,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        sigma = float(value)
        if sigma > 0.0:
            nonzero_stochastic = True
            if (
                sample_count is not None
                and sample_count > 0
                and math.ceil(6.0 * sigma * sample_rate_hz) >= sample_count
            ):
                raise ConfigValidationError(
                    f"{table}.clock_jitter_std_s.{mic_id}={value!r} violates "
                    "ceil(6 * jitter_std_s * sample_rate_hz) < sample_count for "
                    f"sample_count={sample_count}, backend={backend_id!r}, "
                    f"profile={runtime_profile!r}."
                )

    drift = config.clock_drift_ppm
    if drift is not None:
        if not isinstance(drift, Mapping):
            raise ConfigValidationError(
                f"{table}.clock_drift_ppm must be a per-microphone mapping; "
                f"received {type(drift).__name__}."
            )
        _validate_effect_mapping_order(
            tuple(drift),
            orders,
            table=f"{table}.clock_drift_ppm",
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        for mic_id, value in drift.items():
            _validate_finite_range(
                value,
                field=f"{table}.clock_drift_ppm.{mic_id}",
                lower=-1000.0,
                upper=1000.0,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )

    if (
        config.enabled
        and backend_id in {"geometry_only", "tdoa_synthetic"}
        and (self_noise is not None or ambient is not None)
    ):
        feature = "self_noise" if self_noise is not None else "ambient"
        raise UnsupportedEffectError(
            f"{table}.{feature} is waveform-only and unsupported by backend "
            f"{backend_id!r} at profile {runtime_profile!r}; supported envelope "
            "on L0/L1 is additive clock jitter/drift delay metadata."
        )
    if nonzero_stochastic and config.seed is None:
        raise ConfigValidationError(
            f"{table}.seed is required for every nonzero stochastic noise setting; "
            f"received None, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_noise_level_spec(
    config: object,
    *,
    table: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if not isinstance(config, NoiseLevelSpecConfig):
        raise ConfigValidationError(
            f"{table} must be NoiseLevelSpecConfig; received {type(config).__name__}."
        )
    _validate_absolute_level(
        config.level_db,
        field=f"{table}.level_db",
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )
    points = config.spectrum
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.spectrum requires at least two points; received {len(points)}, "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.spectrum[{index}]"
        if not isinstance(point, NoiseSpectrumPointConfig):
            raise ConfigValidationError(
                f"{prefix} must be NoiseSpectrumPointConfig; received "
                f"{type(point).__name__}."
            )
        _validate_finite_range(
            point.freq_hz,
            field=f"{prefix}.freq_hz",
            lower=0.0,
            upper=sample_rate_hz / 2.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            lower_inclusive=False,
        )
        frequency = float(point.freq_hz)
        if frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.freq_hz={frequency!r} must be strictly increasing; "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
        _validate_finite_range(
            point.level_db,
            field=f"{prefix}.level_db",
            lower=-120.0,
            upper=120.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        previous = frequency


def _validate_electronics_config(
    config: ElectronicsConfig,
    *,
    noise: NoiseConfig,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
) -> None:
    table = "audio.effects.electronics"
    if not isinstance(config, ElectronicsConfig):
        raise ConfigValidationError(
            f"{table} must normalize to ElectronicsConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if config.full_scale is not None:
        _validate_finite_range(
            config.full_scale,
            field=f"{table}.full_scale",
            lower=0.0,
            upper=float("inf"),
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            lower_inclusive=False,
        )
    if config.bit_depth is not None and (
        type(config.bit_depth) is not int or not 8 <= config.bit_depth <= 32
    ):
        raise ConfigValidationError(
            f"{table}.bit_depth must be an exact integer in [8, 32]; received "
            f"{config.bit_depth!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.dither_enabled is not None and type(config.dither_enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.dither_enabled must be a bool or None; received "
            f"{config.dither_enabled!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.enabled and (config.full_scale is None or config.bit_depth is None):
        missing = [
            name
            for name, value in (
                ("full_scale", config.full_scale),
                ("bit_depth", config.bit_depth),
            )
            if value is None
        ]
        error_type = (
            UnsupportedEffectError
            if config.full_scale is None
            and config.bit_depth is None
            and config.dither_enabled is None
            and config.agc is None
            else ConfigValidationError
        )
        raise error_type(
            f"{table}.enabled=true requires {missing!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.full_scale is not None and config.bit_depth is not None:
        step = 2.0 * float(config.full_scale) / 2**config.bit_depth
        if not math.isfinite(step) or step <= 0.0:
            raise ConfigValidationError(
                f"{table} derived quantization step must be finite and positive; "
                f"received {step!r} from full_scale={config.full_scale!r}, "
                f"bit_depth={config.bit_depth!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
    agc = config.agc
    if agc is not None:
        _validate_agc_config(
            agc,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
    if (
        config.enabled
        and config.dither_enabled
        and (type(noise.seed) is not int or not -(2**63) <= noise.seed < 2**63)
    ):
        raise ConfigValidationError(
            f"{table}.dither_enabled=true requires audio.effects.noise.seed to "
            "be an exact integer in [-2**63, 2**63 - 1]; received "
            f"{noise.seed!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and backend_id in {"geometry_only", "tdoa_synthetic"}:
        raise UnsupportedEffectError(
            f"{table}.enabled=true is waveform-only and unsupported by backend "
            f"{backend_id!r} at profile {runtime_profile!r}; electronics has no "
            "L0/L1 metadata representation."
        )
    if config.enabled and runtime_profile != "waveform_fidelity":
        raise UnsupportedEffectError(
            f"{table}.enabled=true requires runtime profile 'waveform_fidelity'; "
            f"received {runtime_profile!r} on backend {backend_id!r}."
        )
    if (
        config.enabled
        and config.agc is not None
        and config.agc.enabled
        and sample_count == 0
    ):
        raise ConfigValidationError(
            f"{table}.agc.enabled=true requires a non-empty time axis; received "
            f"sample_count=0, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_agc_config(
    config: AgcConfig,
    *,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    table = "audio.effects.electronics.agc"
    if not isinstance(config, AgcConfig):
        raise ConfigValidationError(
            f"{table} must normalize to AgcConfig; received {type(config).__name__}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    ranges = (
        ("target_rms_dbfs", config.target_rms_dbfs, -120.0, 0.0, True),
        ("attack_time_s", config.attack_time_s, 0.0, 60.0, False),
        ("release_time_s", config.release_time_s, 0.0, 60.0, False),
        ("gain_floor_db", config.gain_floor_db, -120.0, 120.0, True),
        ("gain_ceiling_db", config.gain_ceiling_db, -120.0, 120.0, True),
    )
    for name, value, lower, upper, inclusive in ranges:
        if value is not None:
            _validate_finite_range(
                value,
                field=f"{table}.{name}",
                lower=lower,
                upper=upper,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
                lower_inclusive=inclusive,
            )
    values = {
        "target_rms_dbfs": config.target_rms_dbfs,
        "attack_time_s": config.attack_time_s,
        "release_time_s": config.release_time_s,
        "gain_floor_db": config.gain_floor_db,
        "gain_ceiling_db": config.gain_ceiling_db,
    }
    if config.enabled and any(value is None for value in values.values()):
        missing = [name for name, value in values.items() if value is None]
        raise ConfigValidationError(
            f"{table}.enabled=true requires {missing!r}; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if (
        config.gain_floor_db is not None
        and config.gain_ceiling_db is not None
        and not config.gain_floor_db <= 0.0 <= config.gain_ceiling_db
    ):
        raise ConfigValidationError(
            f"{table} gain bounds must satisfy gain_floor_db <= 0.0 <= "
            f"gain_ceiling_db; received {config.gain_floor_db!r}, "
            f"{config.gain_ceiling_db!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.enabled:
        assert config.target_rms_dbfs is not None
        assert config.attack_time_s is not None
        assert config.release_time_s is not None
        assert config.gain_floor_db is not None
        assert config.gain_ceiling_db is not None
        derived = (
            10.0 ** (config.target_rms_dbfs / 20.0),
            10.0 ** (config.gain_floor_db / 20.0),
            10.0 ** (config.gain_ceiling_db / 20.0),
            math.exp(-1.0 / (config.attack_time_s * sample_rate_hz)),
            math.exp(-1.0 / (config.release_time_s * sample_rate_hz)),
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in derived) or any(
            value >= 1.0 for value in derived[-2:]
        ):
            raise ConfigValidationError(
                f"{table} derived target, gains, and coefficients must be finite "
                f"and positive, with coefficients below one; received {derived!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )


def _validate_absolute_level(
    value: object,
    *,
    field: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if value == -math.inf and isinstance(value, Real) and not isinstance(value, bool):
        return
    _validate_finite_range(
        value,
        field=field,
        lower=-300.0,
        upper=60.0,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )


def _validate_finite_range(
    value: object,
    *,
    field: str,
    lower: float,
    upper: float,
    backend_id: str,
    runtime_profile: str,
    lower_inclusive: bool = True,
) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field} must be a finite number in "
            f"{'[' if lower_inclusive else '('}{lower}, {upper}]; received "
            f"{value!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    number = float(value)
    lower_ok = number >= lower if lower_inclusive else number > lower
    if not math.isfinite(number) or not lower_ok or number > upper:
        raise ConfigValidationError(
            f"{field} must be a finite number in "
            f"{'[' if lower_inclusive else '('}{lower}, {upper}]; received "
            f"{value!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_effect_mapping_order(
    configured_ids: tuple[str, ...],
    orders: tuple[tuple[str, ...], ...],
    *,
    table: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if any(not isinstance(mic_id, str) or not mic_id for mic_id in configured_ids):
        raise ConfigValidationError(
            f"{table} ids must be exact non-empty MicrophoneSpec.mic_id strings; "
            f"received {configured_ids!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    known = {mic_id for order in orders for mic_id in order}
    unknown = tuple(mic_id for mic_id in configured_ids if mic_id not in known)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unknown exact MicrophoneSpec.mic_id values "
            f"{unknown!r}; available arrays {orders!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if configured_ids and not any(
        configured_ids == tuple(mic_id for mic_id in order if mic_id in configured_ids)
        and set(configured_ids).issubset(order)
        for order in orders
    ):
        raise ConfigValidationError(
            f"{table} order mismatch: configured {configured_ids!r}, available "
            f"array orders {orders!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


def _validate_reserved_stage(
    stage: object,
    stage_name: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    enabled = getattr(stage, "enabled", None)
    if type(enabled) is not bool:
        raise ConfigValidationError(
            f"audio.effects.{stage_name}.enabled must be a bool; received {enabled!r}."
        )
    if enabled:
        raise UnsupportedEffectError(
            f"audio.effects.{stage_name}.enabled=true is outside implemented "
            f"subphase S3.3 for backend {backend_id!r}, profile "
            f"{runtime_profile!r}; enable it only after its owning S3 contract is "
            "implemented."
        )


def validate_motion_effects_config(config: MotionEffectsConfig) -> None:
    """Validate a normalized S3.1 motion record without backend side effects."""

    table = "audio.effects.motion"
    if isinstance(config, _LegacyEnabledMotionEffectsConfig):
        raise UnsupportedEffectError(
            f"{table}.enabled=true is removed by S3.1; accepted fields are "
            "derive_velocity_from_poses, teleport_speed_threshold_mps, "
            "stale_time_s, smoothing_alpha, and segments_per_window."
        )
    if not isinstance(config, MotionEffectsConfig):
        raise ConfigValidationError(
            f"{table} must normalize to MotionEffectsConfig; received "
            f"{type(config).__name__}."
        )
    if type(config.derive_velocity_from_poses) is not bool:
        raise ConfigValidationError(
            f"{table}.derive_velocity_from_poses must be a bool; received "
            f"{config.derive_velocity_from_poses!r}."
        )
    if (
        type(config.segments_per_window) is not int
        or not 1 <= config.segments_per_window <= 64
    ):
        raise ConfigValidationError(
            f"{table}.segments_per_window must be an exact integer in [1, 64]; "
            f"received {config.segments_per_window!r}."
        )
    _validate_bounded_number(
        config.teleport_speed_threshold_mps,
        f"{table}.teleport_speed_threshold_mps",
        upper=100.0,
    )
    _validate_bounded_number(
        config.stale_time_s,
        f"{table}.stale_time_s",
        upper=60.0,
    )
    if config.smoothing_alpha is not None:
        _validate_bounded_number(
            config.smoothing_alpha,
            f"{table}.smoothing_alpha",
            upper=1.0,
        )


def _mapping(value: object, table: str) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(
            f"{table} must be a table/mapping; received {type(value).__name__}."
        )
    return value


def _reject_unknown(values: Mapping[Any, Any], allowed: set[str], table: str) -> None:
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unsupported fields {unknown}; expected a subset of "
            f"{sorted(allowed)}."
        )


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ConfigValidationError(f"{field_name} must be a bool; received {value!r}.")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )
    result = float(value)
    if not math.isfinite(result):
        raise ConfigValidationError(f"{field_name} must be finite; received {value!r}.")
    return result


def _absolute_level(value: object, field_name: str) -> float:
    if (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and float(value) == -math.inf
    ):
        return -math.inf
    return _number(value, field_name)


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        ) from exc
    if not math.isfinite(result):
        raise ConfigValidationError(f"{field_name} must be finite; received {value!r}.")
    return result


def _bounded_optional_float(
    value: object,
    field_name: str,
    *,
    upper: float,
    optional: bool,
) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )
    result = _optional_float(value, field_name)
    if result is None or result <= 0.0 or result > upper:
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )
    return result


def _validate_bounded_number(value: object, field_name: str, *, upper: float) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )
    result = float(value)
    if not math.isfinite(result) or result <= 0.0 or result > upper:
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


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
    "UnsupportedEffectError",
    "parse_effects_config",
    "validate_effects_config",
    "validate_motion_effects_config",
]
