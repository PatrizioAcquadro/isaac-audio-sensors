"""Evaluation must distinguish extra lobes from independently localized sources."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("soundfile")

from tools.validation.motion_localization import score


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
    from tools.validation.joint_motion import assess, received_reference

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


def test_received_evidence_preserves_public_pcm(tmp_path, monkeypatch):
    from tools.validation.motion_localization import render

    monkeypatch.chdir(tmp_path)
    args = (tmp_path, "square", "broadband", "stationary1", 0.0, 0.0, 381, [])
    observed, _, _ = render(*args, duration=0.3)
    evidence = render(*args, duration=0.3, received_evidence=True)
    np.testing.assert_array_equal(observed, evidence["samples"])
    np.testing.assert_allclose(evidence["received_power"], evidence["direct_power"])


def test_received_transitions_keep_unresolved_and_require_two_correct_updates():
    from tools.validation.joint_motion import transitions

    rows = [
        dict(
            time_s=(i + 1) / 10,
            source_indices=ids,
            exact=exact,
            completion_delay_ms=10.0,
        )
        for i, (ids, exact) in enumerate(
            [
                ([], False),
                ([], True),
                ([0], True),
                ([0], True),
                ([0, 1], False),
                ([0, 1], True),
            ]
        )
    ]
    result = transitions(rows)
    assert result[0]["response_ms"] is None
    assert result[1]["response_ms"] == pytest.approx(210.0)
    assert result[2]["response_ms"] is None


def test_occlusion_reference_keeps_noise_and_restores_received_samples(
    tmp_path, monkeypatch
):
    from tools.validation.joint_motion import render_occlusion
    from tools.validation.motion_localization import render

    monkeypatch.chdir(tmp_path)
    common = (tmp_path, "square", "broadband")
    clear = render(
        *common,
        "control_20",
        0,
        0,
        73,
        [],
        duration=4,
        received_evidence=True,
        natural_speech=True,
    )
    occluded = render_occlusion(*common, "occlusion_one", 0, 0, 73, [])
    np.testing.assert_array_equal(
        occluded["samples"][:, :16000], clear["samples"][:, :16000]
    )
    np.testing.assert_array_equal(
        occluded["samples"][:, 48000:], clear["samples"][:, 48000:]
    )
    np.testing.assert_array_equal(occluded["noise_power"], clear["noise_power"])
    np.testing.assert_allclose(
        occluded["received_power"][10:30],
        clear["received_power"][10:30] * 0.01,
        rtol=1e-5,
    )
    np.testing.assert_allclose(occluded["received_power"], occluded["direct_power"])
