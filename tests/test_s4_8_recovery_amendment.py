from __future__ import annotations

import copy
import json
import multiprocessing
import shutil
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery as recovery
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_ARTIFACT_NAMES = (
    "grant",
    "authorization",
    "ledger",
    "journal",
    "recovery_context",
    "derived_terminal_state",
    "terminal_manifest",
    "final_validation",
)


def _synthetic_attempt_inventory(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    takes = payload["takes"]
    records = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "attempt_root": f"dataset/test/{index:03d}/attempt_01",
            "selected_for_evaluation": True,
            "rejected": False,
        }
        for index, take in enumerate(takes)
    ]
    records.append(
        {
            "planned_take_id": takes[26]["identity"]["planned_take_id"],
            "attempt_root": "dataset/test/026/attempt_00",
            "selected_for_evaluation": False,
            "rejected": True,
        }
    )
    return records


def _synthetic_ledger_event(
    *,
    grant_id: str,
    grant_sha256: str,
) -> dict[str, Any]:
    payload = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "grant_id": grant_id,
        "grant_sha256": grant_sha256,
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {**payload, "event_sha256": s4_8.canonical_sha256(payload)}


def _preservation_passed(_root: Path) -> dict[str, Any]:
    return {
        "schema": "ias.s4_8.historical_preservation.v1",
        "status": "passed",
        "packages": [],
    }


def _spawned_validate_and_replay(
    canonical: str,
    output: str,
    outcome: multiprocessing.Queue,
) -> None:
    s4_8._validate_source_commit = lambda *_args, **_kwargs: None
    s4_8._result_dependency_records = lambda *_args, **_kwargs: []
    s4_8.preservation_report = _preservation_passed
    try:
        validation = recovery.validate_recovery_evidence_package(
            Path(canonical),
            repo_root=ROOT,
        )
        replay = recovery.replay_recovery_evidence_package(
            Path(canonical),
            output=Path(output),
            repo_root=ROOT,
        )
        outcome.put(("result", validation, replay))
    except Exception as exc:  # pragma: no cover - surfaced in the parent
        outcome.put(("error", type(exc).__name__, str(exc)))


def _spawned_create_recovery_grant(
    repo_root: str,
    source_commit: str,
    authorization_id: str,
    start: multiprocessing.Event,
    outcome: multiprocessing.Queue,
) -> None:
    root = Path(repo_root)
    amendment = copy.deepcopy(recovery.load_amendment(ROOT))
    contract = recovery._recovery_contract(ROOT, amendment)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(recovery, "load_amendment", lambda _root: amendment)
    monkeypatch.setattr(
        recovery,
        "_recovery_contract",
        lambda _root, _amendment: copy.deepcopy(contract),
    )
    monkeypatch.setattr(
        recovery,
        "validate_original_failure",
        lambda _root: {"status": "passed"},
    )
    monkeypatch.setattr(
        recovery,
        "_validate_independent_review",
        lambda *_args, **_kwargs: {"decision": "approved"},
    )
    monkeypatch.setattr(
        s4_8,
        "preopen_validate",
        lambda _root, *, source_commit, **_kwargs: {
            "seal_file_sha256": "b" * 64,
            "split_plan_sha256": "d" * 64,
            "prerequisite": {
                key: f"value-{key}"
                for key in s4_8.PREREQUISITE_BINDING_FIELDS
            },
        },
    )
    try:
        start.wait()
        result = recovery.create_recovery_grant(
            root,
            source_commit=source_commit,
            authorization_id=authorization_id,
        )
        outcome.put(("result", result))
    except Exception as exc:  # pragma: no cover - surfaced in the parent
        outcome.put(("error", type(exc).__name__, str(exc)))
    finally:
        monkeypatch.undo()


