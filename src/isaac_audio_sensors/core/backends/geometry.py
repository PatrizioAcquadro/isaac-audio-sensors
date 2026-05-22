"""Deterministic geometry-only backend."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.math_utils import (
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

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
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
            delta = subtract(source.position_world, sensor.position_world)
            distance = norm(delta)
            forward_component = dot(delta, sensor.forward_vec_world)
            right_component = dot(delta, sensor.right_vec_world)
            up_component = dot(delta, sensor.up_vec_world)
            horizontal_distance = math.hypot(forward_component, right_component)
            bearing = bearing_from_components(forward_component, right_component)
            confidence = (
                0.0
                if bearing is None or distance <= 0.0
                else horizontal_distance / distance
            )
            sector = None if bearing is None else bearing_deg_to_sector_name(bearing)
            per_mic_rms = _rms_proxy_for_source(source.position_world, sensor)
            for mic_id, rms in per_mic_rms.items():
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
                    ground_truth_bearing_deg=bearing,
                    source_distance_m=distance,
                    doa=DoaEstimate(
                        estimated_bearing_deg=bearing,
                        candidate_bearing_deg=(() if bearing is None else (bearing,)),
                        bearing_sector=sector,
                        bearing_confidence=confidence,
                        ambiguity_class=None,
                        ambiguity_reason=None,
                    ),
                    source_pose=Pose3D.from_source(source),
                    per_mic_delay_s={},
                    per_mic_rms=per_mic_rms,
                    audio_asset_path=source.audio_asset_path,
                    diagnostics={
                        "backend": self.backend_id,
                        "physical_waveform": False,
                        "forward_component_m": forward_component,
                        "right_component_m": right_component,
                        "up_component_m": up_component,
                        "horizontal_distance_m": horizontal_distance,
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
                "source_count": len(scene.sources),
                "active_source_count": len(detections),
                "coordinate_convention": sensor.coordinate_convention,
            },
        )


def _rms_proxy_for_source(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> dict[str, float]:
    per_mic: dict[str, float] = {}
    for mic_id, mic_position in microphone_world_positions(sensor).items():
        distance = max(norm(subtract(source_position_world, mic_position)), 0.1)
        per_mic[mic_id] = 1.0 / (distance * distance)
    return per_mic
