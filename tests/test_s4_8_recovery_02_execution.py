"""Synthetic and state-machine tests for amendment-02 one-shot execution."""

from __future__ import annotations

import copy
import json
import shutil
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


def _synthetic_derived(
    *,
    payload: dict[str, Any],
    evaluation: dict[str, Any],
    evaluation_state: str = "evaluation_completed",
    run_failure: dict[str, Any] | None = None,
    journal_path: str = "state/first_run_journal.jsonl",
) -> dict[str, Any]:
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
    return {
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
        "run_journal": {
            "path": journal_path,
            "opening_event_count": 2,
        },
        "observation_inventory": inventory,
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "evaluation_state": evaluation_state,
        "evaluation": evaluation,
        "evaluation_sha256": canonical_sha256(evaluation),
        "run_failure": run_failure,
        "runtime_provenance": {},
    }


def _install_finalization_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = execution._execution_contract(ROOT)
    config["evidence"]["derived_input_path"] = "state/derived.json"
    config["evidence"]["run_journal_path"] = "state/first_run_journal.jsonl"
    config["evidence"]["output_path"] = "output/package"
    amendment = copy.deepcopy(recovery.load_amendment(ROOT))
    amendment["future_attempt"]["derived_input_path"] = config["evidence"][
        "derived_input_path"
    ]
    amendment["future_attempt"]["journal_path"] = config["evidence"][
        "run_journal_path"
    ]
    amendment["future_attempt"]["output_path"] = config["evidence"]["output_path"]
    amendment["future_attempt"]["closeout_path"] = "closeout/terminal.md"
    payload = evaluator.build_synthetic_payload(ROOT)
    evaluation = evaluator.evaluate_payload(payload, repo_root=ROOT).report()
    evaluation["evaluation_invocation_count"] = 1
    derived = _synthetic_derived(
        payload=payload,
        evaluation=evaluation,
        journal_path=config["evidence"]["run_journal_path"],
    )
    derived_path = tmp_path / config["evidence"]["derived_input_path"]
    derived_path.parent.mkdir(parents=True)
    derived_path.write_text(s4_8.pretty_json(derived), encoding="utf-8")
    journal_path = tmp_path / config["evidence"]["run_journal_path"]
    opening = s4_8._opening_journal_records(
        source_commit=SOURCE_COMMIT,
        event_time_utc=derived["event_time_utc"],
        ledger_event=derived["ledger_event"],
    )
    journal_path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in opening
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recovery, "load_amendment", lambda _root: amendment)
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
    monkeypatch.setattr(
        s4_8,
        "_validate_source_commit",
        lambda *_a, **_k: None,
    )
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
    return config, amendment, derived


def _write_journal(path: Path, records: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    chained: list[dict[str, Any]] = []
    for record in records:
        payload = {
            key: value
            for key, value in record.items()
            if key not in {"event_sha256", "previous_event_sha256"}
        }
        payload["previous_event_sha256"] = previous
        chained_record = {
            **payload,
            "event_sha256": canonical_sha256(payload),
        }
        chained.append(chained_record)
        previous = chained_record["event_sha256"]
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in chained
        ),
        encoding="utf-8",
    )


