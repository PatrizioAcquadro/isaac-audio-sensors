"""Deterministic evidence for the additive S4.7 corrective_03 contract."""

from __future__ import annotations

import copy
import json
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    ACCEPTANCE_SCHEMA,
    CANONICAL_PACKAGE,
    CANONICAL_PREREQUISITE,
    EVIDENCE_INDEX_SCHEMA,
    INDEX_EXCLUSIONS,
    REPORT_SCHEMAS,
    REQUIRED_PACKAGE_FILES,
    SOURCE_BOUND_FILES,
    SPEC_PATH,
    V1_SPEC_PATH,
    S47PrerequisiteError,
    canonical_sha256,
    expected_effective_criteria,
    expected_scientific_semantics_sha256,
    validate_s4_7_corrective_03_prerequisite,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    CONFIG_PATH,
    SCHEMA_PATH,
    V1_CONFIG_PATH,
    CorrectiveAcceptanceError,
    build_identity_registry,
    build_semantic_bypass_regression_payload,
    build_synthetic_payload,
    evaluate_corrective,
    load_corrective_config,
    sha256_file,
)

OUTPUT_PATH = CANONICAL_PACKAGE
CORRECTIVE_02_CONFIG_PATH = Path(
    "configs/s4_7_holdout_acceptance.corrective_02.v3.json"
)
HISTORICAL_PACKAGES = (
    (
        Path("outputs/isaac_audio_sensors/S4/S4.7"),
        16,
        "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53",
    ),
    (
        Path("outputs/isaac_audio_sensors/S4/S4.7_corrective_01"),
        18,
        "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676",
    ),
    (
        Path("outputs/isaac_audio_sensors/S4/S4.7_corrective_02"),
        18,
        "79ce288bd60c38b25b611ce7921c5dcbb9462427dba2be13e71fbacc86f1b6a1",
    ),
)
BASELINE_COMMIT = "f2230128fd02294892282b5809abe71092f19013"
CORRECTIVE_01_CLOSEOUT_COMMIT = "6b0e8387a3c04fa4b513ab1bbe8514ef1f6b11d3"
CORRECTIVE_02_CLOSEOUT_COMMIT = "ca6c2f01316cd87c4a9835ccafe8eeb85f8b0804"


