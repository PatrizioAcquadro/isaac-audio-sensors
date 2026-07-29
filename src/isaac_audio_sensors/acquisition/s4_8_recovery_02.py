"""Preregistration gate for a new unseen S4.8 recovery holdout."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8

AMENDMENT_PATH = Path("configs/s4_8_recovery_amendment_02.v1.json")
AMENDMENT_SCHEMA_PATH = Path("docs/schemas/s4_8_recovery_amendment_02.v1.schema.json")
HOLDOUT_BINDING_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_unseen_holdout_binding.v1.schema.json"
)
AMENDMENT_SPEC_PATH = Path("docs/development/specs/s4_8_recovery_amendment_02.md")

EXPECTED_ARTIFACT_KEYS = {
    "original_s4_8": frozenset(
        {
            "grant",
            "authorization",
            "ledger",
            "journal",
            "recovery_context",
            "derived_terminal_state",
            "terminal_manifest",
            "final_validation",
        }
    ),
    "recovery_amendment_01": frozenset(
        {
            "grant",
            "authorization",
            "ledger",
            "journal",
            "post_consumption_progress",
            "recovery_context",
            "derived_terminal_state",
            "independent_review",
            "terminal_manifest",
            "final_validation",
        }
    ),
}


def _safe_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise s4_8.S48Error(f"invalid amendment_02 path: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise s4_8.S48Error(f"unsafe amendment_02 path: {value!r}")
    return Path(*pure.parts)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def load_amendment(repo_root: Path) -> dict[str, Any]:
    """Load and validate the forward-only preregistration."""

    root = repo_root.resolve()
    amendment = s4_8.load_json(root / AMENDMENT_PATH)
    schema = s4_8.load_json(root / AMENDMENT_SCHEMA_PATH)
    try:
        jsonschema.validate(amendment, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 schema failure: {exc.message}"
        ) from exc
    _validate_scientific_bindings(root, amendment)
    _validate_preliminary_bindings(root, amendment)
    _validate_operator_policy_binding(root, amendment)
    _validate_namespaces(amendment)
    return amendment


def _validate_scientific_bindings(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    preregistration = amendment["scientific_preregistration"]
    bindings = (
        ("producer_source_path", "producer_source_sha256"),
        ("criteria_config_path", "criteria_config_sha256"),
        ("criteria_schema_path", "criteria_schema_sha256"),
        ("criteria_spec_path", "criteria_spec_sha256"),
        ("design_template_path", "design_template_sha256"),
    )
    for path_key, digest_key in bindings:
        path = repo_root / _safe_relative(preregistration[path_key])
        if not path.is_file() or s4_8.sha256_file(path) != preregistration[digest_key]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 binding mismatch: {path_key}"
            )


def _validate_namespaces(amendment: Mapping[str, Any]) -> None:
    historical_paths = {
        _safe_relative(record["path"])
        for run in amendment["prior_terminal_runs"]
        for record in run["artifacts"].values()
    }
    unseen = amendment["unseen_holdout"]
    future = amendment["future_attempt"]
    namespace = _safe_relative(unseen["namespace_root"])
    observation_root = _safe_relative(unseen["observation_root"])
    if any(
        not _is_within(_safe_relative(unseen[key]), namespace)
        for key in (
            "precollection_seal_path",
            "partition_manifest_path",
            "session_manifest_path",
            "holdout_seal_path",
        )
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 holdout paths escape the new namespace"
        )
    consumed_roots = {
        _safe_relative(path) for path in unseen["consumed_observation_roots"]
    }
    if any(_is_within(observation_root, root) for root in consumed_roots):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 observation root reuses consumed data"
        )
    future_paths = {
        _safe_relative(future[key])
        for key in (
            "grant_path",
            "ledger_path",
            "journal_path",
            "derived_input_path",
            "output_path",
            "closeout_path",
            "independent_review_path",
        )
    }
    if (
        len(future_paths) != 7
        or future_paths & historical_paths
        or observation_root in historical_paths
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 future paths overlap terminal history"
        )


def _validate_preliminary_bindings(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    preliminary = amendment["preliminary_readiness"]
    for path_key, digest_key in (
        ("workflow_config_path", "workflow_config_sha256"),
        ("workflow_schema_path", "workflow_schema_sha256"),
        ("workflow_spec_path", "workflow_spec_sha256"),
    ):
        path = repo_root / _safe_relative(preliminary[path_key])
        if (
            not path.is_file()
            or s4_8.sha256_file(path) != preliminary[digest_key]
        ):
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 binding mismatch: {path_key}"
            )


def _validate_operator_policy_binding(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    unseen = amendment["unseen_holdout"]
    for path_key, digest_key in (
        (
            "operator_acquisition_policy_path",
            "operator_acquisition_policy_sha256",
        ),
        (
            "operator_acquisition_policy_schema_path",
            "operator_acquisition_policy_schema_sha256",
        ),
        (
            "operator_acquisition_spec_path",
            "operator_acquisition_spec_sha256",
        ),
    ):
        path = repo_root / _safe_relative(unseen[path_key])
        if not path.is_file() or s4_8.sha256_file(path) != unseen[digest_key]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 operator binding mismatch: {path_key}"
            )
    policy = s4_8.load_json(
        repo_root / _safe_relative(unseen["operator_acquisition_policy_path"])
    )
    schema = s4_8.load_json(
        repo_root
        / _safe_relative(unseen["operator_acquisition_policy_schema_path"])
    )
    try:
        jsonschema.validate(policy, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 operator acquisition policy schema failure: {exc.message}"
        ) from exc
    controls = (
        "operator_authorization_required_per_take",
        "one_take_per_command",
        "automatic_batch_forbidden",
        "all_attempts_retained",
        "scientific_outcomes_must_remain_uninspected",
    )
    if any(
        unseen.get(key) is not True or policy["policy"].get(key) is not True
        for key in controls
    ):
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 operator policy is weakened"
        )


def _preliminary_readiness_state(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> tuple[bool, bool]:
    preliminary = amendment["preliminary_readiness"]
    path = repo_root / _safe_relative(preliminary["readiness_path"])
    if not path.exists():
        return False, False
    report = s4_8.load_json(path)
    passed = (
        report.get("schema") == "ias.s4_8.preliminary_readiness.v1"
        and report.get("status") == preliminary["required_status"]
        and report.get("preliminary_take_count")
        == preliminary["required_take_count"]
        and report.get("all_required_gates_passed") is True
        and report.get("final_protocol_freeze_permitted") is True
        and report.get("final_protocol_frozen") is False
        and report.get("official_acquisition_permitted") is False
        and report.get("grant_creation_authorized") is False
        and report.get("grant_consumption_authorized") is False
        and report.get("holdout_opening_authorized") is False
        and report.get("official_evaluation_authorized") is False
    )
    if not passed:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 preliminary readiness is invalid"
        )
    return True, True


def _validate_terminal_package(
    repo_root: Path,
    *,
    run: Mapping[str, Any],
) -> None:
    artifacts = run["artifacts"]
    package = (
        repo_root / _safe_relative(artifacts["terminal_manifest"]["path"])
    ).parent
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != s4_8.PACKAGE_FILES:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 package drift: {run['run_id']}"
        )
    s4_8._validate_manifest(package)
    final = s4_8.load_json(
        repo_root / _safe_relative(artifacts["final_validation"]["path"])
    )
    if (
        final.get("status") != "failed"
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
        or final.get("scientific_evaluation_state") != run["evaluation_state"]
        or final.get("scientific_evaluation_status") != run["scientific_status"]
    ):
        raise s4_8.S48Error(
            f"S4.8 recovery amendment_02 terminal status drift: {run['run_id']}"
        )
    provenance = s4_8.load_json(package / "provenance.json")
    if provenance.get("source_commit") != run["source_commit"]:
        raise s4_8.S48Error(f"S4.8 recovery amendment_02 source drift: {run['run_id']}")
    if run["failure_gate"] is not None:
        criteria = s4_8.load_json(package / "criteria_results.json")
        if criteria.get("failed_gating_criteria") != [run["failure_gate"]]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 failure drift: {run['run_id']}"
            )


def validate_terminal_history(
    repo_root: Path,
    amendment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Authenticate both terminal runs without loading scientific payloads."""

    root = repo_root.resolve()
    loaded = dict(amendment or load_amendment(root))
    artifact_count = 0
    manifest_hashes: dict[str, str] = {}
    for run in loaded["prior_terminal_runs"]:
        run_id = run["run_id"]
        artifacts = run["artifacts"]
        if frozenset(artifacts) != EXPECTED_ARTIFACT_KEYS[run_id]:
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 artifact set drift: {run_id}"
            )
        grant = s4_8.load_json(root / _safe_relative(artifacts["grant"]["path"]))
        if grant.get("grant_id") != run["grant_id"]:
            raise s4_8.S48Error(f"S4.8 recovery amendment_02 grant drift: {run_id}")
        for name, record in artifacts.items():
            path = root / _safe_relative(record["path"])
            if not path.is_file() or s4_8.sha256_file(path) != record["sha256"]:
                raise s4_8.S48Error(
                    "S4.8 recovery amendment_02 terminal artifact mismatch: "
                    f"{run_id}.{name}"
                )
            artifact_count += 1
        manifest_hashes[run_id] = artifacts["terminal_manifest"]["sha256"]
        _validate_terminal_package(root, run=run)
    return {
        "schema": "ias.s4_8.recovery_amendment_02_terminal_history.v1",
        "status": "passed",
        "terminal_run_count": 2,
        "terminal_statuses": {
            run["run_id"]: run["terminal_status"]
            for run in loaded["prior_terminal_runs"]
        },
        "artifact_count": artifact_count,
        "package_manifest_sha256": manifest_hashes,
        "raw_holdout_read": False,
        "scientific_payload_loaded": False,
    }


