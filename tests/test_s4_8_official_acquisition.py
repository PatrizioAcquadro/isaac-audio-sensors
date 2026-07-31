from __future__ import annotations

import copy
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_8 import load_json
from isaac_audio_sensors.acquisition.s4_8_official_acquisition import (
    S48OfficialAcquisitionError,
    append_attempt_record,
    build_official_attempt_record,
    build_official_design,
    build_partition_manifest,
    build_session_manifest,
    build_take_authorization,
    next_attempt,
    validate_session_manifest,
    validate_take_authorization,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = ROOT / "configs/s4_8_recovery_amendment_02_preholdout_manifest.v2.json"


def _design() -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = load_json(DESIGN_PATH)
    return manifest, build_official_design(
        manifest,
        physical_contract=manifest["physical_contract"],
    )


def _session() -> dict[str, object]:
    manifest, design = _design()
    partition = build_partition_manifest(
        holdout_id="s4_8_recovery_amendment_02_unseen_holdout",
        observation_root=(
            "dataset/S4.4/amendments/s4_4_data_expansion_amendment_04/attempts"
        ),
        consumed_observation_roots=[
            "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/attempts"
        ],
        design_manifest_sha256="a" * 64,
        design=design,
    )
    return build_session_manifest(
        code_head="1" * 40,
        source_archive_sha256="b" * 64,
        source_package_hashes={"controller.py": "c" * 64},
        environment={"identity": "test"},
        reference_wav_sha256="d" * 64,
        gate_configuration_sha256="e" * 64,
        detector_configuration_sha256="f" * 64,
        controller={"identity": "controller", "version": "1", "sha256": "0" * 64},
        protocol={"identity": "recovery-02", "sha256": "2" * 64},
        devices={
            "respeaker": {"serial": "114993701261100454"},
            "playback": {"model": "MacBookPro18,1"},
            "zed": {"serial": "39011785"},
        },
        channel_map=[
            "Conference",
            "ASR",
            "raw microphone 0",
            "raw microphone 1",
            "raw microphone 2",
            "raw microphone 3",
        ],
        design=design,
        operational_locations={
            "campaign_root": "/tmp/freeze",
            "observation_root": "/tmp/attempts",
            "attempt_ledger_path": "/tmp/ledger.jsonl",
            "pi_capture_root": "S4.8/recovery",
        },
        design_manifest_sha256="a" * 64,
        partition_manifest_sha256=partition["partition_manifest_sha256"],
        preflight_report_sha256="3" * 64,
    )


def _attempt(
    session: dict[str, object],
    authorization: dict[str, object],
    take: dict[str, object],
    attempt_number: int,
    decision: str,
    *,
    start_state: tuple[bool, bool, bool] = (True, False, False),
) -> dict[str, object]:
    return build_official_attempt_record(
        session_manifest_sha256=session["manifest_sha256"],
        partition_manifest_sha256=session["partition_manifest_sha256"],
        precollection_seal_sha256="4" * 64,
        source_commit=session["code_head"],
        take=take,
        attempt_number=attempt_number,
        authorization=authorization,
        decision=decision,
        technical_report_sha256="5" * 64,
        technical_candidate_seal_sha256=(
            "6" * 64 if decision == "PASS" else None
        ),
        recorder_started=start_state[0],
        playback_started=start_state[1],
        zed_recording_started=start_state[2],
        controller_failure=(
            None if decision == "PASS" else {"error_type": "test_failure"}
        ),
    )


def test_official_design_preserves_all_identities_and_mode_setup() -> None:
    manifest, design = _design()

    assert [take["planned_take_id"] for take in design] == [
        take["planned_take_id"] for take in manifest["take_order"]
    ]
    assert len(design) == 37
    assert design[0]["planned_take_id"] == (
        "s48r02_preholdout_001_silence_beginning"
    )
    assert design[0]["physical_setup"]["mac"]["playback"] == "off"
    assert design[0]["physical_setup"]["mac"]["position_m_f_project"] is None
    assert design[1]["physical_setup"]["mac"]["position_m_f_project"] == [
        0.8,
        0.0,
        -0.135,
    ]
    assert design[1]["physical_setup"]["mac"]["playback"] == "reference_signal"
    assert design[-1]["acquisition_mode"] == "impact_av"
    assert design[-1]["zed_required"] is True
    assert design[-1]["physical_setup"]["mac"]["playback"] == "off"


def test_official_design_rejects_reordered_identity() -> None:
    manifest = load_json(DESIGN_PATH)
    altered = copy.deepcopy(manifest)
    altered["take_order"][0], altered["take_order"][1] = (
        altered["take_order"][1],
        altered["take_order"][0],
    )

    with pytest.raises(S48OfficialAcquisitionError, match="reordered"):
        build_official_design(
            altered,
            physical_contract=altered["physical_contract"],
        )


def test_partition_rejects_overlap() -> None:
    _, design = _design()
    with pytest.raises(S48OfficialAcquisitionError, match="not disjoint"):
        build_partition_manifest(
            holdout_id="holdout",
            observation_root="dataset/shared/attempts",
            consumed_observation_roots=["dataset/shared"],
            design_manifest_sha256="a" * 64,
            design=design,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("code_head", "9" * 40),
        ("preflight_report_sha256", "9" * 64),
        ("devices", {"tampered": True}),
    ],
)
def test_session_rejects_source_preflight_or_hardware_tampering(
    field: str,
    value: object,
) -> None:
    session = _session()
    session[field] = value

    with pytest.raises(S48OfficialAcquisitionError):
        validate_session_manifest(
            session,
            expected_manifest_sha256=session["manifest_sha256"],
        )


