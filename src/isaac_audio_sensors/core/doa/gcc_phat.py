"""Waveform-derived GCC-PHAT TDOA utilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class GccPhatDelay:
    """One pairwise GCC-PHAT delay estimate."""

    delay_s: float
    peak_value: float
    sample_shift: float
    max_delay_s: float | None


def gcc_phat_delay(
    signal: Sequence[float],
    reference_signal: Sequence[float],
    *,
    sample_rate_hz: int,
    max_delay_s: float | None = None,
    interp: int = 8,
) -> GccPhatDelay:
    """Estimate the delay of ``signal`` relative to ``reference_signal``.

    A positive delay means ``signal`` arrives later than ``reference_signal``.
    ``max_delay_s`` should normally be bounded by the microphone-array aperture
    divided by the speed of sound.
    """

    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    if interp <= 0:
        raise ValueError("interp must be positive.")
    if max_delay_s is not None and max_delay_s < 0.0:
        raise ValueError("max_delay_s must be non-negative.")

    sig = _as_waveform(signal, "signal")
    ref = _as_waveform(reference_signal, "reference_signal")
    if sig.size == 0 or ref.size == 0:
        raise ValueError("signals must not be empty.")
    if not np.any(sig) or not np.any(ref):
        raise ValueError("signals must contain at least one non-zero sample.")

    sig = sig - float(np.mean(sig))
    ref = ref - float(np.mean(ref))
    n_fft = _next_power_of_two(sig.size + ref.size - 1)
    spectrum = np.fft.rfft(sig, n=n_fft) * np.conj(np.fft.rfft(ref, n=n_fft))
    magnitude = np.abs(spectrum)
    spectrum = np.divide(
        spectrum,
        magnitude,
        out=np.zeros_like(spectrum),
        where=magnitude > 1e-15,
    )

    n_corr = n_fft * interp
    correlation = np.fft.irfft(spectrum, n=n_corr)
    max_shift = n_corr // 2
    if max_delay_s is not None:
        max_shift = min(
            max_shift,
            int(round(max_delay_s * float(sample_rate_hz) * float(interp))),
        )
    window = np.concatenate((correlation[-max_shift:], correlation[: max_shift + 1]))
    shifts = np.arange(-max_shift, max_shift + 1, dtype=float)
    peak_index = int(np.argmax(np.abs(window)))
    sample_shift = float(shifts[peak_index]) / float(interp)
    return GccPhatDelay(
        delay_s=sample_shift / float(sample_rate_hz),
        peak_value=float(window[peak_index]),
        sample_shift=sample_shift,
        max_delay_s=max_delay_s,
    )


def estimate_tdoa_matrix(
    waveforms: Mapping[str, Sequence[float]],
    *,
    sample_rate_hz: int,
    max_delay_s: float | None = None,
    interp: int = 8,
) -> dict[str, float]:
    """Return pairwise TDOA estimates in seconds for all microphone pairs."""

    mic_ids = tuple(waveforms)
    matrix: dict[str, float] = {}
    for left in mic_ids:
        for right in mic_ids:
            if left == right:
                matrix[f"{left}->{right}"] = 0.0
                continue
            matrix[f"{left}->{right}"] = gcc_phat_delay(
                waveforms[left],
                waveforms[right],
                sample_rate_hz=sample_rate_hz,
                max_delay_s=max_delay_s,
                interp=interp,
            ).delay_s
    return matrix


def estimate_tdoa_diagnostics(
    waveforms: Mapping[str, Sequence[float]],
    *,
    sample_rate_hz: int,
    max_delay_s: float | None = None,
    interp: int = 8,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return pairwise TDOA estimates and GCC-PHAT peak diagnostics."""

    mic_ids = tuple(waveforms)
    delays: dict[str, float] = {}
    peaks: dict[str, float] = {}
    for left in mic_ids:
        for right in mic_ids:
            key = f"{left}->{right}"
            if left == right:
                delays[key] = 0.0
                peaks[key] = 1.0
                continue
            result = gcc_phat_delay(
                waveforms[left],
                waveforms[right],
                sample_rate_hz=sample_rate_hz,
                max_delay_s=max_delay_s,
                interp=interp,
            )
            delays[key] = result.delay_s
            peaks[key] = result.peak_value
    return delays, peaks


def relative_delays_from_tdoa_matrix(
    tdoa_matrix_s: Mapping[str, float],
    *,
    mic_ids: Sequence[str],
    reference_mic_id: str | None = None,
) -> dict[str, float]:
    """Convert pairwise TDOA values into reference-relative per-mic delays."""

    if not mic_ids:
        raise ValueError("mic_ids must not be empty.")
    reference = reference_mic_id or mic_ids[0]
    if reference not in mic_ids:
        raise ValueError("reference_mic_id must be present in mic_ids.")
    delays = {reference: 0.0}
    for mic_id in mic_ids:
        if mic_id == reference:
            continue
        delays[mic_id] = float(tdoa_matrix_s[f"{mic_id}->{reference}"])
    return delays


def rms_by_channel(
    waveforms: Mapping[str, Sequence[float]],
) -> dict[str, float]:
    """Compute RMS amplitude per waveform channel."""

    rms: dict[str, float] = {}
    for mic_id, waveform in waveforms.items():
        values = _as_waveform(waveform, mic_id)
        if values.size == 0:
            rms[mic_id] = 0.0
        else:
            rms[mic_id] = float(np.sqrt(np.mean(values * values)))
    return rms


def _as_waveform(values: Sequence[float], name: str) -> np.ndarray:
    waveform = np.asarray(values, dtype=float).reshape(-1)
    if not np.all(np.isfinite(waveform)):
        raise ValueError(f"{name} must contain only finite values.")
    return waveform


def _next_power_of_two(value: int) -> int:
    return 1 << max(1, int(value - 1).bit_length())
