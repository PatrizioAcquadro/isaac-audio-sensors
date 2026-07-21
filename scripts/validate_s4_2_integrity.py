#!/usr/bin/env python3
"""Validate S4.2 tracked contracts and optional machine-local raw integrity."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import load_json, sha256_file
from isaac_audio_sensors.acquisition.s4_2_reference import generate_reference

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REFERENCE_SHA256 = (
    "27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468"
)
REQUIRED_ROLES = {
    "s4_2_specification",
    "operator_runbook",
    "acquisition_implementation",
    "workstation_cli",
    "pi_helper",
    "zed_capture_helper",
    "zed_svo_validator",
    "mac_preflight_helper",
    "mac_source_inventory",
    "reference_generator",
    "reference_wav",
    "reference_metadata",
    "acquisition_configuration",
    "semantic_validator",
    "tests",
    "accepted_mac_preflight",
    "stable_session_preflight",
    "mac_dynamic_preflight",
    "producer_readiness_validation",
    "operator_remove_cue",
    "accepted_attempt_manifest",
    "accepted_validation_report",
    "accepted_alignment_report",
    "accepted_gate",
    "raw_respeaker_wav",
    "raw_zed_svo2",
    "raw_zed_frame_records",
    "retained_failure",
    "machine_local_validation_record",
    "pre_capture_acceptance_amendment",
    "dual_frame_coordinate_reconciliation",
    "superseded_post_capture_coordinate_correction",
    "corrected_accepted_configuration_copy",
    "historical_accepted_configuration_copy",
    "event_observation_confirmation",
    "alignment_review_helper",
    "privacy_deletion_helper",
    "s4_2_closeout",
    "evidence_checksums",
}


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _tracked(relative: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _parse_checksum_manifest(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"{path}:{line_number}: malformed SHA-256 line")
        digest, relative = parts
        if relative in records:
            raise ValueError(f"{path}:{line_number}: duplicate path {relative}")
        records[relative] = digest
    return records


def validate_index(
    index_path: str | Path,
    *,
    require_complete: bool,
    require_git_tracked: bool,
    repository_root: str | Path | None = None,
    require_machine_local: bool = False,
) -> dict[str, Any]:
    """Validate one evidence index without repairing or coercing evidence."""

    index_file = Path(index_path)
    payload = load_json(index_file)
    issues: list[dict[str, str]] = []
    if payload.get("schema") != "ias.s4_2.evidence_index.v1":
        issues.append(
            _issue("invalid_schema", str(index_file), repr(payload.get("schema")))
        )
    if require_complete and payload.get("status") != "passed":
        issues.append(
            _issue(
                "incomplete_evidence_index",
                str(index_file),
                f"status is {payload.get('status')!r}",
            )
        )
    entries = payload.get("artifacts")
    if not isinstance(entries, list):
        entries = []
        issues.append(_issue("invalid_artifact_list", "artifacts", "must be a list"))
    seen_paths: set[str] = set()
    roles: set[str] = set()
    root = Path(repository_root).resolve() if repository_root else REPO_ROOT
    indexed_hashes: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            issues.append(
                _issue(
                    "invalid_artifact_record",
                    f"artifacts[{index}]",
                    "must be an object",
                )
            )
            continue
        relative = entry.get("path")
        role = entry.get("role")
        retention = entry.get("retention")
        if not isinstance(relative, str) or not relative:
            issues.append(
                _issue("invalid_path", f"artifacts[{index}].path", repr(relative))
            )
            continue
        candidate_relative = Path(relative)
        if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
            issues.append(_issue("unsafe_path", relative, "path must be repo-relative"))
            continue
        if relative in seen_paths:
            issues.append(_issue("duplicate_path", relative, "path appears twice"))
            continue
        seen_paths.add(relative)
        if not isinstance(role, str) or not role:
            issues.append(_issue("missing_role", relative, repr(role)))
        else:
            roles.add(role)
        if retention not in {"tracked", "machine_local_gitignored"}:
            issues.append(_issue("invalid_retention", relative, repr(retention)))
        expected_hash = entry.get("sha256")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
        ):
            issues.append(
                _issue("invalid_checksum", f"{relative}.sha256", repr(expected_hash))
            )
        else:
            indexed_hashes[relative] = expected_hash
        expected_size = entry.get("byte_size")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            issues.append(
                _issue(
                    "invalid_byte_size",
                    f"{relative}.byte_size",
                    repr(expected_size),
                )
            )
        if retention == "machine_local_gitignored":
            if not relative.startswith("dataset/S4.2/"):
                issues.append(
                    _issue(
                        "invalid_machine_local_path",
                        relative,
                        "machine-local raw evidence must be under dataset/S4.2/",
                    )
                )
            if entry.get("local_relative_path") != relative:
                issues.append(
                    _issue(
                        "invalid_local_relative_path",
                        relative,
                        repr(entry.get("local_relative_path")),
                    )
                )
            if not isinstance(entry.get("media_properties"), dict):
                issues.append(
                    _issue("missing_media_properties", relative, "must be an object")
                )
            if not isinstance(entry.get("acquisition_contract"), dict):
                issues.append(
                    _issue(
                        "missing_acquisition_contract", relative, "must be an object"
                    )
                )
        candidate = root / candidate_relative
        if not candidate.is_file():
            if retention == "tracked" or require_machine_local:
                issues.append(
                    _issue("missing_artifact", relative, "file is unavailable")
                )
            continue
        actual_size = candidate.stat().st_size
        if expected_size != actual_size:
            issues.append(
                _issue(
                    "size_mismatch",
                    relative,
                    f"expected {expected_size!r}, got {actual_size}",
                )
            )
        actual_hash = sha256_file(candidate)
        if expected_hash != actual_hash:
            issues.append(
                _issue(
                    "checksum_mismatch",
                    relative,
                    f"expected {expected_hash!r}, got {actual_hash}",
                )
            )
        if retention == "tracked" and require_git_tracked and not _tracked(relative):
            issues.append(
                _issue(
                    "not_git_tracked", relative, "tracked artifact is absent from index"
                )
            )
    if require_complete:
        missing_roles = sorted(REQUIRED_ROLES - roles)
        if missing_roles:
            issues.append(
                _issue(
                    "missing_evidence_roles",
                    "artifacts",
                    f"missing roles: {missing_roles}",
                )
            )
    if any(
        path.startswith("outputs/isaac_audio_sensors/S4/S4.3/") for path in seen_paths
    ):
        issues.append(
            _issue(
                "s4_3_scope_violation",
                "artifacts",
                "S4.3 content is forbidden in S4.2 evidence",
            )
        )
    checksum_path_value = payload.get("checksum_manifest")
    if isinstance(checksum_path_value, str):
        checksum_path = root / checksum_path_value
        if checksum_path.is_file():
            try:
                manifest_hashes = _parse_checksum_manifest(checksum_path)
            except (OSError, ValueError) as exc:
                issues.append(
                    _issue("corrupt_checksum_manifest", checksum_path_value, str(exc))
                )
            else:
                expected_covered = {
                    path: digest
                    for path, digest in indexed_hashes.items()
                    if path != checksum_path_value
                }
                if manifest_hashes != expected_covered:
                    issues.append(
                        _issue(
                            "checksum_coverage_mismatch",
                            checksum_path_value,
                            "checksum lines do not exactly cover indexed artifacts",
                        )
                    )
        else:
            issues.append(
                _issue(
                    "missing_checksum_manifest",
                    checksum_path_value,
                    "file is unavailable",
                )
            )
    else:
        issues.append(
            _issue(
                "missing_checksum_manifest",
                "checksum_manifest",
                repr(checksum_path_value),
            )
        )
    with tempfile.TemporaryDirectory(prefix="ias_s4_2_reference_") as temporary:
        regenerated = Path(temporary) / "reference.wav"
        metadata = Path(temporary) / "reference.json"
        reference = generate_reference(regenerated, metadata)
        if reference["sha256"] != EXPECTED_REFERENCE_SHA256:
            issues.append(
                _issue(
                    "reference_regeneration_mismatch",
                    "reference_wav",
                    f"got {reference['sha256']}",
                )
            )
    status = "passed" if not issues else "failed"
    return {
        "schema": "ias.s4_2.integrity_validation.v1",
        "status": status,
        "index": str(index_file),
        "require_complete": require_complete,
        "require_git_tracked": require_git_tracked,
        "repository_root": str(root),
        "require_machine_local": require_machine_local,
        "artifact_count": len(entries),
        "roles": sorted(roles),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S4/S4.2/evidence_index.json"),
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--require-git-tracked", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=None)
    parser.add_argument("--require-machine-local", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_index(
        args.index,
        require_complete=not args.allow_incomplete,
        require_git_tracked=args.require_git_tracked,
        repository_root=args.repository_root,
        require_machine_local=args.require_machine_local,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"S4.2 integrity {report['status']}: "
            f"artifacts={report['artifact_count']} issues={len(report['issues'])}"
        )
        for issue in report["issues"]:
            print(f"- {issue['code']} {issue['path']}: {issue['message']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
