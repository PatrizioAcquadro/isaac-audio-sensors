"""USD sound/listener authoring helpers."""

from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import isaac_audio_sensors.isaac.pose_resolver as usd
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthoredPrimRecord:
    """Summary of a prim authored or configured by the helper."""

    prim_path: str
    prim_type: str
    attributes: dict[str, object]


def require_isaac_usd() -> tuple[Any, Any]:
    """Import USD/Omniverse audio modules or raise a clear optional error."""

    try:
        from pxr import Sdf, Usd  # type: ignore
    except ImportError as exc:
        raise IsaacIntegrationUnavailable(
            "Isaac/Omniverse USD modules are unavailable. Run this helper "
            "inside an Isaac Sim Python environment with pxr/omni modules."
        ) from exc
    return Sdf, Usd


def create_sound_prim(
    stage: Any,
    *,
    prim_path: str,
    audio_asset_path: str,
    spatial: bool = True,
    loop: bool = False,
    loop_count: int | None = None,
    start_time_s: float = 0.0,
    duration_s: float | None = None,
    gain_db: float = 0.0,
) -> AuthoredPrimRecord:
    """Create or configure a USD sound prim through stage APIs."""

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    if audio_asset_path.strip() == "":
        raise ValueError("audio_asset_path must be non-empty.")
    if type(loop) is not bool:
        raise ValueError("loop must be a boolean.")
    if loop and loop_count is not None:
        raise ValueError("Provide loop=True or loop_count, not both.")
    resolved_loop_count = -1 if loop else 0
    if loop_count is not None:
        if type(loop_count) is not int or loop_count < -1:
            raise ValueError("loop_count must be -1 or a non-negative integer.")
        resolved_loop_count = loop_count
    start_s = _finite_float(start_time_s, "start_time_s")
    if start_s < 0.0:
        raise ValueError("start_time_s must be non-negative for Kit Audio.")
    duration = None
    if duration_s is not None:
        duration = _finite_float(duration_s, "duration_s")
        if duration <= 0.0:
            raise ValueError("duration_s must be positive when provided.")
    resolved_gain_db = _finite_float(gain_db, "gain_db")
    linear_gain = _db_to_linear_gain(resolved_gain_db)
    time_codes_per_second = _stage_time_codes_per_second(stage)
    start_time_code = start_s * time_codes_per_second
    end_time_code = (
        None if duration is None else (start_s + duration) * time_codes_per_second
    )

    prim = _define_or_retype_prim(
        stage,
        prim_path=prim_path,
        prim_type="OmniSound",
    )
    clear_prim_attrs(prim, ("spatial", "loop"))
    attributes: dict[str, object] = {
        "ias:audio_asset_path": audio_asset_path,
        "auralMode": "spatial" if spatial else "nonSpatial",
        "loopCount": resolved_loop_count,
        "startTime": start_time_code,
        "gain": linear_gain,
    }
    if audio_asset_path.startswith("generated://"):
        clear_prim_attrs(prim, ("filePath",))
    else:
        attributes["filePath"] = audio_asset_path
    if end_time_code is None:
        clear_prim_attrs(prim, ("endTime",))
    else:
        attributes["endTime"] = end_time_code
    for name, value in attributes.items():
        _set_attr(prim, name, value)
    return AuthoredPrimRecord(
        prim_path=prim_path,
        prim_type="OmniSound",
        attributes=attributes,
    )


def attach_sound_source_attrs(
    prim: Any,
    *,
    source_id: str,
    class_label: str,
    position_world: tuple[float, float, float] | None = None,
    orientation_world_quat: tuple[float, float, float, float] | None = None,
    audio_asset_path: str | None = None,
    start_time_s: float = 0.0,
    duration_s: float | None = None,
    gain_db: float = 0.0,
    directivity: str = "omni",
) -> dict[str, object]:
    """Attach ``isaac_audio_sensors`` metadata to a sound source prim."""

    attrs: dict[str, object] = {
        "ias:source_id": source_id,
        "ias:class_label": class_label,
        "ias:start_time_s": float(start_time_s),
        "ias:gain_db": float(gain_db),
        "ias:directivity": directivity,
    }
    if audio_asset_path is not None:
        attrs["ias:audio_asset_path"] = audio_asset_path
    if position_world is not None:
        attrs["ias:position_world"] = position_world
    if orientation_world_quat is not None:
        attrs["ias:orientation_world_quat"] = orientation_world_quat
    if duration_s is not None:
        attrs["ias:duration_s"] = float(duration_s)
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    set_prim_xform_pose(
        prim,
        position=position_world,
        orientation=orientation_world_quat,
    )
    return attrs


