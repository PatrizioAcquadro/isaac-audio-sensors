"""Forward-only recovery gate for the terminal pre-observation S4.8 defect."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition import s4_8

AMENDMENT_PATH = Path("configs/s4_8_recovery_amendment_01.v1.json")
AMENDMENT_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_recovery_amendment.v1.schema.json"
)
AMENDMENT_SPEC_PATH = Path(
    "docs/development/specs/s4_8_recovery_amendment_01.md"
)
RECOVERY_SCRIPT_PATH = Path("scripts/run_s4_8_recovery.py")
RECOVERY_TEST_PATH = Path("tests/test_s4_8_recovery_amendment.py")
RECOVERY_MODULE_PATH = Path(
    "src/isaac_audio_sensors/acquisition/s4_8_recovery.py"
)
RECOVERY_SOURCE_BOUND_FILES = (
    AMENDMENT_PATH,
    AMENDMENT_SCHEMA_PATH,
    AMENDMENT_SPEC_PATH,
    RECOVERY_MODULE_PATH,
    RECOVERY_SCRIPT_PATH,
    RECOVERY_TEST_PATH,
)
REVIEW_FIELDS = frozenset(
    {
        "schema",
        "amendment_id",
        "source_commit",
        "decision",
        "independent",
        "reviewer_id",
        "reviewed_at_utc",
    }
)


def load_amendment(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    amendment = s4_8.load_json(root / AMENDMENT_PATH)
    schema = s4_8.load_json(root / AMENDMENT_SCHEMA_PATH)
    try:
        jsonschema.validate(amendment, schema)
    except jsonschema.ValidationError as exc:
        raise s4_8.S48Error(
            f"S4.8 recovery amendment schema failure: {exc.message}"
        ) from exc
    return amendment


def _artifact_paths(amendment: Mapping[str, Any]) -> dict[str, Path]:
    return {
        name: Path(record["path"])
        for name, record in amendment["original_run"]["artifacts"].items()
    }


def _require_exact_artifacts(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> dict[str, Path]:
    paths = _artifact_paths(amendment)
    for name, record in amendment["original_run"]["artifacts"].items():
        path = repo_root / paths[name]
        if not path.is_file() or s4_8.sha256_file(path) != record["sha256"]:
            raise s4_8.S48Error(
                f"S4.8 recovery original artifact mismatch: {name}"
            )
    return paths


def _require_zero_observation_state(
    derived: Mapping[str, Any],
    *,
    original: Mapping[str, Any],
) -> None:
    failure = {
        "stage": original["failure_stage"],
        "error_type": original["failure_type"],
        "error": original["failure_message"],
        "terminal": True,
        "automatic_retry_forbidden": True,
    }
    payload = derived.get("payload")
    inventory = derived.get("observation_inventory")
    evaluation = derived.get("evaluation")
    if (
        derived.get("source_commit") != original["source_commit"]
        or derived.get("evaluation_state") != "not_evaluated"
        or derived.get("run_failure") != failure
        or derived.get("partial_progress") is not None
        or not isinstance(payload, Mapping)
        or payload.get("takes") != []
        or payload.get("sim_vs_real") != []
        or derived.get("payload_sha256") != s4_8.canonical_sha256(payload)
        or not isinstance(evaluation, Mapping)
        or evaluation.get("status") != "not_evaluated"
        or evaluation.get("readiness_passed") is not False
        or evaluation.get("criteria") != []
        or evaluation.get("comparison_classifications") != []
        or derived.get("evaluation_sha256") != s4_8.canonical_sha256(evaluation)
        or not isinstance(inventory, list)
        or len(inventory) != 48
    ):
        raise s4_8.S48Error(
            "S4.8 recovery original state is not exact FAILED/NOT_EVALUATED"
        )
    if any(
        record.get("scientific_observation_opened") is True
        or record.get("scientific_observations_derived") is True
        or record.get("analysis_completed") is True
        for record in inventory
    ):
        raise s4_8.S48Error(
            "S4.8 recovery is ineligible after observation or derivation progress"
        )


def _require_terminal_package(
    repo_root: Path,
    *,
    paths: Mapping[str, Path],
    original: Mapping[str, Any],
) -> None:
    package = (repo_root / paths["terminal_manifest"]).parent
    present = {path.name for path in package.iterdir() if path.is_file()}
    if present != s4_8.PACKAGE_FILES:
        raise s4_8.S48Error("S4.8 recovery terminal package file set changed")
    s4_8._validate_manifest(package)
    index = s4_8.load_json(package / "evidence_index.json")
    for record in index.get("records", []):
        path = package / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != record["byte_size"]
            or s4_8.sha256_file(path) != record["sha256"]
        ):
            raise s4_8.S48Error(
                f"S4.8 recovery terminal package index mismatch: {record['path']}"
            )
    if (
        (package / "derived_evaluation_input.json").read_bytes()
        != (repo_root / paths["derived_terminal_state"]).read_bytes()
    ):
        raise s4_8.S48Error(
            "S4.8 recovery terminal package derived state changed"
        )
    final = s4_8.load_json(repo_root / paths["final_validation"])
    expected_failure = {
        "stage": original["failure_stage"],
        "error_type": original["failure_type"],
        "error": original["failure_message"],
        "terminal": True,
        "automatic_retry_forbidden": True,
    }
    if (
        final.get("status") != "failed"
        or final.get("package_profile") != s4_8.TERMINAL_FAILURE_PROFILE
        or final.get("scientific_evaluation_state") != "not_evaluated"
        or final.get("completed_take_count") != 0
        or final.get("partial_current_take") is not None
        or final.get("run_failure") != expected_failure
        or final.get("terminal") is not True
        or final.get("automatic_retry_forbidden") is not True
    ):
        raise s4_8.S48Error(
            "S4.8 recovery terminal package is not the exact original failure"
        )
    provenance = s4_8.load_json(package / "provenance.json")
    if provenance.get("source_commit") != original["source_commit"]:
        raise s4_8.S48Error("S4.8 recovery original source binding mismatch")


def validate_original_failure(repo_root: Path) -> dict[str, Any]:
    """Authenticate the immutable first run without reading holdout content."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    original = amendment["original_run"]
    paths = _require_exact_artifacts(root, amendment)
    base = s4_8.load_contract(root)
    grant = s4_8.load_json(root / paths["grant"])
    authorization = s4_8.load_json(root / paths["authorization"])
    ledger_records = [
        json.loads(line, parse_constant=s4_8._reject_json_constant)
        for line in (root / paths["ledger"]).read_text(encoding="utf-8").splitlines()
    ]
    if (
        grant.get("grant_id") != original["grant_id"]
        or len(ledger_records) != 1
        or ledger_records[0].get("event_sha256")
        != original["ledger_event_sha256"]
        or ledger_records[0].get("grant_id") != original["grant_id"]
        or ledger_records[0].get("holdout_opened") is not True
        or s4_8.validate_ledger(
            root / paths["ledger"],
            expected_seal_sha256=grant["seal_sha256"],
        ).get("status")
        != "passed"
    ):
        raise s4_8.S48Error("S4.8 recovery original grant or ledger mismatch")
    s4_8._validate_authorization_record(
        authorization,
        config=base,
        source_commit=original["source_commit"],
        grant=grant,
        ledger_event=ledger_records[0],
    )
    terminal = s4_8._validate_terminal_journal(
        root / paths["journal"],
        source_commit=original["source_commit"],
        expected_status="failed",
        expected_ledger_event_sha256=original["ledger_event_sha256"],
    )
    if terminal.get("run_failure", {}).get("error") != original["failure_message"]:
        raise s4_8.S48Error("S4.8 recovery original terminal failure mismatch")
    context = s4_8.load_json(root / paths["recovery_context"])
    context_payload = {
        key: value for key, value in context.items() if key != "context_sha256"
    }
    if (
        context.get("source_commit") != original["source_commit"]
        or context.get("evaluation_state") != "not_evaluated"
        or context.get("run_failure") is not None
        or context.get("context_sha256") != s4_8.canonical_sha256(context_payload)
    ):
        raise s4_8.S48Error("S4.8 recovery original context mismatch")
    _require_zero_observation_state(
        s4_8.load_json(root / paths["derived_terminal_state"]),
        original=original,
    )
    for forbidden in (
        (root / paths["journal"]).with_name(s4_8.POST_CONSUMPTION_PROGRESS_NAME),
        (root / paths["journal"]).with_name(
            s4_8.POST_CONSUMPTION_PROGRESS_QUARANTINE_NAME
        ),
        (root / paths["derived_terminal_state"]).parent / "provisional_evidence.v1",
    ):
        if forbidden.exists():
            raise s4_8.S48Error(
                "S4.8 recovery is ineligible after progress or provisional state"
            )
    _require_terminal_package(root, paths=paths, original=original)
    return {
        "schema": "ias.s4_8.recovery_original_validation.v1",
        "status": "passed",
        "source_commit": original["source_commit"],
        "grant_id": original["grant_id"],
        "grant_consumed": True,
        "opening_authorized": True,
        "terminal_status": "failed",
        "evaluation_state": "not_evaluated",
        "completed_observation_count": 0,
        "derived_observation_count": 0,
        "progress_state_present": False,
        "provisional_state_present": False,
        "raw_holdout_read": False,
        "original_artifact_count": len(paths),
    }


