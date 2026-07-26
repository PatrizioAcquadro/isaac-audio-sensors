"""Deterministic package tests for the S4.7 preregistration evidence machinery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition.s4_7 import (
    ACCEPTANCE_SCHEMA,
    OUTPUT_PATH,
    REQUIRED_FILES,
    build_evidence_package,
    validate_evidence_package,
)

ROOT = Path(__file__).resolve().parents[1]
DUMMY_COMMIT = "0" * 40


def _build(target: Path) -> dict[str, Any]:
    return build_evidence_package(
        repo_root=ROOT,
        output=target,
        source_commit=DUMMY_COMMIT,
        source_tree_replay=True,
    )


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_contains_exactly_the_required_files(tmp_path: Path) -> None:
    target = tmp_path / "package"
    result = _build(target)

    assert result["status"] == "passed"
    assert {path.name for path in target.iterdir()} == REQUIRED_FILES
    assert _json(target / "final_validation.json")["status"] == "passed"


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _build(first)
    _build(second)

    for name in REQUIRED_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_checksum_manifest_covers_every_other_file(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    listed: dict[str, str] = {}
    for line in (target / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest

    assert set(listed) == REQUIRED_FILES - {"SHA256SUMS"}
    for name, digest in listed.items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest


def test_rebuilding_into_a_populated_directory_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)

    with pytest.raises(ValueError, match="evidence output must be empty"):
        _build(target)


def test_fail_closed_matrix_records_executed_outcomes(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    matrix = _json(target / "fail_closed_matrix.json")

    assert matrix["status"] == "passed"
    assert matrix["case_count"] >= 25
    identifiers = [case["case_id"] for case in matrix["cases"]]
    assert len(identifiers) == len(set(identifiers))
    for case in matrix["cases"]:
        assert case["status"] == "passed", case["case_id"]
        assert case["actual"] == case["expected"], case["case_id"]
        assert case["detail"].strip(), case["case_id"]
        assert case["detail"] != "covered_by_focused_executable_tests"
    assert {
        "missing_observable",
        "counter_denominator_mismatch",
        "unexpected_observable",
        "config_status_not_frozen",
        "config_declares_opening_workflow",
        "absolute_config_path",
    } <= set(identifiers)


def test_no_evidence_file_embeds_a_machine_specific_path(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    machine_paths = (str(ROOT), str(tmp_path), "/tmp/", "/home/")

    for path in sorted(target.iterdir()):
        text = path.read_text(encoding="utf-8")
        for fragment in machine_paths:
            assert fragment not in text, f"{path.name} embeds {fragment}"


def test_interlock_artifact_matches_the_frozen_grant_contract(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    acceptance = _json(target / "holdout_acceptance.json")

    assert acceptance["schema"] == ACCEPTANCE_SCHEMA == "ias.s4_7.holdout_acceptance.v1"
    assert acceptance["status"] == "passed"
    assert acceptance["authorizes_holdout_opening"] is False
    assert acceptance["grant_still_required_for_s4_8"] is True
    assert acceptance["holdout_observations_accessed"] == 0
    assert acceptance["holdout_access_grant_created"] is False
    assert acceptance["readiness_criterion_count"] == 23
    assert (
        acceptance["criteria_config_sha256"]
        == hashlib.sha256(
            (ROOT / "configs/s4_7_holdout_acceptance.v1.json").read_bytes()
        ).hexdigest()
    )


def test_historical_v1_artifact_cannot_satisfy_corrective_interlock(
    tmp_path: Path,
) -> None:
    from isaac_audio_sensors.acquisition.s4_4 import (
        S44Error,
        canonical_sha256,
        consume_s4_8_grant,
        sha256_file,
    )

    target = tmp_path / "package"
    _build(target)
    prerequisite = target / "holdout_acceptance.json"
    seal = tmp_path / "seal.json"
    seal.write_text('{"schema": "test.seal"}\n', encoding="utf-8")
    ledger = tmp_path / "access_ledger.jsonl"

    payload = {
        "schema": "ias.s4_4.holdout_access_grant.v1",
        "grant_id": "s4_7_interlock_check",
        "purpose": "S4.8_evaluation",
        "seal_sha256": sha256_file(seal),
        "split_plan_sha256": "0" * 64,
        "prerequisite": {
            "path": prerequisite.as_posix(),
            "sha256": sha256_file(prerequisite),
            "schema": ACCEPTANCE_SCHEMA,
            "status": "passed",
        },
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    grant = tmp_path / "grant.json"
    grant.write_text(
        json.dumps({**payload, "grant_sha256": canonical_sha256(payload)}),
        encoding="utf-8",
    )

    with pytest.raises(S44Error, match="prerequisite authentication failed"):
        consume_s4_8_grant(
            grant,
            seal_path=seal,
            split_plan_sha256="0" * 64,
            prerequisite_path=prerequisite,
            ledger_path=ledger,
            event_time_utc="2026-07-24T00:00:00+00:00",
        )


def test_evidence_declares_the_preserved_prior_phase_trees(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    preservation = _json(target / "preservation_phase_boundary_report.json")

    assert preservation["status"] == "passed"
    assert preservation["holdout_observations_accessed"] == 0
    assert preservation["s4_8_access_grant_created"] is False
    assert preservation["later_phases_started"] == []
    assert preservation["s4_8_started"] is False
    assert preservation["s4_9_started"] is False
    assert preservation["dataset_accessed"] is False


def test_blindness_attestation_names_only_development_evidence(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    blindness = _json(target / "blindness_attestation.json")

    assert blindness["status"] == "passed"
    assert blindness["holdout_observations_accessed"] == 0
    assert blindness["holdout_opening_workflow_implemented"] is False
    assert blindness["later_phase_artifacts_present"] == []
    assert blindness["threshold_evidence_kind"] == "development_fit_and_pilot_only"
    assert blindness["enforcement_limitation"].strip()


def test_synthetic_evaluation_proves_the_gate_executes(tmp_path: Path) -> None:
    target = tmp_path / "package"
    _build(target)
    synthetic = _json(target / "synthetic_evaluation_report.json")

    assert synthetic["status"] == "passed"
    assert synthetic["fixtures_are_synthetic"] is True
    assert synthetic["gate_bites"] is True
    assert synthetic["stretch_tier_is_independent"] is True
    assert synthetic["conforming_evaluation"]["readiness_passed"] is True
    assert synthetic["violating_evaluation"]["readiness_passed"] is False


@pytest.mark.skipif(
    not (ROOT / OUTPUT_PATH / "provenance.json").is_file(),
    reason="the canonical S4.7 package is not present",
)
def test_committed_package_passes_tracked_validation() -> None:
    report = validate_evidence_package(
        ROOT,
        OUTPUT_PATH,
        require_tracked=True,
        require_committed=True,
    )
    assert report["issues"] == []
    assert report["status"] == "passed"
