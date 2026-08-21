"""Room-acoustics scene-to-frame backend orchestration."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from typing import Any

import numpy as np

from isaac_audio_sensors.core.backends.room_acoustics.diagnostics import (
    _ground_truth_bearing,
    _ground_truth_elevation,
    _occluder_material_evidence,
    _rir_lengths,
    _rir_peak_delays,
    _room_config_summary,
    _room_material_resolution,
    _room_state_hash,
)
from isaac_audio_sensors.core.backends.room_acoustics.rendering import (
    _add_microphone_array,
    _apply_band_attenuation,
    _apply_directivity_to_premix,
    _build_shoebox_room,
    _import_pyroomacoustics,
    _max_microphone_spacing,
    _simulate_piecewise_room,
    _simulate_premix,
    _world_to_room_positions,
)
from isaac_audio_sensors.core.backends.room_acoustics.signals import (
    _doppler_resampled_signal,
    _scheduled_window_signal,
)
from isaac_audio_sensors.core.backends.tdoa import estimate_doa_from_delays
from isaac_audio_sensors.core.constants import (
    DEFAULT_SPEED_OF_SOUND_MPS,
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
    EffectsConfig,
)
from isaac_audio_sensors.core.effects.directivity import (
    directivity_diagnostics,
    microphone_world_orientation,
)
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
)
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
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
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    Pose3D,
)

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
        if doa_estimator not in DOA_ESTIMATOR_IDS:
            raise ValueError(
                f"doa_estimator must be one of {sorted(DOA_ESTIMATOR_IDS)}."
            )
        _import_pyroomacoustics()
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
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
            # Attenuate each stem before summing so RMS, DOA, and export agree.
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
                    # GCC-PHAT is undefined for an active all-zero signal.
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


__all__ = ["RoomAcousticsBackend", "RoomAcousticsSrpBackend"]
