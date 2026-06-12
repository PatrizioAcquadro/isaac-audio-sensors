"""TOML config loading and validation for audio scenes and sensors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_SPEED_OF_SOUND_MPS,
    KNOWN_BACKENDS,
    TDOA_AMBIGUITY_POLICIES,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.math_utils import basis_from_quaternion
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
    RoomAcousticsSpec,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSensorConfig:
    """Validated TOML config data for scenes and sensor examples."""

    scene_id: str
    stage_units: str
    up_axis: str
    default_backend: str
    sample_rate_hz: int
    speed_of_sound_mps: float
    write_waveforms: bool
    waveform_dir: str | None
    tdoa_ambiguity_policy: str
    sources: tuple[AudioSourceSpec, ...]
    arrays: dict[str, MicrophoneArraySpec]
    room: RoomAcousticsSpec | None
    lab: dict[str, Any]


def load_audio_config(path: str | Path) -> AudioSensorConfig:
    """Load and validate a TOML config file."""

    config_path = Path(path)
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return validate_audio_config(raw)


def validate_audio_config(raw: dict[str, Any]) -> AudioSensorConfig:
    """Validate raw TOML data and return typed config records."""

    try:
        scene = _required_table(raw, "scene")
        audio = _required_table(raw, "audio")
        scene_id = _required_str(scene, "scene_id", table="scene")
        stage_units = str(scene.get("stage_units", "meters"))
        up_axis = str(scene.get("up_axis", "z")).lower()
        if stage_units != "meters":
            raise ConfigValidationError("scene.stage_units must be 'meters'.")
        if up_axis != "z":
            raise ConfigValidationError("scene.up_axis must be 'z'.")

        sample_rate_hz = int(audio.get("sample_rate_hz", DEFAULT_SAMPLE_RATE_HZ))
        if sample_rate_hz <= 0:
            raise ConfigValidationError("audio.sample_rate_hz must be positive.")
        default_backend = str(audio.get("default_backend", "geometry_only"))
        if default_backend not in KNOWN_BACKENDS:
            raise ConfigValidationError(
                f"audio.default_backend must be one of {sorted(KNOWN_BACKENDS)}."
            )
        speed_of_sound = float(
            audio.get("speed_of_sound_mps", DEFAULT_SPEED_OF_SOUND_MPS)
        )
        if speed_of_sound <= 0.0:
            raise ConfigValidationError("audio.speed_of_sound_mps must be positive.")
        ambiguity_policy_explicit = "tdoa_ambiguity_policy" in audio
        ambiguity_policy = str(audio.get("tdoa_ambiguity_policy", "none"))
        if ambiguity_policy not in TDOA_AMBIGUITY_POLICIES:
            raise ConfigValidationError(
                "audio.tdoa_ambiguity_policy must be 'none' or 'front_hemisphere'."
            )

        sources = _parse_sources(raw.get("sources"))
        arrays = _parse_arrays(raw.get("arrays", {}), sample_rate_hz=sample_rate_hz)
        room = _parse_room(raw.get("room"))
        lab = dict(raw.get("lab", {}))
        _validate_lab(lab)
        _validate_backend_requirements(
            default_backend=default_backend,
            arrays=arrays,
            ambiguity_policy=ambiguity_policy,
            ambiguity_policy_explicit=ambiguity_policy_explicit,
        )
        return AudioSensorConfig(
            scene_id=scene_id,
            stage_units=stage_units,
            up_axis=up_axis,
            default_backend=default_backend,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=speed_of_sound,
            write_waveforms=bool(audio.get("write_waveforms", False)),
            waveform_dir=(
                None
                if audio.get("waveform_dir") is None
                else str(audio["waveform_dir"])
            ),
            tdoa_ambiguity_policy=ambiguity_policy,
            sources=sources,
            arrays=arrays,
            room=room,
            lab=lab,
        )
    except KeyError as exc:
        raise ConfigValidationError(
            f"Missing required config key {exc.args[0]!r}."
        ) from exc
    except ValueError as exc:
        if isinstance(exc, ConfigValidationError):
            raise
        raise ConfigValidationError(str(exc)) from exc


def build_scene_snapshot(
    config: AudioSensorConfig,
    *,
    timestamp_ms: int,
) -> AudioSceneSnapshot:
    """Build a scene snapshot from a validated config."""

    return AudioSceneSnapshot(
        stage_id=config.scene_id,
        timestamp_ms=timestamp_ms,
        sources=config.sources,
        arrays=tuple(config.arrays.values()),
        room=config.room,
    )


def _parse_sources(raw_sources: Any) -> tuple[AudioSourceSpec, ...]:
    if raw_sources is None:
        return ()
    if not isinstance(raw_sources, list):
        raise ConfigValidationError("[[sources]] must be a list of tables.")
    sources: list[AudioSourceSpec] = []
    seen: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ConfigValidationError("Each source must be a table.")
        source_id = _required_str(raw_source, "source_id", table="sources")
        if source_id in seen:
            raise ConfigValidationError(f"Duplicate source id {source_id!r}.")
        seen.add(source_id)
        sources.append(
            AudioSourceSpec(
                source_id=source_id,
                prim_path=_required_str(raw_source, "prim_path", table="sources"),
                class_label=_required_str(raw_source, "class_label", table="sources"),
                audio_asset_path=raw_source.get("audio_asset_path"),
                position_world=tuple(raw_source.get("position_world", (0.0, 0.0, 0.0))),
                orientation_world_quat=raw_source.get("orientation_world_quat"),
                start_time_s=float(raw_source.get("start_time_s", 0.0)),
                duration_s=(
                    None
                    if raw_source.get("duration_s") is None
                    else float(raw_source["duration_s"])
                ),
                gain_db=float(raw_source.get("gain_db", 0.0)),
                directivity=str(raw_source.get("directivity", "omni")),
            )
        )
    return tuple(sources)


def _parse_arrays(
    raw_arrays: Any,
    *,
    sample_rate_hz: int,
) -> dict[str, MicrophoneArraySpec]:
    if not isinstance(raw_arrays, dict) or not raw_arrays:
        raise ConfigValidationError("[arrays] must define at least one array.")
    arrays: dict[str, MicrophoneArraySpec] = {}
    for table_name, raw_array in raw_arrays.items():
        if not isinstance(raw_array, dict):
            raise ConfigValidationError("Each arrays entry must be a table.")
        array_id = str(raw_array.get("array_id", table_name))
        if array_id in arrays:
            raise ConfigValidationError(f"Duplicate array id {array_id!r}.")
        orientation = tuple(
            raw_array.get("orientation_world_quat", (0.0, 0.0, 0.0, 1.0))
        )
        forward, right, up = basis_from_quaternion(orientation)
        microphones = _parse_microphones(raw_array.get("microphones", ()))
        arrays[array_id] = MicrophoneArraySpec(
            array_id=array_id,
            prim_path=_required_str(
                raw_array, "prim_path", table=f"arrays.{table_name}"
            ),
            position_world=tuple(raw_array.get("position_world", (0.0, 0.0, 0.0))),
            orientation_world_quat=orientation,
            forward_vec_world=tuple(raw_array.get("forward_vec_world", forward)),
            right_vec_world=tuple(raw_array.get("right_vec_world", right)),
            up_vec_world=tuple(raw_array.get("up_vec_world", up)),
            microphones=microphones,
            sample_rate_hz=int(raw_array.get("sample_rate_hz", sample_rate_hz)),
            coordinate_convention=str(
                raw_array.get("coordinate_convention", COORDINATE_CONVENTION)
            ),
        )
    return arrays


def _parse_microphones(raw_microphones: Any) -> tuple[MicrophoneSpec, ...]:
    if not isinstance(raw_microphones, list) or not raw_microphones:
        raise ConfigValidationError("arrays.*.microphones must be a non-empty list.")
    microphones: list[MicrophoneSpec] = []
    seen: set[str] = set()
    for raw_microphone in raw_microphones:
        if not isinstance(raw_microphone, dict):
            raise ConfigValidationError("Each microphone must be a table.")
        mic_id = _required_str(raw_microphone, "mic_id", table="microphones")
        if mic_id in seen:
            raise ConfigValidationError(f"Duplicate microphone id {mic_id!r}.")
        seen.add(mic_id)
        microphones.append(
            MicrophoneSpec(
                mic_id=mic_id,
                relative_position_m=tuple(
                    raw_microphone.get("relative_position_m", (0.0, 0.0, 0.0))
                ),
                relative_orientation_quat=raw_microphone.get(
                    "relative_orientation_quat"
                ),
                gain_db=float(raw_microphone.get("gain_db", 0.0)),
                self_noise_db=raw_microphone.get("self_noise_db"),
            )
        )
    return tuple(microphones)


def _parse_room(raw_room: Any) -> RoomAcousticsSpec | None:
    if raw_room is None:
        return None
    if not isinstance(raw_room, dict):
        raise ConfigValidationError("[room] must be a table.")
    return RoomAcousticsSpec(
        room_id=_required_str(raw_room, "room_id", table="room"),
        dimensions_m=tuple(raw_room["dimensions_m"]),
        absorption=raw_room.get("absorption", 0.35),
        max_order=int(raw_room.get("max_order", 0)),
        air_absorption=bool(raw_room.get("air_absorption", False)),
        ray_tracing=bool(raw_room.get("ray_tracing", False)),
        origin_m=tuple(raw_room.get("origin_m", (0.0, 0.0, 0.0))),
        out_of_bounds=str(raw_room.get("out_of_bounds", "error")),
    )


def _validate_lab(lab: dict[str, Any]) -> None:
    if not lab:
        return
    if float(lab.get("update_period", 0.0)) < 0.0:
        raise ConfigValidationError("lab.update_period must be non-negative.")
    prim_path = lab.get("prim_path")
    if prim_path is not None and str(prim_path).strip() == "":
        raise ConfigValidationError("lab.prim_path must be non-empty.")


def _validate_backend_requirements(
    *,
    default_backend: str,
    arrays: dict[str, MicrophoneArraySpec],
    ambiguity_policy: str,
    ambiguity_policy_explicit: bool,
) -> None:
    if default_backend == "geometry_only":
        return
    for array in arrays.values():
        if default_backend in {"tdoa_synthetic", "room_acoustics"}:
            if len(array.microphones) < 2:
                raise ConfigValidationError(
                    f"{default_backend} requires at least two microphones "
                    f"for array {array.array_id!r}."
                )
            if len(array.microphones) == 2 and (
                not ambiguity_policy_explicit
                or ambiguity_policy not in TDOA_AMBIGUITY_POLICIES
            ):
                raise ConfigValidationError(
                    "2-mic TDOA configs must select an ambiguity policy."
                )


def _required_table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigValidationError(f"[{key}] table is required.")
    return value


def _required_str(raw: dict[str, Any], key: str, *, table: str) -> str:
    value = raw[key]
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigValidationError(f"{table}.{key} must be a non-empty string.")
    return value
