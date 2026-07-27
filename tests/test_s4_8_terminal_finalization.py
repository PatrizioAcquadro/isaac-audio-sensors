from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def _load_run_cli():
    spec = importlib.util.spec_from_file_location(
        "test_run_s4_8_cli",
        ROOT / "scripts/run_s4_8.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "stage",
    [
        "observation_input",
        "observation_analysis",
        "evidence_packaging",
        "finalization_publication",
    ],
)
def test_execute_cli_exits_nonzero_for_every_terminal_failure(
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_cli()
    failure = {
        "stage": stage,
        "error_type": "RuntimeError",
        "error": "injected",
        "terminal": True,
        "automatic_retry_forbidden": True,
    }
    monkeypatch.setattr(
        module,
        "run_authorized_evaluation_once",
        lambda *_args, **_kwargs: {
            "schema": "ias.s4_8.authorized_run_outcome.v1",
            "status": "failed",
            "readiness_passed": False,
            "scientific_readiness_passed": stage == "evidence_packaging",
            "failed_gating_criteria": [],
            "run_failure": failure,
            "evaluation": {},
            "evidence": {"status": "failed"},
            "automatic_retry_forbidden": True,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_s4_8.py",
            "--execute",
            "--source-commit",
            "a" * 40,
            "--event-time-utc",
            "2030-01-01T00:00:00Z",
        ],
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["readiness_passed"] is False
    assert result["run_failure"]["stage"] == stage


def test_analysis_failure_preserves_exact_n_take_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["holdout"]["seal_path"] = "seal.json"
    (tmp_path / "seal.json").write_text("{}\n", encoding="utf-8")
    registry = s4_8.build_identity_registry(ROOT)
    take_ids = sorted(registry)
    relative_roots = {
        take_id: Path("dataset/synthetic") / take_id / "attempt_01"
        for take_id in take_ids
    }
    absolute_roots = {
        take_id: tmp_path / relative
        for take_id, relative in relative_roots.items()
    }
    candidates = {
        take_id: {relative_roots[take_id]} for take_id in take_ids
    }
    replacement_take_id = take_ids[26]
    candidates[replacement_take_id].add(
        Path("dataset/synthetic")
        / replacement_take_id
        / "attempt_00"
    )
    synthetic_takes = {
        take["identity"]["planned_take_id"]: take
        for take in build_synthetic_payload(ROOT)["takes"]
    }
    completed_before_failure = 7
    calls = 0

    def analyze(
        _root: Path,
        attempt_root: Path,
        identity,
        *,
        profile,
        seal,
    ):
        del profile, seal
        nonlocal calls
        calls += 1
        if calls == completed_before_failure + 1:
            raise RuntimeError("injected Nth-take failure")
        take = copy.deepcopy(synthetic_takes[identity.planned_take_id])
        return take, {
            "planned_take_id": identity.planned_take_id,
            "attempt_root": attempt_root.relative_to(tmp_path).as_posix(),
            "window_count": len(take["bearing_windows"]),
            "failed": take["failed"],
            "failure_reasons": take["failure_reasons"],
            "rejected": False,
            "excluded": False,
            "av_analysis": None,
        }

    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
    monkeypatch.setattr(s4_8, "_require_consumed_ledger", lambda *_args: None)
    monkeypatch.setattr(
        s4_8,
        "hash_only_holdout_integrity",
        lambda *_args, **_kwargs: {"status": "passed"},
    )
    monkeypatch.setattr(
        s4_8,
        "build_identity_registry",
        lambda _root: registry,
    )
    monkeypatch.setattr(
        s4_8,
        "_sealed_attempt_candidates",
        lambda *_args: candidates,
    )
    monkeypatch.setattr(
        s4_8,
        "_sealed_attempt_roots",
        lambda *_args: absolute_roots,
    )
    monkeypatch.setattr(
        s4_8,
        "_seal_record",
        lambda *_args: {"sha256": "b" * 64},
    )
    monkeypatch.setattr(s4_8, "_profile_runtime", lambda _root: {})
    monkeypatch.setattr(
        s4_8,
        "build_simulation_comparisons",
        lambda _root: [],
    )
    monkeypatch.setattr(s4_8, "_analyze_real_take", analyze)

    with pytest.raises(s4_8.S48PartialAnalysisError) as raised:
        s4_8.build_real_payload(tmp_path)
    error = raised.value
    assert len(error.payload["takes"]) == completed_before_failure
    selected = [
        record
        for record in error.observation_inventory
        if record["selected_for_evaluation"] is True
    ]
    opened = [
        record
        for record in selected
        if record["scientific_observation_opened"] is True
    ]
    derived = [
        record
        for record in selected
        if record["scientific_observations_derived"] is True
    ]
    unopened = [
        record
        for record in selected
        if record["scientific_observation_opened"] is False
    ]
    failed_record = opened[-1]
    assert len(opened) == completed_before_failure + 1
    assert len(derived) == completed_before_failure
    assert len(unopened) == 47 - completed_before_failure - 1
    assert failed_record["scientific_observations_derived"] is False
    assert failed_record["terminal_error"] == "injected Nth-take failure"
    assert all(
        record["scientific_observations_derived"] is False
        for record in unopened
    )


def _synthetic_inventory(
    payload: dict[str, object],
) -> list[dict[str, object]]:
    takes = payload["takes"]
    assert isinstance(takes, list)
    records = [
        {
            "planned_take_id": take["identity"]["planned_take_id"],
            "attempt_root": f"dataset/test/{index:03d}/attempt_01",
            "selected_for_evaluation": True,
            "scientific_observation_opened": True,
            "scientific_observations_derived": True,
            "analysis_completed": True,
            "rejected": False,
        }
        for index, take in enumerate(takes)
    ]
    records.append(
        {
            "planned_take_id": takes[26]["identity"]["planned_take_id"],
            "attempt_root": "dataset/test/026/attempt_00",
            "selected_for_evaluation": False,
            "scientific_observation_opened": False,
            "scientific_observations_derived": False,
            "analysis_completed": False,
            "rejected": True,
        }
    )
    return records


def _ledger_event() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {**payload, "event_sha256": s4_8.canonical_sha256(payload)}


@pytest.mark.parametrize("already_published", [False, True])
def test_prepared_finalization_recovers_at_publication_journal_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    already_published: bool,
) -> None:
    source_commit = "a" * 40
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["evidence"]["output_path"] = "output/S4.8"
    config["evidence"]["run_journal_path"] = "state/journal.jsonl"
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    evaluation = s4_8.evaluate_payload(payload, repo_root=ROOT)
    failure = {
        "stage": "finalization_publication",
        "error_type": "RuntimeError",
        "error": "injected crash boundary",
        "terminal": True,
        "automatic_retry_forbidden": True,
    }
    derived = {
        "schema": s4_8.DERIVED_INPUT_SCHEMA,
        "tool_version": s4_8.TOOL_VERSION,
        "source_commit": source_commit,
        "event_time_utc": "2030-01-01T00:00:00Z",
        "authorization_record": {"source_commit": source_commit},
        "grant": {"grant_sha256": "b" * 64},
        "ledger_event": _ledger_event(),
        "run_journal": {"terminal_event_required": True},
        "observation_inventory": _synthetic_inventory(payload),
        "payload": payload,
        "payload_sha256": s4_8.canonical_sha256(payload),
        "evaluation": evaluation,
        "run_failure": failure,
        "runtime_provenance": s4_8._runtime_dependency_provenance(),
    }
    output = tmp_path / config["evidence"]["output_path"]
    staging = s4_8._finalization_staging_path(output)
    staging.parent.mkdir(parents=True)
    staging.mkdir()
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
    s4_8._build_terminal_failure_package_in_place(
        ROOT,
        derived,
        destination=staging,
        source_commit=source_commit,
    )
    journal = tmp_path / config["evidence"]["run_journal_path"]
    ledger_event = derived["ledger_event"]
    opening = s4_8._opening_journal_records(
        source_commit=source_commit,
        event_time_utc="2030-01-01T00:00:00Z",
        ledger_event=ledger_event,
    )
    journal.parent.mkdir(parents=True)
    journal.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in opening
        ),
        encoding="utf-8",
    )
    prepared = {
        "event": "first_run_finalization_prepared",
        "event_time_utc": "2030-01-01T00:00:00Z",
        "source_commit": source_commit,
        "terminal_status": "failed",
        "readiness_passed": False,
        "scientific_readiness_passed": True,
        "failed_gating_criteria": [],
        "run_failure": failure,
        "derived_input_sha256": "c" * 64,
        "evidence_manifest_sha256": s4_8.sha256_file(
            staging / "SHA256SUMS"
        ),
        "staging_path": staging.relative_to(tmp_path).as_posix(),
        "output_path": output.relative_to(tmp_path).as_posix(),
        "automatic_retry_forbidden": True,
    }
    s4_8._append_run_journal(journal, prepared)
    if already_published:
        os.replace(staging, output)
    original_validate = s4_8.validate_evidence_package
    monkeypatch.setattr(
        s4_8,
        "validate_evidence_package",
        lambda package, *, repo_root: original_validate(
            package,
            repo_root=ROOT,
        ),
    )
    monkeypatch.setattr(
        s4_8,
        "_build_evidence_package_in_place",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery retried the full package builder")
        ),
    )
    result = s4_8._recover_pending_finalization(
        tmp_path,
        config=config,
        source_commit=source_commit,
    )
    assert result["final_status"] == "failed"
    assert output.is_dir()
    assert not staging.exists()
    assert [record["event"] for record in s4_8._load_run_journal(journal)] == [
        "grant_consumed",
        "observation_opening_authorized",
        "first_run_finalization_prepared",
        "first_run_terminal",
    ]


