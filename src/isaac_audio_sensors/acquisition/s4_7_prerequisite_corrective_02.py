"""Semantic authentication of the canonical S4.7 corrective_02 prerequisite."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CANONICAL_PREREQUISITE = Path(
    "outputs/isaac_audio_sensors/S4/S4.7_corrective_02/holdout_acceptance.json"
)
CANONICAL_PACKAGE = CANONICAL_PREREQUISITE.parent
ACCEPTANCE_SCHEMA = "ias.s4_7.holdout_acceptance_corrective.v3"
EVIDENCE_INDEX_SCHEMA = "ias.s4_7.corrective_evidence_index.v3"
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
        "source_commit",
        "evidence_commit",
        "bound_holdout_id",
        "planned_take_count",
    }
)

REPORT_SCHEMAS = {
    "blindness_attestation.json": "ias.s4_7.corrective_blindness_attestation.v3",
    "contract_validation.json": "ias.s4_7.corrective_contract_validation.v3",
    "criteria_register.json": "ias.s4_7.corrective_criteria_register.v3",
    "determinism_report.json": "ias.s4_7.corrective_determinism.v3",
    "fail_closed_matrix.json": "ias.s4_7.corrective_fail_closed_matrix.v3",
    "final_validation.json": "ias.s4_7.corrective_final_validation.v3",
    "freeze_ordering.json": "ias.s4_7.corrective_freeze_ordering.v3",
    "historical_preservation.json": (
        "ias.s4_7.corrective_historical_preservation.v3"
    ),
    "holdout_binding_report.json": "ias.s4_7.corrective_holdout_binding.v3",
    "identity_registry.json": "ias.s4_7.corrective_identity_registry.v3",
    "input_contract_report.json": "ias.s4_7.corrective_input_contract.v3",
    "phase_boundary.json": "ias.s4_7.corrective_phase_boundary.v3",
    "reproduction.json": "ias.s4_7.corrective_reproduction.v3",
    "sim_vs_real_registry.json": (
        "ias.s4_7.corrective_sim_vs_real_registry.v3"
    ),
    "synthetic_evaluation_report.json": (
        "ias.s4_7.corrective_synthetic_evaluation.v3"
    ),
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
REPORT_DETAIL_FIELDS = {
    "blindness_attestation.json": frozenset(
        {
            "holdout_derived_outcomes_accessed",
            "raw_dataset_content_accessed",
            "holdout_access_grant_created",
            "holdout_access_grant_consumed",
            "thresholds_selected_from_holdout",
        }
    ),
    "contract_validation.json": frozenset(
        {
            "criteria_validation_status",
            "thresholds_changed",
            "claimed_envelope_changed",
            "scientific_eligibility_changed",
            "criteria_config_sha256",
            "criteria_schema_sha256",
            "corrective_spec_sha256",
        }
    ),
    "criteria_register.json": frozenset(
        {
            "inherited_config_sha256",
            "criterion_count",
            "readiness_criterion_count",
            "stretch_criterion_count",
            "resolution",
            "criteria",
        }
    ),
    "determinism_report.json": frozenset(
        {
            "run_count",
            "evaluation_reports_identical",
            "randomness_used",
            "wall_clock_input_used",
        }
    ),
    "fail_closed_matrix.json": frozenset(
        {"case_count", "cases", "silent_pass_observed"}
    ),
    "final_validation.json": frozenset(
        {
            "criteria_only_validation_passed",
            "identity_registry_complete",
            "comparison_registry_complete",
            "fail_closed_matrix_passed",
            "deterministic",
            "freeze_ordering_valid",
            "historical_packages_preserved",
            "holdout_binding_valid",
            "readiness_criterion_count",
            "stretch_criterion_count",
        }
    ),
    "freeze_ordering.json": frozenset(
        {
            "baseline_commit",
            "corrective_01_closeout_commit",
            "frozen_at_utc",
            "source_commit",
            "baseline_before_freeze",
            "corrective_01_before_freeze",
            "source_descends_from_corrective_01",
        }
    ),
    "historical_preservation.json": frozenset({"packages"}),
    "holdout_binding_report.json": frozenset(
        {
            "seal_path",
            "partition_manifest_path",
            "partition_manifest_sha256",
            "session_manifest_path",
            "session_manifest_sha256",
            "group_count",
            "scientifically_opened",
            "technical_qa_only",
        }
    ),
    "identity_registry.json": frozenset(
        {
            "take_count",
            "take_ids_sha256",
            "group_count",
            "stratum_counts",
            "raw_microphone_ids",
            "microphone_pair_ids",
        }
    ),
    "input_contract_report.json": frozenset(
        {
            "exact_take_set_required",
            "unique_identity_required",
            "per_take_window_coverage_required",
            "latency_take_count",
            "raw_channel_record_count",
            "tdoa_take_pair_record_count",
            "bearing_sim_real_condition_count",
            "bearing_referenced_take_count",
            "maximum_clip_run_threshold_samples",
            "sustained_clipping_minimum_samples",
            "real_values_derived",
        }
    ),
    "phase_boundary.json": frozenset(
        {
            "holdout_access_grant_created",
            "holdout_access_grant_consumed",
            "s4_8_started",
            "s4_9_started",
            "s5_started",
            "s6_started",
            "push_performed",
            "tag_created",
        }
    ),
    "reproduction.json": frozenset(
        {
            "command",
            "comparison",
            "clean_source_archive",
            "requires_holdout_observations",
        }
    ),
    "sim_vs_real_registry.json": frozenset(
        {
            "comparison_registry",
            "comparison_count",
            "bearing_sim_real_condition_count",
            "bearing_referenced_take_count",
            "payload_may_supply_real",
        }
    ),
    "synthetic_evaluation_report.json": frozenset(
        {
            "fixtures_are_synthetic",
            "conforming_evaluation",
            "violating_evaluation",
            "conforming_fixture_passes",
            "violating_fixture_fails",
        }
    ),
}


class S47PrerequisiteError(ValueError):
    """Raised when the S4.8 prerequisite is not canonical and authenticated."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_s4_7_corrective_02_prerequisite(
    prerequisite_path: Path,
    *,
    seal_path: Path,
    require_committed: bool = True,
    verify_replay: bool = True,
) -> dict[str, Any]:
    """Validate the complete canonical corrective package and return its identity."""

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
        raise S47PrerequisiteError(
            "corrective acceptance fields mismatch: "
            f"expected={sorted(ACCEPTANCE_FIELDS)}, "
            f"found={sorted(acceptance)}"
        )
    _validate_acceptance_constants(acceptance)
    _validate_bound_sources(repo_root, acceptance)
    _validate_evidence_index(package, acceptance)
    _validate_report_semantics(repo_root, package, acceptance)
    _validate_holdout_binding(repo_root, seal_path.resolve(), acceptance)
    _validate_source_commit(repo_root, acceptance)
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
    """Require a grant to bind every security-relevant prerequisite identity."""

    if not isinstance(binding, Mapping) or set(binding) != PREREQUISITE_BINDING_FIELDS:
        found = (
            sorted(binding)
            if isinstance(binding, Mapping)
            else type(binding).__name__
        )
        raise S47PrerequisiteError(
            "grant prerequisite fields mismatch: "
            f"expected={sorted(PREREQUISITE_BINDING_FIELDS)}, found={found}"
        )
    expected = {key: authenticated[key] for key in PREREQUISITE_BINDING_FIELDS}
    if dict(binding) != expected:
        raise S47PrerequisiteError("grant prerequisite identity binding mismatch")


