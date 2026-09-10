"""Scalar reference backend for pure scene snapshots."""

from __future__ import annotations

from collections.abc import Sequence

import torch

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.perception import _build_standard_perception_pipeline
from isaac_audio_sensors.core.simulation import simulate_frame
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioTimeWindow,
)
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData


class ReferenceBackend:
    """Run core backends per environment and project observed-only Lab tensors."""

    def __init__(
        self,
        *,
        backend_id: str,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        analytic_max_order: int = 0,
        analytic_air_absorption: bool = False,
        analytic_ray_tracing: bool = False,
        max_observations: int,
        max_doa_candidates: int = 2,
        energy_threshold_dbfs: float,
        doa_enabled: bool = False,
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
        self._sample_rates = tuple(array.sample_rate_hz for array in selected_arrays)
        self.max_observations = max_observations
        self.max_doa_candidates = max_doa_candidates
        self._next_samples = [0] * len(self.snapshots)
        self._frame_indices = [0] * len(self.snapshots)
        self._observations = [()] * len(self.snapshots)
        self.processing_status = [{} for _ in self.snapshots]
        kwargs: dict[str, object] = {
            "effects": effects,
            "speed_of_sound_mps": speed_of_sound_mps,
            "max_order": analytic_max_order,
            "air_absorption": analytic_air_absorption,
            "ray_tracing": analytic_ray_tracing,
        }
        self._backends = tuple(
            get_backend(backend_id, **kwargs) for _ in self.snapshots
        )
        self._perception = tuple(
            _build_standard_perception_pipeline(
                energy_threshold_dbfs=energy_threshold_dbfs,
                doa_enabled=doa_enabled,
                max_observations=None,
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
        update_period: float,
        device: str,
    ) -> AudioArraySensorData:
        count = int(env_ids.numel())
        observations = []
        window_s = float(update_period) or 0.1
        for row in range(count):
            env_id = int(env_ids[row].item())
            snapshot = self.snapshots[env_id]
            array_id = self.array_ids[env_id]
            sample_rate = self._sample_rates[env_id]
            # Timestamps are elapsed episode time, never the next window's start.
            end_sample = int(float(timestamps_s[row].item()) * sample_rate + 1e-7)
            if end_sample < self._next_samples[env_id]:
                raise ValueError("Reference time moved backwards without reset.")
            window_samples = max(1, round(window_s * sample_rate))
            while self._next_samples[env_id] < end_sample:
                start_sample = self._next_samples[env_id]
                stop_sample = min(start_sample + window_samples, end_sample)
                frame, _ = simulate_frame(
                    self._backends[env_id],
                    snapshot,
                    array_id,
                    AudioTimeWindow(
                        start_time_s=start_sample / sample_rate,
                        end_time_s=stop_sample / sample_rate,
                        frame_index=self._frame_indices[env_id],
                    ),
                    perception=self._perception[env_id],
                )
                self._next_samples[env_id] = stop_sample
                self._frame_indices[env_id] += 1
                self._observations[env_id] = frame.observations
                self.processing_status[env_id] = frame.diagnostics["perception"]
            observations.append(self._observations[env_id])
        return AudioArraySensorData.from_observations(
            observations,
            max_observations=self.max_observations,
            max_doa_candidates=self.max_doa_candidates,
            device=device,
        )

    def reset(self, env_ids: torch.Tensor) -> None:
        """Reset perception state for the selected environments."""

        for env_id in env_ids.tolist():
            self._next_samples[env_id] = 0
            self._frame_indices[env_id] = 0
            self._observations[env_id] = ()
            self.processing_status[env_id] = {}
            self._perception[int(env_id)].reset()
            reset = getattr(self._backends[int(env_id)], "reset", None)
            if callable(reset):
                reset()
