from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

ROOT = Path(__file__).resolve().parents[1]


def test_amendment_02_preregistration_is_schema_valid_and_frozen() -> None:
    amendment = recovery.load_amendment(ROOT)

    assert amendment["status"] == "preregistered_awaiting_unseen_holdout"
    assert [run["run_id"] for run in amendment["prior_terminal_runs"]] == [
        "original_s4_8",
        "recovery_amendment_01",
    ]
    preregistration = amendment["scientific_preregistration"]
    assert preregistration["producer_fix_commit"] == (
        "3738554f1fcfcf906eefcf26871d56ece21f11e4"
    )
    assert preregistration["criteria_unchanged"] is True
    assert preregistration["readiness_criterion_count"] == 23
    assert preregistration["stretch_criterion_count"] == 6
    assert preregistration["planned_take_count"] == 47
    assert preregistration["leakage_group_count"] == 15


def test_terminal_history_authenticates_both_failed_runs_hash_only() -> None:
    result = recovery.validate_terminal_history(ROOT)

    assert result["status"] == "passed"
    assert result["terminal_run_count"] == 2
    assert result["terminal_statuses"] == {
        "original_s4_8": "failed",
        "recovery_amendment_01": "failed",
    }
    assert result["artifact_count"] == 18
    assert result["package_manifest_sha256"] == {
        "original_s4_8": (
            "bb3e57bdac2cdf545f9adf39e867db3bf5b35831892c66b101e57913af9e59e2"
        ),
        "recovery_amendment_01": (
            "3ebcaf1070f5d8d53f878ea666cb8c63a4b9f1350d84e70ae68405a9652e3cbb"
        ),
    }
    assert result["raw_holdout_read"] is False
    assert result["scientific_payload_loaded"] is False


def test_terminal_artifact_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    record = amendment["prior_terminal_runs"][1]["artifacts"]["journal"]
    path = (ROOT / record["path"]).resolve()
    original = s4_8.sha256_file

    def changed(candidate: Path) -> str:
        if candidate.resolve() == path:
            return "0" * 64
        return original(candidate)

    monkeypatch.setattr(s4_8, "sha256_file", changed)
    with pytest.raises(s4_8.S48Error, match="terminal artifact mismatch"):
        recovery.validate_terminal_history(ROOT, amendment)


def test_unseen_holdout_namespace_cannot_reuse_consumed_observations() -> None:
    amendment = recovery.load_amendment(ROOT)
    altered = copy.deepcopy(amendment)
    altered["unseen_holdout"]["observation_root"] = (
        "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/attempts/reused"
    )

    with pytest.raises(s4_8.S48Error, match="reuses consumed data"):
        recovery._validate_namespaces(altered)


def test_future_state_paths_are_disjoint_and_absent() -> None:
    amendment = recovery.load_amendment(ROOT)
    historical = {
        record["path"]
        for run in amendment["prior_terminal_runs"]
        for record in run["artifacts"].values()
    }
    future = amendment["future_attempt"]
    future_paths = {
        future[key]
        for key in (
            "grant_path",
            "ledger_path",
            "journal_path",
            "derived_input_path",
            "output_path",
            "closeout_path",
            "independent_review_path",
        )
    }

    assert historical.isdisjoint(future_paths)
    assert all(not (ROOT / path).exists() for path in future_paths)


def test_amendment_02_exposes_no_grant_or_execution_function() -> None:
    amendment = recovery.load_amendment(ROOT)
    future = amendment["future_attempt"]

    assert future["grant_creation_authorized"] is False
    assert future["grant_consumption_authorized"] is False
    assert future["evaluation_execution_authorized"] is False
    assert future["automatic_retry_of_prior_runs"] is False
    assert not hasattr(recovery, "create_recovery_grant")
    assert not hasattr(recovery, "run_recovery_evaluation_once")


def test_authority_cannot_be_enabled_inside_preregistration_schema() -> None:
    amendment = recovery.load_amendment(ROOT)
    schema = s4_8.load_json(ROOT / recovery.AMENDMENT_SCHEMA_PATH)
    altered = copy.deepcopy(amendment)
    altered["future_attempt"]["grant_creation_authorized"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(altered, schema)


def test_future_binding_schema_requires_sealed_unopened_state() -> None:
    schema = s4_8.load_json(ROOT / recovery.HOLDOUT_BINDING_SCHEMA_PATH)
    binding = {
        "schema": "ias.s4_8.recovery_unseen_holdout_binding.v1",
        "amendment_id": "s4_8_recovery_amendment_02",
        "holdout_id": "s4_8_recovery_amendment_02_unseen_holdout",
        "status": "sealed_unopened",
        "preregistration_commit": "a" * 40,
        "precollection_seal": {"path": "future/pre.json", "sha256": "a" * 64},
        "partition_manifest": {"path": "future/part.json", "sha256": "b" * 64},
        "session_manifest": {"path": "future/session.json", "sha256": "c" * 64},
        "holdout_seal": {"path": "future/seal.json", "sha256": "d" * 64},
        "observation_root": (
            "dataset/S4.4/amendments/s4_4_data_expansion_amendment_04/attempts"
        ),
        "planned_take_count": 47,
        "leakage_group_count": 15,
        "scientifically_opened": False,
    }
    jsonschema.validate(binding, schema)
    opened = copy.deepcopy(binding)
    opened["scientifically_opened"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(opened, schema)


def test_preopen_is_truthful_no_go_without_new_unseen_holdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        s4_8,
        "preopen_validate",
        lambda *_args, **_kwargs: pytest.fail(
            "consumed-holdout preopen path must not run"
        ),
    )
    result = recovery.recovery_preopen_validate(ROOT)

    assert result["status"] == "passed"
    assert result["readiness"] == "no_go"
    assert result["blockers"] == [
        "new_unseen_holdout_not_collected_or_bound",
        "evaluator_not_bound_to_new_holdout",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    assert result["criteria_unchanged"] is True
    assert result["planned_take_count"] == 47
    assert result["leakage_group_count"] == 15
    assert not any(result["unseen_holdout_paths_present"].values())
    assert result["grant_creation_authorized"] is False
    assert result["grant_consumption_authorized"] is False
    assert result["evaluation_execution_authorized"] is False
    assert result["new_grant_present"] is False
    assert result["new_ledger_present"] is False
    assert result["holdout_observation_opened"] is False
    assert result["content_derived_values_returned"] is False


def test_preopen_does_not_load_terminal_derived_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original = s4_8.load_json

    def record(path: Path):
        loaded_paths.append(path.resolve())
        return original(path)

    monkeypatch.setattr(s4_8, "load_json", record)
    recovery.recovery_preopen_validate(ROOT)
    amendment = recovery.load_amendment(ROOT)
    derived = {
        (ROOT / run["artifacts"]["derived_terminal_state"]["path"]).resolve()
        for run in amendment["prior_terminal_runs"]
    }

    assert derived.isdisjoint(loaded_paths)


def test_preopen_requires_source_containing_producer_fix() -> None:
    with pytest.raises(s4_8.S48Error, match="does not contain producer fix"):
        recovery.recovery_preopen_validate(
            ROOT,
            source_commit="b0d5575feded9f37316bff8ed4b62483084587bd",
        )


def test_preopen_cli_reports_no_go_without_writing_state() -> None:
    before = recovery.recovery_preopen_validate(ROOT)
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "scripts/run_s4_8_recovery_02.py",
            "--preopen",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report == before
    assert report["readiness"] == "no_go"
    assert report["new_grant_present"] is False
