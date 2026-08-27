"""Deterministic geometry-only backend."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.acoustics.occlusion import (
    occlusion_detection_diagnostics,
    occlusion_flag,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.backends.amplitude import (
    aggregate_rms_power_sum,
    source_amplitude_at,
)
from isaac_audio_sensors.core.directivity import DIRECTIVITY_MODE
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.effects.channel_response import metadata_channel_values
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.noise import metadata_noise_timing_values
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.math_utils import (
    basis_from_quaternion,
    bearing_from_components,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import microphone_world_positions
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


class GeometryBackend:
    """Direct pose-to-bearing baseline.

    This backend is deterministic and useful for frame-convention validation.
    It does not produce physically meaningful waveforms or localization
    measurements.
    """

    backend_id = "geometry_only"

    def __init__(
        self,
        *,
        effects: EffectsConfig | None = None,
        runtime_profile: str = "waveform_fidelity",
    ) -> None:
        self.effects = EffectsConfig() if effects is None else effects
        self.runtime_profile = runtime_profile

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
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
        effect_gain_db: dict[str, float] = {}
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
            effect_gain_db, _delays, _polarities, response_diagnostics = (
                metadata_channel_values(
                    self.effects.channel_response,
                    mic_ids,
                )
            )
            if response_diagnostics:
                effect_diagnostics["channel_response"] = response_diagnostics
            _noise_offsets, noise_diagnostics = metadata_noise_timing_values(
                self.effects.noise,
                mic_ids=mic_ids,
                sample_rate_hz=time_window.sample_rate_hz,
                frame_id=frame_id,
                nominal_window_start_sample=int(
                    round(time_window.start_time_s * time_window.sample_rate_hz)
                ),
                sample_count=sample_count,
            )
            if noise_diagnostics:
                effect_diagnostics["noise"] = noise_diagnostics
        detections: list[AudioDetection] = []
        aggregate_rms_power = {
            microphone.mic_id: 0.0 for microphone in sensor.microphones
        }

        forward, right, up = basis_from_quaternion(sensor.orientation_world_quat)
        active = active_sources(scene, time_window)
        for index, source in enumerate(active):
            delta = subtract(source.position_world, sensor.position_world)
            distance = norm(delta)
            forward_component = dot(delta, forward)
            right_component = dot(delta, right)
            up_component = dot(delta, up)
            horizontal_distance = math.hypot(forward_component, right_component)
            bearing = bearing_from_components(forward_component, right_component)
            elevation = (
                None
                if distance <= 0.0
                else math.degrees(
                    math.asin(max(-1.0, min(1.0, up_component / distance)))
                )
            )
            confidence = (
                0.0
                if bearing is None or distance <= 0.0
                else min(1.0, horizontal_distance / distance)
            )
            sector = None if bearing is None else bearing_deg_to_sector_name(bearing)
            occlusion = scene.occlusion_for(sensor.array_id, source.source_id)
            per_mic_rms = _rms_proxy_for_source(
                source,
                sensor,
                per_mic_extra_gain_db=occlusion_per_mic_extra_gain_db(
                    occlusion,
                    mic_ids,
                ),
                effect_gain_db=effect_gain_db,
            )
            for mic_id, rms in per_mic_rms.items():
                aggregate_rms_power[mic_id] += rms * rms

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
                    ground_truth_bearing_deg=bearing,
                    ground_truth_elevation_deg=elevation,
                    source_distance_m=distance,
                    doa=DoaEstimate(
                        estimated_bearing_deg=bearing,
                        candidate_bearing_deg=(() if bearing is None else (bearing,)),
                        bearing_sector=sector,
                        bearing_confidence=confidence,
                        ambiguity_class=None,
                        ambiguity_reason=None,
                        estimated_elevation_deg=elevation,
                        candidate_elevation_deg=(
                            () if elevation is None else (elevation,)
                        ),
                    ),
                    source_pose=Pose3D.from_source(source),
                    per_mic_delay_s={},
                    per_mic_rms=per_mic_rms,
                    audio_asset_path=source.audio_asset_path,
                    occluded=occlusion_flag(occlusion),
                    diagnostics={
                        "backend": self.backend_id,
                        "physical_waveform": False,
                        "forward_component_m": forward_component,
                        "right_component_m": right_component,
                        "up_component_m": up_component,
                        "horizontal_distance_m": horizontal_distance,
                        "source_gain_db": source.gain_db,
                        "microphone_gain_db": {
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
                        **occlusion_detection_diagnostics(occlusion, mic_ids),
                    },
                )
            )

        frame_diagnostics: dict[str, object] = {
            "backend": self.backend_id,
            "source_count": len(scene.sources),
            "active_source_count": len(detections),
            "coordinate_convention": sensor.coordinate_convention,
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


def _rms_proxy_for_source(
    source: AudioSourceSpec,
    sensor: MicrophoneArraySpec,
    *,
    per_mic_extra_gain_db: dict[str, float] | None = None,
    effect_gain_db: dict[str, float] | None = None,
) -> dict[str, float]:
    per_mic: dict[str, float] = {}
    extra_gains = per_mic_extra_gain_db or {}
    effect_gains = effect_gain_db or {}
    positions = microphone_world_positions(sensor)
    for microphone in sensor.microphones:
        mic_id = microphone.mic_id
        per_mic[mic_id] = source_amplitude_at(
            source,
            microphone,
            positions[mic_id],
            sensor.orientation_world_quat,
            occlusion_gain_delta_db=extra_gains.get(mic_id, 0.0),
            channel_response_gain_delta_db=effect_gains.get(mic_id, 0.0),
        )
    return per_mic
