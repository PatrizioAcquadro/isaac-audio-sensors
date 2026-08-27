"""Channel-response configuration parsing and validation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from isaac_audio_sensors.core.effects.config import (
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    FrequencyResponsePointConfig,
)
from isaac_audio_sensors.core.effects.config.common import (
    boolean,
    mapping,
    optional_float,
    reject_unknown,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain


def parse_channel_response(raw: object) -> ChannelResponseConfig:
    if raw is None:
        return ChannelResponseConfig()
    table = mapping(raw, "audio.effects.channel_response")
    reject_unknown(table, {"enabled", "microphones"}, "audio.effects.channel_response")
    enabled = boolean(
        table.get("enabled", False),
        "audio.effects.channel_response.enabled",
    )
    raw_microphones = table.get("microphones")
    if raw_microphones is None:
        microphones = None
    else:
        microphone_table = mapping(
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


def validate_channel_response(
    response: ChannelResponseConfig,
    *,
    orders: tuple[tuple[str, ...], ...],
    sample_rate_hz: int,
    backend_id: str,
    runtime_profile: str,
    sample_count: int | None,
) -> None:
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


def _parse_mic_config(mic_id: str, raw: object) -> ChannelResponseMicConfig:
    table_name = f"audio.effects.channel_response.microphones.{mic_id}"
    table = mapping(raw, table_name)
    reject_unknown(
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
            point_table = mapping(
                raw_point, f"{table_name}.frequency_response[{index}]"
            )
            reject_unknown(
                point_table,
                {"frequency_hz", "magnitude_db", "phase_deg"},
                f"{table_name}.frequency_response[{index}]",
            )
            parsed.append(
                FrequencyResponsePointConfig(
                    frequency_hz=optional_float(
                        point_table.get("frequency_hz"),
                        f"{table_name}.frequency_response[{index}].frequency_hz",
                    ),
                    magnitude_db=optional_float(
                        point_table.get("magnitude_db"),
                        f"{table_name}.frequency_response[{index}].magnitude_db",
                    ),
                    phase_deg=optional_float(
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
        gain_db=optional_float(table.get("gain_db"), f"{table_name}.gain_db"),
        delay_s=optional_float(table.get("delay_s"), f"{table_name}.delay_s"),
        polarity=polarity,
        frequency_response=points,
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
    if config.gain_db is not None:
        try:
            db_to_amplitude_gain(config.gain_db, f"{table}.gain_db")
        except ValueError as exc:
            raise ConfigValidationError(str(exc)) from exc
    if config.delay_s is not None and not math.isfinite(float(config.delay_s)):
            raise ConfigValidationError(
                f"{table}.delay_s must be finite; received {config.delay_s!r}, "
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


__all__ = ["parse_channel_response", "validate_channel_response"]
