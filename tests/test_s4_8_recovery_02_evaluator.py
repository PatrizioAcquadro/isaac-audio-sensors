"""Synthetic-only tests for the frozen 37-take evaluator adapter."""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02 as recovery,
)
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_evaluator as evaluator,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as c2
from isaac_audio_sensors.core import acceptance_criteria_corrective_03 as c3

ROOT = Path(__file__).resolve().parents[1]


def _outcome(report: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    return next(
        item for item in report["criteria"] if item["criterion_id"] == criterion_id
    )


def _set_wrong_bearing(take: dict[str, Any]) -> None:
    target = float(take["identity"]["target_bearing_deg_f_project"])
    wrong = (target + 180.0) % 360.0
    for window in take["bearing_windows"]:
        window["srp_bearing_deg_f_project"] = wrong
    take["bearing_absolute_error_deg"] = None
    take["estimated_bearing_deg_f_project"] = None
    take["sector_correct"] = None


def test_registry_is_exactly_the_frozen_37_take_design() -> None:
    registry = evaluator.build_identity_registry(ROOT)
    material = evaluator._protocol_material(ROOT)

    assert list(registry) == material["partition"]["planned_take_ids"]
    assert len(registry) == 37
    assert Counter(item.stratum_id for item in registry.values()) == (
        recovery.STRATUM_COUNTS
    )
    assert len({item.group_id for item in registry.values()}) == 15
    assert {
        item.repetition
        for item in registry.values()
        if item.stratum_id == "A_controlled_boundary_sweep"
    } == {1, 2, 3}
    assert sum(
        item.paired_counterpart_take_id is not None
        for item in registry.values()
    ) == 8


def test_synthetic_evaluation_is_deterministic_and_uses_amended_roles() -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    first = evaluator.evaluate_payload(payload, repo_root=ROOT).report()
    second = evaluator.evaluate_payload(payload, repo_root=ROOT).report()

    assert first == second
    assert first["status"] == "passed"
    assert len(first["criteria"]) == 30
    assert first["identity_summary"]["inherited_criterion_count"] == 29
    assert first["identity_summary"]["effective_gating_criterion_count"] == 17
    assert first["identity_summary"]["raw_channel_record_count"] == 148
    assert first["identity_summary"]["categorical_applicable_take_count"] == 28
    assert first["identity_summary"]["categorical_expected_direction_counts"] == {
        "forward": 7,
        "right": 10,
        "left": 7,
        "None": 4,
    }
    assert _outcome(
        first, "squadbot_categorical_direction_accuracy"
    )["sample_count"] == 28
    for criterion_id in (
        recovery.CONTINUOUS_BEARING_DIAGNOSTIC_CRITERIA
        | recovery.SUPERSEDED_SECTOR_CRITERIA
    ):
        assert _outcome(first, criterion_id)["gating"] is False


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [
        (0.0, "forward"),
        (44.999, "forward"),
        (45.0, "right"),
        (164.999, "right"),
        (165.0, "None"),
        (194.999, "None"),
        (195.0, "left"),
        (314.999, "left"),
        (315.0, "forward"),
        (360.0, "forward"),
    ],
)
def test_squadbot_boundaries_are_frozen(
    bearing: float,
    expected: str,
) -> None:
    assert recovery.bearing_to_squadbot_direction(bearing) == expected


def test_mapping_is_applied_once_to_the_linear_median() -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    take = next(
        item
        for item in payload["takes"]
        if item["identity"]["planned_take_id"].endswith(
            "008_direction_090_r1"
        )
    )
    bearings = [10.0] * 60 + [100.0] * 50 + [300.0] * 49
    assert len(bearings) == len(take["bearing_windows"])
    for window, bearing in zip(take["bearing_windows"], bearings, strict=True):
        window["srp_bearing_deg_f_project"] = bearing
    take["bearing_absolute_error_deg"] = None
    take["estimated_bearing_deg_f_project"] = None
    result = evaluator.evaluate_payload(payload, repo_root=ROOT).report()
    record = next(
        item
        for item in result["categorical_take_results"]
        if item["planned_take_id"] == take["identity"]["planned_take_id"]
    )

    assert Counter(
        recovery.bearing_to_squadbot_direction(value) for value in bearings
    ).most_common(1)[0][0] == "forward"
    assert record["representative_bearing_deg_f_project"] == 100.0
    assert record["observed_direction"] == "right"
    assert record["categorical_correct"] is True


