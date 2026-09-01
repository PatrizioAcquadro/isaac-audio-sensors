"""Noise configuration parsing and validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from types import MappingProxyType
from typing import Any

from isaac_audio_sensors.core.effects.config import (
    AmbientNoiseConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.effects.config.common import (
    absolute_level,
    boolean,
    mapping,
    number,
    reject_unknown,
    validate_absolute_level,
    validate_finite_range,
    validate_mapping_order,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    UnsupportedEffectError,
)


def parse_noise(raw: object) -> NoiseConfig:
    if raw is None:
        return NoiseConfig()
    table_name = "audio.effects.noise"
    table = mapping(raw, table_name)
    reject_unknown(
        table,
        {
            "enabled",
            "seed",
            "self_noise",
            "ambient",
            "clock_jitter_std_s",
            "clock_drift_ppm",
        },
        table_name,
    )
    seed = table.get("seed")
    if seed is not None and type(seed) is not int:
        raise ConfigValidationError(
            f"{table_name}.seed must be an exact integer; received {seed!r}."
        )
    jitter = table.get("clock_jitter_std_s")
    if isinstance(jitter, Mapping):
        jitter = _parse_number_mapping(
            jitter,
            f"{table_name}.clock_jitter_std_s",
        )
    elif jitter is not None:
        jitter = number(jitter, f"{table_name}.clock_jitter_std_s")
    drift_raw = table.get("clock_drift_ppm")
    drift = (
        None
        if drift_raw is None
        else _parse_number_mapping(drift_raw, f"{table_name}.clock_drift_ppm")
    )
    return NoiseConfig(
        enabled=boolean(table.get("enabled", False), f"{table_name}.enabled"),
        seed=seed,
        self_noise=_parse_self_noise(table.get("self_noise")),
        ambient=_parse_ambient_noise(table.get("ambient")),
        clock_jitter_std_s=jitter,
        clock_drift_ppm=drift,
    )


def validate_noise(
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
            validate_mapping_order(
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
                validate_absolute_level(
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
        validate_finite_range(
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
        validate_mapping_order(
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
        validate_finite_range(
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
        validate_mapping_order(
            tuple(drift),
            orders,
            table=f"{table}.clock_drift_ppm",
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        for mic_id, value in drift.items():
            validate_finite_range(
                value,
                field=f"{table}.clock_drift_ppm.{mic_id}",
                lower=-1000.0,
                upper=1000.0,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
            )

    if nonzero_stochastic and config.seed is None:
        raise ConfigValidationError(
            f"{table}.seed is required for every nonzero stochastic noise setting; "
            f"received None, backend={backend_id!r}, profile={runtime_profile!r}."
        )


def _parse_self_noise(raw: object) -> SelfNoiseConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.noise.self_noise"
    table = mapping(raw, table_name)
    reject_unknown(table, {"default", "microphones"}, table_name)
    microphones_raw = table.get("microphones")
    microphones: Mapping[str, NoiseLevelSpecConfig] | None = None
    if microphones_raw is not None:
        mic_table = mapping(microphones_raw, f"{table_name}.microphones")
        microphones = _parse_mic_mapping(
            mic_table,
            table=f"{table_name}.microphones",
            value_parser=_parse_noise_level,
        )
    default_raw = table.get("default")
    return SelfNoiseConfig(
        default=(
            None
            if default_raw is None
            else _parse_noise_level(default_raw, f"{table_name}.default")
        ),
        microphones=microphones,
    )


def _parse_ambient_noise(raw: object) -> AmbientNoiseConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.noise.ambient"
    table = mapping(raw, table_name)
    reject_unknown(
        table,
        {"level_db", "spectrum", "coherent_fraction"},
        table_name,
    )
    return AmbientNoiseConfig(
        level_db=(
            None
            if "level_db" not in table
            else absolute_level(table["level_db"], f"{table_name}.level_db")
        ),
        spectrum=_parse_noise_spectrum(table.get("spectrum"), table_name),
        coherent_fraction=(
            None
            if "coherent_fraction" not in table
            else number(
                table["coherent_fraction"],
                f"{table_name}.coherent_fraction",
            )
        ),
    )


def _parse_noise_level(raw: object, table_name: str) -> NoiseLevelSpecConfig:
    table = mapping(raw, table_name)
    reject_unknown(table, {"level_db", "spectrum"}, table_name)
    return NoiseLevelSpecConfig(
        level_db=(
            None
            if "level_db" not in table
            else absolute_level(table["level_db"], f"{table_name}.level_db")
        ),
        spectrum=_parse_noise_spectrum(table.get("spectrum"), table_name),
    )


def _parse_noise_spectrum(
    raw: object,
    table_name: str,
) -> tuple[NoiseSpectrumPointConfig, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise ConfigValidationError(
            f"{table_name}.spectrum must be a sequence of tables; received "
            f"{type(raw).__name__}."
        )
    points: list[NoiseSpectrumPointConfig] = []
    for index, raw_point in enumerate(raw):
        point_name = f"{table_name}.spectrum[{index}]"
        point = mapping(raw_point, point_name)
        reject_unknown(point, {"freq_hz", "level_db"}, point_name)
        points.append(
            NoiseSpectrumPointConfig(
                freq_hz=(
                    None
                    if "freq_hz" not in point
                    else number(point["freq_hz"], f"{point_name}.freq_hz")
                ),
                level_db=(
                    None
                    if "level_db" not in point
                    else number(point["level_db"], f"{point_name}.level_db")
                ),
            )
        )
    return tuple(points)


def _parse_number_mapping(
    raw: Mapping[Any, Any], table: str
) -> Mapping[str, float]:
    return _parse_mic_mapping(raw, table=table, value_parser=number)


def _parse_mic_mapping(
    raw: Mapping[Any, Any],
    *,
    table: str,
    value_parser: Any,
) -> Mapping[str, Any]:
    normalized_ids = tuple(str(raw_id) for raw_id in raw)
    if len(set(normalized_ids)) != len(normalized_ids):
        duplicate = next(
            mic_id
            for index, mic_id in enumerate(normalized_ids)
            if mic_id in normalized_ids[:index]
        )
        raise ConfigValidationError(
            f"{table} contains duplicate id {duplicate!r} after normalization."
        )
    values: dict[str, Any] = {}
    for raw_id, raw_value in raw.items():
        mic_id = str(raw_id)
        if not isinstance(raw_id, str) or not mic_id:
            raise ConfigValidationError(
                f"{table} ids must be exact non-empty MicrophoneSpec.mic_id "
                f"strings; received {raw_id!r}."
            )
        values[mic_id] = value_parser(raw_value, f"{table}.{mic_id}")
    return MappingProxyType(values)


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
    validate_absolute_level(
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
        validate_finite_range(
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
        validate_finite_range(
            point.level_db,
            field=f"{prefix}.level_db",
            lower=-120.0,
            upper=120.0,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
        )
        previous = frequency


__all__ = ["parse_noise", "validate_noise"]
