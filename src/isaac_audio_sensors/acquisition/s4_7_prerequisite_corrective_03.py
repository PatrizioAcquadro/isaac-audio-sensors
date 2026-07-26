"""Exact semantic authentication of the canonical S4.7 corrective_03 package."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    CONFIG_PATH,
    SCHEMA_PATH,
    V1_CONFIG_PATH,
    build_identity_registry,
    load_corrective_config,
)

CANONICAL_PREREQUISITE = Path(
    "outputs/isaac_audio_sensors/S4/S4.7_corrective_03/holdout_acceptance.json"
)
CANONICAL_PACKAGE = CANONICAL_PREREQUISITE.parent
ACCEPTANCE_SCHEMA = "ias.s4_7.holdout_acceptance_corrective.v4"
EVIDENCE_INDEX_SCHEMA = "ias.s4_7.corrective_evidence_index.v4"
SPEC_PATH = Path(
    "docs/development/specs/s4_holdout_acceptance_corrective_03.md"
)
V1_SPEC_PATH = Path("docs/development/specs/s4_holdout_acceptance.md")
CORRECTIVE_02_CONFIG_PATH = Path(
    "configs/s4_7_holdout_acceptance.corrective_02.v3.json"
)
REQUIRED_PACKAGE_FILES = frozenset(
    {
        "SHA256SUMS",
        "blindness_attestation.json",
        "contract_validation.json",
        "criteria_register.json",
        "determinism_report.json",
        "evidence_index.json",
        "fail_closed_matrix.json",
        "final_validation.json",
        "freeze_ordering.json",
        "historical_preservation.json",
        "holdout_acceptance.json",
        "holdout_binding_report.json",
        "identity_registry.json",
        "input_contract_report.json",
        "phase_boundary.json",
        "reproduction.json",
        "sim_vs_real_registry.json",
        "synthetic_evaluation_report.json",
    }
)
INDEX_EXCLUSIONS = frozenset(
    {"SHA256SUMS", "evidence_index.json", "holdout_acceptance.json"}
)
REPORT_SCHEMAS = {
    name: f"ias.s4_7.corrective_{suffix}.v4"
    for name, suffix in {
        "blindness_attestation.json": "blindness_attestation",
        "contract_validation.json": "contract_validation",
        "criteria_register.json": "criteria_register",
        "determinism_report.json": "determinism",
        "fail_closed_matrix.json": "fail_closed_matrix",
        "final_validation.json": "final_validation",
        "freeze_ordering.json": "freeze_ordering",
        "historical_preservation.json": "historical_preservation",
        "holdout_binding_report.json": "holdout_binding",
        "identity_registry.json": "identity_registry",
        "input_contract_report.json": "input_contract",
        "phase_boundary.json": "phase_boundary",
        "reproduction.json": "reproduction",
        "sim_vs_real_registry.json": "sim_vs_real_registry",
        "synthetic_evaluation_report.json": "synthetic_evaluation",
    }.items()
}
REPORT_FIELDS = frozenset(
    {
        "schema",
        "status",
        "source_commit",
        "bound_holdout_id",
        "seal_file_sha256",
        "seal_payload_sha256",
        "planned_take_count",
        "holdout_observations_accessed",
        "later_phases_started",
        "details",
    }
)
ACCEPTANCE_FIELDS = frozenset(
    {
        "schema",
        "status",
        "corrective_id",
        "evidence_path",
        "evidence_index_path",
        "evidence_index_sha256",
        "criteria_config_path",
        "criteria_config_sha256",
        "criteria_schema_path",
        "criteria_schema_sha256",
        "corrective_spec_path",
        "corrective_spec_sha256",
        "inherited_config_path",
        "inherited_config_sha256",
        "inherited_spec_path",
        "inherited_spec_sha256",
        "source_commit",
        "bound_holdout_id",
        "seal_path",
        "seal_file_sha256",
        "seal_payload_sha256",
        "planned_take_count",
        "readiness_criterion_count",
        "stretch_criterion_count",
        "readiness_passed",
        "holdout_observations_accessed",
        "authorizes_holdout_opening",
        "grant_still_required_for_s4_8",
        "evidence_commit_policy",
        "deterministic_replay_required",
        "scientific_semantics_sha256",
    }
)
PREREQUISITE_BINDING_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "schema",
        "status",
        "seal_file_sha256",
        "seal_payload_sha256",
        "criteria_config_sha256",
        "criteria_schema_sha256",
        "corrective_spec_sha256",
        "evidence_index_sha256",
        "package_manifest_sha256",
        "scientific_semantics_sha256",
        "source_commit",
        "evidence_commit",
        "bound_holdout_id",
        "planned_take_count",
    }
)
SOURCE_BOUND_FILES = (
    CONFIG_PATH,
    SCHEMA_PATH,
    SPEC_PATH,
    Path(
        "src/isaac_audio_sensors/core/acceptance_criteria_corrective_03.py"
    ),
    Path(
        "src/isaac_audio_sensors/acquisition/s4_7_corrective_03.py"
    ),
    Path("src/isaac_audio_sensors/acquisition/s4_4.py"),
    Path("scripts/generate_s4_7_corrective_03_evidence.py"),
    Path("scripts/run_s4_7_corrective_03_evaluation.py"),
    Path("scripts/validate_s4_7_corrective_03.py"),
    Path("tests/test_s4_7_corrective_03_acceptance.py"),
    Path("tests/test_s4_7_corrective_03_contract.py"),
    Path("tests/test_s4_7_corrective_03_evidence.py"),
    Path("tests/test_s4_8_corrective_03_interlock.py"),
)


class S47PrerequisiteError(ValueError):
    """Raised when the S4.8 prerequisite is not canonical and authenticated."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def expected_effective_criteria(repo_root: Path) -> list[dict[str, Any]]:
    """Generate the only permitted effective scientific criteria register."""

    root = repo_root.resolve()
    config = load_corrective_config(root)
    v1 = _load_json(root / V1_CONFIG_PATH)
    semantics = config["scientific_semantics_authentication"]
    output: list[dict[str, Any]] = []
    for criterion in v1["criteria"]:
        criterion_id = criterion["criterion_id"]
        if criterion_id == "within_cell_bearing_circular_range_stratum_a":
            resolution = semantics["repeatability_resolution"]
        elif criterion_id.startswith("sector_accuracy_stratum_b"):
            resolution = semantics["sector_resolution"]
        elif criterion_id.startswith("bearing_") or criterion_id.startswith(
            "sim_adjusted_bearing_"
        ):
            resolution = semantics["bearing_resolution"]
        else:
            resolution = semantics["default_resolution"]
        output.append(
            {
                "criterion_id": criterion_id,
                "tier": criterion["tier"],
                "gating": criterion["gating"],
                "metric": criterion["metric"],
                "statistic": criterion["statistic"],
                "comparator": criterion["comparator"],
                "threshold": criterion["threshold"],
                "denominator": criterion["denominator"],
                "strata": criterion["strata"],
                "sample_kind": criterion["sample_kind"],
                "observable": criterion["observable"],
                "failure_logic": criterion["failure_logic"],
                "scientific_contract": criterion["metric_contract"],
                "resolution": resolution,
            }
        )
    return output


