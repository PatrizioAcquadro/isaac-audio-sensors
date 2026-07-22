from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_4_amendment import (
    PREFLIGHT_SCHEMA,
    S44AmendmentError,
    append_ledger_event,
    authorize_and_record_access,
    build_aggregate_index,
    build_attempt_contract,
    build_holdout_seal,
    build_manifests,
    build_precollection_seal,
    canonical_sha256,
    combined_partition_manifest,
    hash_only_holdout_integrity,
    initialize_access_ledger,
    require_evidence_access,
    sanitize_holdout_technical_qa,
    sha256_file,
    validate_attempt_census,
    validate_configuration,
    validate_historical_freeze,
    validate_holdout_technical_qa,
    validate_ledger,
    validate_manifests,
    validate_precollection_seal,
    validate_session_preflight,
)
from scripts.build_s4_4_amendment import build
from scripts.execute_s4_4_amendment_attempt import _argument
from scripts.run_s4_4_amendment_take import _capture_plan
from scripts.validate_s4_4_amendment import validate

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/s4_4_data_expansion_amendment_01.v1.json"


@pytest.fixture
def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def manifests(config: dict) -> dict:
    return build_manifests(config)


def _takes(manifests: dict) -> list[dict]:
    return [take for manifest in manifests.values() for take in manifest["takes"]]


def _preflight(config: dict, session_id: str, session_date: str) -> dict:
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "status": "passed",
        "session_id": session_id,
        "session_date_local": session_date,
        "checks": {key: "passed" for key in config["preflight_required_checks"]},
        "identity_contract_sha256": canonical_sha256(config["identities"]),
        "observations": {"exact_values_recorded": True},
    }
    return {**payload, "preflight_sha256": canonical_sha256(payload)}


def _qa_input(planned_id: str, **extra: object) -> dict:
    return {
        "planned_take_id": planned_id,
        "attempt_id": planned_id + "__attempt_01",
        "identity_pass": True,
        "assigned_metadata_pass": True,
        "duration_pass": True,
        "channel_order_pass": True,
        "channel_health_pass": True,
        "clipping_pass": True,
        "timestamps_pass": True,
        "reference_presence_pass": True,
        "integrity_pass": True,
        "privacy_pass": True,
        "full_svo2_replay_pass": True,
        **extra,
    }


def test_configuration_preserves_original_s4_4_and_scope(config: dict) -> None:
    validate_configuration(config, ROOT)
    validate_historical_freeze(config, ROOT)
    assert config["scope"]["planned_total_takes"] == 149
    assert config["scope"]["later_phases_started"] is False


def test_historical_freeze_hash_change_fails_closed(config: dict) -> None:
    changed = copy.deepcopy(config)
    changed["historical_freeze"]["records"][0]["sha256"] = "0" * 64
    with pytest.raises(S44AmendmentError, match="immutable historical"):
        validate_historical_freeze(changed, ROOT)


def test_exact_session_partition_and_category_counts(manifests: dict) -> None:
    validate_manifests(manifests, json.loads(CONFIG_PATH.read_text()))
    assert {key: len(value["takes"]) for key, value in manifests.items()} == {
        "fit_a": 51,
        "fit_b": 51,
        "prospective_holdout": 47,
    }
    counts = Counter(
        (take["session_id"], take["category"]) for take in _takes(manifests)
    )
    assert counts[("fit_a", "controlled")] == 32
    assert counts[("fit_b", "confidence")] == 12
    assert counts[("prospective_holdout", "controlled")] == 24
    assert counts[("prospective_holdout", "confidence")] == 16
    assert Counter(take["partition"] for take in _takes(manifests)) == {
        "fit": 102,
        "prospective_holdout": 47,
    }


