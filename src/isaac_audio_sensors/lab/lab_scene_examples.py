"""Minimal Isaac Lab scene snippet strings for documentation and tests."""

from __future__ import annotations


def audio_array_sensor_cfg_snippet() -> str:
    """Return a snippet showing how a Lab user attaches the sensor config."""

    return (
        "classes = ensure_isaac_lab_sensor_classes(); "
        "classes.cfg("
        "prim_path='{ENV_REGEX_NS}/Robot/audio_array', "
        "update_period=0.05, backend='tdoa_synthetic', "
        "microphone_layout='quad_front', max_events=2, debug_vis=True)"
    )


def stage_binding_snippet() -> str:
    """Return a compact snippet for cloned-stage audio binding."""

    return (
        "sensor.bind_lab_scene(scene=scene, binding_cfg=LabAudioStageBindingCfg("
        "array_prim_path='{ENV_NS}/Robot/audio_array', discover_sources=True, "
        "source_discovery_root_path='Sources', microphone_layout=None))"
    )


def entity_binding_snippet() -> str:
    """Return a compact snippet for scene-entity tensor binding."""

    return (
        "sensor.bind_lab_entities(scene=scene, binding_cfg=LabAudioEntityBindingCfg("
        "robot_entity_name='robot', array_mount_body_name='head', "
        "source_entities=(LabAudioSourceEntityCfg(entity_name='speaker', "
        "source_id='speaker', class_label='Speech'),)))"
    )
