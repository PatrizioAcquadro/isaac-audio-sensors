from __future__ import annotations

import hashlib
import json
import wave
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.acquisition.s4_8_engineering_campaign as campaign
from isaac_audio_sensors.acquisition.s4_8_engineering_campaign import (
    S48EngineeringCampaignError,
    append_attempt_ledger_record,
    append_nonreference_journal_event,
    build_reference_take_manifest,
    build_stratum_aware_campaign_manifest,
    create_nonreference_candidate_clearance,
    derive_stratum_aware_design,
    evaluate_nonreference_presealing_gate,
    run_supported_nonreference_acquisition,
    seal_nonreference_candidate,
    validate_attempt_ledger,
    validate_attempt_request,
    validate_campaign_manifest,
    validate_nonreference_process_journal,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    DEFAULT_PRESEALING_CONFIG_V2,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / (
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/manifests/sessions/"
    "prospective_holdout.json"
)


def _design() -> list[dict[str, object]]:
    return derive_stratum_aware_design(
        json.loads(TEMPLATE.read_text(encoding="utf-8"))
    )


def _manifest() -> dict[str, object]:
    return build_stratum_aware_campaign_manifest(
        code_head="4" * 40,
        source_archive_sha256="1" * 64,
        source_package_hashes={
            "controller.py": "2" * 64,
            "presealing_gate_v2.py": "3" * 64,
        },
        environment={
            "host": "workstation",
            "python": "3.12.3",
            "dependency_lock_sha256": "4" * 64,
        },
        reference_wav_sha256="5" * 64,
        gate_configuration_sha256=canonical_sha256(
            DEFAULT_PRESEALING_CONFIG_V2
        ),
        detector_configuration_sha256=canonical_sha256(
            DEFAULT_PRESEALING_CONFIG_V2["detector"]
        ),
        controller={
            "identity": "ias.s4_8.stratum_aware_engineering_controller",
            "version": "1.0",
            "sha256": "6" * 64,
        },
        protocol={
            "identity": "s4_8_physical_engineering_rehearsal_stratum_aware_v1",
            "sha256": "7" * 64,
        },
        devices={
            "respeaker": {
                "profile_id": "respeaker_usb_6ch_pcm16_v1",
                "serial": "114993701261100454",
                "sample_rate_hz": 16000,
                "channel_count": 6,
                "sample_format": "S16_LE",
            },
            "playback": {
                "model": "MacBookPro18,1",
                "volume_percent": 40,
            },
            "zed": {"model": "ZED 2i", "serial": "39011785"},
        },
        channel_map=DEFAULT_PRESEALING_CONFIG_V2["expected_channel_map"],
        design=_design(),
        retry_policy={
            "maximum_attempts_per_planned_take": 2,
            "replacement_requires_retained_retry_required": True,
            "sequence_advances_only_after_pass": True,
            "configuration_change_restarts_campaign": True,
        },
        operational_locations={
            "campaign_root": "/tmp/s4_8_physical_rehearsal",
            "pi_capture_root": "S4.8/engineering_rehearsal",
        },
        template_manifest_sha256=hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
    )


def _write_wav(path: Path, samples: np.ndarray, rate: int = 16_000) -> None:
    encoded = np.rint(
        np.clip(samples, -1.0, 32767.0 / 32768.0) * 32768.0
    ).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(encoded.tobytes())


def test_design_preserves_all_47_cells_and_maps_each_stratum() -> None:
    design = _design()

    assert len(design) == 47
    assert [take["sequence_index"] for take in design] == list(range(1, 48))
    assert {
        stratum: sum(take["stratum_id"] == stratum for take in design)
        for stratum in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
            "C_center_low_level",
            "D_silence",
            "E_impact_audio_video",
        }
    } == {
        "A_controlled_boundary_sweep": 24,
        "B_center_nominal_level": 8,
        "C_center_low_level": 8,
        "D_silence": 3,
        "E_impact_audio_video": 4,
    }
    assert {
        take["acquisition_mode"]
        for take in design
        if take["stratum_id"].startswith("A_")
    } == {"reference"}
    assert {
        take["acquisition_mode"]
        for take in design
        if take["stratum_id"].startswith("B_")
    } == {"reference"}
    assert {
        take["acquisition_mode"]
        for take in design
        if take["stratum_id"].startswith("C_")
    } == {"reference"}
    assert {
        take["acquisition_mode"] for take in design if take["stratum_id"] == "D_silence"
    } == {"silence"}
    assert {
        take["acquisition_mode"]
        for take in design
        if take["stratum_id"] == "E_impact_audio_video"
    } == {"impact_av"}
    assert all(
        take["engineering_take_id"].startswith("s48eng_rehearsal_")
        and "prospective_holdout" not in take["engineering_take_id"]
        for take in design
    )


