#!/usr/bin/env python3
"""Validate the S4.4 data-expansion amendment without opening the holdout."""

from __future__ import annotations

import argparse
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
    combined_partition_manifest,
    hash_only_integrity_and_record,
    load_json,
    sha256_file,
    validate_attempt_census,
    validate_configuration,
    validate_holdout_technical_qa,
    validate_ledger,
    validate_manifests,
    validate_precollection_seal,
    validate_session_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
CANONICAL_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.4/amendments") / AMENDMENT_ID
DEFAULT_INDEX = ROOT / CANONICAL_OUTPUT / "evidence_index.v1.json"
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"
MEDIA_SUFFIXES = {".wav", ".svo", ".svo2", ".png", ".jpg", ".jpeg", ".mp4"}


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _resolve(relative: str, repo_root: Path, evidence_root: Path) -> Path:
    prefix = CANONICAL_OUTPUT.as_posix() + "/"
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
    require_tracked: bool,
    require_committed: bool,
    require_machine_local: bool,
) -> dict[str, Any]:
    """Validate precollection or final machine-local amendment state."""

    issues: list[dict[str, str]] = []
    repo_root = repo_root.resolve()
    evidence_root = index_path.resolve().parent
    config = load_json(
        DEFAULT_CONFIG
        if repo_root == ROOT
        else repo_root / DEFAULT_CONFIG.relative_to(ROOT)
    )
    try:
        validate_configuration(config, repo_root)
    except S44AmendmentError as exc:
        issues.append(_issue("configuration_invalid", str(DEFAULT_CONFIG), str(exc)))

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

    artifacts = (
        index.get("artifacts") if isinstance(index.get("artifacts"), list) else []
    )
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
        candidate = _resolve(relative, repo_root, evidence_root).resolve()
        if not candidate.is_file():
            issues.append(_issue("missing_artifact", relative, "file absent"))
            continue
        if candidate.stat().st_size != record.get("byte_size"):
            issues.append(_issue("artifact_size_mismatch", relative, "size differs"))
        if sha256_file(candidate) != record.get("sha256"):
            issues.append(_issue("artifact_hash_mismatch", relative, "hash differs"))
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
            seal, repo_root=repo_root, require_committed=require_committed
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
    for phase in ("S4.5", "S4.6", "S4.7", "S4.8"):
        if (repo_root / f"outputs/isaac_audio_sensors/S4/{phase}").exists():
            issues.append(_issue("later_phase_directory_present", phase, "forbidden"))

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
        "checked_artifact_count": len(artifacts),
        "planned_counts": {"fit": 102, "prospective_holdout": 47, "total": 149},
        "machine_local_hash_only": machine_integrity,
        "access_ledger": ledger_report,
        "prospective_holdout_scientifically_opened": False,
        "scientific_outcomes_returned": False,
        "original_s4_4_unchanged": not any(
            issue["code"] == "configuration_invalid" for issue in issues
        ),
        "S4.5_or_later_started": False,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--require-tracked", action="store_true")
    parser.add_argument("--require-committed", action="store_true")
    parser.add_argument("--require-machine-local", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(
            args.index,
            repo_root=args.repo_root,
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