def _validate_acceptance_constants(acceptance: Mapping[str, Any]) -> None:
    expected = {
        "schema": ACCEPTANCE_SCHEMA,
        "status": "passed",
        "corrective_id": "s4_7_corrective_02",
        "evidence_path": CANONICAL_PACKAGE.as_posix(),
        "evidence_index_path": (
            CANONICAL_PACKAGE / "evidence_index.json"
        ).as_posix(),
        "criteria_config_path": (
            "configs/s4_7_holdout_acceptance.corrective_02.v3.json"
        ),
        "criteria_schema_path": (
            "docs/schemas/s4_7_holdout_acceptance.corrective_02.v3.schema.json"
        ),
        "corrective_spec_path": (
            "docs/development/specs/s4_holdout_acceptance_corrective_02.md"
        ),
        "inherited_config_path": "configs/s4_7_holdout_acceptance.v1.json",
        "inherited_spec_path": "docs/development/specs/s4_holdout_acceptance.md",
        "bound_holdout_id": (
            "s4_4_data_expansion_amendment_03_prospective_holdout"
        ),
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
    }
    for field, value in expected.items():
        if acceptance.get(field) != value:
            raise S47PrerequisiteError(
                f"corrective acceptance {field} mismatch: "
                f"expected={value!r}, found={acceptance.get(field)!r}"
            )