def test_campaign_manifest_binds_reproducibility_design_retry_and_locations() -> None:
    manifest = _manifest()

    validate_campaign_manifest(
        manifest,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
    )
    assert manifest["planned_take_count"] == 47
    assert manifest["reference_wav_sha256"] == "5" * 64
    assert manifest["source_package_hashes"]["controller.py"] == "2" * 64
    assert manifest["retry_policy"]["sequence_advances_only_after_pass"] is True
    assert manifest["authority"] == {
        "creates_grant": False,
        "consumes_grant": False,
        "official_state_machine": False,
        "publishes_official_evidence": False,
    }
    altered = deepcopy(manifest)
    altered["design"][0]["acquisition_mode"] = "reference"
    altered["design"][0]["duration_s"] = 20
    with pytest.raises(S48EngineeringCampaignError):
        validate_campaign_manifest(
            altered,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
        )


def test_reference_take_manifest_is_anchored_to_campaign_and_exact_cell() -> None:
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "reference"
    )

    take_manifest = build_reference_take_manifest(
        campaign_manifest=manifest,
        take=take,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
    )

    assert manifest["manifest_sha256"] in take_manifest["protocol_id"]
    assert take["engineering_take_definition_sha256"] in take_manifest["protocol_id"]
    assert take_manifest["reference_wav_sha256"] == manifest["reference_wav_sha256"]
    assert take_manifest["code_head"] == manifest["code_head"]


def test_silence_gate_uses_capture_integrity_without_reference_or_outcomes(
    tmp_path: Path,
) -> None:
    capture = np.zeros((15 * 16_000, 6), dtype=np.float64)
    capture[:, 2:6] = np.random.default_rng(801).normal(
        0.0, 0.0005, size=(15 * 16_000, 4)
    )
    capture_path = tmp_path / "silence.wav"
    _write_wav(capture_path, capture)
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "silence"
    )

    report = evaluate_nonreference_presealing_gate(
        capture_path=capture_path,
        take=take,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        process_journal_head_sha256="8" * 64,
        repo_root=ROOT,
        zed_artifacts=None,
        dry_run=True,
    )

    assert report["decision"] == "PASS"
    assert report["mode"] == "silence"
    assert report["input_provenance"]["reference_sha256"] is None
    assert report["input_provenance"]["outcome_fields_read"] == []
    assert report["authority"]["official_state_machine"] is False