def expected_scientific_semantics_sha256(repo_root: Path) -> str:
    return canonical_sha256(expected_effective_criteria(repo_root))


def validate_effective_criteria(value: Any, repo_root: Path) -> None:
    """Reject any effective register other than the generated exact contract."""

    if value != expected_effective_criteria(repo_root):
        raise S47PrerequisiteError(
            "criteria register scientific semantics mismatch"
        )


def validate_s4_7_corrective_03_prerequisite(
    prerequisite_path: Path,
    *,
    seal_path: Path,
    require_committed: bool = True,
    verify_replay: bool = True,
) -> dict[str, Any]:
    """Authenticate bytes, reports, scientific semantics, and source replay."""

    prerequisite_path = prerequisite_path.resolve()
    repo_root = _git_root(prerequisite_path)
    expected_path = (repo_root / CANONICAL_PREREQUISITE).resolve()
    if prerequisite_path != expected_path:
        raise S47PrerequisiteError(
            f"prerequisite path must be canonical: {CANONICAL_PREREQUISITE}"
        )
    package = prerequisite_path.parent
    present = {path.name for path in package.iterdir()} if package.is_dir() else set()
    if present != REQUIRED_PACKAGE_FILES:
        raise S47PrerequisiteError(
            "corrective package file set mismatch: "
            f"missing={sorted(REQUIRED_PACKAGE_FILES - present)}, "
            f"extra={sorted(present - REQUIRED_PACKAGE_FILES)}"
        )
    _validate_sha256_manifest(package)
    acceptance = _load_json(prerequisite_path)
    if set(acceptance) != ACCEPTANCE_FIELDS:
        raise S47PrerequisiteError("corrective acceptance fields mismatch")
    _validate_acceptance(repo_root, acceptance)
    _validate_evidence_index(package, acceptance)
    _validate_reports(repo_root, package, acceptance)
    _validate_holdout_binding(repo_root, seal_path.resolve(), acceptance)
    _validate_source_commit(repo_root, acceptance["source_commit"])
    evidence_commit = ""
    if require_committed:
        evidence_commit = _validate_committed_package(
            repo_root, package, acceptance["source_commit"]
        )
    if verify_replay:
        _validate_deterministic_replay(repo_root)
    return {
        "schema": acceptance["schema"],
        "status": acceptance["status"],
        "path": CANONICAL_PREREQUISITE.as_posix(),
        "sha256": sha256_file(prerequisite_path),
        "seal_file_sha256": acceptance["seal_file_sha256"],
        "seal_payload_sha256": acceptance["seal_payload_sha256"],
        "criteria_config_sha256": acceptance["criteria_config_sha256"],
        "criteria_schema_sha256": acceptance["criteria_schema_sha256"],
        "corrective_spec_sha256": acceptance["corrective_spec_sha256"],
        "evidence_index_sha256": acceptance["evidence_index_sha256"],
        "package_manifest_sha256": sha256_file(package / "SHA256SUMS"),
        "scientific_semantics_sha256": acceptance[
            "scientific_semantics_sha256"
        ],
        "source_commit": acceptance["source_commit"],
        "evidence_commit": evidence_commit,
        "bound_holdout_id": acceptance["bound_holdout_id"],
        "planned_take_count": acceptance["planned_take_count"],
        "package_file_count": len(present),
        "repository_root": repo_root.as_posix(),
        "committed": require_committed,
        "deterministic_replay_verified": verify_replay,
    }


