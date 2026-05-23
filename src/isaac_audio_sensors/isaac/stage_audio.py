"""USD sound/listener authoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    start_time_s: float = 0.0,
    gain_db: float = 0.0,
) -> AuthoredPrimRecord:
    """Create or configure a USD sound prim using duck-typed stage APIs.

    The helper intentionally does not require importing ``pxr`` before it
    authors attributes. Isaac's real USD stage and the lightweight fake stages
    used by tests both expose ``DefinePrim``; environment validation remains
    available through ``require_isaac_usd`` for live Isaac smoke checks.
    """

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    if audio_asset_path.strip() == "":
        raise ValueError("audio_asset_path must be non-empty.")
    prim = get_or_define_prim(stage, prim_path=prim_path, prim_type="Sound")
    _set_attr(prim, "filePath", audio_asset_path)
    _set_attr(prim, "spatial", bool(spatial))
    _set_attr(prim, "loop", bool(loop))
    _set_attr(prim, "startTime", float(start_time_s))
    _set_attr(prim, "gain", float(gain_db))
    return AuthoredPrimRecord(
        prim_path=prim_path,
        prim_type="Sound",
        attributes={
            "filePath": audio_asset_path,
            "spatial": spatial,
            "loop": loop,
            "startTime": start_time_s,
            "gain": gain_db,
        },
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
    return attrs


def create_listener_prim(
    stage: Any,
    *,
    prim_path: str,
    array_id: str,
) -> AuthoredPrimRecord:
    """Create or configure a USD listener prim using duck-typed stage APIs."""

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    if array_id.strip() == "":
        raise ValueError("array_id must be non-empty.")
    prim = get_or_define_prim(stage, prim_path=prim_path, prim_type="Listener")
    _set_attr(prim, "ias:array_id", array_id)
    return AuthoredPrimRecord(
        prim_path=prim_path,
        prim_type="Listener",
        attributes={"ias:array_id": array_id},
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
    microphone_relative_offsets_m: tuple[tuple[float, float, float], ...]
    | None = None,
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
    return attrs


def get_or_define_prim(stage: Any, *, prim_path: str, prim_type: str) -> Any:
    """Return an existing prim or define it on a USD-like stage."""

    _require_stage(stage)
    if prim_path.strip() == "":
        raise ValueError("prim_path must be non-empty.")
    prim = _existing_prim(stage, prim_path)
    if prim is not None:
        return prim
    return stage.DefinePrim(prim_path, prim_type)


def _require_stage(stage: Any) -> None:
    if stage is None or not hasattr(stage, "DefinePrim"):
        raise ValueError("stage must provide a DefinePrim method.")


def _existing_prim(stage: Any, prim_path: str) -> Any | None:
    if hasattr(stage, "GetPrimAtPath"):
        prim = stage.GetPrimAtPath(prim_path)
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


def _usd_value_type_name(value: object, *, attr_name: str) -> Any:
    try:
        from pxr import Sdf  # type: ignore
    except ImportError:
        return None
    if attr_name in {"filePath", "inputs:file"}:
        return Sdf.ValueTypeNames.Asset
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
