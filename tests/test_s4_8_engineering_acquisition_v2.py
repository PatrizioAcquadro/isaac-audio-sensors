from __future__ import annotations

import hashlib
import inspect
import signal
import sys
import wave
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.acquisition.s4_8_engineering_acquisition as acquisition
from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    SubprocessEngineeringBackend,
    append_engineering_journal_event,
    build_engineering_precollection_manifest,
    create_candidate_engineering_clearance,
    run_presealing_gate_from_engineering_files,
    run_supported_engineering_acquisition,
    seal_engineering_candidate,
    validate_engineering_process_journal,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    DEFAULT_PRESEALING_CONFIG_V2,
)


def _manifest(*, reference_sha256: str = "a" * 64) -> dict[str, object]:
    return build_engineering_precollection_manifest(
        code_head="4" * 40,
        environment_identity="ubuntu24-respeaker-host-v1",
        reference_wav_sha256=reference_sha256,
        gate_configuration_sha256="b" * 64,
        detector_configuration_sha256="c" * 64,
        device_profile_id="respeaker_usb_6ch_pcm16_v1",
        channel_map=[
            "playback_left",
            "playback_right",
            "microphone_0",
            "microphone_1",
            "microphone_2",
            "microphone_3",
        ],
        protocol_id="s4_8_physical_engineering_rehearsal_v2",
        capture_controller_identity="ias.s4_8.engineering_controller",
        capture_controller_version="2.0",
    )


def _append(
    journal: list[dict[str, object]],
    manifest: dict[str, object],
    event_type: str,
    data: dict[str, object],
) -> None:
    append_engineering_journal_event(
        journal,
        manifest_anchor_sha256=str(manifest["manifest_sha256"]),
        event_type=event_type,
        observed_monotonic_ns=1_000_000_000 + len(journal) * 100_000_000,
        data=data,
    )


def _journal_through_capture(
    manifest: dict[str, object],
) -> list[dict[str, object]]:
    journal: list[dict[str, object]] = []
    events = [
        (
            "capture_controller_started",
            {
                "identity": "ias.s4_8.engineering_controller",
                "version": "2.0",
                "pid": 100,
            },
        ),
        ("recorder_started", {"pid": 101, "process_identity": "arecord"}),
        ("recorder_ready", {"pid": 101, "ready": True}),
        ("playback_commanded", {"command_sha256": "d" * 64}),
        ("playback_started", {"pid": 102, "process_identity": "aplay"}),
        ("playback_stop_planned", {"planned_monotonic_ns": 20_000_000_000}),
        ("playback_terminated", {"pid": 102, "exit_status": 0}),
        ("recorder_terminated", {"pid": 101, "exit_status": 0}),
        (
            "capture_authenticated",
            {
                "capture_sha256": "e" * 64,
                "reference_sha256": "a" * 64,
                "device_profile_id": "respeaker_usb_6ch_pcm16_v1",
                "channel_map": manifest["channel_map"],
                "gate_configuration_sha256": "b" * 64,
                "detector_configuration_sha256": "c" * 64,
            },
        ),
    ]
    for event_type, data in events:
        _append(journal, manifest, event_type, data)
    return journal


def _report(
    manifest: dict[str, object],
    journal: list[dict[str, object]],
    *,
    decision: str = "PASS",
) -> dict[str, object]:
    return {
        "schema": "ias.s4_8.presealing_gate_report.v2",
        "decision": decision,
        "reasons": []
        if decision == "PASS"
        else [
            {
                "code": "acoustic_playback_stopped_early",
                "category": "playback_presence",
                "message": "missing stop sentinel",
                "details": {},
            }
        ],
        "input_provenance": {
            "capture_sha256": "e" * 64,
            "reference_sha256": "a" * 64,
            "manifest_sha256": manifest["manifest_sha256"],
            "process_journal_head_sha256": journal[-1]["event_sha256"],
            "configuration_sha256": "b" * 64,
            "detector_configuration_sha256": "c" * 64,
            "outcome_fields_read": [],
        },
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
            "official_take_seal": False,
        },
    }


