from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "s4_8_repeatability_diagnostic",
    ROOT / "scripts/run_s4_8_repeatability_diagnostic.py",
)
assert SPEC is not None and SPEC.loader is not None
repeatability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repeatability)


def test_take_definitions_are_exact_independent_repositions() -> None:
    takes = repeatability._take_definitions()

    assert len(takes) == 3
    assert [take["take_number"] for take in takes] == [1, 2, 3]
    assert all(take["source_bearing_deg"] == 22.5 for take in takes)
    assert all(take["source_radius_m"] == 0.8 for take in takes)
    assert all(take["playback_gain"] == 0.75 for take in takes)
    assert all(take["independent_recording"] is True for take in takes)
    assert [take["mac_removal_and_exact_reposition_before_take"] for take in takes] == [
        False,
        True,
        True,
    ]


def test_campaign_root_rejects_historical_and_external_paths(tmp_path: Path) -> None:
    with pytest.raises(repeatability.RepeatabilityError, match="child"):
        repeatability._campaign_root(tmp_path)
    with pytest.raises(repeatability.RepeatabilityError, match="historical"):
        repeatability._campaign_root(
            repeatability.LOCAL_ROOT / "s4_8_preliminary_confirmation_02"
        )


def test_pair_medians_exclude_abstained_windows() -> None:
    analysis = {
        "windows": [
            {"abstained": False, "tdoa_s": {"a->b": 10e-6}},
            {"abstained": True, "tdoa_s": {"a->b": 900e-6}},
            {"abstained": False, "tdoa_s": {"a->b": 30e-6}},
        ]
    }

    assert repeatability._pair_medians_us(analysis) == pytest.approx({"a->b": 20.0})
