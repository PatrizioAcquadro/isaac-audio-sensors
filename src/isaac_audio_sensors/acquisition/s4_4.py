"""Deterministic S4.4 grouped freeze and fail-closed holdout access controls."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from isaac_audio_sensors.core.dataset.splits import SplitPlan, verify_no_leakage

PRESEED_SCHEMA = "ias.s4_4.preseed_coverage_constraints.v1"
ADAPTER_SCHEMA = "ias.s4_4.constraint_adapter_algorithm.v1"
ADAPTER_ID = "ias.s4_4.constraint_aware_group_adapter.v1"
SEAL_SCHEMA = "ias.s4_4.holdout_seal.v1"
GRANT_SCHEMA = "ias.s4_4.holdout_access_grant.v1"
LEDGER_SCHEMA = "ias.s4_4.access_ledger_event.v1"
SOURCE_CHECKPOINT_SCHEMA = "ias.s4_4.source_checkpoint.v1"
S43_ROOM_ID = "WANG_2022_DESK_NEAR_ENTRANCE"
ZERO_SHA256 = "0" * 64

_HOLDOUT_ATTEMPT_FIELDS = {
    "attempt_id",
    "attempt_root",
    "category",
    "eligibility_reason",
    "group_id",
    "lifecycle_state",
    "outcome",
    "partition",
    "quality_status",
    "retained",
    "trial_id",
    "usable_coverage",
}
_HOLDOUT_CONDITION_FIELDS = {
    "attempt_count",
    "category",
    "eligibility_reason",
    "group_id",
    "partition",
    "quality_eligible",
    "trial_id",
}

_GROUP_FIELDS = {
    "group_id",
    "category",
    "condition_cell_weight",
    "quality_eligible_condition_cells",
    "quality_ineligible_condition_cells",
    "retained_failed_attempts",
    "trial_ids",
    "source_device",
    "source_type",
    "source_identity",
    "position_m_f_project",
    "bearing_deg_f_project",
    "distance_m",
    "mounting_condition",
    "acoustic_condition",
}
_KNOWN_PURPOSES = {
    "S4.4_integrity_validation",
    "S4.5_fit",
    "S4.5_validation",
    "S4.8_evaluation",
}


class S44Error(ValueError):
    """A located S4.4 contract, integrity, or access-control failure."""


@dataclass(frozen=True, slots=True)
class AdapterSelection:
    """One exhaustive, deterministic constraint-aware S4.4 assignment."""

    seed: int
    plan: SplitPlan
    score_order: tuple[str, ...]
    ranking_key: tuple[Any, ...]
    subset_count: int
    feasible_subset_count: int
    coverage: dict[str, int]
    global_optimum_verified: bool


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of canonical compact JSON."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_blob(repo_root: Path, commit: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", "--no-ext-diff", f"{commit}:{relative}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S44Error(
            f"source checkpoint: {relative} is absent from exact commit {commit}"
        )
    return result.stdout


def _checkpoint_records(
    repo_root: Path, commit: str, paths: tuple[str, ...], label: str
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for relative in sorted(paths):
        safe = _safe_relative(relative, f"source checkpoint {label} path")
        candidate = repo_root / safe
        if not candidate.is_file():
            raise S44Error(f"source checkpoint: missing working checkout file {safe}")
        blob_sha256 = hashlib.sha256(_git_blob(repo_root, commit, safe)).hexdigest()
        working_sha256 = sha256_file(candidate)
        if working_sha256 != blob_sha256:
            raise S44Error(
                "source checkpoint: working checkout differs from exact commit "
                f"for {safe}"
            )
        records.append({"path": safe, "sha256": blob_sha256})
    return records


def build_source_checkpoint_contract(
    *,
    repo_root: Path,
    branch: str,
    commit: str,
    source_paths: tuple[str, ...],
    frozen_input_paths: tuple[str, ...],
) -> dict[str, Any]:
    """Create a self-hashed contract for one exact committed S4.4 source tree."""

    repo_root = repo_root.resolve()
    if not isinstance(branch, str) or not branch:
        raise S44Error("source checkpoint branch: expected non-empty string")
    _require_git_commit(commit, "source checkpoint commit")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        raise S44Error(f"source checkpoint commit does not exist: {commit}")
    payload: dict[str, Any] = {
        "schema": SOURCE_CHECKPOINT_SCHEMA,
        "status": "frozen",
        "source_checkpoint_branch": branch,
        "source_checkpoint_commit": commit,
        "source_artifacts": _checkpoint_records(
            repo_root, commit, source_paths, "source_artifacts"
        ),
        "frozen_inputs": _checkpoint_records(
            repo_root, commit, frozen_input_paths, "frozen_inputs"
        ),
    }
    return {**payload, "contract_sha256": canonical_sha256(payload)}


def validate_source_checkpoint_contract(
    contract: dict[str, Any],
    *,
    repo_root: Path,
    expected_source_paths: tuple[str, ...],
    expected_frozen_input_paths: tuple[str, ...],
) -> None:
    """Validate one immutable checkpoint against exact files and Git blobs."""

    required = {
        "schema",
        "status",
        "source_checkpoint_branch",
        "source_checkpoint_commit",
        "source_artifacts",
        "frozen_inputs",
        "contract_sha256",
    }
    if set(contract) != required:
        raise S44Error(
            "source checkpoint fields: expected "
            f"{sorted(required)}, found {sorted(contract)}"
        )
    if contract["schema"] != SOURCE_CHECKPOINT_SCHEMA:
        raise S44Error("source checkpoint schema: invalid")
    if contract["status"] != "frozen":
        raise S44Error("source checkpoint status: expected frozen")
    commit = _require_git_commit(
        contract["source_checkpoint_commit"], "source checkpoint commit"
    )
    supplied_hash = _require_sha256(
        contract["contract_sha256"], "source checkpoint contract hash"
    )
    payload = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if supplied_hash != canonical_sha256(payload):
        raise S44Error("source checkpoint contract hash mismatch")
    repo_root = repo_root.resolve()
    record_sets = (
        ("source_artifacts", expected_source_paths),
        ("frozen_inputs", expected_frozen_input_paths),
    )
    for field, expected_paths in record_sets:
        records = contract[field]
        if not isinstance(records, list):
            raise S44Error(f"source checkpoint {field}: expected list")
        if any(not isinstance(record, dict) for record in records):
            raise S44Error(f"source checkpoint {field}: invalid record")
        if any(set(record) != {"path", "sha256"} for record in records):
            raise S44Error(f"source checkpoint {field}: invalid record fields")
        paths = tuple(record["path"] for record in records)
        if paths != tuple(sorted(expected_paths)):
            raise S44Error(f"source checkpoint {field}: exact path set mismatch")
        for record in records:
            relative = _safe_relative(
                record["path"], f"source checkpoint {field}.path"
            )
            expected_sha256 = _require_sha256(
                record["sha256"], f"source checkpoint {field}.sha256"
            )
            candidate = repo_root / relative
            if not candidate.is_file() or sha256_file(candidate) != expected_sha256:
                raise S44Error(
                    "source checkpoint: working checkout hash mismatch for "
                    f"{relative}"
                )
            if (repo_root / ".git").exists():
                blob_sha256 = hashlib.sha256(
                    _git_blob(repo_root, commit, relative)
                ).hexdigest()
                if blob_sha256 != expected_sha256:
                    raise S44Error(
                        "source checkpoint: exact commit content mismatch for "
                        f"{relative}"
                    )


def validate_provenance_source_checkpoint(
    provenance: dict[str, Any],
    contract: dict[str, Any],
    *,
    checkpoint_path: str,
    checkpoint_file_sha256: str,
) -> None:
    """Require provenance to bind exactly to the authoritative checkpoint."""

    if provenance.get("source_checkpoint_commit") != contract.get(
        "source_checkpoint_commit"
    ):
        raise S44Error("provenance does not use the exact source checkpoint commit")
    if provenance.get("source_checkpoint_branch") != contract.get(
        "source_checkpoint_branch"
    ):
        raise S44Error("provenance does not use the exact source checkpoint branch")
    if provenance.get("implementation") != contract.get("source_artifacts"):
        raise S44Error("provenance implementation differs from source checkpoint")
    expected_binding = {
        "path": checkpoint_path,
        "sha256": _require_sha256(
            checkpoint_file_sha256, "source checkpoint file SHA-256"
        ),
        "contract_sha256": contract.get("contract_sha256"),
    }
    if provenance.get("source_checkpoint_contract") != expected_binding:
        raise S44Error("provenance source checkpoint contract binding mismatch")


def holdout_manifest_content_declarations() -> dict[str, Any]:
    """Return the precise, frozen disclosure for held-out manifest metadata."""

    return {
        "historical_s4_3_quality_and_lifecycle_metadata_included": True,
        "included_attempt_metadata_fields": [
            "eligibility_reason",
            "lifecycle_state",
            "outcome",
            "quality_status",
            "usable_coverage",
        ],
        "performance_metrics_included": False,
        "raw_or_analysis_payload_included": False,
        "assignment_used_outcome_metrics": False,
    }


def validate_holdout_manifest_content(manifest: dict[str, Any]) -> None:
    """Enforce honest quality metadata disclosure and metric-free holdout rows."""

    declarations = manifest.get("content_declarations")
    expected = holdout_manifest_content_declarations()
    if not isinstance(declarations, dict):
        raise S44Error("holdout manifest quality and lifecycle declaration missing")
    if declarations != expected:
        raise S44Error("holdout manifest quality and lifecycle declaration mismatch")
    attempts = manifest.get("attempts")
    conditions = manifest.get("condition_cells")
    if not isinstance(attempts, list) or not isinstance(conditions, list):
        raise S44Error("holdout manifest attempts or condition cells invalid")
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or set(attempt) != _HOLDOUT_ATTEMPT_FIELDS:
            raise S44Error(
                "holdout manifest performance metric or unexpected attempt field "
                f"at attempts[{index}]"
            )
    for index, condition in enumerate(conditions):
        if (
            not isinstance(condition, dict)
            or set(condition) != _HOLDOUT_CONDITION_FIELDS
        ):
            raise S44Error(
                "holdout manifest performance metric or unexpected condition field "
                f"at condition_cells[{index}]"
            )


def sha256_file(path: Path) -> str:
    """Hash a file in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object or fail with a located S4.4 error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S44Error(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S44Error(f"{path}: expected a JSON object")
    return value


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise S44Error(f"{label}: expected lowercase SHA-256")
    return value


def _require_git_commit(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise S44Error(f"{label}: expected 40-character lowercase Git commit")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise S44Error(f"{label}: expected a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise S44Error(f"{label}: unsafe repository-relative path {value!r}")
    return value


def _require_finite(value: object, label: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise S44Error(f"{label}: numeric metadata must be finite")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_finite(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_finite(item, f"{label}.{key}")


def _verify_bound_file(repo_root: Path, record: dict[str, Any], label: str) -> None:
    relative = _safe_relative(record.get("path"), f"{label}.path")
    expected = _require_sha256(record.get("sha256"), f"{label}.sha256")
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise S44Error(f"{label}.path: escapes repository") from exc
    if not candidate.is_file():
        raise S44Error(f"{label}.path: missing bound file {relative}")
    if sha256_file(candidate) != expected:
        raise S44Error(f"{label}.sha256: bound file hash mismatch for {relative}")


def validate_preseed_contract(
    constraints: dict[str, Any],
    *,
    repo_root: Path,
    verify_bindings: bool = True,
) -> None:
    """Validate the immutable pre-seed population and coverage contract."""

    if constraints.get("schema") != PRESEED_SCHEMA:
        raise S44Error(f"preseed schema: expected {PRESEED_SCHEMA}")
    if constraints.get("status") != "frozen_before_seed_enumeration":
        raise S44Error("preseed status: contract is not frozen")
    if (
        constraints.get("seed") is not None
        or constraints.get("assignments") is not None
    ):
        raise S44Error("preseed contract must not contain a seed or assignments")
    split = constraints.get("split_contract")
    if not isinstance(split, dict):
        raise S44Error("preseed split_contract: expected object")
    if split.get("kind") != "fit_holdout":
        raise S44Error("preseed split_contract.kind: expected fit_holdout")
    if split.get("grouping_key") != "s4_4_condition_group_id":
        raise S44Error("preseed split_contract.grouping_key: unexpected value")
    if split.get("nominal_ratios") != {"fit": 0.75, "holdout": 0.25}:
        raise S44Error("preseed nominal ratios: expected approved 75/25 target")

    mapping = constraints.get("group_mapping")
    if not isinstance(mapping, list) or len(mapping) != 9:
        raise S44Error("preseed group_mapping: expected exactly nine groups")
    group_ids: set[str] = set()
    trial_ids: set[str] = set()
    weight = 0
    eligible = 0
    ineligible = 0
    failed = 0
    for index, group in enumerate(mapping):
        if not isinstance(group, dict):
            raise S44Error(f"group_mapping[{index}]: expected object")
        missing = _GROUP_FIELDS - set(group)
        if missing:
            raise S44Error(
                f"group_mapping[{index}]: missing fields {sorted(missing)}"
            )
        _require_finite(group, f"group_mapping[{index}]")
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise S44Error(f"group_mapping[{index}].group_id: invalid")
        if group_id in group_ids:
            raise S44Error(f"group_mapping: duplicate group_id {group_id}")
        group_ids.add(group_id)
        category = group.get("category")
        if category not in {"repeatability", "controlled", "robustness"}:
            raise S44Error(f"group_mapping[{index}].category: invalid {category!r}")
        for field in (
            "source_device",
            "source_type",
            "source_identity",
            "mounting_condition",
            "acoustic_condition",
        ):
            if not isinstance(group.get(field), str) or not group[field]:
                raise S44Error(f"group_mapping[{index}].{field}: invalid metadata")
        cells = group.get("condition_cell_weight")
        usable = group.get("quality_eligible_condition_cells")
        excluded = group.get("quality_ineligible_condition_cells")
        retained = group.get("retained_failed_attempts")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (cells, usable, excluded, retained)
        ):
            raise S44Error(f"group_mapping[{index}]: invalid count metadata")
        if cells <= 0 or usable + excluded != cells:
            raise S44Error(f"group_mapping[{index}]: inconsistent cell counts")
        trials = group.get("trial_ids")
        if not isinstance(trials, list) or len(trials) != cells:
            raise S44Error(f"group_mapping[{index}].trial_ids: count mismatch")
        for trial_id in trials:
            if not isinstance(trial_id, str) or not trial_id or trial_id in trial_ids:
                raise S44Error(
                    "group_mapping"
                    f"[{index}].trial_ids: invalid or duplicate {trial_id!r}"
                )
            trial_ids.add(trial_id)
        weight += cells
        eligible += usable
        ineligible += excluded
        failed += retained
    if (weight, eligible, ineligible, failed) != (16, 15, 1, 3):
        raise S44Error(
            "preseed population counts: expected 16 cells, 15 eligible, "
            "1 ineligible, and 3 failed attempts"
        )
    required = constraints.get("preseed_holdout_constraints", {}).get(
        "required_complete_repeatability_group"
    )
    if required not in group_ids:
        raise S44Error("preseed required repeatability group: unknown group")
    if verify_bindings:
        sources = constraints.get("source_identities")
        if not isinstance(sources, list) or not sources:
            raise S44Error("preseed source_identities: expected non-empty list")
        for index, record in enumerate(sources):
            if not isinstance(record, dict):
                raise S44Error(f"source_identities[{index}]: expected object")
            _verify_bound_file(repo_root, record, f"source_identities[{index}]")


def validate_adapter_contract(
    algorithm: dict[str, Any],
    constraints: dict[str, Any],
    *,
    repo_root: Path,
    verify_bindings: bool = True,
) -> None:
    """Validate the frozen pre-seed adapter algorithm and bindings."""

    if algorithm.get("schema") != ADAPTER_SCHEMA:
        raise S44Error(f"adapter schema: expected {ADAPTER_SCHEMA}")
    if algorithm.get("status") != "frozen_before_seed_enumeration":
        raise S44Error("adapter status: algorithm was not frozen before enumeration")
    adapter = algorithm.get("adapter")
    if not isinstance(adapter, dict) or adapter.get("id") != ADAPTER_ID:
        raise S44Error(f"adapter id: expected {ADAPTER_ID}")
    if adapter.get("standard_s2_5_builder_modified") is not False:
        raise S44Error("adapter must leave standard S2.5 builder unchanged")
    if adapter.get("standard_s2_5_builder_reproduces_assignment") is not False:
        raise S44Error("adapter must not claim standard S2.5 reproduction")
    fixed = algorithm.get("fixed_inputs")
    if not isinstance(fixed, dict):
        raise S44Error("adapter fixed_inputs: expected object")
    split = constraints["split_contract"]
    for field in ("grouping_key", "kind"):
        if fixed.get(field) != split.get(field):
            raise S44Error(f"adapter fixed_inputs.{field}: binding mismatch")
    if fixed.get("ratios") != split.get("nominal_ratios"):
        raise S44Error("adapter fixed_inputs.ratios: binding mismatch")
    if (
        algorithm.get("seed") is not None
        or algorithm.get("selected_groups") is not None
    ):
        raise S44Error("adapter algorithm freeze must not contain selection results")
    expected_mapping = canonical_sha256(constraints["group_mapping"])
    bindings = algorithm.get("bindings")
    if not isinstance(bindings, dict) or bindings.get(
        "eligible_population_group_mapping_canonical_sha256"
    ) != expected_mapping:
        raise S44Error("adapter eligible population binding mismatch")
    if verify_bindings:
        for name in (
            "preseed_coverage_constraints",
            "s2_5_constraint_feasibility",
            "s2_5_split_implementation",
        ):
            record = bindings.get(name)
            if not isinstance(record, dict):
                raise S44Error(f"adapter bindings.{name}: expected object")
            _verify_bound_file(repo_root, record, f"adapter bindings.{name}")


def _group_score(dataset_id: str, seed: int, grouping_key: str, group_id: str) -> int:
    payload = f"{dataset_id}:{seed}:{grouping_key}:{group_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _candidate_coverage(
    mapping: dict[str, dict[str, Any]], holdout: tuple[str, ...]
) -> dict[str, int]:
    return {
        "quality_eligible_repeatability_cells": sum(
            mapping[group_id]["quality_eligible_condition_cells"]
            for group_id in holdout
            if mapping[group_id]["category"] == "repeatability"
        ),
        "quality_eligible_controlled_cells": sum(
            mapping[group_id]["quality_eligible_condition_cells"]
            for group_id in holdout
            if mapping[group_id]["category"] == "controlled"
        ),
        "quality_eligible_robustness_cells": sum(
            mapping[group_id]["quality_eligible_condition_cells"]
            for group_id in holdout
            if mapping[group_id]["category"] == "robustness"
        ),
        "quality_ineligible_cells": sum(
            mapping[group_id]["quality_ineligible_condition_cells"]
            for group_id in holdout
        ),
        "retained_failed_attempts": sum(
            mapping[group_id]["retained_failed_attempts"] for group_id in holdout
        ),
    }


def select_constraint_aware_split(
    constraints: dict[str, Any], algorithm: dict[str, Any], *, seed: int
) -> AdapterSelection:
    """Exhaustively select the globally optimal feasible whole-group split."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise S44Error("adapter seed: expected a non-negative integer")
    mapping = {item["group_id"]: item for item in constraints["group_mapping"]}
    group_ids = tuple(sorted(mapping))
    fixed = algorithm["fixed_inputs"]
    target = int(fixed["nominal_condition_cell_targets"]["holdout"])
    required = constraints["preseed_holdout_constraints"][
        "required_complete_repeatability_group"
    ]
    score_order = tuple(
        sorted(
            group_ids,
            key=lambda group_id: (
                _group_score(
                    fixed["dataset_id"], seed, fixed["grouping_key"], group_id
                ),
                group_id,
            ),
        )
    )
    ranks = {group_id: index for index, group_id in enumerate(score_order)}
    candidates: list[
        tuple[tuple[Any, ...], tuple[str, ...], tuple[str, ...], dict[str, int]]
    ] = []
    for mask in range(1 << len(group_ids)):
        holdout = tuple(
            group_ids[index]
            for index in range(len(group_ids))
            if mask & (1 << index)
        )
        holdout_set = set(holdout)
        fit = tuple(group_id for group_id in group_ids if group_id not in holdout_set)
        if not holdout or not fit or required not in holdout_set:
            continue
        coverage = _candidate_coverage(mapping, holdout)
        if coverage["quality_eligible_controlled_cells"] < 1:
            continue
        if coverage["quality_eligible_robustness_cells"] < 1:
            continue
        holdout_weight = sum(
            mapping[group_id]["condition_cell_weight"] for group_id in holdout
        )
        selected_ranks = tuple(sorted(ranks[group_id] for group_id in holdout))
        key: tuple[Any, ...] = (
            abs(holdout_weight - target),
            1 if holdout_weight < target else 0,
            len(holdout),
            sum(selected_ranks),
            selected_ranks,
            holdout,
        )
        candidates.append((key, holdout, fit, coverage))
    if not candidates:
        raise S44Error("adapter constraints: no feasible whole-group subset")
    key, holdout, fit, coverage = min(candidates, key=lambda item: item[0])
    weights = {
        group_id: int(mapping[group_id]["condition_cell_weight"])
        for group_id in group_ids
    }
    plan = SplitPlan(
        dataset_id=fixed["dataset_id"],
        grouping_key=fixed["grouping_key"],
        kind="fit_holdout",
        seed=seed,
        ratios=fixed["ratios"],
        assignments={"fit": fit, "holdout": holdout},
        group_weights=weights,
        manifest_configuration_sha256=algorithm["bindings"][
            "preseed_coverage_constraints"
        ]["sha256"],
    )
    restored = SplitPlan.from_dict(json.loads(plan.serialize()))
    if restored != plan or not verify_no_leakage(restored):
        raise S44Error("adapter output: unchanged SplitPlan verification failed")
    return AdapterSelection(
        seed=seed,
        plan=plan,
        score_order=score_order,
        ranking_key=key,
        subset_count=1 << len(group_ids),
        feasible_subset_count=len(candidates),
        coverage=coverage,
        global_optimum_verified=True,
    )


def find_first_valid_seed(
    constraints: dict[str, Any],
    algorithm: dict[str, Any],
    *,
    maximum_seed: int,
    expected_seed: int | None = None,
) -> AdapterSelection:
    """Return the first non-negative seed producing a verified adapter plan."""

    if isinstance(maximum_seed, bool) or not isinstance(maximum_seed, int):
        raise S44Error("maximum_seed: expected integer")
    if maximum_seed < 0:
        raise S44Error("maximum_seed: must be non-negative")
    for seed in range(maximum_seed + 1):
        selection = select_constraint_aware_split(constraints, algorithm, seed=seed)
        if expected_seed is not None and seed != expected_seed:
            raise S44Error(
                f"first valid seed mismatch: expected {expected_seed}, found {seed}"
            )
        return selection
    raise S44Error(f"no valid seed found through {maximum_seed}")


def _trial_to_group(constraints: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in constraints["group_mapping"]:
        for trial_id in group["trial_ids"]:
            if trial_id in mapping:
                raise S44Error(f"duplicate trial mapping: {trial_id}")
            mapping[trial_id] = group["group_id"]
    return mapping


def build_trial_census(
    inventory: dict[str, Any],
    constraints: dict[str, Any],
    selection: AdapterSelection,
) -> dict[str, Any]:
    """Build a complete outcome-preserving attempt and condition census."""

    if inventory.get("schema") != "ias.s4_3.trial_inventory.v1":
        raise S44Error("S4.3 inventory schema: unexpected value")
    trials = inventory.get("trials")
    if not isinstance(trials, list):
        raise S44Error("S4.3 inventory trials: expected list")
    group_by_trial = _trial_to_group(constraints)
    partition_by_group = {
        group_id: partition
        for partition, group_ids in selection.plan.assignments.items()
        for group_id in group_ids
    }
    attempts: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    seen_trials: set[str] = set()
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            raise S44Error(f"S4.3 inventory trials[{index}]: expected object")
        trial_id = trial.get("trial_id")
        if trial_id not in group_by_trial:
            raise S44Error(f"S4.3 inventory: unknown trial group for {trial_id!r}")
        seen_trials.add(trial_id)
        group_id = group_by_trial[trial_id]
        cell_eligible = trial.get("planned_outcome") == "accepted"
        cell_reason = (
            "terminal_quality_accepted"
            if cell_eligible
            else "terminal_quality_failure_invalid_capture"
        )
        cells.append(
            {
                "trial_id": trial_id,
                "category": trial.get("category"),
                "group_id": group_id,
                "partition": partition_by_group[group_id],
                "quality_eligible": cell_eligible,
                "eligibility_reason": cell_reason,
                "attempt_count": len(trial.get("attempts", [])),
            }
        )
        trial_attempts = trial.get("attempts")
        if not isinstance(trial_attempts, list) or not trial_attempts:
            raise S44Error(f"S4.3 inventory trial {trial_id}: attempts missing")
        for number, attempt in enumerate(trial_attempts):
            if not isinstance(attempt, dict):
                raise S44Error(f"S4.3 inventory {trial_id}.attempts[{number}]: invalid")
            usable = (
                attempt.get("outcome") == "accepted"
                and attempt.get("quality_status") == "passed"
            )
            if usable:
                eligibility_reason = "quality_passed"
            elif (
                attempt.get("manifest_sha256") is None
                and attempt.get("analysis_sha256") is None
            ):
                eligibility_reason = "pre_recording_failure_no_usable_capture"
            else:
                eligibility_reason = "quality_failure_invalid_capture"
            attempts.append(
                {
                    "trial_id": trial_id,
                    "attempt_id": attempt.get("attempt_id"),
                    "attempt_root": attempt.get("attempt_root"),
                    "category": trial.get("category"),
                    "group_id": group_id,
                    "partition": partition_by_group[group_id],
                    "outcome": attempt.get("outcome"),
                    "lifecycle_state": attempt.get("lifecycle_state"),
                    "quality_status": attempt.get("quality_status"),
                    "usable_coverage": usable,
                    "eligibility_reason": eligibility_reason,
                    "retained": True,
                }
            )
    missing = set(group_by_trial) - seen_trials
    if missing:
        raise S44Error(f"S4.3 inventory missing frozen trials: {sorted(missing)}")
    if len(attempts) != 18 or len(cells) != 16:
        raise S44Error("S4.3 census counts: expected 18 attempts and 16 cells")
    return {
        "schema": "ias.s4_4.trial_census.v1",
        "status": "complete",
        "counts": {
            "attempts": len(attempts),
            "condition_cells": len(cells),
            "quality_eligible_condition_cells": sum(
                bool(cell["quality_eligible"]) for cell in cells
            ),
            "quality_ineligible_condition_cells": sum(
                not bool(cell["quality_eligible"]) for cell in cells
            ),
            "retained_failed_attempts": sum(
                attempt["outcome"] == "failed" for attempt in attempts
            ),
        },
        "condition_cells": sorted(cells, key=lambda item: item["trial_id"]),
        "attempts": sorted(attempts, key=lambda item: item["attempt_id"]),
        "outcome_metrics_used_for_assignment": False,
        "all_failures_retained": True,
    }


def _axis_value(group: dict[str, Any], axis: str, constraints: dict[str, Any]) -> Any:
    if axis == "scientific_session_id":
        return constraints["population_contract"]["scientific_session_id"]
    if axis == "room_id":
        return S43_ROOM_ID
    value = group[axis]
    if isinstance(value, list):
        return json.dumps(value, separators=(",", ":"))
    return value


def _sorted_values(values: set[Any]) -> list[Any]:
    return sorted(values, key=lambda value: json.dumps(value, sort_keys=True))


def build_coverage_report(
    constraints: dict[str, Any], selection: AdapterSelection
) -> dict[str, Any]:
    """Build the proportional matrix and explicit per-axis overlap report."""

    axes = (
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
    )
    mapping = {item["group_id"]: item for item in constraints["group_mapping"]}
    axis_reports: dict[str, Any] = {}
    for axis in axes:
        counts: dict[str, dict[str, Any]] = {}
        values_by_partition: dict[str, set[Any]] = {"fit": set(), "holdout": set()}
        for partition, group_ids in selection.plan.assignments.items():
            for group_id in group_ids:
                group = mapping[group_id]
                value = _axis_value(group, axis, constraints)
                key = json.dumps(value, sort_keys=True, separators=(",", ":"))
                values_by_partition[partition].add(value)
                record = counts.setdefault(
                    key,
                    {
                        "value": value,
                        "fit_condition_cells": 0,
                        "holdout_condition_cells": 0,
                    },
                )
                record[f"{partition}_condition_cells"] += group[
                    "condition_cell_weight"
                ]
        rows = []
        for key in sorted(counts):
            record = counts[key]
            total = record["fit_condition_cells"] + record["holdout_condition_cells"]
            rows.append(
                {
                    **record,
                    "total_condition_cells": total,
                    "fit_proportion": record["fit_condition_cells"] / total,
                    "holdout_proportion": record["holdout_condition_cells"] / total,
                }
            )
        overlap = values_by_partition["fit"] & values_by_partition["holdout"]
        axis_reports[axis] = {
            "values": rows,
            "fit_values": _sorted_values(values_by_partition["fit"]),
            "holdout_values": _sorted_values(values_by_partition["holdout"]),
            "overlap_values": _sorted_values(overlap),
            "overlap_permitted_by": (
                "approved full composite-condition leakage identity; equality on "
                "one axis alone does not merge groups"
            ),
        }
    weights = selection.plan.group_weights
    achieved = {
        partition: sum(weights[group_id] for group_id in group_ids)
        for partition, group_ids in selection.plan.assignments.items()
    }
    group_counts = {
        partition: len(group_ids)
        for partition, group_ids in selection.plan.assignments.items()
    }
    return {
        "schema": "ias.s4_4.coverage_report.v1",
        "status": "passed",
        "nominal_ratios": dict(selection.plan.ratios),
        "nominal_condition_cell_counts": {"fit": 12, "holdout": 4},
        "achieved_condition_cell_counts": achieved,
        "achieved_condition_cell_proportions": {
            partition: count / 16 for partition, count in achieved.items()
        },
        "achieved_group_counts": group_counts,
        "achieved_group_proportions": {
            partition: count / 9 for partition, count in group_counts.items()
        },
        "axes": axis_reports,
        "claim_limits": {
            "holdout_source_devices": ["MacBookPro18,1 built-in speakers"],
            "holdout_source_types": ["reference_wav"],
            "heldout_cross_source_generalization": False,
            "heldout_cross_device_generalization": False,
            "fit_only_source_types": [
                "silence",
                "standardized_voice_phrase",
                "reference_wav_plus_standardized_voice",
                "visible_audible_ordinary_object_impact",
            ],
            "fit_only_conditions": [
                "occlusion",
                "silence",
                "voice",
                "overlap",
                "impact",
            ],
            "historical_s4_3_outcomes_already_analyzed": True,
        },
        "quality_ineligible_cells_counted_as_usable_coverage": False,
        "outcome_metrics_used_for_selection": False,
    }


def build_assignment_companion(
    constraints: dict[str, Any],
    algorithm: dict[str, Any],
    selection: AdapterSelection,
) -> dict[str, Any]:
    """Bind the authorized population, algorithm, seed, assignment, and plan."""

    weights = selection.plan.group_weights
    achieved = {
        partition: sum(weights[group_id] for group_id in group_ids)
        for partition, group_ids in selection.plan.assignments.items()
    }
    return {
        "schema": "ias.s4_4.assignment_companion.v1",
        "status": "frozen",
        "adapter": {
            "id": algorithm["adapter"]["id"],
            "assignment_producer": "S4.4 constraint-aware adapter",
            "standard_s2_5_builder_modified": False,
            "standard_s2_5_builder_reproduction_claimed": False,
        },
        "bindings": {
            "preseed_coverage_constraints_sha256": algorithm["bindings"][
                "preseed_coverage_constraints"
            ]["sha256"],
            "adapter_algorithm_canonical_sha256": canonical_sha256(algorithm),
            "eligible_population_group_mapping_canonical_sha256": canonical_sha256(
                constraints["group_mapping"]
            ),
        },
        "optimization": {
            "objective": algorithm["candidate_ranking"],
            "subsets_enumerated": selection.subset_count,
            "feasible_subsets_ranked": selection.feasible_subset_count,
            "selected_ranking_key": _json_ready(selection.ranking_key),
            "global_optimum_verified": selection.global_optimum_verified,
        },
        "seed": selection.seed,
        "score_order": list(selection.score_order),
        "assignments": {
            partition: list(group_ids)
            for partition, group_ids in selection.plan.assignments.items()
        },
        "nominal_ratios": dict(selection.plan.ratios),
        "nominal_condition_cell_counts": {"fit": 12, "holdout": 4},
        "achieved_condition_cell_counts": achieved,
        "achieved_condition_cell_proportions": {
            partition: count / 16 for partition, count in achieved.items()
        },
        "split_plan_sha256": selection.plan.plan_sha256,
        "outcome_metrics_used": False,
        "s4_5_started": False,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


def build_holdout_seal(
    constraints: dict[str, Any],
    selection: AdapterSelection,
    census: dict[str, Any],
    s43_index: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic metadata-and-hash-only holdout seal."""

    holdout_attempts = {
        item["attempt_id"]: item
        for item in census["attempts"]
        if item["partition"] == "holdout"
    }
    fit_attempt_ids = sorted(
        item["attempt_id"]
        for item in census["attempts"]
        if item["partition"] == "fit"
    )
    artifacts: list[dict[str, Any]] = []
    indexed = s43_index.get("artifacts")
    if not isinstance(indexed, list):
        raise S44Error("S4.3 evidence index artifacts: expected list")
    for record in indexed:
        if not isinstance(record, dict):
            continue
        path = record.get("path")
        if not isinstance(path, str):
            continue
        for attempt_id, attempt in holdout_attempts.items():
            root = attempt.get("attempt_root")
            if isinstance(root, str) and (path == root or path.startswith(root + "/")):
                artifacts.append(
                    {
                        "attempt_id": attempt_id,
                        "path": path,
                        "role": record.get("role"),
                        "retention": record.get("retention"),
                        "byte_size": record.get("byte_size"),
                        "sha256": record.get("sha256"),
                    }
                )
                break
    if not artifacts:
        raise S44Error("holdout seal: no S4.3 artifact metadata found")
    seal: dict[str, Any] = {
        "schema": SEAL_SCHEMA,
        "status": "sealed",
        "split_plan_sha256": selection.plan.plan_sha256,
        "holdout_group_ids": list(selection.plan.assignments["holdout"]),
        "holdout_attempt_ids": sorted(holdout_attempts),
        "fit_attempt_ids": fit_attempt_ids,
        "artifacts": sorted(
            artifacts, key=lambda item: (item["path"], item["attempt_id"])
        ),
        "access_policy": {
            "state": "sealed",
            "enforcement_boundary": "repository_tooling",
            "filesystem_owner_direct_reads_detected_or_prevented": False,
            "historical_s4_3_outcomes_already_analyzed": True,
            "holdout_opened_during_s4_4": False,
            "s4_8_grant_created_during_s4_4": False,
            "integrity_validation_is_holdout_open": False,
            "integrity_validation_returns_content_derived_values": False,
            "future_open_purpose": "S4.8_evaluation",
            "future_prerequisite": "hash-bound passing S4.7 preregistration",
            "future_grant_location": "dataset/S4.4/access/holdout_access_grant.json",
            "future_ledger_location": "dataset/S4.4/access/access_ledger.jsonl",
            "future_grant_single_use": True,
        },
        "contents": "metadata_paths_sizes_roles_and_sha256_only",
        "raw_media_copied": False,
        "analysis_content_included": False,
        "derived_holdout_outcomes_included": False,
    }
    seal["seal_payload_sha256"] = canonical_sha256(seal)
    return seal


def validate_holdout_seal(seal: dict[str, Any], plan: SplitPlan) -> None:
    """Validate seal structure, self-hash, assignment, and no-content policy."""

    if seal.get("schema") != SEAL_SCHEMA or seal.get("status") != "sealed":
        raise S44Error("holdout seal schema or status invalid")
    supplied = _require_sha256(
        seal.get("seal_payload_sha256"), "holdout seal payload hash"
    )
    payload = {
        key: value for key, value in seal.items() if key != "seal_payload_sha256"
    }
    expected = canonical_sha256(payload)
    if supplied != expected:
        raise S44Error(
            f"holdout seal payload hash mismatch: expected {expected}, found {supplied}"
        )
    if seal.get("split_plan_sha256") != plan.plan_sha256:
        raise S44Error("holdout seal SplitPlan hash mismatch")
    if tuple(seal.get("holdout_group_ids", ())) != plan.assignments["holdout"]:
        raise S44Error("holdout seal group assignment mismatch")
    if seal.get("raw_media_copied") is not False:
        raise S44Error("holdout seal must not copy raw media")
    if seal.get("analysis_content_included") is not False:
        raise S44Error("holdout seal must not include analysis content")
    if seal.get("derived_holdout_outcomes_included") is not False:
        raise S44Error("holdout seal must not include derived outcomes")
    artifacts = seal.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise S44Error("holdout seal artifacts: expected metadata records")
    for index, record in enumerate(artifacts):
        if not isinstance(record, dict):
            raise S44Error(f"holdout seal artifacts[{index}]: expected object")
        _safe_relative(record.get("path"), f"holdout seal artifacts[{index}].path")
        _require_sha256(
            record.get("sha256"), f"holdout seal artifacts[{index}].sha256"
        )
        size = record.get("byte_size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise S44Error(f"holdout seal artifacts[{index}].byte_size: invalid")


def hash_only_holdout_integrity(
    seal: dict[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    """Verify only size/hash integrity and return no content-derived values."""

    issues: list[dict[str, str]] = []
    supplied = seal.get("seal_payload_sha256")
    payload = {
        key: value for key, value in seal.items() if key != "seal_payload_sha256"
    }
    if supplied != canonical_sha256(payload):
        issues.append(
            {"code": "seal_hash_mismatch", "path": "seal", "message": "invalid"}
        )
    checked = 0
    for record in seal.get("artifacts", []):
        relative = record.get("path")
        try:
            safe = _safe_relative(relative, "holdout artifact path")
        except S44Error as exc:
            issues.append(
                {"code": "unsafe_path", "path": str(relative), "message": str(exc)}
            )
            continue
        path = (repo_root / safe).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError:
            issues.append(
                {"code": "unsafe_path", "path": safe, "message": "escapes root"}
            )
            continue
        if not path.is_file():
            issues.append(
                {"code": "missing_file", "path": safe, "message": "file absent"}
            )
            continue
        if path.stat().st_size != record.get("byte_size"):
            issues.append(
                {"code": "size_mismatch", "path": safe, "message": "size differs"}
            )
        if sha256_file(path) != record.get("sha256"):
            issues.append(
                {"code": "hash_mismatch", "path": safe, "message": "SHA-256 differs"}
            )
        checked += 1
    return {
        "schema": "ias.s4_4.hash_only_integrity.v1",
        "status": "passed" if not issues else "failed",
        "checked_artifact_count": checked,
        "issues": issues,
        "holdout_opened": False,
        "content_derived_values_returned": False,
    }


def require_evidence_access(
    seal: dict[str, Any], *, attempt_id: str, purpose: str
) -> dict[str, Any]:
    """Authorize fit-only or hash-only operations and deny holdout tuning."""

    if purpose not in _KNOWN_PURPOSES:
        raise S44Error(f"unknown purpose: {purpose!r}")
    fit_ids = set(seal.get("fit_attempt_ids", ()))
    holdout_ids = set(seal.get("holdout_attempt_ids", ()))
    if attempt_id not in fit_ids | holdout_ids:
        raise S44Error(f"unknown attempt: {attempt_id!r}")
    if attempt_id in holdout_ids:
        if purpose in {"S4.5_fit", "S4.5_validation"}:
            raise S44Error(
                f"holdout access denied for {purpose}; sealed evidence cannot tune"
            )
        if purpose == "S4.4_integrity_validation":
            return {"allowed": True, "mode": "hash_only", "holdout_opened": False}
        raise S44Error("holdout access requires a valid future S4.8 grant")
    return {"allowed": True, "mode": "fit_only", "holdout_opened": False}


def validate_ledger(
    ledger_path: Path, *, expected_seal_sha256: str
) -> dict[str, Any]:
    """Validate an append-only canonical JSONL hash chain."""

    _require_sha256(expected_seal_sha256, "ledger expected seal SHA-256")
    if not ledger_path.exists():
        return {
            "schema": "ias.s4_4.access_ledger_validation.v1",
            "status": "passed",
            "event_count": 0,
            "head_sha256": ZERO_SHA256,
            "issues": [],
        }
    issues: list[dict[str, str]] = []
    previous = ZERO_SHA256
    count = 0
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise S44Error(f"cannot read access ledger {ledger_path}: {exc}") from exc
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(
                {"code": "malformed_event", "path": str(index), "message": str(exc)}
            )
            continue
        if not isinstance(record, dict):
            issues.append(
                {"code": "invalid_event", "path": str(index), "message": "not object"}
            )
            continue
        supplied = record.get("event_sha256")
        payload = {key: value for key, value in record.items() if key != "event_sha256"}
        expected = canonical_sha256(payload)
        if record.get("schema") != LEDGER_SCHEMA:
            issues.append(
                {"code": "wrong_schema", "path": str(index), "message": "invalid"}
            )
        if record.get("sequence") != index:
            issues.append(
                {"code": "sequence_mismatch", "path": str(index), "message": "invalid"}
            )
        if record.get("previous_event_sha256") != previous:
            issues.append(
                {"code": "chain_mismatch", "path": str(index), "message": "invalid"}
            )
        if record.get("seal_sha256") != expected_seal_sha256:
            issues.append(
                {"code": "seal_mismatch", "path": str(index), "message": "invalid"}
            )
        if supplied != expected:
            issues.append(
                {
                    "code": "event_hash_mismatch",
                    "path": str(index),
                    "message": "invalid",
                }
            )
        previous = str(supplied)
        count += 1
    return {
        "schema": "ias.s4_4.access_ledger_validation.v1",
        "status": "passed" if not issues else "failed",
        "event_count": count,
        "head_sha256": previous,
        "issues": issues,
    }


def append_ledger_event(ledger_path: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one canonical event after validating the existing hash chain."""

    seal_sha = _require_sha256(event.get("seal_sha256"), "ledger event seal_sha256")
    validation = validate_ledger(ledger_path, expected_seal_sha256=seal_sha)
    if validation["status"] != "passed":
        raise S44Error("access ledger chain is invalid; refusing append")
    payload = {
        "schema": LEDGER_SCHEMA,
        "sequence": validation["event_count"],
        "previous_event_sha256": validation["head_sha256"],
        **event,
    }
    record = {**payload, "event_sha256": canonical_sha256(payload)}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def consume_s4_8_grant(
    grant_path: Path,
    *,
    seal_path: Path,
    split_plan_sha256: str,
    prerequisite_path: Path,
    ledger_path: Path,
    event_time_utc: str,
) -> dict[str, Any]:
    """Validate and consume one future purpose-bound S4.8 grant."""

    grant = load_json(grant_path)
    required = {
        "schema",
        "grant_id",
        "purpose",
        "seal_sha256",
        "split_plan_sha256",
        "prerequisite",
        "single_use",
        "authorization",
        "grant_sha256",
    }
    if set(grant) != required:
        raise S44Error(
            f"grant fields: expected {sorted(required)}, found {sorted(grant)}"
        )
    if grant["schema"] != GRANT_SCHEMA:
        raise S44Error("grant schema: invalid")
    if grant["purpose"] != "S4.8_evaluation":
        raise S44Error("grant purpose: expected S4.8_evaluation")
    if grant["single_use"] is not True:
        raise S44Error("grant single_use: must be true")
    if grant["authorization"] != "explicit_user_authorization_required":
        raise S44Error("grant authorization: invalid")
    payload = {key: value for key, value in grant.items() if key != "grant_sha256"}
    if grant["grant_sha256"] != canonical_sha256(payload):
        raise S44Error("grant hash mismatch")
    seal_sha = sha256_file(seal_path)
    if grant["seal_sha256"] != seal_sha:
        raise S44Error("grant seal binding mismatch")
    if grant["split_plan_sha256"] != split_plan_sha256:
        raise S44Error("grant SplitPlan binding mismatch")
    prerequisite = grant.get("prerequisite")
    if not isinstance(prerequisite, dict):
        raise S44Error("grant prerequisite: expected object")
    expected_prerequisite_fields = {"path", "sha256", "schema", "status"}
    if set(prerequisite) != expected_prerequisite_fields:
        raise S44Error(
            "grant prerequisite fields: expected "
            f"{sorted(expected_prerequisite_fields)}, found {sorted(prerequisite)}"
        )
    if prerequisite.get("path") != prerequisite_path.as_posix():
        raise S44Error("grant prerequisite path binding mismatch")
    if prerequisite.get("schema") != "ias.s4_7.holdout_acceptance.v1":
        raise S44Error("grant prerequisite schema binding mismatch")
    if prerequisite.get("status") != "passed":
        raise S44Error("grant prerequisite status binding mismatch")
    actual_prerequisite_sha = sha256_file(prerequisite_path)
    if prerequisite.get("sha256") != actual_prerequisite_sha:
        raise S44Error("grant prerequisite hash mismatch")
    prerequisite_payload = load_json(prerequisite_path)
    if prerequisite_payload.get("schema") != prerequisite.get("schema"):
        raise S44Error("grant prerequisite schema mismatch")
    if prerequisite_payload.get("status") != prerequisite.get("status"):
        raise S44Error("grant prerequisite status mismatch")
    ledger = validate_ledger(ledger_path, expected_seal_sha256=seal_sha)
    if ledger["status"] != "passed":
        raise S44Error("access ledger chain invalid")
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("grant_id") == grant["grant_id"]:
                raise S44Error(f"grant already used: {grant['grant_id']}")
    record = append_ledger_event(
        ledger_path,
        {
            "event": "holdout_open_authorized",
            "event_time_utc": event_time_utc,
            "seal_sha256": seal_sha,
            "split_plan_sha256": split_plan_sha256,
            "grant_id": grant["grant_id"],
            "grant_sha256": grant["grant_sha256"],
            "prerequisite_sha256": actual_prerequisite_sha,
            "purpose": "S4.8_evaluation",
            "holdout_opened": True,
        },
    )
    return {"allowed": True, "mode": "S4.8_evaluation", "ledger_event": record}
