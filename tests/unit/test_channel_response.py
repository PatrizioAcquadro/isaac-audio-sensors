"""Deterministic channel-response tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from isaac_audio_sensors.core.effects import (
    ChannelEffectsChain,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    FrequencyResponsePointConfig,
)
from isaac_audio_sensors.core.effects.channel_response import response_tap_count

SAMPLE_RATE_HZ = 48_000
EDGE_EXCLUSION = response_tap_count(SAMPLE_RATE_HZ) // 2 + 65
GAIN_TOLERANCE_DB = 0.05
DELAY_TOLERANCE_SAMPLES = 0.10
FREQUENCY_RESPONSE_TOLERANCE_DB = 0.25
RESPONSE_POINTS = (
    (100.0, -1.0),
    (1_000.0, 0.0),
    (4_000.0, -3.0),
    (12_000.0, 2.0),
    (20_000.0, -2.0),
)


def _effects(mic: ChannelResponseMicConfig) -> EffectsConfig:
    return EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"mic": mic},
        )
    )


def _apply(samples: np.ndarray, mic: ChannelResponseMicConfig) -> np.ndarray:
    output, diagnostics = ChannelEffectsChain(_effects(mic)).apply(
        samples,
        mic_ids=("mic",),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="channel_response_fixture",
    )
    assert diagnostics["channel_response"]["applied_mic_ids"] == ("mic",)
    return output


@pytest.mark.parametrize("frequency_hz", [1_000, 8_000])
@pytest.mark.parametrize("gain_db", [-12.0, -3.0, 6.0])
def test_tone_gain_recovery_meets_frozen_maximum_error(frequency_hz, gain_db):
    sample_count = 48_000
    time_s = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE_HZ
    samples = (0.1 * np.sin(2.0 * np.pi * frequency_hz * time_s))[None, :]

    output = _apply(samples, ChannelResponseMicConfig(gain_db=gain_db))

    usable = slice(EDGE_EXCLUSION, -EDGE_EXCLUSION)
    rms_in = float(np.sqrt(np.mean(samples[0, usable] ** 2)))
    rms_out = float(np.sqrt(np.mean(output[0, usable] ** 2)))
    recovered_db = 20.0 * math.log10(rms_out / rms_in)
    assert abs(recovered_db - gain_db) <= GAIN_TOLERANCE_DB


def _band_limited_probe() -> np.ndarray:
    sample_count = 16_384
    rng = np.random.default_rng(20_260_718)
    spectrum = np.fft.rfft(rng.standard_normal(sample_count))
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / SAMPLE_RATE_HZ)
    spectrum[(frequencies < 300.0) | (frequencies > 18_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=sample_count) * np.hanning(sample_count)
    return np.asarray(probe / np.max(np.abs(probe)), dtype=np.float64)


def _parabolic_absolute_correlation_lag(
    output: np.ndarray,
    source: np.ndarray,
) -> float:
    correlation = np.correlate(output, source, mode="full")
    magnitude = np.abs(correlation)
    peak = int(np.argmax(magnitude))
    left, center, right = magnitude[peak - 1 : peak + 2]
    offset = 0.5 * (left - right) / (left - 2.0 * center + right)
    return float(peak - (source.size - 1) + offset)


@pytest.mark.parametrize("delay_samples", [-3.25, -0.50, 0.50, 2.75])
def test_fractional_delay_recovery_meets_frozen_maximum_error(delay_samples):
    probe = _band_limited_probe()
    output = _apply(
        probe[None, :],
        ChannelResponseMicConfig(delay_s=delay_samples / SAMPLE_RATE_HZ),
    )

    recovered = _parabolic_absolute_correlation_lag(output[0], probe)
    assert abs(recovered - delay_samples) <= DELAY_TOLERANCE_SAMPLES


def test_polarity_is_exact_for_asymmetric_values_and_signed_zero():
    rng = np.random.default_rng(3_303)
    fixture = np.concatenate(
        (
            np.asarray([0.0, -0.0, 1.0, -2.0, 0.25, -0.125]),
            rng.standard_normal(257),
        )
    ).astype(np.float64)[None, :]

    output = _apply(fixture, ChannelResponseMicConfig(polarity=-1))
    expected = np.negative(fixture)

    assert np.array_equal(output, expected)
    assert output.tobytes(order="C") == expected.tobytes(order="C")


def _welch_h1(
    source: np.ndarray,
    output: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    nperseg = 8_192
    noverlap = 4_096
    step = nperseg - noverlap
    window = np.hanning(nperseg)
    s_xx = np.zeros(nperseg // 2 + 1, dtype=np.complex128)
    s_yx = np.zeros_like(s_xx)
    for start in range(0, source.size - nperseg + 1, step):
        x_spectrum = np.fft.rfft(source[start : start + nperseg] * window)
        y_spectrum = np.fft.rfft(output[start : start + nperseg] * window)
        s_xx += x_spectrum * np.conj(x_spectrum)
        s_yx += y_spectrum * np.conj(x_spectrum)
    frequencies = np.fft.rfftfreq(nperseg, d=1.0 / SAMPLE_RATE_HZ)
    return frequencies, s_yx / s_xx


def test_frequency_response_welch_h1_meets_frozen_passband_error():
    rng = np.random.default_rng(20_260_718)
    samples = rng.standard_normal(2**18).astype(np.float64)[None, :]
    points = tuple(
        FrequencyResponsePointConfig(frequency_hz=frequency, magnitude_db=db)
        for frequency, db in RESPONSE_POINTS
    )

    output = _apply(
        samples,
        ChannelResponseMicConfig(frequency_response=points),
    )

    usable = slice(EDGE_EXCLUSION, -EDGE_EXCLUSION)
    frequencies, transfer = _welch_h1(samples[0, usable], output[0, usable])
    point_frequencies = np.asarray([point[0] for point in RESPONSE_POINTS])
    point_amplitudes = 10.0 ** (
        np.asarray([point[1] for point in RESPONSE_POINTS]) / 20.0
    )
    target = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    errors_db = np.abs(
        20.0 * np.log10(np.maximum(np.abs(transfer), np.finfo(float).tiny))
        - 20.0 * np.log10(target)
    )
    passband = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    assert float(np.max(errors_db[passband])) <= FREQUENCY_RESPONSE_TOLERANCE_DB


def test_response_tap_policy_is_513_at_48_khz():
    assert response_tap_count(SAMPLE_RATE_HZ) == 513


def test_active_channel_response_keeps_silence_finite_and_exactly_zero():
    samples = np.zeros((1, 2_048), dtype=np.float64)
    output = _apply(
        samples,
        ChannelResponseMicConfig(
            gain_db=6.0,
            delay_s=0.5 / SAMPLE_RATE_HZ,
            polarity=-1,
        ),
    )
    assert np.array_equal(output, samples)
    assert np.all(np.isfinite(output))
