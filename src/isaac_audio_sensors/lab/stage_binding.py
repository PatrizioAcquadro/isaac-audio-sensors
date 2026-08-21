"""Cloned-environment USD/stage binding for Isaac Lab audio observations."""

from __future__ import annotations

import fnmatch
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    ROOM_OUT_OF_BOUNDS_POLICIES,
)
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    add,
    as_quaternion_xyzw,
    as_vector3,
    normalize_quaternion,
    quaternion_multiply,
    rotate_vector_by_quaternion,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.room_anchor import room_spec_from_bounds
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.usd_bounds import (
    DEFAULT_SEMANTIC_ABSORPTION,
    resolve_room_absorption,
    world_aligned_bbox,
)

StageProviderResult = Mapping[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]]


@dataclass(frozen=True, slots=True, kw_only=True)
class StageTransform:
    """Resolved world pose for a stage prim."""

    position_world: Vector3
    orientation_world_quat: Quaternion | None
    provenance: str
    time_code: Any | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LabAudioStageBindingCfg:
    """Describe how audio prims are resolved inside cloned Isaac Lab envs."""

    num_envs: int | None = None
    array_prim_path: str | None = None
    source_prim_paths: tuple[str, ...] = ()
    env_namespace_pattern: str = "/World/envs/env_{env_id}"
    source_ids: tuple[str, ...] | None = None
    class_labels: tuple[str, ...] | None = None
    array_id: str = "audio_array"
    microphone_layout: str | None = "quad_front"
    microphone_relative_offsets_m: tuple[tuple[str, Vector3], ...] | None = None
    discover_child_microphones: bool = True
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    default_audio_asset_path: str | None = "generated://impulse"
    default_class_label: str = "Sound"
    discover_arrays: bool = False
    array_discovery_root_path: str | None = None
    preferred_array: str | None = None
    array_discovery_attr_names: tuple[str, ...] = (
        "ias:array_id",
        "ias:layout_name",
    )
    array_discovery_type_name_patterns: tuple[str, ...] = (
        "*AudioArray*",
        "*MicrophoneArray*",
        "*MicArray*",
    )
    array_discovery_name_patterns: tuple[str, ...] = (
        "*audio_array*",
        "*AudioArray*",
        "*microphone_array*",
        "*MicrophoneArray*",
        "*mic_array*",
        "*MicArray*",
    )
    discover_sources: bool = False
    source_discovery_root_path: str | None = None
    source_discovery_attr_names: tuple[str, ...] = (
        "ias:source_id",
        "filePath",
        "inputs:file",
        "inputs:audio",
        "ias:audio_asset_path",
    )
    source_discovery_type_names: tuple[str, ...] = (
        "Sound",
        "AudioSource",
        "OmniAudioSource",
    )
    source_discovery_name_patterns: tuple[str, ...] = (
        "*speaker*",
        "*source*",
        "*sound*",
    )
    allow_scene_num_envs: bool = True
    time_code: Any | None = None
    usd_time_code_scale: float | None = None
    usd_time_code_offset: float = 0.0
    room_prim_path: str | None = None
    room_id: str = "stage_room"
    room_absorption: float | dict[str, float] = 0.35
    room_absorption_from_tags: bool = True
    room_semantic_absorption: tuple[tuple[str, float], ...] = (
        DEFAULT_SEMANTIC_ABSORPTION
    )
    room_max_order: int = 0
    room_out_of_bounds: str = "error"

    def __post_init__(self) -> None:
        if self.num_envs is not None and int(self.num_envs) <= 0:
            raise ValueError("LabAudioStageBindingCfg.num_envs must be positive.")
        if self.array_prim_path is None and not self.discover_arrays:
            raise ValueError("Provide array_prim_path or enable discover_arrays.")
        if self.array_prim_path is not None:
            _require_path(self.array_prim_path, "array_prim_path")
        if not self.source_prim_paths and not self.discover_sources:
            raise ValueError("Provide source_prim_paths or enable discover_sources.")
        for path in self.source_prim_paths:
            _require_path(path, "source_prim_paths")
        if self.source_discovery_root_path is not None:
            _require_path(
                self.source_discovery_root_path,
                "source_discovery_root_path",
            )
        if self.array_discovery_root_path is not None:
            _require_path(
                self.array_discovery_root_path,
                "array_discovery_root_path",
            )
        _require_path(self.env_namespace_pattern, "env_namespace_pattern")
        if (
            self.source_ids is not None
            and self.source_prim_paths
            and len(self.source_ids) != len(self.source_prim_paths)
        ):
            raise ValueError("source_ids must match source_prim_paths length.")
        if (
            self.class_labels is not None
            and self.source_prim_paths
            and len(self.class_labels) != len(self.source_prim_paths)
        ):
            raise ValueError("class_labels must match source_prim_paths length.")
        if (
            self.microphone_layout is None
            and not self.microphone_relative_offsets_m
            and not self.discover_child_microphones
        ):
            raise ValueError(
                "Provide microphone_layout, microphone_relative_offsets_m, or "
                "enable discover_child_microphones."
            )
        if int(self.sample_rate_hz) <= 0:
            raise ValueError("sample_rate_hz must be positive.")
        if self.usd_time_code_scale is not None and not math.isfinite(
            float(self.usd_time_code_scale)
        ):
            raise ValueError("usd_time_code_scale must be finite.")
        if not math.isfinite(float(self.usd_time_code_offset)):
            raise ValueError("usd_time_code_offset must be finite.")
        if self.room_prim_path is not None:
            _require_path(self.room_prim_path, "room_prim_path")
        if not str(self.room_id).strip():
            raise ValueError("room_id must be non-empty.")
        if int(self.room_max_order) < 0:
            raise ValueError("room_max_order must be non-negative.")
        if self.room_out_of_bounds not in ROOM_OUT_OF_BOUNDS_POLICIES:
            raise ValueError(
                "room_out_of_bounds must be one of "
                f"{sorted(ROOM_OUT_OF_BOUNDS_POLICIES)}."
            )


