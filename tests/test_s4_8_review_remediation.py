from __future__ import annotations

import copy
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_4 import (
    S44Error,
    canonical_sha256,
    sha256_file,
    validate_ledger,
)
from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    PREREQUISITE_BINDING_FIELDS,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _ledger_event() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "event_time_utc": "2030-01-01T00:00:00Z",
        "seal_sha256": "b" * 64,
        "split_plan_sha256": "c" * 64,
        "grant_id": "synthetic",
        "grant_sha256": "d" * 64,
        "prerequisite_sha256": "e" * 64,
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {**payload, "event_sha256": canonical_sha256(payload)}


def _inventory(payload: dict[str, object]) -> list[dict[str, object]]:
    takes = payload["takes"]
    assert isinstance(takes, list)
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


def _derived(
    payload: dict[str, object],
    *,
    run_failure: dict[str, object] | None = None,
) -> dict[str, object]:
    evaluation = s4_8.evaluate_payload(payload, repo_root=ROOT)
    return {
        "schema": s4_8.DERIVED_INPUT_SCHEMA,
        "tool_version": s4_8.TOOL_VERSION,
        "source_commit": "a" * 40,
        "event_time_utc": "2030-01-01T00:00:00Z",
        "authorization_record": {
            "authorization_id": "synthetic",
            "source_commit": "a" * 40,
        },
        "grant": {
            "path": "dataset/S4.8/access/grant.json",
            "file_sha256": "b" * 64,
            "grant_sha256": "c" * 64,
        },
        "ledger_event": _ledger_event(),
        "run_journal": {
            "opening_event_count": 2,
            "opening_head_sha256": "f" * 64,
            "terminal_event_required": True,
        },
        "observation_inventory": _inventory(
            build_synthetic_payload(ROOT)
        ),
        "payload": payload,
        "payload_sha256": canonical_sha256(payload),
        "evaluation": evaluation,
        "run_failure": run_failure,
    }


@pytest.fixture
def package_test_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        s4_8,
        "preservation_report",
        lambda _root: {
            "schema": "ias.s4_8.historical_preservation.v1",
            "status": "passed",
            "packages": [],
        },
    )


def _all_window_abstention_payload() -> dict[str, object]:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    takes = payload["takes"]
    assert isinstance(takes, list)
    take = next(
        item
        for item in takes
        if item["identity"]["stratum_id"]
        == "A_controlled_boundary_sweep"
    )
    for window in take["bearing_windows"]:
        window["abstained"] = True
        window["srp_bearing_deg_f_project"] = None
    take["window_summary"]["abstained_window_count"] = len(
        take["bearing_windows"]
    )
    take["bearing_absolute_error_deg"] = None
    take["estimated_bearing_deg_f_project"] = None
    take["candidate_covered"] = False
    take["candidate_bearings_deg_f_project"] = []
    return payload


def test_all_window_abstention_finalizes_complete_failed_package(
    tmp_path: Path,
    package_test_stubs: None,
) -> None:
    payload = _all_window_abstention_payload()
    derived = _derived(payload)
    assert derived["evaluation"]["failed_gating_criteria"] == [
        "evaluation_input_contract_rejected"
    ]
    package = tmp_path / "S4.8"
    result = s4_8.build_evidence_package(
        ROOT,
        derived,
        output=package,
        source_commit="a" * 40,
    )
    assert result["status"] == "failed"
    assert {path.name for path in package.iterdir()} == s4_8.PACKAGE_FILES
    validation = s4_8.validate_evidence_package(package, repo_root=ROOT)
    assert validation["final_status"] == "failed"
    final = s4_8.load_json(package / "final_validation.json")
    assert final["terminal"] is True
    assert final["automatic_retry_forbidden"] is True


def test_package_construction_is_atomic_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_test_stubs: None,
) -> None:
    payload = build_synthetic_payload(ROOT)
    derived = _derived(payload)
    output = tmp_path / "S4.8"

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected packaging failure")

    monkeypatch.setattr(s4_8, "_build_evidence_package_in_place", fail)
    with pytest.raises(RuntimeError, match="injected packaging failure"):
        s4_8.build_evidence_package(
            ROOT,
            derived,
            output=output,
            source_commit="a" * 40,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".S4.8.*.staging"))


