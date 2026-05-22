"""Build core scene snapshots from config or duck-typed USD stages."""

from __future__ import annotations

from typing import Any

from isaac_audio_sensors.core.config import AudioSensorConfig, build_scene_snapshot
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.core.math_utils import basis_from_quaternion
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
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
    default_class_label: str = "Sound",
) -> AudioSceneSnapshot:
    """Build a static core snapshot from a USD-like stage.

    The function accepts real USD stages and lightweight duck-typed test
    stages. It reads ordinary sound prims plus namespaced ``ias:*`` microphone
    metadata, with transforms represented as either ``ias:position_world`` or
    ``xformOp:translate`` attributes.
    """

    prims = _traverse(stage)
    arrays = tuple(
        _array_from_prim(prim, prims)
        for prim in prims
        if _is_array_prim(prim)
        and (array_prim_path is None or _prim_path(prim) == array_prim_path)
    )
    if array_prim_path is not None and not arrays:
        raise ValueError(f"No microphone array prim found at {array_prim_path!r}.")

    sources = tuple(
        _source_from_prim(prim, default_class_label=default_class_label)
        for prim in prims
        if _is_sound_prim(prim)
    )
    return AudioSceneSnapshot(
        stage_id=stage_id or _stage_id(stage),
        timestamp_ms=timestamp_ms,
        sources=sources,
        arrays=arrays,
        room=None,
    )


def _source_from_prim(prim: Any, *, default_class_label: str) -> AudioSourceSpec:
    attrs = _attrs(prim)
    path = _prim_path(prim)
    source_id = str(attrs.get("ias:source_id", _path_name(path)))
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=path,
        class_label=str(attrs.get("ias:class_label", default_class_label)),
        audio_asset_path=_asset_path(attrs.get("filePath", attrs.get("inputs:file"))),
        position_world=_vec3_attr(
            attrs,
            ("ias:position_world", "xformOp:translate"),
            default=(0.0, 0.0, 0.0),
        ),
        orientation_world_quat=_quat_attr(
            attrs,
            ("ias:orientation_world_quat", "xformOp:orient"),
            default=None,
        ),
        start_time_s=_float_attr(attrs, ("ias:start_time_s", "startTime"), default=0.0),
        duration_s=_optional_float_attr(attrs, ("ias:duration_s", "duration")),
        gain_db=_float_attr(attrs, ("ias:gain_db", "gain"), default=0.0),
        directivity=str(attrs.get("ias:directivity", "omni")),
    )


def _array_from_prim(prim: Any, prims: tuple[Any, ...]) -> MicrophoneArraySpec:
    attrs = _attrs(prim)
    path = _prim_path(prim)
    array_id = str(attrs.get("ias:array_id", _path_name(path)))
    orientation = _quat_attr(
        attrs,
        ("ias:orientation_world_quat", "xformOp:orient"),
        default=(0.0, 0.0, 0.0, 1.0),
    )
    if orientation is None:
        orientation = (0.0, 0.0, 0.0, 1.0)
    forward, right, up = basis_from_quaternion(orientation)
    microphones = _microphones_for_array(path, attrs, prims)
    return MicrophoneArraySpec(
        array_id=array_id,
        prim_path=path,
        position_world=_vec3_attr(
            attrs,
            ("ias:position_world", "xformOp:translate"),
            default=(0.0, 0.0, 0.0),
        ),
        orientation_world_quat=orientation,
        forward_vec_world=_vec3_attr(
            attrs, ("ias:forward_vec_world",), default=forward
        ),
        right_vec_world=_vec3_attr(attrs, ("ias:right_vec_world",), default=right),
        up_vec_world=_vec3_attr(attrs, ("ias:up_vec_world",), default=up),
        microphones=microphones,
        sample_rate_hz=int(attrs.get("ias:sample_rate_hz", DEFAULT_SAMPLE_RATE_HZ)),
        coordinate_convention=str(
            attrs.get("ias:coordinate_convention", COORDINATE_CONVENTION)
        ),
    )


def _microphones_for_array(
    array_path: str,
    array_attrs: dict[str, Any],
    prims: tuple[Any, ...],
) -> tuple[MicrophoneSpec, ...]:
    microphones: list[MicrophoneSpec] = []
    for prim in prims:
        path = _prim_path(prim)
        if not path.startswith(f"{array_path}/"):
            continue
        attrs = _attrs(prim)
        mic_id = attrs.get("ias:microphone_id")
        if mic_id is None:
            continue
        microphones.append(
            MicrophoneSpec(
                mic_id=str(mic_id),
                relative_position_m=_vec3_attr(
                    attrs,
                    ("ias:relative_position_m", "xformOp:translate"),
                    default=(0.0, 0.0, 0.0),
                ),
                relative_orientation_quat=_quat_attr(
                    attrs,
                    ("ias:relative_orientation_quat", "xformOp:orient"),
                    default=None,
                ),
                gain_db=_float_attr(attrs, ("ias:gain_db",), default=0.0),
                self_noise_db=_optional_float_attr(attrs, ("ias:self_noise_db",)),
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


def _traverse(stage: Any) -> tuple[Any, ...]:
    if stage is None or not hasattr(stage, "Traverse"):
        raise ValueError("stage must provide a Traverse method.")
    return tuple(stage.Traverse())


def _is_sound_prim(prim: Any) -> bool:
    attrs = _attrs(prim)
    return _prim_type_name(prim) == "Sound" or "filePath" in attrs


def _is_array_prim(prim: Any) -> bool:
    return _attrs(prim).get("ias:array_id") is not None


def _attrs(prim: Any) -> dict[str, Any]:
    if hasattr(prim, "attributes"):
        return dict(prim.attributes)
    attrs: dict[str, Any] = {}
    if hasattr(prim, "GetAttributes"):
        for attr in prim.GetAttributes():
            if hasattr(attr, "GetName") and hasattr(attr, "Get"):
                attrs[str(attr.GetName())] = attr.Get()
    return attrs


def _prim_type_name(prim: Any) -> str:
    if hasattr(prim, "GetTypeName"):
        return str(prim.GetTypeName())
    return str(getattr(prim, "type_name", ""))


def _prim_path(prim: Any) -> str:
    if hasattr(prim, "GetPath"):
        return str(prim.GetPath())
    return str(getattr(prim, "path", ""))


def _stage_id(stage: Any) -> str:
    if hasattr(stage, "GetRootLayer"):
        root_layer = stage.GetRootLayer()
        identifier = getattr(root_layer, "identifier", None)
        if identifier:
            return str(identifier)
    identifier = getattr(stage, "identifier", None)
    return str(identifier or "isaac_stage")


def _path_name(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or "prim"


def _asset_path(value: Any) -> str | None:
    if value is None:
        return None
    path = getattr(value, "path", None)
    return str(path if path is not None else value)


def _vec3_attr(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
    *,
    default: tuple[float, float, float],
) -> tuple[float, float, float]:
    for key in keys:
        if key in attrs:
            x, y, z = attrs[key]
            return (float(x), float(y), float(z))
    return default


def _quat_attr(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
    *,
    default: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    for key in keys:
        if key not in attrs:
            continue
        value = attrs[key]
        if hasattr(value, "GetImaginary") and hasattr(value, "GetReal"):
            x, y, z = value.GetImaginary()
            return (float(x), float(y), float(z), float(value.GetReal()))
        x, y, z, w = value
        return (float(x), float(y), float(z), float(w))
    return default


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
