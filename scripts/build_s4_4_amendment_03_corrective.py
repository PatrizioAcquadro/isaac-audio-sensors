#!/usr/bin/env python3
"""Build the additive Amendment 03 corrective-02 provenance records."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / (
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_03"
)
CORRECTION_ID = "corrective_02"
CORRECTIVE_ROOT = EVIDENCE_ROOT / CORRECTION_ID
GATE_PATH = EVIDENCE_ROOT / "validation/final_closeout_corrective_02.v1.json"
PREVIOUS_CORRECTIVE_ROOT = EVIDENCE_ROOT / "corrective_01"
PREVIOUS_GATE_PATH = (
    EVIDENCE_ROOT / "validation/final_closeout_corrective_01.v1.json"
)
SOURCE_PATHS = (
    "docs/development/specs/s4_4_data_expansion_amendment_03.md",
    "scripts/build_s4_4_amendment_03_corrective.py",
    "scripts/build_s4_4_amendment_03_multiday.py",
    "scripts/validate_s4_4_amendment.py",
    "scripts/validate_s4_4_amendment_03.py",
    "scripts/validate_s4_4_amendment_03_final.py",
    "src/isaac_audio_sensors/acquisition/s4_4_amendment_03.py",
    "tests/test_s4_4_amendment_03.py",
    "tests/test_s4_4_amendment_03_final.py",
)
FINAL_DOCUMENT_PATH = (
    "docs/development/closeouts/S4/s4_4_data_expansion_amendment_03_holdout.md"
)
EXPECTED_CENSUS = {
    "valid_cells_total": 149,
    "retained_attempts_total": 152,
    "failures_total": 3,
    "replacements_total": 3,
    "incomplete_logical_cells": 0,
}


def _git_blob_sha256(commit: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "show", "--no-ext-diff", f"{commit}:{relative}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S44AmendmentError(f"corrective source Git blob absent: {relative}")
    return __import__("hashlib").sha256(result.stdout).hexdigest()


def _record(relative: str, role: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        raise S44AmendmentError(f"corrective artifact absent: {relative}")
    return {
        "path": relative,
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build(*, source_commit: str, gate_results_path: Path) -> dict[str, Any]:
    gate_results = load_json(gate_results_path)
    if (
        gate_results.get("status") != "incomplete"
        or gate_results.get("validation_scope") != "diagnostic_incomplete"
        or gate_results.get("authoritative_final") is not False
        or gate_results.get("require_tracked") is not True
        or gate_results.get("require_committed") is not True
        or gate_results.get("require_machine_local") is not True
        or gate_results.get("require_corrective") is not False
        or gate_results.get("issues") != []
        or gate_results.get("source_commit") != source_commit
        or gate_results.get("census") != EXPECTED_CENSUS
        or gate_results.get("holdout_scientifically_opened") is not False
        or gate_results.get("scientific_outcomes_returned") is not False
        or gate_results.get("S4.5_or_later_started") is not False
    ):
        raise S44AmendmentError(
            "corrective pre-provenance validation contract is incomplete or invalid"
        )
    source_records = []
    for relative in SOURCE_PATHS:
        digest = _git_blob_sha256(source_commit, relative)
        if sha256_file(ROOT / relative) != digest:
            raise S44AmendmentError(
                f"corrective source checkout differs from source commit: {relative}"
            )
        source_records.append({"path": relative, "sha256": digest})
    checkpoint_payload = {
        "schema": "ias.s4_4.amendment_03_corrective_source_checkpoint.v1",
        "source_commit": source_commit,
        "historical_source_checkpoint_commit": (
            "d86710df72c0ad782420b05135b3371cd9e0048f"
        ),
        "historical_precollection_commit": ("9e1d0eb46c60f7bb8714cb182c6fd99f76232d4d"),
        "historical_holdout_closeout_commit": (
            "c432d9848d1c1498914ed1a2aad6c78baefc6519"
        ),
        "historical_final_gate_commit": ("322afa08c4276e42a3f69182695f7227a67b9c9d"),
        "supersedes_correction_id": "corrective_01",
        "previous_corrective_sha256": {
            "corrective_01/SHA256SUMS": sha256_file(
                PREVIOUS_CORRECTIVE_ROOT / "SHA256SUMS"
            ),
            "corrective_01/corrective_index.v1.json": sha256_file(
                PREVIOUS_CORRECTIVE_ROOT / "corrective_index.v1.json"
            ),
            "corrective_01/source_checkpoint.v1.json": sha256_file(
                PREVIOUS_CORRECTIVE_ROOT / "source_checkpoint.v1.json"
            ),
            "validation/final_closeout_corrective_01.v1.json": sha256_file(
                PREVIOUS_GATE_PATH
            ),
        },
        "source_records": source_records,
    }
    checkpoint = {
        **checkpoint_payload,
        "checkpoint_sha256": canonical_sha256(checkpoint_payload),
    }
    CORRECTIVE_ROOT.mkdir(parents=True, exist_ok=True)
    checkpoint_path = CORRECTIVE_ROOT / "source_checkpoint.v1.json"
    write_json_atomic(checkpoint_path, checkpoint)

    gate_payload = {
        "schema": "ias.s4_4.amendment_03_final_closeout_corrective.v1",
        **gate_results,
        "status": "passed",
        "validation_scope": "corrective_02_source_and_scientific_evidence",
        "pre_corrective_validation_status": "incomplete",
        "incomplete_only_because_corrective_02_was_not_yet_materialized": True,
        "historical_records_rewritten": False,
        "scientific_holdout_outcomes_inspected": False,
        "S4.5_or_later_started": False,
    }
    gate = {**gate_payload, "gate_sha256": canonical_sha256(gate_payload)}
    write_json_atomic(GATE_PATH, gate)

    records = [
        *(_record(relative, "corrected_source") for relative in SOURCE_PATHS),
        _record(FINAL_DOCUMENT_PATH, "authoritative_final_closeout"),
        _record(
            checkpoint_path.relative_to(ROOT).as_posix(),
            "corrective_source_checkpoint",
        ),
        _record(
            GATE_PATH.relative_to(ROOT).as_posix(),
            "corrective_final_gate",
        ),
    ]
    records.sort(key=lambda item: item["path"])
    index_payload = {
        "schema": "ias.s4_4.amendment_03_corrective_index.v1",
        "status": "passed",
        "amendment_id": "s4_4_data_expansion_amendment_03",
        "correction_id": CORRECTION_ID,
        "supersedes_correction_id": "corrective_01",
        "previous_corrective_sha256": checkpoint_payload[
            "previous_corrective_sha256"
        ],
        "source_checkpoint_sha256": sha256_file(checkpoint_path),
        "final_gate_sha256": sha256_file(GATE_PATH),
        "record_count": len(records),
        "records": records,
        "historical_v1_v5_rewritten": False,
        "historical_closeout_checksums_rewritten": False,
        "reduced_mac_readiness_authoritative": True,
        "legacy_readiness_extra_fields_optional": True,
        "technical_qa_canonical_projection": ("ias.s4_4.amendment_technical_qa.v2"),
        "fit_b_complete": True,
        "prospective_holdout_complete": True,
        "prospective_holdout_scientifically_opened": False,
        "S4.5_or_later_started": False,
        "census": EXPECTED_CENSUS,
    }
    index = {
        **index_payload,
        "corrective_index_sha256": canonical_sha256(index_payload),
    }
    index_path = CORRECTIVE_ROOT / "corrective_index.v1.json"
    write_json_atomic(index_path, index)
    checksum_path = CORRECTIVE_ROOT / "SHA256SUMS"
    checksum_path.write_text(
        "".join(f"{record['sha256']}  {record['path']}\n" for record in records),
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "source_commit": source_commit,
        "record_count": len(records),
        "source_checkpoint_sha256": sha256_file(checkpoint_path),
        "final_gate_sha256": sha256_file(GATE_PATH),
        "corrective_index_sha256": sha256_file(index_path),
        "checksum_sha256": sha256_file(checksum_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--gate-results", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(
            source_commit=args.source_commit,
            gate_results_path=args.gate_results,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 Amendment 03 corrective build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
