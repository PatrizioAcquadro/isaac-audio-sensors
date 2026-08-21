"""Scalar reference backend for pure scene snapshots."""

from __future__ import annotations

from collections.abc import Sequence

import torch

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import SECTOR_ORDER
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioTimeWindow,
    MicrophoneArraySpec,
)


class ReferenceBackend:
    """Run core backends per environment and emit the six Lab tensors."""

    def __init__(
        self,
        *,
        backend_id: str,
        ambiguity_policy: str,
        effects: EffectsConfig,
        snapshots: Sequence[AudioSceneSnapshot],
        array_specs: Sequence[MicrophoneArraySpec],
    ) -> None:
        self.snapshots = tuple(snapshots)
        self.array_specs = tuple(array_specs)
        if not self.snapshots or len(self.snapshots) != len(self.array_specs):
            raise ValueError(
                "snapshots and array_specs must be non-empty and have equal length."
            )
        if not all(isinstance(item, AudioSceneSnapshot) for item in self.snapshots):
            raise TypeError("snapshots must contain AudioSceneSnapshot values.")
        if not all(isinstance(item, MicrophoneArraySpec) for item in self.array_specs):
            raise TypeError("array_specs must contain MicrophoneArraySpec values.")
        mic_counts = {len(item.microphones) for item in self.array_specs}
        if len(mic_counts) != 1:
            raise ValueError(
                "All reference arrays must have the same microphone count."
            )
        self.num_mics = mic_counts.pop()
        kwargs: dict[str, object] = {"effects": effects}
        if backend_id in {
            "tdoa_synthetic",
            "room_acoustics",
            "room_acoustics_srp",
        }:
            kwargs["ambiguity_policy"] = ambiguity_policy
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
    ) -> dict[str, torch.Tensor]:
        count = int(env_ids.numel())
        shape = (count, max_events)
        result = {
            "event_presence": torch.zeros(shape, dtype=torch.bool, device=device),
            "bearing_deg": torch.full(
                shape, float("nan"), dtype=torch.float32, device=device
            ),
            "confidence": torch.zeros(shape, dtype=torch.float32, device=device),
            "sector_onehot": torch.zeros(
                (*shape, len(SECTOR_ORDER)), dtype=torch.float32, device=device
            ),
            "per_mic_rms": torch.zeros(
                (*shape, self.num_mics), dtype=torch.float32, device=device
            ),
            "ambiguity_mask": torch.zeros(shape, dtype=torch.bool, device=device),
        }
        sector_indices = {name: index for index, name in enumerate(SECTOR_ORDER)}
        window_s = max(float(update_period), 1e-3)
        for row in range(count):
            env_id = int(env_ids[row].item())
            start_s = float(timestamps_s[row].item())
            spec = self.array_specs[env_id]
            frame = self._backend.simulate(
                self.snapshots[env_id],
                spec,
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
                result["event_presence"][row, event_index] = True
                bearing = detection.doa.estimated_bearing_deg
                if bearing is not None:
                    result["bearing_deg"][row, event_index] = float(bearing)
                    sector = detection.doa.bearing_sector
                    if sector is None:
                        sector = bearing_deg_to_sector_name(float(bearing))
                    result["sector_onehot"][
                        row, event_index, sector_indices[sector]
                    ] = 1.0
                result["confidence"][row, event_index] = float(
                    detection.doa.bearing_confidence
                )
                result["ambiguity_mask"][row, event_index] = (
                    detection.doa.ambiguity_class is not None
                )
                for mic_index, microphone in enumerate(spec.microphones):
                    result["per_mic_rms"][row, event_index, mic_index] = float(
                        detection.per_mic_rms.get(microphone.mic_id, 0.0)
                    )
        return result
