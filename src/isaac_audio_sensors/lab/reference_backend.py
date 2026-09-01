"""Scalar reference backend for pure scene snapshots."""

from __future__ import annotations

from collections.abc import Sequence

import torch

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS, SECTOR_ORDER
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.effects import EffectsConfig
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
        ambiguity_policy: str,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        doa_estimator: str = "tdoa_least_squares",
        analytic_max_order: int = 0,
        analytic_air_absorption: bool = False,
        analytic_ray_tracing: bool = False,
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
        kwargs: dict[str, object] = {"effects": effects}
        if backend_id in {
            "analytic_acoustics",
            "tdoa_synthetic",
            "room_acoustics",
            "room_acoustics_srp",
        }:
            kwargs["ambiguity_policy"] = ambiguity_policy
            kwargs["speed_of_sound_mps"] = speed_of_sound_mps
        if backend_id == "analytic_acoustics":
            kwargs.update(
                doa_estimator=doa_estimator,
                max_order=analytic_max_order,
                air_absorption=analytic_air_absorption,
                ray_tracing=analytic_ray_tracing,
            )
        self._backend = get_backend(backend_id, **kwargs)

    @property
    def num_envs(self) -> int:
        return len(self.snapshots)

    def observations(
        self,
        *,
        env_ids: torch.Tensor,
        timestamps_s: torch.Tensor,
        frame_indices: torch.Tensor,
        max_events: int,
        update_period: float,
        device: str,
    ) -> AudioArraySensorData:
        count = int(env_ids.numel())
        result = AudioArraySensorData.allocate(
            num_envs=count,
            max_events=max_events,
            num_mics=self.num_mics,
            device=device,
        )
        sector_indices = {name: index for index, name in enumerate(SECTOR_ORDER)}
        window_s = max(float(update_period), 1e-3)
        for row in range(count):
            env_id = int(env_ids[row].item())
            start_s = float(timestamps_s[row].item())
            snapshot = self.snapshots[env_id]
            array_id = self.array_ids[env_id]
            spec = snapshot.array_by_id(array_id)
            frame = self._backend.simulate(
                snapshot,
                array_id,
                AudioTimeWindow(
                    start_time_s=start_s,
                    end_time_s=start_s + window_s,
                    timestamp_ms=round(start_s * 1000.0),
                    sample_rate_hz=spec.sample_rate_hz,
                    frame_index=int(frame_indices[row].item()),
                    max_events=max_events,
                ),
            )
            for event_index, detection in enumerate(frame.detections[:max_events]):
                result.event_presence[row, event_index] = True
                bearing = detection.doa.estimated_bearing_deg
                if bearing is not None:
                    result.bearing_deg[row, event_index] = float(bearing)
                    sector = detection.doa.bearing_sector
                    if sector is None:
                        sector = bearing_deg_to_sector_name(float(bearing))
                    result.sector_onehot[row, event_index, sector_indices[sector]] = 1.0
                result.confidence[row, event_index] = float(
                    detection.doa.bearing_confidence
                )
                result.ambiguity_mask[row, event_index] = (
                    detection.doa.ambiguity_class is not None
                )
                for mic_index, microphone in enumerate(spec.microphones):
                    result.per_mic_rms[row, event_index, mic_index] = float(
                        detection.per_mic_rms.get(microphone.mic_id, 0.0)
                    )
        return result
