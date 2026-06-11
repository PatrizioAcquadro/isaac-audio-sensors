"""Lazy USD/fake-stage world-pose resolution for Isaac audio snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    add,
    as_quaternion_xyzw,
    as_vector3,
    normalize_quaternion,
    quaternion_multiply,
    rotate_vector_by_quaternion,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class StagePose:
    """Resolved world-frame pose for one USD or USD-like prim."""

    prim_path: str
    position_world: Vector3
    orientation_world_quat: Quaternion | None
    provenance: str
    time_code: Any | None = None


class IsaacStagePoseResolver:
    """Resolve live world poses from real USD APIs or duck-typed test stages."""

    def __init__(
        self,
        stage: Any,
        *,
        time_code: Any | None = None,
        prims: tuple[Any, ...] | None = None,
    ) -> None:
        if stage is None or not hasattr(stage, "Traverse"):
            raise ValueError("stage must provide a Traverse method.")
        self.stage = stage
        self.time_code = time_code
        self.prims = tuple(stage.Traverse()) if prims is None else tuple(prims)
        self.prims_by_path = {_prim_path(prim): prim for prim in self.prims}

    def resolve_world_pose(
        self,
        prim_or_path: Any,
        *,
        field_name: str | None = None,
    ) -> StagePose:
        """Resolve a prim's world pose at this resolver's time code."""

        prim = self.prim(prim_or_path)
        path = _prim_path(prim)
        field = field_name or path
        attrs = self.attrs(prim)
        has_world_attr = "ias:position_world" in attrs
        has_xform_stack = self.has_xform_stack(prim)
        if _has_pxr_usd_geom() and (has_xform_stack or not has_world_attr):
            try:
                return _usd_world_pose(prim, time_code=self.time_code)
            except Exception as exc:
                if not has_world_attr and not has_xform_stack:
                    raise ValueError(
                        f"{field!r} world pose could not be computed from USD APIs: "
                        f"{exc}"
                    ) from exc
        stack_pose = self._fallback_xform_stack_pose(prim)
        if stack_pose is not None:
            return stack_pose
        if has_world_attr:
            return StagePose(
                prim_path=path,
                position_world=_required_vec3_attr(
                    attrs,
                    ("ias:position_world",),
                    field_name=field,
                ),
                orientation_world_quat=_quat_attr(
                    attrs,
                    ("ias:orientation_world_quat", "xformOp:orient"),
                    default=None,
                ),
                provenance="ias:position_world",
                time_code=self.time_code,
            )
        raise ValueError(
            f"{field!r} is missing a computable transform. Expected a USD "
            "Xformable transform stack, ias:position_world, or xformOp:translate."
        )

    def attrs(self, prim_or_path: Any) -> dict[str, Any]:
        """Return current attributes, resolving fake and USD time samples."""

        prim = self.prim(prim_or_path)
        if hasattr(prim, "attributes"):
            return {
                str(key): _value_at_time(value, self.time_code)
                for key, value in dict(prim.attributes).items()
            }
        attrs: dict[str, Any] = {}
        if hasattr(prim, "GetAttributes"):
            for attr in prim.GetAttributes():
                if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                    attrs[str(attr.GetName())] = _usd_attr_get(attr, self.time_code)
        return attrs

    def prim(self, prim_or_path: Any) -> Any:
        """Resolve a prim object or absolute prim path."""

        if isinstance(prim_or_path, str):
            prim = self.prims_by_path.get(prim_or_path)
            if prim is None:
                raise ValueError(f"No prim found at {prim_or_path!r}.")
            return prim
        return prim_or_path

    def has_xform_stack(self, prim_or_path: Any) -> bool:
        """Return whether the prim or one of its ancestors has xform ops."""

        prim = self.prim(prim_or_path)
        for ancestor_path in _ancestor_paths(_prim_path(prim)):
            ancestor = self.prims_by_path.get(ancestor_path)
            if ancestor is None:
                continue
            if _has_xform_attrs(self.attrs(ancestor)):
                return True
        return False

    def _fallback_xform_stack_pose(self, prim: Any) -> StagePose | None:
        path = _prim_path(prim)
        position = (0.0, 0.0, 0.0)
        orientation = (0.0, 0.0, 0.0, 1.0)
        found_transform = False
        for ancestor_path in _ancestor_paths(path):
            ancestor = self.prims_by_path.get(ancestor_path)
            if ancestor is None:
                continue
            attrs = self.attrs(ancestor)
            local_position = _optional_vec3_attr(attrs, ("xformOp:translate",))
            local_orientation = _quat_attr(attrs, ("xformOp:orient",), default=None)
            if local_position is None and local_orientation is None:
                continue
            found_transform = True
            if local_position is not None:
                position = add(
                    position,
                    rotate_vector_by_quaternion(local_position, orientation),
                )
            if local_orientation is not None:
                orientation = normalize_quaternion(
                    quaternion_multiply(orientation, local_orientation)
                )
        if not found_transform:
            return None
        return StagePose(
            prim_path=path,
            position_world=position,
            orientation_world_quat=orientation,
            provenance="xformOp:stack",
            time_code=self.time_code,
        )


def resolve_world_pose(
    stage: Any,
    prim: Any,
    *,
    time_code: Any | None = None,
) -> StagePose:
    """Resolve one prim's live world pose from a USD-like stage."""

    return IsaacStagePoseResolver(stage, time_code=time_code).resolve_world_pose(prim)


