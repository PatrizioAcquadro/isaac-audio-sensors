#!/usr/bin/env python3
"""Validate the S4.4 data-expansion amendment without opening the holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    build_aggregate_index,
    build_manifests,
    canonical_sha256,
    combined_partition_manifest,
    hash_only_integrity_and_record,
    load_amendment_configuration,
    load_json,
    sha256_file,
    validate_attempt_census,
    validate_configuration,
    validate_holdout_technical_qa,
    validate_ledger,
    validate_manifests,
    validate_precollection_seal,
    validate_session_preflight,
    validate_source_checkpoint,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    detect_later_phase_artifacts,
)

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
CANONICAL_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.4/amendments") / AMENDMENT_ID
DEFAULT_INDEX = ROOT / CANONICAL_OUTPUT / "evidence_index.v1.json"
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"
MEDIA_SUFFIXES = {".wav", ".svo", ".svo2", ".png", ".jpg", ".jpeg", ".mp4"}
EXECUTION_CORRECTIVE_PATH = "freeze/execution_corrective_01.v1.json"
EXECUTION_CORRECTIVE_CHECKPOINT_PATH = (
    "freeze/source_checkpoint.execution_corrective_01.v1.json"
)
EXECUTION_CORRECTIVE_SEAL_PATH = (
    "freeze/precollection_seal.execution_corrective_01.v1.json"
)
SUPERSEDED_DELIVERY_ROLES = {"amendment_source", "amendment_closeout"}
NO_GO_RECORD_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/closures/"
    "s4_4_data_expansion_amendment_01_no_go.v1.json"
)
NO_GO_SEAL_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/closures/"
    "s4_4_data_expansion_amendment_01_no_go_seal.v1.json"
)


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _resolve(
    relative: str,
    repo_root: Path,
    evidence_root: Path,
    canonical_output: Path,
) -> Path:
    prefix = canonical_output.as_posix() + "/"
    return (
        evidence_root / relative[len(prefix) :]
        if relative.startswith(prefix)
        else repo_root / relative
    )


def _tracked(repo_root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "  " not in line:
            raise S44AmendmentError(f"{path}:{number}: malformed checksum record")
        digest, relative = line.split("  ", 1)
        if relative in result:
            raise S44AmendmentError(f"{path}:{number}: duplicate path")
        result[relative] = digest
    return result


def _validate_historical_no_go(
    config: dict[str, Any],
    *,
    repo_root: Path,
    require_tracked: bool,
    require_committed: bool,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    historical = config["historical_no_go_amendment_01"]
    record_path = repo_root / historical["closure_record_path"]
    seal_path = repo_root / historical["closure_seal_path"]
    try:
        record = load_json(record_path)
        seal = load_json(seal_path)
        record_payload = {
            key: value for key, value in record.items() if key != "closeout_sha256"
        }
        seal_payload = {
            key: value for key, value in seal.items() if key != "seal_sha256"
        }
        if (
            record.get("schema") != "ias.s4_4.amendment_no_go_closeout.v1"
            or record.get("status") != "no_go"
            or canonical_sha256(record_payload) != record.get("closeout_sha256")
        ):
            raise S44AmendmentError("amendment_01 NO-GO closeout invalid")
        if (
            seal.get("schema") != "ias.s4_4.amendment_no_go_seal.v1"
            or seal.get("disposition") != "irreversible_no_go"
            or canonical_sha256(seal_payload) != seal.get("seal_sha256")
            or seal.get("closeout_record_sha256") != sha256_file(record_path)
            or seal.get("collection_allowed") is not False
            or seal.get("attempt_retry_allowed") is not False
        ):
            raise S44AmendmentError("amendment_01 NO-GO seal invalid")
        if require_committed:
            checkpoint = seal.get("source_checkpoint")
            if seal.get("status") != "committed" or not isinstance(checkpoint, dict):
                raise S44AmendmentError("amendment_01 NO-GO seal is not committed")
            validate_source_checkpoint(
                checkpoint, repo_root, require_current_checkout=False
            )
        closeout = repo_root / record["existing_closeout"]["path"]
        if sha256_file(closeout) != record["existing_closeout"]["sha256"]:
            raise S44AmendmentError("amendment_01 closeout changed")
        for collection, label in (
            (record["tracked_amendment_records"], "tracked"),
            (record["machine_local_amendment_records"], "machine-local"),
        ):
            for item in collection:
                path = repo_root / item["path"]
                if label == "machine-local" and not path.exists():
                    continue
                if (
                    not path.is_file()
                    or path.stat().st_size != item["byte_size"]
                    or sha256_file(path) != item["sha256"]
                ):
                    raise S44AmendmentError(
                        f"amendment_01 {label} byte changed: {item['path']}"
                    )
        if require_tracked:
            for path in (record_path, seal_path):
                relative = path.relative_to(repo_root).as_posix()
                if not _tracked(repo_root, relative):
                    raise S44AmendmentError(
                        f"amendment_01 NO-GO evidence not tracked: {relative}"
                    )
    except (KeyError, OSError, S44AmendmentError) as exc:
        issues.append(_issue("historical_no_go_invalid", str(record_path), str(exc)))
    return issues


def _committed_no_go_closure_active(
    repo_root: Path, *, require_tracked: bool
) -> tuple[bool, list[dict[str, str]]]:
    """Recognize the additive closure without rebinding amendment_01 evidence.

    Once committed, the closure freezes the exact amendment_01 bytes and its
    corrective source checkpoint becomes historical. Forward amendment_02 work
    must therefore not invalidate amendment_01 merely because shared tooling has
    advanced in the current checkout.
    """

    record_path = repo_root / NO_GO_RECORD_PATH
    seal_path = repo_root / NO_GO_SEAL_PATH
    if not record_path.is_file() and not seal_path.is_file():
        return False, []
    issues: list[dict[str, str]] = []
    try:
        record = load_json(record_path)
        seal = load_json(seal_path)
        if seal.get("status") == "awaiting_commit_authorization":
            return False, []
        record_payload = {
            key: value for key, value in record.items() if key != "closeout_sha256"
        }
        seal_payload = {
            key: value for key, value in seal.items() if key != "seal_sha256"
        }
        if (
            record.get("schema") != "ias.s4_4.amendment_no_go_closeout.v1"
            or record.get("amendment_id") != AMENDMENT_ID
            or record.get("status") != "no_go"
            or canonical_sha256(record_payload) != record.get("closeout_sha256")
        ):
            raise S44AmendmentError("amendment_01 NO-GO closeout invalid")
        checkpoint = seal.get("source_checkpoint")
        if (
            seal.get("schema") != "ias.s4_4.amendment_no_go_seal.v1"
            or seal.get("amendment_id") != AMENDMENT_ID
            or seal.get("status") != "committed"
            or seal.get("disposition") != "irreversible_no_go"
            or seal.get("collection_allowed") is not False
            or seal.get("attempt_retry_allowed") is not False
            or canonical_sha256(seal_payload) != seal.get("seal_sha256")
            or seal.get("closeout_record_sha256") != sha256_file(record_path)
            or not isinstance(checkpoint, dict)
        ):
            raise S44AmendmentError("amendment_01 NO-GO seal invalid or uncommitted")
        validate_source_checkpoint(
            checkpoint, repo_root, require_current_checkout=False
        )
        if require_tracked:
            for relative in (NO_GO_RECORD_PATH, NO_GO_SEAL_PATH):
                if not _tracked(repo_root, relative.as_posix()):
                    raise S44AmendmentError(
                        f"amendment_01 NO-GO evidence not tracked: {relative}"
                    )
    except (KeyError, OSError, S44AmendmentError) as exc:
        issues.append(_issue("no_go_closure_invalid", str(record_path), str(exc)))
        return False, issues
    return True, issues


def _validate_execution_corrective(
    *,
    evidence_root: Path,
    repo_root: Path,
    require_tracked: bool,
    require_machine_local: bool,
    canonical_output: Path,
    historical_no_go_active: bool,
) -> tuple[bool, list[dict[str, str]]]:
    """Validate the additive execution corrective without mutating its predecessor."""

    issues: list[dict[str, str]] = []
    relative_paths = (
        EXECUTION_CORRECTIVE_PATH,
        EXECUTION_CORRECTIVE_CHECKPOINT_PATH,
        EXECUTION_CORRECTIVE_SEAL_PATH,
    )
    paths = [evidence_root / relative for relative in relative_paths]
    present = [path.is_file() for path in paths]
    if not any(present):
        return False, issues
    if not all(present):
        issues.append(
            _issue(
                "execution_corrective_incomplete",
                str(evidence_root / "freeze"),
                "corrective record, checkpoint, and seal must all exist",
            )
        )
        return True, issues
    evidence_path, checkpoint_path, seal_path = paths
    try:
        evidence = load_json(evidence_path)
        checkpoint = load_json(checkpoint_path)
        seal = load_json(seal_path)
        payload = {
            key: value
            for key, value in evidence.items()
            if key != "corrective_evidence_sha256"
        }
        if (
            evidence.get("schema") != "ias.s4_4.amendment_execution_corrective.v1"
            or evidence.get("status") != "committed"
            or canonical_sha256(payload) != evidence.get("corrective_evidence_sha256")
        ):
            raise S44AmendmentError("execution corrective evidence invalid")
        validate_precollection_seal(
            seal,
            repo_root=repo_root,
            require_committed=not historical_no_go_active,
            require_current_source=False,
        )
        if seal.get("source_checkpoint") != checkpoint:
            raise S44AmendmentError("corrective checkpoint/seal mismatch")
        if evidence.get("source_commit") != checkpoint.get("commit"):
            raise S44AmendmentError("corrective source commit mismatch")
        predecessor_path = evidence_root / "precollection_seal.v1.json"
        if (
            evidence.get("predecessor_precollection_seal_sha256")
            != sha256_file(predecessor_path)
            or evidence.get("corrective_precollection_seal_sha256")
            != sha256_file(seal_path)
            or evidence.get("corrective_delivery_sha256")
            != sha256_file(repo_root / str(evidence["corrective_delivery_path"]))
        ):
            raise S44AmendmentError("execution corrective hash binding mismatch")
        scope = evidence.get("scope")
        if not isinstance(scope, dict) or any(
            scope.get(field) is not False
            for field in (
                "assignment_changed",
                "matrix_changed",
                "ordering_changed",
                "grouping_changed",
                "replacement_policy_changed",
                "S4.5_or_later_started",
            )
        ):
            raise S44AmendmentError("execution corrective scope expanded")
        fit = load_json(evidence_root / "manifests/fit_manifest.v1.json")
        holdout = load_json(
            evidence_root / "manifests/prospective_holdout_manifest.v1.json"
        )
        if evidence.get("fit_manifest_payload_sha256") != fit.get(
            "partition_manifest_sha256"
        ) or evidence.get("prospective_holdout_manifest_payload_sha256") != holdout.get(
            "partition_manifest_sha256"
        ):
            raise S44AmendmentError("execution corrective assignment hash changed")
        if require_machine_local:
            failure_path = repo_root / str(evidence["retained_failure_path"])
            if not failure_path.is_file() or sha256_file(failure_path) != evidence.get(
                "retained_failure_sha256"
            ):
                raise S44AmendmentError(
                    "retained pre-recording failure is absent or changed"
                )
        if require_tracked:
            for relative in relative_paths:
                repo_relative = (canonical_output / relative).as_posix()
                if not _tracked(repo_root, repo_relative):
                    raise S44AmendmentError(
                        f"execution corrective artifact not tracked: {repo_relative}"
                    )
    except (KeyError, OSError, S44AmendmentError) as exc:
        issues.append(
            _issue("execution_corrective_invalid", str(evidence_path), str(exc))
        )
    return True, issues


def _validate_machine_local(
    config: dict[str, Any],
    manifests: dict[str, dict[str, Any]],
    repo_root: Path,
) -> tuple[list[dict[str, str]], dict[str, Any] | None, dict[str, Any] | None]:
    issues: list[dict[str, str]] = []
    session_root = repo_root / config["retention"]["session_root"]
    preflights: dict[str, dict[str, Any]] = {}
    dates: list[str] = []
    for session_id in manifests:
        path = session_root / session_id / "preflight.json"
        if not path.is_file():
            issues.append(_issue("missing_session_preflight", str(path), "file absent"))
            continue
        record = load_json(path)
        try:
            validate_session_preflight(record, config, other_dates=dates)
        except S44AmendmentError as exc:
            issues.append(_issue("invalid_session_preflight", str(path), str(exc)))
        else:
            preflights[session_id] = record
            dates.append(str(record["session_date_local"]))
    if len(set(dates)) != 3:
        issues.append(
            _issue(
                "session_dates_not_distinct",
                str(session_root),
                "expected three distinct dates",
            )
        )

    attempt_root = repo_root / config["retention"]["attempt_root"]
    attempts: list[dict[str, Any]] = []
    for path in sorted(attempt_root.glob("*/*/manifest.json")):
        attempts.append(load_json(path))
    census: dict[str, Any] | None = None
    try:
        census = validate_attempt_census(manifests, attempts)
    except S44AmendmentError as exc:
        issues.append(_issue("invalid_attempt_census", str(attempt_root), str(exc)))
    else:
        if census["status"] != "passed":
            issues.append(
                _issue("amendment_incomplete", str(attempt_root), census["status"])
            )

    access_root = repo_root / config["retention"]["access_root"]
    qa_root = access_root / "technical_qa"
    holdout_ids = set(
        combined_partition_manifest(manifests, "prospective_holdout")[
            "planned_take_ids"
        ]
    )
    qa_ids: set[str] = set()
    for path in sorted(qa_root.glob("*.json")):
        record = load_json(path)
        try:
            validate_holdout_technical_qa(record)
        except S44AmendmentError as exc:
            issues.append(_issue("invalid_holdout_qa", str(path), str(exc)))
        else:
            qa_ids.add(str(record["planned_take_id"]))
            if record["overall_technical_pass"] is not True:
                issues.append(
                    _issue("holdout_qa_failed", str(path), "technical QA failed")
                )
    if qa_ids != holdout_ids:
        issues.append(
            _issue(
                "holdout_qa_incomplete",
                str(qa_root),
                "expected one record per holdout cell",
            )
        )

    seal_path = access_root / "holdout_seal.json"
    machine_integrity: dict[str, Any] | None = None
    ledger_report: dict[str, Any] | None = None
    if not seal_path.is_file():
        issues.append(_issue("holdout_seal_missing", str(seal_path), "file absent"))
    else:
        seal = load_json(seal_path)
        try:
            ledger_path = access_root / "access_ledger.jsonl"
            machine_integrity = hash_only_integrity_and_record(
                seal,
                repo_root=repo_root,
                ledger_path=ledger_path,
                seal_sha256=sha256_file(seal_path),
                event_time_utc=datetime.now(timezone.utc).isoformat(),
            )
        except S44AmendmentError as exc:
            issues.append(_issue("holdout_seal_invalid", str(seal_path), str(exc)))
        else:
            if machine_integrity["status"] != "passed":
                issues.extend(
                    _issue(item["code"], item["path"], "hash-only validation failed")
                    for item in machine_integrity["issues"]
                )
            ledger_report = validate_ledger(
                ledger_path, expected_seal_sha256=sha256_file(seal_path)
            )
            if ledger_report["status"] != "passed":
                issues.append(
                    _issue(
                        "access_ledger_invalid", str(ledger_path), "hash chain failed"
                    )
                )
    return issues, machine_integrity, ledger_report


def validate(
    index_path: Path,
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG,
    require_tracked: bool,
    require_committed: bool,
    require_machine_local: bool,
) -> dict[str, Any]:
    """Validate precollection or final machine-local amendment state."""

    issues: list[dict[str, str]] = []
    repo_root = repo_root.resolve()
    evidence_root = index_path.resolve().parent
    resolved_config_path = (
        repo_root / DEFAULT_CONFIG.relative_to(ROOT)
        if config_path == DEFAULT_CONFIG and repo_root != ROOT
        else config_path
        if config_path.is_absolute()
        else repo_root / config_path
    )
    config = load_amendment_configuration(resolved_config_path, repo_root)
    canonical_output = Path(config["retention"]["tracked_evidence_root"])
    try:
        validate_configuration(config, repo_root)
    except S44AmendmentError as exc:
        issues.append(
            _issue("configuration_invalid", str(resolved_config_path), str(exc))
        )

    index = load_json(index_path)
    if index.get("schema") != "ias.s4_4.amendment_evidence_index.v1":
        issues.append(_issue("wrong_index_schema", str(index_path), "unexpected"))
    if index.get("planned_counts") != {
        "fit": 102,
        "prospective_holdout": 47,
        "total": 149,
    }:
        issues.append(_issue("index_counts_invalid", str(index_path), "unexpected"))
    if index.get("prospective_holdout_scientifically_opened") is not False:
        issues.append(_issue("holdout_opened", str(index_path), "forbidden"))
    if index.get("S4.5_or_later_started") is not False:
        issues.append(_issue("later_phase_started", str(index_path), "forbidden"))

    corrective_active = False
    corrective_issues: list[dict[str, str]] = []
    if int(config["version"]) == 1:
        no_go_active, no_go_issues = _committed_no_go_closure_active(
            repo_root, require_tracked=require_tracked
        )
        issues.extend(no_go_issues)
        corrective_active, corrective_issues = _validate_execution_corrective(
            evidence_root=evidence_root,
            repo_root=repo_root,
            require_tracked=require_tracked,
            require_machine_local=require_machine_local,
            canonical_output=canonical_output,
            historical_no_go_active=no_go_active,
        )
    else:
        issues.extend(
            _validate_historical_no_go(
                config,
                repo_root=repo_root,
                require_tracked=require_tracked,
                require_committed=require_committed,
            )
        )
    issues.extend(corrective_issues)

    artifacts = (
        index.get("artifacts") if isinstance(index.get("artifacts"), list) else []
    )
    historical_source_commit = None
    if int(config["version"]) == 2:
        try:
            historical_source_commit = load_json(
                evidence_root / "precollection_seal.v1.json"
            )["source_checkpoint"]["commit"]
        except (KeyError, OSError, TypeError):
            historical_source_commit = None
    expected_checksums: dict[str, str] = {}
    seen: set[str] = set()
    for number, record in enumerate(artifacts):
        if not isinstance(record, dict):
            issues.append(_issue("invalid_artifact", str(number), "not object"))
            continue
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            issues.append(
                _issue("invalid_or_duplicate_path", str(number), str(relative))
            )
            continue
        seen.add(relative)
        expected_checksums[relative] = str(record.get("sha256"))
        if Path(relative).suffix.lower() in MEDIA_SUFFIXES:
            issues.append(_issue("tracked_media_forbidden", relative, "metadata only"))
        if any(
            f"/S4/{phase}/" in relative for phase in ("S4.5", "S4.6", "S4.7", "S4.8")
        ):
            issues.append(_issue("later_phase_artifact", relative, "forbidden"))
        candidate = _resolve(
            relative, repo_root, evidence_root, canonical_output
        ).resolve()
        if not candidate.is_file():
            issues.append(_issue("missing_artifact", relative, "file absent"))
            continue
        superseded_by_corrective = (
            corrective_active and record.get("role") in SUPERSEDED_DELIVERY_ROLES
        )
        historical_source = bool(
            historical_source_commit and record.get("role") == "amendment_source"
        )
        if historical_source:
            blob = subprocess.run(
                [
                    "git",
                    "show",
                    "--no-ext-diff",
                    f"{historical_source_commit}:{relative}",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
            )
            if (
                blob.returncode != 0
                or len(blob.stdout) != record.get("byte_size")
                or hashlib.sha256(blob.stdout).hexdigest() != record.get("sha256")
            ):
                issues.append(
                    _issue(
                        "historical_artifact_mismatch",
                        relative,
                        "pinned Git blob differs",
                    )
                )
        elif not superseded_by_corrective:
            if candidate.stat().st_size != record.get("byte_size"):
                issues.append(
                    _issue("artifact_size_mismatch", relative, "size differs")
                )
            if sha256_file(candidate) != record.get("sha256"):
                issues.append(
                    _issue("artifact_hash_mismatch", relative, "hash differs")
                )
        if require_tracked and candidate.is_relative_to(repo_root):
            repo_relative = candidate.relative_to(repo_root).as_posix()
            if not _tracked(repo_root, repo_relative):
                issues.append(_issue("artifact_not_tracked", relative, "not in Git"))
    checksum_path = evidence_root / "SHA256SUMS"
    try:
        if _checksums(checksum_path) != expected_checksums:
            issues.append(
                _issue(
                    "checksum_coverage_mismatch", str(checksum_path), "index differs"
                )
            )
    except (OSError, S44AmendmentError) as exc:
        issues.append(_issue("checksums_invalid", str(checksum_path), str(exc)))

    manifests: dict[str, dict[str, Any]] = {}
    for session_id in ("fit_a", "fit_b", "prospective_holdout"):
        path = evidence_root / f"manifests/sessions/{session_id}.json"
        try:
            manifests[session_id] = load_json(path)
        except S44AmendmentError as exc:
            issues.append(_issue("session_manifest_invalid", str(path), str(exc)))
    if len(manifests) == 3:
        try:
            validate_manifests(manifests, config)
            expected = build_manifests(config)
            if manifests != expected:
                raise S44AmendmentError("byte-semantic deterministic rebuild differs")
        except S44AmendmentError as exc:
            issues.append(_issue("manifest_validation_failed", "manifests", str(exc)))
        fit = combined_partition_manifest(manifests, "fit")
        holdout = combined_partition_manifest(manifests, "prospective_holdout")
        if load_json(evidence_root / "manifests/fit_manifest.v1.json") != fit:
            issues.append(
                _issue(
                    "fit_manifest_mismatch", "fit_manifest.v1.json", "rebuild differs"
                )
            )
        if (
            load_json(evidence_root / "manifests/prospective_holdout_manifest.v1.json")
            != holdout
        ):
            issues.append(
                _issue(
                    "holdout_manifest_mismatch",
                    "prospective_holdout_manifest.v1.json",
                    "rebuild differs",
                )
            )
        aggregate = build_aggregate_index(
            config,
            fit_manifest_sha256=fit["partition_manifest_sha256"],
            holdout_manifest_sha256=holdout["partition_manifest_sha256"],
        )
        if load_json(evidence_root / "aggregate_index.v1.json") != aggregate:
            issues.append(
                _issue(
                    "aggregate_index_mismatch",
                    "aggregate_index.v1.json",
                    "rebuild differs",
                )
            )

    seal_path = evidence_root / "precollection_seal.v1.json"
    try:
        seal = load_json(seal_path)
        validate_precollection_seal(
            seal,
            repo_root=repo_root,
            require_committed=require_committed and not corrective_active,
            require_current_source=False,
        )
    except S44AmendmentError as exc:
        issues.append(_issue("precollection_seal_invalid", str(seal_path), str(exc)))
    else:
        if sha256_file(seal_path) != index.get("precollection_seal_sha256"):
            issues.append(_issue("seal_index_mismatch", str(seal_path), "hash differs"))
        if require_committed and index.get("collection_allowed") is not True:
            issues.append(
                _issue("collection_not_allowed", str(index_path), "commit gate closed")
            )

    tracked_dataset = subprocess.run(
        ["git", "ls-files", "dataset"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tracked_dataset:
        issues.append(_issue("raw_dataset_tracked", "dataset", tracked_dataset))
    later_phase_artifacts = detect_later_phase_artifacts(repo_root)
    for relative in later_phase_artifacts:
        issues.append(_issue("later_phase_artifact_present", relative, "forbidden"))

    machine_integrity = None
    ledger_report = None
    if require_machine_local and len(manifests) == 3:
        machine_issues, machine_integrity, ledger_report = _validate_machine_local(
            config, manifests, repo_root
        )
        issues.extend(machine_issues)
    return {
        "schema": "ias.s4_4.amendment_integrity_validation.v1",
        "status": "passed" if not issues else "failed",
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "require_machine_local": require_machine_local,
        "checked_artifact_count": len(artifacts) + (3 if corrective_active else 0),
        "execution_corrective_active": corrective_active,
        "planned_counts": {"fit": 102, "prospective_holdout": 47, "total": 149},
        "machine_local_hash_only": machine_integrity,
        "access_ledger": ledger_report,
        "prospective_holdout_scientifically_opened": False,
        "scientific_outcomes_returned": False,
        "original_s4_4_unchanged": not any(
            issue["code"] == "configuration_invalid" for issue in issues
        ),
        "S4.5_or_later_started": bool(later_phase_artifacts),
        "later_phase_artifacts": later_phase_artifacts,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--require-machine-local", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(
            args.index,
            repo_root=args.repo_root,
            config_path=args.config,
            require_tracked=args.require_tracked,
            require_committed=args.require_committed,
            require_machine_local=args.require_machine_local,
        )
    except (OSError, S44AmendmentError, ValueError) as exc:
        print(f"S4.4 amendment validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
