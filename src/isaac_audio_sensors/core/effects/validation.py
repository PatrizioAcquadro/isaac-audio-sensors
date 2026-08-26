"""Public facade for audio-effects configuration validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from isaac_audio_sensors.core.effects.config import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.core.effects.config.channel_response import (
    validate_channel_response,
)
from isaac_audio_sensors.core.effects.config.directivity import validate_directivity
from isaac_audio_sensors.core.effects.config.electronics import validate_electronics
from isaac_audio_sensors.core.effects.config.motion import validate_motion
from isaac_audio_sensors.core.effects.config.noise import validate_noise
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    UnsupportedEffectError,
)


def validate_effects_config(
    config: EffectsConfig,
    *,
    microphone_orders: Sequence[Sequence[str]],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None = None,
    microphone_self_noise_db: Mapping[str, float | None] | None = None,
    source_ids: Sequence[str] | None = None,
    source_orientations: Mapping[str, tuple[float, float, float, float] | None]
    | None = None,
    microphone_orientations: Mapping[str, tuple[float, float, float, float] | None]
    | None = None,
) -> None:
    """Validate effects against arrays and a concrete backend/profile envelope."""

    if not isinstance(config, EffectsConfig):
        raise ConfigValidationError(
            "audio.effects must normalize to EffectsConfig; received "
            f"{type(config).__name__} for backend {backend_id!r}, profile "
            f"{runtime_profile!r}."
        )
    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        raise ConfigValidationError(
            "audio.effects sample_rate_hz must be a positive integer; received "
            f"{sample_rate_hz!r} for backend {backend_id!r}, profile "
            f"{runtime_profile!r}."
        )
    orders = tuple(tuple(order) for order in microphone_orders)
    if not orders or any(not order for order in orders):
        raise ConfigValidationError(
            "audio.effects requires a selected non-empty microphone array; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    for order in orders:
        if len(set(order)) != len(order):
            raise ConfigValidationError(
                "audio.effects selected array contains duplicate microphone ids "
                f"after normalization: {order!r}; backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )

    validate_channel_response(
        config.channel_response,
        orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
    )
    validate_noise(
        config.noise,
        orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
        microphone_self_noise_db=microphone_self_noise_db,
    )
    validate_electronics(
        config.electronics,
        noise=config.noise,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
    )
    validate_directivity(
        config.directivity,
        microphone_orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        source_ids=source_ids,
        source_orientations=source_orientations,
        microphone_orientations=microphone_orientations,
    )
    validate_motion_effects_config(config.motion)

    segments = config.motion.segments_per_window
    if segments > 1:
        if not config.motion.derive_velocity_from_poses:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires "
                "derive_velocity_from_poses=true."
            )
        if backend_id not in {"room_acoustics", "room_acoustics_srp"}:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 is unsupported by "
                f"backend {backend_id!r}; use room_acoustics or "
                "room_acoustics_srp."
            )
        if runtime_profile != "waveform_fidelity":
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires runtime "
                "profile 'waveform_fidelity'."
            )
        if sample_count is not None and segments > sample_count:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window must be no greater "
                f"than window_sample_count={sample_count}; received {segments}."
            )


def validate_motion_effects_config(config: MotionEffectsConfig) -> None:
    """Validate normalized motion settings without backend side effects."""

    validate_motion(config)


__all__ = [
    "UnsupportedEffectError",
    "validate_effects_config",
    "validate_motion_effects_config",
]
