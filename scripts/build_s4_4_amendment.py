#!/usr/bin/env python3
"""Build the deterministic S4.4 data-expansion precollection package."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    build_aggregate_index,
    build_manifests,
    build_precollection_seal,
    build_source_checkpoint,
    canonical_sha256,
    combined_partition_manifest,
    load_json,
    sha256_file,
    validate_configuration,
    validate_manifests,
    validate_precollection_seal,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_01"
CANONICAL_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.4/amendments") / AMENDMENT_ID
DEFAULT_OUTPUT = ROOT / CANONICAL_OUTPUT
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"
CHECKPOINT_PATH = "freeze/source_checkpoint.v1.json"
SOURCE_PATHS = (
    "configs/s4_4_data_expansion_amendment_01.v1.json",
    "docs/development/specs/s4_4_data_expansion_amendment_01.md",
    "docs/schemas/s4_4_amendment_aggregate_index.v1.schema.json",
    "docs/schemas/s4_4_amendment_attempt_census.v1.schema.json",
    "docs/schemas/s4_4_amendment_manifest.v1.schema.json",
    "docs/schemas/s4_4_amendment_precollection_seal.v1.schema.json",
    "docs/schemas/s4_4_amendment_session_preflight.v1.schema.json",
    "docs/schemas/s4_4_amendment_technical_qa.v1.schema.json",
    "scripts/build_s4_4_amendment.py",
    "scripts/run_s4_4_amendment_take.py",
    "scripts/validate_s4_4_amendment.py",
    "src/isaac_audio_sensors/acquisition/s4_4_amendment.py",
    "tests/test_s4_4_amendment.py",
)
DELIVERY_PATHS = ("docs/development/closeouts/S4/s4_4_data_expansion_amendment_01.md",)
SCHEMA_PATHS = tuple(path for path in SOURCE_PATHS if path.startswith("docs/schemas/"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)


def _artifact(path: Path, relative: str, role: str) -> dict[str, Any]:
    return {
        "path": relative,
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "retention": "tracked_metadata_only",
    }


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _access_policy(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_4.amendment_access_policy.v1",
        "status": "precollection_locked",
        "enforcement_boundary": {
            "mechanism": "repository_tooling",
            "os_level_protection": False,
            "filesystem_owner_direct_reads_prevented_or_detected": False,
        },
        "fit_access": {
            "S4.5_facing_tools_expose_fit_only": True,
            "prospective_holdout_allowed": False,
        },
        "prospective_holdout_technical_qa": {
            "allowed": [
                "identity_and_assigned_metadata",
                "duration",
                "channel_order_and_health",
                "clipping",
                "timestamps",
                "required_reference_presence",
                "file_integrity_and_checksums",
                "privacy",
                "full_svo2_replay",
            ],
            "scientific_outputs_suppressed": True,
            "scientifically_opened": False,
        },
        "sealed_integrity": {
            "hash_only": True,
            "returns_media_analysis_or_scientific_outcomes": False,
        },
        "unknown_path_purpose_group_grant_or_record": "deny",
        "missing_or_altered_manifest_seal_ledger_or_hash": "deny",
        "separate_access_ledger": config["retention"]["access_root"]
        + "/access_ledger.jsonl",
        "future_S4.7_or_S4.8_opening_workflow_implemented": False,
        "S4.5_or_later_started": False,
    }


def build(
    *,
    output: Path,
    config_path: Path,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    """Build all deterministic precollection metadata."""

    repo_root = repo_root.resolve()
    config = load_json(config_path)
    validate_configuration(config, repo_root)
    manifests = build_manifests(config)
    validate_manifests(manifests, config)

    output.mkdir(parents=True, exist_ok=True)
    (output / "freeze").mkdir(parents=True, exist_ok=True)
    if config_path.resolve() != (output / "freeze/config.v1.json").resolve():
        shutil.copyfile(config_path, output / "freeze/config.v1.json")
    for session_id, manifest in manifests.items():
        _write(output / f"manifests/sessions/{session_id}.json", manifest)

    fit_manifest = combined_partition_manifest(manifests, "fit")
    holdout_manifest = combined_partition_manifest(manifests, "prospective_holdout")
    _write(output / "manifests/fit_manifest.v1.json", fit_manifest)
    _write(output / "manifests/prospective_holdout_manifest.v1.json", holdout_manifest)

    aggregate = build_aggregate_index(
        config,
        fit_manifest_sha256=fit_manifest["partition_manifest_sha256"],
        holdout_manifest_sha256=holdout_manifest["partition_manifest_sha256"],
    )
    _write(output / "aggregate_index.v1.json", aggregate)
    policy = _access_policy(config)
    _write(output / "access_policy.v1.json", policy)
    holdout_intent_payload = {
        "schema": "ias.s4_4.amendment_holdout_seal_intent.v1",
        "status": "awaiting_collection_and_technical_QA",
        "prospective_holdout_manifest_sha256": holdout_manifest[
            "partition_manifest_sha256"
        ],
        "planned_take_count": 47,
        "scientifically_opened": False,
        "technical_qa_only": True,
        "scientific_outputs_allowed": False,
        "repository_tool_enforcement_only": True,
        "future_opening_workflow_implemented": False,
    }
    holdout_intent = {
        **holdout_intent_payload,
        "seal_intent_sha256": canonical_sha256(holdout_intent_payload),
    }
    _write(output / "prospective_holdout_seal_intent.v1.json", holdout_intent)

    checkpoint_file = output / CHECKPOINT_PATH
    checkpoint = load_json(checkpoint_file) if checkpoint_file.is_file() else None
    bindings = {
        "config_file_sha256": sha256_file(output / "freeze/config.v1.json"),
        "fit_a_manifest_file_sha256": sha256_file(
            output / "manifests/sessions/fit_a.json"
        ),
        "fit_b_manifest_file_sha256": sha256_file(
            output / "manifests/sessions/fit_b.json"
        ),
        "holdout_session_manifest_file_sha256": sha256_file(
            output / "manifests/sessions/prospective_holdout.json"
        ),
        "fit_partition_manifest_file_sha256": sha256_file(
            output / "manifests/fit_manifest.v1.json"
        ),
        "holdout_partition_manifest_file_sha256": sha256_file(
            output / "manifests/prospective_holdout_manifest.v1.json"
        ),
        "aggregate_index_file_sha256": sha256_file(output / "aggregate_index.v1.json"),
        "access_policy_file_sha256": sha256_file(output / "access_policy.v1.json"),
        "holdout_seal_intent_file_sha256": sha256_file(
            output / "prospective_holdout_seal_intent.v1.json"
        ),
        **{
            "schema_" + Path(relative).stem.replace(".", "_") + "_sha256": sha256_file(
                repo_root / relative
            )
            for relative in SCHEMA_PATHS
        },
    }
    seal = build_precollection_seal(config, bindings=bindings, checkpoint=checkpoint)
    validate_precollection_seal(
        seal, repo_root=repo_root, require_committed=checkpoint is not None
    )
    _write(output / "precollection_seal.v1.json", seal)

    validation = {
        "schema": "ias.s4_4.amendment_precollection_validation.v1",
        "status": "passed",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "counts": {
            "fit": 102,
            "prospective_holdout": 47,
            "total": 149,
            "sessions": 3,
        },
        "exact_matrix_and_order": True,
        "room_bounds_valid": True,
        "deterministic_ids_and_hashes": True,
        "no_fit_holdout_group_crossing": True,
        "original_s4_4_byte_set_unchanged": True,
        "historical_split_plan_payload_sha256": config["historical_freeze"][
            "split_plan_payload_sha256"
        ],
        "S4.5_or_later_started": False,
    }
    _write(output / "validation/precollection_validation.json", validation)

    generated_roles = {
        "access_policy.v1.json": "access_policy",
        "aggregate_index.v1.json": "aggregate_index",
        "freeze/config.v1.json": "frozen_configuration",
        "manifests/fit_manifest.v1.json": "fit_partition_manifest",
        "manifests/prospective_holdout_manifest.v1.json": (
            "prospective_holdout_partition_manifest"
        ),
        "manifests/sessions/fit_a.json": "fit_a_session_manifest",
        "manifests/sessions/fit_b.json": "fit_b_session_manifest",
        "manifests/sessions/prospective_holdout.json": "holdout_session_manifest",
        "precollection_seal.v1.json": "precollection_seal",
        "prospective_holdout_seal_intent.v1.json": "holdout_seal_intent",
        "validation/precollection_validation.json": "precollection_validation",
    }
    if checkpoint_file.is_file():
        generated_roles[CHECKPOINT_PATH] = "source_checkpoint"
    artifacts = [
        _artifact(
            output / relative,
            f"{CANONICAL_OUTPUT}/{relative}",
            role,
        )
        for relative, role in sorted(generated_roles.items())
    ]
    for relative in SOURCE_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise S44AmendmentError(f"required amendment source absent: {relative}")
        artifacts.append(_artifact(path, relative, "amendment_source"))
    for relative in DELIVERY_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise S44AmendmentError(
                f"required amendment delivery document absent: {relative}"
            )
        artifacts.append(_artifact(path, relative, "amendment_closeout"))
    evidence_index = {
        "schema": "ias.s4_4.amendment_evidence_index.v1",
        "status": "precollection_frozen",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
        "artifact_count": len(artifacts),
        "planned_counts": {"fit": 102, "prospective_holdout": 47, "total": 149},
        "precollection_seal_sha256": sha256_file(output / "precollection_seal.v1.json"),
        "prospective_holdout_scientifically_opened": False,
        "original_s4_4_unchanged": True,
        "raw_media_tracked": False,
        "S4.5_or_later_started": False,
    }
    _write(output / "evidence_index.v1.json", evidence_index)
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{item['sha256']}  {item['path']}\n"
            for item in evidence_index["artifacts"]
        ),
        encoding="utf-8",
    )
    return {
        "status": "passed",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "fit_takes": 102,
        "prospective_holdout_takes": 47,
        "planned_total": 149,
        "fit_manifest_sha256": fit_manifest["partition_manifest_sha256"],
        "prospective_holdout_manifest_sha256": holdout_manifest[
            "partition_manifest_sha256"
        ],
        "aggregate_index_sha256": aggregate["aggregate_index_sha256"],
        "precollection_seal_file_sha256": evidence_index["precollection_seal_sha256"],
        "historical_split_plan_payload_sha256": config["historical_freeze"][
            "split_plan_payload_sha256"
        ],
        "prospective_holdout_scientifically_opened": False,
        "S4.5_or_later_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--freeze-source-checkpoint", action="store_true")
    args = parser.parse_args()
    try:
        if args.freeze_source_checkpoint:
            checkpoint_path = args.output / CHECKPOINT_PATH
            checkpoint = build_source_checkpoint(ROOT, _git_head(), SOURCE_PATHS)
            if checkpoint_path.is_file() and load_json(checkpoint_path) != checkpoint:
                raise S44AmendmentError(
                    "refusing to replace a different immutable source checkpoint"
                )
            _write(checkpoint_path, checkpoint)
        summary = build(output=args.output, config_path=args.config)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
