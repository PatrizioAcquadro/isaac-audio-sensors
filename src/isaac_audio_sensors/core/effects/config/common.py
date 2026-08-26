"""Shared parsing and validation primitives for effects configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real

from isaac_audio_sensors.core.exceptions import ConfigValidationError


def mapping(value: object, table: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(
            f"{table} must be a table/mapping; received {type(value).__name__}."
        )
    return value


def reject_unknown(
    values: Mapping[object, object], allowed: set[str], table: str
) -> None:
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unsupported fields {unknown}; expected a subset of "
            f"{sorted(allowed)}."
        )


def boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ConfigValidationError(f"{field_name} must be a bool; received {value!r}.")
    return value


def number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )
    result = float(value)
    if not math.isfinite(result):
        raise ConfigValidationError(f"{field_name} must be finite; received {value!r}.")
    return result


def absolute_level(value: object, field_name: str) -> float:
    if (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and float(value) == -math.inf
    ):
        return -math.inf
    return number(value, field_name)


def optional_float(value: object, field_name: str) -> float | None:
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


def validate_absolute_level(
    value: object,
    *,
    field: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if value == -math.inf and isinstance(value, Real) and not isinstance(value, bool):
        return
    validate_finite_range(
        value,
        field=field,
        lower=-300.0,
        upper=60.0,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )


def validate_finite_range(
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
    normalized = float(value)
    lower_ok = normalized >= lower if lower_inclusive else normalized > lower
    if not math.isfinite(normalized) or not lower_ok or normalized > upper:
        raise ConfigValidationError(
            f"{field} must be a finite number in "
            f"{'[' if lower_inclusive else '('}{lower}, {upper}]; received "
            f"{value!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def validate_mapping_order(
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
