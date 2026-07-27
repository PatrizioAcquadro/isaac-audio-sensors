"""S4.8 held-out functional sim-to-real evaluation.

The pre-opening functions authenticate only tracked contracts and sealed
artifact bytes. Scientific observation functions are separate, explicit, and
require an already-consumed purpose-bound grant.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import importlib.metadata
import itertools
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
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
    validate_ledger,
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
TERMINAL_FAILURE_PROFILE = "terminal_failure.v1"
FULL_EVIDENCE_PROFILE = "full_evidence.v1"
RUNTIME_DISTRIBUTIONS = (
    ("isaac-audio-sensors", "isaac_audio_sensors"),
    ("jsonschema", "jsonschema"),
    ("numpy", "numpy"),
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
RESULT_DEPENDENCY_ROOTS = (
    Path("src/isaac_audio_sensors"),
    Path("configs"),
    Path("outputs/isaac_audio_sensors/S4"),
    Path("docs/schemas"),
)
RESULT_DEPENDENCY_FILES = (
    Path("pyproject.toml"),
    CONFIG_PATH,
    SCHEMA_PATH,
    SPEC_PATH,
    Path("scripts/run_s4_8.py"),
    Path("scripts/validate_s4_8.py"),
    Path("scripts/replay_s4_8.py"),
)
IMPORT_SHADOW_NAMES = frozenset(
    {
        "hashlib",
        "importlib",
        "itertools",
        "json",
        "jsonschema",
        "math",
        "numpy",
        "subprocess",
        "time",
        "wave",
    }
)
PRESERVATION_BASELINE_COMMIT = "ab81af2e521661294d107d3ca28c7b30c581065c"
PRESERVATION_ROOT = Path("outputs/isaac_audio_sensors/S4")


class S48Error(RuntimeError):
    """A located S4.8 contract, access, analysis, or evidence failure."""


class S48PartialAnalysisError(S48Error):
    """A terminal analysis error retaining every completed/opened observation."""

    def __init__(
        self,
        message: str,
        *,
        payload: dict[str, Any],
        observation_inventory: list[dict[str, Any]],
        cause: Exception,
    ) -> None:
        super().__init__(message)
        self.payload = payload
        self.observation_inventory = observation_inventory
        self.cause = cause


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
    if (
        seal.get("partition_manifest_sha256")
        != config["holdout"]["split_plan_sha256"]
    ):
        raise S48Error("holdout seal split-plan identity mismatch")
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
        "split_plan_sha256": config["holdout"]["split_plan_sha256"],
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
        "split_plan_sha256": preopen["split_plan_sha256"],
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
    ledger_path = root / config["grant"]["ledger_path"]
    journal_path = root / config["evidence"]["run_journal_path"]
    transition = ledger_path.parent
    if journal_path.parent != transition:
        raise S48Error(
            "S4.8 ledger and journal must share one atomic transition directory"
        )
    lock_path = transition.parent / ".s4_8_opening_transition.lock"
    with _exclusive_transition_lock(lock_path):
        grant = load_json(grant_path)
        expected_id = config["grant"]["grant_id_template"].format(
            source_commit=source_commit
        )
        if grant.get("grant_id") != expected_id:
            raise S48Error(
                "grant is not bound to the exact evaluator source commit"
            )
        if transition.exists():
            raise S48Error(
                "S4.8 opening transition already claimed; retry forbidden"
            )
        transition.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=".opening_transition.",
                suffix=".staging",
                dir=transition.parent,
            )
        )
        try:
            staged_ledger = staging / ledger_path.name
            staged_journal = staging / journal_path.name
            result = consume_s4_8_grant(
                grant_path,
                seal_path=_repo_file(root, config["holdout"]["seal_path"]),
                split_plan_sha256=config["holdout"]["split_plan_sha256"],
                prerequisite_path=_repo_file(
                    root, config["prerequisite"]["path"]
                ),
                ledger_path=staged_ledger,
                event_time_utc=event_time_utc,
            )
            if (
                result.get("allowed") is not True
                or result.get("mode") != "S4.8_evaluation"
            ):
                raise S48Error("canonical interlock did not authorize S4.8")
            records = _opening_journal_records(
                source_commit=source_commit,
                event_time_utc=event_time_utc,
                ledger_event=result["ledger_event"],
            )
            encoded = "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":"))
                + "\n"
                for record in records
            )
            _atomic_write_text(staged_journal, encoded)
            directory_fd = os.open(staging, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            os.replace(staging, transition)
            parent_fd = os.open(transition.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return {**result, "journal_records": records}


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
    if journal_path.exists():
        records = _load_run_journal(journal_path)
        if (
            any(
                record.get("event") == "first_run_finalization_prepared"
                for record in records
            )
            and not any(
                record.get("event") == "first_run_terminal"
                for record in records
            )
        ):
            _recover_pending_finalization(
                root,
                config=config,
                source_commit=source_commit,
            )
        raise S48Error("first S4.8 result already exists; automatic retry forbidden")
    if derived_path.exists() or output.exists():
        raise S48Error("first S4.8 result already exists; automatic retry forbidden")
    preopen_validate(
        root,
        source_commit=source_commit,
        require_access_paths_absent=False,
    )
    consumption = consume_grant_once(
        root, source_commit=source_commit, event_time_utc=event_time_utc
    )
    run_failure: dict[str, Any] | None = None
    try:
        payload, observation_inventory = build_real_payload(root)
    except S48PartialAnalysisError as exc:
        payload = exc.payload
        observation_inventory = exc.observation_inventory
        run_failure = _run_failure_record(
            stage="observation_analysis",
            error=exc.cause,
        )
    except Exception as exc:
        payload = _input_rejection_payload(root)
        observation_inventory = _input_rejection_inventory(root, exc)
        run_failure = _run_failure_record(
            stage="observation_input",
            error=exc,
        )
    evaluation = evaluate_payload(payload, repo_root=root)
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
            "opening_event_count": len(consumption["journal_records"]),
            "opening_head_sha256": consumption["journal_records"][-1][
                "event_sha256"
            ],
            "terminal_event_required": True,
        },
        "observation_inventory": observation_inventory,
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "evaluation": evaluation,
        "run_failure": run_failure,
        "runtime_provenance": _runtime_dependency_provenance(),
    }
    _atomic_write_text(derived_path, pretty_json(derived))
    derived, package_result = _finalize_first_run(
        root,
        config=config,
        derived=derived,
        source_commit=source_commit,
        event_time_utc=event_time_utc,
    )
    evaluation = dict(derived["evaluation"])
    run_failure = derived.get("run_failure")
    terminal_status = package_result["status"]
    _validate_terminal_journal(
        journal_path,
        source_commit=source_commit,
        expected_status=terminal_status,
        expected_ledger_event_sha256=consumption["ledger_event"][
            "event_sha256"
        ],
    )
    return _run_outcome(
        evaluation=evaluation,
        run_failure=run_failure,
        package_result=package_result,
    )


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
    inventory = _initial_observation_inventory(
        root,
        seal=seal,
        registry=registry,
        attempt_candidates=attempt_candidates,
        attempt_roots=attempt_roots,
    )
    records_by_root = {
        record["attempt_root"]: record for record in inventory
    }
    simulation = build_simulation_comparisons(root)
    for take_id in sorted(registry):
        identity = registry[take_id]
        attempt_root = attempt_roots[take_id]
        relative_root = attempt_root.relative_to(root).as_posix()
        progress_record = records_by_root[relative_root]
        progress_record["scientific_observation_opened"] = True
        try:
            take, record = _analyze_real_take(
                root,
                attempt_root,
                identity,
                profile=profile,
                seal=seal,
            )
        except Exception as exc:
            progress_record.update(
                {
                    "analysis_completed": False,
                    "failed": True,
                    "failure_reasons": ["observation_analysis_failed"],
                    "rejected": True,
                    "scientific_observations_derived": False,
                    "terminal_error_type": type(exc).__name__,
                    "terminal_error": str(exc),
                }
            )
            partial_payload = _partial_payload(
                config,
                takes=takes,
                simulation=simulation,
            )
            inventory.sort(key=lambda item: item["attempt_root"])
            raise S48PartialAnalysisError(
                f"{take_id}: observation analysis failed after "
                f"{len(takes)} completed takes",
                payload=partial_payload,
                observation_inventory=inventory,
                cause=exc,
            ) from exc
        takes.append(take)
        progress_record.update(record)
        progress_record.update(
            {
                "selected_for_evaluation": True,
                "scientific_observation_opened": True,
                "scientific_observations_derived": True,
                "analysis_completed": True,
            }
        )
    payload = _partial_payload(config, takes=takes, simulation=simulation)
    inventory.sort(key=lambda record: record["attempt_root"])
    return payload, inventory


def _initial_observation_inventory(
    repo_root: Path,
    *,
    seal: Mapping[str, Any],
    registry: Mapping[str, Any],
    attempt_candidates: Mapping[str, set[Path]],
    attempt_roots: Mapping[str, Path],
) -> list[dict[str, Any]]:
    """Create the complete inventory before the first observation is opened."""

    records: list[dict[str, Any]] = []
    for take_id in sorted(registry):
        selected = attempt_roots[take_id]
        for candidate in sorted(attempt_candidates[take_id]):
            is_selected = repo_root / candidate == selected
            wav_record = _seal_record(
                seal, candidate / "raw/respeaker_audio.wav"
            )
            qa_record = _seal_record(seal, candidate / "technical_qa.json")
            records.append(
                {
                    "planned_take_id": take_id,
                    "attempt_root": candidate.as_posix(),
                    "wav_sha256": wav_record["sha256"],
                    "technical_qa_sha256": qa_record["sha256"],
                    "window_count": None,
                    "failed": not is_selected,
                    "failure_reasons": (
                        []
                        if is_selected
                        else ["predeclared_replacement_attempt_not_selected"]
                    ),
                    "rejected": not is_selected,
                    "excluded": False,
                    "selected_for_evaluation": is_selected,
                    "scientific_observation_opened": False,
                    "scientific_observations_derived": False,
                    "analysis_completed": False,
                    "av_analysis": None,
                }
            )
    return records


def _partial_payload(
    config: Mapping[str, Any],
    *,
    takes: Sequence[Mapping[str, Any]],
    simulation: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "ias.s4_7.corrective_metrics.v4",
        "contract": {
            "config_sha256": config["criteria"]["corrective_config_sha256"],
            "bound_holdout_id": config["holdout"]["bound_holdout_id"],
            "seal_payload_sha256": config["holdout"]["seal_payload_sha256"],
            "planned_take_count": 47,
        },
        "takes": [dict(take) for take in takes],
        "sim_vs_real": [dict(item) for item in simulation],
    }


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


def _input_rejection_payload(repo_root: Path) -> dict[str, Any]:
    """Create a frozen-identity payload that the evaluator rejects closed."""

    config = load_contract(repo_root)
    return {
        "schema": "ias.s4_7.corrective_metrics.v4",
        "contract": {
            "config_sha256": config["criteria"]["corrective_config_sha256"],
            "bound_holdout_id": config["holdout"]["bound_holdout_id"],
            "seal_payload_sha256": config["holdout"]["seal_payload_sha256"],
            "planned_take_count": 47,
        },
        "takes": [],
        "sim_vs_real": [],
    }


def _input_rejection_inventory(
    repo_root: Path, error: Exception
) -> list[dict[str, Any]]:
    """Retain all sealed attempts when observation derivation rejects input."""

    config = load_contract(repo_root)
    seal = load_json(_repo_file(repo_root, config["holdout"]["seal_path"]))
    registry = build_identity_registry(repo_root)
    candidates = _sealed_attempt_candidates(seal, set(registry))
    selected = _sealed_attempt_roots(repo_root, seal, set(registry))
    records: list[dict[str, Any]] = []
    for take_id in sorted(candidates):
        for candidate in sorted(candidates[take_id]):
            records.append(
                {
                    "planned_take_id": take_id,
                    "attempt_root": candidate.as_posix(),
                    "selected_for_evaluation": (
                        repo_root / candidate == selected[take_id]
                    ),
                    "rejected": True,
                    "excluded": False,
                    "failed": True,
                    "failure_reasons": [
                        "evaluation_input_contract_rejected"
                    ],
                    "scientific_observations_derived": False,
                    "terminal_error_type": type(error).__name__,
                    "terminal_error": str(error),
                }
            )
    return records


def _run_failure_record(*, stage: str, error: Exception) -> dict[str, Any]:
    return {
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "terminal": True,
        "automatic_retry_forbidden": True,
    }


def _recomputed_evaluation(
    repo_root: Path, derived: Mapping[str, Any]
) -> dict[str, Any]:
    payload = derived.get("payload")
    if not isinstance(payload, Mapping):
        raise S48Error("S4.8 derived payload is missing or invalid")
    expected_payload_sha = derived.get("payload_sha256")
    actual_payload_sha = canonical_sha256(payload)
    if expected_payload_sha is not None and expected_payload_sha != actual_payload_sha:
        raise S48Error("S4.8 preserved observation payload hash mismatch")
    recomputed = evaluate_payload(payload, repo_root=repo_root)
    if derived.get("evaluation") != recomputed:
        raise S48Error(
            "S4.8 preserved evaluation contradicts recomputation from payload"
        )
    return recomputed


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


def _run_outcome(
    *,
    evaluation: Mapping[str, Any],
    run_failure: Mapping[str, Any] | None,
    package_result: Mapping[str, Any],
) -> dict[str, Any]:
    passed = (
        package_result.get("status") == "passed"
        and run_failure is None
        and evaluation.get("readiness_passed") is True
    )
    return {
        "schema": "ias.s4_8.authorized_run_outcome.v1",
        "status": "passed" if passed else "failed",
        "readiness_passed": passed,
        "scientific_readiness_passed": (
            evaluation.get("readiness_passed") is True
        ),
        "failed_gating_criteria": evaluation.get(
            "failed_gating_criteria", []
        ),
        "run_failure": None if run_failure is None else dict(run_failure),
        "evaluation": dict(evaluation),
        "evidence": dict(package_result),
        "automatic_retry_forbidden": True,
    }


def _finalization_staging_path(output: Path) -> Path:
    return output.parent / f".{output.name}.first-run-finalization.v1"


def _finalize_first_run(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    derived: dict[str, Any],
    source_commit: str,
    event_time_utc: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stage one package, prepare the journal, then publish and terminalize."""

    root = repo_root.resolve()
    output = root / config["evidence"]["output_path"]
    derived_path = root / config["evidence"]["derived_input_path"]
    journal_path = root / config["evidence"]["run_journal_path"]
    staging = _finalization_staging_path(output)
    if output.exists() or staging.exists():
        raise S48Error("S4.8 finalization destination already exists")
    _validate_source_commit(root, source_commit, require_current_head=True)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    prepared: dict[str, Any] | None = None
    try:
        try:
            package_result = _build_evidence_package_in_place(
                root,
                derived,
                destination=staging,
                source_commit=source_commit,
            )
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            derived = {
                **derived,
                "run_failure": _run_failure_record(
                    stage="evidence_packaging",
                    error=exc,
                ),
            }
            _atomic_write_text(derived_path, pretty_json(derived))
            staging.mkdir()
            package_result = _build_terminal_failure_package_in_place(
                root,
                derived,
                destination=staging,
                source_commit=source_commit,
            )
        prepared = {
            "event": "first_run_finalization_prepared",
            "event_time_utc": event_time_utc,
            "source_commit": source_commit,
            "terminal_status": package_result["status"],
            "readiness_passed": package_result["status"] == "passed",
            "scientific_readiness_passed": (
                derived["evaluation"].get("readiness_passed") is True
            ),
            "failed_gating_criteria": derived["evaluation"].get(
                "failed_gating_criteria", []
            ),
            "run_failure": derived.get("run_failure"),
            "derived_input_sha256": sha256_file(derived_path),
            "evidence_manifest_sha256": package_result["manifest_sha256"],
            "staging_path": staging.relative_to(root).as_posix(),
            "output_path": output.relative_to(root).as_posix(),
            "automatic_retry_forbidden": True,
        }
        _append_run_journal(journal_path, prepared)
        os.replace(staging, output)
        _fsync_directory(output.parent)
        _append_run_journal(
            journal_path,
            _terminal_event_from_prepared(prepared),
        )
    except Exception as exc:
        records = _load_run_journal(journal_path)
        if prepared is not None and any(
            item.get("event") == "first_run_finalization_prepared"
            for item in records
        ):
            return _finalize_transition_failure(
                root,
                config=config,
                derived=derived,
                source_commit=source_commit,
                event_time_utc=event_time_utc,
                error=exc,
            )
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return (
        derived,
        {
            **package_result,
            "output": output.as_posix(),
        },
    )