def test_runtime_provenance_declares_jsonschema() -> None:
    provenance = s4_8._runtime_dependency_provenance()
    versions = {
        item["distribution"]: item["version"]
        for item in provenance["distributions"]
    }
    assert "jsonschema" in versions
    assert versions["jsonschema"]
    assert "jsonschema>=4.10" in provenance["declared_runtime_dependencies"]
    assert '"jsonschema>=4.10"' in (ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_terminal_journal_write_failure_downgrades_same_run_to_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_commit = "a" * 40
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["evidence"]["derived_input_path"] = "state/derived.json"
    config["evidence"]["run_journal_path"] = "state/journal.jsonl"
    config["evidence"]["output_path"] = "output/S4.8"
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)
    evaluation = s4_8.evaluate_payload(payload, repo_root=ROOT)
    derived = {
        "schema": s4_8.DERIVED_INPUT_SCHEMA,
        "tool_version": s4_8.TOOL_VERSION,
        "source_commit": source_commit,
        "event_time_utc": "2030-01-01T00:00:00Z",
        "authorization_record": {"source_commit": source_commit},
        "grant": {"grant_sha256": "b" * 64},
        "ledger_event": _ledger_event(),
        "run_journal": {"terminal_event_required": True},
        "observation_inventory": _synthetic_inventory(payload),
        "payload": payload,
        "payload_sha256": s4_8.canonical_sha256(payload),
        "evaluation": evaluation,
        "run_failure": None,
        "runtime_provenance": s4_8._runtime_dependency_provenance(),
    }
    derived_path = tmp_path / config["evidence"]["derived_input_path"]
    derived_path.parent.mkdir(parents=True)
    derived_path.write_text(s4_8.pretty_json(derived), encoding="utf-8")
    journal = tmp_path / config["evidence"]["run_journal_path"]
    opening = s4_8._opening_journal_records(
        source_commit=source_commit,
        event_time_utc="2030-01-01T00:00:00Z",
        ledger_event=derived["ledger_event"],
    )
    journal.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in opening
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
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
    original_full = s4_8._build_evidence_package_in_place
    original_failure = s4_8._build_terminal_failure_package_in_place
    monkeypatch.setattr(
        s4_8,
        "_build_evidence_package_in_place",
        lambda _root, value, **kwargs: original_full(
            ROOT, value, **kwargs
        ),
    )
    monkeypatch.setattr(
        s4_8,
        "_build_terminal_failure_package_in_place",
        lambda _root, value, **kwargs: original_failure(
            ROOT, value, **kwargs
        ),
    )
    original_append = s4_8._append_run_journal
    injected = False

    def append_with_terminal_failure(
        path: Path,
        event: dict[str, object],
    ) -> None:
        nonlocal injected
        if event.get("event") == "first_run_terminal" and not injected:
            injected = True
            raise OSError("injected terminal journal write failure")
        original_append(path, event)

    monkeypatch.setattr(
        s4_8,
        "_append_run_journal",
        append_with_terminal_failure,
    )
    finalized, package = s4_8._finalize_first_run(
        tmp_path,
        config=config,
        derived=derived,
        source_commit=source_commit,
        event_time_utc="2030-01-01T00:00:00Z",
    )
    assert package["status"] == "failed"
    assert finalized["run_failure"]["stage"] == "finalization_publication"
    output = tmp_path / config["evidence"]["output_path"]
    assert s4_8.load_json(output / "final_validation.json")["status"] == "failed"
    assert (derived_path.parent / "provisional_evidence.v1").is_dir()
    assert [record["event"] for record in s4_8._load_run_journal(journal)] == [
        "grant_consumed",
        "observation_opening_authorized",
        "first_run_finalization_prepared",
        "first_run_finalization_failed",
        "first_run_terminal",
    ]
