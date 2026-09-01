"""Frame preparation for the room-acoustics backend pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.backends.room_acoustics.diagnostics import (
    _environment_config_summary,
)
from isaac_audio_sensors.core.directivity import microphone_world_orientation
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
)
from isaac_audio_sensors.core.math_utils import Quaternion, Vector3
from isaac_audio_sensors.core.microphone_array import (
    microphone_world_positions,
    validate_tdoa_array,
)
from isaac_audio_sensors.core.motion import WindowMotionPlan
from isaac_audio_sensors.core.scene import active_sources, deterministic_frame_id
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
)


@dataclass(frozen=True, slots=True)
class PreparedRoomFrame:
    """Validated immutable inputs shared by every room-frame pipeline stage."""

    scene: AudioSceneSnapshot
    sensor: MicrophoneArraySpec
    time_window: AudioTimeWindow
    frame_id: str
    mic_ids: tuple[str, ...]
    sample_rate_hz: int
    nominal_window_start_sample: int
    microphone_self_noise_db: dict[str, float | None]
    microphone_orientations: dict[str, Quaternion]
    window_sample_count: int
    pra: Any
    active: tuple[AudioSourceSpec, ...]
    environment_config: dict[str, object]
    max_order: int
    air_absorption: bool
    ray_tracing: bool
    microphone_positions_world: dict[str, Vector3]
    segments_per_window: int
    segment_factor_rows: tuple[dict[str, float], ...]
    per_surface_materials: bool


def prepare_room_frame(
    scene: AudioSceneSnapshot,
    sensor: MicrophoneArraySpec,
    time_window: AudioTimeWindow,
    *,
    backend_id: str,
    effects: EffectsConfig,
    runtime_profile: str,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
    window_motion: WindowMotionPlan | None,
    import_pyroomacoustics: Callable[[], Any],
    allowed_environment_kinds: tuple[str, ...] = ("shoebox",),
    per_surface_materials: bool = False,
    require_three_mics: bool = False,
) -> PreparedRoomFrame:
    """Validate one capture window and normalize its shared frame state."""

    if (backend_id == "room_acoustics_srp" or require_three_mics) and len(
        sensor.microphones
    ) == 2:
        raise UnsupportedEffectError(
            f"{backend_id} requires at least three microphones for an "
            "unambiguous localization claim"
        )
    validate_tdoa_array(sensor)
    if scene.environment is None:
        raise ValueError(
            f"{backend_id} requires scene.environment to be configured."
        )
    if scene.environment.kind not in allowed_environment_kinds:
        if allowed_environment_kinds != ("shoebox",):
            raise ValueError(
                f"{backend_id} does not support environment.kind="
                f"{scene.environment.kind!r}."
            )
        raise ValueError(
            "R7.1 room_acoustics requires environment.kind='shoebox'; "
            f"received {scene.environment.kind!r}. Other solver routing belongs to R8."
        )
    segments_per_window = effects.motion.segments_per_window
    if segments_per_window > 1 and window_motion is None:
        raise UnsupportedEffectError(
            "audio.effects.motion.segments_per_window>1 requires a live "
            "bracketed window-motion plan."
        )
    frame_id = deterministic_frame_id(
        backend_id=backend_id,
        stage_id=scene.stage_id,
        array_id=sensor.array_id,
        timestamp_ms=time_window.timestamp_ms,
        frame_index=time_window.frame_index,
    )
    mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
    sample_rate_hz = time_window.sample_rate_hz
    nominal_window_start_sample = int(round(time_window.start_time_s * sample_rate_hz))
    microphone_self_noise_db = {
        microphone.mic_id: microphone.self_noise_db for microphone in sensor.microphones
    }
    microphone_orientations = {
        microphone.mic_id: microphone_world_orientation(
            sensor.orientation_world_quat,
            microphone.relative_orientation_quat,
        )
        for microphone in sensor.microphones
    }
    window_sample_count = max(
        1,
        int(
            round((time_window.end_time_s - time_window.start_time_s) * sample_rate_hz)
        ),
    )
    if effects != EffectsConfig() or effects.motion.segments_per_window != 1:
        validate_effects_config(
            effects,
            microphone_orders=(mic_ids,),
            sample_rate_hz=sample_rate_hz,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            sample_count=window_sample_count,
            microphone_self_noise_db=microphone_self_noise_db,
        )
    if segments_per_window > 1:
        assert window_motion is not None
        if (
            window_motion.sample_rate_hz != sample_rate_hz
            or window_motion.window_sample_count != window_sample_count
            or len(window_motion.segments) != segments_per_window
        ):
            raise UnsupportedEffectError(
                "window-motion plan disagrees with the configured capture window"
            )
    pra = import_pyroomacoustics()
    active = active_sources(scene, time_window)
    segment_factor_rows = (
        tuple({} for _ in window_motion.segments)
        if segments_per_window > 1 and window_motion is not None
        else ()
    )
    return PreparedRoomFrame(
        scene=scene,
        sensor=sensor,
        time_window=time_window,
        frame_id=frame_id,
        mic_ids=mic_ids,
        sample_rate_hz=sample_rate_hz,
        nominal_window_start_sample=nominal_window_start_sample,
        microphone_self_noise_db=microphone_self_noise_db,
        microphone_orientations=microphone_orientations,
        window_sample_count=window_sample_count,
        pra=pra,
        active=active,
        environment_config=_environment_config_summary(
            scene.environment,
            per_surface_materials=per_surface_materials,
        ),
        max_order=max_order,
        air_absorption=air_absorption,
        ray_tracing=ray_tracing,
        microphone_positions_world=microphone_world_positions(sensor),
        segments_per_window=segments_per_window,
        segment_factor_rows=segment_factor_rows,
        per_surface_materials=per_surface_materials,
    )


__all__ = ["PreparedRoomFrame", "prepare_room_frame"]
