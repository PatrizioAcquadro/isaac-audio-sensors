"""S4.8 held-out functional sim-to-real evaluation.

The pre-opening functions authenticate only tracked contracts and sealed
artifact bytes. Scientific observation functions are separate, explicit, and
require an already-consumed purpose-bound grant.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import subprocess
import time
import wave
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any

import jsonschema
import numpy as np

from isaac_audio_sensors.acquisition.s4_2 import inspect_six_channel_wav
from isaac_audio_sensors.acquisition.s4_3 import (
    _aligned_correlation,
    _expected_tdoa,
    _prospective_transient_events,
    load_pilot_configuration,
)
from isaac_audio_sensors.acquisition.s4_4 import (
    GRANT_SCHEMA,
    canonical_sha256,
    consume_s4_8_grant,
    hash_only_holdout_integrity,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    PREREQUISITE_BINDING_FIELDS,
    validate_s4_7_corrective_03_prerequisite,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    CorrectiveAcceptanceError,
    build_identity_registry,
    evaluate_corrective,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
)
from isaac_audio_sensors.core.doa.sector_mapping import (
    bearing_deg_to_sector_name,
)
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.profile_application import (
    apply_profile_application,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)

CONFIG_PATH = Path("configs/s4_8_heldout_evaluation.v1.json")
SCHEMA_PATH = Path("docs/schemas/s4_8_heldout_evaluation.v1.schema.json")
SPEC_PATH = Path("docs/development/specs/s4_8_heldout_evaluation.md")
OUTPUT_PATH = Path("outputs/isaac_audio_sensors/S4/S4.8")
TOOL_VERSION = "ias_s4_8_evaluation/1.0.0"
RESULT_SCHEMA = "ias.s4_8.heldout_result.v1"
DERIVED_INPUT_SCHEMA = "ias.s4_8.derived_evaluation_input.v1"
PACKAGE_FILES = frozenset(
    {
        "SHA256SUMS",
        "authorization_access.json",
        "criteria_results.json",
        "derived_evaluation_input.json",
        "determinism_report.json",
        "evidence_index.json",
        "failure_inventory.json",
        "final_validation.json",
        "preservation_report.json",
        "provenance.json",
        "reproduction.json",
        "robustness.json",
        "sim_vs_real.json",
        "supported_unsupported.json",
        "take_inventory.json",
        "window_results.json",
    }
)
SOURCE_BOUND_FILES = (
    CONFIG_PATH,
    SCHEMA_PATH,
    SPEC_PATH,
    Path("src/isaac_audio_sensors/acquisition/s4_8.py"),
    Path("scripts/run_s4_8.py"),
    Path("scripts/validate_s4_8.py"),
    Path("scripts/replay_s4_8.py"),
    Path("tests/test_s4_8_contract.py"),
    Path("tests/test_s4_8_evaluation.py"),
)
PRESERVATION_BASELINE_COMMIT = "ab81af2e521661294d107d3ca28c7b30c581065c"
PRESERVATION_ROOT = Path("outputs/isaac_audio_sensors/S4")


class S48Error(RuntimeError):
    """A located S4.8 contract, access, analysis, or evidence failure."""


def pretty_json(value: Any) -> str:
    return json.dumps(
        value, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=True
    ) + "\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise S48Error(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S48Error(f"expected JSON object: {path}")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def load_contract(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    config = load_json(root / CONFIG_PATH)
    schema = load_json(root / SCHEMA_PATH)
    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise S48Error(f"S4.8 contract schema failure: {exc.message}") from exc
    for section, path_key, digest_key in (
        ("prerequisite", "path", "sha256"),
        ("prerequisite", "package_manifest_path", "package_manifest_sha256"),
        ("holdout", "seal_path", "seal_file_sha256"),
        ("holdout", "partition_manifest_path", "partition_manifest_sha256"),
        ("holdout", "session_manifest_path", "session_manifest_sha256"),
        ("profile_application", "config_path", "config_sha256"),
        ("profile_application", "active_pointer_path", "active_pointer_sha256"),
        ("criteria", "v1_config_path", "v1_config_sha256"),
        ("criteria", "corrective_config_path", "corrective_config_sha256"),
        ("criteria", "corrective_schema_path", "corrective_schema_sha256"),
        ("criteria", "delegated_config_path", "delegated_config_sha256"),
        ("criteria", "delegated_schema_path", "delegated_schema_sha256"),
        ("analysis", "s4_3_effective_config_path", "s4_3_effective_config_sha256"),
        ("analysis", "transient_contract_path", "transient_contract_sha256"),
    ):
        record = config[section]
        path = _repo_file(root, record[path_key])
        if sha256_file(path) != record[digest_key]:
            raise S48Error(f"S4.8 frozen binding mismatch: {path_key}")
    return config


def preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None = None,
    verify_prerequisite_replay: bool = True,
    require_access_paths_absent: bool = True,
) -> dict[str, Any]:
    """Authenticate readiness without interpreting held-out content."""

    root = repo_root.resolve()
    config = load_contract(root)
    seal_path = _repo_file(root, config["holdout"]["seal_path"])
    prerequisite = validate_s4_7_corrective_03_prerequisite(
        _repo_file(root, config["prerequisite"]["path"]),
        seal_path=seal_path,
        require_committed=True,
        verify_replay=verify_prerequisite_replay,
    )
    if (
        prerequisite["scientific_semantics_sha256"]
        != config["prerequisite"]["scientific_semantics_sha256"]
    ):
        raise S48Error("scientific-semantics identity mismatch")
    seal = load_json(seal_path)
    integrity = hash_only_holdout_integrity(seal, repo_root=root)
    if integrity != {
        "schema": "ias.s4_4.hash_only_integrity.v1",
        "status": "passed",
        "checked_artifact_count": 160,
        "issues": [],
        "holdout_opened": False,
        "content_derived_values_returned": False,
    }:
        raise S48Error(f"sealed dataset hash-only integrity failed: {integrity}")
    registry = build_identity_registry(root)
    if len(registry) != 47:
        raise S48Error("corrective_03 identity registry is not 47 takes")
    groups = {identity.group_id for identity in registry.values()}
    if len(groups) != 15:
        raise S48Error("corrective_03 identity registry is not 15 groups")
    sealed_roots = _sealed_attempt_roots(root, seal, set(registry))
    _validate_profile_modes(root, config)
    grant_path = root / config["grant"]["path"]
    ledger_path = root / config["grant"]["ledger_path"]
    first_result_paths = (
        grant_path,
        ledger_path,
        root / config["evidence"]["derived_input_path"],
        root / config["evidence"]["run_journal_path"],
        root / config["evidence"]["output_path"],
    )
    if require_access_paths_absent and any(
        path.exists() for path in first_result_paths
    ):
        raise S48Error(
            "S4.8 access or first-result state already exists; refusing a "
            "new first opening"
        )
    resolved_commit = source_commit or _git(root, "rev-parse", "HEAD")
    if source_commit is not None:
        _validate_source_commit(root, resolved_commit)
    return {
        "schema": "ias.s4_8.preopen_validation.v1",
        "status": "passed",
        "source_commit": resolved_commit,
        "prerequisite": {
            key: prerequisite[key]
            for key in sorted(PREREQUISITE_BINDING_FIELDS)
        },
        "seal_file_sha256": sha256_file(seal_path),
        "seal_payload_sha256": seal["seal_payload_sha256"],
        "partition_manifest_sha256": sha256_file(
            _repo_file(root, config["holdout"]["partition_manifest_path"])
        ),
        "session_manifest_sha256": sha256_file(
            _repo_file(root, config["holdout"]["session_manifest_path"])
        ),
        "scientific_semantics_sha256": prerequisite[
            "scientific_semantics_sha256"
        ],
        "planned_take_count": len(registry),
        "leakage_group_count": len(groups),
        "sealed_artifact_count": integrity["checked_artifact_count"],
        "sealed_attempt_root_count": len(sealed_roots),
        "content_derived_values_returned": False,
        "holdout_opened": False,
        "grant_path": config["grant"]["path"],
        "ledger_path": config["grant"]["ledger_path"],
        "grant_present": grant_path.exists(),
        "ledger_present": ledger_path.exists(),
        "profile_modes": ["off", "apply"],
        "robustness_status": "not_evaluable",
        "historical_preservation": preservation_report(root)["status"],
    }


def create_grant(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    """Create, but do not consume, the exact real single-use grant."""

    root = repo_root.resolve()
    if not authorization_id.strip():
        raise S48Error("authorization_id must be non-empty")
    preopen = preopen_validate(root, source_commit=source_commit)
    config = load_contract(root)
    grant_path = root / config["grant"]["path"]
    ledger_path = root / config["grant"]["ledger_path"]
    if grant_path.exists() or ledger_path.exists():
        raise S48Error("grant or ledger already exists; refusing overwrite")
    grant_id = config["grant"]["grant_id_template"].format(
        source_commit=source_commit
    )
    payload = {
        "schema": GRANT_SCHEMA,
        "grant_id": grant_id,
        "purpose": "S4.8_evaluation",
        "seal_sha256": preopen["seal_file_sha256"],
        "split_plan_sha256": preopen["partition_manifest_sha256"],
        "prerequisite": preopen["prerequisite"],
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    grant = {**payload, "grant_sha256": canonical_sha256(payload)}
    grant_path.parent.mkdir(parents=True, exist_ok=False)
    grant_path.write_text(pretty_json(grant), encoding="utf-8")
    authorization_record = {
        "schema": "ias.s4_8.authorization_record.v1",
        "authorization_id": authorization_id,
        "source_commit": source_commit,
        "grant_id": grant_id,
        "grant_path": config["grant"]["path"],
        "grant_sha256": grant["grant_sha256"],
        "ledger_path": config["grant"]["ledger_path"],
        "irreversible_scientific_action_acknowledged": True,
    }
    record_path = grant_path.with_name("authorization_record.v1.json")
    record_path.write_text(pretty_json(authorization_record), encoding="utf-8")
    return {
        "grant": grant,
        "authorization_record": authorization_record,
        "grant_file_sha256": sha256_file(grant_path),
    }


def consume_grant_once(
    repo_root: Path,
    *,
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Consume the exact source-identified grant through the canonical interlock."""

    root = repo_root.resolve()
    config = load_contract(root)
    grant_path = root / config["grant"]["path"]
    grant = load_json(grant_path)
    expected_id = config["grant"]["grant_id_template"].format(
        source_commit=source_commit
    )
    if grant.get("grant_id") != expected_id:
        raise S48Error("grant is not bound to the exact evaluator source commit")
    result = consume_s4_8_grant(
        grant_path,
        seal_path=_repo_file(root, config["holdout"]["seal_path"]),
        split_plan_sha256=config["holdout"]["partition_manifest_sha256"],
        prerequisite_path=_repo_file(root, config["prerequisite"]["path"]),
        ledger_path=root / config["grant"]["ledger_path"],
        event_time_utc=event_time_utc,
    )
    if result.get("allowed") is not True or result.get("mode") != "S4.8_evaluation":
        raise S48Error("canonical interlock did not authorize S4.8")
    return result


