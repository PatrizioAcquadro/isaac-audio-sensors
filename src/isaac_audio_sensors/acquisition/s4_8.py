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
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, BinaryIO

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
RECOVERY_CONTEXT_NAME = "recovery_context.v1.json"
POST_CONSUMPTION_PROGRESS_NAME = "post_consumption_progress.v2"
POST_CONSUMPTION_PROGRESS_QUARANTINE_NAME = "post_consumption_progress_quarantine.v1"
AUTHORIZATION_RECORD_NAME = "authorization_record.v1.json"
GRANT_PUBLICATION_STAGING_NAME = ".s4_8_grant_publication.v1.staging"
AUTHORIZED_EXECUTION_LOCK_PATH = Path("dataset/.s4_8_authorized_execution.lock")


class _ExecutionLockLease:
    """Revocable capability for one acquired execution-lock descriptor."""

    __slots__ = (
        "_active",
        "_authority",
        "_descriptor",
        "_lock_path",
        "_pid",
        "_repo_root",
        "_stream",
    )

    def __init__(
        self,
        *,
        repo_root: Path,
        lock_path: Path,
        stream: BinaryIO,
        authority: object | None = None,
    ) -> None:
        self._active = True
        self._authority = authority
        self._descriptor = stream.fileno()
        self._lock_path = lock_path
        self._pid = os.getpid()
        self._repo_root = repo_root
        self._stream = stream

    def _revoke(self) -> None:
        self._active = False


def _make_execution_lease_authority() -> tuple[
    Callable[..., _ExecutionLockLease],
    Callable[[_ExecutionLockLease], bool],
]:
    authority = object()

    def issue(
        *,
        repo_root: Path,
        lock_path: Path,
        stream: BinaryIO,
    ) -> _ExecutionLockLease:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _ExecutionLockLease(
            repo_root=repo_root,
            lock_path=lock_path,
            stream=stream,
            authority=authority,
        )

    def validates(lease: _ExecutionLockLease) -> bool:
        return lease._authority is authority

    return issue, validates


(
    _issue_execution_lock_lease,
    _is_issued_execution_lock_lease,
) = _make_execution_lease_authority()
del _make_execution_lease_authority

_ACTIVE_EXECUTION_LEASE: ContextVar[_ExecutionLockLease | None] = ContextVar(
    "s4_8_active_execution_lease",
    default=None,
)
AUTHORIZATION_RECORD_SCHEMA = "ias.s4_8.authorization_record.v1"
AUTHORIZATION_RECORD_FIELDS = frozenset(
    {
        "schema",
        "authorization_id",
        "source_commit",
        "grant_id",
        "grant_path",
        "grant_sha256",
        "ledger_path",
        "irreversible_scientific_action_acknowledged",
    }
)
EVALUATION_STATES = frozenset(
    {
        "not_evaluated",
        "evaluation_failed",
        "evaluation_completed",
    }
)
PROGRESS_STAGE_ORDER = {
    "observation_analysis": 10,
    "observation_analysis_completed": 20,
    "evaluation_failed": 30,
    "evaluation_completed": 30,
    "runtime_provenance_completed": 40,
    "derived_state_persisted": 50,
}
PROGRESS_STAGE_EVALUATION_STATE = {
    "observation_analysis": "not_evaluated",
    "observation_analysis_completed": "not_evaluated",
    "evaluation_failed": "evaluation_failed",
    "evaluation_completed": "evaluation_completed",
    "runtime_provenance_completed": "evaluation_completed",
    "derived_state_persisted": "evaluation_completed",
}
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


class S48PartialTakeError(S48Error):
    """A take-level failure retaining every completed window exactly."""

    def __init__(
        self,
        message: str,
        *,
        expected_window_count: int,
        failed_window_index: int,
        completed_windows: list[dict[str, Any]],
        cause: Exception,
    ) -> None:
        super().__init__(message)
        self.expected_window_count = expected_window_count
        self.failed_window_index = failed_window_index
        self.completed_windows = completed_windows
        self.cause = cause


def pretty_json(value: Any) -> str:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=True)
        + "\n"
    )


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


def _evaluation_placeholder(
    state: str,
    *,
    error: Exception | None = None,
) -> dict[str, Any]:
    if state not in {"not_evaluated", "evaluation_failed"}:
        raise S48Error(f"invalid incomplete evaluation state: {state}")
    return {
        "schema": RESULT_SCHEMA,
        "status": state,
        "readiness_passed": False,
        "failed_gating_criteria": [],
        "criteria": [],
        "comparison_classifications": [],
        "identity_summary": {},
        "config_identity": {},
        "evaluation_error": None if error is None else str(error),
        "robustness": {
            "status": "not_evaluable",
            "denominator": 0,
        },
    }


