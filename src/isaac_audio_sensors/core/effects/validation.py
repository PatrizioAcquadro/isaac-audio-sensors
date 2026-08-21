"""Semantic validation for active audio-effects stages."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real

from isaac_audio_sensors.core.effects.config import (
    AgcConfig,
    AmbientNoiseConfig,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    ElectronicsConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


class UnsupportedEffectError(ConfigValidationError):
    """Configured effect is outside the selected backend envelope."""


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

    response = config.channel_response
    if not isinstance(response, ChannelResponseConfig):
        raise ConfigValidationError(
            "audio.effects.channel_response must normalize to "
            f"ChannelResponseConfig; received {type(response).__name__}."
        )
    if type(response.enabled) is not bool:
        raise ConfigValidationError(
            "audio.effects.channel_response.enabled must be a bool; received "
            f"{response.enabled!r}."
        )
    microphones = response.microphones
    if microphones is not None:
        if not isinstance(microphones, Mapping):
            raise ConfigValidationError(
                "audio.effects.channel_response.microphones must be a mapping; "
                f"received {type(microphones).__name__}."
            )
        for mic_id, mic_config in microphones.items():
            if not isinstance(mic_id, str) or not isinstance(
                mic_config, ChannelResponseMicConfig
            ):
                raise ConfigValidationError(
                    "audio.effects.channel_response.microphones must map exact "
                    "string ids to ChannelResponseMicConfig values."
                )
        if response.enabled:
            configured_ids = tuple(microphones)
            _validate_microphone_order(
                configured_ids, orders, backend_id, runtime_profile
            )
            for mic_id, mic_config in microphones.items():
                _validate_mic_config(
                    mic_id,
                    mic_config,
                    sample_rate_hz=sample_rate_hz,
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                    sample_count=sample_count,
                )

    _validate_noise_config(
        config.noise,
        orders=orders,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
        microphone_self_noise_db=microphone_self_noise_db,
    )
    _validate_electronics_config(
        config.electronics,
        noise=config.noise,
        sample_rate_hz=sample_rate_hz,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
        sample_count=sample_count,
    )
    from isaac_audio_sensors.core.effects.directivity import (
        validate_directivity_config,
    )

    validate_directivity_config(
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

    if response.enabled:
        for mic_id, mic_config in (microphones or {}).items():
            if mic_config.frequency_response is not None and (
                backend_id in {"geometry_only", "tdoa_synthetic"}
                or runtime_profile != "waveform_fidelity"
            ):
                raise UnsupportedEffectError(
                    "audio.effects.channel_response.microphones."
                    f"{mic_id}.frequency_response is waveform-only and unsupported "
                    f"by backend {backend_id!r} at profile {runtime_profile!r}; "
                    "supported envelope is metadata gain/delay/polarity on L0/L1 "
                    "or magnitude response on an L2/L3 waveform backend."
                )


def _validate_mic_config(
    mic_id: str,
    config: ChannelResponseMicConfig,
    *,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
) -> None:
    table = f"audio.effects.channel_response.microphones.{mic_id}"
    if not isinstance(config, ChannelResponseMicConfig):
        raise ConfigValidationError(
            f"{table} must be ChannelResponseMicConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    for field_name, value in (("gain_db", config.gain_db), ("delay_s", config.delay_s)):
        if value is not None and not math.isfinite(float(value)):
            raise ConfigValidationError(
                f"{table}.{field_name} must be finite; received {value!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
    if config.polarity is not None and (
        type(config.polarity) is not int or config.polarity not in {-1, 1}
    ):
        raise ConfigValidationError(
            f"{table}.polarity must be exactly -1 or 1; received "
            f"{config.polarity!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.delay_s is not None and sample_count is not None:
        shifted_samples = math.ceil(abs(float(config.delay_s) * sample_rate_hz))
        if sample_count <= 0 or shifted_samples >= sample_count:
            raise ConfigValidationError(
                f"{table}.delay_s={config.delay_s!r} leaves no non-empty valid "
                f"region in a {sample_count}-sample window at {sample_rate_hz} Hz; "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
    points = config.frequency_response
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.frequency_response requires at least two points; received "
            f"{len(points)}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.frequency_response[{index}]"
        if point.frequency_hz is None or not math.isfinite(float(point.frequency_hz)):
            raise ConfigValidationError(
                f"{prefix}.frequency_hz must be finite and positive; received "
                f"{point.frequency_hz!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        frequency = float(point.frequency_hz)
        if frequency <= 0.0 or frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.frequency_hz={frequency!r} must be positive and strictly "
                f"increasing; backend={backend_id!r}, profile={runtime_profile!r}."
            )
        if point.magnitude_db is None or not math.isfinite(float(point.magnitude_db)):
            raise ConfigValidationError(
                f"{prefix}.magnitude_db must be finite; received "
                f"{point.magnitude_db!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        if point.phase_deg is not None:
            raise UnsupportedEffectError(
                f"{prefix}.phase_deg={point.phase_deg!r} is unsupported by the "
                "magnitude-only linear-phase FIR; use delay_s for a supported "
                f"linear phase offset, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
        previous = frequency
    nyquist = sample_rate_hz / 2.0
    if previous > nyquist:
        raise ConfigValidationError(
            f"{table}.frequency_response highest frequency {previous!r} exceeds "
            f"Nyquist {nyquist!r} at {sample_rate_hz} Hz; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


def _validate_microphone_order(
    configured_ids: tuple[str, ...],
    orders: tuple[tuple[str, ...], ...],
    backend_id: str,
    runtime_profile: str,
) -> None:
    known = {mic_id for order in orders for mic_id in order}
    unknown = tuple(mic_id for mic_id in configured_ids if mic_id not in known)
    if unknown:
        raise ConfigValidationError(
            "audio.effects.channel_response.microphones contains unknown exact "
            f"MicrophoneSpec.mic_id values {unknown!r}; configured order "
            f"{configured_ids!r}, available arrays {orders!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if configured_ids and not any(
        configured_ids == tuple(mic_id for mic_id in order if mic_id in configured_ids)
        and set(configured_ids).issubset(order)
        for order in orders
    ):
        raise ConfigValidationError(
            "audio.effects.channel_response.microphones order mismatch: configured "
            f"{configured_ids!r}, available array orders {orders!r}; backend="
            f"{backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_noise_config(
    config: NoiseConfig,
    *,
    orders: tuple[tuple[str, ...], ...],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
    microphone_self_noise_db: Mapping[str, float | None] | None,
) -> None:
    table = "audio.effects.noise"
    if not isinstance(config, NoiseConfig):
        raise ConfigValidationError(
            f"{table} must normalize to NoiseConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if not config.enabled:
        return
    if config.seed is not None and (
        type(config.seed) is not int or not -(2**63) <= config.seed < 2**63
    ):
        raise ConfigValidationError(
            f"{table}.seed must be an exact integer in "
            f"[-2**63, 2**63 - 1]; received {config.seed!r}, "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and all(
        value is None
        for value in (
            config.self_noise,
            config.ambient,
            config.clock_jitter_std_s,
            config.clock_drift_ppm,
        )
    ):
        raise UnsupportedEffectError(
            f"{table}.enabled=true has no configured noise contribution for "
            f"backend {backend_id!r}, profile {runtime_profile!r}."
        )

    selected_ids = tuple(dict.fromkeys(mic_id for order in orders for mic_id in order))
    self_noise = config.self_noise
    nonzero_stochastic = False
    if self_noise is not None:
        if not isinstance(self_noise, SelfNoiseConfig):
            raise ConfigValidationError(
                f"{table}.self_noise must be SelfNoiseConfig; received "
                f"{type(self_noise).__name__}."
            )
        if self_noise.default is not None:
            _validate_noise_level_spec(
                self_noise.default,
                table=f"{table}.self_noise.default",
                sample_rate_hz=sample_rate_hz,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )
        microphones = self_noise.microphones
        if microphones is not None:
            if not isinstance(microphones, Mapping):
                raise ConfigValidationError(
                    f"{table}.self_noise.microphones must be a mapping; received "
                    f"{type(microphones).__name__}."
                )
            _validate_effect_mapping_order(
                tuple(microphones),
                orders,
                table=f"{table}.self_noise.microphones",
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )
            for mic_id, level in microphones.items():
                _validate_noise_level_spec(
                    level,
                    table=f"{table}.self_noise.microphones.{mic_id}",
                    sample_rate_hz=sample_rate_hz,
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                )
        for mic_id in selected_ids:
            resolved = (microphones or {}).get(mic_id, self_noise.default)
            if resolved is not None and resolved.level_db != -math.inf:
                nonzero_stochastic = True
            elif (
                resolved is None
                and microphone_self_noise_db is not None
                and microphone_self_noise_db.get(mic_id) is not None
            ):
                metadata_level = microphone_self_noise_db[mic_id]
                _validate_absolute_level(
                    metadata_level,
                    field=(
                        f"{table}.self_noise MicrophoneSpec.self_noise_db "
                        f"fallback for {mic_id}"
                    ),
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                )
                if metadata_level != -math.inf:
                    nonzero_stochastic = True

    ambient = config.ambient
    if ambient is not None:
        if not isinstance(ambient, AmbientNoiseConfig):
            raise ConfigValidationError(
                f"{table}.ambient must be AmbientNoiseConfig; received "
                f"{type(ambient).__name__}."
            )
        _validate_noise_level_spec(
            NoiseLevelSpecConfig(
                level_db=ambient.level_db,
                spectrum=ambient.spectrum,
            ),
            table=f"{table}.ambient",
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        coherent = (
            0.0 if ambient.coherent_fraction is None else ambient.coherent_fraction
        )
        _validate_finite_range(
            coherent,
            field=f"{table}.ambient.coherent_fraction",
            lower=0.0,
            upper=1.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        if ambient.level_db != -math.inf:
            nonzero_stochastic = True

    jitter = config.clock_jitter_std_s
    if isinstance(jitter, Mapping):
        _validate_effect_mapping_order(
            tuple(jitter),
            orders,
            table=f"{table}.clock_jitter_std_s",
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        jitter_values = tuple(jitter.items())
    elif jitter is None:
        jitter_values = ()
    elif isinstance(jitter, bool) or not isinstance(jitter, Real):
        raise ConfigValidationError(
            f"{table}.clock_jitter_std_s must be a scalar number or exact "
            f"per-microphone mapping; received {jitter!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    else:
        jitter_values = tuple((mic_id, jitter) for mic_id in selected_ids)
    for mic_id, value in jitter_values:
        _validate_finite_range(
            value,
            field=f"{table}.clock_jitter_std_s.{mic_id}",
            lower=0.0,
            upper=0.25,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        sigma = float(value)
        if sigma > 0.0:
            nonzero_stochastic = True
            if (
                sample_count is not None
                and sample_count > 0
                and math.ceil(6.0 * sigma * sample_rate_hz) >= sample_count
            ):
                raise ConfigValidationError(
                    f"{table}.clock_jitter_std_s.{mic_id}={value!r} violates "
                    "ceil(6 * jitter_std_s * sample_rate_hz) < sample_count for "
                    f"sample_count={sample_count}, backend={backend_id!r}, "
                    f"profile={runtime_profile!r}."
                )

    drift = config.clock_drift_ppm
    if drift is not None:
        if not isinstance(drift, Mapping):
            raise ConfigValidationError(
                f"{table}.clock_drift_ppm must be a per-microphone mapping; "
                f"received {type(drift).__name__}."
            )
        _validate_effect_mapping_order(
            tuple(drift),
            orders,
            table=f"{table}.clock_drift_ppm",
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        for mic_id, value in drift.items():
            _validate_finite_range(
                value,
                field=f"{table}.clock_drift_ppm.{mic_id}",
                lower=-1000.0,
                upper=1000.0,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )

    if (
        config.enabled
        and backend_id in {"geometry_only", "tdoa_synthetic"}
        and (self_noise is not None or ambient is not None)
    ):
        feature = "self_noise" if self_noise is not None else "ambient"
        raise UnsupportedEffectError(
            f"{table}.{feature} is waveform-only and unsupported by backend "
            f"{backend_id!r} at profile {runtime_profile!r}; supported envelope "
            "on L0/L1 is additive clock jitter/drift delay metadata."
        )
    if nonzero_stochastic and config.seed is None:
        raise ConfigValidationError(
            f"{table}.seed is required for every nonzero stochastic noise setting; "
            f"received None, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_noise_level_spec(
    config: object,
    *,
    table: str,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if not isinstance(config, NoiseLevelSpecConfig):
        raise ConfigValidationError(
            f"{table} must be NoiseLevelSpecConfig; received {type(config).__name__}."
        )
    _validate_absolute_level(
        config.level_db,
        field=f"{table}.level_db",
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )
    points = config.spectrum
    if points is None:
        return
    if len(points) < 2:
        raise ConfigValidationError(
            f"{table}.spectrum requires at least two points; received {len(points)}, "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    previous = 0.0
    for index, point in enumerate(points):
        prefix = f"{table}.spectrum[{index}]"
        if not isinstance(point, NoiseSpectrumPointConfig):
            raise ConfigValidationError(
                f"{prefix} must be NoiseSpectrumPointConfig; received "
                f"{type(point).__name__}."
            )
        _validate_finite_range(
            point.freq_hz,
            field=f"{prefix}.freq_hz",
            lower=0.0,
            upper=sample_rate_hz / 2.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            lower_inclusive=False,
        )
        frequency = float(point.freq_hz)
        if frequency <= previous:
            raise ConfigValidationError(
                f"{prefix}.freq_hz={frequency!r} must be strictly increasing; "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )
        _validate_finite_range(
            point.level_db,
            field=f"{prefix}.level_db",
            lower=-120.0,
            upper=120.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        previous = frequency


def _validate_electronics_config(
    config: ElectronicsConfig,
    *,
    noise: NoiseConfig,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
) -> None:
    table = "audio.effects.electronics"
    if not isinstance(config, ElectronicsConfig):
        raise ConfigValidationError(
            f"{table} must normalize to ElectronicsConfig; received "
            f"{type(config).__name__}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    if not config.enabled:
        return
    if config.full_scale is not None:
        _validate_finite_range(
            config.full_scale,
            field=f"{table}.full_scale",
            lower=0.0,
            upper=float("inf"),
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            lower_inclusive=False,
        )
    if config.bit_depth is not None and (
        type(config.bit_depth) is not int or not 8 <= config.bit_depth <= 32
    ):
        raise ConfigValidationError(
            f"{table}.bit_depth must be an exact integer in [8, 32]; received "
            f"{config.bit_depth!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.dither_enabled is not None and type(config.dither_enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.dither_enabled must be a bool or None; received "
            f"{config.dither_enabled!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.enabled and (config.full_scale is None or config.bit_depth is None):
        missing = [
            name
            for name, value in (
                ("full_scale", config.full_scale),
                ("bit_depth", config.bit_depth),
            )
            if value is None
        ]
        error_type = (
            UnsupportedEffectError
            if config.full_scale is None
            and config.bit_depth is None
            and config.dither_enabled is None
            and config.agc is None
            else ConfigValidationError
        )
        raise error_type(
            f"{table}.enabled=true requires {missing!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.full_scale is not None and config.bit_depth is not None:
        step = 2.0 * float(config.full_scale) / 2**config.bit_depth
        if not math.isfinite(step) or step <= 0.0:
            raise ConfigValidationError(
                f"{table} derived quantization step must be finite and positive; "
                f"received {step!r} from full_scale={config.full_scale!r}, "
                f"bit_depth={config.bit_depth!r}, backend={backend_id!r}, "
                f"profile={runtime_profile!r}."
            )
    agc = config.agc
    if agc is not None:
        _validate_agc_config(
            agc,
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
    if (
        config.enabled
        and config.dither_enabled
        and (type(noise.seed) is not int or not -(2**63) <= noise.seed < 2**63)
    ):
        raise ConfigValidationError(
            f"{table}.dither_enabled=true requires audio.effects.noise.seed to "
            "be an exact integer in [-2**63, 2**63 - 1]; received "
            f"{noise.seed!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if config.enabled and backend_id in {"geometry_only", "tdoa_synthetic"}:
        raise UnsupportedEffectError(
            f"{table}.enabled=true is waveform-only and unsupported by backend "
            f"{backend_id!r} at profile {runtime_profile!r}; electronics has no "
            "L0/L1 metadata representation."
        )
    if config.enabled and runtime_profile != "waveform_fidelity":
        raise UnsupportedEffectError(
            f"{table}.enabled=true requires runtime profile 'waveform_fidelity'; "
            f"received {runtime_profile!r} on backend {backend_id!r}."
        )
    if (
        config.enabled
        and config.agc is not None
        and config.agc.enabled
        and sample_count == 0
    ):
        raise ConfigValidationError(
            f"{table}.agc.enabled=true requires a non-empty time axis; received "
            f"sample_count=0, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_agc_config(
    config: AgcConfig,
    *,
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
) -> None:
    table = "audio.effects.electronics.agc"
    if not isinstance(config, AgcConfig):
        raise ConfigValidationError(
            f"{table} must normalize to AgcConfig; received {type(config).__name__}."
        )
    if type(config.enabled) is not bool:
        raise ConfigValidationError(
            f"{table}.enabled must be a bool; received {config.enabled!r}."
        )
    ranges = (
        ("target_rms_dbfs", config.target_rms_dbfs, -120.0, 0.0, True),
        ("attack_time_s", config.attack_time_s, 0.0, 60.0, False),
        ("release_time_s", config.release_time_s, 0.0, 60.0, False),
        ("gain_floor_db", config.gain_floor_db, -120.0, 120.0, True),
        ("gain_ceiling_db", config.gain_ceiling_db, -120.0, 120.0, True),
    )
    for name, value, lower, upper, inclusive in ranges:
        if value is not None:
            _validate_finite_range(
                value,
                field=f"{table}.{name}",
                lower=lower,
                upper=upper,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
                lower_inclusive=inclusive,
            )
    values = {
        "target_rms_dbfs": config.target_rms_dbfs,
        "attack_time_s": config.attack_time_s,
        "release_time_s": config.release_time_s,
        "gain_floor_db": config.gain_floor_db,
        "gain_ceiling_db": config.gain_ceiling_db,
    }
    if config.enabled and any(value is None for value in values.values()):
        missing = [name for name, value in values.items() if value is None]
        raise ConfigValidationError(
            f"{table}.enabled=true requires {missing!r}; "
            f"backend={backend_id!r}, profile={runtime_profile!r}."
        )
    if (
        config.gain_floor_db is not None
        and config.gain_ceiling_db is not None
        and not config.gain_floor_db <= 0.0 <= config.gain_ceiling_db
    ):
        raise ConfigValidationError(
            f"{table} gain bounds must satisfy gain_floor_db <= 0.0 <= "
            f"gain_ceiling_db; received {config.gain_floor_db!r}, "
            f"{config.gain_ceiling_db!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if config.enabled:
        assert config.target_rms_dbfs is not None
        assert config.attack_time_s is not None
        assert config.release_time_s is not None
        assert config.gain_floor_db is not None
        assert config.gain_ceiling_db is not None
        derived = (
            10.0 ** (config.target_rms_dbfs / 20.0),
            10.0 ** (config.gain_floor_db / 20.0),
            10.0 ** (config.gain_ceiling_db / 20.0),
            math.exp(-1.0 / (config.attack_time_s * sample_rate_hz)),
            math.exp(-1.0 / (config.release_time_s * sample_rate_hz)),
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in derived) or any(
            value >= 1.0 for value in derived[-2:]
        ):
            raise ConfigValidationError(
                f"{table} derived target, gains, and coefficients must be finite "
                f"and positive, with coefficients below one; received {derived!r}, "
                f"backend={backend_id!r}, profile={runtime_profile!r}."
            )


def _validate_absolute_level(
    value: object,
    *,
    field: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if value == -math.inf and isinstance(value, Real) and not isinstance(value, bool):
        return
    _validate_finite_range(
        value,
        field=field,
        lower=-300.0,
        upper=60.0,
        backend_id=backend_id,
        runtime_profile=runtime_profile,
    )


def _validate_finite_range(
    value: object,
    *,
    field: str,
    lower: float,
    upper: float,
    backend_id: str,
    runtime_profile: str,
    lower_inclusive: bool = True,
) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field} must be a finite number in "
            f"{'[' if lower_inclusive else '('}{lower}, {upper}]; received "
            f"{value!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )
    number = float(value)
    lower_ok = number >= lower if lower_inclusive else number > lower
    if not math.isfinite(number) or not lower_ok or number > upper:
        raise ConfigValidationError(
            f"{field} must be a finite number in "
            f"{'[' if lower_inclusive else '('}{lower}, {upper}]; received "
            f"{value!r}, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _validate_effect_mapping_order(
    configured_ids: tuple[str, ...],
    orders: tuple[tuple[str, ...], ...],
    *,
    table: str,
    backend_id: str,
    runtime_profile: str,
) -> None:
    if any(not isinstance(mic_id, str) or not mic_id for mic_id in configured_ids):
        raise ConfigValidationError(
            f"{table} ids must be exact non-empty MicrophoneSpec.mic_id strings; "
            f"received {configured_ids!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    known = {mic_id for order in orders for mic_id in order}
    unknown = tuple(mic_id for mic_id in configured_ids if mic_id not in known)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unknown exact MicrophoneSpec.mic_id values "
            f"{unknown!r}; available arrays {orders!r}, backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )
    if configured_ids and not any(
        configured_ids == tuple(mic_id for mic_id in order if mic_id in configured_ids)
        and set(configured_ids).issubset(order)
        for order in orders
    ):
        raise ConfigValidationError(
            f"{table} order mismatch: configured {configured_ids!r}, available "
            f"array orders {orders!r}; backend={backend_id!r}, "
            f"profile={runtime_profile!r}."
        )


def validate_motion_effects_config(config: MotionEffectsConfig) -> None:
    """Validate normalized motion settings without backend side effects."""

    table = "audio.effects.motion"
    if not isinstance(config, MotionEffectsConfig):
        raise ConfigValidationError(
            f"{table} must normalize to MotionEffectsConfig; received "
            f"{type(config).__name__}."
        )
    if type(config.derive_velocity_from_poses) is not bool:
        raise ConfigValidationError(
            f"{table}.derive_velocity_from_poses must be a bool; received "
            f"{config.derive_velocity_from_poses!r}."
        )
    if type(config.segments_per_window) is not int:
        raise ConfigValidationError(
            f"{table}.segments_per_window must be an exact integer; "
            f"received {config.segments_per_window!r}."
        )
    _validate_finite_number(
        config.teleport_speed_threshold_mps,
        f"{table}.teleport_speed_threshold_mps",
    )
    _validate_finite_number(config.stale_time_s, f"{table}.stale_time_s")
    if config.smoothing_alpha is not None:
        _validate_finite_number(
            config.smoothing_alpha,
            f"{table}.smoothing_alpha",
        )
    if not config.derive_velocity_from_poses and config.segments_per_window == 1:
        return
    if not 1 <= config.segments_per_window <= 64:
        raise ConfigValidationError(
            f"{table}.segments_per_window must be in [1, 64]; "
            f"received {config.segments_per_window!r}."
        )
    _validate_bounded_number(
        config.teleport_speed_threshold_mps,
        f"{table}.teleport_speed_threshold_mps",
        upper=100.0,
    )
    _validate_bounded_number(
        config.stale_time_s,
        f"{table}.stale_time_s",
        upper=60.0,
    )
    if config.smoothing_alpha is not None:
        _validate_bounded_number(
            config.smoothing_alpha,
            f"{table}.smoothing_alpha",
            upper=1.0,
        )


def _validate_bounded_number(value: object, field_name: str, *, upper: float) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )
    result = float(value)
    if not math.isfinite(result) or result <= 0.0 or result > upper:
        raise ConfigValidationError(
            f"{field_name} must be a finite number in (0.0, {upper}]; "
            f"received {value!r}."
        )


def _validate_finite_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
    ):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )


__all__ = [
    "UnsupportedEffectError",
    "validate_effects_config",
    "validate_motion_effects_config",
]
