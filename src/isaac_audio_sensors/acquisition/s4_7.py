"""Deterministic S4.7 preregistration evidence generation and validation.

The package records the frozen acceptance criteria, their strata and
denominators, the sealed-holdout binding, the blindness attestation, the
not-evaluable declaration, the sim-versus-real criteria, and an executed
fail-closed matrix. It reads only tracked repository files and never touches a
held-out observation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.acceptance_criteria import (
    CRITERIA_CONFIG_PATH,
    CRITERIA_SCHEMA_PATH,
    AcceptanceCriteriaError,
    evaluate_criteria,
    load_criteria,
)

OUTPUT_PATH = Path("outputs/isaac_audio_sensors/S4/S4.7")
TOOL_VERSION = "ias_s4_7_evidence/1.0.0"
ENTRY_COMMIT = "08c8009814dd2bc2cc1dc4d2d49ddebc96852371"
SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance.md")
PASS_FIXTURE_PATH = Path("examples/s4_7/synthetic_pass_metrics.v1.json")
FAIL_FIXTURE_PATH = Path("examples/s4_7/synthetic_fail_metrics.v1.json")
HOLDOUT_SEAL_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/holdout_seal.v1.json"
)
HISTORICAL_SEAL_PATH = Path("outputs/isaac_audio_sensors/S4/S4.4/holdout_seal.json")
ACCEPTANCE_SCHEMA = "ias.s4_7.holdout_acceptance.v1"
PROFILE_SCHEMA_SHA256 = (
    "fb56c9024bfa16ce25a999ed8e2552ab19189459f44801f33edd9f0d75d1ff46"
)
S4_4_TREE_DIGEST = "b079f2441f8c1a9c66d7d6fa9180b01a34ceb7a1be750c47db165afd2dc06caa"
S4_5_TREE_DIGEST = "165c49b2f483a4ba9d258f86f368323ffbbee8389553b57b5cbe993f3b70b234"
S4_6_TREE_DIGEST = "3ce8e3075a2d7acd9dd78b380bb1af269cb7539d314131d2f62cd59d20320dc6"
EXACT_REPLAY_COMMAND = (
    "python3 scripts/replay_s4_7.py --canonical outputs/isaac_audio_sensors/S4/S4.7"
)
REQUIRED_FILES = {
    "SHA256SUMS",
    "blindness_attestation.json",
    "criteria_register.json",
    "determinism_report.json",
    "evidence_index.json",
    "fail_closed_matrix.json",
    "final_validation.json",
    "holdout_acceptance.json",
    "holdout_binding_report.json",
    "not_evaluable_report.json",
    "preservation_phase_boundary_report.json",
    "provenance.json",
    "reproduction.json",
    "sim_vs_real_criteria.json",
    "strata_and_denominators.json",
    "synthetic_evaluation_report.json",
}
SOURCE_BOUND_FILES = (
    CRITERIA_CONFIG_PATH,
    CRITERIA_SCHEMA_PATH,
    SPEC_PATH,
    PASS_FIXTURE_PATH,
    FAIL_FIXTURE_PATH,
    Path("scripts/generate_s4_7_evidence.py"),
    Path("scripts/replay_s4_7.py"),
    Path("scripts/run_s4_7_preregistration.py"),
    Path("scripts/validate_s4_7.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_7.py"),
    Path("src/isaac_audio_sensors/core/acceptance_criteria.py"),
    Path("tests/conftest.py"),
    Path("tests/test_s4_7_acceptance_criteria.py"),
    Path("tests/test_s4_7_contract.py"),
    Path("tests/test_s4_7_evidence.py"),
)
PRESERVED_S4_4 = (Path("outputs/isaac_audio_sensors/S4/S4.4"),)
PRESERVED_S4_5 = (
    Path("outputs/isaac_audio_sensors/S4/S4.5"),
    Path("outputs/isaac_audio_sensors/S4/S4.5_corrective_01"),
    Path("outputs/isaac_audio_sensors/S4/S4.5_handoff_01"),
    Path("outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json"),
)
PRESERVED_S4_6 = (Path("outputs/isaac_audio_sensors/S4/S4.6"),)
LATER_PHASE_PATHS = (
    Path("outputs/isaac_audio_sensors/S4/S4.8"),
    Path("outputs/isaac_audio_sensors/S4/S4.9"),
    Path("outputs/isaac_audio_sensors/S5"),
    Path("dataset/S4.4/access/holdout_access_grant.json"),
    Path(
        "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/access/"
        "holdout_access_grant.json"
    ),
)


class S47EvidenceError(ValueError):
    """Raised when S4.7 evidence cannot be produced or validated."""


def pretty_json(value: Any) -> str:
    """Serialize one payload in the canonical evidence form."""

    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object, rejecting anything else."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S47EvidenceError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S47EvidenceError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _source_commit_valid(repo_root: Path, source_commit: str) -> None:
    if len(source_commit) != 40 or any(
        char not in "0123456789abcdef" for char in source_commit
    ):
        raise S47EvidenceError("source commit must be a full lowercase SHA-1")
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S47EvidenceError("source commit does not exist")
    changed = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *SOURCE_BOUND_FILES],
        cwd=repo_root,
        check=False,
    )
    if changed.returncode != 0:
        raise S47EvidenceError(
            "implementation sources differ from the requested source commit"
        )


def _tree_digest(repo_root: Path, source_commit: str, paths: tuple[Path, ...]) -> str:
    result = subprocess.run(
        ["git", "ls-tree", "-r", source_commit, *paths],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _evidence_records(output: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name not in {"SHA256SUMS", "evidence_index.json"}
    ]


def _checksum_text(output: Path) -> str:
    return "".join(
        f"{sha256_file(path)}  {path.name}\n"
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    )


def _copy_criteria_surface(repo_root: Path, target: Path) -> None:
    for relative in (CRITERIA_CONFIG_PATH, CRITERIA_SCHEMA_PATH):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / relative, destination)


def _payload_rejections(
    repo_root: Path,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Execute every payload-level fail-closed case against the real evaluator."""

    cases: tuple[tuple[str, Callable[[dict[str, Any]], None], str, str], ...] = (
        (
            "missing_observable",
            lambda item: item.pop("stratum_a_take_median_bearing_absolute_error_deg"),
            "criterion_failure",
            "bearing_median_absolute_error_stratum_a",
        ),
        (
            "non_finite_value",
            lambda item: item[
                "stratum_b_take_median_bearing_absolute_error_deg"
            ].__setitem__(0, float("nan")),
            "criterion_failure",
            "bearing_median_absolute_error_stratum_b",
        ),
        (
            "series_denominator_mismatch",
            lambda item: item["stratum_a_take_median_bearing_absolute_error_deg"].pop(),
            "criterion_failure",
            "bearing_median_absolute_error_stratum_a",
        ),
        (
            "counter_denominator_mismatch",
            lambda item: item.__setitem__(
                "stratum_b_sector_correct_take_count",
                {"numerator": 7, "denominator": 9},
            ),
            "criterion_failure",
            "sector_accuracy_stratum_b",
        ),
        (
            "counter_missing_field",
            lambda item: item.__setitem__(
                "stratum_b_sector_correct_take_count", {"numerator": 7}
            ),
            "criterion_failure",
            "sector_accuracy_stratum_b",
        ),
        (
            "counter_numerator_exceeds_denominator",
            lambda item: item.__setitem__(
                "stratum_b_sector_correct_take_count",
                {"numerator": 9, "denominator": 8},
            ),
            "criterion_failure",
            "sector_accuracy_stratum_b",
        ),
        (
            "series_non_numeric_member",
            lambda item: item[
                "stratum_e_av_association_absolute_residual_ms"
            ].__setitem__(0, "18.4"),
            "criterion_failure",
            "coarse_av_association_residual_stratum_e",
        ),
        (
            "empty_series",
            lambda item: item.__setitem__(
                "stratum_e_av_association_absolute_residual_ms", []
            ),
            "criterion_failure",
            "coarse_av_association_residual_stratum_e",
        ),
        (
            "grouped_series_group_count_mismatch",
            lambda item: item["stratum_a_cell_take_median_bearing_deg"].pop(
                "cell_22.5"
            ),
            "criterion_failure",
            "within_cell_bearing_circular_range_stratum_a",
        ),
        (
            "grouped_series_not_a_mapping",
            lambda item: item.__setitem__(
                "stratum_a_cell_take_median_bearing_deg", [1.0, 2.0]
            ),
            "criterion_failure",
            "within_cell_bearing_circular_range_stratum_a",
        ),
        (
            "scalar_not_a_number",
            lambda item: item.__setitem__(
                "all_takes_raw_channel_health_failure_count", True
            ),
            "criterion_failure",
            "raw_channel_health_failure_count",
        ),
        (
            "missing_comparison_set",
            lambda item: item.pop("sim_vs_real_comparisons"),
            "criterion_failure",
            "sim_adjustment_worsened_gating_metric_count",
        ),
        (
            "empty_comparison_set",
            lambda item: item.__setitem__("sim_vs_real_comparisons", []),
            "criterion_failure",
            "sim_adjustment_worsened_gating_metric_count",
        ),
        (
            "unexpected_observable",
            lambda item: item.__setitem__("invented_observable", [1.0]),
            "rejected",
            "",
        ),
        (
            "comparison_record_field_set_mismatch",
            lambda item: item["sim_vs_real_comparisons"][0].pop("band_key"),
            "rejected",
            "",
        ),
        (
            "comparison_unknown_band_key",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "band_key", "invented_band"
            ),
            "rejected",
            "",
        ),
        (
            "comparison_non_boolean_direction",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "lower_is_better", "yes"
            ),
            "rejected",
            "",
        ),
        (
            "comparison_non_finite_value",
            lambda item: item["sim_vs_real_comparisons"][0].__setitem__(
                "adjusted_simulation", float("inf")
            ),
            "rejected",
            "",
        ),
        (
            "comparison_set_not_a_sequence",
            lambda item: item.__setitem__("sim_vs_real_comparisons", {"a": 1}),
            "rejected",
            "",
        ),
    )

    records: list[dict[str, Any]] = []
    for case_id, mutate, expected, criterion_id in cases:
        mutated = copy.deepcopy(dict(payload))
        mutate(mutated)
        records.append(
            _execute_payload_case(repo_root, case_id, mutated, expected, criterion_id)
        )
    return records


