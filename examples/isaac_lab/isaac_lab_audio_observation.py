"""Isaac Lab audio observation config and tensor field example."""

from __future__ import annotations

from isaac_audio_sensors.lab import (
    LabAudioEntityBindingCfg,
    LabAudioSourceEntityCfg,
    LabAudioStageBindingCfg,
    ensure_isaac_lab_sensor_classes,
    get_audio_array_sensor_classes,
)

_classes = get_audio_array_sensor_classes(require_real=False)

audio_array = _classes.cfg(
    prim_path="{ENV_REGEX_NS}/Robot/audio_array",
    update_period=0.05,
    backend="tdoa_synthetic",
    microphone_layout="quad_front",
    max_events=2,
    debug_vis=True,
)

AUDIO_OBSERVATION_FIELDS = (
    "event_presence",
    "bearing_deg",
    "confidence",
    "sector_onehot",
    "per_mic_rms",
    "ambiguity_mask",
)

explicit_stage_binding = LabAudioStageBindingCfg(
    num_envs=2,
    env_namespace_pattern="/World/envs/env_{env_id}",
    array_prim_path="Robot/audio_array",
    source_prim_paths=("Sources/speaker",),
    microphone_layout="quad_front",
)

discovered_scene_binding = LabAudioStageBindingCfg(
    discover_arrays=True,
    array_discovery_root_path="Robot",
    preferred_array="audio_array",
    discover_sources=True,
    source_discovery_root_path="Sources",
    microphone_layout="quad_front",
)

entity_tensor_binding = LabAudioEntityBindingCfg(
    num_envs=2,
    robot_entity_name="robot",
    array_mount_body_name="head",
    array_relative_position_m=(0.08, 0.0, 0.0),
    microphone_layout="quad_front",
    source_entities=(
        LabAudioSourceEntityCfg(
            entity_name="speaker",
            source_id="speaker",
            class_label="Speech",
            duration_s=1.0,
        ),
    ),
)


def bind_from_stage(stage):
    """Create the live Lab sensor after AppLauncher/SimulationApp starts."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_stage(
        stage=stage,
        binding_cfg=explicit_stage_binding,
    )


def bind_from_scene(scene):
    """Bind from a scene/env wrapper that exposes stage and num_envs."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_scene(
        scene=scene,
        binding_cfg=discovered_scene_binding,
    )


def bind_from_scene_entities(scene):
    """Bind from a scene wrapper that exposes Lab entity tensor state."""

    classes = ensure_isaac_lab_sensor_classes()
    cfg = classes.cfg(
        prim_path="{ENV_REGEX_NS}/Robot/head/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
        microphone_layout="quad_front",
        max_events=2,
    )
    return classes.sensor(cfg).bind_lab_entities(
        scene=scene,
        binding_cfg=entity_tensor_binding,
    )
