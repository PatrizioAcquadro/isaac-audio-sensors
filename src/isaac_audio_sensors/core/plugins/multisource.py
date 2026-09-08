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

    WPE/group-sparse covariance supports the bounded 16 kHz indoor reference
    for relatively stable sources. Memory is 750 ms; measured response can
    exceed one second. Physical recordings and arbitrary rooms are unqualified.
    Stereo and other planar sample rates keep the existing single-event role.
    All dependencies remain lazy.
    """

    consumer_context_duration_s = 0.75
    consumer_jump_threshold_deg = 150.0
    consumer_confirmation_tolerance_deg = 30.0

    def __init__(self, *, runtime_profile: str = DEFAULT_RUNTIME_PROFILE) -> None:
        self._stereo = MaintainedDoaEstimator(runtime_profile=runtime_profile)
        self._spatial = None
        self._geometry: bytes | None = None

    def reset(self) -> None:
        # Bound optional steering caches to the current valid-channel geometry.
        self._spatial = None
        self._geometry = None

    def consumer_context_duration_s_for(
        self, sample_rate_hz: int, channel_count: int
    ) -> float:
        """Keep the existing single-event context for stereo/other rates."""
        return 0.25 if channel_count == 2 or sample_rate_hz != 16000 else 0.75

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
                values[:, -round(0.25 * sample_rate_hz) :], positions, sample_rate_hz
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
        if values.shape[1] < 12000:
            return (), {"status": "unavailable", "reason": "insufficient_context"}
        if positions.tobytes() != self._geometry:
            self.reset()
            self._geometry = positions.tobytes()
        if self._spatial is None:
            try:
                from nara_wpe.wpe import wpe_v7  # noqa: F401

                from isaac_audio_sensors.core.plugins._multisource_sparse import (
                    WpeSparseCovariance,
                )
                from isaac_audio_sensors.core.plugins.pyroomacoustics import (
                    _import_supported_pyroomacoustics,
                )

                _import_supported_pyroomacoustics()
            except ImportError as exc:
                raise OptionalDependencyUnavailable(
                    "Multisource DOA requires isaac-audio-sensors[room]."
                ) from exc
            self._spatial = WpeSparseCovariance()
        directions, diagnostics = self._spatial.localize(
            values[:, -12000:], positions, sample_rate_hz
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
            "doa_estimator": "wpe_group_sparse_covariance",
            "role": "3d" if rank == 3 else "planar",
            "event_confidence_available": False,
            "temporal_policy": "causal_window_event_set",
            "qualification_scope": "simulated_indoor_stable_sources",
        }
