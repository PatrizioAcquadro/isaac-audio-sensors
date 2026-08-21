"""Isaac Lab audio array sensor configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.constants import (
    COMPUTE_PATHS,
    DEFAULT_SAMPLE_RATE_HZ,
    TDOA_AMBIGUITY_POLICIES,
)
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.exceptions import IsaacLabUnavailable
from isaac_audio_sensors.lab._isaac_lab import load_isaac_lab_types


def _audio_array_sensor_class() -> type:
    from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor

    return AudioArraySensor


def _validate_cfg(cfg: Any) -> None:
    if str(cfg.prim_path).strip() == "":
        raise ValueError("AudioArraySensorCfg.prim_path must be non-empty.")
    if float(cfg.update_period) < 0.0:
        raise ValueError("AudioArraySensorCfg.update_period must be non-negative.")
    if int(cfg.history_length) < 0:
        raise ValueError("AudioArraySensorCfg.history_length must be non-negative.")
    if str(cfg.backend) not in registered_backend_ids():
        raise ValueError("AudioArraySensorCfg.backend is unknown.")
    if str(cfg.microphone_layout).strip() == "":
        raise ValueError("AudioArraySensorCfg.microphone_layout must be non-empty.")
    if int(cfg.sample_rate_hz) <= 0:
        raise ValueError("AudioArraySensorCfg.sample_rate_hz must be positive.")
    if int(cfg.max_events) < 0:
        raise ValueError("AudioArraySensorCfg.max_events must be non-negative.")
    if cfg.num_mics is not None and int(cfg.num_mics) <= 0:
        raise ValueError("AudioArraySensorCfg.num_mics must be positive when set.")
    if cfg.device is not None and str(cfg.device).strip() == "":
        raise ValueError("AudioArraySensorCfg.device must be non-empty when set.")
    if str(cfg.ambiguity_policy) not in TDOA_AMBIGUITY_POLICIES:
        raise ValueError("AudioArraySensorCfg.ambiguity_policy is unknown.")
    if str(cfg.compute_path) not in COMPUTE_PATHS:
        raise ValueError(
            "AudioArraySensorCfg.compute_path must be 'auto', 'scalar', or "
            "'batched'."
        )
    if not isinstance(cfg.effects, EffectsConfig):
        raise TypeError("AudioArraySensorCfg.effects must be an EffectsConfig.")


_LAB_TYPES = load_isaac_lab_types()


if _LAB_TYPES is not None:

    @_LAB_TYPES.configclass
    class AudioArraySensorCfg(_LAB_TYPES.SensorBaseCfg):  # type: ignore[misc]
        """Configuration for the Isaac Lab audio array sensor."""

        class_type: type | None = None
        prim_path: str = ""
        update_period: float = 0.0
        history_length: int = 0
        debug_vis: bool = False
        backend: str = "tdoa_synthetic"
        microphone_layout: str = "quad_front"
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
        max_events: int = 8
        num_mics: int | None = None
        device: str | None = None
        ambiguity_policy: str = "none"
        compute_path: str = "auto"
        effects: EffectsConfig = EffectsConfig()
        write_waveforms: bool = False
        writer_path: str | None = None
        waveform_dir: str | None = None

        def __post_init__(self) -> None:
            if self.class_type is None:
                self.class_type = _audio_array_sensor_class()
            self.sample_rate_hz = int(self.sample_rate_hz)
            self.max_events = int(self.max_events)
            self.history_length = int(self.history_length)
            if self.num_mics is not None:
                self.num_mics = int(self.num_mics)
            _validate_cfg(self)

else:

    @dataclass(kw_only=True)
    class AudioArraySensorCfg:
        """Configuration fallback used when Isaac Lab is not importable."""

        prim_path: str
        update_period: float = 0.0
        history_length: int = 0
        debug_vis: bool = False
        backend: str = "tdoa_synthetic"
        microphone_layout: str = "quad_front"
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
        max_events: int = 8
        num_mics: int | None = None
        device: str | None = None
        ambiguity_policy: str = "none"
        compute_path: str = "auto"
        effects: EffectsConfig = EffectsConfig()
        write_waveforms: bool = False
        writer_path: str | None = None
        waveform_dir: str | None = None
        class_type: type | None = None

        def __post_init__(self) -> None:
            _raise_if_live_lab_after_fallback_import("AudioArraySensorCfg")
            if self.class_type is None:
                self.class_type = _audio_array_sensor_class()
            self.sample_rate_hz = int(self.sample_rate_hz)
            self.max_events = int(self.max_events)
            self.history_length = int(self.history_length)
            if self.num_mics is not None:
                self.num_mics = int(self.num_mics)
            _validate_cfg(self)

        def copy(self) -> AudioArraySensorCfg:
            """Return a deep copy matching Isaac Lab configclass behavior."""

            return deepcopy(self)

        def replace(self, **kwargs: object) -> AudioArraySensorCfg:
            """Return a config copy with field overrides."""

            return replace(self, **kwargs)

        def validate(self) -> list[str]:
            """Validate the fallback config and mirror configclass API shape."""

            _raise_if_live_lab_after_fallback_import("AudioArraySensorCfg")
            _validate_cfg(self)
            return []


def _raise_if_live_lab_after_fallback_import(component_name: str) -> None:
    if _LAB_TYPES is None and load_isaac_lab_types() is not None:
        raise IsaacLabUnavailable(
            f"{component_name} is a fallback class imported before Isaac Lab "
            "SensorBase was available. Call "
            "isaac_audio_sensors.lab.ensure_isaac_lab_sensor_classes() after "
            "AppLauncher initialization and use the returned classes, or restart "
            "and import isaac_audio_sensors.lab only after AppLauncher."
        )
