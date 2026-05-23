"""Discovery records for USD audio sources."""

from __future__ import annotations

import fnmatch
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
    for prim in sorted(stage.Traverse(), key=_prim_path):
        prim_type = _prim_type_name(prim)
        attrs = _attrs(prim)
        if not _looks_like_source(_prim_path(prim), prim_type, attrs):
            continue
        path = _prim_path(prim)
        records.append(
            SourceRecord(
                prim_path=path,
                source_id=str(attrs.get("ias:source_id", path.rsplit("/", 1)[-1])),
                audio_asset_path=_asset_path(
                    _first_present(
                        attrs,
                        (
                            "filePath",
                            "inputs:file",
                            "inputs:audio",
                            "ias:audio_asset_path",
                        ),
                    )
                ),
                class_label=(
                    None
                    if attrs.get("ias:class_label") is None
                    else str(attrs["ias:class_label"])
                ),
            )
        )
    return tuple(records)


def _looks_like_source(path: str, prim_type: str, attrs: dict[str, object]) -> bool:
    if prim_type in {"Sound", "AudioSource", "OmniAudioSource"}:
        return True
    if any(
        attrs.get(name) is not None
        for name in (
            "filePath",
            "inputs:file",
            "inputs:audio",
            "ias:audio_asset_path",
            "ias:source_id",
            "ias:class_label",
        )
    ):
        return True
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatchcase(name, pattern)
        for pattern in ("*Speaker*", "*Sound*", "*AudioSource*")
    )


def _first_present(attrs: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if attrs.get(key) is not None:
            return attrs[key]
    return None


def _asset_path(value: object | None) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    return str(path if path is not None else value)


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