class LabAudioStageProvider:
    """Callable provider that re-reads live stage transforms for env ids."""

    def __init__(
        self,
        *,
        stage: Any,
        binding_cfg: LabAudioStageBindingCfg,
        num_envs: int | None = None,
    ) -> None:
        if stage is None or not hasattr(stage, "Traverse"):
            raise ValueError("stage must provide a Traverse method.")
        self.stage = stage
        self.cfg = binding_cfg
        self.num_envs = _resolve_num_envs(
            binding_cfg=binding_cfg,
            owner=stage,
            num_envs=num_envs,
        )
        self.last_diagnostics: dict[int, dict[str, Any]] = {}
        self._sim_time_s_by_env: dict[int, float] = {}

    @property
    def num_mics(self) -> int:
        """Return the configured microphone count, deriving child mics when needed."""

        if self.cfg.microphone_relative_offsets_m is not None:
            return len(self.cfg.microphone_relative_offsets_m)
        prims_by_path = {_prim_path(prim): prim for prim in _traverse(self.stage)}
        try:
            env_ns = _env_namespace(self.cfg.env_namespace_pattern, 0)
            time_code = self._time_code_for_env(0)
            array_path, _array_discovery = _array_path_for_env(
                binding_cfg=self.cfg,
                prims_by_path=prims_by_path,
                env_namespace=env_ns,
                env_id=0,
                time_code=time_code,
            )
            child_mics = _child_microphones(
                array_path=array_path,
                prims_by_path=prims_by_path,
                time_code=time_code,
            )
            if child_mics:
                return len(child_mics)
        except ValueError:
            if self.cfg.microphone_layout is None:
                raise
        if self.cfg.microphone_layout is None:
            return 0
        return len(microphone_layout(self.cfg.microphone_layout))

    def set_update_context(
        self,
        *,
        sim_time_s_by_env: Mapping[int, float] | None = None,
    ) -> None:
        """Receive the current sensor time before a selected-env provider call."""

        if sim_time_s_by_env is None:
            self._sim_time_s_by_env = {}
            return
        self._sim_time_s_by_env = {
            int(env_id): float(sim_time_s)
            for env_id, sim_time_s in sim_time_s_by_env.items()
        }

    def __call__(self, env_ids: Sequence[int]) -> StageProviderResult:
        prims_by_path = {_prim_path(prim): prim for prim in _traverse(self.stage)}
        result: dict[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]] = {}
        diagnostics: dict[int, dict[str, Any]] = {}
        for env_id in env_ids:
            env_id = int(env_id)
            if env_id < 0 or env_id >= self.num_envs:
                raise ValueError(
                    f"env_id {env_id} is outside configured cloned env range "
                    f"[0, {self.num_envs - 1}]."
                )
            binding, env_diagnostics = self._read_env(env_id, prims_by_path)
            result[env_id] = binding
            diagnostics[env_id] = env_diagnostics
        self.last_diagnostics = diagnostics
        return result

    def _read_env(
        self,
        env_id: int,
        prims_by_path: Mapping[str, Any],
    ) -> tuple[tuple[AudioSceneSnapshot, MicrophoneArraySpec], dict[str, Any]]:
        env_ns = _env_namespace(self.cfg.env_namespace_pattern, env_id)
        time_code = self._time_code_for_env(env_id)
        array_path, array_discovery = _array_path_for_env(
            binding_cfg=self.cfg,
            prims_by_path=prims_by_path,
            env_namespace=env_ns,
            env_id=env_id,
            time_code=time_code,
        )
        array_prim = _required_prim(prims_by_path, array_path, "microphone array")
        array_transform = _resolve_world_transform(
            array_prim,
            prims_by_path=prims_by_path,
            time_code=time_code,
            field_name=array_path,
        )
        array = _array_from_prim(
            array_prim,
            env_id=env_id,
            array_path=array_path,
            transform=array_transform,
            binding_cfg=self.cfg,
            prims_by_path=prims_by_path,
            time_code=time_code,
        )
        source_paths, source_discovery = _source_paths_for_env(
            binding_cfg=self.cfg,
            prims_by_path=prims_by_path,
            env_namespace=env_ns,
            env_id=env_id,
            time_code=time_code,
        )
        sources: list[AudioSourceSpec] = []
        source_diagnostics: dict[str, dict[str, Any]] = {}
        for source_index, source_path in enumerate(source_paths):
            resolved_path = _resolve_env_path(
                source_path,
                env_namespace=env_ns,
                env_id=env_id,
            )
            source_prim = _required_prim(
                prims_by_path,
                resolved_path,
                "audio source",
            )
            source_transform = _resolve_world_transform(
                source_prim,
                prims_by_path=prims_by_path,
                time_code=time_code,
                field_name=resolved_path,
            )
            sources.append(
                _source_from_prim(
                    source_prim,
                    env_id=env_id,
                    source_index=source_index,
                    transform=source_transform,
                    binding_cfg=self.cfg,
                )
            )
            source_diagnostics[resolved_path] = {
                **_transform_diagnostics(source_transform),
                "discovery_reasons": source_discovery.get(resolved_path, ()),
            }
        room, room_diagnostics = _room_for_env(
            binding_cfg=self.cfg,
            prims_by_path=prims_by_path,
            env_namespace=env_ns,
            env_id=env_id,
            time_code=time_code,
        )
        timestamp_ms = int(round(self._sim_time_s_by_env.get(env_id, 0.0) * 1000.0))
        snapshot = AudioSceneSnapshot(
            stage_id=f"{_stage_id(self.stage)}:env_{env_id}",
            timestamp_ms=timestamp_ms,
            sources=tuple(sources),
            arrays=(array,),
            room=room,
        )
        diagnostics = {
            "env_id": env_id,
            "env_namespace": env_ns,
            "time_code": _diagnostic_time_code(time_code),
            "array_prim_path": array_path,
            "array_transform": _transform_diagnostics(array_transform),
            "array_discovery": array_discovery,
            "source_prim_paths": tuple(source_paths),
            "source_discovery": source_discovery,
            "source_transforms": source_diagnostics,
            "source_count": len(sources),
        }
        if room_diagnostics is not None:
            diagnostics["room"] = room_diagnostics
        return (snapshot, array), diagnostics

    def _time_code_for_env(self, env_id: int) -> Any | None:
        if self.cfg.time_code is not None:
            return self.cfg.time_code
        if self.cfg.usd_time_code_scale is None:
            return None
        sim_time_s = self._sim_time_s_by_env.get(int(env_id), 0.0)
        return float(sim_time_s) * float(self.cfg.usd_time_code_scale) + float(
            self.cfg.usd_time_code_offset
        )


