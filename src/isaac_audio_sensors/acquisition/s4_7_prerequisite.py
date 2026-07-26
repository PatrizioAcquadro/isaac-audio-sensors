"""Authentication of the canonical committed S4.7 corrective prerequisite."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CANONICAL_PREREQUISITE = Path(
    "outputs/isaac_audio_sensors/S4/S4.7_corrective_01/holdout_acceptance.json"
)
CANONICAL_PACKAGE = CANONICAL_PREREQUISITE.parent
ACCEPTANCE_SCHEMA = "ias.s4_7.holdout_acceptance_corrective.v2"
EVIDENCE_INDEX_SCHEMA = "ias.s4_7.corrective_evidence_index.v2"
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
        "evidence_index_sha256",
        "source_commit",
        "bound_holdout_id",
        "planned_take_count",
    }
)


class S47PrerequisiteError(ValueError):
    """Raised when the S4.8 prerequisite is not canonical and authenticated."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_s4_7_corrective_prerequisite(
    prerequisite_path: Path,
    *,
    seal_path: Path,
    require_committed: bool = True,
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
    _validate_holdout_binding(repo_root, seal_path.resolve(), acceptance)
    _validate_source_commit(repo_root, acceptance)
    if require_committed:
        _validate_committed_package(repo_root, package)
    return {
        "schema": acceptance["schema"],
        "status": acceptance["status"],
        "path": CANONICAL_PREREQUISITE.as_posix(),
        "sha256": sha256_file(prerequisite_path),
        "seal_file_sha256": acceptance["seal_file_sha256"],
        "seal_payload_sha256": acceptance["seal_payload_sha256"],
        "criteria_config_sha256": acceptance["criteria_config_sha256"],
        "evidence_index_sha256": acceptance["evidence_index_sha256"],
        "source_commit": acceptance["source_commit"],
        "bound_holdout_id": acceptance["bound_holdout_id"],
        "planned_take_count": acceptance["planned_take_count"],
        "package_file_count": len(present),
        "repository_root": repo_root.as_posix(),
        "committed": require_committed,
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
        "corrective_id": "s4_7_corrective_01",
        "evidence_path": CANONICAL_PACKAGE.as_posix(),
        "evidence_index_path": (
            CANONICAL_PACKAGE / "evidence_index.json"
        ).as_posix(),
        "criteria_config_path": (
            "configs/s4_7_holdout_acceptance.corrective_01.v2.json"
        ),
        "criteria_schema_path": (
            "docs/schemas/s4_7_holdout_acceptance.corrective_01.v2.schema.json"
        ),
        "corrective_spec_path": (
            "docs/development/specs/s4_holdout_acceptance_corrective_01.md"
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


def _validate_committed_package(repo_root: Path, package: Path) -> None:
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
    "REQUIRED_PACKAGE_FILES",
    "S47PrerequisiteError",
    "sha256_file",
    "validate_grant_prerequisite_binding",
    "validate_s4_7_corrective_prerequisite",
]
