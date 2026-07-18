"""Frozen S3.1 pure pose-history policy and estimator tests."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.motion import PoseHistory


@pytest.mark.parametrize(
    ("entity_id", "origin", "velocity"),
    [
        ("source", (1.0, -2.0, 0.5), (20.0, -7.5, 0.125)),
        ("array", (-3.0, 4.0, 1.0), (-2.0, 1.25, 0.0)),
    ],
)
def test_raw_constant_velocity_recovery_frozen_fixture(
    entity_id,
    origin,
    velocity,
):
    history = PoseHistory()
    first = history.observe(entity_id, 0.0, origin)
    assert first.velocity_world_mps is None
    assert first.reason == "first_sample"

    for step in range(1, 41):
        time_s = 0.05 * step
        position = tuple(
            origin[index] + velocity[index] * time_s for index in range(3)
        )
        result = history.observe(entity_id, time_s, position)
        assert result.reason == "derived"
        assert result.velocity_world_mps is not None
        assert max(
            abs(result.velocity_world_mps[index] - velocity[index])
            for index in range(3)
        ) <= 1e-9


def test_smoothed_constant_velocity_settles_after_exactly_40_updates():
    origin = (1.0, -2.0, 0.5)
    velocity = (20.0, -7.5, 0.125)
    history = PoseHistory(smoothing_alpha=0.5)
    history.observe("source", 0.0, origin)

    for step in range(1, 41):
        time_s = 0.05 * step
        position = tuple(
            origin[index] + velocity[index] * time_s for index in range(3)
        )
        result = history.observe("source", time_s, position)
        expected = tuple((1.0 - 0.5**step) * component for component in velocity)
        assert result.reason == "derived"
        assert result.velocity_world_mps == pytest.approx(expected, abs=1e-12)

    assert result.velocity_world_mps is not None
    assert max(
        abs(result.velocity_world_mps[index] - velocity[index])
        for index in range(3)
    ) <= 1e-9


def test_first_sample_and_duplicate_after_first_replay_exact_result():
    history = PoseHistory()
    first = history.observe("entity", -2.0, (1.0, 2.0, 3.0))
    duplicate = history.observe("entity", -2.0, (99.0, 99.0, 99.0))
    assert duplicate is first
    assert duplicate.velocity_world_mps is None
    assert duplicate.reason == "first_sample"


def test_duplicate_after_derived_does_not_append_or_advance_smoothing():
    history = PoseHistory(smoothing_alpha=0.5)
    history.observe("entity", 0.0, (0.0, 0.0, 0.0))
    derived = history.observe("entity", 0.1, (1.0, 0.0, 0.0))
    duplicate = history.observe("entity", 0.1, (100.0, 0.0, 0.0))
    following = history.observe("entity", 0.2, (2.0, 0.0, 0.0))
    assert duplicate is derived
    assert derived.velocity_world_mps == (5.0, 0.0, 0.0)
    assert following.velocity_world_mps == (7.5, 0.0, 0.0)


def test_strict_time_decrease_resets_then_recovers_from_new_anchor():
    history = PoseHistory()
    history.observe("entity", 1.0, (0.0, 0.0, 0.0))
    history.observe("entity", 1.1, (1.0, 0.0, 0.0))
    reset = history.observe("entity", 0.5, (10.0, 0.0, 0.0))
    duplicate = history.observe("entity", 0.5, (999.0, 0.0, 0.0))
    recovered = history.observe("entity", 0.6, (10.2, 0.0, 0.0))
    assert reset.velocity_world_mps is None
    assert reset.reason == "time_reset"
    assert duplicate is reset
    assert recovered.reason == "derived"
    assert recovered.velocity_world_mps == pytest.approx((2.0, 0.0, 0.0))


def test_gap_exactly_stale_boundary_is_derived():
    history = PoseHistory(stale_time_s=0.5)
    history.observe("entity", 0.0, (0.0, 0.0, 0.0))
    result = history.observe("entity", 0.5, (1.0, 0.0, 0.0))
    assert result.reason == "derived"
    assert result.velocity_world_mps == (2.0, 0.0, 0.0)


def test_gap_above_stale_boundary_precedes_teleport_and_recovers():
    history = PoseHistory(stale_time_s=0.5, teleport_speed_threshold_mps=50.0)
    history.observe("entity", 0.0, (0.0, 0.0, 0.0))
    stale = history.observe("entity", math.nextafter(0.5, math.inf), (100.0, 0.0, 0.0))
    recovered = history.observe("entity", 0.6, (100.1, 0.0, 0.0))
    assert stale.velocity_world_mps is None
    assert stale.reason == "stale_pose"
    assert recovered.reason == "derived"


def test_speed_exactly_teleport_boundary_is_derived_and_above_is_teleport():
    exact = PoseHistory(teleport_speed_threshold_mps=50.0)
    exact.observe("entity", 0.0, (0.0, 0.0, 0.0))
    boundary = exact.observe("entity", 0.1, (5.0, 0.0, 0.0))
    assert boundary.reason == "derived"
    assert boundary.velocity_world_mps == (50.0, 0.0, 0.0)

    above = PoseHistory(teleport_speed_threshold_mps=50.0)
    above.observe("entity", 0.0, (0.0, 0.0, 0.0))
    teleport = above.observe(
        "entity",
        0.1,
        (math.nextafter(5.0, math.inf), 0.0, 0.0),
    )
    recovered = above.observe("entity", 0.2, (5.1, 0.0, 0.0))
    assert teleport.velocity_world_mps is None
    assert teleport.reason == "teleport"
    assert recovered.reason == "derived"


def test_orientation_only_motion_derives_exact_zero_and_duplicate_replays_it():
    history = PoseHistory()
    history.observe("entity", 0.0, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0))
    derived = history.observe(
        "entity", 0.1, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0, 0.0)
    )
    duplicate = history.observe(
        "entity", 0.1, (9.0, 9.0, 9.0), (0.0, 0.0, -1.0, 0.0)
    )
    assert derived.velocity_world_mps == (0.0, 0.0, 0.0)
    assert derived.reason == "derived"
    assert duplicate is derived


def test_reset_remove_and_per_entity_state_are_isolated():
    history = PoseHistory(smoothing_alpha=0.5)
    history.observe("a", 0.0, (0.0, 0.0, 0.0))
    history.observe("b", 0.0, (10.0, 0.0, 0.0))
    history.observe("a", 0.1, (1.0, 0.0, 0.0))
    history.remove_entity("a")
    assert history.observe("a", 0.2, (2.0, 0.0, 0.0)).reason == "first_sample"
    assert history.observe("b", 0.1, (11.0, 0.0, 0.0)).reason == "derived"
    history.remove("b")
    assert history.observe("b", 0.2, (12.0, 0.0, 0.0)).reason == "first_sample"
    history.reset()
    assert history.observe("a", 0.3, (3.0, 0.0, 0.0)).reason == "first_sample"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entity_id", ""),
        ("entity_id", 1),
        ("time_s", True),
        ("time_s", float("nan")),
        ("time_s", float("inf")),
        ("position_world_m", (1.0, 2.0)),
        ("position_world_m", (1.0, float("nan"), 3.0)),
        ("position_world_m", (1.0, "bad", 3.0)),
        ("orientation_world_xyzw", (0.0, 0.0, 1.0)),
        ("orientation_world_xyzw", (0.0, 0.0, 0.0, float("inf"))),
    ],
)
def test_invalid_pose_fails_before_history_mutation(field, value):
    history = PoseHistory()
    history.observe("entity", 0.0, (0.0, 0.0, 0.0))
    kwargs = {
        "entity_id": "entity",
        "time_s": 0.1,
        "position_world_m": (1.0, 0.0, 0.0),
        "orientation_world_xyzw": None,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match="received|finite|non-empty"):
        history.observe(**kwargs)
    recovered = history.observe("entity", 0.1, (1.0, 0.0, 0.0))
    assert recovered.reason == "derived"
    assert recovered.velocity_world_mps == (10.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("teleport_speed_threshold_mps", 0.0),
        ("teleport_speed_threshold_mps", 100.0001),
        ("teleport_speed_threshold_mps", True),
        ("teleport_speed_threshold_mps", float("nan")),
        ("stale_time_s", 0.0),
        ("stale_time_s", 60.0001),
        ("stale_time_s", float("inf")),
        ("smoothing_alpha", 0.0),
        ("smoothing_alpha", 1.0001),
        ("smoothing_alpha", False),
    ],
)
def test_invalid_history_configuration_fails_closed(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError, match=field):
        PoseHistory(**kwargs)


def test_ring_capacity_is_exactly_two():
    history = PoseHistory()
    for step in range(4):
        history.observe("entity", 0.1 * step, (float(step), 0.0, 0.0))
    assert history._entities["entity"].samples.maxlen == 2
    assert len(history._entities["entity"].samples) == 2