def attach_source_object_binding_attrs(
    prim: Any,
    *,
    object_prim_path: str,
    local_offset_m: tuple[float, float, float],
) -> dict[str, object]:
    """Attach object-binding metadata and a local source offset to a source prim."""

    if object_prim_path.strip() == "":
        raise ValueError("object_prim_path must be non-empty.")
    offset = tuple(float(component) for component in local_offset_m)
    attrs: dict[str, object] = {
        "ias:attached_object_prim_path": object_prim_path,
        "ias:source_local_offset_m": offset,
    }
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    set_prim_xform_pose(prim, position=offset)
    return attrs


def clear_source_object_binding_attrs(prim: Any) -> None:
    """Remove object-binding metadata from a source prim when it is detached."""

    clear_prim_attrs(
        prim,
        (
            "ias:attached_object_prim_path",
            "ias:source_local_offset_m",
        ),
    )


def attach_array_object_binding_attrs(
    prim: Any,
    *,
    object_prim_path: str,
    local_offset_m: tuple[float, float, float],
    local_orientation_quat: tuple[float, float, float, float] | None = None,
) -> dict[str, object]:
    """Attach object-binding metadata and a local mount pose to an array prim."""

    if object_prim_path.strip() == "":
        raise ValueError("object_prim_path must be non-empty.")
    offset = tuple(float(component) for component in local_offset_m)
    attrs: dict[str, object] = {
        "ias:attached_object_prim_path": object_prim_path,
        "ias:array_local_offset_m": offset,
    }
    orientation: tuple[float, float, float, float] | None = None
    if local_orientation_quat is not None:
        orientation = tuple(float(component) for component in local_orientation_quat)
        attrs["ias:array_local_orientation_quat"] = orientation
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    set_prim_xform_pose(prim, position=offset, orientation=orientation)
    return attrs


def clear_array_object_binding_attrs(prim: Any) -> None:
    """Remove object-binding metadata from an array prim when it is detached."""

    clear_prim_attrs(
        prim,
        (
            "ias:attached_object_prim_path",
            "ias:array_local_offset_m",
            "ias:array_local_orientation_quat",
        ),
    )


def clear_prim_attrs(prim: Any, names: tuple[str, ...]) -> None:
    """Remove authored attributes when present."""

    if hasattr(prim, "attributes"):
        for name in names:
            prim.attributes.pop(name, None)
        return
    for name in names:
        if hasattr(prim, "RemoveProperty"):
            with suppress(Exception):
                prim.RemoveProperty(name)


def set_prim_xform_pose(
    prim: Any,
    *,
    position: tuple[float, float, float] | None = None,
    orientation: tuple[float, float, float, float] | None = None,
) -> None:
    """Set a prim-local transform."""

    if position is not None and not _set_usd_translate_op(prim, position):
        _set_attr(prim, "xformOp:translate", position)
    if orientation is not None and not _set_usd_orient_op(prim, orientation):
        _set_attr(prim, "xformOp:orient", orientation)


def move_prim_to_path(
    stage: Any,
    *,
    source_path: str,
    dest_path: str,
    prim_type: str = "Xform",
    include_children: bool = False,
) -> Any:
    """Move a simple prim to a new path, preserving authored attributes.

    The helper copies attributes and then removes the old prim when the stage API
    exposes a removal path. Descendant prims are only carried along when
    ``include_children`` is set; the default keeps the single-prim behavior.
    """

    _require_stage(stage)
    if source_path == dest_path:
        return get_or_define_prim(stage, prim_path=dest_path, prim_type=prim_type)
    source = _existing_prim(stage, source_path)
    effective_type = usd.prim_type_name(source) if source is not None else prim_type
    dest = get_or_define_prim(
        stage,
        prim_path=dest_path,
        prim_type=effective_type or prim_type,
    )
    if source is not None:
        _copy_prim_attrs(source, dest)
        if include_children:
            _move_descendant_prims(
                stage,
                source_path=source_path,
                dest_path=dest_path,
            )
        remove_prim(stage, source_path)
    return dest


