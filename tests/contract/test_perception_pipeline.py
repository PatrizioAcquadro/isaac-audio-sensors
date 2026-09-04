from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core import (
    ActivityDecision,
    AudioObservation,
    AudioPerceptionPipeline,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
    ObservationOrigin,
)


class FakeDetector:
    detector_id = "fake"

    def __init__(self, active: bool, probability: float | None = 0.75) -> None:
        self.active = active
        self.probability = probability
        self.calls: list[tuple[np.ndarray, int]] = []
        self.reset_count = 0

    def detect(
        self,
        samples: np.ndarray,
        sample_rate_hz: int,
    ) -> ActivityDecision:
        self.calls.append((samples, sample_rate_hz))
        return ActivityDecision(
            active=self.active,
            activity_probability=self.probability,
            diagnostics={"activity": "fake"},
        )

    def reset(self) -> None:
        self.reset_count += 1


class FakeEstimator:
    def __init__(self, estimate: DoaEstimate) -> None:
        self.result = estimate
        self.calls: list[tuple[np.ndarray, np.ndarray, int]] = []

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        self.calls.append((samples, microphone_positions_m, sample_rate_hz))
        return self.result, {"localization": "fake"}


class RawEstimator:
    def __init__(self, result: object) -> None:
        self.result = result

    def estimate(self, samples, microphone_positions_m, sample_rate_hz):
        del samples, microphone_positions_m, sample_rate_hz
        return self.result


class StatefulPerceptionComponent:
    detector_id = "stateful"

    def __init__(self) -> None:
        self.reset_count = 0

    def detect(self, samples, sample_rate_hz):
        del samples, sample_rate_hz
        return ActivityDecision(active=False)

    def estimate(self, samples, microphone_positions_m, sample_rate_hz):
        del samples, microphone_positions_m, sample_rate_hz
        return DoaEstimate(estimated_bearing_deg=0.0), {}

    def reset(self) -> None:
        self.reset_count += 1


class SequenceDetector(FakeDetector):
    def __init__(self, decisions: list[bool]) -> None:
        super().__init__(False)
        self.decisions = iter(decisions)

    def detect(self, samples, sample_rate_hz):
        self.active = next(self.decisions)
        return super().detect(samples, sample_rate_hz)


class ConsumerPolicyEstimator:
    consumer_context_duration_s = 0.25
    consumer_jump_threshold_deg = 150.0
    consumer_confirmation_tolerance_deg = 30.0

    def __init__(self, bearings: list[float]) -> None:
        self.bearings = iter(bearings)
        self.calls: list[np.ndarray] = []

    def estimate(self, samples, microphone_positions_m, sample_rate_hz):
        del microphone_positions_m
        self.calls.append(np.array(samples, copy=True))
        required = round(self.consumer_context_duration_s * sample_rate_hz)
        if samples.shape[1] < required:
            return (
                DoaEstimate(
                    estimated_bearing_deg=None,
                    ambiguity_class="insufficient_context",
                    ambiguity_reason="complete causal context required",
                ),
                {"doa_estimator": "policy_fake", "resolved": False},
            )
        bearing = next(self.bearings)
        return (
            DoaEstimate(
                estimated_bearing_deg=bearing,
                candidate_bearing_deg=(bearing,),
                bearing_confidence=0.8,
            ),
            {
                "doa_estimator": "policy_fake",
                "reliability_score": 0.8,
                "resolved": True,
            },
        )


def test_inactive_and_detector_free_frames_have_no_observations() -> None:
    detector = FakeDetector(False)
    inactive = AudioPerceptionPipeline(activity_detector=detector).process(
        _block(), _array(), frame_id="inactive"
    )
    detector_free = AudioPerceptionPipeline().process(
        _block(), _array(), frame_id="detector_free"
    )

    assert inactive.observations == ()
    assert detector_free.observations == ()
    assert len(detector.calls) == 1
    assert detector_free.waveform_paths == ()


def test_reset_reaches_each_stateful_component_once_by_identity() -> None:
    shared = StatefulPerceptionComponent()
    pipeline = AudioPerceptionPipeline(
        activity_detector=shared,
        doa_estimator=shared,
    )

    pipeline.reset()

    assert shared.reset_count == 1


def test_activity_decision_probability_and_diagnostics_are_bounded() -> None:
    diagnostics = {"energy_dbfs": -24.0}
    decision = ActivityDecision(
        active=True,
        activity_probability=0.0,
        diagnostics=diagnostics,
    )
    diagnostics["energy_dbfs"] = -12.0

    assert decision.activity_probability == 0.0
    assert decision.diagnostics == {"energy_dbfs": -24.0}
    assert ActivityDecision(active=True, activity_probability=1.0)
    assert ActivityDecision(active=False).activity_probability is None
    for invalid in (-0.01, 1.01, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="activity_probability"):
            ActivityDecision(active=True, activity_probability=invalid)
    with pytest.raises(ValueError, match="active"):
        ActivityDecision(active=1)
    with pytest.raises(TypeError, match="diagnostics"):
        ActivityDecision(active=False, diagnostics=())


