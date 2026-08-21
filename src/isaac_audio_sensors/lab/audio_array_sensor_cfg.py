"""Isaac Lab audio sensor configuration."""

from __future__ import annotations

import math

from isaaclab.sensors import SensorBaseCfg
from isaaclab.utils.configclass import configclass

from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.constants import TDOA_AMBIGUITY_POLICIES
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor


@configclass
class AudioArraySensorCfg(SensorBaseCfg):
    """Configuration for fixed-shape Isaac Lab audio observations."""

    class_type: type[AudioArraySensor] = AudioArraySensor
    backend: str = "tdoa_synthetic"
    max_events: int = 8
    ambiguity_policy: str = "none"
    effects: EffectsConfig = EffectsConfig()

    def validate_config(self) -> None:
        if not str(self.prim_path).strip():
            raise ValueError("prim_path must be non-empty.")
        if not math.isfinite(float(self.update_period)) or self.update_period < 0.0:
            raise ValueError("update_period must be finite and non-negative.")
        if self.backend not in registered_backend_ids():
            raise ValueError(f"Unknown backend {self.backend!r}.")
        if isinstance(self.max_events, bool) or not isinstance(self.max_events, int):
            raise TypeError("max_events must be an integer.")
        if self.max_events < 0:
            raise ValueError("max_events must be non-negative.")
        if self.ambiguity_policy not in TDOA_AMBIGUITY_POLICIES:
            raise ValueError(f"Unknown ambiguity policy {self.ambiguity_policy!r}.")
        if not isinstance(self.effects, EffectsConfig):
            raise TypeError("effects must be an EffectsConfig.")
        if self.debug_vis:
            raise NotImplementedError(
                "AudioArraySensor has no debug visualization implementation."
            )