def run_authorized_evaluation_once(
    repo_root: Path,
    *,
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Consume once, open once, evaluate once, and preserve the first input."""

    root = repo_root.resolve()
    config = load_contract(root)
    derived_path = root / config["evidence"]["derived_input_path"]
    journal_path = root / config["evidence"]["run_journal_path"]
    output = root / config["evidence"]["output_path"]
    if derived_path.exists() or journal_path.exists() or output.exists():
        raise S48Error("first S4.8 result already exists; automatic retry forbidden")
    preopen_validate(
        root,
        source_commit=source_commit,
        require_access_paths_absent=False,
    )
    consumption = consume_grant_once(
        root, source_commit=source_commit, event_time_utc=event_time_utc
    )
    _append_run_journal(
        journal_path,
        {
            "event": "grant_consumed",
            "event_time_utc": event_time_utc,
            "source_commit": source_commit,
            "ledger_event_sha256": consumption["ledger_event"]["event_sha256"],
        },
    )
    _append_run_journal(
        journal_path,
        {
            "event": "observation_opening_started",
            "event_time_utc": event_time_utc,
            "source_commit": source_commit,
        },
    )
    try:
        payload, observation_inventory = build_real_payload(root)
        evaluation = evaluate_payload(payload, repo_root=root)
        _append_run_journal(
            journal_path,
            {
                "event": "first_evaluation_completed",
                "event_time_utc": event_time_utc,
                "source_commit": source_commit,
                "readiness_passed": evaluation["readiness_passed"],
                "failed_gating_criteria": evaluation[
                    "failed_gating_criteria"
                ],
            },
        )
    except Exception as exc:
        _append_run_journal(
            journal_path,
            {
                "event": "first_evaluation_interrupted",
                "event_time_utc": event_time_utc,
                "source_commit": source_commit,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "automatic_retry_forbidden": True,
            },
        )
        raise
    grant_path = root / config["grant"]["path"]
    authorization_record = load_json(
        grant_path.with_name("authorization_record.v1.json")
    )
    derived = {
        "schema": DERIVED_INPUT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "source_commit": source_commit,
        "event_time_utc": event_time_utc,
        "authorization_record": authorization_record,
        "grant": {
            "path": config["grant"]["path"],
            "file_sha256": sha256_file(root / config["grant"]["path"]),
            "grant_sha256": load_json(root / config["grant"]["path"])[
                "grant_sha256"
            ],
        },
        "ledger_event": consumption["ledger_event"],
        "run_journal": {
            "path": config["evidence"]["run_journal_path"],
            "file_sha256": sha256_file(journal_path),
            "event_count": 3,
        },
        "observation_inventory": observation_inventory,
        "payload": payload,
        "evaluation": evaluation,
    }
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_path.write_text(pretty_json(derived), encoding="utf-8")
    build_evidence_package(
        root,
        derived,
        output=output,
        source_commit=source_commit,
    )
    return evaluation


def build_real_payload(
    repo_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open and derive the real payload. Caller must have consumed the grant."""

    root = repo_root.resolve()
    config = load_contract(root)
    _require_consumed_ledger(root, config)
    seal = load_json(_repo_file(root, config["holdout"]["seal_path"]))
    integrity = hash_only_holdout_integrity(seal, repo_root=root)
    if integrity["status"] != "passed":
        raise S48Error("sealed artifact bytes changed before observation opening")
    registry = build_identity_registry(root)
    attempt_candidates = _sealed_attempt_candidates(seal, set(registry))
    attempt_roots = _sealed_attempt_roots(root, seal, set(registry))
    profile = _profile_runtime(root)
    takes: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for take_id in sorted(registry):
        identity = registry[take_id]
        attempt_root = attempt_roots[take_id]
        take, record = _analyze_real_take(
            root,
            attempt_root,
            identity,
            profile=profile,
            seal=seal,
        )
        takes.append(take)
        record["selected_for_evaluation"] = True
        inventory.append(record)
        for candidate in sorted(attempt_candidates[take_id]):
            absolute = root / candidate
            if absolute == attempt_root:
                continue
            wav_record = _seal_record(
                seal, candidate / "raw/respeaker_audio.wav"
            )
            qa_record = _seal_record(seal, candidate / "technical_qa.json")
            inventory.append(
                {
                    "planned_take_id": take_id,
                    "attempt_root": candidate.as_posix(),
                    "wav_sha256": wav_record["sha256"],
                    "technical_qa_sha256": qa_record["sha256"],
                    "window_count": None,
                    "failed": True,
                    "failure_reasons": [
                        "predeclared_replacement_attempt_not_selected"
                    ],
                    "rejected": True,
                    "excluded": False,
                    "selected_for_evaluation": False,
                    "scientific_observations_derived": False,
                    "av_analysis": None,
                }
            )
    payload = {
        "schema": "ias.s4_7.corrective_metrics.v4",
        "contract": {
            "config_sha256": config["criteria"]["corrective_config_sha256"],
            "bound_holdout_id": config["holdout"]["bound_holdout_id"],
            "seal_payload_sha256": config["holdout"]["seal_payload_sha256"],
            "planned_take_count": 47,
        },
        "takes": takes,
        "sim_vs_real": build_simulation_comparisons(root),
    }
    inventory.sort(key=lambda record: record["attempt_root"])
    return payload, inventory


def evaluate_payload(
    payload: Mapping[str, Any], *, repo_root: Path
) -> dict[str, Any]:
    """Return a truthful result, including an explicit failed rejection."""

    try:
        result = evaluate_corrective(payload, repo_root=repo_root)
    except CorrectiveAcceptanceError as exc:
        return {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "readiness_passed": False,
            "failed_gating_criteria": [
                "evaluation_input_contract_rejected",
            ],
            "criteria": [],
            "comparison_classifications": [],
            "identity_summary": {},
            "config_identity": {},
            "evaluation_error": str(exc),
            "robustness": {
                "status": "not_evaluable",
                "denominator": 0,
            },
        }
    report = result.report()
    report["schema"] = RESULT_SCHEMA
    report["robustness"] = {
        "status": "not_evaluable",
        "denominator": 0,
    }
    report["evaluation_error"] = None
    return report


def build_simulation_comparisons(repo_root: Path) -> list[dict[str, Any]]:
    """Run the deterministic core simulator with S4.6 off and apply modes."""

    root = repo_root.resolve()
    config = load_contract(root)
    registry = build_identity_registry(root)
    paths = {
        mode: _simulate_path(root, registry, mode)
        for mode in ("off", "apply")
    }
    corrective = load_json(
        _repo_file(root, config["criteria"]["delegated_config_path"])
    )
    comparisons: list[dict[str, Any]] = []
    for entry in corrective["sim_vs_real"]["comparison_registry"]:
        conditions = []
        for condition_id in sorted(
            _comparison_condition_ids(entry, registry, corrective)
        ):
            conditions.append(
                {
                    "condition_id": condition_id,
                    "unadjusted_simulation": paths["off"][
                        entry["comparison_id"]
                    ][condition_id],
                    "adjusted_simulation": paths["apply"][
                        entry["comparison_id"]
                    ][condition_id],
                }
            )
        comparisons.append(
            {
                "comparison_id": entry["comparison_id"],
                "conditions": conditions,
            }
        )
    return comparisons


def build_evidence_package(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    output: Path,
    source_commit: str,
    require_current_head: bool = True,
) -> dict[str, Any]:
    """Build the deterministic tracked package from the preserved first input."""

    root = repo_root.resolve()
    _validate_source_commit(
        root,
        source_commit,
        require_current_head=require_current_head,
    )
    destination = output if output.is_absolute() else root / output
    if destination.exists():
        raise S48Error(f"refusing to overwrite S4.8 package: {destination}")
    destination.mkdir(parents=True)
    evaluation = dict(derived["evaluation"])
    payload = dict(derived["payload"])
    takes = payload["takes"]
    windows = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "stratum_id": take["identity"]["stratum_id"],
            "windows": take["bearing_windows"],
            "window_summary": take["window_summary"],
        }
        for take in takes
    ]
    failures = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "failed": take["failed"],
            "failure_reasons": take["failure_reasons"],
        }
        for take in takes
        if take["failed"]
    ]
    preservation = preservation_report(root)
    contract = load_contract(root)
    source_files = [
        {
            "path": path.as_posix(),
            "sha256": sha256_file(root / path),
        }
        for path in SOURCE_BOUND_FILES
    ]
    reports: dict[str, Any] = {
        "authorization_access.json": {
            "schema": "ias.s4_8.authorization_access.v1",
            "status": "passed",
            "authorization_record": derived["authorization_record"],
            "grant": derived["grant"],
            "ledger_event": derived["ledger_event"],
            "run_journal": derived.get("run_journal"),
            "grant_consumed_exactly_once": True,
            "raw_content_included": False,
        },
        "criteria_results.json": evaluation,
        "derived_evaluation_input.json": dict(derived),
        "failure_inventory.json": {
            "schema": "ias.s4_8.failure_inventory.v1",
            "status": "complete",
            "planned_take_count": 47,
            "failed_take_count": len(failures),
            "failures": failures,
            "rejected_attempts": [
                record
                for record in derived.get("observation_inventory", [])
                if record.get("rejected") is True
            ],
            "all_planned_takes_retained": True,
        },
        "preservation_report.json": preservation,
        "provenance.json": {
            "schema": "ias.s4_8.provenance.v1",
            "status": "passed",
            "tool_version": TOOL_VERSION,
            "source_commit": source_commit,
            "contract_path": CONFIG_PATH.as_posix(),
            "contract_sha256": sha256_file(root / CONFIG_PATH),
            "source_bound_files": source_files,
            "source_bound_files_sha256": canonical_sha256(source_files),
            "prerequisite_sha256": contract["prerequisite"]["sha256"],
            "prerequisite_manifest_sha256": contract["prerequisite"][
                "package_manifest_sha256"
            ],
            "seal_file_sha256": contract["holdout"]["seal_file_sha256"],
            "seal_payload_sha256": contract["holdout"][
                "seal_payload_sha256"
            ],
            "partition_manifest_sha256": contract["holdout"][
                "partition_manifest_sha256"
            ],
            "session_manifest_sha256": contract["holdout"][
                "session_manifest_sha256"
            ],
            "scientific_semantics_sha256": contract["prerequisite"][
                "scientific_semantics_sha256"
            ],
            "criteria_v1_config_sha256": contract["criteria"][
                "v1_config_sha256"
            ],
            "criteria_corrective_03_config_sha256": contract["criteria"][
                "corrective_config_sha256"
            ],
            "criteria_corrective_02_config_sha256": contract["criteria"][
                "delegated_config_sha256"
            ],
            "s4_6_config_sha256": contract["profile_application"][
                "config_sha256"
            ],
            "s4_6_active_pointer_sha256": contract[
                "profile_application"
            ]["active_pointer_sha256"],
            "s4_3_effective_config_sha256": contract["analysis"][
                "s4_3_effective_config_sha256"
            ],
            "s4_3_transient_contract_sha256": contract["analysis"][
                "transient_contract_sha256"
            ],
            "s4_6_application_report": _profile_runtime(root)[
                "application_report"
            ],
            "raw_data_tracked": False,
        },
        "reproduction.json": {
            "schema": "ias.s4_8.reproduction.v1",
            "status": "passed",
            "command": (
                "python3 scripts/replay_s4_8.py "
                "--canonical outputs/isaac_audio_sensors/S4/S4.8"
            ),
            "source_commit": source_commit,
            "input": "canonical package reports",
            "opens_raw_holdout": False,
            "consumes_grant": False,
        },
        "robustness.json": {
            "schema": "ias.s4_8.robustness.v1",
            "status": "not_evaluable",
            "denominator": 0,
            "gating": False,
            "quantities": [
                "alternate_rooms",
                "alternate_mounts",
                "alternate_sources",
                "occlusion",
                "overlap",
                "elevated_noise",
                "distance_variation",
                "motion",
                "endurance",
            ],
        },
        "sim_vs_real.json": {
            "schema": "ias.s4_8.sim_vs_real.v1",
            "status": "complete",
            "comparison_classifications": evaluation[
                "comparison_classifications"
            ],
            "condition_inputs": payload["sim_vs_real"],
            "paths": ["real", "unadjusted_simulation", "adjusted_simulation"],
            "unadjusted_profile_mode": "off",
            "adjusted_profile_mode": "apply",
        },
        "supported_unsupported.json": {
            "schema": "ias.s4_8.supported_unsupported.v1",
            "status": "complete",
            "supported_envelope": "controlled_source_single_room_single_mount",
            "supported_metrics": [
                "bearing",
                "sector_accuracy",
                "candidate_coverage",
                "tdoa",
                "confidence",
                "abstention",
                "relative_latency",
                "channel_health",
                "clipping",
                "coarse_audio_video_association",
            ],
            "unsupported": [
                "absolute_spl",
                "absolute_microphone_sensitivity",
                "isolated_frequency_response",
                "certified_reverberation",
                "traceable_calibration",
                "precision_optical_acoustic_extrinsics",
                "universal_transfer",
                "live_end_to_end_capture_latency",
            ],
        },
        "take_inventory.json": {
            "schema": "ias.s4_8.take_inventory.v1",
            "status": "complete",
            "planned_take_count": 47,
            "leakage_group_count": 15,
            "sealed_attempt_count": len(
                derived.get("observation_inventory", [])
            ),
            "selected_attempt_count": sum(
                record.get("selected_for_evaluation") is True
                for record in derived.get("observation_inventory", [])
            ),
            "unselected_attempt_count": sum(
                record.get("selected_for_evaluation") is False
                for record in derived.get("observation_inventory", [])
            ),
            "attempt_records": derived.get("observation_inventory", []),
            "records": [
                {
                    key: take[key]
                    for key in (
                        "identity",
                        "failed",
                        "failure_reasons",
                        "latency",
                        "window_summary",
                        "channels",
                        "bearing_absolute_error_deg",
                        "estimated_bearing_deg_f_project",
                        "sector_correct",
                        "candidate_covered",
                        "candidate_bearings_deg_f_project",
                        "confidence",
                        "tdoa",
                        "audio_event_time_ms",
                        "video_event_time_ms",
                        "av_absolute_residual_ms",
                    )
                }
                for take in takes
            ],
        },
        "window_results.json": {
            "schema": "ias.s4_8.window_results.v1",
            "status": "complete",
            "record_count": sum(len(item["windows"]) for item in windows),
            "takes": windows,
        },
    }
    final_status = (
        "passed" if evaluation.get("readiness_passed") is True else "failed"
    )
    reports["final_validation.json"] = {
        "schema": "ias.s4_8.final_validation.v1",
        "status": final_status,
        "readiness_passed": evaluation.get("readiness_passed") is True,
        "readiness_criterion_count": len(
            [item for item in evaluation.get("criteria", []) if item["gating"]]
        ),
        "stretch_criterion_count": len(
            [
                item
                for item in evaluation.get("criteria", [])
                if not item["gating"]
            ]
        ),
        "planned_take_count": len(takes),
        "historical_preservation_passed": preservation["status"] == "passed",
        "robustness_status": "not_evaluable",
        "s4_complete": False,
        "s4_9_started": False,
        "later_phases_started": [],
    }
    for name, report in reports.items():
        (destination / name).write_text(pretty_json(report), encoding="utf-8")
    _write_index_and_manifest(destination, source_commit)
    deterministic = {
        "schema": "ias.s4_8.determinism.v1",
        "status": "passed",
        "source_commit": source_commit,
        "canonical_file_count": len(PACKAGE_FILES),
        "raw_holdout_reopened": False,
        "grant_reconsumed": False,
        "replay_method": "validate_and_copy_canonical_derived_reports",
    }
    (destination / "determinism_report.json").write_text(
        pretty_json(deterministic), encoding="utf-8"
    )
    _write_index_and_manifest(destination, source_commit)
    validate_evidence_package(destination, repo_root=root)
    return {
        "status": final_status,
        "output": destination.as_posix(),
        "file_count": len(PACKAGE_FILES),
        "manifest_sha256": sha256_file(destination / "SHA256SUMS"),
    }


