"""Waveform localization and analytic detection assembly."""

from __future__ import annotations

from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.occlusion import (
    occlusion_detection_diagnostics,
    occlusion_flag,
)
from isaac_audio_sensors.core.backends._analytic.diagnostics import (
    _ground_truth_bearing,
    _ground_truth_elevation,
    _rir_lengths,
    _rir_peak_delays,
)
from isaac_audio_sensors.core.backends._analytic.doa import estimate_doa_from_delays
from isaac_audio_sensors.core.backends._analytic.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends._analytic.rendering import (
    RenderedRoom,
    _max_microphone_spacing,
)
from isaac_audio_sensors.core.directivity import DIRECTIVITY_MODE
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    relative_delays_from_tdoa_matrix,
    rms_by_channel,
)
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.math_utils import angular_error_deg, norm, subtract
from isaac_audio_sensors.core.microphone_array import (
    layout_rank_xy,
    layout_rank_xyz,
)
from isaac_audio_sensors.core.scene import (
    deterministic_detection_id,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    DoaEstimate,
    MicrophoneArraySpec,
    Pose3D,
)


def assemble_detections(
    prepared: PreparedRoomFrame,
    rendered: RenderedRoom,
    *,
    backend_id: str,
    speed_of_sound_mps: float,
    ambiguity_policy: str,
    gcc_phat_interp: int,
    doa_estimator: str,
) -> tuple[list[AudioDetection], dict[str, dict[str, object]]]:
    """Localize every rendered source and assemble its public detection."""

    detections: list[AudioDetection] = []
    per_source_rir_summary: dict[str, dict[str, object]] = {}
    if not prepared.active:
        return detections, per_source_rir_summary

    environment = prepared.scene.environment
    assert environment is not None
    assert rendered.room is not None
    max_delay = (
        _max_microphone_spacing(rendered.microphone_environment_positions)
        / speed_of_sound_mps
        + 0.002
    )
    for index, source in enumerate(prepared.active):
        source_waveforms = {
            mic_id: rendered.premix[index, mic_index]
            for mic_index, mic_id in enumerate(prepared.mic_ids)
        }
        signals_active = all(np.any(waveform) for waveform in source_waveforms.values())
        if signals_active:
            tdoa_matrix, gcc_peaks = estimate_tdoa_diagnostics(
                source_waveforms,
                sample_rate_hz=prepared.sample_rate_hz,
                max_delay_s=max_delay,
                interp=gcc_phat_interp,
            )
            per_mic_delay_s = relative_delays_from_tdoa_matrix(
                tdoa_matrix,
                mic_ids=prepared.mic_ids,
                reference_mic_id=prepared.mic_ids[0],
            )
        else:
            tdoa_matrix = {
                f"{left}->{right}": 0.0
                for left in prepared.mic_ids
                for right in prepared.mic_ids
            }
            gcc_peaks = {key: 0.0 for key in tdoa_matrix}
            per_mic_delay_s = {mic_id: 0.0 for mic_id in prepared.mic_ids}
        per_mic_rms = rms_by_channel(source_waveforms)
        source_environment = rendered.source_environment_positions[source.source_id]
        rir_length_samples = _rir_lengths(
            rendered.room,
            prepared.mic_ids,
            source_index=index,
        )
        rir_peak_delay_s = _rir_peak_delays(
            rendered.room,
            prepared.mic_ids,
            prepared.sample_rate_hz,
            source_index=index,
        )
        waveform_sample_count = {
            mic_id: int(rendered.premix.shape[2]) for mic_id in prepared.mic_ids
        }
        direct_path_delay_s = {
            mic_id: norm(
                subtract(
                    source_environment,
                    rendered.microphone_environment_positions[mic_id],
                )
            )
            / speed_of_sound_mps
            for mic_id in prepared.mic_ids
        }
        ground_truth_bearing = _ground_truth_bearing(
            source.position_world,
            prepared.sensor,
        )
        ground_truth_elevation = _ground_truth_elevation(
            source.position_world,
            prepared.sensor,
        )
        doa, doa_estimator_diagnostics = _estimate_source_doa(
            sensor=prepared.sensor,
            source_waveforms=source_waveforms,
            per_mic_delay_s=per_mic_delay_s,
            sample_rate_hz=prepared.sample_rate_hz,
            max_delay_s=max_delay,
            signals_active=signals_active,
            doa_estimator=doa_estimator,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
            gcc_phat_interp=gcc_phat_interp,
        )
        oracle_bearing_error = (
            None
            if doa.estimated_bearing_deg is None or ground_truth_bearing is None
            else angular_error_deg(
                doa.estimated_bearing_deg,
                ground_truth_bearing,
            )
        )
        oracle_elevation_error = (
            None
            if doa.estimated_elevation_deg is None or ground_truth_elevation is None
            else abs(doa.estimated_elevation_deg - ground_truth_elevation)
        )
        occlusion = prepared.scene.occlusion_for(
            prepared.sensor.array_id,
            source.source_id,
        )
        detections.append(
            AudioDetection(
                detection_id=deterministic_detection_id(
                    frame_id=prepared.frame_id,
                    source_id=source.source_id,
                    index=index,
                ),
                source_id=source.source_id,
                class_label=source.class_label,
                detection_mode="scheduled_known_source",
                timestamp_ms=prepared.time_window.timestamp_ms,
                ground_truth_bearing_deg=ground_truth_bearing,
                ground_truth_elevation_deg=ground_truth_elevation,
                source_distance_m=norm(
                    subtract(
                        source.position_world,
                        prepared.sensor.position_world,
                    )
                ),
                doa=doa,
                source_pose=Pose3D.from_source(source),
                per_mic_delay_s=per_mic_delay_s,
                per_mic_rms=per_mic_rms,
                audio_asset_path=source.audio_asset_path,
                occluded=occlusion_flag(occlusion),
                diagnostics={
                    "backend": backend_id,
                    "physical_waveform": True,
                    "environment_id": environment.environment_id,
                    "environment_config": prepared.environment_config,
                    "environment_dimensions_m": (environment.dimensions_m),
                    "analytic_acoustics_options": {
                        "max_order": prepared.max_order,
                        "air_absorption": prepared.air_absorption,
                        "ray_tracing": prepared.ray_tracing,
                    },
                    "pyroomacoustics_version": getattr(
                        prepared.pra,
                        "__version__",
                        "unknown",
                    ),
                    "speed_of_sound_mps": speed_of_sound_mps,
                    "sample_rate_hz": prepared.sample_rate_hz,
                    "array_geometry_rank_xy": layout_rank_xy(prepared.sensor),
                    "array_geometry_rank_xyz": layout_rank_xyz(prepared.sensor),
                    "estimated_tdoa_matrix_s": tdoa_matrix,
                    "gcc_phat_peaks": gcc_peaks,
                    "gcc_phat_peak": gcc_peaks,
                    "direct_path_delay_s": direct_path_delay_s,
                    "oracle_bearing_error_deg": oracle_bearing_error,
                    "oracle_elevation_error_deg": oracle_elevation_error,
                    **doa_estimator_diagnostics,
                    "per_mic_rms": per_mic_rms,
                    "rir_length_samples": rir_length_samples,
                    "rir_peak_delay_s": rir_peak_delay_s,
                    "waveform_sample_count": waveform_sample_count,
                    "source_waveform_mode": rendered.scheduled[index].mode,
                    "source_nominal_gain_db": source.gain_db,
                    "microphone_nominal_gain_db": {
                        microphone.mic_id: microphone.gain_db
                        for microphone in prepared.sensor.microphones
                    },
                    "directivity": {
                        "mode": DIRECTIVITY_MODE,
                        "source_pattern": source.directivity.value,
                        "microphone_patterns": {
                            microphone.mic_id: microphone.directivity.value
                            for microphone in prepared.sensor.microphones
                        },
                    },
                    "scheduled_start_offset_samples": (
                        rendered.scheduled[index].start_offset_samples
                    ),
                    "scheduled_content_sample_count": (
                        rendered.scheduled[index].content_sample_count
                    ),
                    **(
                        {
                            "doppler_factor": rendered.doppler_factors[
                                source.source_id
                            ],
                            "doppler_waveform_rendered": abs(
                                rendered.doppler_factors[source.source_id] - 1.0
                            )
                            > 1e-9,
                        }
                        if source.source_id in rendered.doppler_factors
                        else {}
                    ),
                    "environment_source_position_m": source_environment,
                    "environment_microphone_positions_m": (
                        rendered.microphone_environment_positions
                    ),
                    **occlusion_detection_diagnostics(occlusion),
                },
            )
        )
        per_source_rir_summary[source.source_id] = {
            "rir_length_samples": rir_length_samples,
            "rir_peak_delay_s": rir_peak_delay_s,
            "waveform_sample_count": waveform_sample_count,
            "source_waveform_mode": rendered.scheduled[index].mode,
            "environment_source_position_m": source_environment,
            "environment_microphone_positions_m": (
                rendered.microphone_environment_positions
            ),
        }
    return detections, per_source_rir_summary