def test_first_run_packaging_failure_finalizes_failed_evidence_and_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_test_stubs: None,
) -> None:
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["grant"]["path"] = "access/grant.json"
    config["grant"]["ledger_path"] = "access/ledger.jsonl"
    config["evidence"]["derived_input_path"] = "derived/input.json"
    config["evidence"]["run_journal_path"] = "derived/journal.jsonl"
    config["evidence"]["output_path"] = "output/S4.8"
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
    source_commit = "a" * 40
    grant_path = tmp_path / config["grant"]["path"]
    grant_path.parent.mkdir(parents=True)
    grant_path.write_text(
        s4_8.pretty_json({"grant_sha256": "c" * 64}),
        encoding="utf-8",
    )
    grant_path.with_name("authorization_record.v1.json").write_text(
        s4_8.pretty_json(
            {
                "authorization_id": "synthetic",
                "source_commit": source_commit,
            }
        ),
        encoding="utf-8",
    )
    ledger_event = _ledger_event()

    def fake_consume(
        repo_root: Path,
        *,
        source_commit: str,
        event_time_utc: str,
    ) -> dict[str, object]:
        journal = repo_root / config["evidence"]["run_journal_path"]
        records = s4_8._opening_journal_records(
            source_commit=source_commit,
            event_time_utc=event_time_utc,
            ledger_event=ledger_event,
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(
            "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":"))
                + "\n"
                for record in records
            ),
            encoding="utf-8",
        )
        return {
            "allowed": True,
            "mode": "S4.8_evaluation",
            "ledger_event": ledger_event,
            "journal_records": records,
        }

    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    original_evaluate = s4_8.evaluate_payload
    monkeypatch.setattr(
        s4_8,
        "evaluate_payload",
        lambda value, *, repo_root: original_evaluate(
            value, repo_root=ROOT
        ),
    )
    monkeypatch.setattr(s4_8, "preopen_validate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(s4_8, "consume_grant_once", fake_consume)
    monkeypatch.setattr(
        s4_8,
        "build_real_payload",
        lambda _root: (payload, _inventory(payload)),
    )
    original_atomic = s4_8._build_evidence_package_atomic

    def fallback(
        _repo_root: Path,
        derived,
        *,
        output: Path,
        source_commit: str,
        require_current_head: bool,
    ):
        return original_atomic(
            ROOT,
            derived,
            output=output,
            source_commit=source_commit,
            require_current_head=require_current_head,
        )

    monkeypatch.setattr(s4_8, "_build_evidence_package_atomic", fallback)
    monkeypatch.setattr(
        s4_8,
        "build_evidence_package",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected packaging failure")
        ),
    )
    result = s4_8.run_authorized_evaluation_once(
        tmp_path,
        source_commit=source_commit,
        event_time_utc="2030-01-01T00:00:00Z",
    )
    assert result["readiness_passed"] is True
    output = tmp_path / config["evidence"]["output_path"]
    assert {path.name for path in output.iterdir()} == s4_8.PACKAGE_FILES
    final = s4_8.load_json(output / "final_validation.json")
    assert final["status"] == "failed"
    assert final["run_failure"]["stage"] == "evidence_packaging"
    journal = tmp_path / config["evidence"]["run_journal_path"]
    terminal = s4_8._load_run_journal(journal)[-1]
    assert terminal["event"] == "first_run_terminal"
    assert terminal["terminal_status"] == "failed"
    with pytest.raises(s4_8.S48Error, match="automatic retry forbidden"):
        s4_8.run_authorized_evaluation_once(
            tmp_path,
            source_commit=source_commit,
            event_time_utc="2030-01-01T00:00:01Z",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda package: _mutate_json(
            package / "derived_evaluation_input.json",
            lambda value: value["payload"]["takes"].pop(),
            refresh_payload_hash=True,
        ),
        lambda package: _mutate_json(
            package / "criteria_results.json",
            lambda value: value.__setitem__(
                "readiness_passed", not value["readiness_passed"]
            ),
        ),
        lambda package: _mutate_json(
            package / "final_validation.json",
            lambda value: value.__setitem__(
                "readiness_passed", not value["readiness_passed"]
            ),
        ),
        lambda package: _mutate_json(
            package / "sim_vs_real.json",
            lambda value: value["comparison_classifications"][0].__setitem__(
                "classification", "worsens"
            ),
        ),
        lambda package: _mutate_json(
            package / "final_validation.json",
            lambda value: value.__setitem__("status", "failed"),
        ),
    ],
    ids=[
        "altered_observation",
        "altered_criteria",
        "altered_pass_flag",
        "altered_classification",
        "altered_final_status",
    ],
)
def test_validation_rejects_checksum_consistent_contradictions(
    tmp_path: Path,
    mutation,
    package_test_stubs: None,
) -> None:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    package = tmp_path / "S4.8"
    s4_8.build_evidence_package(
        ROOT,
        _derived(payload),
        output=package,
        source_commit="a" * 40,
    )
    mutation(package)
    s4_8._write_index_and_manifest(package, "a" * 40)
    with pytest.raises(s4_8.S48Error):
        s4_8.validate_evidence_package(package, repo_root=ROOT)


def _mutate_json(
    path: Path,
    mutation,
    *,
    refresh_payload_hash: bool = False,
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    if refresh_payload_hash:
        value["payload_sha256"] = canonical_sha256(value["payload"])
    path.write_text(s4_8.pretty_json(value), encoding="utf-8")


def test_replay_recomputes_scientific_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_test_stubs: None,
) -> None:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    canonical = tmp_path / "canonical"
    s4_8.build_evidence_package(
        ROOT,
        _derived(payload),
        output=canonical,
        source_commit="a" * 40,
    )
    calls = 0
    original = s4_8.evaluate_payload

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(s4_8, "evaluate_payload", counted)
    replay = s4_8.replay_evidence_package(
        canonical,
        output=tmp_path / "replay",
        repo_root=ROOT,
    )
    assert replay["byte_identical"] is True
    assert calls >= 3


