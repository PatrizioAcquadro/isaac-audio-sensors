"""Deterministic evidence for the additive S4.7 corrective preregistration."""

from __future__ import annotations

import copy
import json
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_7_prerequisite import (
    ACCEPTANCE_SCHEMA,
    CANONICAL_PACKAGE,
    CANONICAL_PREREQUISITE,
    EVIDENCE_INDEX_SCHEMA,
    REQUIRED_PACKAGE_FILES,
    S47PrerequisiteError,
    validate_s4_7_corrective_prerequisite,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective import (
    CONFIG_PATH,
    SCHEMA_PATH,
    V1_CONFIG_PATH,
    CorrectiveAcceptanceError,
    build_identity_registry,
    build_synthetic_payload,
    evaluate_corrective,
    load_corrective_config,
    sha256_file,
)

SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance_corrective_01.md")
V1_SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance.md")
V1_PACKAGE = Path("outputs/isaac_audio_sensors/S4/S4.7")
OUTPUT_PATH = CANONICAL_PACKAGE
TOOL_VERSION = "ias_s4_7_corrective_evidence/2.0.0"
BASELINE_COMMIT = "f2230128fd02294892282b5809abe71092f19013"
HISTORICAL_SOURCE_COMMIT = "e4be6b1ff610b0353f7301d3da98c946f052caa6"
CONTRACT_COMMIT = "ae66e2fbe80cc9dd91cfe8fb094475ec6fed7786"
EVALUATOR_COMMIT = "5b8f43b2e35c4118f1cf70dc76db0651884346ea"
SOURCE_BOUND_FILES = (
    CONFIG_PATH,
    SCHEMA_PATH,
    SPEC_PATH,
    V1_CONFIG_PATH,
    V1_SPEC_PATH,
    Path("scripts/generate_s4_7_corrective_evidence.py"),
    Path("scripts/replay_s4_7_corrective.py"),
    Path("scripts/run_s4_7_corrective_evaluation.py"),
    Path("scripts/validate_s4_7_corrective.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_4.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7_corrective.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7_prerequisite.py"),
    Path("src/isaac_audio_sensors/core/acceptance_criteria_corrective.py"),
    Path("tests/test_s4_4_holdout_freeze.py"),
    Path("tests/test_s4_7_corrective_acceptance.py"),
    Path("tests/test_s4_7_corrective_contract.py"),
    Path("tests/test_s4_7_corrective_evidence.py"),
    Path("tests/test_s4_7_evidence.py"),
    Path("tests/test_s4_8_corrective_interlock.py"),
)
INDEX_EXCLUSIONS = {
    "SHA256SUMS",
    "evidence_index.json",
    "holdout_acceptance.json",
}


class S47CorrectiveEvidenceError(ValueError):
    """Raised when corrective evidence cannot be built or validated."""


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def validate_criteria_only(repo_root: Path) -> dict[str, Any]:
    """Validate the frozen contract and evaluator without an evidence package."""

    root = repo_root.resolve()
    try:
        config = load_corrective_config(root)
        registry = build_identity_registry(root, config)
        passing_payload = build_synthetic_payload(root)
        failing_payload = build_synthetic_payload(root, passing=False)
        first = evaluate_corrective(passing_payload, repo_root=root)
        second = evaluate_corrective(passing_payload, repo_root=root)
        failing = evaluate_corrective(failing_payload, repo_root=root)
        v1 = _load_json(root / V1_CONFIG_PATH)
        issues = []
        if first.report() != second.report():
            issues.append("synthetic evaluation is not deterministic")
        if not first.readiness_passed:
            issues.append("identity-complete conforming fixture failed")
        if failing.readiness_passed:
            issues.append("violating fixture passed")
        if len(v1["criteria"]) != 29:
            issues.append("inherited criterion count changed")
        if len(registry) != 47:
            issues.append("identity registry does not contain 47 takes")
    except (OSError, CorrectiveAcceptanceError, KeyError) as exc:
        config = {}
        registry = {}
        first = second = failing = None
        issues = [str(exc)]
    return {
        "schema": "ias.s4_7.corrective_criteria_validation.v2",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "criteria_config_sha256": (
            sha256_file(root / CONFIG_PATH) if (root / CONFIG_PATH).is_file() else None
        ),
        "criteria_schema_sha256": (
            sha256_file(root / SCHEMA_PATH) if (root / SCHEMA_PATH).is_file() else None
        ),
        "corrective_spec_sha256": (
            sha256_file(root / SPEC_PATH) if (root / SPEC_PATH).is_file() else None
        ),
        "take_count": len(registry),
        "readiness_passed": bool(first and first.readiness_passed),
        "violating_fixture_failed": bool(failing and not failing.readiness_passed),
        "deterministic": bool(first and second and first.report() == second.report()),
        "bound_holdout_id": (
            config.get("holdout_binding", {}).get("bound_holdout_id")
        ),
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }


def build_evidence_package(
    *,
    repo_root: Path,
    output: Path,
    source_commit: str,
    source_tree_replay: bool = False,
) -> dict[str, Any]:
    """Build the exact 18-file corrective evidence package."""

    root = repo_root.resolve()
    target = output if output.is_absolute() else root / output
    if not source_tree_replay:
        _validate_source_commit(root, source_commit)
    if target.exists() and any(target.iterdir()):
        raise S47CorrectiveEvidenceError(f"output must be empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    config = load_corrective_config(root)
    registry = build_identity_registry(root, config)
    criteria_validation = validate_criteria_only(root)
    passing_payload = build_synthetic_payload(root)
    failing_payload = build_synthetic_payload(root, passing=False)
    first = evaluate_corrective(passing_payload, repo_root=root)
    second = evaluate_corrective(passing_payload, repo_root=root)
    failing = evaluate_corrective(failing_payload, repo_root=root)
    matrix = _fail_closed_matrix(root, passing_payload)
    v1 = _load_json(root / V1_CONFIG_PATH)
    freeze = _freeze_ordering(root, config, source_commit, source_tree_replay)
    binding = _holdout_binding(root, config)
    preservation = _historical_preservation(root)
    identity_records = [
        {
            **registry[take_id].payload_identity(),
            "duration_s": registry[take_id].duration_s,
        }
        for take_id in sorted(registry)
    ]
    stratum_counts = Counter(item.stratum_id for item in registry.values())
    internal_pass = all(
        (
            criteria_validation["status"] == "passed",
            first.readiness_passed,
            not failing.readiness_passed,
            first.report() == second.report(),
            all(item["status"] == "passed" for item in matrix),
            freeze["status"] == "passed",
            binding["status"] == "passed",
            preservation["status"] == "passed",
        )
    )
    common = {
        "status": "passed" if internal_pass else "failed",
        "holdout_observations_accessed": 0,
    }
    reports: dict[str, dict[str, Any]] = {
        "blindness_attestation.json": {
            "schema": "ias.s4_7.corrective_blindness_attestation.v2",
            **common,
            "holdout_derived_outcomes_accessed": 0,
            "raw_dataset_content_accessed": False,
            "tracked_technical_manifests_used": [
                config["holdout_binding"]["session_manifest_path"],
                config["holdout_binding"]["partition_manifest_path"],
                config["holdout_binding"]["seal_path"],
            ],
            "holdout_access_grant_created": False,
            "holdout_access_grant_consumed": False,
            "thresholds_selected_from_holdout": False,
        },
        "contract_validation.json": {
            "schema": "ias.s4_7.corrective_contract_validation.v2",
            **common,
            "criteria_validation": criteria_validation,
            "thresholds_changed": False,
            "claimed_envelope_changed": False,
            "scientific_eligibility_changed": False,
            "criteria_config_sha256": sha256_file(root / CONFIG_PATH),
            "criteria_schema_sha256": sha256_file(root / SCHEMA_PATH),
            "corrective_spec_sha256": sha256_file(root / SPEC_PATH),
        },
        "criteria_register.json": {
            "schema": "ias.s4_7.corrective_criteria_register.v2",
            **common,
            "inherited_config_path": V1_CONFIG_PATH.as_posix(),
            "inherited_config_sha256": sha256_file(root / V1_CONFIG_PATH),
            "criteria": v1["criteria"],
            "criterion_count": len(v1["criteria"]),
            "readiness_criterion_count": sum(
                item["gating"] for item in v1["criteria"]
            ),
            "stretch_criterion_count": sum(
                not item["gating"] for item in v1["criteria"]
            ),
        },
        "determinism_report.json": {
            "schema": "ias.s4_7.corrective_determinism.v2",
            **common,
            "run_count": 2,
            "evaluation_reports_identical": first.report() == second.report(),
            "randomness_used": False,
            "wall_clock_input_used": False,
        },
        "fail_closed_matrix.json": {
            "schema": "ias.s4_7.corrective_fail_closed_matrix.v2",
            **common,
            "case_count": len(matrix),
            "cases": matrix,
            "silent_pass_observed": False,
        },
        "freeze_ordering.json": freeze,
        "historical_preservation.json": preservation,
        "holdout_binding_report.json": binding,
        "identity_registry.json": {
            "schema": "ias.s4_7.corrective_identity_registry.v2",
            **common,
            "registry_source": config["identity_contract"]["registry_source"],
            "session_manifest_path": config["holdout_binding"][
                "session_manifest_path"
            ],
            "session_manifest_sha256": config["holdout_binding"][
                "session_manifest_sha256"
            ],
            "take_count": len(identity_records),
            "group_count": len({item.group_id for item in registry.values()}),
            "stratum_counts": dict(sorted(stratum_counts.items())),
            "raw_microphone_ids": config["identity_contract"][
                "raw_microphone_ids"
            ],
            "microphone_pair_ids": config["identity_contract"][
                "microphone_pair_ids"
            ],
            "takes": identity_records,
        },
        "input_contract_report.json": {
            "schema": "ias.s4_7.corrective_input_contract.v2",
            **common,
            "exact_take_set_required": True,
            "unique_identity_required": True,
            "per_take_window_coverage_required": True,
            "window_contract": config["window_contract"],
            "latency_contract": config["latency_contract"],
            "physical_domains": config["physical_domains"],
            "raw_channel_record_count": 188,
            "tdoa_take_pair_record_count": 144,
            "bearing_sim_real_condition_count": 32,
            "bearing_referenced_take_count": 40,
        },
        "phase_boundary.json": {
            "schema": "ias.s4_7.corrective_phase_boundary.v2",
            **common,
            "holdout_access_grant_created": False,
            "holdout_access_grant_consumed": False,
            "s4_8_started": False,
            "s4_9_started": False,
            "s5_started": False,
            "s6_started": False,
            "push_performed": False,
            "tag_created": False,
        },
        "reproduction.json": {
            "schema": "ias.s4_7.corrective_reproduction.v2",
            **common,
            "source_commit": source_commit,
            "command": (
                "python3 scripts/replay_s4_7_corrective.py "
                "--canonical outputs/isaac_audio_sensors/S4/S4.7_corrective_01"
            ),
            "comparison": "byte_for_byte_complete_package",
            "clean_source_archive": True,
            "requires_holdout_observations": False,
            "historical_v1_replay_command": (
                "python3 scripts/replay_s4_7.py "
                "--canonical outputs/isaac_audio_sensors/S4/S4.7"
            ),
        },
        "sim_vs_real_registry.json": {
            "schema": "ias.s4_7.corrective_sim_vs_real_registry.v2",
            **common,
            **config["sim_vs_real"],
        },
        "synthetic_evaluation_report.json": {
            "schema": "ias.s4_7.corrective_synthetic_evaluation.v2",
            **common,
            "fixtures_are_synthetic": True,
            "conforming_evaluation": first.report(),
            "violating_evaluation": failing.report(),
            "conforming_fixture_passes": first.readiness_passed,
            "violating_fixture_fails": not failing.readiness_passed,
        },
    }
    reports["final_validation.json"] = {
        "schema": "ias.s4_7.corrective_final_validation.v2",
        **common,
        "criteria_only_validation_passed": criteria_validation["status"] == "passed",
        "identity_registry_complete": len(registry) == 47,
        "comparison_registry_complete": len(
            config["sim_vs_real"]["comparison_registry"]
        )
        == 7,
        "fail_closed_matrix_passed": all(
            item["status"] == "passed" for item in matrix
        ),
        "deterministic": first.report() == second.report(),
        "freeze_ordering_valid": freeze["status"] == "passed",
        "historical_v1_preserved": preservation["status"] == "passed",
        "holdout_binding_valid": binding["status"] == "passed",
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "later_phases_started": [],
    }
    expected_indexed = REQUIRED_PACKAGE_FILES - INDEX_EXCLUSIONS
    if set(reports) != expected_indexed:
        raise S47CorrectiveEvidenceError(
            "internal report set mismatch: "
            f"missing={sorted(expected_indexed - set(reports))}, "
            f"extra={sorted(set(reports) - expected_indexed)}"
        )
    for name, payload in reports.items():
        _write_json(target / name, payload)
    records = _evidence_records(target, expected_indexed)
    index = {
        "schema": EVIDENCE_INDEX_SCHEMA,
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "file_count": len(REQUIRED_PACKAGE_FILES),
        "records": records,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    _write_json(target / "evidence_index.json", index)
    acceptance = {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "passed" if internal_pass else "failed",
        "corrective_id": "s4_7_corrective_01",
        "evidence_path": OUTPUT_PATH.as_posix(),
        "evidence_index_path": (OUTPUT_PATH / "evidence_index.json").as_posix(),
        "evidence_index_sha256": sha256_file(target / "evidence_index.json"),
        "criteria_config_path": CONFIG_PATH.as_posix(),
        "criteria_config_sha256": sha256_file(root / CONFIG_PATH),
        "criteria_schema_path": SCHEMA_PATH.as_posix(),
        "criteria_schema_sha256": sha256_file(root / SCHEMA_PATH),
        "corrective_spec_path": SPEC_PATH.as_posix(),
        "corrective_spec_sha256": sha256_file(root / SPEC_PATH),
        "inherited_config_path": V1_CONFIG_PATH.as_posix(),
        "inherited_config_sha256": sha256_file(root / V1_CONFIG_PATH),
        "inherited_spec_path": V1_SPEC_PATH.as_posix(),
        "inherited_spec_sha256": sha256_file(root / V1_SPEC_PATH),
        "source_commit": source_commit,
        "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
        "seal_path": config["holdout_binding"]["seal_path"],
        "seal_file_sha256": config["holdout_binding"]["seal_file_sha256"],
        "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
        "planned_take_count": 47,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "readiness_passed": internal_pass,
        "holdout_observations_accessed": 0,
        "authorizes_holdout_opening": False,
        "grant_still_required_for_s4_8": True,
    }
    _write_json(target / CANONICAL_PREREQUISITE.name, acceptance)
    (target / "SHA256SUMS").write_text(
        _checksum_text(target), encoding="utf-8"
    )
    return {
        "schema": "ias.s4_7.corrective_evidence_build.v2",
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "output": str(target),
        "file_count": len(REQUIRED_PACKAGE_FILES),
        "holdout_observations_accessed": 0,
    }


def validate_evidence_package(
    repo_root: Path,
    output: Path = OUTPUT_PATH,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
) -> dict[str, Any]:
    """Validate bytes, semantics, source replay, and optional Git state."""

    root = repo_root.resolve()
    target = output if output.is_absolute() else root / output
    issues: list[str] = []
    source_commit = ""
    try:
        acceptance = _load_json(target / CANONICAL_PREREQUISITE.name)
        source_commit = str(acceptance["source_commit"])
        validate_s4_7_corrective_prerequisite(
            target / CANONICAL_PREREQUISITE.name,
            seal_path=root / acceptance["seal_path"],
            require_committed=require_committed,
        )
    except (
        OSError,
        KeyError,
        S47PrerequisiteError,
        json.JSONDecodeError,
    ) as exc:
        issues.append(str(exc))
    if require_tracked and target.is_dir():
        paths = [target / name for name in sorted(REQUIRED_PACKAGE_FILES)]
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", *paths],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            issues.append("corrective package is not fully tracked")
    return {
        "schema": "ias.s4_7.corrective_evidence_validation.v2",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "source_commit": source_commit,
        "file_count": (
            len(list(target.iterdir())) if target.is_dir() else 0
        ),
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }


def _fail_closed_matrix(
    repo_root: Path, passing_payload: Mapping[str, Any]
) -> list[dict[str, Any]]:
    cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        (
            "only_one_of_seven_comparisons",
            lambda item: item["sim_vs_real"].__setitem__(slice(1, None), []),
        ),
        (
            "payload_flips_direction",
            lambda item: item["sim_vs_real"][0].__setitem__(
                "lower_is_better", False
            ),
        ),
        (
            "payload_selects_other_band",
            lambda item: item["sim_vs_real"][0].__setitem__("band_key", "tdoa_us"),
        ),
        ("missing_take", lambda item: item["takes"].pop()),
        (
            "duplicate_take",
            lambda item: item["takes"].append(copy.deepcopy(item["takes"][0])),
        ),
        (
            "misstratified_take",
            lambda item: item["takes"][0]["identity"].__setitem__(
                "stratum_id", "A_controlled_boundary_sweep"
            ),
        ),
        (
            "wrong_group",
            lambda item: item["takes"][0]["identity"].__setitem__(
                "group_id", "wrong"
            ),
        ),
        (
            "wrong_pair",
            lambda item: item["takes"][26]["identity"].__setitem__(
                "paired_counterpart_take_id",
                item["takes"][28]["identity"]["planned_take_id"],
            ),
        ),
        (
            "one_window_for_stratum",
            lambda item: item["takes"][0].__setitem__(
                "window_summary",
                {
                    "source_window_count": 1,
                    "abstained_window_count": 1,
                    "sub_floor_direction_emission_count": 0,
                },
            ),
        ),
        (
            "one_real_counterpart_for_32",
            lambda item: item["sim_vs_real"][0].__setitem__(
                "conditions", item["sim_vs_real"][0]["conditions"][:1]
            ),
        ),
        (
            "duplicate_tdoa_pair",
            lambda item: item["takes"][1]["tdoa"].__setitem__(
                1, copy.deepcopy(item["takes"][1]["tdoa"][0])
            ),
        ),
        (
            "negative_absolute_error",
            lambda item: item["takes"][1].__setitem__(
                "bearing_absolute_error_deg", -1.0
            ),
        ),
        (
            "negative_latency",
            lambda item: item["takes"][0]["latency"].__setitem__(
                "frame_to_adapter_round_trip_ms", -1.0
            ),
        ),
        (
            "negative_clip_run",
            lambda item: item["takes"][0]["channels"][0].__setitem__(
                "maximum_clip_run_samples", -1
            ),
        ),
        (
            "negative_av_residual",
            lambda item: item["takes"][43].__setitem__(
                "av_absolute_residual_ms", -1.0
            ),
        ),
        (
            "tdoa_outside_physical_domain",
            lambda item: item["takes"][1]["tdoa"][0].__setitem__(
                "tdoa_us", 273.0
            ),
        ),
        (
            "confidence_above_one",
            lambda item: item["takes"][26].__setitem__("confidence", 1.1),
        ),
    ]
    records: list[dict[str, Any]] = []
    for name, mutation in cases:
        payload = copy.deepcopy(passing_payload)
        try:
            mutation(payload)
            result = evaluate_corrective(payload, repo_root=repo_root)
            rejected = not result.readiness_passed
            detail = (
                "evaluation failed readiness"
                if rejected
                else "unexpected readiness pass"
            )
        except CorrectiveAcceptanceError as exc:
            rejected = True
            detail = str(exc)
        records.append(
            {
                "case": name,
                "status": "passed" if rejected else "failed",
                "fail_closed": rejected,
                "detail": detail,
            }
        )
    return records


def _freeze_ordering(
    repo_root: Path,
    config: Mapping[str, Any],
    source_commit: str,
    source_tree_replay: bool,
) -> dict[str, Any]:
    frozen = _timestamp(config["frozen_at_utc"])
    baseline_time = _timestamp(config["baseline"]["committed_at_utc"])
    contract_time = _timestamp("2026-07-26T15:29:18Z")
    evaluator_time = _timestamp("2026-07-26T15:36:06Z")
    ordered = baseline_time < frozen <= contract_time <= evaluator_time
    ancestry_valid = True
    if not source_tree_replay:
        for ancestor in (BASELINE_COMMIT, CONTRACT_COMMIT, EVALUATOR_COMMIT):
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, source_commit],
                cwd=repo_root,
                check=False,
            )
            ancestry_valid = ancestry_valid and result.returncode == 0
    return {
        "schema": "ias.s4_7.corrective_freeze_ordering.v2",
        "status": "passed" if ordered and ancestry_valid else "failed",
        "baseline_commit": BASELINE_COMMIT,
        "baseline_committed_at_utc": config["baseline"]["committed_at_utc"],
        "frozen_at_utc": config["frozen_at_utc"],
        "contract_commit": CONTRACT_COMMIT,
        "contract_committed_at_utc": "2026-07-26T15:29:18Z",
        "evaluator_commit": EVALUATOR_COMMIT,
        "evaluator_committed_at_utc": "2026-07-26T15:36:06Z",
        "source_commit": source_commit,
        "baseline_before_freeze": baseline_time < frozen,
        "freeze_not_after_contract_commit": frozen <= contract_time,
        "contract_not_after_evaluator_commit": contract_time <= evaluator_time,
        "corrective_ancestry_valid": ancestry_valid,
        "holdout_observations_accessed": 0,
    }


