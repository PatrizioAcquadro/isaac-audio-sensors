from __future__ import annotations

import hashlib
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
        self.stdout = None
        self.stderr = None

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float) -> int:
        del timeout
        return self.returncode


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
        mac_continuous_asset_path="continuous.wav",
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
        lambda command: next(processes),
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
        lambda command: process,
    )
    reference_path = tmp_path / "reference.wav"
    reference_path.write_bytes(b"exact reference")
    backend = _backend(tmp_path)

    prepared = backend.prepare_playback(reference_path)
    playback = backend.start_playback(prepared)
    stopped = backend.stop_playback(playback)

    assert prepared["authenticated_reference_sha256"] == hashlib.sha256(
        reference_path.read_bytes()
    ).hexdigest()
    assert prepared["continuous_asset_path"] == "continuous.wav"
    assert playback["process_identity"] == "ssh_mac_afplay"
    assert stopped["exit_status"] == 0
    assert stopped["controller_requested_termination"] is False