def test_fit_orders_silence_sweeps_confidence_and_av(manifests: dict) -> None:
    fit_a = manifests["fit_a"]["takes"]
    fit_b = manifests["fit_b"]["takes"]
    assert [
        take["sequence_index"] for take in fit_a if take["category"] == "silence"
    ] == [1, 26, 47]
    assert [
        take["sequence_index"] for take in fit_b if take["category"] == "silence"
    ] == [1, 26, 47]
    assert all(take["category"] == "audio_video" for take in fit_a[-4:] + fit_b[-4:])
    controlled_a = [take for take in fit_a if take["category"] == "controlled"]
    controlled_b = [take for take in fit_b if take["category"] == "controlled"]
    assert [
        (take["target_radius_m"], take["sweep_direction"])
        for take in controlled_a[::16]
    ] == [(0.6, "clockwise"), (1.0, "counterclockwise")]
    assert [
        (take["target_radius_m"], take["sweep_direction"])
        for take in controlled_b[::16]
    ] == [(1.0, "clockwise"), (0.6, "counterclockwise")]
    gains_a = [
        take["playback_gain"] for take in fit_a if take["category"] == "confidence"
    ]
    gains_b = [
        take["playback_gain"] for take in fit_b if take["category"] == "confidence"
    ]
    assert gains_a == [1.0] * 4 + [0.5] * 4 + [0.25] * 4
    assert gains_b == [0.25] * 4 + [0.5] * 4 + [1.0] * 4


def test_holdout_alternating_sweeps_and_counterbalanced_gains(manifests: dict) -> None:
    takes = manifests["prospective_holdout"]["takes"]
    controlled = [take for take in takes if take["category"] == "controlled"]
    assert [controlled[index]["sweep_direction"] for index in (0, 8, 16)] == [
        "clockwise",
        "counterclockwise",
        "clockwise",
    ]
    confidence = [take for take in takes if take["category"] == "confidence"]
    by_condition: dict[tuple[float, int], list[float]] = {}
    for take in confidence:
        by_condition.setdefault(
            (take["target_bearing_deg_f_project"], take["repetition"]), []
        ).append(take["playback_gain"])
    assert set(map(tuple, by_condition.values())) == {(0.75, 0.35), (0.35, 0.75)}
    for bearing in (45.0, 135.0, 225.0, 315.0):
        assert by_condition[(bearing, 1)] == list(reversed(by_condition[(bearing, 2)]))
    assert [
        take["sequence_index"] for take in takes if take["category"] == "silence"
    ] == [1, 26, 43]
    assert all(take["category"] == "audio_video" for take in takes[-4:])


def test_exact_positions_durations_repositioning_and_impact_identity(
    manifests: dict,
) -> None:
    takes = _takes(manifests)
    assert {take["duration_s"] for take in takes if take["category"] == "silence"} == {
        15
    }
    assert {take["duration_s"] for take in takes if take["category"] != "silence"} == {
        20
    }
    for take in takes:
        if take["category"] in {"controlled", "confidence"}:
            assert take["target_position_m_f_project"][2] == -0.135
            assert take["complete_removal_and_fresh_reposition_required"] is True
            assert (
                take["source_identity"]
                == "27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468"
            )
        if take["category"] == "audio_video":
            assert take["source_identity"] == "plain_paper_roll__blue_wastebasket"
            assert take["impact_target_elapsed_times_s"] == [5.0, 10.0, 15.0]


def test_every_position_is_inside_exact_room_bounds(
    manifests: dict, config: dict
) -> None:
    for take in _takes(manifests):
        position = take["target_position_m_f_project"]
        if position is None:
            continue
        for value, axis in zip(position, ("x", "y", "z"), strict=True):
            low, high = config["room_bounds_m"][axis]
            assert low <= value <= high


def test_out_of_bounds_position_is_rejected(manifests: dict, config: dict) -> None:
    changed = copy.deepcopy(manifests)
    take = next(
        take for take in changed["fit_a"]["takes"] if take["category"] == "controlled"
    )
    take["target_position_m_f_project"][0] = 2.5
    take["take_definition_sha256"] = canonical_sha256(
        {key: value for key, value in take.items() if key != "take_definition_sha256"}
    )
    payload = {
        key: value
        for key, value in changed["fit_a"].items()
        if key != "manifest_sha256"
    }
    changed["fit_a"]["manifest_sha256"] = canonical_sha256(payload)
    with pytest.raises(S44AmendmentError, match="outside frozen room bounds"):
        validate_manifests(changed, config)


def test_deterministic_ids_serialization_and_hashes(config: dict) -> None:
    first = build_manifests(config)
    second = build_manifests(config)
    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    ids = [take["planned_take_id"] for take in _takes(first)]
    assert len(ids) == len(set(ids)) == 149


