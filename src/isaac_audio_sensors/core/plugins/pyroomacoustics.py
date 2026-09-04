"""Lazy PyRoomAcoustics SRP-PHAT direction-estimator adapter."""

from __future__ import annotations

import importlib
import math
import re
from typing import Any

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.plugins.adapters import (
    _apply_reliability,
    _has_spatial_variation,
    _maximum_rms,
    _ordered_inputs,
    _probability,
    _unresolved,
    _xy_rank,
)
from isaac_audio_sensors.core.types import DoaEstimate

_SUPPORTED_VERSION_MIN = (0, 10, 1)
_SUPPORTED_VERSION_MAX = (0, 11, 0)


class PyroomacousticsSrpEstimator:
    """Run PyRoomAcoustics SRP-PHAT on the current mixture block only."""

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        nfft: int = 512,
        hop: int = 256,
        frequency_range_hz: tuple[float, float] = (300.0, 6000.0),
        azimuth_step_deg: float = 2.0,
        elevation_step_deg: float = 5.0,
        minimum_reliability: float = 0.06,
        minimum_rms: float = 1e-8,
    ) -> None:
        self.speed_of_sound_mps = _positive(
            speed_of_sound_mps,
            "speed_of_sound_mps",
        )
        self.nfft = int(nfft)
        self.hop = int(hop)
        if self.nfft < 2 or self.nfft & (self.nfft - 1):
            raise ValueError("nfft must be a power of two greater than one.")
        if self.hop <= 0 or self.hop > self.nfft:
            raise ValueError("hop must be in [1, nfft].")
        if len(frequency_range_hz) != 2:
            raise ValueError("frequency_range_hz must contain two values.")
        minimum_hz = _non_negative(
            frequency_range_hz[0],
            "frequency_range_hz[0]",
        )
        maximum_hz = _positive(
            frequency_range_hz[1],
            "frequency_range_hz[1]",
        )
        if minimum_hz >= maximum_hz:
            raise ValueError("frequency_range_hz must be strictly increasing.")
        self.frequency_range_hz = (minimum_hz, maximum_hz)
        self.azimuth_step_deg = _grid_step(
            azimuth_step_deg,
            "azimuth_step_deg",
        )
        self.elevation_step_deg = _grid_step(
            elevation_step_deg,
            "elevation_step_deg",
        )
        self.minimum_reliability = _probability(
            minimum_reliability,
            "minimum_reliability",
        )
        self.minimum_rms = _non_negative(minimum_rms, "minimum_rms")

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        """Estimate one direction from a bounded, past-and-present STFT."""

        _waveforms, _sensor, _aperture = _ordered_inputs(
            samples,
            microphone_positions_m,
            sample_rate_hz,
        )
        positions = np.asarray(microphone_positions_m, dtype=float)
        if positions.shape[0] < 3 or _xy_rank(positions) < 2:
            return _unresolved(
                estimator_id="pyroomacoustics_srp",
                ambiguity_class="unsupported_geometry",
                reason=(
                    "PyRoom SRP requires at least three non-collinear "
                    "microphones in array-local XY."
                ),
                reliability=0.0,
                threshold=self.minimum_reliability,
            )
        if np.asarray(samples).shape[1] < self.nfft:
            return _unresolved(
                estimator_id="pyroomacoustics_srp",
                ambiguity_class="insufficient_context",
                reason=f"PyRoom SRP requires at least {self.nfft} samples.",
                reliability=0.0,
                threshold=self.minimum_reliability,
            )
        if _maximum_rms(samples) <= self.minimum_rms:
            return _unresolved(
                estimator_id="pyroomacoustics_srp",
                ambiguity_class="low_information",
                reason="Signal RMS does not exceed the estimator noise floor.",
                reliability=0.0,
                threshold=self.minimum_reliability,
            )
        if not _has_spatial_variation(samples):
            return _unresolved(
                estimator_id="pyroomacoustics_srp",
                ambiguity_class="unobservable_azimuth",
                reason="Waveforms contain no observable inter-channel delay.",
                reliability=0.0,
                threshold=self.minimum_reliability,
            )

        nyquist_hz = float(sample_rate_hz) / 2.0
        frequency_range = (
            self.frequency_range_hz[0],
            min(self.frequency_range_hz[1], np.nextafter(nyquist_hz, 0.0)),
        )
        if frequency_range[0] >= frequency_range[1]:
            raise ValueError(
                "frequency_range_hz contains no bins below the sample-rate Nyquist."
            )

        pra, version = _import_supported_pyroomacoustics()
        spectra = _stft(np.asarray(samples, dtype=float), self.nfft, self.hop)
        centered_positions = positions - np.mean(positions, axis=0, keepdims=True)
        rank_xyz = int(
            np.linalg.matrix_rank(centered_positions[1:] - centered_positions[0])
        )
        azimuth = np.radians(
            np.arange(0.0, 360.0, self.azimuth_step_deg, dtype=float)
        )
        if rank_xyz >= 3:
            elevation_count = int(math.floor(90.0 / self.elevation_step_deg))
            elevation = (
                np.arange(-elevation_count, elevation_count + 1, dtype=float)
                * self.elevation_step_deg
            )
            azimuth_grid = np.repeat(azimuth, elevation.size)
            colatitude_grid = np.radians(90.0 - np.tile(elevation, azimuth.size))
            estimator = pra.doa.SRP(
                centered_positions.T,
                int(sample_rate_hz),
                self.nfft,
                c=self.speed_of_sound_mps,
                num_src=1,
                dim=3,
                azimuth=azimuth_grid,
                colatitude=colatitude_grid,
            )
        else:
            estimator = pra.doa.SRP(
                centered_positions[:, :2].T,
                int(sample_rate_hz),
                self.nfft,
                c=self.speed_of_sound_mps,
                num_src=1,
                azimuth=azimuth,
            )
        frequencies_hz = np.fft.rfftfreq(self.nfft, 1.0 / float(sample_rate_hz))
        allowed_bins = np.flatnonzero(
            (frequencies_hz >= frequency_range[0])
            & (frequencies_hz <= frequency_range[1])
        )
        if allowed_bins.size == 0:
            raise ValueError("frequency_range_hz contains no discrete STFT bins.")
        bin_energy = np.mean(np.abs(spectra[:, allowed_bins, :]) ** 2, axis=(0, 2))
        median_energy = float(np.median(bin_energy))
        selected = allowed_bins[
            bin_energy
            >= max(
                4.0 * median_energy,
                0.1 * float(np.max(bin_energy)),
            )
        ]
        if selected.size < 4:
            selected = allowed_bins
        estimator.locate_sources(spectra, freq_bins=selected)
        grid_values = np.asarray(estimator.grid.values, dtype=float)
        if grid_values.size == 0 or not np.all(np.isfinite(grid_values)):
            raise RuntimeError("PyRoom SRP returned an invalid response grid.")

        peak_index = int(np.argmax(grid_values))
        bearing_deg = float(np.degrees(estimator.grid.azimuth[peak_index]))
        elevation_deg = None
        if rank_xyz >= 3:
            elevation_deg = float(
                90.0 - np.degrees(estimator.grid.colatitude[peak_index])
            )
        peak = float(grid_values[peak_index])
        mean = float(np.mean(grid_values))
        microphone_count = positions.shape[0]
        pair_count = microphone_count * (microphone_count - 1) / 2.0
        incoherent_floor = float(microphone_count / pair_count)
        coherent_ceiling = float(microphone_count * microphone_count / pair_count)
        coherent_excess = float(
            np.clip(
                (peak - incoherent_floor)
                / max(coherent_ceiling - incoherent_floor, np.finfo(float).eps),
                0.0,
                1.0,
            )
        )
        contrast = float(
            np.clip((peak - mean) / max(peak, np.finfo(float).eps), 0.0, 1.0)
        )
        reliability = coherent_excess * contrast
        doa = DoaEstimate(
            estimated_bearing_deg=bearing_deg,
            candidate_bearing_deg=(bearing_deg,),
            bearing_confidence=reliability,
            estimated_elevation_deg=elevation_deg,
            candidate_elevation_deg=(
                () if elevation_deg is None else (elevation_deg,)
            ),
        )
        doa = _apply_reliability(
            doa,
            reliability=reliability,
            threshold=self.minimum_reliability,
        )
        return doa, {
            "doa_estimator": "pyroomacoustics_srp",
            "pyroomacoustics_version": version,
            "stft": {
                "nfft": self.nfft,
                "hop": self.hop,
                "snapshot_count": int(spectra.shape[2]),
                "frequency_range_hz": frequency_range,
                "frequency_bin_count": int(selected.size),
                "frequency_bin_selection": "observed_energy_support",
            },
            "srp_phat": {
                "azimuth_step_deg": self.azimuth_step_deg,
                "elevation_step_deg": (
                    self.elevation_step_deg if rank_xyz >= 3 else None
                ),
                "grid_point_count": int(grid_values.size),
                "pair_count": int(pair_count),
                "peak_power": peak,
                "mean_power": mean,
                "incoherent_floor": incoherent_floor,
                "coherent_ceiling": coherent_ceiling,
                "coherent_excess": coherent_excess,
                "grid_contrast": contrast,
            },
            "observation_samples": int(np.asarray(samples).shape[1]),
            "observation_duration_s": (
                float(np.asarray(samples).shape[1]) / float(sample_rate_hz)
            ),
            "reliability_score": reliability,
            "minimum_reliability": self.minimum_reliability,
            "resolved": doa.estimated_bearing_deg is not None,
        }