def test_terminal_journal_rejects_any_retry(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    ledger_sha = "a" * 64
    source_commit = "b" * 40
    for event in ("grant_consumed", "observation_opening_authorized"):
        s4_8._append_run_journal(
            journal,
            {
                "event": event,
                "source_commit": source_commit,
                "ledger_event_sha256": ledger_sha,
            },
        )
    s4_8._append_run_journal(
        journal,
        {
            "event": "first_run_terminal",
            "source_commit": source_commit,
            "terminal_status": "failed",
            "automatic_retry_forbidden": True,
        },
    )
    s4_8._validate_terminal_journal(
        journal,
        source_commit=source_commit,
        expected_status="failed",
        expected_ledger_event_sha256=ledger_sha,
    )
    with pytest.raises(s4_8.S48Error, match="terminal; retry forbidden"):
        s4_8._append_run_journal(journal, {"event": "retry"})


def test_dirty_transitive_dependency_and_import_shadow_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    dependency = repo / "src/isaac_audio_sensors/core/transitive.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.name", "S4.8 test")
    _git(repo, "config", "user.email", "s4.8@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate")
    source_commit = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(s4_8, "_validate_import_origins", lambda _root: None)
    s4_8._validate_source_commit(repo, source_commit)
    dependency.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(s4_8.S48Error, match="result dependency differs"):
        s4_8._validate_source_commit(repo, source_commit)
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    shadow = repo / "numpy.py"
    shadow.write_text("shadow = True\n", encoding="utf-8")
    with pytest.raises(s4_8.S48Error, match="uncommitted Python code"):
        s4_8._validate_source_commit(repo, source_commit)


def test_concurrent_consumers_have_exactly_one_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from isaac_audio_sensors.acquisition import (
        s4_7_prerequisite_corrective_03 as prerequisite_module,
    )

    seal = tmp_path / "seal.json"
    seal.write_text('{"seal":"synthetic"}\n', encoding="utf-8")
    prerequisite = tmp_path / "prerequisite.json"
    prerequisite.write_text("{}\n", encoding="utf-8")
    seal_sha = sha256_file(seal)
    authenticated = {
        key: f"value-{key}" for key in PREREQUISITE_BINDING_FIELDS
    }
    authenticated["sha256"] = "e" * 64
    authenticated["seal_file_sha256"] = seal_sha
    monkeypatch.setattr(
        prerequisite_module,
        "validate_s4_7_corrective_03_prerequisite",
        lambda *_args, **_kwargs: authenticated,
    )
    monkeypatch.setattr(
        prerequisite_module,
        "validate_grant_prerequisite_binding",
        lambda binding, expected: None,
    )
    source_commit = "a" * 40
    payload = {
        "schema": "ias.s4_4.holdout_access_grant.v1",
        "grant_id": f"s4_8_corrective_03_{source_commit}",
        "purpose": "S4.8_evaluation",
        "seal_sha256": seal_sha,
        "split_plan_sha256": "c" * 64,
        "prerequisite": {
            key: authenticated[key]
            for key in PREREQUISITE_BINDING_FIELDS
        },
        "single_use": True,
        "authorization": "explicit_user_authorization_required",
    }
    grant = {**payload, "grant_sha256": canonical_sha256(payload)}
    grant_path = tmp_path / "grant.json"
    grant_path.write_text(s4_8.pretty_json(grant), encoding="utf-8")
    transition = tmp_path / "opening_transition.v1"
    ledger = transition / "ledger.jsonl"
    journal = transition / "journal.jsonl"
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["grant"]["path"] = grant_path.name
    config["grant"]["ledger_path"] = ledger.relative_to(tmp_path).as_posix()
    config["evidence"]["run_journal_path"] = (
        journal.relative_to(tmp_path).as_posix()
    )
    config["holdout"]["seal_path"] = seal.name
    config["holdout"]["split_plan_sha256"] = "c" * 64
    config["prerequisite"]["path"] = prerequisite.name
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
    errors: list[str] = []

    def consume() -> bool:
        try:
            s4_8.consume_grant_once(
                tmp_path,
                source_commit=source_commit,
                event_time_utc="2030-01-01T00:00:00Z",
            )
        except (S44Error, s4_8.S48Error) as exc:
            errors.append(str(exc))
            return False
        return True

    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = list(executor.map(lambda _index: consume(), range(24)))
    assert outcomes.count(True) == 1, errors
    validation = validate_ledger(
        ledger,
        expected_seal_sha256=seal_sha,
    )
    assert validation["status"] == "passed"
    assert validation["event_count"] == 1
    journal_records = s4_8._load_run_journal(journal)
    assert [record["event"] for record in journal_records] == [
        "grant_consumed",
        "observation_opening_authorized",
    ]
