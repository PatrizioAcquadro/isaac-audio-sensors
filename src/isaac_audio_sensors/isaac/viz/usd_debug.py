"""Author debug primitives as persistent USD geometry.

The transient drawer (``viz.debug_draw``) clears every frame; this module
authors the same ``DebugPrimitive`` records as real prims (Spheres for
microphones/sources, BasisCurves for bearing rays and sector wedges) so the
debug picture survives pause, camera moves, and screenshots, and is visible
to anything that reads the stage. Authoring targets the session layer by
default so user stages are not dirtied.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from contextlib import nullcontext, suppress
from typing import Any

from isaac_audio_sensors.isaac.stage_audio import (
    get_or_define_prim,
    remove_prim,
    set_prim_xform_pose,
)
from isaac_audio_sensors.isaac.viz.overlays import DebugPrimitive

DEFAULT_DEBUG_ROOT = "/World/IasAudioDebug"
_SPHERE_KINDS = frozenset({"microphone", "source"})


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") or "primitive"


def _set_attr(prim: Any, name: str, value: Any) -> None:
    """Set an attribute on fake (dict-backed) or real USD prims."""

    if hasattr(prim, "attributes"):
        prim.attributes[name] = value
        return
    attr = None
    getter = getattr(prim, "GetAttribute", None)
    if callable(getter):
        with suppress(Exception):
            candidate = getter(name)
            if candidate is not None and getattr(candidate, "IsValid", bool)():
                attr = candidate
    if attr is None:
        creator = getattr(prim, "CreateAttribute", None)
        if not callable(creator):
            return
        try:
            from pxr import Sdf  # type: ignore
        except ImportError:
            return
        value_type = getattr(Sdf.ValueTypeNames, "String", None)
        if isinstance(value, bool):
            value_type = getattr(Sdf.ValueTypeNames, "Bool", value_type)
        elif isinstance(value, (int, float)):
            value_type = getattr(Sdf.ValueTypeNames, "Double", value_type)
        with suppress(Exception):
            attr = creator(name, value_type)
    if attr is not None:
        with suppress(Exception):
            attr.Set(value)


class UsdDebugGeometryAuthor:
    """Maintain a stable subtree of debug prims mirroring the latest frame."""

    def __init__(
        self,
        *,
        root: str = DEFAULT_DEBUG_ROOT,
        use_session_layer: bool = True,
    ) -> None:
        self.root = str(root or DEFAULT_DEBUG_ROOT)
        self.use_session_layer = bool(use_session_layer)
        self._authored_paths: tuple[str, ...] = ()

    @property
    def authored_paths(self) -> tuple[str, ...]:
        return self._authored_paths

    def author(
        self,
        stage: Any,
        primitives: Sequence[DebugPrimitive],
    ) -> tuple[str, ...]:
        """Author/update one prim per primitive; prune prims that vanished."""

        with self._edit_context(stage):
            get_or_define_prim(stage, prim_path=self.root, prim_type="Scope")
            paths: list[str] = []
            for index, primitive in enumerate(primitives):
                path = (
                    f"{self.root}/"
                    f"{primitive.kind}_{index:02d}_{_slug(primitive.label)}"
                )
                self._author_primitive(stage, path, primitive)
                paths.append(path)
            for stale in set(self._authored_paths) - set(paths):
                with suppress(Exception):
                    remove_prim(stage, stale)
        self._authored_paths = tuple(paths)
        return self._authored_paths

    def clear(self, stage: Any) -> None:
        """Remove the whole debug subtree."""

        with self._edit_context(stage), suppress(Exception):
            remove_prim(stage, self.root)
        self._authored_paths = ()

    def _author_primitive(
        self,
        stage: Any,
        path: str,
        primitive: DebugPrimitive,
    ) -> None:
        if primitive.kind in _SPHERE_KINDS and primitive.points_world:
            prim = get_or_define_prim(stage, prim_path=path, prim_type="Sphere")
            _set_attr(prim, "radius", float(primitive.radius_m or 0.05))
            position = primitive.points_world[0]
            set_prim_xform_pose(
                prim,
                position=tuple(float(value) for value in position),
            )
        else:
            prim = get_or_define_prim(stage, prim_path=path, prim_type="BasisCurves")
            points = [
                tuple(float(value) for value in point)
                for point in primitive.points_world
            ]
            _set_attr(prim, "type", "linear")
            _set_attr(prim, "curveVertexCounts", [len(points)])
            _set_attr(prim, "points", points)
            _set_attr(prim, "widths", [float(primitive.radius_m or 0.01)])
        _set_attr(
            prim,
            "primvars:displayColor",
            [tuple(float(channel) for channel in primitive.color_rgba[:3])],
        )
        _set_attr(prim, "ias:debug:kind", primitive.kind)
        _set_attr(prim, "ias:debug:label", primitive.label)

    def _edit_context(self, stage: Any) -> Any:
        if not self.use_session_layer:
            return nullcontext()
        try:
            from pxr import Usd  # type: ignore
        except ImportError:
            return nullcontext()
        get_session = getattr(stage, "GetSessionLayer", None)
        if not callable(get_session):
            return nullcontext()
        try:
            session = get_session()
            if session is None:
                return nullcontext()
            return Usd.EditContext(stage, session)
        except Exception:
            return nullcontext()