def _move_descendant_prims(stage: Any, *, source_path: str, dest_path: str) -> None:
    if not hasattr(stage, "Traverse"):
        return
    prefix = source_path.rstrip("/") + "/"
    descendants = sorted(
        (
            (path, prim)
            for prim in stage.Traverse()
            for path in (usd.prim_path(prim),)
            if path.startswith(prefix)
        ),
        key=lambda item: item[0],
    )
    for path, prim in descendants:
        new_path = f"{dest_path.rstrip('/')}/{path[len(prefix) :]}"
        moved = get_or_define_prim(
            stage,
            prim_path=new_path,
            prim_type=usd.prim_type_name(prim) or "Xform",
        )
        _copy_prim_attrs(prim, moved)
    for path, _prim in reversed(descendants):
        remove_prim(stage, path)


def create_listener_prim(
    stage: Any,
    *,
    prim_path: str,
    array_id: str,
    orientation_from_view: bool = False,
) -> AuthoredPrimRecord:
    """Create or configure a USD listener prim through stage APIs."""

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    if array_id.strip() == "":
        raise ValueError("array_id must be non-empty.")
    prim = _define_or_retype_prim(
        stage,
        prim_path=prim_path,
        prim_type="OmniListener",
    )
    attributes: dict[str, object] = {
        "ias:array_id": array_id,
        "orientationFromView": bool(orientation_from_view),
    }
    for name, value in attributes.items():
        _set_attr(prim, name, value)
    return AuthoredPrimRecord(
        prim_path=prim_path,
        prim_type="OmniListener",
        attributes=attributes,
    )