def _stft(samples: np.ndarray, nfft: int, hop: int) -> np.ndarray:
    window = np.hanning(nfft)
    starts = range(0, samples.shape[1] - nfft + 1, hop)
    frames = np.stack([samples[:, start : start + nfft] * window for start in starts])
    return np.fft.rfft(frames, n=nfft, axis=2).transpose(1, 2, 0)


def _import_supported_pyroomacoustics() -> tuple[Any, str]:
    try:
        module = importlib.import_module("pyroomacoustics")
    except ImportError as exc:
        raise RuntimeError(
            "PyRoom SRP requires the 'room' optional dependencies."
        ) from exc
    version = str(getattr(module, "__version__", ""))
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise RuntimeError(
            f"Cannot validate pyroomacoustics version {version!r}."
        )
    parsed = tuple(int(part) for part in match.groups())
    if not (
        _SUPPORTED_VERSION_MIN <= parsed < _SUPPORTED_VERSION_MAX
    ):
        raise RuntimeError(
            "PyRoom SRP is qualified only for pyroomacoustics>=0.10.1,<0.11; "
            f"found {version or 'unknown'}."
        )
    return module, version


def _positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be positive and finite.")
    return number


def _non_negative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return number


def _grid_step(value: float, name: str) -> float:
    number = _positive(value, name)
    if number > 90.0:
        raise ValueError(f"{name} must be in (0, 90].")
    return number


__all__ = ["PyroomacousticsSrpEstimator"]
