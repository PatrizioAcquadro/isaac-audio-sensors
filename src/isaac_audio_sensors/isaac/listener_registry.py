"""Discovery records for USD audio listeners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ListenerRecord:
    """Minimal listener record discovered from a USD stage."""

    prim_path: str
    listener_id: str
    array_id: str | None


def discover_listeners(stage: Any) -> tuple[ListenerRecord, ...]:
    """Discover listener-like prims from a duck-typed USD stage."""

    if stage is None or not hasattr(stage, "Traverse"):
        raise ValueError("stage must provide a Traverse method.")
    records: list[ListenerRecord] = []
    for prim in stage.Traverse():
        attrs = dict(getattr(prim, "attributes", {}))
        prim_type = str(getattr(prim, "type_name", ""))
        if hasattr(prim, "GetTypeName"):
            prim_type = str(prim.GetTypeName())
        if prim_type != "Listener" and "ias:array_id" not in attrs:
            continue
        path = str(prim.GetPath()) if hasattr(prim, "GetPath") else str(prim.path)
        records.append(
            ListenerRecord(
                prim_path=path,
                listener_id=str(attrs.get("ias:listener_id", path.rsplit("/", 1)[-1])),
                array_id=None
                if attrs.get("ias:array_id") is None
                else str(attrs["ias:array_id"]),
            )
        )
    return tuple(records)