def _future_state_paths(amendment: Mapping[str, Any]) -> dict[str, Path]:
    future = amendment["future_attempt"]
    grant = _safe_relative(future["grant_path"])
    return {
        "grant": grant,
        "authorization": grant.with_name(s4_8.AUTHORIZATION_RECORD_NAME),
        "ledger": _safe_relative(future["ledger_path"]),
        "journal": _safe_relative(future["journal_path"]),
        "derived_input": _safe_relative(future["derived_input_path"]),
        "output": _safe_relative(future["output_path"]),
    }


def _require_no_unauthorized_state(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> None:
    for name, relative in _future_state_paths(amendment).items():
        if (repo_root / relative).exists():
            raise s4_8.S48Error(
                f"S4.8 recovery amendment_02 unauthorized future state exists: {name}"
            )


def _require_fix_ancestor(
    repo_root: Path,
    *,
    amendment: Mapping[str, Any],
    source_commit: str,
) -> None:
    fixed = amendment["scientific_preregistration"]["producer_fix_commit"]
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", fixed, source_commit],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise s4_8.S48Error(
            "S4.8 recovery amendment_02 source does not contain producer fix"
        )


def recovery_preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Validate the preregistration while keeping execution at NO-GO."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    history = validate_terminal_history(root, amendment)
    resolved_commit = source_commit or s4_8._git(root, "rev-parse", "HEAD")
    _require_fix_ancestor(
        root,
        amendment=amendment,
        source_commit=resolved_commit,
    )
    _require_no_unauthorized_state(root, amendment)
    unseen = amendment["unseen_holdout"]
    future = amendment["future_attempt"]
    holdout_paths = {
        key: _safe_relative(unseen[key])
        for key in (
            "binding_path",
            "precollection_seal_path",
            "partition_manifest_path",
            "session_manifest_path",
            "holdout_seal_path",
            "observation_root",
        )
    }
    present = {key: (root / path).exists() for key, path in holdout_paths.items()}
    readiness_present, readiness_passed = _preliminary_readiness_state(
        root, amendment
    )
    final_protocol_frozen = (
        amendment["preliminary_readiness"]["final_protocol_status"] == "frozen"
    )
    if any(present.values()) and not (readiness_passed and final_protocol_frozen):
        raise s4_8.S48Error(
            "S4.8 official holdout state exists before preliminary readiness "
            "and final protocol freeze"
        )
    review_present = (
        root / _safe_relative(future["independent_review_path"])
    ).is_file()
    blockers = [
        "preliminary_readiness_not_established",
        "final_official_protocol_not_frozen",
        "new_unseen_holdout_not_collected_or_bound",
        "evaluator_not_bound_to_new_holdout",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    return {
        "schema": "ias.s4_8.recovery_amendment_02_preopen.v1",
        "status": "passed",
        "readiness": "no_go",
        "amendment_id": amendment["amendment_id"],
        "source_commit": resolved_commit,
        "candidate_grant_id": future["grant_id_template"].format(
            source_commit=resolved_commit
        ),
        "blockers": blockers,
        "terminal_history": history,
        "criteria_unchanged": True,
        "readiness_criterion_count": 23,
        "stretch_criterion_count": 6,
        "planned_take_count": 47,
        "preliminary_take_count": 4,
        "preliminary_readiness_present": readiness_present,
        "preliminary_readiness_passed": readiness_passed,
        "final_protocol_frozen": final_protocol_frozen,
        "official_acquisition_permitted": False,
        "leakage_group_count": 15,
        "unseen_holdout_id": unseen["holdout_id"],
        "unseen_holdout_paths_present": present,
        "independent_review_present": review_present,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "evaluation_execution_authorized": False,
        "new_grant_present": False,
        "new_ledger_present": False,
        "holdout_observation_opened": False,
        "content_derived_values_returned": False,
    }


__all__ = [
    "AMENDMENT_PATH",
    "load_amendment",
    "recovery_preopen_validate",
    "validate_terminal_history",
]
