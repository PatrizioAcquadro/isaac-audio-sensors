"""Thin plugin adapters over the existing DOA numerical functions."""

from __future__ import annotations

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.types import (
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSpec,
)


class GccPhatLeastSquaresEstimator:
    """GCC-PHAT delays followed by the existing least-squares DOA solver."""

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        interp: int = 8,
        max_delay_margin_s: float = 0.002,
        minimum_reliability: float = 0.0,
        minimum_rms: float = 1e-8,
    ) -> None:
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.interp = int(interp)
        self.max_delay_margin_s = float(max_delay_margin_s)
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
        """Run the existing GCC-PHAT and least-squares computation unchanged."""

        values, waveforms, sensor, aperture = _least_squares_inputs(
            samples,
            microphone_positions_m,
            sample_rate_hz,
        )
        if _maximum_rms(values) <= self.minimum_rms:
            return _unresolved(
                estimator_id="tdoa_least_squares",
                ambiguity_class="low_information",
                reason="Signal RMS does not exceed the estimator noise floor.",
                reliability=0.0,
                threshold=self.minimum_reliability,
            )
        if values.shape[0] > 2 and not _has_spatial_variation(values):
            return _unresolved(
                estimator_id="tdoa_least_squares",
                ambiguity_class="unobservable_azimuth",
                reason="Waveforms contain no observable inter-channel delay.",
                reliability=0.0,
                threshold=self.minimum_reliability,
            )
        from isaac_audio_sensors.core.backends._analytic.doa import (
            estimate_doa_from_delays,
        )
        from isaac_audio_sensors.core.doa.gcc_phat import (
            estimate_tdoa_diagnostics,
            relative_delays_from_tdoa_matrix,
        )

        max_delay_s = aperture / self.speed_of_sound_mps + self.max_delay_margin_s
        tdoa_matrix_s, peak_values = estimate_tdoa_diagnostics(
            waveforms,
            sample_rate_hz=sample_rate_hz,
            max_delay_s=max_delay_s,
            interp=self.interp,
        )
        mic_ids = tuple(waveforms)
        per_mic_delay_s = relative_delays_from_tdoa_matrix(
            tdoa_matrix_s,
            mic_ids=mic_ids,
        )
        result = estimate_doa_from_delays(
            sensor=sensor,
            per_mic_delay_s=per_mic_delay_s,
            speed_of_sound_mps=self.speed_of_sound_mps,
        )
        pair_peaks = [
            abs(float(peak_values[f"{left}->{right}"]))
            for index, left in enumerate(mic_ids)
            for right in mic_ids[index + 1 :]
        ]
        gcc_strength = float(
            np.clip(np.median(pair_peaks) * float(self.interp), 0.0, 1.0)
        )
        reliability = float(result.bearing_confidence) * gcc_strength
        result = _apply_reliability(
            result,
            reliability=reliability,
            threshold=self.minimum_reliability,
        )
        return result, {
            "doa_estimator": "tdoa_least_squares",
            "gcc_phat_peak": peak_values,
            "gcc_phat_pair_strength": gcc_strength,
            "tdoa_matrix_s": tdoa_matrix_s,
            "reliability_score": reliability,
            "minimum_reliability": self.minimum_reliability,
            "resolved": result.estimated_bearing_deg is not None,
        }


def _apply_reliability(
    estimate: DoaEstimate,
    *,
    reliability: float,
    threshold: float,
) -> DoaEstimate:
    reliability = float(np.clip(reliability, 0.0, 1.0))
    if estimate.estimated_bearing_deg is None:
        return estimate
    if reliability < threshold:
        return DoaEstimate(
            estimated_bearing_deg=None,
            candidate_bearing_deg=estimate.candidate_bearing_deg,
            bearing_confidence=0.0,
            ambiguity_class="low_information",
            ambiguity_reason=(
                f"Estimator-local reliability {reliability:.6g} is below "
                f"the configured threshold {threshold:.6g}."
            ),
            candidate_elevation_deg=estimate.candidate_elevation_deg,
        )
    return DoaEstimate(
        estimated_bearing_deg=estimate.estimated_bearing_deg,
        candidate_bearing_deg=estimate.candidate_bearing_deg,
        bearing_sector=estimate.bearing_sector,
        bearing_confidence=reliability,
        ambiguity_class=estimate.ambiguity_class,
        ambiguity_reason=estimate.ambiguity_reason,
        estimated_elevation_deg=estimate.estimated_elevation_deg,
        candidate_elevation_deg=estimate.candidate_elevation_deg,
    )


