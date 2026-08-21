"""Unit tests for WAV reading, waveform/spectrogram rasters, and audition."""

from __future__ import annotations

import struct
import sys
from types import ModuleType

import numpy as np
import pytest

from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.kit.audition import AuditionPlayer
from isaac_audio_sensors.kit.spectro import (
    mixdown,
    render_spectrogram_rgba,
    render_waveform_rgba,
    stft_db,
    waveform_envelope,
)


def _wav_bytes(
    samples: np.ndarray,
    *,
    sample_rate_hz: int = 16000,
    audio_format: int = 3,
) -> bytes:
    channels, _ = samples.shape
    interleaved = np.ascontiguousarray(samples.T)
    if audio_format == 3:
        bits = 32
        data = interleaved.astype("<f4").tobytes()
    else:
        bits = 16
        data = np.clip(interleaved * 32767.0, -32768, 32767).astype("<i2").tobytes()
    block_align = channels * bits // 8
    fmt = struct.pack(
        "<HHIIHH",
        audio_format,
        channels,
        sample_rate_hz,
        sample_rate_hz * block_align,
        block_align,
        bits,
    )
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _sine(frequency_hz: float, *, sample_rate_hz: int, duration_s: float = 0.25):
    t = np.arange(int(sample_rate_hz * duration_s)) / sample_rate_hz
    return 0.5 * np.sin(2.0 * np.pi * frequency_hz * t)


@pytest.mark.parametrize("audio_format", [3, 1])
def test_read_wav_stdlib_parses_float32_and_pcm16(tmp_path, monkeypatch, audio_format):
    monkeypatch.setitem(sys.modules, "soundfile", None)  # force stdlib reader
    sample_rate = 8000
    samples = np.stack(
        [
            _sine(440.0, sample_rate_hz=sample_rate),
            _sine(880.0, sample_rate_hz=sample_rate),
        ]
    )
    path = tmp_path / "frame.wav"
    path.write_bytes(
        _wav_bytes(samples, sample_rate_hz=sample_rate, audio_format=audio_format)
    )

    data = read_wav(path)
    assert data.sample_rate_hz == sample_rate
    assert data.channel_count == 2
    assert data.frame_count == samples.shape[1]
    assert data.duration_s == pytest.approx(0.25)
    tolerance = 1e-6 if audio_format == 3 else 1e-3
    np.testing.assert_allclose(data.samples, samples, atol=tolerance)


def test_read_wav_stdlib_rejects_unsupported_encoding(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "soundfile", None)
    samples = np.zeros((1, 16), dtype=np.float64)
    blob = bytearray(_wav_bytes(samples, audio_format=3))
    blob[20:22] = struct.pack("<H", 7)  # mu-law
    path = tmp_path / "bad.wav"
    path.write_bytes(bytes(blob))
    with pytest.raises(ValueError, match="Unsupported WAV encoding"):
        read_wav(path)


def test_read_wav_uses_soundfile_when_available(tmp_path):
    pytest.importorskip("soundfile")
    sample_rate = 8000
    samples = np.stack([_sine(440.0, sample_rate_hz=sample_rate)])
    path = tmp_path / "sf.wav"
    path.write_bytes(_wav_bytes(samples, sample_rate_hz=sample_rate))
    data = read_wav(path)
    assert data.channel_count == 1
    assert data.sample_rate_hz == sample_rate
    np.testing.assert_allclose(data.samples, samples, atol=1e-6)


def test_mixdown_and_envelope():
    samples = np.array([[1.0, -1.0, 0.5, -0.5], [0.0, 0.0, 0.5, -0.5]])
    mono = mixdown(samples)
    np.testing.assert_allclose(mono, [0.5, -0.5, 0.5, -0.5])
    envelope = waveform_envelope(samples, bins=2)
    assert envelope.shape == (2, 2)
    assert envelope[0, 0] == -0.5
    assert envelope[0, 1] == 0.5
    assert waveform_envelope(np.zeros((1, 0)), bins=4).shape == (4, 2)


def test_stft_db_peaks_at_sine_frequency():
    sample_rate = 8000
    samples = np.stack([_sine(1000.0, sample_rate_hz=sample_rate, duration_s=0.5)])
    db = stft_db(samples, n_fft=512, hop=256)
    assert db.shape[0] == 257
    assert db.max() == 0.0
    assert db.min() >= -80.0
    peak_bin = int(db.mean(axis=1).argmax())
    expected_bin = round(1000.0 * 512 / sample_rate)
    assert abs(peak_bin - expected_bin) <= 1


def test_render_waveform_and_spectrogram_shapes():
    sample_rate = 8000
    samples = np.stack([_sine(440.0, sample_rate_hz=sample_rate)])
    wave = render_waveform_rgba(samples, width=200, height=60)
    assert wave.shape == (60, 200, 4)
    assert wave.dtype == np.uint8
    # The sine fills a tall green band around the center line.
    assert int((wave[:, 100, 1] > 150).sum()) > 10

    spec = render_spectrogram_rgba(samples, width=120, height=64)
    assert spec.shape == (64, 120, 4)
    assert spec.dtype == np.uint8
    assert int(spec[..., 1].max()) > 150  # bright energy somewhere

    silent = render_waveform_rgba(np.zeros((1, 256)), width=50, height=20)
    assert silent.shape == (20, 50, 4)


class _FakeKitAudioPlayer:
    instances: list[_FakeKitAudioPlayer] = []

    def __init__(self) -> None:
        self.played: list[str] = []
        self.stopped = False
        _FakeKitAudioPlayer.instances.append(self)

    def play_sound(self, path: str) -> None:
        self.played.append(path)

    def stop_sound(self) -> None:
        self.stopped = True


def test_audition_player_uses_omni_audioplayer(tmp_path, monkeypatch):
    _FakeKitAudioPlayer.instances = []
    omni = ModuleType("omni")
    omni.__path__ = []
    module = ModuleType("omni.audioplayer")
    module.AudioPlayer = _FakeKitAudioPlayer
    omni.audioplayer = module
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.audioplayer", module)
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav_bytes(np.zeros((1, 8))))

    player = AuditionPlayer()
    status = player.play(wav)
    assert "omni.audioplayer" in status
    assert _FakeKitAudioPlayer.instances[0].played == [str(wav)]

    stop_status = player.stop()
    assert "stopped" in stop_status
    assert _FakeKitAudioPlayer.instances[0].stopped is True
    assert "nothing is playing" in player.stop()


def test_audition_player_reports_missing_file(tmp_path):
    player = AuditionPlayer()
    status = player.play(tmp_path / "missing.wav")
    assert "no WAV" in status


def test_audition_player_falls_back_to_system_player(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "omni.audioplayer", None)
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav_bytes(np.zeros((1, 8))))
    opened: list[str] = []
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    player = AuditionPlayer()
    status = player.play(wav)
    assert "system audio player" in status
    assert opened and opened[0].startswith("file://")
