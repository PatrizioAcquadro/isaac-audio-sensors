"""Config-driven simulator-independent audio simulation."""

from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.core.backends.base import (
    _simulate_legacy_frame,
    get_backend,
)
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.types import AudioSensorFrame, AudioTimeWindow


def simulate_from_config(
    path: str | Path,
    *,
    backend_id: str | None = None,
    array_id: str | None = None,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_observations: int | None = None,
) -> AudioSensorFrame:
    """Simulate one frame from a validated audio configuration."""

    config = load_audio_config(path)
    selected_backend = backend_id or config.default_backend
    selected_array = array_id or next(iter(config.arrays))
    scene = build_scene_snapshot(config)
    time_window = AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        frame_index=0,
    )
    backend_kwargs: dict[str, object] = {
        "effects": config.effects,
        "runtime_profile": config.runtime_profile,
        "max_observations": max_observations,
    }
    backend_kwargs.update(
        speed_of_sound_mps=config.speed_of_sound_mps,
        max_order=config.analytic_max_order,
        air_absorption=config.analytic_air_absorption,
        ray_tracing=config.analytic_ray_tracing,
    )
    backend = get_backend(selected_backend, **backend_kwargs)
    return _simulate_legacy_frame(backend, scene, selected_array, time_window)


__all__ = ["simulate_from_config"]