def _unresolved(
    *,
    estimator_id: str,
    ambiguity_class: str,
    reason: str,
    reliability: float,
    threshold: float,
) -> tuple[DoaEstimate, dict[str, object]]:
    estimate = DoaEstimate(
        estimated_bearing_deg=None,
        bearing_confidence=0.0,
        ambiguity_class=ambiguity_class,
        ambiguity_reason=reason,
    )
    return estimate, {
        "doa_estimator": estimator_id,
        "reliability_score": reliability,
        "minimum_reliability": threshold,
        "resolved": False,
    }


def _maximum_rms(samples: np.ndarray) -> float:
    values = np.asarray(samples, dtype=float)
    return float(np.max(np.sqrt(np.mean(values * values, axis=1))))


def _has_spatial_variation(samples: np.ndarray) -> bool:
    values = np.asarray(samples, dtype=float)
    demeaned = values - np.mean(values, axis=1, keepdims=True)
    signal_rms = float(np.sqrt(np.mean(demeaned * demeaned)))
    if signal_rms <= np.finfo(float).eps:
        return False
    spatial = demeaned - np.mean(demeaned, axis=0, keepdims=True)
    spatial_rms = float(np.sqrt(np.mean(spatial * spatial)))
    return spatial_rms / signal_rms > 1e-6


def _xy_rank(positions: np.ndarray) -> int:
    values = np.asarray(positions, dtype=float)
    return int(np.linalg.matrix_rank(values[1:, :2] - values[0, :2]))


def _probability(value: float, name: str) -> float:
    number = float(value)
    if not np.isfinite(number) or number < 0.0 or number > 1.0:
        raise ValueError(f"{name} must be finite and in [0, 1].")
    return number


def _non_negative(value: float, name: str) -> float:
    number = float(value)
    if not np.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return number


def _validate_doa_inputs(
    samples: np.ndarray,
    microphone_positions_m: np.ndarray,
    sample_rate_hz: int,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(samples, dtype=float)
    positions = np.asarray(microphone_positions_m, dtype=float)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] == 0:
        raise ValueError("samples must have shape [at least 2 channels, samples].")
    if positions.shape != (values.shape[0], 3):
        raise ValueError(
            "microphone_positions_m must have shape [channels, 3] matching samples."
        )
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(positions)):
        raise ValueError("samples and microphone_positions_m must be finite.")
    if int(sample_rate_hz) <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    return values, positions


def _least_squares_inputs(
    samples: np.ndarray,
    microphone_positions_m: np.ndarray,
    sample_rate_hz: int,
) -> tuple[np.ndarray, dict[str, np.ndarray], MicrophoneArraySpec, float]:
    values, positions = _validate_doa_inputs(
        samples,
        microphone_positions_m,
        sample_rate_hz,
    )

    mic_ids = tuple(f"channel_{index}" for index in range(values.shape[0]))
    waveforms = {mic_id: values[index] for index, mic_id in enumerate(mic_ids)}
    microphones = tuple(
        MicrophoneSpec(
            mic_id=mic_id,
            relative_position_m=tuple(float(value) for value in positions[index]),
        )
        for index, mic_id in enumerate(mic_ids)
    )
    sensor = MicrophoneArraySpec(
        array_id="plugin_doa_array",
        prim_path="/PluginDoaArray",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=int(sample_rate_hz),
    )
    aperture = max(
        float(np.linalg.norm(positions[left] - positions[right]))
        for left in range(positions.shape[0])
        for right in range(left + 1, positions.shape[0])
    )
    return values, waveforms, sensor, aperture


__all__ = ["GccPhatLeastSquaresEstimator"]
