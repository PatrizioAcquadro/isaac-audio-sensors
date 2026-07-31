"""Synthetic and state-machine tests for amendment-02 one-shot execution."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_evaluator as evaluator,
)
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_execution as execution,
)
from isaac_audio_sensors.acquisition.s4_4 import GRANT_SCHEMA, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40


def _preopen() -> dict[str, Any]:
    return {
        "seal_file_sha256": "1" * 64,
        "split_plan_sha256": "2" * 64,
        "prerequisite": {
            "schema": "ias.s4_8.recovery_02.authorization_prerequisite.v1",
            "source_commit": SOURCE_COMMIT,
        },
    }


def _grant() -> dict[str, Any]:
    preopen = _preopen()
    payload = {
        "schema": GRANT_SCHEMA,
        "grant_id": (
            f"s4_8_recovery_amendment_02_37_take_corrective_03_{SOURCE_COMMIT}"
        ),
        "purpose": "S4.8_evaluation",
        "seal_sha256": preopen["seal_file_sha256"],
        "split_plan_sha256": preopen["split_plan_sha256"],
        "prerequisite": preopen["prerequisite"],
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    return {**payload, "grant_sha256": canonical_sha256(payload)}


def _ledger_event(grant: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "event_time_utc": "2026-07-31T12:00:00Z",
        "seal_sha256": "1" * 64,
        "split_plan_sha256": "2" * 64,
        "grant_id": grant["grant_id"],
        "grant_sha256": grant["grant_sha256"],
        "prerequisite_sha256": canonical_sha256(_preopen()["prerequisite"]),
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {**payload, "event_sha256": canonical_sha256(payload)}


def test_execution_contract_is_additive_and_37_take_scoped() -> None:
    contract = execution._execution_contract(ROOT)
    amendment = recovery.load_amendment(ROOT)

    assert contract["holdout"]["planned_take_count"] == 37
    assert contract["holdout"]["sealed_artifact_count"] == 374
    assert contract["grant"]["path"] == amendment["future_attempt"]["grant_path"]
    assert (
        contract["grant"]["ledger_path"] == (amendment["future_attempt"]["ledger_path"])
    )
    assert (
        contract["evidence"]["output_path"]
        == (amendment["future_attempt"]["output_path"])
    )
    assert contract["criteria"]["readiness_count"] == 17
    assert contract["criteria"]["stretch_count"] == 13
    assert amendment["future_attempt"]["grant_creation_authorized"] is False
    assert amendment["future_attempt"]["grant_consumption_authorized"] is False
    assert amendment["future_attempt"]["evaluation_execution_authorized"] is False


def test_bound_evaluator_can_be_invoked_only_once() -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    counter = {"count": 0}

    report = execution._evaluation_callback(
        counter,
        payload,
        repo_root=ROOT,
    )

    assert report["evaluation_invocation_count"] == 1
    assert report["readiness_passed"] is True
    assert report["identity_summary"]["take_count"] == 37
    assert report["identity_summary"]["raw_channel_record_count"] == 148
    assert report["identity_summary"]["categorical_applicable_take_count"] == 28
    assert report["identity_summary"]["stratum_counts"] == {
        "A_controlled_boundary_sweep": 24,
        "B_center_nominal_level": 4,
        "C_center_low_level": 4,
        "D_silence": 3,
        "E_impact_audio_video": 2,
    }
    sample_counts = {
        item["criterion_id"]: item["sample_count"] for item in report["criteria"]
    }
    assert sample_counts["within_cell_bearing_circular_range_stratum_a"] == 8
    assert sample_counts["within_cell_pair_tdoa_range_stratum_a"] == 48
    assert sample_counts["coarse_av_association_residual_stratum_e"] == 2
    with pytest.raises(s4_8.S48Error, match="invocation already consumed"):
        execution._evaluation_callback(counter, payload, repo_root=ROOT)


def test_custom_grant_consumption_is_single_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    grant = _grant()
    grant_path = tmp_path / "holdout_access_grant.corrective_03.v1.json"
    authorization_path = tmp_path / s4_8.AUTHORIZATION_RECORD_NAME
    grant_path.write_text(s4_8.pretty_json(grant), encoding="utf-8")
    authorization_path.write_text(
        s4_8.pretty_json(
            {
                "schema": "ias.s4_8.authorization_record.v1",
                "authorization_id": "authorization-001",
                "source_commit": SOURCE_COMMIT,
                "grant_id": grant["grant_id"],
                "grant_path": (
                    "dataset/S4.8/recovery_amendment_02_37_take/access/"
                    "holdout_access_grant.corrective_03.v1.json"
                ),
                "grant_sha256": grant["grant_sha256"],
                "ledger_path": (
                    "dataset/S4.8/recovery_amendment_02_37_take/access/"
                    "opening_transition.v1/access_ledger.jsonl"
                ),
                "irreversible_scientific_action_acknowledged": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(execution, "preopen_validate", lambda *_a, **_k: _preopen())
    monkeypatch.setattr(s4_8, "_validate_authorization_record", lambda *_a, **_k: None)
    monkeypatch.setattr(
        s4_8,
        "load_contract",
        lambda _root: {
            "grant": {
                "grant_id_template": (
                    "s4_8_recovery_amendment_02_37_take_corrective_03_{source_commit}"
                )
            }
        },
    )
    ledger_path = tmp_path / "access_ledger.jsonl"

    result = execution.consume_grant(
        ROOT,
        grant_path=grant_path,
        ledger_path=ledger_path,
        source_commit=SOURCE_COMMIT,
        event_time_utc="2026-07-31T12:00:00Z",
    )

    assert result["allowed"] is True
    assert result["ledger_event"]["sequence"] == 0
    with pytest.raises(s4_8.S48Error, match="already consumed"):
        execution.consume_grant(
            ROOT,
            grant_path=grant_path,
            ledger_path=ledger_path,
            source_commit=SOURCE_COMMIT,
            event_time_utc="2026-07-31T12:00:01Z",
        )
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 1


def test_custom_grant_tamper_fails_before_ledger_append(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    grant = _grant()
    altered = copy.deepcopy(grant)
    altered["prerequisite"]["source_commit"] = "b" * 40
    grant_path = tmp_path / "holdout_access_grant.corrective_03.v1.json"
    grant_path.write_text(s4_8.pretty_json(altered), encoding="utf-8")
    grant_path.with_name(s4_8.AUTHORIZATION_RECORD_NAME).write_text(
        "{}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution, "preopen_validate", lambda *_a, **_k: _preopen())
    monkeypatch.setattr(
        s4_8,
        "load_contract",
        lambda _root: {
            "grant": {
                "grant_id_template": (
                    "s4_8_recovery_amendment_02_37_take_corrective_03_{source_commit}"
                )
            }
        },
    )
    ledger_path = tmp_path / "access_ledger.jsonl"

    with pytest.raises(s4_8.S48Error, match="grant mismatch"):
        execution.consume_grant(
            ROOT,
            grant_path=grant_path,
            ledger_path=ledger_path,
            source_commit=SOURCE_COMMIT,
            event_time_utc="2026-07-31T12:00:00Z",
        )
    assert not ledger_path.exists()


def test_package_build_and_validation_never_reinvoke_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    evaluation = evaluator.evaluate_payload(payload, repo_root=ROOT).report()
    evaluation["evaluation_invocation_count"] = 1
    grant = _grant()
    event = _ledger_event(grant)
    inventory = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "attempt_root": f"attempts/{take['identity']['planned_take_id']}",
            "selected_for_evaluation": True,
            "rejected": False,
            "failed": False,
        }
        for take in payload["takes"]
    ]
    derived = {
        "schema": execution.DERIVED_INPUT_SCHEMA,
        "tool_version": execution.TOOL_VERSION,
        "source_commit": SOURCE_COMMIT,
        "event_time_utc": "2026-07-31T12:00:00Z",
        "authorization_record": {"authorization_id": "authorization-001"},
        "grant": {
            "path": "grant.json",
            "file_sha256": "3" * 64,
            "grant_sha256": grant["grant_sha256"],
        },
        "ledger_event": event,
        "run_journal": {"opening_event_count": 2},
        "observation_inventory": inventory,
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "evaluation_state": "evaluation_completed",
        "evaluation": evaluation,
        "evaluation_sha256": canonical_sha256(evaluation),
        "run_failure": None,
        "runtime_provenance": {},
    }
    monkeypatch.setattr(
        s4_8,
        "_validate_authorization_evidence",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        s4_8,
        "_provenance_report",
        lambda *_a, **_k: {
            "schema": "ias.s4_8.provenance.v1",
            "source_commit": SOURCE_COMMIT,
        },
    )
    monkeypatch.setattr(
        s4_8,
        "_validate_provenance",
        lambda *_a, **_k: SOURCE_COMMIT,
    )
    monkeypatch.setattr(
        s4_8,
        "preservation_report",
        lambda _root: {"status": "passed"},
    )
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: {})
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: pytest.fail("evaluator was reinvoked"),
    )
    reports = execution._package_reports(
        ROOT,
        derived,
        source_commit=SOURCE_COMMIT,
        package_profile=execution.FULL_EVIDENCE_PROFILE,
    )
    assert reports["final_validation.json"]["status"] == "passed"

    contradictory = copy.deepcopy(derived)
    first_gating = next(
        item
        for item in contradictory["evaluation"]["criteria"]
        if item["gating"] is True
    )
    first_gating["passed"] = False
    contradictory_reports = execution._package_reports(
        ROOT,
        contradictory,
        source_commit=SOURCE_COMMIT,
        package_profile=execution.FULL_EVIDENCE_PROFILE,
    )
    assert contradictory_reports["final_validation.json"]["status"] == "failed"
    assert contradictory_reports["final_validation.json"]["readiness_passed"] is False

    evaluation_failed = copy.deepcopy(derived)
    evaluation_failed["evaluation_state"] = "evaluation_failed"
    evaluation_failed["run_failure"] = {"stage": "evaluation", "message": "fault"}
    failure_reports = execution._package_reports(
        ROOT,
        evaluation_failed,
        source_commit=SOURCE_COMMIT,
        package_profile=execution.TERMINAL_FAILURE_PROFILE,
    )
    assert failure_reports["final_validation.json"]["status"] == "failed"
    assert failure_reports["final_validation.json"]["readiness_passed"] is False

    destination = tmp_path / "package"
    destination.mkdir()

    built = execution.build_evidence_package(
        ROOT,
        derived,
        destination=destination,
        source_commit=SOURCE_COMMIT,
        validate_result=False,
    )
    validated = execution.validate_evidence_package(
        destination,
        repo_root=ROOT,
    )

    assert built["scientific_recomputed"] is False
    assert validated["scientific_recomputed"] is False
    assert validated["evaluator_invocation_count"] == 1
    assert validated["holdout_opening_event_count"] == 1
    final = s4_8.load_json(destination / "final_validation.json")
    assert final["readiness_criterion_count"] == 17
    assert final["planned_take_count"] == 37