def validate_grant_prerequisite_binding(
    binding: Any, authenticated: Mapping[str, Any]
) -> None:
    """Require a grant to bind the complete corrective_03 identity."""

    if not isinstance(binding, Mapping) or set(binding) != PREREQUISITE_BINDING_FIELDS:
        raise S47PrerequisiteError("grant prerequisite fields mismatch")
    expected = {key: authenticated[key] for key in PREREQUISITE_BINDING_FIELDS}
    if dict(binding) != expected:
        raise S47PrerequisiteError("grant prerequisite identity binding mismatch")


def _validate_acceptance(
    repo_root: Path, acceptance: Mapping[str, Any]
) -> None:
    config = load_corrective_config(repo_root)
    c2 = _load_json(repo_root / CORRECTIVE_02_CONFIG_PATH)
    expected = {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "passed",
        "corrective_id": "s4_7_corrective_03",
        "evidence_path": CANONICAL_PACKAGE.as_posix(),
        "evidence_index_path": (
            CANONICAL_PACKAGE / "evidence_index.json"
        ).as_posix(),
        "criteria_config_path": CONFIG_PATH.as_posix(),
        "criteria_config_sha256": sha256_file(repo_root / CONFIG_PATH),
        "criteria_schema_path": SCHEMA_PATH.as_posix(),
        "criteria_schema_sha256": sha256_file(repo_root / SCHEMA_PATH),
        "corrective_spec_path": SPEC_PATH.as_posix(),
        "corrective_spec_sha256": sha256_file(repo_root / SPEC_PATH),
        "inherited_config_path": V1_CONFIG_PATH.as_posix(),
        "inherited_config_sha256": sha256_file(repo_root / V1_CONFIG_PATH),
        "inherited_spec_path": V1_SPEC_PATH.as_posix(),
        "inherited_spec_sha256": sha256_file(repo_root / V1_SPEC_PATH),
        "bound_holdout_id": c2["holdout_binding"]["bound_holdout_id"],
        "seal_path": c2["holdout_binding"]["seal_path"],
        "seal_file_sha256": c2["holdout_binding"]["seal_file_sha256"],
        "seal_payload_sha256": c2["holdout_binding"]["seal_payload_sha256"],
        "planned_take_count": 47,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "readiness_passed": True,
        "holdout_observations_accessed": 0,
        "authorizes_holdout_opening": False,
        "grant_still_required_for_s4_8": True,
        "evidence_commit_policy": (
            "derived_from_git_commit_containing_exact_package_bytes"
        ),
        "deterministic_replay_required": True,
        "scientific_semantics_sha256": expected_scientific_semantics_sha256(
            repo_root
        ),
    }
    for key, value in expected.items():
        if acceptance.get(key) != value:
            raise S47PrerequisiteError(
                f"corrective acceptance {key} mismatch"
            )
    if acceptance["source_commit"] != config.get(
        "source_commit", acceptance["source_commit"]
    ):
        raise S47PrerequisiteError("corrective acceptance source commit mismatch")


