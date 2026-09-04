"""Dataset composition from one private analytic render."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.math_utils import (
    bearing_from_components,
    norm,
    quaternion_conjugate,
    rotate_vector_by_quaternion,
    subtract,
)
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.simulation import _frame_from_signal
from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneSignalBlock,
)
from isaac_audio_sensors.recording.truth import FrameTruth, TruthEvent

if TYPE_CHECKING:
    from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics


def simulate_dataset_frame(
    backend: AnalyticAcoustics,
    scene: AudioSceneSnapshot,
    array_id: str,
    time_window: AudioTimeWindow,
    *,
    perception: AudioPerceptionPipeline,
    waveform_sink: WaveformSink | None = None,
    external_observations: Sequence[AudioObservation] = (),
) -> tuple[AudioSensorFrame, MicrophoneSignalBlock, FrameTruth]:
    """Return observed data and separate supervision without rendering twice.

    Geometry describes the supplied snapshot. Audio evidence covers exactly the
    returned window and inherits the producer's motion and propagation limits.
    No private stem or truth is supplied to perception or the waveform sink.
    """
    import numpy as np

    from isaac_audio_sensors.core.backends._analytic.block import assemble_signal_block
    from isaac_audio_sensors.core.backends.analytic import (
        _CORE_SOLVERS,
        AnalyticAcoustics,
    )

    if not isinstance(backend, AnalyticAcoustics):
        raise TypeError("Dataset truth production requires AnalyticAcoustics.")
    prepared, rendered, solver_id = backend._render_signal(scene, array_id, time_window)
    block = assemble_signal_block(
        prepared,
        rendered,
        backend_id=backend.backend_id,
        solver_id=solver_id,
        core_solver=solver_id in _CORE_SOLVERS,
        effects=backend.effects,
    )
    frame = _frame_from_signal(
        block,
        scene,
        array_id,
        perception=perception,
        waveform_sink=waveform_sink,
        external_observations=external_observations,
    )
    sample_count = block.samples.shape[1]
    # Renders can retain a longer private tail; evidence must use the public window.
    stems = rendered.premix[:, :, :sample_count]
    if stems.shape[2] < sample_count:
        stems = np.pad(stems, ((0, 0), (0, 0), (0, sample_count - stems.shape[2])))
    received = np.sqrt(np.mean(stems * stems, axis=2))
    residual = block.samples.astype(float) - np.sum(stems, axis=0)
    residual_rms = np.sqrt(np.mean(residual * residual, axis=1))
    active_indices = {
        source.source_id: index for index, source in enumerate(prepared.active)
    }
    occlusions = {
        item.source_id: item
        for item in (scene.occlusion or ())
        if item.array_id == array_id
    }
    events = []
    for source in scene.sources:
        local = rotate_vector_by_quaternion(
            subtract(source.position_world, prepared.sensor.position_world),
            quaternion_conjugate(prepared.sensor.orientation_world_quat),
        )
        distance = norm(local)
        index = active_indices.get(source.source_id)
        events.append(
            TruthEvent(
                source_id=source.source_id,
                class_label=source.class_label,
                position_world_m=source.position_world,
                orientation_world_xyzw=source.orientation_world_quat,
                bearing_deg=bearing_from_components(local[0], local[1])
                if distance
                else None,
                elevation_deg=math.degrees(
                    math.atan2(local[2], math.hypot(local[0], local[1]))
                )
                if distance
                else None,
                distance_m=distance,
                prim_path=source.prim_path,
                audio_asset_path=source.audio_asset_path
                or "generated://deterministic_pulse",
                schedule_overlap=source.is_active_in(
                    time_window.start_time_s, time_window.end_time_s
                ),
                emission_rms=0.0
                if index is None
                else rendered.scheduled[index].emission_rms,
                received_rms={
                    mic_id: 0.0 if index is None else float(received[index, mic_index])
                    for mic_index, mic_id in enumerate(block.microphone_ids)
                },
                occlusion=occlusions.get(source.source_id),
            )
        )
    truth = FrameTruth(
        frame_id=frame.frame_id,
        array_id=array_id,
        time_window=time_window,
        sample_rate_hz=block.sample_rate_hz,
        truth_events=tuple(events),
        mixture_residual_rms=dict(
            zip(block.microphone_ids, residual_rms.tolist(), strict=True)
        ),
    )
    return frame, block, truth


__all__ = ["simulate_dataset_frame"]