def attach_microphone_array_attrs(
    prim: Any,
    *,
    array_id: str,
    sample_rate_hz: int,
    coordinate_convention: str,
    layout_name: str,
    position_world: tuple[float, float, float] | None = None,
    orientation_world_quat: tuple[float, float, float, float] | None = None,
    microphone_relative_offsets_m: tuple[tuple[float, float, float], ...] | None = None,
    microphone_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Attach namespaced microphone-array metadata to an existing prim."""

    attrs: dict[str, object] = {
        "ias:array_id": array_id,
        "ias:sample_rate_hz": int(sample_rate_hz),
        "ias:coordinate_convention": coordinate_convention,
        "ias:layout_name": layout_name,
    }
    if position_world is not None:
        attrs["ias:position_world"] = position_world
    if orientation_world_quat is not None:
        attrs["ias:orientation_world_quat"] = orientation_world_quat
    if microphone_relative_offsets_m is not None:
        attrs["ias:microphone_relative_offsets_m"] = tuple(
            tuple(float(component) for component in offset)
            for offset in microphone_relative_offsets_m
        )
    if microphone_ids is not None:
        attrs["ias:microphone_ids"] = tuple(str(mic_id) for mic_id in microphone_ids)
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    set_prim_xform_pose(
        prim,
        position=position_world,
        orientation=orientation_world_quat,
    )
    return attrs


def attach_microphone_attrs(
    prim: Any,
    *,
    mic_id: str,
    relative_position_m: tuple[float, float, float],
    relative_orientation_quat: tuple[float, float, float, float] | None = None,
    gain_db: float = 0.0,
    self_noise_db: float | None = None,
) -> dict[str, object]:
    """Attach one microphone's metadata to an array child prim."""

    attrs: dict[str, object] = {
        "ias:microphone_id": mic_id,
        "ias:relative_position_m": relative_position_m,
        "ias:gain_db": float(gain_db),
    }
    if relative_orientation_quat is not None:
        attrs["ias:relative_orientation_quat"] = relative_orientation_quat
    if self_noise_db is not None:
        attrs["ias:self_noise_db"] = float(self_noise_db)
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    set_prim_xform_pose(
        prim,
        position=relative_position_m,
        orientation=relative_orientation_quat,
    )
    return attrs


def remove_prim(stage: Any, prim_path: str) -> None:
    """Remove a prim when supported by the stage."""

    if hasattr(stage, "RemovePrim"):
        try:
            stage.RemovePrim(usd.usd_path(prim_path))
            return
        except Exception:
            try:
                stage.RemovePrim(prim_path)
                return
            except Exception:
                pass
    prims = getattr(stage, "_prims", None)
    if isinstance(prims, list):
        stage._prims = [prim for prim in prims if usd.prim_path(prim) != prim_path]


def get_or_define_prim(stage: Any, *, prim_path: str, prim_type: str) -> Any:
    """Return an existing prim or define it on a USD-like stage."""

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    prim = _existing_prim(stage, prim_path)
    if prim is not None:
        return prim
    return stage.DefinePrim(prim_path, prim_type)


def _define_or_retype_prim(stage: Any, *, prim_path: str, prim_type: str) -> Any:
    """Define one typed prim, updating an existing prim's schema type."""

    _require_stage(stage)
    prim = _existing_prim(stage, prim_path)
    if prim is None:
        return stage.DefinePrim(prim_path, prim_type)
    if usd.prim_type_name(prim) == prim_type:
        return prim
    set_type_name = getattr(prim, "SetTypeName", None)
    if callable(set_type_name):
        set_type_name(prim_type)
        return prim
    if hasattr(prim, "type_name"):
        prim.type_name = prim_type
        return prim
    return stage.DefinePrim(prim_path, prim_type)


def _copy_prim_attrs(source: Any, dest: Any) -> None:
    if hasattr(source, "attributes") and hasattr(dest, "attributes"):
        dest.attributes.update(dict(source.attributes))
        return
    if not hasattr(source, "GetAttributes") or not hasattr(dest, "CreateAttribute"):
        return
    for attr in source.GetAttributes():
        try:
            name = attr.GetName()
            value = attr.Get()
            type_name = attr.GetTypeName() if hasattr(attr, "GetTypeName") else None
            custom = attr.IsCustom() if hasattr(attr, "IsCustom") else True
            dest_attr = dest.CreateAttribute(name, type_name, custom=custom)
            if hasattr(dest_attr, "Set"):
                dest_attr.Set(value)
        except Exception:
            continue


def _require_stage(stage: Any) -> None:
    if stage is None or not hasattr(stage, "DefinePrim"):
        raise ValueError("stage must provide a DefinePrim method.")


def _existing_prim(stage: Any, prim_path: str) -> Any | None:
    if hasattr(stage, "GetPrimAtPath"):
        for candidate_path in (usd.usd_path(prim_path), prim_path):
            try:
                prim = stage.GetPrimAtPath(candidate_path)
            except TypeError:
                continue
            if _prim_is_valid(prim):
                return prim
    if hasattr(stage, "Traverse"):
        for prim in stage.Traverse():
            path = getattr(prim, "path", None)
            if path is None and hasattr(prim, "GetPath"):
                path = prim.GetPath()
            if str(path) == prim_path:
                return prim
    return None


def _prim_is_valid(prim: Any) -> bool:
    if prim is None:
        return False
    if hasattr(prim, "IsValid"):
        try:
            return bool(prim.IsValid())
        except Exception:
            return False
    return True


def _set_attr(prim: Any, name: str, value: object) -> None:
    if hasattr(prim, "CreateAttribute"):
        attr = prim.CreateAttribute(
            name,
            _usd_value_type_name(value, attr_name=name),
            custom=True,
        )
        if hasattr(attr, "Set"):
            attr.Set(_usd_value(value, attr_name=name))
            return
    if hasattr(prim, "attributes"):
        prim.attributes[name] = value
        return
    setattr(prim, name.replace(":", "_"), value)


def _set_usd_translate_op(
    prim: Any,
    position: tuple[float, float, float],
) -> bool:
    try:
        from pxr import Gf, UsdGeom  # type: ignore
    except ImportError:
        return False
    if not hasattr(prim, "IsValid"):
        return False
    try:
        value = Gf.Vec3d(*(float(component) for component in position))
        api = UsdGeom.XformCommonAPI(prim)
        if hasattr(api, "SetTranslate") and api.SetTranslate(value):
            return True
        xformable = UsdGeom.Xformable(prim)
        for op in xformable.GetOrderedXformOps():
            if hasattr(op, "GetOpName") and op.GetOpName() == "xformOp:translate":
                op.Set(value)
                return True
        xformable.AddTranslateOp().Set(value)
        return True
    except Exception:
        return False


def _set_usd_orient_op(
    prim: Any,
    orientation: tuple[float, float, float, float],
) -> bool:
    try:
        from pxr import Gf, UsdGeom  # type: ignore
    except ImportError:
        return False
    if not hasattr(prim, "IsValid"):
        return False
    try:
        x, y, z, w = (float(component) for component in orientation)
        value = Gf.Quatf(w, Gf.Vec3f(x, y, z))
        xformable = UsdGeom.Xformable(prim)
        for op in xformable.GetOrderedXformOps():
            if hasattr(op, "GetOpName") and op.GetOpName() == "xformOp:orient":
                op.Set(value)
                return True
        xformable.AddOrientOp().Set(value)
        return True
    except Exception:
        return False


def _usd_value_type_name(value: object, *, attr_name: str) -> Any:
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return None
    if attr_name in {"filePath", "inputs:file"}:
        return Sdf.ValueTypeNames.Asset
    if attr_name == "auralMode":
        return Sdf.ValueTypeNames.Token
    if attr_name in {"startTime", "endTime"}:
        return Sdf.ValueTypeNames.TimeCode
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int) and not isinstance(value, bool):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    if isinstance(value, str):
        return Sdf.ValueTypeNames.String
    if _is_sequence_of_numeric_tuples(value, 3):
        return Sdf.ValueTypeNames.Double3Array
    if _is_sequence_of_strings(value):
        return Sdf.ValueTypeNames.StringArray
    if _is_numeric_tuple(value, 3):
        return Sdf.ValueTypeNames.Double3
    if _is_numeric_tuple(value, 4):
        return Sdf.ValueTypeNames.Quatd
    return Sdf.ValueTypeNames.String


