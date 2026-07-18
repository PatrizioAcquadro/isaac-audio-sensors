"""Pure bounded S3.2 pose interpolation and segment division."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from isaac_audio_sensors.core.motion.pose_history import PoseHistory, Vector3


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityMotionInput:
    """Selected snapshot motion metadata for one exact entity id."""

    position_world_m: Vector3
    velocity_world_mps: Vector3 | None
    velocity_source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SegmentEntityMotion:
    """One entity's interpolated poses for a single sample segment."""

    start_position_world_m: Vector3
    end_position_world_m: Vector3
    midpoint_position_world_m: Vector3
    velocity_world_mps: Vector3 | None
    velocity_source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowMotionSegment:
    """One ordered half-open segment of a capture window."""

    index: int
    start_sample: int
    end_sample: int
    start_time_s: float
    end_time_s: float
    entities: Mapping[str, SegmentEntityMotion]

    @property
    def sample_count(self) -> int:
        return self.end_sample - self.start_sample


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowMotionPlan:
    """Complete bounded interpolation plan for one live trailing window."""

    sample_rate_hz: int
    window_sample_count: int
    segments: tuple[WindowMotionSegment, ...]


def segment_boundaries(
    window_sample_count: int,
    segments_per_window: int,
) -> tuple[int, ...]:
    """Divide samples with the longer remainder segments first."""

    if type(window_sample_count) is not int or window_sample_count <= 0:
        raise ValueError("window_sample_count must be a positive integer")
    if (
        type(segments_per_window) is not int
        or not 1 <= segments_per_window <= 64
        or segments_per_window > window_sample_count
    ):
        raise ValueError(
            "segments_per_window must be an integer in "
            f"[1, min(64, {window_sample_count})]"
        )
    quotient, remainder = divmod(window_sample_count, segments_per_window)
    boundaries = [0]
    for index in range(segments_per_window):
        boundaries.append(
            boundaries[-1] + quotient + int(index < remainder)
        )
    return tuple(boundaries)


def build_window_motion(
    pose_history: PoseHistory,
    *,
    entities: Mapping[str, EntityMotionInput],
    start_time_s: float,
    sample_rate_hz: int,
    window_sample_count: int,
    segments_per_window: int,
) -> WindowMotionPlan:
    """Build midpoint geometry from a bracketed PoseHistory endpoint pair."""

    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be a positive integer")
    boundaries = segment_boundaries(window_sample_count, segments_per_window)
    end_time_s = start_time_s + window_sample_count / sample_rate_hz
    bracket_tolerance_s = 1e-9 * max(1.0, abs(end_time_s))
    resolved: list[WindowMotionSegment] = []
    for segment_index, (start_sample, end_sample) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=True)
    ):
        length = end_sample - start_sample
        segment_start_s = start_time_s + start_sample / sample_rate_hz
        segment_end_s = start_time_s + end_sample / sample_rate_hz
        midpoint_s = (
            start_time_s
            + (start_sample + (length - 1) / 2.0) / sample_rate_hz
        )
        segment_entities: dict[str, SegmentEntityMotion] = {}
        for entity_id, entity in entities.items():
            result = pose_history.last_result(entity_id)
            if result is None:
                raise ValueError(f"entity {entity_id!r} has no pose history")
            if entity.velocity_source.startswith("none:"):
                start_position = entity.position_world_m
                end_position = entity.position_world_m
                midpoint_position = entity.position_world_m
                velocity = None
            else:
                samples = pose_history.samples(entity_id)
                if (
                    len(samples) != 2
                    or samples[0].time_s
                    > start_time_s + bracket_tolerance_s
                    or samples[1].time_s < end_time_s - bracket_tolerance_s
                ):
                    raise ValueError(
                        f"entity {entity_id!r} pose pair does not bracket trailing "
                        f"window [{start_time_s!r}, {end_time_s!r}]"
                    )
                start_position = pose_history.interpolate_position(
                    entity_id, segment_start_s
                )
                end_position = pose_history.interpolate_position(
                    entity_id, segment_end_s
                )
                midpoint_position = pose_history.interpolate_position(
                    entity_id, midpoint_s
                )
                velocity = entity.velocity_world_mps
            segment_entities[entity_id] = SegmentEntityMotion(
                start_position_world_m=start_position,
                end_position_world_m=end_position,
                midpoint_position_world_m=midpoint_position,
                velocity_world_mps=velocity,
                velocity_source=entity.velocity_source,
            )
        resolved.append(
            WindowMotionSegment(
                index=segment_index,
                start_sample=start_sample,
                end_sample=end_sample,
                start_time_s=segment_start_s,
                end_time_s=segment_end_s,
                entities=MappingProxyType(segment_entities),
            )
        )
    return WindowMotionPlan(
        sample_rate_hz=sample_rate_hz,
        window_sample_count=window_sample_count,
        segments=tuple(resolved),
    )


def motion_segment_diagnostics(
    plan: WindowMotionPlan,
    doppler_factor_by_segment: tuple[Mapping[str, float], ...],
) -> list[dict[str, object]]:
    """Serialize bounded segment metadata in deterministic plan order."""

    if len(doppler_factor_by_segment) != len(plan.segments):
        raise ValueError("doppler factor rows must match motion segments")
    rows: list[dict[str, object]] = []
    for segment, factors in zip(
        plan.segments, doppler_factor_by_segment, strict=True
    ):
        entities = {
            entity_id: {
                "start_position_world_m": entity.start_position_world_m,
                "end_position_world_m": entity.end_position_world_m,
                "mid_position_world_m": entity.midpoint_position_world_m,
                "velocity_world_mps": entity.velocity_world_mps,
                "velocity_source": entity.velocity_source,
            }
            for entity_id, entity in segment.entities.items()
        }
        rows.append(
            {
                "index": segment.index,
                "start_sample": segment.start_sample,
                "end_sample": segment.end_sample,
                "start_time_s": segment.start_time_s,
                "end_time_s": segment.end_time_s,
                "entities": entities,
                "doppler_factor_by_source": dict(factors),
            }
        )
    return rows


__all__ = [
    "EntityMotionInput",
    "SegmentEntityMotion",
    "WindowMotionPlan",
    "WindowMotionSegment",
    "build_window_motion",
    "motion_segment_diagnostics",
    "segment_boundaries",
]