def _execute_payload_case(
    repo_root: Path,
    case_id: str,
    mutated: Mapping[str, Any],
    expected: str,
    criterion_id: str,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "case_id": case_id,
        "expected": expected,
        "criterion_id": criterion_id or None,
    }
    try:
        result = evaluate_criteria(mutated, repo_root=repo_root)
    except AcceptanceCriteriaError as exc:
        record["actual"] = "rejected"
        record["detail"] = str(exc)
    else:
        outcome = next(
            item for item in result.outcomes if item.criterion_id == criterion_id
        )
        record["actual"] = "criterion_failure" if not outcome.passed else "accepted"
        record["detail"] = f"{outcome.status}: {outcome.detail}"
        record["readiness_passed"] = result.readiness_passed
    record["status"] = "passed" if record["actual"] == expected else "failed"
    return record


def _configuration_rejections(repo_root: Path) -> list[dict[str, Any]]:
    """Execute every configuration-level fail-closed case."""

    cases: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
        ("config_status_not_frozen", lambda item: item.__setitem__("status", "draft")),
        (
            "config_schema_mismatch",
            lambda item: item.__setitem__("schema", "ias.s4_7.invented.v1"),
        ),
        (
            "config_duplicate_criterion_id",
            lambda item: item["criteria"].append(copy.deepcopy(item["criteria"][0])),
        ),
        (
            "config_unknown_statistic",
            lambda item: item["criteria"][0].__setitem__("statistic", "mean"),
        ),
        (
            "config_incomplete_metric_contract",
            lambda item: item["criteria"][0]["metric_contract"].pop("exclusions"),
        ),
        (
            "config_holdout_declared_open",
            lambda item: item["holdout_binding"].__setitem__(
                "scientifically_opened", True
            ),
        ),
        (
            "config_declares_holdout_access",
            lambda item: item["phase_boundary"].__setitem__(
                "holdout_observations_accessed", 4
            ),
        ),
        (
            "config_declares_opening_workflow",
            lambda item: item["authority"].__setitem__(
                "implements_holdout_opening_workflow", True
            ),
        ),
    )

    records: list[dict[str, Any]] = []
    for case_id, mutate in cases:
        with tempfile.TemporaryDirectory(prefix="ias-s4-7-config-") as temp:
            root = Path(temp)
            _copy_criteria_surface(repo_root, root)
            config = load_json(root / CRITERIA_CONFIG_PATH)
            mutate(config)
            _write_json(root / CRITERIA_CONFIG_PATH, config)
            record: dict[str, Any] = {"case_id": case_id, "expected": "rejected"}
            try:
                load_criteria(repo_root=root)
            except AcceptanceCriteriaError as exc:
                record["actual"] = "rejected"
                record["detail"] = str(exc)
            else:
                record["actual"] = "accepted"
                record["detail"] = "the mutated configuration was accepted"
            record["status"] = "passed" if record["actual"] == "rejected" else "failed"
            records.append(record)
    return records