def _recovery_contract(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> dict[str, Any]:
    contract = deepcopy(s4_8.load_contract(repo_root))
    future = amendment["future_attempt"]
    contract["grant"]["grant_id_template"] = future["grant_id_template"]
    contract["grant"]["path"] = future["grant_path"]
    contract["grant"]["ledger_path"] = future["ledger_path"]
    contract["evidence"]["run_journal_path"] = future["journal_path"]
    contract["evidence"]["derived_input_path"] = future["derived_input_path"]
    contract["evidence"]["output_path"] = future["output_path"]
    contract["evidence"]["closeout_path"] = future["closeout_path"]
    return contract


@contextmanager
def _use_recovery_contract(
    repo_root: Path,
    amendment: Mapping[str, Any],
) -> Iterator[None]:
    contract = _recovery_contract(repo_root, amendment)
    with s4_8._use_contract(
        contract,
        contract_path=AMENDMENT_PATH,
        extra_source_bound_files=RECOVERY_SOURCE_BOUND_FILES,
    ):
        yield


def _recovery_package_path(
    repo_root: Path,
    amendment: Mapping[str, Any],
    package: Path | None,
) -> Path:
    selected = package or Path(amendment["future_attempt"]["output_path"])
    return selected if selected.is_absolute() else repo_root / selected


def _validate_recovery_provenance(
    package: Path,
    *,
    repo_root: Path,
) -> None:
    provenance = s4_8.load_json(package / "provenance.json")
    source_paths = tuple(
        dict.fromkeys((*s4_8.SOURCE_BOUND_FILES, *RECOVERY_SOURCE_BOUND_FILES))
    )
    source_files = [
        {
            "path": path.as_posix(),
            "sha256": s4_8.sha256_file(repo_root / path),
        }
        for path in source_paths
    ]
    if (
        provenance.get("contract_path") != AMENDMENT_PATH.as_posix()
        or provenance.get("contract_sha256")
        != s4_8.sha256_file(repo_root / AMENDMENT_PATH)
        or provenance.get("source_bound_files") != source_files
        or provenance.get("source_bound_files_sha256")
        != s4_8.canonical_sha256(source_files)
    ):
        raise s4_8.S48Error("S4.8 recovery amendment provenance mismatch")


def validate_recovery_evidence_package(
    package: Path | None = None,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Validate one recovery package under the amendment contract."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    validate_original_failure(root)
    selected = _recovery_package_path(root, amendment, package).resolve()
    with _use_recovery_contract(root, amendment):
        result = s4_8.validate_evidence_package(selected, repo_root=root)
        _validate_recovery_provenance(selected, repo_root=root)
    return {**result, "amendment_id": amendment["amendment_id"]}


def replay_recovery_evidence_package(
    canonical: Path | None = None,
    *,
    output: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Byte-replay one recovery package under the amendment contract."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    validate_original_failure(root)
    selected = _recovery_package_path(root, amendment, canonical).resolve()
    destination = output if output.is_absolute() else root / output
    with _use_recovery_contract(root, amendment):
        _validate_recovery_provenance(selected, repo_root=root)
        result = s4_8.replay_evidence_package(
            selected,
            output=destination,
            repo_root=root,
        )
    return {**result, "amendment_id": amendment["amendment_id"]}


def recovery_preopen_validate(
    repo_root: Path,
    *,
    source_commit: str | None = None,
    verify_prerequisite_replay: bool = True,
) -> dict[str, Any]:
    """Validate eligibility and new paths without creating a grant."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    original = validate_original_failure(root)
    resolved_commit = source_commit or s4_8._git(root, "rev-parse", "HEAD")
    with _use_recovery_contract(root, amendment):
        preopen = s4_8.preopen_validate(
            root,
            source_commit=resolved_commit,
            verify_prerequisite_replay=verify_prerequisite_replay,
        )
    future = amendment["future_attempt"]
    return {
        "schema": "ias.s4_8.recovery_preopen_validation.v1",
        "status": "passed",
        "amendment_id": amendment["amendment_id"],
        "source_commit": resolved_commit,
        "candidate_grant_id": future["grant_id_template"].format(
            source_commit=resolved_commit
        ),
        "candidate_paths": {
            key: future[key]
            for key in (
                "grant_path",
                "ledger_path",
                "journal_path",
                "derived_input_path",
                "output_path",
                "independent_review_path",
            )
        },
        "original_run": original,
        "planned_take_count": preopen["planned_take_count"],
        "sealed_artifact_count": preopen["sealed_artifact_count"],
        "content_derived_values_returned": False,
        "new_grant_present": preopen["grant_present"],
        "new_ledger_present": preopen["ledger_present"],
        "independent_review_required": True,
        "independent_review_present": (
            root / future["independent_review_path"]
        ).is_file(),
        "new_explicit_authorization_required": True,
        "grant_creation_authorized": False,
        "grant_consumption_authorized": False,
        "holdout_observation_opened": False,
    }


def _validate_independent_review(
    repo_root: Path,
    *,
    amendment: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    path = repo_root / amendment["future_attempt"]["independent_review_path"]
    review = s4_8.load_json(path)
    if (
        set(review) != REVIEW_FIELDS
        or review.get("schema") != "ias.s4_8.independent_recovery_review.v1"
        or review.get("amendment_id") != amendment["amendment_id"]
        or review.get("source_commit") != source_commit
        or review.get("decision") != "approved"
        or review.get("independent") is not True
        or not isinstance(review.get("reviewer_id"), str)
        or not review["reviewer_id"].strip()
        or not isinstance(review.get("reviewed_at_utc"), str)
        or not review["reviewed_at_utc"].strip()
    ):
        raise s4_8.S48Error(
            "S4.8 recovery requires an independent review bound to this source"
        )
    return review


def create_recovery_grant(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
) -> dict[str, Any]:
    """Create only after a future review and new explicit authorization."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    validate_original_failure(root)
    review = _validate_independent_review(
        root,
        amendment=amendment,
        source_commit=source_commit,
    )
    original_authorization = s4_8.load_json(
        root
        / amendment["original_run"]["artifacts"]["authorization"]["path"]
    )
    if authorization_id == original_authorization.get("authorization_id"):
        raise s4_8.S48Error(
            "S4.8 recovery requires a new explicit authorization identity"
        )
    with _use_recovery_contract(root, amendment):
        result = s4_8.create_grant(
            root,
            source_commit=source_commit,
            authorization_id=authorization_id,
        )
    return {**result, "independent_review": review}


def run_recovery_evaluation_once(
    repo_root: Path,
    *,
    source_commit: str,
    authorization_id: str,
    event_time_utc: str,
) -> dict[str, Any]:
    """Reuse the existing one-shot evaluator and state machine on new paths."""

    root = repo_root.resolve()
    amendment = load_amendment(root)
    validate_original_failure(root)
    _validate_independent_review(
        root,
        amendment=amendment,
        source_commit=source_commit,
    )
    future = amendment["future_attempt"]
    authorization = s4_8.load_json(
        (root / future["grant_path"]).with_name(s4_8.AUTHORIZATION_RECORD_NAME)
    )
    if (
        authorization.get("source_commit") != source_commit
        or authorization.get("authorization_id") != authorization_id
    ):
        raise s4_8.S48Error(
            "S4.8 recovery consumption lacks the new explicit authorization"
        )
    with _use_recovery_contract(root, amendment):
        return s4_8.run_authorized_evaluation_once(
            root,
            source_commit=source_commit,
            event_time_utc=event_time_utc,
        )


__all__ = [
    "AMENDMENT_PATH",
    "create_recovery_grant",
    "load_amendment",
    "replay_recovery_evidence_package",
    "recovery_preopen_validate",
    "run_recovery_evaluation_once",
    "validate_recovery_evidence_package",
    "validate_original_failure",
]