def _interrupt_failed_closeout_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fault_step: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, int]]:
    config, amendment, derived = _install_finalization_fixture(
        tmp_path,
        monkeypatch,
    )
    original_publish = execution._publish_operational_closeout
    publish_calls = {"count": 0}

    def fail_after_publish(*args: Any, **kwargs: Any) -> None:
        publish_calls["count"] += 1
        original_publish(*args, **kwargs)
        raise OSError("injected closeout publication failure")

    boundary_injected = False

    def stop_at_boundary(step: str) -> None:
        nonlocal boundary_injected
        if step == fault_step and not boundary_injected:
            boundary_injected = True
            raise OSError(f"injected downgrade interruption: {step}")

    monkeypatch.setattr(execution, "_publish_operational_closeout", fail_after_publish)
    monkeypatch.setattr(s4_8, "_downgrade_step", stop_at_boundary)
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: pytest.fail("evaluator was reinvoked"),
    )
    counter = {"count": 0}
    with (
        s4_8._use_execution_adapter(execution._adapter(counter)),
        pytest.raises(OSError, match=f"injected downgrade interruption: {fault_step}"),
    ):
        s4_8._finalize_first_run(
            tmp_path,
            config=config,
            derived=derived,
            source_commit=SOURCE_COMMIT,
            event_time_utc=derived["event_time_utc"],
        )

    assert boundary_injected
    assert publish_calls["count"] == 1
    assert counter["count"] == 0
    return config, amendment, derived, counter


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
    derived = _synthetic_derived(payload=payload, evaluation=evaluation)
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
    validated = execution._validate_evidence_package_structure(
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


def test_public_validation_authenticates_terminal_journal_and_rejects_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config, _amendment, derived = _install_finalization_fixture(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: pytest.fail("evaluator was reinvoked"),
    )
    counter = {"count": 0}
    with s4_8._use_execution_adapter(execution._adapter(counter)):
        _finalized, result = s4_8._finalize_first_run(
            tmp_path,
            config=config,
            derived=derived,
            source_commit=SOURCE_COMMIT,
            event_time_utc=derived["event_time_utc"],
        )
        package = Path(result["output"])
        validated = execution.validate_evidence_package(
            package,
            repo_root=tmp_path,
        )
        assert validated["journal_authenticated"] is True
        assert validated["final_status"] == "passed"
        assert validated["closeout"]["verdict"] == "GO"

        rewritten = tmp_path / "rewritten"
        shutil.copytree(package, rewritten)
        reproduction = s4_8.load_json(rewritten / "reproduction.json")
        reproduction["status"] = "self_consistently_rewritten"
        (rewritten / "reproduction.json").write_text(
            s4_8.pretty_json(reproduction),
            encoding="utf-8",
        )
        s4_8._write_index_and_manifest(rewritten, SOURCE_COMMIT)
        execution._validate_evidence_package_structure(
            rewritten,
            repo_root=tmp_path,
        )
        with pytest.raises(
            s4_8.S48Error,
            match="terminal journal/package mismatch",
        ):
            execution.validate_evidence_package(
                rewritten,
                repo_root=tmp_path,
            )


@pytest.mark.parametrize(
    "tamper",
    ["missing", "truncated", "source_commit", "terminal_status"],
)
def test_public_validation_rejects_invalid_terminal_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    config, _amendment, derived = _install_finalization_fixture(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: pytest.fail("evaluator was reinvoked"),
    )
    with s4_8._use_execution_adapter(execution._adapter({"count": 0})):
        _finalized, result = s4_8._finalize_first_run(
            tmp_path,
            config=config,
            derived=derived,
            source_commit=SOURCE_COMMIT,
            event_time_utc=derived["event_time_utc"],
        )
        journal_path = tmp_path / config["evidence"]["run_journal_path"]
        records = s4_8._load_run_journal(journal_path)
        if tamper == "missing":
            journal_path.unlink()
        elif tamper == "truncated":
            _write_journal(journal_path, records[:-1])
        elif tamper == "source_commit":
            for record in records:
                record["source_commit"] = "b" * 40
            _write_journal(journal_path, records)
        else:
            records[-2]["terminal_status"] = "failed"
            records[-2]["readiness_passed"] = False
            records[-1]["terminal_status"] = "failed"
            records[-1]["readiness_passed"] = False
            _write_journal(journal_path, records)

        with pytest.raises(s4_8.S48Error):
            execution.validate_evidence_package(
                Path(result["output"]),
                repo_root=tmp_path,
            )


@pytest.mark.parametrize("failure_after_write", [False, True])
def test_closeout_failure_downgrades_and_preserves_provisional_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_after_write: bool,
) -> None:
    config, amendment, derived = _install_finalization_fixture(
        tmp_path,
        monkeypatch,
    )
    original_publish = execution._publish_operational_closeout
    calls = 0

    def fail_closeout(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if failure_after_write:
            original_publish(*args, **kwargs)
        raise OSError("injected closeout publication failure")

    monkeypatch.setattr(execution, "_publish_operational_closeout", fail_closeout)
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: pytest.fail("evaluator was reinvoked"),
    )
    counter = {"count": 0}
    with s4_8._use_execution_adapter(execution._adapter(counter)):
        finalized, result = s4_8._finalize_first_run(
            tmp_path,
            config=config,
            derived=derived,
            source_commit=SOURCE_COMMIT,
            event_time_utc=derived["event_time_utc"],
        )
        validated = execution.validate_evidence_package(
            Path(result["output"]),
            repo_root=tmp_path,
        )

    assert calls == 1
    assert counter["count"] == 0
    assert result["status"] == "failed"
    assert finalized["run_failure"]["stage"] == "operational_closeout_publication"
    assert validated["final_status"] == "failed"
    assert validated["readiness_passed"] is False
    assert validated["closeout"]["publication_status"] == "failed"
    closeout = tmp_path / amendment["future_attempt"]["closeout_path"]
    assert not closeout.exists()
    provisional = (
        tmp_path / config["evidence"]["derived_input_path"]
    ).parent / "provisional_evidence.v1"
    assert provisional.is_dir()
    assert s4_8.load_json(provisional / "final_validation.json")["status"] == "passed"
    provisional_closeout = provisional.parent / "provisional_closeout.v1.md"
    assert provisional_closeout.exists() is failure_after_write
    journal = s4_8._load_run_journal(
        tmp_path / config["evidence"]["run_journal_path"]
    )
    assert journal[-1]["event"] == "first_run_terminal"
    assert journal[-1]["terminal_status"] == "failed"
    assert journal[-1]["operational_closeout"]["verdict"] == "NO-GO"


