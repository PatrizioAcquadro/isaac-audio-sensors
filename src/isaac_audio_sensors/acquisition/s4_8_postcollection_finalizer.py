"""Outcome-blind postcollection sealing for S4.8 recovery amendment 02."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_8_official_acquisition import (
    S48OfficialAcquisitionError,
    next_attempt,
    validate_attempt_ledger,
    validate_take_authorization,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256

SEAL_SCHEMA = "ias.s4_8.recovery_02_holdout_seal.v2"
SEAL_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_holdout_seal.v2.schema.json"
)
FINALIZER_SOURCE_PATHS = (
    Path(
        "src/isaac_audio_sensors/acquisition/"
        "s4_8_postcollection_finalizer.py"
    ),
    Path("scripts/finalize_s4_8_recovery_02.py"),
    SEAL_SCHEMA_PATH,
)
SCIENTIFIC_CONTENT_FILENAMES = frozenset(
    {
        "technical_gate_report.json",
        "respeaker_audio.wav",
        "capture.svo2",
        "frames.jsonl",
        "zed_svo_replay.json",
        "producer_summary.json",
        "pi_producer_status.json",
        "process_journal.jsonl",
    }
)
COMMON_PASS_FILES = frozenset(
    {
        "official_attempt_record.json",
        "official_take_authorization.json",
        "pi_producer_status.json",
        "process_journal.jsonl",
        "respeaker_audio.wav",
        "technical_candidate_seal.json",
        "technical_clearance_consumed.json",
        "technical_gate_report.json",
    }
)
REFERENCE_PASS_FILES = COMMON_PASS_FILES | {"technical_precollection_manifest.json"}
IMPACT_PASS_FILES = COMMON_PASS_FILES | {
    "zed/capture.svo2",
    "zed/frames.jsonl",
    "zed/producer_summary.json",
    "zed/zed_svo_replay.json",
}
METADATA_FILENAMES = frozenset(
    {
        "official_attempt_record.json",
        "official_take_authorization.json",
        "technical_candidate_seal.json",
        "technical_clearance_consumed.json",
    }
)


class S48PostcollectionFinalizerError(RuntimeError):
    """Postcollection collection, seal, or binding authentication failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise S48PostcollectionFinalizerError(message)


def _safe_relative(value: object, label: str) -> Path:
    _require(isinstance(value, str) and bool(value), f"{label}: path required")
    relative = PurePosixPath(str(value))
    _require(
        not relative.is_absolute() and ".." not in relative.parts,
        f"{label}: unsafe path",
    )
    return Path(*relative.parts)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _load_metadata_json(path: Path) -> dict[str, Any]:
    """Load allowlisted provenance JSON, never scientific-result content."""

    _require(
        path.name in METADATA_FILENAMES
        or (
            path.parent.name == "authorizations"
            and path.name.endswith(".json")
        ),
        f"scientific or non-allowlisted JSON parse refused: {path}",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path}: metadata record is not an object")
    return value


def _load_control_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path}: control record is not an object")
    return value


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    _require(path.is_file() and not path.is_symlink(), "attempt ledger missing")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = json.loads(line)
        _require(isinstance(value, dict), f"attempt ledger line {number} invalid")
        records.append(value)
    return records


def _validate_self_hash(
    record: Mapping[str, Any],
    field: str,
    label: str,
) -> None:
    payload = {key: value for key, value in record.items() if key != field}
    _require(
        record.get(field) == canonical_sha256(payload),
        f"{label}: self-hash mismatch",
    )


def _require_regular_file(repo_root: Path, relative: Path, label: str) -> Path:
    root = repo_root.resolve()
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), f"{label}: symlink refused: {relative}")
    _require(
        candidate.is_file() and candidate.resolve().is_relative_to(root),
        f"{label}: regular file missing or escaped: {relative}",
    )
    return candidate


def _artifact_record(repo_root: Path, relative: Path, role: str) -> dict[str, Any]:
    path = _require_regular_file(repo_root, relative, role)
    return {
        "path": relative.as_posix(),
        "role": role,
        "byte_size": path.stat().st_size,
        "sha256": s4_8.sha256_file(path),
    }