def _journal_and_clearance() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
]:
    manifest = _manifest()
    journal = _journal_through_capture(manifest)
    report = _report(manifest, journal)
    _append(
        journal,
        manifest,
        "gate_evaluated",
        {"report_sha256": canonical_sha256(report), "decision": "PASS"},
    )
    clearance = create_candidate_engineering_clearance(
        report,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
    )
    _append(
        journal,
        manifest,
        "candidate_clearance_created",
        {"clearance_sha256": clearance["clearance_sha256"]},
    )
    return manifest, journal, report, clearance


def test_hash_chained_process_journal_rejects_sequence_and_anchor_defects() -> None:
    manifest = _manifest()
    journal = _journal_through_capture(manifest)

    validate_engineering_process_journal(
        manifest,
        journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        required_terminal_event="capture_authenticated",
    )
    mutations = []
    missing = deepcopy(journal)
    del missing[2]
    mutations.append(missing)
    reordered = deepcopy(journal)
    reordered[1], reordered[2] = reordered[2], reordered[1]
    mutations.append(reordered)
    duplicated = deepcopy(journal)
    duplicated.insert(2, deepcopy(duplicated[1]))
    mutations.append(duplicated)
    altered = deepcopy(journal)
    altered[1]["data"]["pid"] = 999
    mutations.append(altered)
    for invalid in mutations:
        with pytest.raises(S48EngineeringAcquisitionError):
            validate_engineering_process_journal(
                manifest,
                invalid,
                expected_manifest_sha256=str(manifest["manifest_sha256"]),
                required_terminal_event="capture_authenticated",
            )
    recomputed_manifest = deepcopy(manifest)
    recomputed_manifest["environment_identity"] = "different-host"
    recomputed_manifest["manifest_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in recomputed_manifest.items()
            if key != "manifest_sha256"
        }
    )
    with pytest.raises(S48EngineeringAcquisitionError, match="anchor"):
        validate_engineering_process_journal(
            recomputed_manifest,
            [],
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            required_terminal_event="capture_authenticated",
        )


def test_pass_creates_exact_candidate_clearance_and_retry_cannot_clear() -> None:
    manifest = _manifest()
    journal = _journal_through_capture(manifest)
    passing = _report(manifest, journal)
    _append(
        journal,
        manifest,
        "gate_evaluated",
        {"report_sha256": canonical_sha256(passing), "decision": "PASS"},
    )

    clearance = create_candidate_engineering_clearance(
        passing,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
    )

    assert clearance["capture_sha256"] == "e" * 64
    assert clearance["report_sha256"] == canonical_sha256(passing)
    retry_journal = _journal_through_capture(manifest)
    retry = _report(manifest, retry_journal, decision="RETRY_REQUIRED")
    _append(
        retry_journal,
        manifest,
        "gate_evaluated",
        {
            "report_sha256": canonical_sha256(retry),
            "decision": "RETRY_REQUIRED",
        },
    )
    with pytest.raises(S48EngineeringAcquisitionError, match="RETRY_REQUIRED"):
        create_candidate_engineering_clearance(
            retry,
            manifest=manifest,
            journal=retry_journal,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
        )


