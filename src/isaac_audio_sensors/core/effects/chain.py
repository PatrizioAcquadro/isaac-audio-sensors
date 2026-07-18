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
from isaac_audio_sensors.core.effects.electronics import apply_electronics
from isaac_audio_sensors.core.effects.noise import apply_noise
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
        nominal_window_start_sample: int = 0,
        microphone_self_noise_db: dict[str, float | None] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Return effected samples and stage diagnostics."""

        if self.config.all_disabled:
            if self.config != EffectsConfig():
                sample_count = (
                    samples.shape[1]
                    if isinstance(samples, np.ndarray) and samples.ndim == 2
                    else None
                )
                validate_effects_config(
                    self.config,
                    microphone_orders=(tuple(mic_ids),),
                    sample_rate_hz=sample_rate_hz,
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                    sample_count=sample_count,
                    microphone_self_noise_db=microphone_self_noise_db,
                )
            return samples, {}
        self.validate(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            microphone_self_noise_db=microphone_self_noise_db,
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
        if self.config.noise.enabled:
            output, noise_diagnostics = apply_noise(
                output,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                nominal_window_start_sample=nominal_window_start_sample,
                config=self.config.noise,
                microphone_self_noise_db=microphone_self_noise_db,
            )
            if noise_diagnostics:
                diagnostics["noise"] = noise_diagnostics
        if self.config.electronics.enabled:
            output, electronics_diagnostics = apply_electronics(
                output,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                config=self.config.electronics,
                seed=self.config.noise.seed,
            )
            diagnostics["electronics"] = electronics_diagnostics
        return output, diagnostics

    def apply_premix(
        self,
        samples: np.ndarray,
        *,
        mic_ids: Sequence[str],
        sample_rate_hz: int,
        frame_id: str,
        backend_id: str,
        runtime_profile: str,
        microphone_self_noise_db: dict[str, float | None] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Apply only deterministic linear stages to one source premix."""

        del frame_id
        if not self.config.channel_response.enabled:
            return samples, {}
        self.validate(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            microphone_self_noise_db=microphone_self_noise_db,
        )
        output, diagnostics = apply_channel_response(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=sample_rate_hz,
            config=self.config.channel_response,
        )
        return output, ({"channel_response": diagnostics} if diagnostics else {})

    def apply_mixture(
        self,
        samples: np.ndarray,
        *,
        mic_ids: Sequence[str],
        sample_rate_hz: int,
        frame_id: str,
        backend_id: str,
        runtime_profile: str,
        nominal_window_start_sample: int,
        microphone_self_noise_db: dict[str, float | None] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Apply stochastic/nonlinear stages once to the summed mixture."""

        if not (self.config.noise.enabled or self.config.electronics.enabled):
            return samples, {}
        self.validate(
            samples,
            mic_ids=mic_ids,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            microphone_self_noise_db=microphone_self_noise_db,
        )
        output = samples
        stage_diagnostics: dict[str, Any] = {}
        if self.config.noise.enabled:
            output, noise_diagnostics = apply_noise(
                output,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                nominal_window_start_sample=nominal_window_start_sample,
                config=self.config.noise,
                microphone_self_noise_db=microphone_self_noise_db,
            )
            if noise_diagnostics:
                stage_diagnostics["noise"] = noise_diagnostics
        if self.config.electronics.enabled:
            output, electronics_diagnostics = apply_electronics(
                output,
                mic_ids=mic_ids,
                sample_rate_hz=sample_rate_hz,
                frame_id=frame_id,
                config=self.config.electronics,
                seed=self.config.noise.seed,
            )
            stage_diagnostics["electronics"] = electronics_diagnostics
        return output, stage_diagnostics

    def validate(
        self,
        samples: np.ndarray,
        *,
        mic_ids: Sequence[str],
        sample_rate_hz: int,
        backend_id: str,
        runtime_profile: str,
        microphone_self_noise_db: dict[str, float | None] | None = None,
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
            microphone_self_noise_db=microphone_self_noise_db,
        )


__all__ = ["ChannelEffectsChain"]