def _validate_bound_sources(
    repo_root: Path, acceptance: Mapping[str, Any]
) -> None:
    bindings = (
        ("criteria_config_path", "criteria_config_sha256"),
        ("criteria_schema_path", "criteria_schema_sha256"),
        ("corrective_spec_path", "corrective_spec_sha256"),
        ("inherited_config_path", "inherited_config_sha256"),
        ("inherited_spec_path", "inherited_spec_sha256"),
    )
    for path_field, hash_field in bindings:
        relative = Path(acceptance[path_field])
        path = _repo_file(repo_root, relative)
        if sha256_file(path) != acceptance[hash_field]:
            raise S47PrerequisiteError(f"stale source hash: {relative}")
    config = _load_json(repo_root / acceptance["criteria_config_path"])
    schema = _load_json(repo_root / acceptance["criteria_schema_path"])
    import jsonschema

    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise S47PrerequisiteError(
            f"corrective config schema validation failed: {exc.message}"
        ) from exc
    binding = config.get("holdout_binding")
    if not isinstance(binding, Mapping):
        raise S47PrerequisiteError("corrective config holdout binding missing")
    expected = {
        "bound_holdout_id": acceptance["bound_holdout_id"],
        "seal_path": acceptance["seal_path"],
        "seal_file_sha256": acceptance["seal_file_sha256"],
        "seal_payload_sha256": acceptance["seal_payload_sha256"],
        "planned_take_count": acceptance["planned_take_count"],
    }
    for field, value in expected.items():
        if binding.get(field) != value:
            raise S47PrerequisiteError(
                f"corrective config holdout {field} mismatch"
            )


def _validate_evidence_index(
    package: Path, acceptance: Mapping[str, Any]
) -> None:
    index_path = package / "evidence_index.json"
    if sha256_file(index_path) != acceptance["evidence_index_sha256"]:
        raise S47PrerequisiteError("stale evidence index hash")
    index = _load_json(index_path)
    expected_fields = {
        "schema",
        "status",
        "source_commit",
        "file_count",
        "records",
        "holdout_observations_accessed",
        "later_phases_started",
    }
    if set(index) != expected_fields:
        raise S47PrerequisiteError("evidence index fields mismatch")
    if (
        index["schema"] != EVIDENCE_INDEX_SCHEMA
        or index["status"] != "passed"
        or index["source_commit"] != acceptance["source_commit"]
        or index["file_count"] != len(REQUIRED_PACKAGE_FILES)
        or index["holdout_observations_accessed"] != 0
        or index["later_phases_started"] != []
    ):
        raise S47PrerequisiteError("evidence index identity mismatch")
    records = index["records"]
    if not isinstance(records, list):
        raise S47PrerequisiteError("evidence index records must be a list")
    expected_names = REQUIRED_PACKAGE_FILES - {
        "SHA256SUMS",
        "evidence_index.json",
        "holdout_acceptance.json",
    }
    by_name: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "path",
            "sha256",
            "byte_size",
        }:
            raise S47PrerequisiteError("evidence index record fields mismatch")
        name = record["path"]
        if not isinstance(name, str) or name in by_name:
            raise S47PrerequisiteError("duplicate or invalid evidence index path")
        by_name[name] = record
    if set(by_name) != expected_names:
        raise S47PrerequisiteError("evidence index record set mismatch")
    for name, record in by_name.items():
        path = package / name
        if (
            sha256_file(path) != record["sha256"]
            or path.stat().st_size != record["byte_size"]
        ):
            raise S47PrerequisiteError(f"evidence index mismatch: {name}")


