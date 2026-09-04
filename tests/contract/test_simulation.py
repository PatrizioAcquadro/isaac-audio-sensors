from __future__ import annotations

import numpy as np
import pytest

from isaac_audio_sensors.core import (
    ActivityDecision,
    AudioPerceptionPipeline,
    AudioSceneSnapshot,
    AudioTimeWindow,
    DoaEstimate,
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


class AlwaysActiveDetector:
    detector_id = "active"

    def detect(self, samples, sample_rate_hz):
        del samples, sample_rate_hz
        return ActivityDecision(active=True)

    def reset(self) -> None:
        pass


class CapturingEstimator:
    def __init__(self) -> None:
        self.calls = []

    def estimate(self, samples, microphone_positions_m, sample_rate_hz):
        self.calls.append((samples, microphone_positions_m, sample_rate_hz))
        return (
            DoaEstimate(
                estimated_bearing_deg=None,
                candidate_bearing_deg=(0.0, 180.0),
                ambiguity_class="ambiguous_front_back",
                ambiguity_reason="two compatible bearings",
            ),
            {"localization": "captured_mixture"},
        )


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


def test_simulate_frame_localizes_only_the_propagated_mixture() -> None:
    array = quad_array()
    window = AudioTimeWindow(start_time_s=0.0, end_time_s=0.01, frame_index=8)
    scene = AudioSceneSnapshot(
        stage_id="mixture_boundary",
        sources=(),
        arrays=(array,),
        environment=free_field_environment(environment_id="free"),
    )
    samples = np.arange(4 * 480, dtype=np.float32).reshape(4, 480)
    block = MicrophoneSignalBlock(
        samples=samples,
        microphone_ids=tuple(mic.mic_id for mic in array.microphones),
        array_id=array.array_id,
        sample_rate_hz=array.sample_rate_hz,
        time_window=window,
        channel_validity=(True, True, True, True),
        producer_id="counting",
        provenance="synthetic/core",
        diagnostics={"private_render_state": "must_not_reach_estimator"},
    )
    estimator = CapturingEstimator()

    frame, returned = simulate_frame(
        CountingBackend(block),
        scene,
        array.array_id,
        window,
        perception=AudioPerceptionPipeline(
            activity_detector=AlwaysActiveDetector(),
            doa_estimator=estimator,
        ),
    )

    observed, positions, sample_rate_hz = estimator.calls[0]
    assert returned is block
    assert np.array_equal(observed, block.samples)
    assert not observed.flags.writeable
    assert positions.tolist() == [
        list(microphone.relative_position_m) for microphone in array.microphones
    ]
    assert sample_rate_hz == block.sample_rate_hz
    assert frame.observations[0].doa is not None
    assert frame.observations[0].doa.estimated_bearing_deg is None
    assert frame.observations[0].diagnostics["doa_estimator"] == {
        "localization": "captured_mixture"
    }


@pytest.mark.parametrize("threshold", (True, float("nan")))
def test_simulate_from_config_rejects_invalid_explicit_threshold(threshold) -> None:
    with pytest.raises(ConfigValidationError, match="energy_threshold_dbfs"):
        simulate_from_config(
            "examples/configs/isaac_audio_sensors_demo.toml",
            energy_threshold_dbfs=threshold,
        )


def test_simulate_from_config_doa_is_explicitly_opt_in() -> None:
    default_frame = simulate_from_config(
        "examples/configs/isaac_audio_sensors_demo.toml",
        array_id="rig_stereo",
        energy_threshold_dbfs=-60.0,
    )
    enabled_frame = simulate_from_config(
        "examples/configs/isaac_audio_sensors_demo.toml",
        array_id="rig_stereo",
        energy_threshold_dbfs=-60.0,
        doa_enabled=True,
    )

    assert default_frame.observations[0].doa is None
    assert "doa_context" not in default_frame.diagnostics["perception"]
    assert enabled_frame.observations[0].doa is not None
    diagnostics = enabled_frame.observations[0].diagnostics["doa_estimator"]
    assert diagnostics["selection"] == {
        "policy": "maintained_roles_v1",
        "role": "two_microphone_ambiguity",
        "selected_estimator_id": "tdoa_least_squares",
    }
    context = enabled_frame.diagnostics["perception"]["doa_context"]
    assert context["causal"] is True
    assert "context" not in diagnostics["consumer"]
    assert "compute_latency_ms" not in diagnostics["consumer"]


def test_simulate_from_config_rejects_non_boolean_doa_opt_in() -> None:
    with pytest.raises(ConfigValidationError, match="doa_enabled"):
        simulate_from_config(
            "examples/configs/isaac_audio_sensors_demo.toml",
            energy_threshold_dbfs=-60.0,
            doa_enabled="true",
        )
