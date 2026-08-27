"""Fixed-shape Isaac Lab audio array sensor."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
import warp as wp
from isaaclab.sensors import SensorBase

from isaac_audio_sensors.core.constants import EPSILON
from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.types import AudioSceneSnapshot
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData
from isaac_audio_sensors.lab.batched_backend import (
    compact_active_events,
    geometry_observations,
    precompute_tdoa_operator,
    tdoa_observations,
)
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
        self._reference_frame_indices: torch.Tensor | None = None
        self._tdoa_operator: tuple[torch.Tensor, torch.Tensor] | None = None
        super().__init__(cfg)

    @property
    def data(self) -> AudioArraySensorData:
        if not self.is_initialized or self._data is None:
            raise RuntimeError("AudioArraySensor is not initialized.")
        self._update_outdated_buffers()
        return self._data

    def bind_entities(self, scene: object, cfg: EntityBindingCfg) -> AudioArraySensor:
        """Bind the batched entity/tensor execution path."""

        if self.is_initialized:
            raise RuntimeError(
                "Bind AudioArraySensor before simulation initialization."
            )
        self._entity_binding = EntityBinding(scene, cfg)
        self._reference_backend = None
        self._reference_frame_indices = None
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
        self._reference_backend = ReferenceBackend(
            backend_id=self.cfg.backend,
            ambiguity_policy=self.cfg.ambiguity_policy,
            effects=self.cfg.effects,
            snapshots=snapshots,
            array_ids=array_ids,
        )
        self._entity_binding = None
        self._tdoa_operator = None
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
        if self._reference_frame_indices is not None:
            self._reference_frame_indices[mask_torch] = 0

    def _initialize_impl(self) -> None:
        super()._initialize_impl()
        self._validate_bound_runtime(runtime_ready=True)
        num_mics = self._bound_num_mics()
        self._data = AudioArraySensorData.allocate(
            num_envs=self._num_envs,
            max_events=int(self.cfg.max_events),
            num_mics=num_mics,
            device=self.device,
        )
        if self._reference_backend is not None:
            self._reference_frame_indices = torch.zeros(
                self._num_envs, dtype=torch.long, device=self.device
            )
        elif self.cfg.backend == "tdoa_synthetic":
            assert self._entity_binding is not None
            solve, baseline, determinant = precompute_tdoa_operator(
                self._entity_binding.static.mic_offsets_local
            )
            if abs(determinant) <= EPSILON:
                raise ValueError(
                    "tdoa_synthetic requires non-degenerate least-squares geometry."
                )
            self._tdoa_operator = (solve, baseline)

    def _update_buffers_impl(self, env_mask: wp.array) -> None:
        if self._data is None:
            raise RuntimeError("AudioArraySensor buffers are not initialized.")
        env_ids = torch.nonzero(wp.to_torch(env_mask), as_tuple=False).squeeze(-1)
        if env_ids.numel() == 0:
            return
        timestamps = wp.to_torch(self._timestamp).index_select(0, env_ids)
        if self._entity_binding is not None:
            observations = self._entity_observations(env_ids, timestamps)
        else:
            assert self._reference_backend is not None
            assert self._reference_frame_indices is not None
            indices = self._reference_frame_indices.index_select(0, env_ids)
            observations = self._reference_backend.observations(
                env_ids=env_ids,
                timestamps_s=timestamps,
                frame_indices=indices,
                max_events=int(self.cfg.max_events),
                update_period=float(self.cfg.update_period),
                device=self.device,
            )
            self._reference_frame_indices.index_add_(
                0, env_ids, torch.ones_like(env_ids)
            )
        self._data.write(env_ids, observations)

    def _entity_observations(
        self, env_ids: torch.Tensor, timestamps: torch.Tensor
    ) -> AudioArraySensorData:
        assert self._entity_binding is not None
        batch = self._entity_binding.pose_batch(env_ids, device=self.device)
        static = batch.static
        end_time = timestamps + max(float(self.cfg.update_period), 1e-3)
        active = (static.source_start_s.unsqueeze(0) < end_time.unsqueeze(1)) & (
            static.source_end_s.unsqueeze(0) > timestamps.unsqueeze(1)
        )
        if self.cfg.backend == "geometry_only":
            source_observations = geometry_observations(batch)
        else:
            assert self._tdoa_operator is not None
            source_observations = tdoa_observations(
                batch,
                solve_operator=self._tdoa_operator[0],
                baseline_matrix=self._tdoa_operator[1],
            )
        return compact_active_events(
            source_observations,
            active_mask=active,
            max_events=int(self.cfg.max_events),
        )

    def _validate_bound_runtime(self, *, runtime_ready: bool = False) -> None:
        if self._entity_binding is None and self._reference_backend is None:
            if runtime_ready or self.is_initialized:
                raise RuntimeError(
                    "Call bind_entities() or bind_reference() before initialization."
                )
            return
        if self._entity_binding is not None:
            if self.cfg.backend not in {"geometry_only", "tdoa_synthetic"}:
                raise ValueError(
                    "Entity binding supports only geometry_only and tdoa_synthetic."
                )
            if self.cfg.effects != EffectsConfig():
                raise ValueError("Entity binding requires effects to be disabled.")
            if self.cfg.backend == "tdoa_synthetic" and self._bound_num_mics() < 3:
                raise ValueError(
                    "tdoa_synthetic entity binding requires at least 3 microphones."
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

    def _bound_num_mics(self) -> int:
        if self._entity_binding is not None:
            return self._entity_binding.num_mics
        if self._reference_backend is not None:
            return self._reference_backend.num_mics
        raise RuntimeError("No Lab binding configured.")
