"""Optional pyroomacoustics-backed room simulation path."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
    MaterialResolution,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.backends.tdoa import estimate_doa_from_delays
from isaac_audio_sensors.core.constants import (
    DEFAULT_SPEED_OF_SOUND_MPS,
    ROOM_CLAMP_MARGIN_M,
)
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    relative_delays_from_tdoa_matrix,
    rms_by_channel,
)
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.doppler import source_doppler_factor
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import (
    DirectivityConfig,
    EffectsConfig,
)
from isaac_audio_sensors.core.effects.directivity import (
    apply_pair_directivity,
    directivity_diagnostics,
    microphone_world_orientation,
    resolve_pattern,
)
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    basis_from_quaternion,
    bearing_from_components,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import (
    layout_rank_xy,
    layout_rank_xyz,
    microphone_world_positions,
    validate_tdoa_array,
)
from isaac_audio_sensors.core.motion import (
    WindowMotionPlan,
    motion_segment_diagnostics,
)
from isaac_audio_sensors.core.scene import (
    active_sources,
    deterministic_detection_id,
    deterministic_frame_id,
    deterministic_frame_name,
    occlusion_band_attenuation_db,
    occlusion_detection_diagnostics,
    occlusion_flag,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    Pose3D,
    RoomAcousticsSpec,
)

_SECONDARY_TONE_RATIO = 1.618033988749895
_SECONDARY_TONE_GAIN = 0.6
_TWO_TONE_PEAK = 1.0 + _SECONDARY_TONE_GAIN
_EDGE_RAMP_S = 0.004
_IMPULSE_SPIKES_S = ((0.004, 1.0),)
_PULSE_SPIKES_S = ((0.004, 1.0), (0.010, -0.65), (0.017, 0.4))


# Waveform-domain DOA estimator ids accepted by the room backend; future
# estimators (e.g. MUSIC) register here and dispatch in _estimate_source_doa.
DOA_ESTIMATOR_IDS = ("tdoa_least_squares", "srp_phat")


class RoomAcousticsBackend:
    """Optional shoebox-room backend using pyroomacoustics and GCC-PHAT.

    All active sources share one room per frame, so microphone signals are
    true mixtures; per-source diagnostics come from the simulation premix.
    """

    backend_id = "room_acoustics"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        source_waveform_duration_s: float = 0.08,
        gcc_phat_interp: int = 8,
        waveform_writer: WaveformSink | None = None,
        doa_estimator: str = "tdoa_least_squares",
        effects: EffectsConfig | None = None,
        runtime_profile: str = "waveform_fidelity",
        window_motion: WindowMotionPlan | None = None,
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if source_waveform_duration_s <= 0.0:
            raise ValueError("source_waveform_duration_s must be positive.")
        if doa_estimator not in DOA_ESTIMATOR_IDS:
            raise ValueError(
                f"doa_estimator must be one of {sorted(DOA_ESTIMATOR_IDS)}."
            )
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
        # Retained for API compatibility: generated sources now emit
        # continuously over their scheduled interval instead of a fixed-length
        # per-window probe.
        self.source_waveform_duration_s = float(source_waveform_duration_s)
        self.gcc_phat_interp = int(gcc_phat_interp)
        self.waveform_writer = waveform_writer
        self.doa_estimator = doa_estimator
        self.effects = EffectsConfig() if effects is None else effects
        self.runtime_profile = runtime_profile
        self.window_motion = window_motion
        self.effects_chain = ChannelEffectsChain(self.effects)

    @staticmethod
    def is_available() -> bool:
        """Return whether the optional pyroomacoustics dependency imports."""

        try:
            importlib.import_module("pyroomacoustics")
        except ImportError:
            return False
        return True

    def _estimate_source_doa(
        self,
        *,
        sensor: MicrophoneArraySpec,
        source_waveforms: dict[str, np.ndarray],
        per_mic_delay_s: dict[str, float],
        sample_rate_hz: int,
        max_delay_s: float,
        signals_active: bool,
    ) -> tuple[DoaEstimate, dict[str, Any]]:
        """Dispatch the configured waveform-domain DOA estimator.

        Silent windows fall back to the delay-based estimator because steered
        response power is undefined on all-zero signals.
        """

        if self.doa_estimator == "srp_phat" and signals_active:
            mic_positions = {
                microphone.mic_id: microphone.relative_position_m
                for microphone in sensor.microphones
            }
            result = srp_phat_direction(
                source_waveforms,
                mic_positions_m=mic_positions,
                sample_rate_hz=sample_rate_hz,
                speed_of_sound_mps=self.speed_of_sound_mps,
                max_delay_s=max_delay_s,
                interp=self.gcc_phat_interp,
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
        if self.doa_estimator != "tdoa_least_squares":
            diagnostics["doa_estimator_requested"] = self.doa_estimator
        return (
            estimate_doa_from_delays(
                sensor=sensor,
                per_mic_delay_s=per_mic_delay_s,
                speed_of_sound_mps=self.speed_of_sound_mps,
                ambiguity_policy=self.ambiguity_policy,
            ),
            diagnostics,
        )

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        if self.backend_id == "room_acoustics_srp" and len(sensor.microphones) == 2:
            raise UnsupportedEffectError(
                "room_acoustics_srp requires at least three microphones for an "
                "unambiguous localization claim"
            )
        validate_tdoa_array(sensor)
        if scene.room is None:
            raise ValueError("room_acoustics requires scene.room to be configured.")
        segments_per_window = self.effects.motion.segments_per_window
        if segments_per_window > 1 and self.window_motion is None:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires a live "
                "bracketed window-motion plan."
            )
        frame_id = deterministic_frame_id(
            backend_id=self.backend_id,
            stage_id=scene.stage_id,
            array_id=sensor.array_id,
            timestamp_ms=time_window.timestamp_ms,
            frame_index=time_window.frame_index,
        )
        mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
        sample_rate_hz = time_window.sample_rate_hz
        nominal_window_start_sample = int(
            round(time_window.start_time_s * sample_rate_hz)
        )
        microphone_self_noise_db = {
            microphone.mic_id: microphone.self_noise_db
            for microphone in sensor.microphones
        }
        microphone_orientations = {
            microphone.mic_id: microphone_world_orientation(
                sensor.orientation_world_quat,
                microphone.relative_orientation_quat,
            )
            for microphone in sensor.microphones
        }
        window_sample_count = max(
            1,
            int(
                round(
                    (time_window.end_time_s - time_window.start_time_s) * sample_rate_hz
                )
            ),
        )
        if (
            self.effects != EffectsConfig()
            or self.effects.motion.segments_per_window != 1
        ):
            validate_effects_config(
                self.effects,
                microphone_orders=(mic_ids,),
                sample_rate_hz=sample_rate_hz,
                backend_id=self.backend_id,
                runtime_profile=self.runtime_profile,
                sample_count=window_sample_count,
                microphone_self_noise_db=microphone_self_noise_db,
                source_ids=tuple(source.source_id for source in scene.sources),
                source_orientations={
                    source.source_id: source.orientation_world_quat
                    for source in scene.sources
                },
                microphone_orientations=microphone_orientations,
            )
        if segments_per_window > 1:
            assert self.window_motion is not None
            if (
                self.window_motion.sample_rate_hz != sample_rate_hz
                or self.window_motion.window_sample_count != window_sample_count
                or len(self.window_motion.segments) != segments_per_window
            ):
                raise UnsupportedEffectError(
                    "window-motion plan disagrees with the configured capture window"
                )
        pra = _import_pyroomacoustics()

        detections: list[AudioDetection] = []
        active = active_sources(scene, time_window)
        room_config = _room_config_summary(scene.room)
        mic_world = microphone_world_positions(sensor)
        per_source_rir_summary: dict[str, dict[str, object]] = {}
        mixture = np.zeros((len(mic_ids), window_sample_count), dtype=float)
        clamped_position_ids: tuple[str, ...] = ()
        effect_diagnostics: dict[str, Any] = {}
        segment_factor_rows: tuple[dict[str, float], ...] = (
            tuple({} for _ in self.window_motion.segments)
            if segments_per_window > 1 and self.window_motion is not None
            else ()
        )

        if active:
            if segments_per_window > 1:
                assert self.window_motion is not None
                piecewise = _simulate_piecewise_room(
                    pra=pra,
                    room_spec=scene.room,
                    active=active,
                    sensor=sensor,
                    time_window=time_window,
                    plan=self.window_motion,
                    speed_of_sound_mps=self.speed_of_sound_mps,
                    directivity_config=self.effects.directivity,
                )
                room = piecewise.last_room
                scheduled = list(piecewise.scheduled)
                doppler_factors = {}
                premix = piecewise.premix
                source_room_positions = piecewise.source_room_positions
                mic_room = piecewise.microphone_room_positions
                clamped_position_ids = piecewise.clamped_position_ids
                segment_factor_rows = piecewise.doppler_factor_by_segment
            else:
                source_positions = {
                    f"source:{source.source_id}": source.position_world
                    for source in active
                }
                microphone_positions = {
                    f"mic:{mic_id}": position for mic_id, position in mic_world.items()
                }
                room_positions, clamped_position_ids = _world_to_room_positions(
                    room_spec=scene.room,
                    positions={**source_positions, **microphone_positions},
                )
                source_room_positions = {
                    source.source_id: room_positions[f"source:{source.source_id}"]
                    for source in active
                }
                mic_room = {
                    mic_id: room_positions[f"mic:{mic_id}"] for mic_id in mic_ids
                }

                room = _build_shoebox_room(
                    pra=pra,
                    room_spec=scene.room,
                    sample_rate_hz=sample_rate_hz,
                    speed_of_sound_mps=self.speed_of_sound_mps,
                )
                scheduled = []
                doppler_factors: dict[str, float] = {}
                for source in active:
                    signal = _scheduled_window_signal(source, time_window=time_window)
                    factor = source_doppler_factor(
                        source,
                        sensor,
                        speed_of_sound_mps=self.speed_of_sound_mps,
                    )
                    if (
                        factor is None
                        and self.effects.motion.derive_velocity_from_poses
                    ):
                        factor = 1.0
                    if factor is not None:
                        doppler_factors[source.source_id] = factor
                        if abs(factor - 1.0) > 1e-9:
                            signal = replace(
                                signal,
                                signal=_doppler_resampled_signal(
                                    signal.signal, factor=factor
                                ),
                            )
                    scheduled.append(signal)
                    room.add_source(
                        source_room_positions[source.source_id],
                        signal=signal.signal,
                    )
                mic_matrix = np.asarray(
                    [mic_room[mic_id] for mic_id in mic_ids], dtype=float
                ).T
                _add_microphone_array(
                    pra, room, mic_matrix, sample_rate_hz=sample_rate_hz
                )
                room.compute_rir()
                premix = _simulate_premix(
                    room,
                    source_count=len(active),
                    mic_count=len(mic_ids),
                )
                if self.effects.directivity.enabled:
                    premix, diagnostics = _apply_directivity_to_premix(
                        premix,
                        active=active,
                        sensor=sensor,
                        microphone_positions_world=mic_world,
                        sample_rate_hz=sample_rate_hz,
                        config=self.effects.directivity,
                    )
                    if diagnostics:
                        effect_diagnostics["directivity"] = diagnostics
            if segments_per_window > 1 and self.effects.directivity.enabled:
                diagnostics = directivity_diagnostics(
                    self.effects.directivity,
                    active_source_ids=tuple(source.source_id for source in active),
                    microphone_ids=mic_ids,
                )
                if diagnostics:
                    effect_diagnostics["directivity"] = diagnostics
            # Occlusion attenuates the per-source/per-mic premix before
            # summing, so the mixture, per-source premix RMS, aggregate RMS,
            # GCC-PHAT diagnostics, and exported waveforms all stay mutually
            # consistent (uniform records are equivalent to scaling the
            # source input signal by linearity).
            for index, source in enumerate(active):
                occlusion = scene.occlusion_for(sensor.array_id, source.source_id)
                if occlusion is None:
                    continue
                per_mic_gain_db = occlusion_per_mic_extra_gain_db(occlusion, mic_ids)
                for mic_index, mic_id in enumerate(mic_ids):
                    band = occlusion_band_attenuation_db(occlusion, mic_id)
                    if band is not None:
                        premix[index, mic_index] = _apply_band_attenuation(
                            premix[index, mic_index],
                            sample_rate_hz=sample_rate_hz,
                            band_centers_hz=band[0],
                            band_attenuation_db=band[1],
                        )
                    elif per_mic_gain_db[mic_id] != 0.0:
                        premix[index, mic_index] *= 10.0 ** (
                            per_mic_gain_db[mic_id] / 20.0
                        )
            if self.effects.channel_response.enabled:
                for index in range(len(active)):
                    processed, diagnostics = self.effects_chain.apply_premix(
                        premix[index],
                        mic_ids=mic_ids,
                        sample_rate_hz=sample_rate_hz,
                        frame_id=frame_id,
                        backend_id=self.backend_id,
                        runtime_profile=self.runtime_profile,
                        microphone_self_noise_db=microphone_self_noise_db,
                    )
                    premix[index] = processed
                    if diagnostics:
                        effect_diagnostics.update(diagnostics)
            summed = np.sum(premix, axis=0)
            if summed.shape[1] >= window_sample_count:
                mixture = summed
            else:
                mixture[:, : summed.shape[1]] = summed
            if self.effects.noise.enabled or self.effects.electronics.enabled:
                mixture, diagnostics = self.effects_chain.apply_mixture(
                    mixture,
                    mic_ids=mic_ids,
                    sample_rate_hz=sample_rate_hz,
                    frame_id=frame_id,
                    backend_id=self.backend_id,
                    runtime_profile=self.runtime_profile,
                    nominal_window_start_sample=nominal_window_start_sample,
                    microphone_self_noise_db=microphone_self_noise_db,
                )
                if diagnostics:
                    effect_diagnostics.update(diagnostics)

            max_delay = (
                _max_microphone_spacing(mic_room) / self.speed_of_sound_mps + 0.002
            )
            for index, source in enumerate(active):
                source_waveforms = {
                    mic_id: premix[index, mic_index]
                    for mic_index, mic_id in enumerate(mic_ids)
                }
                signals_active = all(
                    np.any(waveform) for waveform in source_waveforms.values()
                )
                if signals_active:
                    tdoa_matrix, gcc_peaks = estimate_tdoa_diagnostics(
                        source_waveforms,
                        sample_rate_hz=sample_rate_hz,
                        max_delay_s=max_delay,
                        interp=self.gcc_phat_interp,
                    )
                    per_mic_delay_s = relative_delays_from_tdoa_matrix(
                        tdoa_matrix,
                        mic_ids=mic_ids,
                        reference_mic_id=mic_ids[0],
                    )
                else:
                    # Active but silent in this window (e.g. an exhausted file
                    # asset): GCC-PHAT is undefined on all-zero signals.
                    tdoa_matrix = {
                        f"{left}->{right}": 0.0 for left in mic_ids for right in mic_ids
                    }
                    gcc_peaks = {key: 0.0 for key in tdoa_matrix}
                    per_mic_delay_s = {mic_id: 0.0 for mic_id in mic_ids}
                per_mic_rms = rms_by_channel(source_waveforms)
                source_room = source_room_positions[source.source_id]
                rir_length_samples = _rir_lengths(room, mic_ids, source_index=index)
                rir_peak_delay_s = _rir_peak_delays(
                    room, mic_ids, sample_rate_hz, source_index=index
                )
                waveform_sample_count = {
                    mic_id: int(premix.shape[2]) for mic_id in mic_ids
                }
                direct_path_delay_s = {
                    mic_id: norm(subtract(source_room, mic_room[mic_id]))
                    / self.speed_of_sound_mps
                    for mic_id in mic_ids
                }
                ground_truth_bearing = _ground_truth_bearing(
                    source.position_world, sensor
                )
                ground_truth_elevation = _ground_truth_elevation(
                    source.position_world, sensor
                )
                doa, doa_estimator_diagnostics = self._estimate_source_doa(
                    sensor=sensor,
                    source_waveforms=source_waveforms,
                    per_mic_delay_s=per_mic_delay_s,
                    sample_rate_hz=sample_rate_hz,
                    max_delay_s=max_delay,
                    signals_active=signals_active,
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
                    if doa.estimated_elevation_deg is None
                    or ground_truth_elevation is None
                    else abs(doa.estimated_elevation_deg - ground_truth_elevation)
                )
                occlusion = scene.occlusion_for(
                    sensor.array_id,
                    source.source_id,
                )
                detections.append(
                    AudioDetection(
                        detection_id=deterministic_detection_id(
                            frame_id=frame_id,
                            source_id=source.source_id,
                            index=index,
                        ),
                        source_id=source.source_id,
                        class_label=source.class_label,
                        detection_mode="scheduled_known_source",
                        timestamp_ms=time_window.timestamp_ms,
                        ground_truth_bearing_deg=ground_truth_bearing,
                        ground_truth_elevation_deg=ground_truth_elevation,
                        source_distance_m=norm(
                            subtract(source.position_world, sensor.position_world)
                        ),
                        doa=doa,
                        source_pose=Pose3D.from_source(source),
                        per_mic_delay_s=per_mic_delay_s,
                        per_mic_rms=per_mic_rms,
                        audio_asset_path=source.audio_asset_path,
                        occluded=occlusion_flag(occlusion),
                        diagnostics={
                            "backend": self.backend_id,
                            "physical_waveform": True,
                            "room_id": scene.room.room_id,
                            "room_config": room_config,
                            "room_dimensions_m": scene.room.dimensions_m,
                            "absorption": scene.room.absorption,
                            "max_order": scene.room.max_order,
                            "air_absorption": scene.room.air_absorption,
                            "ray_tracing": scene.room.ray_tracing,
                            "pyroomacoustics_version": getattr(
                                pra, "__version__", "unknown"
                            ),
                            "speed_of_sound_mps": self.speed_of_sound_mps,
                            "sample_rate_hz": sample_rate_hz,
                            "array_geometry_rank_xy": layout_rank_xy(sensor),
                            "array_geometry_rank_xyz": layout_rank_xyz(sensor),
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
                            "source_waveform_mode": scheduled[index].mode,
                            "scheduled_start_offset_samples": (
                                scheduled[index].start_offset_samples
                            ),
                            "scheduled_content_sample_count": (
                                scheduled[index].content_sample_count
                            ),
                            **(
                                {
                                    "doppler_factor": doppler_factors[source.source_id],
                                    "doppler_waveform_rendered": abs(
                                        doppler_factors[source.source_id] - 1.0
                                    )
                                    > 1e-9,
                                }
                                if source.source_id in doppler_factors
                                else {}
                            ),
                            "room_source_position_m": source_room,
                            "room_microphone_positions_m": mic_room,
                            **occlusion_detection_diagnostics(occlusion),
                        },
                    )
                )
                per_source_rir_summary[source.source_id] = {
                    "rir_length_samples": rir_length_samples,
                    "rir_peak_delay_s": rir_peak_delay_s,
                    "waveform_sample_count": waveform_sample_count,
                    "source_waveform_mode": scheduled[index].mode,
                    "room_source_position_m": source_room,
                    "room_microphone_positions_m": mic_room,
                }

        if not active and self.effects.channel_response.enabled:
            mixture, diagnostics = self.effects_chain.apply_premix(
                mixture,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                backend_id=self.backend_id,
                runtime_profile=self.runtime_profile,
                microphone_self_noise_db=microphone_self_noise_db,
            )
            if diagnostics:
                effect_diagnostics.update(diagnostics)
        if not active and (
            self.effects.noise.enabled or self.effects.electronics.enabled
        ):
            mixture, diagnostics = self.effects_chain.apply_mixture(
                mixture,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                backend_id=self.backend_id,
                runtime_profile=self.runtime_profile,
                nominal_window_start_sample=nominal_window_start_sample,
                microphone_self_noise_db=microphone_self_noise_db,
            )
            if diagnostics:
                effect_diagnostics.update(diagnostics)

        aggregate_per_mic_rms = rms_by_channel(
            {mic_id: mixture[mic_index] for mic_index, mic_id in enumerate(mic_ids)}
        )
        frame_diagnostics: dict[str, Any] = {
            "backend": self.backend_id,
            "active_source_count": len(detections),
            "scheduled_source_ids": tuple(source.source_id for source in active),
            "physical_waveform": True,
            "room_id": scene.room.room_id,
            "room_config": room_config,
            "pyroomacoustics_version": getattr(pra, "__version__", "unknown"),
            "speed_of_sound_mps": self.speed_of_sound_mps,
            "sample_rate_hz": sample_rate_hz,
            "ambiguity_policy": self.ambiguity_policy,
            "max_events": time_window.max_events,
            "time_window_s": (
                time_window.start_time_s,
                time_window.end_time_s,
            ),
            "window_sample_count": window_sample_count,
            "doa_estimator": self.doa_estimator,
            "room_clamped_position_ids": clamped_position_ids,
            "per_source_rir_summary": per_source_rir_summary,
            "per_source_rir_length_samples": {
                source_id: summary["rir_length_samples"]
                for source_id, summary in per_source_rir_summary.items()
            },
        }
        if isinstance(scene.room.absorption, str) or scene.occlusion:
            room_resolution = _room_material_resolution(scene.room)
            material_evidence = {
                "room": room_resolution[1],
                **_occluder_material_evidence(scene),
            }
            frame_diagnostics["acoustics_state"] = {
                "room_state_hash": _room_state_hash(scene.room),
                "material_evidence": material_evidence,
            }
        if effect_diagnostics:
            frame_diagnostics["effects"] = effect_diagnostics
        if segments_per_window > 1:
            assert self.window_motion is not None
            frame_diagnostics["motion"] = {
                "segments_per_window": segments_per_window,
                "segments": motion_segment_diagnostics(
                    self.window_motion,
                    segment_factor_rows,
                ),
            }
        waveform_paths: tuple[str, ...] = ()
        if self.waveform_writer is not None:
            write_result = self.waveform_writer.write_frame_mixture(
                frame_id=frame_id,
                mixture=mixture,
                sample_rate_hz=sample_rate_hz,
                mic_ids=mic_ids,
                window_sample_count=window_sample_count,
            )
            waveform_paths = write_result.paths
            frame_diagnostics["waveform"] = dict(write_result.diagnostics)

        return AudioSensorFrame(
            frame_id=frame_id,
            frame_name=deterministic_frame_name(
                backend_id=self.backend_id,
                stage_id=scene.stage_id,
                array_id=sensor.array_id,
                timestamp_ms=time_window.timestamp_ms,
                frame_index=time_window.frame_index,
            ),
            timestamp_ms=time_window.timestamp_ms,
            backend_id=self.backend_id,
            array_id=sensor.array_id,
            array_pose=Pose3D.from_array(sensor),
            start_time_s=time_window.start_time_s,
            end_time_s=time_window.end_time_s,
            sample_rate_hz=sample_rate_hz,
            frame_index=time_window.frame_index,
            coordinate_convention=sensor.coordinate_convention,
            provenance="room_acoustics",
            max_events=time_window.max_events,
            detections=tuple(detections),
            aggregate_per_mic_rms=aggregate_per_mic_rms,
            waveform_paths=waveform_paths,
            diagnostics=frame_diagnostics,
        )


class RoomAcousticsSrpBackend(RoomAcousticsBackend):
    """Room-acoustics backend variant with SRP-PHAT as the DOA estimator.

    Emits the same L2 frames as ``room_acoustics`` (shared room, premix
    diagnostics, waveform export) with the direction estimate steered over
    the SRP-PHAT grid instead of the GCC-PHAT least-squares path.
    """

    backend_id = "room_acoustics_srp"

    def __init__(self, **kwargs: Any) -> None:
        estimator = kwargs.setdefault("doa_estimator", "srp_phat")
        if estimator != "srp_phat":
            raise ValueError("room_acoustics_srp pins doa_estimator='srp_phat'.")
        super().__init__(**kwargs)


@dataclass(frozen=True, slots=True)
class _ScheduledSignal:
    """One source's window-relative signal with sample-accurate scheduling."""

    signal: np.ndarray
    mode: str
    start_offset_samples: int
    content_sample_count: int


