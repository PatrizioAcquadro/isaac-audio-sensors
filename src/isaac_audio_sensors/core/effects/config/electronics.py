"""Electronics configuration parsing and validation."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.effects.config import (
    AgcConfig,
    ElectronicsConfig,
    NoiseConfig,
)
from isaac_audio_sensors.core.effects.config.common import (
    boolean,
    mapping,
    number,
    optional_float,
    reject_unknown,
    validate_finite_range,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    UnsupportedEffectError,
)


def parse_electronics(raw: object) -> ElectronicsConfig:
    if raw is None:
        return ElectronicsConfig()
    table_name = "audio.effects.electronics"
    table = mapping(raw, table_name)
    reject_unknown(
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
        dither = boolean(dither, f"{table_name}.dither_enabled")
    return ElectronicsConfig(
        enabled=boolean(table.get("enabled", False), f"{table_name}.enabled"),
        full_scale=(
            None
            if "full_scale" not in table
            else number(table["full_scale"], f"{table_name}.full_scale")
        ),
        bit_depth=bit_depth,
        dither_enabled=dither,
        agc=_parse_agc(table.get("agc")),
    )


def validate_electronics(
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
        validate_finite_range(
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


def _parse_agc(raw: object) -> AgcConfig | None:
    if raw is None:
        return None
    table_name = "audio.effects.electronics.agc"
    table = mapping(raw, table_name)
    fields = {
        "enabled",
        "target_rms_dbfs",
        "attack_time_s",
        "release_time_s",
        "gain_floor_db",
        "gain_ceiling_db",
    }
    reject_unknown(table, fields, table_name)
    return AgcConfig(
        enabled=boolean(table.get("enabled", False), f"{table_name}.enabled"),
        target_rms_dbfs=optional_float(
            table.get("target_rms_dbfs"), f"{table_name}.target_rms_dbfs"
        ),
        attack_time_s=optional_float(
            table.get("attack_time_s"), f"{table_name}.attack_time_s"
        ),
        release_time_s=optional_float(
            table.get("release_time_s"), f"{table_name}.release_time_s"
        ),
        gain_floor_db=optional_float(
            table.get("gain_floor_db"), f"{table_name}.gain_floor_db"
        ),
        gain_ceiling_db=optional_float(
            table.get("gain_ceiling_db"), f"{table_name}.gain_ceiling_db"
        ),
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
            validate_finite_range(
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


__all__ = ["parse_electronics", "validate_electronics"]
