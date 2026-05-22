"""Lazy debug-draw access for Isaac Sim visualization."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.isaac.viz.overlays import DebugPrimitive


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


def acquire_debug_draw_interface() -> Any:
    """Return the Isaac debug-draw interface with lazy optional imports."""

    debug_draw = require_debug_draw()
    if hasattr(debug_draw, "acquire_debug_draw_interface"):
        return debug_draw.acquire_debug_draw_interface()
    debug_draw_module = getattr(debug_draw, "_debug_draw", None)
    if debug_draw_module is not None and hasattr(
        debug_draw_module,
        "acquire_debug_draw_interface",
    ):
        return debug_draw_module.acquire_debug_draw_interface()
    raise IsaacIntegrationUnavailable(
        "Isaac debug visualization is importable, but no debug-draw interface "
        "factory was found."
    )


class IsaacDebugDrawer:
    """Best-effort renderer for structured audio debug primitives."""

    def __init__(self, interface: Any | None = None) -> None:
        self.interface = interface
        self.last_primitives: tuple[DebugPrimitive, ...] = ()

    def draw(
        self,
        primitives: tuple[DebugPrimitive, ...],
        *,
        clear: bool = True,
    ) -> tuple[DebugPrimitive, ...]:
        """Draw primitives when Isaac debug draw is available.

        The primitives are always returned and stored so callers have a
        structured fallback for testing, USD authoring, or JSON export.
        """

        self.last_primitives = tuple(primitives)
        interface = self.interface or acquire_debug_draw_interface()
        if clear and hasattr(interface, "clear_lines"):
            interface.clear_lines()
        if clear and hasattr(interface, "clear_points"):
            interface.clear_points()
        _draw_points(interface, primitives)
        _draw_lines(interface, primitives)
        return self.last_primitives


def _draw_points(interface: Any, primitives: tuple[DebugPrimitive, ...]) -> None:
    points = []
    colors = []
    sizes = []
    for primitive in primitives:
        if primitive.kind not in {"microphone", "source"}:
            continue
        points.extend(primitive.points_world)
        colors.extend([primitive.color_rgba] * len(primitive.points_world))
        sizes.extend([float(primitive.radius_m or 0.035)] * len(primitive.points_world))
    if points and hasattr(interface, "draw_points"):
        interface.draw_points(points, colors, sizes)


def _draw_lines(interface: Any, primitives: tuple[DebugPrimitive, ...]) -> None:
    starts = []
    ends = []
    colors = []
    widths = []
    for primitive in primitives:
        if primitive.kind == "bearing_ray" and len(primitive.points_world) >= 2:
            starts.append(primitive.points_world[0])
            ends.append(primitive.points_world[1])
            colors.append(primitive.color_rgba)
            widths.append(float(primitive.radius_m or 0.015))
        elif primitive.kind == "sector_wedge" and len(primitive.points_world) == 3:
            center, left, right = primitive.points_world
            segments = ((center, left), (center, right), (left, right))
            for line_start, line_end in segments:
                starts.append(line_start)
                ends.append(line_end)
                colors.append(primitive.color_rgba)
                widths.append(float(primitive.radius_m or 0.01))
    if starts and hasattr(interface, "draw_lines"):
        interface.draw_lines(starts, ends, colors, widths)
