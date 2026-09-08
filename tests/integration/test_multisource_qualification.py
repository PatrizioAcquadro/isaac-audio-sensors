"""Check evaluation semantics independently of candidate performance."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("soundfile")

from tools.qualification.doa_04_4.cases import ASSETS, make_cases, match


def unit(bearing):
    angle = np.radians(bearing)
    return [np.cos(angle), np.sin(angle), 0.0]


def test_matching_counts_misses_and_spurious_events():
    truth = [unit(-40), unit(40)]
    assert match([unit(-40)], truth)["fn"] == 1
    assert match([], truth)["abstained"]
    result = match([unit(40), unit(-40), unit(170)], truth)
    assert (result["tp"], result["fp"], result["fn"]) == (2, 1, 0)
    assert not result["count_correct"]


def test_matching_is_circular_and_rejects_wrong_directions():
    assert match([unit(179)], [unit(-179)])["errors"] == pytest.approx([2])
    result = match([unit(150)], [unit(0)])
    assert result["count_correct"]
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)
    assert result["errors"] == []


def test_matching_prioritizes_admissible_cardinality_before_error():
    result = match([unit(0), unit(25)], [unit(5), unit(-25)])
    assert result["tp"] == 2
    assert sorted(result["errors"]) == pytest.approx([20, 25])


def test_partitions_are_disjoint_and_cover_pair_orientations():
    seen_assets = set()
    seen_seeds = set()
    for split, assets in ASSETS.items():
        assert seen_assets.isdisjoint(assets)
        seen_assets.update(assets)
        cases = make_cases(split, 4)
        seeds = {case.seed for case in cases}
        assert len(seeds) == len(cases) == 864
        assert seen_seeds.isdisjoint(seeds)
        seen_seeds.update(seeds)
        for array in ("raised", "tetra"):
            for condition in {case.condition for case in cases}:
                assert {
                    case.orientation
                    for case in cases
                    if case.array == array
                    and case.condition == condition
                    and case.count == 2
                } == {"azimuth", "elevation"}
