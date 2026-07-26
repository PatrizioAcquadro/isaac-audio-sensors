#!/usr/bin/env python3
"""Validate tracked and optional machine-local S4.4 freeze integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    append_ledger_event,
    build_coverage_report,
    hash_only_holdout_integrity,
    load_json,
    sha256_file,
    validate_adapter_contract,
    validate_holdout_manifest_content,
    validate_holdout_seal,
    validate_ledger,
    validate_preseed_contract,
    validate_provenance_source_checkpoint,
    validate_source_checkpoint_contract,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic
from isaac_audio_sensors.core.dataset.splits import SplitPlan, verify_no_leakage

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.4")
DEFAULT_INDEX = ROOT / CANONICAL_OUTPUT / "evidence_index.json"
MEDIA_SUFFIXES = {".wav", ".svo", ".svo2", ".png", ".jpg", ".jpeg", ".mp4"}
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


def _problem(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _resolve_artifact(
    relative: str, *, repo_root: Path, evidence_root: Path
) -> Path:
    prefix = CANONICAL_OUTPUT.as_posix() + "/"
    if relative.startswith(prefix):
        return evidence_root / relative[len(prefix) :]
    return repo_root / relative


def _read_checksum_manifest(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            raise S44Error(f"{path}:{number}: malformed checksum record")
        digest, relative = line.split("  ", 1)
        if relative in records:
            raise S44Error(f"{path}:{number}: duplicate path {relative}")
        records[relative] = digest
    return records


def _git_tracked(repo_root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _git_blob(repo_root: Path, commit: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", "--no-ext-diff", f"{commit}:{relative}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S44Error(
            f"historical source artifact absent from {commit}: {relative}"
        )
    return result.stdout


def validate(
    index_path: Path,
    *,
    repo_root: Path,
    require_machine_local: bool,
    require_final: bool,
    require_tracked: bool,
    record_integrity_event: bool,
) -> dict[str, Any]:
    """Validate S4.4 without raw media unless explicitly requested."""

    issues: list[dict[str, str]] = []
    repo_root = repo_root.resolve()
    evidence_root = index_path.resolve().parent
    if require_final and index_path.resolve() != (
        repo_root / CANONICAL_OUTPUT / "evidence_index.json"
    ).resolve():
        raise S44Error("final S4.4 index must use the canonical repository path")
    index = load_json(index_path)
    source_checkpoint_path = evidence_root / "freeze/source_checkpoint.v1.json"
    source_checkpoint = load_json(source_checkpoint_path)
    historical_source_commit = str(
        source_checkpoint.get("source_checkpoint_commit", "")
    )
    if index.get("schema") != "ias.s4_4.evidence_index.v1":
        issues.append(_problem("wrong_index_schema", str(index_path), "unexpected"))
    if index.get("status") != "passed":
        issues.append(_problem("index_not_passed", str(index_path), "unexpected"))
    if index.get("s4_5_started") is not False:
        issues.append(_problem("s4_5_started", str(index_path), "must be false"))
    if index.get("s4_8_grant_created") is not False:
        issues.append(
            _problem("s4_8_grant_created", str(index_path), "must be false")
        )
    if index.get("holdout_opened") is not False:
        issues.append(_problem("holdout_opened", str(index_path), "must be false"))

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        issues.append(_problem("invalid_artifacts", str(index_path), "expected list"))
    seen: set[str] = set()
    expected_checksums: dict[str, str] = {}
    for number, record in enumerate(artifacts):
        if not isinstance(record, dict):
            issues.append(
                _problem("invalid_artifact", f"artifacts[{number}]", "not object")
            )
            continue
        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            issues.append(
                _problem("invalid_artifact_path", f"artifacts[{number}]", "invalid")
            )
            continue
        if relative in seen:
            issues.append(_problem("duplicate_artifact", relative, "duplicate"))
            continue
        seen.add(relative)
        expected_checksums[relative] = str(record.get("sha256"))
        if Path(relative).suffix.lower() in MEDIA_SUFFIXES:
            issues.append(
                _problem("tracked_media_forbidden", relative, "metadata only required")
            )
        if "/S4/S4.5/" in relative or "/S4/S4.8/" in relative:
            issues.append(_problem("later_phase_content", relative, "forbidden"))
        candidate = _resolve_artifact(
            relative, repo_root=repo_root, evidence_root=evidence_root
        ).resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            try:
                candidate.relative_to(evidence_root)
            except ValueError:
                issues.append(_problem("unsafe_artifact_path", relative, "escapes"))
                continue
        if not candidate.is_file():
            issues.append(_problem("missing_artifact", relative, "file absent"))
            continue
        if relative in SOURCE_PATHS:
            try:
                historical_bytes = _git_blob(
                    repo_root, historical_source_commit, relative
                )
            except S44Error as exc:
                issues.append(
                    _problem("historical_source_missing", relative, str(exc))
                )
                continue
            observed_size = len(historical_bytes)
            observed_sha256 = hashlib.sha256(historical_bytes).hexdigest()
        else:
            observed_size = candidate.stat().st_size
            observed_sha256 = sha256_file(candidate)
        if observed_size != record.get("byte_size"):
            issues.append(_problem("artifact_size_mismatch", relative, "size differs"))
        if observed_sha256 != record.get("sha256"):
            issues.append(_problem("artifact_hash_mismatch", relative, "hash differs"))
        if require_tracked and candidate.is_relative_to(repo_root):
            repo_relative = candidate.relative_to(repo_root).as_posix()
            if not _git_tracked(repo_root, repo_relative):
                issues.append(_problem("artifact_not_tracked", relative, "not in Git"))

    checksum_path = evidence_root / "SHA256SUMS"
    if not checksum_path.is_file():
        issues.append(_problem("missing_checksums", str(checksum_path), "file absent"))
    else:
        try:
            checksums = _read_checksum_manifest(checksum_path)
        except (OSError, S44Error) as exc:
            issues.append(_problem("invalid_checksums", str(checksum_path), str(exc)))
        else:
            if checksums != expected_checksums:
                issues.append(
                    _problem(
                        "checksum_coverage_mismatch",
                        str(checksum_path),
                        "does not match evidence index",
                    )
                )

    required = {
        "access_policy.json",
        "assignment_companion.v1.json",
        "coverage_report.json",
        "fit_manifest.json",
        "group_manifest.json",
        "holdout_manifest.json",
        "holdout_seal.json",
        "provenance.json",
        "split_plan.json",
        "trial_census.json",
        "freeze/constraint_adapter_algorithm.v1.json",
        "freeze/preseed_coverage_constraints.json",
        "freeze/s2_5_constraint_feasibility.json",
        "freeze/source_checkpoint.v1.json",
        "validation/adapter_validation.json",
    }
    for relative in sorted(required):
        if not (evidence_root / relative).is_file():
            issues.append(
                _problem("required_evidence_missing", relative, "file absent")
            )

    plan: SplitPlan | None = None
    try:
        plan = SplitPlan.from_dict(load_json(evidence_root / "split_plan.json"))
        verify_no_leakage(plan)
    except (OSError, S44Error, ValueError) as exc:
        issues.append(_problem("split_plan_invalid", "split_plan.json", str(exc)))
    if plan is not None:
        if plan.plan_sha256 != index.get("split_plan_sha256"):
            issues.append(
                _problem("split_plan_index_mismatch", "split_plan.json", "hash differs")
            )
        expected_assignments = {
            "fit": (
                "g02_mac_reference_front",
                "g04_silence",
                "g05_mac_reference_occluded",
                "g06_standardized_voice_left",
                "g07_reference_voice_overlap_left",
                "g09_ordinary_object_impact_front",
            ),
            "holdout": (
                "g01_mac_reference_left_baseline",
                "g03_mac_reference_opposite",
                "g08_mac_reference_rear_near",
            ),
        }
        if dict(plan.assignments) != expected_assignments:
            issues.append(
                _problem("assignment_mismatch", "split_plan.json", "not approved 10/6")
            )

    try:
        constraints = load_json(
            evidence_root / "freeze/preseed_coverage_constraints.json"
        )
        algorithm = load_json(
            evidence_root / "freeze/constraint_adapter_algorithm.v1.json"
        )
        validate_preseed_contract(constraints, repo_root=repo_root)
        validate_adapter_contract(algorithm, constraints, repo_root=repo_root)
    except (OSError, S44Error, ValueError) as exc:
        constraints = {}
        issues.append(_problem("frozen_contract_invalid", "freeze", str(exc)))

    companion = load_json(evidence_root / "assignment_companion.v1.json")
    if plan is not None:
        if companion.get("split_plan_sha256") != plan.plan_sha256:
            issues.append(
                _problem(
                    "companion_plan_mismatch",
                    "assignment_companion.v1.json",
                    "hash differs",
                )
            )
        if companion.get("seed") != 0:
            issues.append(
                _problem("companion_seed_mismatch", "assignment_companion", "not 0")
            )
        if companion.get("outcome_metrics_used") is not False:
            issues.append(
                _problem("outcome_metrics_used", "assignment_companion", "forbidden")
            )
        if companion.get("adapter", {}).get("assignment_producer") != (
            "S4.4 constraint-aware adapter"
        ):
            issues.append(
                _problem("wrong_assignment_producer", "assignment_companion", "invalid")
            )

    census = load_json(evidence_root / "trial_census.json")
    if census.get("counts") != {
        "attempts": 18,
        "condition_cells": 16,
        "quality_eligible_condition_cells": 15,
        "quality_ineligible_condition_cells": 1,
        "retained_failed_attempts": 3,
    }:
        issues.append(_problem("census_counts_invalid", "trial_census.json", "invalid"))
    if census.get("all_failures_retained") is not True:
        issues.append(_problem("failures_not_retained", "trial_census.json", "invalid"))

    provenance = load_json(evidence_root / "provenance.json")
    try:
        validate_source_checkpoint_contract(
            source_checkpoint,
            repo_root=repo_root,
            expected_source_paths=SOURCE_PATHS,
            expected_frozen_input_paths=FROZEN_INPUT_PATHS,
            require_working_checkout_match=False,
        )
        validate_provenance_source_checkpoint(
            provenance,
            source_checkpoint,
            checkpoint_path=(
                f"{CANONICAL_OUTPUT}/freeze/source_checkpoint.v1.json"
            ),
            checkpoint_file_sha256=sha256_file(source_checkpoint_path),
        )
        if (
            provenance.get("status") != "frozen_source_checkpoint"
            or provenance.get("final_source_commit_pending") is not False
        ):
            raise S44Error("provenance checkpoint status is invalid")
    except (OSError, S44Error, ValueError) as exc:
        issues.append(
            _problem(
                "provenance_checkpoint_invalid", "provenance.json", str(exc)
            )
        )

    coverage = load_json(evidence_root / "coverage_report.json")
    if coverage.get("achieved_condition_cell_counts") != {"fit": 10, "holdout": 6}:
        issues.append(_problem("coverage_counts_invalid", "coverage_report", "invalid"))
    if coverage.get("quality_ineligible_cells_counted_as_usable_coverage") is not False:
        issues.append(_problem("ineligible_coverage", "coverage_report", "forbidden"))
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
    if set(coverage.get("axes", {})) != required_axes:
        issues.append(_problem("coverage_axes_missing", "coverage_report", "invalid"))
    if plan is not None and constraints:
        from isaac_audio_sensors.acquisition.s4_4 import AdapterSelection

        synthetic_selection = AdapterSelection(
            seed=0,
            plan=plan,
            score_order=tuple(companion.get("score_order", ())),
            ranking_key=(),
            subset_count=512,
            feasible_subset_count=188,
            coverage={},
            global_optimum_verified=True,
        )
        expected_coverage = build_coverage_report(constraints, synthetic_selection)
        if coverage != expected_coverage:
            issues.append(
                _problem(
                    "coverage_inconsistent", "coverage_report.json", "rebuild differs"
                )
            )

    access_policy = load_json(evidence_root / "access_policy.json")
    if (
        access_policy.get("status") != "sealed"
        or access_policy.get("s4_8_grant_created") is not False
        or access_policy.get("holdout_opened") is not False
    ):
        issues.append(
            _problem("access_policy_invalid", "access_policy.json", "invalid")
        )
    holdout_manifest = load_json(evidence_root / "holdout_manifest.json")
    try:
        validate_holdout_manifest_content(holdout_manifest)
    except S44Error as exc:
        issues.append(
            _problem(
                "holdout_manifest_content_invalid",
                "holdout_manifest.json",
                str(exc),
            )
        )
    seal = load_json(evidence_root / "holdout_seal.json")
    if plan is not None:
        try:
            validate_holdout_seal(seal, plan)
        except S44Error as exc:
            issues.append(
                _problem("holdout_seal_invalid", "holdout_seal.json", str(exc))
            )
    if sha256_file(evidence_root / "holdout_seal.json") != index.get(
        "holdout_seal_sha256"
    ):
        issues.append(
            _problem("seal_index_mismatch", "holdout_seal.json", "hash differs")
        )

    machine_report: dict[str, Any] | None = None
    ledger_report: dict[str, Any] | None = None
    if require_machine_local:
        machine_report = hash_only_holdout_integrity(seal, repo_root=repo_root)
        if machine_report["status"] != "passed":
            issues.extend(
                _problem(item["code"], item["path"], item["message"])
                for item in machine_report["issues"]
            )
        access_root = repo_root / "dataset/S4.4/access"
        grant = access_root / "holdout_access_grant.json"
        if grant.exists():
            issues.append(_problem("s4_8_grant_present", str(grant), "forbidden"))
        state_path = access_root / "seal_state.json"
        if not state_path.is_file():
            issues.append(
                _problem("seal_state_missing", str(state_path), "file absent")
            )
        else:
            state = load_json(state_path)
            if state.get("tracked_seal_sha256") != sha256_file(
                evidence_root / "holdout_seal.json"
            ):
                issues.append(
                    _problem("seal_state_mismatch", str(state_path), "invalid")
                )
            if state.get("grant_present") is not False:
                issues.append(
                    _problem("grant_state_invalid", str(state_path), "invalid")
                )
            if state.get("holdout_opened") is not False:
                issues.append(
                    _problem("holdout_open_state", str(state_path), "invalid")
                )
        ledger_path = access_root / "access_ledger.jsonl"
        seal_file_sha = sha256_file(evidence_root / "holdout_seal.json")
        if not ledger_path.is_file():
            issues.append(
                _problem("access_ledger_missing", str(ledger_path), "file absent")
            )
        ledger_report = validate_ledger(
            ledger_path, expected_seal_sha256=seal_file_sha
        )
        if ledger_report["status"] != "passed":
            issues.append(_problem("ledger_invalid", str(ledger_path), "chain failed"))
        if any(
            json.loads(line).get("holdout_opened") is True
            for line in (
                ledger_path.read_text(encoding="utf-8").splitlines()
                if ledger_path.exists()
                else []
            )
        ):
            issues.append(_problem("holdout_was_opened", str(ledger_path), "forbidden"))
        if record_integrity_event and not issues:
            append_ledger_event(
                ledger_path,
                {
                    "event": "integrity_validation",
                    "event_time_utc": "2026-07-22T01:24:06Z",
                    "seal_sha256": seal_file_sha,
                    "split_plan_sha256": plan.plan_sha256 if plan else "0" * 64,
                    "purpose": "S4.4_integrity_validation",
                    "checked_artifact_count": machine_report[
                        "checked_artifact_count"
                    ],
                    "holdout_opened": False,
                    "content_derived_values_returned": False,
                },
            )
            ledger_report = validate_ledger(
                ledger_path, expected_seal_sha256=seal_file_sha
            )

    if (repo_root / "outputs/isaac_audio_sensors/S4/S4.5").exists():
        issues.append(_problem("s4_5_directory_present", "S4.5", "must be unstarted"))
    if (repo_root / "outputs/isaac_audio_sensors/S4/S4.8").exists():
        issues.append(_problem("s4_8_directory_present", "S4.8", "must be unstarted"))
    return {
        "schema": "ias.s4_4.integrity_validation.v1",
        "status": "passed" if not issues else "failed",
        "require_machine_local": require_machine_local,
        "require_final": require_final,
        "require_tracked": require_tracked,
        "checked_tracked_artifact_count": len(artifacts),
        "machine_local_hash_only": machine_report,
        "access_ledger": ledger_report,
        "holdout_opened": False,
        "content_derived_values_returned": False,
        "s4_5_started": False,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--require-machine-local", action="store_true")
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--record-integrity-event", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = validate(
            args.index,
            repo_root=args.repo_root,
            require_machine_local=args.require_machine_local,
            require_final=args.require_final,
            require_tracked=args.require_tracked,
            record_integrity_event=args.record_integrity_event,
        )
    except (OSError, S44Error, ValueError) as exc:
        print(f"S4.4 integrity validation failed: {exc}", file=sys.stderr)
        return 1
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        write_json_atomic(args.output, result)
        sys.stdout.write(encoded)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
