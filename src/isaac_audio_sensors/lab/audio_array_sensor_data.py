"""Tensor observation buffers for Isaac Lab."""

from __future__ import annotations

from dataclasses import dataclass

import torch

from isaac_audio_sensors.core.constants import SECTOR_ORDER


@dataclass(slots=True, kw_only=True)
class AudioArraySensorData:
    """Fixed-shape RL observations on the sensor device."""

    event_presence: torch.Tensor
    bearing_deg: torch.Tensor
    confidence: torch.Tensor
    sector_onehot: torch.Tensor
    per_mic_rms: torch.Tensor
    ambiguity_mask: torch.Tensor

    @classmethod
    def allocate(
        cls,
        *,
        num_envs: int,
        max_events: int,
        num_mics: int,
        device: str,
    ) -> AudioArraySensorData:
        shape = (num_envs, max_events)
        return cls(
            event_presence=torch.zeros(shape, dtype=torch.bool, device=device),
            bearing_deg=torch.full(
                shape, float("nan"), dtype=torch.float32, device=device
            ),
            confidence=torch.zeros(shape, dtype=torch.float32, device=device),
            sector_onehot=torch.zeros(
                (*shape, len(SECTOR_ORDER)), dtype=torch.float32, device=device
            ),
            per_mic_rms=torch.zeros(
                (*shape, num_mics), dtype=torch.float32, device=device
            ),
            ambiguity_mask=torch.zeros(shape, dtype=torch.bool, device=device),
        )

    def reset(self, env_mask: torch.Tensor) -> None:
        self.event_presence[env_mask] = False
        self.bearing_deg[env_mask] = float("nan")
        self.confidence[env_mask] = 0.0
        self.sector_onehot[env_mask] = 0.0
        self.per_mic_rms[env_mask] = 0.0
        self.ambiguity_mask[env_mask] = False

    def write(
        self, env_ids: torch.Tensor, observations: AudioArraySensorData
    ) -> None:
        for field_name in self.__dataclass_fields__:
            getattr(self, field_name).index_copy_(
                0, env_ids, getattr(observations, field_name)
            )
