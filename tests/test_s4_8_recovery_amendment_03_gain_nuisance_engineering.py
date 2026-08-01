from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    canonical_sha256,
)
from scripts import (
    run_s4_8_recovery_03_gain_nuisance_engineering as workflow,
)

ROOT = Path(__file__).resolve().parents[1]


def _contract() -> dict[str, Any]:
    return workflow.load_contract(ROOT, require_base_replay=False)


def _ledger_record(
    *,
    repo_root: Path,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    take: dict[str, Any],
    sequence: int,
    attempt_number: int,
    decision: str,
    previous: str,
) -> dict[str, Any]:
    attempt_root = (
        repo_root
        / contract["campaign"]["root"]
        / "takes"
        / (f"{take['engineering_take_id']}__attempt_{attempt_number:02d}")
    )
    artifacts = (
        {"candidate_seal.json": "a" * 64}
        if decision == "PASS"
        else {"retry_report.json": "b" * 64}
    )
    payload = {
        "schema": workflow.LEDGER_SCHEMA,
        "sequence": sequence,
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "previous_record_sha256": previous,
        "engineering_take_id": take["engineering_take_id"],
        "engineering_take_definition_sha256": take[
            "engineering_take_definition_sha256"
        ],
        "take_number": take["take_number"],
        "attempt_number": attempt_number,
        "decision": decision,
        "authorization_sha256": "c" * 64,
        "attempt_root": attempt_root.relative_to(repo_root).as_posix(),
        "artifact_sha256": artifacts,
    }
    return {**payload, "record_sha256": canonical_sha256(payload)}


def _base_payload(contract: dict[str, Any]) -> dict[str, Any]:
    design = workflow._load_json(ROOT / contract["bindings"]["base_design"]["path"])
    takes = [
        {
            "identity": {"planned_take_id": take["planned_take_id"]},
            "source": "old",
        }
        for take in design["take_order"]
    ]
    return {
        "schema": "ias.s4_8.recovery_02.corrective_metrics.v1",
        "contract": {"test": True},
        "takes": takes,
        "sim_vs_real": [],
    }


def _derived_replacements(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        take["engineering_take_id"]: {
            "identity": {"planned_take_id": take["replacement_planned_take_id"]},
            "source": take["engineering_take_id"],
        }
        for take in contract["campaign"]["takes"]
    }


def _complete_evaluation() -> dict[str, Any]:
    criteria = [
        {
            "criterion_id": f"criterion_{index:02d}",
            "gating": True,
            "passed": True,
        }
        for index in range(17)
    ]
    return {
        "schema": workflow.recovery03.EVALUATION_SCHEMA,
        "status": "passed",
        "readiness_passed": True,
        "failed_gating_criteria": [],
        "criteria": criteria,
        "comparison_classifications": [],
        "categorical_take_results": [],
        "identity_summary": {},
        "config_identity": {},
        "evaluation_error": None,
        "holdout_observations_accessed_by_evaluator": 0,
    }


def test_contract_defines_exact_eight_take_engineering_campaign() -> None:
    contract = _contract()
    takes = contract["campaign"]["takes"]

    assert contract["authority"] == workflow.AUTHORITY_NONE
    assert contract["classification"] == workflow.CLASSIFICATION
    assert [take["target_bearing_deg_f_project"] for take in takes] == [
        0.0,
        90.0,
        180.0,
        270.0,
    ] * 2
    assert [take["playback_gain"] for take in takes] == [0.75] * 4 + [0.35] * 4
    assert [take["realized_condition_id"] for take in takes] == [
        "clean",
        "clean",
        "clean",
        "clean",
        "front_occluded",
        "right_noise",
        "rear_noise",
        "left_occluded",
    ]
    assert all(
        not take["noise"]["enabled"] and not take["occlusion"]["enabled"]
        for take in takes[:4]
    )
    assert takes[4]["occlusion"]["enabled"] is True
    assert takes[5]["noise"]["repetitions"] == 2
    assert takes[6]["noise"]["repetitions"] == 2
    assert takes[7]["occlusion"]["enabled"] is True
    assert len(workflow._take_definitions(contract)) == 8
    assert contract["replay"]["common_old_sequence_indices"] == [
        *range(1, 27),
        35,
        36,
        37,
    ]