def _file_binding(
    repo_root: Path,
    relative: Path,
    *,
    payload_sha256: str,
) -> dict[str, Any]:
    path = _require_regular_file(repo_root, relative, "binding")
    _require(_is_sha256(payload_sha256), "binding payload hash invalid")
    return {
        "path": relative.as_posix(),
        "file_sha256": s4_8.sha256_file(path),
        "payload_sha256": payload_sha256,
    }


def _expected_pass_files(mode: str) -> frozenset[str]:
    if mode == "reference":
        return REFERENCE_PASS_FILES
    if mode == "silence":
        return COMMON_PASS_FILES
    if mode == "impact_av":
        return IMPACT_PASS_FILES
    raise S48PostcollectionFinalizerError(f"unsupported acquisition mode: {mode}")


def _validate_candidate_seal(
    attempt_dir: Path,
    *,
    official_attempt: Mapping[str, Any],
    acquisition_mode: str,
) -> None:
    candidate_path = attempt_dir / "technical_candidate_seal.json"
    candidate = _load_metadata_json(candidate_path)
    _validate_self_hash(candidate, "seal_sha256", str(candidate_path))
    _require(
        candidate.get("seal_sha256")
        == official_attempt.get("technical_candidate_seal_sha256"),
        f"{attempt_dir}: official candidate-seal binding mismatch",
    )
    _require(
        candidate.get("status") == "engineering_candidate_sealed"
        and candidate.get("engineering_only") is True
        and candidate.get("dry_run") is False,
        f"{attempt_dir}: candidate-seal state invalid",
    )
    _require(
        candidate.get("report_sha256")
        == official_attempt.get("technical_report_sha256"),
        f"{attempt_dir}: technical-report binding mismatch",
    )
    authority = candidate.get("authority")
    _require(
        isinstance(authority, Mapping)
        and authority
        and all(value is False for value in authority.values()),
        f"{attempt_dir}: candidate seal carries authority",
    )
    capture = attempt_dir / "respeaker_audio.wav"
    _require(
        capture.is_file() and not capture.is_symlink(),
        f"{attempt_dir}: capture missing or symlinked",
    )
    _require(
        s4_8.sha256_file(capture) == candidate.get("capture_sha256"),
        f"{attempt_dir}: capture hash mismatch",
    )
    zed_hashes = candidate.get("zed_artifact_hashes")
    if acquisition_mode == "impact_av":
        _require(
            isinstance(zed_hashes, Mapping)
            and set(zed_hashes) == {"svo2_sha256", "frames_sha256"},
            f"{attempt_dir}: ZED candidate binding invalid",
        )
        _require(
            s4_8.sha256_file(attempt_dir / "zed/capture.svo2")
            == zed_hashes["svo2_sha256"]
            and s4_8.sha256_file(attempt_dir / "zed/frames.jsonl")
            == zed_hashes["frames_sha256"],
            f"{attempt_dir}: ZED artifact hash mismatch",
        )
    else:
        _require(zed_hashes is None, f"{attempt_dir}: unexpected ZED binding")
    clearance = _load_metadata_json(
        attempt_dir / "technical_clearance_consumed.json"
    )
    _require(
        clearance.get("candidate_seal_sha256") == candidate["seal_sha256"],
        f"{attempt_dir}: clearance consumption mismatch",
    )