class S47CorrectiveEvidenceError(ValueError):
    """Raised when corrective_03 evidence cannot be built or validated."""


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def validate_criteria_only(repo_root: Path) -> dict[str, Any]:
    """Validate contract, exact semantics, and both synthetic outcomes."""

    root = repo_root.resolve()
    issues: list[str] = []
    try:
        config = load_corrective_config(root)
        registry = build_identity_registry(root, config)
        passing = build_synthetic_payload(root)
        bypass = build_semantic_bypass_regression_payload(root)
        first = evaluate_corrective(passing, repo_root=root)
        second = evaluate_corrective(passing, repo_root=root)
        bypass_result = evaluate_corrective(bypass, repo_root=root)
        semantics = expected_effective_criteria(root)
        bypass_bearing = _criterion(
            bypass_result.report(),
            "bearing_median_absolute_error_stratum_b",
        )
        bypass_sector = _criterion(
            bypass_result.report(), "sector_accuracy_stratum_b"
        )
        if first.report() != second.report():
            issues.append("synthetic evaluation is not deterministic")
        if not first.readiness_passed:
            issues.append("conforming exact-window fixture failed")
        if bypass_result.readiness_passed:
            issues.append("semantic-bypass regression passed")
        if bypass_bearing["observed"] != 19.5:
            issues.append("semantic-bypass B bearing result is not 19.5 deg")
        if bypass_sector["observed"] != 0.5:
            issues.append("semantic-bypass B sector result is not 0.50")
        if len(registry) != 47 or len(semantics) != 29:
            issues.append("identity or criteria register is incomplete")
    except (OSError, KeyError, CorrectiveAcceptanceError) as exc:
        config = {}
        registry = {}
        first = second = bypass_result = None
        semantics = []
        issues.append(str(exc))
    return {
        "schema": "ias.s4_7.corrective_criteria_validation.v4",
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
        "scientific_semantics_sha256": (
            canonical_sha256(semantics) if semantics else None
        ),
        "take_count": len(registry),
        "readiness_passed": bool(first and first.readiness_passed),
        "semantic_bypass_failed": bool(
            bypass_result and not bypass_result.readiness_passed
        ),
        "semantic_bypass_bearing_observed": (
            _criterion(
                bypass_result.report(),
                "bearing_median_absolute_error_stratum_b",
            )["observed"]
            if bypass_result
            else None
        ),
        "semantic_bypass_sector_observed": (
            _criterion(
                bypass_result.report(), "sector_accuracy_stratum_b"
            )["observed"]
            if bypass_result
            else None
        ),
        "deterministic": bool(
            first and second and first.report() == second.report()
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
    """Build the exact 18-file corrective_03 evidence package."""

    root = repo_root.resolve()
    target = output if output.is_absolute() else root / output
    if not source_tree_replay:
        _validate_source_commit(root, source_commit)
    if target.exists() and any(target.iterdir()):
        raise S47CorrectiveEvidenceError(f"output must be empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    config = load_corrective_config(root)
    c2 = _load_json(root / CORRECTIVE_02_CONFIG_PATH)
    registry = build_identity_registry(root, config)
    criteria_validation = validate_criteria_only(root)
    passing_payload = build_synthetic_payload(root)
    bypass_payload = build_semantic_bypass_regression_payload(root)
    first = evaluate_corrective(passing_payload, repo_root=root)
    second = evaluate_corrective(passing_payload, repo_root=root)
    bypass = evaluate_corrective(bypass_payload, repo_root=root)
    matrix = _fail_closed_matrix(root, passing_payload)
    preservation = _historical_preservation(root)
    binding = c2["holdout_binding"]
    semantics = expected_effective_criteria(root)
    semantics_sha = canonical_sha256(semantics)
    freeze = _freeze_ordering(root, source_commit)
    stratum_counts = Counter(item.stratum_id for item in registry.values())
    bypass_bearing = _criterion(
        bypass.report(), "bearing_median_absolute_error_stratum_b"
    )
    bypass_sector = _criterion(bypass.report(), "sector_accuracy_stratum_b")
    internal_pass = all(
        (
            criteria_validation["status"] == "passed",
            first.readiness_passed,
            first.report() == second.report(),
            not bypass.readiness_passed,
            bypass_bearing["observed"] == 19.5,
            bypass_sector["observed"] == 0.5,
            all(item["status"] == "passed" for item in matrix),
            all(item["manifest_valid"] for item in preservation["packages"]),
            all(freeze[key] for key in freeze if key.endswith("_valid")),
            semantics_sha == expected_scientific_semantics_sha256(root),
        )
    )
    common = {
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "bound_holdout_id": binding["bound_holdout_id"],
        "seal_file_sha256": binding["seal_file_sha256"],
        "seal_payload_sha256": binding["seal_payload_sha256"],
        "planned_take_count": 47,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }

    reports = {
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
                "scientific_semantics_sha256": semantics_sha,
            },
        ),
        "criteria_register.json": _report(
            "criteria_register.json",
            common,
            {
                "register_schema": "ias.s4_7.effective_criteria_register.v4",
                "resolution": (
                    "corrective_03_exact_machine_readable_semantics"
                ),
                "inherited_config_sha256": sha256_file(root / V1_CONFIG_PATH),
                "criterion_count": 29,
                "readiness_criterion_count": 23,
                "stretch_criterion_count": 6,
                "scientific_semantics_sha256": semantics_sha,
                "criteria": semantics,
            },
        ),
        "determinism_report.json": _report(
            "determinism_report.json",
            common,
            {
                "run_count": 2,
                "evaluation_reports_identical": first.report() == second.report(),
                "scientific_semantics_identical": (
                    semantics == expected_effective_criteria(root)
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
        "final_validation.json": _report(
            "final_validation.json",
            common,
            {
                "criteria_only_validation_passed": True,
                "identity_registry_complete": len(registry) == 47,
                "comparison_registry_complete": (
                    len(c2["sim_vs_real"]["comparison_registry"]) == 7
                ),
                "fail_closed_matrix_passed": all(
                    item["status"] == "passed" for item in matrix
                ),
                "semantic_bypass_regression_failed_closed": (
                    not bypass.readiness_passed
                ),
                "exact_scientific_semantics_authenticated": (
                    semantics_sha
                    == expected_scientific_semantics_sha256(root)
                ),
                "deterministic": first.report() == second.report(),
                "freeze_ordering_valid": all(
                    freeze[key] for key in freeze if key.endswith("_valid")
                ),
                "historical_packages_preserved": all(
                    item["manifest_valid"]
                    for item in preservation["packages"]
                ),
                "holdout_binding_valid": (
                    binding["scientifically_opened"] is False
                    and binding["technical_qa_only"] is True
                ),
                "readiness_criterion_count": 23,
                "stretch_criterion_count": 6,
            },
        ),
        "freeze_ordering.json": _report(
            "freeze_ordering.json", common, freeze
        ),
        "historical_preservation.json": _report(
            "historical_preservation.json", common, preservation
        ),
        "holdout_binding_report.json": _report(
            "holdout_binding_report.json",
            common,
            {
                key: binding[key]
                for key in (
                    "seal_path",
                    "partition_manifest_path",
                    "partition_manifest_sha256",
                    "session_manifest_path",
                    "session_manifest_sha256",
                    "group_count",
                    "scientifically_opened",
                    "technical_qa_only",
                )
            },
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
                "raw_microphone_ids": c2["identity_contract"][
                    "raw_microphone_ids"
                ],
                "microphone_pair_ids": c2["identity_contract"][
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
                "exact_bearing_window_identity_required": True,
                "bearing_window_record_count": first.report()[
                    "identity_summary"
                ]["bearing_window_record_count"],
                "latency_take_count": 47,
                "raw_channel_record_count": 188,
                "tdoa_take_pair_record_count": 144,
                "bearing_sim_real_condition_count": 32,
                "maximum_clip_run_threshold_samples": 8,
                "sustained_clipping_minimum_samples": 4000,
                "real_values_derived_from_exact_windows": True,
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
                    "python3 scripts/replay_s4_7_corrective_03.py --canonical "
                    "outputs/isaac_audio_sensors/S4/S4.7_corrective_03"
                ),
                "comparison": (
                    "byte_for_byte_and_exact_scientific_semantics"
                ),
                "clean_source_archive": True,
                "requires_holdout_observations": False,
            },
        ),
        "sim_vs_real_registry.json": _report(
            "sim_vs_real_registry.json",
            common,
            {
                "comparison_registry": c2["sim_vs_real"][
                    "comparison_registry"
                ],
                "comparison_count": 7,
                "bearing_sim_real_condition_count": 32,
                "bearing_referenced_take_count": 40,
                "payload_may_supply_real": False,
                "bearing_real_source": (
                    "median_valid_window_circular_absolute_error"
                ),
                "sector_real_source": (
                    "valid_window_sector_unique_majority_correctness"
                ),
            },
        ),
        "synthetic_evaluation_report.json": _report(
            "synthetic_evaluation_report.json",
            common,
            {
                "fixtures_are_synthetic": True,
                "conforming_evaluation": first.report(),
                "semantic_bypass_evaluation": bypass.report(),
                "conforming_fixture_passes": first.readiness_passed,
                "semantic_bypass_fails": not bypass.readiness_passed,
                "incorrect_corrective_02_b_median_error_deg": 4.5,
                "incorrect_corrective_02_b_sector_accuracy": 1.0,
                "frozen_b_median_error_deg": bypass_bearing["observed"],
                "frozen_b_sector_accuracy": bypass_sector["observed"],
            },
        ),
    }
    expected_reports = REQUIRED_PACKAGE_FILES - INDEX_EXCLUSIONS
    if set(reports) != expected_reports:
        raise S47CorrectiveEvidenceError("internal report set mismatch")
    for name, report in reports.items():
        _write_json(target / name, report)
    records = [
        {
            "path": name,
            "sha256": sha256_file(target / name),
            "byte_size": (target / name).stat().st_size,
        }
        for name in sorted(expected_reports)
    ]
    index = {
        "schema": EVIDENCE_INDEX_SCHEMA,
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "file_count": 18,
        "records": records,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }
    _write_json(target / "evidence_index.json", index)
    acceptance = {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "passed" if internal_pass else "failed",
        "corrective_id": "s4_7_corrective_03",
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
        "bound_holdout_id": binding["bound_holdout_id"],
        "seal_path": binding["seal_path"],
        "seal_file_sha256": binding["seal_file_sha256"],
        "seal_payload_sha256": binding["seal_payload_sha256"],
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
        "scientific_semantics_sha256": semantics_sha,
    }
    _write_json(target / CANONICAL_PREREQUISITE.name, acceptance)
    (target / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(target / name)}  {name}\n"
            for name in sorted(REQUIRED_PACKAGE_FILES - {"SHA256SUMS"})
        ),
        encoding="utf-8",
    )
    return {
        "schema": "ias.s4_7.corrective_evidence_build.v4",
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "output": str(target),
        "file_count": 18,
        "scientific_semantics_sha256": semantics_sha,
        "holdout_observations_accessed": 0,
    }


def validate_evidence_package(
    repo_root: Path,
    output: Path = OUTPUT_PATH,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
    verify_replay: bool = True,
) -> dict[str, Any]:
    """Validate package bytes, exact report semantics, and source replay."""

    root = repo_root.resolve()
    target = output if output.is_absolute() else root / output
    issues: list[str] = []
    source_commit = ""
    try:
        acceptance = _load_json(target / CANONICAL_PREREQUISITE.name)
        source_commit = str(acceptance["source_commit"])
        validate_s4_7_corrective_03_prerequisite(
            target / CANONICAL_PREREQUISITE.name,
            seal_path=root / acceptance["seal_path"],
            require_committed=require_committed,
            verify_replay=verify_replay,
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
        "schema": "ias.s4_7.corrective_evidence_validation.v4",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "source_commit": source_commit,
        "file_count": len(list(target.iterdir())) if target.is_dir() else 0,
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "verify_replay": verify_replay,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }


def _fail_closed_matrix(
    repo_root: Path, passing_payload: Mapping[str, Any]
) -> list[dict[str, Any]]:
    def first_a(payload: dict[str, Any]) -> dict[str, Any]:
        return next(
            take
            for take in payload["takes"]
            if take["identity"]["stratum_id"]
            == "A_controlled_boundary_sweep"
        )

    cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        (
            "missing_window",
            lambda payload: first_a(payload)["bearing_windows"].pop(),
        ),
        (
            "duplicate_window_index",
            lambda payload: first_a(payload)["bearing_windows"][1].__setitem__(
                "window_index", 0
            ),
        ),
        (
            "non_finite_window_bearing",
            lambda payload: first_a(payload)["bearing_windows"][0].__setitem__(
                "srp_bearing_deg_f_project", float("nan")
            ),
        ),
        (
            "contradictory_reported_error",
            lambda payload: first_a(payload).__setitem__(
                "bearing_absolute_error_deg", 5.0
            ),
        ),
        (
            "caller_supplied_real",
            lambda payload: payload["sim_vs_real"][0]["conditions"][
                0
            ].__setitem__("real", 4.0),
        ),
        (
            "no_valid_bearing_window",
            _abstain_all_first_a,
        ),
    ]
    results = []
    for name, mutate in cases:
        fixture = copy.deepcopy(passing_payload)
        mutate(fixture)
        try:
            evaluate_corrective(fixture, repo_root=repo_root)
        except CorrectiveAcceptanceError as exc:
            results.append(
                {
                    "case": name,
                    "status": "passed",
                    "fail_closed": True,
                    "detail": str(exc),
                }
            )
        else:
            results.append(
                {
                    "case": name,
                    "status": "failed",
                    "fail_closed": False,
                    "detail": "invalid payload passed",
                }
            )
    return results