@dataclass(frozen=True, slots=True)
class _PiecewiseRoomResult:
    premix: np.ndarray
    scheduled: tuple[_ScheduledSignal, ...]
    last_room: Any
    source_room_positions: dict[str, tuple[float, float, float]]
    microphone_room_positions: dict[str, tuple[float, float, float]]
    clamped_position_ids: tuple[str, ...]
    doppler_factor_by_segment: tuple[dict[str, float], ...]


def _piecewise_phase_signal(
    waveform: np.ndarray,
    *,
    factors: tuple[float, ...],
    segment_lengths: tuple[int, ...],
) -> np.ndarray:
    """Render sample-exact segments with one cumulative float64 phase cursor."""

    if len(factors) != len(segment_lengths) or not factors:
        raise ValueError("piecewise factors and segment lengths must match")
    if any(length <= 0 for length in segment_lengths):
        raise ValueError("piecewise segment lengths must be positive")
    source = np.asarray(waveform, dtype=float)
    output = np.zeros(sum(segment_lengths), dtype=float)
    cursor = 0.0
    output_index = 0
    for factor, length in zip(factors, segment_lengths, strict=True):
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("piecewise Doppler factors must be positive and finite")
        for _ in range(length):
            lower = math.floor(cursor)
            fraction = cursor - lower
            first = source[lower] if 0 <= lower < source.size else 0.0
            second_index = lower + 1
            second = source[second_index] if 0 <= second_index < source.size else 0.0
            output[output_index] = first + fraction * (second - first)
            output_index += 1
            cursor += factor
    return output


