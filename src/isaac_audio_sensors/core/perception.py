"""Observed-signal perception and sensor-frame construction."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSensorFrame,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    ObservationOrigin,
    Pose3D,
)
from isaac_audio_sensors.core.types._validation import require_non_empty

_ActivityDetector = Callable[
    [Any, int],
    tuple[bool, float | None, Mapping[str, object]],
]


class AudioPerceptionPipeline:
    """Create observed-only frames from immutable microphone signal blocks."""

    def __init__(
        self,
        *,
        activity_detector: _ActivityDetector | None = None,
        detector_id: str | None = None,
        doa_estimator: object | None = None,
        max_observations: int | None = None,
    ) -> None:
        if activity_detector is None:
            if detector_id is not None:
                raise ValueError(
                    "detector_id requires an injected activity_detector."
                )
            if doa_estimator is not None:
                raise ValueError(
                    "doa_estimator requires an injected activity_detector."
                )
        else:
            if not callable(activity_detector):
                raise TypeError("activity_detector must be callable.")
            if detector_id is None:
                raise ValueError(
                    "detector_id is required with an injected activity_detector."
                )
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
            active, score, detector_diagnostics = _activity_result(
                self._activity_detector(valid_samples, block.sample_rate_hz)
            )
            perception_diagnostics.update(
                {
                    "activity_detected": active,
                    "activity_ran": True,
                    "detector_id": self.detector_id,
                    "detector_diagnostics": detector_diagnostics,
                }
            )
            if active:
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
                        detection_score=score,
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
            diagnostics={"perception": perception_diagnostics},
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


def _activity_result(
    result: object,
) -> tuple[bool, float | None, dict[str, object]]:
    if not isinstance(result, tuple) or len(result) != 3:
        raise TypeError(
            "activity_detector must return (active, detection_score, diagnostics)."
        )
    active, score, diagnostics = result
    if type(active) is not bool:
        raise TypeError("activity_detector active result must be a bool.")
    if score is not None:
        if isinstance(score, bool):
            raise ValueError("activity_detector score must be a finite number.")
        numeric_score = float(score)
        if not math.isfinite(numeric_score):
            raise ValueError("activity_detector score must be finite.")
        score = numeric_score
    if not isinstance(diagnostics, Mapping):
        raise TypeError("activity_detector diagnostics must be a mapping.")
    return active, score, dict(diagnostics)


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
