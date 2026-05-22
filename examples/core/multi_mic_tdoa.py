"""Four-microphone synthetic TDOA example."""

from __future__ import annotations

from examples.core.single_source_bearing import array, scene
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.types import AudioTimeWindow

frame = TdoaSyntheticBackend().simulate(
    scene,
    array,
    AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=array.sample_rate_hz,
    ),
)
print(frame.detections[0].per_mic_delay_s)
print(frame.detections[0].doa)
