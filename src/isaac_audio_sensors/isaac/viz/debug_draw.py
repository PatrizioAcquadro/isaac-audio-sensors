"""Lazy debug-draw access for Isaac Sim visualization."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable


def require_debug_draw() -> Any:
    """Return Isaac debug-draw interface or raise a clear optional error."""

    try:
        import omni.isaac.debug_draw as debug_draw  # type: ignore
    except ImportError as exc:
        raise IsaacIntegrationUnavailable(
            "Isaac debug visualization requires omni.isaac.debug_draw inside "
            "an Isaac Sim Python environment."
        ) from exc
    return debug_draw