def _validate_authorization_record(
    record: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    source_commit: str,
    grant: Mapping[str, Any],
    grant_record: Mapping[str, Any] | None = None,
    ledger_event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the complete authorization schema and every frozen binding."""

    expected_grant_id = config["grant"]["grant_id_template"].format(
        source_commit=source_commit
    )
    authorization_id = record.get("authorization_id")
    grant_sha256 = record.get("grant_sha256")
    if (
        set(record) != AUTHORIZATION_RECORD_FIELDS
        or record.get("schema") != AUTHORIZATION_RECORD_SCHEMA
        or not isinstance(authorization_id, str)
        or not authorization_id.strip()
        or authorization_id != authorization_id.strip()
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
        or not isinstance(grant_sha256, str)
        or len(grant_sha256) != 64
        or any(character not in "0123456789abcdef" for character in grant_sha256)
        or record.get("source_commit") != source_commit
        or record.get("grant_id") != expected_grant_id
        or record.get("grant_path") != config["grant"]["path"]
        or record.get("grant_sha256") != grant.get("grant_sha256")
        or record.get("ledger_path") != config["grant"]["ledger_path"]
        or record.get("irreversible_scientific_action_acknowledged") is not True
    ):
        raise S48Error("S4.8 authorization record schema or binding mismatch")
    if grant.get("grant_id") not in (None, expected_grant_id):
        raise S48Error("S4.8 authorization grant identity mismatch")
    if grant_record is not None and (
        grant_record.get("path") != config["grant"]["path"]
        or grant_record.get("grant_sha256") != record["grant_sha256"]
    ):
        raise S48Error("S4.8 authorization grant evidence mismatch")
    if ledger_event is not None and (
        ledger_event.get("grant_id") != record["grant_id"]
        or ledger_event.get("grant_sha256") != record["grant_sha256"]
    ):
        raise S48Error("S4.8 authorization ledger evidence mismatch")
    return dict(record)


def _validate_authorization_evidence(
    derived: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
) -> None:
    authorization = derived.get("authorization_record")
    grant_record = derived.get("grant")
    ledger_event = derived.get("ledger_event")
    source_commit = derived.get("source_commit")
    if (
        not isinstance(authorization, Mapping)
        or not isinstance(grant_record, Mapping)
        or not isinstance(ledger_event, Mapping)
        or not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
        or set(grant_record) != {"path", "file_sha256", "grant_sha256"}
        or not isinstance(grant_record.get("file_sha256"), str)
        or len(grant_record["file_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in grant_record["file_sha256"]
        )
        or not isinstance(grant_record.get("grant_sha256"), str)
        or len(grant_record["grant_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in grant_record["grant_sha256"]
        )
    ):
        raise S48Error("S4.8 authorization evidence is malformed")
    _validate_authorization_record(
        authorization,
        config=config,
        source_commit=source_commit,
        grant={
            "grant_id": authorization.get("grant_id"),
            "grant_sha256": grant_record.get("grant_sha256"),
        },
        grant_record=grant_record,
        ledger_event=ledger_event,
    )
    event_payload = {
        key: value for key, value in ledger_event.items() if key != "event_sha256"
    }
    if (
        ledger_event.get("schema") != "ias.s4_4.access_ledger_event.v1"
        or ledger_event.get("sequence") != 0
        or ledger_event.get("event") != "holdout_open_authorized"
        or ledger_event.get("purpose") != "S4.8_evaluation"
        or ledger_event.get("holdout_opened") is not True
        or ledger_event.get("event_sha256") != canonical_sha256(event_payload)
    ):
        raise S48Error("S4.8 authorization ledger evidence mismatch")


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
    if seal.get("partition_manifest_sha256") != config["holdout"]["split_plan_sha256"]:
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
            key: prerequisite[key] for key in sorted(PREREQUISITE_BINDING_FIELDS)
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
        "scientific_semantics_sha256": prerequisite["scientific_semantics_sha256"],
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


def _grant_creation_step(_step: str) -> None:
    """Fault-injection boundary for atomic grant-pair publication."""


def _grant_stage_entry_allowed(name: str, *, grant_name: str) -> bool:
    expected = {grant_name, AUTHORIZATION_RECORD_NAME}
    return name in expected or any(
        name.startswith(f".{item}.") and name.endswith(".staging") for item in expected
    )


def _cleanup_grant_staging(stage: Path, *, grant_name: str) -> None:
    if not stage.is_dir() or stage.is_symlink():
        raise S48Error("S4.8 grant staging path is invalid")
    for item in stage.iterdir():
        if (
            not _grant_stage_entry_allowed(item.name, grant_name=grant_name)
            or not item.is_file()
            or item.is_symlink()
        ):
            raise S48Error("S4.8 grant staging contains unexpected state")
    shutil.rmtree(stage)
    _fsync_directory(stage.parent)


def _validate_staged_grant_pair(
    root: Path,
    *,
    grant: Mapping[str, Any],
    authorization_record: Mapping[str, Any],
    grant_name: str,
) -> None:
    expected_names = {grant_name, AUTHORIZATION_RECORD_NAME}
    if (
        not root.is_dir()
        or root.is_symlink()
        or {item.name for item in root.iterdir()} != expected_names
    ):
        raise S48Error("S4.8 staged grant publication is incomplete")
    grant_path = root / grant_name
    authorization_path = root / AUTHORIZATION_RECORD_NAME
    if (
        grant_path.is_symlink()
        or authorization_path.is_symlink()
        or load_json(grant_path) != grant
        or load_json(authorization_path) != authorization_record
        or grant.get("grant_sha256")
        != canonical_sha256(
            {key: value for key, value in grant.items() if key != "grant_sha256"}
        )
    ):
        raise S48Error("S4.8 staged grant publication validation failed")


def _reconcile_grant_publication(
    publication_root: Path,
    *,
    stage: Path,
    grant: Mapping[str, Any],
    authorization_record: Mapping[str, Any],
    grant_name: str,
) -> dict[str, Any] | None:
    """Clean private crash state and recognize one exact atomic publication."""

    if stage.exists():
        _cleanup_grant_staging(stage, grant_name=grant_name)
    if not publication_root.exists():
        return None
    if not publication_root.is_dir() or publication_root.is_symlink():
        raise S48Error("S4.8 grant publication path is invalid")
    entries = {item.name: item for item in publication_root.iterdir()}
    expected_names = {grant_name, AUTHORIZATION_RECORD_NAME}
    if set(entries) == expected_names:
        _validate_staged_grant_pair(
            publication_root,
            grant=grant,
            authorization_record=authorization_record,
            grant_name=grant_name,
        )
        return {
            "grant": dict(grant),
            "authorization_record": dict(authorization_record),
            "grant_file_sha256": sha256_file(publication_root / grant_name),
        }
    if not entries:
        publication_root.rmdir()
        _fsync_directory(publication_root.parent)
        return None
    if set(entries) == {grant_name}:
        candidate = entries[grant_name]
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or load_json(candidate) != grant
        ):
            raise S48Error("S4.8 interrupted grant publication is invalid")
        shutil.rmtree(publication_root)
        _fsync_directory(publication_root.parent)
        return None
    raise S48Error("S4.8 grant publication is partial or mismatched")


def create_grant(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    """Atomically create, but do not consume, the exact single-use grant."""

    root = repo_root.resolve()
    if (
        not isinstance(authorization_id, str)
        or not authorization_id.strip()
        or authorization_id != authorization_id.strip()
    ):
        raise S48Error("authorization_id must be non-empty")
    config = load_contract(root)
    grant_path = root / config["grant"]["path"]
    publication_root = grant_path.parent
    publication_parent = publication_root.parent
    ledger_path = root / config["grant"]["ledger_path"]
    stage = publication_parent / GRANT_PUBLICATION_STAGING_NAME
    lock_path = root / "dataset/.s4_8_grant_creation.lock"
    _ensure_durable_directory(
        lock_path.parent,
        parents=True,
        exist_ok=True,
        boundary="grant_creation_lock_parent",
    )
    with _exclusive_transition_lock(lock_path):
        _ensure_durable_directory(
            publication_parent,
            parents=True,
            exist_ok=True,
            boundary="grant_publication_parent",
        )
        preopen = preopen_validate(
            root,
            source_commit=source_commit,
            require_access_paths_absent=False,
        )
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
        authorization_record = {
            "schema": AUTHORIZATION_RECORD_SCHEMA,
            "authorization_id": authorization_id,
            "source_commit": source_commit,
            "grant_id": grant_id,
            "grant_path": config["grant"]["path"],
            "grant_sha256": grant["grant_sha256"],
            "ledger_path": config["grant"]["ledger_path"],
            "irreversible_scientific_action_acknowledged": True,
        }
        result_paths = (
            ledger_path,
            root / config["evidence"]["derived_input_path"],
            root / config["evidence"]["run_journal_path"],
            root / config["evidence"]["output_path"],
        )
        if any(path.exists() for path in result_paths):
            raise S48Error(
                "grant consumption or first-result state already exists; "
                "refusing grant creation"
            )
        existing = _reconcile_grant_publication(
            publication_root,
            stage=stage,
            grant=grant,
            authorization_record=authorization_record,
            grant_name=grant_path.name,
        )
        if existing is not None:
            return existing

        _ensure_durable_directory(
            stage,
            parents=False,
            exist_ok=False,
            boundary="grant_staging",
        )
        _grant_creation_step("staging_created")
        staged_grant = stage / grant_path.name
        staged_authorization = stage / AUTHORIZATION_RECORD_NAME
        try:
            _grant_creation_step("before_grant_write")
            _atomic_write_text(staged_grant, pretty_json(grant))
            _grant_creation_step("grant_written")
            _grant_creation_step("before_authorization_write")
            _atomic_write_text(
                staged_authorization,
                pretty_json(authorization_record),
            )
            _grant_creation_step("authorization_written")
            _validate_staged_grant_pair(
                stage,
                grant=grant,
                authorization_record=authorization_record,
                grant_name=grant_path.name,
            )
            _grant_creation_step("before_staging_fsync")
            _fsync_package_tree(stage)
            _grant_creation_step("staging_fsynced")
            _grant_creation_step("before_final_publication")
            os.replace(stage, publication_root)
            _grant_creation_step("final_published")
            _fsync_directory(publication_parent)
            _grant_creation_step("publication_fsynced")
        except Exception:
            if stage.exists():
                _cleanup_grant_staging(stage, grant_name=grant_path.name)
            raise
        return {
            "grant": grant,
            "authorization_record": authorization_record,
            "grant_file_sha256": sha256_file(grant_path),
        }


def _consume_grant_once(
    repo_root: Path,
    *,
    source_commit: str,
    event_time_utc: str,
    recovery_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume the exact source-identified grant through the canonical interlock."""

    root = repo_root.resolve()
    _require_execution_lock(root)
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
        _cleanup_opening_transition_staging(
            transition.parent,
            ledger_name=ledger_path.name,
            journal_name=journal_path.name,
        )
        grant = load_json(grant_path)
        expected_id = config["grant"]["grant_id_template"].format(
            source_commit=source_commit
        )
        if grant.get("grant_id") != expected_id:
            raise S48Error("grant is not bound to the exact evaluator source commit")
        authorization_record = load_json(
            grant_path.with_name("authorization_record.v1.json")
        )
        _validate_authorization_record(
            authorization_record,
            config=config,
            source_commit=source_commit,
            grant=grant,
        )
        _validate_recovery_context_for_consumption(
            recovery_context,
            config=config,
            grant=grant,
            grant_path=grant_path,
            source_commit=source_commit,
        )
        if transition.exists():
            _ensure_durable_directory(
                transition,
                parents=False,
                exist_ok=True,
                boundary="opening_transition",
            )
            raise S48Error("S4.8 opening transition already claimed; retry forbidden")
        staging = _durable_mkdtemp(
            parent=transition.parent,
            prefix=".opening_transition.",
            suffix=".staging",
            boundary="opening_transition_staging",
        )
        try:
            staged_ledger = staging / ledger_path.name
            staged_journal = staging / journal_path.name
            staged_recovery = staging / RECOVERY_CONTEXT_NAME
            result = consume_s4_8_grant(
                grant_path,
                seal_path=_repo_file(root, config["holdout"]["seal_path"]),
                split_plan_sha256=config["holdout"]["split_plan_sha256"],
                prerequisite_path=_repo_file(root, config["prerequisite"]["path"]),
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
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in records
            )
            _atomic_write_text(staged_journal, encoded)
            _atomic_write_text(
                staged_recovery,
                pretty_json(dict(recovery_context)),
            )
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
            if staging.exists():
                _remove_directory_durably(staging)
            raise
    return {**result, "journal_records": records}


def _cleanup_opening_transition_staging(
    parent: Path,
    *,
    ledger_name: str,
    journal_name: str,
) -> None:
    """Remove only private transition stages left by a terminated owner."""

    for path in sorted(parent.glob(".opening_transition.*.staging")):
        if path.is_symlink() or not path.is_dir():
            raise S48Error("S4.8 opening-transition staging path is invalid")
        allowed = {
            ledger_name,
            journal_name,
            RECOVERY_CONTEXT_NAME,
        }
        for item in path.iterdir():
            if item.is_symlink() or not item.is_file():
                raise S48Error("S4.8 opening-transition staging contains invalid state")
            if item.name not in allowed and not any(
                item.name.startswith(f".{name}.")
                and item.name.endswith(".staging")
                for name in allowed
            ):
                raise S48Error(
                    "S4.8 opening-transition staging contains unexpected state"
                )
        _remove_directory_durably(path)


def _validate_recovery_context_for_consumption(
    context: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    grant: Mapping[str, Any],
    grant_path: Path,
    source_commit: str,
) -> None:
    context_grant = context.get("grant")
    authorization = context.get("authorization_record")
    context_payload = {
        key: value for key, value in context.items() if key != "context_sha256"
    }
    if (
        context.get("schema") != "ias.s4_8.post_consumption_recovery_context.v1"
        or context.get("source_commit") != source_commit
        or not isinstance(authorization, Mapping)
        or not isinstance(context.get("observation_inventory"), list)
        or not isinstance(context.get("payload"), Mapping)
        or context.get("payload_sha256") != canonical_sha256(context.get("payload"))
        or context.get("evaluation_state") != "not_evaluated"
        or not isinstance(context.get("evaluation"), Mapping)
        or context.get("evaluation_sha256")
        != canonical_sha256(context.get("evaluation"))
        or context.get("evaluation") != _evaluation_placeholder("not_evaluated")
        or not isinstance(context.get("runtime_provenance"), Mapping)
        or not isinstance(context_grant, Mapping)
        or context_grant.get("path") != config["grant"]["path"]
        or context_grant.get("file_sha256") != sha256_file(grant_path)
        or context_grant.get("grant_sha256") != grant.get("grant_sha256")
        or context.get("context_sha256") != canonical_sha256(context_payload)
    ):
        raise S48Error("S4.8 recovery context is not bound to this grant consumption")
    _validate_authorization_record(
        authorization,
        config=config,
        source_commit=source_commit,
        grant=grant,
        grant_record=context_grant,
    )


def _build_preconsumption_recovery_context(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Freeze enough non-scientific state to terminalize after consumption."""

    grant_path = repo_root / config["grant"]["path"]
    authorization_record = load_json(
        grant_path.with_name("authorization_record.v1.json")
    )
    grant = load_json(grant_path)
    _validate_authorization_record(
        authorization_record,
        config=config,
        source_commit=source_commit,
        grant=grant,
    )
    payload = _input_rejection_payload(repo_root)
    inventory = _input_rejection_inventory(
        repo_root,
        S48Error("no scientific observation was derived"),
    )
    evaluation = _evaluation_placeholder("not_evaluated")
    runtime = _runtime_dependency_provenance()
    context = {
        "schema": "ias.s4_8.post_consumption_recovery_context.v1",
        "source_commit": source_commit,
        "event_time_utc": event_time_utc,
        "authorization_record": authorization_record,
        "grant": {
            "path": config["grant"]["path"],
            "file_sha256": sha256_file(grant_path),
            "grant_sha256": grant["grant_sha256"],
        },
        "observation_inventory": inventory,
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "evaluation_state": "not_evaluated",
        "evaluation": evaluation,
        "evaluation_sha256": canonical_sha256(evaluation),
        "runtime_provenance": runtime,
    }
    return {**context, "context_sha256": canonical_sha256(context)}


def _recovery_context_path(repo_root: Path, config: Mapping[str, Any]) -> Path:
    journal = repo_root / config["evidence"]["run_journal_path"]
    return journal.with_name(RECOVERY_CONTEXT_NAME)


def _progress_path(repo_root: Path, config: Mapping[str, Any]) -> Path:
    journal = repo_root / config["evidence"]["run_journal_path"]
    return journal.with_name(POST_CONSUMPTION_PROGRESS_NAME)


def _post_consumption_stage(_stage: str) -> None:
    """Fault-injection boundary for the irreversible authorized run."""


def _downgrade_step(_step: str) -> None:
    """Fault-injection boundary for crash-consistent failure downgrade."""


def _progress_persistence_step(_step: str) -> None:
    """Fault-injection boundary for journal-anchored progress persistence."""


def _directory_creation_step(_step: str, _path: Path) -> None:
    """Fault-injection boundary for durable one-shot directory creation."""


def run_authorized_evaluation_once(
    repo_root: Path,
    *,
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Consume once, open once, evaluate once, and preserve the first input."""

    root = repo_root.resolve()
    lock_path = root / AUTHORIZED_EXECUTION_LOCK_PATH
    with _exclusive_execution_lock(lock_path):
        return _run_authorized_evaluation_once_locked(
            root,
            source_commit=source_commit,
            event_time_utc=event_time_utc,
        )


def _run_authorized_evaluation_once_locked(
    root: Path,
    *,
    source_commit: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Run or recover while holding the process-scoped execution lock."""

    _require_execution_lock(root)
    config = load_contract(root)
    _anchor_existing_one_shot_directories(root, config)
    derived_path = root / config["evidence"]["derived_input_path"]
    journal_path = root / config["evidence"]["run_journal_path"]
    output = root / config["evidence"]["output_path"]
    if journal_path.exists():
        records = _load_run_journal(journal_path)
        events = [record.get("event") for record in records]
        if events[-1:] == ["first_run_terminal"]:
            raise S48Error(
                "first S4.8 result already exists; automatic retry forbidden"
            )
        if any(
            event
            in {
                "first_run_finalization_prepared",
                "first_run_downgrade_intent",
                "first_run_finalization_failed",
            }
            for event in events
        ):
            validation = _recover_pending_finalization(
                root,
                config=config,
                source_commit=source_commit,
            )
            derived = load_json(derived_path)
            return _run_outcome(
                evaluation=derived["evaluation"],
                run_failure=derived.get("run_failure"),
                package_result={
                    **validation,
                    "output": output.as_posix(),
                },
            )
        if events[:2] == [
            "grant_consumed",
            "observation_opening_authorized",
        ]:
            return _recover_post_consumption_run(
                root,
                config=config,
                source_commit=source_commit,
                event_time_utc=event_time_utc,
                error=S48Error(
                    "recovered interrupted post-consumption run before "
                    "scientific evaluation could resume"
                ),
            )
        raise S48Error("S4.8 run journal state is invalid")
    if derived_path.exists() or output.exists():
        raise S48Error("first S4.8 result already exists; automatic retry forbidden")
    preopen_validate(
        root,
        source_commit=source_commit,
        require_access_paths_absent=False,
    )
    recovery_context = _build_preconsumption_recovery_context(
        root,
        config=config,
        source_commit=source_commit,
        event_time_utc=event_time_utc,
    )
    consumption = _consume_grant_once(
        root,
        source_commit=source_commit,
        event_time_utc=event_time_utc,
        recovery_context=recovery_context,
    )
    active_stage = "journal_initialization"
    try:
        _post_consumption_stage("journal_initialization")
        _append_run_journal(
            journal_path,
            {
                "event": "post_consumption_started",
                "event_time_utc": event_time_utc,
                "source_commit": source_commit,
                "automatic_retry_forbidden": True,
            },
        )
        active_stage = "authorization_loading"
        _post_consumption_stage("authorization_loading")
        grant_path = root / config["grant"]["path"]
        authorization_record = load_json(
            grant_path.with_name("authorization_record.v1.json")
        )
        active_stage = "grant_loading"
        _post_consumption_stage("grant_loading")
        grant = load_json(grant_path)
        grant_record = {
            "path": config["grant"]["path"],
            "file_sha256": sha256_file(grant_path),
            "grant_sha256": grant["grant_sha256"],
        }
        active_stage = "observation_analysis"
        _post_consumption_stage("observation_analysis")
        payload, observation_inventory = _build_real_payload(
            root,
            progress_callback=lambda progress: _persist_post_consumption_progress(
                _progress_path(root, config),
                journal_path=journal_path,
                source_commit=source_commit,
                stage="observation_analysis",
                progress=progress,
                evaluation_state="not_evaluated",
            ),
        )
        completed_progress = {
            "observation_inventory": observation_inventory,
            "payload": payload,
            "current_take": None,
        }
        _persist_post_consumption_progress(
            _progress_path(root, config),
            journal_path=journal_path,
            source_commit=source_commit,
            stage="observation_analysis_completed",
            progress=completed_progress,
            evaluation_state="not_evaluated",
        )
        active_stage = "scientific_evaluation"
        _post_consumption_stage("scientific_evaluation")
        try:
            evaluation = evaluate_payload(payload, repo_root=root)
        except Exception as exc:
            failed_evaluation = _evaluation_placeholder(
                "evaluation_failed",
                error=exc,
            )
            _persist_post_consumption_progress(
                _progress_path(root, config),
                journal_path=journal_path,
                source_commit=source_commit,
                stage="evaluation_failed",
                progress=completed_progress,
                evaluation_state="evaluation_failed",
                evaluation=failed_evaluation,
            )
            raise
        _persist_post_consumption_progress(
            _progress_path(root, config),
            journal_path=journal_path,
            source_commit=source_commit,
            stage="evaluation_completed",
            progress=completed_progress,
            evaluation_state="evaluation_completed",
            evaluation=evaluation,
        )
        active_stage = "runtime_provenance"
        _post_consumption_stage("runtime_provenance")
        runtime_provenance = _runtime_dependency_provenance()
        _persist_post_consumption_progress(
            _progress_path(root, config),
            journal_path=journal_path,
            source_commit=source_commit,
            stage="runtime_provenance_completed",
            progress=completed_progress,
            evaluation_state="evaluation_completed",
            evaluation=evaluation,
            runtime_provenance=runtime_provenance,
        )
        derived = {
            "schema": DERIVED_INPUT_SCHEMA,
            "tool_version": TOOL_VERSION,
            "source_commit": source_commit,
            "event_time_utc": event_time_utc,
            "authorization_record": authorization_record,
            "grant": grant_record,
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
            "evaluation_state": "evaluation_completed",
            "evaluation": evaluation,
            "evaluation_sha256": canonical_sha256(evaluation),
            "run_failure": None,
            "runtime_provenance": runtime_provenance,
        }
        active_stage = "derived_state_persistence"
        _post_consumption_stage("derived_state_persistence")
        _persist_derived_state(derived_path, derived)
        _persist_post_consumption_progress(
            _progress_path(root, config),
            journal_path=journal_path,
            source_commit=source_commit,
            stage="derived_state_persisted",
            progress=completed_progress,
            evaluation_state="evaluation_completed",
            evaluation=evaluation,
            runtime_provenance=runtime_provenance,
        )
        active_stage = "finalization"
        derived, package_result = _finalize_first_run(
            root,
            config=config,
            derived=derived,
            source_commit=source_commit,
            event_time_utc=event_time_utc,
        )
    except Exception as exc:
        return _recover_post_consumption_run(
            root,
            config=config,
            source_commit=source_commit,
            event_time_utc=event_time_utc,
            error=exc,
            ledger_event=consumption["ledger_event"],
            failure_stage=active_stage,
        )
    evaluation = dict(derived["evaluation"])
    run_failure = derived.get("run_failure")
    terminal_status = package_result["status"]
    _validate_terminal_journal(
        journal_path,
        source_commit=source_commit,
        expected_status=terminal_status,
        expected_ledger_event_sha256=consumption["ledger_event"]["event_sha256"],
    )
    return _run_outcome(
        evaluation=evaluation,
        run_failure=run_failure,
        package_result=package_result,
    )


def _build_real_payload(
    repo_root: Path,
    *,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open and derive the real payload. Caller must have consumed the grant."""

    root = repo_root.resolve()
    _require_execution_lock(root)
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
    records_by_root = {record["attempt_root"]: record for record in inventory}
    simulation = build_simulation_comparisons(root)
    _emit_observation_progress(
        progress_callback,
        inventory=inventory,
        payload=_partial_payload(config, takes=takes, simulation=simulation),
        current_take=None,
    )
    for take_id in sorted(registry):
        identity = registry[take_id]
        attempt_root = attempt_roots[take_id]
        relative_root = attempt_root.relative_to(root).as_posix()
        progress_record = records_by_root[relative_root]
        progress_record["scientific_observation_opened"] = True
        _emit_observation_progress(
            progress_callback,
            inventory=inventory,
            payload=_partial_payload(config, takes=takes, simulation=simulation),
            current_take={
                "planned_take_id": take_id,
                "attempt_root": relative_root,
                "expected_window_count": {
                    15: 119,
                    20: 159,
                }[identity.duration_s],
                "completed_window_count": 0,
                "completed_windows": [],
                "failed_window_index": None,
            },
        )
        latest_window_progress: dict[str, Any] = {
            "expected_window_count": {
                15: 119,
                20: 159,
            }[identity.duration_s],
            "completed_window_count": 0,
            "completed_windows": [],
            "failed_window_index": None,
        }
        try:
            analyze_kwargs: dict[str, Any] = {
                "profile": profile,
                "seal": seal,
            }
            if progress_callback is not None:

                def record_window_progress(
                    window_progress: Mapping[str, Any],
                    current_take_id: str = take_id,
                    current_attempt_root: str = relative_root,
                ) -> None:
                    nonlocal latest_window_progress
                    latest_window_progress = dict(window_progress)
                    _emit_observation_progress(
                        progress_callback,
                        inventory=inventory,
                        payload=_partial_payload(
                            config, takes=takes, simulation=simulation
                        ),
                        current_take={
                            "planned_take_id": current_take_id,
                            "attempt_root": current_attempt_root,
                            **dict(window_progress),
                        },
                    )

                analyze_kwargs["window_progress_callback"] = record_window_progress
            take, record = _analyze_real_take(
                root, attempt_root, identity, **analyze_kwargs
            )
        except S48PartialTakeError as exc:
            progress_record.update(
                {
                    "analysis_completed": False,
                    "failed": True,
                    "failure_reasons": ["observation_analysis_failed"],
                    "rejected": True,
                    "scientific_observations_derived": bool(exc.completed_windows),
                    "partial_window_count": len(exc.completed_windows),
                    "expected_window_count": exc.expected_window_count,
                    "failed_window_index": exc.failed_window_index,
                    "terminal_error_type": type(exc.cause).__name__,
                    "terminal_error": str(exc.cause),
                }
            )
            partial_payload = _partial_payload(
                config,
                takes=takes,
                simulation=simulation,
            )
            current_take = {
                "planned_take_id": take_id,
                "attempt_root": relative_root,
                "expected_window_count": exc.expected_window_count,
                "completed_window_count": len(exc.completed_windows),
                "completed_windows": exc.completed_windows,
                "failed_window_index": exc.failed_window_index,
            }
            _emit_observation_progress(
                progress_callback,
                inventory=inventory,
                payload=partial_payload,
                current_take=current_take,
            )
            inventory.sort(key=lambda item: item["attempt_root"])
            raise S48PartialAnalysisError(
                f"{take_id}: observation analysis failed after "
                f"{len(takes)} completed takes and "
                f"{len(exc.completed_windows)} completed windows",
                payload=partial_payload,
                observation_inventory=inventory,
                cause=exc.cause,
            ) from exc
        except Exception as exc:
            completed_windows = latest_window_progress["completed_windows"]
            progress_record.update(
                {
                    "analysis_completed": False,
                    "failed": True,
                    "failure_reasons": ["observation_analysis_failed"],
                    "rejected": True,
                    "scientific_observations_derived": bool(completed_windows),
                    "partial_window_count": len(completed_windows),
                    "expected_window_count": latest_window_progress[
                        "expected_window_count"
                    ],
                    "failed_window_index": latest_window_progress[
                        "failed_window_index"
                    ],
                    "terminal_error_type": type(exc).__name__,
                    "terminal_error": str(exc),
                }
            )
            partial_payload = _partial_payload(
                config,
                takes=takes,
                simulation=simulation,
            )
            _emit_observation_progress(
                progress_callback,
                inventory=inventory,
                payload=partial_payload,
                current_take={
                    "planned_take_id": take_id,
                    "attempt_root": relative_root,
                    **latest_window_progress,
                },
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
        _emit_observation_progress(
            progress_callback,
            inventory=inventory,
            payload=_partial_payload(config, takes=takes, simulation=simulation),
            current_take=None,
        )
    payload = _partial_payload(config, takes=takes, simulation=simulation)
    inventory.sort(key=lambda record: record["attempt_root"])
    return payload, inventory


def _emit_observation_progress(
    callback: Callable[[Mapping[str, Any]], None] | None,
    *,
    inventory: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
    current_take: Mapping[str, Any] | None,
) -> None:
    if callback is None:
        return
    callback(
        {
            "observation_inventory": [dict(record) for record in inventory],
            "payload": dict(payload),
            "current_take": (None if current_take is None else dict(current_take)),
        }
    )


def _persist_post_consumption_progress(
    path: Path,
    *,
    journal_path: Path,
    source_commit: str,
    stage: str,
    progress: Mapping[str, Any],
    evaluation_state: str,
    evaluation: Mapping[str, Any] | None = None,
    runtime_provenance: Mapping[str, Any] | None = None,
) -> None:
    if (
        stage not in PROGRESS_STAGE_ORDER
        or evaluation_state not in EVALUATION_STATES
        or PROGRESS_STAGE_EVALUATION_STATE.get(stage) != evaluation_state
    ):
        raise S48Error("S4.8 post-consumption progress stage is invalid")
    if evaluation_state in {
        "evaluation_completed",
        "evaluation_failed",
    } and not isinstance(evaluation, Mapping):
        raise S48Error("S4.8 completed evaluation progress is incomplete")
    records = _load_run_journal(journal_path)
    if len(records) < 3 or records[:3][-1].get("event") != "post_consumption_started":
        raise S48Error("S4.8 progress has no authenticated journal start")
    progress_events = [
        record
        for record in records
        if record.get("event") == "post_consumption_progress"
    ]
    sequence = len(progress_events)
    previous = (
        progress_events[-1]["progress_snapshot_sha256"]
        if progress_events
        else records[1]["event_sha256"]
    )
    previous_order = progress_events[-1]["stage_order"] if progress_events else -1
    stage_order = PROGRESS_STAGE_ORDER[stage]
    if stage_order < previous_order:
        raise S48Error("S4.8 progress stage rollback is forbidden")
    if (
        progress_events
        and progress_events[-1].get("evaluation_state") == "evaluation_completed"
        and evaluation_state != "evaluation_completed"
    ):
        raise S48Error("S4.8 completed evaluation cannot be downgraded")
    if (
        progress_events
        and progress_events[-1].get("evaluation_state") == "evaluation_failed"
    ):
        raise S48Error("S4.8 failed evaluation cannot advance")
    payload = progress.get("payload")
    inventory = progress.get("observation_inventory")
    current_take = progress.get("current_take")
    if not isinstance(payload, Mapping) or not isinstance(inventory, list):
        raise S48Error("S4.8 post-consumption progress payload is invalid")
    snapshot_payload = {
        "schema": "ias.s4_8.post_consumption_progress.v2",
        "sequence": sequence,
        "previous_progress_sha256": previous,
        "opening_journal_head_sha256": records[1]["event_sha256"],
        "source_commit": source_commit,
        "stage": stage,
        "stage_order": stage_order,
        "evaluation_state": evaluation_state,
        "observation_inventory": [dict(item) for item in inventory],
        "observation_inventory_sha256": canonical_sha256(inventory),
        "payload": dict(payload),
        "payload_sha256": canonical_sha256(payload),
        "current_take": None if current_take is None else dict(current_take),
        "current_take_sha256": canonical_sha256(current_take),
        "evaluation": None if evaluation is None else dict(evaluation),
        "evaluation_sha256": canonical_sha256(evaluation),
        "runtime_provenance": (
            None if runtime_provenance is None else dict(runtime_provenance)
        ),
        "runtime_provenance_sha256": canonical_sha256(runtime_provenance),
    }
    snapshot = {
        **snapshot_payload,
        "snapshot_sha256": canonical_sha256(snapshot_payload),
    }
    _ensure_durable_directory(
        path,
        parents=True,
        exist_ok=True,
        boundary="progress_snapshot_root",
    )
    snapshot_name = f"{sequence:06d}.{snapshot['snapshot_sha256']}.json"
    snapshot_path = path / snapshot_name
    if snapshot_path.exists():
        raise S48Error("S4.8 progress snapshot already exists")
    _progress_persistence_step("before_snapshot_persistence")
    _atomic_write_text(snapshot_path, pretty_json(snapshot))
    _progress_persistence_step("snapshot_persisted")
    _fsync_directory(path)
    _progress_persistence_step("snapshot_fsynced")
    _progress_persistence_step("before_journal_append")
    _append_run_journal(
        journal_path,
        {
            "event": "post_consumption_progress",
            "source_commit": source_commit,
            "progress_sequence": sequence,
            "progress_snapshot_path": snapshot_path.relative_to(
                journal_path.parent
            ).as_posix(),
            "progress_snapshot_sha256": snapshot["snapshot_sha256"],
            "stage": stage,
            "stage_order": stage_order,
            "evaluation_state": evaluation_state,
        },
    )
    _progress_persistence_step("journal_appended")
    if progress_events:
        _progress_persistence_step("before_old_snapshot_pruning")
        previous_path = journal_path.parent / _safe_relative(
            progress_events[-1]["progress_snapshot_path"]
        )
        with suppress(FileNotFoundError):
            previous_path.unlink()
        _progress_persistence_step("old_snapshot_pruned")
        _fsync_directory(path)
        _progress_persistence_step("pruning_fsynced")


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
            wav_record = _seal_record(seal, candidate / "raw/respeaker_audio.wav")
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


def evaluate_payload(payload: Mapping[str, Any], *, repo_root: Path) -> dict[str, Any]:
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
                    "failure_reasons": ["evaluation_input_contract_rejected"],
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


def _load_recovery_context(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    path = _recovery_context_path(repo_root, config)
    context = load_json(path)
    context_payload = {
        key: value for key, value in context.items() if key != "context_sha256"
    }
    if (
        context.get("schema") != "ias.s4_8.post_consumption_recovery_context.v1"
        or context.get("source_commit") != source_commit
        or context.get("payload_sha256") != canonical_sha256(context.get("payload"))
        or context.get("evaluation_state") != "not_evaluated"
        or context.get("context_sha256") != canonical_sha256(context_payload)
    ):
        raise S48Error("S4.8 post-consumption recovery context is invalid")
    grant = context.get("grant")
    if not isinstance(grant, Mapping):
        raise S48Error("S4.8 recovery grant record is invalid")
    grant_path = repo_root / _safe_relative(grant.get("path"))
    if not grant_path.is_file() or sha256_file(grant_path) != grant.get("file_sha256"):
        raise S48Error("S4.8 recovery grant authentication failed")
    grant_payload = load_json(grant_path)
    if grant_payload.get("grant_sha256") != grant.get("grant_sha256"):
        raise S48Error("S4.8 recovery grant authentication failed")
    authorization = context.get("authorization_record")
    if not isinstance(authorization, Mapping):
        raise S48Error("S4.8 recovery authorization record is invalid")
    _validate_authorization_record(
        authorization,
        config=config,
        source_commit=source_commit,
        grant=grant_payload,
        grant_record=grant,
    )
    if context.get("evaluation_sha256") != canonical_sha256(context.get("evaluation")):
        raise S48Error("S4.8 recovery evaluation hash is invalid")
    return context


def _consumed_ledger_event(
    repo_root: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    ledger_path = repo_root / config["grant"]["ledger_path"]
    if not ledger_path.is_file():
        raise S48Error("S4.8 consumed ledger event is unavailable")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise S48Error("S4.8 consumed ledger must contain exactly one event")
    try:
        event = json.loads(lines[0], parse_constant=_reject_json_constant)
    except (ValueError, json.JSONDecodeError) as exc:
        raise S48Error("S4.8 consumed ledger JSON is invalid") from exc
    if not isinstance(event, dict) or event.get("event_sha256") != canonical_sha256(
        {key: value for key, value in event.items() if key != "event_sha256"}
    ):
        raise S48Error("S4.8 consumed ledger event is invalid")
    return event


def _progress_chain_metadata(
    journal_path: Path,
    *,
    source_commit: str,
) -> tuple[list[dict[str, Any]], str, set[Path]]:
    journal = _load_run_journal(journal_path)
    progress_events = [
        record
        for record in journal
        if record.get("event") == "post_consumption_progress"
    ]
    if len(journal) < 3 or journal[2].get("event") != "post_consumption_started":
        raise S48Error("S4.8 progress journal start is invalid")
    opening_head = journal[1]["event_sha256"]
    previous_order = -1
    completed = False
    failed = False
    authenticated_paths: set[Path] = set()
    for sequence, event in enumerate(progress_events):
        relative = _safe_relative(event.get("progress_snapshot_path"))
        snapshot_path = journal_path.parent / relative
        supplied = event.get("progress_snapshot_sha256")
        stage = event.get("stage")
        stage_order = event.get("stage_order")
        evaluation_state = event.get("evaluation_state")
        authenticated_paths.add(snapshot_path.resolve())
        if (
            event.get("source_commit") != source_commit
            or event.get("progress_sequence") != sequence
            or stage not in PROGRESS_STAGE_ORDER
            or stage_order != PROGRESS_STAGE_ORDER[stage]
            or evaluation_state != PROGRESS_STAGE_EVALUATION_STATE[stage]
            or stage_order < previous_order
            or evaluation_state not in EVALUATION_STATES
            or snapshot_path.parent.resolve()
            != (journal_path.parent / POST_CONSUMPTION_PROGRESS_NAME).resolve()
            or snapshot_path.name != f"{sequence:06d}.{supplied}.json"
            or failed
            or (completed and evaluation_state != "evaluation_completed")
        ):
            raise S48Error("S4.8 post-consumption progress chain is invalid")
        if snapshot_path.exists():
            expected_previous = (
                progress_events[sequence - 1]["progress_snapshot_sha256"]
                if sequence
                else opening_head
            )
            _validated_progress_snapshot(
                snapshot_path,
                source_commit=source_commit,
                sequence=sequence,
                expected_previous=expected_previous,
                opening_head=opening_head,
                expected_stage=stage,
                expected_stage_order=stage_order,
                expected_evaluation_state=evaluation_state,
                expected_sha256=supplied,
            )
        completed = completed or evaluation_state == "evaluation_completed"
        failed = failed or evaluation_state == "evaluation_failed"
        previous_order = int(stage_order)
    return progress_events, opening_head, authenticated_paths


def _validated_progress_snapshot(
    snapshot_path: Path,
    *,
    source_commit: str,
    sequence: int,
    expected_previous: str,
    opening_head: str,
    expected_stage: str,
    expected_stage_order: int,
    expected_evaluation_state: str,
    expected_sha256: str,
) -> dict[str, Any]:
    if (
        not snapshot_path.is_file()
        or snapshot_path.is_symlink()
        or snapshot_path.name != f"{sequence:06d}.{expected_sha256}.json"
    ):
        raise S48Error("S4.8 post-consumption progress chain is invalid")
    snapshot = load_json(snapshot_path)
    supplied = snapshot.get("snapshot_sha256")
    payload = {
        key: value for key, value in snapshot.items() if key != "snapshot_sha256"
    }
    if (
        snapshot.get("schema") != "ias.s4_8.post_consumption_progress.v2"
        or snapshot.get("sequence") != sequence
        or snapshot.get("previous_progress_sha256") != expected_previous
        or snapshot.get("opening_journal_head_sha256") != opening_head
        or snapshot.get("source_commit") != source_commit
        or snapshot.get("stage") != expected_stage
        or snapshot.get("stage_order") != expected_stage_order
        or snapshot.get("evaluation_state") != expected_evaluation_state
        or snapshot.get("observation_inventory_sha256")
        != canonical_sha256(snapshot.get("observation_inventory"))
        or snapshot.get("payload_sha256") != canonical_sha256(snapshot.get("payload"))
        or snapshot.get("current_take_sha256")
        != canonical_sha256(snapshot.get("current_take"))
        or snapshot.get("evaluation_sha256")
        != canonical_sha256(snapshot.get("evaluation"))
        or snapshot.get("runtime_provenance_sha256")
        != canonical_sha256(snapshot.get("runtime_provenance"))
        or supplied != canonical_sha256(payload)
        or supplied != expected_sha256
        or not isinstance(snapshot.get("observation_inventory"), list)
        or not isinstance(snapshot.get("payload"), Mapping)
        or (
            expected_evaluation_state in {"evaluation_completed", "evaluation_failed"}
            and not isinstance(snapshot.get("evaluation"), Mapping)
        )
    ):
        raise S48Error("S4.8 post-consumption progress chain is invalid")
    return snapshot


def _quarantine_progress_residue(progress_root: Path, residue: Path) -> None:
    if not residue.is_file() or residue.is_symlink():
        raise S48Error("S4.8 progress residue is not a regular file")
    quarantine = progress_root.with_name(POST_CONSUMPTION_PROGRESS_QUARANTINE_NAME)
    _ensure_durable_directory(
        quarantine,
        parents=False,
        exist_ok=True,
        boundary="progress_quarantine",
    )
    digest = sha256_file(residue)
    destination = quarantine / f"{digest}.crash-residue"
    if destination.exists():
        if (
            not destination.is_file()
            or destination.is_symlink()
            or sha256_file(destination) != digest
        ):
            raise S48Error("S4.8 progress quarantine collision")
        residue.unlink()
    else:
        os.replace(residue, destination)
    _fsync_directory(quarantine)
    _fsync_directory(progress_root)


def _reconcile_progress_crash_residues(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
) -> None:
    """Quarantine only structurally valid residues outside the journal chain."""

    progress_root = _progress_path(repo_root, config)
    if not progress_root.exists():
        return
    if not progress_root.is_dir() or progress_root.is_symlink():
        raise S48Error("S4.8 progress snapshot root is invalid")
    journal_path = repo_root / config["evidence"]["run_journal_path"]
    progress_events, opening_head, authenticated_paths = _progress_chain_metadata(
        journal_path,
        source_commit=source_commit,
    )
    if progress_events:
        latest = progress_events[-1]
        expected_previous = (
            progress_events[-2]["progress_snapshot_sha256"]
            if len(progress_events) > 1
            else opening_head
        )
        _validated_progress_snapshot(
            journal_path.parent / _safe_relative(latest["progress_snapshot_path"]),
            source_commit=source_commit,
            sequence=latest["progress_sequence"],
            expected_previous=expected_previous,
            opening_head=opening_head,
            expected_stage=latest["stage"],
            expected_stage_order=latest["stage_order"],
            expected_evaluation_state=latest["evaluation_state"],
            expected_sha256=latest["progress_snapshot_sha256"],
        )
    unexpected = [
        candidate
        for candidate in progress_root.iterdir()
        if candidate.resolve() not in authenticated_paths
    ]
    canonical_residues = [
        candidate
        for candidate in unexpected
        if not (candidate.name.startswith(".") and candidate.name.endswith(".staging"))
    ]
    if len(canonical_residues) > 1:
        raise S48Error("S4.8 multiple unjournaled progress snapshots detected")
    if canonical_residues:
        residue = canonical_residues[0]
        if not residue.is_file() or residue.is_symlink():
            raise S48Error("S4.8 unjournaled progress snapshot is invalid")
        try:
            snapshot = load_json(residue)
        except (OSError, ValueError) as exc:
            raise S48Error("S4.8 unjournaled progress snapshot is invalid") from exc
        sequence = len(progress_events)
        previous = (
            progress_events[-1]["progress_snapshot_sha256"]
            if progress_events
            else opening_head
        )
        previous_order = progress_events[-1]["stage_order"] if progress_events else -1
        previous_state = (
            progress_events[-1]["evaluation_state"]
            if progress_events
            else "not_evaluated"
        )
        stage = snapshot.get("stage")
        stage_order = snapshot.get("stage_order")
        evaluation_state = snapshot.get("evaluation_state")
        supplied = snapshot.get("snapshot_sha256")
        if (
            stage not in PROGRESS_STAGE_ORDER
            or stage_order != PROGRESS_STAGE_ORDER[stage]
            or evaluation_state != PROGRESS_STAGE_EVALUATION_STATE[stage]
            or stage_order < previous_order
            or (
                previous_state == "evaluation_completed"
                and evaluation_state != "evaluation_completed"
            )
            or previous_state == "evaluation_failed"
            or not isinstance(supplied, str)
        ):
            raise S48Error("S4.8 unjournaled progress snapshot is invalid")
        _validated_progress_snapshot(
            residue,
            source_commit=source_commit,
            sequence=sequence,
            expected_previous=previous,
            opening_head=opening_head,
            expected_stage=stage,
            expected_stage_order=stage_order,
            expected_evaluation_state=evaluation_state,
            expected_sha256=supplied,
        )
    for residue in unexpected:
        _quarantine_progress_residue(progress_root, residue)


def _load_partial_progress(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any] | None:
    progress_root = _progress_path(repo_root, config)
    journal_path = repo_root / config["evidence"]["run_journal_path"]
    progress_events, opening_head, authenticated_paths = _progress_chain_metadata(
        journal_path,
        source_commit=source_commit,
    )
    if not progress_events:
        if progress_root.exists() and any(progress_root.iterdir()):
            raise S48Error("S4.8 progress snapshots are not journal-authenticated")
        return None
    if progress_root.is_dir():
        unexpected = {
            candidate.resolve()
            for candidate in progress_root.iterdir()
            if candidate.is_file()
        } - authenticated_paths
        if unexpected:
            raise S48Error("S4.8 unjournaled progress snapshot detected")
    latest_event = progress_events[-1]
    latest_path = journal_path.parent / _safe_relative(
        latest_event["progress_snapshot_path"]
    )
    expected_previous = (
        progress_events[-2]["progress_snapshot_sha256"]
        if len(progress_events) > 1
        else opening_head
    )
    return _validated_progress_snapshot(
        latest_path,
        source_commit=source_commit,
        sequence=latest_event["progress_sequence"],
        expected_previous=expected_previous,
        opening_head=opening_head,
        expected_stage=latest_event["stage"],
        expected_stage_order=latest_event["stage_order"],
        expected_evaluation_state=latest_event["evaluation_state"],
        expected_sha256=latest_event["progress_snapshot_sha256"],
    )


def _recover_post_consumption_run(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    source_commit: str,
    event_time_utc: str,
    error: Exception,
    ledger_event: Mapping[str, Any] | None = None,
    failure_stage: str = "post_consumption_recovery",
) -> dict[str, Any]:
    """Terminalize one consumed run without reopening scientific content."""

    journal_path = repo_root / config["evidence"]["run_journal_path"]
    records = _load_run_journal(journal_path)
    events = [record.get("event") for record in records]
    original_event_time = (
        records[0].get("event_time_utc") if records else event_time_utc
    )
    if events[-1:] == ["first_run_terminal"]:
        derived = load_json(repo_root / config["evidence"]["derived_input_path"])
        validation = validate_evidence_package(
            repo_root / config["evidence"]["output_path"],
            repo_root=repo_root,
        )
        return _run_outcome(
            evaluation=derived["evaluation"],
            run_failure=derived.get("run_failure"),
            package_result={
                **validation,
                "output": (repo_root / config["evidence"]["output_path"]).as_posix(),
            },
        )
    if events == ["grant_consumed", "observation_opening_authorized"]:
        _append_run_journal(
            journal_path,
            {
                "event": "post_consumption_started",
                "event_time_utc": original_event_time,
                "source_commit": source_commit,
                "recovered_from_opening_only": True,
                "automatic_retry_forbidden": True,
            },
        )
    elif not (
        events[:3]
        == [
            "grant_consumed",
            "observation_opening_authorized",
            "post_consumption_started",
        ]
        and all(event == "post_consumption_progress" for event in events[3:])
    ):
        if any(
            event
            in {
                "first_run_finalization_prepared",
                "first_run_downgrade_intent",
                "first_run_finalization_failed",
            }
            for event in events
        ):
            validation = _recover_pending_finalization(
                repo_root,
                config=config,
                source_commit=source_commit,
            )
            derived = load_json(repo_root / config["evidence"]["derived_input_path"])
            return _run_outcome(
                evaluation=derived["evaluation"],
                run_failure=derived.get("run_failure"),
                package_result={
                    **validation,
                    "output": (
                        repo_root / config["evidence"]["output_path"]
                    ).as_posix(),
                },
            )
        raise S48Error("S4.8 interrupted post-consumption state is invalid")
    context = _load_recovery_context(
        repo_root,
        config=config,
        source_commit=source_commit,
    )
    _reconcile_progress_crash_residues(
        repo_root,
        config=config,
        source_commit=source_commit,
    )
    progress = _load_partial_progress(
        repo_root,
        config=config,
        source_commit=source_commit,
    )
    failure = _run_failure_record(stage=failure_stage, error=error)
    event = (
        dict(ledger_event)
        if ledger_event is not None
        else _consumed_ledger_event(repo_root, config)
    )
    opening_records = _load_run_journal(journal_path)[:2]
    evaluation_state = (
        context["evaluation_state"]
        if progress is None
        else progress["evaluation_state"]
    )
    recovered_payload = context["payload"] if progress is None else progress["payload"]
    recovered_evaluation = (
        context["evaluation"] if progress is None else progress["evaluation"]
    )
    if evaluation_state == "not_evaluated":
        recovered_evaluation = _evaluation_placeholder("not_evaluated")
    elif evaluation_state == "evaluation_failed":
        if not isinstance(recovered_evaluation, Mapping):
            recovered_evaluation = _evaluation_placeholder(
                "evaluation_failed",
                error=error,
            )
    elif evaluation_state != "evaluation_completed":
        raise S48Error("S4.8 recovered evaluation state is invalid")
    recovered_runtime = (
        progress.get("runtime_provenance") if progress is not None else None
    )
    if not isinstance(recovered_runtime, Mapping):
        recovered_runtime = context["runtime_provenance"]
    derived = {
        "schema": DERIVED_INPUT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "source_commit": source_commit,
        "event_time_utc": context["event_time_utc"],
        "authorization_record": context["authorization_record"],
        "grant": context["grant"],
        "ledger_event": event,
        "run_journal": {
            "path": config["evidence"]["run_journal_path"],
            "opening_event_count": 2,
            "opening_head_sha256": opening_records[-1]["event_sha256"],
            "terminal_event_required": True,
        },
        "observation_inventory": (
            context["observation_inventory"]
            if progress is None
            else progress["observation_inventory"]
        ),
        "partial_progress": progress,
        "payload": recovered_payload,
        "payload_sha256": canonical_sha256(recovered_payload),
        "evaluation_state": evaluation_state,
        "evaluation": recovered_evaluation,
        "evaluation_sha256": canonical_sha256(recovered_evaluation),
        "run_failure": failure,
        "runtime_provenance": recovered_runtime,
    }
    derived_path = repo_root / config["evidence"]["derived_input_path"]
    _persist_derived_state(derived_path, derived)
    finalized, package_result = _finalize_first_run(
        repo_root,
        config=config,
        derived=derived,
        source_commit=source_commit,
        event_time_utc=context["event_time_utc"],
        failure_only=True,
    )
    return _run_outcome(
        evaluation=finalized["evaluation"],
        run_failure=finalized.get("run_failure"),
        package_result=package_result,
    )


def _recomputed_evaluation(
    repo_root: Path, derived: Mapping[str, Any]
) -> dict[str, Any]:
    evaluation_state = derived.get("evaluation_state", "evaluation_completed")
    evaluation = derived.get("evaluation")
    if evaluation_state not in EVALUATION_STATES or not isinstance(evaluation, Mapping):
        raise S48Error("S4.8 evaluation state is missing or invalid")
    if derived.get("evaluation_sha256") is not None and derived.get(
        "evaluation_sha256"
    ) != canonical_sha256(evaluation):
        raise S48Error("S4.8 preserved evaluation hash mismatch")
    payload = derived.get("payload")
    if not isinstance(payload, Mapping):
        raise S48Error("S4.8 derived payload is missing or invalid")
    expected_payload_sha = derived.get("payload_sha256")
    actual_payload_sha = canonical_sha256(payload)
    if expected_payload_sha is not None and expected_payload_sha != actual_payload_sha:
        raise S48Error("S4.8 preserved observation payload hash mismatch")
    if evaluation_state != "evaluation_completed":
        expected_status = evaluation_state
        if (
            evaluation.get("schema") != RESULT_SCHEMA
            or evaluation.get("status") != expected_status
            or evaluation.get("readiness_passed") is not False
            or evaluation.get("failed_gating_criteria") != []
            or evaluation.get("criteria") != []
            or evaluation.get("comparison_classifications") != []
            or (
                evaluation_state == "not_evaluated"
                and evaluation.get("evaluation_error") is not None
            )
            or (
                evaluation_state == "evaluation_failed"
                and not isinstance(evaluation.get("evaluation_error"), str)
            )
        ):
            raise S48Error("S4.8 incomplete evaluation state is contradictory")
        return dict(evaluation)
    recomputed = evaluate_payload(payload, repo_root=repo_root)
    if evaluation != recomputed:
        raise S48Error(
            "S4.8 preserved evaluation contradicts recomputation from payload"
        )
    return recomputed


def build_simulation_comparisons(repo_root: Path) -> list[dict[str, Any]]:
    """Run the deterministic core simulator with S4.6 off and apply modes."""

    root = repo_root.resolve()
    config = load_contract(root)
    registry = build_identity_registry(root)
    paths = {mode: _simulate_path(root, registry, mode) for mode in ("off", "apply")}
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
                    "unadjusted_simulation": paths["off"][entry["comparison_id"]][
                        condition_id
                    ],
                    "adjusted_simulation": paths["apply"][entry["comparison_id"]][
                        condition_id
                    ],
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
        "scientific_readiness_passed": (evaluation.get("readiness_passed") is True),
        "failed_gating_criteria": evaluation.get("failed_gating_criteria", []),
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
    failure_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stage one package, prepare the journal, then publish and terminalize."""

    root = repo_root.resolve()
    output = root / config["evidence"]["output_path"]
    derived_path = root / config["evidence"]["derived_input_path"]
    journal_path = root / config["evidence"]["run_journal_path"]
    staging = _finalization_staging_path(output)
    if output.exists():
        raise S48Error("S4.8 finalization destination already exists")
    if staging.exists():
        records = _load_run_journal(journal_path)
        if any(
            record.get("event")
            in {
                "first_run_finalization_prepared",
                "first_run_downgrade_intent",
                "first_run_finalization_failed",
            }
            for record in records
        ):
            raise S48Error("S4.8 finalization destination already exists")
        _remove_directory_durably(staging)
    _validate_source_commit(root, source_commit, require_current_head=True)
    _ensure_durable_directory(
        staging,
        parents=True,
        exist_ok=False,
        boundary="finalization_staging",
    )
    prepared: dict[str, Any] | None = None
    try:
        try:
            if failure_only:
                package_result = _build_terminal_failure_package_in_place(
                    root,
                    derived,
                    destination=staging,
                    source_commit=source_commit,
                )
            else:
                _post_consumption_stage("evidence_packaging")
                package_result = _build_evidence_package_in_place(
                    root,
                    derived,
                    destination=staging,
                    source_commit=source_commit,
                )
        except Exception as exc:
            if failure_only:
                raise
            if staging.exists():
                _remove_directory_durably(staging)
            derived = {
                **derived,
                "run_failure": _run_failure_record(
                    stage="evidence_packaging",
                    error=exc,
                ),
            }
            _persist_derived_state(derived_path, derived)
            _ensure_durable_directory(
                staging,
                parents=True,
                exist_ok=False,
                boundary="terminal_failure_staging",
            )
            package_result = _build_terminal_failure_package_in_place(
                root,
                derived,
                destination=staging,
                source_commit=source_commit,
            )
        _fsync_package_tree(staging)
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
        if not failure_only:
            _post_consumption_stage("evidence_publication")
        _fsync_package_tree(staging)
        os.replace(staging, output)
        _fsync_directory(output.parent)
        if not failure_only:
            _post_consumption_stage("journal_finalization")
        _append_run_journal(
            journal_path,
            _terminal_event_from_prepared(prepared),
        )
    except Exception as exc:
        records = _load_run_journal(journal_path)
        if prepared is not None and any(
            item.get("event") == "first_run_finalization_prepared" for item in records
        ):
            return _finalize_transition_failure(
                root,
                config=config,
                derived=derived,
                source_commit=source_commit,
                event_time_utc=event_time_utc,
                error=exc,
            )
        if staging.exists():
            _remove_directory_durably(staging)
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
    candidates = [path for path in (output, staging) if path.exists()]
    if len(candidates) != 1:
        raise S48Error("S4.8 finalization failure has no unique provisional package")
    failure = _run_failure_record(
        stage="finalization_publication",
        error=error,
    )
    if derived.get("run_failure") is not None:
        failure["prior_run_failure"] = derived["run_failure"]
    intent = {
        "event": "first_run_downgrade_intent",
        "event_time_utc": event_time_utc,
        "source_commit": source_commit,
        "run_failure": failure,
        "provisional_path": candidates[0].relative_to(repo_root).as_posix(),
        "provisional_manifest_sha256": sha256_file(candidates[0] / "SHA256SUMS"),
        "provisional_evidence_path": archive.relative_to(repo_root).as_posix(),
        "output_path": output.relative_to(repo_root).as_posix(),
        "staging_path": staging.relative_to(repo_root).as_posix(),
        "automatic_retry_forbidden": True,
    }
    _append_run_journal(journal_path, intent)
    _downgrade_step("intent_recorded")
    return _continue_failure_downgrade(
        repo_root,
        config=config,
        derived=derived,
        source_commit=source_commit,
        intent=intent,
    )


def _continue_failure_downgrade(
    repo_root: Path,
    *,
    config: Mapping[str, Any],
    derived: dict[str, Any],
    source_commit: str,
    intent: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Idempotently continue a journaled downgrade from provisional evidence."""

    output = repo_root / _safe_relative(intent["output_path"])
    staging = repo_root / _safe_relative(intent["staging_path"])
    provisional = repo_root / _safe_relative(intent["provisional_path"])
    archive = repo_root / _safe_relative(intent["provisional_evidence_path"])
    journal_path = repo_root / config["evidence"]["run_journal_path"]
    derived_path = repo_root / config["evidence"]["derived_input_path"]
    expected_provisional = intent["provisional_manifest_sha256"]
    existing = [
        path
        for path in (provisional, archive)
        if path.is_dir()
        and (path / "SHA256SUMS").is_file()
        and sha256_file(path / "SHA256SUMS") == expected_provisional
    ]
    if archive.exists() and provisional == archive:
        existing = [archive]
    if len(existing) != 1:
        raise S48Error("S4.8 downgrade has no unique provisional evidence package")
    candidate = existing[0]
    if (
        not candidate.is_dir()
        or sha256_file(candidate / "SHA256SUMS") != expected_provisional
    ):
        raise S48Error("S4.8 provisional evidence authentication failed")
    _validate_manifest(candidate)
    if candidate != archive:
        _ensure_durable_directory(
            archive.parent,
            parents=True,
            exist_ok=True,
            boundary="provisional_archive_parent",
        )
        if archive.exists():
            if archive.is_symlink() or not archive.is_dir() or any(archive.iterdir()):
                raise S48Error("S4.8 provisional evidence archive is invalid")
            _remove_directory_durably(archive)
        os.replace(candidate, archive)
        _fsync_directory(archive.parent)
    _downgrade_step("provisional_archived")
    failure = dict(intent["run_failure"])
    derived = {**derived, "run_failure": failure}
    _persist_derived_state(derived_path, derived)
    _downgrade_step("failure_derived_persisted")
    if staging.exists():
        if output.exists():
            raise S48Error("S4.8 downgrade has two failure packages")
        _remove_directory_durably(staging)
    if not output.exists():
        _ensure_durable_directory(
            staging,
            parents=True,
            exist_ok=False,
            boundary="downgraded_failure_staging",
        )
        package_result = _build_terminal_failure_package_in_place(
            repo_root,
            derived,
            destination=staging,
            source_commit=source_commit,
        )
        _fsync_package_tree(staging)
    else:
        package_result = validate_evidence_package(output, repo_root=repo_root)
        package_result = {
            **package_result,
            "manifest_sha256": sha256_file(output / "SHA256SUMS"),
        }
    _downgrade_step("failure_package_ready")
    records = _load_run_journal(journal_path)
    failed = next(
        (
            record
            for record in records
            if record.get("event") == "first_run_finalization_failed"
        ),
        None,
    )
    if failed is None:
        failed = {
            "event": "first_run_finalization_failed",
            "event_time_utc": intent["event_time_utc"],
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
            "provisional_evidence_path": archive.relative_to(repo_root).as_posix(),
            "automatic_retry_forbidden": True,
        }
        _append_run_journal(journal_path, failed)
    _downgrade_step("failure_prepared")
    if staging.exists():
        _fsync_package_tree(staging)
        os.replace(staging, output)
        _fsync_directory(output.parent)
    if not output.is_dir():
        raise S48Error("S4.8 downgraded failure package is unavailable")
    if sha256_file(output / "SHA256SUMS") != failed.get("evidence_manifest_sha256"):
        raise S48Error("S4.8 downgraded failure manifest mismatch")
    _downgrade_step("failure_published")
    if not any(
        record.get("event") == "first_run_terminal"
        for record in _load_run_journal(journal_path)
    ):
        _append_run_journal(
            journal_path,
            _terminal_event_from_prepared(failed),
        )
    _downgrade_step("failure_terminal")
    return (
        derived,
        {
            **package_result,
            "status": "failed",
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
        "scientific_readiness_passed": prepared["scientific_readiness_passed"],
        "failed_gating_criteria": prepared["failed_gating_criteria"],
        "run_failure": prepared["run_failure"],
        "derived_input_sha256": prepared["derived_input_sha256"],
        "evidence_manifest_sha256": prepared["evidence_manifest_sha256"],
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
    if records and records[-1].get("event") == "first_run_terminal":
        output = root / config["evidence"]["output_path"]
        if not output.is_dir():
            raise S48Error("S4.8 terminal journal has no evidence package")
        return validate_evidence_package(output, repo_root=root)
    intents = [
        record
        for record in records
        if record.get("event") == "first_run_downgrade_intent"
    ]
    if intents and not any(
        record.get("event") == "first_run_finalization_failed" for record in records
    ):
        derived = load_json(root / config["evidence"]["derived_input_path"])
        _, result = _continue_failure_downgrade(
            root,
            config=config,
            derived=derived,
            source_commit=source_commit,
            intent=intents[-1],
        )
        return validate_evidence_package(
            Path(result["output"]),
            repo_root=root,
        )
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
        _ensure_durable_directory(
            output.parent,
            parents=True,
            exist_ok=True,
            boundary="recovered_output_parent",
        )
        _fsync_package_tree(staging)
        os.replace(staging, output)
        _fsync_directory(output.parent)
    if not output.is_dir():
        raise S48Error("S4.8 prepared finalization package is unavailable")
    if sha256_file(output / "SHA256SUMS") != prepared.get("evidence_manifest_sha256"):
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
    _validate_authorization_evidence(derived, config=load_contract(root))
    evaluation = _recomputed_evaluation(root, derived)
    payload = dict(derived["payload"])
    partial_progress = derived.get("partial_progress")
    progress_payload = (
        partial_progress.get("payload")
        if isinstance(partial_progress, Mapping)
        else payload
    )
    if not isinstance(progress_payload, Mapping):
        raise S48Error("terminal-failure partial payload is invalid")
    takes = progress_payload.get("takes", [])
    if not isinstance(takes, list):
        raise S48Error("terminal-failure payload takes must be a list")
    current_take = (
        partial_progress.get("current_take")
        if isinstance(partial_progress, Mapping)
        else None
    )
    if current_take is not None and not isinstance(current_take, Mapping):
        raise S48Error("terminal-failure current take progress is invalid")
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
            "partial_current_take": current_take,
            "run_failure": dict(run_failure),
            "attempt_records": inventory,
            "all_planned_takes_retained": True,
        },
        "final_validation.json": {
            "schema": "ias.s4_8.final_validation.v1",
            "package_profile": TERMINAL_FAILURE_PROFILE,
            "status": "failed",
            "readiness_passed": False,
            "scientific_readiness_passed": (evaluation.get("readiness_passed") is True),
            "scientific_evaluation_state": derived.get(
                "evaluation_state", "evaluation_completed"
            ),
            "scientific_evaluation_status": evaluation.get("status"),
            "run_failure": dict(run_failure),
            "terminal": True,
            "automatic_retry_forbidden": True,
            "planned_take_count": 47,
            "completed_take_count": len(takes),
            "partial_current_take": current_take,
            "historical_preservation_passed": (preservation["status"] == "passed"),
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
            "condition_inputs": progress_payload.get("sim_vs_real", []),
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
                item.get("selected_for_evaluation") is True for item in inventory
            ),
            "unselected_attempt_count": sum(
                item.get("selected_for_evaluation") is False for item in inventory
            ),
            "opened_attempt_count": sum(
                item.get("scientific_observation_opened") is True for item in inventory
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
            "partial_current_take": current_take,
        },
        "window_results.json": {
            "schema": "ias.s4_8.window_results.v1",
            "status": "partial" if len(takes) < 47 else "complete",
            "record_count": sum(len(take.get("bearing_windows", [])) for take in takes)
            + (
                int(current_take.get("completed_window_count", 0))
                if isinstance(current_take, Mapping)
                else 0
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
            "partial_current_take": current_take,
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
    _fsync_package_tree(destination)
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
    staging = _durable_mkdtemp(
        parent=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".staging",
        boundary="evidence_package_staging",
    )
    try:
        result = _build_evidence_package_in_place(
            root,
            derived,
            destination=staging,
            source_commit=source_commit,
        )
        _fsync_package_tree(staging)
        os.replace(staging, destination)
        _fsync_directory(destination.parent)
    except Exception as exc:
        if staging.exists():
            _remove_directory_durably(staging)
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
    _validate_authorization_evidence(derived, config=load_contract(root))
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
            "comparison_classifications": evaluation["comparison_classifications"],
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
            "sealed_attempt_count": len(derived.get("observation_inventory", [])),
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
        "scientific_readiness_passed": (evaluation.get("readiness_passed") is True),
        "scientific_evaluation_state": derived.get(
            "evaluation_state", "evaluation_completed"
        ),
        "scientific_evaluation_status": evaluation.get("status"),
        "run_failure": derived.get("run_failure"),
        "terminal": True,
        "automatic_retry_forbidden": True,
        "readiness_criterion_count": len(
            [item for item in evaluation.get("criteria", []) if item["gating"]]
        ),
        "stretch_criterion_count": len(
            [item for item in evaluation.get("criteria", []) if not item["gating"]]
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
    _fsync_package_tree(destination)
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
            f"S4.8 package files mismatch: missing={sorted(PACKAGE_FILES - present)}, "
            f"extra={sorted(present - PACKAGE_FILES)}"
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
    _validate_authorization_evidence(
        derived,
        config=load_contract(repo_root.resolve()),
    )
    recomputed = _recomputed_evaluation(repo_root, derived)
    criteria = load_json(package / "criteria_results.json")
    if criteria != recomputed:
        raise S48Error("S4.8 criteria results contradict scientific recomputation")
    final = load_json(package / "final_validation.json")
    if final.get("package_profile") == TERMINAL_FAILURE_PROFILE:
        return _validate_terminal_failure_package(
            package,
            repo_root=repo_root.resolve(),
            regenerate=True,
        )
    expected_overall_readiness = (
        criteria.get("readiness_passed") is True and derived.get("run_failure") is None
    )
    if (
        final.get("package_profile") != FULL_EVIDENCE_PROFILE
        or final["readiness_passed"] is not expected_overall_readiness
        or final.get("scientific_readiness_passed")
        is not (criteria.get("readiness_passed") is True)
        or final.get("scientific_evaluation_state")
        != derived.get("evaluation_state", "evaluation_completed")
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
    if not isinstance(conditions, list):
        raise S48Error("S4.8 sim-versus-real condition inventory invalid")
    condition_count = sum(len(item.get("conditions", [])) for item in conditions)
    if input_rejected:
        if (conditions and (len(conditions) != 7 or condition_count != 271)) or sim.get(
            "comparison_classifications"
        ):
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
        key: value for key, value in ledger_event.items() if key != "event_sha256"
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
            if (package / name).read_bytes() != (regenerated / name).read_bytes()
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
        or provenance.get("runtime_sha256") != canonical_sha256(expected_runtime)
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
            raise S48Error(f"S4.8 terminal-failure index mismatch: {record['path']}")
    derived = load_json(package / "derived_evaluation_input.json")
    _validate_authorization_evidence(
        derived,
        config=load_contract(repo_root.resolve()),
    )
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
        or final.get("scientific_readiness_passed")
        is not (evaluation.get("readiness_passed") is True)
        or final.get("scientific_evaluation_state")
        != derived.get("evaluation_state", "evaluation_completed")
        or final.get("run_failure") != run_failure
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
    ):
        raise S48Error("S4.8 terminal-failure result is contradictory")
    inventory = load_json(package / "take_inventory.json")
    attempt_records = derived.get("observation_inventory")
    partial_progress = derived.get("partial_progress")
    progress_payload = (
        partial_progress.get("payload")
        if isinstance(partial_progress, Mapping)
        else derived.get("payload", {})
    )
    takes = (
        progress_payload.get("takes") if isinstance(progress_payload, Mapping) else None
    )
    current_take = (
        partial_progress.get("current_take")
        if isinstance(partial_progress, Mapping)
        else None
    )
    if (
        not isinstance(attempt_records, list)
        or len(attempt_records) != 48
        or inventory.get("attempt_records") != attempt_records
        or not isinstance(takes, list)
        or inventory.get("records") != takes
        or inventory.get("partial_current_take") != current_take
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
    partial_derived = 0
    if current_take is not None:
        if not isinstance(current_take, Mapping):
            raise S48Error("S4.8 current-take partial progress is invalid")
        completed_windows = current_take.get("completed_windows")
        completed_count = current_take.get("completed_window_count")
        expected_count = current_take.get("expected_window_count")
        failed_index = current_take.get("failed_window_index")
        if (
            not isinstance(completed_windows, list)
            or completed_count != len(completed_windows)
            or not isinstance(expected_count, int)
            or expected_count <= 0
            or not isinstance(completed_count, int)
            or completed_count < 0
            or completed_count > expected_count
            or [item.get("window_index") for item in completed_windows]
            != list(range(completed_count))
            or (failed_index is not None and failed_index != completed_count)
        ):
            raise S48Error("S4.8 intra-take window progress is inconsistent")
        partial_derived = int(completed_count > 0)
        matching = [
            record
            for record in selected
            if record.get("planned_take_id") == current_take.get("planned_take_id")
            and record.get("scientific_observation_opened") is True
        ]
        if len(matching) != 1 or (
            matching[0].get("scientific_observations_derived")
            is not (completed_count > 0)
        ):
            raise S48Error("S4.8 current-take inventory progress mismatch")
    if (
        inventory.get("opened_attempt_count") != len(opened)
        or inventory.get("derived_attempt_count") != len(derived_records)
        or inventory.get("unopened_selected_take_count") != 47 - len(opened)
        or len(derived_records) != len(takes) + partial_derived
    ):
        raise S48Error("S4.8 terminal-failure progress counts mismatch")
    windows_report = load_json(package / "window_results.json")
    if windows_report.get("partial_current_take") != current_take or windows_report.get(
        "record_count"
    ) != sum(len(take.get("bearing_windows", [])) for take in takes) + (
        int(current_take.get("completed_window_count", 0))
        if isinstance(current_take, Mapping)
        else 0
    ):
        raise S48Error("S4.8 terminal-failure window progress mismatch")
    if load_json(package / "robustness.json").get("status") != "not_evaluable":
        raise S48Error("S4.8 robustness must be not_evaluable")
    authorization = load_json(package / "authorization_access.json")
    ledger_event = authorization.get("ledger_event")
    if (
        authorization.get("grant_consumed_exactly_once") is not True
        or not isinstance(ledger_event, Mapping)
        or ledger_event.get("event_sha256")
        != canonical_sha256(
            {key: value for key, value in ledger_event.items() if key != "event_sha256"}
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
                if (package / name).read_bytes() != (regenerated / name).read_bytes()
            ]
            if mismatched:
                raise S48Error(
                    "S4.8 terminal-failure replay mismatch: " + ", ".join(mismatched)
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
        _ensure_durable_directory(
            output,
            parents=True,
            exist_ok=False,
            boundary="replay_output",
        )
        try:
            _build_terminal_failure_package_in_place(
                repo_root.resolve(),
                derived,
                destination=output,
                source_commit=source_commit,
            )
        except Exception:
            if output.exists():
                _remove_directory_durably(output)
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
        path.name: path.read_bytes() for path in canonical.iterdir() if path.is_file()
    }
    right = {
        path.name: path.read_bytes() for path in output.iterdir() if path.is_file()
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
    window_progress_callback: (Callable[[Mapping[str, Any]], None] | None) = None,
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
        raise S48Error(f"{take_id}: expected {expected_count} exact windows at 16 kHz")
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
        {} if target is None else _expected_tdoa(positions, ids, float(target), 343.0)
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
        try:
            (
                record,
                confidence,
                measured_tdoa,
                correlations,
                elapsed_ms,
                adapter_elapsed_ms,
            ) = _analyze_window(
                frame_raw,
                ids=ids,
                position_map=position_map,
                sample_rate_hz=rate,
                max_delay_s=max_delay,
                index=index,
                start=start,
                take_id=take_id,
            )
        except Exception as exc:
            raise S48PartialTakeError(
                f"{take_id}: window {index} analysis failed",
                expected_window_count=expected_count,
                failed_window_index=index,
                completed_windows=[dict(item) for item in windows],
                cause=exc,
            ) from exc
        bearing = record["srp_bearing_deg_f_project"]
        if bearing is not None:
            valid_bearings.append(float(bearing))
        confidences.append(confidence)
        runtime_ms.append(250.0 + elapsed_ms)
        adapter_ms.append(adapter_elapsed_ms)
        for key, value in measured_tdoa.items():
            tdoa_by_pair[key].append(value * 1_000_000.0)
        for key, value in correlations.items():
            correlation_by_pair[key].append(value)
        windows.append(record)
        if window_progress_callback is not None:
            try:
                window_progress_callback(
                    {
                        "expected_window_count": expected_count,
                        "completed_window_count": len(windows),
                        "completed_windows": [dict(item) for item in windows],
                        "failed_window_index": None,
                    }
                )
            except Exception as exc:
                raise S48PartialTakeError(
                    f"{take_id}: window {index} progress persistence failed",
                    expected_window_count=expected_count,
                    failed_window_index=index + 1,
                    completed_windows=[dict(item) for item in windows],
                    cause=exc,
                ) from exc
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
        [_circular_difference(float(target), value) for value in valid_bearings]
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
        [representative] if applicable_bearing and representative is not None else []
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
            "abstained_window_count": sum(item["abstained"] for item in windows),
            "sub_floor_direction_emission_count": 0,
        },
        "channels": channels,
        "bearing_absolute_error_deg": (float(median(errors)) if errors else None),
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
            if identity.stratum_id in {"B_center_nominal_level", "C_center_low_level"}
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


def _analyze_window(
    frame_raw: np.ndarray,
    *,
    ids: Sequence[str],
    position_map: Mapping[str, tuple[float, ...]],
    sample_rate_hz: int,
    max_delay_s: float,
    index: int,
    start: int,
    take_id: str,
) -> tuple[
    dict[str, Any],
    float,
    dict[str, float],
    dict[str, float],
    float,
    float,
]:
    started = time.perf_counter_ns()
    per_rms = np.sqrt(np.mean(frame_raw * frame_raw, axis=1))
    signal = float(np.median(per_rms)) > 0.002
    bearing: float | None = None
    confidence = 0.0
    measured_tdoa: dict[str, float] = {}
    correlations: dict[str, float] = {}
    if signal:
        waveforms = {mic_id: frame_raw[channel] for channel, mic_id in enumerate(ids)}
        srp = srp_phat_direction(
            waveforms,
            mic_positions_m=position_map,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=343.0,
            azimuth_step_deg=2.0,
            max_delay_s=max_delay_s,
            interp=8,
        )
        confidence = float(srp_phat_confidence(srp))
        if confidence >= 0.015:
            bearing = float(srp.bearing_deg)
        tdoa, _peaks = estimate_tdoa_diagnostics(
            waveforms,
            sample_rate_hz=sample_rate_hz,
            max_delay_s=max_delay_s,
            interp=8,
        )
        measured_tdoa = {key: float(value) for key, value in tdoa.items()}
        for left in range(4):
            for right in range(left + 1, 4):
                key = f"{ids[left]}->{ids[right]}"
                correlations[key] = _aligned_correlation(
                    frame_raw[left],
                    frame_raw[right],
                    measured_tdoa[key],
                    sample_rate_hz,
                )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
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
    adapter_elapsed_ms = (time.perf_counter_ns() - adapter_started) / 1_000_000.0
    if restored != record:
        raise S48Error(f"{take_id}: adapter round trip changed a window")
    return (
        record,
        confidence,
        measured_tdoa,
        correlations,
        elapsed_ms,
        adapter_elapsed_ms,
    )


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
    if (
        len(frames) < 2
        or any(
            later <= earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        )
        or any(
            later <= earlier
            for earlier, later in zip(host_times_ms, host_times_ms[1:], strict=False)
        )
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
    audio_candidates = [int(record["peak_sample"]) for record in transient["events"]]
    audio_samples = _select_three_spaced_events(
        audio_candidates,
        sample_rate_hz=16000,
        expected_interval_s=float(contract["analysis"]["av_expected_interval_s"]),
    )
    producer = load_json(producer_path)
    audio_start_ms = (
        1000.0 * _parse_utc(producer.get("started_wall_time_utc")).timestamp()
    )
    depth_motion = _depth_grid_motion(frames)
    search_half_width = float(contract["analysis"]["av_visual_search_half_width_ms"])
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
                f"{attempt_root.name}: no visual candidate for event {event_index}"
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
                "visual_motion_mean_absolute_depth_delta_m": depth_motion[video_index],
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
    context = load_json(repo_root / "configs/s4_6_profile_application.v1.json")[
        "application_context"
    ]
    application = apply_profile_application(
        validate_audio_config(raw_config),
        repo_root=repo_root,
        mode=mode,
        runtime_context=context if mode == "apply" else None,
    )
    if application.mode != mode:
        raise S48Error(f"simulation profile mode mismatch: {mode}")
    expected_applied = 7 if mode == "apply" else 0
    if (
        sum(row["status"] == "applied" for row in application.field_status)
        != expected_applied
    ):
        raise S48Error(f"simulation profile application count mismatch: {mode}")
    array = application.config.arrays["xvf3800_array"]
    simulation_ids = tuple(microphone.mic_id for microphone in array.microphones)
    simulation_positions = np.asarray(
        [microphone.relative_position_m for microphone in array.microphones],
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
                    else (0.75 if identity.stratum_id != "C_center_low_level" else 0.35)
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
            result["confidence_bc"][take_id] = float(detection.doa.bearing_confidence)
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
                "coordinate_convention": ("x_forward_y_right_z_up_clockwise_bearing"),
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
            list(microphone.relative_position_m) for microphone in array.microphones
        ],
        "gain_multipliers": gains,
        "application_report": application.report(),
    }


def _validate_profile_modes(repo_root: Path, config: Mapping[str, Any]) -> None:
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
    if (
        applied.mode != "apply"
        or sum(row["status"] == "applied" for row in applied.field_status) != 7
    ):
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
            repo_root / amendment_root / "access" / "technical_qa" / f"{take_id}.json"
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
        record for record in seal["artifacts"] if record["path"] == path.as_posix()
    ]
    if len(matches) != 1:
        raise S48Error(f"file is not uniquely seal-declared: {path}")
    return matches[0]


def _verify_sealed_file(repo_root: Path, path: Path, seal: Mapping[str, Any]) -> None:
    relative = path.relative_to(repo_root).as_posix()
    matches = [record for record in seal["artifacts"] if record["path"] == relative]
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
            for pair_id in corrective["identity_contract"]["microphone_pair_ids"]
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


def _require_consumed_ledger(repo_root: Path, config: Mapping[str, Any]) -> None:
    ledger_path = repo_root / config["grant"]["ledger_path"]
    if not ledger_path.is_file():
        raise S48Error("S4.8 ledger is absent; observations remain closed")
    grant = load_json(repo_root / config["grant"]["path"])
    expected_id = grant["grant_id"]
    ledger_validation = validate_ledger(
        ledger_path,
        expected_seal_sha256=grant["seal_sha256"],
    )
    if ledger_validation["status"] != "passed" or ledger_validation["event_count"] != 1:
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
        (repo_root / config["grant"]["path"]).with_name("authorization_record.v1.json")
    )
    _validate_authorization_record(
        authorization,
        config=config,
        source_commit=str(authorization.get("source_commit")),
        grant=grant,
        ledger_event=opened[0],
    )
    journal = _load_run_journal(repo_root / config["evidence"]["run_journal_path"])
    journal_events = [record.get("event") for record in journal]
    if journal_events[:2] != [
        "grant_consumed",
        "observation_opening_authorized",
    ] or journal_events[2:] not in ([], ["post_consumption_started"]):
        raise S48Error("S4.8 atomic opening transition journal is incomplete")
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
    last_event = records[-1].get("event") if records else None
    allowed: dict[str | None, set[str]] = {
        None: {"grant_consumed"},
        "grant_consumed": {"observation_opening_authorized"},
        "observation_opening_authorized": {
            "post_consumption_started",
            "first_run_finalization_prepared",
        },
        "post_consumption_started": {
            "post_consumption_progress",
            "first_run_finalization_prepared",
        },
        "post_consumption_progress": {
            "post_consumption_progress",
            "first_run_finalization_prepared",
        },
        "first_run_finalization_prepared": {
            "first_run_downgrade_intent",
            "first_run_terminal",
        },
        "first_run_downgrade_intent": {"first_run_finalization_failed"},
        "first_run_finalization_failed": {"first_run_terminal"},
    }
    domain_events = {item for choices in allowed.values() for item in choices}
    domain_events.update(key for key in allowed if isinstance(key, str))
    generic_chain = event_name not in domain_events and last_event not in domain_events
    if event_name not in allowed.get(last_event, set()) and not generic_chain:
        raise S48Error(
            f"S4.8 journal transition {last_event!r} -> {event_name!r} is invalid"
        )
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
                record = json.loads(line, parse_constant=_reject_json_constant)
            except (ValueError, json.JSONDecodeError) as exc:
                raise S48Error(f"S4.8 run journal JSON is invalid: {exc}") from exc
            if not isinstance(record, dict):
                raise S48Error("S4.8 run journal contains a non-object")
            records.append(record)
    previous = "0" * 64
    for sequence, record in enumerate(records):
        supplied = record.get("event_sha256")
        payload = {key: value for key, value in record.items() if key != "event_sha256"}
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
    prefix = ["grant_consumed", "observation_opening_authorized"]
    remainder = events[2:]
    if remainder[:1] == ["post_consumption_started"]:
        remainder = remainder[1:]
        while remainder[:1] == ["post_consumption_progress"]:
            remainder = remainder[1:]
    if events[:2] != prefix or remainder not in (
        ["first_run_finalization_prepared", "first_run_terminal"],
        [
            "first_run_finalization_prepared",
            "first_run_downgrade_intent",
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
    _ensure_durable_directory(
        path.parent,
        parents=True,
        exist_ok=True,
        boundary="transition_lock_parent",
    )
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_execution_lock(path: Path) -> Iterator[None]:
    """Acquire the persistent nonblocking lock for the whole authorized run."""

    _ensure_durable_directory(
        path.parent,
        parents=True,
        exist_ok=True,
        boundary="execution_lock_parent",
    )
    with path.open("a+b") as stream:
        try:
            lock_path = path.resolve()
            lease = _issue_execution_lock_lease(
                repo_root=lock_path.parent.parent,
                lock_path=lock_path,
                stream=stream,
            )
        except BlockingIOError as exc:
            raise S48Error(
                "S4.8 authorized execution is already active; state unchanged"
            ) from exc
        token = _ACTIVE_EXECUTION_LEASE.set(lease)
        try:
            _fsync_directory(path.parent)
            yield
        finally:
            lease._revoke()
            try:
                _ACTIVE_EXECUTION_LEASE.reset(token)
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _require_execution_lock(repo_root: Path) -> None:
    pid = os.getpid()
    lease = _ACTIVE_EXECUTION_LEASE.get()
    expected_root = repo_root.resolve()
    expected_lock = (expected_root / AUTHORIZED_EXECUTION_LOCK_PATH).resolve()
    valid = (
        lease is not None
        and _is_issued_execution_lock_lease(lease)
        and lease._active
        and lease._pid == pid
        and lease._repo_root == expected_root
        and lease._lock_path == expected_lock
        and not lease._stream.closed
    )
    if valid:
        try:
            descriptor = lease._stream.fileno()
            descriptor_stat = os.fstat(descriptor)
            lock_stat = expected_lock.stat()
        except (OSError, ValueError):
            valid = False
        else:
            valid = (
                descriptor == lease._descriptor
                and descriptor_stat.st_dev == lock_stat.st_dev
                and descriptor_stat.st_ino == lock_stat.st_ino
            )
            if valid:
                try:
                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except OSError:
                    valid = False
    if not valid:
        raise S48Error(
            "S4.8 irreversible operation requires the authorized execution lock"
        )


def _ensure_durable_directory(
    path: Path,
    *,
    parents: bool,
    exist_ok: bool,
    boundary: str,
) -> bool:
    """Create directories one at a time and durably publish each entry."""

    if path.is_symlink():
        raise S48Error(f"S4.8 state directory may not be a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise S48Error(f"S4.8 state directory is invalid: {path}")
        if not exist_ok:
            raise FileExistsError(path)
        _directory_creation_step(f"{boundary}:before_parent_fsync", path)
        _fsync_directory(path.parent)
        _directory_creation_step(f"{boundary}:after_parent_fsync", path)
        return False

    missing = [path]
    if parents:
        ancestor = path.parent
        while not ancestor.exists() and not ancestor.is_symlink():
            missing.append(ancestor)
            if ancestor == ancestor.parent:
                break
            ancestor = ancestor.parent
        if ancestor.is_symlink() or not ancestor.is_dir():
            raise S48Error(f"S4.8 state directory ancestor is invalid: {ancestor}")
    elif not path.parent.is_dir() or path.parent.is_symlink():
        raise S48Error(f"S4.8 state directory parent is invalid: {path.parent}")

    for directory in reversed(missing):
        _directory_creation_step(f"{boundary}:before_mkdir", directory)
        directory.mkdir()
        _directory_creation_step(f"{boundary}:after_mkdir", directory)
        _directory_creation_step(f"{boundary}:before_parent_fsync", directory)
        _fsync_directory(directory.parent)
        _directory_creation_step(f"{boundary}:after_parent_fsync", directory)
    return True


def _durable_mkdtemp(
    *,
    parent: Path,
    prefix: str,
    suffix: str,
    boundary: str,
) -> Path:
    """Create and durably anchor one private same-filesystem directory."""

    _ensure_durable_directory(
        parent,
        parents=True,
        exist_ok=True,
        boundary=f"{boundary}_parent",
    )
    _directory_creation_step(f"{boundary}:before_mkdir", parent)
    path = Path(tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=parent))
    _directory_creation_step(f"{boundary}:after_mkdir", path)
    _directory_creation_step(f"{boundary}:before_parent_fsync", path)
    _fsync_directory(parent)
    _directory_creation_step(f"{boundary}:after_parent_fsync", path)
    return path


def _remove_directory_durably(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise S48Error(f"S4.8 crash directory is invalid: {path}")
    shutil.rmtree(path)
    _fsync_directory(path.parent)


def _anchor_existing_one_shot_directories(
    repo_root: Path,
    config: Mapping[str, Any],
) -> None:
    """Repair a possible crash gap between mkdir and containing-dir fsync."""

    grant_path = repo_root / config["grant"]["path"]
    journal_path = repo_root / config["evidence"]["run_journal_path"]
    derived_path = repo_root / config["evidence"]["derived_input_path"]
    output = repo_root / config["evidence"]["output_path"]
    candidates = {
        grant_path.parent.parent,
        grant_path.parent,
        journal_path.parent,
        _progress_path(repo_root, config),
        _progress_path(repo_root, config).with_name(
            POST_CONSUMPTION_PROGRESS_QUARANTINE_NAME
        ),
        derived_path.parent,
        derived_path.parent / "provisional_evidence.v1",
        output,
        _finalization_staging_path(output),
    }
    for path in sorted(candidates, key=lambda item: len(item.parts)):
        if path.exists() or path.is_symlink():
            _ensure_durable_directory(
                path,
                parents=False,
                exist_ok=True,
                boundary="existing_one_shot_state",
            )


def _atomic_write_text(path: Path, content: str) -> None:
    _ensure_durable_directory(
        path.parent,
        parents=True,
        exist_ok=True,
        boundary="atomic_write_parent",
    )
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


def _persist_derived_state(path: Path, derived: Mapping[str, Any]) -> None:
    _ensure_durable_directory(
        path.parent,
        parents=True,
        exist_ok=True,
        boundary="derived_state_parent",
    )
    _atomic_write_text(path, pretty_json(dict(derived)))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_package_tree(path: Path) -> None:
    """Durably flush all regular package files, then the package directory."""

    if not path.is_dir():
        raise S48Error(f"S4.8 package directory is unavailable: {path}")
    for item in sorted(path.iterdir()):
        if not item.is_file():
            continue
        descriptor = os.open(item, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _fsync_directory(path)


def _validate_source_commit(
    repo_root: Path,
    source_commit: str,
    *,
    require_current_head: bool = True,
) -> None:
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise S48Error("source commit must be a full lowercase SHA-1")
    if require_current_head and _git(repo_root, "rev-parse", "HEAD") != source_commit:
        raise S48Error("source commit must be the exact current HEAD")
    if (
        _git(repo_root, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
        != source_commit
    ):
        raise S48Error("source commit is not available")
    dependencies = _result_dependency_paths(repo_root, source_commit)
    for path in dependencies:
        current = repo_root / path
        if not current.is_file():
            raise S48Error(f"S4.8 result dependency is missing: {path}")
        committed = _git_blob(repo_root, source_commit, path)
        if current.read_bytes() != committed:
            raise S48Error(f"S4.8 result dependency differs from source commit: {path}")
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


def _result_dependency_paths(repo_root: Path, source_commit: str) -> tuple[Path, ...]:
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
        if (name in exact or any(name.startswith(prefix) for prefix in roots))
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
                "distribution_metadata_version": (
                    importlib.metadata.version(distribution_name)
                ),
                "module": module_name,
                "module_runtime_version": (
                    getattr(module, "__version__", None)
                    if module_name == "isaac_audio_sensors"
                    else None
                ),
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
        "partition_manifest_sha256": contract["holdout"]["partition_manifest_sha256"],
        "split_plan_sha256": contract["holdout"]["split_plan_sha256"],
        "session_manifest_sha256": contract["holdout"]["session_manifest_sha256"],
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
        "s4_6_config_sha256": contract["profile_application"]["config_sha256"],
        "s4_6_active_pointer_sha256": contract["profile_application"][
            "active_pointer_sha256"
        ],
        "s4_3_effective_config_sha256": contract["analysis"][
            "s4_3_effective_config_sha256"
        ],
        "s4_3_transient_contract_sha256": contract["analysis"][
            "transient_contract_sha256"
        ],
        "s4_6_application_report": _profile_runtime(repo_root)["application_report"],
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
        raise S48Error(f"S4.8 result dependency is absent from {commit}: {path}")
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
    (package / "evidence_index.json").write_text(pretty_json(index), encoding="utf-8")
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
    "build_simulation_comparisons",
    "create_grant",
    "evaluate_payload",
    "load_contract",
    "preopen_validate",
    "preservation_report",
    "replay_evidence_package",
    "run_authorized_evaluation_once",
    "validate_evidence_package",
]