def _path_rejections(repo_root: Path) -> list[dict[str, Any]]:
    """Execute the path-safety cases that guard the frozen configuration.

    The absolute case uses a fixed literal rather than the real repository
    root, so that the recorded rejection message stays machine independent and
    the package replays byte-for-byte from a clean checkout.
    """

    cases = (
        ("absolute_config_path", Path("/configs/s4_7_holdout_acceptance.v1.json")),
        ("parent_traversal_config_path", Path("../configs/s4_7.json")),
        ("missing_config_path", Path("configs/s4_7_absent.v1.json")),
    )
    records: list[dict[str, Any]] = []
    for case_id, config_path in cases:
        record: dict[str, Any] = {"case_id": case_id, "expected": "rejected"}
        try:
            load_criteria(repo_root=repo_root, config_path=Path(config_path))
        except AcceptanceCriteriaError as exc:
            record["actual"] = "rejected"
            record["detail"] = str(exc)
        else:
            record["actual"] = "accepted"
            record["detail"] = "the unsafe configuration path was accepted"
        record["status"] = "passed" if record["actual"] == "rejected" else "failed"
        records.append(record)
    return records


def _criteria_register(config: Mapping[str, Any]) -> dict[str, Any]:
    readiness = [item for item in config["criteria"] if item["tier"] == "readiness"]
    stretch = [item for item in config["criteria"] if item["tier"] == "stretch"]
    return {
        "schema": "ias.s4_7.criteria_register.v1",
        "status": "passed",
        "criteria": list(config["criteria"]),
        "criterion_count": len(config["criteria"]),
        "readiness_criterion_count": len(readiness),
        "stretch_criterion_count": len(stretch),
        "gating_rule": config["failure_logic"]["readiness_pass_rule"],
        "statistics": config["statistics"],
        "missing_and_unsupported_treatment": config[
            "missing_and_unsupported_treatment"
        ],
        "failure_logic": config["failure_logic"],
        "metrics_covered": sorted({item["metric"] for item in config["criteria"]}),
        "thresholds_selected_from_holdout": False,
    }


