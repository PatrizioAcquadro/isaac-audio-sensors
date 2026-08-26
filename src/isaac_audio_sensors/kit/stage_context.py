"""Stage, prim, and selection helpers shared by the extension GUI."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import Any

from isaac_audio_sensors.isaac.pose_resolver import (
    prim_path,
    prim_type_name,
    quat_from_any,
    usd_path,
    vec3_from_any,
)
from isaac_audio_sensors.isaac.stage_audio import (
    get_or_define_prim,
    set_prim_xform_pose,
)

from .state import (
    CurrentStageContext,
    DiscoveredPrimSummary,
    ExtensionActionError,
    ExtensionUiState,
    _json_ready,
)


def current_omni_stage_context() -> CurrentStageContext:
    """Return the live Omni stage and selected prims through lazy imports."""

    try:
        omni_usd = importlib.import_module("omni.usd")
    except ImportError as exc:
        raise ExtensionActionError(
            "omni.usd is unavailable; load this extension inside Isaac Sim "
            "or pass an explicit stage in tests."
        ) from exc
    if not hasattr(omni_usd, "get_context"):
        raise ExtensionActionError("omni.usd.get_context is unavailable.")
    context = omni_usd.get_context()
    stage = context.get_stage() if hasattr(context, "get_stage") else None
    selected_paths: tuple[str, ...] = ()
    if hasattr(context, "get_selection"):
        selection = context.get_selection()
        if hasattr(selection, "get_selected_prim_paths"):
            selected_paths = _normalize_paths(selection.get_selected_prim_paths())
    return CurrentStageContext(stage=stage, selected_prim_paths=selected_paths)


def _stage_has_prim(stage: Any, path: str) -> bool:
    if not path:
        return False
    if hasattr(stage, "GetPrimAtPath"):
        for candidate_path in (usd_path(path), path):
            try:
                prim = stage.GetPrimAtPath(candidate_path)
            except TypeError:
                continue
            if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
                return True
    if hasattr(stage, "Traverse"):
        return any(prim_path(prim) == path for prim in stage.Traverse())
    return False


def _stage_prim_at_path(stage: Any | None, path: str) -> Any | None:
    if stage is None or not path:
        return None
    if hasattr(stage, "GetPrimAtPath"):
        for candidate_path in (usd_path(path), path):
            try:
                prim = stage.GetPrimAtPath(candidate_path)
            except TypeError:
                continue
            if prim is not None and (not hasattr(prim, "IsValid") or prim.IsValid()):
                return prim
    if hasattr(stage, "Traverse"):
        for prim in stage.Traverse():
            if prim_path(prim) == path:
                return prim
    return None


def _author_position_arg(
    prim: Any,
    *,
    default: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    attrs = _prim_attrs(prim)
    if _prim_has_xform_pose(prim):
        return None
    if "ias:position_world" in attrs:
        try:
            return vec3_from_any(attrs["ias:position_world"])
        except (TypeError, ValueError):
            pass
    return default


def _author_orientation_arg(
    prim: Any,
    *,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    attrs = _prim_attrs(prim)
    if _prim_has_xform_orientation(prim):
        return None
    if "ias:orientation_world_quat" in attrs:
        try:
            return quat_from_any(attrs["ias:orientation_world_quat"])
        except (TypeError, ValueError):
            pass
    return default


def _prim_has_xform_pose(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(key in attrs for key in ("xformOp:translate", "usd_world_position"))


def _prim_has_xform_orientation(prim: Any) -> bool:
    attrs = _prim_attrs(prim)
    return any(key in attrs for key in ("xformOp:orient", "usd_world_orientation"))


def _prim_attrs(prim: Any) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = attr.Get()
    return attrs


def _set_prim_attr(prim: Any, name: str, value: Any) -> None:
    if hasattr(prim, "attributes"):
        prim.attributes[name] = value
        return
    if not hasattr(prim, "CreateAttribute"):
        return
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return
    value_type = getattr(Sdf.ValueTypeNames, "String", None)
    if isinstance(value, bool):
        value_type = getattr(Sdf.ValueTypeNames, "Bool", value_type)
    elif isinstance(value, float):
        value_type = getattr(Sdf.ValueTypeNames, "Double", value_type)
    try:
        attr = prim.CreateAttribute(name, value_type)
        if hasattr(attr, "Set"):
            attr.Set(value)
    except Exception:
        return


def _refresh_applied_profile_binding_snapshot(
    prim: Any,
    state: ExtensionUiState,
    *,
    object_path: str,
    local_offset_m: tuple[float, float, float],
) -> dict[str, object]:
    if not state.applied_source_profile:
        return {}
    profile_id = str(state.applied_source_profile.get("profile_id") or "")
    display_label = str(state.applied_source_profile.get("display_label") or "")
    attrs: dict[str, object] = {}
    if profile_id:
        _set_prim_attr(prim, "ias:sound_profile_id", profile_id)
        attrs["ias:sound_profile_id"] = profile_id
    if display_label:
        _set_prim_attr(prim, "ias:sound_profile_label", display_label)
        attrs["ias:sound_profile_label"] = display_label
    state.applied_source_profile = _json_ready(
        {
            **state.applied_source_profile,
            "source_prim_path": state.source_prim_path,
            "source_id": state.source_id,
            "class_label": state.source_class_label,
            "audio_asset_path": state.audio_asset_path,
            "start_time_s": state.source_start_time_s,
            "duration_s": state.source_duration_s,
            "gain_db": state.source_gain_db,
            "loop_count": state.source_loop_count,
            "directivity": state.source_directivity,
            "source_attached_to_object": True,
            "object_prim_path": object_path,
            "object_label": state.object_label,
            "attached_object_prim_path": object_path,
            "source_local_offset_m": local_offset_m,
        }
    )
    attrs["applied_source_profile"] = state.applied_source_profile
    return attrs


def _object_label_candidates_for_path(stage: Any | None, path: str) -> tuple[str, ...]:
    if not path:
        return ()
    labels: list[str] = []
    prim = _stage_prim_at_path(stage, path)
    attrs = {} if prim is None else _prim_attrs(prim)
    for attr_name in (
        "ias:object_label",
        "semantic:class",
        "semantics:class",
        "semantics:semanticType",
        "primvars:displayName",
        "displayName",
        "label",
    ):
        value = attrs.get(attr_name)
        if value is not None:
            labels.append(str(value))
    labels.append(_path_name(path))
    return tuple(labels)


def _normalize_paths(paths: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for path in paths:
        path_string = getattr(path, "pathString", None)
        normalized.append(str(path_string if path_string is not None else path))
    return tuple(path for path in normalized if path)


def _validate_abs_path(path: str, field_name: str) -> None:
    if not path.strip() or not path.startswith("/"):
        raise ExtensionActionError(f"{field_name} must be an absolute USD prim path.")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _discover_scene_objects(
    stage: Any,
    *,
    roots: tuple[str, ...],
    excluded_paths: tuple[str, ...],
) -> tuple[DiscoveredPrimSummary, ...]:
    if not hasattr(stage, "Traverse"):
        return ()
    normalized_roots = tuple(root.rstrip("/") for root in roots if root.strip())
    excluded = tuple(path.rstrip("/") for path in excluded_paths if path.strip())
    objects: list[DiscoveredPrimSummary] = []
    for prim in sorted(stage.Traverse(), key=prim_path):
        path = prim_path(prim)
        if not path or path == "/World":
            continue
        if normalized_roots and not any(
            path == root or path.startswith(f"{root}/") for root in normalized_roots
        ):
            continue
        if any(path == item or path.startswith(f"{item}/") for item in excluded):
            continue
        attrs = _prim_attrs(prim)
        type_name = prim_type_name(prim)
        if _is_audio_metadata_prim(type_name, attrs):
            continue
        if not _looks_like_scene_object(path, type_name, attrs):
            continue
        objects.append(
            DiscoveredPrimSummary(
                id=_path_name(path),
                prim_path=path,
                reasons=(f"type:{type_name or 'unknown'}",),
            )
        )
    return tuple(objects)


def _get_or_define_demo_object_prim(stage: Any, prim_path: str) -> Any:
    prim = get_or_define_prim(stage, prim_path=prim_path, prim_type="Cube")
    if hasattr(prim, "type_name"):
        prim.type_name = "Cube"
        return prim
    set_type_name = getattr(prim, "SetTypeName", None)
    if callable(set_type_name):
        with suppress(Exception):
            set_type_name("Cube")
    return prim


def _style_demo_object_prim(
    stage: Any,
    *,
    prim: Any,
    position_world: tuple[float, float, float],
) -> None:
    if hasattr(prim, "attributes"):
        if "xformOp:translate" not in prim.attributes:
            set_prim_xform_pose(prim, position=position_world)
        prim.attributes["size"] = 0.9
        prim.attributes["displayColor"] = (0.95, 0.48, 0.08)
        prim.attributes["displayOpacity"] = 1.0
        prim.attributes["doubleSided"] = True
        light = get_or_define_prim(
            stage,
            prim_path="/World/KeyLight",
            prim_type="DistantLight",
        )
        if hasattr(light, "attributes"):
            light.attributes["inputs:intensity"] = 750.0
            light.attributes["inputs:angle"] = 0.35
        dome = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectDomeLight",
            prim_type="DomeLight",
        )
        if hasattr(dome, "attributes"):
            dome.attributes["inputs:intensity"] = 450.0
            dome.attributes["inputs:color"] = (1.0, 0.92, 0.82)
        fill = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectFillLight",
            prim_type="SphereLight",
        )
        if hasattr(fill, "attributes"):
            fill.attributes["inputs:intensity"] = 1800.0
            fill.attributes["inputs:radius"] = 3.0
            set_prim_xform_pose(fill, position=(-3.0, -4.0, 3.0))
        return
    try:
        from pxr import Gf, UsdGeom, UsdLux  # type: ignore

        cube = UsdGeom.Cube(prim)
        cube.CreateSizeAttr(0.9)
        gprim = UsdGeom.Gprim(prim)
        gprim.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.48, 0.08)])
        gprim.CreateDisplayOpacityAttr([1.0])
        gprim.CreateDoubleSidedAttr(True)
        light_prim = get_or_define_prim(
            stage,
            prim_path="/World/KeyLight",
            prim_type="DistantLight",
        )
        light = UsdLux.DistantLight(light_prim)
        light.CreateIntensityAttr(750.0)
        light.CreateAngleAttr(0.35)
        set_prim_xform_pose(light_prim, position=(0.0, -3.0, 5.0))
        dome_prim = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectDomeLight",
            prim_type="DomeLight",
        )
        dome = UsdLux.DomeLight(dome_prim)
        dome.CreateIntensityAttr(450.0)
        dome.CreateColorAttr(Gf.Vec3f(1.0, 0.92, 0.82))
        fill_prim = get_or_define_prim(
            stage,
            prim_path="/World/DemoObjectFillLight",
            prim_type="SphereLight",
        )
        fill = UsdLux.SphereLight(fill_prim)
        fill.CreateIntensityAttr(1800.0)
        fill.CreateRadiusAttr(3.0)
        set_prim_xform_pose(fill_prim, position=(-3.0, -4.0, 3.0))
    except Exception:
        return


def _is_audio_metadata_prim(type_name: str, attrs: Mapping[str, Any]) -> bool:
    if type_name in {
        "OmniSound",
        "Sound",
        "AudioSource",
        "OmniAudioSource",
        "Microphone",
        "OmniListener",
        "Listener",
    }:
        return True
    return any(
        key in attrs
        for key in (
            "ias:source_id",
            "ias:class_label",
            "ias:array_id",
            "ias:microphone_id",
            "filePath",
            "inputs:file",
            "inputs:audio",
        )
    )


def _looks_like_scene_object(
    path: str,
    type_name: str,
    attrs: Mapping[str, Any],
) -> bool:
    name = _path_name(path)
    if name in {"World", "Rig", "Sources"}:
        return False
    if type_name in {"Xform", "Mesh", "Cube", "Sphere", "Cylinder", "Capsule"}:
        return True
    return any(key.startswith("xformOp:") for key in attrs)
