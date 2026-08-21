"""Normalize TOML and dictionary audio-effects configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from types import MappingProxyType
from typing import Any

from isaac_audio_sensors.core.effects.config import (
    AgcConfig,
    AmbientNoiseConfig,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    ElectronicsConfig,
    FrequencyResponsePointConfig,
    MotionEffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


def parse_effects_config(raw: object) -> EffectsConfig:
    """Parse ``[audio.effects.*]`` mappings into immutable records."""

    if raw is None:
        return EffectsConfig()
    effects = _mapping(raw, "audio.effects")
    _reject_unknown(
        effects,
        {"channel_response", "noise", "electronics", "directivity", "motion"},
        "audio.effects",
    )
    return EffectsConfig(
        channel_response=_parse_channel_response(effects.get("channel_response")),
        noise=_parse_noise(effects.get("noise")),
        electronics=_parse_electronics(effects.get("electronics")),
        directivity=_parse_directivity(effects.get("directivity")),
        motion=_parse_motion(effects.get("motion")),
    )


def _parse_channel_response(raw: object) -> ChannelResponseConfig:
    if raw is None:
        return ChannelResponseConfig()
    table = _mapping(raw, "audio.effects.channel_response")
    _reject_unknown(table, {"enabled", "microphones"}, "audio.effects.channel_response")
    enabled = _bool(
        table.get("enabled", False),
        "audio.effects.channel_response.enabled",
    )
    raw_microphones = table.get("microphones")
    if raw_microphones is None:
        microphones = None
    else:
        microphone_table = _mapping(
            raw_microphones, "audio.effects.channel_response.microphones"
        )
        normalized_ids = tuple(str(raw_mic_id) for raw_mic_id in microphone_table)
        if len(set(normalized_ids)) != len(normalized_ids):
            duplicate = next(
                mic_id
                for index, mic_id in enumerate(normalized_ids)
                if mic_id in normalized_ids[:index]
            )
            raise ConfigValidationError(
                "audio.effects.channel_response.microphones contains duplicate "
                f"id {duplicate!r} after normalization."
            )
        normalized: dict[str, ChannelResponseMicConfig] = {}
        for raw_mic_id, raw_mic in microphone_table.items():
            mic_id = str(raw_mic_id)
            if not isinstance(raw_mic_id, str) or not mic_id:
                raise ConfigValidationError(
                    "audio.effects.channel_response.microphones ids must be exact "
                    f"non-empty MicrophoneSpec.mic_id strings; received {raw_mic_id!r}."
                )
            normalized[mic_id] = _parse_mic_config(mic_id, raw_mic)
        microphones = MappingProxyType(normalized)
    return ChannelResponseConfig(enabled=enabled, microphones=microphones)


def _parse_noise(raw: object) -> NoiseConfig:
    if raw is None:
        return NoiseConfig()
    table_name = "audio.effects.noise"
    table = _mapping(raw, table_name)
    _reject_unknown(
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
        jitter = _number(jitter, f"{table_name}.clock_jitter_std_s")
    drift_raw = table.get("clock_drift_ppm")
    drift = (
        None
        if drift_raw is None
        else _parse_number_mapping(drift_raw, f"{table_name}.clock_drift_ppm")
    )
    return NoiseConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        seed=seed,
        self_noise=_parse_self_noise(table.get("self_noise")),
        ambient=_parse_ambient_noise(table.get("ambient")),
        clock_jitter_std_s=jitter,
        clock_drift_ppm=drift,
    )


def _parse_electronics(raw: object) -> ElectronicsConfig:
    if raw is None:
        return ElectronicsConfig()
    table_name = "audio.effects.electronics"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"enabled", "full_scale", "bit_depth", "dither_enabled", "agc"},
        table_name,
    )
    bit_depth = table.get("bit_depth")
    if bit_depth is not None and type(bit_depth) is not int:
        raise ConfigValidationError(
            f"{table_name}.bit_depth must be an exact integer in [8, 32]; "
            f"received {bit_depth!r}."
        )
    dither = table.get("dither_enabled")
    if dither is not None:
        dither = _bool(dither, f"{table_name}.dither_enabled")
    return ElectronicsConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        full_scale=(
            None
            if "full_scale" not in table
            else _number(table["full_scale"], f"{table_name}.full_scale")
        ),
        bit_depth=bit_depth,
        dither_enabled=dither,
        agc=_parse_agc(table.get("agc")),
    )


def _parse_directivity(raw: object) -> DirectivityConfig:
    if raw is None:
        return DirectivityConfig()
    table_name = "audio.effects.directivity"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"enabled", "source_patterns", "mic_patterns", "mode"},
        table_name,
    )
    mode = table.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise ConfigValidationError(
            f"{table_name}.mode must be exactly 'per_pair_direct_path' or None; "
            f"received {mode!r}."
        )
    return DirectivityConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        source_patterns=_parse_directivity_pattern_set(
            table.get("source_patterns"),
            table=f"{table_name}.source_patterns",
            entity_label="AudioSourceSpec.source_id",
        ),
        mic_patterns=_parse_directivity_pattern_set(
            table.get("mic_patterns"),
            table=f"{table_name}.mic_patterns",
            entity_label="MicrophoneSpec.mic_id",
        ),
        mode=mode,
    )


def _parse_directivity_pattern_set(
    raw: object,
    *,
    table: str,
    entity_label: str,
) -> DirectivityPatternSetConfig | None:
    if raw is None:
        return None
    values = _mapping(raw, table)
    _reject_unknown(values, {"default", "overrides"}, table)
    overrides_raw = values.get("overrides")
    overrides: Mapping[str, DirectivityPatternConfig] | None = None
    if overrides_raw is not None:
        override_table = _mapping(overrides_raw, f"{table}.overrides")
        normalized_ids = tuple(str(raw_id) for raw_id in override_table)
        if len(set(normalized_ids)) != len(normalized_ids):
            duplicate = next(
                entity_id
                for index, entity_id in enumerate(normalized_ids)
                if entity_id in normalized_ids[:index]
            )
            raise ConfigValidationError(
                f"{table}.overrides contains duplicate id {duplicate!r} "
                "after normalization."
            )
        parsed_overrides: dict[str, DirectivityPatternConfig] = {}
        for raw_id, raw_pattern in override_table.items():
            entity_id = str(raw_id)
            if not isinstance(raw_id, str) or not entity_id:
                raise ConfigValidationError(
                    f"{table}.overrides ids must be exact non-empty {entity_label} "
                    f"strings; received {raw_id!r}."
                )
            parsed_overrides[entity_id] = _parse_directivity_pattern(
                raw_pattern,
                table=f"{table}.overrides.{entity_id}",
            )
        overrides = MappingProxyType(parsed_overrides)
    default_raw = values.get("default")
    return DirectivityPatternSetConfig(
        default=(
            None
            if default_raw is None
            else _parse_directivity_pattern(default_raw, table=f"{table}.default")
        ),
        overrides=overrides,
    )


def _parse_directivity_pattern(
    raw: object,
    *,
    table: str,
) -> DirectivityPatternConfig:
    values = _mapping(raw, table)
    _reject_unknown(values, {"family", "frequency_points"}, table)
    family = values.get("family")
    if family is not None and not isinstance(family, str):
        raise ConfigValidationError(
            f"{table}.family must be an exact case-sensitive string; received "
            f"{family!r}."
        )
    raw_points = values.get("frequency_points")
    points: tuple[DirectivityFrequencyPointConfig, ...] | None = None
    if raw_points is not None:
        if not isinstance(raw_points, (list, tuple)):
            raise ConfigValidationError(
                f"{table}.frequency_points must be a sequence of tables; "
                f"received {type(raw_points).__name__}."
            )
        parsed: list[DirectivityFrequencyPointConfig] = []
        for index, raw_point in enumerate(raw_points):
            point_table_name = f"{table}.frequency_points[{index}]"
            point = _mapping(raw_point, point_table_name)
            _reject_unknown(point, {"freq_hz", "gain_db"}, point_table_name)
            parsed.append(
                DirectivityFrequencyPointConfig(
                    freq_hz=_optional_float(
                        point.get("freq_hz"), f"{point_table_name}.freq_hz"
                    ),
                    gain_db=_optional_float(
                        point.get("gain_db"), f"{point_table_name}.gain_db"
                    ),
                )
            )
        points = tuple(parsed)
    return DirectivityPatternConfig(family=family, frequency_points=points)


def _parse_agc(raw: object) -> AgcConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.electronics.agc"
    table = _mapping(raw, table_name)
    fields = {
        "enabled",
        "target_rms_dbfs",
        "attack_time_s",
        "release_time_s",
        "gain_floor_db",
        "gain_ceiling_db",
    }
    _reject_unknown(table, fields, table_name)
    return AgcConfig(
        enabled=_bool(table.get("enabled", False), f"{table_name}.enabled"),
        target_rms_dbfs=_optional_float(
            table.get("target_rms_dbfs"), f"{table_name}.target_rms_dbfs"
        ),
        attack_time_s=_optional_float(
            table.get("attack_time_s"), f"{table_name}.attack_time_s"
        ),
        release_time_s=_optional_float(
            table.get("release_time_s"), f"{table_name}.release_time_s"
        ),
        gain_floor_db=_optional_float(
            table.get("gain_floor_db"), f"{table_name}.gain_floor_db"
        ),
        gain_ceiling_db=_optional_float(
            table.get("gain_ceiling_db"), f"{table_name}.gain_ceiling_db"
        ),
    )


def _parse_self_noise(raw: object) -> SelfNoiseConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.noise.self_noise"
    table = _mapping(raw, table_name)
    _reject_unknown(table, {"default", "microphones"}, table_name)
    microphones_raw = table.get("microphones")
    microphones: Mapping[str, NoiseLevelSpecConfig] | None = None
    if microphones_raw is not None:
        mic_table = _mapping(microphones_raw, f"{table_name}.microphones")
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
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"level_db", "spectrum", "coherent_fraction"},
        table_name,
    )
    return AmbientNoiseConfig(
        level_db=(
            None
            if "level_db" not in table
            else _absolute_level(table["level_db"], f"{table_name}.level_db")
        ),
        spectrum=_parse_noise_spectrum(table.get("spectrum"), table_name),
        coherent_fraction=(
            None
            if "coherent_fraction" not in table
            else _number(
                table["coherent_fraction"],
                f"{table_name}.coherent_fraction",
            )
        ),
    )


def _parse_noise_level(raw: object, table_name: str) -> NoiseLevelSpecConfig:
    table = _mapping(raw, table_name)
    _reject_unknown(table, {"level_db", "spectrum"}, table_name)
    return NoiseLevelSpecConfig(
        level_db=(
            None
            if "level_db" not in table
            else _absolute_level(table["level_db"], f"{table_name}.level_db")
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
        point = _mapping(raw_point, point_name)
        _reject_unknown(point, {"freq_hz", "level_db"}, point_name)
        points.append(
            NoiseSpectrumPointConfig(
                freq_hz=(
                    None
                    if "freq_hz" not in point
                    else _number(point["freq_hz"], f"{point_name}.freq_hz")
                ),
                level_db=(
                    None
                    if "level_db" not in point
                    else _number(point["level_db"], f"{point_name}.level_db")
                ),
            )
        )
    return tuple(points)


def _parse_number_mapping(raw: Mapping[Any, Any], table: str) -> Mapping[str, float]:
    return _parse_mic_mapping(raw, table=table, value_parser=_number)


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


def _parse_motion(raw: object) -> MotionEffectsConfig:
    if raw is None:
        return MotionEffectsConfig()
    table_name = "audio.effects.motion"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {
            "derive_velocity_from_poses",
            "teleport_speed_threshold_mps",
            "stale_time_s",
            "smoothing_alpha",
            "segments_per_window",
        },
        table_name,
    )
    segments = table.get("segments_per_window", 1)
    if type(segments) is not int:
        raise ConfigValidationError(
            f"{table_name}.segments_per_window must be an exact integer; "
            f"received {segments!r}."
        )
    return MotionEffectsConfig(
        derive_velocity_from_poses=_bool(
            table.get("derive_velocity_from_poses", False),
            f"{table_name}.derive_velocity_from_poses",
        ),
        teleport_speed_threshold_mps=_number(
            table.get("teleport_speed_threshold_mps", 50.0),
            f"{table_name}.teleport_speed_threshold_mps",
        ),
        stale_time_s=_number(
            table.get("stale_time_s", 0.5),
            f"{table_name}.stale_time_s",
        ),
        smoothing_alpha=_optional_float(
            table.get("smoothing_alpha"),
            f"{table_name}.smoothing_alpha",
        ),
        segments_per_window=segments,
    )


def _parse_mic_config(mic_id: str, raw: object) -> ChannelResponseMicConfig:
    table_name = f"audio.effects.channel_response.microphones.{mic_id}"
    table = _mapping(raw, table_name)
    _reject_unknown(
        table,
        {"gain_db", "delay_s", "polarity", "frequency_response"},
        table_name,
    )
    response = table.get("frequency_response")
    points: tuple[FrequencyResponsePointConfig, ...] | None = None
    if response is not None:
        if not isinstance(response, (list, tuple)):
            raise ConfigValidationError(
                f"{table_name}.frequency_response must be a sequence of tables; "
                f"received {type(response).__name__}."
            )
        parsed: list[FrequencyResponsePointConfig] = []
        for index, raw_point in enumerate(response):
            point_table = _mapping(
                raw_point, f"{table_name}.frequency_response[{index}]"
            )
            _reject_unknown(
                point_table,
                {"frequency_hz", "magnitude_db", "phase_deg"},
                f"{table_name}.frequency_response[{index}]",
            )
            parsed.append(
                FrequencyResponsePointConfig(
                    frequency_hz=_optional_float(
                        point_table.get("frequency_hz"),
                        f"{table_name}.frequency_response[{index}].frequency_hz",
                    ),
                    magnitude_db=_optional_float(
                        point_table.get("magnitude_db"),
                        f"{table_name}.frequency_response[{index}].magnitude_db",
                    ),
                    phase_deg=_optional_float(
                        point_table.get("phase_deg"),
                        f"{table_name}.frequency_response[{index}].phase_deg",
                    ),
                )
            )
        points = tuple(parsed)
    polarity = table.get("polarity")
    if polarity is not None and (type(polarity) is not int or polarity not in {-1, 1}):
        raise ConfigValidationError(
            f"{table_name}.polarity must be exactly -1 or 1; received {polarity!r}."
        )
    return ChannelResponseMicConfig(
        gain_db=_optional_float(table.get("gain_db"), f"{table_name}.gain_db"),
        delay_s=_optional_float(table.get("delay_s"), f"{table_name}.delay_s"),
        polarity=polarity,
        frequency_response=points,
    )


def _mapping(value: object, table: str) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(
            f"{table} must be a table/mapping; received {type(value).__name__}."
        )
    return value


def _reject_unknown(values: Mapping[Any, Any], allowed: set[str], table: str) -> None:
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise ConfigValidationError(
            f"{table} contains unsupported fields {unknown}; expected a subset of "
            f"{sorted(allowed)}."
        )


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ConfigValidationError(f"{field_name} must be a bool; received {value!r}.")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )
    result = float(value)
    if not math.isfinite(result):
        raise ConfigValidationError(f"{field_name} must be finite; received {value!r}.")
    return result


def _absolute_level(value: object, field_name: str) -> float:
    if (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and float(value) == -math.inf
    ):
        return -math.inf
    return _number(value, field_name)


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(
            f"{field_name} must be a finite number; received {value!r}."
        ) from exc
    if not math.isfinite(result):
        raise ConfigValidationError(f"{field_name} must be finite; received {value!r}.")
    return result


__all__ = ["parse_effects_config"]