def _estimate_source_doa(
    *,
    sensor: MicrophoneArraySpec,
    source_waveforms: dict[str, np.ndarray],
    per_mic_delay_s: dict[str, float],
    sample_rate_hz: int,
    max_delay_s: float,
    signals_active: bool,
    doa_estimator: str,
    speed_of_sound_mps: float,
    ambiguity_policy: str,
    gcc_phat_interp: int,
) -> tuple[DoaEstimate, dict[str, Any]]:
    """Dispatch the configured waveform-domain DOA estimator."""

    if doa_estimator == "srp_phat" and signals_active:
        mic_positions = {
            microphone.mic_id: microphone.relative_position_m
            for microphone in sensor.microphones
        }
        result = srp_phat_direction(
            source_waveforms,
            mic_positions_m=mic_positions,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_delay_s=max_delay_s,
            interp=gcc_phat_interp,
        )
        elevation = result.elevation_deg
        doa = DoaEstimate(
            estimated_bearing_deg=result.bearing_deg,
            candidate_bearing_deg=(result.bearing_deg,),
            bearing_confidence=srp_phat_confidence(result),
            ambiguity_class=None,
            ambiguity_reason=None,
            estimated_elevation_deg=elevation,
            candidate_elevation_deg=(() if elevation is None else (elevation,)),
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
    diagnostics: dict[str, Any] = {"doa_estimator": "tdoa_least_squares"}
    if doa_estimator != "tdoa_least_squares":
        diagnostics["doa_estimator_requested"] = doa_estimator
    return (
        estimate_doa_from_delays(
            sensor=sensor,
            per_mic_delay_s=per_mic_delay_s,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
        ),
        diagnostics,
    )


__all__ = ["assemble_detections"]
