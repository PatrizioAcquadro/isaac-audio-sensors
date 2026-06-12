"""Optional room-acoustics backend example."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)

array = create_microphone_array(
    array_id="rig_front",
    prim_path="/World/Rig/AudioArray",
    layout_name="quad_front",
)
scene = AudioSceneSnapshot(
    stage_id="room_acoustics_example",
    timestamp_ms=0,
    sources=(
        AudioSourceSpec(
            source_id="speaker",
            prim_path="/World/Sources/Speaker",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            position_world=(3.0, 2.0, 1.0),
            orientation_world_quat=None,
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        ),
    ),
    arrays=(array,),
    room=RoomAcousticsSpec(
        room_id="shoebox",
        dimensions_m=(5.0, 4.0, 2.7),
        absorption=0.35,
        max_order=2,
        # World placement of the room's minimum corner: the array sits at the
        # origin and the speaker at (3, 2, 1), both inside the room.
        origin_m=(-1.0, -1.0, -0.5),
    ),
)
try:
    frame = RoomAcousticsBackend().simulate(
        scene,
        array,
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            timestamp_ms=0,
            sample_rate_hz=array.sample_rate_hz,
        ),
    )
except OptionalDependencyUnavailable as exc:
    print(f"room_acoustics skipped: {exc}")
else:
    print(
        {
            "backend": frame.backend_id,
            "active_source_count": frame.diagnostics["active_source_count"],
            "pyroomacoustics_version": frame.diagnostics[
                "pyroomacoustics_version"
            ],
            "room_config": frame.diagnostics["room_config"],
            "rir_summary": frame.diagnostics["per_source_rir_summary"],
        }
    )
    print(frame.detections[0].diagnostics["estimated_tdoa_matrix_s"])
