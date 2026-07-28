from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    S48PresealingGateError,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    DEFAULT_PRESEALING_CONFIG_V2,
    evaluate_capture_integrity_v2,
    read_pcm16_wav_strict,
)

RATE = 16_000


def _capture() -> np.ndarray:
    rng = np.random.default_rng(492)
    capture = rng.normal(0.0, 0.01, size=(20 * RATE, 6))
    return np.clip(capture, -0.5, 0.5)


def _evaluate(
    capture: np.ndarray,
    *,
    device_profile_id: str | None = "respeaker_usb_6ch_pcm16_v1",
    channel_map: list[str] | None = None,
) -> dict[str, object]:
    return evaluate_capture_integrity_v2(
        capture,
        sample_rate_hz=RATE,
        device_profile_id=device_profile_id,
        channel_map=(
            DEFAULT_PRESEALING_CONFIG_V2["expected_channel_map"]
            if channel_map is None
            else channel_map
        ),
        config=DEFAULT_PRESEALING_CONFIG_V2,
    )


def _reason_codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["reasons"]}


def _write_pcm16(path: Path, capture: np.ndarray) -> None:
    encoded = np.rint(capture * 32768.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(capture.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(encoded.tobytes())


def test_strict_wav_reader_accepts_pcm16_and_rejects_width_or_truncation(
    tmp_path: Path,
) -> None:
    capture = _capture()[:400]
    valid = tmp_path / "valid.wav"
    width24 = tmp_path / "width24.wav"
    truncated = tmp_path / "truncated.wav"
    _write_pcm16(valid, capture)
    with wave.open(str(width24), "wb") as stream:
        stream.setnchannels(6)
        stream.setsampwidth(3)
        stream.setframerate(RATE)
        stream.writeframes(b"\0" * (400 * 6 * 3))
    truncated.write_bytes(valid.read_bytes()[:-1])

    decoded, rate = read_pcm16_wav_strict(valid)

    assert decoded.shape == capture.shape
    assert rate == RATE
    for invalid in (width24, truncated):
        with pytest.raises(S48PresealingGateError):
            read_pcm16_wav_strict(invalid)


def test_strict_wav_reader_rejects_inconsistent_riff_and_frame_sizes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bad_sizes.wav"
    capture = _capture()[:40]
    _write_pcm16(path, capture)
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, 4, len(data) + 100)
    path.write_bytes(data)

    with pytest.raises(S48PresealingGateError):
        read_pcm16_wav_strict(path)


def test_capture_integrity_rejects_frozen_repeated_buffers() -> None:
    capture = _capture()
    capture[8 * RATE : 9 * RATE] = np.tile(
        capture[8 * RATE : 8 * RATE + 2_000],
        (8, 1),
    )

    report = _evaluate(capture)

    assert report["decision"] == "RETRY_REQUIRED"
    assert "frozen_or_repeated_capture_buffer" in _reason_codes(report)


def test_capture_integrity_rejects_suspicious_duplicate_microphones() -> None:
    capture = _capture()
    capture[:, 3] = capture[:, 2]

    report = _evaluate(capture)

    assert report["decision"] == "RETRY_REQUIRED"
    assert "suspicious_duplicate_microphone_channels" in _reason_codes(report)


def test_capture_integrity_rejects_distributed_clipping_without_long_run() -> None:
    capture = _capture()
    capture[::500, 2] = 32767.0 / 32768.0

    report = _evaluate(capture)

    assert report["decision"] == "RETRY_REQUIRED"
    assert "distributed_clipping_limit_exceeded" in _reason_codes(report)
    assert report["metrics"]["maximum_clip_run_samples_by_channel"][0] == 1


@pytest.mark.parametrize(
    ("device_profile_id", "channel_map", "reason"),
    [
        (None, None, "device_profile_identity_missing"),
        (
            "wrong_profile",
            None,
            "device_profile_identity_mismatch",
        ),
        (
            "respeaker_usb_6ch_pcm16_v1",
            [
                "playback_left",
                "playback_right",
                "microphone_1",
                "microphone_0",
                "microphone_2",
                "microphone_3",
            ],
            "channel_map_identity_mismatch",
        ),
    ],
)
def test_capture_integrity_requires_exact_device_and_channel_map(
    device_profile_id: str | None,
    channel_map: list[str] | None,
    reason: str,
) -> None:
    report = evaluate_capture_integrity_v2(
        _capture(),
        sample_rate_hz=RATE,
        device_profile_id=device_profile_id,
        channel_map=channel_map,
        config=DEFAULT_PRESEALING_CONFIG_V2,
    )

    assert report["decision"] == "RETRY_REQUIRED"
    assert reason in _reason_codes(report)
