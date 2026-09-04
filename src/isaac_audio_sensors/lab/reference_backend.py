"""Scalar reference backend for pure scene snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import torch

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.plugins.protocols import ActivityDetector
from isaac_audio_sensors.core.plugins.registry import get_default_registry
from isaac_audio_sensors.core.simulation import simulate_frame
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioTimeWindow,
)
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData


class ReferenceBackend:
    """Run core backends per environment and emit the six Lab tensors."""

    def __init__(
        self,
        *,
        backend_id: str,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        analytic_max_order: int = 0,
        analytic_air_absorption: bool = False,
        analytic_ray_tracing: bool = False,
        max_observations: int,
        energy_threshold_dbfs: float,
        effects: EffectsConfig,
        snapshots: Sequence[AudioSceneSnapshot],
        array_ids: Sequence[str],
    ) -> None:
        self.snapshots = tuple(snapshots)
        self.array_ids = tuple(array_ids)
        if not self.snapshots or len(self.snapshots) != len(self.array_ids):
            raise ValueError(
                "snapshots and array_ids must be non-empty and have equal length."
            )
        if not all(isinstance(item, AudioSceneSnapshot) for item in self.snapshots):
            raise TypeError("snapshots must contain AudioSceneSnapshot values.")
        if not all(isinstance(item, str) for item in self.array_ids):
            raise TypeError("array_ids must contain str values.")
        selected_arrays = tuple(
            snapshot.array_by_id(array_id)
            for snapshot, array_id in zip(self.snapshots, self.array_ids, strict=True)
        )
        mic_counts = {len(item.microphones) for item in selected_arrays}
        if len(mic_counts) != 1:
            raise ValueError(
                "All reference arrays must have the same microphone count."
            )
        self.num_mics = mic_counts.pop()
        self.max_observations = max_observations
        kwargs: dict[str, object] = {
            "effects": effects,
            "speed_of_sound_mps": speed_of_sound_mps,
            "max_order": analytic_max_order,
            "air_absorption": analytic_air_absorption,
            "ray_tracing": analytic_ray_tracing,
        }
        self._backend = get_backend(backend_id, **kwargs)
        self._perception = tuple(
            AudioPerceptionPipeline(
                activity_detector=cast(
                    ActivityDetector,
                    get_default_registry().resolve(
                        "activity_detector",
                        "auditok",
                        factory_kwargs={
                            "energy_threshold_dbfs": energy_threshold_dbfs
                        },
                    ),
                ),
                max_observations=max_observations,
            )
            for _ in self.snapshots
        )

    @property
    def num_envs(self) -> int:
        return len(self.snapshots)

    def observations(
        self,
        *,
        env_ids: torch.Tensor,
        timestamps_s: torch.Tensor,
        frame_indices: torch.Tensor,
        update_period: float,
        device: str,
    ) -> AudioArraySensorData:
        count = int(env_ids.numel())
        result = AudioArraySensorData.allocate(
            num_envs=count,
            max_observations=self.max_observations,
            num_mics=self.num_mics,
            device=device,
        )
        window_s = max(float(update_period), 1e-3)
        for row in range(count):
            env_id = int(env_ids[row].item())
            start_s = float(timestamps_s[row].item())
            snapshot = self.snapshots[env_id]
            array_id = self.array_ids[env_id]
            simulate_frame(
                self._backend,
                snapshot,
                array_id,
                AudioTimeWindow(
                    start_time_s=start_s,
                    end_time_s=start_s + window_s,
                    frame_index=int(frame_indices[row].item()),
                ),
                perception=self._perception[env_id],
            )
        return result

    def reset(self, env_ids: torch.Tensor) -> None:
        """Reset perception state for the selected environments."""

        for env_id in env_ids.tolist():
            self._perception[int(env_id)].reset()