def build_lab_stage_provider(
    *,
    stage: Any,
    binding_cfg: LabAudioStageBindingCfg,
    num_envs: int | None = None,
) -> LabAudioStageProvider:
    """Create a provider suitable for ``AudioArraySensor.bind_provider``."""

    return LabAudioStageProvider(
        stage=stage,
        binding_cfg=binding_cfg,
        num_envs=num_envs,
    )


def resolve_lab_stage(owner: object | None = None) -> object:
    """Resolve a USD stage from common Isaac Lab scene/env wrappers."""

    candidates = _stage_owner_candidates(owner)
    for candidate in candidates:
        if candidate is None:
            continue
        if hasattr(candidate, "Traverse"):
            return candidate
        stage = getattr(candidate, "stage", None)
        if stage is not None and hasattr(stage, "Traverse"):
            return stage
        get_stage = getattr(candidate, "get_stage", None)
        if callable(get_stage):
            stage = get_stage()
            if stage is not None and hasattr(stage, "Traverse"):
                return stage
    stage = _omni_context_stage()
    if stage is not None:
        return stage
    raise ValueError(
        "Could not resolve a USD stage. Expected an object with Traverse(), "
        ".stage, .get_stage(), .sim.stage, .world.stage, or a live omni.usd "
        "context."
    )


def resolve_lab_num_envs(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    owner: object | None = None,
    num_envs: int | None = None,
) -> int:
    """Resolve clone count from config first, then common scene/env attributes."""

    return _resolve_num_envs(
        binding_cfg=binding_cfg,
        owner=owner,
        num_envs=num_envs,
    )


def _array_from_prim(
    prim: Any,
    *,
    env_id: int,
    array_path: str,
    transform: StageTransform,
    binding_cfg: LabAudioStageBindingCfg,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> MicrophoneArraySpec:
    attrs = _attrs(prim, time_code=time_code)
    orientation = transform.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
    microphones = _microphones_from_stage_or_cfg(
        binding_cfg=binding_cfg,
        attrs=attrs,
        array_path=array_path,
        prims_by_path=prims_by_path,
        time_code=time_code,
    )
    array_id = str(attrs.get("ias:array_id", f"{binding_cfg.array_id}_{env_id}"))
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=array_path,
        position_world=transform.position_world,
        orientation_world_quat=orientation,
        microphones=microphones,
        sample_rate_hz=int(attrs.get("ias:sample_rate_hz", binding_cfg.sample_rate_hz)),
        coordinate_convention=str(
            attrs.get("ias:coordinate_convention", COORDINATE_CONVENTION)
        ),
    )


