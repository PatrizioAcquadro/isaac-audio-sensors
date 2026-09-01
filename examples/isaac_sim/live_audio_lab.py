"""Isaac Sim script sketch for a live audio array scene."""

from __future__ import annotations

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.isaac import (
    IsaacAudioArraySensor,
    IsaacAudioSceneBindingCfg,
    IsaacEnvironmentResolutionCfg,
)
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    create_listener_prim,
    create_sound_prim,
)


def author_scene(stage) -> None:
    """Author sound/listener prims inside Isaac Sim."""

    create_sound_prim(
        stage,
        prim_path="/World/Sources/SpeakerA/Sound",
        audio_asset_path="generated://impulse",
        spatial=True,
    )
    array_prim = stage.DefinePrim("/World/Rig/AudioArray", "Xform")
    attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
    )
    create_listener_prim(
        stage,
        prim_path="/World/Rig/AudioArray/Listener",
        array_id="rig_front",
    )


def build_discovered_sensor(stage) -> IsaacAudioArraySensor:
    """Bind the authored scene by semantic discovery instead of exact paths."""

    return IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        environment_resolution_cfg=IsaacEnvironmentResolutionCfg(mode="manual"),
        environment=free_field_environment(environment_id="example_free_field"),
        binding_cfg=IsaacAudioSceneBindingCfg(
            discovery_roots=("/World",),
            preferred_array="rig_front",
            required_arrays=True,
            required_sources=True,
        ),
    )