def _validate_reports(
    repo_root: Path, package: Path, acceptance: Mapping[str, Any]
) -> None:
    reports: dict[str, dict[str, Any]] = {}
    for name, schema in REPORT_SCHEMAS.items():
        report = _load_json(package / name)
        reports[name] = report
        if set(report) != REPORT_FIELDS:
            raise S47PrerequisiteError(f"{name} semantic fields mismatch")
        expected_common = {
            "schema": schema,
            "status": "passed",
            "source_commit": acceptance["source_commit"],
            "bound_holdout_id": acceptance["bound_holdout_id"],
            "seal_file_sha256": acceptance["seal_file_sha256"],
            "seal_payload_sha256": acceptance["seal_payload_sha256"],
            "planned_take_count": 47,
            "holdout_observations_accessed": 0,
            "later_phases_started": [],
        }
        for key, value in expected_common.items():
            if report.get(key) != value:
                raise S47PrerequisiteError(
                    f"{name} semantic {key} mismatch"
                )
        if not isinstance(report["details"], Mapping):
            raise S47PrerequisiteError(f"{name} details must be an object")

    register = reports["criteria_register.json"]["details"]
    expected_criteria = expected_effective_criteria(repo_root)
    expected_register = {
        "register_schema": (
            "ias.s4_7.effective_criteria_register.v4"
        ),
        "resolution": "corrective_03_exact_machine_readable_semantics",
        "inherited_config_sha256": sha256_file(repo_root / V1_CONFIG_PATH),
        "criterion_count": 29,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "scientific_semantics_sha256": canonical_sha256(expected_criteria),
        "criteria": expected_criteria,
    }
    if register != expected_register:
        raise S47PrerequisiteError(
            "criteria register scientific semantics mismatch"
        )
    validate_effective_criteria(register["criteria"], repo_root)
    if any("effective_semantics" in item for item in register["criteria"]):
        raise S47PrerequisiteError("arbitrary effective_semantics is forbidden")

    contract = reports["contract_validation.json"]["details"]
    expected_contract = {
        "criteria_validation_status": "passed",
        "thresholds_changed": False,
        "claimed_envelope_changed": False,
        "scientific_eligibility_changed": False,
        "criteria_config_sha256": acceptance["criteria_config_sha256"],
        "criteria_schema_sha256": acceptance["criteria_schema_sha256"],
        "corrective_spec_sha256": acceptance["corrective_spec_sha256"],
        "scientific_semantics_sha256": acceptance[
            "scientific_semantics_sha256"
        ],
    }
    if contract != expected_contract:
        raise S47PrerequisiteError("contract validation semantics mismatch")
    blindness = reports["blindness_attestation.json"]["details"]
    if blindness != {
        "holdout_derived_outcomes_accessed": 0,
        "raw_dataset_content_accessed": False,
        "holdout_access_grant_created": False,
        "holdout_access_grant_consumed": False,
        "thresholds_selected_from_holdout": False,
    }:
        raise S47PrerequisiteError("blindness semantics mismatch")
    phase = reports["phase_boundary.json"]["details"]
    if phase != {
        "holdout_access_grant_created": False,
        "holdout_access_grant_consumed": False,
        "s4_8_started": False,
        "s4_9_started": False,
        "s5_started": False,
        "s6_started": False,
        "push_performed": False,
        "tag_created": False,
    }:
        raise S47PrerequisiteError("phase-boundary semantics mismatch")
    determinism = reports["determinism_report.json"]["details"]
    if determinism != {
        "run_count": 2,
        "evaluation_reports_identical": True,
        "scientific_semantics_identical": True,
        "randomness_used": False,
        "wall_clock_input_used": False,
    }:
        raise S47PrerequisiteError("determinism semantics mismatch")
    matrix = reports["fail_closed_matrix.json"]["details"]
    if (
        not isinstance(matrix.get("cases"), list)
        or matrix.get("case_count") != len(matrix["cases"])
        or matrix.get("silent_pass_observed") is not False
        or not all(item.get("status") == "passed" for item in matrix["cases"])
    ):
        raise S47PrerequisiteError("fail-closed matrix semantics mismatch")
    final = reports["final_validation.json"]["details"]
    required_true = {
        "criteria_only_validation_passed",
        "identity_registry_complete",
        "comparison_registry_complete",
        "fail_closed_matrix_passed",
        "semantic_bypass_regression_failed_closed",
        "exact_scientific_semantics_authenticated",
        "deterministic",
        "freeze_ordering_valid",
        "historical_packages_preserved",
        "holdout_binding_valid",
    }
    if (
        set(final)
        != required_true
        | {"readiness_criterion_count", "stretch_criterion_count"}
        or not all(final[key] is True for key in required_true)
        or final["readiness_criterion_count"] != 23
        or final["stretch_criterion_count"] != 6
    ):
        raise S47PrerequisiteError("final validation semantics mismatch")
    reproduction = reports["reproduction.json"]["details"]
    if reproduction != {
        "command": (
            "python3 scripts/replay_s4_7_corrective_03.py --canonical "
            "outputs/isaac_audio_sensors/S4/S4.7_corrective_03"
        ),
        "comparison": "byte_for_byte_and_exact_scientific_semantics",
        "clean_source_archive": True,
        "requires_holdout_observations": False,
    }:
        raise S47PrerequisiteError("reproduction semantics mismatch")
    c2 = _load_json(repo_root / CORRECTIVE_02_CONFIG_PATH)
    preservation = reports["historical_preservation.json"]["details"]
    if preservation != {
        "packages": [
            {
                "path": "outputs/isaac_audio_sensors/S4/S4.7",
                "file_count": 16,
                "sha256_manifest_sha256": (
                    "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53"
                ),
                "manifest_valid": True,
            },
            {
                "path": "outputs/isaac_audio_sensors/S4/S4.7_corrective_01",
                "file_count": 18,
                "sha256_manifest_sha256": (
                    "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676"
                ),
                "manifest_valid": True,
            },
            {
                "path": "outputs/isaac_audio_sensors/S4/S4.7_corrective_02",
                "file_count": 18,
                "sha256_manifest_sha256": (
                    "79ce288bd60c38b25b611ce7921c5dcbb9462427dba2be13e71fbacc86f1b6a1"
                ),
                "manifest_valid": True,
            },
        ]
    }:
        raise S47PrerequisiteError("historical preservation semantics mismatch")
    holdout = reports["holdout_binding_report.json"]["details"]
    if holdout != {
        key: c2["holdout_binding"][key]
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
    }:
        raise S47PrerequisiteError("holdout binding report semantics mismatch")
    registry = build_identity_registry(repo_root)
    stratum_counts: dict[str, int] = {}
    for identity in registry.values():
        stratum_counts[identity.stratum_id] = (
            stratum_counts.get(identity.stratum_id, 0) + 1
        )
    identity = reports["identity_registry.json"]["details"]
    if identity != {
        "take_count": 47,
        "take_ids_sha256": canonical_sha256(sorted(registry)),
        "group_count": 15,
        "stratum_counts": dict(sorted(stratum_counts.items())),
        "raw_microphone_ids": c2["identity_contract"]["raw_microphone_ids"],
        "microphone_pair_ids": c2["identity_contract"]["microphone_pair_ids"],
    }:
        raise S47PrerequisiteError("identity registry semantics mismatch")
    input_contract = reports["input_contract_report.json"]["details"]
    if input_contract != {
        "exact_take_set_required": True,
        "unique_identity_required": True,
        "exact_bearing_window_identity_required": True,
        "bearing_window_record_count": 5088,
        "latency_take_count": 47,
        "raw_channel_record_count": 188,
        "tdoa_take_pair_record_count": 144,
        "bearing_sim_real_condition_count": 32,
        "maximum_clip_run_threshold_samples": 8,
        "sustained_clipping_minimum_samples": 4000,
        "real_values_derived_from_exact_windows": True,
    }:
        raise S47PrerequisiteError("input contract report semantics mismatch")
    freeze = reports["freeze_ordering.json"]["details"]
    if freeze != {
        "baseline_commit": "f2230128fd02294892282b5809abe71092f19013",
        "corrective_01_closeout_commit": (
            "6b0e8387a3c04fa4b513ab1bbe8514ef1f6b11d3"
        ),
        "corrective_02_closeout_commit": (
            "ca6c2f01316cd87c4a9835ccafe8eeb85f8b0804"
        ),
        "source_commit": acceptance["source_commit"],
        "baseline_ancestry_valid": True,
        "corrective_01_ancestry_valid": True,
        "corrective_02_ancestry_valid": True,
    }:
        raise S47PrerequisiteError("freeze ordering semantics mismatch")
    sim_registry = reports["sim_vs_real_registry.json"]["details"]
    if sim_registry != {
        "comparison_registry": c2["sim_vs_real"]["comparison_registry"],
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
    }:
        raise S47PrerequisiteError("sim-real registry semantics mismatch")
    synthetic = reports["synthetic_evaluation_report.json"]["details"]
    conforming = synthetic.get("conforming_evaluation", {})
    bypass = synthetic.get("semantic_bypass_evaluation", {})
    if (
        synthetic.get("fixtures_are_synthetic") is not True
        or synthetic.get("conforming_fixture_passes") is not True
        or synthetic.get("semantic_bypass_fails") is not True
        or conforming.get("schema") != "ias.s4_7.criteria_evaluation_result.v4"
        or conforming.get("status") != "passed"
        or bypass.get("schema") != "ias.s4_7.criteria_evaluation_result.v4"
        or bypass.get("status") != "failed"
        or synthetic.get("incorrect_corrective_02_b_median_error_deg") != 4.5
        or synthetic.get("incorrect_corrective_02_b_sector_accuracy") != 1.0
        or synthetic.get("frozen_b_median_error_deg") != 19.5
        or synthetic.get("frozen_b_sector_accuracy") != 0.5
    ):
        raise S47PrerequisiteError("synthetic evaluation semantics mismatch")