def test_stream_boundaries_require_an_explicit_reset() -> None:
    detector = FakeDetector(False)
    pipeline = AudioPerceptionPipeline(activity_detector=detector)
    pipeline.process(_block(), _array(), frame_id="before_gap")
    pipeline.process(
        _block(
            time_window=AudioTimeWindow(
                start_time_s=10.0,
                end_time_s=11.0,
                frame_index=99,
            )
        ),
        _array(),
        frame_id="after_gap",
    )

    assert detector.reset_count == 0
    pipeline.reset()
    assert detector.reset_count == 1


def test_block_diagnostics_are_copied_beside_perception_namespace() -> None:
    block = _block(diagnostics={"analytic_solver": {"solver_id": "test"}})
    frame = AudioPerceptionPipeline().process(
        block, _array(), frame_id="diagnostics"
    )

    assert frame.diagnostics["analytic_solver"] == {"solver_id": "test"}
    assert frame.diagnostics["perception"]["activity_ran"] is False
    assert frame.diagnostics is not block.diagnostics
    assert "perception" not in block.diagnostics


def test_active_signal_creates_one_observation_and_preserves_unresolved_doa() -> None:
    unresolved = DoaEstimate(
        estimated_bearing_deg=None,
        candidate_bearing_deg=(90.0, 270.0),
        bearing_confidence=0.0,
        ambiguity_class="two_mic_front_back",
        ambiguity_reason="two compatible bearings",
    )
    detector = FakeDetector(True, probability=0.8)
    estimator = FakeEstimator(unresolved)
    frame = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    ).process(_block(), _array(), frame_id="active")

    assert len(frame.observations) == 1
    observation = frame.observations[0]
    assert observation.origin is ObservationOrigin.SIGNAL_DERIVED
    assert observation.detector_id == "fake"
    assert observation.detection_score == 0.8
    assert observation.doa is unresolved
    assert len(estimator.calls) == 1


def test_one_valid_channel_reaches_detector_and_skips_estimator() -> None:
    detector = FakeDetector(True)
    estimator = FakeEstimator(
        DoaEstimate(estimated_bearing_deg=0.0, bearing_confidence=0.5)
    )
    block = _block(
        samples=np.array(
            [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]],
            dtype=np.float32,
        ),
        channel_validity=(False, True),
    )
    frame = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    ).process(block, _array(), frame_id="partial")

    detector_samples, detector_rate = detector.calls[0]
    assert detector_rate == 4
    assert detector_samples.tolist() == [[5.0, 6.0, 7.0, 8.0]]
    assert not detector_samples.flags.writeable
    assert estimator.calls == []
    assert frame.observations[0].doa is None
    assert frame.channel_validity == {"left": False, "right": True}
    assert frame.aggregate_per_mic_rms == pytest.approx(
        {"left": np.sqrt(7.5), "right": np.sqrt(43.5)}
    )


def test_only_final_valid_mixture_and_local_geometry_reach_estimator() -> None:
    detector = FakeDetector(True)
    estimator = FakeEstimator(
        DoaEstimate(estimated_bearing_deg=0.0, bearing_confidence=0.5)
    )
    array = _three_mic_array()
    block = _block(
        samples=np.array(
            (
                (1.0, 2.0, 3.0, 4.0),
                (5.0, 6.0, 7.0, 8.0),
                (9.0, 10.0, 11.0, 12.0),
            ),
            dtype=np.float32,
        ),
        microphone_ids=("front", "right", "left"),
        channel_validity=(True, False, True),
    )

    AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    ).process(block, array, frame_id="mixture_only")

    samples, positions, sample_rate_hz = estimator.calls[0]
    assert sample_rate_hz == block.sample_rate_hz
    assert samples.tolist() == [[1.0, 2.0, 3.0, 4.0], [9.0, 10.0, 11.0, 12.0]]
    assert not samples.flags.writeable
    assert positions.tolist() == [[0.1, 0.0, 0.0], [0.0, -0.1, 0.0]]


@pytest.mark.parametrize(
    ("result", "message"),
    (
        (DoaEstimate(estimated_bearing_deg=0.0), "return"),
        ((object(), {}), "DoaEstimate"),
        ((DoaEstimate(estimated_bearing_deg=0.0), ()), "diagnostics"),
    ),
)
def test_structurally_invalid_doa_results_fail_closed(result, message) -> None:
    with pytest.raises(TypeError, match=message):
        AudioPerceptionPipeline(
            activity_detector=FakeDetector(True),
            doa_estimator=RawEstimator(result),
        ).process(_block(), _array(), frame_id="invalid_doa")


