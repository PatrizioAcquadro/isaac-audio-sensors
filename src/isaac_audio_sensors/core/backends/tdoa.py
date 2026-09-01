"""Synthetic per-microphone TDOA backend."""

from __future__ import annotations

import hashlib
import math
import random

from isaac_audio_sensors.core.acoustics.occlusion import (
    occlusion_detection_diagnostics,
    occlusion_flag,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.backends.amplitude import (
    aggregate_rms_power_sum,
    source_amplitude_at,
)
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS, EPSILON
from isaac_audio_sensors.core.directivity import DIRECTIVITY_MODE
from isaac_audio_sensors.core.doa.ambiguity import (
    TWO_MIC_ENDPOINT_TOLERANCE,
    choose_front_hemisphere_candidate,
    deduplicate_candidate_bearings,
    two_mic_candidate_bearings,
)
from isaac_audio_sensors.core.doa.least_squares import least_squares_direction
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.effects.channel_response import metadata_channel_values
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.noise import metadata_noise_timing_values
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    basis_from_quaternion,
    bearing_from_components,
    clamp,
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
from isaac_audio_sensors.core.motion.doppler import (
    doppler_factor,
    source_doppler_factor,
)
from isaac_audio_sensors.core.scene import (
    active_sources,
    deterministic_detection_id,
    deterministic_frame_id,
    deterministic_frame_name,
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
)


class TdoaSyntheticBackend:
    """Synthetic direct-path TDOA backend with explicit ambiguity diagnostics."""

    backend_id = "tdoa_synthetic"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        noise_std_s: float = 0.0,
        clock_jitter_s: float = 0.0,
        gain_mismatch_db: float = 0.0,
        ambiguity_policy: str = "none",
        seed: int | None = None,
        air_absorption_db_per_m: float = 0.0,
        effects: EffectsConfig | None = None,
        runtime_profile: str = "waveform_fidelity",
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if noise_std_s < 0.0 or not math.isfinite(noise_std_s):
            raise ValueError("noise_std_s must be non-negative and finite.")
        if clock_jitter_s < 0.0 or not math.isfinite(clock_jitter_s):
            raise ValueError("clock_jitter_s must be non-negative and finite.")
        if isinstance(gain_mismatch_db, bool) or not math.isfinite(gain_mismatch_db):
            raise ValueError("gain_mismatch_db must be finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if air_absorption_db_per_m < 0.0 or not math.isfinite(air_absorption_db_per_m):
            raise ValueError("air_absorption_db_per_m must be non-negative and finite.")
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.noise_std_s = float(noise_std_s)
        self.clock_jitter_s = float(clock_jitter_s)
        self.gain_mismatch_db = float(gain_mismatch_db)
        self.ambiguity_policy = ambiguity_policy
        self.seed = None if seed is None else int(seed)
        self.air_absorption_db_per_m = float(air_absorption_db_per_m)
        self.effects = EffectsConfig() if effects is None else effects
        self.runtime_profile = runtime_profile

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        array_id: str,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        sensor = scene.array_by_id(array_id)
        validate_tdoa_array(sensor)
        mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
        frame_id = deterministic_frame_id(
            backend_id=self.backend_id,
            stage_id=scene.stage_id,
            array_id=sensor.array_id,
            timestamp_ms=time_window.timestamp_ms,
            frame_index=time_window.frame_index,
        )
        sample_count = max(
            1,
            int(
                round(
                    (time_window.end_time_s - time_window.start_time_s)
                    * time_window.sample_rate_hz
                )
            ),
        )
        nominal_window_start_sample = int(
            round(time_window.start_time_s * time_window.sample_rate_hz)
        )
        effect_gain_db: dict[str, float] = {}
        effect_delay_s: dict[str, float] = {}
        effect_diagnostics: dict[str, object] = {}
        if (
            self.effects != EffectsConfig()
            or self.effects.motion.segments_per_window != 1
        ):
            validate_effects_config(
                self.effects,
                microphone_orders=(mic_ids,),
                sample_rate_hz=time_window.sample_rate_hz,
                backend_id=self.backend_id,
                runtime_profile=self.runtime_profile,
                sample_count=sample_count,
                microphone_self_noise_db={
                    microphone.mic_id: microphone.self_noise_db
                    for microphone in sensor.microphones
                },
            )
            (
                effect_gain_db,
                effect_delay_s,
                _effect_polarity,
                response_diagnostics,
            ) = metadata_channel_values(
                self.effects.channel_response,
                mic_ids,
            )
            if response_diagnostics:
                effect_diagnostics["channel_response"] = response_diagnostics
            noise_offsets, noise_diagnostics = metadata_noise_timing_values(
                self.effects.noise,
                mic_ids=mic_ids,
                sample_rate_hz=time_window.sample_rate_hz,
                frame_id=frame_id,
                nominal_window_start_sample=nominal_window_start_sample,
                sample_count=sample_count,
            )
            for mic_id, offset_s in noise_offsets.items():
                effect_delay_s[mic_id] = effect_delay_s.get(mic_id, 0.0) + offset_s
            if noise_diagnostics:
                effect_diagnostics["noise"] = noise_diagnostics
        detections: list[AudioDetection] = []
        aggregate_rms_power = {
            microphone.mic_id: 0.0 for microphone in sensor.microphones
        }

        active = active_sources(scene, time_window)
        for index, source in enumerate(active):
            occlusion = scene.occlusion_for(sensor.array_id, source.source_id)
            delay_result = self._per_mic_delays_and_rms(
                source,
                sensor,
                frame_id=frame_id,
                per_mic_extra_gain_db=occlusion_per_mic_extra_gain_db(
                    occlusion,
                    mic_ids,
                ),
                effect_gain_db=effect_gain_db,
                effect_delay_s=effect_delay_s,
            )
            ground_truth_bearing = _ground_truth_bearing(source.position_world, sensor)
            ground_truth_elevation = _ground_truth_elevation(
                source.position_world, sensor
            )
            doa = self._estimate_doa(
                sensor=sensor,
                per_mic_delay_s=delay_result.per_mic_delay_s,
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
            for mic_id, rms in delay_result.per_mic_rms.items():
                aggregate_rms_power[mic_id] += rms * rms

            doppler_diagnostics = _doppler_diagnostics(
                source,
                sensor,
                speed_of_sound_mps=self.speed_of_sound_mps,
                force_unity_when_absent=(
                    self.effects.motion.derive_velocity_from_poses
                ),
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
                    source_distance_m=delay_result.source_distance_m,
                    doa=doa,
                    source_pose=Pose3D.from_source(source),
                    per_mic_delay_s=delay_result.per_mic_delay_s,
                    per_mic_rms=delay_result.per_mic_rms,
                    audio_asset_path=source.audio_asset_path,
                    occluded=occlusion_flag(occlusion),
                    diagnostics={
                        "backend": self.backend_id,
                        "physical_waveform": False,
                        "speed_of_sound_mps": self.speed_of_sound_mps,
                        "array_geometry_rank_xy": layout_rank_xy(sensor),
                        "array_geometry_rank_xyz": layout_rank_xyz(sensor),
                        "per_mic_distance_m": delay_result.per_mic_distance_m,
                        "tdoa_matrix_s": _tdoa_matrix(delay_result.per_mic_delay_s),
                        "noise_std_s": self.noise_std_s,
                        "clock_jitter_s": self.clock_jitter_s,
                        "tdoa_gain_mismatch_std_db": self.gain_mismatch_db,
                        "noise_seed": self.seed,
                        "air_absorption_db_per_m": self.air_absorption_db_per_m,
                        "source_nominal_gain_db": source.gain_db,
                        "microphone_nominal_gain_db": {
                            microphone.mic_id: microphone.gain_db
                            for microphone in sensor.microphones
                        },
                        "directivity": {
                            "mode": DIRECTIVITY_MODE,
                            "source_pattern": source.directivity.value,
                            "microphone_patterns": {
                                microphone.mic_id: microphone.directivity.value
                                for microphone in sensor.microphones
                            },
                        },
                        "oracle_bearing_error_deg": oracle_bearing_error,
                        "oracle_elevation_error_deg": oracle_elevation_error,
                        "tdoa_gain_mismatch_delta_db": (
                            delay_result.per_mic_gain_offset_db
                        ),
                        "stress_controls_deterministic": True,
                        **doppler_diagnostics,
                        **occlusion_detection_diagnostics(occlusion),
                    },
                )
            )

        frame_diagnostics: dict[str, object] = {
            "backend": self.backend_id,
            "active_source_count": len(detections),
            "ambiguity_policy": self.ambiguity_policy,
            "noise_std_s": self.noise_std_s,
            "clock_jitter_s": self.clock_jitter_s,
            "tdoa_gain_mismatch_std_db": self.gain_mismatch_db,
            "noise_seed": self.seed,
            "air_absorption_db_per_m": self.air_absorption_db_per_m,
            "array_geometry_rank_xy": layout_rank_xy(sensor),
            "array_geometry_rank_xyz": layout_rank_xyz(sensor),
            "stress_controls_deterministic": True,
        }
        if effect_diagnostics:
            frame_diagnostics["effects"] = effect_diagnostics

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
            sample_rate_hz=time_window.sample_rate_hz,
            frame_index=time_window.frame_index,
            coordinate_convention=sensor.coordinate_convention,
            provenance="synthetic/core",
            max_events=time_window.max_events,
            detections=tuple(detections),
            aggregate_per_mic_rms=aggregate_rms_power_sum(
                aggregate_rms_power,
                sensor.microphones,
            ),
            waveform_paths=(),
            diagnostics=frame_diagnostics,
        )

    def _per_mic_delays_and_rms(
        self,
        source: AudioSourceSpec,
        sensor: MicrophoneArraySpec,
        *,
        frame_id: str,
        per_mic_extra_gain_db: dict[str, float] | None = None,
        effect_gain_db: dict[str, float] | None = None,
        effect_delay_s: dict[str, float] | None = None,
    ) -> _DelayResult:
        positions = microphone_world_positions(sensor)
        extra_gains = per_mic_extra_gain_db or {}
        effect_gains = effect_gain_db or {}
        effect_delays = effect_delay_s or {}
        distances: dict[str, float] = {}
        delays: dict[str, float] = {}
        rms: dict[str, float] = {}
        gain_offsets: dict[str, float] = {}
        for microphone in sensor.microphones:
            mic_position = positions[microphone.mic_id]
            distance = norm(subtract(source.position_world, mic_position))
            delay_noise = self._delay_noise_s(
                frame_id=frame_id,
                mic_id=microphone.mic_id,
            )
            delay = (
                distance / self.speed_of_sound_mps
                + delay_noise
                + effect_delays.get(microphone.mic_id, 0.0)
            )
            gain_offset_db = self._gain_offset_db(microphone.mic_id)
            amplitude = source_amplitude_at(
                source,
                microphone,
                mic_position,
                sensor.orientation_world_quat,
                occlusion_gain_delta_db=extra_gains.get(microphone.mic_id, 0.0),
                tdoa_gain_mismatch_delta_db=gain_offset_db,
                channel_response_gain_delta_db=effect_gains.get(
                    microphone.mic_id,
                    0.0,
                ),
                air_absorption_db_per_m=self.air_absorption_db_per_m,
            )
            distances[microphone.mic_id] = distance
            delays[microphone.mic_id] = delay
            rms[microphone.mic_id] = amplitude
            gain_offsets[microphone.mic_id] = gain_offset_db
        source_distance = norm(subtract(source.position_world, sensor.position_world))
        return _DelayResult(
            per_mic_distance_m=distances,
            per_mic_delay_s=delays,
            per_mic_rms=rms,
            per_mic_gain_offset_db=gain_offsets,
            source_distance_m=source_distance,
        )

    def _delay_noise_s(self, *, frame_id: str, mic_id: str) -> float:
        noise = 0.0
        if self.noise_std_s > 0.0:
            noise += self._seeded_gauss(
                "delay_noise",
                frame_id,
                mic_id,
                std=self.noise_std_s,
            )
        if self.clock_jitter_s > 0.0:
            noise += self._seeded_gauss(
                "clock_jitter",
                frame_id,
                mic_id,
                std=self.clock_jitter_s,
            )
        return noise

    def _gain_offset_db(self, mic_id: str) -> float:
        magnitude = abs(self.gain_mismatch_db)
        if magnitude == 0.0:
            return 0.0
        return self._seeded_gauss("gain_mismatch", mic_id, std=magnitude)

    def _seeded_gauss(self, *parts: str, std: float) -> float:
        """Deterministic Gaussian draw keyed by seed and the given parts."""

        seed = 0 if self.seed is None else self.seed
        key = ":".join((str(seed), *parts))
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        return rng.gauss(0.0, std)

    def _estimate_doa(
        self,
        *,
        sensor: MicrophoneArraySpec,
        per_mic_delay_s: dict[str, float],
    ) -> DoaEstimate:
        if len(sensor.microphones) == 2:
            return self._estimate_two_mic(sensor, per_mic_delay_s)
        return self._estimate_multi_mic(
            sensor=sensor,
            per_mic_delay_s=per_mic_delay_s,
        )

    def _estimate_two_mic(
        self,
        sensor: MicrophoneArraySpec,
        per_mic_delay_s: dict[str, float],
    ) -> DoaEstimate:
        first, second = sensor.microphones
        first_pos = first.relative_position_m
        second_pos = second.relative_position_m
        baseline = (second_pos[0] - first_pos[0], second_pos[1] - first_pos[1])
        spacing = math.hypot(baseline[0], baseline[1])
        if spacing <= EPSILON:
            return DoaEstimate(
                estimated_bearing_deg=None,
                bearing_confidence=0.0,
                ambiguity_class="degenerate_array",
                ambiguity_reason="Two microphones are coincident in local XY.",
            )

        dt = per_mic_delay_s[second.mic_id] - per_mic_delay_s[first.mic_id]
        raw_projection = -self.speed_of_sound_mps * dt / spacing
        if abs(raw_projection) > 1.0 + TWO_MIC_ENDPOINT_TOLERANCE:
            return DoaEstimate(
                estimated_bearing_deg=None,
                candidate_bearing_deg=(),
                bearing_confidence=0.0,
                ambiguity_class="invalid_tdoa_delay",
                ambiguity_reason=(
                    "Observed delay exceeds the physical two-microphone aperture "
                    "beyond the eight-ULP endpoint tolerance."
                ),
            )
        projection = clamp(raw_projection, -1.0, 1.0)
        candidates = two_mic_candidate_bearings(
            baseline_unit_xy=(baseline[0] / spacing, baseline[1] / spacing),
            projection=projection,
        )
        stress_penalty = self._stress_penalty(spacing / self.speed_of_sound_mps)
        if len(candidates) <= 1:
            estimated = candidates[0] if candidates else None
            return DoaEstimate(
                estimated_bearing_deg=estimated,
                candidate_bearing_deg=candidates,
                bearing_confidence=0.9 * stress_penalty,
                ambiguity_class=None,
                ambiguity_reason=None,
            )
        if self.ambiguity_policy == "front_hemisphere":
            estimated = choose_front_hemisphere_candidate(candidates)
            return DoaEstimate(
                estimated_bearing_deg=estimated,
                candidate_bearing_deg=candidates,
                bearing_confidence=0.65 * stress_penalty,
                ambiguity_class="front_hemisphere_prior",
                ambiguity_reason=(
                    "Two-mic TDOA is front/back ambiguous; selected a bearing "
                    "using explicit front_hemisphere prior."
                ),
            )
        return DoaEstimate(
            estimated_bearing_deg=None,
            candidate_bearing_deg=candidates,
            bearing_confidence=0.35 * stress_penalty,
            ambiguity_class="ambiguous_front_back",
            ambiguity_reason=(
                "Two-mic linear TDOA cannot distinguish mirrored front/back "
                "bearings without an explicit prior."
            ),
        )

    def _estimate_multi_mic(
        self,
        *,
        sensor: MicrophoneArraySpec,
        per_mic_delay_s: dict[str, float],
    ) -> DoaEstimate:
        result = least_squares_direction(
            sensor, per_mic_delay_s, self.speed_of_sound_mps
        )
        if result is None:
            return DoaEstimate(
                estimated_bearing_deg=None,
                bearing_confidence=0.0,
                ambiguity_class="degenerate_array",
                ambiguity_reason="Microphone layout cannot solve a 2D direction.",
            )

        ux, uy, uz, residual = result
        bearing = bearing_from_components(ux, uy)
        if bearing is None:
            return DoaEstimate(
                estimated_bearing_deg=None,
                bearing_confidence=0.0,
                ambiguity_class="degenerate_solution",
                ambiguity_reason="Least-squares direction has zero horizontal norm.",
            )
        elevation = (
            None if uz is None else math.degrees(math.asin(clamp(uz, -1.0, 1.0)))
        )
        residual_penalty = 1.0 / (1.0 + residual * 40.0)
        confidence = 0.95 * self._stress_penalty(0.001) * residual_penalty
        return DoaEstimate(
            estimated_bearing_deg=bearing,
            candidate_bearing_deg=deduplicate_candidate_bearings((bearing,)),
            bearing_sector=bearing_deg_to_sector_name(bearing),
            bearing_confidence=clamp(confidence, 0.0, 1.0),
            ambiguity_class=None,
            ambiguity_reason=None,
            estimated_elevation_deg=elevation,
            candidate_elevation_deg=(() if elevation is None else (elevation,)),
        )

    def _stress_penalty(self, reference_delay_s: float) -> float:
        return self._delay_noise_penalty(reference_delay_s) * self._gain_penalty()

    def _delay_noise_penalty(self, reference_delay_s: float) -> float:
        noise = self.noise_std_s + self.clock_jitter_s
        if noise <= 0.0:
            return 1.0
        return 1.0 / (1.0 + noise / max(reference_delay_s, 1e-6))

    def _gain_penalty(self) -> float:
        mismatch_db = abs(self.gain_mismatch_db)
        if mismatch_db == 0.0:
            return 1.0
        return 1.0 / (1.0 + mismatch_db / 12.0)


def estimate_doa_from_delays(
    *,
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
    ambiguity_policy: str = "none",
) -> DoaEstimate:
    """Estimate DOA from externally measured per-microphone delays."""

    return TdoaSyntheticBackend(
        speed_of_sound_mps=speed_of_sound_mps,
        ambiguity_policy=ambiguity_policy,
    )._estimate_doa(
        sensor=sensor,
        per_mic_delay_s=per_mic_delay_s,
    )


class _DelayResult:
    def __init__(
        self,
        *,
        per_mic_distance_m: dict[str, float],
        per_mic_delay_s: dict[str, float],
        per_mic_rms: dict[str, float],
        per_mic_gain_offset_db: dict[str, float],
        source_distance_m: float,
    ) -> None:
        self.per_mic_distance_m = per_mic_distance_m
        self.per_mic_delay_s = per_mic_delay_s
        self.per_mic_rms = per_mic_rms
        self.per_mic_gain_offset_db = per_mic_gain_offset_db
        self.source_distance_m = source_distance_m


def _ground_truth_bearing(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    forward, right, _ = basis_from_quaternion(sensor.orientation_world_quat)
    return bearing_from_components(
        dot(delta, forward),
        dot(delta, right),
    )


def _doppler_diagnostics(
    source: AudioSourceSpec,
    sensor: MicrophoneArraySpec,
    *,
    speed_of_sound_mps: float,
    force_unity_when_absent: bool = False,
) -> dict[str, object]:
    """Doppler metadata for L1: frequency-shift ratios only, no rendering.

    Emitted only when the source or array declares a velocity so static
    scenes keep byte-identical diagnostics.
    """

    factor = source_doppler_factor(
        source,
        sensor,
        speed_of_sound_mps=speed_of_sound_mps,
    )
    if factor is None:
        if not force_unity_when_absent:
            return {}
        factor = 1.0
    per_mic = {
        mic_id: doppler_factor(
            source_position=source.position_world,
            listener_position=mic_position,
            source_velocity=source.velocity_world_mps,
            listener_velocity=sensor.velocity_world_mps,
            speed_of_sound_mps=speed_of_sound_mps,
        )
        for mic_id, mic_position in microphone_world_positions(sensor).items()
    }
    return {
        "doppler_factor": factor,
        "per_mic_doppler_factor": per_mic,
        "doppler_waveform_rendered": False,
    }


def _ground_truth_elevation(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    distance = norm(delta)
    if distance <= EPSILON:
        return None
    _, _, up = basis_from_quaternion(sensor.orientation_world_quat)
    up_component = dot(delta, up)
    return math.degrees(math.asin(clamp(up_component / distance, -1.0, 1.0)))


def _tdoa_matrix(per_mic_delay_s: dict[str, float]) -> dict[str, float]:
    matrix: dict[str, float] = {}
    mic_ids = tuple(per_mic_delay_s)
    for left in mic_ids:
        for right in mic_ids:
            matrix[f"{left}->{right}"] = per_mic_delay_s[left] - per_mic_delay_s[right]
    return matrix
