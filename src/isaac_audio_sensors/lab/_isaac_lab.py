"""Lazy Isaac Lab type loading for optional Lab integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IsaacLabTypes:
    """Loaded Isaac Lab base classes and decorators."""

    SensorBase: type
    SensorBaseCfg: type
    configclass: Callable[[type], type]
    module_name: str


_SUCCESS: IsaacLabTypes | None = None
_LAST_IMPORT_ERROR: BaseException | None = None


def load_isaac_lab_types() -> IsaacLabTypes | None:
    """Return Isaac Lab bases when they are importable in this runtime.

    Isaac Lab imports can fail before Kit/AppLauncher initializes modules such
    as ``carb`` and ``omni``. Failures are intentionally not cached so a caller
    that launches Kit and imports this package afterwards can still get the real
    ``SensorBase`` classes.
    """

    global _LAST_IMPORT_ERROR, _SUCCESS
    if _SUCCESS is not None:
        return _SUCCESS

    loaders = (
        _load_modern_isaac_lab,
        _load_legacy_omni_isaac_lab,
    )
    for loader in loaders:
        try:
            _SUCCESS = loader()
            _LAST_IMPORT_ERROR = None
            return _SUCCESS
        except ImportError as exc:
            _LAST_IMPORT_ERROR = exc
    return None


def last_isaac_lab_import_error() -> BaseException | None:
    """Return the last optional Isaac Lab import error, if any."""

    return _LAST_IMPORT_ERROR


def reset_isaac_lab_type_cache() -> None:
    """Clear cached optional Isaac Lab import state.

    This is primarily useful for tests and for explicit recovery flows that
    deliberately re-probe after AppLauncher initializes Kit modules.
    """

    global _LAST_IMPORT_ERROR, _SUCCESS
    _SUCCESS = None
    _LAST_IMPORT_ERROR = None


def _load_modern_isaac_lab() -> IsaacLabTypes:
    from isaaclab.sensors import SensorBase, SensorBaseCfg  # type: ignore
    from isaaclab.utils import configclass  # type: ignore

    return IsaacLabTypes(
        SensorBase=SensorBase,
        SensorBaseCfg=SensorBaseCfg,
        configclass=configclass,
        module_name="isaaclab",
    )


def _load_legacy_omni_isaac_lab() -> IsaacLabTypes:
    from omni.isaac.lab.sensors import SensorBase, SensorBaseCfg  # type: ignore
    from omni.isaac.lab.utils import configclass  # type: ignore

    return IsaacLabTypes(
        SensorBase=SensorBase,
        SensorBaseCfg=SensorBaseCfg,
        configclass=configclass,
        module_name="omni.isaac.lab",
    )
