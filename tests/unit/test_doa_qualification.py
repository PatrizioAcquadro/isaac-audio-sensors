from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qualification.doa.phase_04_2 import (
    _great_circle_error,
    _real_take_label,
    run_qualification,
)


def test_quick_qualification_semantics_are_deterministic() -> None:
    first = run_qualification(
        evidence_root=None,
        calibration_profile=None,
        quick=True,
    )
    second = run_qualification(
        evidence_root=None,
        calibration_profile=None,
        quick=True,
    )

    assert first["semantic"] == second["semantic"]
    assert first["semantic"]["matrix"]["future_lookahead"] is False
    assert first["semantic"]["evidence"] == {"included": False}
    assert set(first["semantic"]["thresholds"]) == {
        "tdoa_least_squares",
        "srp_phat",
        "pyroomacoustics_srp",
    }
    json.dumps(first)


def test_real_qualification_requires_both_existing_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="provided together"):
        run_qualification(
            evidence_root=tmp_path,
            calibration_profile=None,
            quick=True,
        )
    with pytest.raises(FileNotFoundError, match="evidence root"):
        run_qualification(
            evidence_root=tmp_path / "missing",
            calibration_profile=tmp_path / "profile.json",
            quick=True,
        )


@pytest.mark.parametrize(
    ("take", "bearing", "condition"),
    (
        ("s48r02_preholdout_002_direction_000_r1", 0.0, "nominal"),
        ("s48r02_preholdout_027_front_occluded_000", 0.0, "stress"),
        ("s48r02_preholdout_032_low_right_090", 90.0, "low_level"),
        ("s48r02_preholdout_035_silence_end", None, "silence"),
    ),
)
def test_real_take_labels(
    take: str,
    bearing: float | None,
    condition: str,
) -> None:
    assert _real_take_label(take) == (bearing, condition)


def test_great_circle_error_covers_elevation() -> None:
    assert _great_circle_error(45.0, 20.0, 45.0, 20.0) == pytest.approx(0.0)
    assert _great_circle_error(0.0, 0.0, 90.0, 0.0) == pytest.approx(90.0)