def _collection_artifacts(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Authenticate completion and return a byte-only collection inventory."""

    # Import lazily so recovery validation can call back into this module.
    from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

    unseen = amendment["unseen_holdout"]
    freeze = recovery._validate_official_precollection_freeze(  # noqa: SLF001
        repo_root,
        amendment,
        require_current_source=False,
    )
    _require(
        freeze["valid"],
        f"precollection freeze invalid: {freeze.get('reason', 'unknown')}",
    )
    session_rel = _safe_relative(unseen["session_manifest_path"], "session manifest")
    partition_rel = _safe_relative(
        unseen["partition_manifest_path"], "partition manifest"
    )
    precollection_rel = _safe_relative(
        unseen["precollection_seal_path"], "precollection seal"
    )
    ledger_rel = _safe_relative(unseen["attempt_ledger_path"], "attempt ledger")
    observation_rel = _safe_relative(unseen["observation_root"], "observation root")
    namespace_rel = _safe_relative(unseen["namespace_root"], "namespace root")
    session = _load_control_json(repo_root / session_rel)
    partition = _load_control_json(repo_root / partition_rel)
    precollection = _load_control_json(repo_root / precollection_rel)
    ledger = _load_ledger(repo_root / ledger_rel)
    validate_attempt_ledger(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )
    try:
        next_attempt(
            ledger,
            session_manifest=session,
            expected_session_manifest_sha256=session["manifest_sha256"],
        )
    except S48OfficialAcquisitionError as exc:
        _require(
            str(exc) == "official collection is complete",
            f"official completion validation failed: {exc}",
        )
    else:
        raise S48PostcollectionFinalizerError("official collection is incomplete")
    pass_count = sum(record["decision"] == "PASS" for record in ledger)
    retry_count = sum(record["decision"] == "RETRY_REQUIRED" for record in ledger)
    _require(
        pass_count == 37 and pass_count + retry_count == len(ledger),
        "official completion census invalid",
    )

    observation_root = repo_root / observation_rel
    _require(
        observation_root.is_dir() and not observation_root.is_symlink(),
        "official observation root missing or symlinked",
    )
    expected_attempt_dirs: set[Path] = set()
    artifact_paths: list[tuple[Path, str]] = []
    passed_before = 0
    attempt_before = 1
    for sequence, ledger_record in enumerate(ledger):
        take = session["design"][passed_before]
        _require(
            ledger_record["planned_take_id"] == take["planned_take_id"]
            and ledger_record["attempt_number"] == attempt_before,
            "ledger/session take sequence mismatch",
        )
        attempt_name = (
            f"{take['planned_take_id']}__attempt_{attempt_before:02d}"
        )
        attempt_rel = observation_rel / take["planned_take_id"] / attempt_name
        attempt_dir = repo_root / attempt_rel
        _require(
            attempt_dir.is_dir() and not attempt_dir.is_symlink(),
            f"retained attempt directory missing: {attempt_rel}",
        )
        expected_attempt_dirs.add(attempt_dir)
        official_path = attempt_dir / "official_attempt_record.json"
        authorization_path = attempt_dir / "official_take_authorization.json"
        official = _load_metadata_json(official_path)
        authorization = _load_metadata_json(authorization_path)
        _validate_self_hash(
            official, "official_attempt_record_sha256", str(official_path)
        )
        _validate_self_hash(
            authorization, "authorization_sha256", str(authorization_path)
        )
        validate_take_authorization(
            authorization,
            session_manifest=session,
            precollection_seal_sha256=precollection["seal_sha256"],
            ledger=ledger[:sequence],
            take=take,
            attempt_number=attempt_before,
        )
        _require(
            official.get("official_attempt_record_sha256")
            == ledger_record["official_attempt_record_sha256"]
            and official.get("authorization_sha256")
            == ledger_record["authorization_sha256"]
            == authorization["authorization_sha256"]
            and official.get("decision") == ledger_record["decision"]
            and official.get("session_manifest_sha256")
            == session["manifest_sha256"]
            and official.get("partition_manifest_sha256")
            == partition["partition_manifest_sha256"]
            and official.get("precollection_seal_sha256")
            == precollection["seal_sha256"]
            and official.get("planned_take_definition_sha256")
            == take["planned_take_definition_sha256"]
            and official.get("source_commit") == session["code_head"]
            and official.get("retained") is True
            and official.get("counts_as_official_attempt") is True
            and official.get("automatic_retry") is False
            and official.get("automatic_continuation") is False,
            f"{attempt_dir}: official wrapper mismatch",
        )
        names = {
            path.relative_to(attempt_dir).as_posix()
            for path in attempt_dir.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        directories = {
            path.relative_to(attempt_dir).as_posix()
            for path in attempt_dir.rglob("*")
            if path.is_dir() and not path.is_symlink()
        }
        allowed_directories = (
            {"zed", "zed/_staging_frames"}
            if take["acquisition_mode"] == "impact_av"
            else set()
        )
        _require(
            all(not path.is_symlink() for path in attempt_dir.rglob("*"))
            and directories <= allowed_directories
            and (
                "zed/_staging_frames" not in directories
                or "zed" in directories
            ),
            f"{attempt_dir}: nested, non-file, or symlink artifact refused",
        )
        allowed = _expected_pass_files(str(take["acquisition_mode"]))
        if ledger_record["decision"] == "PASS":
            _require(
                names == allowed and directories == allowed_directories,
                f"{attempt_dir}: PASS artifact set mismatch",
            )
            _validate_candidate_seal(
                attempt_dir,
                official_attempt=official,
                acquisition_mode=str(take["acquisition_mode"]),
            )
            passed_before += 1
            attempt_before = 1
        else:
            _require(
                {"official_attempt_record.json", "official_take_authorization.json"}
                <= names
                and names <= allowed,
                f"{attempt_dir}: retry artifact set invalid",
            )
            _require(
                official.get("technical_candidate_seal_sha256") is None,
                f"{attempt_dir}: retry unexpectedly sealed as candidate",
            )
            _require(
                {
                    "technical_candidate_seal.json",
                    "technical_clearance_consumed.json",
                }.isdisjoint(names),
                f"{attempt_dir}: retry contains candidate-seal state",
            )
            attempt_before += 1
        for name in sorted(names):
            artifact_paths.append(
                (
                    attempt_rel / Path(name),
                    f"retained_attempt_{Path(name).name}",
                )
            )

        external_rel = (
            namespace_rel
            / "acquisition"
            / "authorizations"
            / f"{attempt_name}.json"
        )
        external = _load_metadata_json(repo_root / external_rel)
        _require(
            external == authorization,
            f"{attempt_dir}: external authorization copy mismatch",
        )
        artifact_paths.append((external_rel, "external_take_authorization"))

    actual_attempt_dirs = {
        path
        for group in observation_root.iterdir()
        if group.is_dir() and not group.is_symlink()
        for path in group.iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    _require(
        actual_attempt_dirs == expected_attempt_dirs,
        "observation root contains missing or extra attempt directories",
    )
    _require(
        all(
            group.is_dir()
            and not group.is_symlink()
            and all(
                child.is_dir() and not child.is_symlink()
                for child in group.iterdir()
            )
            for group in observation_root.iterdir()
        ),
        "observation root contains unexpected entries",
    )

    acquisition_root = repo_root / namespace_rel / "acquisition"
    expected_acquisition_files = {
        repo_root / ledger_rel,
        *(
            repo_root / relative
            for relative, role in artifact_paths
            if role == "external_take_authorization"
        ),
    }
    actual_acquisition_files = {
        path
        for path in acquisition_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    _require(
        actual_acquisition_files == expected_acquisition_files,
        "acquisition provenance contains missing or extra files",
    )
    artifact_paths.append((ledger_rel, "official_attempt_ledger"))
    records = [
        _artifact_record(repo_root, relative, role)
        for relative, role in sorted(
            artifact_paths, key=lambda item: item[0].as_posix()
        )
    ]
    _require(
        len({record["path"] for record in records}) == len(records),
        "collection inventory contains duplicate paths",
    )
    return records, {
        "observation_root": observation_rel.as_posix(),
        "attempt_ledger_path": ledger_rel.as_posix(),
        "planned_take_count": 37,
        "completed_take_count": pass_count,
        "retained_attempt_count": len(ledger),
        "pass_attempt_count": pass_count,
        "retry_required_attempt_count": retry_count,
        "ledger_record_count": len(ledger),
        "ledger_file_sha256": s4_8.sha256_file(repo_root / ledger_rel),
        "ledger_head_sha256": ledger[-1]["record_sha256"],
        "authorization_record_count": len(ledger),
        "attempt_artifact_count": len(records) - len(ledger) - 1,
        "collection_artifact_count": len(records),
    }


def _require_finalizer_source(repo_root: Path, commit: str) -> None:
    _require(
        isinstance(commit, str)
        and len(commit) == 40
        and all(character in "0123456789abcdef" for character in commit),
        "finalizer source commit invalid",
    )
    for relative in FINALIZER_SOURCE_PATHS:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}:{relative.as_posix()}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
        _require(
            result.returncode == 0,
            f"finalizer source commit does not contain {relative}",
        )
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    _require(ancestor.returncode == 0, "finalizer source is not an ancestor of HEAD")


def build_postcollection_documents(
    repo_root: Path,
    *,
    finalizer_source_commit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic seal and binding documents without writing them."""

    from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    _require_finalizer_source(root, finalizer_source_commit)
    artifacts, collection = _collection_artifacts(root, amendment)
    unseen = amendment["unseen_holdout"]
    precollection_rel = _safe_relative(
        unseen["precollection_seal_path"], "precollection seal"
    )
    partition_rel = _safe_relative(
        unseen["partition_manifest_path"], "partition manifest"
    )
    session_rel = _safe_relative(unseen["session_manifest_path"], "session manifest")
    precollection = _load_control_json(root / precollection_rel)
    partition = _load_control_json(root / partition_rel)
    session = _load_control_json(root / session_rel)
    payload = {
        "schema": SEAL_SCHEMA,
        "status": "sealed_unopened",
        "amendment_id": amendment["amendment_id"],
        "revision_id": amendment["revision_id"],
        "holdout_id": unseen["holdout_id"],
        "finalizer_source_commit": finalizer_source_commit,
        "bindings": {
            "precollection_seal": _file_binding(
                root,
                precollection_rel,
                payload_sha256=precollection["seal_sha256"],
            ),
            "partition_manifest": _file_binding(
                root,
                partition_rel,
                payload_sha256=partition["partition_manifest_sha256"],
            ),
            "session_manifest": _file_binding(
                root,
                session_rel,
                payload_sha256=session["manifest_sha256"],
            ),
        },
        "collection": collection,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "artifact_inventory_sha256": canonical_sha256(artifacts),
        "technically_sealed": True,
        "scientifically_opened": False,
        "scientific_artifact_contents_parsed": False,
        "scientific_outcomes_derived": False,
        "scientific_outputs_returned": False,
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "opens_holdout": False,
            "runs_evaluation": False,
            "adds_independent_review": False,
        },
    }
    seal = {**payload, "seal_payload_sha256": canonical_sha256(payload)}
    seal_bytes = _json_bytes(seal)
    binding = {
        "schema": "ias.s4_8.recovery_unseen_holdout_binding.v2",
        "amendment_id": amendment["amendment_id"],
        "holdout_id": unseen["holdout_id"],
        "status": "sealed_unopened",
        "preregistration_commit": precollection["source_commit"],
        "precollection_seal": {
            "path": precollection_rel.as_posix(),
            "sha256": s4_8.sha256_file(root / precollection_rel),
        },
        "partition_manifest": {
            "path": partition_rel.as_posix(),
            "sha256": s4_8.sha256_file(root / partition_rel),
        },
        "session_manifest": {
            "path": session_rel.as_posix(),
            "sha256": s4_8.sha256_file(root / session_rel),
        },
        "holdout_seal": {
            "path": unseen["holdout_seal_path"],
            "sha256": hashlib.sha256(seal_bytes).hexdigest(),
        },
        "observation_root": unseen["observation_root"],
        "planned_take_count": 37,
        "leakage_group_count": 15,
        "scientifically_opened": False,
    }
    return seal, binding


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _validate_seal_document(
    repo_root: Path,
    seal: Mapping[str, Any],
) -> None:
    schema = _load_control_json(repo_root / SEAL_SCHEMA_PATH)
    try:
        jsonschema.validate(dict(seal), schema)
    except jsonschema.ValidationError as exc:
        raise S48PostcollectionFinalizerError(
            f"holdout seal schema failure: {exc.message}"
        ) from exc
    _validate_self_hash(seal, "seal_payload_sha256", "holdout seal")
    _require(
        seal.get("artifact_inventory_sha256")
        == canonical_sha256(seal.get("artifacts")),
        "holdout seal inventory hash mismatch",
    )
    _require_finalizer_source(repo_root, str(seal["finalizer_source_commit"]))