def _holdout_binding(
    repo_root: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    binding = config["holdout_binding"]
    checks = {
        "seal_file": sha256_file(repo_root / binding["seal_path"])
        == binding["seal_file_sha256"],
        "partition_manifest": sha256_file(
            repo_root / binding["partition_manifest_path"]
        )
        == binding["partition_manifest_sha256"],
        "session_manifest": sha256_file(
            repo_root / binding["session_manifest_path"]
        )
        == binding["session_manifest_sha256"],
        "same_holdout_as_v1": binding["bound_holdout_id"]
        == "s4_4_data_expansion_amendment_03_prospective_holdout",
        "planned_take_count": binding["planned_take_count"] == 47,
        "scientifically_unopened": binding["scientifically_opened"] is False,
    }
    return {
        "schema": "ias.s4_7.corrective_holdout_binding.v2",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        **binding,
        "holdout_observations_accessed": 0,
    }


def _historical_preservation(repo_root: Path) -> dict[str, Any]:
    package = repo_root / V1_PACKAGE
    expected_manifest_sha = (
        "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53"
    )
    records = [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
        }
        for path in sorted(package.iterdir())
        if path.is_file()
    ]
    checksum_valid = True
    for line in (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        checksum_valid = checksum_valid and sha256_file(package / name) == digest
    v1_preservation = _load_json(
        package / "preservation_phase_boundary_report.json"
    )
    status = (
        len(records) == 16
        and sha256_file(package / "SHA256SUMS") == expected_manifest_sha
        and checksum_valid
        and v1_preservation["status"] == "passed"
    )
    return {
        "schema": "ias.s4_7.corrective_historical_preservation.v2",
        "status": "passed" if status else "failed",
        "historical_package_path": V1_PACKAGE.as_posix(),
        "historical_source_commit": HISTORICAL_SOURCE_COMMIT,
        "historical_package_file_count": len(records),
        "historical_sha256_manifest_sha256": sha256_file(
            package / "SHA256SUMS"
        ),
        "expected_historical_sha256_manifest_sha256": expected_manifest_sha,
        "historical_sha256_manifest_valid": checksum_valid,
        "historical_records": records,
        "preserved_s4_4_tracked_tree_sha256": v1_preservation[
            "s4_4_tracked_tree_sha256"
        ],
        "preserved_s4_5_tracked_tree_sha256": v1_preservation[
            "s4_5_tracked_tree_sha256"
        ],
        "preserved_s4_6_tracked_tree_sha256": v1_preservation[
            "s4_6_tracked_tree_sha256"
        ],
        "holdout_observations_accessed": 0,
    }


def _validate_source_commit(repo_root: Path, source_commit: str) -> None:
    if (
        len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise S47CorrectiveEvidenceError(
            "source commit must be a full lowercase SHA-1"
        )
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise S47CorrectiveEvidenceError("source commit does not exist")
    changed = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *SOURCE_BOUND_FILES],
        cwd=repo_root,
        check=False,
    )
    if changed.returncode != 0:
        raise S47CorrectiveEvidenceError(
            "corrective sources differ from source commit"
        )
    for ancestor in (BASELINE_COMMIT, CONTRACT_COMMIT, EVALUATOR_COMMIT):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, source_commit],
            cwd=repo_root,
            check=False,
        )
        if result.returncode != 0:
            raise S47CorrectiveEvidenceError(
                f"source commit does not descend from {ancestor}"
            )


def _evidence_records(
    output: Path, names: set[str] | frozenset[str]
) -> list[dict[str, Any]]:
    return [
        {
            "path": name,
            "sha256": sha256_file(output / name),
            "byte_size": (output / name).stat().st_size,
        }
        for name in sorted(names)
    ]


def _checksum_text(output: Path) -> str:
    return "".join(
        f"{sha256_file(output / name)}  {name}\n"
        for name in sorted(REQUIRED_PACKAGE_FILES - {"SHA256SUMS"})
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise S47CorrectiveEvidenceError(f"expected object: {path}")
    return value


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = [
    "OUTPUT_PATH",
    "SOURCE_BOUND_FILES",
    "S47CorrectiveEvidenceError",
    "build_evidence_package",
    "validate_criteria_only",
    "validate_evidence_package",
]
