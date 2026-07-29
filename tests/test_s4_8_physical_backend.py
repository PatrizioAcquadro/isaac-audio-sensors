from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

import isaac_audio_sensors.acquisition.s4_8_physical_backend as physical_backend
from isaac_audio_sensors.acquisition.s4_8_physical_backend import (
    RemotePhysicalEngineeringBackend,
    S48PhysicalBackendError,
    build_continuous_playback_asset,
    evaluate_mac_preflight_acceptance,
)


def _write_wav(path: Path, samples: np.ndarray, rate: int = 48_000) -> None:
    encoded = np.rint(
        np.clip(samples, -1.0, 32767.0 / 32768.0) * 32768.0
    ).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(encoded.tobytes())


def test_continuous_asset_tiles_exact_reference_without_gap(
    tmp_path: Path,
) -> None:
    reference = np.arange(12, dtype=np.float64).reshape(-1, 1) / 100.0
    source = tmp_path / "reference.wav"
    output = tmp_path / "continuous.wav"
    _write_wav(source, reference, rate=12)

    result = build_continuous_playback_asset(
        reference_path=source,
        output_path=output,
        duration_s=2.5,
    )

    with wave.open(str(output), "rb") as stream:
        assert stream.getframerate() == 12
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getnframes() == 30
        actual = np.frombuffer(stream.readframes(30), dtype="<i2")
    with wave.open(str(source), "rb") as stream:
        original = np.frombuffer(stream.readframes(12), dtype="<i2")
    np.testing.assert_array_equal(actual, np.resize(original, 30))
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["asset_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["gap_samples_inserted"] == 0


def test_continuous_asset_tiles_only_frozen_active_reference_interval(
    tmp_path: Path,
) -> None:
    reference = np.arange(120, dtype=np.float64).reshape(-1, 1) / 1000.0
    source = tmp_path / "reference.wav"
    output = tmp_path / "continuous.wav"
    _write_wav(source, reference, rate=12)

    result = build_continuous_playback_asset(
        reference_path=source,
        output_path=output,
        duration_s=2.5,
        source_start_s=2.25,
        source_stop_s=7.25,
    )

    with wave.open(str(output), "rb") as stream:
        actual = np.frombuffer(stream.readframes(30), dtype="<i2")
    with wave.open(str(source), "rb") as stream:
        original = np.frombuffer(stream.readframes(120), dtype="<i2")
    active = original[27:87]
    np.testing.assert_array_equal(actual, np.resize(active, 30))
    assert result["source_active_start_frame"] == 27
    assert result["source_active_stop_frame"] == 87
    assert result["source_active_duration_s"] == 5.0
    assert result["construction"] == "exact_active_pcm_frame_tiling"


def test_continuous_asset_refuses_overwrite_or_non_pcm16(
    tmp_path: Path,
) -> None:
    source = tmp_path / "reference.wav"
    output = tmp_path / "continuous.wav"
    _write_wav(source, np.zeros((12, 1)), rate=12)
    output.write_bytes(b"existing")

    with pytest.raises(S48PhysicalBackendError, match="overwrite"):
        build_continuous_playback_asset(
            reference_path=source,
            output_path=output,
            duration_s=2.0,
        )


class _CompletedProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode = 0
        self.stdin = _ProcessInput()
        self.stdout = None
        self.stderr = None

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float) -> int:
        del timeout
        return self.returncode


class _ProcessInput:
    def __init__(self) -> None:
        self.values: list[str] = []

    def write(self, value: str) -> int:
        self.values.append(value)
        return len(value)

    def flush(self) -> None:
        return None


