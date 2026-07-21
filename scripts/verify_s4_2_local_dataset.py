#!/usr/bin/env python3
"""Verify indexed S4.2 raw artifacts in place without copying or repairing them."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_2 import (
    S42_VALIDATION_PROFILE,
    inspect_six_channel_wav,
    load_json,
    read_jsonl,
    sha256_file,
    validate_zed_records,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic


def verify_local_dataset(
    index_path: Path, repository_root: Path, report_path: Path
) -> dict[str, Any]:
    """Verify machine-local entries and preserve a new immutable report."""

    index = load_json(index_path)
    if index.get("schema") != "ias.s4_2.evidence_index.v1":
        raise ValueError("incompatible evidence index schema")
    if report_path.exists():
        raise FileExistsError(f"validation report already exists: {report_path}")
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for entry in index.get("artifacts", []):
        if entry.get("retention") != "machine_local_gitignored":
            continue
        relative = Path(str(entry.get("path", "")))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.as_posix().startswith("dataset/S4.2/")
        ):
            failures.append(f"unsafe machine-local path: {relative}")
            continue
        artifact = repository_root / relative
        record = {
            "path": relative.as_posix(),
            "role": entry.get("role"),
            "status": "failed",
        }
        if not artifact.is_file():
            failures.append(f"missing artifact: {relative}")
        elif artifact.stat().st_size != entry.get("byte_size"):
            failures.append(f"byte-size mismatch: {relative}")
        elif sha256_file(artifact) != entry.get("sha256"):
            failures.append(f"checksum mismatch: {relative}")
        else:
            role = entry.get("role")
            semantic_issues: list[str] = []
            if role == "raw_respeaker_wav":
                _, issues = inspect_six_channel_wav(
                    artifact,
                    require_nonsilent_channels=True,
                    reject_sustained_clipping=True,
                )
                semantic_issues = [issue.code for issue in issues]
            elif role == "raw_zed_frame_records":
                rows, jsonl_issues = read_jsonl(artifact)
                contract = entry.get("acquisition_contract", {})
                duration_s = float(contract.get("duration_s", 0.0))
                fps = int(contract.get("fps", 0))
                if duration_s <= 0.0 or fps <= 0:
                    semantic_issues.append("invalid_zed_acquisition_contract")
                else:
                    semantic_issues.extend(issue.code for issue in jsonl_issues)
                    semantic_issues.extend(
                        issue.code
                        for issue in validate_zed_records(
                            rows,
                            duration_s=duration_s,
                            fps=fps,
                            validation_profile=S42_VALIDATION_PROFILE,
                        ).issues
                    )
            elif artifact.stat().st_size == 0:
                semantic_issues.append("empty_artifact")
            if semantic_issues:
                failures.append(
                    f"semantic validation failed for {relative}: {semantic_issues}"
                )
            else:
                record["status"] = "verified"
        records.append(record)
    report = {
        "schema": "ias.s4_2.machine_local_validation.v1",
        "status": "passed" if not failures else "failed",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "index": str(index_path),
        "repository_root": str(repository_root),
        "machine_local_root": "dataset/S4.2",
        "fresh_clone_available": False,
        "replicated": False,
        "records": records,
        "failures": failures,
    }
    write_json_atomic(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_local_dataset(
            args.index, args.repository_root.resolve(), args.report
        )
    except (OSError, ValueError) as exc:
        print(f"S4.2 machine-local validation failed: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
