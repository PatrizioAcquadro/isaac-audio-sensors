"""Semantic discovery and scene binding for Isaac audio prims."""

from __future__ import annotations

import fnmatch
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    normalize_quaternion,
    quaternion_conjugate,
    quaternion_multiply,
    rotate_vector_by_quaternion,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import (
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    IsaacStagePoseResolver,
    StagePose,
    diagnostic_time_code,
    optional_vec3_attr,
    prim_path,
    prim_type_name,
    quat_attr,
)
from isaac_audio_sensors.isaac.pose_resolver import (
    stage_id as resolve_stage_id,
)
from isaac_audio_sensors.isaac.stage_audio import (
    _linear_gain_to_db,
    _time_code_to_seconds,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _IsaacAudioDiscoveryFields:
    """Shared discovery fields and normalization."""

    discovery_roots: tuple[str, ...] = ("/World",)
    robot_base_prim_path: str | None = None
    array_roots: tuple[str, ...] = ()
    source_roots: tuple[str, ...] = ()
    restrict_arrays_to_robot: bool = False
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    include_regexes: tuple[str, ...] = ()
    exclude_regexes: tuple[str, ...] = ()
    array_name_patterns: tuple[str, ...] = (
        "*AudioArray*",
        "*MicrophoneArray*",
        "*MicArray*",
    )
    array_type_name_patterns: tuple[str, ...] = (
        "*AudioArray*",
        "*MicrophoneArray*",
        "*MicArray*",
    )
    source_name_patterns: tuple[str, ...] = (
        "*Speaker*",
        "*Sound*",
        "*AudioSource*",
    )
    source_type_names: tuple[str, ...] = (
        "OmniSound",
        "Sound",
        "AudioSource",
        "OmniAudioSource",
    )
    default_class_label: str = "Sound"
    source_class_label_overrides: Mapping[str, str] = field(default_factory=dict)
    default_microphone_layout: str | None = "quad_front"
    default_sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    required_arrays: bool = False
    required_sources: bool = False
    default_source_start_time_s: float = 0.0
    default_source_duration_s: float | None = None
    metadata_precedence: tuple[str, ...] = ("ias", "usd", "defaults")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "discovery_roots",
            _normalize_paths(self.discovery_roots, field_name="discovery_roots"),
        )
        object.__setattr__(
            self,
            "array_roots",
            _normalize_paths(self.array_roots, field_name="array_roots"),
        )
        object.__setattr__(
            self,
            "source_roots",
            _normalize_paths(self.source_roots, field_name="source_roots"),
        )
        if self.robot_base_prim_path is not None:
            object.__setattr__(
                self,
                "robot_base_prim_path",
                _normalize_path(
                    self.robot_base_prim_path,
                    field_name="robot_base_prim_path",
                ),
            )
        for field_name in (
            "include_globs",
            "exclude_globs",
            "include_regexes",
            "exclude_regexes",
            "array_name_patterns",
            "array_type_name_patterns",
            "source_name_patterns",
            "source_type_names",
            "metadata_precedence",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(str(value) for value in getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "source_class_label_overrides",
            {
                str(key): str(value)
                for key, value in dict(self.source_class_label_overrides).items()
            },
        )
        if int(self.default_sample_rate_hz) <= 0:
            raise ValueError("default_sample_rate_hz must be positive.")
        object.__setattr__(
            self,
            "default_sample_rate_hz",
            int(self.default_sample_rate_hz),
        )
        if not math.isfinite(float(self.default_source_start_time_s)):
            raise ValueError("default_source_start_time_s must be finite.")
        if self.default_source_duration_s is not None and (
            not math.isfinite(float(self.default_source_duration_s))
            or self.default_source_duration_s <= 0.0
        ):
            raise ValueError("default_source_duration_s must be positive.")
        if set(self.metadata_precedence) != {"ias", "usd", "defaults"} or len(
            self.metadata_precedence
        ) != 3:
            raise ValueError(
                "metadata_precedence must contain ias, usd, and defaults exactly once."
            )

    def _discovery_kwargs(self) -> dict[str, object]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(_IsaacAudioDiscoveryFields)
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class IsaacAudioDiscoveryCfg(_IsaacAudioDiscoveryFields):
    """Typed controls for semantic audio discovery on a USD-like stage."""

    strict_candidate_errors: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class IsaacAudioSceneBindingCfg(_IsaacAudioDiscoveryFields):
    """Convenience config for binding an Isaac Sim stage by discovery."""

    required_arrays: bool = True
    preferred_array: str | None = None
    preferred_source: str | None = None
    # False (default) keeps the cached live path: full discovery runs once
    # and steady-state ticks re-resolve only poses until something
    # invalidates the cache. True forces full discovery (one Traverse) on
    # every capture/update.
    rediscover_each_update: bool = False
    strict_candidate_errors: bool = False

    def to_discovery_cfg(self) -> IsaacAudioDiscoveryCfg:
        """Return the lower-level discovery config represented by this binding."""

        return IsaacAudioDiscoveryCfg(
            **self._discovery_kwargs(),
            strict_candidate_errors=self.strict_candidate_errors,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscoveredAudioArray:
    """A discovered microphone array plus discovery diagnostics."""

    spec: MicrophoneArraySpec
    reasons: tuple[str, ...]
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscoveredAudioSource:
    """A discovered sound source plus discovery diagnostics."""

    spec: AudioSourceSpec
    reasons: tuple[str, ...]
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class IsaacAudioDiscoveryResult:
    """Semantic discovery result for one stage read."""

    stage_id: str
    arrays: tuple[DiscoveredAudioArray, ...]
    sources: tuple[DiscoveredAudioSource, ...]
    selected_array: DiscoveredAudioArray | None
    selected_source: DiscoveredAudioSource | None
    diagnostics: Mapping[str, Any]


def discover_stage_audio(
    stage: Any,
    *,
    cfg: IsaacAudioDiscoveryCfg | None = None,
    timestamp_ms: int = 0,
    stage_id: str | None = None,
    usd_time_code: Any | None = None,
    time_code: Any | None = None,
    explicit_array_prim_path: str | None = None,
    explicit_source_prim_path: str | None = None,
    preferred_array: str | None = None,
    preferred_source: str | None = None,
    diagnostics_out: dict[str, Any] | None = None,
    prims: tuple[Any, ...] | None = None,
) -> IsaacAudioDiscoveryResult:
    """Discover arrays and sources from semantic USD metadata and names.

    When ``prims`` is provided, the stage is not re-traversed; the supplied
    prim tuple backs the pose resolver instead.
    """

    discovery_cfg = cfg or IsaacAudioDiscoveryCfg()
    resolved_time_code = _resolve_time_code(
        usd_time_code=usd_time_code,
        time_code=time_code,
    )
    resolver = IsaacStagePoseResolver(
        stage,
        time_code=resolved_time_code,
        prims=prims,
    )
    resolved_stage_id = stage_id or resolve_stage_id(stage)
    diagnostics = _base_diagnostics(
        stage_id=resolved_stage_id,
        timestamp_ms=timestamp_ms,
        cfg=discovery_cfg,
        explicit_array_prim_path=explicit_array_prim_path,
        explicit_source_prim_path=explicit_source_prim_path,
        preferred_array=preferred_array,
        preferred_source=preferred_source,
        time_code=resolved_time_code,
    )

    if discovery_cfg.robot_base_prim_path is not None:
        robot_prim = _required_prim(
            resolver,
            discovery_cfg.robot_base_prim_path,
            "robot/base frame",
        )
        diagnostics["robot_base_transform"] = _pose_diagnostics(
            resolver.resolve_world_pose(
                robot_prim,
                field_name=discovery_cfg.robot_base_prim_path,
            )
        )

    arrays = _discover_arrays(
        resolver=resolver,
        cfg=discovery_cfg,
        explicit_array_prim_path=explicit_array_prim_path,
        diagnostics=diagnostics,
    )
    sources = _discover_sources(
        resolver=resolver,
        cfg=discovery_cfg,
        explicit_source_prim_path=explicit_source_prim_path,
        diagnostics=diagnostics,
    )
    selected_array = _select_array(arrays, preferred_array)
    selected_source = _select_source(sources, preferred_source)

    diagnostics["array_count"] = len(arrays)
    diagnostics["source_count"] = len(sources)
    diagnostics["selected_array"] = (
        None
        if selected_array is None
        else {
            "array_id": selected_array.spec.array_id,
            "prim_path": selected_array.spec.prim_path,
            "reasons": selected_array.reasons,
        }
    )
    diagnostics["selected_source"] = (
        None
        if selected_source is None
        else {
            "source_id": selected_source.spec.source_id,
            "prim_path": selected_source.spec.prim_path,
            "reasons": selected_source.reasons,
        }
    )

    if (
        explicit_array_prim_path is not None or discovery_cfg.required_arrays
    ) and not arrays:
        raise ValueError(_missing_message("microphone array", explicit_array_prim_path))
    if (
        explicit_source_prim_path is not None or discovery_cfg.required_sources
    ) and not sources:
        raise ValueError(_missing_message("audio source", explicit_source_prim_path))
    if preferred_array is not None and selected_array is None:
        raise ValueError(f"No discovered microphone array matches {preferred_array!r}.")
    if preferred_source is not None and selected_source is None:
        raise ValueError(f"No discovered audio source matches {preferred_source!r}.")

    if diagnostics_out is not None:
        diagnostics_out.clear()
        diagnostics_out.update(diagnostics)
    return IsaacAudioDiscoveryResult(
        stage_id=resolved_stage_id,
        arrays=arrays,
        sources=sources,
        selected_array=selected_array,
        selected_source=selected_source,
        diagnostics=diagnostics,
    )


def _discover_arrays(
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    explicit_array_prim_path: str | None,
    diagnostics: dict[str, Any],
) -> tuple[DiscoveredAudioArray, ...]:
    arrays: list[DiscoveredAudioArray] = []
    for prim in sorted(resolver.prims, key=prim_path):
        path = prim_path(prim)
        explicit = (
            explicit_array_prim_path is not None and path == explicit_array_prim_path
        )
        if explicit_array_prim_path is not None and not explicit:
            continue
        if not explicit and not _path_in_roots(path, _array_roots(cfg)):
            continue
        if (
            not explicit
            and cfg.restrict_arrays_to_robot
            and cfg.robot_base_prim_path is not None
            and not _is_descendant_or_self(path, cfg.robot_base_prim_path)
        ):
            diagnostics["array_rejections"][path] = {
                "reason": "outside_robot_base_prim_path",
                "robot_base_prim_path": cfg.robot_base_prim_path,
            }
            continue
        if not explicit and not _passes_filters(path, cfg):
            diagnostics["array_rejections"][path] = {"reason": "filtered"}
            continue
        reasons = _array_reasons(
            prim,
            resolver=resolver,
            cfg=cfg,
            explicit=explicit,
        )
        if not reasons:
            continue
        try:
            spec, array_diagnostics = _array_spec_from_prim(
                prim,
                resolver=resolver,
                cfg=cfg,
                reasons=reasons,
                diagnostics=diagnostics,
            )
        except ValueError as exc:
            diagnostics["array_rejections"][path] = {
                "reason": "metadata_or_transform_error",
                "error": str(exc),
                "candidate_reasons": reasons,
            }
            if explicit or cfg.strict_candidate_errors:
                raise
            continue
        arrays.append(
            DiscoveredAudioArray(
                spec=spec,
                reasons=reasons,
                diagnostics=array_diagnostics,
            )
        )
    if explicit_array_prim_path is not None and not arrays:
        _required_prim(resolver, explicit_array_prim_path, "microphone array")
    return tuple(arrays)


def _discover_sources(
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    explicit_source_prim_path: str | None,
    diagnostics: dict[str, Any],
) -> tuple[DiscoveredAudioSource, ...]:
    sources: list[DiscoveredAudioSource] = []
    for prim in sorted(resolver.prims, key=prim_path):
        path = prim_path(prim)
        explicit = (
            explicit_source_prim_path is not None and path == explicit_source_prim_path
        )
        if explicit_source_prim_path is not None and not explicit:
            continue
        if not explicit and not _path_in_roots(path, _source_roots(cfg)):
            continue
        if not explicit and not _passes_filters(path, cfg):
            diagnostics["source_rejections"][path] = {"reason": "filtered"}
            continue
        reasons = _source_reasons(
            prim,
            resolver=resolver,
            cfg=cfg,
            explicit=explicit,
        )
        if not reasons:
            continue
        aural_mode = resolver.attrs(prim).get("auralMode")
        if str(aural_mode).strip().lower() == "nonspatial":
            error = (
                "OmniSound auralMode=nonSpatial is a device-mix source and is "
                "excluded from physical microphone-array discovery."
            )
            diagnostics["source_rejections"][path] = {
                "reason": "non_spatial_source",
                "error": error,
                "candidate_reasons": reasons,
            }
            if explicit:
                raise ValueError(error)
            continue
        try:
            spec, source_diagnostics = _source_spec_from_prim(
                prim,
                resolver=resolver,
                cfg=cfg,
                reasons=reasons,
                diagnostics=diagnostics,
            )
        except ValueError as exc:
            diagnostics["source_rejections"][path] = {
                "reason": "metadata_or_transform_error",
                "error": str(exc),
                "candidate_reasons": reasons,
            }
            if explicit or cfg.strict_candidate_errors:
                raise
            continue
        sources.append(
            DiscoveredAudioSource(
                spec=spec,
                reasons=reasons,
                diagnostics=source_diagnostics,
            )
        )
    if explicit_source_prim_path is not None and not sources:
        _required_prim(resolver, explicit_source_prim_path, "audio source")
    return tuple(sources)


def _array_spec_from_prim(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    reasons: tuple[str, ...],
    diagnostics: dict[str, Any],
) -> tuple[MicrophoneArraySpec, dict[str, Any]]:
    attrs = resolver.attrs(prim)
    path = prim_path(prim)
    pose = resolver.resolve_world_pose(prim, field_name=path)
    orientation = pose.orientation_world_quat or quat_attr(
        attrs,
        ("ias:orientation_world_quat", "xformOp:orient"),
        default=(0.0, 0.0, 0.0, 1.0),
    )
    if orientation is None:
        orientation = (0.0, 0.0, 0.0, 1.0)
    orientation = normalize_quaternion(orientation)
    array_pose = StagePose(
        prim_path=pose.prim_path,
        position_world=pose.position_world,
        orientation_world_quat=orientation,
        provenance=pose.provenance,
        time_code=pose.time_code,
    )
    microphones, microphone_diagnostics = _microphones_for_array(
        array_path=path,
        array_attrs=attrs,
        resolver=resolver,
        array_pose=array_pose,
        cfg=cfg,
    )
    if microphone_diagnostics.get("source") == "child_prims":
        diagnostics["microphone_transforms"].update(microphone_diagnostics["items"])
    array_id = str(attrs.get("ias:array_id", _path_name(path)))
    array_diagnostics = {
        "prim_path": path,
        "array_id": array_id,
        "reasons": reasons,
        "transform": _pose_diagnostics(array_pose),
        "microphones": microphone_diagnostics,
        "sample_rate_provenance": (
            "ias:sample_rate_hz" if "ias:sample_rate_hz" in attrs else "default"
        ),
        "coordinate_convention_provenance": (
            "ias:coordinate_convention"
            if "ias:coordinate_convention" in attrs
            else "default"
        ),
    }
    diagnostics["array_transforms"][path] = _pose_diagnostics(array_pose)
    diagnostics["array_candidates"][path] = array_diagnostics
    return (
        MicrophoneArraySpec(
            array_id=array_id,
            prim_path=path,
            position_world=pose.position_world,
            orientation_world_quat=orientation,
            microphones=microphones,
            sample_rate_hz=int(
                attrs.get("ias:sample_rate_hz", cfg.default_sample_rate_hz)
            ),
            coordinate_convention=str(
                attrs.get("ias:coordinate_convention", cfg.coordinate_convention)
            ),
        ),
        array_diagnostics,
    )


def _source_spec_from_prim(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    reasons: tuple[str, ...],
    diagnostics: dict[str, Any],
) -> tuple[AudioSourceSpec, dict[str, Any]]:
    attrs = resolver.attrs(prim)
    path = prim_path(prim)
    pose = resolver.resolve_world_pose(prim, field_name=path)
    source_id_value, source_id_provenance = _metadata_value(
        cfg,
        ias=_attr_candidate(attrs, "ias:source_id"),
        defaults=(_path_name(path), "default"),
    )
    source_id = str(source_id_value)
    override_label = _class_label_override(cfg, source_id=source_id, prim_path=path)
    if override_label is not None:
        class_label = override_label
        class_label_provenance = "override"
    else:
        class_label_value, class_label_provenance = _metadata_value(
            cfg,
            ias=_attr_candidate(attrs, "ias:class_label"),
            defaults=(cfg.default_class_label, "default"),
        )
        class_label = str(class_label_value)

    audio_asset_value, audio_asset_provenance = _metadata_value(
        cfg,
        ias=_asset_candidate(attrs, ("ias:audio_asset_path",)),
        usd=_asset_candidate(attrs, ("filePath", "inputs:file", "inputs:audio")),
        defaults=(None, "default"),
    )
    audio_asset_path = _asset_path(audio_asset_value)
    start_value, start_provenance = _metadata_value(
        cfg,
        ias=lambda: _float_candidate(attrs, "ias:start_time_s"),
        usd=lambda: _time_code_candidate(
            attrs, "startTime", stage=resolver.stage
        ),
        defaults=(float(cfg.default_source_start_time_s), "default"),
    )
    start_time_s = float(start_value)
    if start_provenance == "startTime" and start_time_s < 0.0:
        raise ValueError(
            "Native Kit Audio startTime is negative, so the source is disabled."
        )

    duration_value, duration_provenance = _metadata_value(
        cfg,
        ias=lambda: _float_candidate(attrs, "ias:duration_s"),
        usd=lambda: _native_duration_candidate(
            attrs,
            stage=resolver.stage,
            selected_start_time_s=start_time_s,
        ),
        defaults=(cfg.default_source_duration_s, "default"),
    )
    duration_s = None if duration_value is None else float(duration_value)

    loop_count_value, loop_count_provenance = _metadata_value(
        cfg,
        usd=lambda: _loop_count_candidate(attrs),
        defaults=(0, "default"),
    )
    loop_count = int(loop_count_value)

    gain_value, gain_provenance = _metadata_value(
        cfg,
        ias=lambda: _float_candidate(attrs, "ias:gain_db"),
        usd=lambda: _linear_gain_candidate(attrs),
        defaults=(0.0, "default"),
    )
    gain_db = float(gain_value)
    directivity_value, directivity_provenance = _metadata_value(
        cfg,
        ias=_attr_candidate(attrs, "ias:directivity"),
        defaults=("omni", "default"),
    )
    source_diagnostics = {
        "prim_path": path,
        "source_id": source_id,
        "source_id_provenance": source_id_provenance,
        "reasons": reasons,
        "transform": _pose_diagnostics(pose),
        "class_label_provenance": class_label_provenance,
        "audio_asset_path": audio_asset_path,
        "audio_asset_path_provenance": audio_asset_provenance,
        "active_window_provenance": {
            "start_time_s": start_provenance,
            "duration_s": duration_provenance,
        },
        "gain_db_provenance": gain_provenance,
        "loop_count_provenance": loop_count_provenance,
        "directivity_provenance": directivity_provenance,
    }
    diagnostics["source_transforms"][path] = _pose_diagnostics(pose)
    diagnostics["source_candidates"][path] = source_diagnostics
    return (
        AudioSourceSpec(
            source_id=source_id,
            prim_path=path,
            class_label=class_label,
            audio_asset_path=audio_asset_path,
            position_world=pose.position_world,
            orientation_world_quat=pose.orientation_world_quat,
            start_time_s=start_time_s,
            duration_s=duration_s,
            gain_db=gain_db,
            loop_count=loop_count,
            directivity=str(directivity_value),
        ),
        source_diagnostics,
    )


def _microphones_for_array(
    *,
    array_path: str,
    array_attrs: Mapping[str, Any],
    resolver: IsaacStagePoseResolver,
    array_pose: StagePose,
    cfg: IsaacAudioDiscoveryCfg,
) -> tuple[tuple[MicrophoneSpec, ...], dict[str, Any]]:
    child_mics, child_diagnostics = _child_microphones_for_array(
        array_path=array_path,
        resolver=resolver,
        array_pose=array_pose,
    )
    if child_mics:
        return child_mics, {
            "source": "child_prims",
            "items": child_diagnostics,
        }

    explicit = _explicit_microphones_from_attrs(array_attrs)
    if explicit:
        return explicit, {
            "source": "ias:microphone_relative_offsets_m",
            "items": {
                microphone.mic_id: {
                    "relative_position_m": microphone.relative_position_m,
                    "relative_orientation_quat": microphone.relative_orientation_quat,
                }
                for microphone in explicit
            },
        }

    layout_name = array_attrs.get("ias:layout_name", cfg.default_microphone_layout)
    if layout_name is not None:
        return microphone_layout(str(layout_name)), {
            "source": (
                "ias:layout_name"
                if "ias:layout_name" in array_attrs
                else "default_microphone_layout"
            ),
            "layout_name": str(layout_name),
        }
    raise ValueError(
        f"Microphone array {array_path!r} has no microphone child prims, "
        "explicit offsets, layout name, or configured default layout."
    )


def _child_microphones_for_array(
    *,
    array_path: str,
    resolver: IsaacStagePoseResolver,
    array_pose: StagePose,
) -> tuple[tuple[MicrophoneSpec, ...], dict[str, Any]]:
    microphones: list[MicrophoneSpec] = []
    diagnostics: dict[str, Any] = {}
    prefix = f"{array_path.rstrip('/')}/"
    for prim in sorted(resolver.prims, key=prim_path):
        path = prim_path(prim)
        if not path.startswith(prefix):
            continue
        relative_path = path.removeprefix(prefix)
        if "/" in relative_path:
            continue
        attrs = resolver.attrs(prim)
        if not _looks_like_microphone_child(attrs, prim):
            continue
        child_pose: StagePose | None = None
        relative_position = optional_vec3_attr(attrs, ("ias:relative_position_m",))
        if relative_position is None:
            child_pose = resolver.resolve_world_pose(prim, field_name=path)
            relative_position = _relative_position_from_world(child_pose, array_pose)
        relative_orientation = quat_attr(
            attrs,
            ("ias:relative_orientation_quat",),
            default=None,
        )
        if relative_orientation is None:
            if child_pose is None:
                try:
                    child_pose = resolver.resolve_world_pose(prim, field_name=path)
                except ValueError:
                    child_pose = None
            if child_pose is not None and child_pose.orientation_world_quat is not None:
                relative_orientation = _relative_orientation_from_world(
                    child_pose,
                    array_pose,
                )
        diagnostics[path] = {
            "relative_position_m": relative_position,
            "relative_orientation_quat": relative_orientation,
            "world_transform": (
                None if child_pose is None else _pose_diagnostics(child_pose)
            ),
        }
        microphones.append(
            MicrophoneSpec(
                mic_id=str(attrs.get("ias:microphone_id", _path_name(path))),
                relative_position_m=relative_position,
                relative_orientation_quat=relative_orientation,
                gain_db=_float_attr(attrs, ("ias:gain_db", "gain"), default=0.0),
                self_noise_db=_optional_float_attr(
                    attrs,
                    ("ias:self_noise_db", "selfNoise"),
                ),
            )
        )
    return tuple(microphones), diagnostics


def _explicit_microphones_from_attrs(
    attrs: Mapping[str, Any],
) -> tuple[MicrophoneSpec, ...]:
    offsets = _first_present(
        attrs,
        (
            "ias:microphone_relative_offsets_m",
            "ias:microphone_offsets_m",
            "ias:mic_offsets_m",
        ),
        default=None,
    )
    if offsets is None:
        return ()
    ids = _first_present(
        attrs,
        ("ias:microphone_ids", "ias:mic_ids"),
        default=None,
    )
    positions = tuple(offsets)
    mic_ids = tuple(str(value) for value in ids) if ids is not None else ()
    microphones = []
    for index, position in enumerate(positions):
        mic_id = mic_ids[index] if index < len(mic_ids) else f"mic_{index}"
        microphones.append(
            MicrophoneSpec(
                mic_id=mic_id,
                relative_position_m=_vector3_from_any(position),
            )
        )
    return tuple(microphones)


def _array_reasons(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    explicit: bool,
) -> tuple[str, ...]:
    attrs = resolver.attrs(prim)
    path = prim_path(prim)
    type_name = prim_type_name(prim)
    if not explicit and type_name.lower() in {"listener", "omnilistener"}:
        return ()
    reasons: list[str] = []
    if explicit:
        reasons.append("explicit_array_prim_path")
    if attrs.get("ias:array_id") is not None:
        reasons.append("ias:array_id")
    if attrs.get("ias:layout_name") is not None:
        reasons.append("ias:layout_name")
    if _has_direct_microphone_child(path, resolver):
        reasons.append("child_ias:microphone_id")
    name = _path_name(path)
    for pattern in cfg.array_name_patterns:
        if fnmatch.fnmatchcase(name, pattern):
            reasons.append(f"name_pattern:{pattern}")
            break
    for pattern in cfg.array_type_name_patterns:
        if fnmatch.fnmatchcase(type_name, pattern):
            reasons.append(f"type_pattern:{pattern}")
            break
    return tuple(dict.fromkeys(reasons))


def _source_reasons(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    cfg: IsaacAudioDiscoveryCfg,
    explicit: bool,
) -> tuple[str, ...]:
    attrs = resolver.attrs(prim)
    path = prim_path(prim)
    type_name = prim_type_name(prim)
    if type_name.lower() in {"listener", "omnilistener"}:
        return ()
    reasons: list[str] = []
    if explicit:
        reasons.append("explicit_source_prim_path")
    if type_name in cfg.source_type_names:
        reasons.append(f"type:{type_name}")
    for attr_name in ("filePath", "inputs:file", "inputs:audio"):
        if attrs.get(attr_name) is not None:
            reasons.append(attr_name)
    if attrs.get("ias:audio_asset_path") is not None:
        reasons.append("ias:audio_asset_path")
    if attrs.get("ias:source_id") is not None:
        reasons.append("ias:source_id")
    if attrs.get("ias:class_label") is not None:
        reasons.append("ias:class_label")
    name = _path_name(path)
    for pattern in cfg.source_name_patterns:
        if fnmatch.fnmatchcase(name, pattern):
            reasons.append(f"name_pattern:{pattern}")
            break
    return tuple(dict.fromkeys(reasons))


def _has_direct_microphone_child(
    array_path: str,
    resolver: IsaacStagePoseResolver,
) -> bool:
    prefix = f"{array_path.rstrip('/')}/"
    for prim in resolver.prims:
        path = prim_path(prim)
        if not path.startswith(prefix):
            continue
        relative_path = path.removeprefix(prefix)
        if "/" in relative_path:
            continue
        attrs = resolver.attrs(prim)
        if _looks_like_microphone_child(attrs, prim):
            return True
    return False


def _looks_like_microphone_child(attrs: Mapping[str, Any], prim: Any) -> bool:
    if "ias:microphone_id" in attrs or "ias:relative_position_m" in attrs:
        return True
    type_name = prim_type_name(prim).lower()
    return "microphone" in type_name or _path_name(prim_path(prim)).lower() == "mic"


def _select_array(
    arrays: tuple[DiscoveredAudioArray, ...],
    preferred_array: str | None,
) -> DiscoveredAudioArray | None:
    if not arrays:
        return None
    if preferred_array is None:
        return arrays[0]
    for array in arrays:
        if _matches_preference(
            preferred_array,
            item_id=array.spec.array_id,
            prim_path=array.spec.prim_path,
        ):
            return array
    return None


def _select_source(
    sources: tuple[DiscoveredAudioSource, ...],
    preferred_source: str | None,
) -> DiscoveredAudioSource | None:
    if not sources:
        return None
    if preferred_source is None:
        return sources[0]
    for source in sources:
        if _matches_preference(
            preferred_source,
            item_id=source.spec.source_id,
            prim_path=source.spec.prim_path,
        ):
            return source
    return None


def _matches_preference(preference: str, *, item_id: str, prim_path: str) -> bool:
    name = _path_name(prim_path)
    if preference in {item_id, prim_path, name}:
        return True
    return (
        fnmatch.fnmatchcase(item_id, preference)
        or fnmatch.fnmatchcase(prim_path, preference)
        or fnmatch.fnmatchcase(name, preference)
    )


def _base_diagnostics(
    *,
    stage_id: str,
    timestamp_ms: int,
    cfg: IsaacAudioDiscoveryCfg,
    explicit_array_prim_path: str | None,
    explicit_source_prim_path: str | None,
    preferred_array: str | None,
    preferred_source: str | None,
    time_code: Any | None,
) -> dict[str, Any]:
    return {
        "provenance": "isaac_sim_live_usd_stage_snapshot",
        "discovery_provenance": "isaac_semantic_discovery",
        "stage_id": stage_id,
        "timestamp_ms": int(timestamp_ms),
        "time_code": diagnostic_time_code(time_code),
        "array_prim_path": explicit_array_prim_path,
        "robot_base_prim_path": cfg.robot_base_prim_path,
        "source_prim_path": explicit_source_prim_path,
        "preferred_array": preferred_array,
        "preferred_source": preferred_source,
        "transform_resolver": "IsaacStagePoseResolver",
        "metadata_precedence": cfg.metadata_precedence,
        "discovery_roots": cfg.discovery_roots,
        "array_roots": cfg.array_roots,
        "source_roots": cfg.source_roots,
        "restrict_arrays_to_robot": cfg.restrict_arrays_to_robot,
        "coordinate_frames": {
            "world": "USD stage world frame",
            "robot_base": "optional robot/base prim resolved in world frame",
            "array": "microphone array prim resolved in world frame",
            "microphone": "array-local microphone offsets derived from child prims",
        },
        "array_candidates": {},
        "source_candidates": {},
        "array_rejections": {},
        "source_rejections": {},
        "array_transforms": {},
        "source_transforms": {},
        "microphone_transforms": {},
    }


def _pose_diagnostics(pose: StagePose) -> dict[str, Any]:
    return {
        "prim_path": pose.prim_path,
        "position_world": pose.position_world,
        "orientation_world_quat": pose.orientation_world_quat,
        "provenance": pose.provenance,
        "time_code": diagnostic_time_code(pose.time_code),
    }


def _required_prim(
    resolver: IsaacStagePoseResolver,
    path: str,
    description: str,
) -> Any:
    prim = resolver.prims_by_path.get(path)
    if prim is None:
        raise ValueError(f"No {description} prim found at {path!r}.")
    return prim


def _resolve_time_code(
    *,
    usd_time_code: Any | None,
    time_code: Any | None,
) -> Any | None:
    if (
        usd_time_code is not None
        and time_code is not None
        and usd_time_code != time_code
    ):
        raise ValueError("Provide only one of usd_time_code or time_code.")
    return time_code if time_code is not None else usd_time_code


def _array_roots(cfg: IsaacAudioDiscoveryCfg) -> tuple[str, ...]:
    return cfg.array_roots or cfg.discovery_roots


def _source_roots(cfg: IsaacAudioDiscoveryCfg) -> tuple[str, ...]:
    return cfg.source_roots or cfg.discovery_roots


def _path_in_roots(path: str, roots: tuple[str, ...]) -> bool:
    return any(_is_descendant_or_self(path, root) for root in roots)


def _passes_filters(path: str, cfg: IsaacAudioDiscoveryCfg) -> bool:
    name = _path_name(path)
    if cfg.include_globs and not any(
        fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(name, pattern)
        for pattern in cfg.include_globs
    ):
        return False
    if cfg.include_regexes and not any(
        re.search(pattern, path) or re.search(pattern, name)
        for pattern in cfg.include_regexes
    ):
        return False
    if any(
        fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(name, pattern)
        for pattern in cfg.exclude_globs
    ):
        return False
    return not any(
        re.search(pattern, path) or re.search(pattern, name)
        for pattern in cfg.exclude_regexes
    )


def _is_descendant_or_self(path: str, root: str) -> bool:
    root = root.rstrip("/")
    return path == root or path.startswith(f"{root}/")


def _relative_position_from_world(
    child_pose: StagePose,
    array_pose: StagePose,
) -> Vector3:
    array_orientation = array_pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
    return rotate_vector_by_quaternion(
        subtract(child_pose.position_world, array_pose.position_world),
        quaternion_conjugate(array_orientation),
    )


def _relative_orientation_from_world(
    child_pose: StagePose,
    array_pose: StagePose,
) -> Quaternion:
    array_orientation = array_pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
    child_orientation = child_pose.orientation_world_quat or (0.0, 0.0, 0.0, 1.0)
    return normalize_quaternion(
        quaternion_multiply(quaternion_conjugate(array_orientation), child_orientation)
    )


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


_MISSING = object()


def _metadata_value(
    cfg: IsaacAudioDiscoveryCfg,
    *,
    ias: tuple[Any, str] | Callable[[], object] | object = _MISSING,
    usd: tuple[Any, str] | Callable[[], object] | object = _MISSING,
    defaults: tuple[Any, str] | Callable[[], object] | object = _MISSING,
) -> tuple[Any, str]:
    candidates = {"ias": ias, "usd": usd, "defaults": defaults}
    for source in cfg.metadata_precedence:
        candidate = candidates[source]
        if callable(candidate):
            candidate = candidate()
        if candidate is not _MISSING:
            return candidate  # type: ignore[return-value]
    raise ValueError("No metadata value or default is available.")


def _attr_candidate(
    attrs: Mapping[str, Any],
    key: str,
) -> tuple[Any, str] | object:
    if key not in attrs or attrs[key] is None:
        return _MISSING
    return attrs[key], key


def _float_candidate(
    attrs: Mapping[str, Any],
    key: str,
) -> tuple[float, str] | object:
    candidate = _attr_candidate(attrs, key)
    if candidate is _MISSING:
        return _MISSING
    value, provenance = candidate
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{key} must be finite.")
    return resolved, provenance


def _loop_count_candidate(
    attrs: Mapping[str, Any],
) -> tuple[int, str] | object:
    candidate = _attr_candidate(attrs, "loopCount")
    if candidate is _MISSING:
        return _MISSING
    value, provenance = candidate
    if type(value) is not int or value < -1:
        raise ValueError(
            "Native Kit Audio loopCount must be -1 or a non-negative integer."
        )
    return value, provenance


def _asset_candidate(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[Any, str] | object:
    for key in keys:
        candidate = _attr_candidate(attrs, key)
        if candidate is _MISSING:
            continue
        value, provenance = candidate
        if _asset_path(value):
            return value, provenance
    return _MISSING


def _time_code_candidate(
    attrs: Mapping[str, Any],
    key: str,
    *,
    stage: Any,
) -> tuple[float, str] | object:
    candidate = _attr_candidate(attrs, key)
    if candidate is _MISSING:
        return _MISSING
    value, provenance = candidate
    return _time_code_to_seconds(stage, value), provenance


def _native_duration_candidate(
    attrs: Mapping[str, Any],
    *,
    stage: Any,
    selected_start_time_s: float,
) -> tuple[float | None, str] | object:
    end_candidate = _time_code_candidate(attrs, "endTime", stage=stage)
    if end_candidate is not _MISSING:
        end_time_s, _provenance = end_candidate
        if end_time_s < 0.0:
            return None, "endTime"
        duration_s = end_time_s - selected_start_time_s
        if duration_s <= 0.0:
            raise ValueError(
                "Native Kit Audio endTime must be later than the selected start time."
            )
        return duration_s, "endTime"
    return _float_candidate(attrs, "duration")


def _linear_gain_candidate(
    attrs: Mapping[str, Any],
) -> tuple[float, str] | object:
    candidate = _attr_candidate(attrs, "gain")
    if candidate is _MISSING:
        return _MISSING
    value, provenance = candidate
    return _linear_gain_to_db(value), provenance


def _first_present_key(attrs: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return key
    return None


def _class_label_override(
    cfg: IsaacAudioDiscoveryCfg,
    *,
    source_id: str,
    prim_path: str,
) -> str | None:
    overrides = cfg.source_class_label_overrides
    return (
        overrides.get(prim_path)
        or overrides.get(source_id)
        or overrides.get(_path_name(prim_path))
    )


def _asset_path(value: Any) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    resolved = str(path if path is not None else value)
    return resolved if resolved else None


def _float_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: float,
) -> float:
    value = _optional_float_attr(attrs, keys, default=None)
    return default if value is None else value


def _optional_float_attr(
    attrs: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    default: float | None = None,
) -> float | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return float(attrs[key])
    return None if default is None else float(default)


def _vector3_from_any(value: Any) -> Vector3:
    if hasattr(value, "GetLength") and callable(value.GetLength):
        return (float(value[0]), float(value[1]), float(value[2]))
    return (float(value[0]), float(value[1]), float(value[2]))


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _normalize_paths(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    paths = tuple(_normalize_path(value, field_name=field_name) for value in values)
    if field_name == "discovery_roots" and not paths:
        raise ValueError("discovery_roots must not be empty.")
    return paths


def _normalize_path(value: str, *, field_name: str) -> str:
    path = str(value).strip().rstrip("/")
    if not path or not path.startswith("/"):
        raise ValueError(f"{field_name} entries must be absolute prim paths.")
    return path or "/"


def _missing_message(kind: str, explicit_path: str | None) -> str:
    if explicit_path is not None:
        return f"No {kind} prim found at {explicit_path!r}."
    return f"No {kind} prims were discovered from the configured stage roots."
