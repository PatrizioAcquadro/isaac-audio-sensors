"""Received-PCM parity scoring must preserve misses and unavailable directions."""

import numpy as np
import pytest

pytest.importorskip("scipy")

from tools.validation.lab_perception import score


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
