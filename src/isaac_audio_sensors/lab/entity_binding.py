"""Duck-typed Isaac Lab scene/entity binding for audio observations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_quaternion_xyzw,
    as_vector3,
    basis_from_quaternion,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
    RoomAcousticsSpec,
)

_ROOT_POSE_FIELDS = (
    "root_state_w",
    "root_pos_w",
    "root_quat_w",
)
_BODY_POSE_FIELDS = (
    "body_state_w",
    "body_pos_w",
    "body_quat_w",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class LabAudioSourceEntityCfg:
    """Describe one scene entity/body that should become an audio source."""

    entity_name: str
    body_name: str | None = None
    source_id: str | None = None
    class_label: str = "Sound"
    audio_asset_path: str | None = "generated://impulse"
    start_time_s: float = 0.0
    duration_s: float | None = 1.0
    gain_db: float = 0.0
    directivity: str = "omni"
    relative_position_m: Vector3 = (0.0, 0.0, 0.0)
    relative_orientation_quat: Quaternion = (0.0, 0.0, 0.0, 1.0)
    prim_path: str | None = None

    def __post_init__(self) -> None:
        _require_name(self.entity_name, "LabAudioSourceEntityCfg.entity_name")
        if self.body_name is not None:
            _require_name(self.body_name, "LabAudioSourceEntityCfg.body_name")
        if self.source_id is not None:
            _require_name(self.source_id, "LabAudioSourceEntityCfg.source_id")
        _require_name(self.class_label, "LabAudioSourceEntityCfg.class_label")
        _require_name(self.directivity, "LabAudioSourceEntityCfg.directivity")
        object.__setattr__(
            self,
            "relative_position_m",
            as_vector3(
                self.relative_position_m,
                "LabAudioSourceEntityCfg.relative_position_m",
            ),
        )
        object.__setattr__(
            self,
            "relative_orientation_quat",
            as_quaternion_xyzw(
                self.relative_orientation_quat,
                "LabAudioSourceEntityCfg.relative_orientation_quat",
            ),
        )
        _require_finite(self.start_time_s, "LabAudioSourceEntityCfg.start_time_s")
        _require_finite(self.gain_db, "LabAudioSourceEntityCfg.gain_db")
        if self.duration_s is not None:
            _require_finite(self.duration_s, "LabAudioSourceEntityCfg.duration_s")
            if self.duration_s <= 0.0:
                raise ValueError("LabAudioSourceEntityCfg.duration_s must be positive.")
        if self.prim_path is not None:
            _require_name(self.prim_path, "LabAudioSourceEntityCfg.prim_path")


@dataclass(frozen=True, slots=True, kw_only=True)
class LabAudioEntityBindingCfg:
    """Bind audio arrays and sources to Isaac Lab scene entities/tensors."""

    num_envs: int | None = None
    scene: Any | None = None
    env: Any | None = None
    robot_entity_name: str = "robot"
    array_mount_body_name: str | None = None
    array_id: str = "audio_array"
    array_prim_path: str | None = None
    array_relative_position_m: Vector3 = (0.0, 0.0, 0.0)
    array_relative_orientation_quat: Quaternion = (0.0, 0.0, 0.0, 1.0)
    microphone_layout: str | None = "quad_front"
    microphone_relative_offsets_m: tuple[tuple[str, Vector3], ...] | None = None
    source_entities: tuple[LabAudioSourceEntityCfg, ...] = ()
    env_namespace_pattern: str | None = "/World/envs/env_{env_id}"
    state_position_frame: Literal["world", "env"] = "world"
    env_origins: Any | None = None
    device: str | None = None
    state_quat_order: Literal["wxyz", "xyzw"] = "wxyz"
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    stage_id: str = "isaac_lab_entity_scene"
    allow_scene_num_envs: bool = True
    diagnostics: bool = True
    # Entity scenes carry no USD stage to anchor a room to; an explicit spec
    # (with origin_m placing it in world space) enables room_acoustics here.
    room: RoomAcousticsSpec | None = None

    def __post_init__(self) -> None:
        if self.num_envs is not None and int(self.num_envs) <= 0:
            raise ValueError("LabAudioEntityBindingCfg.num_envs must be positive.")
        _require_name(self.robot_entity_name, "robot_entity_name")
        _require_name(self.array_id, "array_id")
        if self.array_mount_body_name is not None:
            _require_name(self.array_mount_body_name, "array_mount_body_name")
        if self.array_prim_path is not None:
            _require_name(self.array_prim_path, "array_prim_path")
        object.__setattr__(
            self,
            "array_relative_position_m",
            as_vector3(
                self.array_relative_position_m,
                "LabAudioEntityBindingCfg.array_relative_position_m",
            ),
        )
        object.__setattr__(
            self,
            "array_relative_orientation_quat",
            as_quaternion_xyzw(
                self.array_relative_orientation_quat,
                "LabAudioEntityBindingCfg.array_relative_orientation_quat",
            ),
        )
        if self.microphone_layout is None and not self.microphone_relative_offsets_m:
            raise ValueError(
                "Provide microphone_layout or microphone_relative_offsets_m."
            )
        if not self.source_entities:
            raise ValueError("LabAudioEntityBindingCfg.source_entities is required.")
        if self.state_position_frame not in {"world", "env"}:
            raise ValueError("state_position_frame must be 'world' or 'env'.")
        if self.state_quat_order not in {"wxyz", "xyzw"}:
            raise ValueError("state_quat_order must be 'wxyz' or 'xyzw'.")
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("sample_rate_hz must be positive.")
        if self.env_namespace_pattern is not None:
            _require_name(self.env_namespace_pattern, "env_namespace_pattern")
        if self.device is not None:
            _require_name(self.device, "device")
        _require_name(self.stage_id, "stage_id")
        if self.microphone_relative_offsets_m is not None:
            normalized = []
            for mic_id, position in self.microphone_relative_offsets_m:
                _require_name(str(mic_id), "microphone id")
                normalized.append(
                    (
                        str(mic_id),
                        as_vector3(position, "microphone_relative_offsets_m"),
                    )
                )
            object.__setattr__(
                self,
                "microphone_relative_offsets_m",
                tuple(normalized),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class _PoseBatch:
    positions_world: Any
    orientations_world_xyzw: Any
    provenance: str
    body_index: int | None
    body_names: tuple[str, ...]
    tensor_device: str
    env_origin_applied: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityStaticBatchMeta:
    """Per-binding constants for the batched compute path.

    The source axis is pre-sorted with the same key ``active_sources`` uses
    (``start_time_s, source_id, prim_path``) so batched event slots match the
    scalar path without per-frame sorting.
    """

    mic_ids: tuple[str, ...]
    mic_offsets_local: Any
    mic_gains_db: Any
    source_ids: tuple[str, ...]
    class_labels: tuple[str, ...]
    source_start_s: Any
    source_end_s: Any
    source_gain_scale: Any
    source_is_cardioid: Any
    sort_permutation: tuple[int, ...]
    tensor_device: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityPoseTensorBatch:
    """Selected-env pose tensors for the batched compute path."""

    env_ids: Any
    array_positions: Any
    array_quats_xyzw: Any
    source_positions: Any
    source_quats_xyzw: Any
    static: EntityStaticBatchMeta


class LabAudioEntityProvider:
    """Callable provider that reads selected Lab entity tensor rows."""

    diagnostics_key = "entity_binding"

    def __init__(
        self,
        *,
        scene: Any | None,
        binding_cfg: LabAudioEntityBindingCfg,
    ) -> None:
        self.cfg = binding_cfg
        self.scene = resolve_lab_entity_scene(
            scene=scene,
            env=binding_cfg.env,
            fallback_scene=binding_cfg.scene,
        )
        self.num_envs = resolve_lab_entity_num_envs(
            binding_cfg=binding_cfg,
            owner=self.scene,
        )
        self.last_diagnostics: dict[int, dict[str, Any]] = {}
        self.read_counts: dict[int, int] = {
            env_id: 0 for env_id in range(self.num_envs)
        }
        self._sim_time_s_by_env: dict[int, float] = {}
        self._static_batch_meta: EntityStaticBatchMeta | None = None
        self._sorted_source_cfgs: tuple[LabAudioSourceEntityCfg, ...] | None = None

    @property
    def num_mics(self) -> int:
        """Return the configured microphone count."""

        if self.cfg.microphone_relative_offsets_m is not None:
            return len(self.cfg.microphone_relative_offsets_m)
        if self.cfg.microphone_layout is None:
            return 0
        return len(microphone_layout(self.cfg.microphone_layout))

    def set_update_context(
        self,
        *,
        sim_time_s_by_env: Mapping[int, float] | None = None,
    ) -> None:
        """Receive the current sensor time before a selected-env call."""

        if sim_time_s_by_env is None:
            self._sim_time_s_by_env = {}
            return
        self._sim_time_s_by_env = {
            int(env_id): float(sim_time_s)
            for env_id, sim_time_s in sim_time_s_by_env.items()
        }

    def __call__(
        self,
        env_ids: Sequence[int],
    ) -> Mapping[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]]:
        ids = tuple(int(env_id) for env_id in env_ids)
        for env_id in ids:
            if env_id < 0 or env_id >= self.num_envs:
                raise ValueError(
                    f"env_id {env_id} is outside configured entity range "
                    f"[0, {self.num_envs - 1}]."
                )
            self.read_counts[env_id] = self.read_counts.get(env_id, 0) + 1

        robot = resolve_scene_entity(self.scene, self.cfg.robot_entity_name)
        robot_pose = _resolve_entity_pose_batch(
            scene=self.scene,
            entity=robot,
            entity_name=self.cfg.robot_entity_name,
            body_name=self.cfg.array_mount_body_name,
            env_ids=ids,
            binding_cfg=self.cfg,
            required_for="array",
        )
        array_pose = _compose_relative_pose_batch(
            base_pose=robot_pose,
            relative_position_m=self.cfg.array_relative_position_m,
            relative_orientation_quat=self.cfg.array_relative_orientation_quat,
        )

        source_batches = []
        for source_cfg in self.cfg.source_entities:
            source_entity = resolve_scene_entity(self.scene, source_cfg.entity_name)
            source_pose = _resolve_entity_pose_batch(
                scene=self.scene,
                entity=source_entity,
                entity_name=source_cfg.entity_name,
                body_name=source_cfg.body_name,
                env_ids=ids,
                binding_cfg=self.cfg,
                required_for=f"source {source_cfg.entity_name}",
            )
            source_batches.append(
                (
                    source_cfg,
                    _compose_relative_pose_batch(
                        base_pose=source_pose,
                        relative_position_m=source_cfg.relative_position_m,
                        relative_orientation_quat=source_cfg.relative_orientation_quat,
                    ),
                    source_pose,
                )
            )

        result: dict[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]] = {}
        diagnostics: dict[int, dict[str, Any]] = {}
        for row_index, env_id in enumerate(ids):
            array = _array_for_env(
                binding_cfg=self.cfg,
                pose_batch=array_pose,
                env_id=env_id,
                row_index=row_index,
                robot_pose=robot_pose,
            )
            sources = tuple(
                _source_for_env(
                    source_cfg=source_cfg,
                    pose_batch=source_world_pose,
                    base_pose=source_base_pose,
                    env_id=env_id,
                    row_index=row_index,
                    source_index=source_index,
                    binding_cfg=self.cfg,
                )
                for source_index, (
                    source_cfg,
                    source_world_pose,
                    source_base_pose,
                ) in enumerate(source_batches)
            )
            timestamp_ms = int(round(self._sim_time_s_by_env.get(env_id, 0.0) * 1000.0))
            snapshot = AudioSceneSnapshot(
                stage_id=f"{self.cfg.stage_id}:env_{env_id}",
                timestamp_ms=timestamp_ms,
                sources=sources,
                arrays=(array,),
                room=self.cfg.room,
            )
            result[env_id] = (snapshot, array)
            if self.cfg.diagnostics:
                diagnostics[env_id] = _diagnostics_for_env(
                    binding_cfg=self.cfg,
                    env_id=env_id,
                    row_index=row_index,
                    robot_pose=robot_pose,
                    array_pose=array_pose,
                    source_batches=source_batches,
                    array=array,
                    sources=sources,
                    read_count=self.read_counts[env_id],
                )
        self.last_diagnostics = diagnostics
        return result

    def static_batch_meta(self, *, device: str) -> EntityStaticBatchMeta:
        """Return cached per-binding constants on the requested device."""

        cached = self._static_batch_meta
        if cached is not None and cached.tensor_device == str(device):
            return cached
        torch = _require_torch()
        microphones = _microphones(self.cfg)
        permutation = self._source_sort_permutation()
        sorted_cfgs = self._source_cfgs_sorted()
        source_ids = tuple(
            _resolved_source_id(source_cfg) for source_cfg in sorted_cfgs
        )
        start_s = [float(source_cfg.start_time_s) for source_cfg in sorted_cfgs]
        end_s = [
            math.inf
            if source_cfg.duration_s is None
            else float(source_cfg.start_time_s) + float(source_cfg.duration_s)
            for source_cfg in sorted_cfgs
        ]
        meta = EntityStaticBatchMeta(
            mic_ids=tuple(microphone.mic_id for microphone in microphones),
            mic_offsets_local=torch.tensor(
                [microphone.relative_position_m for microphone in microphones],
                dtype=torch.float32,
                device=device,
            ),
            mic_gains_db=torch.tensor(
                [float(microphone.gain_db) for microphone in microphones],
                dtype=torch.float32,
                device=device,
            ),
            source_ids=source_ids,
            class_labels=tuple(
                source_cfg.class_label for source_cfg in sorted_cfgs
            ),
            source_start_s=torch.tensor(
                start_s,
                dtype=torch.float32,
                device=device,
            ),
            source_end_s=torch.tensor(
                end_s,
                dtype=torch.float32,
                device=device,
            ),
            source_gain_scale=torch.tensor(
                [
                    10.0 ** (float(source_cfg.gain_db) / 20.0)
                    for source_cfg in sorted_cfgs
                ],
                dtype=torch.float32,
                device=device,
            ),
            source_is_cardioid=torch.tensor(
                [source_cfg.directivity == "cardioid" for source_cfg in sorted_cfgs],
                dtype=torch.bool,
                device=device,
            ),
            sort_permutation=permutation,
            tensor_device=str(device),
        )
        self._static_batch_meta = meta
        return meta

    def pose_tensor_batch(self, env_ids: Sequence[int]) -> EntityPoseTensorBatch:
        """Read selected-env poses as tensors without snapshot construction.

        This is the batched-compute counterpart of ``__call__``: identical pose
        math (`_resolve_entity_pose_batch` + `_compose_relative_pose_batch`),
        but the tensors never leave the device and no per-env dataclasses or
        diagnostics are built.
        """

        torch = _require_torch()
        ids = tuple(int(env_id) for env_id in env_ids)
        for env_id in ids:
            if env_id < 0 or env_id >= self.num_envs:
                raise ValueError(
                    f"env_id {env_id} is outside configured entity range "
                    f"[0, {self.num_envs - 1}]."
                )
            self.read_counts[env_id] = self.read_counts.get(env_id, 0) + 1

        robot = resolve_scene_entity(self.scene, self.cfg.robot_entity_name)
        robot_pose = _resolve_entity_pose_batch(
            scene=self.scene,
            entity=robot,
            entity_name=self.cfg.robot_entity_name,
            body_name=self.cfg.array_mount_body_name,
            env_ids=ids,
            binding_cfg=self.cfg,
            required_for="array",
        )
        array_pose = _compose_relative_pose_batch(
            base_pose=robot_pose,
            relative_position_m=self.cfg.array_relative_position_m,
            relative_orientation_quat=self.cfg.array_relative_orientation_quat,
        )
        source_positions = []
        source_quats = []
        for source_cfg in self._source_cfgs_sorted():
            source_entity = resolve_scene_entity(self.scene, source_cfg.entity_name)
            source_pose = _resolve_entity_pose_batch(
                scene=self.scene,
                entity=source_entity,
                entity_name=source_cfg.entity_name,
                body_name=source_cfg.body_name,
                env_ids=ids,
                binding_cfg=self.cfg,
                required_for=f"source {source_cfg.entity_name}",
            )
            world_pose = _compose_relative_pose_batch(
                base_pose=source_pose,
                relative_position_m=source_cfg.relative_position_m,
                relative_orientation_quat=source_cfg.relative_orientation_quat,
            )
            source_positions.append(world_pose.positions_world)
            source_quats.append(world_pose.orientations_world_xyzw)
        device = str(array_pose.positions_world.device)
        return EntityPoseTensorBatch(
            env_ids=torch.tensor(ids, dtype=torch.long, device=device),
            array_positions=array_pose.positions_world,
            array_quats_xyzw=array_pose.orientations_world_xyzw,
            source_positions=torch.stack(source_positions, dim=1),
            source_quats_xyzw=torch.stack(source_quats, dim=1),
            static=self.static_batch_meta(device=device),
        )

    def _source_cfgs_sorted(self) -> tuple[LabAudioSourceEntityCfg, ...]:
        if self._sorted_source_cfgs is None:
            permutation = self._source_sort_permutation()
            self._sorted_source_cfgs = tuple(
                self.cfg.source_entities[index] for index in permutation
            )
        return self._sorted_source_cfgs

    def _source_sort_permutation(self) -> tuple[int, ...]:
        # Mirror active_sources ordering. Unique source ids make
        # (start_time_s, source_id) a total order; the env-0 prim path
        # tie-break is unreachable but kept for key-shape parity.
        return tuple(
            sorted(
                range(len(self.cfg.source_entities)),
                key=lambda index: (
                    float(self.cfg.source_entities[index].start_time_s),
                    _resolved_source_id(self.cfg.source_entities[index]),
                    _source_prim_path(
                        self.cfg.source_entities[index],
                        self.cfg,
                        0,
                    ),
                ),
            )
        )


def _resolved_source_id(source_cfg: LabAudioSourceEntityCfg) -> str:
    if source_cfg.source_id is not None:
        return source_cfg.source_id
    return f"{source_cfg.entity_name}_{source_cfg.body_name or 'root'}"


def build_lab_entity_provider(
    *,
    scene: Any | None,
    binding_cfg: LabAudioEntityBindingCfg,
) -> LabAudioEntityProvider:
    """Create an env-id provider for Isaac Lab entity tensor bindings."""

    return LabAudioEntityProvider(scene=scene, binding_cfg=binding_cfg)


def resolve_lab_entity_scene(
    *,
    scene: Any | None = None,
    env: Any | None = None,
    fallback_scene: Any | None = None,
) -> Any:
    """Resolve a common Isaac Lab scene object from scene/env wrappers."""

    for candidate in (scene, fallback_scene):
        if candidate is not None:
            return candidate
    if env is not None:
        direct_scene = getattr(env, "scene", None)
        if direct_scene is not None:
            return direct_scene
        unwrapped = getattr(env, "unwrapped", None)
        if unwrapped is not None:
            unwrapped_scene = getattr(unwrapped, "scene", None)
            if unwrapped_scene is not None:
                return unwrapped_scene
    raise ValueError(
        "Could not resolve an Isaac Lab scene. Provide scene=..., "
        "binding_cfg.scene, or an env with .scene/.unwrapped.scene."
    )


def resolve_lab_entity_num_envs(
    *,
    binding_cfg: LabAudioEntityBindingCfg,
    owner: Any | None,
    num_envs: int | None = None,
) -> int:
    """Resolve clone count from config first, then common scene/env attributes."""

    candidates: list[Any] = [num_envs, binding_cfg.num_envs]
    if binding_cfg.allow_scene_num_envs:
        candidates.extend(
            (
                getattr(owner, "num_envs", None),
                getattr(getattr(owner, "env", None), "num_envs", None),
                getattr(getattr(owner, "unwrapped", None), "num_envs", None),
            )
        )
    for value in candidates:
        if value is None:
            continue
        resolved = int(value)
        if resolved <= 0:
            raise ValueError("Resolved num_envs must be positive.")
        return resolved
    raise ValueError(
        "Could not resolve num_envs for LabAudioEntityBindingCfg. Set "
        "num_envs explicitly or expose scene.num_envs/env.num_envs."
    )


def resolve_scene_entity(scene: Any, entity_name: str) -> Any:
    """Resolve a scene entity by name using common Isaac Lab lookup patterns."""

    _require_name(entity_name, "entity_name")
    if isinstance(scene, Mapping) and entity_name in scene:
        return scene[entity_name]
    getitem = getattr(scene, "__getitem__", None)
    if callable(getitem):
        try:
            return scene[entity_name]
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
    if hasattr(scene, entity_name):
        return getattr(scene, entity_name)
    for container_name in (
        "articulations",
        "rigid_objects",
        "rigid_object_collections",
    ):
        container = getattr(scene, container_name, None)
        if container is None:
            continue
        if isinstance(container, Mapping) and entity_name in container:
            return container[entity_name]
        container_getitem = getattr(container, "__getitem__", None)
        if callable(container_getitem):
            try:
                return container[entity_name]
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
        if hasattr(container, entity_name):
            return getattr(container, entity_name)
    raise ValueError(
        f"Could not resolve scene entity {entity_name!r}. Expected scene[name], "
        f"scene.{entity_name}, scene.articulations[name], "
        "scene.rigid_objects[name], or scene.rigid_object_collections[name]."
    )


def _resolve_entity_pose_batch(
    *,
    scene: Any,
    entity: Any,
    entity_name: str,
    body_name: str | None,
    env_ids: tuple[int, ...],
    binding_cfg: LabAudioEntityBindingCfg,
    required_for: str,
) -> _PoseBatch:
    device = binding_cfg.device
    body_names = _body_names(entity)
    body_index = _body_index(body_names, body_name, entity_name)
    if body_name is None:
        positions, quats, provenance = _root_pose_tensors(
            entity=entity,
            entity_name=entity_name,
            required_for=required_for,
            device=device,
        )
    else:
        positions, quats, provenance = _body_pose_tensors(
            entity=entity,
            entity_name=entity_name,
            body_name=body_name,
            body_index=body_index,
            required_for=required_for,
            device=device,
        )
    selected_positions = _select_env_rows(positions, env_ids, device=device)
    selected_quats = _select_env_rows(quats, env_ids, device=device)
    selected_quats = _quats_to_xyzw(
        selected_quats,
        order=binding_cfg.state_quat_order,
    )
    selected_quats = _normalize_quat_batch(selected_quats)
    origin_applied = False
    if binding_cfg.state_position_frame == "env":
        origins = _resolve_env_origins(
            scene=scene,
            env_ids=env_ids,
            binding_cfg=binding_cfg,
            device=str(selected_positions.device),
        )
        selected_positions = selected_positions + origins
        origin_applied = True
    return _PoseBatch(
        positions_world=selected_positions,
        orientations_world_xyzw=selected_quats,
        provenance=provenance,
        body_index=body_index,
        body_names=body_names,
        tensor_device=str(selected_positions.device),
        env_origin_applied=origin_applied,
    )


def _root_pose_tensors(
    *,
    entity: Any,
    entity_name: str,
    required_for: str,
    device: str | None,
) -> tuple[Any, Any, str]:
    state = _first_attr(entity, ("root_state_w",), device=device)
    if state is not None:
        if len(tuple(state.shape)) < 2 or int(state.shape[-1]) < 7:
            raise ValueError(
                f"{entity_name!r}.root_state_w for {required_for} must have "
                "shape [num_envs, >=7]."
            )
        return state[..., 0:3], state[..., 3:7], "root_state_w"
    pos = _first_attr(entity, ("root_pos_w",), device=device)
    quat = _first_attr(entity, ("root_quat_w",), device=device)
    if pos is not None and quat is not None:
        return pos, quat, "root_pos_w+root_quat_w"
    _raise_missing_pose(
        entity_name=entity_name,
        body_name=None,
        required_for=required_for,
        expected=_ROOT_POSE_FIELDS,
    )


def _body_pose_tensors(
    *,
    entity: Any,
    entity_name: str,
    body_name: str,
    body_index: int | None,
    required_for: str,
    device: str | None,
) -> tuple[Any, Any, str]:
    if body_index is None:
        raise ValueError(
            f"Could not resolve body/link {body_name!r} on entity "
            f"{entity_name!r}; no body_names/link_names are available."
        )
    state = _first_attr(entity, ("body_state_w",), device=device)
    if state is not None:
        shape = tuple(state.shape)
        if len(shape) < 3 or int(shape[-1]) < 7:
            raise ValueError(
                f"{entity_name!r}.body_state_w for {required_for} must have "
                "shape [num_envs, num_bodies, >=7]."
            )
        return (
            state[:, body_index, 0:3],
            state[:, body_index, 3:7],
            f"body_state_w[{body_name}]",
        )
    pos = _first_attr(entity, ("body_pos_w",), device=device)
    quat = _first_attr(entity, ("body_quat_w",), device=device)
    if pos is not None and quat is not None:
        return (
            pos[:, body_index, :],
            quat[:, body_index, :],
            f"body_pos_w+body_quat_w[{body_name}]",
        )
    _raise_missing_pose(
        entity_name=entity_name,
        body_name=body_name,
        required_for=required_for,
        expected=_BODY_POSE_FIELDS,
    )


def _first_attr(entity: Any, names: tuple[str, ...], *, device: str | None) -> Any:
    for owner in _entity_data_candidates(entity):
        for name in names:
            if hasattr(owner, name):
                value = getattr(owner, name)
                if value is not None:
                    return _as_tensor(value, device=device)
    return None


def _entity_data_candidates(entity: Any) -> tuple[Any, ...]:
    data = getattr(entity, "data", None)
    if data is None:
        return (entity,)
    return (data, entity)


def _body_names(entity: Any) -> tuple[str, ...]:
    for owner in _entity_data_candidates(entity):
        for attr_name in ("body_names", "link_names"):
            value = getattr(owner, attr_name, None)
            if value is not None:
                return tuple(str(item) for item in value)
    return ()


def _body_index(
    body_names: tuple[str, ...],
    body_name: str | None,
    entity_name: str,
) -> int | None:
    if body_name is None:
        return None
    if not body_names:
        return None
    try:
        return body_names.index(body_name)
    except ValueError as exc:
        raise ValueError(
            f"Entity {entity_name!r} has no body/link {body_name!r}. "
            f"Available bodies: {body_names}."
        ) from exc


def _compose_relative_pose_batch(
    *,
    base_pose: _PoseBatch,
    relative_position_m: Vector3,
    relative_orientation_quat: Quaternion,
) -> _PoseBatch:
    torch = _require_torch()
    rel_pos = torch.tensor(
        relative_position_m,
        dtype=base_pose.positions_world.dtype,
        device=base_pose.positions_world.device,
    ).expand_as(base_pose.positions_world)
    rel_quat = torch.tensor(
        relative_orientation_quat,
        dtype=base_pose.orientations_world_xyzw.dtype,
        device=base_pose.orientations_world_xyzw.device,
    ).expand_as(base_pose.orientations_world_xyzw)
    rotated_offset = _torch_rotate_vectors_xyzw(
        rel_pos,
        base_pose.orientations_world_xyzw,
    )
    composed_quat = _normalize_quat_batch(
        _torch_quat_multiply_xyzw(
            base_pose.orientations_world_xyzw,
            rel_quat,
        )
    )
    return _PoseBatch(
        positions_world=base_pose.positions_world + rotated_offset,
        orientations_world_xyzw=composed_quat,
        provenance=base_pose.provenance,
        body_index=base_pose.body_index,
        body_names=base_pose.body_names,
        tensor_device=base_pose.tensor_device,
        env_origin_applied=base_pose.env_origin_applied,
    )


def _array_for_env(
    *,
    binding_cfg: LabAudioEntityBindingCfg,
    pose_batch: _PoseBatch,
    env_id: int,
    row_index: int,
    robot_pose: _PoseBatch,
) -> MicrophoneArraySpec:
    position = _row_vec3(pose_batch.positions_world, row_index)
    orientation = _row_quat(pose_batch.orientations_world_xyzw, row_index)
    return MicrophoneArraySpec(
        array_id=f"{binding_cfg.array_id}_{env_id}",
        prim_path=_array_prim_path(binding_cfg, env_id),
        position_world=position,
        orientation_world_quat=orientation,
        microphones=_microphones(binding_cfg),
        sample_rate_hz=int(binding_cfg.sample_rate_hz),
        coordinate_convention=COORDINATE_CONVENTION,
    )


def _source_for_env(
    *,
    source_cfg: LabAudioSourceEntityCfg,
    pose_batch: _PoseBatch,
    base_pose: _PoseBatch,
    env_id: int,
    row_index: int,
    source_index: int,
    binding_cfg: LabAudioEntityBindingCfg,
) -> AudioSourceSpec:
    source_id = _resolved_source_id(source_cfg)
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=_source_prim_path(source_cfg, binding_cfg, env_id),
        class_label=source_cfg.class_label,
        audio_asset_path=source_cfg.audio_asset_path,
        position_world=_row_vec3(pose_batch.positions_world, row_index),
        orientation_world_quat=_row_quat(
            pose_batch.orientations_world_xyzw,
            row_index,
        ),
        start_time_s=source_cfg.start_time_s,
        duration_s=source_cfg.duration_s,
        gain_db=source_cfg.gain_db,
        directivity=source_cfg.directivity,
    )


def _microphones(
    binding_cfg: LabAudioEntityBindingCfg,
) -> tuple[MicrophoneSpec, ...]:
    if binding_cfg.microphone_relative_offsets_m is not None:
        return tuple(
            MicrophoneSpec(mic_id=mic_id, relative_position_m=position)
            for mic_id, position in binding_cfg.microphone_relative_offsets_m
        )
    if binding_cfg.microphone_layout is None:
        raise ValueError("microphone_layout is required without explicit offsets.")
    return microphone_layout(binding_cfg.microphone_layout)


def _array_prim_path(binding_cfg: LabAudioEntityBindingCfg, env_id: int) -> str:
    if binding_cfg.array_prim_path is not None:
        return _format_env_path(binding_cfg.array_prim_path, binding_cfg, env_id)
    env_ns = _env_namespace(binding_cfg, env_id)
    body = binding_cfg.array_mount_body_name or "root"
    return f"{env_ns}/{binding_cfg.robot_entity_name}/{body}/{binding_cfg.array_id}"


def _source_prim_path(
    source_cfg: LabAudioSourceEntityCfg,
    binding_cfg: LabAudioEntityBindingCfg,
    env_id: int,
) -> str:
    if source_cfg.prim_path is not None:
        return _format_env_path(source_cfg.prim_path, binding_cfg, env_id)
    env_ns = _env_namespace(binding_cfg, env_id)
    body = source_cfg.body_name or "root"
    return f"{env_ns}/{source_cfg.entity_name}/{body}"


def _format_env_path(
    path: str,
    binding_cfg: LabAudioEntityBindingCfg,
    env_id: int,
) -> str:
    env_ns = _env_namespace(binding_cfg, env_id)
    formatted = path.format(
        env_id=env_id,
        ENV_ID=env_id,
        ENV_NS=env_ns,
        ENV_REGEX_NS=env_ns,
    )
    if formatted.startswith("/") or binding_cfg.env_namespace_pattern is None:
        return formatted
    return f"{env_ns}/{formatted.lstrip('/')}"


def _env_namespace(binding_cfg: LabAudioEntityBindingCfg, env_id: int) -> str:
    pattern = binding_cfg.env_namespace_pattern
    if pattern is None:
        return f"env_{env_id}"
    return pattern.format(
        env_id=env_id,
        ENV_ID=env_id,
        ENV_NS=f"env_{env_id}",
    ).rstrip("/")


def _resolve_env_origins(
    *,
    scene: Any,
    env_ids: tuple[int, ...],
    binding_cfg: LabAudioEntityBindingCfg,
    device: str,
) -> Any:
    value = binding_cfg.env_origins
    if value is None:
        value = getattr(scene, "env_origins", None)
    if value is None:
        raise ValueError(
            "LabAudioEntityBindingCfg.state_position_frame='env' requires "
            "env_origins in the config or scene.env_origins."
        )
    origins = _as_tensor(value, device=device)
    shape = tuple(origins.shape)
    if len(shape) < 2 or int(shape[-1]) != 3:
        raise ValueError("env_origins must have shape [num_envs, 3].")
    return _select_env_rows(origins, env_ids, device=device)


def _diagnostics_for_env(
    *,
    binding_cfg: LabAudioEntityBindingCfg,
    env_id: int,
    row_index: int,
    robot_pose: _PoseBatch,
    array_pose: _PoseBatch,
    source_batches: list[tuple[LabAudioSourceEntityCfg, _PoseBatch, _PoseBatch]],
    array: MicrophoneArraySpec,
    sources: tuple[AudioSourceSpec, ...],
    read_count: int,
) -> dict[str, Any]:
    forward, right, up = basis_from_quaternion(array.orientation_world_quat)
    return {
        "mode": "lab_entity_binding",
        "env_id": env_id,
        "env_namespace": _env_namespace(binding_cfg, env_id),
        "read_count": read_count,
        "robot_entity_name": binding_cfg.robot_entity_name,
        "array_mount_body_name": binding_cfg.array_mount_body_name,
        "array_body_index": robot_pose.body_index,
        "array_body_pose_source": robot_pose.provenance,
        "array_relative_pose": {
            "position_m": binding_cfg.array_relative_position_m,
            "orientation_xyzw": binding_cfg.array_relative_orientation_quat,
        },
        "array_world_pose": {
            "position_m": _row_vec3(array_pose.positions_world, row_index),
            "orientation_xyzw": _row_quat(
                array_pose.orientations_world_xyzw,
                row_index,
            ),
            "forward_vec_world": forward,
            "right_vec_world": right,
            "up_vec_world": up,
        },
        "source_entities": tuple(
            {
                "source_id": source.source_id,
                "entity_name": source_cfg.entity_name,
                "body_name": source_cfg.body_name,
                "body_index": source_base_pose.body_index,
                "pose_source": source_base_pose.provenance,
                "relative_pose": {
                    "position_m": source_cfg.relative_position_m,
                    "orientation_xyzw": source_cfg.relative_orientation_quat,
                },
                "world_pose": {
                    "position_m": source.position_world,
                    "orientation_xyzw": source.orientation_world_quat,
                },
            }
            for source, (source_cfg, _source_world_pose, source_base_pose) in zip(
                sources,
                source_batches,
                strict=True,
            )
        ),
        "source_count": len(sources),
        "state_position_frame": binding_cfg.state_position_frame,
        "env_origin_applied": array_pose.env_origin_applied,
        "state_quat_order": binding_cfg.state_quat_order,
        "tensor_device": array_pose.tensor_device,
    }


def _as_tensor(value: Any, *, device: str | None) -> Any:
    torch = _require_torch()
    if hasattr(value, "detach") and hasattr(value, "shape"):
        if device is not None and str(value.device) != str(device):
            return value.to(device)
        return value
    return torch.as_tensor(value, dtype=torch.float32, device=device)


def _select_env_rows(
    value: Any,
    env_ids: tuple[int, ...],
    *,
    device: str | None,
) -> Any:
    torch = _require_torch()
    tensor = _as_tensor(value, device=device)
    index = torch.tensor(env_ids, dtype=torch.long, device=tensor.device)
    return tensor.index_select(0, index)


def _quats_to_xyzw(value: Any, *, order: str) -> Any:
    if order == "xyzw":
        return value
    if order == "wxyz":
        return value[..., (1, 2, 3, 0)]
    raise ValueError("state_quat_order must be 'wxyz' or 'xyzw'.")


def _normalize_quat_batch(value: Any) -> Any:
    torch = _require_torch()
    norm = torch.linalg.norm(value, dim=-1, keepdim=True)
    if bool((norm <= 1e-12).any().detach().cpu().item()):
        raise ValueError("State quaternion tensor contains a zero quaternion.")
    return value / norm


def _torch_quat_multiply_xyzw(left: Any, right: Any) -> Any:
    torch = _require_torch()
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


def _torch_rotate_vectors_xyzw(vectors: Any, quats: Any) -> Any:
    torch = _require_torch()
    zeros = torch.zeros(
        (*vectors.shape[:-1], 1),
        dtype=vectors.dtype,
        device=vectors.device,
    )
    qvec = torch.cat((vectors, zeros), dim=-1)
    qconj = torch.cat((-quats[..., :3], quats[..., 3:4]), dim=-1)
    return _torch_quat_multiply_xyzw(
        _torch_quat_multiply_xyzw(quats, qvec),
        qconj,
    )[..., :3]


def _row_vec3(tensor: Any, row_index: int) -> Vector3:
    return as_vector3(
        tensor[int(row_index)].detach().cpu().tolist(),
        "entity pose position",
    )


def _row_quat(tensor: Any, row_index: int) -> Quaternion:
    return as_quaternion_xyzw(
        tensor[int(row_index)].detach().cpu().tolist(),
        "entity pose orientation",
    )


def _raise_missing_pose(
    *,
    entity_name: str,
    body_name: str | None,
    required_for: str,
    expected: tuple[str, ...],
) -> None:
    body_detail = "" if body_name is None else f" body/link {body_name!r}"
    raise ValueError(
        f"Entity {entity_name!r}{body_detail} for {required_for} is missing pose "
        f"tensors. Expected one of: {', '.join(expected)} on the entity or "
        "entity.data."
    )


def _require_name(value: str, field_name: str) -> None:
    if str(value).strip() == "":
        raise ValueError(f"{field_name} must be non-empty.")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite.")


def _require_torch() -> Any:
    try:
        import torch  # type: ignore

        return torch
    except ImportError as exc:
        raise RuntimeError(
            "Lab entity binding requires torch tensors or torch-convertible "
            "state arrays."
        ) from exc
