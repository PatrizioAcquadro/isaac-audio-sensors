"""Observed-signal perception and sensor-frame construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.exceptions import ConfigValidationError
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
        self._doa_context_duration_s = _optional_positive_attribute(
            doa_estimator,
            "consumer_context_duration_s",
        )
        self._doa_jump_threshold_deg = _optional_bearing_attribute(
            doa_estimator,
            "consumer_jump_threshold_deg",
        )
        self._doa_confirmation_tolerance_deg = _optional_bearing_attribute(
            doa_estimator,
            "consumer_confirmation_tolerance_deg",
        )
        self._doa_history: object | None = None
        self._doa_history_signature: tuple[object, ...] | None = None
        self._doa_history_end_s: float | None = None
        self._doa_stable_bearing_deg: float | None = None
        self._doa_pending_bearing_deg: float | None = None

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
        self._clear_doa_consumer_state()

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
            doa_samples: object = valid_samples
            positions: object | None = None
            if self._doa_estimator is not None:
                positions = np.asarray(
                    [
                        array.microphones[index].relative_position_m
                        for index in valid_indices
                    ],
                    dtype=float,
                )
                doa_samples, context_diagnostics = self._update_doa_context(
                    valid_samples,
                    positions,
                    tuple(block.microphone_ids[index] for index in valid_indices),
                    block,
                )
                if context_diagnostics is not None:
                    perception_diagnostics["doa_context"] = context_diagnostics
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
            if not decision.active:
                self._clear_doa_temporal_state()
            if decision.active:
                observation_diagnostics: dict[str, object] = {
                    "activity_detector": detector_diagnostics,
                }
                doa: DoaEstimate | None = None
                if self._doa_estimator is not None and len(valid_indices) >= 2:
                    assert positions is not None
                    doa, doa_diagnostics = _doa_result(
                        self._doa_estimator.estimate(
                            doa_samples,
                            positions,
                            block.sample_rate_hz,
                        )
                    )
                    doa, temporal_diagnostics = self._apply_doa_temporal_policy(doa)
                    if self._doa_context_duration_s is not None:
                        doa_diagnostics["consumer"] = {
                            "temporal_stability": temporal_diagnostics,
                        }
                    observation_diagnostics["doa_estimator"] = doa_diagnostics
                elif self._doa_estimator is not None:
                    observation_diagnostics["doa_skipped"] = (
                        "fewer_than_two_valid_channels"
                    )
                assert self.detector_id is not None
                signal_observations = (
                    AudioObservation(
                        observation_id=(f"{frame_id}_{self.detector_id}_00"),
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

    def _update_doa_context(
        self,
        samples: object,
        positions: object,
        microphone_ids: tuple[str, ...],
        block: MicrophoneSignalBlock,
    ) -> tuple[object, dict[str, object] | None]:
        import numpy as np

        if self._doa_estimator is None or self._doa_context_duration_s is None:
            return samples, None

        values = np.asarray(samples)
        geometry = np.asarray(positions, dtype=float)
        signature = (
            block.array_id,
            block.producer_id,
            block.provenance,
            block.sample_rate_hz,
            microphone_ids,
            geometry.shape,
            geometry.tobytes(),
        )
        reset_reason: str | None = None
        if (
            self._doa_history_signature is not None
            and signature != self._doa_history_signature
        ):
            previous_signature = self._doa_history_signature
            if signature[:3] != previous_signature[:3]:
                reset_reason = "stream_identity_changed"
            elif signature[3] != previous_signature[3]:
                reset_reason = "sample_rate_changed"
            else:
                reset_reason = "valid_channel_layout_changed"
            self._clear_doa_consumer_state()
        elif self._doa_history_end_s is not None and not _times_touch(
            self._doa_history_end_s,
            block.time_window.start_time_s,
        ):
            reset_reason = "non_contiguous_time_window"
            self._clear_doa_consumer_state()

        previous = self._doa_history
        buffered = (
            np.array(values, copy=True, order="C")
            if previous is None
            else np.concatenate((np.asarray(previous), values), axis=1)
        )
        required_samples = round(self._doa_context_duration_s * block.sample_rate_hz)
        if buffered.shape[1] > required_samples:
            buffered = np.array(
                buffered[:, -required_samples:],
                copy=True,
                order="C",
            )
        buffered.setflags(write=False)
        self._doa_history = buffered
        self._doa_history_signature = signature
        self._doa_history_end_s = block.time_window.end_time_s
        return buffered, {
            "causal": True,
            "required_duration_s": self._doa_context_duration_s,
            "required_sample_count": required_samples,
            "available_duration_s": buffered.shape[1] / block.sample_rate_hz,
            "available_sample_count": int(buffered.shape[1]),
            "complete": buffered.shape[1] == required_samples,
            "reset_reason": reset_reason,
        }

    def _apply_doa_temporal_policy(
        self,
        estimate: DoaEstimate,
    ) -> tuple[DoaEstimate, dict[str, object] | None]:
        threshold = self._doa_jump_threshold_deg
        tolerance = self._doa_confirmation_tolerance_deg
        if threshold is None or tolerance is None:
            return estimate, None

        bearing = estimate.estimated_bearing_deg
        stable = self._doa_stable_bearing_deg
        pending = self._doa_pending_bearing_deg
        diagnostics: dict[str, object] = {
            "jump_threshold_deg": threshold,
            "confirmation_tolerance_deg": tolerance,
            "previous_accepted_bearing_deg": stable,
            "pending_bearing_deg": pending,
            "observed_bearing_deg": bearing,
            "pending": pending is not None,
            "confirmed": False,
            "abstention_reason": None,
        }
        if bearing is None:
            diagnostics["abstention_reason"] = estimate.ambiguity_reason
            if pending is not None:
                self._doa_pending_bearing_deg = None
                diagnostics["status"] = "pending_not_confirmed"
                diagnostics["pending"] = False
            else:
                diagnostics["status"] = "estimator_unresolved"
            return estimate, diagnostics
        if stable is None:
            self._doa_stable_bearing_deg = bearing
            self._doa_pending_bearing_deg = None
            diagnostics["status"] = "accepted_initial"
            diagnostics["pending"] = False
            return estimate, diagnostics
        if pending is not None:
            confirmation_delta = _circular_distance_deg(bearing, pending)
            diagnostics["confirmation_delta_deg"] = confirmation_delta
            self._doa_pending_bearing_deg = None
            if confirmation_delta <= tolerance:
                self._doa_stable_bearing_deg = bearing
                diagnostics["status"] = "accepted_confirmed"
                diagnostics["pending"] = False
                diagnostics["confirmed"] = True
                return estimate, diagnostics
            diagnostics["status"] = "pending_not_confirmed"
            diagnostics["pending"] = False
            diagnostics["abstention_reason"] = (
                "The next active bearing did not confirm the pending lobe."
            )
            return _temporal_instability(
                estimate,
                reason=str(diagnostics["abstention_reason"]),
            ), diagnostics

        jump = _circular_distance_deg(bearing, stable)
        diagnostics["jump_delta_deg"] = jump
        if jump >= threshold:
            self._doa_pending_bearing_deg = bearing
            diagnostics["status"] = "confirmation_required"
            diagnostics["pending"] = True
            diagnostics["abstention_reason"] = (
                f"The observed bearing jumped by {jump:.6g} degrees and requires "
                "confirmation from the next active update."
            )
            return _temporal_instability(
                estimate,
                reason=str(diagnostics["abstention_reason"]),
            ), diagnostics

        self._doa_stable_bearing_deg = bearing
        diagnostics["status"] = "accepted_consistent"
        return estimate, diagnostics

    def _clear_doa_temporal_state(self) -> None:
        self._doa_stable_bearing_deg = None
        self._doa_pending_bearing_deg = None

    def _clear_doa_consumer_state(self) -> None:
        self._doa_history = None
        self._doa_history_signature = None
        self._doa_history_end_s = None
        self._clear_doa_temporal_state()

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


def _optional_positive_attribute(component: object, name: str) -> float | None:
    if component is None or not hasattr(component, name):
        return None
    value = float(getattr(component, name))
    if value <= 0.0:
        raise ValueError(f"{name} must be positive.")
    return value


def _optional_bearing_attribute(component: object, name: str) -> float | None:
    value = _optional_positive_attribute(component, name)
    if value is not None and value > 180.0:
        raise ValueError(f"{name} must be in (0, 180].")
    return value


def _times_touch(left: float, right: float) -> bool:
    import math

    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _circular_distance_deg(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _temporal_instability(
    estimate: DoaEstimate,
    *,
    reason: str,
) -> DoaEstimate:
    candidates = estimate.candidate_bearing_deg or (
        (estimate.estimated_bearing_deg,)
        if estimate.estimated_bearing_deg is not None
        else ()
    )
    return DoaEstimate(
        estimated_bearing_deg=None,
        candidate_bearing_deg=candidates,
        bearing_confidence=0.0,
        ambiguity_class="temporal_instability",
        ambiguity_reason=reason,
        candidate_elevation_deg=estimate.candidate_elevation_deg,
    )


def _build_standard_perception_pipeline(
    *,
    energy_threshold_dbfs: float,
    doa_enabled: bool = False,
    max_observations: int | None = None,
    runtime_profile: str = DEFAULT_RUNTIME_PROFILE,
) -> AudioPerceptionPipeline:
    """Compose the maintained scalar detector and optional DOA consumer."""

    if not isinstance(doa_enabled, bool):
        raise ConfigValidationError("doa_enabled must be a boolean.")

    from isaac_audio_sensors.core.plugins.protocols import ActivityDetector
    from isaac_audio_sensors.core.plugins.registry import get_default_registry
    from isaac_audio_sensors.core.plugins.standard_doa import MaintainedDoaEstimator

    activity_detector = cast(
        ActivityDetector,
        get_default_registry().resolve(
            "activity_detector",
            "auditok",
            runtime_profile=runtime_profile,
            factory_kwargs={"energy_threshold_dbfs": energy_threshold_dbfs},
        ),
    )
    return AudioPerceptionPipeline(
        activity_detector=activity_detector,
        doa_estimator=(
            MaintainedDoaEstimator(runtime_profile=runtime_profile)
            if doa_enabled
            else None
        ),
        max_observations=max_observations,
    )


__all__ = ["AudioPerceptionPipeline"]
