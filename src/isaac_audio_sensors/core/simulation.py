"""Config-driven simulator-independent audio simulation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.plugins.protocols import PropagationBackend
from isaac_audio_sensors.core.scene import (
    deterministic_frame_id,
    deterministic_frame_name,
)
from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneSignalBlock,
)


def simulate_frame(
    backend: PropagationBackend,
    scene: AudioSceneSnapshot,
    array_id: str,
    time_window: AudioTimeWindow,
    *,
    perception: AudioPerceptionPipeline,
    waveform_sink: WaveformSink | None = None,
    external_observations: Sequence[AudioObservation] = (),
) -> tuple[AudioSensorFrame, MicrophoneSignalBlock]:
    """Propagate one window, run perception, and optionally persist its block."""

    array = scene.array_by_id(array_id)
    block = backend.propagate(scene, array_id, time_window)
    if not isinstance(block, MicrophoneSignalBlock):
        raise TypeError(
            "PropagationBackend.propagate() must return MicrophoneSignalBlock."
        )
    if block.time_window != time_window:
        raise ValueError(
            "PropagationBackend.propagate() returned a different time window."
        )
    frame_id = deterministic_frame_id(
        backend_id=block.producer_id,
        stage_id=scene.stage_id,
        array_id=array.array_id,
        start_time_s=time_window.start_time_s,
        frame_index=time_window.frame_index,
    )
    frame = perception.process(
        block,
        array,
        frame_id=frame_id,
        frame_name=deterministic_frame_name(
            backend_id=block.producer_id,
            stage_id=scene.stage_id,
            array_id=array.array_id,
            start_time_s=time_window.start_time_s,
            frame_index=time_window.frame_index,
        ),
        external_observations=external_observations,
    )
    if waveform_sink is not None:
        write_result = waveform_sink.write_signal_block(
            frame_id=frame.frame_id,
            block=block,
        )
        diagnostics = dict(frame.diagnostics)
        diagnostics["waveform"] = dict(write_result.diagnostics)
        frame = replace(
            frame,
            waveform_paths=write_result.paths,
            diagnostics=diagnostics,
        )
    return frame, block


def simulate_from_config(
    path: str | Path,
    *,
    backend_id: str | None = None,
    array_id: str | None = None,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_observations: int | None = None,
) -> AudioSensorFrame:
    """Simulate one frame from a validated audio configuration."""

    config = load_audio_config(path)
    selected_backend = backend_id or config.default_backend
    selected_array = array_id or next(iter(config.arrays))
    scene = build_scene_snapshot(config)
    time_window = AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        frame_index=0,
    )
    backend_kwargs: dict[str, object] = {
        "effects": config.effects,
        "runtime_profile": config.runtime_profile,
    }
    backend_kwargs.update(
        speed_of_sound_mps=config.speed_of_sound_mps,
        max_order=config.analytic_max_order,
        air_absorption=config.analytic_air_absorption,
        ray_tracing=config.analytic_ray_tracing,
    )
    backend = get_backend(selected_backend, **backend_kwargs)
    frame, _block = simulate_frame(
        backend,
        scene,
        selected_array,
        time_window,
        perception=AudioPerceptionPipeline(max_observations=max_observations),
    )
    return frame


__all__ = ["simulate_frame", "simulate_from_config"]
