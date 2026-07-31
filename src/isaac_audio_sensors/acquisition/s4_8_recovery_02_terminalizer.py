"""Forward-only terminalization for the completed S4.8 amendment-02 run."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition.s4_8_recovery_02_profiles import (
    require_input_contract_rejected,
)

CONTRACT_PATH = Path("configs/s4_8_recovery_amendment_02_terminalization.v1.json")
CONTRACT_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_amendment_02_terminalization.v1.schema.json"
)
PACKAGE_FILES = frozenset(
    {
        "SHA256SUMS",
        "evidence_index.json",
        "heldout_evaluation_input.v2.json",
        "terminal_validation.v1.json",
        "terminalization_authorization.v1.json",
    }
)
CORE_INPUT_ROLES = frozenset(
    {
        "scientific_grant",
        "scientific_authorization",
        "scientific_ledger",
        "scientific_journal",
        "recovery_context",
        "derived_state",
        "independent_review",
        "amendment_contract",
    }
)


class S48TerminalizationError(RuntimeError):
    """Raised when the terminalization-only boundary does not authenticate."""


@dataclass(frozen=True)
class _InputSnapshot:
    role: str
    relative_path: str
    sha256: str
    data: bytes


@dataclass(frozen=True)
class _ValidatedState:
    root: Path
    implementation_commit: str
    contract: dict[str, Any]
    contract_sha256: str
    authorization_schema: dict[str, Any]
    terminal_schema: dict[str, Any]
    snapshots: dict[str, _InputSnapshot]
    derived: dict[str, Any]
    binding: dict[str, Any]
    binding_sha256: str
    candidate_authorization_id: str
    authorization_path: Path
    output_path: Path
    closeout_path: Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(_canonical_bytes(value))


def _pretty_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise S48TerminalizationError("terminalization path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise S48TerminalizationError(f"unsafe terminalization path: {value}")
    return path


def _is_within(path: PurePosixPath, parent: PurePosixPath) -> bool:
    return path == parent or parent in path.parents


def _filesystem_path(root: Path, relative: str) -> Path:
    parsed = _relative_path(relative)
    candidate = root.joinpath(*parsed.parts)
    if candidate.resolve(strict=False) != root.resolve().joinpath(*parsed.parts):
        raise S48TerminalizationError(
            f"terminalization path escapes repository: {relative}"
        )
    return candidate


def _read_regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise S48TerminalizationError(
            f"terminalization input is not a regular file: {path}"
        )
    with path.open("rb") as stream:
        return stream.read()


def _json_from_bytes(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise S48TerminalizationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise S48TerminalizationError(f"{label} must be a JSON object")
    return value


def _json_lines(data: bytes, *, label: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise S48TerminalizationError(f"{label} is not UTF-8") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise S48TerminalizationError(
                f"{label} line {line_number} is invalid"
            ) from exc
        if not isinstance(record, dict):
            raise S48TerminalizationError(
                f"{label} line {line_number} must be an object"
            )
        records.append(record)
    if not records:
        raise S48TerminalizationError(f"{label} is empty")
    return records


def _load_schema(root: Path, relative: str) -> tuple[dict[str, Any], str]:
    path = _filesystem_path(root, relative)
    data = _read_regular_bytes(path)
    schema = _json_from_bytes(data, label=relative)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise S48TerminalizationError(
            f"terminalization schema is invalid: {relative}"
        ) from exc
    return schema, _sha256(data)


def _load_contract(
    root: Path,
) -> tuple[
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    dict[str, Any],
    str,
]:
    contract_path = _filesystem_path(root, CONTRACT_PATH.as_posix())
    contract_data = _read_regular_bytes(contract_path)
    contract = _json_from_bytes(
        contract_data,
        label=CONTRACT_PATH.as_posix(),
    )
    contract_schema, _ = _load_schema(root, CONTRACT_SCHEMA_PATH.as_posix())
    try:
        jsonschema.validate(contract, contract_schema)
    except jsonschema.ValidationError as exc:
        raise S48TerminalizationError(
            "terminalization contract schema mismatch"
        ) from exc
    authorization_schema, authorization_schema_sha256 = _load_schema(
        root,
        contract["authorization"]["schema_path"],
    )
    terminal_schema, terminal_schema_sha256 = _load_schema(
        root,
        contract["publication"]["terminal_schema_path"],
    )
    _validate_contract_semantics(contract)
    return (
        contract,
        _sha256(contract_data),
        authorization_schema,
        authorization_schema_sha256,
        terminal_schema,
        terminal_schema_sha256,
    )


def _validate_contract_semantics(contract: Mapping[str, Any]) -> None:
    inputs = contract["allowed_inputs"]
    roles = [record["role"] for record in inputs]
    paths = [record["path"] for record in inputs]
    if (
        len(roles) != len(set(roles))
        or len(paths) != len(set(paths))
        or not CORE_INPUT_ROLES.issubset(roles)
    ):
        raise S48TerminalizationError(
            "terminalization input allowlist is incomplete or ambiguous"
        )
    raw_roots = [_relative_path(value) for value in contract["raw_observation_roots"]]
    for value in paths:
        parsed = _relative_path(value)
        if any(_is_within(parsed, raw) for raw in raw_roots):
            raise S48TerminalizationError(f"raw observation path is forbidden: {value}")
    protected_paths = [
        contract["authorization"]["path"],
        contract["publication"]["output_path"],
        contract["publication"]["closeout_path"],
    ]
    for value in protected_paths:
        parsed = _relative_path(value)
        if value in paths or any(_is_within(parsed, raw) for raw in raw_roots):
            raise S48TerminalizationError(
                f"terminalization protected path is invalid: {value}"
            )
    if set(contract["publication"]["package_files"]) != PACKAGE_FILES:
        raise S48TerminalizationError("terminalization package file contract mismatch")
    derived = next(record for record in inputs if record["role"] == "derived_state")
    if derived["sha256"] != contract["scientific_identity"]["derived_state_sha256"]:
        raise S48TerminalizationError("terminalization derived-state binding mismatch")


def _snapshot_inputs(
    root: Path,
    contract: Mapping[str, Any],
) -> dict[str, _InputSnapshot]:
    snapshots: dict[str, _InputSnapshot] = {}
    for record in contract["allowed_inputs"]:
        path = _filesystem_path(root, record["path"])
        data = _read_regular_bytes(path)
        digest = _sha256(data)
        if digest != record["sha256"]:
            raise S48TerminalizationError(
                f"terminalization input hash mismatch: {record['role']}"
            )
        snapshots[record["role"]] = _InputSnapshot(
            role=record["role"],
            relative_path=record["path"],
            sha256=digest,
            data=data,
        )
    return snapshots


def _snapshot_json(
    snapshots: Mapping[str, _InputSnapshot],
    role: str,
) -> dict[str, Any]:
    return _json_from_bytes(
        snapshots[role].data,
        label=snapshots[role].relative_path,
    )


def _without_hash(record: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != field}


def _validate_scientific_state(
    contract: Mapping[str, Any],
    snapshots: Mapping[str, _InputSnapshot],
) -> dict[str, Any]:
    identity = contract["scientific_identity"]
    source_commit = identity["scientific_source_commit"]
    grant_id = identity["grant_id"]
    grant = _snapshot_json(snapshots, "scientific_grant")
    scientific_authorization = _snapshot_json(
        snapshots,
        "scientific_authorization",
    )
    ledger_records = _json_lines(
        snapshots["scientific_ledger"].data,
        label=snapshots["scientific_ledger"].relative_path,
    )
    journal = _json_lines(
        snapshots["scientific_journal"].data,
        label=snapshots["scientific_journal"].relative_path,
    )
    recovery_context = _snapshot_json(snapshots, "recovery_context")
    derived = _snapshot_json(snapshots, "derived_state")
    review = _snapshot_json(snapshots, "independent_review")
    amendment = _snapshot_json(snapshots, "amendment_contract")
    evaluator_binding = _snapshot_json(snapshots, "evaluator_binding")
    holdout_binding = _snapshot_json(snapshots, "holdout_binding")

    if (
        grant.get("grant_id") != grant_id
        or grant.get("single_use") is not True
        or grant.get("purpose") != "S4.8_evaluation"
        or grant.get("prerequisite", {}).get("source_commit") != source_commit
        or grant.get("grant_sha256")
        != _canonical_sha256(_without_hash(grant, "grant_sha256"))
    ):
        raise S48TerminalizationError("scientific grant binding mismatch")
    if (
        scientific_authorization.get("authorization_id") != grant_id
        or scientific_authorization.get("grant_id") != grant_id
        or scientific_authorization.get("source_commit") != source_commit
        or scientific_authorization.get("grant_sha256") != grant["grant_sha256"]
        or scientific_authorization.get("irreversible_scientific_action_acknowledged")
        is not True
    ):
        raise S48TerminalizationError("scientific authorization binding mismatch")
    if len(ledger_records) != 1:
        raise S48TerminalizationError("scientific holdout-opening count is not one")
    ledger = ledger_records[0]
    if (
        ledger.get("sequence") != 0
        or ledger.get("event") != "holdout_open_authorized"
        or ledger.get("holdout_opened") is not True
        or ledger.get("grant_id") != grant_id
        or ledger.get("grant_sha256") != grant["grant_sha256"]
        or ledger.get("event_sha256")
        != _canonical_sha256(_without_hash(ledger, "event_sha256"))
    ):
        raise S48TerminalizationError("scientific ledger binding mismatch")
    previous = "0" * 64
    for sequence, record in enumerate(journal):
        if (
            record.get("sequence") != sequence
            or record.get("previous_event_sha256") != previous
            or record.get("source_commit") != source_commit
            or record.get("event_sha256")
            != _canonical_sha256(_without_hash(record, "event_sha256"))
        ):
            raise S48TerminalizationError(
                f"scientific journal chain mismatch at sequence {sequence}"
            )
        previous = record["event_sha256"]
    if (
        journal[0].get("event") != "grant_consumed"
        or journal[1].get("event") != "observation_opening_authorized"
        or journal[0].get("ledger_event_sha256") != ledger["event_sha256"]
        or journal[1].get("ledger_event_sha256") != ledger["event_sha256"]
        or journal[-1].get("evaluation_state") != "evaluation_completed"
        or any(record.get("event") == "first_run_terminal" for record in journal)
    ):
        raise S48TerminalizationError(
            "scientific journal terminalization boundary mismatch"
        )
    if (
        recovery_context.get("context_sha256")
        != _canonical_sha256(_without_hash(recovery_context, "context_sha256"))
        or recovery_context.get("source_commit") != source_commit
        or recovery_context.get("authorization_record") != scientific_authorization
        or recovery_context.get("grant", {}).get("file_sha256")
        != snapshots["scientific_grant"].sha256
        or recovery_context.get("grant", {}).get("grant_sha256")
        != grant["grant_sha256"]
    ):
        raise S48TerminalizationError("recovery-context binding mismatch")
    if (
        review.get("schema") != "ias.s4_8.independent_recovery_review.v1"
        or review.get("amendment_id") != "s4_8_recovery_amendment_02"
        or review.get("source_commit") != source_commit
        or review.get("decision") != "approved"
        or review.get("independent") is not True
    ):
        raise S48TerminalizationError("independent review binding mismatch")
    prerequisite = grant["prerequisite"]
    if (
        amendment.get("amendment_id") != prerequisite["amendment_id"]
        or amendment.get("revision_id") != prerequisite["revision_id"]
        or prerequisite.get("evaluator_binding_sha256")
        != snapshots["evaluator_binding"].sha256
        or prerequisite.get("holdout_binding_file_sha256")
        != snapshots["holdout_binding"].sha256
        or prerequisite.get("independent_review_file_sha256")
        != snapshots["independent_review"].sha256
        or prerequisite.get("holdout_seal_file_sha256")
        != snapshots["holdout_seal"].sha256
        or evaluator_binding.get("bindings", {})
        .get("holdout_binding", {})
        .get("sha256")
        != snapshots["holdout_binding"].sha256
        or holdout_binding.get("holdout_seal", {}).get("sha256")
        != snapshots["holdout_seal"].sha256
    ):
        raise S48TerminalizationError("immutable scientific metadata binding mismatch")
    evaluation = derived.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise S48TerminalizationError("derived evaluation is unavailable")
    try:
        profile = require_input_contract_rejected(evaluation)
    except ValueError as exc:
        raise S48TerminalizationError(str(exc)) from exc
    run_failure = derived.get("run_failure")
    if (
        derived.get("source_commit") != source_commit
        or derived.get("authorization_record") != scientific_authorization
        or derived.get("ledger_event") != ledger
        or derived.get("grant", {}).get("file_sha256")
        != snapshots["scientific_grant"].sha256
        or derived.get("grant", {}).get("grant_sha256") != grant["grant_sha256"]
        or derived.get("evaluation_state") != "evaluation_completed"
        or derived.get("evaluation_sha256") != identity["evaluation_sha256"]
        or _canonical_sha256(evaluation) != identity["evaluation_sha256"]
        or evaluation.get("evaluation_invocation_count") != 1
        or profile != identity["evaluation_profile"]
        or not isinstance(run_failure, Mapping)
        or run_failure.get("automatic_retry_forbidden") is not True
        or run_failure.get("terminal") is not True
        or derived.get("run_journal", {}).get("path")
        != snapshots["scientific_journal"].relative_path
    ):
        raise S48TerminalizationError(
            "authoritative derived evaluation binding mismatch"
        )
    return derived


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S48TerminalizationError(
            f"git {' '.join(arguments)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _validate_repository(
    root: Path,
    *,
    implementation_commit: str,
    baseline_commit: str,
    scientific_source_commit: str,
) -> None:
    if len(implementation_commit) != 40 or any(
        character not in "0123456789abcdef" for character in implementation_commit
    ):
        raise S48TerminalizationError(
            "terminalizer implementation commit must be a full lowercase SHA-1"
        )
    if _git(root, "rev-parse", "HEAD") != implementation_commit:
        raise S48TerminalizationError(
            "terminalizer implementation commit is not current HEAD"
        )
    if _git(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise S48TerminalizationError("tracked or staged changes are present")
    parents = _git(
        root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        implementation_commit,
    ).split()
    if parents != [implementation_commit, baseline_commit]:
        raise S48TerminalizationError(
            "terminalizer implementation commit is not the sole child of baseline"
        )
    result = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            scientific_source_commit,
            implementation_commit,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise S48TerminalizationError(
            "scientific source commit is not an ancestor of implementation"
        )


def _path_state(path: Path, *, label: str) -> bool:
    if path.is_symlink():
        raise S48TerminalizationError(f"{label} path is a symlink")
    if path.exists() and not path.is_file():
        raise S48TerminalizationError(f"{label} path has invalid type")
    return path.is_file()


def _output_state(path: Path) -> bool:
    if path.is_symlink():
        raise S48TerminalizationError("terminal package path is a symlink")
    return path.exists()


def _authorization_binding(
    *,
    contract: Mapping[str, Any],
    contract_sha256: str,
    implementation_commit: str,
    snapshots: Mapping[str, _InputSnapshot],
    authorization_schema_sha256: str,
    terminal_schema_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "ias.s4_8.recovery_02.terminalization_authorization_binding.v1",
        "terminalization_contract_id": contract["contract_id"],
        "terminalization_contract_sha256": contract_sha256,
        "scientific_source_commit": contract["scientific_identity"][
            "scientific_source_commit"
        ],
        "terminalizer_implementation_commit": implementation_commit,
        "scientific_grant_id": contract["scientific_identity"]["grant_id"],
        "immutable_evidence_sha256": {
            role: snapshot.sha256 for role, snapshot in sorted(snapshots.items())
        },
        "authorization_schema_sha256": authorization_schema_sha256,
        "terminal_schema_sha256": terminal_schema_sha256,
        "authorization_path": contract["authorization"]["path"],
        "output_path": contract["publication"]["output_path"],
    }


def _prepare_state(
    repo_root: Path,
    *,
    implementation_commit: str,
    authorization_policy: str,
) -> _ValidatedState:
    root = repo_root.resolve()
    (
        contract,
        contract_sha256,
        authorization_schema,
        authorization_schema_sha256,
        terminal_schema,
        terminal_schema_sha256,
    ) = _load_contract(root)
    _validate_repository(
        root,
        implementation_commit=implementation_commit,
        baseline_commit=contract["implementation_baseline_commit"],
        scientific_source_commit=contract["scientific_identity"][
            "scientific_source_commit"
        ],
    )
    snapshots = _snapshot_inputs(root, contract)
    derived = _validate_scientific_state(contract, snapshots)
    binding = _authorization_binding(
        contract=contract,
        contract_sha256=contract_sha256,
        implementation_commit=implementation_commit,
        snapshots=snapshots,
        authorization_schema_sha256=authorization_schema_sha256,
        terminal_schema_sha256=terminal_schema_sha256,
    )
    binding_sha256 = _canonical_sha256(binding)
    candidate = contract["authorization"]["authorization_id_prefix"] + binding_sha256
    authorization_path = _filesystem_path(
        root,
        contract["authorization"]["path"],
    )
    output_path = _filesystem_path(
        root,
        contract["publication"]["output_path"],
    )
    closeout_path = _filesystem_path(
        root,
        contract["publication"]["closeout_path"],
    )
    authorization_present = _path_state(
        authorization_path,
        label="terminalization authorization",
    )
    if authorization_policy == "absent" and authorization_present:
        raise S48TerminalizationError("terminalization authorization already exists")
    if authorization_policy == "present" and not authorization_present:
        raise S48TerminalizationError("terminalization authorization is absent")
    if authorization_policy not in {"absent", "present"}:
        raise S48TerminalizationError("terminalization authorization policy is invalid")
    if _output_state(output_path):
        raise S48TerminalizationError("refusing to overwrite existing terminal package")
    if _path_state(closeout_path, label="terminal closeout"):
        raise S48TerminalizationError("terminal closeout already exists")
    return _ValidatedState(
        root=root,
        implementation_commit=implementation_commit,
        contract=contract,
        contract_sha256=contract_sha256,
        authorization_schema=authorization_schema,
        terminal_schema=terminal_schema,
        snapshots=snapshots,
        derived=derived,
        binding=binding,
        binding_sha256=binding_sha256,
        candidate_authorization_id=candidate,
        authorization_path=authorization_path,
        output_path=output_path,
        closeout_path=closeout_path,
    )


def preterminal_validate(
    repo_root: Path,
    *,
    implementation_commit: str,
) -> dict[str, Any]:
    """Strictly validate terminalization readiness without writing state."""

    state = _prepare_state(
        repo_root,
        implementation_commit=implementation_commit,
        authorization_policy="absent",
    )
    evaluation = state.derived["evaluation"]
    return {
        "schema": "ias.s4_8.recovery_02.preterminal_validation.v1",
        "preterminal_status": "passed",
        "scientific_source_commit": state.contract["scientific_identity"][
            "scientific_source_commit"
        ],
        "terminalizer_implementation_commit": state.implementation_commit,
        "candidate_terminalization_authorization_id": (
            state.candidate_authorization_id
        ),
        "authorization_binding_sha256": state.binding_sha256,
        "terminalization_authorization_present": False,
        "terminal_package_present": False,
        "terminal_closeout_present": False,
        "scientific_verdict": "NO-GO",
        "terminal_status": "failed",
        "readiness": False,
        "evaluation_state": state.derived["evaluation_state"],
        "evaluation_status": evaluation["status"],
        "failed_gate": "evaluation_input_contract_rejected",
        "evaluator_invocation_count": 1,
        "evaluator_raw_observation_access_count": 0,
        "scientific_recomputation_count": 0,
        "holdout_opening_count": 1,
        "automatic_retry_forbidden": True,
        "derived_state_sha256": state.snapshots["derived_state"].sha256,
        "evaluation_sha256": state.derived["evaluation_sha256"],
    }


def _validate_utc(value: str) -> None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError) as exc:
        raise S48TerminalizationError(
            "authorized-at time must be canonical UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise S48TerminalizationError("authorized-at time must be canonical UTC")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_fsync(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_create_file(path: Path, data: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise S48TerminalizationError("terminalization authorization parent is invalid")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".staging",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def create_terminalization_authorization(
    repo_root: Path,
    *,
    implementation_commit: str,
    authorization_id: str,
    authorized_at_utc: str,
) -> dict[str, Any]:
    """Create a separate immutable terminalization authorization record."""

    state = _prepare_state(
        repo_root,
        implementation_commit=implementation_commit,
        authorization_policy="absent",
    )
    if authorization_id != state.candidate_authorization_id:
        raise S48TerminalizationError("terminalization authorization identity mismatch")
    _validate_utc(authorized_at_utc)
    record = {
        "schema": state.contract["authorization"]["schema"],
        "authorization_id": authorization_id,
        "authorized_at_utc": authorized_at_utc,
        "authorization_binding": state.binding,
        "authorization_binding_sha256": state.binding_sha256,
        "terminal_package_publication_authorized": True,
        "scientific_recomputation_authorized": False,
        "raw_observation_access_authorized": False,
    }
    try:
        jsonschema.validate(record, state.authorization_schema)
    except jsonschema.ValidationError as exc:
        raise S48TerminalizationError(
            "terminalization authorization schema mismatch"
        ) from exc
    data = _pretty_json(record)
    try:
        _atomic_create_file(state.authorization_path, data)
    except FileExistsError as exc:
        raise S48TerminalizationError(
            "terminalization authorization already exists"
        ) from exc
    return {
        "schema": "ias.s4_8.recovery_02.authorization_creation.v1",
        "authorization_status": "created",
        "authorization_id": authorization_id,
        "authorization_path": state.contract["authorization"]["path"],
        "authorization_sha256": _sha256(data),
        "scientific_recomputation_authorized": False,
        "raw_observation_access_authorized": False,
        "terminal_package_published": False,
    }


def _load_terminalization_authorization(
    state: _ValidatedState,
    *,
    authorization_id: str,
) -> tuple[dict[str, Any], bytes]:
    data = _read_regular_bytes(state.authorization_path)
    record = _json_from_bytes(
        data,
        label=state.contract["authorization"]["path"],
    )
    try:
        jsonschema.validate(record, state.authorization_schema)
    except jsonschema.ValidationError as exc:
        raise S48TerminalizationError(
            "terminalization authorization schema mismatch"
        ) from exc
    if (
        record.get("authorization_id") != authorization_id
        or authorization_id != state.candidate_authorization_id
        or record.get("authorization_binding") != state.binding
        or record.get("authorization_binding_sha256") != state.binding_sha256
        or _canonical_sha256(record["authorization_binding"]) != state.binding_sha256
    ):
        raise S48TerminalizationError("terminalization authorization binding mismatch")
    return record, data


def _terminal_record(
    state: _ValidatedState,
    *,
    authorization_id: str,
) -> dict[str, Any]:
    return {
        "schema": "ias.s4_8.recovery_02.terminal_validation.v1",
        "terminalization_contract_id": state.contract["contract_id"],
        "terminalization_completed": True,
        "identities": {
            "scientific_source_commit": state.contract["scientific_identity"][
                "scientific_source_commit"
            ],
            "terminalizer_implementation_commit": state.implementation_commit,
            "terminalization_authorization_id": authorization_id,
        },
        "authorization_binding_sha256": state.binding_sha256,
        "scientific_verdict": "NO-GO",
        "terminal_status": "failed",
        "readiness": False,
        "scientific_evaluation_state": "evaluation_completed",
        "scientific_evaluation_status": "failed",
        "failed_gate": "evaluation_input_contract_rejected",
        "evaluator_invocation_count": 1,
        "evaluator_raw_observation_access_count": 0,
        "scientific_recomputation_count": 0,
        "holdout_opening_count": 1,
        "automatic_retry_forbidden": True,
        "derived_state": {
            "source_path": state.snapshots["derived_state"].relative_path,
            "source_sha256": state.snapshots["derived_state"].sha256,
            "package_path": "heldout_evaluation_input.v2.json",
            "evaluation_sha256": state.derived["evaluation_sha256"],
        },
        "immutable_evidence": {
            role: {
                "path": snapshot.relative_path,
                "sha256": snapshot.sha256,
            }
            for role, snapshot in sorted(state.snapshots.items())
        },
    }


def _package_index(staging: Path) -> dict[str, Any]:
    names = [
        "heldout_evaluation_input.v2.json",
        "terminal_validation.v1.json",
        "terminalization_authorization.v1.json",
    ]
    return {
        "schema": "ias.s4_8.recovery_02.terminal_evidence_index.v1",
        "record_count": len(names),
        "records": [
            {
                "path": name,
                "byte_size": (staging / name).stat().st_size,
                "sha256": _sha256(_read_regular_bytes(staging / name)),
            }
            for name in names
        ],
    }


def _checksum_file(staging: Path) -> bytes:
    names = sorted(PACKAGE_FILES - {"SHA256SUMS"})
    return "".join(
        f"{_sha256(_read_regular_bytes(staging / name))}  {name}\n" for name in names
    ).encode("utf-8")


def _fsync_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise S48TerminalizationError("terminalization package tree is invalid")
    for item in sorted(path.iterdir()):
        if item.is_symlink() or not item.is_file():
            raise S48TerminalizationError(
                "terminalization package contains a non-regular entry"
            )
        descriptor = os.open(item, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _fsync_directory(path)


def _validate_terminal_package(
    package: Path,
    *,
    state: _ValidatedState,
    authorization_bytes: bytes,
) -> dict[str, Any]:
    if package.is_symlink() or not package.is_dir():
        raise S48TerminalizationError("terminalization package is unavailable")
    present = {path.name for path in package.iterdir()}
    if present != PACKAGE_FILES:
        raise S48TerminalizationError("terminalization package file set mismatch")
    checksums: dict[str, str] = {}
    try:
        lines = _read_regular_bytes(package / "SHA256SUMS").decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise S48TerminalizationError("terminalization checksums are invalid") from exc
    for line in lines:
        parts = line.split("  ", maxsplit=1)
        if len(parts) != 2 or parts[1] in checksums:
            raise S48TerminalizationError("terminalization checksums are malformed")
        checksums[parts[1]] = parts[0]
    expected_names = PACKAGE_FILES - {"SHA256SUMS"}
    if set(checksums) != expected_names:
        raise S48TerminalizationError("terminalization checksum file set mismatch")
    for name, digest in checksums.items():
        if _sha256(_read_regular_bytes(package / name)) != digest:
            raise S48TerminalizationError(f"terminalization checksum mismatch: {name}")
    if (
        _read_regular_bytes(package / "heldout_evaluation_input.v2.json")
        != state.snapshots["derived_state"].data
        or _read_regular_bytes(package / "terminalization_authorization.v1.json")
        != authorization_bytes
    ):
        raise S48TerminalizationError("terminalization byte-preservation mismatch")
    terminal = _json_from_bytes(
        _read_regular_bytes(package / "terminal_validation.v1.json"),
        label="terminal_validation.v1.json",
    )
    try:
        jsonschema.validate(terminal, state.terminal_schema)
    except jsonschema.ValidationError as exc:
        raise S48TerminalizationError("terminal validation schema mismatch") from exc
    index = _json_from_bytes(
        _read_regular_bytes(package / "evidence_index.json"),
        label="evidence_index.json",
    )
    expected_index = _package_index(package)
    if index != expected_index:
        raise S48TerminalizationError("terminalization evidence index mismatch")
    return terminal


def _publication_step(_step: str, _path: Path) -> None:
    """Fault-injection seam for atomic-publication tests."""


def _remove_created_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        return
    _fsync_directory(path.parent)


def terminalize(
    repo_root: Path,
    *,
    implementation_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    """Publish the already-completed scientific failure without recomputation."""

    state = _prepare_state(
        repo_root,
        implementation_commit=implementation_commit,
        authorization_policy="present",
    )
    _authorization, authorization_bytes = _load_terminalization_authorization(
        state,
        authorization_id=authorization_id,
    )
    parent = state.output_path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise S48TerminalizationError("terminal package parent is invalid")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{state.output_path.name}.",
            suffix=".staging",
            dir=parent,
        )
    )
    _fsync_directory(parent)
    _publication_step("staging_created", staging)
    try:
        _write_fsync(
            staging / "heldout_evaluation_input.v2.json",
            state.snapshots["derived_state"].data,
        )
        _write_fsync(
            staging / "terminalization_authorization.v1.json",
            authorization_bytes,
        )
        terminal = _terminal_record(
            state,
            authorization_id=authorization_id,
        )
        try:
            jsonschema.validate(terminal, state.terminal_schema)
        except jsonschema.ValidationError as exc:
            raise S48TerminalizationError(
                "terminal validation schema mismatch"
            ) from exc
        _write_fsync(
            staging / "terminal_validation.v1.json",
            _pretty_json(terminal),
        )
        _write_fsync(
            staging / "evidence_index.json",
            _pretty_json(_package_index(staging)),
        )
        _write_fsync(staging / "SHA256SUMS", _checksum_file(staging))
        _publication_step("package_written", staging)
        _validate_terminal_package(
            staging,
            state=state,
            authorization_bytes=authorization_bytes,
        )
        _fsync_tree(staging)
        _publication_step("staging_fsynced", staging)
        refreshed = _snapshot_inputs(state.root, state.contract)
        if refreshed != state.snapshots:
            raise S48TerminalizationError(
                "terminalization input changed during publication"
            )
        if _read_regular_bytes(state.authorization_path) != authorization_bytes:
            raise S48TerminalizationError(
                "terminalization authorization changed during publication"
            )
        _publication_step("sources_reauthenticated", staging)
        if _output_state(state.output_path):
            raise S48TerminalizationError(
                "refusing to overwrite existing terminal package"
            )
        _publication_step("before_rename", staging)
        os.replace(staging, state.output_path)
        _publication_step("after_rename", state.output_path)
        terminal = _validate_terminal_package(
            state.output_path,
            state=state,
            authorization_bytes=authorization_bytes,
        )
        _publication_step("destination_validated", state.output_path)
        _fsync_directory(parent)
        _publication_step("parent_fsynced", state.output_path)
    except Exception:
        if staging.exists() or staging.is_symlink():
            _remove_created_path(staging)
        if state.output_path.exists() or state.output_path.is_symlink():
            try:
                _validate_terminal_package(
                    state.output_path,
                    state=state,
                    authorization_bytes=authorization_bytes,
                )
            except Exception:
                _remove_created_path(state.output_path)
        raise
    return {
        "schema": "ias.s4_8.recovery_02.terminalization_result.v1",
        "terminalization_status": "completed",
        "scientific_verdict": terminal["scientific_verdict"],
        "terminal_status": terminal["terminal_status"],
        "readiness": terminal["readiness"],
        "scientific_source_commit": terminal["identities"]["scientific_source_commit"],
        "terminalizer_implementation_commit": terminal["identities"][
            "terminalizer_implementation_commit"
        ],
        "terminalization_authorization_id": terminal["identities"][
            "terminalization_authorization_id"
        ],
        "output_path": state.contract["publication"]["output_path"],
        "manifest_sha256": _sha256(
            _read_regular_bytes(state.output_path / "SHA256SUMS")
        ),
        "evaluator_invocation_count": 1,
        "scientific_recomputation_count": 0,
        "holdout_opening_count": 1,
    }


__all__ = [
    "CONTRACT_PATH",
    "S48TerminalizationError",
    "create_terminalization_authorization",
    "preterminal_validate",
    "terminalize",
]
