"""Discovery records for USD audio sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecord:
    """Minimal source record discovered from a USD stage."""

    prim_path: str
    source_id: str
    audio_asset_path: str | None
    class_label: str | None = None


def discover_sound_sources(stage: Any) -> tuple[SourceRecord, ...]:
    """Discover sound-like prims from a duck-typed USD stage."""

    if stage is None or not hasattr(stage, "Traverse"):
        raise ValueError("stage must provide a Traverse method.")
    records: list[SourceRecord] = []
    for prim in stage.Traverse():
        prim_type = _prim_type_name(prim)
        attrs = _attrs(prim)
        if prim_type != "Sound" and "filePath" not in attrs:
            continue
        path = _prim_path(prim)
        records.append(
            SourceRecord(
                prim_path=path,
                source_id=str(attrs.get("ias:source_id", path.rsplit("/", 1)[-1])),
                audio_asset_path=(
                    None if attrs.get("filePath") is None else str(attrs["filePath"])
                ),
                class_label=(
                    None
                    if attrs.get("ias:class_label") is None
                    else str(attrs["ias:class_label"])
                ),
            )
        )
    return tuple(records)


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))


def _attrs(prim: Any) -> dict[str, object]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    return {}