def authenticate_existing_finalization(
    repo_root: Path,
) -> dict[str, Any]:
    """Authenticate the existing seal and binding without scientific parsing."""

    from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    unseen = amendment["unseen_holdout"]
    seal_rel = _safe_relative(unseen["holdout_seal_path"], "holdout seal")
    binding_rel = _safe_relative(unseen["binding_path"], "holdout binding")
    seal_path = root / seal_rel
    binding_path = root / binding_rel
    _require(
        seal_path.is_file()
        and not seal_path.is_symlink()
        and binding_path.is_file()
        and not binding_path.is_symlink(),
        "holdout seal and binding must both exist",
    )
    seal = _load_control_json(seal_path)
    binding = _load_control_json(binding_path)
    _validate_seal_document(root, seal)
    binding_schema = _load_control_json(
        root / _safe_relative(unseen["binding_schema_path"], "binding schema")
    )
    try:
        jsonschema.validate(binding, binding_schema)
    except jsonschema.ValidationError as exc:
        raise S48PostcollectionFinalizerError(
            f"holdout binding schema failure: {exc.message}"
        ) from exc
    expected_seal, expected_binding = build_postcollection_documents(
        root,
        finalizer_source_commit=str(seal["finalizer_source_commit"]),
    )
    _require(seal == expected_seal, "holdout seal does not match collection")
    _require(binding == expected_binding, "holdout binding does not match seal")
    _require(
        binding["holdout_seal"]["sha256"] == s4_8.sha256_file(seal_path),
        "holdout binding file hash mismatch",
    )
    return {
        "status": "passed",
        "holdout_collection_complete": True,
        "holdout_seal_authenticated": True,
        "holdout_binding_authenticated": True,
        "holdout_seal_path": seal_rel.as_posix(),
        "holdout_seal_file_sha256": s4_8.sha256_file(seal_path),
        "holdout_seal_payload_sha256": seal["seal_payload_sha256"],
        "holdout_binding_path": binding_rel.as_posix(),
        "holdout_binding_file_sha256": s4_8.sha256_file(binding_path),
        "collection_artifact_count": seal["artifact_count"],
        "retained_attempt_count": seal["collection"]["retained_attempt_count"],
        "pass_attempt_count": seal["collection"]["pass_attempt_count"],
        "retry_required_attempt_count": seal["collection"][
            "retry_required_attempt_count"
        ],
        "scientifically_opened": False,
        "scientific_artifact_contents_parsed": False,
        "scientific_outcomes_derived": False,
        "scientific_outputs_returned": False,
        "grant_created": False,
        "grant_consumed": False,
        "evaluation_run": False,
    }


