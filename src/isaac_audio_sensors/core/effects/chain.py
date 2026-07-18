"""Ordered post-synthesis per-channel effects chain."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from isaac_audio_sensors.core.effects.channel_response import (
    apply_channel_response,
)
from isaac_audio_sensors.core.effects.config import (
    EffectsConfig,
    validate_effects_config,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


class ChannelEffectsChain:
    """Dispatch enabled effects while preserving the exact all-disabled input."""

    def __init__(self, config: EffectsConfig | None = None) -> None:
        self.config = EffectsConfig() if config is None else config

    def apply(
        self,
        samples: np.ndarray,
        *,
        mic_ids: Sequence[str],
        sample_rate_hz: int,
        frame_id: str,
        backend_id: str = "waveform",
        runtime_profile: str = "waveform_fidelity",
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Return effected samples and stage diagnostics."""

        del frame_id  # Reserved for named stochastic streams in later stages.
        if self.config.all_disabled:
            return samples, {}
        self.validate(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        output = samples
        diagnostics: dict[str, Any] = {}
        if self.config.channel_response.enabled:
            output, response_diagnostics = apply_channel_response(
                output,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                config=self.config.channel_response,
            )
            if response_diagnostics:
                diagnostics["channel_response"] = response_diagnostics
        return output, diagnostics

    def validate(
        self,
        samples: np.ndarray,
        *,
        mic_ids: Sequence[str],
        sample_rate_hz: int,
        backend_id: str,
        runtime_profile: str,
    ) -> None:
        """Fail before any active stage can mutate caller-owned samples."""

        if not isinstance(samples, np.ndarray):
            raise ConfigValidationError(
                "audio.effects chain samples must be a numpy.ndarray; received "
                f"{type(samples).__name__}."
            )
        if samples.ndim != 2:
            raise ConfigValidationError(
                "audio.effects chain samples must have microphone-major shape "
                f"(microphone_count, sample_count); received {samples.shape!r}."
            )
        if samples.shape[0] == 0:
            raise ConfigValidationError(
                "audio.effects chain samples must contain at least one channel; "
                f"received shape {samples.shape!r}."
            )
        if samples.shape[0] != len(mic_ids):
            raise ConfigValidationError(
                "audio.effects chain microphone-count/order mismatch: sample shape "
                f"{samples.shape!r}, mic_ids={tuple(mic_ids)!r}."
            )
        if not np.issubdtype(samples.dtype, np.floating):
            raise ConfigValidationError(
                "audio.effects chain samples must use a floating dtype; received "
                f"{samples.dtype}."
            )
        if not np.all(np.isfinite(samples)):
            raise ConfigValidationError(
                "audio.effects chain samples contain non-finite values; active "
                "effects require finite input."
            )
        validate_effects_config(
            self.config,
            microphone_orders=(tuple(mic_ids),),
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            sample_count=samples.shape[1],
        )


__all__ = ["ChannelEffectsChain"]
