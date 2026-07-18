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
class NoiseConfig:
    """Reserved S3.4 configuration container; behavior is not implemented."""

    enabled: bool = False
    seed: int | None = None
    microphone: object | None = None
    ambient: object | None = None
    jitter: object | None = None
    drift: object | None = None

    def __post_init__(self) -> None:
        for name in ("microphone", "ambient", "jitter", "drift"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _freeze(value))


@dataclass(frozen=True, slots=True, kw_only=True)
class ElectronicsConfig:
    """Reserved S3.5 configuration container; behavior is not implemented."""

    enabled: bool = False
    quantization: object | None = None
    saturation: object | None = None
    agc: object | None = None

    def __post_init__(self) -> None:
        for name in ("quantization", "saturation", "agc"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _freeze(value))


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectivityConfig:
    """Reserved S3.6 configuration container; behavior is not implemented."""

    enabled: bool = False
    source_pattern: object | None = None
    microphone_pattern: object | None = None
    mode: object | None = None

    def __post_init__(self) -> None:
        for name in ("source_pattern", "microphone_pattern", "mode"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _freeze(value))


@dataclass(frozen=True, slots=True, kw_only=True)
class MotionEffectsConfig:
    """Pose-derived linear-velocity policy configuration."""

    derive_velocity_from_poses: bool = False
    teleport_speed_threshold_mps: float = 50.0
    stale_time_s: float = 0.5
    smoothing_alpha: float | None = None

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
        noise=_parse_reserved(
            effects.get("noise"),
            table="audio.effects.noise",
            record=NoiseConfig,
            fields=("seed", "microphone", "ambient", "jitter", "drift"),
        ),
        electronics=_parse_reserved(
            effects.get("electronics"),
            table="audio.effects.electronics",
            record=ElectronicsConfig,
            fields=("quantization", "saturation", "agc"),
        ),
        directivity=_parse_reserved(
            effects.get("directivity"),
            table="audio.effects.directivity",
            record=DirectivityConfig,
            fields=("source_pattern", "microphone_pattern", "mode"),
        ),
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

    _validate_reserved_stage(config.noise, "noise", backend_id, runtime_profile)
    _validate_reserved_stage(
        config.electronics, "electronics", backend_id, runtime_profile
    )
    _validate_reserved_stage(
        config.directivity, "directivity", backend_id, runtime_profile
    )
    validate_motion_effects_config(config.motion)

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


def _validate_reserved_stage(
    stage: object,
    stage_name: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    enabled = getattr(stage, "enabled", None)
    if type(enabled) is not bool:
        raise ConfigValidationError(
            f"audio.effects.{stage_name}.enabled must be a bool; received "
            f"{enabled!r}."
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
            "stale_time_s, and smoothing_alpha."
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


def _reject_unknown(
    values: Mapping[Any, Any], allowed: set[str], table: str
) -> None:
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unsupported fields {unknown}; expected a subset of "
            f"{sorted(allowed)}."
        )


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ConfigValidationError(
            f"{field_name} must be a bool; received {value!r}."
        )
    return value


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
        raise ConfigValidationError(
            f"{field_name} must be finite; received {value!r}."
        )
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
    "ChannelResponseConfig",
    "ChannelResponseMicConfig",
    "DirectivityConfig",
    "EffectsConfig",
    "ElectronicsConfig",
    "FrequencyResponsePointConfig",
    "MotionEffectsConfig",
    "NoiseConfig",
    "UnsupportedEffectError",
    "parse_effects_config",
    "validate_effects_config",
    "validate_motion_effects_config",
]
