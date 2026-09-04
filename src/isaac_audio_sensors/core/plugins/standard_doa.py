"""Maintained role selection for high-level DOA consumers."""

from __future__ import annotations

from typing import cast

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.plugins.adapters import _ordered_inputs
from isaac_audio_sensors.core.plugins.protocols import DoaEstimator
from isaac_audio_sensors.core.types import DoaEstimate


class MaintainedDoaEstimator:
    """Select the single maintained estimator for the observed array geometry."""

    consumer_context_duration_s = 0.25
    consumer_jump_threshold_deg = 150.0
    consumer_confirmation_tolerance_deg = 30.0

    def __init__(self, *, runtime_profile: str = DEFAULT_RUNTIME_PROFILE) -> None:
        self.runtime_profile = runtime_profile
        self._estimators: dict[str, DoaEstimator] = {}

    def estimate(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[DoaEstimate, dict[str, object]]:
        """Route one causal observation to its maintained estimator role."""

        _waveforms, _sensor, _aperture = _ordered_inputs(
            samples,
            microphone_positions_m,
            sample_rate_hz,
        )
        positions = np.asarray(microphone_positions_m, dtype=float)
        role, estimator_id, reason = _select_role(positions)
        if estimator_id is None:
            return _unresolved_selection(role=role, reason=reason)

        required_samples = round(self.consumer_context_duration_s * sample_rate_hz)
        if np.asarray(samples).shape[1] < required_samples:
            return _unresolved_selection(
                role=role,
                estimator_id=estimator_id,
                ambiguity_class="insufficient_context",
                reason=(
                    "Maintained DOA requires a complete causal 250 ms observation."
                ),
                extra={
                    "required_observation_samples": required_samples,
                    "available_observation_samples": int(
                        np.asarray(samples).shape[1]
                    ),
                },
            )

        estimator = self._resolve(estimator_id)
        estimate, diagnostics = estimator.estimate(
            samples,
            positions,
            sample_rate_hz,
        )
        return estimate, {
            **diagnostics,
            "selection": {
                "policy": "maintained_roles_v1",
                "role": role,
                "selected_estimator_id": estimator_id,
            },
        }

    def reset(self) -> None:
        """Reset any resolved estimator with state."""

        for estimator in self._estimators.values():
            reset = getattr(estimator, "reset", None)
            if callable(reset):
                reset()

    def _resolve(self, estimator_id: str) -> DoaEstimator:
        cached = self._estimators.get(estimator_id)
        if cached is not None:
            return cached

        from isaac_audio_sensors.core.plugins.registry import get_default_registry

        registry = get_default_registry()
        availability = registry.probe_availability("doa_estimator", estimator_id)
        if not availability.available:
            missing = ", ".join(availability.missing_dependencies)
            raise OptionalDependencyUnavailable(
                "Planar DOA requires isaac-audio-sensors[room]; missing "
                f"dependencies: {missing}."
            )
        estimator = cast(
            DoaEstimator,
            registry.resolve(
                "doa_estimator",
                estimator_id,
                runtime_profile=self.runtime_profile,
            ),
        )
        self._estimators[estimator_id] = estimator
        return estimator


def _select_role(positions: np.ndarray) -> tuple[str, str | None, str]:
    microphone_count = int(positions.shape[0])
    if microphone_count == 2:
        return "two_microphone_ambiguity", "tdoa_least_squares", ""

    centered = positions - positions[0]
    xyz_rank = int(np.linalg.matrix_rank(centered[1:]))
    xy_rank = int(np.linalg.matrix_rank(centered[1:, :2]))
    horizontal = bool(
        np.allclose(positions[:, 2], positions[0, 2], rtol=0.0, atol=1e-9)
    )
    if xyz_rank >= 3:
        return (
            "optional_3d_unselected",
            None,
            "Rank-3 DOA is available only through explicit estimator injection and "
            "is not a qualified maintained product role.",
        )
    if not horizontal or xy_rank < 2:
        return (
            "unsupported_geometry",
            None,
            "Maintained planar DOA requires at least three non-collinear "
            "microphones in array-local XY.",
        )
    return "primary_planar_doa", "pyroomacoustics_srp", ""


def _unresolved_selection(
    *,
    role: str,
    reason: str,
    estimator_id: str | None = None,
    ambiguity_class: str = "unsupported_geometry",
    extra: dict[str, object] | None = None,
) -> tuple[DoaEstimate, dict[str, object]]:
    return (
        DoaEstimate(
            estimated_bearing_deg=None,
            bearing_confidence=0.0,
            ambiguity_class=ambiguity_class,
            ambiguity_reason=reason,
        ),
        {
            "doa_estimator": estimator_id,
            "selection": {
                "policy": "maintained_roles_v1",
                "role": role,
                "selected_estimator_id": estimator_id,
                "reason": reason,
            },
            "reliability_score": 0.0,
            "resolved": False,
            **(extra or {}),
        },
    )


__all__ = ["MaintainedDoaEstimator"]