def test_predecessor_successor_and_expected_attempt_paths(manifests: dict) -> None:
    for manifest in manifests.values():
        takes = manifest["takes"]
        for index, take in enumerate(takes):
            assert take["predecessor_planned_take_id"] == (
                None if index == 0 else takes[index - 1]["planned_take_id"]
            )
            assert take["successor_planned_take_id"] == (
                None if index == len(takes) - 1 else takes[index + 1]["planned_take_id"]
            )
            assert take["expected_artifact_paths"]["attempt_01_root"].endswith(
                take["planned_take_id"] + "__attempt_01"
            )
            assert take["expected_artifact_paths"][
                "replacement_attempt_02_root"
            ].endswith(take["planned_take_id"] + "__attempt_02")


def test_no_group_crosses_fit_and_holdout(manifests: dict) -> None:
    partitions: dict[str, set[str]] = {}
    for take in _takes(manifests):
        partitions.setdefault(take["group_id"], set()).add(take["partition"])
    assert all(len(values) == 1 for values in partitions.values())


def test_aggregate_keeps_legacy_and_prospective_claims_separate(
    config: dict, manifests: dict
) -> None:
    fit = combined_partition_manifest(manifests, "fit")
    holdout = combined_partition_manifest(manifests, "prospective_holdout")
    aggregate = build_aggregate_index(
        config,
        fit_manifest_sha256=fit["partition_manifest_sha256"],
        holdout_manifest_sha256=holdout["partition_manifest_sha256"],
    )
    assert aggregate["records"][0]["role"] == "historically_analyzed_legacy_evidence"
    assert aggregate["records"][0]["historically_unopened_claim"] is False
    assert (
        aggregate["records"][1]["role"]
        == "primary_unopened_prospective_holdout_for_future_evaluation"
    )
    assert aggregate["assignments_merged"] is False
    assert aggregate["access_histories_merged"] is False
    assert aggregate["blindness_claims_merged"] is False


def test_uncommitted_precollection_seal_rejects_capture(config: dict) -> None:
    seal = build_precollection_seal(config, bindings={"manifest": "1" * 64})
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=False)
    with pytest.raises(S44AmendmentError, match="capture denied"):
        validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)


def test_session_preflight_requires_all_checks_and_distinct_dates(config: dict) -> None:
    first = _preflight(config, "fit_a", "2026-07-23")
    validate_session_preflight(first, config, other_dates=[])
    duplicate = _preflight(config, "fit_b", "2026-07-23")
    with pytest.raises(S44AmendmentError, match="differ"):
        validate_session_preflight(duplicate, config, other_dates=["2026-07-23"])
    missing = _preflight(config, "fit_b", "2026-07-24")
    missing["checks"].pop(next(iter(missing["checks"])))
    payload = {
        key: value for key, value in missing.items() if key != "preflight_sha256"
    }
    missing["preflight_sha256"] = canonical_sha256(payload)
    with pytest.raises(S44AmendmentError, match="check set"):
        validate_session_preflight(missing, config, other_dates=["2026-07-23"])


def test_attempt_ids_and_one_replacement_limit(manifests: dict) -> None:
    take = manifests["fit_a"]["takes"][0]
    first = build_attempt_contract(
        take, attempt_number=1, precollection_seal_sha256="1" * 64
    )
    second = build_attempt_contract(
        take, attempt_number=2, precollection_seal_sha256="1" * 64
    )
    assert first["attempt_id"].endswith("__attempt_01")
    assert second["replacement"] is True
    with pytest.raises(S44AmendmentError, match="at most one"):
        build_attempt_contract(
            take, attempt_number=3, precollection_seal_sha256="1" * 64
        )


def test_second_technical_failure_declares_no_go(manifests: dict) -> None:
    take = manifests["fit_a"]["takes"][0]
    attempts = []
    for number in (1, 2):
        record = build_attempt_contract(
            take, attempt_number=number, precollection_seal_sha256="1" * 64
        )
        record["outcome"] = "invalid"
        record["technical_failure_reason"] = "frozen_technical_quality_failure"
        attempts.append(record)
    census = validate_attempt_census(manifests, attempts)
    assert census["status"] == "no_go"
    assert census["attempts"] == 2
    assert census["failures"] == 2
    assert census["replacements"] == 1
    assert census["all_attempts_retained"] is True


