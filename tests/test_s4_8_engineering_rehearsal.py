from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.acquisition.s4_8_engineering_rehearsal import (
    run_synthetic_engineering_rehearsal,
)

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_non_holdout_rehearsal_exercises_complete_available_path() -> None:
    report = run_synthetic_engineering_rehearsal(
        ROOT,
        gate_execution_count=2,
    )

    assert report["non_holdout"] is True
    assert report["synthetic"] is True
    assert report["physical_hardware_used"] is False
    assert report["old_holdout_observations_used"] == 0
    assert report["acquisition"]["protocol_duration_s"] == 20.0
    assert report["acquisition"]["gate_execution_count"] == 2
    assert report["authentication"]["all_process_records_authenticated"] is True
    assert report["presealing"]["all_valid_decisions"] == "PASS"
    assert report["presealing"]["retry_decision"] == "RETRY_REQUIRED"
    assert report["producer"]["status"] == "complete"
    assert report["producer"]["manually_edited_outputs"] is False
    assert report["payload"]["planned_take_count"] == 47
    assert report["evaluation"]["criterion_count"] == 29
    assert report["evaluation"]["evaluated_criterion_count"] == 29
    assert report["evaluation"]["mandatory_passed_count"] == 23
    assert report["evaluation"]["mandatory_criterion_count"] == 23
    assert report["evaluation"]["readiness_passed"] is True
    assert report["metrics"]["useful_sound_coverage"] >= 0.90
    assert report["metrics"]["longest_continuous_useful_s"] >= 16.0
    assert report["metrics"]["maximum_non_applicable_gap_s"] <= 0.5
    assert report["metrics"]["active_abstention_rate"] <= 0.10
    assert report["metrics"]["stratum_b_median_confidence"] >= 0.015
    assert report["determinism"]["byte_equivalent"] is True
    assert report["authority"] == {
        "creates_grant": False,
        "consumes_grant": False,
        "official_state_machine": False,
        "publishes_official_evidence": False,
    }
    assert report["remaining_hardware_gate"] is not None