@pytest.mark.parametrize("fault_step", ["failure_prepared", "failure_published"])
def test_failed_closeout_crash_recovery_terminalizes_without_republication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault_step: str,
) -> None:
    config, amendment, derived, counter = _interrupt_failed_closeout_downgrade(
        tmp_path,
        monkeypatch,
        fault_step=fault_step,
    )
    journal_path = tmp_path / config["evidence"]["run_journal_path"]
    interrupted = s4_8._load_run_journal(journal_path)
    intent = next(
        record
        for record in interrupted
        if record["event"] == "first_run_downgrade_intent"
    )
    failed = interrupted[-1]
    assert failed["event"] == "first_run_finalization_failed"
    assert failed["terminal_status"] == "failed"
    assert failed["operational_closeout"] == {
        "publication_status": "failed",
        "path": amendment["future_attempt"]["closeout_path"],
        "sha256": None,
        "verdict": "NO-GO",
    }

    monkeypatch.setattr(s4_8, "_downgrade_step", lambda _step: None)
    monkeypatch.setattr(
        execution,
        "_publish_operational_closeout",
        lambda *_a, **_k: pytest.fail("failed closeout was republished"),
    )
    with s4_8._use_execution_adapter(execution._adapter(counter)):
        recovered = s4_8._recover_pending_finalization(
            tmp_path,
            config=config,
            source_commit=SOURCE_COMMIT,
        )
        output = tmp_path / config["evidence"]["output_path"]
        validated = execution.validate_evidence_package(
            output,
            repo_root=tmp_path,
        )
        with pytest.raises(s4_8.S48Error, match="automatic retry forbidden"):
            s4_8.run_authorized_evaluation_once(
                tmp_path,
                source_commit=SOURCE_COMMIT,
                event_time_utc="2026-07-31T12:00:01Z",
            )

    assert recovered["final_status"] == "failed"
    assert validated["final_status"] == "failed"
    assert validated["readiness_passed"] is False
    assert validated["closeout"]["publication_status"] == "failed"
    assert validated["closeout"]["sha256"] is None
    assert counter["count"] == 0
    closeout = tmp_path / amendment["future_attempt"]["closeout_path"]
    assert not closeout.exists()
    provisional = (
        tmp_path / config["evidence"]["derived_input_path"]
    ).parent / "provisional_evidence.v1"
    assert provisional.is_dir()
    assert s4_8.load_json(provisional / "final_validation.json")["status"] == "passed"
    assert (
        s4_8.sha256_file(provisional / "SHA256SUMS")
        == intent["provisional_manifest_sha256"]
    )
    assert (provisional.parent / "provisional_closeout.v1.md").is_file()
    journal = s4_8._load_run_journal(journal_path)
    events = [record["event"] for record in journal]
    assert events.count("first_run_downgrade_intent") == 1
    assert events[-2:] == ["first_run_finalization_failed", "first_run_terminal"]
    assert journal[-1]["terminal_status"] == "failed"
    assert journal[-1]["automatic_retry_forbidden"] is True