def test_ledger_requires_manual_retry_and_backend_uses_frozen_gain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    takes = workflow._take_definitions(contract)
    manifest = {
        "manifest_sha256": "d" * 64,
        "takes": takes,
        "continuous_asset_sha256": "e" * 64,
        "code_head": "f" * 40,
    }
    retry = _ledger_record(
        repo_root=tmp_path,
        contract=contract,
        manifest=manifest,
        take=takes[0],
        sequence=0,
        attempt_number=1,
        decision="RETRY_REQUIRED",
        previous=manifest["manifest_sha256"],
    )
    next_take, next_attempt = workflow._validate_ledger(
        tmp_path,
        contract,
        manifest,
        [retry],
        authenticate_artifacts=False,
    )
    assert next_take == takes[0]
    assert next_attempt == 2
    authorization_payload = {
        "schema": workflow.AUTHORIZATION_SCHEMA,
        "recorded_at_utc": "2026-08-01T00:00:00+00:00",
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "base_code_head": manifest["code_head"],
        "controller_source_sha256": "1" * 64,
        "engineering_take_id": takes[0]["engineering_take_id"],
        "engineering_take_definition_sha256": takes[0][
            "engineering_take_definition_sha256"
        ],
        "take_number": 1,
        "attempt_number": 2,
        "previous_record_sha256": retry["record_sha256"],
        "physical_setup": workflow._physical_setup(takes[0]),
        "automatic_continuation": False,
        "automatic_retry": False,
        "retry_authorized": True,
        "classification": workflow.CLASSIFICATION,
        "authority": workflow.AUTHORITY_NONE,
    }
    authorization = {
        **authorization_payload,
        "authorization_sha256": canonical_sha256(authorization_payload),
    }
    workflow._validate_authorization(
        authorization,
        manifest=manifest,
        take=takes[0],
        attempt_number=2,
        previous_record_sha256=retry["record_sha256"],
    )

    passed = _ledger_record(
        repo_root=tmp_path,
        contract=contract,
        manifest=manifest,
        take=takes[0],
        sequence=1,
        attempt_number=2,
        decision="PASS",
        previous=retry["record_sha256"],
    )
    next_take, next_attempt = workflow._validate_ledger(
        tmp_path,
        contract,
        manifest,
        [retry, passed],
        authenticate_artifacts=False,
    )
    assert next_take == takes[1]
    assert next_attempt == 1

    captured: dict[str, Any] = {}

    def fake_backend(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(
        workflow,
        "RemotePhysicalEngineeringBackend",
        fake_backend,
    )
    config = workflow._load_json(ROOT / workflow.ENGINEERING_CONFIG_PATH)
    backend = workflow._build_backend(
        repo_root=ROOT,
        config=config,
        manifest=manifest,
        take=takes[0],
        attempt_number=2,
    )
    assert backend == captured
    assert captured["playback_gain"] == 0.75
    assert captured["capture_duration_s"] == 20.0
    assert captured["pi_remote_attempt"].endswith("/attempt_02")


def test_compositions_are_exact_29_plus_4_plus_4_and_leave_base_unchanged() -> None:
    contract = _contract()
    base = _base_payload(contract)
    original = copy.deepcopy(base)
    replacements = _derived_replacements(contract)

    clean, clean_provenance = workflow.compose_variant_payload(
        base,
        replacements,
        contract,
        "clean",
    )
    perturbed, perturbed_provenance = workflow.compose_variant_payload(
        base,
        replacements,
        contract,
        "perturbed",
    )

    assert base == original
    assert len(clean["takes"]) == len(perturbed["takes"]) == 37
    assert len(clean_provenance) == len(perturbed_provenance) == 4
    clean_new = {item["replacement_planned_take_id"] for item in clean_provenance}
    perturbed_new = {
        item["replacement_planned_take_id"] for item in perturbed_provenance
    }
    for sequence, old in enumerate(original["takes"], start=1):
        take_id = old["identity"]["planned_take_id"]
        if sequence in contract["replay"]["common_old_sequence_indices"]:
            assert clean["takes"][sequence - 1] == old
            assert perturbed["takes"][sequence - 1] == old
        elif take_id in clean_new:
            assert clean["takes"][sequence - 1]["source"].startswith("s48eng_")
            assert perturbed["takes"][sequence - 1] == old
        elif take_id in perturbed_new:
            assert perturbed["takes"][sequence - 1]["source"].startswith("s48eng_")
            assert clean["takes"][sequence - 1] == old
        else:  # pragma: no cover - the frozen 37-take partition is exhaustive
            raise AssertionError(take_id)

    missing = copy.deepcopy(replacements)
    missing.pop(contract["campaign"]["takes"][0]["engineering_take_id"])
    with pytest.raises(
        workflow.GainNuisanceEngineeringError,
        match="replacement is unavailable",
    ):
        workflow.compose_variant_payload(base, missing, contract, "clean")


def test_two_stub_evaluations_are_complete_without_scientific_evaluator() -> None:
    calls: list[str] = []
    payloads = {
        "clean": {"variant": "clean"},
        "perturbed": {"variant": "perturbed"},
    }

    def stub(payload: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
        assert repo_root == ROOT
        calls.append(payload["variant"])
        return _complete_evaluation()

    results = workflow.evaluate_variants(
        payloads,
        repo_root=ROOT,
        evaluator=stub,
    )

    assert calls == ["clean", "perturbed"]
    assert set(results) == {"clean", "perturbed"}
    assert all(
        result["evaluation_invocation_count"] == 1 for result in results.values()
    )


def test_hash_mismatch_and_existing_output_fail_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "attempt" / "gate_report.json"
    artifact.parent.mkdir()
    artifact.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        workflow.GainNuisanceEngineeringError,
        match="artifact hash mismatch",
    ):
        workflow._validate_artifact_hashes(
            tmp_path,
            {
                "attempt_root": "attempt",
                "artifact_sha256": {"gate_report.json": "0" * 64},
            },
        )

    contract = _contract()
    destination = tmp_path / contract["replay"]["output_root"]
    destination.mkdir(parents=True)
    with pytest.raises(
        workflow.GainNuisanceEngineeringError,
        match="output already exists",
    ):
        workflow._replay_destination(tmp_path, contract)
