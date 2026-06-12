"""World-aligned bounding boxes and room tags from USD or duck-typed prims.

Shared by the Isaac Lab stage binding and the Isaac Sim extension, so it
lives outside both packages and keeps ``core`` USD-free. Real pxr prims use
``UsdGeom.BBoxCache``; fake prims (live-smoke fallback stages, unit tests)
provide explicit ``ias:room_min_world``/``ias:room_max_world`` attributes or
``ias:room_size_m`` centered on the prim's world position.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from isaac_audio_sensors.core.math_utils import Vector3, as_vector3

ROOM_MIN_WORLD_ATTR = "ias:room_min_world"
ROOM_MAX_WORLD_ATTR = "ias:room_max_world"
ROOM_SIZE_ATTR = "ias:room_size_m"
ABSORPTION_ATTR = "ias:absorption"
MATERIAL_ATTR = "ias:material"
_SEMANTIC_DATA_SUFFIX = ":semanticData"

# Broadband energy-absorption coefficients for common wall labels, used when
# a room prim carries a material/semantic tag instead of an explicit
# ias:absorption value.
DEFAULT_SEMANTIC_ABSORPTION: tuple[tuple[str, float], ...] = (
    ("concrete", 0.05),
    ("brick", 0.04),
    ("glass", 0.05),
    ("metal", 0.05),
    ("plaster", 0.10),
    ("drywall", 0.10),
    ("wood", 0.10),
    ("fabric", 0.40),
    ("curtain", 0.40),
    ("carpet", 0.30),
    ("acoustic_panel", 0.70),
    ("foam", 0.70),
)


def world_aligned_bbox(
    prim: Any,
    *,
    prim_path: str,
    time_code: Any | None = None,
) -> tuple[Vector3, Vector3]:
    """Return the (min, max) world-aligned bounding box of a prim."""

    pxr_bbox = _pxr_world_aligned_bbox(prim, time_code=time_code)
    if pxr_bbox is not None:
        return pxr_bbox
    attrs = prim_attributes(prim, time_code=time_code)
    minimum = _optional_vec3(attrs.get(ROOM_MIN_WORLD_ATTR))
    maximum = _optional_vec3(attrs.get(ROOM_MAX_WORLD_ATTR))
    if minimum is not None and maximum is not None:
        return minimum, maximum
    size = _optional_vec3(attrs.get(ROOM_SIZE_ATTR))
    center = _optional_vec3(
        attrs.get("ias:position_world", attrs.get("xformOp:translate"))
    )
    if size is not None and center is not None:
        half = tuple(abs(component) / 2.0 for component in size)
        return (
            tuple(center[axis] - half[axis] for axis in range(3)),
            tuple(center[axis] + half[axis] for axis in range(3)),
        )
    raise ValueError(
        f"Room prim {prim_path!r} has no computable world-aligned bounding "
        f"box. Expected USD geometry (UsdGeom.BBoxCache), "
        f"{ROOM_MIN_WORLD_ATTR}/{ROOM_MAX_WORLD_ATTR} attributes, or "
        f"{ROOM_SIZE_ATTR} with a world position."
    )


def resolve_room_absorption(
    prim: Any,
    *,
    semantic_absorption: Mapping[str, float],
    default: float | dict[str, float],
    time_code: Any | None = None,
) -> tuple[float | dict[str, float], str]:
    """Resolve a room's absorption coefficient and its provenance.

    Precedence: explicit ``ias:absorption`` attribute on the prim, then a
    material/semantic label looked up (case-insensitively) in
    ``semantic_absorption``, then the configured default.
    """

    attrs = prim_attributes(prim, time_code=time_code)
    explicit = attrs.get(ABSORPTION_ATTR)
    if explicit is not None:
        return float(explicit), f"attr:{ABSORPTION_ATTR}"
    table = {
        str(label).lower(): float(value)
        for label, value in dict(semantic_absorption).items()
    }
    for label in _prim_labels(attrs):
        coefficient = table.get(label.lower())
        if coefficient is not None:
            return coefficient, f"semantic:{label}"
    return default, "config"


def prim_attributes(prim: Any, *, time_code: Any | None = None) -> dict[str, Any]:
    """Read prim attributes from fake (dict-backed) or real USD prims."""

    if hasattr(prim, "attributes"):
        return {
            str(key): _value_of(value, time_code)
            for key, value in dict(prim.attributes).items()
        }
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = _value_of(attr, time_code)
    return attrs


def _prim_labels(attrs: Mapping[str, Any]) -> tuple[str, ...]:
    labels: list[str] = []
    material = attrs.get(MATERIAL_ATTR)
    if material is not None and str(material).strip():
        labels.append(str(material).strip())
    for key, value in attrs.items():
        if (
            key.endswith(_SEMANTIC_DATA_SUFFIX)
            and value is not None
            and str(value).strip()
        ):
            labels.append(str(value).strip())
    return tuple(labels)


def _pxr_world_aligned_bbox(
    prim: Any,
    *,
    time_code: Any | None,
) -> tuple[Vector3, Vector3] | None:
    try:
        from pxr import Usd, UsdGeom  # type: ignore
    except ImportError:
        return None
    try:
        cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default()
            if time_code is None
            else Usd.TimeCode(float(time_code)),
            [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
        )
        aligned = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if aligned.IsEmpty():
            return None
        minimum = aligned.GetMin()
        maximum = aligned.GetMax()
    except Exception:
        return None
    return (
        (float(minimum[0]), float(minimum[1]), float(minimum[2])),
        (float(maximum[0]), float(maximum[1]), float(maximum[2])),
    )


def _optional_vec3(value: Any) -> Vector3 | None:
    if value is None:
        return None
    if hasattr(value, "GetLength") and callable(value.GetLength):
        return as_vector3((value[0], value[1], value[2]), "usd_bounds vector")
    return as_vector3(value, "usd_bounds vector")


def _value_of(value: Any, time_code: Any | None) -> Any:
    if hasattr(value, "Get") and callable(value.Get):
        try:
            return value.Get(time_code)
        except TypeError:
            return value.Get()
    return value