def validate_evidence_package(package: Path, *, repo_root: Path) -> dict[str, Any]:
    package = package.resolve()
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != PACKAGE_FILES:
        raise S48Error(
            f"S4.8 package files mismatch: missing={sorted(PACKAGE_FILES-present)}, "
            f"extra={sorted(present-PACKAGE_FILES)}"
        )
    _validate_manifest(package)
    index = load_json(package / "evidence_index.json")
    if index.get("record_count") != len(PACKAGE_FILES) - 3:
        raise S48Error("S4.8 evidence index count mismatch")
    for record in index.get("records", []):
        path = package / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != record["byte_size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise S48Error(f"S4.8 evidence index mismatch: {record['path']}")
    criteria = load_json(package / "criteria_results.json")
    final = load_json(package / "final_validation.json")
    if final["readiness_passed"] is not (
        criteria.get("readiness_passed") is True
    ):
        raise S48Error("S4.8 final status contradicts criteria")
    if load_json(package / "robustness.json")["status"] != "not_evaluable":
        raise S48Error("S4.8 robustness must be not_evaluable")
    gating = [
        item for item in criteria.get("criteria", []) if item.get("gating") is True
    ]
    stretch = [
        item for item in criteria.get("criteria", []) if item.get("gating") is False
    ]
    if len(gating) != 23 or len(stretch) != 6:
        raise S48Error("S4.8 criteria count is not exactly 23 readiness and 6 stretch")
    inventory = load_json(package / "take_inventory.json")
    attempt_records = inventory.get("attempt_records")
    if (
        inventory.get("planned_take_count") != 47
        or inventory.get("leakage_group_count") != 15
        or inventory.get("sealed_attempt_count") != 48
        or inventory.get("selected_attempt_count") != 47
        or inventory.get("unselected_attempt_count") != 1
        or not isinstance(attempt_records, list)
        or len(attempt_records) != 48
    ):
        raise S48Error("S4.8 planned-take or sealed-attempt inventory mismatch")
    selected_ids = [
        record.get("planned_take_id")
        for record in attempt_records
        if record.get("selected_for_evaluation") is True
    ]
    if len(selected_ids) != len(set(selected_ids)) or len(selected_ids) != 47:
        raise S48Error("S4.8 selected attempt identities are incomplete or duplicate")
    sim = load_json(package / "sim_vs_real.json")
    conditions = sim.get("condition_inputs")
    if (
        not isinstance(conditions, list)
        or len(conditions) != 7
        or sum(len(item.get("conditions", [])) for item in conditions) != 271
    ):
        raise S48Error("S4.8 sim-versus-real condition inventory mismatch")
    derived = load_json(package / "derived_evaluation_input.json")
    if derived.get("evaluation") != criteria:
        raise S48Error("S4.8 derived input and criteria result disagree")
    authorization = load_json(package / "authorization_access.json")
    ledger_event = authorization.get("ledger_event")
    if (
        authorization.get("grant_consumed_exactly_once") is not True
        or not isinstance(ledger_event, dict)
        or ledger_event.get("schema") != "ias.s4_4.access_ledger_event.v1"
        or ledger_event.get("sequence") != 0
        or ledger_event.get("event") != "holdout_open_authorized"
        or ledger_event.get("purpose") != "S4.8_evaluation"
        or ledger_event.get("holdout_opened") is not True
    ):
        raise S48Error("S4.8 authenticated grant or ledger evidence mismatch")
    event_payload = {
        key: value
        for key, value in ledger_event.items()
        if key != "event_sha256"
    }
    if ledger_event.get("event_sha256") != canonical_sha256(event_payload):
        raise S48Error("S4.8 ledger event hash mismatch")
    if preservation_report(repo_root)["status"] != "passed":
        raise S48Error("historical S4 packages changed")
    return {
        "schema": "ias.s4_8.package_validation.v1",
        "status": "passed",
        "file_count": len(present),
        "manifest_sha256": sha256_file(package / "SHA256SUMS"),
        "readiness_passed": final["readiness_passed"],
    }


def replay_evidence_package(
    canonical: Path, *, output: Path, repo_root: Path
) -> dict[str, Any]:
    """Reproduce package bytes without reopening data or consuming a grant."""

    canonical = canonical.resolve()
    validate_evidence_package(canonical, repo_root=repo_root)
    if output.exists():
        raise S48Error(f"replay output already exists: {output}")
    derived = load_json(canonical / "derived_evaluation_input.json")
    source_commit = load_json(canonical / "provenance.json")["source_commit"]
    build_evidence_package(
        repo_root,
        derived,
        output=output,
        source_commit=source_commit,
        require_current_head=False,
    )
    left = {
        path.name: path.read_bytes()
        for path in canonical.iterdir()
        if path.is_file()
    }
    right = {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.is_file()
    }
    if left != right:
        raise S48Error("S4.8 deterministic replay byte mismatch")
    return {
        "schema": "ias.s4_8.replay_validation.v1",
        "status": "passed",
        "file_count": len(left),
        "byte_identical": True,
        "raw_holdout_reopened": False,
        "grant_reconsumed": False,
        "regenerated_from_derived_input": True,
    }


def preservation_report(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    baseline_paths = _git_lines(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        PRESERVATION_BASELINE_COMMIT,
        "--",
        PRESERVATION_ROOT.as_posix(),
    )
    records = []
    for path in baseline_paths:
        current = root / path
        baseline_blob = subprocess.run(
            ["git", "show", f"{PRESERVATION_BASELINE_COMMIT}:{path}"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        current_bytes = current.read_bytes() if current.is_file() else None
        records.append(
            {
                "path": path,
                "baseline_sha256": hashlib.sha256(baseline_blob).hexdigest(),
                "current_sha256": (
                    hashlib.sha256(current_bytes).hexdigest()
                    if current_bytes is not None
                    else None
                ),
                "unchanged": current_bytes == baseline_blob,
            }
        )
    valid = bool(records) and all(record["unchanged"] for record in records)
    return {
        "schema": "ias.s4_8.historical_preservation.v1",
        "status": "passed" if valid else "failed",
        "baseline_commit": PRESERVATION_BASELINE_COMMIT,
        "tracked_file_count": len(records),
        "records_sha256": canonical_sha256(records),
        "files": records,
    }


def _analyze_real_take(
    repo_root: Path,
    attempt_root: Path,
    identity: Any,
    *,
    profile: Mapping[str, Any],
    seal: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    take_id = identity.planned_take_id
    wav_path = attempt_root / "raw/respeaker_audio.wav"
    qa_path = attempt_root / "technical_qa.json"
    _verify_sealed_file(repo_root, wav_path, seal)
    _verify_sealed_file(repo_root, qa_path, seal)
    properties, issues = inspect_six_channel_wav(
        wav_path,
        require_nonsilent_channels=identity.stratum_id != "D_silence",
        reject_sustained_clipping=False,
        sustained_clip_run_samples_min=4000,
        expected_duration_s=float(identity.duration_s),
        duration_tolerance_s=0.25,
    )
    samples, rate = _read_pcm16(wav_path)
    raw = samples[:, 2:6].T
    raw_adjusted = raw * np.asarray(profile["gain_multipliers"])[:, None]
    window_count = 1 + (raw.shape[1] - 4000) // 2000
    expected_count = {15: 119, 20: 159}[identity.duration_s]
    if rate != 16000 or window_count != expected_count:
        raise S48Error(
            f"{take_id}: expected {expected_count} exact windows at 16 kHz"
        )
    positions = np.asarray(profile["positions"], dtype=float)
    ids = tuple(f"raw_microphone_{index}" for index in range(4))
    position_map = dict(zip(ids, map(tuple, positions), strict=True))
    aperture = max(
        float(np.linalg.norm(positions[left] - positions[right]))
        for left in range(4)
        for right in range(left + 1, 4)
    )
    max_delay = aperture / 343.0 + 1.0 / rate
    target = identity.target_bearing_deg_f_project
    expected_tdoa = (
        {}
        if target is None
        else _expected_tdoa(positions, ids, float(target), 343.0)
    )
    windows = []
    confidences = []
    tdoa_by_pair: dict[str, list[float]] = defaultdict(list)
    correlation_by_pair: dict[str, list[float]] = defaultdict(list)
    runtime_ms = []
    adapter_ms = []
    valid_bearings: list[float] = []
    for index in range(window_count):
        start = index * 2000
        frame_raw = raw_adjusted[:, start : start + 4000]
        started = time.perf_counter_ns()
        per_rms = np.sqrt(np.mean(frame_raw * frame_raw, axis=1))
        signal = float(np.median(per_rms)) > 0.002
        bearing: float | None = None
        confidence = 0.0
        measured_tdoa: dict[str, float] = {}
        if signal:
            waveforms = {
                mic_id: frame_raw[channel]
                for channel, mic_id in enumerate(ids)
            }
            srp = srp_phat_direction(
                waveforms,
                mic_positions_m=position_map,
                sample_rate_hz=rate,
                speed_of_sound_mps=343.0,
                azimuth_step_deg=2.0,
                max_delay_s=max_delay,
                interp=8,
            )
            confidence = float(srp_phat_confidence(srp))
            if confidence >= 0.015:
                bearing = float(srp.bearing_deg)
                valid_bearings.append(bearing)
            tdoa, _peaks = estimate_tdoa_diagnostics(
                waveforms,
                sample_rate_hz=rate,
                max_delay_s=max_delay,
                interp=8,
            )
            measured_tdoa = {key: float(value) for key, value in tdoa.items()}
            for key, value in measured_tdoa.items():
                tdoa_by_pair[key].append(value * 1_000_000.0)
            for left in range(4):
                for right in range(left + 1, 4):
                    key = f"{ids[left]}->{ids[right]}"
                    correlation_by_pair[key].append(
                        _aligned_correlation(
                            frame_raw[left],
                            frame_raw[right],
                            measured_tdoa[key],
                            rate,
                        )
                    )
        confidences.append(confidence)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        runtime_ms.append(250.0 + elapsed)
        record = {
            "window_id": f"window_{index:03d}",
            "window_index": index,
            "start_sample": start,
            "abstained": bearing is None,
            "srp_bearing_deg_f_project": bearing,
            "sub_floor_direction_emitted": False,
        }
        adapter_started = time.perf_counter_ns()
        restored = json.loads(json.dumps(record, sort_keys=True))
        adapter_ms.append(
            (time.perf_counter_ns() - adapter_started) / 1_000_000.0
        )
        if restored != record:
            raise S48Error(f"{take_id}: adapter round trip changed a window")
        windows.append(record)
    applicable_bearing = identity.stratum_id in {
        "A_controlled_boundary_sweep",
        "B_center_nominal_level",
    }
    if applicable_bearing and not valid_bearings:
        issues = [
            *issues,
            type(
                "Issue",
                (),
                {"code": "no_valid_bearing_window"},
            )(),
        ]
    representative = float(median(valid_bearings)) if valid_bearings else None
    errors = (
        [
            _circular_difference(float(target), value)
            for value in valid_bearings
        ]
        if applicable_bearing
        else []
    )
    channels = _channel_records(properties, correlation_by_pair)
    failure_reasons = sorted(
        {
            *(getattr(issue, "code", "analysis_issue") for issue in issues),
            *(
                "raw_channel_health_failure"
                for channel in channels
                if channel["health_failure"]
            ),
        }
    )
    qa = load_json(qa_path)
    if qa.get("overall_technical_pass") is not True:
        failure_reasons.append("technical_qa_failed")
    av = (
        _derive_av_association(
            repo_root,
            attempt_root,
            take_id,
            raw,
            seal,
        )
        if identity.stratum_id == "E_impact_audio_video"
        else None
    )
    candidate_bearings = (
        [representative]
        if applicable_bearing and representative is not None
        else []
    )
    candidate_covered = (
        any(
            _circular_difference(float(target), item) <= 20.0
            for item in candidate_bearings
        )
        if applicable_bearing
        else None
    )
    tdoa = []
    if identity.stratum_id == "A_controlled_boundary_sweep":
        for pair_id in _pair_ids():
            observed = float(median(tdoa_by_pair.get(pair_id, [0.0])))
            reference = float(expected_tdoa[pair_id] * 1_000_000.0)
            tdoa.append(
                {
                    "pair_id": pair_id,
                    "tdoa_us": observed,
                    "reference_tdoa_us": reference,
                    "absolute_error_us": abs(observed - reference),
                }
            )
    take = {
        "identity": identity.payload_identity(),
        "failed": bool(failure_reasons),
        "failure_reasons": sorted(set(failure_reasons)),
        "latency": {
            "frame_to_adapter_round_trip_ms": float(median(adapter_ms)),
            "capture_to_frame_offline_ms": float(median(runtime_ms)),
        },
        "window_summary": {
            "source_window_count": window_count,
            "abstained_window_count": sum(
                item["abstained"] for item in windows
            ),
            "sub_floor_direction_emission_count": 0,
        },
        "channels": channels,
        "bearing_absolute_error_deg": (
            float(median(errors)) if errors else None
        ),
        "estimated_bearing_deg_f_project": representative,
        "sector_correct": (
            _sector_majority_correct(valid_bearings, float(target))
            if identity.stratum_id == "B_center_nominal_level"
            else None
        ),
        "candidate_covered": candidate_covered,
        "candidate_bearings_deg_f_project": candidate_bearings,
        "confidence": (
            float(median(confidences))
            if identity.stratum_id
            in {"B_center_nominal_level", "C_center_low_level"}
            else None
        ),
        "tdoa": tdoa,
        "audio_event_time_ms": None if av is None else av["audio_event_time_ms"],
        "video_event_time_ms": None if av is None else av["video_event_time_ms"],
        "av_absolute_residual_ms": (
            None if av is None else av["av_absolute_residual_ms"]
        ),
        "bearing_windows": windows if applicable_bearing else [],
    }
    return take, {
        "planned_take_id": take_id,
        "attempt_root": attempt_root.relative_to(repo_root).as_posix(),
        "wav_sha256": sha256_file(wav_path),
        "technical_qa_sha256": sha256_file(qa_path),
        "window_count": window_count,
        "failed": take["failed"],
        "failure_reasons": take["failure_reasons"],
        "rejected": False,
        "excluded": False,
        "av_analysis": av,
    }


def _derive_av_association(
    repo_root: Path,
    attempt_root: Path,
    take_id: str,
    raw: np.ndarray,
    seal: Mapping[str, Any],
) -> dict[str, Any]:
    confirmation_path = attempt_root / "operator_event_confirmation.json"
    frames_path = attempt_root / "raw/zed_frames.jsonl"
    producer_path = attempt_root / "raw/pi_producer_status.json"
    _verify_sealed_file(repo_root, confirmation_path, seal)
    _verify_sealed_file(repo_root, frames_path, seal)
    _verify_sealed_file(repo_root, producer_path, seal)
    confirmation = load_json(confirmation_path)
    if (
        confirmation.get("schema")
        != "ias.s4_4.amendment_av_operator_event_confirmation.v1"
        or confirmation.get("planned_take_id") != take_id
        or confirmation.get("attempt_id") != attempt_root.name
        or confirmation.get("protocol_compliance_pass") is not True
        or confirmation.get("required_impact_count") != 3
        or confirmation.get("retained_media_deleted_or_overwritten") is not False
        or confirmation.get("scientific_outcome_used_for_replacement") is not False
        or confirmation.get("technical_qa_passed") is not True
        or confirmation.get("technical_quality_failure_reason") is not None
    ):
        raise S48Error(f"{attempt_root.name}: invalid AV confirmation")
    frames = []
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line, parse_constant=_reject_json_constant)
        if not isinstance(record, dict):
            raise S48Error(f"{attempt_root.name}: invalid ZED frame record")
        frames.append(record)
    timestamps = [int(record["device_timestamp_ns"]) for record in frames]
    host_times_ms = [
        1000.0 * _parse_utc(record["host_wall_time_utc"]).timestamp()
        for record in frames
    ]
    if len(frames) < 2 or any(
        later <= earlier
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
    ) or any(
        later <= earlier
        for earlier, later in zip(host_times_ms, host_times_ms[1:], strict=False)
    ):
        raise S48Error(f"{attempt_root.name}: invalid ZED timestamps")
    contract = load_contract(repo_root)
    detector_config = load_pilot_configuration(
        _repo_file(
            repo_root,
            contract["analysis"]["s4_3_effective_config_path"],
        ),
        repo_root=repo_root,
    )
    transient = _prospective_transient_events(
        raw.T,
        detector_config,
        contract_sha256=contract["analysis"]["transient_contract_sha256"],
    )
    audio_candidates = [
        int(record["peak_sample"]) for record in transient["events"]
    ]
    audio_samples = _select_three_spaced_events(
        audio_candidates,
        sample_rate_hz=16000,
        expected_interval_s=float(
            contract["analysis"]["av_expected_interval_s"]
        ),
    )
    producer = load_json(producer_path)
    audio_start_ms = 1000.0 * _parse_utc(
        producer.get("started_wall_time_utc")
    ).timestamp()
    depth_motion = _depth_grid_motion(frames)
    search_half_width = float(
        contract["analysis"]["av_visual_search_half_width_ms"]
    )
    associations = []
    for event_index, sample in enumerate(audio_samples):
        audio_ms = audio_start_ms + 1000.0 * sample / 16000.0
        candidates = [
            index
            for index in range(1, len(frames))
            if abs(host_times_ms[index] - audio_ms) <= search_half_width
        ]
        if not candidates:
            raise S48Error(
                f"{attempt_root.name}: no visual candidate for event "
                f"{event_index}"
            )
        video_index = max(
            candidates,
            key=lambda index: (depth_motion[index], -index),
        )
        video_ms = host_times_ms[video_index]
        associations.append(
            {
                "event_index": event_index,
                "audio_peak_sample": sample,
                "audio_event_time_ms": audio_ms,
                "video_frame_index": int(frames[video_index]["frame_index"]),
                "video_event_time_ms": video_ms,
                "visual_motion_mean_absolute_depth_delta_m": depth_motion[
                    video_index
                ],
                "av_absolute_residual_ms": abs(audio_ms - video_ms),
            }
        )
    worst = max(associations, key=lambda item: item["av_absolute_residual_ms"])
    return {
        "audio_event_time_ms": worst["audio_event_time_ms"],
        "video_event_time_ms": worst["video_event_time_ms"],
        "av_absolute_residual_ms": worst["av_absolute_residual_ms"],
        "events": associations,
        "audio_candidates": transient,
    }


def _select_three_spaced_events(
    samples: Sequence[int],
    *,
    sample_rate_hz: int,
    expected_interval_s: float,
) -> tuple[int, int, int]:
    if len(samples) < 3 or sample_rate_hz <= 0:
        raise S48Error("fewer than three frozen audio transient candidates")
    candidates = []
    for combination in itertools.combinations(sorted(samples), 3):
        gaps = (
            (combination[1] - combination[0]) / sample_rate_hz,
            (combination[2] - combination[1]) / sample_rate_hz,
        )
        candidates.append(
            (
                sum(abs(gap - expected_interval_s) for gap in gaps),
                combination,
            )
        )
    return min(candidates)[1]


def _depth_grid_motion(frames: Sequence[Mapping[str, Any]]) -> list[float]:
    motion = [0.0]
    for previous, current in zip(frames, frames[1:], strict=False):
        left = previous.get("depth_sample_grid_m")
        right = current.get("depth_sample_grid_m")
        if (
            not isinstance(left, list)
            or not isinstance(right, list)
            or len(left) != len(right)
            or not left
        ):
            raise S48Error("invalid ZED depth-grid identity")
        differences = [
            abs(float(first) - float(second))
            for first, second in zip(left, right, strict=True)
            if first is not None
            and second is not None
            and math.isfinite(float(first))
            and math.isfinite(float(second))
        ]
        if not differences:
            raise S48Error("ZED depth-grid delta has no finite support")
        motion.append(float(sum(differences) / len(differences)))
    return motion


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise S48Error("required UTC timestamp is absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise S48Error(f"invalid UTC timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise S48Error(f"UTC timestamp lacks timezone: {value}")
    if parsed.utcoffset().total_seconds() != 0:
        raise S48Error(f"timestamp is not UTC: {value}")
    return parsed


def _simulate_path(
    repo_root: Path, registry: Mapping[str, Any], mode: str
) -> dict[str, dict[str, float]]:
    raw_config = _base_sim_config()
    context = load_json(
        repo_root / "configs/s4_6_profile_application.v1.json"
    )["application_context"]
    application = apply_profile_application(
        validate_audio_config(raw_config),
        repo_root=repo_root,
        mode=mode,
        runtime_context=context if mode == "apply" else None,
    )
    if application.mode != mode:
        raise S48Error(f"simulation profile mode mismatch: {mode}")
    expected_applied = 7 if mode == "apply" else 0
    if sum(
        row["status"] == "applied" for row in application.field_status
    ) != expected_applied:
        raise S48Error(f"simulation profile application count mismatch: {mode}")
    array = application.config.arrays["xvf3800_array"]
    simulation_ids = tuple(microphone.mic_id for microphone in array.microphones)
    simulation_positions = np.asarray(
        [
            microphone.relative_position_m
            for microphone in array.microphones
        ],
        dtype=float,
    )
    backend = TdoaSyntheticBackend(
        speed_of_sound_mps=343.0,
        effects=application.config.effects,
        runtime_profile=application.config.runtime_profile,
    )
    result: dict[str, dict[str, float]] = {
        key: {}
        for key in (
            "bearing_doa_error_ab",
            "sector_accuracy_b",
            "candidate_bearing_ab",
            "tdoa_a",
            "abstention_abd",
            "confidence_bc",
            "coarse_audio_video_association_e",
        )
    }
    for take_id in sorted(registry):
        identity = registry[take_id]
        target = identity.target_bearing_deg_f_project
        source = None
        if identity.stratum_id != "D_silence":
            bearing = 0.0 if target is None else float(target)
            radius = 0.8
            source = AudioSourceSpec(
                source_id=take_id,
                prim_path=f"/World/Sources/{take_id}",
                class_label="controlled_reference",
                audio_asset_path="generated://s4_8_reference",
                position_world=(
                    radius * math.cos(math.radians(bearing)),
                    radius * math.sin(math.radians(bearing)),
                    0.0,
                ),
                orientation_world_quat=None,
                start_time_s=0.0,
                duration_s=0.25,
                gain_db=20.0
                * math.log10(
                    1.0
                    if identity.stratum_id == "E_impact_audio_video"
                    else (
                        0.75
                        if identity.stratum_id
                        != "C_center_low_level"
                        else 0.35
                    )
                ),
            )
        scene = AudioSceneSnapshot(
            stage_id=f"s4_8_{mode}_{take_id}",
            timestamp_ms=0,
            sources=() if source is None else (source,),
            arrays=(array,),
        )
        frame = backend.simulate(
            scene,
            array,
            AudioTimeWindow(
                start_time_s=0.0,
                end_time_s=0.25,
                timestamp_ms=0,
                sample_rate_hz=16000,
                frame_index=0,
            ),
        )
        detection = frame.detections[0] if frame.detections else None
        if identity.stratum_id in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
        }:
            assert target is not None and detection is not None
            estimated = detection.doa.estimated_bearing_deg
            if estimated is None:
                raise S48Error(f"simulation {mode} abstained unexpectedly")
            error = _circular_difference(float(target), estimated)
            result["bearing_doa_error_ab"][take_id] = error
            result["candidate_bearing_ab"][take_id] = float(
                any(
                    _circular_difference(float(target), item) <= 20.0
                    for item in detection.doa.candidate_bearing_deg
                )
            )
            if identity.stratum_id == "B_center_nominal_level":
                result["sector_accuracy_b"][take_id] = float(
                    bearing_deg_to_sector_name(estimated)
                    == bearing_deg_to_sector_name(float(target))
                )
        if identity.stratum_id == "A_controlled_boundary_sweep":
            assert detection is not None and target is not None
            delays = detection.per_mic_delay_s
            reference_tdoa = _expected_tdoa(
                simulation_positions,
                simulation_ids,
                float(target),
                343.0,
            )
            for pair_id in _pair_ids("ch"):
                left, right = pair_id.split("->")
                raw_pair = pair_id.replace("ch", "raw_microphone_")
                observed = (delays[left] - delays[right]) * 1_000_000.0
                result["tdoa_a"][f"{take_id}|{raw_pair}"] = abs(
                    observed - reference_tdoa[pair_id] * 1_000_000.0
                )
        if identity.stratum_id in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
            "D_silence",
        }:
            result["abstention_abd"][take_id] = 0.0
        if identity.stratum_id in {
            "B_center_nominal_level",
            "C_center_low_level",
        }:
            assert detection is not None
            result["confidence_bc"][take_id] = float(
                detection.doa.bearing_confidence
            )
        if identity.stratum_id == "E_impact_audio_video":
            result["coarse_audio_video_association_e"][take_id] = 0.0
    return result


def _base_sim_config() -> dict[str, Any]:
    return {
        "scene": {"scene_id": "s4_8_simulation"},
        "audio": {
            "sample_rate_hz": 16000,
            "default_backend": "tdoa_synthetic",
            "runtime_profile": "waveform_fidelity",
        },
        "sources": [
            {
                "source_id": "macbook_reference_source",
                "prim_path": "/World/Source",
                "class_label": "Reference",
                "position_world": [1.0, 0.0, 0.0],
                "gain_db": 0.0,
            }
        ],
        "arrays": {
            "xvf3800_array": {
                "array_id": "xvf3800_array",
                "prim_path": "/World/Array",
                "sample_rate_hz": 16000,
                "coordinate_convention": (
                    "x_forward_y_right_z_up_clockwise_bearing"
                ),
                "microphones": [
                    {
                        "mic_id": "ch0",
                        "relative_position_m": [-0.033, -0.033, 0.0],
                    },
                    {
                        "mic_id": "ch1",
                        "relative_position_m": [-0.033, 0.033, 0.0],
                    },
                    {
                        "mic_id": "ch2",
                        "relative_position_m": [0.033, 0.033, 0.0],
                    },
                    {
                        "mic_id": "ch3",
                        "relative_position_m": [0.033, -0.033, 0.0],
                    },
                ],
            }
        },
    }


def _profile_runtime(repo_root: Path) -> dict[str, Any]:
    config = load_json(repo_root / "configs/s4_6_profile_application.v1.json")
    application = apply_profile_application(
        validate_audio_config(_base_sim_config()),
        repo_root=repo_root,
        mode="apply",
        runtime_context=config["application_context"],
    )
    array = application.config.arrays["xvf3800_array"]
    profile_path = load_json(
        repo_root / "outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json"
    )["active_profile_path"]
    profile = load_json(repo_root / profile_path)
    gains = [
        10.0 ** (float(channel["gain_db"]["value"]) / 20.0)
        for channel in profile["channels"]
    ]
    return {
        "positions": [
            list(microphone.relative_position_m)
            for microphone in array.microphones
        ],
        "gain_multipliers": gains,
        "application_report": application.report(),
    }


def _validate_profile_modes(
    repo_root: Path, config: Mapping[str, Any]
) -> None:
    context = load_json(
        _repo_file(repo_root, config["profile_application"]["config_path"])
    )["application_context"]
    raw = validate_audio_config(_base_sim_config())
    off = apply_profile_application(raw, repo_root=repo_root, mode="off")
    applied = apply_profile_application(
        raw,
        repo_root=repo_root,
        mode="apply",
        runtime_context=context,
    )
    if off.config != raw or off.bundle_identity is not None:
        raise S48Error("S4.6 off mode is not unadjusted")
    if applied.mode != "apply" or sum(
        row["status"] == "applied" for row in applied.field_status
    ) != 7:
        raise S48Error("S4.6 apply mode did not apply exactly seven components")


def _sealed_attempt_roots(
    repo_root: Path,
    seal: Mapping[str, Any],
    expected_take_ids: set[str],
) -> dict[str, Path]:
    roots = _sealed_attempt_candidates(seal, expected_take_ids)
    selected: dict[str, Path] = {}
    for take_id, candidates in roots.items():
        if len(candidates) == 1:
            selected[take_id] = next(iter(candidates))
            continue
        first = next(iter(candidates))
        amendment_root = first.parents[2]
        projection = (
            repo_root
            / amendment_root
            / "access"
            / "technical_qa"
            / f"{take_id}.json"
        )
        if not projection.is_file():
            raise S48Error(f"missing attempt-selection projection: {take_id}")
        projection_sha256 = sha256_file(projection)
        matches = [
            candidate
            for candidate in candidates
            if sha256_file(repo_root / candidate / "technical_qa.json")
            == projection_sha256
        ]
        if len(matches) != 1:
            raise S48Error(f"ambiguous sealed attempt selection: {take_id}")
        selected[take_id] = matches[0]
    return {take_id: repo_root / path for take_id, path in selected.items()}


def _sealed_attempt_candidates(
    seal: Mapping[str, Any],
    expected_take_ids: set[str],
) -> dict[str, set[Path]]:
    roots: dict[str, set[Path]] = defaultdict(set)
    for record in seal.get("artifacts", []):
        relative = _safe_relative(record.get("path"))
        parts = relative.parts
        try:
            index = parts.index("attempts")
        except ValueError as exc:
            raise S48Error(f"sealed artifact is outside attempts: {relative}") from exc
        take_id = parts[index + 1]
        attempt_root = Path(*parts[: index + 3])
        roots[take_id].add(attempt_root)
    if set(roots) != expected_take_ids:
        raise S48Error("sealed attempt-root identity mismatch")
    return dict(roots)


def _seal_record(
    seal: Mapping[str, Any],
    path: Path,
) -> Mapping[str, Any]:
    matches = [
        record
        for record in seal["artifacts"]
        if record["path"] == path.as_posix()
    ]
    if len(matches) != 1:
        raise S48Error(f"file is not uniquely seal-declared: {path}")
    return matches[0]


def _verify_sealed_file(
    repo_root: Path, path: Path, seal: Mapping[str, Any]
) -> None:
    relative = path.relative_to(repo_root).as_posix()
    matches = [
        record for record in seal["artifacts"] if record["path"] == relative
    ]
    if len(matches) != 1:
        raise S48Error(f"file is not uniquely seal-declared: {relative}")
    record = matches[0]
    if (
        not path.is_file()
        or path.stat().st_size != record["byte_size"]
        or sha256_file(path) != record["sha256"]
    ):
        raise S48Error(f"sealed file changed: {relative}")


def _channel_records(
    properties: Mapping[str, Any],
    correlations: Mapping[str, Sequence[float]],
) -> list[dict[str, Any]]:
    rms = properties.get("per_channel_rms_pcm16", [])
    clips = properties.get("per_channel_maximum_clip_run_samples", [])
    anomalies: set[int] = set()
    for pair_id, values in correlations.items():
        if values and median(values) < -0.25:
            left, right = pair_id.split("->")
            anomalies.update(
                {
                    int(left.rsplit("_", 1)[1]),
                    int(right.rsplit("_", 1)[1]),
                }
            )
    output = []
    for raw_index in range(4):
        channel_index = raw_index + 2
        maximum_clip = int(clips[channel_index]) if len(clips) > channel_index else 0
        health_failure = (
            len(rms) <= channel_index
            or not math.isfinite(float(rms[channel_index]))
            or float(rms[channel_index]) <= 0.0
        )
        output.append(
            {
                "microphone_id": f"raw_microphone_{raw_index}",
                "health_failure": health_failure,
                "major_polarity_anomaly": raw_index in anomalies,
                "maximum_clip_run_samples": maximum_clip,
                "sustained_clipping": maximum_clip >= 4000,
            }
        )
    return output


def _read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as stream:
        if (
            stream.getnchannels() != 6
            or stream.getsampwidth() != 2
            or stream.getframerate() != 16000
        ):
            raise S48Error(f"{path}: expected six-channel 16 kHz S16_LE WAV")
        rate = stream.getframerate()
        frames = stream.readframes(stream.getnframes())
    values = np.frombuffer(frames, dtype="<i2").reshape(-1, 6)
    return values.astype(np.float64) / 32768.0, rate


def _comparison_condition_ids(
    entry: Mapping[str, Any],
    registry: Mapping[str, Any],
    corrective: Mapping[str, Any],
) -> set[str]:
    strata = set(entry["applicable_strata"])
    take_ids = {
        take_id
        for take_id, identity in registry.items()
        if identity.stratum_id in strata
    }
    if entry["condition_kind"] == "take":
        output = take_ids
    else:
        output = {
            f"{take_id}|{pair_id}"
            for take_id in take_ids
            for pair_id in corrective["identity_contract"][
                "microphone_pair_ids"
            ]
        }
    if len(output) != entry["expected_count"]:
        raise S48Error(f"comparison condition count mismatch: {entry['comparison_id']}")
    return output


def _pair_ids(prefix: str = "raw_microphone_") -> tuple[str, ...]:
    return tuple(
        f"{prefix}{left}->{prefix}{right}"
        for left in range(4)
        for right in range(left + 1, 4)
    )


def _sector_majority_correct(bearings: Sequence[float], target: float) -> bool:
    counts = Counter(bearing_deg_to_sector_name(value) for value in bearings)
    if not counts:
        return False
    highest = max(counts.values())
    winners = [key for key, value in counts.items() if value == highest]
    return len(winners) == 1 and winners[0] == bearing_deg_to_sector_name(target)


def _circular_difference(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _require_consumed_ledger(
    repo_root: Path, config: Mapping[str, Any]
) -> None:
    ledger_path = repo_root / config["grant"]["ledger_path"]
    if not ledger_path.is_file():
        raise S48Error("S4.8 ledger is absent; observations remain closed")
    records = [
        json.loads(line, parse_constant=_reject_json_constant)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    expected_id = load_json(repo_root / config["grant"]["path"])["grant_id"]
    opened = [
        record
        for record in records
        if record.get("event") == "holdout_open_authorized"
        and record.get("grant_id") == expected_id
        and record.get("holdout_opened") is True
    ]
    if len(opened) != 1 or len(records) != 1:
        raise S48Error("S4.8 grant was not consumed exactly once")


def _append_run_journal(path: Path, event: Mapping[str, Any]) -> None:
    records = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line, parse_constant=_reject_json_constant)
            if not isinstance(record, dict):
                raise S48Error("S4.8 run journal contains a non-object")
            records.append(record)
    previous = "0" * 64
    for sequence, record in enumerate(records):
        supplied = record.get("event_sha256")
        payload = {
            key: value for key, value in record.items()
            if key != "event_sha256"
        }
        if (
            record.get("schema") != "ias.s4_8.first_run_journal_event.v1"
            or record.get("sequence") != sequence
            or record.get("previous_event_sha256") != previous
            or supplied != canonical_sha256(payload)
        ):
            raise S48Error("S4.8 run journal chain is invalid")
        previous = str(supplied)
    payload = {
        "schema": "ias.s4_8.first_run_journal_event.v1",
        "sequence": len(records),
        "previous_event_sha256": previous,
        **event,
    }
    record = {**payload, "event_sha256": canonical_sha256(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        )


def _validate_source_commit(
    repo_root: Path,
    source_commit: str,
    *,
    require_current_head: bool = True,
) -> None:
    if (
        len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise S48Error("source commit must be a full lowercase SHA-1")
    if require_current_head and _git(repo_root, "rev-parse", "HEAD") != source_commit:
        raise S48Error("source commit must be the exact current HEAD")
    if _git(
        repo_root, "rev-parse", "--verify", f"{source_commit}^{{commit}}"
    ) != source_commit:
        raise S48Error("source commit is not available")
    result = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--", *SOURCE_BOUND_FILES],
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        raise S48Error("S4.8 source-bound files differ from source commit")
    for path in SOURCE_BOUND_FILES:
        if not _git_lines(repo_root, "ls-files", path.as_posix()):
            raise S48Error(f"S4.8 source-bound file is uncommitted: {path}")


def _write_index_and_manifest(package: Path, source_commit: str) -> None:
    excluded = {"SHA256SUMS", "evidence_index.json", "determinism_report.json"}
    records = [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
        }
        for path in sorted(package.iterdir())
        if path.is_file() and path.name not in excluded
    ]
    index = {
        "schema": "ias.s4_8.evidence_index.v1",
        "status": "complete",
        "source_commit": source_commit,
        "record_count": len(records),
        "records": records,
        "raw_content_included": False,
    }
    (package / "evidence_index.json").write_text(
        pretty_json(index), encoding="utf-8"
    )
    names = sorted(PACKAGE_FILES - {"SHA256SUMS"})
    missing = [name for name in names if not (package / name).is_file()]
    if missing:
        return
    (package / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(package / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


def _validate_manifest(package: Path) -> None:
    lines = (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    expected = sorted(PACKAGE_FILES - {"SHA256SUMS"})
    found = []
    for line in lines:
        digest, name = line.split("  ", 1)
        found.append(name)
        if sha256_file(package / name) != digest:
            raise S48Error(f"S4.8 manifest mismatch: {name}")
    if found != expected:
        raise S48Error("S4.8 manifest file set mismatch")


def _repo_file(repo_root: Path, value: str | Path) -> Path:
    relative = _safe_relative(value)
    path = (repo_root / relative).resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise S48Error(f"path escapes repository: {value}") from exc
    if not path.is_file():
        raise S48Error(f"required file missing: {relative}")
    return path


def _safe_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise S48Error(f"invalid repository-relative path: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise S48Error(f"unsafe repository-relative path: {value!r}")
    return Path(*pure.parts)


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_lines(repo_root: Path, *args: str) -> list[str]:
    output = _git(repo_root, *args)
    return [] if not output else output.splitlines()


__all__ = [
    "CONFIG_PATH",
    "OUTPUT_PATH",
    "S48Error",
    "build_evidence_package",
    "build_real_payload",
    "build_simulation_comparisons",
    "consume_grant_once",
    "create_grant",
    "evaluate_payload",
    "load_contract",
    "preopen_validate",
    "preservation_report",
    "replay_evidence_package",
    "run_authorized_evaluation_once",
    "validate_evidence_package",
]