def test_fully_invalid_block_skips_all_perception() -> None:
    detector = FakeDetector(True)
    estimator = FakeEstimator(DoaEstimate(estimated_bearing_deg=0.0))
    frame = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    ).process(
        _block(channel_validity=(False, False)),
        _array(),
        frame_id="invalid",
    )

    assert detector.calls == []
    assert estimator.calls == []
    assert frame.observations == ()


def test_causal_context_accumulates_inactive_blocks_and_keeps_trailing_window() -> None:
    detector = SequenceDetector([False, False, False, False, True, True])
    estimator = ConsumerPolicyEstimator([0.0, 0.0])
    pipeline = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    )

    frames = [
        pipeline.process(
            _stream_block(index, value=float(index + 1)),
            _stream_array(),
            frame_id=f"rolling_{index}",
        )
        for index in range(6)
    ]

    assert all(not frame.observations for frame in frames[:4])
    assert frames[4].observations[0].doa.estimated_bearing_deg == 0.0
    assert estimator.calls[0].tolist() == [[1, 2, 3, 4, 5]] * 3
    assert estimator.calls[1].tolist() == [[2, 3, 4, 5, 6]] * 3
    context = frames[5].diagnostics["perception"]["doa_context"]
    assert context == {
        "required_duration_s": 0.25,
        "required_sample_count": 5,
        "available_duration_s": 0.25,
        "available_sample_count": 5,
        "complete": True,
        "reset_reason": None,
    }


def test_opposite_jump_requires_next_active_confirmation() -> None:
    detector = SequenceDetector([True] * 7)
    estimator = ConsumerPolicyEstimator([0.0, 180.0, 178.0])
    pipeline = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    )

    frames = [
        pipeline.process(
            _stream_block(index, value=float(index + 1)),
            _stream_array(),
            frame_id=f"jump_{index}",
        )
        for index in range(7)
    ]

    assert all(
        frame.observations[0].doa.ambiguity_class == "insufficient_context"
        for frame in frames[:4]
    )
    assert frames[4].observations[0].doa.estimated_bearing_deg == 0.0
    unstable = frames[5].observations[0]
    assert unstable.doa.estimated_bearing_deg is None
    assert unstable.doa.ambiguity_class == "temporal_instability"
    assert unstable.doa.candidate_bearing_deg == (180.0,)
    assert (
        unstable.diagnostics["doa_estimator"]["consumer"]["temporal_stability"][
            "status"
        ]
        == "confirmation_required"
    )
    confirmed = frames[6].observations[0]
    assert confirmed.doa.estimated_bearing_deg == 178.0
    assert (
        confirmed.diagnostics["doa_estimator"]["consumer"][
            "temporal_stability"
        ]["status"]
        == "accepted_confirmed"
    )


def test_failed_confirmation_abstains_and_inactivity_clears_reference() -> None:
    detector = SequenceDetector([True] * 7 + [False, True])
    estimator = ConsumerPolicyEstimator([0.0, 180.0, 90.0, 180.0])
    pipeline = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    )
    frames = [
        pipeline.process(
            _stream_block(index, value=float(index + 1)),
            _stream_array(),
            frame_id=f"reset_{index}",
        )
        for index in range(9)
    ]

    assert frames[5].observations[0].doa.ambiguity_class == "temporal_instability"
    assert frames[6].observations[0].doa.ambiguity_class == "temporal_instability"
    assert frames[7].observations == ()
    assert frames[8].observations[0].doa.estimated_bearing_deg == 180.0
    assert (
        frames[8].observations[0].diagnostics["doa_estimator"]["consumer"][
            "temporal_stability"
        ]["status"]
        == "accepted_initial"
    )


def test_doa_context_resets_on_discontinuity_and_explicit_reset() -> None:
    detector = SequenceDetector([False, False, False])
    estimator = ConsumerPolicyEstimator([])
    pipeline = AudioPerceptionPipeline(
        activity_detector=detector,
        doa_estimator=estimator,
    )
    pipeline.process(_stream_block(0, value=1.0), _stream_array(), frame_id="first")
    gap = pipeline.process(
        _stream_block(2, value=3.0),
        _stream_array(),
        frame_id="gap",
    )
    assert gap.diagnostics["perception"]["doa_context"]["reset_reason"] == (
        "non_contiguous_time_window"
    )
    assert gap.diagnostics["perception"]["doa_context"]["available_sample_count"] == 1

    pipeline.reset()
    after_reset = pipeline.process(
        _stream_block(3, value=4.0),
        _stream_array(),
        frame_id="after_reset",
    )
    assert after_reset.diagnostics["perception"]["doa_context"][
        "available_sample_count"
    ] == 1