def _source_from_prim(
    prim: Any,
    *,
    env_id: int,
    source_index: int,
    transform: StageTransform,
    binding_cfg: LabAudioStageBindingCfg,
) -> AudioSourceSpec:
    attrs = _attrs(prim, time_code=transform.time_code)
    path = _prim_path(prim)
    source_id = _indexed_or_attr(
        binding_cfg.source_ids,
        source_index,
        attrs,
        "ias:source_id",
        default=f"{_path_name(path)}_{env_id}",
    )
    class_label = _indexed_or_attr(
        binding_cfg.class_labels,
        source_index,
        attrs,
        "ias:class_label",
        default=binding_cfg.default_class_label,
    )
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=path,
        class_label=class_label,
        audio_asset_path=_asset_path(
            _first_present(
                attrs,
                (
                    "filePath",
                    "inputs:file",
                    "inputs:audio",
                    "ias:audio_asset_path",
                ),
                default=binding_cfg.default_audio_asset_path,
            )
        ),
        position_world=transform.position_world,
        orientation_world_quat=transform.orientation_world_quat,
        start_time_s=_float_attr(attrs, ("ias:start_time_s", "startTime"), default=0.0),
        duration_s=_optional_float_attr(attrs, ("ias:duration_s", "duration")),
        gain_db=_float_attr(attrs, ("ias:gain_db", "gain"), default=0.0),
        directivity=str(attrs.get("ias:directivity", "omni")),
    )


