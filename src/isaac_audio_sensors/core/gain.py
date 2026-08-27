"""Canonical scalar decibel-to-amplitude conversion."""

from __future__ import annotations

import math
from numbers import Real


def db_to_amplitude_gain(value: Real, field_name: str = "gain_db") -> float:
    """Convert a finite amplitude gain in dB to a positive finite scalar."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a real number, not a boolean.")
    gain_db = float(value)
    if not math.isfinite(gain_db):
        raise ValueError(f"{field_name} must be finite.")
    try:
        linear = 10.0 ** (gain_db / 20.0)
    except OverflowError as exc:
        raise ValueError(
            f"{field_name} is outside the supported amplitude range."
        ) from exc
    if not math.isfinite(linear) or linear <= 0.0:
        raise ValueError(
            f"{field_name} must map to a positive finite amplitude gain."
        )
    return linear


__all__ = ["db_to_amplitude_gain"]