def diagnostic_time_code(time_code: Any | None) -> Any | None:
    """Return a JSON-friendly time-code diagnostic value."""

    if time_code is None:
        return None
    if isinstance(time_code, (str, int, float)):
        return time_code
    if hasattr(time_code, "GetValue"):
        try:
            return float(time_code.GetValue())
        except Exception:
            return str(time_code)
    return str(time_code)


def prim_path(prim: Any) -> str:
    """Return a prim path for real or fake prims."""

    return _prim_path(prim)


def prim_type_name(prim: Any) -> str:
    """Return a prim type name for real or fake prims."""

    return _prim_type_name(prim)


def stage_id(stage: Any) -> str:
    """Return a stable stage identifier for diagnostics."""

    if hasattr(stage, "GetRootLayer"):
        root_layer = stage.GetRootLayer()
        identifier = getattr(root_layer, "identifier", None)
        if identifier:
            return str(identifier)
    identifier = getattr(stage, "identifier", None)
    return str(identifier or "isaac_stage")


def vec3_from_any(value: Any) -> Vector3:
    """Coerce a USD/fake vector value into a core 3-vector."""

    return _vec3_from_any(value)


def quat_from_any(value: Any) -> Quaternion:
    """Coerce a USD/fake quaternion into core ``(x, y, z, w)`` order."""

    return _quat_from_any(value)


def optional_vec3_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Vector3 | None:
    """Return the first present vector attribute."""

    return _optional_vec3_attr(attrs, keys)


def quat_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: Quaternion | None,
) -> Quaternion | None:
    """Return the first present quaternion attribute."""

    return _quat_attr(attrs, keys, default=default)


def _usd_world_pose(prim: Any, *, time_code: Any | None) -> StagePose:
    from pxr import UsdGeom  # type: ignore

    usd_time = _usd_time_code(time_code)
    if hasattr(UsdGeom, "XformCache"):
        matrix = UsdGeom.XformCache(usd_time).GetLocalToWorldTransform(prim)
        provenance = "usd:XformCache"
    else:
        matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(usd_time)
        provenance = "usd:ComputeLocalToWorldTransform"
    translation = matrix.ExtractTranslation()
    return StagePose(
        prim_path=_prim_path(prim),
        position_world=_vec3_from_any(translation),
        orientation_world_quat=_quat_from_matrix(matrix),
        provenance=provenance,
        time_code=time_code,
    )


def _usd_time_code(time_code: Any | None) -> Any:
    from pxr import Usd  # type: ignore

    if time_code is None:
        return Usd.TimeCode.Default()
    if hasattr(time_code, "GetValue"):
        return time_code
    if isinstance(time_code, str) and time_code.lower() == "default":
        return Usd.TimeCode.Default()
    try:
        return Usd.TimeCode(float(time_code))
    except TypeError:
        return float(time_code)


def _usd_attr_get(attr: Any, time_code: Any | None) -> Any:
    if time_code is None:
        try:
            return attr.Get()
        except TypeError:
            return attr.Get(_usd_time_code(None))
    try:
        return attr.Get(_usd_time_code(time_code))
    except TypeError:
        return attr.Get(time_code)


