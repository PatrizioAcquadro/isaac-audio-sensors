#!/usr/bin/env python3
"""Build the deterministic additive S4.4 amendment-03 package."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    build_source_checkpoint,
    canonical_sha256,
    load_json,
    sha256_file,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    LOGICAL_COUNTS,
    S44AmendmentError,
    build_aggregate_index,
    build_continuation_reference,
    build_future_manifests,
    build_inherited_fit_a,
    build_precollection_seal,
    combined_future_manifest,
    load_configuration,
    validate_configuration,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_predecessor_bytes,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_ID = "s4_4_data_expansion_amendment_03"
DEFAULT_CONFIG = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
DEFAULT_OUTPUT = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments" / AMENDMENT_ID
CHECKPOINT_PATH = "freeze/source_checkpoint.v1.json"
SCHEMA_PATHS = (
    "docs/schemas/s4_4_amendment_aggregate_index.v3.schema.json",
    "docs/schemas/s4_4_amendment_inherited_fit_a.v1.schema.json",
    "docs/schemas/s4_4_amendment_manifest.v3.schema.json",
    "docs/schemas/s4_4_amendment_precollection_seal.v3.schema.json",
    "docs/schemas/s4_4_amendment_session_preflight.v2.schema.json",
    "docs/schemas/s4_4_amendment_session_readiness.v2.schema.json",
)
SOURCE_PATHS = (
    "configs/s4_4_data_expansion_amendment_03.v1.json",
    "docs/development/specs/s4_4_data_expansion_amendment_03.md",
    *SCHEMA_PATHS,
    "scripts/build_s4_4_amendment_03.py",
    "scripts/execute_s4_4_amendment_03_attempt.py",
    "scripts/run_s4_4_amendment_03_readiness.py",
    "scripts/run_s4_4_amendment_03_take.py",
    "scripts/validate_s4_4_amendment_03.py",
    "src/isaac_audio_sensors/acquisition/s4_4_amendment_03.py",
    "tests/test_s4_4_amendment_03.py",
    # Immutable runtime dependencies reused without editing.
    "scripts/execute_s4_4_amendment_attempt.py",
    "scripts/s4_2_mac_preflight.py",
    "scripts/s4_2_pi_capture.py",
    "scripts/preflight_s4_2_zed.py",
    "src/isaac_audio_sensors/acquisition/s4_4_amendment.py",
)
DELIVERY_PATHS = ("docs/development/closeouts/S4/s4_4_data_expansion_amendment_03.md",)


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


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _access_policy(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_4.amendment_03_access_policy.v1",
        "status": "precollection_locked",
        "enforcement_boundary": {
            "mechanism": "repository_tooling",
            "os_level_protection": False,
            "filesystem_owner_direct_reads_prevented_or_detected": False,
        },
        "fit_access": {
            "S4.5_facing_tools_expose_fit_only": True,
            "inherited_amendment_02_fit_a_included": True,
            "new_amendment_03_fit_b_included": True,
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
        "precollection_access_ledger_state": "absent_until_holdout_seal",
        "future_S4.7_or_S4.8_opening_workflow_implemented": False,
        "S4.5_or_later_started": False,
    }


def build(*, output: Path, config_path: Path, repo_root: Path = ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    config = load_configuration(config_path, repo_root)
    validate_configuration(config)
    predecessor_validation = validate_predecessor_bytes(
        config, repo_root, require_machine_local=True
    )
    inherited_fit_a = build_inherited_fit_a(config, repo_root)
    validate_inherited_fit_a(inherited_fit_a, config)
    future = build_future_manifests(config, repo_root)
    fit_b = future["fit_b"]
    holdout = future["prospective_holdout"]
    fit_b_partition = combined_future_manifest(future, "fit")
    holdout_partition = combined_future_manifest(future, "prospective_holdout")
    continuation = build_continuation_reference(config, inherited_fit_a)
    aggregate = build_aggregate_index(config, inherited_fit_a, fit_b, holdout)
    policy = _access_policy(config)

    output.mkdir(parents=True, exist_ok=True)
    _write(output / "freeze/config.v1.json", config)
    _write(output / "freeze/amendment_02_continuation.v1.json", continuation)
    _write(output / "inheritance/inherited_fit_a.v1.json", inherited_fit_a)
    _write(output / "manifests/sessions/fit_b.json", fit_b)
    _write(output / "manifests/sessions/prospective_holdout.json", holdout)
    _write(output / "manifests/fit_b_manifest.v1.json", fit_b_partition)
    _write(output / "manifests/prospective_holdout_manifest.v1.json", holdout_partition)
    _write(output / "aggregate_index.v1.json", aggregate)
    _write(output / "access_policy.v1.json", policy)
    holdout_intent_payload = {
        "schema": "ias.s4_4.amendment_03_holdout_seal_intent.v1",
        "status": "awaiting_collection_and_technical_QA",
        "prospective_holdout_manifest_sha256": holdout_partition[
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

    checkpoint_path = output / CHECKPOINT_PATH
    checkpoint = load_json(checkpoint_path) if checkpoint_path.is_file() else None
    generated_binding_paths = {
        "config_file_sha256": output / "freeze/config.v1.json",
        "continuation_reference_file_sha256": output
        / "freeze/amendment_02_continuation.v1.json",
        "inherited_fit_a_file_sha256": output / "inheritance/inherited_fit_a.v1.json",
        "fit_b_session_manifest_file_sha256": output / "manifests/sessions/fit_b.json",
        "holdout_session_manifest_file_sha256": output
        / "manifests/sessions/prospective_holdout.json",
        "fit_b_partition_manifest_file_sha256": output
        / "manifests/fit_b_manifest.v1.json",
        "holdout_partition_manifest_file_sha256": output
        / "manifests/prospective_holdout_manifest.v1.json",
        "aggregate_index_file_sha256": output / "aggregate_index.v1.json",
        "access_policy_file_sha256": output / "access_policy.v1.json",
        "holdout_seal_intent_file_sha256": output
        / "prospective_holdout_seal_intent.v1.json",
    }
    bindings = {key: sha256_file(path) for key, path in generated_binding_paths.items()}
    for relative in SCHEMA_PATHS:
        bindings["schema_" + Path(relative).stem.replace(".", "_") + "_sha256"] = (
            sha256_file(repo_root / relative)
        )
    bindings.update(
        {
            "amendment_01_tracked_tree_sha256": config["immutable_predecessors"][
                "amendment_01"
            ]["tracked_tree_sha256"],
            "amendment_01_machine_local_tree_sha256": config["immutable_predecessors"][
                "amendment_01"
            ]["machine_local_tree_sha256"],
            "amendment_02_tracked_tree_sha256": config["immutable_predecessors"][
                "amendment_02"
            ]["tracked_tree_sha256"],
            "amendment_02_machine_local_tree_sha256": config["immutable_predecessors"][
                "amendment_02"
            ]["machine_local_tree_sha256"],
            "amendment_02_precollection_seal_file_sha256": config[
                "immutable_predecessors"
            ]["amendment_02"]["precollection_seal_file_sha256"],
        }
    )
    seal = build_precollection_seal(bindings=bindings, checkpoint=checkpoint)
    validate_precollection_seal(
        seal, repo_root=repo_root, require_committed=checkpoint is not None
    )
    _write(output / "precollection_seal.v1.json", seal)

    validation = {
        "schema": "ias.s4_4.amendment_03_precollection_validation.v1",
        "status": "passed",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "logical_counts": LOGICAL_COUNTS,
        "new_planned_counts": {"fit_b": 51, "prospective_holdout": 47},
        "inherited_fit_a_census": {
            "logical_cells": 51,
            "attempts": 52,
            "valid_cells": 51,
            "failures": 1,
            "replacements": 1,
        },
        "same_calendar_date_permitted": True,
        "truthful_dates_timestamps_and_distinct_session_ids_required": True,
        "restart_or_reconnection_required": False,
        "live_readiness_required": True,
        "no_fit_holdout_group_crossing": True,
        "predecessor_bytes_unchanged": True,
        "predecessor_validation": predecessor_validation,
        "holdout_scientifically_opened": False,
        "S4.5_or_later_started": False,
    }
    _write(output / "validation/precollection_validation.json", validation)

    generated_roles = {
        "access_policy.v1.json": "access_policy",
        "aggregate_index.v1.json": "aggregate_logical_index",
        "freeze/amendment_02_continuation.v1.json": "immutable_continuation_reference",
        "freeze/config.v1.json": "resolved_configuration",
        "inheritance/inherited_fit_a.v1.json": "inherited_fit_a_inventory",
        "manifests/fit_b_manifest.v1.json": "future_fit_b_partition_manifest",
        "manifests/prospective_holdout_manifest.v1.json": (
            "future_prospective_holdout_partition_manifest"
        ),
        "manifests/sessions/fit_b.json": "future_fit_b_session_manifest",
        "manifests/sessions/prospective_holdout.json": (
            "future_prospective_holdout_session_manifest"
        ),
        "precollection_seal.v1.json": "precollection_seal",
        "prospective_holdout_seal_intent.v1.json": "holdout_seal_intent",
        "validation/precollection_validation.json": "precollection_validation",
    }
    if checkpoint_path.is_file():
        generated_roles[CHECKPOINT_PATH] = "source_checkpoint"
    canonical_output = Path(config["retention"]["tracked_evidence_root"])
    artifacts = [
        _artifact(output / relative, f"{canonical_output}/{relative}", role)
        for relative, role in sorted(generated_roles.items())
    ]
    for relative in SOURCE_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise S44AmendmentError(f"required amendment_03 source absent: {relative}")
        role = (
            "immutable_runtime_dependency"
            if "amendment_03" not in relative
            and not relative.startswith("docs/schemas/s4_4_amendment_")
            else "amendment_source"
        )
        artifacts.append(_artifact(path, relative, role))
    for relative in DELIVERY_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise S44AmendmentError(
                f"required amendment_03 closeout absent: {relative}"
            )
        artifacts.append(_artifact(path, relative, "amendment_closeout"))
    evidence_index = {
        "schema": "ias.s4_4.amendment_03_evidence_index.v1",
        "status": "precollection_frozen",
        "commit_status": seal["status"],
        "collection_allowed": seal["collection_allowed"],
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
        "artifact_count": len(artifacts),
        "logical_counts": LOGICAL_COUNTS,
        "new_planned_counts": {"fit_b": 51, "prospective_holdout": 47},
        "precollection_seal_sha256": sha256_file(output / "precollection_seal.v1.json"),
        "inherited_fit_a_sha256": inherited_fit_a["inherited_fit_a_sha256"],
        "prospective_holdout_scientifically_opened": False,
        "amendment_01_unchanged": True,
        "amendment_02_unchanged": True,
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
        "logical_counts": LOGICAL_COUNTS,
        "fit_b_manifest_sha256": fit_b["manifest_sha256"],
        "prospective_holdout_manifest_sha256": holdout["manifest_sha256"],
        "aggregate_index_sha256": aggregate["aggregate_index_sha256"],
        "inherited_fit_a_sha256": inherited_fit_a["inherited_fit_a_sha256"],
        "precollection_seal_file_sha256": evidence_index["precollection_seal_sha256"],
        "amendment_01_tracked_tree_sha256": config["immutable_predecessors"][
            "amendment_01"
        ]["tracked_tree_sha256"],
        "amendment_02_tracked_tree_sha256": config["immutable_predecessors"][
            "amendment_02"
        ]["tracked_tree_sha256"],
        "amendment_02_machine_local_tree_sha256": config["immutable_predecessors"][
            "amendment_02"
        ]["machine_local_tree_sha256"],
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
            checkpoint = build_source_checkpoint(ROOT, _git_head(ROOT), SOURCE_PATHS)
            if checkpoint_path.is_file() and load_json(checkpoint_path) != checkpoint:
                raise S44AmendmentError(
                    "refusing to replace a different amendment_03 source checkpoint"
                )
            _write(checkpoint_path, checkpoint)
        summary = build(output=args.output, config_path=args.config)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"S4.4 amendment-03 build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
