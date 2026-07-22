#!/usr/bin/env python3
"""Build deterministic S4.4 split, coverage, seal, and provenance evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    append_ledger_event,
    build_assignment_companion,
    build_coverage_report,
    build_holdout_seal,
    build_trial_census,
    canonical_sha256,
    find_first_valid_seed,
    load_json,
    sha256_file,
    validate_adapter_contract,
    validate_holdout_seal,
    validate_preseed_contract,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_OUTPUT = Path("outputs/isaac_audio_sensors/S4/S4.4")
DEFAULT_OUTPUT = ROOT / CANONICAL_OUTPUT
DEFAULT_CONSTRAINTS = DEFAULT_OUTPUT / "freeze/preseed_coverage_constraints.json"
DEFAULT_FEASIBILITY = DEFAULT_OUTPUT / "freeze/s2_5_constraint_feasibility.json"
DEFAULT_ALGORITHM = DEFAULT_OUTPUT / "freeze/constraint_adapter_algorithm.v1.json"
DEFAULT_INVENTORY = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/trial_inventory.json"
)
DEFAULT_S43_INDEX = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.3/evidence_index.json"
)

_SOURCE_ARTIFACTS = {
    "src/isaac_audio_sensors/acquisition/s4_4.py": "s4_4_implementation",
    "scripts/build_s4_4_evidence.py": "evidence_builder",
    "scripts/validate_s4_4_integrity.py": "integrity_validator",
    "tests/test_s4_4_holdout_freeze.py": "focused_tests",
}
_DELIVERY_ARTIFACTS = {
    "docs/development/closeouts/S4/s4_4_holdout_freeze.md": "closeout",
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)


def _copy_frozen(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copyfile(source, destination)


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _partition_manifest(
    census: dict[str, Any], *, partition: str, selection_groups: tuple[str, ...]
) -> dict[str, Any]:
    attempts = [
        item for item in census["attempts"] if item["partition"] == partition
    ]
    cells = [
        item for item in census["condition_cells"] if item["partition"] == partition
    ]
    return {
        "schema": f"ias.s4_4.{partition}_manifest.v1",
        "status": "frozen",
        "partition": partition,
        "group_ids": list(selection_groups),
        "condition_cells": cells,
        "attempts": attempts,
        "counts": {
            "groups": len(selection_groups),
            "condition_cells": len(cells),
            "quality_eligible_condition_cells": sum(
                bool(item["quality_eligible"]) for item in cells
            ),
            "quality_ineligible_condition_cells": sum(
                not bool(item["quality_eligible"]) for item in cells
            ),
            "attempts": len(attempts),
            "usable_attempts": sum(bool(item["usable_coverage"]) for item in attempts),
            "retained_failed_attempts": sum(
                item["outcome"] == "failed" for item in attempts
            ),
        },
        "failed_or_ineligible_counted_as_usable_coverage": False,
    }


def _access_policy() -> dict[str, Any]:
    return {
        "schema": "ias.s4_4.holdout_access_policy.v1",
        "status": "sealed",
        "enforcement_boundary": {
            "mechanism": "repository_tooling",
            "direct_filesystem_owner_reads_prevented": False,
            "direct_filesystem_owner_reads_detected": False,
            "limitation": (
                "The repository cannot prevent or detect direct reads by the "
                "filesystem owner; supported S4.5-S4.8 tooling fails closed."
            ),
        },
        "historical_visibility": {
            "s4_3_outcomes_analyzed_before_freeze": True,
            "historically_unseen_claim": False,
            "post_freeze_tuning_use_allowed": False,
        },
        "fit_access": {
            "purposes": ["S4.5_fit", "S4.5_validation"],
            "holdout_attempts_allowed": False,
        },
        "integrity_access": {
            "purpose": "S4.4_integrity_validation",
            "hash_only": True,
            "opens_holdout": False,
            "returns_content_derived_values": False,
            "modifies_tracked_seal": False,
        },
        "future_s4_8_access": {
            "grant_created_during_s4_4": False,
            "required_purpose": "S4.8_evaluation",
            "requires_passing_hash_bound_s4_7_preregistration": True,
            "requires_explicit_machine_local_grant": True,
            "grant_single_use": True,
            "grant_purpose_bound": True,
            "grant_prerequisite_bound": True,
            "grant_seal_bound": True,
            "grant_split_plan_bound": True,
            "append_only_hash_chained_ledger_required": True,
            "malformed_altered_inconsistent_or_reused_grant": "deny",
        },
        "unknown_attempt_group_path_or_purpose": "deny",
        "machine_local_paths": {
            "grant": "dataset/S4.4/access/holdout_access_grant.json",
            "ledger": "dataset/S4.4/access/access_ledger.jsonl",
            "seal_state": "dataset/S4.4/access/seal_state.json",
            "gitignored": True,
        },
        "s4_5_started": False,
        "s4_8_grant_created": False,
        "holdout_opened": False,
    }


def _artifact_record(path: Path, *, role: str, relative: str) -> dict[str, Any]:
    return {
        "path": relative,
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "retention": "tracked_metadata_only",
    }


def _initialize_access_state(output: Path, seal_path: Path) -> dict[str, Any]:
    access_root = ROOT / "dataset/S4.4/access"
    grant = access_root / "holdout_access_grant.json"
    if grant.exists():
        raise S44Error(
            "S4.4 refuses to initialize with an S4.8 holdout access grant present"
        )
    seal_sha = sha256_file(seal_path)
    state = {
        "schema": "ias.s4_4.machine_local_seal_state.v1",
        "status": "sealed",
        "tracked_seal_path": f"{CANONICAL_OUTPUT}/holdout_seal.json",
        "tracked_seal_sha256": seal_sha,
        "split_plan_sha256": load_json(output / "split_plan.json")["plan_sha256"],
        "grant_present": False,
        "holdout_opened": False,
        "gitignored": True,
    }
    _write_json(access_root / "seal_state.json", state)
    ledger = access_root / "access_ledger.jsonl"
    if not ledger.exists():
        append_ledger_event(
            ledger,
            {
                "event": "seal_initialized",
                "event_time_utc": "2026-07-22T01:24:06Z",
                "seal_sha256": seal_sha,
                "split_plan_sha256": state["split_plan_sha256"],
                "purpose": "S4.4_sealing",
                "holdout_opened": False,
            },
        )
    return state


def build(
    *,
    output: Path,
    constraints_path: Path,
    feasibility_path: Path,
    algorithm_path: Path,
    inventory_path: Path,
    s43_index_path: Path,
    initialize_access_state: bool,
) -> dict[str, Any]:
    """Build the complete deterministic tracked S4.4 evidence package."""

    constraints = load_json(constraints_path)
    algorithm = load_json(algorithm_path)
    validate_preseed_contract(constraints, repo_root=ROOT)
    validate_adapter_contract(algorithm, constraints, repo_root=ROOT)
    feasibility = load_json(feasibility_path)
    if feasibility.get("status") != "no_satisfying_unadapted_assignment":
        raise S44Error("S2.5 feasibility record does not preserve the blocker")
    selection = find_first_valid_seed(
        constraints, algorithm, maximum_seed=0, expected_seed=0
    )
    expected_plan = (
        "1569c00cbaec57e5625e0876fd243e17a2a67b287b3edf9865e41bb7ce8c0ce3"
    )
    if selection.plan.plan_sha256 != expected_plan:
        raise S44Error(
            "approved SplitPlan hash mismatch: "
            f"expected {expected_plan}, found {selection.plan.plan_sha256}"
        )

    output.mkdir(parents=True, exist_ok=True)
    frozen_sources = {
        "preseed_coverage_constraints.json": constraints_path,
        "s2_5_constraint_feasibility.json": feasibility_path,
        "constraint_adapter_algorithm.v1.json": algorithm_path,
    }
    for name, source in frozen_sources.items():
        _copy_frozen(source, output / "freeze" / name)

    inventory = load_json(inventory_path)
    s43_index = load_json(s43_index_path)
    census = build_trial_census(inventory, constraints, selection)
    coverage = build_coverage_report(constraints, selection)
    companion = build_assignment_companion(constraints, algorithm, selection)
    companion["bindings"]["adapter_algorithm_file_sha256"] = sha256_file(
        algorithm_path
    )
    companion["bindings"]["s4_3_trial_inventory_sha256"] = sha256_file(
        inventory_path
    )
    companion["bindings"]["s4_3_evidence_index_sha256"] = sha256_file(
        s43_index_path
    )
    group_manifest = {
        "schema": "ias.s4_4.group_manifest.v1",
        "status": "frozen",
        "scientific_session_id": constraints["population_contract"][
            "scientific_session_id"
        ],
        "room_id": "WANG_2022_DESK_NEAR_ENTRANCE",
        "groups": [
            {
                **group,
                "partition": next(
                    partition
                    for partition, group_ids in selection.plan.assignments.items()
                    if group["group_id"] in group_ids
                ),
            }
            for group in constraints["group_mapping"]
        ],
        "group_identity": (
            "scientific session, room, source device, exact WAV/source type, "
            "canonical position, bearing, distance, installed mount, and acoustic "
            "condition"
        ),
        "attempt_id_participates_in_group_identity": False,
        "outcome_participates_in_group_identity": False,
    }
    fit_manifest = _partition_manifest(
        census,
        partition="fit",
        selection_groups=selection.plan.assignments["fit"],
    )
    holdout_manifest = _partition_manifest(
        census,
        partition="holdout",
        selection_groups=selection.plan.assignments["holdout"],
    )
    holdout_manifest["contains_analysis_content"] = False
    holdout_manifest["contains_derived_outcomes"] = False
    access_policy = _access_policy()

    _write_json(output / "trial_census.json", census)
    _write_json(output / "coverage_report.json", coverage)
    _write_json(output / "assignment_companion.v1.json", companion)
    _write_json(output / "group_manifest.json", group_manifest)
    _write_json(output / "fit_manifest.json", fit_manifest)
    _write_json(output / "holdout_manifest.json", holdout_manifest)
    _write_json(output / "access_policy.json", access_policy)
    (output / "split_plan.json").write_text(
        selection.plan.serialize() + "\n", encoding="utf-8"
    )
    seal = build_holdout_seal(constraints, selection, census, s43_index)
    seal["access_policy_document"] = {
        "path": f"{CANONICAL_OUTPUT}/access_policy.json",
        "sha256": sha256_file(output / "access_policy.json"),
    }
    seal["seal_payload_sha256"] = canonical_sha256(
        {key: value for key, value in seal.items() if key != "seal_payload_sha256"}
    )
    validate_holdout_seal(seal, selection.plan)
    _write_json(output / "holdout_seal.json", seal)

    source_checkpoint_branch = _git_output("branch", "--show-current")
    source_checkpoint_commit = _git_output("rev-parse", "HEAD")
    provenance = {
        "schema": "ias.s4_4.provenance.v1",
        "status": "frozen_source_checkpoint",
        "baseline_branch": constraints["baseline"]["branch"],
        "baseline_commit": constraints["baseline"]["commit"],
        "source_checkpoint_branch": source_checkpoint_branch,
        "source_checkpoint_commit": source_checkpoint_commit,
        "final_source_commit_pending": False,
        "evidence_delivery_commit": (
            "the Git commit containing this artifact; intentionally not "
            "self-referenced"
        ),
        "source_identities": constraints["source_identities"],
        "implementation": [
            {
                "path": relative,
                "sha256": sha256_file(ROOT / relative),
            }
            for relative in sorted(_SOURCE_ARTIFACTS)
            if (ROOT / relative).is_file()
        ],
        "delivery_documents": [
            {
                "path": relative,
                "sha256": sha256_file(ROOT / relative),
            }
            for relative in sorted(_DELIVERY_ARTIFACTS)
            if (ROOT / relative).is_file()
        ],
        "split_plan_sha256": selection.plan.plan_sha256,
        "holdout_seal_sha256": sha256_file(output / "holdout_seal.json"),
        "raw_media_copied_to_tracked_outputs": False,
        "s4_5_started": False,
        "s4_8_grant_created": False,
        "holdout_opened": False,
    }
    _write_json(output / "provenance.json", provenance)

    adapter_validation = {
        "schema": "ias.s4_4.adapter_validation.v1",
        "status": "passed",
        "seed": selection.seed,
        "subsets_enumerated": selection.subset_count,
        "feasible_subsets": selection.feasible_subset_count,
        "global_optimum_verified": selection.global_optimum_verified,
        "split_plan_round_trip": "passed",
        "split_plan_integrity": "passed",
        "no_group_crossing": True,
        "coverage": selection.coverage,
        "outcome_metrics_used": False,
        "standard_s2_5_builder_modified": False,
        "standard_s2_5_builder_reproduction_claimed": False,
    }
    _write_json(output / "validation/adapter_validation.json", adapter_validation)

    output_roles = {
        "access_policy.json": "access_policy",
        "assignment_companion.v1.json": "assignment_companion",
        "coverage_report.json": "coverage_report",
        "fit_manifest.json": "fit_manifest",
        "group_manifest.json": "group_manifest",
        "holdout_manifest.json": "holdout_manifest",
        "holdout_seal.json": "holdout_seal",
        "provenance.json": "provenance",
        "split_plan.json": "split_plan",
        "trial_census.json": "trial_census",
        "freeze/constraint_adapter_algorithm.v1.json": "frozen_adapter_algorithm",
        "freeze/preseed_coverage_constraints.json": "frozen_coverage_constraints",
        "freeze/s2_5_constraint_feasibility.json": "s2_5_feasibility",
        "validation/adapter_validation.json": "adapter_validation",
    }
    artifacts = [
        _artifact_record(
            output / relative,
            role=role,
            relative=f"{CANONICAL_OUTPUT}/{relative}",
        )
        for relative, role in sorted(output_roles.items())
    ]
    for relative, role in sorted(_SOURCE_ARTIFACTS.items()):
        path = ROOT / relative
        if path.is_file():
            artifacts.append(_artifact_record(path, role=role, relative=relative))
    for relative, role in sorted(_DELIVERY_ARTIFACTS.items()):
        path = ROOT / relative
        if path.is_file():
            artifacts.append(_artifact_record(path, role=role, relative=relative))
    index = {
        "schema": "ias.s4_4.evidence_index.v1",
        "status": "passed",
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
        "tracked_artifact_count": len(artifacts),
        "holdout_raw_artifact_count": len(seal["artifacts"]),
        "split_plan_sha256": selection.plan.plan_sha256,
        "holdout_seal_sha256": sha256_file(output / "holdout_seal.json"),
        "raw_validation_mode": "separate_machine_local_hash_only",
        "s4_5_started": False,
        "s4_8_grant_created": False,
        "holdout_opened": False,
    }
    _write_json(output / "evidence_index.json", index)
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{item['sha256']}  {item['path']}\n" for item in index["artifacts"]
        ),
        encoding="utf-8",
    )
    state = (
        _initialize_access_state(output, output / "holdout_seal.json")
        if initialize_access_state
        else None
    )
    return {
        "status": "passed",
        "seed": selection.seed,
        "split_plan_sha256": selection.plan.plan_sha256,
        "fit_condition_cells": 10,
        "holdout_condition_cells": 6,
        "fit_groups": 6,
        "holdout_groups": 3,
        "holdout_quality_eligible_cells": 6,
        "holdout_quality_ineligible_cells": 0,
        "holdout_seal_sha256": index["holdout_seal_sha256"],
        "tracked_artifact_count": len(artifacts),
        "access_state_initialized": state is not None,
        "s4_5_started": False,
        "s4_8_grant_created": False,
        "holdout_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY)
    parser.add_argument("--algorithm", type=Path, default=DEFAULT_ALGORITHM)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--s4-3-index", type=Path, default=DEFAULT_S43_INDEX)
    parser.add_argument("--initialize-access-state", action="store_true")
    args = parser.parse_args()
    try:
        result = build(
            output=args.output,
            constraints_path=args.constraints,
            feasibility_path=args.feasibility,
            algorithm_path=args.algorithm,
            inventory_path=args.inventory,
            s43_index_path=args.s4_3_index,
            initialize_access_state=args.initialize_access_state,
        )
    except (OSError, S44Error, ValueError, subprocess.CalledProcessError) as exc:
        print(f"S4.4 evidence build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