def _configure_synthetic_grant_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    amendment = copy.deepcopy(recovery.load_amendment(ROOT))
    contract = recovery._recovery_contract(ROOT, amendment)
    preopen_calls: list[str] = []
    original_authorization = amendment["original_run"]["artifacts"]["authorization"][
        "path"
    ]
    destination = tmp_path / original_authorization
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / original_authorization, destination)
    monkeypatch.setattr(recovery, "load_amendment", lambda _root: amendment)
    monkeypatch.setattr(
        recovery,
        "_recovery_contract",
        lambda _root, _amendment: copy.deepcopy(contract),
    )
    monkeypatch.setattr(
        recovery,
        "validate_original_failure",
        lambda _root: {"status": "passed"},
    )
    monkeypatch.setattr(
        recovery,
        "_validate_independent_review",
        lambda *_args, **_kwargs: {"decision": "approved"},
    )
    monkeypatch.setattr(
        s4_8,
        "preopen_validate",
        lambda _root, *, source_commit, **_kwargs: (
            preopen_calls.append(source_commit)
            or {
                "seal_file_sha256": "b" * 64,
                "split_plan_sha256": "d" * 64,
                "prerequisite": {
                    key: f"value-{key}"
                    for key in s4_8.PREREQUISITE_BINDING_FIELDS
                },
            }
        ),
    )
    return amendment, contract, preopen_calls


def _original_artifacts_present() -> bool:
    amendment = recovery.load_amendment(ROOT)
    return all(
        (ROOT / record["path"]).is_file()
        for record in amendment["original_run"]["artifacts"].values()
    )


@pytest.mark.skipif(
    not _original_artifacts_present(),
    reason="machine-local immutable first-run artifacts are unavailable",
)
def test_recovery_gate_authenticates_exact_original_without_observations() -> None:
    result = recovery.validate_original_failure(ROOT)
    assert result["status"] == "passed"
    assert result["terminal_status"] == "failed"
    assert result["evaluation_state"] == "not_evaluated"
    assert result["completed_observation_count"] == 0
    assert result["derived_observation_count"] == 0
    assert result["raw_holdout_read"] is False


@pytest.fixture
def original_failure_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object]]:
    if not _original_artifacts_present():
        pytest.skip("machine-local immutable first-run artifacts are unavailable")
    amendment = copy.deepcopy(recovery.load_amendment(ROOT))
    paths = amendment["original_run"]["artifacts"]
    for record in paths.values():
        source = ROOT / record["path"]
        destination = tmp_path / record["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    package = ROOT / "outputs/isaac_audio_sensors/S4/S4.8"
    destination_package = tmp_path / "outputs/isaac_audio_sensors/S4/S4.8"
    for source in package.iterdir():
        if source.is_file():
            destination = destination_package / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    base = s4_8.load_contract(ROOT)
    monkeypatch.setattr(recovery, "load_amendment", lambda _root: amendment)
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: copy.deepcopy(base))
    return tmp_path, amendment


@pytest.mark.parametrize(
    "artifact",
    ORIGINAL_ARTIFACT_NAMES,
)
@pytest.mark.parametrize("mutation", ["missing", "tampered"])
@pytest.mark.parametrize("operation", ["validate", "replay"])
def test_recovery_validation_and_replay_reject_original_artifact_drift(
    original_failure_root: tuple[Path, dict[str, object]],
    artifact: str,
    mutation: str,
    operation: str,
) -> None:
    root, amendment = original_failure_root
    path = root / amendment["original_run"]["artifacts"][artifact]["path"]
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n")

    if operation == "validate":

        def call() -> None:
            recovery.validate_recovery_evidence_package(
                repo_root=root,
            )

    else:

        def call() -> None:
            recovery.replay_recovery_evidence_package(
                output=root / "replay",
                repo_root=root,
            )

    with pytest.raises(s4_8.S48Error, match="original artifact mismatch"):
        call()
    assert not (root / "replay").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "scientific_observation_opened", True
        ),
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "scientific_observations_derived", True
        ),
        lambda derived: derived["observation_inventory"][0].__setitem__(
            "analysis_completed", True
        ),
        lambda derived: derived["payload"]["takes"].append({"derived": True}),
        lambda derived: derived.__setitem__("evaluation_state", "evaluation_completed"),
        lambda derived: derived["run_failure"].__setitem__(
            "error", "different failure"
        ),
    ],
    ids=[
        "observation-opened",
        "observation-derived",
        "analysis-completed",
        "payload-derived",
        "evaluation-completed",
        "different-failure",
    ],
)
def test_recovery_gate_rejects_ineligible_scientific_state(
    original_failure_root: tuple[Path, dict[str, object]],
    mutation,
) -> None:
    root, amendment = original_failure_root
    record = amendment["original_run"]["artifacts"]["derived_terminal_state"]
    path = root / record["path"]
    derived = s4_8.load_json(path)
    mutation(derived)
    if "payload" in derived:
        derived["payload_sha256"] = s4_8.canonical_sha256(derived["payload"])
    path.write_text(s4_8.pretty_json(derived), encoding="utf-8")
    record["sha256"] = s4_8.sha256_file(path)
    with pytest.raises(
        s4_8.S48Error,
        match="FAILED/NOT_EVALUATED|ineligible",
    ):
        recovery.validate_original_failure(root)


