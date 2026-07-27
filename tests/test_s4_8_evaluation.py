from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_8 import (
    S48Error,
    build_evidence_package,
    build_simulation_comparisons,
    create_grant,
    evaluate_payload,
    load_contract,
    preopen_validate,
    replay_evidence_package,
    validate_evidence_package,
)
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_attempt_inventory(
    payload: dict[str, object],
) -> list[dict[str, object]]:
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


def _synthetic_ledger_event() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {**payload, "event_sha256": s4_8.canonical_sha256(payload)}


def test_preopen_validation_authenticates_without_opening() -> None:
    result = preopen_validate(
        ROOT,
        verify_prerequisite_replay=False,
    )
    assert result["status"] == "passed"
    assert result["planned_take_count"] == 47
    assert result["leakage_group_count"] == 15
    assert result["sealed_artifact_count"] == 160
    assert result["content_derived_values_returned"] is False
    assert result["holdout_opened"] is False
    assert result["grant_present"] is False
    assert result["ledger_present"] is False


def test_preopen_attempt_selection_uses_frozen_technical_projection() -> None:
    config = load_contract(ROOT)
    seal = s4_8.load_json(ROOT / config["holdout"]["seal_path"])
    registry = s4_8.build_identity_registry(ROOT)
    selected = s4_8._sealed_attempt_roots(
        ROOT,
        seal,
        set(registry),
    )
    assert selected["s44a03_prospective_holdout_027_conf"].name.endswith(
        "__attempt_02"
    )
    assert len(selected) == 47


def test_first_run_journal_is_hash_chained_and_tamper_evident(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "first_run.jsonl"
    s4_8._append_run_journal(journal, {"event": "one"})
    s4_8._append_run_journal(journal, {"event": "two"})
    records = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["sequence"] for record in records] == [0, 1]
    assert records[1]["previous_event_sha256"] == records[0]["event_sha256"]
    records[0]["event"] = "tampered"
    journal.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(S48Error, match="journal chain"):
        s4_8._append_run_journal(journal, {"event": "three"})


def test_av_audio_candidate_selection_uses_frozen_spacing() -> None:
    selected = s4_8._select_three_spaced_events(
        [100, 5100, 5400, 10100, 15100],
        sample_rate_hz=1000,
        expected_interval_s=5.0,
    )
    assert selected == (100, 5100, 10100)
    with pytest.raises(S48Error, match="fewer than three"):
        s4_8._select_three_spaced_events(
            [100, 200],
            sample_rate_hz=1000,
            expected_interval_s=5.0,
        )


def test_simulation_harness_runs_exact_s4_6_modes_deterministically() -> None:
    first = build_simulation_comparisons(ROOT)
    second = build_simulation_comparisons(ROOT)
    assert first == second
    assert [item["comparison_id"] for item in first] == [
        "bearing_doa_error_ab",
        "sector_accuracy_b",
        "candidate_bearing_ab",
        "tdoa_a",
        "abstention_abd",
        "confidence_bc",
        "coarse_audio_video_association_e",
    ]
    assert sum(len(item["conditions"]) for item in first) == 271


def test_actual_simulation_payload_passes_corrective_03() -> None:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = build_simulation_comparisons(ROOT)
    result = evaluate_payload(payload, repo_root=ROOT)
    assert result["readiness_passed"] is True
    assert len(result["criteria"]) == 29
    assert all(
        item["classification"] == "preserves"
        for item in result["comparison_classifications"]
    )
    assert result["robustness"] == {
        "status": "not_evaluable",
        "denominator": 0,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["takes"].pop(),
        lambda payload: payload["takes"][0]["channels"].pop(),
        lambda payload: payload["takes"][0]["latency"].__setitem__(
            "capture_to_frame_offline_ms", float("nan")
        ),
        lambda payload: payload["takes"][1]["bearing_windows"].pop(),
        lambda payload: payload["takes"][1]["identity"].__setitem__(
            "planned_take_id", "unknown"
        ),
        lambda payload: payload["sim_vs_real"][0]["conditions"].pop(),
    ],
)
def test_malformed_or_incomplete_input_fails_closed(mutate) -> None:
    payload = build_synthetic_payload(ROOT)
    mutate(payload)
    result = evaluate_payload(payload, repo_root=ROOT)
    assert result["readiness_passed"] is False
    assert result["failed_gating_criteria"] == [
        "evaluation_input_contract_rejected"
    ]
    assert result["evaluation_error"]