def _finalize_transition_failure(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    derived: dict[str, Any],
    source_commit: str,
    event_time_utc: str,
    error: Exception,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Downgrade an uncommitted publication transaction to terminal FAILED."""

    output = repo_root / config["evidence"]["output_path"]
    derived_path = repo_root / config["evidence"]["derived_input_path"]
    journal_path = repo_root / config["evidence"]["run_journal_path"]
    staging = _finalization_staging_path(output)
    archive = derived_path.parent / "provisional_evidence.v1"
    if archive.exists():
        raise S48Error("S4.8 provisional evidence archive already exists")
    candidates = [path for path in (output, staging) if path.exists()]
    if len(candidates) != 1:
        raise S48Error(
            "S4.8 finalization failure has no unique provisional package"
        )
    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidates[0], archive)
    _fsync_directory(archive.parent)
    failure = _run_failure_record(
        stage="finalization_publication",
        error=error,
    )
    if derived.get("run_failure") is not None:
        failure["prior_run_failure"] = derived["run_failure"]
    derived = {**derived, "run_failure": failure}
    _atomic_write_text(derived_path, pretty_json(derived))
    staging.mkdir()
    package_result = _build_terminal_failure_package_in_place(
        repo_root,
        derived,
        destination=staging,
        source_commit=source_commit,
    )
    replacement = {
        "event": "first_run_finalization_failed",
        "event_time_utc": event_time_utc,
        "source_commit": source_commit,
        "terminal_status": "failed",
        "readiness_passed": False,
        "scientific_readiness_passed": (
            derived["evaluation"].get("readiness_passed") is True
        ),
        "failed_gating_criteria": derived["evaluation"].get(
            "failed_gating_criteria", []
        ),
        "run_failure": failure,
        "derived_input_sha256": sha256_file(derived_path),
        "evidence_manifest_sha256": package_result["manifest_sha256"],
        "staging_path": staging.relative_to(repo_root).as_posix(),
        "output_path": output.relative_to(repo_root).as_posix(),
        "provisional_evidence_path": archive.relative_to(
            repo_root
        ).as_posix(),
        "automatic_retry_forbidden": True,
    }
    _append_run_journal(journal_path, replacement)
    os.replace(staging, output)
    _fsync_directory(output.parent)
    _append_run_journal(
        journal_path,
        _terminal_event_from_prepared(replacement),
    )
    return (
        derived,
        {
            **package_result,
            "output": output.as_posix(),
        },
    )


def _terminal_event_from_prepared(
    prepared: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "event": "first_run_terminal",
        "event_time_utc": prepared["event_time_utc"],
        "source_commit": prepared["source_commit"],
        "terminal_status": prepared["terminal_status"],
        "readiness_passed": prepared["readiness_passed"],
        "scientific_readiness_passed": prepared[
            "scientific_readiness_passed"
        ],
        "failed_gating_criteria": prepared["failed_gating_criteria"],
        "run_failure": prepared["run_failure"],
        "derived_input_sha256": prepared["derived_input_sha256"],
        "evidence_manifest_sha256": prepared[
            "evidence_manifest_sha256"
        ],
        "automatic_retry_forbidden": True,
    }


def _recover_pending_finalization(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    """Commit an already-prepared package without rerunning analysis/builders."""

    root = repo_root.resolve()
    journal_path = root / config["evidence"]["run_journal_path"]
    records = _load_run_journal(journal_path)
    prepared_records = [
        record
        for record in records
        if record.get("event")
        in {
            "first_run_finalization_prepared",
            "first_run_finalization_failed",
        }
    ]
    if not prepared_records or len(prepared_records) > 2:
        raise S48Error("S4.8 pending finalization record is invalid")
    prepared = prepared_records[-1]
    if prepared.get("source_commit") != source_commit:
        raise S48Error("S4.8 pending finalization source commit mismatch")
    output = root / _safe_relative(prepared["output_path"])
    staging = root / _safe_relative(prepared["staging_path"])
    if output.exists() and staging.exists():
        raise S48Error("S4.8 pending finalization has two package candidates")
    if staging.exists():
        if sha256_file(staging / "SHA256SUMS") != prepared.get(
            "evidence_manifest_sha256"
        ):
            raise S48Error("S4.8 staged finalization manifest mismatch")
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, output)
        _fsync_directory(output.parent)
    if not output.is_dir():
        raise S48Error("S4.8 prepared finalization package is unavailable")
    if sha256_file(output / "SHA256SUMS") != prepared.get(
        "evidence_manifest_sha256"
    ):
        raise S48Error("S4.8 published finalization manifest mismatch")
    validation = validate_evidence_package(output, repo_root=root)
    if validation["final_status"] != prepared.get("terminal_status"):
        raise S48Error("S4.8 prepared finalization status mismatch")
    _append_run_journal(
        journal_path,
        _terminal_event_from_prepared(prepared),
    )
    return validation


def _build_terminal_failure_package_in_place(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    destination: Path,
    source_commit: str,
    validate_result: bool = True,
) -> dict[str, Any]:
    """Build terminal-failure evidence without calling the full package builder."""

    root = repo_root.resolve()
    run_failure = derived.get("run_failure")
    if not isinstance(run_failure, Mapping):
        raise S48Error("terminal-failure package requires a run failure")
    evaluation = _recomputed_evaluation(root, derived)
    payload = dict(derived["payload"])
    takes = payload.get("takes", [])
    if not isinstance(takes, list):
        raise S48Error("terminal-failure payload takes must be a list")
    inventory = derived.get("observation_inventory", [])
    if not isinstance(inventory, list):
        raise S48Error("terminal-failure observation inventory is invalid")
    preservation = preservation_report(root)
    provenance = _provenance_report(
        root,
        derived=derived,
        source_commit=source_commit,
        status="failed",
    )
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
            "completed_take_count": len(takes),
            "run_failure": dict(run_failure),
            "attempt_records": inventory,
            "all_planned_takes_retained": True,
        },
        "final_validation.json": {
            "schema": "ias.s4_8.final_validation.v1",
            "package_profile": TERMINAL_FAILURE_PROFILE,
            "status": "failed",
            "readiness_passed": False,
            "scientific_readiness_passed": (
                evaluation.get("readiness_passed") is True
            ),
            "scientific_evaluation_status": evaluation.get("status"),
            "run_failure": dict(run_failure),
            "terminal": True,
            "automatic_retry_forbidden": True,
            "planned_take_count": 47,
            "completed_take_count": len(takes),
            "historical_preservation_passed": (
                preservation["status"] == "passed"
            ),
            "robustness_status": "not_evaluable",
            "s4_complete": False,
            "s4_9_started": False,
            "later_phases_started": [],
        },
        "preservation_report.json": preservation,
        "provenance.json": provenance,
        "reproduction.json": {
            "schema": "ias.s4_8.reproduction.v1",
            "status": "passed",
            "source_commit": source_commit,
            "package_profile": TERMINAL_FAILURE_PROFILE,
            "scientific_recomputation": "required_exact_from_derived_payload",
            "raw_holdout_reopened": False,
            "grant_reconsumed": False,
        },
        "robustness.json": {
            "schema": "ias.s4_8.robustness.v1",
            "status": "not_evaluable",
            "denominator": 0,
            "gating": False,
            "quantities": [],
        },
        "sim_vs_real.json": {
            "schema": "ias.s4_8.sim_vs_real.v1",
            "status": "partial" if len(takes) < 47 else "complete",
            "comparison_classifications": evaluation.get(
                "comparison_classifications", []
            ),
            "condition_inputs": payload.get("sim_vs_real", []),
            "paths": [
                "real",
                "unadjusted_simulation",
                "adjusted_simulation",
            ],
            "unadjusted_profile_mode": "off",
            "adjusted_profile_mode": "apply",
        },
        "supported_unsupported.json": {
            "schema": "ias.s4_8.supported_unsupported.v1",
            "status": "complete",
            "supported_envelope": "controlled_source_single_room_single_mount",
            "unsupported_due_to_terminal_failure": True,
        },
        "take_inventory.json": {
            "schema": "ias.s4_8.take_inventory.v1",
            "status": "complete",
            "planned_take_count": 47,
            "leakage_group_count": 15,
            "sealed_attempt_count": len(inventory),
            "selected_attempt_count": sum(
                item.get("selected_for_evaluation") is True
                for item in inventory
            ),
            "unselected_attempt_count": sum(
                item.get("selected_for_evaluation") is False
                for item in inventory
            ),
            "opened_attempt_count": sum(
                item.get("scientific_observation_opened") is True
                for item in inventory
            ),
            "derived_attempt_count": sum(
                item.get("scientific_observations_derived") is True
                for item in inventory
            ),
            "completed_take_count": len(takes),
            "unopened_selected_take_count": sum(
                item.get("selected_for_evaluation") is True
                and item.get("scientific_observation_opened") is not True
                for item in inventory
            ),
            "attempt_records": inventory,
            "records": takes,
        },
        "window_results.json": {
            "schema": "ias.s4_8.window_results.v1",
            "status": "partial" if len(takes) < 47 else "complete",
            "record_count": sum(
                len(take.get("bearing_windows", [])) for take in takes
            ),
            "takes": [
                {
                    "planned_take_id": take["identity"]["planned_take_id"],
                    "stratum_id": take["identity"]["stratum_id"],
                    "windows": take.get("bearing_windows", []),
                    "window_summary": take.get("window_summary"),
                }
                for take in takes
            ],
        },
        "determinism_report.json": {
            "schema": "ias.s4_8.determinism.v1",
            "status": "passed",
            "source_commit": source_commit,
            "canonical_file_count": len(PACKAGE_FILES),
            "package_profile": TERMINAL_FAILURE_PROFILE,
            "raw_holdout_reopened": False,
            "grant_reconsumed": False,
            "replay_method": "regenerate_terminal_failure_from_derived_input",
        },
    }
    for name, report in reports.items():
        (destination / name).write_text(pretty_json(report), encoding="utf-8")
    _write_index_and_manifest(destination, source_commit)
    if validate_result:
        _validate_terminal_failure_package(destination, repo_root=root)
    return {
        "status": "failed",
        "output": destination.as_posix(),
        "file_count": len(PACKAGE_FILES),
        "manifest_sha256": sha256_file(destination / "SHA256SUMS"),
        "package_profile": TERMINAL_FAILURE_PROFILE,
    }


def build_evidence_package(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    output: Path,
    source_commit: str,
    require_current_head: bool = True,
) -> dict[str, Any]:
    """Atomically build the package from a recomputed preserved input."""

    return _build_evidence_package_atomic(
        repo_root,
        derived,
        output=output,
        source_commit=source_commit,
        require_current_head=require_current_head,
    )


def _build_evidence_package_atomic(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    output: Path,
    source_commit: str,
    require_current_head: bool,
) -> dict[str, Any]:
    root = repo_root.resolve()
    _validate_source_commit(
        root,
        source_commit,
        require_current_head=require_current_head,
    )
    destination = output if output.is_absolute() else root / output
    if destination.exists():
        raise S48Error(f"refusing to overwrite S4.8 package: {destination}")
    _recomputed_evaluation(root, derived)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".staging",
            dir=destination.parent,
        )
    )
    try:
        result = _build_evidence_package_in_place(
            root,
            derived,
            destination=staging,
            source_commit=source_commit,
        )
        os.replace(staging, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if destination.exists():
            raise S48Error(
                f"atomic S4.8 finalization left an unexpected destination: "
                f"{destination}"
            ) from exc
        raise
    return {**result, "output": destination.as_posix()}


def _build_evidence_package_in_place(
    repo_root: Path,
    derived: Mapping[str, Any],
    *,
    destination: Path,
    source_commit: str,
    validate_result: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    evaluation = _recomputed_evaluation(root, derived)
    payload = dict(derived["payload"])
    takes = payload.get("takes", [])
    if not isinstance(takes, list):
        raise S48Error("S4.8 payload takes must be a list")
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
            "run_failure": derived.get("run_failure"),
            "rejected_attempts": [
                record
                for record in derived.get("observation_inventory", [])
                if record.get("rejected") is True
            ],
            "all_planned_takes_retained": True,
        },
        "preservation_report.json": preservation,
        "provenance.json": _provenance_report(
            root,
            derived=derived,
            source_commit=source_commit,
            status="passed",
        ),
        "reproduction.json": {
            "schema": "ias.s4_8.reproduction.v1",
            "status": "passed",
            "command": (
                "python3 scripts/replay_s4_8.py "
                "--canonical outputs/isaac_audio_sensors/S4/S4.8"
            ),
            "source_commit": source_commit,
            "input": "canonical package reports",
            "scientific_recomputation": "required_exact_from_derived_payload",
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
            "condition_inputs": payload.get("sim_vs_real", []),
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
        "passed"
        if (
            evaluation.get("readiness_passed") is True
            and derived.get("run_failure") is None
        )
        else "failed"
    )
    reports["final_validation.json"] = {
        "schema": "ias.s4_8.final_validation.v1",
        "package_profile": FULL_EVIDENCE_PROFILE,
        "status": final_status,
        "readiness_passed": final_status == "passed",
        "scientific_readiness_passed": (
            evaluation.get("readiness_passed") is True
        ),
        "scientific_evaluation_status": evaluation.get("status"),
        "run_failure": derived.get("run_failure"),
        "terminal": True,
        "automatic_retry_forbidden": True,
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
        "replay_method": "recompute_scientific_evaluation_and_regenerate",
    }
    (destination / "determinism_report.json").write_text(
        pretty_json(deterministic), encoding="utf-8"
    )
    _write_index_and_manifest(destination, source_commit)
    if validate_result:
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
    derived = load_json(package / "derived_evaluation_input.json")
    recomputed = _recomputed_evaluation(repo_root, derived)
    criteria = load_json(package / "criteria_results.json")
    if criteria != recomputed:
        raise S48Error(
            "S4.8 criteria results contradict scientific recomputation"
        )
    final = load_json(package / "final_validation.json")
    if final.get("package_profile") == TERMINAL_FAILURE_PROFILE:
        return _validate_terminal_failure_package(
            package,
            repo_root=repo_root.resolve(),
            regenerate=True,
        )
    expected_overall_readiness = (
        criteria.get("readiness_passed") is True
        and derived.get("run_failure") is None
    )
    if (
        final.get("package_profile") != FULL_EVIDENCE_PROFILE
        or final["readiness_passed"] is not expected_overall_readiness
        or final.get("scientific_readiness_passed") is not (
            criteria.get("readiness_passed") is True
        )
    ):
        raise S48Error("S4.8 final status contradicts criteria")
    expected_final_status = (
        "passed"
        if (
            recomputed.get("readiness_passed") is True
            and derived.get("run_failure") is None
        )
        else "failed"
    )
    if (
        final.get("status") != expected_final_status
        or final.get("run_failure") != derived.get("run_failure")
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
    ):
        raise S48Error("S4.8 terminal final status is contradictory")
    if load_json(package / "robustness.json")["status"] != "not_evaluable":
        raise S48Error("S4.8 robustness must be not_evaluable")
    gating = [
        item for item in criteria.get("criteria", []) if item.get("gating") is True
    ]
    stretch = [
        item for item in criteria.get("criteria", []) if item.get("gating") is False
    ]
    input_rejected = criteria.get("failed_gating_criteria") == [
        "evaluation_input_contract_rejected"
    ]
    if input_rejected:
        if gating or stretch or criteria.get("evaluation_error") in (None, ""):
            raise S48Error("S4.8 input-rejection evidence is incomplete")
    elif len(gating) != 23 or len(stretch) != 6:
        raise S48Error(
            "S4.8 criteria count is not exactly 23 readiness and 6 stretch"
        )
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
    if not isinstance(conditions, list):
        raise S48Error("S4.8 sim-versus-real condition inventory invalid")
    condition_count = sum(len(item.get("conditions", [])) for item in conditions)
    if input_rejected:
        if (
            conditions
            and (len(conditions) != 7 or condition_count != 271)
        ) or sim.get("comparison_classifications"):
            raise S48Error(
                "S4.8 rejected input has inconsistent sim-versus-real records"
            )
    elif len(conditions) != 7 or condition_count != 271:
        raise S48Error("S4.8 sim-versus-real condition inventory mismatch")
    if sim.get("comparison_classifications") != recomputed.get(
        "comparison_classifications"
    ):
        raise S48Error("S4.8 comparison classifications contradict recomputation")
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
    provenance = load_json(package / "provenance.json")
    source_commit = _validate_provenance(
        provenance,
        derived=derived,
        repo_root=repo_root.resolve(),
    )
    if preservation_report(repo_root)["status"] != "passed":
        raise S48Error("historical S4 packages changed")
    with tempfile.TemporaryDirectory(
        prefix="ias-s4-8-validation-regeneration-"
    ) as temporary:
        regenerated = Path(temporary)
        _build_evidence_package_in_place(
            repo_root.resolve(),
            derived,
            destination=regenerated,
            source_commit=source_commit,
            validate_result=False,
        )
        mismatched = [
            name
            for name in sorted(PACKAGE_FILES)
            if (package / name).read_bytes()
            != (regenerated / name).read_bytes()
        ]
        if mismatched:
            raise S48Error(
                "S4.8 reports contradict regeneration from preserved payload: "
                + ", ".join(mismatched)
            )
    return {
        "schema": "ias.s4_8.package_validation.v1",
        "status": "passed",
        "file_count": len(present),
        "manifest_sha256": sha256_file(package / "SHA256SUMS"),
        "readiness_passed": final["readiness_passed"],
        "final_status": final["status"],
        "scientific_recomputed": True,
    }


def _validate_provenance(
    provenance: Mapping[str, Any],
    *,
    derived: Mapping[str, Any],
    repo_root: Path,
) -> str:
    source_commit = provenance.get("source_commit")
    if not isinstance(source_commit, str):
        raise S48Error("S4.8 provenance source commit is invalid")
    _validate_source_commit(
        repo_root,
        source_commit,
        require_current_head=False,
    )
    dependency_records = _result_dependency_records(repo_root, source_commit)
    if (
        provenance.get("result_dependencies") != dependency_records
        or provenance.get("result_dependency_count") != len(dependency_records)
        or provenance.get("result_dependencies_sha256")
        != canonical_sha256(dependency_records)
    ):
        raise S48Error("S4.8 result dependency provenance mismatch")
    expected_runtime = derived.get("runtime_provenance")
    if expected_runtime is None:
        expected_runtime = _runtime_dependency_provenance()
    if (
        provenance.get("runtime") != expected_runtime
        or provenance.get("runtime_sha256")
        != canonical_sha256(expected_runtime)
        or expected_runtime != _runtime_dependency_provenance()
    ):
        raise S48Error("S4.8 runtime dependency provenance mismatch")
    return source_commit


def _validate_terminal_failure_package(
    package: Path,
    *,
    repo_root: Path,
    regenerate: bool = False,
) -> dict[str, Any]:
    package = package.resolve()
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != PACKAGE_FILES:
        raise S48Error("S4.8 terminal-failure package files mismatch")
    _validate_manifest(package)
    index = load_json(package / "evidence_index.json")
    if index.get("record_count") != len(PACKAGE_FILES) - 3:
        raise S48Error("S4.8 terminal-failure evidence index mismatch")
    for record in index.get("records", []):
        path = package / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != record["byte_size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise S48Error(
                f"S4.8 terminal-failure index mismatch: {record['path']}"
            )
    derived = load_json(package / "derived_evaluation_input.json")
    evaluation = _recomputed_evaluation(repo_root, derived)
    criteria = load_json(package / "criteria_results.json")
    final = load_json(package / "final_validation.json")
    run_failure = derived.get("run_failure")
    if (
        criteria != evaluation
        or not isinstance(run_failure, Mapping)
        or final.get("package_profile") != TERMINAL_FAILURE_PROFILE
        or final.get("status") != "failed"
        or final.get("readiness_passed") is not False
        or final.get("scientific_readiness_passed") is not (
            evaluation.get("readiness_passed") is True
        )
        or final.get("run_failure") != run_failure
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
    ):
        raise S48Error("S4.8 terminal-failure result is contradictory")
    inventory = load_json(package / "take_inventory.json")
    attempt_records = derived.get("observation_inventory")
    takes = derived.get("payload", {}).get("takes")
    if (
        not isinstance(attempt_records, list)
        or len(attempt_records) != 48
        or inventory.get("attempt_records") != attempt_records
        or not isinstance(takes, list)
        or inventory.get("records") != takes
        or inventory.get("completed_take_count") != len(takes)
        or inventory.get("selected_attempt_count") != 47
        or inventory.get("unselected_attempt_count") != 1
    ):
        raise S48Error("S4.8 terminal-failure partial inventory mismatch")
    selected = [
        record
        for record in attempt_records
        if record.get("selected_for_evaluation") is True
    ]
    opened = [
        record
        for record in selected
        if record.get("scientific_observation_opened") is True
    ]
    derived_records = [
        record
        for record in selected
        if record.get("scientific_observations_derived") is True
    ]
    if (
        inventory.get("opened_attempt_count") != len(opened)
        or inventory.get("derived_attempt_count") != len(derived_records)
        or inventory.get("unopened_selected_take_count")
        != 47 - len(opened)
        or len(derived_records) != len(takes)
    ):
        raise S48Error("S4.8 terminal-failure progress counts mismatch")
    if load_json(package / "robustness.json").get("status") != "not_evaluable":
        raise S48Error("S4.8 robustness must be not_evaluable")
    authorization = load_json(package / "authorization_access.json")
    ledger_event = authorization.get("ledger_event")
    if (
        authorization.get("grant_consumed_exactly_once") is not True
        or not isinstance(ledger_event, Mapping)
        or ledger_event.get("event_sha256")
        != canonical_sha256(
            {
                key: value
                for key, value in ledger_event.items()
                if key != "event_sha256"
            }
        )
    ):
        raise S48Error("S4.8 terminal-failure access evidence mismatch")
    provenance = load_json(package / "provenance.json")
    source_commit = _validate_provenance(
        provenance,
        derived=derived,
        repo_root=repo_root,
    )
    if preservation_report(repo_root)["status"] != "passed":
        raise S48Error("historical S4 packages changed")
    if regenerate:
        with tempfile.TemporaryDirectory(
            prefix="ias-s4-8-terminal-validation-"
        ) as temporary:
            regenerated = Path(temporary)
            _build_terminal_failure_package_in_place(
                repo_root,
                derived,
                destination=regenerated,
                source_commit=source_commit,
                validate_result=False,
            )
            mismatched = [
                name
                for name in sorted(PACKAGE_FILES)
                if (package / name).read_bytes()
                != (regenerated / name).read_bytes()
            ]
            if mismatched:
                raise S48Error(
                    "S4.8 terminal-failure replay mismatch: "
                    + ", ".join(mismatched)
                )
    return {
        "schema": "ias.s4_8.package_validation.v1",
        "status": "passed",
        "file_count": len(present),
        "manifest_sha256": sha256_file(package / "SHA256SUMS"),
        "readiness_passed": False,
        "final_status": "failed",
        "scientific_recomputed": True,
        "package_profile": TERMINAL_FAILURE_PROFILE,
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
    final = load_json(canonical / "final_validation.json")
    if final.get("package_profile") == TERMINAL_FAILURE_PROFILE:
        output.mkdir(parents=True)
        try:
            _build_terminal_failure_package_in_place(
                repo_root.resolve(),
                derived,
                destination=output,
                source_commit=source_commit,
            )
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise
    else:
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
    grant = load_json(repo_root / config["grant"]["path"])
    expected_id = grant["grant_id"]
    ledger_validation = validate_ledger(
        ledger_path,
        expected_seal_sha256=grant["seal_sha256"],
    )
    if (
        ledger_validation["status"] != "passed"
        or ledger_validation["event_count"] != 1
    ):
        raise S48Error("S4.8 access ledger is not one valid event")
    records = [
        json.loads(line, parse_constant=_reject_json_constant)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    opened = [
        record
        for record in records
        if record.get("event") == "holdout_open_authorized"
        and record.get("grant_id") == expected_id
        and record.get("holdout_opened") is True
    ]
    if len(opened) != 1 or len(records) != 1:
        raise S48Error("S4.8 grant was not consumed exactly once")
    authorization = load_json(
        (repo_root / config["grant"]["path"]).with_name(
            "authorization_record.v1.json"
        )
    )
    journal = _load_run_journal(
        repo_root / config["evidence"]["run_journal_path"]
    )
    if [record.get("event") for record in journal] != [
        "grant_consumed",
        "observation_opening_authorized",
    ]:
        raise S48Error(
            "S4.8 atomic opening transition journal is incomplete"
        )
    if any(
        record.get("source_commit") != authorization.get("source_commit")
        for record in journal
    ):
        raise S48Error("S4.8 opening transition source binding mismatch")
    if any(
        record.get("ledger_event_sha256") != opened[0]["event_sha256"]
        for record in journal
    ):
        raise S48Error("S4.8 opening transition ledger binding mismatch")


def _append_run_journal(path: Path, event: Mapping[str, Any]) -> None:
    records = _load_run_journal(path)
    if records and records[-1].get("event") == "first_run_terminal":
        raise S48Error("S4.8 run journal is terminal; retry forbidden")
    event_name = event.get("event")
    prepared = any(
        record.get("event") == "first_run_finalization_prepared"
        for record in records
    )
    if prepared and event_name not in {
        "first_run_finalization_failed",
        "first_run_terminal",
    }:
        raise S48Error("S4.8 run journal is prepared; retry forbidden")
    if event_name == "first_run_finalization_prepared" and [
        record.get("event") for record in records
    ] != ["grant_consumed", "observation_opening_authorized"]:
        raise S48Error("S4.8 finalization preparation is out of sequence")
    if event_name == "first_run_terminal" and (
        not records
        or records[-1].get("event")
        not in {
            "first_run_finalization_prepared",
            "first_run_finalization_failed",
        }
    ):
        raise S48Error("S4.8 terminal event lacks prepared finalization")
    if event_name == "first_run_finalization_failed" and (
        not records
        or records[-1].get("event") != "first_run_finalization_prepared"
    ):
        raise S48Error("S4.8 failed finalization lacks prepared transaction")
    previous = records[-1]["event_sha256"] if records else "0" * 64
    payload = {
        "schema": "ias.s4_8.first_run_journal_event.v1",
        "sequence": len(records),
        "previous_event_sha256": previous,
        **event,
    }
    record = {**payload, "event_sha256": canonical_sha256(payload)}
    encoded = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
        for item in [*records, record]
    )
    _atomic_write_text(path, encoded)


def _load_run_journal(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise S48Error(f"cannot read S4.8 run journal: {exc}") from exc
        for line in lines:
            try:
                record = json.loads(
                    line, parse_constant=_reject_json_constant
                )
            except (ValueError, json.JSONDecodeError) as exc:
                raise S48Error(f"S4.8 run journal JSON is invalid: {exc}") from exc
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
    return records


def _validate_terminal_journal(
    path: Path,
    *,
    source_commit: str,
    expected_status: str,
    expected_ledger_event_sha256: str,
) -> dict[str, Any]:
    records = _load_run_journal(path)
    events = [record.get("event") for record in records]
    if events not in (
        [
            "grant_consumed",
            "observation_opening_authorized",
            "first_run_finalization_prepared",
            "first_run_terminal",
        ],
        [
            "grant_consumed",
            "observation_opening_authorized",
            "first_run_finalization_prepared",
            "first_run_finalization_failed",
            "first_run_terminal",
        ],
    ):
        raise S48Error("S4.8 run journal is not one complete terminal chain")
    if any(record.get("source_commit") != source_commit for record in records):
        raise S48Error("S4.8 run journal source commit mismatch")
    if any(
        record.get("ledger_event_sha256") != expected_ledger_event_sha256
        for record in records[:2]
    ):
        raise S48Error("S4.8 run journal ledger binding mismatch")
    prepared = records[-2]
    terminal = records[-1]
    if (
        terminal.get("terminal_status") != expected_status
        or terminal.get("automatic_retry_forbidden") is not True
        or any(
            terminal.get(key) != prepared.get(key)
            for key in (
                "source_commit",
                "terminal_status",
                "readiness_passed",
                "scientific_readiness_passed",
                "failed_gating_criteria",
                "run_failure",
                "derived_input_sha256",
                "evidence_manifest_sha256",
            )
        )
    ):
        raise S48Error("S4.8 run journal terminal status mismatch")
    return terminal


def _opening_journal_records(
    *,
    source_commit: str,
    event_time_utc: str,
    ledger_event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    previous = "0" * 64
    records: list[dict[str, Any]] = []
    for event in ("grant_consumed", "observation_opening_authorized"):
        payload = {
            "schema": "ias.s4_8.first_run_journal_event.v1",
            "sequence": len(records),
            "previous_event_sha256": previous,
            "event": event,
            "event_time_utc": event_time_utc,
            "source_commit": source_commit,
            "ledger_event_sha256": ledger_event["event_sha256"],
        }
        record = {**payload, "event_sha256": canonical_sha256(payload)}
        records.append(record)
        previous = record["event_sha256"]
    return records


@contextmanager
def _exclusive_transition_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".staging",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    dependencies = _result_dependency_paths(repo_root, source_commit)
    for path in dependencies:
        current = repo_root / path
        if not current.is_file():
            raise S48Error(f"S4.8 result dependency is missing: {path}")
        committed = _git_blob(repo_root, source_commit, path)
        if current.read_bytes() != committed:
            raise S48Error(
                f"S4.8 result dependency differs from source commit: {path}"
            )
    untracked_python = _git_lines(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        "*.py",
    )
    if untracked_python:
        raise S48Error(
            "uncommitted Python code could shadow result dependencies: "
            + ", ".join(sorted(untracked_python))
        )
    for name in sorted(IMPORT_SHADOW_NAMES):
        for candidate in (
            repo_root / f"{name}.py",
            repo_root / name / "__init__.py",
        ):
            if candidate.is_file():
                raise S48Error(f"import-shadowing file is forbidden: {candidate}")
    _validate_import_origins(repo_root)


def _result_dependency_paths(
    repo_root: Path, source_commit: str
) -> tuple[Path, ...]:
    names = _git_lines(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        source_commit,
    )
    roots = tuple(f"{path.as_posix()}/" for path in RESULT_DEPENDENCY_ROOTS)
    exact = {path.as_posix() for path in RESULT_DEPENDENCY_FILES}
    output_prefix = f"{OUTPUT_PATH.as_posix()}/"
    selected = [
        Path(name)
        for name in names
        if (
            name in exact
            or any(name.startswith(prefix) for prefix in roots)
        )
        and not name.startswith(output_prefix)
    ]
    if not selected:
        raise S48Error("S4.8 result dependency inventory is empty")
    return tuple(sorted(selected))


def _result_dependency_records(
    repo_root: Path, source_commit: str
) -> list[dict[str, Any]]:
    return [
        {
            "path": path.as_posix(),
            "sha256": hashlib.sha256(
                _git_blob(repo_root, source_commit, path)
            ).hexdigest(),
        }
        for path in _result_dependency_paths(repo_root, source_commit)
    ]


def _runtime_dependency_provenance() -> dict[str, Any]:
    distributions = []
    for distribution_name, module_name in RUNTIME_DISTRIBUTIONS:
        module = importlib.import_module(module_name)
        origin_value = getattr(module, "__file__", None)
        if not isinstance(origin_value, str):
            raise S48Error(f"{module_name} runtime module has no file origin")
        origin = Path(origin_value).resolve()
        distributions.append(
            {
                "distribution": distribution_name,
                "version": importlib.metadata.version(distribution_name),
                "module": module_name,
                "module_file_name": origin.name,
                "module_file_sha256": sha256_file(origin),
            }
        )
    return {
        "schema": "ias.s4_8.runtime_provenance.v1",
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "cache_tag": sys.implementation.cache_tag,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "distributions": distributions,
        "declared_runtime_dependencies": [
            "jsonschema>=4.10",
            "numpy>=1.26",
            "tomli>=2; python_version < '3.11'",
        ],
    }


def _provenance_report(
    repo_root: Path,
    *,
    derived: Mapping[str, Any],
    source_commit: str,
    status: str,
) -> dict[str, Any]:
    contract = load_contract(repo_root)
    dependency_records = _result_dependency_records(repo_root, source_commit)
    source_files = [
        {
            "path": path.as_posix(),
            "sha256": sha256_file(repo_root / path),
        }
        for path in SOURCE_BOUND_FILES
    ]
    runtime = derived.get("runtime_provenance")
    if runtime is None:
        runtime = _runtime_dependency_provenance()
    return {
        "schema": "ias.s4_8.provenance.v1",
        "status": status,
        "tool_version": TOOL_VERSION,
        "source_commit": source_commit,
        "contract_path": CONFIG_PATH.as_posix(),
        "contract_sha256": sha256_file(repo_root / CONFIG_PATH),
        "source_bound_files": source_files,
        "source_bound_files_sha256": canonical_sha256(source_files),
        "result_dependency_count": len(dependency_records),
        "result_dependencies": dependency_records,
        "result_dependencies_sha256": canonical_sha256(dependency_records),
        "runtime": runtime,
        "runtime_sha256": canonical_sha256(runtime),
        "prerequisite_sha256": contract["prerequisite"]["sha256"],
        "prerequisite_manifest_sha256": contract["prerequisite"][
            "package_manifest_sha256"
        ],
        "seal_file_sha256": contract["holdout"]["seal_file_sha256"],
        "seal_payload_sha256": contract["holdout"]["seal_payload_sha256"],
        "partition_manifest_sha256": contract["holdout"][
            "partition_manifest_sha256"
        ],
        "split_plan_sha256": contract["holdout"]["split_plan_sha256"],
        "session_manifest_sha256": contract["holdout"][
            "session_manifest_sha256"
        ],
        "scientific_semantics_sha256": contract["prerequisite"][
            "scientific_semantics_sha256"
        ],
        "criteria_v1_config_sha256": contract["criteria"]["v1_config_sha256"],
        "criteria_corrective_03_config_sha256": contract["criteria"][
            "corrective_config_sha256"
        ],
        "criteria_corrective_02_config_sha256": contract["criteria"][
            "delegated_config_sha256"
        ],
        "s4_6_config_sha256": contract["profile_application"][
            "config_sha256"
        ],
        "s4_6_active_pointer_sha256": contract["profile_application"][
            "active_pointer_sha256"
        ],
        "s4_3_effective_config_sha256": contract["analysis"][
            "s4_3_effective_config_sha256"
        ],
        "s4_3_transient_contract_sha256": contract["analysis"][
            "transient_contract_sha256"
        ],
        "s4_6_application_report": _profile_runtime(repo_root)[
            "application_report"
        ],
        "raw_data_tracked": False,
    }


def _git_blob(repo_root: Path, commit: str, path: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path.as_posix()}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise S48Error(
            f"S4.8 result dependency is absent from {commit}: {path}"
        )
    return result.stdout


def _validate_import_origins(repo_root: Path) -> None:
    package_root = (repo_root / "src" / "isaac_audio_sensors").resolve()
    local_module = importlib.import_module("isaac_audio_sensors")
    local_origin = Path(str(local_module.__file__)).resolve()
    try:
        local_origin.relative_to(package_root)
    except ValueError as exc:
        raise S48Error(
            f"isaac_audio_sensors import is shadowed by {local_origin}"
        ) from exc
    for name in ("jsonschema", "numpy"):
        module = importlib.import_module(name)
        origin = Path(str(module.__file__)).resolve()
        try:
            origin.relative_to(repo_root)
        except ValueError:
            continue
        raise S48Error(f"{name} import is shadowed by repository file {origin}")


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