def test_clearance_cannot_seal_other_capture_or_be_reused(tmp_path: Path) -> None:
    capture = tmp_path / "capture.wav"
    other_capture = tmp_path / "other.wav"
    reference = tmp_path / "reference.wav"
    capture.write_bytes(b"capture")
    other_capture.write_bytes(b"other")
    reference.write_bytes(b"reference")
    capture_sha256 = hashlib.sha256(capture.read_bytes()).hexdigest()
    reference_sha256 = hashlib.sha256(reference.read_bytes()).hexdigest()
    manifest = _manifest(reference_sha256=reference_sha256)
    # Rebuild a consistent report/clearance/journal around the exact fixture files.
    journal = _journal_through_capture(manifest)
    # Recompute this one event through the supported append path.
    journal = journal[:-1]
    _append(
        journal,
        manifest,
        "capture_authenticated",
        deepcopy(_journal_through_capture(manifest)[-1]["data"])
        | {
            "capture_sha256": capture_sha256,
            "reference_sha256": reference_sha256,
        },
    )
    report = _report(manifest, journal)
    report["input_provenance"]["capture_sha256"] = capture_sha256
    report["input_provenance"]["reference_sha256"] = reference_sha256
    _append(
        journal,
        manifest,
        "gate_evaluated",
        {"report_sha256": canonical_sha256(report), "decision": "PASS"},
    )
    clearance = create_candidate_engineering_clearance(
        report,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
    )
    _append(
        journal,
        manifest,
        "candidate_clearance_created",
        {"clearance_sha256": clearance["clearance_sha256"]},
    )

    with pytest.raises(S48EngineeringAcquisitionError, match="capture"):
        seal_engineering_candidate(
            capture_path=other_capture,
            reference_path=reference,
            report=report,
            clearance=clearance,
            manifest=manifest,
            journal=journal,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            candidate_seal_path=tmp_path / "wrong.json",
            clearance_registry_path=tmp_path / "used.json",
            dry_run=False,
        )
    seal_engineering_candidate(
        capture_path=capture,
        reference_path=reference,
        report=report,
        clearance=clearance,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        candidate_seal_path=tmp_path / "candidate.json",
        clearance_registry_path=tmp_path / "used.json",
        dry_run=False,
    )
    with pytest.raises(S48EngineeringAcquisitionError, match="reused"):
        seal_engineering_candidate(
            capture_path=capture,
            reference_path=reference,
            report=report,
            clearance=clearance,
            manifest=manifest,
            journal=journal,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            candidate_seal_path=tmp_path / "second.json",
            clearance_registry_path=tmp_path / "used.json",
            dry_run=False,
        )


def test_modified_report_configuration_or_journal_invalidates_clearance(
    tmp_path: Path,
) -> None:
    manifest, journal, report, clearance = _journal_and_clearance()
    capture = tmp_path / "capture"
    reference = tmp_path / "reference"
    capture.write_bytes(b"x")
    reference.write_bytes(b"y")
    cases = []
    changed_report = deepcopy(report)
    changed_report["input_provenance"]["configuration_sha256"] = "9" * 64
    cases.append((changed_report, clearance, journal))
    changed_clearance = deepcopy(clearance)
    changed_clearance["configuration_sha256"] = "9" * 64
    cases.append((report, changed_clearance, journal))
    changed_journal = deepcopy(journal)
    changed_journal[6]["data"]["exit_status"] = 1
    cases.append((report, clearance, changed_journal))
    for changed_report, changed_clearance, changed_journal in cases:
        with pytest.raises(S48EngineeringAcquisitionError):
            seal_engineering_candidate(
                capture_path=capture,
                reference_path=reference,
                report=changed_report,
                clearance=changed_clearance,
                manifest=manifest,
                journal=changed_journal,
                expected_manifest_sha256=str(manifest["manifest_sha256"]),
                candidate_seal_path=tmp_path / "candidate.json",
                clearance_registry_path=tmp_path / "used.json",
                dry_run=True,
            )