def _validate_sha256_manifest(package: Path) -> None:
    lines = (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    records: dict[str, str] = {}
    for line in lines:
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise S47PrerequisiteError("invalid SHA256SUMS line") from exc
        if name in records or name == "SHA256SUMS":
            raise S47PrerequisiteError("invalid SHA256SUMS identity set")
        records[name] = digest
    expected = REQUIRED_PACKAGE_FILES - {"SHA256SUMS"}
    if set(records) != expected:
        raise S47PrerequisiteError("SHA256SUMS file set mismatch")
    for name, digest in records.items():
        if sha256_file(package / name) != digest:
            raise S47PrerequisiteError(f"SHA256SUMS mismatch: {name}")


def _validate_evidence_index(
    package: Path, acceptance: Mapping[str, Any]
) -> None:
    index = _load_json(package / "evidence_index.json")
    if (
        index.get("schema") != EVIDENCE_INDEX_SCHEMA
        or index.get("status") != "passed"
        or index.get("source_commit") != acceptance["source_commit"]
        or index.get("file_count") != 18
        or index.get("holdout_observations_accessed") != 0
        or index.get("later_phases_started") != []
    ):
        raise S47PrerequisiteError("evidence index semantics mismatch")
    expected_names = REQUIRED_PACKAGE_FILES - INDEX_EXCLUSIONS
    records = index.get("records")
    if not isinstance(records, list) or {
        item.get("path") for item in records if isinstance(item, Mapping)
    } != expected_names:
        raise S47PrerequisiteError("evidence index record identity mismatch")
    expected_records = [
        {
            "path": name,
            "sha256": sha256_file(package / name),
            "byte_size": (package / name).stat().st_size,
        }
        for name in sorted(expected_names)
    ]
    if records != expected_records:
        raise S47PrerequisiteError("evidence index record mismatch")
    if sha256_file(package / "evidence_index.json") != acceptance[
        "evidence_index_sha256"
    ]:
        raise S47PrerequisiteError("evidence index hash mismatch")


def _validate_holdout_binding(
    repo_root: Path, seal_path: Path, acceptance: Mapping[str, Any]
) -> None:
    expected_path = (repo_root / acceptance["seal_path"]).resolve()
    if seal_path != expected_path:
        raise S47PrerequisiteError("prerequisite seal path binding mismatch")
    if sha256_file(seal_path) != acceptance["seal_file_sha256"]:
        raise S47PrerequisiteError("prerequisite seal file hash mismatch")
    seal = _load_json(seal_path)
    if seal.get("seal_payload_sha256") != acceptance["seal_payload_sha256"]:
        raise S47PrerequisiteError("prerequisite seal payload hash mismatch")
    if seal.get("scientifically_opened") is not False:
        raise S47PrerequisiteError("prerequisite holdout is not sealed")


def _validate_source_commit(repo_root: Path, source_commit: str) -> None:
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise S47PrerequisiteError("source commit must be a full lowercase SHA-1")
    _git(repo_root, "cat-file", "-e", f"{source_commit}^{{commit}}")
    for relative in SOURCE_BOUND_FILES:
        worktree = repo_root / relative
        if not worktree.is_file():
            raise S47PrerequisiteError(f"source-bound file missing: {relative}")
        blob = _git_bytes(repo_root, "show", f"{source_commit}:{relative.as_posix()}")
        if hashlib.sha256(blob).hexdigest() != sha256_file(worktree):
            raise S47PrerequisiteError(
                f"source-bound file differs from source commit: {relative}"
            )


def _validate_committed_package(
    repo_root: Path, package: Path, source_commit: str
) -> str:
    paths = [package / name for name in sorted(REQUIRED_PACKAGE_FILES)]
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *paths],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError("corrective package is not fully tracked")
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *paths],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError("corrective package differs from HEAD")
    evidence_commit = _git(
        repo_root,
        "log",
        "-1",
        "--format=%H",
        "--",
        CANONICAL_PACKAGE.as_posix(),
    )
    _git(repo_root, "merge-base", "--is-ancestor", source_commit, evidence_commit)
    return evidence_commit


