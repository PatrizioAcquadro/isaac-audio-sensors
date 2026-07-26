"""S4.4 constrained split, seal, access, and integrity tests."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import scripts.validate_s4_4_integrity as s44_validator
from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    append_ledger_event,
    build_assignment_companion,
    build_coverage_report,
    build_holdout_seal,
    build_source_checkpoint_contract,
    build_trial_census,
    canonical_sha256,
    consume_s4_8_grant,
    find_first_valid_seed,
    hash_only_holdout_integrity,
    require_evidence_access,
    select_constraint_aware_split,
    validate_adapter_contract,
    validate_holdout_manifest_content,
    validate_holdout_seal,
    validate_ledger,
    validate_preseed_contract,
    validate_provenance_source_checkpoint,
    validate_source_checkpoint_contract,
)
from isaac_audio_sensors.core.dataset.splits import (
    SplitPlan,
    build_split_plan,
    verify_no_leakage,
)
from scripts.build_s4_4_evidence import build as build_evidence
from scripts.validate_s4_4_integrity import validate as validate_evidence
from tests.test_dataset_splits import _multi_group_manifest

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS_PATH = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
    "preseed_coverage_constraints.json"
)
ALGORITHM_PATH = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
    "constraint_adapter_algorithm.v1.json"
)
INVENTORY_PATH = ROOT / "outputs/isaac_audio_sensors/S4/S4.3/trial_inventory.json"
S43_INDEX_PATH = ROOT / "outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json"
SOURCE_CHECKPOINT_PATH = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/freeze/source_checkpoint.v1.json"
)
SOURCE_PATHS = (
    "scripts/build_s4_4_evidence.py",
    "scripts/validate_s4_4_integrity.py",
    "src/isaac_audio_sensors/acquisition/s4_4.py",
    "tests/test_s4_4_holdout_freeze.py",
)
FROZEN_INPUT_PATHS = (
    "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
    "constraint_adapter_algorithm.v1.json",
    "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
    "preseed_coverage_constraints.json",
    "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
    "s2_5_constraint_feasibility.json",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _contracts() -> tuple[dict, dict]:
    return _json(CONSTRAINTS_PATH), _json(ALGORITHM_PATH)


def _selection(seed: int = 0):
    constraints, algorithm = _contracts()
    return select_constraint_aware_split(constraints, algorithm, seed=seed)


def _self_hashed_grant(
    *, seal_sha256: str, split_plan_sha256: str, prerequisite: Path
) -> dict:
    payload = {
        "schema": "ias.s4_4.holdout_access_grant.v1",
        "grant_id": "synthetic_test_grant",
        "purpose": "S4.8_evaluation",
        "seal_sha256": seal_sha256,
        "split_plan_sha256": split_plan_sha256,
        "prerequisite": {
            "path": prerequisite.as_posix(),
            "sha256": hashlib.sha256(prerequisite.read_bytes()).hexdigest(),
            "schema": "ias.s4_7.holdout_acceptance.v1",
            "status": "passed",
        },
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    payload["grant_sha256"] = canonical_sha256(payload)
    return payload


def test_frozen_contracts_validate_and_contain_no_assignment() -> None:
    constraints, algorithm = _contracts()
    validate_preseed_contract(constraints, repo_root=ROOT)
    validate_adapter_contract(algorithm, constraints, repo_root=ROOT)
    assert constraints["seed"] is None
    assert constraints["assignments"] is None
    assert algorithm["seed"] is None
    assert algorithm["selected_groups"] is None
    assert algorithm["adapter"]["standard_s2_5_builder_modified"] is False


def test_seed_zero_assignment_is_deterministic_and_round_trips() -> None:
    first = _selection()
    repeated = _selection()
    assert first == repeated
    assert first.seed == 0
    assert first.plan.plan_sha256 == (
        "1569c00cbaec57e5625e0876fd243e17a2a67b287b3edf9865e41bb7ce8c0ce3"
    )
    assert first.plan.assignments["holdout"] == (
        "g01_mac_reference_left_baseline",
        "g03_mac_reference_opposite",
        "g08_mac_reference_rear_near",
    )
    restored = SplitPlan.from_dict(json.loads(first.plan.serialize()))
    assert restored == first.plan
    assert verify_no_leakage(restored)


def test_changed_seed_changes_constraint_aware_assignment() -> None:
    assert _selection(seed=1).plan.plan_sha256 != _selection(seed=0).plan.plan_sha256
    assert _selection(seed=1).plan.assignments != _selection(seed=0).plan.assignments


def test_seed_zero_is_first_valid_and_selected_subset_is_globally_optimal() -> None:
    constraints, algorithm = _contracts()
    selection = find_first_valid_seed(
        constraints, algorithm, maximum_seed=10, expected_seed=0
    )
    assert selection.seed == 0
    assert selection.subset_count == 512
    assert selection.feasible_subset_count == 188
    assert selection.ranking_key[:3] == (2, 0, 3)
    assert selection.global_optimum_verified
    assert selection.coverage["quality_eligible_repeatability_cells"] == 4
    assert selection.coverage["quality_eligible_controlled_cells"] == 1
    assert selection.coverage["quality_eligible_robustness_cells"] == 1


def test_invalid_or_missing_group_metadata_fails_closed() -> None:
    constraints, algorithm = _contracts()
    missing = copy.deepcopy(constraints)
    del missing["group_mapping"][0]["source_type"]
    with pytest.raises(S44Error, match="source_type"):
        validate_preseed_contract(missing, repo_root=ROOT, verify_bindings=False)

    invalid = copy.deepcopy(constraints)
    invalid["group_mapping"][0]["bearing_deg_f_project"] = float("nan")
    with pytest.raises(S44Error, match="finite"):
        validate_preseed_contract(invalid, repo_root=ROOT, verify_bindings=False)

    unknown = copy.deepcopy(algorithm)
    unknown["fixed_inputs"]["grouping_key"] = "unknown_grouping"
    with pytest.raises(S44Error, match="grouping_key"):
        validate_adapter_contract(
            unknown, constraints, repo_root=ROOT, verify_bindings=False
        )

    unknown_trial = copy.deepcopy(constraints)
    unknown_trial["group_mapping"][0]["trial_ids"][0] = "unknown_trial"
    with pytest.raises(S44Error, match="unknown trial group"):
        build_trial_census(
            _json(INVENTORY_PATH),
            unknown_trial,
            _selection(),
        )


def test_census_retains_every_attempt_and_separates_ineligibility() -> None:
    constraints, _ = _contracts()
    census = build_trial_census(_json(INVENTORY_PATH), constraints, _selection())
    attempts = census["attempts"]
    assert len(attempts) == 18
    assert census["counts"] == {
        "attempts": 18,
        "condition_cells": 16,
        "quality_eligible_condition_cells": 15,
        "quality_ineligible_condition_cells": 1,
        "retained_failed_attempts": 3,
    }
    failed = [item for item in attempts if not item["usable_coverage"]]
    assert len(failed) == 3
    assert {item["eligibility_reason"] for item in failed} == {
        "pre_recording_failure_no_usable_capture",
        "quality_failure_invalid_capture",
    }
    assert all(item["group_id"] for item in attempts)
    assert all(item["partition"] in {"fit", "holdout"} for item in attempts)


def test_coverage_reports_nominal_achieved_and_every_axis_overlap() -> None:
    constraints, _ = _contracts()
    report = build_coverage_report(constraints, _selection())
    assert report["nominal_condition_cell_counts"] == {"fit": 12, "holdout": 4}
    assert report["achieved_condition_cell_counts"] == {"fit": 10, "holdout": 6}
    assert report["achieved_condition_cell_proportions"] == {
        "fit": 0.625,
        "holdout": 0.375,
    }
    required_axes = {
        "scientific_session_id",
        "room_id",
        "source_device",
        "source_type",
        "source_identity",
        "position_m_f_project",
        "bearing_deg_f_project",
        "distance_m",
        "mounting_condition",
        "acoustic_condition",
    }
    assert set(report["axes"]) == required_axes
    assert (
        "reference_wav" in report["axes"]["source_type"]["overlap_values"]
    )
    assert report["claim_limits"]["heldout_cross_source_generalization"] is False
    assert report["claim_limits"]["heldout_cross_device_generalization"] is False
    assert set(report["claim_limits"]["fit_only_source_types"]) == {
        "silence",
        "standardized_voice_phrase",
        "reference_wav_plus_standardized_voice",
        "visible_audible_ordinary_object_impact",
    }
    assert "occlusion" in report["claim_limits"]["fit_only_conditions"]


def test_companion_binds_algorithm_population_plan_and_achieved_ratio() -> None:
    constraints, algorithm = _contracts()
    selection = _selection()
    companion = build_assignment_companion(constraints, algorithm, selection)
    assert companion["adapter"]["assignment_producer"] == (
        "S4.4 constraint-aware adapter"
    )
    assert companion["seed"] == 0
    assert companion["split_plan_sha256"] == selection.plan.plan_sha256
    assert companion["achieved_condition_cell_counts"] == {"fit": 10, "holdout": 6}
    assert companion["optimization"]["global_optimum_verified"] is True
    assert companion["outcome_metrics_used"] is False


def test_seal_contains_only_metadata_hashes_and_detects_tamper() -> None:
    constraints, _ = _contracts()
    selection = _selection()
    census = build_trial_census(_json(INVENTORY_PATH), constraints, selection)
    seal = build_holdout_seal(
        constraints,
        selection,
        census,
        _json(S43_INDEX_PATH),
    )
    encoded = json.dumps(seal, sort_keys=True)
    for forbidden in (
        "absolute_bearing_error",
        "confidence",
        "sector_accuracy",
        "tdoa_error",
        "raw_media_bytes",
    ):
        assert forbidden not in encoded
    validate_holdout_seal(seal, selection.plan)
    tampered = copy.deepcopy(seal)
    tampered["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(S44Error, match="seal payload hash"):
        validate_holdout_seal(tampered, selection.plan)


def test_hash_only_integrity_reports_status_only_and_detects_raw_changes(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.wav"
    raw.write_bytes(b"held-out-synthetic-bytes")
    seal = {
        "schema": "ias.s4_4.holdout_seal.v1",
        "status": "sealed",
        "split_plan_sha256": "a" * 64,
        "holdout_group_ids": ["g_holdout"],
        "holdout_attempt_ids": ["attempt_holdout"],
        "artifacts": [
            {
                "attempt_id": "attempt_holdout",
                "path": "raw.wav",
                "role": "six_channel_audio",
                "byte_size": raw.stat().st_size,
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            }
        ],
        "access_policy": {"state": "sealed"},
    }
    seal["seal_payload_sha256"] = canonical_sha256(seal)
    result = hash_only_holdout_integrity(seal, repo_root=tmp_path)
    assert result == {
        "schema": "ias.s4_4.hash_only_integrity.v1",
        "status": "passed",
        "checked_artifact_count": 1,
        "issues": [],
        "holdout_opened": False,
        "content_derived_values_returned": False,
    }
    raw.write_bytes(b"tampered")
    assert hash_only_holdout_integrity(seal, repo_root=tmp_path)["status"] == "failed"
    raw.unlink()
    result = hash_only_holdout_integrity(seal, repo_root=tmp_path)
    assert result["status"] == "failed"
    assert result["issues"][0]["code"] == "missing_file"


def test_holdout_fitting_and_unknown_access_fail_closed() -> None:
    seal = {
        "status": "sealed",
        "holdout_attempt_ids": ["holdout_attempt"],
        "fit_attempt_ids": ["fit_attempt"],
    }
    assert require_evidence_access(
        seal, attempt_id="fit_attempt", purpose="S4.5_fit"
    )["mode"] == "fit_only"
    with pytest.raises(S44Error, match="holdout access denied"):
        require_evidence_access(
            seal, attempt_id="holdout_attempt", purpose="S4.5_fit"
        )
    with pytest.raises(S44Error, match="unknown attempt"):
        require_evidence_access(seal, attempt_id="unknown", purpose="S4.5_fit")
    with pytest.raises(S44Error, match="unknown purpose"):
        require_evidence_access(seal, attempt_id="fit_attempt", purpose="tune")


def test_grants_fail_on_malformed_purpose_and_historical_stub_prerequisite(
    tmp_path: Path,
) -> None:
    seal = tmp_path / "seal.json"
    seal.write_text('{"schema":"ias.s4_4.holdout_seal.v1"}\n', encoding="utf-8")
    seal_sha = hashlib.sha256(seal.read_bytes()).hexdigest()
    prerequisite = tmp_path / "s4_7.json"
    prerequisite.write_text(
        '{"schema":"ias.s4_7.holdout_acceptance.v1","status":"passed"}\n',
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    grant_path = tmp_path / "grant.json"
    grant = _self_hashed_grant(
        seal_sha256=seal_sha,
        split_plan_sha256="b" * 64,
        prerequisite=prerequisite,
    )

    malformed = copy.deepcopy(grant)
    del malformed["single_use"]
    grant_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(S44Error, match="grant fields"):
        consume_s4_8_grant(
            grant_path,
            seal_path=seal,
            split_plan_sha256="b" * 64,
            prerequisite_path=prerequisite,
            ledger_path=ledger,
            event_time_utc="2030-01-01T00:00:00Z",
        )

    wrong = copy.deepcopy(grant)
    wrong["purpose"] = "S4.5_fit"
    wrong["grant_sha256"] = canonical_sha256(
        {key: value for key, value in wrong.items() if key != "grant_sha256"}
    )
    grant_path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(S44Error, match="purpose"):
        consume_s4_8_grant(
            grant_path,
            seal_path=seal,
            split_plan_sha256="b" * 64,
            prerequisite_path=prerequisite,
            ledger_path=ledger,
            event_time_utc="2030-01-01T00:00:00Z",
        )

    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(S44Error, match="prerequisite authentication failed"):
        consume_s4_8_grant(
            grant_path,
            seal_path=seal,
            split_plan_sha256="b" * 64,
            prerequisite_path=prerequisite,
            ledger_path=ledger,
            event_time_utc="2030-01-01T00:00:00Z",
        )


def test_ledger_chain_tampering_fails_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    append_ledger_event(
        ledger,
        {
            "event": "integrity_validation",
            "seal_sha256": "a" * 64,
            "event_time_utc": "2030-01-01T00:00:00Z",
            "holdout_opened": False,
        },
    )
    append_ledger_event(
        ledger,
        {
            "event": "integrity_validation",
            "seal_sha256": "a" * 64,
            "event_time_utc": "2030-01-01T00:00:01Z",
            "holdout_opened": False,
        },
    )
    assert validate_ledger(ledger, expected_seal_sha256="a" * 64)["status"] == (
        "passed"
    )
    rows = ledger.read_text(encoding="utf-8").splitlines()
    record = json.loads(rows[0])
    record["event"] = "holdout_open"
    rows[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert validate_ledger(ledger, expected_seal_sha256="a" * 64)["status"] == (
        "failed"
    )


def test_standard_s2_5_builder_behavior_remains_unchanged() -> None:
    plan = build_split_plan(
        _multi_group_manifest(),
        kind="fit_holdout",
        ratios={"fit": 0.8, "holdout": 0.2},
        seed=41,
    )
    assert plan.plan_sha256 == (
        "cd4fb84b58cc9364711c2f302f290d6050fdf18a2ab8b86617ce151a21c5b30e"
    )
    assert verify_no_leakage(plan)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _copy_repo_file(repo: Path, relative: str) -> None:
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / relative, destination)


def _prepare_synthetic_final_checkout(repo: Path) -> tuple[str, str, Path]:
    constraints = _json(CONSTRAINTS_PATH)
    algorithm = _json(ALGORITHM_PATH)
    paths = {
        *SOURCE_PATHS,
        *FROZEN_INPUT_PATHS,
        "docs/development/closeouts/S4/s4_4_holdout_freeze.md",
        "outputs/isaac_audio_sensors/S4/S4.3/trial_inventory.json",
        "outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json",
    }
    paths.update(record["path"] for record in constraints["source_identities"])
    paths.update(
        record["path"]
        for record in algorithm["bindings"].values()
        if isinstance(record, dict) and "path" in record
    )
    repo.mkdir(parents=True)
    for relative in sorted(paths):
        _copy_repo_file(repo, relative)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "S4.4 Test")
    _git(repo, "config", "user.email", "s4.4-test@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "source checkpoint")
    source_commit = _git(repo, "rev-parse", "HEAD")
    checkpoint = build_source_checkpoint_contract(
        repo_root=repo,
        branch="main",
        commit=source_commit,
        source_paths=SOURCE_PATHS,
        frozen_input_paths=FROZEN_INPUT_PATHS,
    )
    checkpoint_path = repo / (
        "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
        "source_checkpoint.v1.json"
    )
    checkpoint_path.write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    closeout = repo / "docs/development/closeouts/S4/s4_4_holdout_freeze.md"
    closeout.write_text(
        closeout.read_text(encoding="utf-8")
        + "\nSynthetic delivery checkpoint for regression testing.\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "final delivery checkout")
    final_commit = _git(repo, "rev-parse", "HEAD")
    return source_commit, final_commit, checkpoint_path


def _build_temp_evidence(
    output: Path, *, repo_root: Path, source_checkpoint_path: Path
) -> None:
    build_evidence(
        output=output,
        constraints_path=(
            repo_root
            / "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
            "preseed_coverage_constraints.json"
        ),
        feasibility_path=(
            repo_root
            / "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
            "s2_5_constraint_feasibility.json"
        ),
        algorithm_path=(
            repo_root
            / "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
            "constraint_adapter_algorithm.v1.json"
        ),
        inventory_path=(
            repo_root / "outputs/isaac_audio_sensors/S4/S4.3/trial_inventory.json"
        ),
        s43_index_path=(
            repo_root / "outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json"
        ),
        source_checkpoint_path=source_checkpoint_path,
        initialize_access_state=False,
        repo_root=repo_root,
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_builder_is_byte_deterministic_and_validator_is_raw_independent(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source_commit, final_commit, checkpoint_path = (
        _prepare_synthetic_final_checkout(repo)
    )
    first = repo / "first"
    second = repo / "second"
    _build_temp_evidence(
        first, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    _build_temp_evidence(
        second, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    assert _tree_bytes(first) == _tree_bytes(second)
    result = validate_evidence(
        first / "evidence_index.json",
        repo_root=repo,
        require_machine_local=False,
        require_final=False,
        require_tracked=False,
        record_integrity_event=False,
    )
    assert result["status"] == "passed"
    assert result["machine_local_hash_only"] is None
    assert result["holdout_opened"] is False
    provenance = _json(first / "provenance.json")
    assert provenance["status"] == "frozen_source_checkpoint"
    assert provenance["final_source_commit_pending"] is False
    assert provenance["source_checkpoint_commit"] == source_commit
    assert provenance["source_checkpoint_commit"] != final_commit
    checkpoint = _json(checkpoint_path)
    validate_source_checkpoint_contract(
        checkpoint,
        repo_root=repo,
        expected_source_paths=SOURCE_PATHS,
        expected_frozen_input_paths=FROZEN_INPUT_PATHS,
    )
    validate_provenance_source_checkpoint(
        provenance,
        checkpoint,
        checkpoint_path=(
            "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
            "source_checkpoint.v1.json"
        ),
        checkpoint_file_sha256=hashlib.sha256(
            checkpoint_path.read_bytes()
        ).hexdigest(),
    )
    substituted = copy.deepcopy(provenance)
    substituted["source_checkpoint_commit"] = final_commit
    with pytest.raises(S44Error, match="exact source checkpoint"):
        validate_provenance_source_checkpoint(
            substituted,
            checkpoint,
            checkpoint_path=(
                "outputs/isaac_audio_sensors/S4/S4.4/freeze/"
                "source_checkpoint.v1.json"
            ),
            checkpoint_file_sha256=hashlib.sha256(
                checkpoint_path.read_bytes()
            ).hexdigest(),
        )
    assert {item["path"] for item in provenance["implementation"]} == {
        "scripts/build_s4_4_evidence.py",
        "scripts/validate_s4_4_integrity.py",
        "src/isaac_audio_sensors/acquisition/s4_4.py",
        "tests/test_s4_4_holdout_freeze.py",
    }
    assert provenance["delivery_documents"][0]["path"] == (
        "docs/development/closeouts/S4/s4_4_holdout_freeze.md"
    )


def test_source_checkpoint_rejects_contract_and_checkpoint_content_tamper(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _, _, checkpoint_path = _prepare_synthetic_final_checkout(repo)
    checkpoint = _json(checkpoint_path)
    tampered = copy.deepcopy(checkpoint)
    tampered["source_artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(S44Error, match="contract hash"):
        validate_source_checkpoint_contract(
            tampered,
            repo_root=repo,
            expected_source_paths=SOURCE_PATHS,
            expected_frozen_input_paths=FROZEN_INPUT_PATHS,
        )

    source = repo / SOURCE_PATHS[0]
    source.write_text(source.read_text(encoding="utf-8") + "\n# tampered\n")
    with pytest.raises(S44Error, match="working checkout"):
        validate_source_checkpoint_contract(
            checkpoint,
            repo_root=repo,
            expected_source_paths=SOURCE_PATHS,
            expected_frozen_input_paths=FROZEN_INPUT_PATHS,
        )


def test_holdout_manifest_declares_quality_metadata_not_performance_metrics(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _, _, checkpoint_path = _prepare_synthetic_final_checkout(repo)
    output = repo / "evidence"
    _build_temp_evidence(
        output, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    manifest = _json(output / "holdout_manifest.json")
    declarations = manifest["content_declarations"]
    assert declarations == {
        "historical_s4_3_quality_and_lifecycle_metadata_included": True,
        "included_attempt_metadata_fields": [
            "eligibility_reason",
            "lifecycle_state",
            "outcome",
            "quality_status",
            "usable_coverage",
        ],
        "performance_metrics_included": False,
        "raw_or_analysis_payload_included": False,
        "assignment_used_outcome_metrics": False,
    }
    validate_holdout_manifest_content(manifest)

    misleading = copy.deepcopy(manifest)
    misleading["content_declarations"][
        "historical_s4_3_quality_and_lifecycle_metadata_included"
    ] = False
    with pytest.raises(S44Error, match="quality and lifecycle"):
        validate_holdout_manifest_content(misleading)

    metric_leak = copy.deepcopy(manifest)
    metric_leak["attempts"][0]["median_bearing_error_deg"] = 1.0
    with pytest.raises(S44Error, match="performance metric"):
        validate_holdout_manifest_content(metric_leak)


def test_closeout_documents_valid_dist_kit_pack_rebuild_order() -> None:
    closeout = (
        ROOT / "docs/development/closeouts/S4/s4_4_holdout_freeze.md"
    ).read_text(encoding="utf-8")
    commands = (
        "make build\n",
        "make build-kit\n",
        "make audit-kit\n",
        (
            "make build-pack "
            "WHEELHOUSE=/tmp/ias-s4-3-wheelhouse-Yqs1Oh\n"
        ),
        "make audit-pack\n",
    )
    positions = [closeout.index(command) for command in commands]
    assert positions == sorted(positions)
    assert "outputs/isaac_audio_sensors/S4/S4.3/validation/" in closeout
    assert "repository_validation.json" in closeout
    assert "unavailable" in closeout
    assert "blocker" in closeout


def test_machine_local_mode_fails_closed_when_raw_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _, _, checkpoint_path = _prepare_synthetic_final_checkout(repo)
    output = repo / "evidence"
    _build_temp_evidence(
        output, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    monkeypatch.setattr(
        s44_validator,
        "hash_only_holdout_integrity",
        lambda *_args, **_kwargs: {
            "schema": "ias.s4_4.hash_only_integrity.v1",
            "status": "failed",
            "checked_artifact_count": 0,
            "issues": [
                {
                    "code": "missing_file",
                    "path": "dataset/S4.3/raw.wav",
                    "message": "file absent",
                }
            ],
            "holdout_opened": False,
            "content_derived_values_returned": False,
        },
    )
    result = validate_evidence(
        output / "evidence_index.json",
        repo_root=repo,
        require_machine_local=True,
        require_final=False,
        require_tracked=False,
        record_integrity_event=False,
    )
    assert result["status"] == "failed"
    assert result["issues"][0]["code"] == "missing_file"
    assert result["holdout_opened"] is False
    assert result["content_derived_values_returned"] is False


def test_validator_detects_manifest_tamper_missing_file_and_split_crossing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _, _, checkpoint_path = _prepare_synthetic_final_checkout(repo)
    output = repo / "evidence"
    _build_temp_evidence(
        output, repo_root=repo, source_checkpoint_path=checkpoint_path
    )

    coverage = output / "coverage_report.json"
    payload = _json(coverage)
    payload["achieved_condition_cell_counts"] = {"fit": 9, "holdout": 7}
    coverage.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_evidence(
        output / "evidence_index.json",
        repo_root=repo,
        require_machine_local=False,
        require_final=False,
        require_tracked=False,
        record_integrity_event=False,
    )
    assert result["status"] == "failed"
    assert {issue["code"] for issue in result["issues"]} >= {
        "artifact_hash_mismatch",
        "coverage_counts_invalid",
        "coverage_inconsistent",
    }

    shutil.rmtree(output)
    _build_temp_evidence(
        output, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    (output / "fit_manifest.json").unlink()
    result = validate_evidence(
        output / "evidence_index.json",
        repo_root=repo,
        require_machine_local=False,
        require_final=False,
        require_tracked=False,
        record_integrity_event=False,
    )
    assert "missing_artifact" in {issue["code"] for issue in result["issues"]}

    shutil.rmtree(output)
    _build_temp_evidence(
        output, repo_root=repo, source_checkpoint_path=checkpoint_path
    )
    plan_path = output / "split_plan.json"
    plan = _json(plan_path)
    plan["assignments"]["fit"].append(plan["assignments"]["holdout"][0])
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result = validate_evidence(
        output / "evidence_index.json",
        repo_root=repo,
        require_machine_local=False,
        require_final=False,
        require_tracked=False,
        record_integrity_event=False,
    )
    assert "split_plan_invalid" in {
        issue["code"] for issue in result["issues"]
    }


def test_s4_5_and_s4_8_are_unstarted_and_no_real_grant_exists() -> None:
    assert not (ROOT / "outputs/isaac_audio_sensors/S4/S4.5").exists()
    assert not (ROOT / "outputs/isaac_audio_sensors/S4/S4.8").exists()
    assert not (
        ROOT / "dataset/S4.4/access/holdout_access_grant.json"
    ).exists()
