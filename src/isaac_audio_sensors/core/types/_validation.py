"""Shared validation helpers for public core dataclasses."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import COORDINATE_CONVENTION


def require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string.")


def require_coordinate_convention(value: str, field_name: str) -> None:
    require_non_empty(value, field_name)
    if value != COORDINATE_CONVENTION:
        raise ValueError(f"{field_name} must be {COORDINATE_CONVENTION!r}.")


def require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


def require_probability(value: float, field_name: str) -> None:
    require_finite(value, field_name)
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0.")


def require_unique_ids(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Duplicate {label} {value!r}.")
        seen.add(value)


def coerce_float_dict(
    value: dict[str, float],
    field_name: str,
    *,
    non_negative: bool = False,
) -> dict[str, float]:
    coerced: dict[str, float] = {}
    for key, raw_value in value.items():
        require_non_empty(key, f"{field_name} key")
        numeric = float(raw_value)
        require_finite(numeric, f"{field_name}[{key!r}]")
        if non_negative and numeric < 0.0:
            raise ValueError(f"{field_name}[{key!r}] must be non-negative.")
        coerced[key] = numeric
    return coerced
