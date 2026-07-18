"""Deterministic linear velocity estimates from timestamped world poses."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Literal, TypeAlias

Vector3: TypeAlias = tuple[float, float, float]
Quaternion: TypeAlias = tuple[float, float, float, float]
VelocityReason: TypeAlias = Literal[
    "first_sample",
    "time_reset",
    "stale_pose",
    "teleport",
    "derived",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class VelocityDerivation:
    """One tagged velocity-selection result."""

    velocity_world_mps: Vector3 | None
    reason: VelocityReason


@dataclass(frozen=True, slots=True, kw_only=True)
class PoseHistorySample:
    """Read-only public projection of one retained pose endpoint."""

    time_s: float
    position_world_m: Vector3
    orientation_world_xyzw: Quaternion | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _PoseSample:
    time_s: float
    position_world_m: Vector3
    orientation_world_xyzw: Quaternion | None


@dataclass(slots=True, kw_only=True)
class _EntityState:
    samples: deque[_PoseSample] = field(default_factory=lambda: deque(maxlen=2))
    smoothed_velocity_world_mps: Vector3 = (0.0, 0.0, 0.0)
    last_result: VelocityDerivation = field(
        default_factory=lambda: VelocityDerivation(
            velocity_world_mps=None,
            reason="first_sample",
        )
    )


class PoseHistory:
    """Per-entity two-pose history with frozen S3.1 motion policies."""

    __slots__ = (
        "smoothing_alpha",
        "stale_time_s",
        "teleport_speed_threshold_mps",
        "_entities",
    )

    def __init__(
        self,
        *,
        teleport_speed_threshold_mps: float = 50.0,
        stale_time_s: float = 0.5,
        smoothing_alpha: float | None = None,
    ) -> None:
        self.teleport_speed_threshold_mps = _bounded_finite_number(
            teleport_speed_threshold_mps,
            field_name="teleport_speed_threshold_mps",
            upper=100.0,
        )
        self.stale_time_s = _bounded_finite_number(
            stale_time_s,
            field_name="stale_time_s",
            upper=60.0,
        )
        self.smoothing_alpha = (
            None
            if smoothing_alpha is None
            else _bounded_finite_number(
                smoothing_alpha,
                field_name="smoothing_alpha",
                upper=1.0,
            )
        )
        self._entities: dict[str, _EntityState] = {}

    def observe(
        self,
        entity_id: str,
        time_s: float,
        position_world_m: Sequence[float],
        orientation_world_xyzw: Sequence[float] | None = None,
    ) -> VelocityDerivation:
        """Observe one pose and return the frozen backward-difference result."""

        sample = validate_pose_observation(
            entity_id,
            time_s,
            position_world_m,
            orientation_world_xyzw,
        )
        state = self._entities.get(entity_id)
        if state is None:
            state = _EntityState()
            state.samples.append(sample)
            state.last_result = VelocityDerivation(
                velocity_world_mps=None,
                reason="first_sample",
            )
            self._entities[entity_id] = state
            return state.last_result

        latest = state.samples[-1]
        if sample.time_s < latest.time_s:
            return self._restart_entity(entity_id, sample, reason="time_reset")
        if sample.time_s == latest.time_s:
            return state.last_result

        dt = sample.time_s - latest.time_s
        if dt > self.stale_time_s:
            return self._restart_entity(entity_id, sample, reason="stale_pose")

        raw_velocity = tuple(
            (sample.position_world_m[index] - latest.position_world_m[index]) / dt
            for index in range(3)
        )
        speed = math.sqrt(sum(component * component for component in raw_velocity))
        if speed > self.teleport_speed_threshold_mps:
            return self._restart_entity(entity_id, sample, reason="teleport")

        selected_velocity = raw_velocity
        if self.smoothing_alpha is not None:
            alpha = self.smoothing_alpha
            selected_velocity = tuple(
                alpha * raw_velocity[index]
                + (1.0 - alpha) * state.smoothed_velocity_world_mps[index]
                for index in range(3)
            )
            state.smoothed_velocity_world_mps = selected_velocity
        state.samples.append(sample)
        state.last_result = VelocityDerivation(
            velocity_world_mps=selected_velocity,
            reason="derived",
        )
        return state.last_result

    def reset(self, entity_id: str | None = None) -> None:
        """Clear all state, or only the exact named entity when supplied."""

        if entity_id is None:
            self._entities.clear()
            return
        _validate_entity_id(entity_id)
        self._entities.pop(entity_id, None)

    def remove_entity(self, entity_id: str) -> None:
        """Remove one entity's samples, smoothing tail, and last result."""

        self.reset(entity_id)

    def remove(self, entity_id: str) -> None:
        """Alias for the conceptual S3.1 ``remove(entity_id)`` interface."""

        self.remove_entity(entity_id)

    def samples(self, entity_id: str) -> tuple[PoseHistorySample, ...]:
        """Return the retained endpoints without changing estimator state."""

        _validate_entity_id(entity_id)
        state = self._entities.get(entity_id)
        if state is None:
            return ()
        return tuple(
            PoseHistorySample(
                time_s=sample.time_s,
                position_world_m=sample.position_world_m,
                orientation_world_xyzw=sample.orientation_world_xyzw,
            )
            for sample in state.samples
        )

    def last_result(self, entity_id: str) -> VelocityDerivation | None:
        """Return the latest tagged result without changing estimator state."""

        _validate_entity_id(entity_id)
        state = self._entities.get(entity_id)
        return None if state is None else state.last_result

    def interpolate_position(self, entity_id: str, time_s: float) -> Vector3:
        """Linearly interpolate a time bracketed by the retained endpoint pair."""

        _validate_entity_id(entity_id)
        target = _finite_number(time_s, f"entity {entity_id!r} time_s")
        samples = self.samples(entity_id)
        if len(samples) != 2:
            raise ValueError(
                f"entity {entity_id!r} has no two-sample pose bracket"
            )
        older, newer = samples
        bracket_tolerance_s = 1e-9 * max(1.0, abs(target))
        if (
            target < older.time_s - bracket_tolerance_s
            or target > newer.time_s + bracket_tolerance_s
        ):
            raise ValueError(
                f"entity {entity_id!r} pose pair does not bracket time {target!r}"
            )
        weight = (target - older.time_s) / (newer.time_s - older.time_s)
        weight = min(1.0, max(0.0, weight))
        return tuple(
            older.position_world_m[index]
            + weight
            * (newer.position_world_m[index] - older.position_world_m[index])
            for index in range(3)
        )

    def _restart_entity(
        self,
        entity_id: str,
        sample: _PoseSample,
        *,
        reason: Literal["time_reset", "stale_pose", "teleport"],
    ) -> VelocityDerivation:
        state = _EntityState()
        state.samples.append(sample)
        state.last_result = VelocityDerivation(
            velocity_world_mps=None,
            reason=reason,
        )
        self._entities[entity_id] = state
        return state.last_result


