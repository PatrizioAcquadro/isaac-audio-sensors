from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.qualification.doa.phase_04_2 import (
    BLOCKED,
    FAIL,
    PASS,
    RealTake,
    _aggregate_status,
    _great_circle_error,
    _primary_scenarios,
    _real_take_label,
    _real_take_split,
    _real_take_summaries,
    _score_block,
    _select_reliability_threshold,
    run_qualification,
)
from tools.qualification.doa.phase_04_3 import (
    MEASURED_TICKS,
    RUN_COUNT,
    WARMUP_TICKS,
)
from tools.qualification.doa.phase_04_3 import (
    run_qualification as run_rolling_qualification,
)


def test_phase_04_3_rolling_gate_is_reproducible_and_within_budget() -> None:
    report = run_rolling_qualification()
    semantic = report["semantic"]

    assert semantic["schema"] == "ias.doa.phase_04_3_rolling_qualification.v1"
    assert semantic["status"] == "pass"
    assert semantic["run_count"] == RUN_COUNT == 2
    assert semantic["warmup_ticks_per_run"] == WARMUP_TICKS == 20
    assert semantic["measured_ticks_per_run"] == MEASURED_TICKS == 200
    assert semantic["semantics_identical"] is True
    assert semantic["context_exact"] is True
    assert semantic["no_future_lookahead"] is True
    assert semantic["future_lookahead"] is False
    for run in report["runtime"]["runs"]:
        assert run["compute_p95_ms"] < 50.0
        assert run["compute_max_ms"] < 250.0


def test_quick_qualification_is_role_based_and_deterministic() -> None:
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

    semantic = first["semantic"]
    assert semantic == second["semantic"]
    assert semantic["schema"] == "ias.doa.phase_04_2_qualification.v2"
    assert semantic["matrix"]["future_lookahead"] is False
    assert (
        semantic["matrix"]["primary_synthetic_partition"]
        == "independent_evaluation_only"
    )
    assert semantic["evidence"]["status"] == BLOCKED
    assert set(semantic["roles"]) == {
        "primary_planar_doa",
        "two_microphone_ambiguity",
        "robustness",
        "realtime_planar_compute",
        "optional_3d",
    }
    assert semantic["roles"]["primary_planar_doa"]["status"] == BLOCKED
    assert semantic["roles"]["two_microphone_ambiguity"]["status"] == PASS
    assert semantic["roles"]["realtime_planar_compute"]["status"] == BLOCKED
    assert semantic["roles"]["optional_3d"]["status"] == BLOCKED
    assert (
        semantic["roles"]["two_microphone_ambiguity"]["real_hardware_performance"][
            "status"
        ]
        == BLOCKED
    )
    serialized = json.dumps(first).lower()
    assert "normmusic" not in serialized
    assert '"srp_phat"' not in serialized
    assert "regression" not in serialized


def test_missing_real_inputs_block_roles_instead_of_raising(tmp_path: Path) -> None:
    report = run_qualification(
        evidence_root=tmp_path / "missing",
        calibration_profile=tmp_path / "profile.json",
        quick=True,
    )

    evidence = report["semantic"]["evidence"]
    assert evidence["status"] == BLOCKED
    assert report["semantic"]["roles"]["primary_planar_doa"]["status"] == BLOCKED
    assert report["semantic"]["roles"]["robustness"]["status"] == BLOCKED


@pytest.mark.parametrize(
    ("statuses", "expected"),
    (
        ((PASS, PASS), PASS),
        ((PASS, BLOCKED), BLOCKED),
        ((PASS, BLOCKED, FAIL), FAIL),
        ((), BLOCKED),
    ),
)
def test_tri_state_aggregation(
    statuses: tuple[str, ...],
    expected: str,
) -> None:
    assert _aggregate_status(statuses) == expected


def test_reliability_selection_uses_calibration_records_only() -> None:
    records = [
        *(
            {
                "split": "calibration",
                "condition": "nominal",
                "activity_detected": True,
                "raw_resolved": True,
                "reliability": 0.06,
            }
            for _ in range(20)
        ),
        {
            "split": "calibration",
            "condition": "silence",
            "activity_detected": True,
            "raw_resolved": True,
            "reliability": 0.05,
        },
        {
            "split": "validation",
            "condition": "silence",
            "activity_detected": True,
            "raw_resolved": True,
            "reliability": 0.99,
        },
    ]

    selected = _select_reliability_threshold(records)

    assert selected["status"] == PASS
    assert selected["selected"] == 0.06
    assert selected["selection_rule"] == "lowest_eligible_fixed_grid_value"


def test_real_take_summaries_do_not_weight_one_take_by_another() -> None:
    records = [
        {
            "take_id": "short",
            "split": "validation",
            "condition": "stress",
            "activity_detected": True,
            "resolved": False,
            "bearing_error_deg": None,
        },
        *(
            {
                "take_id": "long",
                "split": "validation",
                "condition": "stress",
                "activity_detected": True,
                "resolved": True,
                "bearing_error_deg": 1.0,
            }
            for _ in range(99)
        ),
    ]

    summaries = {item["take_id"]: item for item in _real_take_summaries(records)}

    assert summaries["short"]["resolved_coverage"] == 0.0
    assert summaries["long"]["resolved_coverage"] == 1.0


def test_scoring_uses_only_complete_sequential_authorized_blocks() -> None:
    take = RealTake(
        take_id="take",
        split="validation",
        condition="nominal",
        bearing_deg=0.0,
        samples=np.zeros((4, 16_000), dtype=np.float32),
        positions_m=np.zeros((4, 3)),
        sample_rate_hz=16_000,
        score_start_s=0.25,
        score_stop_s=0.75,
        wav_sha256="0" * 64,
    )

    assert _score_block(take, 0, 4_000) is False
    assert _score_block(take, 4_000, 8_000) is True
    assert _score_block(take, 8_000, 12_000) is True
    assert _score_block(take, 12_000, 16_000) is False


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


def test_primary_synthetic_matrix_is_independent_evaluation_only() -> None:
    scenarios = list(_primary_scenarios(quick=False))

    assert len(scenarios) == 128
    assert {item.split for item in scenarios} == {"evaluation"}
    assert {item.snr_db for item in scenarios} == {10, 20}
    assert {item.positions_m.shape[0] for item in scenarios} == {3, 4}
    assert {item.frequency_band_hz for item in scenarios} == {
        (300, 800),
        (800, 2000),
        (2000, 4000),
        (4000, 6000),
    }


def test_real_validation_partition_is_named_without_independence_claim() -> None:
    assert _real_take_split("direction_000_r1", "nominal") == "calibration"
    assert _real_take_split("direction_000_r2", "nominal") == "validation"
    assert _real_take_split("silence_middle", "silence") == "validation"


def test_great_circle_error_covers_elevation() -> None:
    assert _great_circle_error(45.0, 20.0, 45.0, 20.0) == pytest.approx(0.0)
    assert _great_circle_error(0.0, 0.0, 90.0, 0.0) == pytest.approx(90.0)
