"""Received-PCM parity scoring must preserve misses and unavailable directions."""

import numpy as np
import pytest

pytest.importorskip("scipy")

from tools.validation.lab_perception import score


def test_matching_prioritizes_valid_edges_over_total_angle():
    from tools.validation.lab_perception import direction

    # Historical distractor_1, 2.4 s: minimum total angle chose two invalid
    # edges (48.30 + 84.80) over one valid edge (17.35 + 115.75).
    found = np.array([direction(140.51), direction(171.46)])
    truth = np.array([direction(-171.19), direction(-103.74)])
    result = score(found, truth)
    assert result["matched"] == [0]
    assert result["misses"] == result["extras"] == 1
    assert min(result["errors"]) == pytest.approx(17.35)
    assert not result["exact"]


def test_matching_maximizes_cardinality_then_minimizes_angle():
    from itertools import permutations

    from tools.validation.lab_perception import direction

    rng = np.random.default_rng(81)
    for found_count, truth_count in ((2, 3), (3, 2), (3, 3)):
        for _ in range(30):
            found = np.array([direction(a) for a in rng.uniform(-40, 40, found_count)])
            truth = np.array([direction(a) for a in rng.uniform(-40, 40, truth_count)])
            cost = np.degrees(np.arccos(np.clip(found @ truth.T, -1, 1)))
            if found_count > truth_count:
                cost = cost.T
            possibilities = [
                cost[np.arange(len(cost)), columns]
                for columns in permutations(range(cost.shape[1]), len(cost))
            ]
            best = min(possibilities, key=lambda e: (-(e <= 20).sum(), e.sum()))
            result = score(found, truth)
            assert len(result["matched"]) == (best <= 20).sum()
            assert sum(result["errors"]) == pytest.approx(best.sum())


def test_motion_scoring_requires_one_to_one_directions():
    truth = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    result = score(np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]), truth)
    assert result["count"]
    assert not result["exact"]
    assert result["misses"] == result["extras"] == 1
    assert result["matched"] == [0]
    assert max(result["errors"]) == pytest.approx(90.0)
    assert not score(np.array([[1.0, 0.0, 0.0]]), np.empty((0, 3)))["exact"]
    assert score(np.empty((0, 3)), np.empty((0, 3)))["exact"]


def test_received_reference_does_not_call_diffuse_tail_a_resolved_source():
    from tools.validation.lab_perception import assess, received_reference

    data = dict(
        received_power=np.array([[0.01, 0.01]]),
        direct_power=np.array([[0.004, 0.0001]]),
        noise_power=np.array([0.001]),
        directions=np.array([[[1.0, 0, 0], [0, 1.0, 0]]]),
        scheduled_count=np.array([0]),
    )
    reference = received_reference(data, 0)
    assert reference["present"].tolist() == [True, True]
    assert reference["direct"].tolist() == [True, False]
    result = assess(np.array([[1.0, 0, 0]]), {"status": "events"}, data, 0)
    assert result["received_count"] == 2
    assert result["unresolved_received_count"] == 1
    assert result["exact"] is None
    assert result["scheduled_count"] == 0
    unavailable = assess(
        np.empty((0, 3)),
        {"status": "unavailable"},
        {**data, "received_power": np.zeros((1, 2)), "direct_power": np.zeros((1, 2))},
        0,
    )
    assert unavailable["exact"] is False
    assert unavailable["count"] is False


def test_onset_response_is_causal_source_specific_and_segment_bounded():
    from tools.validation.lab_perception import onset_responses

    def row(t, present, matched, *, available=True):
        return dict(
            time_s=t,
            source_indices=present,
            matched_source_indices=matched,
            received_count=len(present),
            activity=bool(matched),
            available=available,
        )

    rows = [
        row(0.1, [0], [1]),  # another source is not a response
        row(0.2, [0], [0], available=False),
        row(0.3, [], [0]),  # a late estimate cannot repair the ended segment
        row(0.4, [0, 1], [1]),
        row(0.5, [0, 1], [0, 1]),
    ]
    result = onset_responses(rows, localization=True)
    assert len(result) == 3
    assert result[0]["response_delay_ms"] is None
    assert result[1]["source_index"] == 0
    assert result[1]["onset_bin_start_s"] == pytest.approx(0.3)
    assert result[1]["response_delay_ms"] == pytest.approx(200)
    assert result[2]["response_delay_ms"] == pytest.approx(100)
    activity = onset_responses(rows, localization=False)
    assert len(activity) == 2  # mixture activity, independent of source identity
    assert activity[0]["response_delay_ms"] == pytest.approx(100)


