"""Diagnostics, waveform export, and analytic frame assembly."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.backends._analytic.diagnostics import (
    _environment_material_resolution,
    _environment_state_hash,
    _occluder_material_evidence,
)
from isaac_audio_sensors.core.backends._analytic.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends._analytic.rendering import RenderedRoom
from isaac_audio_sensors.core.doa.gcc_phat import rms_by_channel
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.motion import (
    WindowMotionPlan,
    motion_segment_diagnostics,
)
from isaac_audio_sensors.core.scene import deterministic_frame_name
from isaac_audio_sensors.core.types import AudioDetection, AudioSensorFrame, Pose3D


def assemble_frame(
    prepared: PreparedRoomFrame,
    rendered: RenderedRoom,
    detections: list[AudioDetection],
    per_source_rir_summary: dict[str, dict[str, object]],
    *,
    backend_id: str,
    speed_of_sound_mps: float,
    ambiguity_policy: str,
    doa_estimator: str,
    waveform_writer: WaveformSink | None,
    window_motion: WindowMotionPlan | None,
    provenance: str = "room_acoustics",
) -> AudioSensorFrame:
    """Assemble the public frame after rendering and localization complete."""

    aggregate_per_mic_rms = rms_by_channel(
        {
            mic_id: rendered.mixture[mic_index]
            for mic_index, mic_id in enumerate(prepared.mic_ids)
        }
    )
    environment = prepared.scene.environment
    assert environment is not None
    frame_diagnostics: dict[str, Any] = {
        "backend": backend_id,
        "active_source_count": len(detections),
        "scheduled_source_ids": tuple(source.source_id for source in prepared.active),
        "physical_waveform": True,
        "environment_id": environment.environment_id,
        "environment_config": prepared.environment_config,
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
        "ambiguity_policy": ambiguity_policy,
        "max_events": prepared.time_window.max_events,
        "time_window_s": (
            prepared.time_window.start_time_s,
            prepared.time_window.end_time_s,
        ),
        "window_sample_count": prepared.window_sample_count,
        "doa_estimator": doa_estimator,
        "per_source_rir_summary": per_source_rir_summary,
        "per_source_rir_length_samples": {
            source_id: summary["rir_length_samples"]
            for source_id, summary in per_source_rir_summary.items()
        },
    }
    if (
        any(isinstance(surface.absorption, str) for surface in environment.surfaces)
        or prepared.scene.occlusion
    ):
        material_evidence = _occluder_material_evidence(prepared.scene)
        if environment.surfaces:
            environment_resolution = _environment_material_resolution(environment)
            material_evidence = {
                "environment": environment_resolution[1],
                **material_evidence,
            }
        frame_diagnostics["acoustics_state"] = {
            "environment_state_hash": _environment_state_hash(environment),
            "material_evidence": material_evidence,
        }
    effect_diagnostics = dict(rendered.effect_diagnostics)
    for key in (
        "directivity",
        "source_nominal_gain_db",
        "microphone_nominal_gain_db",
    ):
        if key in effect_diagnostics:
            frame_diagnostics[key] = effect_diagnostics.pop(key)
    if effect_diagnostics:
        frame_diagnostics["effects"] = effect_diagnostics
    if prepared.segments_per_window > 1:
        assert window_motion is not None
        frame_diagnostics["motion"] = {
            "segments_per_window": prepared.segments_per_window,
            "segments": motion_segment_diagnostics(
                window_motion,
                rendered.segment_factor_rows,
            ),
        }
    waveform_paths: tuple[str, ...] = ()
    if waveform_writer is not None:
        write_result = waveform_writer.write_frame_mixture(
            frame_id=prepared.frame_id,
            mixture=rendered.mixture,
            sample_rate_hz=prepared.sample_rate_hz,
            mic_ids=prepared.mic_ids,
            window_sample_count=prepared.window_sample_count,
        )
        waveform_paths = write_result.paths
        frame_diagnostics["waveform"] = dict(write_result.diagnostics)

    return AudioSensorFrame(
        frame_id=prepared.frame_id,
        frame_name=deterministic_frame_name(
            backend_id=backend_id,
            stage_id=prepared.scene.stage_id,
            array_id=prepared.sensor.array_id,
            timestamp_ms=prepared.time_window.timestamp_ms,
            frame_index=prepared.time_window.frame_index,
        ),
        timestamp_ms=prepared.time_window.timestamp_ms,
        backend_id=backend_id,
        array_id=prepared.sensor.array_id,
        array_pose=Pose3D.from_array(prepared.sensor),
        start_time_s=prepared.time_window.start_time_s,
        end_time_s=prepared.time_window.end_time_s,
        sample_rate_hz=prepared.sample_rate_hz,
        frame_index=prepared.time_window.frame_index,
        coordinate_convention=prepared.sensor.coordinate_convention,
        provenance=provenance,
        max_events=prepared.time_window.max_events,
        detections=tuple(detections),
        aggregate_per_mic_rms=aggregate_per_mic_rms,
        waveform_paths=waveform_paths,
        diagnostics=frame_diagnostics,
    )


__all__ = ["assemble_frame"]
