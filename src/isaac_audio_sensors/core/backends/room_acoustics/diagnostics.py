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
    AcousticEnvironmentSpec,
    AudioSceneSnapshot,
    MicrophoneArraySpec,
)


def _environment_config_summary(
    environment: AcousticEnvironmentSpec,
    *,
    per_surface_materials: bool = False,
) -> dict[str, object]:
    orientation = environment.world_pose.orientation_xyzw
    if not environment.surfaces:
        absorption: object = None
    elif per_surface_materials:
        absorption = {
            surface.surface_id: _absorption_summary(surface.absorption)
            for surface in environment.surfaces
        }
    else:
        absorption = _absorption_summary(_uniform_environment_absorption(environment))
    return {
        "environment_id": environment.environment_id,
        "kind": environment.kind,
        "dimensions_m": environment.dimensions_m,
        "position_world": environment.world_pose.position_m,
        "orientation_world_quat": orientation,
        "surface_count": len(environment.surfaces),
        "absorption": absorption,
    }


def _absorption_summary(
    absorption: float | dict[str, float] | str,
) -> float | dict[str, float] | str:
    if isinstance(absorption, str):
        return absorption
    if isinstance(absorption, dict):
        return {str(key): float(value) for key, value in sorted(absorption.items())}
    return float(absorption)


def _environment_material_resolution(
    environment: AcousticEnvironmentSpec,
) -> tuple[
    float | dict[str, float] | tuple[float, ...],
    dict[str, str],
    MaterialResolution | None,
]:
    """Return the applied uniform shoebox absorption and evidence record."""

    absorption = _uniform_environment_absorption(environment)
    if isinstance(absorption, str):
        resolution = resolve_material_coefficients(
            absorption,
            "absorption",
            application=f"environment {environment.environment_id!r}",
        )
        return resolution.values, resolution.evidence_record(), resolution
    if isinstance(absorption, dict):
        return (
            absorption,
            {
                "material_id": "inline_environment_absorption:mapping",
                "coefficient": "absorption",
                "evidence": "nominal",
            },
            None,
        )
    return (
        float(absorption),
        {
            "material_id": "inline_environment_absorption:scalar",
            "coefficient": "absorption",
            "evidence": "nominal",
        },
        None,
    )


def _environment_state_hash(environment: AcousticEnvironmentSpec) -> str:
    """Hash the complete canonical acoustic-environment state."""

    if environment.surfaces:
        applied, evidence, resolution = _environment_material_resolution(environment)
        if isinstance(applied, dict):
            absorption_payload: object = {
                str(key): float(value) for key, value in sorted(applied.items())
            }
        elif isinstance(applied, tuple):
            absorption_payload = list(applied)
        else:
            absorption_payload = [float(applied)] * 6
        material_id = evidence["material_id"]
        material_evidence = evidence["evidence"]
        citation = None if resolution is None else resolution.citation
    else:
        absorption_payload = None
        material_id = None
        material_evidence = None
        citation = None
    state = (
        environment.environment_id,
        environment.kind,
        environment.world_pose.position_m,
        environment.world_pose.orientation_xyzw,
        environment.dimensions_m,
        tuple(
            (
                surface.surface_id,
                surface.role,
                surface.vertices_local_m,
                surface.infinite,
            )
            for surface in environment.surfaces
        ),
        absorption_payload,
        material_id,
        material_evidence,
        citation,
    )
    encoded = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uniform_environment_absorption(
    environment: AcousticEnvironmentSpec,
) -> float | dict[str, float] | str:
    if not environment.surfaces:
        raise ValueError(
            f"Environment {environment.environment_id!r} has no acoustic surfaces."
        )
    absorption = environment.surfaces[0].absorption
    summary = _absorption_summary(absorption)
    if any(
        _absorption_summary(surface.absorption) != summary
        for surface in environment.surfaces[1:]
    ):
        raise ValueError(
            "R7.1 room_acoustics supports uniform shoebox absorption only; "
            "per-surface solver routing belongs to R8."
        )
    return absorption


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
