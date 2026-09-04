from __future__ import annotations

import numpy as np
import pytest

from isaac_audio_sensors.core import (
    AudioPerceptionPipeline,
    AudioSceneSnapshot,
    AudioTimeWindow,
    MicrophoneSignalBlock,
)
from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.simulation import simulate_frame, simulate_from_config
from tests.helpers import CaptureSink, quad_array


class CountingBackend:
    backend_id = "counting"

    def __init__(self, block: MicrophoneSignalBlock) -> None:
        self.block = block
        self.calls = []

    def propagate(self, scene, array_id, time_window):
        self.calls.append((scene, array_id, time_window))
        return self.block


def test_simulate_frame_propagates_once_and_shares_exact_block_with_sink() -> None:
    array = quad_array()
    window = AudioTimeWindow(start_time_s=0.0, end_time_s=0.01, frame_index=7)
    scene = AudioSceneSnapshot(
        stage_id="orchestration",
        sources=(),
        arrays=(array,),
        environment=free_field_environment(environment_id="free"),
    )
    block = MicrophoneSignalBlock(
        samples=np.zeros((4, 480), dtype=np.float32),
        microphone_ids=tuple(mic.mic_id for mic in array.microphones),
        array_id=array.array_id,
        sample_rate_hz=array.sample_rate_hz,
        time_window=window,
        channel_validity=(True, True, True, True),
        producer_id="counting",
        provenance="synthetic/core",
        diagnostics={"backend_detail": "counting"},
    )
    backend = CountingBackend(block)
    sink = CaptureSink()

    frame, returned = simulate_frame(
        backend,
        scene,
        array.array_id,
        window,
        perception=AudioPerceptionPipeline(),
        waveform_sink=sink,
    )

    assert backend.calls == [(scene, array.array_id, window)]
    assert returned is block
    assert sink.calls[0]["block"] is block
    assert frame.frame_id == "counting_orchestration_rig_0_7"
    assert frame.frame_name == "orchestration/rig/counting/frame7_t0ms"
    assert frame.observations == ()
    assert frame.diagnostics["backend_detail"] == "counting"
    assert frame.diagnostics["waveform"] == {"mode": "stub"}


@pytest.mark.parametrize("threshold", (True, float("nan")))
def test_simulate_from_config_rejects_invalid_explicit_threshold(threshold) -> None:
    with pytest.raises(ConfigValidationError, match="energy_threshold_dbfs"):
        simulate_from_config(
            "examples/configs/isaac_audio_sensors_demo.toml",
            energy_threshold_dbfs=threshold,
        )
