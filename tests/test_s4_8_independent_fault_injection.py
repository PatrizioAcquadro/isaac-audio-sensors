from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition import s4_8

ROOT = Path(__file__).resolve().parents[1]


def _ledger_event() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ias.s4_4.access_ledger_event.v1",
        "sequence": 0,
        "previous_event_sha256": "0" * 64,
        "event": "holdout_open_authorized",
        "purpose": "S4.8_evaluation",
        "holdout_opened": True,
    }
    return {
        **payload,
        "event_sha256": s4_8.canonical_sha256(payload),
    }


def test_journal_rejects_failure_downgrade_without_durable_intent(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    journal = tmp_path / "journal.jsonl"
    opening = s4_8._opening_journal_records(
        source_commit=source_commit,
        event_time_utc="2030-01-01T00:00:00Z",
        ledger_event=_ledger_event(),
    )
    journal.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in opening
        ),
        encoding="utf-8",
    )
    s4_8._append_run_journal(
        journal,
        {
            "event": "first_run_finalization_prepared",
            "source_commit": source_commit,
        },
    )
    with pytest.raises(s4_8.S48Error, match="journal transition"):
        s4_8._append_run_journal(
            journal,
            {
                "event": "first_run_finalization_failed",
                "source_commit": source_commit,
            },
        )


def test_recovery_capsule_hash_covers_inventory_and_runtime(
    tmp_path: Path,
) -> None:
    source_commit = "a" * 40
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["grant"]["path"] = "candidate.json"
    config["grant"]["ledger_path"] = "ledger.jsonl"
    candidate = tmp_path / "candidate.json"
    grant_id = f"s4_8_corrective_03_{source_commit}"
    candidate.write_text(
        s4_8.pretty_json(
            {"grant_id": grant_id, "grant_sha256": "b" * 64}
        ),
        encoding="utf-8",
    )
    payload: dict[str, object] = {}
    evaluation = s4_8._evaluation_placeholder("not_evaluated")
    authorization = {
        "schema": s4_8.AUTHORIZATION_RECORD_SCHEMA,
        "authorization_id": "synthetic",
        "source_commit": source_commit,
        "grant_id": grant_id,
        "grant_path": config["grant"]["path"],
        "grant_sha256": "b" * 64,
        "ledger_path": config["grant"]["ledger_path"],
        "irreversible_scientific_action_acknowledged": True,
    }
    context: dict[str, object] = {
        "schema": "ias.s4_8.post_consumption_recovery_context.v1",
        "source_commit": source_commit,
        "authorization_record": authorization,
        "grant": {
            "path": config["grant"]["path"],
            "file_sha256": s4_8.sha256_file(candidate),
            "grant_sha256": "b" * 64,
        },
        "observation_inventory": [{"planned_take_id": "synthetic"}],
        "payload": payload,
        "payload_sha256": s4_8.canonical_sha256(payload),
        "evaluation_state": "not_evaluated",
        "evaluation": evaluation,
        "evaluation_sha256": s4_8.canonical_sha256(evaluation),
        "runtime_provenance": {"python": "synthetic"},
    }
    context["context_sha256"] = s4_8.canonical_sha256(context)
    s4_8._validate_recovery_context_for_consumption(
        context,
        config=config,
        grant={"grant_id": grant_id, "grant_sha256": "b" * 64},
        grant_path=candidate,
        source_commit=source_commit,
    )
    context["runtime_provenance"] = {"python": "tampered"}
    with pytest.raises(s4_8.S48Error, match="recovery context"):
        s4_8._validate_recovery_context_for_consumption(
            context,
            config=config,
            grant={"grant_id": grant_id, "grant_sha256": "b" * 64},
            grant_path=candidate,
            source_commit=source_commit,
        )


def test_downgrade_refuses_unauthenticated_provisional_archive(
    tmp_path: Path,
) -> None:
    config = copy.deepcopy(s4_8.load_contract(ROOT))
    config["evidence"]["derived_input_path"] = "state/derived.json"
    config["evidence"]["run_journal_path"] = "state/journal.jsonl"
    config["evidence"]["output_path"] = "output/S4.8"
    archive = tmp_path / "state/provisional_evidence.v1"
    archive.mkdir(parents=True)
    (archive / "SHA256SUMS").write_text(
        "tampered provisional evidence\n",
        encoding="utf-8",
    )
    intent = {
        "event": "first_run_downgrade_intent",
        "event_time_utc": "2030-01-01T00:00:00Z",
        "source_commit": "a" * 40,
        "run_failure": {"stage": "synthetic"},
        "provisional_path": config["evidence"]["output_path"],
        "provisional_manifest_sha256": "f" * 64,
        "provisional_evidence_path": ("state/provisional_evidence.v1"),
        "output_path": config["evidence"]["output_path"],
        "staging_path": ("output/.S4.8.first-run-finalization.v1"),
    }
    with pytest.raises(s4_8.S48Error, match="unique provisional"):
        s4_8._continue_failure_downgrade(
            tmp_path,
            config=config,
            derived={},
            source_commit="a" * 40,
            intent=intent,
        )
    assert not (tmp_path / config["evidence"]["output_path"]).exists()
