"""Isolation and atomicity tests for S4.8 amendment-02 terminalization."""

from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_terminalizer as terminalizer,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "c45eae3674abd4b8c82b37be656470fe425c8e54"
BASELINE_COMMIT = "59d006818b7958794dd51ce0437dfaa58e7b3db6"
IMPLEMENTATION_COMMIT = "b" * 40
GRANT_ID = f"s4_8_recovery_amendment_02_37_take_corrective_03_{SOURCE_COMMIT}"


def _canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _pretty(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _write(root: Path, relative: str, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_json(root: Path, relative: str, value: dict[str, Any]) -> Path:
    return _write(root, relative, _pretty(value))


def _event(
    *,
    sequence: int,
    event: str,
    previous: str,
    **fields: Any,
) -> dict[str, Any]:
    record = {
        "schema": "ias.s4_8.first_run_journal_event.v1",
        "sequence": sequence,
        "event": event,
        "source_commit": SOURCE_COMMIT,
        "previous_event_sha256": previous,
        **fields,
    }
    return {**record, "event_sha256": _canonical_sha256(record)}


def _fixture_contract(root: Path) -> dict[str, Any]:
    grant_body = {
        "schema": "ias.s4_4.holdout_access_grant.v1",
        "grant_id": GRANT_ID,
        "purpose": "S4.8_evaluation",
        "seal_sha256": "1" * 64,
        "split_plan_sha256": "2" * 64,
        "prerequisite": {
            "schema": "ias.s4_8.recovery_02.authorization_prerequisite.v1",
            "amendment_id": "s4_8_recovery_amendment_02",
            "revision_id": ("s4_8_recovery_amendment_02_preholdout_37_take_revision"),
            "source_commit": SOURCE_COMMIT,
            "evaluator_binding_sha256": "",
            "holdout_binding_file_sha256": "",
            "holdout_seal_file_sha256": "",
            "independent_review_file_sha256": "",
        },
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    paths = {
        "scientific_grant": (
            "dataset/S4.8/recovery_amendment_02_37_take/access/"
            "holdout_access_grant.corrective_03.v1.json"
        ),
        "scientific_authorization": (
            "dataset/S4.8/recovery_amendment_02_37_take/access/"
            "authorization_record.v1.json"
        ),
        "scientific_ledger": (
            "dataset/S4.8/recovery_amendment_02_37_take/access/"
            "opening_transition.v1/access_ledger.jsonl"
        ),
        "scientific_journal": (
            "dataset/S4.8/recovery_amendment_02_37_take/access/"
            "opening_transition.v1/first_run_journal.jsonl"
        ),
        "recovery_context": (
            "dataset/S4.8/recovery_amendment_02_37_take/access/"
            "opening_transition.v1/recovery_context.v1.json"
        ),
        "derived_state": (
            "dataset/S4.8/recovery_amendment_02_37_take/derived/"
            "heldout_evaluation_input.v2.json"
        ),
        "independent_review": (
            "dataset/S4.8/recovery_amendment_02_37_take/review/"
            "independent_review.v1.json"
        ),
        "amendment_contract": "metadata/amendment.json",
        "evaluator_binding": "metadata/evaluator_binding.json",
        "holdout_binding": "metadata/holdout_binding.json",
        "holdout_seal": "metadata/holdout_seal.json",
    }
    holdout_seal = {"schema": "test.holdout_seal.v1"}
    holdout_seal_path = _write_json(
        root,
        paths["holdout_seal"],
        holdout_seal,
    )
    holdout_seal_sha = hashlib.sha256(holdout_seal_path.read_bytes()).hexdigest()
    holdout_binding = {
        "schema": "ias.s4_8.recovery_unseen_holdout_binding.v2",
        "holdout_seal": {
            "path": paths["holdout_seal"],
            "sha256": holdout_seal_sha,
        },
    }
    holdout_binding_path = _write_json(
        root,
        paths["holdout_binding"],
        holdout_binding,
    )
    holdout_binding_sha = hashlib.sha256(holdout_binding_path.read_bytes()).hexdigest()
    evaluator_binding = {
        "schema": "ias.s4_8.recovery_02_evaluator_binding.v2",
        "bindings": {
            "holdout_binding": {
                "path": paths["holdout_binding"],
                "sha256": holdout_binding_sha,
            }
        },
    }
    evaluator_binding_path = _write_json(
        root,
        paths["evaluator_binding"],
        evaluator_binding,
    )
    evaluator_binding_sha = hashlib.sha256(
        evaluator_binding_path.read_bytes()
    ).hexdigest()
    review = {
        "schema": "ias.s4_8.independent_recovery_review.v1",
        "amendment_id": "s4_8_recovery_amendment_02",
        "source_commit": SOURCE_COMMIT,
        "decision": "approved",
        "independent": True,
        "reviewer_id": "test-reviewer",
        "reviewed_at_utc": "2026-07-31T18:45:42Z",
    }
    review_path = _write_json(root, paths["independent_review"], review)
    review_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()
    grant_body["prerequisite"].update(
        {
            "evaluator_binding_sha256": evaluator_binding_sha,
            "holdout_binding_file_sha256": holdout_binding_sha,
            "holdout_seal_file_sha256": holdout_seal_sha,
            "independent_review_file_sha256": review_sha,
        }
    )
    grant = {
        **grant_body,
        "grant_sha256": _canonical_sha256(grant_body),
    }
    grant_path = _write_json(root, paths["scientific_grant"], grant)
    grant_file_sha = hashlib.sha256(grant_path.read_bytes()).hexdigest()
    authorization = {
        "schema": "ias.s4_8.authorization_record.v1",
        "authorization_id": GRANT_ID,
        "source_commit": SOURCE_COMMIT,
        "grant_id": GRANT_ID,
        "grant_path": paths["scientific_grant"],
        "grant_sha256": grant["grant_sha256"],
        "ledger_path": paths["scientific_ledger"],
        "irreversible_scientific_action_acknowledged": True,
    }
    _write_json(root, paths["scientific_authorization"], authorization)
    ledger_body = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "event": "holdout_open_authorized",
        "event_time_utc": "2026-07-31T19:02:30Z",
        "grant_id": GRANT_ID,
        "grant_sha256": grant["grant_sha256"],
        "holdout_opened": True,
        "purpose": "S4.8_evaluation",
        "previous_event_sha256": "0" * 64,
        "seal_sha256": "1" * 64,
        "split_plan_sha256": "2" * 64,
    }
    ledger = {
        **ledger_body,
        "event_sha256": _canonical_sha256(ledger_body),
    }
    _write(
        root,
        paths["scientific_ledger"],
        _canonical_bytes_with_newline(ledger),
    )
    opening_0 = _event(
        sequence=0,
        event="grant_consumed",
        previous="0" * 64,
        ledger_event_sha256=ledger["event_sha256"],
    )
    opening_1 = _event(
        sequence=1,
        event="observation_opening_authorized",
        previous=opening_0["event_sha256"],
        ledger_event_sha256=ledger["event_sha256"],
    )
    completed = _event(
        sequence=2,
        event="post_consumption_progress",
        previous=opening_1["event_sha256"],
        evaluation_state="evaluation_completed",
    )
    _write(
        root,
        paths["scientific_journal"],
        b"".join(
            _canonical_bytes_with_newline(record)
            for record in (opening_0, opening_1, completed)
        ),
    )
    recovery_body = {
        "schema": "ias.s4_8.post_consumption_recovery_context.v1",
        "source_commit": SOURCE_COMMIT,
        "authorization_record": authorization,
        "grant": {
            "path": paths["scientific_grant"],
            "file_sha256": grant_file_sha,
            "grant_sha256": grant["grant_sha256"],
        },
        "evaluation_state": "not_evaluated",
        "evaluation": {"status": "not_evaluated"},
    }
    recovery = {
        **recovery_body,
        "context_sha256": _canonical_sha256(recovery_body),
    }
    _write_json(root, paths["recovery_context"], recovery)
    evaluation = {
        "schema": "ias.s4_8.recovery_02.criteria_evaluation_result.v2",
        "status": "failed",
        "readiness_passed": False,
        "failed_gating_criteria": ["evaluation_input_contract_rejected"],
        "criteria": [],
        "comparison_classifications": [],
        "categorical_take_results": [],
        "evaluation_error": "frozen adverse input",
        "identity_summary": {"input_contract_adverse": True},
        "holdout_observations_accessed_by_evaluator": 0,
        "evaluation_invocation_count": 1,
    }
    derived = {
        "schema": "ias.s4_8.recovery_02.derived_evaluation_input.v2",
        "source_commit": SOURCE_COMMIT,
        "authorization_record": authorization,
        "grant": {
            "path": paths["scientific_grant"],
            "file_sha256": grant_file_sha,
            "grant_sha256": grant["grant_sha256"],
        },
        "ledger_event": ledger,
        "run_journal": {
            "path": paths["scientific_journal"],
            "opening_event_count": 2,
        },
        "evaluation_state": "evaluation_completed",
        "evaluation": evaluation,
        "evaluation_sha256": _canonical_sha256(evaluation),
        "run_failure": {
            "stage": "finalization",
            "terminal": True,
            "automatic_retry_forbidden": True,
        },
    }
    derived_path = _write_json(root, paths["derived_state"], derived)
    amendment = {
        "amendment_id": "s4_8_recovery_amendment_02",
        "revision_id": ("s4_8_recovery_amendment_02_preholdout_37_take_revision"),
    }
    _write_json(root, paths["amendment_contract"], amendment)
    allowed_inputs = []
    for role, relative in paths.items():
        allowed_inputs.append(
            {
                "role": role,
                "path": relative,
                "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            }
        )
    contract = {
        "schema": "ias.s4_8.recovery_02.terminalization_contract.v1",
        "contract_id": ("s4_8_recovery_amendment_02_37_take_terminalization_v1"),
        "status": "frozen_terminalization_only",
        "implementation_baseline_commit": BASELINE_COMMIT,
        "scientific_identity": {
            "scientific_source_commit": SOURCE_COMMIT,
            "grant_id": GRANT_ID,
            "derived_state_sha256": hashlib.sha256(
                derived_path.read_bytes()
            ).hexdigest(),
            "evaluation_profile": "evaluation_input_contract_rejected.v1",
            "evaluation_sha256": derived["evaluation_sha256"],
        },
        "authorization": {
            "authorization_id_prefix": (
                "s4_8_recovery_amendment_02_37_take_terminalization_v1_"
            ),
            "path": (
                "dataset/S4.8/recovery_amendment_02_37_take/access/"
                "terminalization_authorization.v1.json"
            ),
            "schema": ("ias.s4_8.recovery_02.terminalization_authorization.v1"),
            "schema_path": (
                "docs/schemas/"
                "s4_8_recovery_amendment_02_terminalization_authorization."
                "v1.schema.json"
            ),
        },
        "publication": {
            "output_path": (
                "outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_02_37_take"
            ),
            "closeout_path": (
                "docs/development/closeouts/S4/s4_8_recovery_amendment_02_37_take.md"
            ),
            "package_files": sorted(terminalizer.PACKAGE_FILES),
            "terminal_schema_path": (
                "docs/schemas/"
                "s4_8_recovery_amendment_02_terminal_package.v1.schema.json"
            ),
            "overwrite_permitted": False,
            "atomic_same_filesystem_rename_required": True,
        },
        "allowed_inputs": allowed_inputs,
        "raw_observation_roots": ["dataset/raw/attempts"],
        "authority": {
            "automatic_scientific_retry": False,
            "creates_or_consumes_scientific_grant": False,
            "opens_raw_observations": False,
            "preterminal_creates_authorization": False,
            "publishes_closeout": False,
            "recomputes_scientific_result": False,
            "starts_later_phase": False,
        },
    }
    return contract


def _canonical_bytes_with_newline(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture
def terminal_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    for relative in (
        terminalizer.CONTRACT_SCHEMA_PATH,
        Path(
            "docs/schemas/"
            "s4_8_recovery_amendment_02_terminalization_authorization."
            "v1.schema.json"
        ),
        Path("docs/schemas/s4_8_recovery_amendment_02_terminal_package.v1.schema.json"),
    ):
        _write(tmp_path, relative.as_posix(), (ROOT / relative).read_bytes())
    contract = _fixture_contract(tmp_path)
    _write_json(
        tmp_path,
        terminalizer.CONTRACT_PATH.as_posix(),
        contract,
    )
    (tmp_path / "dataset/raw/attempts").mkdir(parents=True)
    (tmp_path / "dataset/raw/attempts/secret.wav").write_bytes(b"raw")
    (tmp_path / "outputs/isaac_audio_sensors/S4").mkdir(parents=True)
    monkeypatch.setattr(
        terminalizer,
        "_validate_repository",
        lambda *_args, **_kwargs: None,
    )
    return tmp_path


def _contract(root: Path) -> dict[str, Any]:
    return json.loads((root / terminalizer.CONTRACT_PATH).read_text())


def _save_contract(root: Path, contract: dict[str, Any]) -> None:
    (root / terminalizer.CONTRACT_PATH).write_bytes(_pretty(contract))


def _input_path(root: Path, role: str) -> Path:
    contract = _contract(root)
    record = next(item for item in contract["allowed_inputs"] if item["role"] == role)
    return root / record["path"]


def _refresh_input(
    root: Path,
    role: str,
    *,
    evaluation_sha256: str | None = None,
) -> None:
    contract = _contract(root)
    record = next(item for item in contract["allowed_inputs"] if item["role"] == role)
    record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
    if role == "derived_state":
        contract["scientific_identity"]["derived_state_sha256"] = record["sha256"]
    if evaluation_sha256 is not None:
        contract["scientific_identity"]["evaluation_sha256"] = evaluation_sha256
    _save_contract(root, contract)


def _authorize(root: Path) -> tuple[str, dict[str, Any]]:
    preterminal = terminalizer.preterminal_validate(
        root,
        implementation_commit=IMPLEMENTATION_COMMIT,
    )
    authorization_id = preterminal["candidate_terminalization_authorization_id"]
    created = terminalizer.create_terminalization_authorization(
        root,
        implementation_commit=IMPLEMENTATION_COMMIT,
        authorization_id=authorization_id,
        authorized_at_utc="2026-07-31T20:30:00Z",
    )
    return authorization_id, created


def test_preterminal_is_strictly_read_only(terminal_root: Path) -> None:
    before = {
        path.relative_to(terminal_root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in terminal_root.rglob("*")
        if path.is_file()
    }

    result = terminalizer.preterminal_validate(
        terminal_root,
        implementation_commit=IMPLEMENTATION_COMMIT,
    )

    after = {
        path.relative_to(terminal_root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in terminal_root.rglob("*")
        if path.is_file()
    }
    contract = _contract(terminal_root)
    assert result["preterminal_status"] == "passed"
    assert result["scientific_verdict"] == "NO-GO"
    assert result["evaluator_invocation_count"] == 1
    assert result["scientific_recomputation_count"] == 0
    assert before == after
    assert not (terminal_root / contract["authorization"]["path"]).exists()
    assert not (terminal_root / contract["publication"]["output_path"]).exists()


def test_raw_observation_open_is_forbidden_before_read(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract(terminal_root)
    raw = terminal_root / "dataset/raw/attempts/secret.wav"
    contract["allowed_inputs"].append(
        {
            "role": "forbidden_raw",
            "path": "dataset/raw/attempts/secret.wav",
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        }
    )
    _save_contract(terminal_root, contract)
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == raw:
            raise AssertionError("raw observation was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="raw observation path is forbidden",
    ):
        terminalizer.preterminal_validate(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
        )


def test_success_path_never_opens_raw_observations(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = terminal_root / "dataset/raw/attempts"
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == raw_root or raw_root in path.parents:
            raise AssertionError("raw observation was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    result = terminalizer.preterminal_validate(
        terminal_root,
        implementation_commit=IMPLEMENTATION_COMMIT,
    )

    assert result["preterminal_status"] == "passed"


def test_terminalizer_import_isolated_from_evaluator_execution() -> None:
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(ROOT / 'src')!r});"
        "import isaac_audio_sensors.acquisition."
        "s4_8_recovery_02_terminalizer;"
        "assert 'isaac_audio_sensors.acquisition."
        "s4_8_recovery_02_evaluator' not in sys.modules;"
        "assert 'isaac_audio_sensors.acquisition."
        "s4_8_recovery_02_execution' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_derived_evaluation_change_fails_closed(terminal_root: Path) -> None:
    derived_path = _input_path(terminal_root, "derived_state")
    derived = json.loads(derived_path.read_text())
    derived["evaluation"]["evaluation_error"] = "changed"
    derived["evaluation_sha256"] = _canonical_sha256(derived["evaluation"])
    derived_path.write_bytes(_pretty(derived))
    _refresh_input(terminal_root, "derived_state")

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="authoritative derived evaluation binding mismatch",
    ):
        terminalizer.preterminal_validate(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
        )


def test_second_evaluator_invocation_fails_closed(terminal_root: Path) -> None:
    derived_path = _input_path(terminal_root, "derived_state")
    derived = json.loads(derived_path.read_text())
    derived["evaluation"]["evaluation_invocation_count"] = 2
    evaluation_sha256 = _canonical_sha256(derived["evaluation"])
    derived["evaluation_sha256"] = evaluation_sha256
    derived_path.write_bytes(_pretty(derived))
    _refresh_input(
        terminal_root,
        "derived_state",
        evaluation_sha256=evaluation_sha256,
    )

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="authoritative derived evaluation binding mismatch",
    ):
        terminalizer.preterminal_validate(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
        )


def test_authorization_is_separate_and_cannot_be_overwritten(
    terminal_root: Path,
) -> None:
    authorization_id, created = _authorize(terminal_root)
    authorization_path = terminal_root / created["authorization_path"]
    before = authorization_path.read_bytes()

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="authorization already exists",
    ):
        terminalizer.create_terminalization_authorization(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
            authorization_id=authorization_id,
            authorized_at_utc="2026-07-31T20:30:00Z",
        )

    assert authorization_path.read_bytes() == before


def test_terminalization_is_byte_preserving_and_never_invokes_evaluator(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_id, _created = _authorize(terminal_root)
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name.endswith(("s4_8_recovery_02_evaluator", "s4_8_recovery_02_execution")):
            raise AssertionError("evaluator execution path was imported")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    derived_bytes = _input_path(
        terminal_root,
        "derived_state",
    ).read_bytes()

    result = terminalizer.terminalize(
        terminal_root,
        implementation_commit=IMPLEMENTATION_COMMIT,
        authorization_id=authorization_id,
    )

    output = terminal_root / result["output_path"]
    terminal = json.loads((output / "terminal_validation.v1.json").read_text())
    assert result["terminalization_status"] == "completed"
    assert result["scientific_verdict"] == "NO-GO"
    assert (output / "heldout_evaluation_input.v2.json").read_bytes() == (derived_bytes)
    assert terminal["identities"] == {
        "scientific_source_commit": SOURCE_COMMIT,
        "terminalizer_implementation_commit": IMPLEMENTATION_COMMIT,
        "terminalization_authorization_id": authorization_id,
    }
    assert terminal["evaluator_invocation_count"] == 1
    assert terminal["scientific_recomputation_count"] == 0
    assert terminal["holdout_opening_count"] == 1


def test_existing_terminal_package_is_never_overwritten(
    terminal_root: Path,
) -> None:
    authorization_id, _created = _authorize(terminal_root)
    contract = _contract(terminal_root)
    output = terminal_root / contract["publication"]["output_path"]
    output.mkdir()
    marker = output / "existing"
    marker.write_text("preserve")

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="refusing to overwrite existing terminal package",
    ):
        terminalizer.terminalize(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
            authorization_id=authorization_id,
        )

    assert marker.read_text() == "preserve"


def test_input_drift_before_publication_leaves_no_package(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_id, _created = _authorize(terminal_root)
    derived_path = _input_path(terminal_root, "derived_state")

    def mutate(step: str, _path: Path) -> None:
        if step == "staging_fsynced":
            derived_path.write_bytes(derived_path.read_bytes() + b"\n")

    monkeypatch.setattr(terminalizer, "_publication_step", mutate)
    contract = _contract(terminal_root)
    output = terminal_root / contract["publication"]["output_path"]

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="input hash mismatch",
    ):
        terminalizer.terminalize(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
            authorization_id=authorization_id,
        )

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}.*.staging"))


def test_pre_rename_failure_leaves_no_partial_package(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_id, _created = _authorize(terminal_root)

    def fail(step: str, _path: Path) -> None:
        if step == "staging_fsynced":
            raise OSError("injected pre-rename failure")

    monkeypatch.setattr(terminalizer, "_publication_step", fail)
    contract = _contract(terminal_root)
    output = terminal_root / contract["publication"]["output_path"]

    with pytest.raises(OSError, match="injected pre-rename failure"):
        terminalizer.terminalize(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
            authorization_id=authorization_id,
        )

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}.*.staging"))


def test_raced_empty_destination_is_never_overwritten_or_removed(
    terminal_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_id, _created = _authorize(terminal_root)
    contract = _contract(terminal_root)
    output = terminal_root / contract["publication"]["output_path"]

    def create_raced_destination(step: str, _path: Path) -> None:
        if step == "before_rename":
            output.mkdir()

    monkeypatch.setattr(
        terminalizer,
        "_publication_step",
        create_raced_destination,
    )

    with pytest.raises(
        terminalizer.S48TerminalizationError,
        match="refusing to overwrite existing terminal package",
    ):
        terminalizer.terminalize(
            terminal_root,
            implementation_commit=IMPLEMENTATION_COMMIT,
            authorization_id=authorization_id,
        )

    assert output.is_dir()
    assert not list(output.iterdir())
    assert not list(output.parent.glob(f".{output.name}.*.staging"))
