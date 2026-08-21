"""Isaac Lab audio observations.

Import this package after ``AppLauncher`` initialization when requesting a
public class. Importing the package itself remains runtime-safe.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacLabUnavailable

__all__ = [
    "AudioArraySensor",
    "AudioArraySensorCfg",
    "AudioArraySensorData",
    "EntityBindingCfg",
    "SourceEntityCfg",
]

_EXPORTS = {
    "AudioArraySensor": ("audio_array_sensor", "AudioArraySensor"),
    "AudioArraySensorCfg": ("audio_array_sensor_cfg", "AudioArraySensorCfg"),
    "AudioArraySensorData": ("audio_array_sensor_data", "AudioArraySensorData"),
    "EntityBindingCfg": ("entity_binding", "EntityBindingCfg"),
    "SourceEntityCfg": ("entity_binding", "SourceEntityCfg"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    try:
        value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    except ImportError as exc:
        raise IsaacLabUnavailable(
            "Initialize Isaac Lab with AppLauncher before importing Lab classes."
        ) from exc
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
