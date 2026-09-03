"""Optional closed-room AnalyticAcoustics example."""

from __future__ import annotations

from isaac_audio_sensors.core import AudioPerceptionPipeline
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
    block = AnalyticAcoustics(max_order=2).propagate(
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
    frame = AudioPerceptionPipeline().process(
        block,
        array,
        frame_id="analytic_acoustics_example_000000",
    )
    print(
        {
            "producer": frame.producer_id,
            "observations": len(frame.observations),
            "aggregate_per_mic_rms": frame.aggregate_per_mic_rms,
            "solver": block.diagnostics["analytic_solver"],
        }
    )
