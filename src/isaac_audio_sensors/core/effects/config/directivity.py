"""Directivity configuration parsing, resolution, and validation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from types import MappingProxyType

from isaac_audio_sensors.core.constants import DIRECTIVITY_COEFFICIENTS
from isaac_audio_sensors.core.effects.config import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
)
from isaac_audio_sensors.core.effects.config.common import (
    boolean,
    mapping,
    optional_float,
    reject_unknown,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.math_utils import Quaternion

PATTERN_COEFFICIENTS: Mapping[str, float] = DIRECTIVITY_COEFFICIENTS
DIRECTIVITY_MODE = "per_pair_direct_path"


def parse_directivity(raw: object) -> DirectivityConfig:
    if raw is None:
        return DirectivityConfig()
    table_name = "audio.effects.directivity"
    table = mapping(raw, table_name)
    reject_unknown(
        table,
        {"enabled", "source_patterns", "mic_patterns", "mode"},
        table_name,
    )
    mode = table.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise ConfigValidationError(
            f"{table_name}.mode must be exactly 'per_pair_direct_path' or None; "
            f"received {mode!r}."
        )
    return DirectivityConfig(
        enabled=boolean(table.get("enabled", False), f"{table_name}.enabled"),
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


def resolve_pattern(
    pattern_set: DirectivityPatternSetConfig | None,
    entity_id: str,
) -> DirectivityPatternConfig:
    """Resolve exact override, then default, then flat omni."""

    if pattern_set is not None:
        overrides = pattern_set.overrides or {}
        if entity_id in overrides:
            return overrides[entity_id]
        if pattern_set.default is not None:
            return pattern_set.default
    return DirectivityPatternConfig(family="omni")


def pattern_is_noop(pattern: DirectivityPatternConfig) -> bool:
    """Return whether a resolved pattern is exactly flat omni."""

    return pattern.family == "omni" and pattern.frequency_points is None


def validate_directivity(
    config: DirectivityConfig,
    *,
    microphone_orders: Sequence[Sequence[str]],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    source_ids: Sequence[str] | None = None,
    source_orientations: Mapping[str, Quaternion | None] | None = None,
    microphone_orientations: Mapping[str, Quaternion | None] | None = None,
) -> None:
    """Validate the frozen directivity contract without synthesis side effects."""

    table = "audio.effects.directivity"
    if not isinstance(config, DirectivityConfig):
        raise ConfigValidationError(
            f"{table} must normalize to DirectivityConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if not config.enabled:
        return
    if config.mode is not None and config.mode != DIRECTIVITY_MODE:
        raise UnsupportedEffectError(
            f"{table}.mode={config.mode!r} is unsupported; the supported "
            f"backend/profile envelope provides only {DIRECTIVITY_MODE!r}."
        )

    orders = tuple(tuple(order) for order in microphone_orders)
    normalized_source_ids = None if source_ids is None else tuple(source_ids)
    _validate_pattern_set(
        config.source_patterns,
        table=f"{table}.source_patterns",
        entity_ids=normalized_source_ids,
        entity_label="AudioSourceSpec.source_id",
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )
    mic_ids = tuple(dict.fromkeys(mic_id for order in orders for mic_id in order))
    _validate_pattern_set(
        config.mic_patterns,
        table=f"{table}.mic_patterns",
        entity_ids=mic_ids,
        entity_orders=orders,
        entity_label="MicrophoneSpec.mic_id",
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )

    if (
        config.enabled
        and config.source_patterns is None
        and config.mic_patterns is None
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true requires source_patterns or mic_patterns; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and (
        backend_id not in {"room_acoustics", "room_acoustics_srp"}
        or runtime_profile != "waveform_fidelity"
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true is waveform-only; supported envelope is "
            "room_acoustics or room_acoustics_srp with profile "
            f"'waveform_fidelity', received backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )

    if normalized_source_ids is not None:
        for source_id in normalized_source_ids:
            pattern = resolve_pattern(config.source_patterns, source_id)
            if pattern.family != "omni" and (
                source_orientations is None
                or source_orientations.get(source_id) is None
            ):
                raise ConfigValidationError(
                    f"{table}.source_patterns resolved non-omni family "
                    f"{pattern.family!r} for {source_id!r}, but "
                    "AudioSourceSpec.orientation_world_quat is missing; "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )
    if microphone_orientations is not None:
        for mic_id in mic_ids:
            pattern = resolve_pattern(config.mic_patterns, mic_id)
            if pattern.family != "omni" and microphone_orientations.get(mic_id) is None:
                raise ConfigValidationError(
                    f"{table}.mic_patterns resolved non-omni family "
                    f"{pattern.family!r} for {mic_id!r}, but the composed "
                    "microphone world orientation is missing; "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )


def _parse_directivity_pattern_set(
    raw: object,
    *,
    table: str,
    entity_label: str,
) -> DirectivityPatternSetConfig | None:
    if raw is None:
        return None
    values = mapping(raw, table)
    reject_unknown(values, {"default", "overrides"}, table)
    overrides_raw = values.get("overrides")
    overrides: Mapping[str, DirectivityPatternConfig] | None = None
    if overrides_raw is not None:
        override_table = mapping(overrides_raw, f"{table}.overrides")
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
    values = mapping(raw, table)
    reject_unknown(values, {"family", "frequency_points"}, table)
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
            point = mapping(raw_point, point_table_name)
            reject_unknown(point, {"freq_hz", "gain_db"}, point_table_name)
            parsed.append(
                DirectivityFrequencyPointConfig(
                    freq_hz=optional_float(
                        point.get("freq_hz"), f"{point_table_name}.freq_hz"
                    ),
                    gain_db=optional_float(
                        point.get("gain_db"), f"{point_table_name}.gain_db"
                    ),
                )
            )
        points = tuple(parsed)
    return DirectivityPatternConfig(family=family, frequency_points=points)


def _validate_pattern_set(
    pattern_set: DirectivityPatternSetConfig | None,
    *,
    table: str,
    entity_ids: tuple[str, ...] | None,
    entity_label: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    entity_orders: tuple[tuple[str, ...], ...] | None = None,
) -> None:
    if pattern_set is None:
        return
    if not isinstance(pattern_set, DirectivityPatternSetConfig):
        raise ConfigValidationError(
            f"{table} must be DirectivityPatternSetConfig; received "
            f"{type(pattern_set).__name__}."
        )
    if pattern_set.default is None and pattern_set.overrides is None:
        raise ConfigValidationError(
            f"{table} must contain a default or non-empty overrides mapping; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if pattern_set.default is not None:
        _validate_pattern(
            pattern_set.default,
            table=f"{table}.default",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
    overrides = pattern_set.overrides
    if overrides is None:
        return
    if not isinstance(overrides, Mapping) or not overrides:
        raise ConfigValidationError(
            f"{table}.overrides must be a non-empty mapping; received "
            f"{overrides!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    configured_ids = tuple(overrides)
    if any(
        not isinstance(entity_id, str) or not entity_id for entity_id in configured_ids
    ):
        raise ConfigValidationError(
            f"{table}.overrides ids must be exact non-empty {entity_label} strings; "
            f"received {configured_ids!r}."
        )
    if entity_ids is not None:
        unknown = tuple(
            entity_id for entity_id in configured_ids if entity_id not in entity_ids
        )
        if unknown:
            raise ConfigValidationError(
                f"{table}.overrides contains unknown exact {entity_label} values "
                f"{unknown!r}; available ids {entity_ids!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
        orders = entity_orders or (entity_ids,)
        if configured_ids and not any(
            configured_ids
            == tuple(entity_id for entity_id in order if entity_id in configured_ids)
            and set(configured_ids).issubset(order)
            for order in orders
        ):
            raise ConfigValidationError(
                f"{table}.overrides order mismatch: configured {configured_ids!r}, "
                f"available orders {orders!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
    for entity_id, pattern in overrides.items():
        _validate_pattern(
            pattern,
            table=f"{table}.overrides.{entity_id}",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )


def _validate_pattern(
    pattern: DirectivityPatternConfig,
    *,
    table: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if not isinstance(pattern, DirectivityPatternConfig):
        raise ConfigValidationError(
            f"{table} must be DirectivityPatternConfig; received "
            f"{type(pattern).__name__}."
        )
    if (
        not isinstance(pattern.family, str)
        or pattern.family not in PATTERN_COEFFICIENTS
    ):
        raise ConfigValidationError(
            f"{table}.family must be one of {tuple(PATTERN_COEFFICIENTS)!r}; "
            f"received {pattern.family!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    points = pattern.frequency_points
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.frequency_points requires at least two points; received "
            f"{len(points)}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.frequency_points[{index}]"
        if not isinstance(point, DirectivityFrequencyPointConfig):
            raise ConfigValidationError(
                f"{prefix} must be DirectivityFrequencyPointConfig; received "
                f"{type(point).__name__}."
            )
        for field_name, value in (
            ("freq_hz", point.freq_hz),
            ("gain_db", point.gain_db),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
            ):
                raise ConfigValidationError(
                    f"{prefix}.{field_name} must be finite; received {value!r}, "
                    f"backend={backend_id!r}, profile={runtime_profile!r}."
                )
        frequency = float(point.freq_hz)
        if frequency <= 0.0 or frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.freq_hz={frequency!r} must be positive and strictly "
                f"increasing; backend={backend_id!r}, profile={runtime_profile!r}."
            )
        previous = frequency
    nyquist = sample_rate_hz / 2.0
    if previous > nyquist:
        raise ConfigValidationError(
            f"{table}.frequency_points highest frequency {previous!r} exceeds "
            f"Nyquist {nyquist!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


__all__ = [
    "DIRECTIVITY_MODE",
    "PATTERN_COEFFICIENTS",
    "parse_directivity",
    "pattern_is_noop",
    "resolve_pattern",
    "validate_directivity",
]
