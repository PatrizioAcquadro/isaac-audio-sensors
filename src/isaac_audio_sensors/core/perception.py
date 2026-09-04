"""Observed-signal perception and sensor-frame construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from isaac_audio_sensors.core.types import (
    ActivityDecision,
    AudioObservation,
    AudioSensorFrame,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    ObservationOrigin,
    Pose3D,
)
from isaac_audio_sensors.core.types._validation import require_non_empty

if TYPE_CHECKING:
    from isaac_audio_sensors.core.plugins.protocols import (
        ActivityDetector,
        DoaEstimator,
    )


class AudioPerceptionPipeline:
    """Create observed-only frames from immutable microphone signal blocks."""

    def __init__(
        self,
        *,
        activity_detector: ActivityDetector | None = None,
        doa_estimator: DoaEstimator | None = None,
        max_observations: int | None = None,
    ) -> None:
        if activity_detector is None:
            if doa_estimator is not None:
                raise ValueError(
                    "doa_estimator requires an injected activity_detector."
                )
            detector_id = None
        else:
            if not callable(getattr(activity_detector, "detect", None)):
                raise TypeError(
                    "activity_detector must provide a callable detect method."
                )
            if not callable(getattr(activity_detector, "reset", None)):
                raise TypeError(
                    "activity_detector must provide a callable reset method."
                )
            detector_id = getattr(activity_detector, "detector_id", None)
            require_non_empty(detector_id, "AudioPerceptionPipeline.detector_id")
        if doa_estimator is not None and not callable(
            getattr(doa_estimator, "estimate", None)
        ):
            raise TypeError("doa_estimator must provide a callable estimate method.")
        if max_observations is not None and (
            type(max_observations) is not int or max_observations < 0
        ):
            raise ValueError("max_observations must be a non-negative integer.")

        self._activity_detector = activity_detector
        self.detector_id = detector_id
        self._doa_estimator = doa_estimator
        self.max_observations = max_observations

    def reset(self) -> None:
        """Reset each injected stateful perception component once."""

        seen: set[int] = set()
        for component in (self._activity_detector, self._doa_estimator):
            if component is None or id(component) in seen:
                continue
            seen.add(id(component))
            reset = getattr(component, "reset", None)
            if callable(reset):
                reset()

    def process(
        self,
        block: MicrophoneSignalBlock,
        array: MicrophoneArraySpec,
        *,
        frame_id: str,
        frame_name: str | None = None,
        external_observations: Sequence[AudioObservation] = (),
    ) -> AudioSensorFrame:
        """Run injected perception and build one frame for the signal window."""

        import numpy as np

        if not isinstance(block, MicrophoneSignalBlock):
            raise TypeError("block must be a MicrophoneSignalBlock.")
        if not isinstance(array, MicrophoneArraySpec):
            raise TypeError("array must be a MicrophoneArraySpec.")
        require_non_empty(frame_id, "AudioPerceptionPipeline.frame_id")
        if frame_name is not None:
            require_non_empty(frame_name, "AudioPerceptionPipeline.frame_name")
        self._validate_binding(block, array)

        external = tuple(external_observations)
        for observation in external:
            if not isinstance(observation, AudioObservation):
                raise TypeError(
                    "external_observations must contain AudioObservation values."
                )
            if observation.origin is not ObservationOrigin.EXTERNAL_SYSTEM:
                raise ValueError(
                    "external_observations must use origin='external_system'."
                )

        valid_indices = tuple(
            index for index, valid in enumerate(block.channel_validity) if valid
        )
        perception_diagnostics: dict[str, object] = {
            "activity_detected": None,
            "activity_ran": False,
            "channel_count": len(block.microphone_ids),
            "valid_channel_count": len(valid_indices),
        }
        signal_observations: tuple[AudioObservation, ...] = ()
        if valid_indices and self._activity_detector is not None:
            valid_samples = np.ascontiguousarray(block.samples[list(valid_indices)])
            valid_samples.setflags(write=False)
            decision = self._activity_detector.detect(
                valid_samples,
                block.sample_rate_hz,
            )
            if not isinstance(decision, ActivityDecision):
                raise TypeError(
                    "activity_detector.detect() must return an ActivityDecision."
                )
            detector_diagnostics = dict(decision.diagnostics)
            perception_diagnostics.update(
                {
                    "activity_detected": decision.active,
                    "activity_probability": decision.activity_probability,
                    "activity_ran": True,
                    "detector_id": self.detector_id,
                    "detector_diagnostics": detector_diagnostics,
                }
            )
            if decision.active:
                observation_diagnostics: dict[str, object] = {
                    "activity_detector": detector_diagnostics,
                }
                doa: DoaEstimate | None = None
                if self._doa_estimator is not None and len(valid_indices) >= 2:
                    positions = np.asarray(
                        [
                            array.microphones[index].relative_position_m
                            for index in valid_indices
                        ],
                        dtype=float,
                    )
                    doa, doa_diagnostics = _doa_result(
                        self._doa_estimator.estimate(
                            valid_samples,
                            positions,
                            block.sample_rate_hz,
                        )
                    )
                    observation_diagnostics["doa_estimator"] = doa_diagnostics
                elif self._doa_estimator is not None:
                    observation_diagnostics["doa_skipped"] = (
                        "fewer_than_two_valid_channels"
                    )
                assert self.detector_id is not None
                signal_observations = (
                    AudioObservation(
                        observation_id=(
                            f"{frame_id}_{self.detector_id}_00"
                        ),
                        origin=ObservationOrigin.SIGNAL_DERIVED,
                        detector_id=self.detector_id,
                        detection_score=decision.activity_probability,
                        doa=doa,
                        diagnostics=observation_diagnostics,
                    ),
                )

        observations = signal_observations + external
        observation_ids = tuple(
            observation.observation_id for observation in observations
        )
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("AudioObservation.observation_id values must be unique.")
        if self.max_observations is not None:
            observations = observations[: self.max_observations]

        time_window = block.time_window
        return AudioSensorFrame(
            frame_id=frame_id,
            frame_name=frame_name,
            producer_id=block.producer_id,
            array_id=block.array_id,
            channel_validity=dict(
                zip(block.microphone_ids, block.channel_validity, strict=True)
            ),
            array_pose=Pose3D.from_array(array),
            start_time_s=time_window.start_time_s,
            end_time_s=time_window.end_time_s,
            sample_rate_hz=block.sample_rate_hz,
            frame_index=time_window.frame_index,
            coordinate_convention=array.coordinate_convention,
            provenance=block.provenance,
            max_observations=self.max_observations,
            observations=observations,
            aggregate_per_mic_rms={
                microphone_id: float(
                    np.sqrt(np.mean(np.square(block.samples[index], dtype=float)))
                )
                for index, microphone_id in enumerate(block.microphone_ids)
            },
            waveform_paths=(),
            diagnostics={
                **block.diagnostics,
                "perception": perception_diagnostics,
            },
        )

    @staticmethod
    def _validate_binding(
        block: MicrophoneSignalBlock,
        array: MicrophoneArraySpec,
    ) -> None:
        if block.array_id != array.array_id:
            raise ValueError(
                "MicrophoneSignalBlock.array_id must match "
                "MicrophoneArraySpec.array_id."
            )
        if block.sample_rate_hz != array.sample_rate_hz:
            raise ValueError(
                "MicrophoneSignalBlock.sample_rate_hz must match "
                "MicrophoneArraySpec.sample_rate_hz."
            )
        expected_microphone_ids = tuple(
            microphone.mic_id for microphone in array.microphones
        )
        if block.microphone_ids != expected_microphone_ids:
            raise ValueError(
                "MicrophoneSignalBlock.microphone_ids must exactly match the "
                "MicrophoneArraySpec microphone order."
            )


def _doa_result(result: object) -> tuple[DoaEstimate, dict[str, object]]:
    if not isinstance(result, tuple) or len(result) != 2:
        raise TypeError("doa_estimator must return (DoaEstimate, diagnostics).")
    doa, diagnostics = result
    if not isinstance(doa, DoaEstimate):
        raise TypeError("doa_estimator must return a DoaEstimate.")
    if not isinstance(diagnostics, Mapping):
        raise TypeError("doa_estimator diagnostics must be a mapping.")
    return doa, dict(diagnostics)


__all__ = ["AudioPerceptionPipeline"]