@pytest.mark.parametrize(
    "contradiction",
    [
        "unknown_status",
        "non_null_sha256",
        "non_failed_terminal",
        "official_closeout_exists",
    ],
)
def test_failed_closeout_recovery_rejects_contradictory_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contradiction: str,
) -> None:
    config, amendment, _derived, counter = _interrupt_failed_closeout_downgrade(
        tmp_path,
        monkeypatch,
        fault_step="failure_prepared",
    )
    journal_path = tmp_path / config["evidence"]["run_journal_path"]
    records = s4_8._load_run_journal(journal_path)
    failed = records[-1]
    assert failed["event"] == "first_run_finalization_failed"
    if contradiction == "unknown_status":
        failed["operational_closeout"]["publication_status"] = "unknown"
    elif contradiction == "non_null_sha256":
        failed["operational_closeout"]["sha256"] = "0" * 64
    elif contradiction == "non_failed_terminal":
        failed["terminal_status"] = "passed"
    else:
        closeout = tmp_path / amendment["future_attempt"]["closeout_path"]
        closeout.parent.mkdir(parents=True, exist_ok=True)
        closeout.write_text("contradictory official closeout\n", encoding="utf-8")
    _write_journal(journal_path, records)

    monkeypatch.setattr(s4_8, "_downgrade_step", lambda _step: None)
    monkeypatch.setattr(
        execution,
        "_publish_operational_closeout",
        lambda *_a, **_k: pytest.fail("contradictory closeout was published"),
    )
    with (
        s4_8._use_execution_adapter(execution._adapter(counter)),
        pytest.raises(s4_8.S48Error),
    ):
        s4_8._recover_pending_finalization(
            tmp_path,
            config=config,
            source_commit=SOURCE_COMMIT,
        )

    journal = s4_8._load_run_journal(journal_path)
    assert journal[-1]["event"] == "first_run_finalization_failed"
    assert all(record["event"] != "first_run_terminal" for record in journal)
    assert counter["count"] == 0