def _usd_value(value: object, *, attr_name: str) -> object:
    try:
        from pxr import Gf, Sdf  # type: ignore
    except ImportError:
        return value
    if attr_name in {"filePath", "inputs:file"} and isinstance(value, str):
        return Sdf.AssetPath(value)
    if attr_name in {"startTime", "endTime"}:
        return Sdf.TimeCode(float(value))
    if _is_sequence_of_numeric_tuples(value, 3):
        return [Gf.Vec3d(float(x), float(y), float(z)) for x, y, z in value]
    if _is_sequence_of_strings(value):
        return [str(item) for item in value]
    if _is_numeric_tuple(value, 3):
        x, y, z = value
        return Gf.Vec3d(float(x), float(y), float(z))
    if _is_numeric_tuple(value, 4):
        x, y, z, w = value
        return Gf.Quatd(float(w), Gf.Vec3d(float(x), float(y), float(z)))
    return value


def _is_numeric_tuple(value: object, length: int) -> bool:
    if not isinstance(value, tuple) or len(value) != length:
        return False
    return all(isinstance(component, (int, float)) for component in value)


def _is_sequence_of_numeric_tuples(value: object, length: int) -> bool:
    if not isinstance(value, tuple):
        return False
    return all(_is_numeric_tuple(item, length) for item in value)


def _is_sequence_of_strings(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    return all(isinstance(item, str) for item in value)


def _stage_time_codes_per_second(stage: Any) -> float:
    """Return stage timecodes per second, with a duck-stage seconds fallback."""

    getter = getattr(stage, "GetTimeCodesPerSecond", None)
    if not callable(getter):
        return 1.0
    value = float(getter())
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("stage timeCodesPerSecond must be positive and finite.")
    return value


def _time_code_to_seconds(stage: Any, value: object) -> float:
    """Convert one USD timecode value to seconds for the SDK contract."""

    getter = getattr(value, "GetValue", None)
    resolved = getter() if callable(getter) else value
    seconds = float(resolved) / _stage_time_codes_per_second(stage)
    if not math.isfinite(seconds):
        raise ValueError("Native Kit Audio timecode must be finite.")
    return seconds


def _db_to_linear_gain(gain_db: float) -> float:
    """Convert the SDK's pressure-like dB gain to Kit's linear scale."""

    try:
        gain = 10.0 ** (float(gain_db) / 20.0)
    except OverflowError as exc:
        raise ValueError("gain_db is too large for Kit Audio linear gain.") from exc
    if not math.isfinite(gain) or gain <= 0.0:
        raise ValueError("gain_db must map to a positive finite Kit Audio gain.")
    return gain


def _linear_gain_to_db(gain: object) -> float:
    """Convert positive Kit linear gain to the SDK's finite dB contract."""

    value = float(gain)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(
            "Native Kit Audio gain must be positive and finite when "
            "ias:gain_db is absent."
        )
    return 20.0 * math.log10(value)


def _finite_float(value: object, field_name: str) -> float:
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{field_name} must be finite.")
    return resolved
