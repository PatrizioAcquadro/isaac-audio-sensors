"""Synthetic per-microphone TDOA backend."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS, EPSILON
from isaac_audio_sensors.core.doa.ambiguity import (
    choose_front_hemisphere_candidate,
    deduplicate_candidate_bearings,
    two_mic_candidate_bearings,
)
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
    bearing_from_components,
    clamp,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import (
    layout_rank_xy,
    microphone_world_positions,
    validate_tdoa_array,
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
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if noise_std_s < 0.0 or not math.isfinite(noise_std_s):
            raise ValueError("noise_std_s must be non-negative and finite.")
        if clock_jitter_s < 0.0 or not math.isfinite(clock_jitter_s):
            raise ValueError("clock_jitter_s must be non-negative and finite.")
        if not math.isfinite(gain_mismatch_db):
            raise ValueError("gain_mismatch_db must be finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.noise_std_s = float(noise_std_s)
        self.clock_jitter_s = float(clock_jitter_s)
        self.gain_mismatch_db = float(gain_mismatch_db)
        self.ambiguity_policy = ambiguity_policy

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        validate_tdoa_array(sensor)
        frame_id = deterministic_frame_id(
            backend_id=self.backend_id,
            stage_id=scene.stage_id,
            array_id=sensor.array_id,
            timestamp_ms=time_window.timestamp_ms,
            frame_index=time_window.frame_index,
        )
        detections: list[AudioDetection] = []
        aggregate_rms = {microphone.mic_id: 0.0 for microphone in sensor.microphones}

        active = active_sources(scene, time_window)
        for index, source in enumerate(active):
            delay_result = self._per_mic_delays_and_rms(source.position_world, sensor)
            ground_truth_bearing = _ground_truth_bearing(source.position_world, sensor)
            doa = self._estimate_doa(
                sensor=sensor,
                per_mic_delay_s=delay_result.per_mic_delay_s,
                ground_truth_bearing_deg=ground_truth_bearing,
            )
            for mic_id, rms in delay_result.per_mic_rms.items():
                aggregate_rms[mic_id] += rms

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
                    source_distance_m=delay_result.source_distance_m,
                    doa=doa,
                    source_pose=Pose3D.from_source(source),
                    per_mic_delay_s=delay_result.per_mic_delay_s,
                    per_mic_rms=delay_result.per_mic_rms,
                    audio_asset_path=source.audio_asset_path,
                    diagnostics={
                        "backend": self.backend_id,
                        "physical_waveform": False,
                        "speed_of_sound_mps": self.speed_of_sound_mps,
                        "array_geometry_rank_xy": layout_rank_xy(sensor),
                        "per_mic_distance_m": delay_result.per_mic_distance_m,
                        "tdoa_matrix_s": _tdoa_matrix(delay_result.per_mic_delay_s),
                        "noise_std_s": self.noise_std_s,
                        "clock_jitter_s": self.clock_jitter_s,
                        "gain_mismatch_db": self.gain_mismatch_db,
                        "per_mic_gain_offset_db": (
                            delay_result.per_mic_gain_offset_db
                        ),
                        "stress_controls_deterministic": True,
                    },
                )
            )

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
            aggregate_per_mic_rms=aggregate_rms,
            waveform_paths=(),
            diagnostics={
                "backend": self.backend_id,
                "active_source_count": len(detections),
                "ambiguity_policy": self.ambiguity_policy,
                "noise_std_s": self.noise_std_s,
                "clock_jitter_s": self.clock_jitter_s,
                "gain_mismatch_db": self.gain_mismatch_db,
                "array_geometry_rank_xy": layout_rank_xy(sensor),
                "stress_controls_deterministic": True,
            },
        )

    def _per_mic_delays_and_rms(
        self,
        source_position_world: tuple[float, float, float],
        sensor: MicrophoneArraySpec,
    ) -> _DelayResult:
        positions = microphone_world_positions(sensor)
        distances: dict[str, float] = {}
        delays: dict[str, float] = {}
        rms: dict[str, float] = {}
        gain_offsets: dict[str, float] = {}
        for index, microphone in enumerate(sensor.microphones):
            mic_position = positions[microphone.mic_id]
            distance = norm(subtract(source_position_world, mic_position))
            deterministic_noise = self._deterministic_delay_noise(index)
            delay = distance / self.speed_of_sound_mps + deterministic_noise
            gain_offset_db = self._deterministic_gain_offset_db(index)
            gain_scale = 10.0 ** ((microphone.gain_db + gain_offset_db) / 20.0)
            amplitude = gain_scale / max(distance, 0.1) ** 2
            distances[microphone.mic_id] = distance
            delays[microphone.mic_id] = delay
            rms[microphone.mic_id] = amplitude
            gain_offsets[microphone.mic_id] = gain_offset_db
        source_distance = norm(subtract(source_position_world, sensor.position_world))
        return _DelayResult(
            per_mic_distance_m=distances,
            per_mic_delay_s=delays,
            per_mic_rms=rms,
            per_mic_gain_offset_db=gain_offsets,
            source_distance_m=source_distance,
        )

    def _deterministic_delay_noise(self, mic_index: int) -> float:
        if self.noise_std_s == 0.0 and self.clock_jitter_s == 0.0:
            return 0.0
        sign = -1.0 if mic_index % 2 == 0 else 1.0
        taper = 1.0 + mic_index * 0.1
        return sign * (self.noise_std_s + self.clock_jitter_s) * taper

    def _deterministic_gain_offset_db(self, mic_index: int) -> float:
        magnitude = abs(self.gain_mismatch_db)
        if magnitude == 0.0:
            return 0.0
        sign = -1.0 if mic_index % 2 == 0 else 1.0
        return sign * magnitude / 2.0

    def _estimate_doa(
        self,
        *,
        sensor: MicrophoneArraySpec,
        per_mic_delay_s: dict[str, float],
        ground_truth_bearing_deg: float | None,
    ) -> DoaEstimate:
        if len(sensor.microphones) == 2:
            return self._estimate_two_mic(sensor, per_mic_delay_s)
        return self._estimate_multi_mic(
            sensor=sensor,
            per_mic_delay_s=per_mic_delay_s,
            ground_truth_bearing_deg=ground_truth_bearing_deg,
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
        projection = clamp(-self.speed_of_sound_mps * dt / spacing, -1.0, 1.0)
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
        ground_truth_bearing_deg: float | None,
    ) -> DoaEstimate:
        result = _least_squares_direction(
            sensor, per_mic_delay_s, self.speed_of_sound_mps
        )
        if result is None:
            return DoaEstimate(
                estimated_bearing_deg=None,
                bearing_confidence=0.0,
                ambiguity_class="degenerate_array",
                ambiguity_reason="Microphone layout cannot solve a 2D direction.",
            )

        ux, uy, residual = result
        bearing = bearing_from_components(ux, uy)
        if bearing is None:
            return DoaEstimate(
                estimated_bearing_deg=None,
                bearing_confidence=0.0,
                ambiguity_class="degenerate_solution",
                ambiguity_reason="Least-squares direction has zero horizontal norm.",
            )
        error = (
            0.0
            if ground_truth_bearing_deg is None
            else angular_error_deg(bearing, ground_truth_bearing_deg)
        )
        residual_penalty = 1.0 / (1.0 + residual * 40.0)
        confidence = 0.95 * self._stress_penalty(0.001) * residual_penalty
        confidence *= max(0.0, 1.0 - min(error, 90.0) / 180.0)
        return DoaEstimate(
            estimated_bearing_deg=bearing,
            candidate_bearing_deg=deduplicate_candidate_bearings((bearing,)),
            bearing_sector=bearing_deg_to_sector_name(bearing),
            bearing_confidence=clamp(confidence, 0.0, 1.0),
            ambiguity_class=None,
            ambiguity_reason=None,
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
    ground_truth_bearing_deg: float | None = None,
) -> DoaEstimate:
    """Estimate DOA from externally measured per-microphone delays."""

    return TdoaSyntheticBackend(
        speed_of_sound_mps=speed_of_sound_mps,
        ambiguity_policy=ambiguity_policy,
    )._estimate_doa(
        sensor=sensor,
        per_mic_delay_s=per_mic_delay_s,
        ground_truth_bearing_deg=ground_truth_bearing_deg,
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
    return bearing_from_components(
        dot(delta, sensor.forward_vec_world),
        dot(delta, sensor.right_vec_world),
    )


def _least_squares_direction(
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    speed_of_sound_mps: float,
) -> tuple[float, float, float] | None:
    microphones = sensor.microphones
    ref = microphones[0]
    ref_pos = ref.relative_position_m
    ref_delay = per_mic_delay_s[ref.mic_id]
    sxx = sxy = syy = bx = by = 0.0
    rows: list[tuple[float, float, float]] = []
    for microphone in microphones[1:]:
        pos = microphone.relative_position_m
        ax = pos[0] - ref_pos[0]
        ay = pos[1] - ref_pos[1]
        b = -speed_of_sound_mps * (per_mic_delay_s[microphone.mic_id] - ref_delay)
        rows.append((ax, ay, b))
        sxx += ax * ax
        sxy += ax * ay
        syy += ay * ay
        bx += ax * b
        by += ay * b
    det = sxx * syy - sxy * sxy
    if abs(det) <= EPSILON:
        return None
    ux = (bx * syy - by * sxy) / det
    uy = (sxx * by - sxy * bx) / det
    length = math.hypot(ux, uy)
    if length <= EPSILON:
        return None
    ux /= length
    uy /= length
    residual = 0.0
    for ax, ay, b in rows:
        residual += (ax * ux + ay * uy - b) ** 2
    residual = math.sqrt(residual / max(len(rows), 1))
    return ux, uy, residual


def _tdoa_matrix(per_mic_delay_s: dict[str, float]) -> dict[str, float]:
    matrix: dict[str, float] = {}
    mic_ids = tuple(per_mic_delay_s)
    for left in mic_ids:
        for right in mic_ids:
            matrix[f"{left}->{right}"] = per_mic_delay_s[left] - per_mic_delay_s[right]
    return matrix