def test_unavailable_and_failure_precedence_are_adverse_or_expected() -> None:
    registry = evaluator.build_identity_registry(ROOT)
    front = next(
        item
        for item in registry.values()
        if item.stratum_id == "A_controlled_boundary_sweep"
        and item.target_bearing_deg_f_project == 0.0
    )
    rear = next(
        item
        for item in registry.values()
        if item.stratum_id == "B_center_nominal_level"
        and item.target_bearing_deg_f_project == 180.0
    )
    silence = next(
        item
        for item in registry.values()
        if item.stratum_id == "D_silence"
    )

    assert evaluator.classify_categorical_take(
        identity=front,
        representative_bearing_deg=None,
        failed=False,
    )["categorical_correct"] is False
    assert evaluator.classify_categorical_take(
        identity=rear,
        representative_bearing_deg=None,
        failed=False,
    )["categorical_correct"] is True
    assert evaluator.classify_categorical_take(
        identity=silence,
        representative_bearing_deg=None,
        failed=False,
    )["categorical_correct"] is True
    assert evaluator.classify_categorical_take(
        identity=rear,
        representative_bearing_deg=None,
        failed=True,
    )["categorical_correct"] is False


def test_categorical_threshold_is_exactly_21_of_28() -> None:
    passing = evaluator.build_synthetic_payload(ROOT)
    applicable = [
        item
        for item in passing["takes"]
        if item["identity"]["stratum_id"]
        in {"A_controlled_boundary_sweep", "B_center_nominal_level"}
    ]
    for take in applicable[:7]:
        _set_wrong_bearing(take)
    pass_report = evaluator.evaluate_payload(passing, repo_root=ROOT).report()
    pass_outcome = _outcome(
        pass_report, "squadbot_categorical_direction_accuracy"
    )
    assert pass_outcome["observed"] == 0.75
    assert pass_outcome["passed"] is True

    failing = evaluator.build_synthetic_payload(ROOT)
    applicable = [
        item
        for item in failing["takes"]
        if item["identity"]["stratum_id"]
        in {"A_controlled_boundary_sweep", "B_center_nominal_level"}
    ]
    for take in applicable[:8]:
        _set_wrong_bearing(take)
    fail_report = evaluator.evaluate_payload(failing, repo_root=ROOT).report()
    fail_outcome = _outcome(
        fail_report, "squadbot_categorical_direction_accuracy"
    )
    assert fail_outcome["observed"] == pytest.approx(20 / 28)
    assert fail_outcome["passed"] is False
    assert fail_report["failed_gating_criteria"] == [
        "squadbot_categorical_direction_accuracy"
    ]


def test_missing_duplicate_and_contract_drift_fail_closed() -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    missing = copy.deepcopy(payload)
    missing["takes"].pop()
    with pytest.raises(c2.CorrectiveAcceptanceError, match="exact take set"):
        evaluator.evaluate_payload(missing, repo_root=ROOT)

    duplicate = copy.deepcopy(payload)
    duplicate["takes"][-1] = copy.deepcopy(duplicate["takes"][0])
    with pytest.raises(c2.CorrectiveAcceptanceError, match="duplicate take"):
        evaluator.evaluate_payload(duplicate, repo_root=ROOT)

    altered = copy.deepcopy(payload)
    altered["contract"]["planned_take_count"] = 36
    with pytest.raises(c2.CorrectiveAcceptanceError, match="contract identity"):
        evaluator.evaluate_payload(altered, repo_root=ROOT)


def test_historical_47_take_evaluator_is_unchanged_and_deterministic() -> None:
    payload = c3.build_synthetic_payload(ROOT)

    first = c3.evaluate_corrective(payload, repo_root=ROOT).report()
    second = c3.evaluate_corrective(payload, repo_root=ROOT).report()

    assert first == second
    assert first["config_identity"]["planned_take_count"] == 47
    assert len(first["criteria"]) == 29


def test_evaluator_never_reads_the_observation_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def reject_dataset_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if "dataset" in path.parts:
            raise AssertionError(f"unexpected observation read: {path}")
        return original_read_text(path, *args, **kwargs)

    def reject_dataset_bytes(path: Path) -> bytes:
        if "dataset" in path.parts:
            raise AssertionError(f"unexpected observation read: {path}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_text", reject_dataset_text)
    monkeypatch.setattr(Path, "read_bytes", reject_dataset_bytes)

    assert evaluator.evaluate_payload(payload, repo_root=ROOT).readiness_passed
