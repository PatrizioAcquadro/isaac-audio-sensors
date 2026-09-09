"""Fixed-shape Isaac Lab audio array sensor."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
import warp as wp
from isaaclab.sensors import SensorBase

from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.types import AudioSceneSnapshot
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData
from isaac_audio_sensors.lab.entity_binding import EntityBinding, EntityBindingCfg
from isaac_audio_sensors.lab.reference_backend import ReferenceBackend

if TYPE_CHECKING:
    from isaac_audio_sensors.lab.audio_array_sensor_cfg import AudioArraySensorCfg


class AudioArraySensor(SensorBase):
    """Convert entity tensors or pure snapshots into batched RL observations."""

    def __init__(self, cfg: AudioArraySensorCfg) -> None:
        self._data: AudioArraySensorData | None = None
        self._entity_binding: EntityBinding | None = None
        self._reference_backend: ReferenceBackend | None = None
        self._audio_time: torch.Tensor | None = None
        self._audio_last_update: torch.Tensor | None = None
        super().__init__(cfg)

    @property
    def data(self) -> AudioArraySensorData:
        if not self.is_initialized or self._data is None:
            raise RuntimeError("AudioArraySensor is not initialized.")
        self._update_outdated_buffers()
        return self._data

    def update(self, dt: float, force_recompute: bool = False) -> None:
        """Advance a double-precision episode clock; reads consume only past audio."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and non-negative.")
        if not self.is_initialized:
            return
        assert self._audio_time is not None
        assert self._audio_last_update is not None
        self._audio_time.add_(dt)
        super().update(dt, force_recompute=False)
        elapsed = self._audio_time - self._audio_last_update
        due = (elapsed > 0) & (elapsed + 1e-12 >= float(self.cfg.update_period))
        if force_recompute:
            due = elapsed > 0
        wp.to_torch(self._is_outdated).copy_(due)
        if force_recompute:
            self._update_outdated_buffers()

    def bind_entities(self, scene: object, cfg: EntityBindingCfg) -> AudioArraySensor:
        """Bind the batched entity/tensor execution path."""

        if self.is_initialized:
            raise RuntimeError(
                "Bind AudioArraySensor before simulation initialization."
            )
        if self.cfg.energy_threshold_dbfs is not None:
            raise ValueError(
                "energy_threshold_dbfs is not supported by the entity binding."
            )
        if self.cfg.doa_enabled:
            raise ValueError(
                "doa_enabled is not supported by the entity binding because it "
                "does not produce microphone waveforms."
            )
        self._entity_binding = EntityBinding(scene, cfg)
        self._reference_backend = None
        self._validate_bound_runtime()
        return self

    def bind_reference(
        self,
        snapshots: Sequence[AudioSceneSnapshot],
        array_ids: Sequence[str],
    ) -> AudioArraySensor:
        """Bind the scalar core backend to pure snapshots."""

        if self.is_initialized:
            raise RuntimeError(
                "Bind AudioArraySensor before simulation initialization."
            )
        if self.cfg.energy_threshold_dbfs is None:
            raise ValueError(
                "energy_threshold_dbfs is required by the reference binding."
            )
        self._reference_backend = ReferenceBackend(
            backend_id=self.cfg.backend,
            speed_of_sound_mps=float(self.cfg.speed_of_sound_mps),
            analytic_max_order=int(self.cfg.analytic_max_order),
            analytic_air_absorption=bool(self.cfg.analytic_air_absorption),
            analytic_ray_tracing=bool(self.cfg.analytic_ray_tracing),
            max_observations=self.cfg.max_observations,
            max_doa_candidates=self.cfg.max_doa_candidates,
            energy_threshold_dbfs=float(self.cfg.energy_threshold_dbfs),
            doa_enabled=bool(self.cfg.doa_enabled),
            effects=self.cfg.effects,
            snapshots=snapshots,
            array_ids=array_ids,
        )
        self._entity_binding = None
        self._validate_bound_runtime()
        return self

    def reset(
        self,
        env_ids: Sequence[int] | None = None,
        env_mask: wp.array | None = None,
    ) -> None:
        mask = self._resolve_indices_and_mask(env_ids, env_mask)
        super().reset(env_mask=mask)
        mask_torch = wp.to_torch(mask)
        if self._data is not None:
            self._data.reset(mask_torch)
        if self._audio_time is not None:
            self._audio_time[mask_torch] = 0
            self._audio_last_update[mask_torch] = 0
        if self._reference_backend is not None:
            env_ids_torch = torch.nonzero(
                mask_torch,
                as_tuple=False,
            ).squeeze(-1)
            self._reference_backend.reset(env_ids_torch)

    def _initialize_impl(self) -> None:
        super()._initialize_impl()
        self._validate_bound_runtime(runtime_ready=True)
        self._data = AudioArraySensorData.allocate(
            num_envs=self._num_envs,
            max_observations=self.cfg.max_observations,
            max_doa_candidates=self.cfg.max_doa_candidates,
            device=self.device,
        )
        self._audio_time = torch.zeros(
            self._num_envs, dtype=torch.float64, device=self.device
        )
        self._audio_last_update = torch.zeros_like(self._audio_time)

    def _update_buffers_impl(self, env_mask: wp.array) -> None:
        if self._data is None:
            raise RuntimeError("AudioArraySensor buffers are not initialized.")
        env_ids = torch.nonzero(wp.to_torch(env_mask), as_tuple=False).squeeze(-1)
        if env_ids.numel() == 0:
            return
        assert self._audio_time is not None
        timestamps = self._audio_time.index_select(0, env_ids)
        if self._entity_binding is not None:
            observations = self._entity_observations(env_ids, timestamps)
        else:
            assert self._reference_backend is not None
            observations = self._reference_backend.observations(
                env_ids=env_ids,
                timestamps_s=timestamps,
                update_period=float(self.cfg.update_period),
                device=self.device,
            )
        self._data.write(env_ids, observations)
        self._audio_last_update[env_ids] = timestamps

    def _entity_observations(
        self, env_ids: torch.Tensor, timestamps: torch.Tensor
    ) -> AudioArraySensorData:
        assert self._entity_binding is not None
        del timestamps
        return AudioArraySensorData.allocate(
            num_envs=int(env_ids.numel()),
            max_observations=self.cfg.max_observations,
            max_doa_candidates=self.cfg.max_doa_candidates,
            device=self.device,
        )

    def _validate_bound_runtime(self, *, runtime_ready: bool = False) -> None:
        if self._entity_binding is None and self._reference_backend is None:
            if runtime_ready or self.is_initialized:
                raise RuntimeError(
                    "Call bind_entities() or bind_reference() before initialization."
                )
            return
        if self._entity_binding is not None:
            if self.cfg.backend != "analytic_acoustics":
                raise ValueError("Entity binding supports only analytic_acoustics.")
            if self._entity_binding.cfg.environment.kind != "free_field":
                raise ValueError(
                    "Entity-bound analytic_acoustics supports only an explicit "
                    "free_field environment."
                )
            if self.cfg.effects != EffectsConfig():
                raise ValueError("Entity binding requires effects to be disabled.")
            if (
                self.cfg.analytic_max_order != 0
                or self.cfg.analytic_air_absorption
                or self.cfg.analytic_ray_tracing
            ):
                raise ValueError(
                    "Entity-bound free_field analytic_acoustics requires max_order=0 "
                    "with air absorption and ray tracing disabled."
                )
        if runtime_ready or self.is_initialized:
            if self._bound_num_envs() != self._num_envs:
                raise ValueError(
                    f"Binding has {self._bound_num_envs()} environments; "
                    f"SensorBase resolved {self._num_envs}."
                )
            if (
                self._entity_binding is not None
                and self._entity_binding.device != self.device
            ):
                raise ValueError(
                    f"Entity tensors are on {self._entity_binding.device}; "
                    f"sensor is on {self.device}."
                )

    def _bound_num_envs(self) -> int:
        if self._entity_binding is not None:
            return self._entity_binding.num_envs
        if self._reference_backend is not None:
            return self._reference_backend.num_envs
        return 0
