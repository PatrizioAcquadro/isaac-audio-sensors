"""Internal sample placement on a ties-to-even lattice."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeGapCursor:
    """Episode-relative placement cursor for the next candidate window."""

    origin_start_time_s: float | None = None
    expected_next_sample: int = 0
    preceding_timestamp_ms: int | None = None

    def to_dict(self) -> dict[str, float | int | None]:
        """Return checkpoint-safe scalar state."""

        return {
            "origin_start_time_s": self.origin_start_time_s,
            "expected_next_sample": self.expected_next_sample,
            "preceding_timestamp_ms": self.preceding_timestamp_ms,
        }

    @classmethod
    def from_dict(cls, value: object) -> TimeGapCursor:
        """Restore validated scalar state from a checkpoint mapping."""

        if not isinstance(value, dict):
            raise ValueError("time-gap cursor checkpoint must be an object")
        origin = value.get("origin_start_time_s")
        expected = value.get("expected_next_sample", 0)
        preceding = value.get("preceding_timestamp_ms")
        if origin is not None:
            origin = _finite_number(origin, "origin_start_time_s")
        if type(expected) is not int or expected < 0:
            raise ValueError("expected_next_sample must be a non-negative integer")
        if preceding is not None and (type(preceding) is not int or preceding < 0):
            raise ValueError(
                "preceding_timestamp_ms must be null or a non-negative integer"
            )
        return cls(
            origin_start_time_s=origin,
            expected_next_sample=expected,
            preceding_timestamp_ms=preceding,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeGapPlan:
    """Single-use placement decision supplied back to ``append_frame``."""

    placement_sequence: int
    expected_start_time_s: float | None
    incoming_start_time_s: float
    placement_sample: int
    delta_samples: int
    tolerance_samples: float
    inserted_silence_samples: int
    absorbed_drift_samples: int
    session_audio_start_sample: int

    def diagnostic(self) -> dict[str, Any]:
        """Return the exact additive frame diagnostic mapping."""

        return {
            "placement_sequence": self.placement_sequence,
            "placement_source": "frame.start_time_s",
            "expected_start_time_s": self.expected_start_time_s,
            "incoming_start_time_s": self.incoming_start_time_s,
            "placement_sample": self.placement_sample,
            "delta_samples": self.delta_samples,
            "tolerance_samples": self.tolerance_samples,
            "inserted_silence_samples": self.inserted_silence_samples,
            "absorbed_drift_samples": self.absorbed_drift_samples,
            "session_audio_start_sample": self.session_audio_start_sample,
        }


def plan_time_gap(
    cursor: TimeGapCursor,
    *,
    placement_sequence: int,
    start_time_s: Real,
    end_time_s: Real,
    timestamp_ms: int,
    sample_rate_hz: int,
    window_sample_count: int,
    hop_sample_count: int,
    session_audio_start_sample: int,
) -> TimeGapPlan:
    """Compute the frozen inclusive-tolerance placement decision once."""

    if type(placement_sequence) is not int or placement_sequence < 0:
        raise ValueError("placement_sequence must be a non-negative integer")
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        raise ValueError("timestamp_ms must be a non-negative integer")
    for name, value in (
        ("sample_rate_hz", sample_rate_hz),
        ("window_sample_count", window_sample_count),
        ("hop_sample_count", hop_sample_count),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if type(session_audio_start_sample) is not int or session_audio_start_sample < 0:
        raise ValueError("session_audio_start_sample must be a non-negative integer")
    start = _finite_real(start_time_s, "frame.start_time_s")
    end = _finite_real(end_time_s, "frame.end_time_s")
    if end <= start:
        raise ValueError("frame.end_time_s must be greater than frame.start_time_s")
    expected_timestamp = round(1000 * start)
    if timestamp_ms != expected_timestamp:
        raise ValueError(
            "timestamp_ms disagrees with round-half-even frame.start_time_s"
        )
    if round((end - start) * sample_rate_hz) != window_sample_count:
        raise ValueError(
            "frame time span disagrees with configuration.window_sample_count"
        )
    if (
        cursor.preceding_timestamp_ms is not None
        and timestamp_ms < cursor.preceding_timestamp_ms
    ):
        raise ValueError("non-monotonic timestamp within the episode")

    anchor = cursor.origin_start_time_s is None
    origin: Real = start if anchor else cursor.origin_start_time_s
    assert origin is not None
    placement_sample = 0 if anchor else round((start - origin) * sample_rate_hz)
    expected_sample = 0 if anchor else cursor.expected_next_sample
    delta_samples = placement_sample - expected_sample
    tolerance_samples = 0.1 * hop_sample_count
    if delta_samples < -tolerance_samples:
        raise ValueError("overlapping window placement exceeds drift tolerance")
    inserted = delta_samples if delta_samples > tolerance_samples else 0
    absorbed = delta_samples if abs(delta_samples) <= tolerance_samples else 0
    expected_start = (
        None if anchor else float(origin + expected_sample / sample_rate_hz)
    )
    return TimeGapPlan(
        placement_sequence=placement_sequence,
        expected_start_time_s=expected_start,
        incoming_start_time_s=float(start),
        placement_sample=placement_sample,
        delta_samples=delta_samples,
        tolerance_samples=tolerance_samples,
        inserted_silence_samples=inserted,
        absorbed_drift_samples=absorbed,
        session_audio_start_sample=(session_audio_start_sample + inserted),
    )


def advance_time_gap_cursor(
    cursor: TimeGapCursor,
    plan: TimeGapPlan,
    *,
    timestamp_ms: int,
    hop_sample_count: int,
) -> TimeGapCursor:
    """Return the phase-locked cursor after one accepted candidate."""

    origin = (
        plan.incoming_start_time_s
        if cursor.origin_start_time_s is None
        else cursor.origin_start_time_s
    )
    return TimeGapCursor(
        origin_start_time_s=origin,
        expected_next_sample=plan.placement_sample + hop_sample_count,
        preceding_timestamp_ms=timestamp_ms,
    )


def _finite_real(value: object, field_name: str) -> Real:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be finite; received {value!r}")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite; received {value!r}")
    return value


def _finite_number(value: object, field_name: str) -> float:
    return float(_finite_real(value, field_name))


__all__: list[str] = []