def _validate_report_semantics(
    repo_root: Path,
    package: Path,
    acceptance: Mapping[str, Any],
) -> None:
    for name, expected_schema in REPORT_SCHEMAS.items():
        report = _load_json(package / name)
        if set(report) != REPORT_FIELDS:
            raise S47PrerequisiteError(f"{name} fields mismatch")
        expected_identity = {
            "schema": expected_schema,
            "status": "passed",
            "source_commit": acceptance["source_commit"],
            "bound_holdout_id": acceptance["bound_holdout_id"],
            "seal_file_sha256": acceptance["seal_file_sha256"],
            "seal_payload_sha256": acceptance["seal_payload_sha256"],
            "planned_take_count": 47,
            "holdout_observations_accessed": 0,
            "later_phases_started": [],
        }
        for field, expected in expected_identity.items():
            if report[field] != expected:
                raise S47PrerequisiteError(
                    f"{name} semantic {field} mismatch"
                )
        details = report["details"]
        if (
            not isinstance(details, Mapping)
            or set(details) != REPORT_DETAIL_FIELDS[name]
        ):
            raise S47PrerequisiteError(f"{name} detail fields mismatch")
        _validate_report_details(repo_root, name, details, acceptance)


def _validate_report_details(
    repo_root: Path,
    name: str,
    details: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> None:
    if name == "blindness_attestation.json":
        expected = {
            "holdout_derived_outcomes_accessed": 0,
            "raw_dataset_content_accessed": False,
            "holdout_access_grant_created": False,
            "holdout_access_grant_consumed": False,
            "thresholds_selected_from_holdout": False,
        }
        _require_details(name, details, expected)
    elif name == "contract_validation.json":
        expected = {
            "criteria_validation_status": "passed",
            "thresholds_changed": False,
            "claimed_envelope_changed": False,
            "scientific_eligibility_changed": False,
            "criteria_config_sha256": acceptance["criteria_config_sha256"],
            "criteria_schema_sha256": acceptance["criteria_schema_sha256"],
            "corrective_spec_sha256": acceptance["corrective_spec_sha256"],
        }
        _require_details(name, details, expected)
    elif name == "criteria_register.json":
        _validate_effective_criteria(repo_root, name, details, acceptance)
    elif name == "determinism_report.json":
        _require_details(
            name,
            details,
            {
                "run_count": 2,
                "evaluation_reports_identical": True,
                "randomness_used": False,
                "wall_clock_input_used": False,
            },
        )
    elif name == "fail_closed_matrix.json":
        cases = details["cases"]
        if (
            not isinstance(cases, list)
            or details["case_count"] != len(cases)
            or not cases
            or details["silent_pass_observed"] is not False
        ):
            raise S47PrerequisiteError(f"{name} matrix summary mismatch")
        for case in cases:
            if (
                not isinstance(case, Mapping)
                or set(case) != {"case", "status", "fail_closed", "detail"}
                or case["status"] != "passed"
                or case["fail_closed"] is not True
            ):
                raise S47PrerequisiteError(f"{name} contains non-passing case")
    elif name == "final_validation.json":
        expected = {
            "criteria_only_validation_passed": True,
            "identity_registry_complete": True,
            "comparison_registry_complete": True,
            "fail_closed_matrix_passed": True,
            "deterministic": True,
            "freeze_ordering_valid": True,
            "historical_packages_preserved": True,
            "holdout_binding_valid": True,
            "readiness_criterion_count": 23,
            "stretch_criterion_count": 6,
        }
        _require_details(name, details, expected)
    elif name == "freeze_ordering.json":
        _require_details(
            name,
            details,
            {
                "baseline_commit": (
                    "f2230128fd02294892282b5809abe71092f19013"
                ),
                "corrective_01_closeout_commit": (
                    "6b0e8387a3c04fa4b513ab1bbe8514ef1f6b11d3"
                ),
                "source_commit": acceptance["source_commit"],
                "baseline_before_freeze": True,
                "corrective_01_before_freeze": True,
                "source_descends_from_corrective_01": True,
            },
            allow_extra={"frozen_at_utc"},
        )
        if not isinstance(details["frozen_at_utc"], str):
            raise S47PrerequisiteError(f"{name} frozen_at_utc mismatch")
    elif name == "historical_preservation.json":
        packages = details["packages"]
        expected = {
            "outputs/isaac_audio_sensors/S4/S4.7": (
                16,
                "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53",
            ),
            "outputs/isaac_audio_sensors/S4/S4.7_corrective_01": (
                18,
                "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676",
            ),
        }
        if not isinstance(packages, list) or len(packages) != 2:
            raise S47PrerequisiteError(f"{name} package count mismatch")
        by_path = {}
        for item in packages:
            if not isinstance(item, Mapping) or set(item) != {
                "path",
                "file_count",
                "sha256_manifest_sha256",
                "manifest_valid",
            }:
                raise S47PrerequisiteError(f"{name} package fields mismatch")
            by_path[item["path"]] = item
        if set(by_path) != set(expected):
            raise S47PrerequisiteError(f"{name} package identity mismatch")
        for path, (count, digest) in expected.items():
            item = by_path[path]
            if (
                item["file_count"] != count
                or item["sha256_manifest_sha256"] != digest
                or item["manifest_valid"] is not True
            ):
                raise S47PrerequisiteError(f"{name} preservation mismatch: {path}")
    elif name == "holdout_binding_report.json":
        config = _load_json(repo_root / acceptance["criteria_config_path"])
        binding = config["holdout_binding"]
        expected = {
            field: binding[field]
            for field in REPORT_DETAIL_FIELDS[name]
        }
        _require_details(name, details, expected)
    elif name == "identity_registry.json":
        expected = {
            "take_count": 47,
            "group_count": 15,
            "stratum_counts": {
                "A_controlled_boundary_sweep": 24,
                "B_center_nominal_level": 8,
                "C_center_low_level": 8,
                "D_silence": 3,
                "E_impact_audio_video": 4,
            },
            "raw_microphone_ids": [
                "raw_microphone_0",
                "raw_microphone_1",
                "raw_microphone_2",
                "raw_microphone_3",
            ],
        }
        _require_details(
            name,
            details,
            expected,
            allow_extra={"take_ids_sha256", "microphone_pair_ids"},
        )
        if (
            not _is_sha256(details["take_ids_sha256"])
            or not isinstance(details["microphone_pair_ids"], list)
            or len(details["microphone_pair_ids"]) != 6
            or len(set(details["microphone_pair_ids"])) != 6
        ):
            raise S47PrerequisiteError(f"{name} identity summary mismatch")
    elif name == "input_contract_report.json":
        _require_details(
            name,
            details,
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
        )
    elif name == "phase_boundary.json":
        _require_details(
            name,
            details,
            {field: False for field in REPORT_DETAIL_FIELDS[name]},
        )
    elif name == "reproduction.json":
        _require_details(
            name,
            details,
            {
                "comparison": "byte_for_byte_complete_package",
                "clean_source_archive": True,
                "requires_holdout_observations": False,
            },
            allow_extra={"command"},
        )
        if "replay_s4_7_corrective_02.py" not in details["command"]:
            raise S47PrerequisiteError(f"{name} replay command mismatch")
    elif name == "sim_vs_real_registry.json":
        if (
            details["comparison_count"] != 7
            or not isinstance(details["comparison_registry"], list)
            or len(details["comparison_registry"]) != 7
            or details["bearing_sim_real_condition_count"] != 32
            or details["bearing_referenced_take_count"] != 40
            or details["payload_may_supply_real"] is not False
        ):
            raise S47PrerequisiteError(f"{name} registry mismatch")
    elif name == "synthetic_evaluation_report.json":
        conforming = details["conforming_evaluation"]
        violating = details["violating_evaluation"]
        if (
            details["fixtures_are_synthetic"] is not True
            or details["conforming_fixture_passes"] is not True
            or details["violating_fixture_fails"] is not True
            or not isinstance(conforming, Mapping)
            or conforming.get("status") != "passed"
            or conforming.get("holdout_observations_accessed_by_evaluator") != 0
            or not isinstance(violating, Mapping)
            or violating.get("status") != "failed"
            or violating.get("holdout_observations_accessed_by_evaluator") != 0
        ):
            raise S47PrerequisiteError(f"{name} evaluation status mismatch")


def _validate_effective_criteria(
    repo_root: Path,
    name: str,
    details: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> None:
    criteria = details["criteria"]
    fields = {
        "criterion_id",
        "tier",
        "gating",
        "metric",
        "statistic",
        "comparator",
        "threshold",
        "denominator",
        "effective_semantics",
        "failure_logic",
    }
    if (
        details["criterion_count"] != 29
        or details["readiness_criterion_count"] != 23
        or details["stretch_criterion_count"] != 6
        or details["resolution"] != "corrective_02_effective_semantics"
        or details["inherited_config_sha256"]
        != acceptance["inherited_config_sha256"]
        or not isinstance(criteria, list)
        or len(criteria) != 29
    ):
        raise S47PrerequisiteError(f"{name} count mismatch")
    inherited = _load_json(repo_root / acceptance["inherited_config_path"])
    frozen = {
        item["criterion_id"]: item
        for item in inherited.get("criteria", [])
    }
    if len(frozen) != 29:
        raise S47PrerequisiteError(f"{name} inherited criterion count mismatch")
    seen = set()
    for criterion in criteria:
        if (
            not isinstance(criterion, Mapping)
            or set(criterion) != fields
            or not isinstance(criterion["effective_semantics"], str)
            or not criterion["effective_semantics"]
        ):
            raise S47PrerequisiteError(f"{name} criterion fields mismatch")
        original = frozen.get(criterion["criterion_id"])
        if original is None:
            raise S47PrerequisiteError(f"{name} unknown criterion id")
        for field in (
            "tier",
            "gating",
            "metric",
            "statistic",
            "comparator",
            "threshold",
            "denominator",
            "failure_logic",
        ):
            if criterion[field] != original[field]:
                raise S47PrerequisiteError(
                    f"{name} changed inherited {field}: "
                    f"{criterion['criterion_id']}"
                )
        seen.add(criterion["criterion_id"])
    if len(seen) != 29:
        raise S47PrerequisiteError(f"{name} duplicate criterion id")


def _require_details(
    name: str,
    details: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    allow_extra: set[str] | frozenset[str] = frozenset(),
) -> None:
    if set(details) != set(expected) | set(allow_extra):
        raise S47PrerequisiteError(f"{name} semantic detail set mismatch")
    for field, value in expected.items():
        if details[field] != value:
            raise S47PrerequisiteError(f"{name} semantic {field} mismatch")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_sha256_manifest(package: Path) -> None:
    manifest = package / "SHA256SUMS"
    records: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise S47PrerequisiteError("malformed SHA256SUMS") from exc
        if name in records or len(digest) != 64:
            raise S47PrerequisiteError("duplicate or invalid SHA256SUMS record")
        records[name] = digest
    expected = REQUIRED_PACKAGE_FILES - {"SHA256SUMS"}
    if set(records) != expected:
        raise S47PrerequisiteError("SHA256SUMS record set mismatch")
    for name, digest in records.items():
        if sha256_file(package / name) != digest:
            raise S47PrerequisiteError(f"SHA256SUMS mismatch: {name}")


def _validate_holdout_binding(
    repo_root: Path, seal_path: Path, acceptance: Mapping[str, Any]
) -> None:
    expected_seal = _repo_file(repo_root, Path(acceptance["seal_path"])).resolve()
    if seal_path != expected_seal:
        raise S47PrerequisiteError("prerequisite seal path binding mismatch")
    if sha256_file(seal_path) != acceptance["seal_file_sha256"]:
        raise S47PrerequisiteError("prerequisite seal file hash mismatch")
    seal = _load_json(seal_path)
    if seal.get("seal_payload_sha256") != acceptance["seal_payload_sha256"]:
        raise S47PrerequisiteError("prerequisite seal payload hash mismatch")
    take_ids = seal.get("planned_take_ids")
    if not isinstance(take_ids, list) or len(take_ids) != 47:
        raise S47PrerequisiteError("prerequisite planned take count mismatch")
    if seal.get("scientifically_opened") is not False:
        raise S47PrerequisiteError("prerequisite holdout is not sealed")


def _validate_source_commit(
    repo_root: Path, acceptance: Mapping[str, Any]
) -> None:
    source_commit = acceptance["source_commit"]
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise S47PrerequisiteError("source commit must be a full lowercase SHA-1")
    _git(
        repo_root,
        ["cat-file", "-e", f"{source_commit}^{{commit}}"],
        "source commit does not exist",
    )
    _git(
        repo_root,
        ["merge-base", "--is-ancestor", source_commit, "HEAD"],
        "source commit is not an ancestor of HEAD",
    )
    bindings = (
        ("criteria_config_path", "criteria_config_sha256"),
        ("criteria_schema_path", "criteria_schema_sha256"),
        ("corrective_spec_path", "corrective_spec_sha256"),
        ("inherited_config_path", "inherited_config_sha256"),
        ("inherited_spec_path", "inherited_spec_sha256"),
    )
    for path_field, hash_field in bindings:
        relative = acceptance[path_field]
        result = subprocess.run(
            ["git", "show", f"{source_commit}:{relative}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            result.returncode != 0
            or hashlib.sha256(result.stdout).hexdigest() != acceptance[hash_field]
        ):
            raise S47PrerequisiteError(
                f"source commit blob hash mismatch: {relative}"
            )


def _validate_committed_package(
    repo_root: Path, package: Path, source_commit: str
) -> str:
    relative = package.relative_to(repo_root)
    paths = [relative / name for name in sorted(REQUIRED_PACKAGE_FILES)]
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *paths],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError("corrective package is not fully tracked")
    for args, message in (
        (
            ["diff", "--quiet", "HEAD", "--", relative],
            "corrective package differs from HEAD",
        ),
        (
            ["diff", "--cached", "--quiet", "--", relative],
            "corrective package has staged changes",
        ),
    ):
        _git(repo_root, args, message)
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", relative],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    evidence_commit = result.stdout.strip()
    if result.returncode != 0 or len(evidence_commit) != 40:
        raise S47PrerequisiteError("evidence commit cannot be resolved")
    _git(
        repo_root,
        ["merge-base", "--is-ancestor", source_commit, evidence_commit],
        "evidence commit does not descend from source commit",
    )
    for path in paths:
        committed = subprocess.run(
            ["git", "show", f"{evidence_commit}:{path.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        if (
            committed.returncode != 0
            or committed.stdout != (repo_root / path).read_bytes()
        ):
            raise S47PrerequisiteError(
                f"evidence commit byte mismatch: {path.name}"
            )
    return evidence_commit


def _validate_deterministic_replay(repo_root: Path) -> None:
    script = repo_root / "scripts/replay_s4_7_corrective_02.py"
    if not script.is_file():
        raise S47PrerequisiteError("corrective_02 replay path is missing")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo_root),
            "--canonical",
            CANONICAL_PACKAGE.as_posix(),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise S47PrerequisiteError(
            f"deterministic byte-for-byte replay failed: {detail}"
        )


def _git_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S47PrerequisiteError("prerequisite is not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def _git(repo_root: Path, args: list[str], message: str) -> None:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, check=False, capture_output=True
    )
    if result.returncode != 0:
        raise S47PrerequisiteError(message)


def _repo_file(repo_root: Path, relative: Path) -> Path:
    if relative.is_absolute():
        raise S47PrerequisiteError(f"path must be repository relative: {relative}")
    candidate = (repo_root / relative).resolve()
    if not candidate.is_relative_to(repo_root) or not candidate.is_file():
        raise S47PrerequisiteError(f"missing repository file: {relative}")
    return candidate


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S47PrerequisiteError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S47PrerequisiteError(f"expected JSON object: {path}")
    return value


__all__ = [
    "ACCEPTANCE_FIELDS",
    "ACCEPTANCE_SCHEMA",
    "CANONICAL_PACKAGE",
    "CANONICAL_PREREQUISITE",
    "EVIDENCE_INDEX_SCHEMA",
    "PREREQUISITE_BINDING_FIELDS",
    "REPORT_DETAIL_FIELDS",
    "REPORT_FIELDS",
    "REPORT_SCHEMAS",
    "REQUIRED_PACKAGE_FILES",
    "S47PrerequisiteError",
    "sha256_file",
    "validate_grant_prerequisite_binding",
    "validate_s4_7_corrective_02_prerequisite",
]
