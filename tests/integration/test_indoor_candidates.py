"""Geometry, mixture-only and evaluation contracts for isolated indoor trials."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")

from tools.qualification.doa_04_4.cases import ARRAYS, FS, match
from tools.qualification.doa_04_4.indoor_candidates import (
    DirectPathRtf,
    WeightedHistogramSrp,
)
from tools.qualification.doa_04_4.sparse_covariance import GroupSparseCovariance


@pytest.mark.parametrize("factory", (DirectPathRtf, WeightedHistogramSrp))
@pytest.mark.parametrize("array", ("triangle", "tetra"))
def test_candidates_reject_silence_and_unsupported_geometry(factory, array):
    positions = ARRAYS[array]
    silence = np.zeros((len(positions), 4000))
    silence.setflags(write=False)
    estimator = factory()
    found, diagnostic = estimator.localize(silence, positions, FS)
    assert found.shape == (0, 3)
    assert diagnostic["status"] == "no_events"
    with pytest.raises(ValueError, match="non-collinear"):
        estimator.localize(silence[:2], positions[:2], FS)


@pytest.mark.parametrize("array", ("triangle", "tetra"))
@pytest.mark.parametrize("factory", (WeightedHistogramSrp, GroupSparseCovariance))
def test_angular_histogram_has_no_two_source_cap(array, factory):
    estimator = factory()
    _, (vectors, _, _, _, _, near) = estimator.prepare(
        np.zeros((len(ARRAYS[array]), 4000)), ARRAYS[array], FS
    )
    # Include the azimuth seam and a polar direction in the spherical case.
    truth = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0]])
    if array == "tetra":
        truth[2] = [0, 0, 1]
    histogram = np.zeros(len(vectors))
    histogram[np.argmax(vectors @ truth.T, axis=0)] = 1 / 3
    found, _ = estimator.events(vectors, histogram, near, {})
    assert match(found, truth)["tp"] == 3
    assert len(found) == 3


def test_pair_matching_cannot_pass_by_returning_two_wrong_directions():
    from tools.qualification.doa_04_4.progressive import grouped

    truth = np.array([[1, 0, 0], [0, 1, 0]])
    rows = [
        dict(
            candidate="trial",
            array="triangle",
            stage="room",
            content="noise",
            count=count,
            compute_ms=1,
            **match(-truth[:count], truth[:count]),
        )
        for count in (0, 1, 2)
    ]
    protocol = dict(
        stages=[dict(name="room")],
        contents=["noise"],
        quality_reference=dict(
            minimum_precision=0.95,
            minimum_recall=0.85,
            minimum_pair_count_accuracy=0.8,
            minimum_count_accuracy=0.85,
            minimum_both_localized_without_extras=0.8,
            maximum_angular_p95_deg=15,
        ),
    )
    result = grouped(rows, protocol)["trial"]["triangle"]["room"]
    assert result["exact_pair_count"] == 1
    assert result["both_localized_without_extras"] == 0
    assert result["second_source_recall"] == 0
    assert "both_localized_without_extras" in result["below_reference"]


@pytest.mark.parametrize("rho", [0.2, 1.0, 3.0])
def test_group_solver_matches_nonnegative_orthogonal_closed_form(rho):
    from tools.qualification.doa_04_4.sparse_covariance import fit_groups

    observed = np.array([[2, -1, 0.02, 3, -2], [1, 3, 0.01, -1, 4]], dtype=float)
    dictionary = np.broadcast_to(np.eye(5), (2, 5, 5))
    expected = np.maximum(observed, 0)
    expected[:, :-2] *= np.maximum(
        1 - 0.5 / np.linalg.norm(expected[:, :-2], axis=0), 0
    )
    fitted, diagnostic = fit_groups(dictionary, observed, 0.5, rho=rho, iterations=500)
    np.testing.assert_allclose(fitted, expected, atol=5e-5)
    assert diagnostic["solver_converged"]


def test_new_speech_blocks_do_not_change_default_episode(monkeypatch):
    from tools.qualification.doa_04_4 import progressive

    seen = []

    def capture(kind, split, index, rng, length, *, asset_name=None):
        seen.append(asset_name)
        return np.zeros(length)

    monkeypatch.setattr(progressive, "wave", capture)
    default = progressive.episode("tetra", "speech", 2, 1800000)
    explicit = progressive.episode("tetra", "speech", 2, 1800000, speech_assets=None)
    np.testing.assert_array_equal(default["noise"], explicit["noise"])
    assert default["assets"] == explicit["assets"]
    assets = [
        dict(name=f"new-{s}-{i}.flac", speaker=s) for s in ("a", "b") for i in range(2)
    ]
    fresh = progressive.episode("tetra", "speech", 2, 2690000, speech_assets=assets)
    assert fresh["assets"] == seen[-2:]
    assert {a.split("-")[1] for a in fresh["assets"]} == {"a", "b"}


def test_confirmation_revisions_keep_speakers_and_episode_seeds_disjoint():
    import json
    from pathlib import Path

    from tools.qualification.doa_04_4.cases import ASSETS
    from tools.qualification.doa_04_4.indoor import load_protocol

    root = Path(__file__).resolve().parents[2] / "tools/qualification/doa_04_4"
    used_speakers = {a.split("-")[0] for group in ASSETS.values() for a in group}
    used_seeds = set()
    for name in (
        "indoor_confirmation_protocol.json",
        "indoor_confirmation_v2_protocol.json",
    ):
        protocol = json.loads((root / name).read_text())
        for block in protocol["blocks"]:
            selected = load_protocol(root / name, block)
            speakers = {a["speaker"] for a in selected["speech_assets"]}
            assert len(speakers) == 8
            assert not speakers & used_speakers
            used_speakers.update(speakers)
            assert selected["seed_base"] not in used_seeds
            used_seeds.add(selected["seed_base"])
            assert selected["repetitions"] == 12
        assert len(protocol["stages"]) == 6
        assert protocol["counts"] == [0, 1, 2]


def test_missing_or_wrong_direction_transition_is_not_a_response():
    from tools.qualification.doa_04_4.indoor_diagnostics import responses

    truths = [np.array([[1, 0, 0]]), np.array([[0, 1, 0]])]
    ticks = [dict(end_s=1.6 + i * 0.1, correct=False, compute_ms=2) for i in range(10)]
    result = responses(ticks, truths, 24000)
    assert result == [
        dict(from_count=1, to_count=1, direction_change=True, delay_ms=None)
    ]
