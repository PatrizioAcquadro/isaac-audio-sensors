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
    ) -> None:
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.interp = int(interp)
        self.max_delay_margin_s = float(max_delay_margin_s)

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        """Run the existing GCC-PHAT and least-squares computation unchanged."""

        waveforms, sensor, aperture = _ordered_inputs(
            samples,
            microphone_positions_m,
            sample_rate_hz,
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
        return result, {
            "doa_estimator": "tdoa_least_squares",
            "gcc_phat_peak": peak_values,
            "tdoa_matrix_s": tdoa_matrix_s,
        }


class SrpPhatEstimator:
    """Adapter exposing the existing SRP-PHAT function as a plugin object."""

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        azimuth_step_deg: float = 2.0,
        elevation_step_deg: float = 5.0,
        interp: int = 8,
        max_delay_margin_s: float = 0.002,
    ) -> None:
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.azimuth_step_deg = float(azimuth_step_deg)
        self.elevation_step_deg = float(elevation_step_deg)
        self.interp = int(interp)
        self.max_delay_margin_s = float(max_delay_margin_s)

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        """Run the existing SRP-PHAT computation and adapt its result type."""

        waveforms, _sensor, aperture = _ordered_inputs(
            samples,
            microphone_positions_m,
            sample_rate_hz,
        )
        from isaac_audio_sensors.core.doa.srp_phat import (
            srp_phat_confidence,
            srp_phat_direction,
        )

        positions = {
            mic_id: tuple(float(value) for value in microphone_positions_m[index])
            for index, mic_id in enumerate(waveforms)
        }
        result = srp_phat_direction(
            waveforms,
            mic_positions_m=positions,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=self.speed_of_sound_mps,
            azimuth_step_deg=self.azimuth_step_deg,
            elevation_step_deg=self.elevation_step_deg,
            max_delay_s=(
                aperture / self.speed_of_sound_mps + self.max_delay_margin_s
            ),
            interp=self.interp,
        )
        elevation = result.elevation_deg
        doa = DoaEstimate(
            estimated_bearing_deg=result.bearing_deg,
            candidate_bearing_deg=(result.bearing_deg,),
            bearing_confidence=srp_phat_confidence(result),
            estimated_elevation_deg=elevation,
            candidate_elevation_deg=() if elevation is None else (elevation,),
        )
        return doa, {
            "doa_estimator": "srp_phat",
            "srp_phat": {
                "azimuth_step_deg": result.azimuth_step_deg,
                "elevation_step_deg": result.elevation_step_deg,
                "grid_point_count": result.grid_point_count,
                "pair_count": result.pair_count,
                "peak_power": result.peak_power,
                "mean_power": result.mean_power,
            },
        }


def _ordered_inputs(
    samples: np.ndarray,
    microphone_positions_m: np.ndarray,
    sample_rate_hz: int,
) -> tuple[dict[str, np.ndarray], MicrophoneArraySpec, float]:
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

    mic_ids = tuple(f"channel_{index}" for index in range(values.shape[0]))
    waveforms = {
        mic_id: values[index]
        for index, mic_id in enumerate(mic_ids)
    }
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
    return waveforms, sensor, aperture


__all__ = ["GccPhatLeastSquaresEstimator", "SrpPhatEstimator"]