def test_supported_sealing_api_has_no_clearance_bypass() -> None:
    parameters = inspect.signature(seal_engineering_candidate).parameters

    assert "clearance" in parameters
    assert parameters["clearance"].default is inspect.Parameter.empty
    assert "report" in parameters
    assert "journal" in parameters
    assert "manifest" in parameters
    backend_methods = {
        name
        for name, value in inspect.getmembers(
            SubprocessEngineeringBackend,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert backend_methods == {
        "monotonic_ns",
        "prepare_playback",
        "start_playback",
        "start_recorder",
        "stop_playback",
        "stop_recorder",
        "wait_recorder_ready",
        "wait_until",
    }


def test_subprocess_backend_preserves_authenticated_controller_termination() -> None:
    backend = SubprocessEngineeringBackend(
        recorder_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        playback_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        readiness_delay_s=0.01,
    )
    command = backend.prepare_playback(Path("reference.wav"))
    playback = backend.start_playback(command)

    status = backend.stop_playback(playback)

    assert status["exit_status"] == -signal.SIGTERM
    assert status["controller_requested_termination"] is True
    assert status["controller_requested_signal"] == signal.SIGTERM
    assert status["observed_termination_monotonic_ns"] > 0


class _FakeBackend:
    def __init__(self, capture_bytes: bytes) -> None:
        self.now = 1_000_000_000
        self.capture_bytes = capture_bytes
        self.operations: list[str] = []

    def monotonic_ns(self) -> int:
        return self.now

    def start_recorder(self, capture_path: Path) -> dict[str, object]:
        self.operations.append("recorder_start")
        self.capture_path = capture_path
        return {"pid": 201, "process_identity": "fake_recorder"}

    def wait_recorder_ready(self, recorder: object) -> bool:
        self.operations.append("recorder_ready")
        return True

    def prepare_playback(self, reference_path: Path) -> dict[str, object]:
        self.operations.append("playback_command")
        return {"command_sha256": "d" * 64}

    def start_playback(self, command: object) -> dict[str, object]:
        self.operations.append("playback_start")
        return {"pid": 202, "process_identity": "fake_player"}

    def wait_until(self, monotonic_ns: int) -> None:
        self.operations.append("continuous_capture")
        self.now = monotonic_ns

    def stop_playback(self, playback: object) -> dict[str, object]:
        self.operations.append("playback_stop")
        return {"pid": 202, "exit_status": 0}

    def stop_recorder(self, recorder: object) -> dict[str, object]:
        self.operations.append("recorder_stop")
        self.capture_path.write_bytes(self.capture_bytes)
        return {"pid": 201, "exit_status": 0}


def test_supported_controller_enforces_complete_order_and_retains_retry_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = tmp_path / "reference.wav"
    capture = tmp_path / "capture.wav"
    reference.write_bytes(b"reference fixture")
    capture_bytes = b"capture fixture"
    manifest = _manifest(
        reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest()
    )

    def passing_gate(**kwargs: object) -> dict[str, object]:
        journal = kwargs["journal"]
        result = _report(manifest, journal)
        result["input_provenance"]["capture_sha256"] = journal[-1]["data"][
            "capture_sha256"
        ]
        result["input_provenance"]["reference_sha256"] = journal[-1]["data"][
            "reference_sha256"
        ]
        return result

    monkeypatch.setattr(
        acquisition,
        "run_presealing_gate_from_engineering_files",
        passing_gate,
    )
    backend = _FakeBackend(capture_bytes)

    result = run_supported_engineering_acquisition(
        backend=backend,
        repo_root=Path(__file__).resolve().parents[1],
        capture_path=capture,
        reference_path=reference,
        manifest=manifest,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        journal_path=tmp_path / "journal.jsonl",
        retry_report_path=tmp_path / "retry.json",
        candidate_seal_path=tmp_path / "candidate.json",
        clearance_registry_path=tmp_path / "used.json",
        dry_run=True,
    )

    assert result["decision"] == "PASS"
    assert result["clearance"]["clearance_sha256"]
    assert result["candidate_seal"]["engineering_only"] is True
    assert backend.operations == [
        "recorder_start",
        "recorder_ready",
        "continuous_capture",
        "playback_command",
        "playback_start",
        "continuous_capture",
        "playback_stop",
        "continuous_capture",
        "recorder_stop",
    ]
    assert not (tmp_path / "candidate.json").exists()
    assert not (tmp_path / "used.json").exists()


def test_file_backed_journal_to_v2_gate_passes_complete_engineering_fixture(
    tmp_path: Path,
) -> None:
    rate = 16_000
    reference = np.random.default_rng(493).normal(0.0, 0.2, size=4_096)
    capture = np.zeros((20 * rate, 6), dtype=np.float64)
    microphones = np.random.default_rng(494).normal(
        0.0,
        0.0005,
        size=(4, 20 * rate),
    )
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (np.arange(rate, 19 * rate) - rate - delay) % reference.size
        microphones[channel, rate : 19 * rate] += 0.04 * reference[indices]
    capture[:, 2:6] = microphones.T
    capture_path = tmp_path / "capture.wav"
    reference_path = tmp_path / "reference.wav"
    _write_wav(capture_path, capture, rate)
    _write_wav(reference_path, reference[:, None], rate)
    manifest = build_engineering_precollection_manifest(
        code_head="4" * 40,
        environment_identity="synthetic-file-fixture",
        reference_wav_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        gate_configuration_sha256=canonical_sha256(DEFAULT_PRESEALING_CONFIG_V2),
        detector_configuration_sha256=canonical_sha256(
            DEFAULT_PRESEALING_CONFIG_V2["detector"]
        ),
        device_profile_id="respeaker_usb_6ch_pcm16_v1",
        channel_map=DEFAULT_PRESEALING_CONFIG_V2["expected_channel_map"],
        protocol_id="s4_8_physical_engineering_rehearsal_v2",
        capture_controller_identity="ias.s4_8.engineering_controller",
        capture_controller_version="2.0",
    )
    journal: list[dict[str, object]] = []
    events = [
        (
            "capture_controller_started",
            900_000_000,
            {
                "identity": "ias.s4_8.engineering_controller",
                "version": "2.0",
                "pid": 100,
            },
        ),
        (
            "recorder_started",
            1_000_000_000,
            {"pid": 101, "process_identity": "fixture_recorder"},
        ),
        ("recorder_ready", 1_050_000_000, {"pid": 101, "ready": True}),
        ("playback_commanded", 1_990_000_000, {"command_sha256": "d" * 64}),
        (
            "playback_started",
            2_000_000_000,
            {"pid": 102, "process_identity": "fixture_player"},
        ),
        (
            "playback_stop_planned",
            2_000_000_000,
            {"planned_monotonic_ns": 20_000_000_000},
        ),
        (
            "playback_terminated",
            20_010_000_000,
            {"pid": 102, "exit_status": 0},
        ),
        (
            "recorder_terminated",
            21_000_000_000,
            {"pid": 101, "exit_status": 0},
        ),
        (
            "capture_authenticated",
            21_010_000_000,
            {
                "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                "reference_sha256": hashlib.sha256(
                    reference_path.read_bytes()
                ).hexdigest(),
                "device_profile_id": manifest["device_profile_id"],
                "channel_map": manifest["channel_map"],
                "gate_configuration_sha256": manifest["gate_configuration_sha256"],
                "detector_configuration_sha256": manifest[
                    "detector_configuration_sha256"
                ],
            },
        ),
    ]
    for event_type, observed_ns, data in events:
        append_engineering_journal_event(
            journal,
            manifest_anchor_sha256=str(manifest["manifest_sha256"]),
            event_type=event_type,
            observed_monotonic_ns=observed_ns,
            data=data,
        )

    report = run_presealing_gate_from_engineering_files(
        capture_path=capture_path,
        reference_path=reference_path,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        repo_root=Path(__file__).resolve().parents[1],
        dry_run=True,
    )

    assert report["decision"] == "PASS"
    assert report["reasons"] == []
    assert report["waveform"]["sentinels"]["start"]["present"] is True
    assert report["waveform"]["sentinels"]["stop"]["present"] is True
    assert report["capture_integrity"]["decision"] == "PASS"


def test_supported_controller_retry_writes_only_operational_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = tmp_path / "reference.wav"
    capture = tmp_path / "capture.wav"
    reference.write_bytes(b"reference fixture")
    manifest = _manifest(
        reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest()
    )

    def retry_gate(**kwargs: object) -> dict[str, object]:
        journal = kwargs["journal"]
        result = _report(manifest, journal, decision="RETRY_REQUIRED")
        result["input_provenance"]["capture_sha256"] = journal[-1]["data"][
            "capture_sha256"
        ]
        result["input_provenance"]["reference_sha256"] = journal[-1]["data"][
            "reference_sha256"
        ]
        return result

    monkeypatch.setattr(
        acquisition,
        "run_presealing_gate_from_engineering_files",
        retry_gate,
    )
    result = run_supported_engineering_acquisition(
        backend=_FakeBackend(b"bad capture"),
        repo_root=Path(__file__).resolve().parents[1],
        capture_path=capture,
        reference_path=reference,
        manifest=manifest,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        journal_path=tmp_path / "journal.jsonl",
        retry_report_path=tmp_path / "retry.json",
        candidate_seal_path=tmp_path / "candidate.json",
        clearance_registry_path=tmp_path / "used.json",
        dry_run=False,
    )

    assert result["decision"] == "RETRY_REQUIRED"
    assert result["clearance"] is None
    assert result["candidate_seal"] is None
    assert (tmp_path / "retry.json").is_file()
    assert not (tmp_path / "candidate.json").exists()
    assert not (tmp_path / "used.json").exists()


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    encoded = np.rint(np.clip(samples, -1.0, 32767.0 / 32768.0) * 32768.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(encoded.tobytes())