def test_all_149_valid_attempts_complete_census(manifests: dict) -> None:
    attempts = []
    for take in _takes(manifests):
        record = build_attempt_contract(
            take, attempt_number=1, precollection_seal_sha256="1" * 64
        )
        record["outcome"] = "valid"
        attempts.append(record)
    census = validate_attempt_census(manifests, attempts)
    assert census["status"] == "passed"
    assert census["planned_takes"] == census["attempts"] == census["valid_takes"] == 149
    assert census["failures"] == census["replacements"] == 0


def test_replacement_cannot_change_partition_or_condition(manifests: dict) -> None:
    take = manifests["fit_a"]["takes"][0]
    record = build_attempt_contract(
        take, attempt_number=1, precollection_seal_sha256="1" * 64
    )
    record["outcome"] = "invalid"
    replacement = build_attempt_contract(
        take, attempt_number=2, precollection_seal_sha256="1" * 64
    )
    replacement["outcome"] = "valid"
    replacement["partition"] = "prospective_holdout"
    with pytest.raises(S44AmendmentError, match="partition changed"):
        validate_attempt_census(manifests, [record, replacement])


def test_holdout_qa_suppresses_scientific_outputs(manifests: dict) -> None:
    planned_id = manifests["prospective_holdout"]["takes"][0]["planned_take_id"]
    report = _qa_input(
        planned_id,
        bearing_error_deg=12.5,
        confidence=0.9,
        gain_estimate=1.2,
        av_offset_ms=3.0,
    )
    output = sanitize_holdout_technical_qa(report, known_holdout_take_ids={planned_id})
    validate_holdout_technical_qa(output)
    assert output["scientific_outputs_exposed"] is False
    assert output["suppressed_field_count"] == 4
    assert "bearing_error_deg" not in output
    assert "confidence" not in output
    assert "gain_estimate" not in output
    assert "av_offset_ms" not in output


def test_persisted_holdout_qa_rejects_extra_field(manifests: dict) -> None:
    planned_id = manifests["prospective_holdout"]["takes"][0]["planned_take_id"]
    output = sanitize_holdout_technical_qa(
        _qa_input(planned_id), known_holdout_take_ids={planned_id}
    )
    output["bearing"] = 0.0
    with pytest.raises(S44AmendmentError, match="not allowlisted"):
        validate_holdout_technical_qa(output)


def test_s4_5_access_is_fit_only_and_unknowns_fail_closed(manifests: dict) -> None:
    fit_ids = set(combined_partition_manifest(manifests, "fit")["planned_take_ids"])
    holdout_ids = set(
        combined_partition_manifest(manifests, "prospective_holdout")[
            "planned_take_ids"
        ]
    )
    fit_id = next(iter(fit_ids))
    holdout_id = next(iter(holdout_ids))
    assert (
        require_evidence_access(
            planned_take_id=fit_id,
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )["mode"]
        == "fit_only"
    )
    assert (
        require_evidence_access(
            planned_take_id=holdout_id,
            purpose="S4.4_amendment_technical_QA",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )["mode"]
        == "technical_QA_only"
    )
    with pytest.raises(S44AmendmentError, match="denied"):
        require_evidence_access(
            planned_take_id=holdout_id,
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )
    with pytest.raises(S44AmendmentError, match="unknown access purpose"):
        require_evidence_access(
            planned_take_id=fit_id,
            purpose="S4.8_evaluation",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )
    with pytest.raises(S44AmendmentError, match="unknown planned take"):
        require_evidence_access(
            planned_take_id="unknown",
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )


def test_holdout_seal_and_hash_only_integrity_return_no_science(
    tmp_path: Path, manifests: dict
) -> None:
    holdout = combined_partition_manifest(manifests, "prospective_holdout")
    ids = holdout["planned_take_ids"]
    qa = [
        sanitize_holdout_technical_qa(
            _qa_input(planned_id), known_holdout_take_ids=set(ids)
        )
        for planned_id in ids
    ]
    artifacts = []
    for index, planned_id in enumerate(ids):
        path = tmp_path / f"artifact_{index:02d}.bin"
        path.write_bytes(f"technical-{index}".encode())
        artifacts.append(
            {
                "planned_take_id": planned_id,
                "path": path.relative_to(tmp_path).as_posix(),
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "role": "retained_attempt_integrity",
            }
        )
    seal = build_holdout_seal(holdout, qa, artifacts)
    result = hash_only_holdout_integrity(seal, tmp_path)
    assert result["status"] == "passed"
    assert result["holdout_opened"] is False
    assert result["content_derived_values_returned"] is False
    assert result["media_returned"] is False
    assert result["scientific_outcomes_returned"] is False


