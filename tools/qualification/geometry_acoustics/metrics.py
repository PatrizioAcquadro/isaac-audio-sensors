"""Quantitative R9.2 metrics and fixed acceptance thresholds."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

TDOA_TOLERANCE_SAMPLES = 1.0
MIN_ALIGNED_CORRELATION = 0.99
FREE_FIELD_DROP_DB = -6.0206
FREE_FIELD_TOLERANCE_DB = 2.0
DOOR_OPEN_GAIN_DB = 3.0
ASSEMBLY_EQUIVALENCE_DB = 1.0
PARTITION_SUM_TOLERANCE_DB = 3.0
SECOND_PARTITION_MIN_DROP_DB = 8.0
TRANSMISSION_TONE_TOLERANCE_DB = 4.0
TRANSMISSION_DYNAMIC_RANGE_DB = 40.0
UPDATE_P95_MS = {1: 100.0, 4: 250.0}
BLOCK_P95_MS = 20.0


@dataclass(frozen=True, slots=True)
class PhaseMetrics:
    microphone_pairs: tuple[str, ...]
    measured_lags_samples: tuple[int, ...]
    expected_lags_samples: tuple[float, ...]
    lag_errors_samples: tuple[float, ...]
    aligned_correlations: tuple[float, ...]
    passed: bool


def transmission_loss_db_to_amplitude(loss_db: ArrayLike) -> NDArray[np.float64]:
    """Convert authored transmission loss to Direct Effect waveform gains."""

    loss = np.asarray(loss_db, dtype=np.float64)
    if np.any(~np.isfinite(loss)) or np.any(loss < 0.0):
        raise ValueError("transmission loss must contain finite non-negative dB.")
    return np.power(10.0, -loss / 20.0)


def interpolate_transmission_amplitude(
    source_frequencies_hz: ArrayLike,
    source_loss_db: ArrayLike,
    target_frequencies_hz: ArrayLike,
) -> NDArray[np.float64]:
    """Interpolate loss on log frequency, then convert it to amplitude."""

    source_frequencies = np.asarray(source_frequencies_hz, dtype=np.float64)
    source_loss = np.asarray(source_loss_db, dtype=np.float64)
    targets = np.asarray(target_frequencies_hz, dtype=np.float64)
    if source_frequencies.ndim != 1 or source_frequencies.size < 2:
        raise ValueError("source frequencies must be a one-dimensional curve.")
    if source_loss.shape != source_frequencies.shape:
        raise ValueError("source loss must match source frequencies.")
    if np.any(source_frequencies <= 0.0) or np.any(np.diff(source_frequencies) <= 0.0):
        raise ValueError("source frequencies must be positive and increasing.")
    if np.any(targets <= 0.0):
        raise ValueError("target frequencies must be positive.")
    interpolated_db = np.interp(
        np.log10(targets), np.log10(source_frequencies), source_loss
    )
    return transmission_loss_db_to_amplitude(interpolated_db)


def expected_tdoa_samples(
    source_xyz_m: Sequence[float],
    microphone_xyz_m: Sequence[Sequence[float]],
    *,
    sample_rate_hz: int,
    sound_speed_m_s: float = 343.0,
) -> tuple[float, ...]:
    source = np.asarray(source_xyz_m, dtype=np.float64)
    microphones = np.asarray(microphone_xyz_m, dtype=np.float64)
    distances = np.linalg.norm(microphones - source, axis=1)
    return tuple((distances - distances[0]) * sample_rate_hz / sound_speed_m_s)


def _normalized_aligned_correlation(
    reference: NDArray[np.float64], signal: NDArray[np.float64], lag: int
) -> float:
    if lag >= 0:
        ref_segment = reference[: reference.size - lag or None]
        signal_segment = signal[lag:]
    else:
        ref_segment = reference[-lag:]
        signal_segment = signal[: signal.size + lag]
    denominator = float(np.linalg.norm(ref_segment) * np.linalg.norm(signal_segment))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(ref_segment, signal_segment) / denominator)


def _fractional_shift(
    samples: NDArray[np.float64], shift_samples: float
) -> NDArray[np.float64]:
    if shift_samples == 0.0:
        return samples.copy()
    guard = math.ceil(abs(shift_samples)) + 64
    padded = np.pad(samples, (guard, guard), mode="constant")
    transform_size = 1 << (int(padded.size) - 1).bit_length()
    cycles_per_sample = np.fft.rfftfreq(transform_size)
    phase = np.exp(-2j * np.pi * cycles_per_sample * shift_samples)
    shifted = np.fft.irfft(
        np.fft.rfft(padded, n=transform_size) * phase,
        n=transform_size,
    )
    return np.asarray(shifted[guard : guard + samples.size], dtype=np.float64)


def phase_metrics(
    samples: ArrayLike,
    expected_lags_samples: Sequence[float],
    microphone_ids: Sequence[str] | None = None,
) -> PhaseMetrics:
    """Measure all microphone-pair lags without modifying provider output."""

    channels = np.asarray(samples, dtype=np.float64)
    if channels.ndim != 2 or channels.shape[0] != len(expected_lags_samples):
        raise ValueError("samples and expected lags must describe the same channels.")
    ids = tuple(microphone_ids or (str(index) for index in range(channels.shape[0])))
    if len(ids) != channels.shape[0] or len(set(ids)) != len(ids):
        raise ValueError("microphone_ids must match channels and be unique.")
    pairs: list[str] = []
    measured: list[int] = []
    expected: list[float] = []
    correlations: list[float] = []
    for left in range(channels.shape[0]):
        for right in range(left + 1, channels.shape[0]):
            reference = channels[left]
            channel = channels[right]
            cross_correlation = np.correlate(channel, reference, mode="full")
            lag = int(np.argmax(cross_correlation) - (reference.size - 1))
            pairs.append(f"{ids[left]}->{ids[right]}")
            measured.append(lag)
            expected.append(
                float(expected_lags_samples[right] - expected_lags_samples[left])
            )
            aligned = _fractional_shift(channel, -expected[-1])
            correlations.append(_normalized_aligned_correlation(reference, aligned, 0))
    errors = tuple(
        abs(float(measured_lag) - float(expected_lag))
        for measured_lag, expected_lag in zip(measured, expected, strict=True)
    )
    passed = (
        max(errors, default=math.inf) <= TDOA_TOLERANCE_SAMPLES
        and min(correlations, default=0.0) >= MIN_ALIGNED_CORRELATION
    )
    return PhaseMetrics(
        microphone_pairs=tuple(pairs),
        measured_lags_samples=tuple(measured),
        expected_lags_samples=tuple(expected),
        lag_errors_samples=errors,
        aligned_correlations=tuple(correlations),
        passed=passed,
    )


def rms_db(samples: ArrayLike) -> float:
    values = np.asarray(samples, dtype=np.float64)
    rms = float(np.sqrt(np.mean(np.square(values))))
    return -math.inf if rms == 0.0 else 20.0 * math.log10(rms)


def amplitude_drops_db(levels: Sequence[ArrayLike]) -> tuple[float, ...]:
    db = tuple(rms_db(level) for level in levels)
    return tuple(right - left for left, right in zip(db, db[1:], strict=False))


def free_field_amplitude_passes(levels: Sequence[ArrayLike]) -> bool:
    drops = amplitude_drops_db(levels)
    return len(drops) == 2 and all(
        abs(drop - FREE_FIELD_DROP_DB) <= FREE_FIELD_TOLERANCE_DB for drop in drops
    )


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sequence.")
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile_value))


def summarize_timings(values_ms: Sequence[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile(values_ms, 50.0),
        "p95_ms": percentile(values_ms, 95.0),
    }


def performance_passes(block_ms: Sequence[float]) -> bool:
    return percentile(block_ms, 95.0) <= BLOCK_P95_MS


def dynamic_update_passes(update_ms: Sequence[float], environment_count: int) -> bool:
    try:
        threshold = UPDATE_P95_MS[environment_count]
    except KeyError as error:
        raise ValueError("environment_count must be one or four.") from error
    return percentile(update_ms, 95.0) <= threshold


def band_differences_db(
    reference_levels: Mapping[str, float], observed_levels: Mapping[str, float]
) -> dict[str, float]:
    if reference_levels.keys() != observed_levels.keys():
        raise ValueError("band inventories must match.")
    return {
        band: float(observed_levels[band] - reference_levels[band])
        for band in reference_levels
    }


def tone_levels_db(
    samples: ArrayLike,
    *,
    sample_rate_hz: int,
    frequencies_hz: Sequence[float] = (400.0, 2500.0, 15000.0),
) -> dict[str, float]:
    """Measure deterministic fixture tones at their exact FFT bins."""

    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("tone samples must be a non-empty mono signal.")
    spectrum = np.abs(np.fft.rfft(values))
    bins = np.fft.rfftfreq(values.size, 1.0 / sample_rate_hz)
    levels: dict[str, float] = {}
    for frequency_hz in frequencies_hz:
        index = int(np.argmin(np.abs(bins - frequency_hz)))
        magnitude = float(spectrum[index])
        levels[str(int(frequency_hz))] = (
            -math.inf if magnitude == 0.0 else 20.0 * math.log10(magnitude)
        )
    return levels


def tone_losses_db(
    reference: ArrayLike,
    observed: ArrayLike,
    *,
    frequencies_hz: Sequence[float] = (400.0, 2500.0, 15000.0),
) -> dict[str, float]:
    reference_levels = tone_levels_db(
        reference, sample_rate_hz=48_000, frequencies_hz=frequencies_hz
    )
    observed_levels = tone_levels_db(
        observed, sample_rate_hz=48_000, frequencies_hz=frequencies_hz
    )
    return {
        band: float(reference_levels[band] - observed_levels[band])
        for band in reference_levels
    }