def _microphones_from_stage_or_cfg(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    attrs: Mapping[str, Any],
    array_path: str,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> tuple[MicrophoneSpec, ...]:
    if binding_cfg.microphone_relative_offsets_m is not None:
        return tuple(
            MicrophoneSpec(
                mic_id=str(mic_id),
                relative_position_m=position,
            )
            for mic_id, position in binding_cfg.microphone_relative_offsets_m
        )
    if binding_cfg.discover_child_microphones:
        child_mics = _child_microphones(
            array_path=array_path,
            prims_by_path=prims_by_path,
            time_code=time_code,
        )
        if child_mics:
            return child_mics
    layout_name = attrs.get("ias:layout_name", binding_cfg.microphone_layout)
    if layout_name is None:
        raise ValueError(
            f"{array_path!r} has no child microphone offsets and no layout name."
        )
    return microphone_layout(str(layout_name))


def _child_microphones(
    *,
    array_path: str,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> tuple[MicrophoneSpec, ...]:
    microphones: list[MicrophoneSpec] = []
    prefix = f"{array_path.rstrip('/')}/"
    for path in sorted(prims_by_path):
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        if "/" in relative:
            continue
        prim = prims_by_path[path]
        attrs = _attrs(prim, time_code=time_code)
        if not _looks_like_microphone_child(attrs, prim):
            continue
        position = _optional_vec3_attr(
            attrs,
            ("ias:relative_position_m", "xformOp:translate"),
        )
        if position is None:
            continue
        orientation = _quat_attr(
            attrs,
            ("ias:relative_orientation_quat", "xformOp:orient"),
            default=None,
        )
        microphones.append(
            MicrophoneSpec(
                mic_id=str(attrs.get("ias:microphone_id", _path_name(path))),
                relative_position_m=position,
                relative_orientation_quat=orientation,
                gain_db=_float_attr(attrs, ("ias:gain_db", "gain"), default=0.0),
                self_noise_db=_optional_float_attr(
                    attrs,
                    ("ias:self_noise_db", "selfNoise"),
                ),
            )
        )
    return tuple(microphones)


def _looks_like_microphone_child(attrs: Mapping[str, Any], prim: Any) -> bool:
    if "ias:microphone_id" in attrs or "ias:relative_position_m" in attrs:
        return True
    type_name = _prim_type_name(prim).lower()
    return "microphone" in type_name or _path_name(_prim_path(prim)).lower() == "mic"


def _source_paths_for_env(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    prims_by_path: Mapping[str, Any],
    env_namespace: str,
    env_id: int,
    time_code: Any | None,
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    if binding_cfg.source_prim_paths:
        resolved = tuple(
            _resolve_env_path(path, env_namespace=env_namespace, env_id=env_id)
            for path in binding_cfg.source_prim_paths
        )
        return binding_cfg.source_prim_paths, {
            path: ("explicit_source_prim_path",) for path in resolved
        }
    root = binding_cfg.source_discovery_root_path
    discovery_root = (
        env_namespace
        if root is None
        else _resolve_env_path(root, env_namespace=env_namespace, env_id=env_id)
    )
    matches: list[str] = []
    diagnostics: dict[str, tuple[str, ...]] = {}
    for path, prim in prims_by_path.items():
        if path == discovery_root or not _is_descendant(path, discovery_root):
            continue
        attrs = _attrs(prim, time_code=time_code)
        reasons = _source_discovery_reasons(path, prim, attrs, binding_cfg)
        if reasons:
            matches.append(path)
            diagnostics[path] = reasons
    if not matches:
        raise ValueError(f"No audio source prims discovered under {discovery_root!r}.")
    sorted_matches = tuple(sorted(matches))
    return sorted_matches, {path: diagnostics[path] for path in sorted_matches}


def _array_path_for_env(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    prims_by_path: Mapping[str, Any],
    env_namespace: str,
    env_id: int,
    time_code: Any | None,
) -> tuple[str, dict[str, Any]]:
    if not binding_cfg.discover_arrays:
        if binding_cfg.array_prim_path is None:
            raise ValueError("array_prim_path is required when discover_arrays=False.")
        array_path = _resolve_env_path(
            binding_cfg.array_prim_path,
            env_namespace=env_namespace,
            env_id=env_id,
        )
        return array_path, {
            "mode": "explicit",
            "selected": array_path,
            "reasons": ("explicit_array_prim_path",),
        }

    root = binding_cfg.array_discovery_root_path
    discovery_root = (
        env_namespace
        if root is None
        else _resolve_env_path(root, env_namespace=env_namespace, env_id=env_id)
    )
    matches: list[tuple[str, tuple[str, ...]]] = []
    for path, prim in prims_by_path.items():
        if not _is_descendant_or_self(path, discovery_root):
            continue
        attrs = _attrs(prim, time_code=time_code)
        reasons = _array_discovery_reasons(
            path,
            prim,
            attrs,
            binding_cfg,
            prims_by_path=prims_by_path,
            time_code=time_code,
        )
        if reasons:
            matches.append((path, reasons))
    if not matches:
        raise ValueError(
            f"No microphone array prims discovered under {discovery_root!r}."
        )
    matches = sorted(matches, key=lambda item: item[0])
    selected_path, selected_reasons = _select_lab_discovery_match(
        matches,
        preferred=binding_cfg.preferred_array,
    )
    return selected_path, {
        "mode": "semantic_discovery",
        "root": discovery_root,
        "selected": selected_path,
        "reasons": selected_reasons,
        "candidates": {path: reasons for path, reasons in matches},
    }


def _source_discovery_reasons(
    path: str,
    prim: Any,
    attrs: Mapping[str, Any],
    binding_cfg: LabAudioStageBindingCfg,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if any(name in attrs for name in binding_cfg.source_discovery_attr_names):
        reasons.append("source_metadata_attr")
    type_name = _prim_type_name(prim)
    if type_name and type_name in binding_cfg.source_discovery_type_names:
        reasons.append(f"type:{type_name}")
    name = _path_name(path).lower()
    for pattern in binding_cfg.source_discovery_name_patterns:
        if fnmatch.fnmatch(name, pattern.lower()):
            reasons.append(f"name_pattern:{pattern}")
            break
    return tuple(dict.fromkeys(reasons))


def _array_discovery_reasons(
    path: str,
    prim: Any,
    attrs: Mapping[str, Any],
    binding_cfg: LabAudioStageBindingCfg,
    *,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for name in binding_cfg.array_discovery_attr_names:
        if attrs.get(name) is not None:
            reasons.append(name)
    type_name = _prim_type_name(prim)
    for pattern in binding_cfg.array_discovery_type_name_patterns:
        if fnmatch.fnmatch(type_name, pattern):
            reasons.append(f"type_pattern:{pattern}")
            break
    prim_name = _path_name(path)
    prim_name_lower = prim_name.lower()
    for pattern in binding_cfg.array_discovery_name_patterns:
        if fnmatch.fnmatch(prim_name, pattern) or fnmatch.fnmatch(
            prim_name_lower,
            pattern.lower(),
        ):
            reasons.append(f"name_pattern:{pattern}")
            break
    if _has_direct_child_microphone(
        array_path=path,
        prims_by_path=prims_by_path,
        time_code=time_code,
    ):
        reasons.append("child_ias:microphone_id")
    return tuple(dict.fromkeys(reasons))


def _select_lab_discovery_match(
    matches: list[tuple[str, tuple[str, ...]]],
    *,
    preferred: str | None,
) -> tuple[str, tuple[str, ...]]:
    if preferred is None:
        return matches[0]
    for path, reasons in matches:
        name = _path_name(path)
        if preferred in {path, name}:
            return path, reasons
        if (
            fnmatch.fnmatch(path, preferred)
            or fnmatch.fnmatch(name, preferred)
            or fnmatch.fnmatch(name.lower(), preferred.lower())
        ):
            return path, reasons
    raise ValueError(f"No discovered microphone array matches {preferred!r}.")


def _has_direct_child_microphone(
    *,
    array_path: str,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> bool:
    prefix = f"{array_path.rstrip('/')}/"
    for path, prim in prims_by_path.items():
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        if "/" in relative:
            continue
        if _looks_like_microphone_child(_attrs(prim, time_code=time_code), prim):
            return True
    return False


def _resolve_world_transform(
    prim: Any,
    *,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
    field_name: str,
) -> StageTransform:
    attrs = _attrs(prim, time_code=time_code)
    has_world_attr = "ias:position_world" in attrs
    if _has_pxr_usd_geom() and (not has_world_attr or _has_xform_attrs(attrs)):
        try:
            return _usd_world_transform(prim, time_code=time_code)
        except Exception as exc:
            if not has_world_attr and not _has_fallback_xform_stack(
                prim,
                prims_by_path=prims_by_path,
                time_code=time_code,
            ):
                raise ValueError(
                    f"{field_name!r} world transform could not be computed from "
                    f"UsdGeom.Xformable: {exc}"
                ) from exc
    if has_world_attr:
        return StageTransform(
            position_world=_required_vec3_attr(
                attrs,
                ("ias:position_world",),
                field_name=field_name,
            ),
            orientation_world_quat=_quat_attr(
                attrs,
                ("ias:orientation_world_quat", "xformOp:orient"),
                default=None,
            ),
            provenance="ias:position_world",
            time_code=time_code,
        )
    stack_transform = _fallback_xform_stack_transform(
        prim,
        prims_by_path=prims_by_path,
        time_code=time_code,
    )
    if stack_transform is not None:
        return stack_transform
    raise ValueError(
        f"{field_name!r} is missing a computable transform. Expected a USD "
        "Xformable transform stack, ias:position_world, or xformOp:translate."
    )


def _usd_world_transform(prim: Any, *, time_code: Any | None) -> StageTransform:
    from pxr import UsdGeom  # type: ignore

    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
        _usd_time_code(time_code)
    )
    translation = matrix.ExtractTranslation()
    return StageTransform(
        position_world=_vec3_from_any(translation),
        orientation_world_quat=_quat_from_matrix(matrix),
        provenance="usd:ComputeLocalToWorldTransform",
        time_code=time_code,
    )


def _fallback_xform_stack_transform(
    prim: Any,
    *,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> StageTransform | None:
    path = _prim_path(prim)
    ancestors = _ancestor_paths(path)
    position = (0.0, 0.0, 0.0)
    orientation = (0.0, 0.0, 0.0, 1.0)
    found_transform = False
    for ancestor_path in ancestors:
        ancestor = prims_by_path.get(ancestor_path)
        if ancestor is None:
            continue
        attrs = _attrs(ancestor, time_code=time_code)
        local_position = _optional_vec3_attr(attrs, ("xformOp:translate",))
        local_orientation = _quat_attr(attrs, ("xformOp:orient",), default=None)
        if local_position is None and local_orientation is None:
            continue
        found_transform = True
        if local_position is not None:
            position = add(
                position,
                rotate_vector_by_quaternion(local_position, orientation),
            )
        if local_orientation is not None:
            orientation = normalize_quaternion(
                quaternion_multiply(orientation, local_orientation)
            )
    if not found_transform:
        return None
    return StageTransform(
        position_world=position,
        orientation_world_quat=orientation,
        provenance="xformOp:stack",
        time_code=time_code,
    )


def _has_fallback_xform_stack(
    prim: Any,
    *,
    prims_by_path: Mapping[str, Any],
    time_code: Any | None,
) -> bool:
    return (
        _fallback_xform_stack_transform(
            prim,
            prims_by_path=prims_by_path,
            time_code=time_code,
        )
        is not None
    )


def _env_namespace(pattern: str, env_id: int) -> str:
    return pattern.format(
        env_id=env_id,
        ENV_ID=env_id,
        ENV_NS=f"env_{env_id}",
    ).rstrip("/")


def _resolve_env_path(path: str, *, env_namespace: str, env_id: int) -> str:
    formatted = path.format(
        env_id=env_id,
        ENV_ID=env_id,
        ENV_NS=env_namespace,
        ENV_REGEX_NS=env_namespace,
    )
    if formatted.startswith("/"):
        return formatted
    return f"{env_namespace}/{formatted.lstrip('/')}"


def _required_prim(
    prims_by_path: Mapping[str, Any],
    path: str,
    description: str,
) -> Any:
    prim = prims_by_path.get(path)
    if prim is None:
        raise ValueError(f"No {description} prim found at {path!r}.")
    return prim


def _room_for_env(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    prims_by_path: Mapping[str, Any],
    env_namespace: str,
    env_id: int,
    time_code: Any | None,
) -> tuple[RoomAcousticsSpec | None, dict[str, Any] | None]:
    """Anchor a shoebox room to the configured prim's world-aligned bbox."""

    if binding_cfg.room_prim_path is None:
        return None, None
    resolved_path = _resolve_env_path(
        binding_cfg.room_prim_path,
        env_namespace=env_namespace,
        env_id=env_id,
    )
    prim = _required_prim(prims_by_path, resolved_path, "room")
    minimum, maximum = world_aligned_bbox(
        prim,
        prim_path=resolved_path,
        time_code=time_code,
    )
    if binding_cfg.room_absorption_from_tags:
        absorption, absorption_provenance = resolve_room_absorption(
            prim,
            semantic_absorption=dict(binding_cfg.room_semantic_absorption),
            default=binding_cfg.room_absorption,
            time_code=time_code,
        )
    else:
        absorption = binding_cfg.room_absorption
        absorption_provenance = "config"
    room = room_spec_from_bounds(
        min_world=minimum,
        max_world=maximum,
        room_id=f"{binding_cfg.room_id}_env_{env_id}",
        absorption=absorption,
        max_order=binding_cfg.room_max_order,
        out_of_bounds=binding_cfg.room_out_of_bounds,
        anchor_prim_path=resolved_path,
    )
    diagnostics = {
        "prim_path": resolved_path,
        "room_id": room.room_id,
        "dimensions_m": room.dimensions_m,
        "origin_m": room.origin_m,
        "absorption": room.absorption,
        "absorption_provenance": absorption_provenance,
        "max_order": room.max_order,
        "out_of_bounds": room.out_of_bounds,
    }
    return room, diagnostics


def _traverse(stage: Any) -> tuple[Any, ...]:
    return tuple(stage.Traverse())


def _attrs(prim: Any, *, time_code: Any | None) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return {
            str(key): _value_at_time(value, time_code)
            for key, value in dict(prim.attributes).items()
        }
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = _usd_attr_get(attr, time_code)
    return attrs


def _value_at_time(value: Any, time_code: Any | None) -> Any:
    if hasattr(value, "Get") and callable(value.Get):
        try:
            return value.Get(time_code)
        except TypeError:
            return value.Get()
    if isinstance(value, Mapping):
        if time_code in value:
            return value[time_code]
        if time_code is not None:
            try:
                numeric_time = float(time_code)
            except (TypeError, ValueError):
                numeric_time = None
            if numeric_time in value:
                return value[numeric_time]
        if "default" in value:
            return value["default"]
    return value


def _usd_attr_get(attr: Any, time_code: Any | None) -> Any:
    try:
        return attr.Get(_usd_time_code(time_code))
    except TypeError:
        return attr.Get()


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))


def _stage_id(stage: Any) -> str:
    if hasattr(stage, "GetRootLayer"):
        root_layer = stage.GetRootLayer()
        identifier = getattr(root_layer, "identifier", None)
        if identifier:
            return str(identifier)
    identifier = getattr(stage, "identifier", None)
    return str(identifier or "isaac_lab_stage")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _asset_path(value: Any) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    return str(path if path is not None else value)


def _indexed_or_attr(
    values: tuple[str, ...] | None,
    index: int,
    attrs: Mapping[str, Any],
    attr_name: str,
    *,
    default: str,
) -> str:
    if values is not None and index < len(values):
        return str(values[index])
    return str(attrs.get(attr_name, default))


def _first_present(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: Any,
) -> Any:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return attrs[key]
    return default


def _required_vec3_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    field_name: str,
) -> Vector3:
    value = _optional_vec3_attr(attrs, keys)
    if value is not None:
        return value
    expected = " or ".join(keys)
    raise ValueError(f"{field_name!r} is missing required transform {expected}.")


def _optional_vec3_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Vector3 | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return _vec3_from_any(attrs[key])
    return None


def _vec3_from_any(value: Any) -> Vector3:
    if hasattr(value, "GetLength") and callable(value.GetLength):
        return as_vector3((value[0], value[1], value[2]), "Vector3")
    return as_vector3(value, "Vector3")


def _quat_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: Quaternion | None,
) -> Quaternion | None:
    for key in keys:
        if key not in attrs or attrs[key] is None:
            continue
        return _quat_from_any(attrs[key])
    return default


def _quat_from_any(value: Any) -> Quaternion:
    if hasattr(value, "GetImaginary") and hasattr(value, "GetReal"):
        x, y, z = value.GetImaginary()
        return as_quaternion_xyzw(
            (float(x), float(y), float(z), float(value.GetReal())),
            "Quaternion",
        )
    return as_quaternion_xyzw(value, "Quaternion")


def _quat_from_matrix(matrix: Any) -> Quaternion:
    if hasattr(matrix, "ExtractRotationQuat"):
        try:
            return _quat_from_any(matrix.ExtractRotationQuat())
        except Exception:
            pass
    if hasattr(matrix, "ExtractRotation"):
        try:
            rotation = matrix.ExtractRotation()
            if hasattr(rotation, "GetQuat"):
                return _quat_from_any(rotation.GetQuat())
        except Exception:
            pass
    if hasattr(matrix, "ExtractRotationMatrix"):
        try:
            return _quat_from_matrix_entries(matrix.ExtractRotationMatrix())
        except Exception:
            pass
    return _quat_from_matrix_entries(matrix)


def _quat_from_matrix_entries(matrix: Any) -> Quaternion:
    try:
        m00 = float(matrix[0][0])
        m01 = float(matrix[0][1])
        m02 = float(matrix[0][2])
        m10 = float(matrix[1][0])
        m11 = float(matrix[1][1])
        m12 = float(matrix[1][2])
        m20 = float(matrix[2][0])
        m21 = float(matrix[2][1])
        m22 = float(matrix[2][2])
    except Exception as exc:
        raise ValueError(
            "Could not extract rotation quaternion from USD matrix."
        ) from exc

    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m21 - m12) / scale
        y = (m02 - m20) / scale
        z = (m10 - m01) / scale
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / scale
        x = 0.25 * scale
        y = (m01 + m10) / scale
        z = (m02 + m20) / scale
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / scale
        x = (m01 + m10) / scale
        y = 0.25 * scale
        z = (m12 + m21) / scale
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / scale
        x = (m02 + m20) / scale
        y = (m12 + m21) / scale
        z = 0.25 * scale
    return as_quaternion_xyzw((x, y, z, w), "USD matrix quaternion")


def _float_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: float,
) -> float:
    value = _optional_float_attr(attrs, keys)
    return default if value is None else value


