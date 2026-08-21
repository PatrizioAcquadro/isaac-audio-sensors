"""Room, material, RIR, and localization diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.materials import (
    MaterialResolution,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.math_utils import (
    basis_from_quaternion,
    bearing_from_components,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    MicrophoneArraySpec,
    RoomAcousticsSpec,
)


def _room_config_summary(room_spec: RoomAcousticsSpec) -> dict[str, object]:
    return {
        "room_id": room_spec.room_id,
        "dimensions_m": room_spec.dimensions_m,
        "absorption": _absorption_summary(room_spec.absorption),
        "max_order": room_spec.max_order,
        "air_absorption": room_spec.air_absorption,
        "ray_tracing": room_spec.ray_tracing,
        "origin_m": room_spec.origin_m,
        "out_of_bounds": room_spec.out_of_bounds,
        "anchor_prim_path": room_spec.anchor_prim_path,
    }


def _absorption_summary(
    absorption: float | dict[str, float] | str,
) -> float | dict[str, float] | str:
    if isinstance(absorption, str):
        return absorption
    if isinstance(absorption, dict):
        return {str(key): float(value) for key, value in sorted(absorption.items())}
    return float(absorption)


def _room_material_resolution(
    room_spec: RoomAcousticsSpec,
) -> tuple[
    float | dict[str, float] | tuple[float, ...],
    dict[str, str],
    MaterialResolution | None,
]:
    """Return the applied room absorption and its frozen evidence record."""

    absorption = room_spec.absorption
    if isinstance(absorption, str):
        resolution = resolve_material_coefficients(
            absorption,
            "absorption",
            application=f"room {room_spec.room_id!r}",
        )
        return resolution.values, resolution.evidence_record(), resolution
    if isinstance(absorption, dict):
        return (
            absorption,
            {
                "material_id": "inline_room_absorption:mapping",
                "coefficient": "absorption",
                "evidence": "nominal",
            },
            None,
        )
    return (
        float(absorption),
        {
            "material_id": "inline_room_absorption:scalar",
            "coefficient": "absorption",
            "evidence": "nominal",
        },
        None,
    )


def _room_state_hash(room_spec: RoomAcousticsSpec) -> str:
    """Hash the complete canonical room state."""

    applied, evidence, resolution = _room_material_resolution(room_spec)
    if isinstance(applied, dict):
        absorption_payload: object = {
            str(key): float(value) for key, value in sorted(applied.items())
        }
    elif isinstance(applied, tuple):
        absorption_payload = list(applied)
    else:
        absorption_payload = [float(applied)] * 6
    state = (
        room_spec.room_id,
        room_spec.dimensions_m,
        room_spec.origin_m,
        room_spec.out_of_bounds,
        room_spec.anchor_prim_path,
        absorption_payload,
        evidence["material_id"],
        evidence["evidence"],
        None if resolution is None else resolution.citation,
        room_spec.max_order,
        room_spec.air_absorption,
        room_spec.ray_tracing,
    )
    encoded = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _occluder_material_evidence(
    scene: AudioSceneSnapshot,
) -> dict[str, dict[str, str]]:
    """Derive pure-core evidence for material ids carried by occlusion records."""

    evidence: dict[str, dict[str, str]] = {}
    for occlusion in scene.occlusion or ():
        for prim_path, authored_id in sorted(occlusion.hit_materials.items()):
            application = f"occluder:{prim_path}"
            if authored_id == "usd_attribute":
                record = {
                    "material_id": f"usd_attribute:{prim_path}",
                    "coefficient": "transmission_db",
                    "evidence": "nominal",
                }
            else:
                record = resolve_material_coefficients(
                    authored_id,
                    "transmission_db",
                    application=application,
                ).evidence_record()
            evidence[application] = record
    return {key: evidence[key] for key in sorted(evidence)}


def _rir_lengths(
    room: Any,
    mic_ids: tuple[str, ...],
    *,
    source_index: int,
) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        lengths[mic_id] = 0 if rir is None else int(len(rir))
    return lengths


def _rir_peak_delays(
    room: Any,
    mic_ids: tuple[str, ...],
    sample_rate_hz: int,
    *,
    source_index: int,
) -> dict[str, float]:
    delays: dict[str, float] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        if rir is None or len(rir) == 0:
            delays[mic_id] = 0.0
        else:
            delays[mic_id] = float(np.argmax(np.abs(rir))) / float(sample_rate_hz)
    return delays


def _rir_for(room: Any, mic_index: int, source_index: int) -> np.ndarray | None:
    rir = getattr(room, "rir", None)
    if rir is None:
        return None
    try:
        return np.asarray(rir[mic_index][source_index], dtype=float)
    except (IndexError, TypeError):
        return None


def _ground_truth_bearing(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    forward, right, _ = basis_from_quaternion(sensor.orientation_world_quat)
    bearing = bearing_from_components(
        dot(delta, forward),
        dot(delta, right),
    )
    if bearing is None:
        return None
    return bearing


def _ground_truth_elevation(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    distance = norm(delta)
    if distance <= 1e-9:
        return None
    _, _, up = basis_from_quaternion(sensor.orientation_world_quat)
    ratio = dot(delta, up) / distance
    return math.degrees(math.asin(max(-1.0, min(1.0, ratio))))
