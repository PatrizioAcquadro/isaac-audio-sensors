"""Tensor binding from Isaac Lab scene entities to audio geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import torch

from isaac_audio_sensors.core.directivity import (
    DIRECTIVITY_COEFFICIENTS,
    DirectivityPattern,
    resolve_directivity_pattern,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_quaternion_xyzw,
    as_vector3,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import MicrophoneSpec


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceEntityCfg:
    """Map one Isaac Lab entity or body to a scheduled source."""

    entity_name: str
    body_name: str | None = None
    source_id: str | None = None
    start_time_s: float = 0.0
    duration_s: float | None = 1.0
    gain_db: float = 0.0
    directivity: DirectivityPattern = DirectivityPattern.OMNI
    relative_position_m: Vector3 = (0.0, 0.0, 0.0)
    relative_orientation_quat: Quaternion = (0.0, 0.0, 0.0, 1.0)

    def __post_init__(self) -> None:
        _require_name(self.entity_name, "entity_name")
        if self.body_name is not None:
            _require_name(self.body_name, "body_name")
        if self.source_id is not None:
            _require_name(self.source_id, "source_id")
        object.__setattr__(
            self,
            "directivity",
            resolve_directivity_pattern(
                self.directivity,
                "SourceEntityCfg.directivity",
            ),
        )
        _require_finite(self.start_time_s, "start_time_s")
        db_to_amplitude_gain(self.gain_db, "SourceEntityCfg.gain_db")
        object.__setattr__(self, "gain_db", float(self.gain_db))
        if self.duration_s is not None:
            _require_finite(self.duration_s, "duration_s")
            if self.duration_s <= 0.0:
                raise ValueError("duration_s must be positive.")
        object.__setattr__(
            self,
            "relative_position_m",
            as_vector3(self.relative_position_m, "relative_position_m"),
        )
        object.__setattr__(
            self,
            "relative_orientation_quat",
            as_quaternion_xyzw(
                self.relative_orientation_quat, "relative_orientation_quat"
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityBindingCfg:
    """Define the array mount, microphones, and source entities."""

    robot_entity_name: str = "robot"
    array_mount_body_name: str | None = None
    array_relative_position_m: Vector3 = (0.0, 0.0, 0.0)
    array_relative_orientation_quat: Quaternion = (0.0, 0.0, 0.0, 1.0)
    microphone_layout: str | None = "quad_front"
    microphones: tuple[MicrophoneSpec, ...] | None = None
    source_entities: tuple[SourceEntityCfg, ...] = ()
    state_position_frame: Literal["world", "env"] = "world"
    env_origins: torch.Tensor | None = None
    state_quat_order: Literal["wxyz", "xyzw"] = "wxyz"

    def __post_init__(self) -> None:
        _require_name(self.robot_entity_name, "robot_entity_name")
        if self.array_mount_body_name is not None:
            _require_name(self.array_mount_body_name, "array_mount_body_name")
        if self.state_position_frame not in {"world", "env"}:
            raise ValueError("state_position_frame must be 'world' or 'env'.")
        if self.state_quat_order not in {"wxyz", "xyzw"}:
            raise ValueError("state_quat_order must be 'wxyz' or 'xyzw'.")
        if self.microphone_layout is None and not self.microphones:
            raise ValueError("Provide microphone_layout or microphones.")
        if not self.source_entities:
            raise ValueError("source_entities must not be empty.")
        if self.microphones is not None:
            microphones = tuple(self.microphones)
            if not all(isinstance(item, MicrophoneSpec) for item in microphones):
                raise TypeError("microphones must contain MicrophoneSpec values.")
            if len({microphone.mic_id for microphone in microphones}) != len(
                microphones
            ):
                raise ValueError("Microphone ids must be unique.")
            object.__setattr__(self, "microphones", microphones)
        object.__setattr__(self, "source_entities", tuple(self.source_entities))
        object.__setattr__(
            self,
            "array_relative_position_m",
            as_vector3(self.array_relative_position_m, "array_relative_position_m"),
        )
        object.__setattr__(
            self,
            "array_relative_orientation_quat",
            as_quaternion_xyzw(
                self.array_relative_orientation_quat,
                "array_relative_orientation_quat",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityStaticBatchMeta:
    mic_offsets_local: torch.Tensor
    mic_relative_quats_xyzw: torch.Tensor
    mic_gain_scale: torch.Tensor
    mic_directivity_coefficient: torch.Tensor
    source_start_s: torch.Tensor
    source_end_s: torch.Tensor
    source_gain_scale: torch.Tensor
    source_directivity_coefficient: torch.Tensor


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityPoseTensorBatch:
    array_positions: torch.Tensor
    array_quats_xyzw: torch.Tensor
    source_positions: torch.Tensor
    source_quats_xyzw: torch.Tensor
    static: EntityStaticBatchMeta


class EntityBinding:
    """Validated zero-copy view over Isaac Lab root/body pose tensors."""

    def __init__(self, scene: Any, cfg: EntityBindingCfg) -> None:
        self.cfg = cfg
        self._robot = scene[cfg.robot_entity_name]
        self._source_cfgs = tuple(
            sorted(
                cfg.source_entities,
                key=lambda item: (item.start_time_s, _source_id(item)),
            )
        )
        source_ids = tuple(_source_id(item) for item in self._source_cfgs)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Resolved source ids must be unique.")
        self._sources = tuple(scene[item.entity_name] for item in self._source_cfgs)

        root_position, _ = _entity_pose(
            self._robot,
            body_name=cfg.array_mount_body_name,
            quat_order=cfg.state_quat_order,
            label=cfg.robot_entity_name,
            validate_quaternion=True,
        )
        self.device = str(root_position.device)
        self.num_envs = int(root_position.shape[0])
        self._env_origins = _env_origins(scene, cfg, root_position)
        self.static = _static_meta(cfg, self._source_cfgs, root_position.device)

        for source_cfg, source in zip(self._source_cfgs, self._sources, strict=True):
            position, _ = _entity_pose(
                source,
                body_name=source_cfg.body_name,
                quat_order=cfg.state_quat_order,
                label=source_cfg.entity_name,
                validate_quaternion=True,
            )
            if position.device != root_position.device:
                raise ValueError(
                    f"Entity {source_cfg.entity_name!r} must be on "
                    f"{root_position.device}."
                )
            if int(position.shape[0]) != self.num_envs:
                raise ValueError(
                    f"Entity {source_cfg.entity_name!r} has {position.shape[0]} rows; "
                    f"expected {self.num_envs}."
                )

    @property
    def num_mics(self) -> int:
        return int(self.static.mic_offsets_local.shape[0])

    def pose_batch(
        self, env_ids: torch.Tensor, *, device: str
    ) -> EntityPoseTensorBatch:
        if str(env_ids.device) != self.device or str(device) != self.device:
            raise ValueError(
                f"Entity tensors are on {self.device}; sensor is on {device}."
            )
        if env_ids.dtype != torch.long or env_ids.ndim != 1:
            raise ValueError("env_ids must be a rank-1 int64 tensor.")

        array_position, array_quat = _entity_pose(
            self._robot,
            body_name=self.cfg.array_mount_body_name,
            quat_order=self.cfg.state_quat_order,
            label=self.cfg.robot_entity_name,
            validate_quaternion=False,
        )
        array_position = array_position.index_select(0, env_ids)
        array_quat = array_quat.index_select(0, env_ids)
        array_position = _apply_origins(array_position, self._env_origins, env_ids)
        array_position, array_quat = _compose_pose(
            array_position,
            array_quat,
            self.cfg.array_relative_position_m,
            self.cfg.array_relative_orientation_quat,
        )

        source_positions = []
        source_quats = []
        for source_cfg, source in zip(self._source_cfgs, self._sources, strict=True):
            position, quat = _entity_pose(
                source,
                body_name=source_cfg.body_name,
                quat_order=self.cfg.state_quat_order,
                label=source_cfg.entity_name,
                validate_quaternion=False,
            )
            position = _apply_origins(
                position.index_select(0, env_ids), self._env_origins, env_ids
            )
            position, quat = _compose_pose(
                position,
                quat.index_select(0, env_ids),
                source_cfg.relative_position_m,
                source_cfg.relative_orientation_quat,
            )
            source_positions.append(position)
            source_quats.append(quat)

        return EntityPoseTensorBatch(
            array_positions=array_position,
            array_quats_xyzw=array_quat,
            source_positions=torch.stack(source_positions, dim=1),
            source_quats_xyzw=torch.stack(source_quats, dim=1),
            static=self.static,
        )


def _entity_pose(
    entity: Any,
    *,
    body_name: str | None,
    quat_order: str,
    label: str,
    validate_quaternion: bool,
) -> tuple[torch.Tensor, torch.Tensor]:
    data = getattr(entity, "data", entity)
    if body_name is None:
        state = getattr(data, "root_state_w", None)
        expected_rank = 2
    else:
        state = getattr(data, "body_state_w", None)
        expected_rank = 3
    if not isinstance(state, torch.Tensor):
        field = "root_state_w" if body_name is None else "body_state_w"
        raise ValueError(f"Entity {label!r} must expose tensor {field}.")
    if state.dtype != torch.float32:
        raise TypeError(f"Entity {label!r} pose tensor must use float32.")
    if state.ndim != expected_rank or state.shape[-1] < 7:
        raise ValueError(
            f"Entity {label!r} pose tensor must have rank {expected_rank} and at "
            "least seven state columns."
        )
    if body_name is not None:
        names = tuple(str(name) for name in getattr(entity, "body_names", ()))
        try:
            body_index = names.index(body_name)
        except ValueError as exc:
            raise ValueError(
                f"Entity {label!r} has no body {body_name!r}; available: {names}."
            ) from exc
        state = state[:, body_index]
    position = state[:, :3]
    quat = state[:, 3:7]
    if quat_order == "wxyz":
        quat = quat[:, (1, 2, 3, 0)]
    norm = torch.linalg.vector_norm(quat, dim=-1, keepdim=True)
    if validate_quaternion and torch.any(norm <= 1e-12).item():
        raise ValueError(f"Entity {label!r} contains a zero quaternion.")
    return position, quat / torch.clamp(norm, min=1e-12)


def _env_origins(
    scene: Any,
    cfg: EntityBindingCfg,
    reference: torch.Tensor,
) -> torch.Tensor | None:
    if cfg.state_position_frame == "world":
        return None
    origins = cfg.env_origins
    if origins is None:
        origins = getattr(scene, "env_origins", None)
    if not isinstance(origins, torch.Tensor):
        raise ValueError("state_position_frame='env' requires tensor env_origins.")
    _validate_tensor(origins, reference, "env_origins", shape=(reference.shape[0], 3))
    return origins


def _apply_origins(
    positions: torch.Tensor,
    origins: torch.Tensor | None,
    env_ids: torch.Tensor,
) -> torch.Tensor:
    if origins is None:
        return positions
    return positions + origins.index_select(0, env_ids)


def _compose_pose(
    position: torch.Tensor,
    quat: torch.Tensor,
    relative_position: Vector3,
    relative_quat: Quaternion,
) -> tuple[torch.Tensor, torch.Tensor]:
    rel_position = position.new_tensor(relative_position).expand_as(position)
    rel_quat = quat.new_tensor(relative_quat).expand_as(quat)
    return position + _rotate(rel_position, quat), _normalize(_quat_mul(quat, rel_quat))


def _static_meta(
    cfg: EntityBindingCfg,
    source_cfgs: tuple[SourceEntityCfg, ...],
    device: torch.device,
) -> EntityStaticBatchMeta:
    if cfg.microphones is None:
        microphones = microphone_layout(str(cfg.microphone_layout))
    else:
        microphones = cfg.microphones
    offsets = tuple(microphone.relative_position_m for microphone in microphones)
    if not offsets:
        raise ValueError("Microphone geometry must not be empty.")
    mic_orientations = tuple(
        microphone.relative_orientation_quat or (0.0, 0.0, 0.0, 1.0)
        for microphone in microphones
    )
    starts = tuple(source.start_time_s for source in source_cfgs)
    ends = tuple(
        math.inf
        if source.duration_s is None
        else source.start_time_s + source.duration_s
        for source in source_cfgs
    )
    return EntityStaticBatchMeta(
        mic_offsets_local=torch.tensor(offsets, dtype=torch.float32, device=device),
        mic_relative_quats_xyzw=torch.tensor(
            mic_orientations,
            dtype=torch.float32,
            device=device,
        ),
        mic_gain_scale=torch.tensor(
            tuple(
                db_to_amplitude_gain(
                    microphone.gain_db,
                    f"MicrophoneSpec[{microphone.mic_id!r}].gain_db",
                )
                for microphone in microphones
            ),
            dtype=torch.float32,
            device=device,
        ),
        mic_directivity_coefficient=torch.tensor(
            tuple(
                DIRECTIVITY_COEFFICIENTS[microphone.directivity]
                for microphone in microphones
            ),
            dtype=torch.float32,
            device=device,
        ),
        source_start_s=torch.tensor(starts, dtype=torch.float32, device=device),
        source_end_s=torch.tensor(ends, dtype=torch.float32, device=device),
        source_gain_scale=torch.tensor(
            tuple(
                db_to_amplitude_gain(
                    source.gain_db,
                    f"SourceEntityCfg[{_source_id(source)!r}].gain_db",
                )
                for source in source_cfgs
            ),
            dtype=torch.float32,
            device=device,
        ),
        source_directivity_coefficient=torch.tensor(
            tuple(
                DIRECTIVITY_COEFFICIENTS[source.directivity] for source in source_cfgs
            ),
            dtype=torch.float32,
            device=device,
        ),
    )


def _validate_tensor(
    value: torch.Tensor,
    reference: torch.Tensor,
    name: str,
    *,
    shape: tuple[int, ...],
) -> None:
    if value.dtype != torch.float32:
        raise TypeError(f"{name} must use float32.")
    if value.device != reference.device:
        raise ValueError(f"{name} must be on {reference.device}.")
    if tuple(value.shape) != shape:
        raise ValueError(f"{name} must have shape {shape}.")


def _quat_mul(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    lx, ly, lz, lw = left.unbind(dim=-1)
    rx, ry, rz, rw = right.unbind(dim=-1)
    return torch.stack(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dim=-1,
    )


def _rotate(vectors: torch.Tensor, quats: torch.Tensor) -> torch.Tensor:
    zeros = torch.zeros_like(vectors[..., :1])
    vector_quat = torch.cat((vectors, zeros), dim=-1)
    conjugate = torch.cat((-quats[..., :3], quats[..., 3:4]), dim=-1)
    return _quat_mul(_quat_mul(quats, vector_quat), conjugate)[..., :3]


def _normalize(quats: torch.Tensor) -> torch.Tensor:
    return quats / torch.linalg.vector_norm(quats, dim=-1, keepdim=True)


def _source_id(cfg: SourceEntityCfg) -> str:
    return cfg.source_id or cfg.entity_name


def _require_name(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field_name} must be non-empty.")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")