def test_impact_gate_requires_frozen_audio_events_and_complete_zed_evidence(
    tmp_path: Path,
) -> None:
    capture = np.zeros((20 * 16_000, 6), dtype=np.float64)
    capture[:, 2:6] = np.random.default_rng(802).normal(
        0.0, 0.0005, size=(20 * 16_000, 4)
    )
    for elapsed_s in (5.0, 10.0, 15.0):
        start = round(elapsed_s * 16_000)
        impulse = np.random.default_rng(round(elapsed_s)).normal(
            0.0, 0.15, size=800
        ) * np.hanning(800)
        for channel, (delay, gain) in enumerate(
            ((0, 1.0), (7, 0.92), (13, 0.84), (19, 0.78))
        ):
            capture[
                start + delay : start + delay + impulse.size,
                channel + 2,
            ] += gain * impulse
    capture_path = tmp_path / "impact.wav"
    _write_wav(capture_path, capture)
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "impact_av"
    )
    zed = {
        "producer_summary": {
            "status": "complete",
            "serial": "39011785",
            "resolution": "HD720",
            "fps": 30,
            "depth_mode": "PERFORMANCE",
            "strictly_increasing_device_timestamps": True,
        },
        "replay_report": {"status": "passed", "full_replay": True},
        "svo2_sha256": "9" * 64,
        "frames_sha256": "a" * 64,
    }

    report = evaluate_nonreference_presealing_gate(
        capture_path=capture_path,
        take=take,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        process_journal_head_sha256="8" * 64,
        repo_root=ROOT,
        zed_artifacts=zed,
        dry_run=True,
    )

    assert report["decision"] == "PASS"
    assert report["impact_integrity"]["selected_event_count"] == 3
    incomplete = deepcopy(zed)
    incomplete["replay_report"]["full_replay"] = False
    retry = evaluate_nonreference_presealing_gate(
        capture_path=capture_path,
        take=take,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        process_journal_head_sha256="8" * 64,
        repo_root=ROOT,
        zed_artifacts=incomplete,
        dry_run=True,
    )
    assert retry["decision"] == "RETRY_REQUIRED"
    assert "zed_full_replay_failed" in {
        reason["code"] for reason in retry["reasons"]
    }


def test_attempt_ledger_is_hash_chained_and_never_discards_retry() -> None:
    manifest = _manifest()
    ledger: list[dict[str, object]] = []
    take = manifest["design"][0]
    first = append_attempt_ledger_record(
        ledger,
        campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        planned_take=take,
        attempt_number=1,
        decision="RETRY_REQUIRED",
        report_sha256="b" * 64,
        candidate_seal_sha256=None,
    )
    second = append_attempt_ledger_record(
        ledger,
        campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        planned_take=take,
        attempt_number=2,
        decision="PASS",
        report_sha256="c" * 64,
        candidate_seal_sha256="d" * 64,
    )

    validate_attempt_ledger(
        ledger,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
    )
    assert first["previous_record_sha256"] == manifest["manifest_sha256"]
    assert second["previous_record_sha256"] == first["record_sha256"]
    assert [record["decision"] for record in ledger] == [
        "RETRY_REQUIRED",
        "PASS",
    ]
    missing_retry = [second]
    with pytest.raises(S48EngineeringCampaignError):
        validate_attempt_ledger(
            missing_retry,
            campaign_manifest=manifest,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        )


def test_attempt_request_is_authorized_before_any_capture_starts() -> None:
    manifest = _manifest()
    ledger: list[dict[str, object]] = []
    first_take = manifest["design"][0]
    second_take = manifest["design"][1]

    validate_attempt_request(
        ledger,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        take=first_take,
        attempt_number=1,
    )
    with pytest.raises(S48EngineeringCampaignError):
        validate_attempt_request(
            ledger,
            campaign_manifest=manifest,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
            take=second_take,
            attempt_number=1,
        )
    append_attempt_ledger_record(
        ledger,
        campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        planned_take=first_take,
        attempt_number=1,
        decision="RETRY_REQUIRED",
        report_sha256="b" * 64,
        candidate_seal_sha256=None,
    )
    validate_attempt_request(
        ledger,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        take=first_take,
        attempt_number=2,
    )
    with pytest.raises(S48EngineeringCampaignError):
        validate_attempt_request(
            ledger,
            campaign_manifest=manifest,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
            take=first_take,
            attempt_number=1,
        )