def _optional_float_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return float(attrs[key])
    return None


def _has_pxr_usd_geom() -> bool:
    try:
        from pxr import UsdGeom  # type: ignore  # noqa: F401

        return True
    except ImportError:
        return False


def _usd_time_code(time_code: Any | None) -> Any:
    from pxr import Usd  # type: ignore

    if time_code is None:
        return Usd.TimeCode.Default()
    if hasattr(time_code, "GetValue"):
        return time_code
    if isinstance(time_code, str) and time_code.lower() == "default":
        return Usd.TimeCode.Default()
    return Usd.TimeCode(float(time_code))


def _has_xform_attrs(attrs: Mapping[str, Any]) -> bool:
    return any(key == "xformOpOrder" or key.startswith("xformOp:") for key in attrs)


def _ancestor_paths(path: str) -> tuple[str, ...]:
    parts = [part for part in path.strip("/").split("/") if part]
    paths = []
    for index in range(1, len(parts) + 1):
        paths.append("/" + "/".join(parts[:index]))
    return tuple(paths)


def _is_descendant(path: str, root: str) -> bool:
    root = root.rstrip("/")
    return path.startswith(f"{root}/")


def _is_descendant_or_self(path: str, root: str) -> bool:
    root = root.rstrip("/")
    return path == root or path.startswith(f"{root}/")