def _simulate_piecewise_room(
    *,
    pra: Any,
    room_spec: RoomAcousticsSpec,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    time_window: AudioTimeWindow,
    plan: WindowMotionPlan,
    speed_of_sound_mps: float,
    directivity_config: DirectivityConfig,
) -> _PiecewiseRoomResult:
    """Simulate segment midpoint geometry and overlap-add every RIR tail."""

    mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
    scheduled = tuple(
        _scheduled_window_signal(source, time_window=time_window) for source in active
    )
    factor_rows: list[dict[str, float]] = []
    factors_by_source: dict[str, list[float]] = {
        source.source_id: [] for source in active
    }
    for segment in plan.segments:
        array_motion = segment.entities[sensor.array_id]
        segment_sensor = replace(
            sensor,
            position_world=array_motion.midpoint_position_world_m,
            velocity_world_mps=array_motion.velocity_world_mps,
        )
        row: dict[str, float] = {}
        for source in active:
            source_motion = segment.entities[source.source_id]
            segment_source = replace(
                source,
                position_world=source_motion.midpoint_position_world_m,
                velocity_world_mps=source_motion.velocity_world_mps,
            )
            if source_motion.velocity_source.startswith(
                "none:"
            ) or array_motion.velocity_source.startswith("none:"):
                factor = 1.0
            else:
                factor = source_doppler_factor(
                    segment_source,
                    segment_sensor,
                    speed_of_sound_mps=speed_of_sound_mps,
                )
                if factor is None:
                    factor = 1.0
            row[source.source_id] = factor
            factors_by_source[source.source_id].append(factor)
        factor_rows.append(row)

    lengths = tuple(segment.sample_count for segment in plan.segments)
    rendered = {
        source.source_id: _piecewise_phase_signal(
            scheduled[index].signal,
            factors=tuple(factors_by_source[source.source_id]),
            segment_lengths=lengths,
        )
        for index, source in enumerate(active)
    }
    assembled = np.zeros(
        (len(active), len(mic_ids), plan.window_sample_count),
        dtype=float,
    )
    clamped: set[str] = set()
    last_room: Any = None
    last_source_room: dict[str, tuple[float, float, float]] = {}
    last_mic_room: dict[str, tuple[float, float, float]] = {}
    for segment in plan.segments:
        array_position = segment.entities[sensor.array_id].midpoint_position_world_m
        segment_sensor = replace(sensor, position_world=array_position)
        mic_world = microphone_world_positions(segment_sensor)
        segment_sources = tuple(
            replace(
                source,
                position_world=segment.entities[
                    source.source_id
                ].midpoint_position_world_m,
                velocity_world_mps=segment.entities[
                    source.source_id
                ].velocity_world_mps,
            )
            for source in active
        )
        source_positions = {
            f"source:{source.source_id}": source.position_world
            for source in segment_sources
        }
        microphone_positions = {
            f"mic:{mic_id}": position for mic_id, position in mic_world.items()
        }
        room_positions, clamped_ids = _world_to_room_positions(
            room_spec=room_spec,
            positions={**source_positions, **microphone_positions},
        )
        clamped.update(clamped_ids)
        source_room = {
            source.source_id: room_positions[f"source:{source.source_id}"]
            for source in active
        }
        mic_room = {mic_id: room_positions[f"mic:{mic_id}"] for mic_id in mic_ids}
        room = _build_shoebox_room(
            pra=pra,
            room_spec=room_spec,
            sample_rate_hz=plan.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
        )
        for source in active:
            room.add_source(
                source_room[source.source_id],
                signal=rendered[source.source_id][
                    segment.start_sample : segment.end_sample
                ],
            )
        mic_matrix = np.asarray([mic_room[mic_id] for mic_id in mic_ids], dtype=float).T
        _add_microphone_array(
            pra,
            room,
            mic_matrix,
            sample_rate_hz=plan.sample_rate_hz,
        )
        room.compute_rir()
        segment_premix = _simulate_premix(
            room,
            source_count=len(active),
            mic_count=len(mic_ids),
        )
        if directivity_config.enabled:
            segment_premix, _diagnostics = _apply_directivity_to_premix(
                segment_premix,
                active=segment_sources,
                sensor=segment_sensor,
                microphone_positions_world=mic_world,
                sample_rate_hz=plan.sample_rate_hz,
                config=directivity_config,
            )
        required = segment.start_sample + segment_premix.shape[2]
        if required > assembled.shape[2]:
            expanded = np.zeros(
                (len(active), len(mic_ids), required),
                dtype=float,
            )
            expanded[:, :, : assembled.shape[2]] = assembled
            assembled = expanded
        assembled[
            :,
            :,
            segment.start_sample : required,
        ] += segment_premix
        last_room = room
        last_source_room = source_room
        last_mic_room = mic_room
    return _PiecewiseRoomResult(
        premix=assembled,
        scheduled=scheduled,
        last_room=last_room,
        source_room_positions=last_source_room,
        microphone_room_positions=last_mic_room,
        clamped_position_ids=tuple(sorted(clamped)),
        doppler_factor_by_segment=tuple(factor_rows),
    )


