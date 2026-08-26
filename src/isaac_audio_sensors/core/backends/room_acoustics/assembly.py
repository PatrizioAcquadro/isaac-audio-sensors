"""Diagnostics, waveform export, and frame assembly for room acoustics."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.backends.room_acoustics.diagnostics import (
    _occluder_material_evidence,
    _room_material_resolution,
    _room_state_hash,
)
from isaac_audio_sensors.core.backends.room_acoustics.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends.room_acoustics.rendering import RenderedRoom
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
) -> AudioSensorFrame:
    """Assemble the public frame after rendering and localization complete."""

    aggregate_per_mic_rms = rms_by_channel(
        {
            mic_id: rendered.mixture[mic_index]
            for mic_index, mic_id in enumerate(prepared.mic_ids)
        }
    )
    frame_diagnostics: dict[str, Any] = {
        "backend": backend_id,
        "active_source_count": len(detections),
        "scheduled_source_ids": tuple(
            source.source_id for source in prepared.active
        ),
        "physical_waveform": True,
        "room_id": prepared.scene.room.room_id,
        "room_config": prepared.room_config,
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
        "room_clamped_position_ids": rendered.clamped_position_ids,
        "per_source_rir_summary": per_source_rir_summary,
        "per_source_rir_length_samples": {
            source_id: summary["rir_length_samples"]
            for source_id, summary in per_source_rir_summary.items()
        },
    }
    if isinstance(prepared.scene.room.absorption, str) or prepared.scene.occlusion:
        room_resolution = _room_material_resolution(prepared.scene.room)
        material_evidence = {
            "room": room_resolution[1],
            **_occluder_material_evidence(prepared.scene),
        }
        frame_diagnostics["acoustics_state"] = {
            "room_state_hash": _room_state_hash(prepared.scene.room),
            "material_evidence": material_evidence,
        }
    if rendered.effect_diagnostics:
        frame_diagnostics["effects"] = rendered.effect_diagnostics
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
        provenance="room_acoustics",
        max_events=prepared.time_window.max_events,
        detections=tuple(detections),
        aggregate_per_mic_rms=aggregate_per_mic_rms,
        waveform_paths=waveform_paths,
        diagnostics=frame_diagnostics,
    )


__all__ = ["assemble_frame"]
