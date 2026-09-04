"""Two-microphone TDOA ambiguity example."""

from __future__ import annotations

from isaac_audio_sensors.core import AudioPerceptionPipeline
from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.plugins import AuditokActivityDetector
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)

array = create_microphone_array(
    array_id="rig_stereo",
    prim_path="/World/Rig/StereoAudioArray",
    layout_name="stereo_y",
)
scene = AudioSceneSnapshot(
    stage_id="two_mic_ambiguity_example",
    sources=(
        AudioSourceSpec(
            source_id="speaker_front",
            prim_path="/World/Sources/SpeakerFront",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            position_world=(5.0, 0.0, 0.0),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    ),
    arrays=(array,),
    environment=free_field_environment(environment_id="ambiguity_free_field"),
)
block = AnalyticAcoustics().propagate(
    scene,
    array.array_id,
    AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        frame_index=0,
    ),
)
frame = AudioPerceptionPipeline(
    activity_detector=AuditokActivityDetector(energy_threshold_dbfs=-60.0)
).process(
    block,
    array,
    frame_id="two_mic_ambiguity_example_000000",
)
print(
    {
        "producer": frame.producer_id,
        "observations": len(frame.observations),
        "note": "Activity detection does not invent a source identity or DOA.",
    }
)
