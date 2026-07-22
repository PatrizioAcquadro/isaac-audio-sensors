#!/usr/bin/env python3
"""Create an additive, immutable NO-GO closure for S4.4 amendment_01."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    build_source_checkpoint,
    canonical_sha256,
    load_json,
    sha256_file,
    validate_attempt_census,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
TRACKED_ROOT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments" / AMENDMENT_ID
MACHINE_ROOT = ROOT / "dataset/S4.4/amendments" / AMENDMENT_ID
CLOSURE_ROOT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/closures"
RECORD_PATH = CLOSURE_ROOT / f"{AMENDMENT_ID}_no_go.v1.json"
SEAL_PATH = CLOSURE_ROOT / f"{AMENDMENT_ID}_no_go_seal.v1.json"
CHECKPOINT_PATH = CLOSURE_ROOT / f"{AMENDMENT_ID}_no_go_source_checkpoint.v1.json"
CLOSEOUT_PATH = ROOT / (
    "docs/development/closeouts/S4/s4_4_data_expansion_amendment_01.md"
)
SOURCE_PATHS = (
    "scripts/build_s4_4_amendment_01_no_go_closure.py",
    "scripts/validate_s4_4_amendment.py",
    "src/isaac_audio_sensors/acquisition/s4_4_amendment.py",
    "tests/test_s4_4_amendment.py",
)


def _files(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _attempt_census() -> dict[str, Any]:
    manifests = {
        path.stem: load_json(path)
        for path in sorted((TRACKED_ROOT / "manifests/sessions").glob("*.json"))
    }
    attempts = [
        load_json(path)
        for path in sorted((MACHINE_ROOT / "attempts").glob("*/*/manifest.json"))
    ]
    return validate_attempt_census(manifests, attempts)


def build(*, freeze_source_checkpoint: bool) -> dict[str, Any]:
    for required in (TRACKED_ROOT, MACHINE_ROOT, CLOSEOUT_PATH):
        if not required.exists():
            raise S44AmendmentError(f"amendment_01 closure input absent: {required}")
    tracked_records = _files(TRACKED_ROOT)
    machine_records = _files(MACHINE_ROOT)
    if any(
        Path(record["path"]).suffix.lower() not in {".json", ""}
        for record in machine_records
    ):
        raise S44AmendmentError(
            "amendment_01 unexpectedly contains media/non-JSON data"
        )
    census = _attempt_census()
    if (
        census.get("status") != "no_go"
        or census.get("second_failure_present") is not True
    ):
        raise S44AmendmentError(
            "amendment_01 is not in the required retained NO-GO state"
        )
    attempt_01 = load_json(
        MACHINE_ROOT
        / "attempts/s44a01_fit_a_001_sil/s44a01_fit_a_001_sil__attempt_01/manifest.json"
    )
    attempt_02 = load_json(
        MACHINE_ROOT
        / "attempts/s44a01_fit_a_001_sil/s44a01_fit_a_001_sil__attempt_02/manifest.json"
    )
    if any(
        attempt.get("outcome") != "pre_recording_failure"
        or attempt.get("recorder_started") is not False
        for attempt in (attempt_01, attempt_02)
    ):
        raise S44AmendmentError("amendment_01 retained attempt outcome changed")
    ledger = MACHINE_ROOT / "access/access_ledger.jsonl"
    if ledger.exists():
        raise S44AmendmentError("unexpected amendment_01 access ledger appeared")
    record_payload = {
        "schema": "ias.s4_4.amendment_no_go_closeout.v1",
        "status": "no_go",
        "amendment_id": AMENDMENT_ID,
        "closed_at_utc": attempt_02["failed_at_utc"],
        "reason": "second_retained_pre_recording_failure",
        "root_cause": {
            "attempt_01": "allocated_before_capture_plan_defect_was_discovered",
            "attempt_02": (
                "allocated_before_mac_dynamic_preflight_and_ssh_was_denied_by_"
                "restricted_sandbox"
            ),
            "lifecycle_defect": (
                "session_readiness_executed_after_planned_cell_attempt_allocation"
            ),
        },
        "attempt_census": census,
        "recorder_started": False,
        "playback_started": False,
        "zed_capture_started": False,
        "scientific_media_created": False,
        "scientific_analysis_started": False,
        "holdout_scientifically_opened": False,
        "access_ledger": {
            "path": ledger.relative_to(ROOT).as_posix(),
            "existed_at_closure": False,
            "reason": "no_holdout_access_or_integrity_event_occurred",
        },
        "existing_closeout": {
            "path": CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(CLOSEOUT_PATH),
            "modified_by_closure": False,
        },
        "tracked_amendment_records": tracked_records,
        "machine_local_amendment_records": machine_records,
        "tracked_record_set_sha256": canonical_sha256(tracked_records),
        "machine_local_record_set_sha256": canonical_sha256(machine_records),
        "original_precollection_seal_sha256": sha256_file(
            TRACKED_ROOT / "precollection_seal.v1.json"
        ),
        "execution_corrective_seal_sha256": sha256_file(
            TRACKED_ROOT / "freeze/precollection_seal.execution_corrective_01.v1.json"
        ),
        "attempts_may_be_deleted_reclassified_retried_or_overwritten": False,
        "S4.5_or_later_started": False,
    }
    record = {**record_payload, "closeout_sha256": canonical_sha256(record_payload)}
    CLOSURE_ROOT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(RECORD_PATH, record)
    checkpoint: dict[str, Any] | None = None
    if freeze_source_checkpoint:
        checkpoint = build_source_checkpoint(ROOT, _git_head(), SOURCE_PATHS)
        write_json_atomic(CHECKPOINT_PATH, checkpoint)
    elif CHECKPOINT_PATH.is_file():
        checkpoint = load_json(CHECKPOINT_PATH)
    seal_payload = {
        "schema": "ias.s4_4.amendment_no_go_seal.v1",
        "status": (
            "committed" if checkpoint is not None else "awaiting_commit_authorization"
        ),
        "amendment_id": AMENDMENT_ID,
        "disposition": "irreversible_no_go",
        "closeout_record_path": RECORD_PATH.relative_to(ROOT).as_posix(),
        "closeout_record_sha256": sha256_file(RECORD_PATH),
        "tracked_record_set_sha256": record["tracked_record_set_sha256"],
        "machine_local_record_set_sha256": record["machine_local_record_set_sha256"],
        "existing_closeout_sha256": record["existing_closeout"]["sha256"],
        "attempt_census_sha256": census["census_sha256"],
        "source_checkpoint": checkpoint,
        "collection_allowed": False,
        "attempt_retry_allowed": False,
        "superseded_in_place": False,
        "S4.5_or_later_started": False,
    }
    seal = {**seal_payload, "seal_sha256": canonical_sha256(seal_payload)}
    write_json_atomic(SEAL_PATH, seal)
    return {
        "status": "passed",
        "commit_status": seal["status"],
        "disposition": "irreversible_no_go",
        "closure_record_file_sha256": sha256_file(RECORD_PATH),
        "closure_seal_file_sha256": sha256_file(SEAL_PATH),
        "attempt_census_sha256": census["census_sha256"],
        "tracked_record_count": len(tracked_records),
        "machine_local_record_count": len(machine_records),
        "amendment_01_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-source-checkpoint", action="store_true")
    args = parser.parse_args()
    try:
        result = build(freeze_source_checkpoint=args.freeze_source_checkpoint)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment_01 closure failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
