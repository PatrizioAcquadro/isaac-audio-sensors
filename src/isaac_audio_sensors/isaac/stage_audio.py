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
    prim = stage.DefinePrim(prim_path, "Sound")
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
    position_world: tuple[float, float, float],
    start_time_s: float = 0.0,
    duration_s: float | None = None,
    gain_db: float = 0.0,
    directivity: str = "omni",
) -> dict[str, object]:
    """Attach ``isaac_audio_sensors`` metadata to a sound source prim."""

    attrs: dict[str, object] = {
        "ias:source_id": source_id,
        "ias:class_label": class_label,
        "ias:position_world": position_world,
        "ias:start_time_s": float(start_time_s),
        "ias:gain_db": float(gain_db),
        "ias:directivity": directivity,
    }
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
    prim = stage.DefinePrim(prim_path, "Listener")
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
) -> dict[str, object]:
    """Attach namespaced microphone-array metadata to an existing prim."""

    attrs = {
        "ias:array_id": array_id,
        "ias:sample_rate_hz": int(sample_rate_hz),
        "ias:coordinate_convention": coordinate_convention,
        "ias:layout_name": layout_name,
    }
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    return attrs


def attach_microphone_attrs(
    prim: Any,
    *,
    mic_id: str,
    relative_position_m: tuple[float, float, float],
    gain_db: float = 0.0,
) -> dict[str, object]:
    """Attach one microphone's metadata to an array child prim."""

    attrs: dict[str, object] = {
        "ias:microphone_id": mic_id,
        "ias:relative_position_m": relative_position_m,
        "ias:gain_db": float(gain_db),
    }
    for name, value in attrs.items():
        _set_attr(prim, name, value)
    return attrs


def _require_stage(stage: Any) -> None:
    if stage is None or not hasattr(stage, "DefinePrim"):
        raise ValueError("stage must provide a DefinePrim method.")


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
