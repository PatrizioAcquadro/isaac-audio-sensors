"""Float-representation tolerance for capture-lattice motion brackets."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    build_window_motion,
)

SAMPLE_RATE_HZ = 48_000
WINDOW_SAMPLE_COUNT = 2_400
SEGMENTS_PER_WINDOW = 8
WINDOW_DURATION_S = 0.05


def test_ulp_jittered_capture_lattice_brackets_many_windows() -> None:
    history = PoseHistory()
    history.observe("source-a", 0.0, (0.0, 0.0, 0.0))
    later_window_end_count = 0

    for slot in range(128):
        sample_end_s = (slot + 1) * WINDOW_DURATION_S
        result = history.observe(
            "source-a",
            sample_end_s,
            (sample_end_s, 0.0, 0.0),
        )
        assert result.velocity_world_mps is not None

        start_time_s = slot * WINDOW_DURATION_S
        computed_end_s = (
            start_time_s + WINDOW_SAMPLE_COUNT / SAMPLE_RATE_HZ
        )
        if computed_end_s > sample_end_s:
            later_window_end_count += 1

        plan = build_window_motion(
            history,
            entities={
                "source-a": EntityMotionInput(
                    position_world_m=(sample_end_s, 0.0, 0.0),
                    velocity_world_mps=result.velocity_world_mps,
                    velocity_source="derived",
                )
            },
            start_time_s=start_time_s,
            sample_rate_hz=SAMPLE_RATE_HZ,
            window_sample_count=WINDOW_SAMPLE_COUNT,
            segments_per_window=SEGMENTS_PER_WINDOW,
        )
        assert len(plan.segments) == SEGMENTS_PER_WINDOW
        assert (
            plan.segments[-1]
            .entities["source-a"]
            .end_position_world_m[0]
            <= sample_end_s
        )

    assert later_window_end_count > 0


def test_material_pose_gap_still_rejects_window_bracket() -> None:
    history = PoseHistory()
    history.observe("source-a", 0.0, (0.0, 0.0, 0.0))
    result = history.observe(
        "source-a",
        WINDOW_DURATION_S - 1e-6,
        (1.0, 0.0, 0.0),
    )
    assert result.velocity_world_mps is not None

    with pytest.raises(ValueError, match="does not bracket trailing window"):
        build_window_motion(
            history,
            entities={
                "source-a": EntityMotionInput(
                    position_world_m=(1.0, 0.0, 0.0),
                    velocity_world_mps=result.velocity_world_mps,
                    velocity_source="derived",
                )
            },
            start_time_s=0.0,
            sample_rate_hz=SAMPLE_RATE_HZ,
            window_sample_count=WINDOW_SAMPLE_COUNT,
            segments_per_window=SEGMENTS_PER_WINDOW,
        )


@pytest.mark.parametrize(
    ("target_time_s", "expected_position"),
    [
        (math.nextafter(0.7, -math.inf), (1.0, 2.0, 3.0)),
        (math.nextafter(0.75, math.inf), (2.0, 3.0, 4.0)),
    ],
)
def test_interpolation_at_ulp_boundary_returns_endpoint_without_extrapolation(
    target_time_s: float,
    expected_position: tuple[float, float, float],
) -> None:
    history = PoseHistory()
    history.observe("source-a", 0.7, (1.0, 2.0, 3.0))
    history.observe("source-a", 0.75, (2.0, 3.0, 4.0))

    assert history.interpolate_position("source-a", target_time_s) == (
        expected_position
    )
