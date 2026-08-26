from __future__ import annotations

import numpy as np

from isaac_audio_sensors.kit.spectro import (
    mixdown,
    render_spectrogram_rgba,
    render_waveform_rgba,
    stft_db,
    waveform_envelope,
)


def _sine(frequency_hz: float, *, sample_rate_hz: int, duration_s: float = 0.25):
    t = np.arange(int(sample_rate_hz * duration_s)) / sample_rate_hz
    return 0.5 * np.sin(2.0 * np.pi * frequency_hz * t)


def test_mixdown_and_envelope():
    samples = np.array([[1.0, -1.0, 0.5, -0.5], [0.0, 0.0, 0.5, -0.5]])
    np.testing.assert_allclose(mixdown(samples), [0.5, -0.5, 0.5, -0.5])
    envelope = waveform_envelope(samples, bins=2)
    assert envelope.shape == (2, 2)
    assert envelope[0].tolist() == [-0.5, 0.5]
    assert waveform_envelope(np.zeros((1, 0)), bins=4).shape == (4, 2)


def test_stft_db_peaks_at_sine_frequency():
    sample_rate = 8_000
    samples = np.stack([_sine(1_000.0, sample_rate_hz=sample_rate, duration_s=0.5)])
    db = stft_db(samples, n_fft=512, hop=256)
    assert db.shape[0] == 257
    assert db.max() == 0.0
    assert db.min() >= -80.0
    assert abs(int(db.mean(axis=1).argmax()) - 64) <= 1


def test_waveform_and_spectrogram_rasters():
    samples = np.stack([_sine(440.0, sample_rate_hz=8_000)])
    waveform = render_waveform_rgba(samples, width=200, height=60)
    spectrogram = render_spectrogram_rgba(samples, width=120, height=64)

    assert waveform.shape == (60, 200, 4)
    assert waveform.dtype == np.uint8
    assert int((waveform[:, 100, 1] > 150).sum()) > 10
    assert spectrogram.shape == (64, 120, 4)
    assert spectrogram.dtype == np.uint8
    assert int(spectrogram[..., 1].max()) > 150
    assert render_waveform_rgba(np.zeros((1, 256)), width=50, height=20).shape == (
        20,
        50,
        4,
    )