def test_unresolved_candidates_do_not_count_as_selected_directions(monkeypatch):
    from isaac_audio_sensors.core.types import DoaEstimate
    from tools.validation import lab_perception

    class AmbiguousLocalizer:
        def __init__(self, **kwargs):
            pass

        def localize(self, samples, positions, sample_rate_hz):
            return (
                (
                    DoaEstimate(
                        estimated_bearing_deg=None,
                        candidate_bearing_deg=(0.0, 180.0),
                        ambiguity_class="ambiguous_front_back",
                    ),
                ),
                {"status": "events"},
            )

    monkeypatch.setattr(lab_perception, "MaintainedEventLocalizer", AmbiguousLocalizer)
    data = dict(
        samples=np.full((2, 12800), 0.1, dtype=np.float32),
        positions=np.array([[-0.03, 0, 0], [0.03, 0, 0]]),
        received_power=np.ones((8, 1)),
        direct_power=np.ones((8, 1)),
        noise_power=np.full(8, 0.01),
        directions=np.tile([[[1.0, 0, 0]]], (8, 1, 1)),
        scheduled_count=np.ones(8),
    )
    result = lab_perception.run_stream(data)[-1]
    assert not result["exact"]
    assert result["misses"] == 1
    assert result["matched_source_indices"] == []
    assert result["ambiguity_count"] == result["unresolved_observation_count"] == 1
    assert result["detected"] == 0


def test_received_input_rejects_partial_windows_and_misaligned_truth(tmp_path):
    from tools.validation.lab_perception import load_input

    data = dict(
        samples=np.zeros((4, 12800)),
        positions=np.zeros((4, 3)),
        received_power=np.zeros((8, 1)),
        direct_power=np.zeros((8, 1)),
        noise_power=np.zeros(8),
        directions=np.tile([[[1.0, 0, 0]]], (8, 1, 1)),
        scheduled_count=np.zeros(8),
    )
    path = tmp_path / "received.npz"
    np.savez(path, **data)
    assert load_input(path)["samples"].shape == (4, 12800)
    np.savez(path, **{**data, "samples": np.zeros((4, 12801))})
    with pytest.raises(ValueError, match="aligned"):
        load_input(path)
    np.savez(path, **{**data, "directions": data["directions"][:-1]})
    with pytest.raises(ValueError, match="references"):
        load_input(path)


def test_quiet_windows_do_not_inflate_active_complete_set_rate():
    from tools.validation.lab_perception import assess, summarize

    data = dict(
        received_power=np.array([[0.0], [1.0]]),
        direct_power=np.array([[0.0], [1.0]]),
        noise_power=np.full(2, 0.01),
        directions=np.tile([[[1.0, 0, 0]]], (2, 1, 1)),
        scheduled_count=np.zeros(2),
    )
    rows = [
        {
            **assess(np.empty((0, 3)), {"status": "no_events"}, data, step),
            "compute_ms": 0.0,
            "completion_delay_ms": 0.0,
        }
        for step in range(2)
    ]
    result = summarize(rows)
    assert result["exact"] == 0.5
    assert result["active_complete_set_rate"] == 0
    assert result["active_resolvable_updates"] == 1


def test_lag_diagnostic_does_not_retime_or_repair_current_quality():
    from tools.validation.lab_perception import direction, direction_lag

    times = np.arange(1, 41) / 10
    data = {"directions": np.array([[direction(60 * t)] for t in times])}
    rows = [
        {
            **score([direction(60 * (t - 0.2))], data["directions"][i]),
            "time_s": t,
            "available": True,
            "fully_resolvable": True,
        }
        for i, t in enumerate(times)
    ]
    original = [r["time_s"] for r in rows]
    result = direction_lag(data, rows)
    assert result["fitted_lag_ms"] == 200
    assert result["current_median_error_deg"] == pytest.approx(12)
    assert result["fitted_median_error_deg"] < 1e-5
    assert [r["time_s"] for r in rows] == original
    assert rows[-1]["errors"] == pytest.approx([12])


def test_active_error_run_duration_and_frequency_exclude_quiet_windows():
    from tools.validation.lab_perception import assess, summarize

    data = dict(
        received_power=np.ones((10, 1)),
        direct_power=np.ones((10, 1)),
        noise_power=np.full(10, 0.01),
        directions=np.tile([[[1.0, 0, 0]]], (10, 1, 1)),
        scheduled_count=np.ones(10),
    )
    rows = [
        {
            **assess(np.empty((0, 3)), {"status": "no_events"}, data, step),
            "compute_ms": 0.0,
            "completion_delay_ms": 0.0,
        }
        for step in range(10)
    ]
    rows[6]["received_count"] = 0
    result = summarize(rows)
    assert result["active_incorrect_run_durations_s"] == pytest.approx([0.6, 0.3])
    assert result["active_long_error_runs"] == 1
    assert result["active_long_error_runs_per_minute"] == pytest.approx(60 / 0.9)