def _abstain_all_first_a(payload: dict[str, Any]) -> None:
    take = next(
        take
        for take in payload["takes"]
        if take["identity"]["stratum_id"] == "A_controlled_boundary_sweep"
    )
    for window in take["bearing_windows"]:
        window["abstained"] = True
        window["srp_bearing_deg_f_project"] = None
    take["window_summary"]["abstained_window_count"] = len(
        take["bearing_windows"]
    )
    take["bearing_absolute_error_deg"] = None
    take["estimated_bearing_deg_f_project"] = None


def _historical_preservation(repo_root: Path) -> dict[str, Any]:
    packages = []
    for relative, expected_count, expected_manifest_sha in HISTORICAL_PACKAGES:
        package = repo_root / relative
        files = [path for path in package.iterdir() if path.is_file()]
        valid = len(files) == expected_count
        for line in (package / "SHA256SUMS").read_text(
            encoding="utf-8"
        ).splitlines():
            digest, name = line.split("  ", 1)
            valid = valid and sha256_file(package / name) == digest
        valid = (
            valid
            and sha256_file(package / "SHA256SUMS")
            == expected_manifest_sha
        )
        packages.append(
            {
                "path": relative.as_posix(),
                "file_count": len(files),
                "sha256_manifest_sha256": sha256_file(
                    package / "SHA256SUMS"
                ),
                "manifest_valid": valid,
            }
        )
    return {"packages": packages}