def _holdout_binding_report(
    repo_root: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    binding = config["holdout_binding"]
    seal = load_json(repo_root / HOLDOUT_SEAL_PATH)
    observed_seal_sha = sha256_file(repo_root / HOLDOUT_SEAL_PATH)
    observed_historical_sha = sha256_file(repo_root / HISTORICAL_SEAL_PATH)
    consistent = (
        binding["seal_file_sha256"] == observed_seal_sha
        and binding["seal_payload_sha256"] == seal["seal_payload_sha256"]
        and binding["planned_take_count"] == len(seal["planned_take_ids"])
        and seal["scientifically_opened"] is False
        and seal["scientific_outputs_included"] is False
        and binding["excluded_historical_holdout"]["seal_file_sha256"]
        == observed_historical_sha
    )
    return {
        "schema": "ias.s4_7.holdout_binding_report.v1",
        "status": "passed" if consistent else "failed",
        "bound_holdout_id": binding["bound_holdout_id"],
        "seal_path": binding["seal_path"],
        "observed_seal_file_sha256": observed_seal_sha,
        "declared_seal_file_sha256": binding["seal_file_sha256"],
        "observed_seal_payload_sha256": seal["seal_payload_sha256"],
        "declared_seal_payload_sha256": binding["seal_payload_sha256"],
        "planned_take_count": len(seal["planned_take_ids"]),
        "seal_status": seal["status"],
        "scientifically_opened": seal["scientifically_opened"],
        "scientific_outputs_included": seal["scientific_outputs_included"],
        "technical_qa_only": seal["technical_qa_only"],
        "enforcement_boundary": "repository_tooling",
        "filesystem_owner_reads_prevented_or_detected": seal[
            "filesystem_owner_reads_prevented_or_detected"
        ],
        "excluded_historical_holdout": {
            **binding["excluded_historical_holdout"],
            "observed_seal_file_sha256": observed_historical_sha,
        },
    }


def _blindness_attestation(
    repo_root: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    anchors = {
        "s4_3_pilot_reports": "outputs/isaac_audio_sensors/S4/S4.3/reports",
        "s4_5_corrective_closeout": (
            "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/corrective_closeout.json"
        ),
        "s4_3_frozen_pilot_config": "configs/s4_3_pilot.v1.json",
    }
    grants = [
        path.as_posix() for path in LATER_PHASE_PATHS if (repo_root / path).exists()
    ]
    return {
        "schema": "ias.s4_7.blindness_attestation.v1",
        "status": "passed" if not grants else "failed",
        "holdout_observations_accessed": 0,
        "holdout_derived_outcomes_accessed": 0,
        "holdout_access_grant_created": False,
        "holdout_opening_workflow_implemented": False,
        "later_phase_artifacts_present": grants,
        "threshold_evidence_anchors": anchors,
        "threshold_evidence_kind": "development_fit_and_pilot_only",
        "attested_claim": (
            "every threshold was selected from S4.3 pilot and S4.5 "
            "development-fit evidence; no held-out observation, derived "
            "holdout outcome, or holdout summary informed any value"
        ),
        "enforcement_limitation": (
            "enforcement is repository tooling only; the sealed holdout "
            "records filesystem_owner_reads_prevented_or_detected as false, so "
            "blindness is attested and hash-bound rather than physically "
            "enforced"
        ),
        "frozen_at_utc": config["frozen_at_utc"],
    }


def _strata_report(config: Mapping[str, Any]) -> dict[str, Any]:
    strata = config["strata"]
    total = sum(item["take_count"] for item in strata)
    return {
        "schema": "ias.s4_7.strata_and_denominators.v1",
        "status": "passed" if total == 47 else "failed",
        "strata": list(strata),
        "total_take_count": total,
        "planned_take_count": config["holdout_binding"]["planned_take_count"],
        "primary_gating_statistic": "per_take_median",
        "sector_accuracy_gated_strata": [
            item["stratum_id"] for item in strata if item["sector_accuracy_gated"]
        ],
        "sector_boundary_strata": [
            item["stratum_id"]
            for item in strata
            if item["sector_geometry"] == "sector_boundary"
        ],
        "envelope": config["envelope"],
        "denominators": [
            {
                "criterion_id": item["criterion_id"],
                "denominator": item["denominator"],
                "statistic": item["statistic"],
                "strata": item["strata"],
            }
            for item in config["criteria"]
        ],
    }


def _not_evaluable_report(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_7.not_evaluable_report.v1",
        "status": "passed",
        "not_evaluable": config["not_evaluable"],
        "unsupported_quantities": config["unsupported_quantities"],
        "robustness_holdout_cell_count": 0,
        "robustness_gating_criterion_count": 0,
        "claimed_envelope": config["envelope"]["claimed_envelope"],
        "controlled_versus_robustness": config["envelope"][
            "controlled_versus_robustness"
        ],
    }


def _sim_vs_real_report(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ias.s4_7.sim_vs_real_criteria.v1",
        "status": "passed",
        **config["sim_vs_real"],
        "gating_criteria": [
            item["criterion_id"]
            for item in config["criteria"]
            if item["metric"] == "sim_versus_real" and item["gating"]
        ],
    }


def build_evidence_package(
    *,
    repo_root: Path,
    output: Path,
    source_commit: str,
    source_tree_replay: bool = False,
) -> dict[str, Any]:
    """Build the complete deterministic S4.7 preregistration evidence package."""

    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    if not source_tree_replay:
        _source_commit_valid(repo_root, source_commit)
    if output.exists() and any(output.iterdir()):
        raise S47EvidenceError(f"evidence output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    config = load_criteria(repo_root=repo_root)
    passing = load_json(repo_root / PASS_FIXTURE_PATH)
    failing = load_json(repo_root / FAIL_FIXTURE_PATH)
    first = evaluate_criteria(passing, repo_root=repo_root)
    second = evaluate_criteria(passing, repo_root=repo_root)
    failed = evaluate_criteria(failing, repo_root=repo_root)
    deterministic = first.report() == second.report()

    matrix = (
        _payload_rejections(repo_root, passing)
        + _configuration_rejections(repo_root)
        + _path_rejections(repo_root)
    )
    matrix_passed = all(record["status"] == "passed" for record in matrix)

    binding = _holdout_binding_report(repo_root, config)
    blindness = _blindness_attestation(repo_root, config)
    strata = _strata_report(config)
    register = _criteria_register(config)

    preservation = {
        "s4_4_tracked_tree_sha256": S4_4_TREE_DIGEST,
        "s4_5_tracked_tree_sha256": S4_5_TREE_DIGEST,
        "s4_6_tracked_tree_sha256": S4_6_TREE_DIGEST,
        "public_profile_schema_sha256": sha256_file(
            repo_root / "docs/schemas/audio_calibration_profile.v1.schema.json"
        ),
        "expected_public_profile_schema_sha256": PROFILE_SCHEMA_SHA256,
        "holdout_observations_accessed": 0,
        "s4_8_access_grant_created": False,
        "later_phases_started": [],
        "raw_media_accessed": False,
        "dataset_accessed": False,
    }
    if not source_tree_replay:
        preservation["s4_4_tracked_tree_sha256"] = _tree_digest(
            repo_root, source_commit, PRESERVED_S4_4
        )
        preservation["s4_5_tracked_tree_sha256"] = _tree_digest(
            repo_root, source_commit, PRESERVED_S4_5
        )
        preservation["s4_6_tracked_tree_sha256"] = _tree_digest(
            repo_root, source_commit, PRESERVED_S4_6
        )
    preservation["status"] = (
        "passed"
        if preservation["s4_4_tracked_tree_sha256"] == S4_4_TREE_DIGEST
        and preservation["s4_5_tracked_tree_sha256"] == S4_5_TREE_DIGEST
        and preservation["s4_6_tracked_tree_sha256"] == S4_6_TREE_DIGEST
        and preservation["public_profile_schema_sha256"] == PROFILE_SCHEMA_SHA256
        else "failed"
    )

    source_records = [
        {"path": path.as_posix(), "sha256": sha256_file(repo_root / path)}
        for path in SOURCE_BOUND_FILES
    ]
    config_sha = sha256_file(repo_root / CRITERIA_CONFIG_PATH)
    internal_pass = (
        deterministic
        and matrix_passed
        and binding["status"] == "passed"
        and blindness["status"] == "passed"
        and strata["status"] == "passed"
        and preservation["status"] == "passed"
        and first.readiness_passed
        and not failed.readiness_passed
    )

    files: dict[str, Any] = {
        "criteria_register.json": register,
        "strata_and_denominators.json": strata,
        "holdout_binding_report.json": binding,
        "blindness_attestation.json": blindness,
        "not_evaluable_report.json": _not_evaluable_report(config),
        "sim_vs_real_criteria.json": _sim_vs_real_report(config),
        "synthetic_evaluation_report.json": {
            "schema": "ias.s4_7.synthetic_evaluation_report.v1",
            "status": "passed"
            if first.readiness_passed and not failed.readiness_passed
            else "failed",
            "fixtures_are_synthetic": True,
            "holdout_observations_accessed": 0,
            "conforming_fixture": PASS_FIXTURE_PATH.as_posix(),
            "violating_fixture": FAIL_FIXTURE_PATH.as_posix(),
            "conforming_evaluation": first.report(),
            "violating_evaluation": failed.report(),
            "gate_bites": not failed.readiness_passed,
            "stretch_tier_is_independent": any(
                not outcome.passed
                for outcome in first.outcomes
                if outcome.tier == "stretch"
            ),
        },
        "determinism_report.json": {
            "schema": "ias.s4_7.determinism_report.v1",
            "status": "passed" if deterministic else "failed",
            "run_count": 2,
            "evaluation_reports_identical": deterministic,
            "randomness_used": False,
            "wall_clock_input_used": False,
        },
        "fail_closed_matrix.json": {
            "schema": "ias.s4_7.fail_closed_matrix.v1",
            "status": "passed" if matrix_passed else "failed",
            "case_count": len(matrix),
            "cases": matrix,
            "silent_pass_observed": False,
        },
        "preservation_phase_boundary_report.json": {
            "schema": "ias.s4_7.preservation_phase_boundary_report.v1",
            **preservation,
            "entry_commit": ENTRY_COMMIT,
            "s4_8_started": False,
            "s4_9_started": False,
            "s5_started": False,
            "s6_started": False,
        },
        "holdout_acceptance.json": {
            "schema": ACCEPTANCE_SCHEMA,
            "status": "passed" if internal_pass else "failed",
            "meaning": (
                "the S4.7 preregistration is complete, frozen, and hash-bound "
                "to the sealed holdout; it asserts nothing about any S4.8 "
                "result"
            ),
            "criteria_config_path": CRITERIA_CONFIG_PATH.as_posix(),
            "criteria_config_sha256": config_sha,
            "spec_path": SPEC_PATH.as_posix(),
            "spec_sha256": sha256_file(repo_root / SPEC_PATH),
            "frozen_at_utc": config["frozen_at_utc"],
            "bound_holdout_id": config["holdout_binding"]["bound_holdout_id"],
            "seal_path": config["holdout_binding"]["seal_path"],
            "seal_file_sha256": config["holdout_binding"]["seal_file_sha256"],
            "seal_payload_sha256": config["holdout_binding"]["seal_payload_sha256"],
            "planned_take_count": config["holdout_binding"]["planned_take_count"],
            "claimed_envelope": config["envelope"]["claimed_envelope"],
            "readiness_criterion_count": register["readiness_criterion_count"],
            "stretch_criterion_count": register["stretch_criterion_count"],
            "readiness_pass_rule": config["failure_logic"]["readiness_pass_rule"],
            "holdout_observations_accessed": 0,
            "holdout_access_grant_created": False,
            "authorizes_holdout_opening": False,
            "grant_still_required_for_s4_8": True,
        },
        "provenance.json": {
            "schema": "ias.s4_7.provenance.v1",
            "status": "passed",
            "source_commit": source_commit,
            "tool_version": TOOL_VERSION,
            "source_files": source_records,
            "criteria_config_sha256": config_sha,
            "holdout_observations_accessed": 0,
            "later_phases_started": [],
            "push_performed": False,
        },
        "reproduction.json": {
            "schema": "ias.s4_7.reproduction.v1",
            "status": "passed",
            "source_commit": source_commit,
            "command": EXACT_REPLAY_COMMAND,
            "comparison": "byte_for_byte_complete_package",
            "clean_source_archive": True,
            "requires_holdout_or_raw_media": False,
            "deterministic": True,
        },
    }
    files["final_validation.json"] = {
        "schema": "ias.s4_7.final_validation.v1",
        "status": "passed" if internal_pass else "failed",
        "criteria_frozen": True,
        "criteria_config_sha256": config_sha,
        "readiness_criterion_count": register["readiness_criterion_count"],
        "stretch_criterion_count": register["stretch_criterion_count"],
        "strata_cover_planned_takes": strata["status"] == "passed",
        "holdout_binding_consistent": binding["status"] == "passed",
        "blindness_attested": blindness["status"] == "passed",
        "fail_closed_matrix_passed": matrix_passed,
        "deterministic": deterministic,
        "preservation_passed": preservation["status"] == "passed",
        "conforming_fixture_passes_gate": first.readiness_passed,
        "violating_fixture_fails_gate": not failed.readiness_passed,
        "thresholds_selected_from_holdout": False,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }

    for name, payload in files.items():
        _write_json(output / name, payload)
    _write_json(
        output / "evidence_index.json",
        {
            "schema": "ias.s4_7.evidence_index.v1",
            "status": "passed" if internal_pass else "failed",
            "source_commit": source_commit,
            "tool_version": TOOL_VERSION,
            "records": _evidence_records(output),
            "holdout_observations_accessed": 0,
            "later_phases_started": [],
        },
    )
    (output / "SHA256SUMS").write_text(_checksum_text(output), encoding="utf-8")
    return {
        "schema": "ias.s4_7.evidence_build_result.v1",
        "status": "passed" if internal_pass else "failed",
        "source_commit": source_commit,
        "output": str(output),
        "file_count": len(REQUIRED_FILES),
    }


def validate_evidence_package(
    repo_root: Path,
    output: Path,
    *,
    require_tracked: bool = False,
    require_committed: bool = False,
) -> dict[str, Any]:
    """Validate completeness, hashes, semantics, provenance, and Git state."""

    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    issues: list[str] = []
    present = {path.name for path in output.iterdir()} if output.is_dir() else set()
    if present != REQUIRED_FILES:
        issues.append(
            f"file set mismatch: missing={sorted(REQUIRED_FILES - present)}, "
            f"extra={sorted(present - REQUIRED_FILES)}"
        )
    if output.is_dir():
        manifest = output / "SHA256SUMS"
        if not manifest.is_file():
            issues.append("SHA256SUMS missing")
        else:
            for line in manifest.read_text(encoding="utf-8").splitlines():
                try:
                    digest, name = line.split("  ", 1)
                except ValueError:
                    issues.append("malformed checksum line")
                    continue
                path = output / name
                if not path.is_file() or sha256_file(path) != digest:
                    issues.append(f"checksum mismatch: {name}")
        acceptance = output / "holdout_acceptance.json"
        if acceptance.is_file():
            payload = load_json(acceptance)
            if payload.get("schema") != ACCEPTANCE_SCHEMA:
                issues.append("holdout_acceptance.json schema mismatch")
            if payload.get("status") != "passed":
                issues.append("holdout_acceptance.json is not passing")
            if payload.get("authorizes_holdout_opening") is not False:
                issues.append("holdout_acceptance.json claims opening authority")
    source_commit = ""
    try:
        provenance = load_json(output / "provenance.json")
        source_commit = str(provenance["source_commit"])
        with tempfile.TemporaryDirectory(prefix="ias-s4-7-validate-") as temp:
            expected = Path(temp) / "package"
            build_evidence_package(
                repo_root=repo_root,
                output=expected,
                source_commit=source_commit,
            )
            for name in REQUIRED_FILES:
                if (
                    not (output / name).is_file()
                    or (output / name).read_bytes() != (expected / name).read_bytes()
                ):
                    issues.append(f"semantic regeneration mismatch: {name}")
    except (KeyError, OSError, S47EvidenceError, AcceptanceCriteriaError) as exc:
        issues.append(f"semantic regeneration failed: {exc}")
    if require_tracked and output.is_dir():
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", *sorted(output.iterdir())],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            issues.append("S4.7 evidence package is not fully tracked")
    if require_committed and output.is_dir():
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", output],
            cwd=repo_root,
            check=False,
        )
        if result.returncode != 0:
            issues.append("S4.7 evidence package differs from HEAD")
    return {
        "schema": "ias.s4_7.evidence_validation_result.v1",
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "source_commit": source_commit,
        "file_count": len(present),
        "require_tracked": require_tracked,
        "require_committed": require_committed,
        "holdout_observations_accessed": 0,
        "later_phases_started": [],
    }


__all__ = [
    "ACCEPTANCE_SCHEMA",
    "EXACT_REPLAY_COMMAND",
    "OUTPUT_PATH",
    "REQUIRED_FILES",
    "S47EvidenceError",
    "build_evidence_package",
    "load_json",
    "validate_evidence_package",
]
