"""Config-driven simulator-independent audio simulation."""

from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.types import AudioSensorFrame, AudioTimeWindow


def simulate_from_config(
    path: str | Path,
    *,
    backend_id: str | None = None,
    array_id: str | None = None,
    timestamp_ms: int = 0,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_events: int | None = None,
) -> AudioSensorFrame:
    """Simulate one frame from a validated audio configuration."""

    config = load_audio_config(path)
    selected_backend = backend_id or config.default_backend
    selected_array = array_id or next(iter(config.arrays))
    scene = build_scene_snapshot(config, timestamp_ms=timestamp_ms)
    sensor = scene.array_by_id(selected_array)
    time_window = AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        timestamp_ms=timestamp_ms,
        sample_rate_hz=sensor.sample_rate_hz,
        frame_index=0,
        max_events=max_events,
    )
    backend_kwargs: dict[str, object] = {
        "effects": config.effects,
        "runtime_profile": config.runtime_profile,
    }
    if selected_backend in {"tdoa_synthetic", "room_acoustics"}:
        backend_kwargs.update(
            speed_of_sound_mps=config.speed_of_sound_mps,
            ambiguity_policy=config.tdoa_ambiguity_policy,
        )
    backend = get_backend(selected_backend, **backend_kwargs)
    return backend.simulate(scene, sensor, time_window)


__all__ = ["simulate_from_config"]
