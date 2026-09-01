"""Optional closed-room AnalyticAcoustics example."""

from __future__ import annotations

from isaac_audio_sensors.core.acoustics import shoebox_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)

array = create_microphone_array(
    array_id="rig_front",
    prim_path="/World/Rig/AudioArray",
    layout_name="quad_front",
)
scene = AudioSceneSnapshot(
    stage_id="analytic_acoustics_example",
    sources=(
        AudioSourceSpec(
            source_id="speaker",
            prim_path="/World/Sources/Speaker",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            position_world=(3.0, 2.0, 1.0),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    ),
    arrays=(array,),
    environment=shoebox_environment(
        environment_id="shoebox",
        dimensions_m=(5.0, 4.0, 2.7),
        absorption=0.35,
        # World placement of the environment's local origin: the array and
        # speaker both remain inside the shoebox.
        position_world=(-1.0, -1.0, -0.5),
    ),
)
try:
    frame = AnalyticAcoustics(max_order=2).simulate(
        scene,
        array.array_id,
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            frame_index=0,
        ),
    )
except OptionalDependencyUnavailable as exc:
    print(f"analytic_acoustics closed-room solver skipped: {exc}")
else:
    print(
        {
            "backend": frame.backend_id,
            "active_source_count": frame.diagnostics["active_source_count"],
            "pyroomacoustics_version": frame.diagnostics["pyroomacoustics_version"],
            "environment_config": frame.diagnostics["environment_config"],
            "rir_summary": frame.diagnostics["per_source_rir_summary"],
        }
    )
    print(frame.detections[0].diagnostics["estimated_tdoa_matrix_s"])