def test_prepared_recovery_downgrades_mismatched_closeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config, amendment, derived = _install_finalization_fixture(
        tmp_path,
        monkeypatch,
    )
    original_transition = s4_8._finalize_transition_failure
    original_publish = execution._publish_operational_closeout

    def stop_before_downgrade(*_args: Any, **_kwargs: Any):
        raise OSError("simulated crash before downgrade intent")

    def fail_initial_publish(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("simulated closeout interruption")

    monkeypatch.setattr(s4_8, "_finalize_transition_failure", stop_before_downgrade)
    monkeypatch.setattr(
        execution,
        "_publish_operational_closeout",
        fail_initial_publish,
    )
    with (
        s4_8._use_execution_adapter(execution._adapter({"count": 0})),
        pytest.raises(OSError, match="crash before downgrade"),
    ):
        s4_8._finalize_first_run(
            tmp_path,
            config=config,
            derived=derived,
            source_commit=SOURCE_COMMIT,
            event_time_utc=derived["event_time_utc"],
        )

    closeout = tmp_path / amendment["future_attempt"]["closeout_path"]
    closeout.parent.mkdir(parents=True, exist_ok=True)
    closeout.write_text("tampered GO closeout\n", encoding="utf-8")
    monkeypatch.setattr(s4_8, "_finalize_transition_failure", original_transition)
    monkeypatch.setattr(
        execution,
        "_publish_operational_closeout",
        original_publish,
    )
    with s4_8._use_execution_adapter(execution._adapter({"count": 0})):
        recovered = s4_8._recover_pending_finalization(
            tmp_path,
            config=config,
            source_commit=SOURCE_COMMIT,
        )
        validated = execution.validate_evidence_package(
            tmp_path / config["evidence"]["output_path"],
            repo_root=tmp_path,
        )

    assert recovered["final_status"] == "failed"
    assert validated["final_status"] == "failed"
    assert not closeout.exists()
    provisional_closeout = (
        tmp_path / config["evidence"]["derived_input_path"]
    ).parent / "provisional_closeout.v1.md"
    assert provisional_closeout.read_text(encoding="utf-8") == (
        "tampered GO closeout\n"
    )


def test_evaluator_exception_count_is_preserved_in_terminal_structures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    counter = {"count": 0}
    monkeypatch.setattr(
        evaluator,
        "evaluate_payload",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("evaluator fault")),
    )
    with pytest.raises(RuntimeError, match="evaluator fault"):
        execution._evaluation_callback(counter, payload, repo_root=ROOT)
    assert counter["count"] == 1
    with pytest.raises(s4_8.S48Error, match="invocation already consumed"):
        execution._evaluation_callback(counter, payload, repo_root=ROOT)

    failed_evaluation = {
        **s4_8._evaluation_placeholder(
            "evaluation_failed",
            error=RuntimeError("evaluator fault"),
        ),
        "evaluation_invocation_count": 1,
    }
    derived = _synthetic_derived(
        payload=payload,
        evaluation=failed_evaluation,
        evaluation_state="evaluation_failed",
        run_failure={"stage": "scientific_evaluation", "error": "evaluator fault"},
    )
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
    destination = tmp_path / "failed"
    destination.mkdir()
    execution.build_terminal_failure_package(
        ROOT,
        derived,
        destination=destination,
        source_commit=SOURCE_COMMIT,
        validate_result=False,
    )
    validated = execution._validate_evidence_package_structure(
        destination,
        repo_root=ROOT,
    )
    final = s4_8.load_json(destination / "final_validation.json")
    determinism = s4_8.load_json(destination / "determinism_report.json")
    assert validated["evaluator_invocation_count"] == 1
    assert final["scientific_evaluation_state"] == "evaluation_failed"
    assert final["evaluator_invocation_count"] == 1
    assert determinism["evaluator_invocation_count"] == 1


def test_not_evaluated_terminal_structure_requires_zero_invocations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = evaluator.build_synthetic_payload(ROOT)
    not_evaluated = s4_8._evaluation_placeholder("not_evaluated")
    derived = _synthetic_derived(
        payload=payload,
        evaluation=not_evaluated,
        evaluation_state="not_evaluated",
        run_failure={"stage": "scientific_evaluation", "error": "pre-entry fault"},
    )
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
    destination = tmp_path / "not-evaluated"
    destination.mkdir()
    execution.build_terminal_failure_package(
        ROOT,
        derived,
        destination=destination,
        source_commit=SOURCE_COMMIT,
        validate_result=False,
    )
    validated = execution._validate_evidence_package_structure(
        destination,
        repo_root=ROOT,
    )
    assert validated["evaluator_invocation_count"] == 0
    final = s4_8.load_json(destination / "final_validation.json")
    assert final["scientific_evaluation_state"] == "not_evaluated"
    assert final["evaluator_invocation_count"] == 0
