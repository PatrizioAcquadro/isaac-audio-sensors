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


def test_only_valid_channels_reach_detector_and_estimator_in_array_order() -> None:
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
