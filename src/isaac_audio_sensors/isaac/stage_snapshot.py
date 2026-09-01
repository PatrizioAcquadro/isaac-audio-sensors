"""Build core scene snapshots from config or live USD-like stages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from isaac_audio_sensors.core.effects.config import MotionEffectsConfig
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.motion import PoseHistory, validate_pose_observation
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioSceneSnapshot,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioDiscoveryResult,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
    resolve_stage_environment,
)


def build_stage_snapshot(
    stage: Any,
    *,
    timestamp_ms: int,
    environment_resolution_cfg: IsaacEnvironmentResolutionCfg,
    environment: AcousticEnvironmentSpec | None = None,
    stage_id: str | None = None,
    array_prim_path: str | None = None,
    robot_base_prim_path: str | None = None,
    source_prim_path: str | None = None,
    usd_time_code: Any | None = None,
    time_code: Any | None = None,
    default_class_label: str = "Sound",
    discovery_cfg: IsaacAudioDiscoveryCfg | None = None,
    preferred_array: str | None = None,
    preferred_source: str | None = None,
    diagnostics_out: dict[str, Any] | None = None,
    motion_config: MotionEffectsConfig | None = None,
    pose_history: PoseHistory | None = None,
    simulation_time_s: float | None = None,
    selected_array_id: str | None = None,
) -> AudioSceneSnapshot:
    """Build a live core snapshot from a real USD or duck-typed stage.

    Real Isaac/pxr stages are resolved through lazy USD transform APIs when
    available. Lightweight test stages fall back to namespaced world-pose attrs
    and simple ``xformOp:translate``/``xformOp:orient`` parent stacks.
    """

    cfg = effective_discovery_cfg(
        discovery_cfg=discovery_cfg,
        array_prim_path=array_prim_path,
        robot_base_prim_path=robot_base_prim_path,
        source_prim_path=source_prim_path,
        default_class_label=default_class_label,
    )
    prims = tuple(stage.Traverse())
    result = discover_stage_audio(
        stage,
        cfg=cfg,
        timestamp_ms=timestamp_ms,
        stage_id=stage_id,
        usd_time_code=usd_time_code,
        time_code=time_code,
        explicit_array_prim_path=array_prim_path,
        explicit_source_prim_path=source_prim_path,
        preferred_array=preferred_array,
        preferred_source=preferred_source,
        prims=prims,
    )
    diagnostics = dict(result.diagnostics)
    if result.selected_array is None:
        raise ValueError(
            "Acoustic-environment resolution requires one selected microphone array."
        )
    environment_diagnostics: dict[str, Any] = {}
    resolved_environment = resolve_stage_environment(
        stage,
        result.selected_array.spec,
        cfg=environment_resolution_cfg,
        manual_environment=environment,
        time_code=usd_time_code if time_code is None else time_code,
        prims=prims,
        diagnostics_out=environment_diagnostics,
    )
    diagnostics["environment_resolution"] = environment_diagnostics
    snapshot = snapshot_from_discovery(
        result,
        timestamp_ms=timestamp_ms,
        preferred_source=preferred_source,
        environment=resolved_environment,
    )
    if motion_config is not None and motion_config.derive_velocity_from_poses:
        if pose_history is None or simulation_time_s is None:
            raise ValueError(
                "Enabled pose derivation requires PoseHistory and a finite explicit "
                "simulation_time_s."
            )
        resolved_array_id = selected_array_id
        if resolved_array_id is None and result.selected_array is not None:
            resolved_array_id = result.selected_array.spec.array_id
        if resolved_array_id is None:
            raise ValueError("Enabled pose derivation requires a selected array.")
        snapshot, velocity_sources = enrich_snapshot_motion(
            snapshot,
            selected_array_id=resolved_array_id,
            time_s=simulation_time_s,
            pose_history=pose_history,
            motion_config=motion_config,
        )
        diagnostics["motion"] = {"velocity_source": velocity_sources}
    if diagnostics_out is not None:
        diagnostics_out.clear()
        diagnostics_out.update(diagnostics)
    return snapshot


def effective_discovery_cfg(
    *,
    discovery_cfg: IsaacAudioDiscoveryCfg | None,
    array_prim_path: str | None,
    robot_base_prim_path: str | None,
    source_prim_path: str | None,
    default_class_label: str = "Sound",
) -> IsaacAudioDiscoveryCfg:
    """Resolve the discovery config used for one live stage snapshot."""

    cfg = discovery_cfg or IsaacAudioDiscoveryCfg(
        discovery_roots=("/World",),
        robot_base_prim_path=robot_base_prim_path,
        required_arrays=array_prim_path is not None,
        required_sources=source_prim_path is not None,
        default_class_label=default_class_label,
        strict_candidate_errors=True,
    )
    if discovery_cfg is not None and robot_base_prim_path is not None:
        cfg = replace(
            cfg,
            robot_base_prim_path=robot_base_prim_path,
            required_arrays=cfg.required_arrays or array_prim_path is not None,
            required_sources=cfg.required_sources or source_prim_path is not None,
        )
    return cfg


def snapshot_from_discovery(
    result: IsaacAudioDiscoveryResult,
    *,
    timestamp_ms: int,
    preferred_source: str | None,
    environment: AcousticEnvironmentSpec,
) -> AudioSceneSnapshot:
    """Assemble the core snapshot from one discovery result."""

    return AudioSceneSnapshot(
        stage_id=result.stage_id,
        timestamp_ms=timestamp_ms,
        sources=(
            (result.selected_source.spec,)
            if preferred_source is not None and result.selected_source is not None
            else tuple(source.spec for source in result.sources)
        ),
        arrays=tuple(array.spec for array in result.arrays),
        environment=environment,
    )


def enrich_snapshot_motion(
    snapshot: AudioSceneSnapshot,
    *,
    selected_array_id: str,
    time_s: float,
    pose_history: PoseHistory,
    motion_config: MotionEffectsConfig,
) -> tuple[AudioSceneSnapshot, dict[str, str]]:
    """Fill absent source/selected-array velocities from resolved live poses."""

    if not motion_config.derive_velocity_from_poses:
        return snapshot, {}
    selected_array = snapshot.array_by_id(selected_array_id)
    if any(source.source_id == selected_array.array_id for source in snapshot.sources):
        raise ConfigValidationError(
            "audio.effects.motion.derive_velocity_from_poses=true cannot represent "
            f"source/selected-array id collision {selected_array.array_id!r}."
        )

    observations = tuple(
        (
            source.source_id,
            source.position_world,
            source.orientation_world_quat,
        )
        for source in snapshot.sources
    ) + (
        (
            selected_array.array_id,
            selected_array.position_world,
            selected_array.orientation_world_quat,
        ),
    )
    for entity_id, position, orientation in observations:
        validate_pose_observation(entity_id, time_s, position, orientation)

    velocity_sources: dict[str, str] = {}
    enriched_sources = []
    for source in snapshot.sources:
        result = pose_history.observe(
            source.source_id,
            time_s,
            source.position_world,
            source.orientation_world_quat,
        )
        if source.velocity_world_mps is not None:
            velocity_sources[source.source_id] = "authored"
            enriched_sources.append(source)
            continue
        velocity_sources[source.source_id] = (
            "derived"
            if result.velocity_world_mps is not None
            else f"none:{result.reason}"
        )
        enriched_sources.append(
            source
            if result.velocity_world_mps is None
            else replace(source, velocity_world_mps=result.velocity_world_mps)
        )

    array_result = pose_history.observe(
        selected_array.array_id,
        time_s,
        selected_array.position_world,
        selected_array.orientation_world_quat,
    )
    if selected_array.velocity_world_mps is not None:
        velocity_sources[selected_array.array_id] = "authored"
        enriched_array = selected_array
    else:
        velocity_sources[selected_array.array_id] = (
            "derived"
            if array_result.velocity_world_mps is not None
            else f"none:{array_result.reason}"
        )
        enriched_array = (
            selected_array
            if array_result.velocity_world_mps is None
            else replace(
                selected_array,
                velocity_world_mps=array_result.velocity_world_mps,
            )
        )

    enriched_arrays = tuple(
        enriched_array if array.array_id == selected_array_id else array
        for array in snapshot.arrays
    )
    if (
        tuple(enriched_sources) == snapshot.sources
        and enriched_arrays == snapshot.arrays
    ):
        return snapshot, velocity_sources
    return (
        replace(
            snapshot,
            sources=tuple(enriched_sources),
            arrays=enriched_arrays,
        ),
        velocity_sources,
    )