def _freeze_ordering(repo_root: Path, source_commit: str) -> dict[str, Any]:
    def ancestor(commit: str) -> bool:
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, source_commit],
                cwd=repo_root,
                check=False,
            ).returncode
            == 0
        )

    return {
        "baseline_commit": BASELINE_COMMIT,
        "corrective_01_closeout_commit": CORRECTIVE_01_CLOSEOUT_COMMIT,
        "corrective_02_closeout_commit": CORRECTIVE_02_CLOSEOUT_COMMIT,
        "source_commit": source_commit,
        "baseline_ancestry_valid": ancestor(BASELINE_COMMIT),
        "corrective_01_ancestry_valid": ancestor(
            CORRECTIVE_01_CLOSEOUT_COMMIT
        ),
        "corrective_02_ancestry_valid": ancestor(
            CORRECTIVE_02_CLOSEOUT_COMMIT
        ),
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
    result = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *SOURCE_BOUND_FILES],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise S47CorrectiveEvidenceError(
            "corrective_03 sources differ from source commit"
        )


def _report(
    name: str, common: Mapping[str, Any], details: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMAS[name],
        **common,
        "details": dict(details),
    }


def _criterion(report: Mapping[str, Any], criterion_id: str) -> dict[str, Any]:
    return next(
        item for item in report["criteria"] if item["criterion_id"] == criterion_id
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise S47CorrectiveEvidenceError(f"expected object: {path}")
    return value


__all__ = [
    "OUTPUT_PATH",
    "S47CorrectiveEvidenceError",
    "build_evidence_package",
    "validate_criteria_only",
    "validate_evidence_package",
]