def test_holdout_seal_requires_every_planned_cell_artifact(manifests: dict) -> None:
    holdout = combined_partition_manifest(manifests, "prospective_holdout")
    ids = holdout["planned_take_ids"]
    qa = [
        sanitize_holdout_technical_qa(_qa_input(value), known_holdout_take_ids=set(ids))
        for value in ids
    ]
    with pytest.raises(S44AmendmentError, match="at least one"):
        build_holdout_seal(holdout, qa, [])


def test_access_ledger_detects_tamper(tmp_path: Path) -> None:
    path = tmp_path / "access_ledger.jsonl"
    seal_sha = "a" * 64
    append_ledger_event(
        path,
        {
            "event": "access_attempt",
            "event_time_utc": "2026-07-22T00:00:00Z",
            "seal_sha256": seal_sha,
            "purpose": "S4.4_amendment_integrity_validation",
            "allowed": True,
            "mode": "hash_only",
        },
    )
    assert validate_ledger(path, expected_seal_sha256=seal_sha)["status"] == "passed"
    line = json.loads(path.read_text())
    line["allowed"] = False
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert validate_ledger(path, expected_seal_sha256=seal_sha)["status"] == "failed"


def test_allowed_and_denied_access_attempts_are_both_audited(
    tmp_path: Path, manifests: dict
) -> None:
    path = tmp_path / "access_ledger.jsonl"
    seal_sha = "b" * 64
    initialize_access_ledger(
        path, seal_sha256=seal_sha, event_time_utc="2026-07-22T00:00:00Z"
    )
    fit_ids = set(combined_partition_manifest(manifests, "fit")["planned_take_ids"])
    holdout_ids = set(
        combined_partition_manifest(manifests, "prospective_holdout")[
            "planned_take_ids"
        ]
    )
    authorize_and_record_access(
        planned_take_id=next(iter(fit_ids)),
        purpose="S4.5_fit",
        fit_ids=fit_ids,
        holdout_ids=holdout_ids,
        ledger_path=path,
        seal_sha256=seal_sha,
        event_time_utc="2026-07-22T00:01:00Z",
    )
    with pytest.raises(S44AmendmentError, match="denied"):
        authorize_and_record_access(
            planned_take_id=next(iter(holdout_ids)),
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
            ledger_path=path,
            seal_sha256=seal_sha,
            event_time_utc="2026-07-22T00:02:00Z",
        )
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["allowed"] for line in lines] == [True, True, False]
    assert validate_ledger(path, expected_seal_sha256=seal_sha)["status"] == "passed"


def test_builder_is_byte_identical_and_clean_checkout_validator_passes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_summary = build(output=first, config_path=CONFIG_PATH)
    second_summary = build(output=second, config_path=CONFIG_PATH)
    assert first_summary == second_summary
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    result = validate(
        first / "evidence_index.v1.json",
        repo_root=ROOT,
        require_tracked=False,
        require_committed=False,
        require_machine_local=False,
    )
    assert result["status"] == "passed", result["issues"]
    assert result["prospective_holdout_scientifically_opened"] is False


def test_schema_files_are_valid_json() -> None:
    for path in sorted((ROOT / "docs/schemas").glob("s4_4_amendment_*.schema.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["additionalProperties"] is False


def test_capture_plan_uses_attempt_scoped_executable_pi_command(
    config: dict, manifests: dict, tmp_path: Path
) -> None:
    take = manifests["fit_a"]["takes"][0]
    attempt_dir = tmp_path / "s44a01_fit_a_001_sil__attempt_02"
    plan = _capture_plan(take, config, attempt_dir)
    command = plan["commands"]["respeaker"]
    assert command[:5] == [
        "ssh",
        "elab-raspberrypi5",
        "/usr/bin/python3",
        "S4.2/bin/s4_2_pi_capture.py",
        "record",
    ]
    assert _argument(command, "--attempt").endswith(
        "/captures/s44a01_fit_a_001_sil__attempt_02"
    )
    assert _argument(command, "--minimum-free-bytes") == "1073741824"
    assert _argument(command, "--duration") == "15"
    assert _argument(command, "--device") == "hw:CARD=Array,DEV=0"
