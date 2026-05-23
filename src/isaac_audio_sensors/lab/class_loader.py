"""Public recovery helpers for Isaac Lab sensor classes."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass

from isaac_audio_sensors.core.exceptions import IsaacLabUnavailable
from isaac_audio_sensors.lab._isaac_lab import (
    IsaacLabTypes,
    last_isaac_lab_import_error,
    load_isaac_lab_types,
)


@dataclass(frozen=True, slots=True)
class AudioArraySensorClasses:
    """Resolved public Lab classes and their Isaac Lab inheritance state."""

    sensor: type
    cfg: type
    data: type
    lab_types: IsaacLabTypes | None
    real: bool


def get_audio_array_sensor_classes(
    *,
    require_real: bool = False,
    reload_if_needed: bool = True,
) -> AudioArraySensorClasses:
    """Return current audio sensor classes, optionally requiring real Lab bases.

    Plain Python callers can use ``require_real=False`` to receive import-safe
    fallback classes. Live Isaac Lab callers should use ``require_real=True``;
    if the fallback classes were imported before AppLauncher initialized Kit,
    this function reloads the Lab modules once and updates the public package
    namespace. If real Lab bases still cannot be proven, it raises a clear
    recovery error instead of silently returning fallback classes.
    """

    classes = _current_classes()
    if not require_real or classes.real:
        return classes

    lab_types = load_isaac_lab_types()
    if lab_types is None:
        raise _unavailable_error(
            "Isaac Lab SensorBase classes are not importable in this runtime. "
            "Launch Isaac Lab/Kit through AppLauncher first, then call "
            "isaac_audio_sensors.lab.ensure_isaac_lab_sensor_classes() before "
            "constructing Lab sensors."
        )

    if reload_if_needed:
        classes = _reload_lab_classes()
        if classes.real:
            return classes

    raise IsaacLabUnavailable(
        "isaac_audio_sensors.lab was imported before Isaac Lab SensorBase was "
        "available, and the fallback classes could not be upgraded in place. "
        "Start AppLauncher before importing AudioArraySensor/AudioArraySensorCfg, "
        "or call ensure_isaac_lab_sensor_classes() after AppLauncher and use the "
        "classes returned from that call. Existing class objects imported before "
        "recovery remain fallback classes."
    )


def ensure_isaac_lab_sensor_classes() -> AudioArraySensorClasses:
    """Return real Isaac Lab classes or raise a deterministic recovery error."""

    return get_audio_array_sensor_classes(require_real=True)


def _current_classes() -> AudioArraySensorClasses:
    cfg_module = importlib.import_module(
        "isaac_audio_sensors.lab.audio_array_sensor_cfg"
    )
    sensor_module = importlib.import_module(
        "isaac_audio_sensors.lab.audio_array_sensor"
    )
    data_module = importlib.import_module(
        "isaac_audio_sensors.lab.audio_array_sensor_data"
    )
    lab_types = load_isaac_lab_types()
    real = False
    if lab_types is not None:
        real = issubclass(
            sensor_module.AudioArraySensor,
            lab_types.SensorBase,
        ) and issubclass(
            cfg_module.AudioArraySensorCfg,
            lab_types.SensorBaseCfg,
        )
    return AudioArraySensorClasses(
        sensor=sensor_module.AudioArraySensor,
        cfg=cfg_module.AudioArraySensorCfg,
        data=data_module.AudioArraySensorData,
        lab_types=lab_types,
        real=real,
    )


def _reload_lab_classes() -> AudioArraySensorClasses:
    cfg_module = importlib.import_module(
        "isaac_audio_sensors.lab.audio_array_sensor_cfg"
    )
    sensor_module = importlib.import_module(
        "isaac_audio_sensors.lab.audio_array_sensor"
    )
    importlib.reload(cfg_module)
    importlib.reload(sensor_module)
    classes = _current_classes()
    lab_package = sys.modules.get("isaac_audio_sensors.lab")
    if lab_package is not None:
        lab_package.AudioArraySensor = classes.sensor
        lab_package.AudioArraySensorCfg = classes.cfg
        lab_package.AudioArraySensorData = classes.data
    return classes


def _unavailable_error(message: str) -> IsaacLabUnavailable:
    import_error = last_isaac_lab_import_error()
    detail = "" if import_error is None else f" Last import error: {import_error}"
    return IsaacLabUnavailable(f"{message}{detail}")