def test_grant_creation_is_source_identified_and_does_not_consume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = copy.deepcopy(load_contract(ROOT))
    source_commit = "a" * 40
    monkeypatch.setattr(s4_8, "load_contract", lambda _root: config)
    monkeypatch.setattr(
        s4_8,
        "preopen_validate",
        lambda _root, source_commit: {
            "seal_file_sha256": "b" * 64,
            "partition_manifest_sha256": "c" * 64,
            "split_plan_sha256": "d" * 64,
            "prerequisite": {
                key: f"value-{key}"
                for key in s4_8.PREREQUISITE_BINDING_FIELDS
            },
        },
    )
    result = create_grant(
        tmp_path,
        source_commit=source_commit,
        authorization_id="user-message-test",
    )
    grant_path = tmp_path / config["grant"]["path"]
    ledger_path = tmp_path / config["grant"]["ledger_path"]
    assert grant_path.is_file()
    assert result["grant"]["grant_id"] == f"s4_8_corrective_03_{source_commit}"
    assert result["grant"]["split_plan_sha256"] == "d" * 64
    assert result["grant"]["single_use"] is True
    assert not ledger_path.exists()
    with pytest.raises(S48Error, match="already exists"):
        create_grant(
            tmp_path,
            source_commit=source_commit,
            authorization_id="user-message-test",
        )


def test_deterministic_evidence_package_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = build_simulation_comparisons(ROOT)
    evaluation = evaluate_payload(payload, repo_root=ROOT)
    derived = {
        "authorization_record": {
            "authorization_id": "synthetic",
            "source_commit": "a" * 40,
        },
        "grant": {
            "path": "dataset/S4.8/access/grant.json",
            "file_sha256": "b" * 64,
            "grant_sha256": "c" * 64,
        },
        "ledger_event": _synthetic_ledger_event(),
        "observation_inventory": _synthetic_attempt_inventory(payload),
        "payload": payload,
        "evaluation": evaluation,
    }
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
    package = tmp_path / "S4.8"
    result = build_evidence_package(
        ROOT,
        derived,
        output=package,
        source_commit="a" * 40,
    )
    assert result["status"] == "passed"
    validation = validate_evidence_package(package, repo_root=ROOT)
    assert validation["status"] == "passed"
    replay = replay_evidence_package(
        package,
        output=tmp_path / "replay",
        repo_root=ROOT,
    )
    assert replay["byte_identical"] is True
    assert replay["raw_holdout_reopened"] is False
    assert replay["grant_reconsumed"] is False


def test_evidence_manifest_rejects_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = build_synthetic_payload(ROOT)
    evaluation = evaluate_payload(payload, repo_root=ROOT)
    derived = {
        "authorization_record": {},
        "grant": {},
        "ledger_event": _synthetic_ledger_event(),
        "observation_inventory": _synthetic_attempt_inventory(payload),
        "payload": payload,
        "evaluation": evaluation,
    }
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
    package = tmp_path / "S4.8"
    build_evidence_package(
        ROOT,
        derived,
        output=package,
        source_commit="a" * 40,
    )
    report = json.loads(
        (package / "robustness.json").read_text(encoding="utf-8")
    )
    report["status"] = "passed"
    (package / "robustness.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    with pytest.raises(S48Error, match="manifest mismatch"):
        validate_evidence_package(package, repo_root=ROOT)