def _stage_owner_candidates(owner: object | None) -> tuple[object | None, ...]:
    if owner is None:
        return (None,)
    return (
        owner,
        getattr(owner, "scene", None),
        getattr(owner, "sim", None),
        getattr(owner, "world", None),
        getattr(getattr(owner, "scene", None), "sim", None),
        getattr(getattr(owner, "scene", None), "world", None),
    )


def _resolve_num_envs(
    *,
    binding_cfg: LabAudioStageBindingCfg,
    owner: object | None,
    num_envs: int | None,
) -> int:
    if num_envs is not None:
        resolved = int(num_envs)
        if resolved <= 0:
            raise ValueError("num_envs must be positive.")
        return resolved
    if binding_cfg.num_envs is not None:
        return int(binding_cfg.num_envs)
    if binding_cfg.allow_scene_num_envs:
        for candidate in _stage_owner_candidates(owner):
            resolved = _num_envs_attr(candidate)
            if resolved is not None:
                return resolved
    raise ValueError(
        "LabAudioStageBindingCfg.num_envs is required unless the scene/env "
        "exposes a positive num_envs attribute."
    )


def _num_envs_attr(candidate: object | None) -> int | None:
    if candidate is None:
        return None
    for attr_name in ("num_envs", "num_env", "env_count", "num_instances"):
        value = getattr(candidate, attr_name, None)
        if value is None:
            continue
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            continue
        if resolved > 0:
            return resolved
    cfg = getattr(candidate, "cfg", None)
    if cfg is not None and cfg is not candidate:
        return _num_envs_attr(cfg)
    return None


def _omni_context_stage() -> object | None:
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        stage = context.get_stage()
        if stage is not None and hasattr(stage, "Traverse"):
            return stage
    except Exception:
        return None
    return None


def _transform_diagnostics(transform: StageTransform) -> dict[str, Any]:
    return {
        "position_world": transform.position_world,
        "orientation_world_quat": transform.orientation_world_quat,
        "provenance": transform.provenance,
        "time_code": _diagnostic_time_code(transform.time_code),
    }


def _diagnostic_time_code(time_code: Any | None) -> Any | None:
    if time_code is None:
        return None
    if isinstance(time_code, (str, int, float)):
        return time_code
    if hasattr(time_code, "GetValue"):
        try:
            return float(time_code.GetValue())
        except Exception:
            return str(time_code)
    return str(time_code)


def _require_path(value: str, field_name: str) -> None:
    if str(value).strip() == "":
        raise ValueError(f"LabAudioStageBindingCfg.{field_name} must be non-empty.")