def validate_pose_observation(
    entity_id: str,
    time_s: float,
    position_world_m: Sequence[float],
    orientation_world_xyzw: Sequence[float] | None = None,
) -> _PoseSample:
    """Validate and normalize a pose without mutating any history."""

    _validate_entity_id(entity_id)
    normalized_time = _finite_number(time_s, f"entity {entity_id!r} time_s")
    position = _finite_vector(
        position_world_m,
        length=3,
        field_name=f"entity {entity_id!r} position_world_m",
    )
    orientation = (
        None
        if orientation_world_xyzw is None
        else _finite_vector(
            orientation_world_xyzw,
            length=4,
            field_name=f"entity {entity_id!r} orientation_world_xyzw",
        )
    )
    return _PoseSample(
        time_s=normalized_time,
        position_world_m=(position[0], position[1], position[2]),
        orientation_world_xyzw=(
            None
            if orientation is None
            else (orientation[0], orientation[1], orientation[2], orientation[3])
        ),
    )


def _validate_entity_id(entity_id: object) -> None:
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError(
            f"entity_id must be an exact non-empty string; received {entity_id!r}."
        )


def _finite_vector(
    value: object,
    *,
    length: int,
    field_name: str,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(
            f"{field_name} must contain exactly {length} finite numbers; "
            f"received {value!r}."
        )
    if len(value) != length:
        raise ValueError(
            f"{field_name} must contain exactly {length} finite numbers; "
            f"received {value!r}."
        )
    return tuple(
        _finite_number(component, f"{field_name}[{index}]")
        for index, component in enumerate(value)
    )


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be finite; received {value!r}.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite; received {value!r}.")
    return result


def _bounded_finite_number(value: object, *, field_name: str, upper: float) -> float:
    try:
        result = _finite_number(value, field_name)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        ) from exc
    if result <= 0.0 or result > upper:
        raise ValueError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )
    return result


__all__ = [
    "PoseHistorySample",
    "PoseHistory",
    "VelocityDerivation",
    "VelocityReason",
    "validate_pose_observation",
]