def test_recovery_gate_rejects_progress_or_provisional_state(
    original_failure_root: tuple[Path, dict[str, object]],
) -> None:
    root, amendment = original_failure_root
    journal = (
        root / amendment["original_run"]["artifacts"]["journal"]["path"]
    )
    progress = journal.with_name(s4_8.POST_CONSUMPTION_PROGRESS_NAME)
    progress.mkdir()
    with pytest.raises(s4_8.S48Error, match="progress or provisional"):
        recovery.validate_original_failure(root)


def test_recovery_amendment_uses_new_paths_and_keeps_authority_closed() -> None:
    amendment = recovery.load_amendment(ROOT)
    original_paths = {
        record["path"]
        for record in amendment["original_run"]["artifacts"].values()
    }
    future = amendment["future_attempt"]
    assert {
        future["grant_path"],
        future["ledger_path"],
        future["journal_path"],
        future["derived_input_path"],
        future["output_path"],
    }.isdisjoint(original_paths)
    assert future["grant_creation_authorized"] is False
    assert future["grant_consumption_authorized"] is False
    assert future["automatic_retry_of_original"] is False
    assert future["independent_review_required"] is True
    assert future["new_explicit_authorization_required"] is True


def test_grant_creation_requires_future_independent_review(
    tmp_path: Path,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    with pytest.raises(
        (OSError, s4_8.S48Error),
        match="independent_review|No such file",
    ):
        recovery._validate_independent_review(
            tmp_path,
            amendment=amendment,
            source_commit="a" * 40,
        )


def test_independent_review_must_bind_exact_candidate_source(
    tmp_path: Path,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    path = tmp_path / amendment["future_attempt"]["independent_review_path"]
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "ias.s4_8.independent_recovery_review.v1",
                "amendment_id": amendment["amendment_id"],
                "source_commit": "b" * 40,
                "decision": "approved",
                "independent": True,
                "reviewer_id": "reviewer",
                "reviewed_at_utc": "2030-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(s4_8.S48Error, match="independent review"):
        recovery._validate_independent_review(
            tmp_path,
            amendment=amendment,
            source_commit="a" * 40,
        )


def test_synthetic_recovery_execute_then_fresh_validate_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    original_paths = {
        ROOT / record["path"]
        for record in amendment["original_run"]["artifacts"].values()
    }
    original_package = ROOT / "outputs/isaac_audio_sensors/S4/S4.8"
    original_paths.update(path for path in original_package.iterdir() if path.is_file())
    original_bytes = {path: path.read_bytes() for path in original_paths}
    amendment, contract, _preopen_calls = _configure_synthetic_grant_creation(
        tmp_path,
        monkeypatch,
    )
    source_commit = "a" * 40
    authorization_id = "synthetic-recovery-authorization"
    created = recovery.create_recovery_grant(
        tmp_path,
        source_commit=source_commit,
        authorization_id=authorization_id,
    )
    canonical = tmp_path / amendment["future_attempt"]["output_path"]

    def synthetic_evaluation(
        _repo_root: Path,
        *,
        source_commit: str,
        event_time_utc: str,
    ) -> dict[str, Any]:
        del event_time_utc
        active = s4_8.load_contract(ROOT)
        assert active["grant"]["path"] == contract["grant"]["path"]
        payload = build_synthetic_payload(ROOT)
        payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
        grant = created["grant"]
        ledger_event = _synthetic_ledger_event(
            grant_id=grant["grant_id"],
            grant_sha256=grant["grant_sha256"],
        )
        derived = {
            "source_commit": source_commit,
            "authorization_record": created["authorization_record"],
            "grant": {
                "path": contract["grant"]["path"],
                "file_sha256": created["grant_file_sha256"],
                "grant_sha256": grant["grant_sha256"],
            },
            "ledger_event": ledger_event,
            "observation_inventory": _synthetic_attempt_inventory(payload),
            "payload": payload,
            "evaluation": s4_8.evaluate_payload(payload, repo_root=ROOT),
        }
        return s4_8.build_evidence_package(
            ROOT,
            derived,
            output=canonical,
            source_commit=source_commit,
        )

    monkeypatch.setattr(
        s4_8,
        "_validate_source_commit",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        s4_8,
        "_result_dependency_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(s4_8, "preservation_report", _preservation_passed)
    monkeypatch.setattr(
        s4_8,
        "run_authorized_evaluation_once",
        synthetic_evaluation,
    )
    executed = recovery.run_recovery_evaluation_once(
        tmp_path,
        source_commit=source_commit,
        authorization_id=authorization_id,
        event_time_utc="2030-01-01T00:00:00Z",
    )
    assert executed["status"] == "passed"
    assert (
        s4_8.load_contract(ROOT)["grant"]["path"]
        != amendment["future_attempt"]["grant_path"]
    )

    context = multiprocessing.get_context("spawn")
    outcome = context.Queue()
    replay_output = tmp_path / "replay"
    worker = context.Process(
        target=_spawned_validate_and_replay,
        args=(canonical.as_posix(), replay_output.as_posix(), outcome),
    )
    worker.start()
    worker.join(timeout=60)
    assert not worker.is_alive()
    result = outcome.get(timeout=5)
    assert result[0] == "result", result
    validation, replay = result[1:]
    assert validation["status"] == "passed"
    assert validation["amendment_id"] == amendment["amendment_id"]
    assert replay["byte_identical"] is True
    assert replay["amendment_id"] == amendment["amendment_id"]
    assert {
        path.name: path.read_bytes() for path in canonical.iterdir()
    } == {path.name: path.read_bytes() for path in replay_output.iterdir()}
    assert {path: path.read_bytes() for path in original_paths} == original_bytes


def test_recovery_grant_exact_pair_retry_reconciles_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _amendment, _contract, preopen_calls = _configure_synthetic_grant_creation(
        tmp_path,
        monkeypatch,
    )
    source_commit = "a" * 40
    created = recovery.create_recovery_grant(
        tmp_path,
        source_commit=source_commit,
        authorization_id="exact-retry",
    )
    retried = recovery.create_recovery_grant(
        tmp_path,
        source_commit=source_commit,
        authorization_id="exact-retry",
    )
    assert retried == created
    assert preopen_calls == [source_commit, source_commit]


def test_standalone_recovery_preopen_remains_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_synthetic_grant_creation(tmp_path, monkeypatch)
    strict_values: list[bool] = []

    def preopen(
        _root: Path,
        *,
        source_commit: str,
        verify_prerequisite_replay: bool,
        require_access_paths_absent: bool = True,
    ) -> dict[str, Any]:
        del source_commit, verify_prerequisite_replay
        strict_values.append(require_access_paths_absent)
        return {
            "planned_take_count": 47,
            "sealed_artifact_count": 160,
            "grant_present": False,
            "ledger_present": False,
        }

    monkeypatch.setattr(s4_8, "preopen_validate", preopen)
    result = recovery.recovery_preopen_validate(
        tmp_path,
        source_commit="a" * 40,
    )
    assert result["status"] == "passed"
    assert strict_values == [True]


def test_spawned_concurrent_identical_recovery_grant_creation_is_idempotent(
    tmp_path: Path,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    original_authorization = amendment["original_run"]["artifacts"][
        "authorization"
    ]["path"]
    destination = tmp_path / original_authorization
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / original_authorization, destination)

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    outcome = context.Queue()
    source_commit = "a" * 40
    workers = [
        context.Process(
            target=_spawned_create_recovery_grant,
            args=(
                tmp_path.as_posix(),
                source_commit,
                "concurrent-exact-pair",
                start,
                outcome,
            ),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=30)
        assert not worker.is_alive()

    results = [outcome.get(timeout=5) for _ in workers]
    assert [item[0] for item in results] == ["result", "result"]
    assert results[0][1] == results[1][1]
    grant_path = tmp_path / amendment["future_attempt"]["grant_path"]
    assert {path.name for path in grant_path.parent.iterdir()} == {
        grant_path.name,
        s4_8.AUTHORIZATION_RECORD_NAME,
    }
    assert not (
        tmp_path / amendment["future_attempt"]["ledger_path"]
    ).exists()


@pytest.mark.parametrize(
    "state",
    ["mismatched", "tampered", "consumed", "result-bearing"],
)
def test_recovery_grant_retry_rejects_non_idempotent_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    amendment, contract, _preopen_calls = _configure_synthetic_grant_creation(
        tmp_path,
        monkeypatch,
    )
    source_commit = "a" * 40
    authorization_id = "exact-retry"
    recovery.create_recovery_grant(
        tmp_path,
        source_commit=source_commit,
        authorization_id=authorization_id,
    )
    if state == "mismatched":
        authorization_id = "different-authorization"
    elif state == "tampered":
        grant_path = tmp_path / amendment["future_attempt"]["grant_path"]
        tampered = s4_8.load_json(grant_path)
        tampered["purpose"] = "tampered"
        grant_path.write_text(s4_8.pretty_json(tampered), encoding="utf-8")
    elif state == "consumed":
        ledger = tmp_path / contract["grant"]["ledger_path"]
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("{}\n", encoding="utf-8")
    else:
        output = tmp_path / contract["evidence"]["output_path"]
        output.mkdir(parents=True)
    with pytest.raises(
        s4_8.S48Error,
        match=(
            "publication validation"
            if state in {"mismatched", "tampered"}
            else "consumption or first-result state"
        ),
    ):
        recovery.create_recovery_grant(
            tmp_path,
            source_commit=source_commit,
            authorization_id=authorization_id,
        )


@pytest.mark.parametrize("operation", ["validate", "replay"])
def test_recovery_contract_context_cleans_up_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    expected_path = amendment["future_attempt"]["grant_path"]

    def fail(*_args, **_kwargs):
        assert s4_8.load_contract(ROOT)["grant"]["path"] == expected_path
        raise s4_8.S48Error("synthetic failure")

    if operation == "validate":
        monkeypatch.setattr(s4_8, "validate_evidence_package", fail)

        def call() -> None:
            recovery.validate_recovery_evidence_package(
                tmp_path,
                repo_root=ROOT,
            )

    else:
        monkeypatch.setattr(recovery, "_validate_recovery_provenance", fail)

        def call() -> None:
            recovery.replay_recovery_evidence_package(
                tmp_path,
                output=tmp_path / "replay",
                repo_root=ROOT,
            )

    with pytest.raises(s4_8.S48Error, match="synthetic failure"):
        call()
    assert s4_8.load_contract(ROOT)["grant"]["path"] != expected_path