def test_one_shot_authorization_rejects_wrong_target_stale_and_reuse() -> None:
    session = _session()
    ledger: list[dict[str, object]] = []
    take, attempt_number = next_attempt(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )
    with pytest.raises(S48OfficialAcquisitionError):
        build_take_authorization(
            session_manifest=session,
            precollection_seal_sha256="4" * 64,
            ledger=ledger,
            planned_take_id=session["design"][1]["planned_take_id"],
            attempt_number=attempt_number,
            source_revision=session["code_head"],
            authorization_id="wrong-take",
            user_confirmation="go",
        )
    authorization = build_take_authorization(
        session_manifest=session,
        precollection_seal_sha256="4" * 64,
        ledger=ledger,
        planned_take_id=take["planned_take_id"],
        attempt_number=attempt_number,
        source_revision=session["code_head"],
        authorization_id="take-001-attempt-01",
        user_confirmation="go",
    )
    retry = _attempt(
        session, authorization, take, attempt_number, "RETRY_REQUIRED"
    )
    append_attempt_record(
        ledger, session_manifest=session, official_attempt=retry
    )

    with pytest.raises(S48OfficialAcquisitionError, match="stale"):
        validate_take_authorization(
            authorization,
            session_manifest=session,
            precollection_seal_sha256="4" * 64,
            ledger=ledger,
            take=take,
            attempt_number=attempt_number,
        )


def test_retry_chain_is_retained_and_pass_advances_exactly_one() -> None:
    session = _session()
    ledger: list[dict[str, object]] = []
    first, attempt_one = next_attempt(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )
    auth_one = build_take_authorization(
        session_manifest=session,
        precollection_seal_sha256="4" * 64,
        ledger=ledger,
        planned_take_id=first["planned_take_id"],
        attempt_number=attempt_one,
        source_revision=session["code_head"],
        authorization_id="first-1",
        user_confirmation="go",
    )
    append_attempt_record(
        ledger,
        session_manifest=session,
        official_attempt=_attempt(
            session, auth_one, first, attempt_one, "RETRY_REQUIRED"
        ),
    )
    same_take, attempt_two = next_attempt(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )
    assert same_take["planned_take_id"] == first["planned_take_id"]
    assert attempt_two == 2
    auth_two = build_take_authorization(
        session_manifest=session,
        precollection_seal_sha256="4" * 64,
        ledger=ledger,
        planned_take_id=first["planned_take_id"],
        attempt_number=attempt_two,
        source_revision=session["code_head"],
        authorization_id="first-2",
        user_confirmation="go",
    )
    append_attempt_record(
        ledger,
        session_manifest=session,
        official_attempt=_attempt(
            session, auth_two, first, attempt_two, "PASS"
        ),
    )
    second, second_attempt = next_attempt(
        ledger,
        session_manifest=session,
        expected_session_manifest_sha256=session["manifest_sha256"],
    )

    assert len(ledger) == 2
    assert [record["attempt_number"] for record in ledger] == [1, 2]
    assert [record["decision"] for record in ledger] == [
        "RETRY_REQUIRED",
        "PASS",
    ]
    assert second["sequence_index"] == 2
    assert second_attempt == 1
    assert auth_one["authorization_sha256"] != auth_two["authorization_sha256"]
    assert all(record["record_sha256"] == canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    ) for record in ledger)


def test_prestart_controller_failure_is_retained_without_continuation() -> None:
    session = _session()
    take = session["design"][0]
    authorization = build_take_authorization(
        session_manifest=session,
        precollection_seal_sha256="4" * 64,
        ledger=[],
        planned_take_id=take["planned_take_id"],
        attempt_number=1,
        source_revision=session["code_head"],
        authorization_id="prestart-failure",
        user_confirmation="go",
    )
    record = _attempt(
        session,
        authorization,
        take,
        1,
        "RETRY_REQUIRED",
        start_state=(False, False, False),
    )

    assert record["decision"] == "RETRY_REQUIRED"
    assert record["start_state"] == {
        "recorder_started": False,
        "playback_started": False,
        "zed_recording_started": False,
    }
    assert record["retained"] is True
    assert record["automatic_retry"] is False
    assert record["automatic_continuation"] is False