def _backend(tmp_path: Path) -> RemotePhysicalEngineeringBackend:
    return RemotePhysicalEngineeringBackend(
        pi_ssh_prefix=["ssh", "pi"],
        pi_scp_prefix=["scp"],
        pi_scp_target="pi",
        pi_helper_path="capture.py",
        pi_remote_attempt="campaign/take_001",
        pi_device="hw:CARD=Array,DEV=0",
        capture_duration_s=20,
        mac_ssh_prefix=["ssh", "mac"],
        mac_playback_helper_path="s4_8_mac_playback.swift",
        mac_continuous_asset_path="continuous.wav",
        mac_continuous_asset_sha256="a" * 64,
        playback_gain=0.5,
        zed_helper_path=tmp_path / "zed_capture.py",
        zed_replay_path=tmp_path / "zed_replay.py",
        expected_zed_serial="39011785",
        expected_zed_sdk="5.4.0",
        expected_zed_camera_firmware="1523",
        expected_zed_sensor_firmware="777",
    )


def test_pi_recorder_readiness_transfer_and_producer_hash_are_authenticated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = iter((_CompletedProcess(101),))
    capture_bytes = b"authenticated completed wav"

    monkeypatch.setattr(
        physical_backend,
        "_start_process",
        lambda command, **kwargs: next(processes),
    )
    monkeypatch.setattr(
        physical_backend,
        "_wait_json_event",
        lambda process, *, expected_event, timeout_s: {
            "event": expected_event,
            "capture_format": {
                "sample_rate_hz": 16000,
                "channel_count": 6,
                "encoding": "PCM_S16_LE",
            },
        },
    )

    def fake_scp(
        command: list[str],
        *,
        text: bool,
        capture_output: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del text, capture_output, timeout, check
        local_path = Path(command[-1])
        if command[-2].endswith("/producer_status.json"):
            local_path.write_text(
                json.dumps(
                        {
                            "status": "complete",
                            "sha256": hashlib.sha256(capture_bytes).hexdigest(),
                            "started_monotonic_ns": 1_000_000_000,
                            "completed_monotonic_ns": 21_000_000_000,
                        }
                ),
                encoding="utf-8",
            )
        elif command[-2].endswith("/respeaker_audio.wav"):
            local_path.write_bytes(capture_bytes)
        else:
            raise AssertionError(f"unexpected transfer: {command}")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(physical_backend.subprocess, "run", fake_scp)
    backend = _backend(tmp_path)
    capture_path = tmp_path / "attempt" / "respeaker_audio.wav"

    recorder = backend.start_recorder(capture_path, duration_s=20)
    assert recorder["process_identity"] == "ssh_pi_respeaker_capture"
    assert backend.wait_recorder_ready(recorder) is True
    status = backend.stop_recorder(recorder)

    assert status["exit_status"] == 0
    assert status["controller_requested_termination"] is False
    assert status["producer_capture_duration_ns"] == 20_000_000_000
    assert capture_path.read_bytes() == capture_bytes
    assert len(status["producer_status_sha256"]) == 64


def test_mac_playback_lifecycle_binds_reference_and_observes_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _CompletedProcess(202)
    monkeypatch.setattr(
        physical_backend,
        "_start_process",
        lambda command, **kwargs: process,
    )
    events = iter(
        (
            {
                "event": "armed",
                "asset_sha256": "a" * 64,
                "helper_monotonic_ns": 1_000,
                "start_observation":
                    "coreaudio_first_nonzero_presented_frame",
                "output_presentation_latency_ns": 12_000,
            },
            {
                "event": "clock_sync",
                "helper_monotonic_ns": 2_000,
            },
            {
                "event": "playback_started",
                "presentation_start_monotonic_ns": 502_000,
                "first_nonzero_frame_offset": 7,
                "start_observation":
                    "coreaudio_first_nonzero_presented_frame",
                "output_presentation_latency_ns": 12_000,
            },
            {
                "event": "playback_completed",
                "playback_exit_status": 0,
                "completion_observation": "coreaudio_data_played_back",
            },
        )
    )
    monkeypatch.setattr(
        physical_backend,
        "_wait_json_event",
        lambda process, *, expected_event, timeout_s: next(events),
    )
    observed_times = iter((10_000, 20_000, 900_000))
    monkeypatch.setattr(
        physical_backend.time,
        "monotonic_ns",
        lambda: next(observed_times),
    )
    reference_path = tmp_path / "reference.wav"
    reference_path.write_bytes(b"exact reference")
    backend = _backend(tmp_path)

    prepared = backend.prepare_playback(reference_path)
    playback = backend.start_playback(
        prepared,
        target_monotonic_ns=515_000,
    )
    stopped = backend.stop_playback(playback)

    assert prepared["authenticated_reference_sha256"] == hashlib.sha256(
        reference_path.read_bytes()
    ).hexdigest()
    assert prepared["continuous_asset_path"] == "continuous.wav"
    assert prepared["clock_sync_round_trip_ns"] == 10_000
    assert playback["process_identity"] == "ssh_mac_coreaudio"
    assert playback["observed_start_monotonic_ns"] == 510_000
    assert (
        playback["presentation_start_upper_bound_monotonic_ns"] == 520_000
    )
    assert playback["output_presentation_latency_ns"] == 12_000
    assert playback["start_observation"] == (
        "coreaudio_first_nonzero_presented_frame"
    )
    assert process.stdin.values == ["SYNC\n", "START_AT 502000\n"]
    assert stopped["exit_status"] == 0
    assert stopped["remote_playback_exit_status"] == 0
    assert stopped["completion_observation"] == "coreaudio_data_played_back"
    assert stopped["controller_requested_termination"] is False


def test_mac_helper_source_uses_render_callback_without_fitted_delay() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "s4_8_mac_playback.swift").read_text(
        encoding="utf-8"
    )

    assert "AVAudioEngine" in source
    assert "installTap" in source
    assert "first_nonzero_presented_frame" in source
    assert "dataPlayedBack" in source
    assert "START_AT " in source
    assert "player.play(" in source
    assert "AVAudioTime.hostTime" in source
    assert "sourceFirstNonzeroNanoseconds" in source
    assert "Thread.sleep" not in source
    assert "asyncAfter" not in source
    assert "recursive-include scripts *.swift" in (
        root / "MANIFEST.in"
    ).read_text(encoding="utf-8")


