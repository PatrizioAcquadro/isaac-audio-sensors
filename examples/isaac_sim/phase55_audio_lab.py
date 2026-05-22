"""Isaac Sim script sketch for Phase 5.5 audio arrays."""

from __future__ import annotations

from isaac_audio_sensors.isaac.stage_audio import (
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
    create_listener_prim(
        stage,
        prim_path="/World/Rig/AudioArray/Listener",
        array_id="rig_front",
    )