class _FakeNonreferenceBackend:
    def __init__(self, capture_bytes: bytes) -> None:
        self.now = 1_000_000_000
        self.capture_bytes = capture_bytes
        self.operations: list[str] = []

    def monotonic_ns(self) -> int:
        return self.now

    def start_recorder(
        self, capture_path: Path, *, duration_s: float
    ) -> dict[str, object]:
        self.operations.append("recorder_start")
        self.capture_path = capture_path
        return {"pid": 301, "process_identity": "fake_recorder"}

    def wait_recorder_ready(self, recorder: object) -> bool:
        self.operations.append("recorder_ready")
        return True

    def begin_silence_interval(self) -> dict[str, object]:
        self.operations.append("silence_begin")
        return {"stimulus": "ambient_silence"}

    def complete_silence_interval(self) -> dict[str, object]:
        self.operations.append("silence_complete")
        return {"stimulus": "ambient_silence"}

    def start_zed(
        self, artifact_root: Path, *, duration_s: float
    ) -> dict[str, object]:
        self.operations.append("zed_start")
        return {"pid": 302, "process_identity": "fake_zed"}

    def wait_zed_ready(self, zed: object) -> bool:
        self.operations.append("zed_ready")
        return True

    def record_impact_cue(self, cue_index: int) -> dict[str, object]:
        self.operations.append(f"impact_cue_{cue_index}")
        return {"cue_index": cue_index}

    def wait_until(self, monotonic_ns: int) -> None:
        self.operations.append("continuous_capture")
        self.now = monotonic_ns

    def stop_zed(self, zed: object) -> dict[str, object]:
        self.operations.append("zed_stop")
        return {
            "pid": 302,
            "exit_status": 0,
            "artifacts": {
                "producer_summary": {"status": "complete"},
                "replay_report": {"status": "passed"},
                "svo2_sha256": "9" * 64,
                "frames_sha256": "a" * 64,
            },
        }

    def stop_recorder(self, recorder: object) -> dict[str, object]:
        self.operations.append("recorder_stop")
        self.capture_path.write_bytes(self.capture_bytes)
        return {"pid": 301, "exit_status": 0}


def _passing_nonreference_report(
    manifest: dict[str, object],
    take: dict[str, object],
    capture_sha256: str,
    journal_head_sha256: str,
) -> dict[str, object]:
    return {
        "schema": "ias.s4_8.nonreference_presealing_report.v1",
        "decision": "PASS",
        "mode": take["acquisition_mode"],
        "dry_run": True,
        "reasons": [],
        "capture_integrity": {"decision": "PASS", "reasons": []},
        "impact_integrity": None,
        "zed_integrity": None,
        "input_provenance": {
            "capture_sha256": capture_sha256,
            "reference_sha256": None,
            "campaign_manifest_sha256": manifest["manifest_sha256"],
            "engineering_take_definition_sha256": take[
                "engineering_take_definition_sha256"
            ],
            "process_journal_head_sha256": journal_head_sha256,
            "configuration_sha256": manifest["gate_configuration_sha256"],
            "detector_configuration_sha256": manifest[
                "detector_configuration_sha256"
            ],
            "zed_artifact_hashes": None,
            "outcome_fields_read": [],
        },
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
        },
    }


def _nonreference_journal_through_capture(
    manifest: dict[str, object],
    take: dict[str, object],
    *,
    capture_sha256: str,
) -> list[dict[str, object]]:
    journal: list[dict[str, object]] = []
    events = [
        (
            "capture_controller_started",
            {
                "identity": manifest["controller"]["identity"],
                "version": manifest["controller"]["version"],
                "pid": 300,
                "mode": take["acquisition_mode"],
            },
        ),
        (
            "recorder_started",
            {"pid": 301, "process_identity": "fake_recorder"},
        ),
        ("recorder_ready", {"pid": 301, "ready": True}),
        ("silence_interval_started", {"stimulus": "ambient_room_silence"}),
        ("silence_interval_completed", {"stimulus": "ambient_room_silence"}),
        ("recorder_terminated", {"pid": 301, "exit_status": 0}),
        (
            "capture_authenticated",
            {
                "capture_sha256": capture_sha256,
                "device_profile_id": manifest["devices"]["respeaker"][
                    "profile_id"
                ],
                "channel_map": manifest["channel_map"],
                "gate_configuration_sha256": manifest[
                    "gate_configuration_sha256"
                ],
                "detector_configuration_sha256": manifest[
                    "detector_configuration_sha256"
                ],
                "zed_artifact_hashes": None,
            },
        ),
    ]
    for event_type, data in events:
        append_nonreference_journal_event(
            journal,
            campaign_manifest=manifest,
            take=take,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
            event_type=event_type,
            observed_monotonic_ns=1_000_000_000 + len(journal) * 100_000_000,
            data=data,
        )
    return journal


