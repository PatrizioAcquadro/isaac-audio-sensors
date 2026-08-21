"""NumPy-only deterministic channel-response operations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from isaac_audio_sensors.core.effects.config import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    FrequencyResponsePointConfig,
)


def apply_channel_response(
    samples: np.ndarray,
    *,
    mic_ids: Sequence[str],
    sample_rate_hz: int,
    config: ChannelResponseConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply FIR, gain, polarity and delay in canonical order."""

    microphones = config.microphones or {}
    applied_ids = tuple(
        mic_id
        for mic_id in mic_ids
        if mic_id in microphones and not is_noop(microphones[mic_id])
    )
    if not applied_ids:
        return samples, {}

    output = samples.copy()
    for mic_index, mic_id in enumerate(mic_ids):
        mic_config = microphones.get(mic_id)
        if mic_config is None or is_noop(mic_config):
            continue
        waveform = output[mic_index]
        if mic_config.frequency_response is not None:
            taps = design_frequency_response_fir(
                mic_config.frequency_response,
                sample_rate_hz=sample_rate_hz,
            )
            waveform = _linear_convolve_compensated(waveform, taps)
        if mic_config.gain_db is not None:
            waveform = waveform * (10.0 ** (mic_config.gain_db / 20.0))
        if mic_config.polarity is not None:
            waveform = (
                np.negative(waveform) if mic_config.polarity == -1 else waveform * 1
            )
        if mic_config.delay_s is not None and mic_config.delay_s != 0.0:
            waveform = fractional_delay(
                waveform,
                delay_s=mic_config.delay_s,
                sample_rate_hz=sample_rate_hz,
            )
        output[mic_index] = waveform
    return output, channel_response_diagnostics(config, mic_ids)


def design_frequency_response_fir(
    points: Sequence[FrequencyResponsePointConfig],
    *,
    sample_rate_hz: int,
) -> np.ndarray:
    """Design the frozen odd-length, Hann-windowed Type-I linear-phase FIR."""

    tap_count = response_tap_count(sample_rate_hz)
    dense_size = _next_power_of_two(max(16_384, tap_count * 16))
    frequencies = np.fft.rfftfreq(dense_size, d=1.0 / float(sample_rate_hz))
    point_frequencies = np.asarray(
        [float(point.frequency_hz) for point in points], dtype=np.float64
    )
    point_amplitudes = 10.0 ** (
        np.asarray([float(point.magnitude_db) for point in points], dtype=np.float64)
        / 20.0
    )
    target = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    zero_phase = np.fft.irfft(target, n=dense_size)
    centered = np.fft.fftshift(zero_phase)
    midpoint = dense_size // 2
    half = tap_count // 2
    taps = centered[midpoint - half : midpoint + half + 1].copy()
    taps *= np.hanning(tap_count)
    return np.asarray(taps, dtype=np.float64)


def response_tap_count(sample_rate_hz: int) -> int:
    """Return ``next_odd(clamp(ceil(fs * 0.010667), 129, 2049))``."""

    count = min(2049, max(129, math.ceil(sample_rate_hz * 0.010667)))
    return count if count % 2 else count + 1


def fractional_delay(
    samples: np.ndarray,
    *,
    delay_s: float,
    sample_rate_hz: int,
) -> np.ndarray:
    """Apply a zero-extended full-window fractional delay with one rFFT."""

    if samples.size == 0 or delay_s == 0.0:
        return samples.copy()
    guard = math.ceil(abs(delay_s * sample_rate_hz)) + 64
    padded = np.pad(samples, (guard, guard), mode="constant")
    transform_size = _next_power_of_two(int(padded.size))
    frequencies = np.fft.rfftfreq(transform_size, d=1.0 / float(sample_rate_hz))
    phase = np.exp(-2j * np.pi * frequencies * delay_s)
    delayed = np.fft.irfft(
        np.fft.rfft(padded, n=transform_size) * phase,
        n=transform_size,
    )
    return np.asarray(delayed[guard : guard + samples.size], dtype=np.float64)


def channel_response_diagnostics(
    config: ChannelResponseConfig,
    mic_ids: Sequence[str],
) -> dict[str, Any]:
    """Build deterministic frame diagnostics for configured non-noop channels."""

    microphones = config.microphones or {}
    applied = tuple(
        mic_id
        for mic_id in mic_ids
        if mic_id in microphones and not is_noop(microphones[mic_id])
    )
    if not applied:
        return {}
    return {
        "applied_mic_ids": applied,
        "gain_db": {
            mic_id: microphones[mic_id].gain_db
            for mic_id in applied
            if microphones[mic_id].gain_db is not None
        },
        "delay_s": {
            mic_id: microphones[mic_id].delay_s
            for mic_id in applied
            if microphones[mic_id].delay_s is not None
        },
        "polarity": {
            mic_id: microphones[mic_id].polarity
            for mic_id in applied
            if microphones[mic_id].polarity is not None
        },
    }


def metadata_channel_values(
    config: ChannelResponseConfig,
    mic_ids: Sequence[str],
) -> tuple[dict[str, float], dict[str, float], dict[str, int], dict[str, Any]]:
    """Return metadata-representable L0/L1 gain, delay, and polarity values."""

    microphones: Mapping[str, ChannelResponseMicConfig] = config.microphones or {}
    gains = {
        mic_id: float(microphones[mic_id].gain_db)
        for mic_id in mic_ids
        if mic_id in microphones and microphones[mic_id].gain_db is not None
    }
    delays = {
        mic_id: float(microphones[mic_id].delay_s)
        for mic_id in mic_ids
        if mic_id in microphones and microphones[mic_id].delay_s is not None
    }
    polarities = {
        mic_id: int(microphones[mic_id].polarity)
        for mic_id in mic_ids
        if mic_id in microphones and microphones[mic_id].polarity is not None
    }
    return gains, delays, polarities, channel_response_diagnostics(config, mic_ids)


def is_noop(config: ChannelResponseMicConfig) -> bool:
    """Return whether every channel field is absent."""

    return (
        config.gain_db is None
        and config.delay_s is None
        and config.polarity is None
        and config.frequency_response is None
    )


def _linear_convolve_compensated(samples: np.ndarray, taps: np.ndarray) -> np.ndarray:
    full_size = samples.size + taps.size - 1
    transform_size = _next_power_of_two(full_size)
    convolution = np.fft.irfft(
        np.fft.rfft(samples, n=transform_size) * np.fft.rfft(taps, n=transform_size),
        n=transform_size,
    )[:full_size]
    group_delay = taps.size // 2
    return np.asarray(
        convolution[group_delay : group_delay + samples.size],
        dtype=np.float64,
    )


def _next_power_of_two(value: int) -> int:
    return 1 if value <= 1 else 1 << (value - 1).bit_length()


__all__ = [
    "apply_channel_response",
    "channel_response_diagnostics",
    "design_frequency_response_fir",
    "fractional_delay",
    "metadata_channel_values",
    "response_tap_count",
]