@pytest.mark.parametrize(
    ("block_overrides", "message"),
    (
        ({"array_id": "other"}, "array_id"),
        ({"sample_rate_hz": 8, "samples": np.zeros((2, 8))}, "sample_rate"),
        ({"microphone_ids": ("right", "left")}, "microphone order"),
    ),
)
def test_block_array_mismatch_is_rejected(block_overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        AudioPerceptionPipeline().process(
            _block(**block_overrides), _array(), frame_id="mismatch"
        )


def test_external_observations_follow_signal_then_input_order_before_cap() -> None:
    external_a = _external("external_a")
    external_b = _external("external_b")
    frame = AudioPerceptionPipeline(
        activity_detector=FakeDetector(True),
        max_observations=2,
    ).process(
        _block(),
        _array(),
        frame_id="ordered",
        external_observations=(external_a, external_b),
    )

    assert [item.origin for item in frame.observations] == [
        ObservationOrigin.SIGNAL_DERIVED,
        ObservationOrigin.EXTERNAL_SYSTEM,
    ]
    assert [item.observation_id for item in frame.observations] == [
        "ordered_fake_00",
        "external_a",
    ]


def test_zero_cap_runs_detector_without_resetting_stream_state() -> None:
    detector = FakeDetector(True, probability=None)
    pipeline = AudioPerceptionPipeline(
        activity_detector=detector,
        max_observations=0,
    )

    first = pipeline.process(_block(), _array(), frame_id="capped_0")
    second = pipeline.process(_block(), _array(), frame_id="capped_1")

    assert first.observations == second.observations == ()
    assert len(detector.calls) == 2
    assert detector.reset_count == 0
    assert first.diagnostics["perception"]["activity_detected"] is True
    assert first.aggregate_per_mic_rms


def test_external_origin_and_all_pre_cap_id_collisions_are_rejected() -> None:
    with pytest.raises(ValueError, match="external_system"):
        AudioPerceptionPipeline().process(
            _block(),
            _array(),
            frame_id="origin",
            external_observations=(
                replace(_external("external"), origin=ObservationOrigin.SIGNAL_DERIVED),
            ),
        )

    pipeline = AudioPerceptionPipeline(max_observations=1)
    with pytest.raises(ValueError, match="unique"):
        pipeline.process(
            _block(),
            _array(),
            frame_id="duplicate",
            external_observations=(_external("same"), _external("same")),
        )


def _array() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=(1.0, 2.0, 3.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -0.1, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, 0.1, 0.0)),
        ),
        sample_rate_hz=4,
    )


def _three_mic_array() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=(4.0, 5.0, 6.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="front", relative_position_m=(0.1, 0.0, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, 0.1, 0.0)),
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -0.1, 0.0)),
        ),
        sample_rate_hz=4,
    )


def _stream_array() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="stream_rig",
        prim_path="/World/StreamRig",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="front", relative_position_m=(0.1, 0.0, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, 0.1, 0.0)),
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -0.1, 0.0)),
        ),
        sample_rate_hz=20,
    )


def _stream_block(index: int, *, value: float) -> MicrophoneSignalBlock:
    start = index * 0.05
    return MicrophoneSignalBlock(
        samples=np.full((3, 1), value, dtype=np.float32),
        microphone_ids=("front", "right", "left"),
        array_id="stream_rig",
        sample_rate_hz=20,
        time_window=AudioTimeWindow(
            start_time_s=start,
            end_time_s=start + 0.05,
            frame_index=index,
        ),
        channel_validity=(True, True, True),
        producer_id="stream",
        provenance="synthetic/core",
    )


def _block(**overrides: object) -> MicrophoneSignalBlock:
    values: dict[str, object] = {
        "samples": np.ones((2, 4), dtype=np.float32),
        "microphone_ids": ("left", "right"),
        "array_id": "rig",
        "sample_rate_hz": 4,
        "time_window": AudioTimeWindow(
            start_time_s=1.0, end_time_s=2.0, frame_index=3
        ),
        "channel_validity": (True, True),
        "producer_id": "capture",
        "provenance": "synthetic/core",
    }
    values.update(overrides)
    if "sample_rate_hz" in overrides and "time_window" not in overrides:
        values["time_window"] = AudioTimeWindow(
            start_time_s=1.0, end_time_s=2.0, frame_index=3
        )
    return MicrophoneSignalBlock(**values)


def _external(observation_id: str) -> AudioObservation:
    return AudioObservation(
        observation_id=observation_id,
        origin=ObservationOrigin.EXTERNAL_SYSTEM,
        detector_id="external_adapter",
    )
