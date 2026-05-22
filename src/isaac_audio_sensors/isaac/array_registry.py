"""Discovery records for USD-authored microphone arrays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ArrayRecord:
    """Microphone-array metadata discovered from namespaced USD attributes."""

    prim_path: str
    array_id: str
    sample_rate_hz: int
    coordinate_convention: str
    layout_name: str | None
    microphone_ids: tuple[str, ...]


def discover_microphone_arrays(stage: Any) -> tuple[ArrayRecord, ...]:
    """Discover microphone-array metadata from a duck-typed USD stage."""

    if stage is None or not hasattr(stage, "Traverse"):
        raise ValueError("stage must provide a Traverse method.")
    prims = tuple(stage.Traverse())
    records: list[ArrayRecord] = []
    for prim in prims:
        attrs = dict(getattr(prim, "attributes", {}))
        array_id = attrs.get("ias:array_id")
        if array_id is None:
            continue
        prim_path = _prim_path(prim)
        microphone_ids = tuple(
            str(child_attrs["ias:microphone_id"])
            for child in prims
            if _prim_path(child).startswith(f"{prim_path}/")
            for child_attrs in (dict(getattr(child, "attributes", {})),)
            if child_attrs.get("ias:microphone_id") is not None
        )
        records.append(
            ArrayRecord(
                prim_path=prim_path,
                array_id=str(array_id),
                sample_rate_hz=int(attrs.get("ias:sample_rate_hz", 48_000)),
                coordinate_convention=str(
                    attrs.get(
                        "ias:coordinate_convention",
                        "x_forward_y_right_z_up_clockwise_bearing",
                    )
                ),
                layout_name=(
                    None
                    if attrs.get("ias:layout_name") is None
                    else str(attrs["ias:layout_name"])
                ),
                microphone_ids=microphone_ids,
            )
        )
    return tuple(records)


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))