def _validate_deterministic_replay(repo_root: Path) -> None:
    script = repo_root / "scripts/replay_s4_7_corrective_03.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--canonical",
            str(repo_root / CANONICAL_PACKAGE),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError(
            "corrective_03 deterministic replay failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError(f"git {' '.join(args)} failed")
    return result.stdout


def _git_root(path: Path) -> Path:
    start = path if path.is_dir() else path.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError(
            "prerequisite is not inside a Git repository"
        )
    return Path(result.stdout.strip()).resolve()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S47PrerequisiteError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise S47PrerequisiteError(f"expected JSON object: {path}")
    return value


__all__ = [
    "ACCEPTANCE_SCHEMA",
    "CANONICAL_PACKAGE",
    "CANONICAL_PREREQUISITE",
    "EVIDENCE_INDEX_SCHEMA",
    "PREREQUISITE_BINDING_FIELDS",
    "REPORT_SCHEMAS",
    "REQUIRED_PACKAGE_FILES",
    "SOURCE_BOUND_FILES",
    "S47PrerequisiteError",
    "canonical_sha256",
    "expected_effective_criteria",
    "expected_scientific_semantics_sha256",
    "sha256_file",
    "validate_grant_prerequisite_binding",
    "validate_effective_criteria",
    "validate_s4_7_corrective_03_prerequisite",
]
