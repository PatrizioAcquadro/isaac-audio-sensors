"""Build core scene snapshots from config or live USD-like stages."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.config import AudioSensorConfig, build_scene_snapshot
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    basis_from_quaternion,
    normalize_quaternion,
    quaternion_conjugate,
    quaternion_multiply,
    rotate_vector_by_quaternion,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    discover_stage_audio,
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


def export_config_snapshot(
    config: AudioSensorConfig,
    *,
    timestamp_ms: int,
) -> AudioSceneSnapshot:
    """Return the config-authored snapshot used by offline Isaac smoke demos."""

    return build_scene_snapshot(config, timestamp_ms=timestamp_ms)


def build_stage_snapshot(
    stage: Any,
    *,
    timestamp_ms: int,
    stage_id: str | None = None,
    array_prim_path: str | None = None,
    robot_base_prim_path: str | None = None,
    source_prim_path: str | None = None,
    usd_time_code: Any | None = None,
    time_code: Any | None = None,
    default_class_label: str = "Sound",
    discovery_cfg: IsaacAudioDiscoveryCfg | None = None,
    preferred_array: str | None = None,
    preferred_source: str | None = None,
    diagnostics_out: dict[str, Any] | None = None,
) -> AudioSceneSnapshot:
    """Build a live core snapshot from a real USD or duck-typed stage.

    Real Isaac/pxr stages are resolved through lazy USD transform APIs when
    available. Lightweight test stages fall back to namespaced world-pose attrs
    and simple ``xformOp:translate``/``xformOp:orient`` parent stacks.
    """

    cfg = discovery_cfg or IsaacAudioDiscoveryCfg(
        discovery_roots=("/World",),
        robot_base_prim_path=robot_base_prim_path,
        required_arrays=array_prim_path is not None,
        required_sources=source_prim_path is not None,
        default_class_label=default_class_label,
        strict_candidate_errors=True,
    )
    if discovery_cfg is not None and robot_base_prim_path is not None:
        cfg = IsaacAudioDiscoveryCfg(
            discovery_roots=cfg.discovery_roots,
            robot_base_prim_path=robot_base_prim_path,
            array_roots=cfg.array_roots,
            source_roots=cfg.source_roots,
            restrict_arrays_to_robot=cfg.restrict_arrays_to_robot,
            include_globs=cfg.include_globs,
            exclude_globs=cfg.exclude_globs,
            include_regexes=cfg.include_regexes,
            exclude_regexes=cfg.exclude_regexes,
            array_name_patterns=cfg.array_name_patterns,
            array_type_name_patterns=cfg.array_type_name_patterns,
            source_name_patterns=cfg.source_name_patterns,
            source_type_names=cfg.source_type_names,
            default_class_label=cfg.default_class_label,
            source_class_label_overrides=cfg.source_class_label_overrides,
            default_microphone_layout=cfg.default_microphone_layout,
            default_sample_rate_hz=cfg.default_sample_rate_hz,
            coordinate_convention=cfg.coordinate_convention,
            required_arrays=cfg.required_arrays or array_prim_path is not None,
            required_sources=cfg.required_sources or source_prim_path is not None,
            default_source_start_time_s=cfg.default_source_start_time_s,
            default_source_duration_s=cfg.default_source_duration_s,
            metadata_precedence=cfg.metadata_precedence,
            strict_candidate_errors=cfg.strict_candidate_errors,
        )
    result = discover_stage_audio(
        stage,
        cfg=cfg,
        timestamp_ms=timestamp_ms,
        stage_id=stage_id,
        usd_time_code=usd_time_code,
        time_code=time_code,
        explicit_array_prim_path=array_prim_path,
        explicit_source_prim_path=source_prim_path,
        preferred_array=preferred_array,
        preferred_source=preferred_source,
    )
    diagnostics = dict(result.diagnostics)
    if diagnostics_out is not None:
        diagnostics_out.clear()
        diagnostics_out.update(diagnostics)

    return AudioSceneSnapshot(
        stage_id=result.stage_id,
        timestamp_ms=timestamp_ms,
        sources=(
            (result.selected_source.spec,)
            if preferred_source is not None and result.selected_source is not None
            else tuple(source.spec for source in result.sources)
        ),
        arrays=tuple(array.spec for array in result.arrays),
        room=None,
    )


def _source_from_prim(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    default_class_label: str,
    diagnostics: dict[str, Any],
) -> AudioSourceSpec:
    attrs = resolver.attrs(prim)
    path = prim_path(prim)
    pose = resolver.resolve_world_pose(prim, field_name=path)
    diagnostics["source_transforms"][path] = _pose_diagnostics(pose)
    source_id = str(attrs.get("ias:source_id", _path_name(path)))
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=path,
        class_label=str(attrs.get("ias:class_label", default_class_label)),
        audio_asset_path=_asset_path(attrs.get("filePath", attrs.get("inputs:file"))),
        position_world=pose.position_world,
        orientation_world_quat=pose.orientation_world_quat,
        start_time_s=_float_attr(attrs, ("ias:start_time_s", "startTime"), default=0.0),
        duration_s=_optional_float_attr(attrs, ("ias:duration_s", "duration")),
        gain_db=_float_attr(attrs, ("ias:gain_db", "gain"), default=0.0),
        directivity=str(attrs.get("ias:directivity", "omni")),
    )


def _array_from_prim(
    prim: Any,
    *,
    resolver: IsaacStagePoseResolver,
    diagnostics: dict[str, Any],
) -> MicrophoneArraySpec:
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
    diagnostics["array_transforms"][path] = _pose_diagnostics(array_pose)
    microphones = _microphones_for_array(
        array_path=path,
        array_attrs=attrs,
        resolver=resolver,
        array_pose=array_pose,
        diagnostics=diagnostics,
    )
    forward, right, up = basis_from_quaternion(orientation)
    array_id = str(attrs.get("ias:array_id", _path_name(path)))
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=path,
        position_world=pose.position_world,
        orientation_world_quat=orientation,
        forward_vec_world=forward,
        right_vec_world=right,
        up_vec_world=up,
        microphones=microphones,
        sample_rate_hz=int(attrs.get("ias:sample_rate_hz", DEFAULT_SAMPLE_RATE_HZ)),
        coordinate_convention=str(
            attrs.get("ias:coordinate_convention", COORDINATE_CONVENTION)
        ),
    )


def _microphones_for_array(
    *,
    array_path: str,
    array_attrs: dict[str, Any],
    resolver: IsaacStagePoseResolver,
    array_pose: StagePose,
    diagnostics: dict[str, Any],
) -> tuple[MicrophoneSpec, ...]:
    microphones: list[MicrophoneSpec] = []
    prefix = f"{array_path.rstrip('/')}/"
    for prim in sorted(resolver.prims, key=prim_path):
        path = prim_path(prim)
        if not path.startswith(prefix):
            continue
        attrs = resolver.attrs(prim)
        if not _looks_like_microphone_child(attrs, prim):
            continue
        child_pose: StagePose | None = None
        relative_position = optional_vec3_attr(attrs, ("ias:relative_position_m",))
        if relative_position is None:
            child_pose = resolver.resolve_world_pose(prim, field_name=path)
            relative_position = _relative_position_from_world(
                child_pose,
                array_pose,
            )
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
        diagnostics["microphone_transforms"][path] = {
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
    if microphones:
        return tuple(microphones)
    layout_name = array_attrs.get("ias:layout_name")
    if layout_name is not None:
        return microphone_layout(str(layout_name))
    raise ValueError(
        f"Microphone array {array_path!r} has no microphone child prims and no layout."
    )


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


def _is_sound_prim(prim: Any, resolver: IsaacStagePoseResolver) -> bool:
    attrs = resolver.attrs(prim)
    return prim_type_name(prim) == "Sound" or "filePath" in attrs


def _is_array_prim(prim: Any, resolver: IsaacStagePoseResolver) -> bool:
    return resolver.attrs(prim).get("ias:array_id") is not None


def _looks_like_microphone_child(attrs: dict[str, Any], prim: Any) -> bool:
    if "ias:microphone_id" in attrs or "ias:relative_position_m" in attrs:
        return True
    type_name = prim_type_name(prim).lower()
    return "microphone" in type_name or _path_name(prim_path(prim)).lower() == "mic"


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


def _base_diagnostics(
    *,
    stage_id: str,
    timestamp_ms: int,
    array_prim_path: str | None,
    robot_base_prim_path: str | None,
    source_prim_path: str | None,
    time_code: Any | None,
) -> dict[str, Any]:
    return {
        "provenance": "isaac_sim_live_usd_stage_snapshot",
        "stage_id": stage_id,
        "timestamp_ms": int(timestamp_ms),
        "time_code": diagnostic_time_code(time_code),
        "array_prim_path": array_prim_path,
        "robot_base_prim_path": robot_base_prim_path,
        "source_prim_path": source_prim_path,
        "transform_resolver": "IsaacStagePoseResolver",
        "coordinate_frames": {
            "world": "USD stage world frame",
            "robot_base": "optional robot/base prim resolved in world frame",
            "array": "microphone array prim resolved in world frame",
            "microphone": "array-local microphone offsets derived from child prims",
        },
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


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _asset_path(value: Any) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    return str(path if path is not None else value)


def _float_attr(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
    *,
    default: float,
) -> float:
    value = _optional_float_attr(attrs, keys)
    return default if value is None else value


def _optional_float_attr(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return float(attrs[key])
    return None