def _value_at_time(value: Any, time_code: Any | None) -> Any:
    if hasattr(value, "Get") and callable(value.Get):
        try:
            return value.Get(time_code)
        except TypeError:
            return value.Get()
    if isinstance(value, Mapping):
        if time_code in value:
            return value[time_code]
        if time_code is not None:
            try:
                numeric_time = float(time_code)
            except (TypeError, ValueError):
                numeric_time = None
            if numeric_time in value:
                return value[numeric_time]
            for sample_time, sample_value in value.items():
                if (
                    isinstance(sample_time, (int, float))
                    and numeric_time is not None
                    and abs(float(sample_time) - numeric_time) <= 1e-5
                ):
                    return sample_value
        if "default" in value:
            return value["default"]
    return value


def _required_vec3_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    field_name: str,
) -> Vector3:
    value = _optional_vec3_attr(attrs, keys)
    if value is not None:
        return value
    expected = " or ".join(keys)
    raise ValueError(f"{field_name!r} is missing required transform {expected}.")


def _optional_vec3_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Vector3 | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return _vec3_from_any(attrs[key])
    return None


def _vec3_from_any(value: Any) -> Vector3:
    if hasattr(value, "GetLength") and callable(value.GetLength):
        return as_vector3((value[0], value[1], value[2]), "Vector3")
    return as_vector3(value, "Vector3")


def _quat_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: Quaternion | None,
) -> Quaternion | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return _quat_from_any(attrs[key])
    return default


def _quat_from_any(value: Any) -> Quaternion:
    if hasattr(value, "GetImaginary") and hasattr(value, "GetReal"):
        x, y, z = value.GetImaginary()
        return as_quaternion_xyzw(
            (float(x), float(y), float(z), float(value.GetReal())),
            "Quaternion",
        )
    return as_quaternion_xyzw(value, "Quaternion")


def _quat_from_matrix(matrix: Any) -> Quaternion:
    if hasattr(matrix, "ExtractRotationQuat"):
        try:
            return _quat_from_any(matrix.ExtractRotationQuat())
        except Exception:
            pass
    if hasattr(matrix, "ExtractRotation"):
        try:
            rotation = matrix.ExtractRotation()
            if hasattr(rotation, "GetQuat"):
                return _quat_from_any(rotation.GetQuat())
        except Exception:
            pass
    if hasattr(matrix, "ExtractRotationMatrix"):
        try:
            return _quat_from_matrix_entries(matrix.ExtractRotationMatrix())
        except Exception:
            pass
    return _quat_from_matrix_entries(matrix)


def _quat_from_matrix_entries(matrix: Any) -> Quaternion:
    try:
        m00 = float(matrix[0][0])
        m01 = float(matrix[0][1])
        m02 = float(matrix[0][2])
        m10 = float(matrix[1][0])
        m11 = float(matrix[1][1])
        m12 = float(matrix[1][2])
        m20 = float(matrix[2][0])
        m21 = float(matrix[2][1])
        m22 = float(matrix[2][2])
    except Exception as exc:
        raise ValueError(
            "Could not extract rotation quaternion from USD matrix."
        ) from exc

    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m21 - m12) / scale
        y = (m02 - m20) / scale
        z = (m10 - m01) / scale
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / scale
        x = 0.25 * scale
        y = (m01 + m10) / scale
        z = (m02 + m20) / scale
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / scale
        x = (m01 + m10) / scale
        y = 0.25 * scale
        z = (m12 + m21) / scale
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / scale
        x = (m02 + m20) / scale
        y = (m12 + m21) / scale
        z = 0.25 * scale
    return as_quaternion_xyzw((x, y, z, w), "USD matrix quaternion")


def _has_pxr_usd_geom() -> bool:
    try:
        from pxr import UsdGeom  # type: ignore  # noqa: F401

        return True
    except ImportError:
        return False


def _has_xform_attrs(attrs: Mapping[str, Any]) -> bool:
    return any(key == "xformOpOrder" or key.startswith("xformOp:") for key in attrs)


def _ancestor_paths(path: str) -> tuple[str, ...]:
    parts = [part for part in path.strip("/").split("/") if part]
    return tuple("/" + "/".join(parts[:index]) for index in range(1, len(parts) + 1))


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))