def _apply_directivity_to_premix(
    premix: np.ndarray,
    *,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    microphone_positions_world: dict[str, tuple[float, float, float]],
    sample_rate_hz: int,
    config: DirectivityConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Weight every complete pair stem using its direct-path angle."""

    mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
    diagnostics = directivity_diagnostics(
        config,
        active_source_ids=tuple(source.source_id for source in active),
        microphone_ids=mic_ids,
    )
    if not diagnostics:
        return premix, {}
    output = premix.copy()
    microphone_orientations = {
        microphone.mic_id: microphone_world_orientation(
            sensor.orientation_world_quat,
            microphone.relative_orientation_quat,
        )
        for microphone in sensor.microphones
    }
    for source_index, source in enumerate(active):
        source_pattern = resolve_pattern(config.source_patterns, source.source_id)
        for mic_index, mic_id in enumerate(mic_ids):
            microphone_pattern = resolve_pattern(config.mic_patterns, mic_id)
            output[source_index, mic_index] = apply_pair_directivity(
                output[source_index, mic_index],
                source_pattern=source_pattern,
                microphone_pattern=microphone_pattern,
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=microphone_positions_world[mic_id],
                microphone_orientation_world_xyzw=microphone_orientations[mic_id],
                sample_rate_hz=sample_rate_hz,
            )
    return output, diagnostics


def _scheduled_window_signal(
    source: AudioSourceSpec,
    *,
    time_window: AudioTimeWindow,
) -> _ScheduledSignal:
    """Position a source's emission inside a window with sample accuracy.

    A source starting mid-window gets leading zero-padding; a source that
    started before the window resumes from its elapsed offset. Content is
    truncated at whichever comes first of the source end and the window end.
    """

    sample_rate_hz = time_window.sample_rate_hz
    start_offset_samples = int(
        round(max(0.0, source.start_time_s - time_window.start_time_s) * sample_rate_hz)
    )
    elapsed_samples = int(
        round(max(0.0, time_window.start_time_s - source.start_time_s) * sample_rate_hz)
    )
    source_end_s = (
        math.inf
        if source.duration_s is None
        else source.start_time_s + float(source.duration_s)
    )
    effective_start_s = max(source.start_time_s, time_window.start_time_s)
    content_samples = max(
        0,
        int(
            round(
                (min(source_end_s, time_window.end_time_s) - effective_start_s)
                * sample_rate_hz
            )
        ),
    )

    if source.audio_asset_path and not source.audio_asset_path.startswith(
        "generated://"
    ):
        base, mode = _load_public_waveform(
            Path(source.audio_asset_path),
            sample_rate_hz=sample_rate_hz,
        )
        content = np.zeros(content_samples, dtype=float)
        available = base[elapsed_samples : elapsed_samples + content_samples]
        content[: available.size] = available
    else:
        mode = source.audio_asset_path or "generated://deterministic_pulse"
        content = _generated_source_content(
            source,
            mode=mode,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
            content_samples=content_samples,
            source_end_s=source_end_s,
        )
    signal = np.concatenate([np.zeros(start_offset_samples, dtype=float), content])
    if signal.size == 0:
        signal = np.zeros(1, dtype=float)
    return _ScheduledSignal(
        signal=signal,
        mode=mode,
        start_offset_samples=start_offset_samples,
        content_sample_count=content_samples,
    )


def _generated_source_content(
    source: AudioSourceSpec,
    *,
    mode: str,
    sample_rate_hz: int,
    elapsed_samples: int,
    content_samples: int,
    source_end_s: float,
) -> np.ndarray:
    """Synthesize a deterministic, phase-continuous slice of a source.

    The base signal is a seeded two-tone (the second tone at an irrational
    frequency ratio keeps GCC-PHAT correlation aperiodic) evaluated at
    absolute source-relative time, so consecutive windows concatenate without
    discontinuities.
    """

    if content_samples <= 0:
        return np.zeros(0, dtype=float)
    seed = int(hashlib.sha256(source.source_id.encode("utf-8")).hexdigest()[:8], 16)
    frequency_hz = 550.0 + float(seed % 700)
    time_s = (elapsed_samples + np.arange(content_samples, dtype=float)) / float(
        sample_rate_hz
    )
    waveform = (
        np.sin(2.0 * math.pi * frequency_hz * time_s)
        + _SECONDARY_TONE_GAIN
        * np.sin(2.0 * math.pi * frequency_hz * _SECONDARY_TONE_RATIO * time_s)
    ) / _TWO_TONE_PEAK
    waveform *= _emission_edge_envelope(
        time_s,
        source=source,
        source_end_s=source_end_s,
    )
    if mode == "generated://impulse":
        waveform *= 0.2
        _add_source_relative_spikes(
            waveform,
            _IMPULSE_SPIKES_S,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
        )
        waveform /= 1.2
    elif mode == "generated://pulse":
        waveform *= 0.15
        _add_source_relative_spikes(
            waveform,
            _PULSE_SPIKES_S,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
        )
        waveform /= 1.15
    gain = 10.0 ** (source.gain_db / 20.0)
    return np.asarray(waveform * gain, dtype=float)


def _emission_edge_envelope(
    time_s: np.ndarray,
    *,
    source: AudioSourceSpec,
    source_end_s: float,
) -> np.ndarray:
    """Short attack/release ramps at the source-relative emission edges."""

    ramp_s = _EDGE_RAMP_S
    if source.duration_s is not None:
        ramp_s = min(ramp_s, float(source.duration_s) / 4.0)
    if ramp_s <= 0.0:
        return np.ones_like(time_s)
    envelope = np.clip(time_s / ramp_s, 0.0, 1.0)
    if math.isfinite(source_end_s):
        emission_s = source_end_s - source.start_time_s
        envelope *= np.clip((emission_s - time_s) / ramp_s, 0.0, 1.0)
    return envelope


def _add_source_relative_spikes(
    waveform: np.ndarray,
    spikes: tuple[tuple[float, float], ...],
    *,
    sample_rate_hz: int,
    elapsed_samples: int,
) -> None:
    """Add transient spikes positioned in source-relative time, in place."""

    for offset_s, amplitude in spikes:
        spike_sample = max(1, int(round(offset_s * sample_rate_hz)))
        window_index = spike_sample - elapsed_samples
        if 0 <= window_index < waveform.size:
            waveform[window_index] += amplitude


def _import_pyroomacoustics() -> Any:
    try:
        return importlib.import_module("pyroomacoustics")
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "room_acoustics backend requires the optional 'room' extra "
            "(pyroomacoustics, scipy, and soundfile)."
        ) from exc


def _build_shoebox_room(
    *,
    pra: Any,
    room_spec: RoomAcousticsSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
) -> Any:
    absorption, _evidence, resolution = _room_material_resolution(room_spec)
    if resolution is not None:
        absorption = {
            "description": resolution.description,
            "coeffs": resolution.values,
            "center_freqs": MATERIAL_BAND_CENTERS_HZ,
        }
    materials = pra.Material(absorption) if hasattr(pra, "Material") else absorption
    kwargs: dict[str, Any] = {
        "fs": sample_rate_hz,
        "materials": materials,
        "max_order": room_spec.max_order,
        "air_absorption": room_spec.air_absorption,
        "ray_tracing": room_spec.ray_tracing,
        "c": speed_of_sound_mps,
    }
    while True:
        try:
            return pra.ShoeBox(room_spec.dimensions_m, **kwargs)
        except TypeError as exc:
            removed = False
            optional_keys = ("c", "ray_tracing", "air_absorption")
            if not isinstance(room_spec.absorption, str):
                optional_keys = (*optional_keys, "materials")
            for optional_key in optional_keys:
                if optional_key in kwargs:
                    kwargs.pop(optional_key)
                    removed = True
                    break
            if not removed:
                raise exc


def _add_microphone_array(
    pra: Any,
    room: Any,
    mic_matrix: np.ndarray,
    *,
    sample_rate_hz: int,
) -> None:
    if hasattr(pra, "MicrophoneArray"):
        room.add_microphone_array(pra.MicrophoneArray(mic_matrix, fs=sample_rate_hz))
    else:
        room.add_microphone_array(mic_matrix)


def _apply_band_attenuation(
    waveform: np.ndarray,
    *,
    sample_rate_hz: int,
    band_centers_hz: tuple[float, ...],
    band_attenuation_db: tuple[float, ...],
) -> np.ndarray:
    """Apply per-band attenuation with a zero-phase rFFT gain curve.

    The per-bin gain interpolates the band gains over log2 frequency with
    flat extrapolation beyond the outermost band centers. Zero-phase
    filtering preserves GCC-PHAT delay estimates.
    """

    sample_count = int(waveform.size)
    if sample_count == 0 or not band_centers_hz:
        return waveform
    centers = np.asarray(band_centers_hz, dtype=float)
    gains_db = -np.asarray(band_attenuation_db, dtype=float)
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / float(sample_rate_hz))
    log_frequencies = np.log2(np.maximum(frequencies, centers[0] / 4.0))
    gain_curve = 10.0 ** (np.interp(log_frequencies, np.log2(centers), gains_db) / 20.0)
    spectrum = np.fft.rfft(waveform) * gain_curve
    return np.fft.irfft(spectrum, n=sample_count)


def _simulate_premix(
    room: Any,
    *,
    source_count: int,
    mic_count: int,
) -> np.ndarray:
    """Run the room simulation and return per-source microphone signals."""

    premix = np.asarray(room.simulate(return_premix=True), dtype=float)
    if (
        premix.ndim != 3
        or premix.shape[0] != source_count
        or premix.shape[1] != mic_count
    ):
        raise ValueError("pyroomacoustics returned an unexpected mic signal shape.")
    return premix


def _load_public_waveform(
    path: Path,
    *,
    sample_rate_hz: int,
) -> tuple[np.ndarray, str]:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(
            "audio_asset_path for room_acoustics must be a relative public "
            "package path."
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
    except ValueError as exc:
        raise ValueError(
            "audio_asset_path for room_acoustics must stay under the current "
            "package checkout."
        ) from exc
    if not path.exists():
        raise ValueError(f"Audio asset {str(path)!r} does not exist.")
    try:
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Reading audio_asset_path files requires soundfile from the 'room' extra."
        ) from exc
    data, file_rate = sf.read(path, always_2d=False)
    waveform = np.asarray(data, dtype=float)
    if waveform.ndim == 2:
        waveform = np.mean(waveform, axis=1)
    if int(file_rate) != int(sample_rate_hz):
        waveform = _resample_waveform(
            waveform,
            from_hz=int(file_rate),
            to_hz=int(sample_rate_hz),
        )
    return waveform, f"file:{path}"


def _resample_waveform(
    waveform: np.ndarray,
    *,
    from_hz: int,
    to_hz: int,
) -> np.ndarray:
    """Resample a mono waveform between sample rates with polyphase filtering."""

    try:
        from scipy.signal import resample_poly  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Resampling audio_asset_path files requires scipy from the 'room' extra."
        ) from exc
    divisor = math.gcd(from_hz, to_hz)
    return np.asarray(
        resample_poly(waveform, to_hz // divisor, from_hz // divisor),
        dtype=float,
    )


def _doppler_resampled_signal(
    waveform: np.ndarray,
    *,
    factor: float,
) -> np.ndarray:
    """Time-compress a window signal by the Doppler factor.

    The output plays the same content over ``len(waveform) / factor`` samples
    at the unchanged frame sample rate, scaling all frequencies by ``factor``.
    One factor applies to the whole window (computed at the array center at
    the snapshot pose), so intra-window motion and the compression of leading
    scheduling silence are deliberate approximations of a continuously moving
    source.
    """

    try:
        from fractions import Fraction

        from scipy.signal import resample_poly  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Doppler waveform resampling requires scipy from the 'room' extra."
        ) from exc
    ratio = Fraction(factor).limit_denominator(10_000)
    return np.asarray(
        resample_poly(waveform, ratio.denominator, ratio.numerator),
        dtype=float,
    )


def _room_config_summary(room_spec: RoomAcousticsSpec) -> dict[str, object]:
    return {
        "room_id": room_spec.room_id,
        "dimensions_m": room_spec.dimensions_m,
        "absorption": _absorption_summary(room_spec.absorption),
        "max_order": room_spec.max_order,
        "air_absorption": room_spec.air_absorption,
        "ray_tracing": room_spec.ray_tracing,
        "origin_m": room_spec.origin_m,
        "out_of_bounds": room_spec.out_of_bounds,
        "anchor_prim_path": room_spec.anchor_prim_path,
    }


def _absorption_summary(
    absorption: float | dict[str, float] | str,
) -> float | dict[str, float] | str:
    if isinstance(absorption, str):
        return absorption
    if isinstance(absorption, dict):
        return {str(key): float(value) for key, value in sorted(absorption.items())}
    return float(absorption)


def _room_material_resolution(
    room_spec: RoomAcousticsSpec,
) -> tuple[
    float | dict[str, float] | tuple[float, ...],
    dict[str, str],
    MaterialResolution | None,
]:
    """Return the applied room absorption and its frozen evidence record."""

    absorption = room_spec.absorption
    if isinstance(absorption, str):
        resolution = resolve_material_coefficients(
            absorption,
            "absorption",
            application=f"room {room_spec.room_id!r}",
        )
        return resolution.values, resolution.evidence_record(), resolution
    if isinstance(absorption, dict):
        return (
            absorption,
            {
                "material_id": "inline_room_absorption:mapping",
                "coefficient": "absorption",
                "evidence": "nominal",
            },
            None,
        )
    return (
        float(absorption),
        {
            "material_id": "inline_room_absorption:scalar",
            "coefficient": "absorption",
            "evidence": "nominal",
        },
        None,
    )


def _room_state_hash(room_spec: RoomAcousticsSpec) -> str:
    """Hash the complete canonical room state."""

    applied, evidence, resolution = _room_material_resolution(room_spec)
    if isinstance(applied, dict):
        absorption_payload: object = {
            str(key): float(value) for key, value in sorted(applied.items())
        }
    elif isinstance(applied, tuple):
        absorption_payload = list(applied)
    else:
        absorption_payload = [float(applied)] * 6
    state = (
        room_spec.room_id,
        room_spec.dimensions_m,
        room_spec.origin_m,
        room_spec.out_of_bounds,
        room_spec.anchor_prim_path,
        absorption_payload,
        evidence["material_id"],
        evidence["evidence"],
        None if resolution is None else resolution.citation,
        room_spec.max_order,
        room_spec.air_absorption,
        room_spec.ray_tracing,
    )
    encoded = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _occluder_material_evidence(
    scene: AudioSceneSnapshot,
) -> dict[str, dict[str, str]]:
    """Derive pure-core evidence for material ids carried by occlusion records."""

    evidence: dict[str, dict[str, str]] = {}
    for occlusion in scene.occlusion or ():
        for prim_path, authored_id in sorted(occlusion.hit_materials.items()):
            application = f"occluder:{prim_path}"
            if authored_id == "usd_attribute":
                record = {
                    "material_id": f"usd_attribute:{prim_path}",
                    "coefficient": "transmission_db",
                    "evidence": "nominal",
                }
            else:
                record = resolve_material_coefficients(
                    authored_id,
                    "transmission_db",
                    application=application,
                ).evidence_record()
            evidence[application] = record
    return {key: evidence[key] for key in sorted(evidence)}


def _world_to_room_positions(
    *,
    room_spec: RoomAcousticsSpec,
    positions: dict[str, tuple[float, float, float]],
) -> tuple[dict[str, tuple[float, float, float]], tuple[str, ...]]:
    """Translate world positions into the room's corner-origin frame.

    The room is anchored in world space at ``room_spec.origin_m``; positions
    outside ``[origin, origin + dimensions]`` follow the spec's out-of-bounds
    policy: ``"error"`` raises naming the offending entity, ``"clamp"`` pulls
    it just inside the nearest wall and reports it.
    """

    dimensions = room_spec.dimensions_m
    origin = room_spec.origin_m
    room_positions: dict[str, tuple[float, float, float]] = {}
    clamped_ids: list[str] = []
    for key, position in positions.items():
        room_position = [float(position[axis] - origin[axis]) for axis in range(3)]
        out_of_bounds = any(
            room_position[axis] < 0.0 or room_position[axis] > dimensions[axis]
            for axis in range(3)
        )
        if out_of_bounds:
            if room_spec.out_of_bounds == "clamp":
                room_position = [
                    min(
                        max(room_position[axis], ROOM_CLAMP_MARGIN_M),
                        dimensions[axis] - ROOM_CLAMP_MARGIN_M,
                    )
                    for axis in range(3)
                ]
                clamped_ids.append(key)
            else:
                anchor = (
                    f" (room anchored to {room_spec.anchor_prim_path!r})"
                    if room_spec.anchor_prim_path is not None
                    else ""
                )
                max_corner = tuple(origin[axis] + dimensions[axis] for axis in range(3))
                raise ValueError(
                    f"room_acoustics position {key!r} at world "
                    f"{tuple(float(value) for value in position)} is outside "
                    f"room {room_spec.room_id!r} world bounds "
                    f"[{room_spec.origin_m}, {max_corner}]{anchor}. Move the "
                    "prim inside the room or set out_of_bounds='clamp'."
                )
        room_positions[key] = (
            room_position[0],
            room_position[1],
            room_position[2],
        )
    return room_positions, tuple(clamped_ids)


def _max_microphone_spacing(
    positions: dict[str, tuple[float, float, float]],
) -> float:
    max_spacing = 0.0
    values = tuple(positions.values())
    for left in values:
        for right in values:
            max_spacing = max(max_spacing, norm(subtract(left, right)))
    return max_spacing


def _rir_lengths(
    room: Any,
    mic_ids: tuple[str, ...],
    *,
    source_index: int,
) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        lengths[mic_id] = 0 if rir is None else int(len(rir))
    return lengths


def _rir_peak_delays(
    room: Any,
    mic_ids: tuple[str, ...],
    sample_rate_hz: int,
    *,
    source_index: int,
) -> dict[str, float]:
    delays: dict[str, float] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        if rir is None or len(rir) == 0:
            delays[mic_id] = 0.0
        else:
            delays[mic_id] = float(np.argmax(np.abs(rir))) / float(sample_rate_hz)
    return delays


def _rir_for(room: Any, mic_index: int, source_index: int) -> np.ndarray | None:
    rir = getattr(room, "rir", None)
    if rir is None:
        return None
    try:
        return np.asarray(rir[mic_index][source_index], dtype=float)
    except (IndexError, TypeError):
        return None


def _ground_truth_bearing(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    forward, right, _ = basis_from_quaternion(sensor.orientation_world_quat)
    bearing = bearing_from_components(
        dot(delta, forward),
        dot(delta, right),
    )
    if bearing is None:
        return None
    return bearing


def _ground_truth_elevation(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    distance = norm(delta)
    if distance <= 1e-9:
        return None
    _, _, up = basis_from_quaternion(sensor.orientation_world_quat)
    ratio = dot(delta, up) / distance
    return math.degrees(math.asin(max(-1.0, min(1.0, ratio))))