def test_supported_silence_controller_has_no_playback_and_seals_only_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "silence"
    )
    backend = _FakeNonreferenceBackend(b"capture")

    def passing_gate(**kwargs: object) -> dict[str, object]:
        return _passing_nonreference_report(
            manifest,
            take,
            hashlib.sha256(b"capture").hexdigest(),
            str(kwargs["process_journal_head_sha256"]),
        )

    monkeypatch.setattr(
        campaign,
        "evaluate_nonreference_presealing_gate",
        passing_gate,
    )
    result = run_supported_nonreference_acquisition(
        backend=backend,
        repo_root=ROOT,
        take=take,
        campaign_manifest=manifest,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        capture_path=tmp_path / "capture.wav",
        zed_artifact_root=None,
        journal_path=tmp_path / "journal.jsonl",
        retry_report_path=tmp_path / "retry.json",
        candidate_seal_path=tmp_path / "candidate.json",
        clearance_registry_path=tmp_path / "used.json",
        dry_run=True,
    )

    assert result["decision"] == "PASS"
    assert result["candidate_seal"]["engineering_only"] is True
    assert backend.operations == [
        "recorder_start",
        "recorder_ready",
        "silence_begin",
        "continuous_capture",
        "silence_complete",
        "recorder_stop",
    ]
    assert all("playback" not in operation for operation in backend.operations)


def test_nonreference_clearance_and_seal_reject_stale_capture(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "silence"
    )
    capture = tmp_path / "capture.wav"
    capture.write_bytes(b"capture")
    report = _passing_nonreference_report(
        manifest,
        take,
        hashlib.sha256(b"capture").hexdigest(),
        "e" * 64,
    )
    journal = _nonreference_journal_through_capture(
        manifest,
        take,
        capture_sha256=hashlib.sha256(b"capture").hexdigest(),
    )
    report["input_provenance"]["process_journal_head_sha256"] = journal[-1][
        "event_sha256"
    ]
    append_nonreference_journal_event(
        journal,
        campaign_manifest=manifest,
        take=take,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        event_type="gate_evaluated",
        observed_monotonic_ns=1_800_000_000,
        data={
            "report_sha256": canonical_sha256(report),
            "decision": "PASS",
        },
    )
    clearance = create_nonreference_candidate_clearance(
        report,
        campaign_manifest=manifest,
        take=take,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        journal=journal,
    )
    append_nonreference_journal_event(
        journal,
        campaign_manifest=manifest,
        take=take,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        event_type="candidate_clearance_created",
        observed_monotonic_ns=1_900_000_000,
        data={"clearance_sha256": clearance["clearance_sha256"]},
    )
    capture.write_bytes(b"changed")

    with pytest.raises(S48EngineeringCampaignError, match="different capture"):
        seal_nonreference_candidate(
            capture_path=capture,
            report=report,
            clearance=clearance,
            campaign_manifest=manifest,
            take=take,
            journal=journal,
            candidate_seal_path=tmp_path / "candidate.json",
            clearance_registry_path=tmp_path / "used.json",
            dry_run=False,
        )


def test_nonreference_journal_rejects_reordering_and_mutation() -> None:
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["acquisition_mode"] == "silence"
    )
    journal = _nonreference_journal_through_capture(
        manifest,
        take,
        capture_sha256="f" * 64,
    )

    validate_nonreference_process_journal(
        campaign_manifest=manifest,
        take=take,
        journal=journal,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
        required_terminal_event="capture_authenticated",
    )
    changed = deepcopy(journal)
    changed[1]["data"]["pid"] = 999
    with pytest.raises(S48EngineeringCampaignError):
        validate_nonreference_process_journal(
            campaign_manifest=manifest,
            take=take,
            journal=changed,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
            required_terminal_event="capture_authenticated",
        )
    reordered = deepcopy(journal)
    reordered[3], reordered[4] = reordered[4], reordered[3]
    with pytest.raises(S48EngineeringCampaignError):
        validate_nonreference_process_journal(
            campaign_manifest=manifest,
            take=take,
            journal=reordered,
            expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
            required_terminal_event="capture_authenticated",
        )
