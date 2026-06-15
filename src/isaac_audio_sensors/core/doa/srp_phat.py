"""SRP-PHAT steered-response-power direction estimation over waveforms.

The estimator computes PHAT-weighted generalized cross-correlations once per
microphone pair and steers them over a deterministic direction grid: azimuth
in degrees clockwise from array forward, and elevation in degrees up from the
array's forward/right plane when the microphone layout has full 3D rank.
Planar layouts steer azimuth only and report ``elevation_deg=None``.

This module hosts the waveform-domain estimator family; future estimators
(e.g. MUSIC) should follow the same input contract so backends can dispatch
on an estimator id.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.microphone_array import microphone_positions_rank_xyz


@dataclass(frozen=True, slots=True)
class SrpPhatResult:
    """Peak of the steered-response power grid with prominence diagnostics."""

    bearing_deg: float
    elevation_deg: float | None
    peak_power: float
    mean_power: float
    azimuth_step_deg: float
    elevation_step_deg: float | None
    grid_point_count: int
    pair_count: int


def srp_phat_direction(
    waveforms: Mapping[str, Sequence[float]],
    *,
    mic_positions_m: Mapping[str, tuple[float, float, float]],
    sample_rate_hz: int,
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
    azimuth_step_deg: float = 2.0,
    elevation_step_deg: float = 5.0,
    max_delay_s: float | None = None,
    interp: int = 8,
) -> SrpPhatResult:
    """Estimate the dominant arrival direction with SRP-PHAT.

    ``waveforms`` and ``mic_positions_m`` are keyed by microphone id and use
    array-local positions, so the returned bearing/elevation are in the
    public array-local convention. ``max_delay_s`` defaults to the array
    aperture divided by the speed of sound.
    """

    mic_ids = tuple(waveforms)
    if len(mic_ids) < 2:
        raise ValueError("srp_phat requires at least two microphones.")
    missing = [mic_id for mic_id in mic_ids if mic_id not in mic_positions_m]
    if missing:
        raise ValueError(f"mic_positions_m is missing microphone ids {missing}.")
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
        raise ValueError("speed_of_sound_mps must be positive and finite.")
    if azimuth_step_deg <= 0.0 or azimuth_step_deg > 90.0:
        raise ValueError("azimuth_step_deg must be in (0, 90].")
    if elevation_step_deg <= 0.0 or elevation_step_deg > 90.0:
        raise ValueError("elevation_step_deg must be in (0, 90].")
    if interp <= 0:
        raise ValueError("interp must be positive.")
    if max_delay_s is not None and max_delay_s < 0.0:
        raise ValueError("max_delay_s must be non-negative.")

    positions = {
        mic_id: np.asarray(mic_positions_m[mic_id], dtype=float)
        for mic_id in mic_ids
    }
    demeaned: dict[str, np.ndarray] = {}
    for mic_id in mic_ids:
        wave = np.asarray(waveforms[mic_id], dtype=float).reshape(-1)
        if wave.size == 0:
            raise ValueError("signals must not be empty.")
        if not np.all(np.isfinite(wave)):
            raise ValueError(f"{mic_id} must contain only finite values.")
        if not np.any(wave):
            raise ValueError("signals must contain at least one non-zero sample.")
        demeaned[mic_id] = wave - float(np.mean(wave))

    aperture = max(
        float(np.linalg.norm(positions[left] - positions[right]))
        for index, left in enumerate(mic_ids)
        for right in mic_ids[index + 1 :]
    )
    if max_delay_s is None:
        max_delay_s = aperture / speed_of_sound_mps + 1.0 / float(sample_rate_hz)

    directions, bearings, elevations = _direction_grid(
        [tuple(positions[mic_id]) for mic_id in mic_ids],
        azimuth_step_deg=azimuth_step_deg,
        elevation_step_deg=elevation_step_deg,
    )

    power = np.zeros(directions.shape[0], dtype=float)
    pair_count = 0
    rfft_cache: dict[tuple[str, int], np.ndarray] = {}

    def _cached_rfft(mic_id: str, n_fft: int) -> np.ndarray:
        key = (mic_id, n_fft)
        if key not in rfft_cache:
            rfft_cache[key] = np.fft.rfft(demeaned[mic_id], n=n_fft)
        return rfft_cache[key]

    for index, left in enumerate(mic_ids):
        for right in mic_ids[index + 1 :]:
            pair_count += 1
            n_fft = _next_power_of_two(
                demeaned[left].size + demeaned[right].size - 1
            )
            spectrum = _cached_rfft(left, n_fft) * np.conj(
                _cached_rfft(right, n_fft)
            )
            magnitude = np.abs(spectrum)
            spectrum = np.divide(
                spectrum,
                magnitude,
                out=np.zeros_like(spectrum),
                where=magnitude > 1e-15,
            )
            n_corr = n_fft * interp
            correlation = np.fft.irfft(spectrum, n=n_corr)
            max_shift = min(
                n_corr // 2,
                int(math.ceil(max_delay_s * float(sample_rate_hz) * float(interp))),
            )
            window = np.concatenate(
                (correlation[-max_shift:], correlation[: max_shift + 1])
            )
            # Plane wave from direction d arrives at mic i at -(p_i . d) / c,
            # so the left-vs-right pair delay is -((p_left - p_right) . d) / c.
            pair_delay_s = (
                -(directions @ (positions[left] - positions[right]))
                / speed_of_sound_mps
            )
            lag_index = (
                pair_delay_s * float(sample_rate_hz) * float(interp) + max_shift
            )
            power += np.interp(
                lag_index,
                np.arange(window.size, dtype=float),
                window,
            )

    peak_index = int(np.argmax(power))
    elevation = elevations[peak_index] if elevations is not None else None
    return SrpPhatResult(
        bearing_deg=float(bearings[peak_index]),
        elevation_deg=None if elevation is None else float(elevation),
        peak_power=float(power[peak_index]),
        mean_power=float(np.mean(power)),
        azimuth_step_deg=float(azimuth_step_deg),
        elevation_step_deg=(
            None if elevations is None else float(elevation_step_deg)
        ),
        grid_point_count=int(power.size),
        pair_count=pair_count,
    )


def srp_phat_confidence(result: SrpPhatResult) -> float:
    """Normalized peak prominence of a steered-response grid in ``[0, 1]``."""

    if result.peak_power <= 0.0:
        return 0.0
    return max(
        0.0,
        min(1.0, (result.peak_power - result.mean_power) / result.peak_power),
    )


def _direction_grid(
    positions: list[tuple[float, float, float]],
    *,
    azimuth_step_deg: float,
    elevation_step_deg: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    azimuths = np.arange(0.0, 360.0, azimuth_step_deg, dtype=float)
    if microphone_positions_rank_xyz(positions) >= 3:
        elevation_count = int(math.floor(90.0 / elevation_step_deg))
        elevations = (
            np.arange(-elevation_count, elevation_count + 1, dtype=float)
            * elevation_step_deg
        )
        azimuth_grid = np.repeat(azimuths, elevations.size)
        elevation_grid = np.tile(elevations, azimuths.size)
    else:
        azimuth_grid = azimuths
        elevation_grid = None

    azimuth_rad = np.radians(azimuth_grid)
    if elevation_grid is None:
        cos_elevation = np.ones_like(azimuth_rad)
        sin_elevation = np.zeros_like(azimuth_rad)
    else:
        elevation_rad = np.radians(elevation_grid)
        cos_elevation = np.cos(elevation_rad)
        sin_elevation = np.sin(elevation_rad)
    directions = np.column_stack(
        (
            cos_elevation * np.cos(azimuth_rad),
            cos_elevation * np.sin(azimuth_rad),
            sin_elevation,
        )
    )
    return directions, azimuth_grid, elevation_grid


def _next_power_of_two(value: int) -> int:
    return 1 << max(1, int(value - 1).bit_length())
