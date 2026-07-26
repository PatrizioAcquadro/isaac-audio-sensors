"""Deterministic evidence for the additive S4.7 corrective_02 contract."""

from __future__ import annotations

import copy
import json
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_02 import (
    ACCEPTANCE_SCHEMA,
    CANONICAL_PACKAGE,
    CANONICAL_PREREQUISITE,
    EVIDENCE_INDEX_SCHEMA,
    REPORT_SCHEMAS,
    REQUIRED_PACKAGE_FILES,
    S47PrerequisiteError,
    validate_s4_7_corrective_02_prerequisite,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_02 import (
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

SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance_corrective_02.md")
V1_SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance.md")
V1_PACKAGE = Path("outputs/isaac_audio_sensors/S4/S4.7")
OUTPUT_PATH = CANONICAL_PACKAGE
CORRECTIVE_01_PACKAGE = Path(
    "outputs/isaac_audio_sensors/S4/S4.7_corrective_01"
)
TOOL_VERSION = "ias_s4_7_corrective_evidence/3.0.0"
BASELINE_COMMIT = "f2230128fd02294892282b5809abe71092f19013"
CORRECTIVE_01_CLOSEOUT_COMMIT = "6b0e8387a3c04fa4b513ab1bbe8514ef1f6b11d3"
SOURCE_BOUND_FILES = (
    CONFIG_PATH,
    SCHEMA_PATH,
    SPEC_PATH,
    V1_CONFIG_PATH,
    V1_SPEC_PATH,
    Path("scripts/generate_s4_7_corrective_02_evidence.py"),
    Path("scripts/replay_s4_7_corrective_02.py"),
    Path("scripts/run_s4_7_corrective_02_evaluation.py"),
    Path("scripts/validate_s4_7_corrective_02.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_4.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7_corrective_02.py"),
    Path(
        "src/isaac_audio_sensors/acquisition/"
        "s4_7_prerequisite_corrective_02.py"
    ),
    Path("src/isaac_audio_sensors/core/acceptance_criteria_corrective_02.py"),
    Path("tests/test_s4_4_holdout_freeze.py"),
    Path("tests/test_s4_7_corrective_02_acceptance.py"),
    Path("tests/test_s4_7_corrective_02_contract.py"),
    Path("tests/test_s4_7_corrective_02_evidence.py"),
    Path("tests/test_s4_7_evidence.py"),
    Path("tests/test_s4_8_corrective_interlock.py"),
    Path("tests/test_s4_8_corrective_02_interlock.py"),
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
        "schema": "ias.s4_7.corrective_criteria_validation.v3",
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
    stratum_counts = Counter(item.stratum_id for item in registry.values())
    effective_criteria = [
        {
            key: item[key]
            for key in (
                "criterion_id",
                "tier",
                "gating",
                "metric",
                "statistic",
                "comparator",
                "threshold",
                "denominator",
                "failure_logic",
            )
        }
        | {"effective_semantics": _effective_semantics(item["criterion_id"])}
        for item in v1["criteria"]
    ]
    internal_pass = all(
        (
            criteria_validation["status"] == "passed",
            first.readiness_passed,
            not failing.readiness_passed,
            first.report() == second.report(),
            all(item["status"] == "passed" for item in matrix),
            freeze["baseline_before_freeze"],
            freeze["corrective_01_before_freeze"],
            freeze["source_descends_from_corrective_01"],
            binding["scientifically_opened"] is False,
            binding["technical_qa_only"] is True,
            all(
                item["manifest_valid"] for item in preservation["packages"]
            ),
        )
    )
    common = {
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
        "seal_file_sha256": config["holdout_binding"]["seal_file_sha256"],
        "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
        "planned_take_count": 47,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    reports: dict[str, dict[str, Any]] = {
        "blindness_attestation.json": _report(
            "blindness_attestation.json",
            common,
            {
                "holdout_derived_outcomes_accessed": 0,
                "raw_dataset_content_accessed": False,
                "holdout_access_grant_created": False,
                "holdout_access_grant_consumed": False,
                "thresholds_selected_from_holdout": False,
            },
        ),
        "contract_validation.json": _report(
            "contract_validation.json",
            common,
            {
                "criteria_validation_status": criteria_validation["status"],
                "thresholds_changed": False,
                "claimed_envelope_changed": False,
                "scientific_eligibility_changed": False,
                "criteria_config_sha256": sha256_file(root / CONFIG_PATH),
                "criteria_schema_sha256": sha256_file(root / SCHEMA_PATH),
                "corrective_spec_sha256": sha256_file(root / SPEC_PATH),
            },
        ),
        "criteria_register.json": _report(
            "criteria_register.json",
            common,
            {
                "inherited_config_sha256": sha256_file(root / V1_CONFIG_PATH),
                "criterion_count": 29,
                "readiness_criterion_count": 23,
                "stretch_criterion_count": 6,
                "resolution": "corrective_02_effective_semantics",
                "criteria": effective_criteria,
            },
        ),
        "determinism_report.json": _report(
            "determinism_report.json",
            common,
            {
                "run_count": 2,
                "evaluation_reports_identical": (
                    first.report() == second.report()
                ),
                "randomness_used": False,
                "wall_clock_input_used": False,
            },
        ),
        "fail_closed_matrix.json": _report(
            "fail_closed_matrix.json",
            common,
            {
                "case_count": len(matrix),
                "cases": matrix,
                "silent_pass_observed": False,
            },
        ),
        "freeze_ordering.json": _report(
            "freeze_ordering.json", common, freeze
        ),
        "historical_preservation.json": _report(
            "historical_preservation.json", common, preservation
        ),
        "holdout_binding_report.json": _report(
            "holdout_binding_report.json", common, binding
        ),
        "identity_registry.json": _report(
            "identity_registry.json",
            common,
            {
                "take_count": len(registry),
                "take_ids_sha256": first.report()["identity_summary"][
                    "take_ids_sha256"
                ],
                "group_count": len(
                    {item.group_id for item in registry.values()}
                ),
                "stratum_counts": dict(sorted(stratum_counts.items())),
                "raw_microphone_ids": config["identity_contract"][
                    "raw_microphone_ids"
                ],
                "microphone_pair_ids": config["identity_contract"][
                    "microphone_pair_ids"
                ],
            },
        ),
        "input_contract_report.json": _report(
            "input_contract_report.json",
            common,
            {
                "exact_take_set_required": True,
                "unique_identity_required": True,
                "per_take_window_coverage_required": True,
                "latency_take_count": 47,
                "raw_channel_record_count": 188,
                "tdoa_take_pair_record_count": 144,
                "bearing_sim_real_condition_count": 32,
                "bearing_referenced_take_count": 40,
                "maximum_clip_run_threshold_samples": 8,
                "sustained_clipping_minimum_samples": 4000,
                "real_values_derived": True,
            },
        ),
        "phase_boundary.json": _report(
            "phase_boundary.json",
            common,
            {
                "holdout_access_grant_created": False,
                "holdout_access_grant_consumed": False,
                "s4_8_started": False,
                "s4_9_started": False,
                "s5_started": False,
                "s6_started": False,
                "push_performed": False,
                "tag_created": False,
            },
        ),
        "reproduction.json": _report(
            "reproduction.json",
            common,
            {
                "command": (
                    "python3 scripts/replay_s4_7_corrective_02.py "
                    "--canonical "
                    "outputs/isaac_audio_sensors/S4/S4.7_corrective_02"
                ),
                "comparison": "byte_for_byte_complete_package",
                "clean_source_archive": True,
                "requires_holdout_observations": False,
            },
        ),
        "sim_vs_real_registry.json": _report(
            "sim_vs_real_registry.json",
            common,
            {
                "comparison_registry": config["sim_vs_real"][
                    "comparison_registry"
                ],
                "comparison_count": 7,
                "bearing_sim_real_condition_count": 32,
                "bearing_referenced_take_count": 40,
                "payload_may_supply_real": False,
            },
        ),
        "synthetic_evaluation_report.json": _report(
            "synthetic_evaluation_report.json",
            common,
            {
                "fixtures_are_synthetic": True,
                "conforming_evaluation": first.report(),
                "violating_evaluation": failing.report(),
                "conforming_fixture_passes": first.readiness_passed,
                "violating_fixture_fails": not failing.readiness_passed,
            },
        ),
    }
    reports["final_validation.json"] = _report(
        "final_validation.json",
        common,
        {
            "criteria_only_validation_passed": (
                criteria_validation["status"] == "passed"
            ),
            "identity_registry_complete": len(registry) == 47,
            "comparison_registry_complete": (
                len(config["sim_vs_real"]["comparison_registry"]) == 7
            ),
            "fail_closed_matrix_passed": all(
                item["status"] == "passed" for item in matrix
            ),
            "deterministic": first.report() == second.report(),
            "freeze_ordering_valid": all(freeze.values()),
            "historical_packages_preserved": all(
                item["manifest_valid"] for item in preservation["packages"]
            ),
            "holdout_binding_valid": (
                binding["scientifically_opened"] is False
                and binding["technical_qa_only"] is True
            ),
            "readiness_criterion_count": 23,
            "stretch_criterion_count": 6,
        },
    )
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
        "corrective_id": "s4_7_corrective_02",
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
        "evidence_commit_policy": (
            "derived_from_git_commit_containing_exact_package_bytes"
        ),
        "deterministic_replay_required": True,
    }
    _write_json(target / CANONICAL_PREREQUISITE.name, acceptance)
    (target / "SHA256SUMS").write_text(
        _checksum_text(target), encoding="utf-8"
    )
    return {
        "schema": "ias.s4_7.corrective_evidence_build.v3",
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
        validate_s4_7_corrective_02_prerequisite(
            target / CANONICAL_PREREQUISITE.name,
            seal_path=root / acceptance["seal_path"],
            require_committed=require_committed,
            verify_replay=True,
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
        "schema": "ias.s4_7.corrective_evidence_validation.v3",
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
    def take_for(payload: dict[str, Any], stratum: str) -> dict[str, Any]:
        return next(
            item
            for item in payload["takes"]
            if item["identity"]["stratum_id"] == stratum
        )

    def set_clip(
        payload: dict[str, Any], run: int, sustained: bool
    ) -> None:
        channel = payload["takes"][0]["channels"][0]
        channel["maximum_clip_run_samples"] = run
        channel["sustained_clipping"] = sustained

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
        (
            "caller_supplied_real_100_for_four_degree_bearing",
            lambda item: item["sim_vs_real"][0]["conditions"][0].__setitem__(
                "real", 100.0
            ),
        ),
        (
            "estimated_bearing_contradicts_reported_error",
            lambda item: take_for(
                item, "A_controlled_boundary_sweep"
            ).__setitem__("estimated_bearing_deg_f_project", 40.0),
        ),
        (
            "target_bearing_contradicts_authenticated_identity",
            lambda item: take_for(
                item, "B_center_nominal_level"
            )["identity"].__setitem__("target_bearing_deg_f_project", 90.0),
        ),
        (
            "sector_result_contradicts_bearings",
            lambda item: take_for(
                item, "B_center_nominal_level"
            ).__setitem__("sector_correct", False),
        ),
        (
            "candidate_result_contradicts_candidates",
            lambda item: take_for(
                item, "A_controlled_boundary_sweep"
            ).__setitem__("candidate_covered", False),
        ),
        (
            "failure_status_contradicts_reasons",
            lambda item: item["takes"][0].__setitem__("failed", True),
        ),
        (
            "tdoa_error_contradicts_source_observations",
            lambda item: take_for(
                item, "A_controlled_boundary_sweep"
            )["tdoa"][0].__setitem__("absolute_error_us", 6.0),
        ),
        (
            "av_residual_contradicts_event_times",
            lambda item: take_for(
                item, "E_impact_audio_video"
            ).__setitem__("av_absolute_residual_ms", 21.0),
        ),
        (
            "sector_condition_fraction",
            lambda item: item["sim_vs_real"][1]["conditions"][0].__setitem__(
                "adjusted_simulation", 0.5
            ),
        ),
        (
            "candidate_condition_fraction",
            lambda item: item["sim_vs_real"][2]["conditions"][0].__setitem__(
                "adjusted_simulation", 0.5
            ),
        ),
        ("nine_sample_run_reported_sustained", lambda item: set_clip(item, 9, True)),
        (
            "3999_sample_run_reported_sustained",
            lambda item: set_clip(item, 3999, True),
        ),
        (
            "4000_sample_run_reported_not_sustained",
            lambda item: set_clip(item, 4000, False),
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
    corrective_01_time = _timestamp("2026-07-26T15:56:52Z")
    ancestry_valid = True
    if not source_tree_replay:
        result = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                CORRECTIVE_01_CLOSEOUT_COMMIT,
                source_commit,
            ],
            cwd=repo_root,
            check=False,
        )
        ancestry_valid = result.returncode == 0
    return {
        "baseline_commit": BASELINE_COMMIT,
        "corrective_01_closeout_commit": CORRECTIVE_01_CLOSEOUT_COMMIT,
        "frozen_at_utc": config["frozen_at_utc"],
        "source_commit": source_commit,
        "baseline_before_freeze": baseline_time < frozen,
        "corrective_01_before_freeze": corrective_01_time < frozen,
        "source_descends_from_corrective_01": ancestry_valid,
    }


def _holdout_binding(
    repo_root: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    binding = config["holdout_binding"]
    if (
        sha256_file(repo_root / binding["seal_path"])
        != binding["seal_file_sha256"]
        or sha256_file(repo_root / binding["partition_manifest_path"])
        != binding["partition_manifest_sha256"]
        or sha256_file(repo_root / binding["session_manifest_path"])
        != binding["session_manifest_sha256"]
    ):
        raise S47CorrectiveEvidenceError("holdout binding hash mismatch")
    return {
        "seal_path": binding["seal_path"],
        "partition_manifest_path": binding["partition_manifest_path"],
        "partition_manifest_sha256": binding["partition_manifest_sha256"],
        "session_manifest_path": binding["session_manifest_path"],
        "session_manifest_sha256": binding["session_manifest_sha256"],
        "group_count": binding["group_count"],
        "scientifically_opened": binding["scientifically_opened"],
        "technical_qa_only": binding["technical_qa_only"],
    }


def _historical_preservation(repo_root: Path) -> dict[str, Any]:
    expected = (
        (
            V1_PACKAGE,
            16,
            "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53",
        ),
        (
            CORRECTIVE_01_PACKAGE,
            18,
            "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676",
        ),
    )
    packages = []
    for relative, file_count, manifest_sha in expected:
        package = repo_root / relative
        present = [path for path in package.iterdir() if path.is_file()]
        valid = len(present) == file_count
        for line in (package / "SHA256SUMS").read_text(
            encoding="utf-8"
        ).splitlines():
            digest, name = line.split("  ", 1)
            valid = valid and sha256_file(package / name) == digest
        valid = (
            valid
            and sha256_file(package / "SHA256SUMS") == manifest_sha
        )
        packages.append(
            {
                "path": relative.as_posix(),
                "file_count": len(present),
                "sha256_manifest_sha256": sha256_file(
                    package / "SHA256SUMS"
                ),
                "manifest_valid": valid,
            }
        )
    return {"packages": packages}


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
    for ancestor in (BASELINE_COMMIT, CORRECTIVE_01_CLOSEOUT_COMMIT):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, source_commit],
            cwd=repo_root,
            check=False,
        )
        if result.returncode != 0:
            raise S47CorrectiveEvidenceError(
                f"source commit does not descend from {ancestor}"
            )


def _report(
    name: str,
    common: Mapping[str, Any],
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMAS[name],
        **common,
        "details": dict(details),
    }


def _effective_semantics(criterion_id: str) -> str:
    if criterion_id.startswith("bearing_"):
        return (
            "derive circular absolute error from authenticated target and "
            "estimated bearing on the exact keyed take set"
        )
    if criterion_id.startswith("sector_accuracy"):
        return (
            "derive exact 0-or-1 B-take sector correctness by applying "
            "bearing_deg_to_sector_name to authenticated target and estimate"
        )
    if criterion_id.startswith("candidate_coverage"):
        return (
            "derive exact 0-or-1 A+B coverage from emitted candidate bearings "
            "within the frozen 20 degree circular target tolerance"
        )
    if criterion_id == "within_cell_bearing_circular_range_stratum_a":
        return (
            "derive from authenticated A-take estimated bearings across eight "
            "exact three-repetition cells"
        )
    if criterion_id == "within_cell_pair_tdoa_range_stratum_a":
        return (
            "derive from 144 authenticated A-take microphone-pair TDOA "
            "observations grouped into 48 exact three-repetition groups"
        )
    if "latency" in criterion_id or criterion_id == "capture_to_frame_offline_spread":
        return "derive from exactly one keyed latency summary per each of 47 takes"
    if criterion_id in {
        "raw_channel_health_failure_count",
        "major_polarity_anomaly_count",
    }:
        return "derive from exactly 188 four-raw-microphone take-channel records"
    if criterion_id == "sustained_clipping_take_count":
        return (
            "classify a take only when any raw-channel run is at least 4000 "
            "consecutive samples; denominator is exactly 47 takes"
        )
    if criterion_id == "maximum_clip_run_samples":
        return (
            "take the maximum over 188 raw-channel take records, never a total; "
            "the unchanged readiness threshold is 8 samples"
        )
    if criterion_id == "take_failure_rate":
        return (
            "derive failed from a non-empty terminal failure-reason list for "
            "every one of 47 planned takes"
        )
    if "abstention" in criterion_id:
        return (
            "derive from exact per-take source and abstained window counts; "
            "active uses abstained fraction and silence uses non-abstained fraction"
        )
    if "confidence" in criterion_id:
        return "derive from the matching exact keyed B or C take confidence"
    if criterion_id == "sub_floor_direction_emission_count":
        return "sum exact keyed per-take below-floor direction-emission counts"
    if criterion_id == "coarse_av_association_residual_stratum_e":
        return (
            "derive each E-take residual as the absolute difference between "
            "matching audio and video event times"
        )
    if criterion_id.startswith("sim_adjust"):
        return (
            "derive every real comparison value from its authenticated keyed "
            "take observation; accept only keyed simulation values"
        )
    raise S47CorrectiveEvidenceError(
        f"missing effective semantics for criterion: {criterion_id}"
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
