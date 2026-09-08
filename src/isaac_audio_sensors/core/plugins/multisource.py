"""Optional scalar event localization with explicit stereo ambiguity."""

from __future__ import annotations

import numpy as np

from isaac_audio_sensors.core.constants import DEFAULT_RUNTIME_PROFILE
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.plugins.adapters import _validate_doa_inputs
from isaac_audio_sensors.core.plugins.standard_doa import MaintainedDoaEstimator
from isaac_audio_sensors.core.types import DoaEstimate


class MaintainedEventLocalizer:
    """Localize independent frame events; retain no source identities.

    MUSIC supports the tested 16 kHz planar/rank-3 direct-path conditions.
    Arbitrary reverberant mixtures and exact physical source count are unqualified.
    Stereo and other planar sample rates keep the existing single-event role.
    All dependencies remain lazy.
    """

    consumer_context_duration_s = 0.25
    consumer_jump_threshold_deg = 150.0
    consumer_confirmation_tolerance_deg = 30.0

    def __init__(self, *, runtime_profile: str = DEFAULT_RUNTIME_PROFILE) -> None:
        self._stereo = MaintainedDoaEstimator(runtime_profile=runtime_profile)
        self._music = None
        self._geometry: bytes | None = None

    def reset(self) -> None:
        # Bound optional steering caches to the current valid-channel geometry.
        self._music = None
        self._geometry = None

    def localize(
        self,
        samples: np.ndarray,
        microphone_positions_m: np.ndarray,
        sample_rate_hz: int,
    ) -> tuple[tuple[DoaEstimate, ...], dict[str, object]]:
        values, positions = _validate_doa_inputs(
            samples, microphone_positions_m, sample_rate_hz
        )
        rank = np.linalg.matrix_rank(positions - positions[0])
        if len(positions) == 2 or (sample_rate_hz != 16000 and rank == 2):
            estimate, diagnostics = self._stereo.estimate(
                values, positions, sample_rate_hz
            )
            return (estimate,), {
                **diagnostics,
                "status": "events",
                "single_event_policy": True,
                "localization_scope": "single_event",
            }
        if rank < 2 or (
            rank == 2
            and not np.allclose(positions[:, 2], positions[0, 2], rtol=0, atol=1e-9)
        ):
            return (), {"status": "unavailable", "reason": "unsupported_geometry"}
        if sample_rate_hz != 16000:
            return (), {"status": "unavailable", "reason": "unsupported_sample_rate"}
        if values.shape[1] < 4000:
            return (), {"status": "unavailable", "reason": "insufficient_context"}
        if positions.tobytes() != self._geometry:
            self.reset()
            self._geometry = positions.tobytes()
        if self._music is None:
            try:
                from isaac_audio_sensors.core.plugins._multisource_music import (
                    _FrequencyOrderMusic,
                )
                from isaac_audio_sensors.core.plugins.pyroomacoustics import (
                    _import_supported_pyroomacoustics,
                )

                _import_supported_pyroomacoustics()
            except ImportError as exc:
                raise OptionalDependencyUnavailable(
                    "Multisource DOA requires isaac-audio-sensors[room]."
                ) from exc
            self._music = _FrequencyOrderMusic(
                0.03,
                relative_loading=0.0001,
                refit_threshold=0.010,
                refit_statistic="product",
                refine_peaks=True,
                order_criterion="aic",
                spectral_weighting=True,
            )
        directions, diagnostics = self._music.localize(
            values[:, -4000:], positions, sample_rate_hz
        )
        events = tuple(
            DoaEstimate(
                estimated_bearing_deg=float(np.degrees(np.arctan2(v[1], v[0]))),
                estimated_elevation_deg=(
                    float(np.degrees(np.arctan2(v[2], np.linalg.norm(v[:2]))))
                    if rank == 3
                    else None
                ),
            )
            for v in directions
        )
        return events, {
            **diagnostics,
            "status": "events" if events else "no_events",
            "doa_estimator": "weighted_covariance_music",
            "role": "3d" if rank == 3 else "planar",
            "event_confidence_available": False,
            "temporal_policy": "causal_window_event_set",
            "qualification_scope": "simulated_direct_path_reference",
        }
