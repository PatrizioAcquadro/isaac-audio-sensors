"""Two-microphone TDOA ambiguity example."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.microphone_array import create_microphone_array
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
    timestamp_ms=0,
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
)
frame = TdoaSyntheticBackend(ambiguity_policy="none").simulate(
    scene,
    array.array_id,
    AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=array.sample_rate_hz,
    ),
)
print(frame.detections[0].doa)
