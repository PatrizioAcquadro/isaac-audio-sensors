"""Isaac Lab audio sensor configuration."""

from __future__ import annotations

import math

from isaaclab.sensors import SensorBaseCfg
from isaaclab.utils.configclass import configclass

from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.lab.audio_array_sensor import AudioArraySensor


@configclass
class AudioArraySensorCfg(SensorBaseCfg):
    """Configuration for fixed-shape Isaac Lab audio observations."""

    class_type: type[AudioArraySensor] = AudioArraySensor
    backend: str = "analytic_acoustics"
    max_observations: int = 8
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS
    analytic_max_order: int = 0
    analytic_air_absorption: bool = False
    analytic_ray_tracing: bool = False
    effects: EffectsConfig = EffectsConfig()

    def validate_config(self) -> None:
        if not str(self.prim_path).strip():
            raise ValueError("prim_path must be non-empty.")
        if not math.isfinite(float(self.update_period)) or self.update_period < 0.0:
            raise ValueError("update_period must be finite and non-negative.")
        if self.backend not in registered_backend_ids():
            raise ValueError(f"Unknown backend {self.backend!r}.")
        if isinstance(self.max_observations, bool) or not isinstance(
            self.max_observations, int
        ):
            raise TypeError("max_observations must be an integer.")
        if self.max_observations < 0:
            raise ValueError("max_observations must be non-negative.")
        if (
            not math.isfinite(float(self.speed_of_sound_mps))
            or self.speed_of_sound_mps <= 0.0
        ):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if (
            isinstance(self.analytic_max_order, bool)
            or not isinstance(self.analytic_max_order, int)
            or self.analytic_max_order < 0
        ):
            raise ValueError("analytic_max_order must be a non-negative integer.")
        if not isinstance(self.analytic_air_absorption, bool):
            raise TypeError("analytic_air_absorption must be a boolean.")
        if not isinstance(self.analytic_ray_tracing, bool):
            raise TypeError("analytic_ray_tracing must be a boolean.")
        if not isinstance(self.effects, EffectsConfig):
            raise TypeError("effects must be an EffectsConfig.")
        if self.debug_vis:
            raise NotImplementedError(
                "AudioArraySensor has no debug visualization implementation."
            )