def _write_pair_exclusive(
    seal_path: Path,
    binding_path: Path,
    *,
    seal: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> None:
    created: list[Path] = []
    try:
        for path, value in ((seal_path, seal), (binding_path, binding)):
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            created.append(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_json_bytes(value))
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def finalize_postcollection(repo_root: Path) -> dict[str, Any]:
    """Create the reserved seal and binding once, or authenticate an exact rerun."""

    from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

    root = repo_root.resolve()
    amendment = recovery.load_amendment(root)
    unseen = amendment["unseen_holdout"]
    seal_path = root / _safe_relative(unseen["holdout_seal_path"], "holdout seal")
    binding_path = root / _safe_relative(unseen["binding_path"], "holdout binding")
    present = (seal_path.exists(), binding_path.exists())
    _require(
        present in {(False, False), (True, True)},
        "partial postcollection finalization state exists",
    )
    if present == (True, True):
        return {
            **authenticate_existing_finalization(root),
            "created": False,
            "already_finalized": True,
        }
    tracked_diff = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    _require(
        tracked_diff.returncode == 0 and staged_diff.returncode == 0,
        "finalizer requires committed tracked source",
    )
    source_commit = s4_8._git(root, "rev-parse", "HEAD")
    seal, binding = build_postcollection_documents(
        root,
        finalizer_source_commit=source_commit,
    )
    _validate_seal_document(root, seal)
    binding_schema = _load_control_json(
        root / _safe_relative(unseen["binding_schema_path"], "binding schema")
    )
    jsonschema.validate(binding, binding_schema)
    _write_pair_exclusive(
        seal_path,
        binding_path,
        seal=seal,
        binding=binding,
    )
    return {
        **authenticate_existing_finalization(root),
        "created": True,
        "already_finalized": False,
    }


__all__ = [
    "SEAL_SCHEMA",
    "SEAL_SCHEMA_PATH",
    "SCIENTIFIC_CONTENT_FILENAMES",
    "S48PostcollectionFinalizerError",
    "authenticate_existing_finalization",
    "build_postcollection_documents",
    "finalize_postcollection",
]
