"""Motion-effects configuration parsing and validation."""

from __future__ import annotations

import math
from numbers import Real

from isaac_audio_sensors.core.effects.config import MotionEffectsConfig
from isaac_audio_sensors.core.effects.config.common import (
    boolean,
    mapping,
    number,
    optional_float,
    reject_unknown,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


def parse_motion(raw: object) -> MotionEffectsConfig:
    if raw is None:
        return MotionEffectsConfig()
    table_name = "audio.effects.motion"
    table = mapping(raw, table_name)
    reject_unknown(
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
    segments = table.get("segments_per_window", 1)
    if type(segments) is not int:
        raise ConfigValidationError(
            f"{table_name}.segments_per_window must be an exact integer; "
            f"received {segments!r}."
        )
    return MotionEffectsConfig(
        derive_velocity_from_poses=boolean(
            table.get("derive_velocity_from_poses", False),
            f"{table_name}.derive_velocity_from_poses",
        ),
        teleport_speed_threshold_mps=number(
            table.get("teleport_speed_threshold_mps", 50.0),
            f"{table_name}.teleport_speed_threshold_mps",
        ),
        stale_time_s=number(
            table.get("stale_time_s", 0.5),
            f"{table_name}.stale_time_s",
        ),
        smoothing_alpha=optional_float(
            table.get("smoothing_alpha"),
            f"{table_name}.smoothing_alpha",
        ),
        segments_per_window=segments,
    )


def validate_motion(config: MotionEffectsConfig) -> None:
    """Validate normalized motion settings without backend side effects."""

    table = "audio.effects.motion"
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
    if type(config.segments_per_window) is not int:
        raise ConfigValidationError(
            f"{table}.segments_per_window must be an exact integer; "
            f"received {config.segments_per_window!r}."
        )
    _validate_finite_number(
        config.teleport_speed_threshold_mps,
        f"{table}.teleport_speed_threshold_mps",
    )
    _validate_finite_number(config.stale_time_s, f"{table}.stale_time_s")
    if config.smoothing_alpha is not None:
        _validate_finite_number(
            config.smoothing_alpha,
            f"{table}.smoothing_alpha",
        )
    if not config.derive_velocity_from_poses and config.segments_per_window == 1:
        return
    if not 1 <= config.segments_per_window <= 64:
        raise ConfigValidationError(
            f"{table}.segments_per_window must be in [1, 64]; "
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


def _validate_finite_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
    ):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )


__all__ = ["parse_motion", "validate_motion"]