def test_runtime_campaign_defaults_are_repository_local() -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_repository_local_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    campaign = json.loads(
        (root / "configs/s4_8_engineering_campaign.v1.json").read_text(
            encoding="utf-8"
        )
    )
    preliminary = json.loads(
        (root / "configs/s4_8_preliminary_workflow.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert runner._repository_local_campaign_root(
        campaign["operational_locations"]["campaign_root"]
    ) == root / ".local/s4_8/s4_8_engineering_rehearsal"
    assert runner._repository_local_campaign_root(
        preliminary["preliminary"]["campaign_root"]
    ) == root / ".local/s4_8/s4_8_preliminary"


def test_runtime_campaign_default_rejects_non_s4_8_name() -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_repository_local_rejection_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    with pytest.raises(
        runner.S48PhysicalRehearsalError,
        match="S4.8 campaign name",
    ):
        runner._repository_local_campaign_root("/tmp/unrelated")


def test_mac_runtime_identity_preserves_stdout_stderr_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location("s48_physical_runner", script_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: float) -> dict[str, object]:
        del timeout
        calls.append(command)
        if command[-1] == "--version":
            return {
                "return_code": 0,
                "stdout": "Apple Swift version frozen\nTarget: arm64\n",
                "stderr": "swift-driver version: frozen ",
            }
        return {"return_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(runner, "_run", fake_run)
    report = runner._verify_mac_playback_runtime(
        {
            "playback": {
                "ssh_prefix": ["ssh", "mac"],
                "playback_runtime_path": "/usr/bin/swift",
                "playback_typecheck_path": "/usr/bin/swiftc",
                "playback_runtime_stdout": (
                    "Apple Swift version frozen\nTarget: arm64"
                ),
                "playback_runtime_stderr": "swift-driver version: frozen",
                "playback_helper_mac_path": "helper.swift",
                "playback_helper_sha256": "a" * 64,
            }
        }
    )

    assert report["status"] == "passed"
    assert report["runtime_stdout"].startswith("Apple Swift")
    assert report["runtime_stderr"].startswith("swift-driver")
    assert calls[1][-2:] == ["-typecheck", "helper.swift"]


def test_runner_retires_failed_raws_only_after_replacement_passes(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_failed_raw_retention_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    take_id = "s48prelim_002_low_level_reference"
    attempts_root = tmp_path / "attempts" / take_id
    for attempt_number in (1, 2):
        attempt_root = attempts_root / f"{take_id}__attempt_{attempt_number:02d}"
        attempt_root.mkdir(parents=True)
        (attempt_root / "respeaker_audio.wav").write_bytes(b"failed raw")
        (attempt_root / "retry_report.json").write_text(
            json.dumps(
                {
                    "reasons": [
                        {
                            "code": (
                                "reference_alignment_failed"
                                if attempt_number == 2
                                else "acoustic_playback_stopped_early"
                            )
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (attempt_root / "zed").mkdir()
        (attempt_root / "zed" / "artifact").write_bytes(b"failed")
    replacement = attempts_root / f"{take_id}__attempt_03"
    replacement.mkdir()
    (replacement / "respeaker_audio.wav").write_bytes(b"valid raw")
    (replacement / "candidate_seal.json").write_text("{}", encoding="utf-8")
    ledger = [
        {
            "engineering_take_id": take_id,
            "attempt_number": 1,
            "decision": "RETRY_REQUIRED",
        },
        {
            "engineering_take_id": take_id,
            "attempt_number": 2,
            "decision": "RETRY_REQUIRED",
        },
        {
            "engineering_take_id": take_id,
            "attempt_number": 3,
            "decision": "PASS",
        },
    ]

    retired = runner._prepare_failed_attempt_retirement(
        campaign_root=tmp_path,
        take_id=take_id,
        replacement_attempt_root=replacement,
        ledger=ledger,
    )

    assert len(retired) == 2
    for attempt_number in (1, 2):
        attempt_root = attempts_root / f"{take_id}__attempt_{attempt_number:02d}"
        assert (attempt_root / "respeaker_audio.wav").is_file()
        assert (attempt_root / "failed_raw_note.json").is_file()

    runner._finalize_failed_attempt_retirement(
        campaign_root=tmp_path,
        attempt_roots=retired,
    )

    for attempt_number in (1, 2):
        attempt_root = attempts_root / f"{take_id}__attempt_{attempt_number:02d}"
        assert [path.name for path in attempt_root.iterdir()] == [
            "failed_raw_note.json"
        ]
        note = json.loads(
            (attempt_root / "failed_raw_note.json").read_text(encoding="utf-8")
        )
        assert set(note) == {
            "attempt_number",
            "replacement_attempt_number",
            "take_id",
            "failure_cause",
            "prevention_guidance",
        }
        assert note["take_id"] == take_id
        assert note["attempt_number"] == attempt_number
        assert note["replacement_attempt_number"] == 3
    assert (replacement / "respeaker_audio.wav").read_bytes() == b"valid raw"


def test_runner_never_deletes_failed_raw_without_valid_replacement(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_failed_raw_safety_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    take_id = "s48prelim_002_low_level_reference"
    failed = (
        tmp_path
        / "attempts"
        / take_id
        / f"{take_id}__attempt_01"
    )
    failed.mkdir(parents=True)
    failed_raw = failed / "respeaker_audio.wav"
    failed_raw.write_bytes(b"retain me")
    (failed / "retry_report.json").write_text(
        '{"reasons":[{"code":"reference_alignment_failed"}]}',
        encoding="utf-8",
    )
    replacement = failed.parent / f"{take_id}__attempt_02"
    replacement.mkdir()
    (replacement / "respeaker_audio.wav").write_bytes(b"unsealed")
    ledger = [
        {
            "engineering_take_id": take_id,
            "attempt_number": 1,
            "decision": "RETRY_REQUIRED",
        },
        {
            "engineering_take_id": take_id,
            "attempt_number": 2,
            "decision": "PASS",
        },
    ]

    with pytest.raises(
        runner.S48PhysicalRehearsalError,
        match="replacement is valid",
    ):
        runner._prepare_failed_attempt_retirement(
            campaign_root=tmp_path,
            take_id=take_id,
            replacement_attempt_root=replacement,
            ledger=ledger,
        )

    assert failed_raw.read_bytes() == b"retain me"


def test_runner_zed_retry_note_prevents_schema_regression() -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_zed_retry_guidance_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    guidance = runner._prevention_guidance(["zed_full_replay_failed"])

    assert "canonical S4.2 SVO replay schema" in guidance
    assert "end-of-SVO" in guidance


def test_runner_never_finalizes_retirement_outside_campaign(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_retirement_path_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "failed_raw_note.json").write_text("{}", encoding="utf-8")
    protected = outside / "protected.bin"
    protected.write_bytes(b"preserve")

    with pytest.raises(
        runner.S48PhysicalRehearsalError,
        match="escapes campaign attempts",
    ):
        runner._finalize_failed_attempt_retirement(
            campaign_root=tmp_path / "campaign",
            attempt_roots=[str(outside)],
        )

    assert protected.read_bytes() == b"preserve"


def test_runner_atomically_replaces_retry_ledger_with_compacted_pass(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "run_s4_8_physical_rehearsal.py"
    spec = importlib.util.spec_from_file_location(
        "s48_compacted_ledger_runner",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    ledger_path = tmp_path / "attempt_ledger.jsonl"
    ledger_path.write_text(
        '{"decision":"RETRY_REQUIRED"}\n{"decision":"PASS"}\n',
        encoding="utf-8",
    )
    compacted = {
        "schema": "ias.s4_8.engineering_compacted_pass_ledger_record.v2",
        "decision": "PASS",
    }

    runner._replace_json_lines(ledger_path, [compacted])

    assert json.loads(ledger_path.read_text(encoding="utf-8")) == compacted
    assert "RETRY_REQUIRED" not in ledger_path.read_text(encoding="utf-8")
    assert list(tmp_path.glob(".attempt_ledger.jsonl.*.tmp")) == []


def test_mac_preflight_does_not_gate_on_power_or_work_focus() -> None:
    checks = {
        "ac_power": False,
        "model_identifier_matches": True,
        "notifications_suppressed": False,
        "os_build_matches": True,
        "os_version_matches": True,
        "output_channels_match": True,
        "output_device_matches": True,
        "output_sample_rate_matches": True,
        "reference_format_matches": True,
        "reference_hash_matches": True,
        "unmuted": True,
        "volume_matches": True,
        "work_focus_active": False,
    }
    report = {"frozen_checks": checks}

    acceptance = evaluate_mac_preflight_acceptance(report)

    assert acceptance["status"] == "passed"
    assert acceptance["power_requirement"] == "none"
    assert acceptance["work_focus_requirement"] == "none"
    assert report["frozen_checks"]["ac_power"] is False
    assert report["frozen_checks"]["work_focus_active"] is False


def test_v9_campaign_retains_70_percent_volume_without_focus_prompt() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "configs/s4_8_engineering_campaign.v1.json").read_text(
            encoding="utf-8"
        )
    )
    runner = (
        root / "scripts/run_s4_8_physical_rehearsal.py"
    ).read_text(encoding="utf-8")

    assert (
        config["protocol"]["identity"]
        == "s4_8_physical_engineering_rehearsal_stratum_aware_v7"
    )
    assert config["controller"]["version"] == "1.8"
    assert config["playback"]["system_volume_percent"] == 70
    assert config["playback"]["playback_helper_mac_path"].endswith(
        "_v9.swift"
    )
    assert config["playback"]["playback_helper_sha256"] == hashlib.sha256(
        (root / "scripts/s4_8_mac_playback.swift").read_bytes()
    ).hexdigest()
    assert config["playback"]["power_policy"] == "battery_allowed"
    assert "--operator-work-focus-confirmed" not in runner
