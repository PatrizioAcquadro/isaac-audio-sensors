"""TOML config loading and validation for audio scenes and sensors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

from isaac_audio_sensors.core.acoustics.environments import (
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
    surface_set_environment,
)
from isaac_audio_sensors.core.backends.base import registered_backend_ids
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_RUNTIME_PROFILE,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_SPEED_OF_SOUND_MPS,
    DOA_ESTIMATOR_IDS,
    RUNTIME_PROFILES,
)
from isaac_audio_sensors.core.effects.config import (
    EffectsConfig,
)
from isaac_audio_sensors.core.effects.parsing import parse_effects_config
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_effects_config,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.microphone_array import layout_rank_xy
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AcousticSurfaceSpec,
    AudioSceneSnapshot,
    AudioSourceSpec,
    MicrophoneArraySpec,
    MicrophoneSpec,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSensorConfig:
    """Validated TOML config data for scenes and sensor examples."""

    scene_id: str
    default_backend: str
    runtime_profile: str = DEFAULT_RUNTIME_PROFILE
    effects: EffectsConfig = field(default_factory=EffectsConfig)
    speed_of_sound_mps: float
    write_waveforms: bool
    waveform_dir: str | None
    doa_estimator: str = "tdoa_least_squares"
    sources: tuple[AudioSourceSpec, ...]
    arrays: dict[str, MicrophoneArraySpec]
    environment: AcousticEnvironmentSpec
    analytic_max_order: int
    analytic_air_absorption: bool
    analytic_ray_tracing: bool


def load_audio_config(path: str | Path) -> AudioSensorConfig:
    """Load and validate a TOML config file."""

    config_path = Path(path)
    with config_path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return validate_audio_config(raw)


def validate_audio_config(raw: dict[str, Any]) -> AudioSensorConfig:
    """Validate raw TOML data and return typed config records."""

    try:
        if "room" in raw:
            raise ConfigValidationError(
                "[room] was removed by R7.1; use the canonical [environment] table."
            )
        scene = _required_table(raw, "scene")
        audio = _required_table(raw, "audio")
        if "room_acoustics" in audio:
            raise ConfigValidationError(
                "[audio.room_acoustics] was removed by R8.3; use "
                "[audio.analytic_acoustics]."
            )
        if "sample_rate_hz" in audio:
            raise ConfigValidationError(
                "audio.sample_rate_hz was removed; configure "
                "arrays.*.sample_rate_hz."
            )
        if "tdoa_ambiguity_policy" in audio:
            raise ConfigValidationError(
                "audio.tdoa_ambiguity_policy was removed; contextual DOA "
                "disambiguation belongs in downstream consumers."
            )
        scene_id = _required_str(scene, "scene_id", table="scene")
        stage_units = str(scene.get("stage_units", "meters"))
        up_axis = str(scene.get("up_axis", "z")).lower()
        if stage_units != "meters":
            raise ConfigValidationError("scene.stage_units must be 'meters'.")
        if up_axis != "z":
            raise ConfigValidationError("scene.up_axis must be 'z'.")

        default_backend = str(audio.get("default_backend", "analytic_acoustics"))
        backend_ids = registered_backend_ids()
        if default_backend not in backend_ids:
            raise ConfigValidationError(
                f"audio.default_backend must be one of {list(backend_ids)}."
            )
        runtime_profile = str(audio.get("runtime_profile", DEFAULT_RUNTIME_PROFILE))
        if runtime_profile not in RUNTIME_PROFILES:
            raise ConfigValidationError(
                f"audio.runtime_profile must be one of {list(RUNTIME_PROFILES)}."
            )
        write_waveforms = bool(audio.get("write_waveforms", False))
        if runtime_profile == "training_features" and write_waveforms:
            raise ConfigValidationError(
                "audio.runtime_profile 'training_features' is incompatible with "
                "audio.write_waveforms=true; select 'waveform_fidelity' or disable "
                "waveform export."
            )
        speed_of_sound = float(
            audio.get("speed_of_sound_mps", DEFAULT_SPEED_OF_SOUND_MPS)
        )
        if speed_of_sound <= 0.0:
            raise ConfigValidationError("audio.speed_of_sound_mps must be positive.")
        doa_estimator = str(audio.get("doa_estimator", "tdoa_least_squares"))
        if doa_estimator not in DOA_ESTIMATOR_IDS:
            raise ConfigValidationError(
                f"audio.doa_estimator must be one of {sorted(DOA_ESTIMATOR_IDS)}."
            )

        sources = _parse_sources(raw.get("sources"))
        arrays = _parse_arrays(raw.get("arrays", {}))
        effects = parse_effects_config(audio.get("effects"))
        if effects.motion.segments_per_window > 1:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 requires a live "
                "Isaac pose-time stream; static/offline configuration is unsupported."
            )
        if effects.motion.derive_velocity_from_poses:
            collisions = sorted(
                {source.source_id for source in sources}.intersection(arrays)
            )
            if collisions:
                raise ConfigValidationError(
                    "audio.effects.motion.derive_velocity_from_poses=true requires "
                    "source ids and selected array ids to be disjoint; received "
                    f"collisions {collisions!r}."
                )
        for array in arrays.values():
            validate_effects_config(
                effects,
                microphone_orders=(
                    tuple(microphone.mic_id for microphone in array.microphones),
                ),
                sample_rate_hz=array.sample_rate_hz,
                backend_id=default_backend,
                runtime_profile=runtime_profile,
                microphone_self_noise_db={
                    microphone.mic_id: microphone.self_noise_db
                    for microphone in array.microphones
                },
            )
        environment = _parse_environment(raw.get("environment"))
        (
            analytic_max_order,
            analytic_air_absorption,
            analytic_ray_tracing,
        ) = _parse_analytic_acoustics_options(audio.get("analytic_acoustics"))
        _validate_backend_requirements(
            arrays=arrays,
            doa_estimator=doa_estimator,
            environment=environment,
            max_order=analytic_max_order,
            air_absorption=analytic_air_absorption,
            ray_tracing=analytic_ray_tracing,
        )
        return AudioSensorConfig(
            scene_id=scene_id,
            default_backend=default_backend,
            runtime_profile=runtime_profile,
            effects=effects,
            speed_of_sound_mps=speed_of_sound,
            write_waveforms=write_waveforms,
            waveform_dir=(
                None
                if audio.get("waveform_dir") is None
                else str(audio["waveform_dir"])
            ),
            doa_estimator=doa_estimator,
            sources=sources,
            arrays=arrays,
            environment=environment,
            analytic_max_order=analytic_max_order,
            analytic_air_absorption=analytic_air_absorption,
            analytic_ray_tracing=analytic_ray_tracing,
        )
    except KeyError as exc:
        raise ConfigValidationError(
            f"Missing required config key {exc.args[0]!r}."
        ) from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ConfigValidationError):
            raise
        raise ConfigValidationError(str(exc)) from exc


def build_scene_snapshot(config: AudioSensorConfig) -> AudioSceneSnapshot:
    """Build a scene snapshot from a validated config."""

    return AudioSceneSnapshot(
        stage_id=config.scene_id,
        sources=config.sources,
        arrays=tuple(config.arrays.values()),
        environment=config.environment,
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
                gain_db=raw_source.get("gain_db", 0.0),
                loop_count=raw_source.get("loop_count", 0),
                directivity=str(raw_source.get("directivity", "omni")),
                velocity_world_mps=(
                    None
                    if raw_source.get("velocity_world_mps") is None
                    else tuple(raw_source["velocity_world_mps"])
                ),
            )
        )
    return tuple(sources)


def _parse_arrays(raw_arrays: Any) -> dict[str, MicrophoneArraySpec]:
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
        microphones = _parse_microphones(raw_array.get("microphones", ()))
        arrays[array_id] = MicrophoneArraySpec(
            array_id=array_id,
            prim_path=_required_str(
                raw_array, "prim_path", table=f"arrays.{table_name}"
            ),
            position_world=tuple(raw_array.get("position_world", (0.0, 0.0, 0.0))),
            orientation_world_quat=orientation,
            microphones=microphones,
            sample_rate_hz=raw_array.get(
                "sample_rate_hz",
                DEFAULT_SAMPLE_RATE_HZ,
            ),
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
                gain_db=raw_microphone.get("gain_db", 0.0),
                self_noise_db=raw_microphone.get("self_noise_db"),
                directivity=str(raw_microphone.get("directivity", "omni")),
            )
        )
    return tuple(microphones)


def _parse_environment(raw_environment: Any) -> AcousticEnvironmentSpec:
    if raw_environment is None:
        raise ConfigValidationError("[environment] table is required by R7.2.")
    if not isinstance(raw_environment, dict):
        raise ConfigValidationError("[environment] must be a table.")
    environment_id = _required_str(
        raw_environment,
        "environment_id",
        table="environment",
    )
    kind = _required_str(raw_environment, "kind", table="environment")
    position = tuple(raw_environment.get("position_world", (0.0, 0.0, 0.0)))
    orientation = tuple(
        raw_environment.get("orientation_world_quat", (0.0, 0.0, 0.0, 1.0))
    )
    common = {
        "environment_id",
        "kind",
        "position_world",
        "orientation_world_quat",
    }
    if kind == "free_field":
        _reject_unknown_keys(raw_environment, common, table="environment")
        return free_field_environment(
            environment_id=environment_id,
            position_world=position,
            orientation_world_quat=orientation,
        )
    if kind == "half_space":
        _reject_unknown_keys(
            raw_environment,
            common | {"absorption"},
            table="environment",
        )
        return half_space_environment(
            environment_id=environment_id,
            absorption=raw_environment.get("absorption", 0.35),
            position_world=position,
            orientation_world_quat=orientation,
        )
    if kind == "shoebox":
        _reject_unknown_keys(
            raw_environment,
            common | {"dimensions_m", "absorption"},
            table="environment",
        )
        try:
            dimensions = tuple(raw_environment["dimensions_m"])
        except KeyError as exc:
            raise ConfigValidationError(
                "environment.dimensions_m is required for kind='shoebox'."
            ) from exc
        return shoebox_environment(
            environment_id=environment_id,
            dimensions_m=dimensions,
            absorption=raw_environment.get("absorption", 0.35),
            position_world=position,
            orientation_world_quat=orientation,
        )
    if kind == "polygon_prism":
        _reject_unknown_keys(
            raw_environment,
            common | {"floor_vertices_local_m", "height_m", "absorption"},
            table="environment",
        )
        try:
            floor_vertices = tuple(
                tuple(vertex) for vertex in raw_environment["floor_vertices_local_m"]
            )
            height_m = raw_environment["height_m"]
        except KeyError as exc:
            raise ConfigValidationError(
                "polygon_prism requires environment.floor_vertices_local_m and "
                "environment.height_m."
            ) from exc
        return polygon_prism_environment(
            environment_id=environment_id,
            floor_vertices_local_m=floor_vertices,
            height_m=height_m,
            absorption=raw_environment.get("absorption", 0.35),
            position_world=position,
            orientation_world_quat=orientation,
        )
    if kind == "surface_set":
        _reject_unknown_keys(
            raw_environment,
            common | {"surfaces"},
            table="environment",
        )
        raw_surfaces = raw_environment.get("surfaces")
        if not isinstance(raw_surfaces, list) or not raw_surfaces:
            raise ConfigValidationError(
                "[[environment.surfaces]] must define at least one surface."
            )
        surfaces: list[AcousticSurfaceSpec] = []
        for index, raw_surface in enumerate(raw_surfaces):
            if not isinstance(raw_surface, dict):
                raise ConfigValidationError(
                    "Each [[environment.surfaces]] entry must be a table."
                )
            table = f"environment.surfaces[{index}]"
            _reject_unknown_keys(
                raw_surface,
                {"surface_id", "role", "vertices_local_m", "absorption"},
                table=table,
            )
            try:
                vertices = tuple(
                    tuple(vertex) for vertex in raw_surface["vertices_local_m"]
                )
            except KeyError as exc:
                raise ConfigValidationError(
                    f"{table}.vertices_local_m is required."
                ) from exc
            surfaces.append(
                AcousticSurfaceSpec(
                    surface_id=_required_str(raw_surface, "surface_id", table=table),
                    role=_required_str(raw_surface, "role", table=table),
                    vertices_local_m=vertices,
                    absorption=raw_surface.get("absorption", 0.35),
                )
            )
        return surface_set_environment(
            environment_id=environment_id,
            surfaces=surfaces,
            position_world=position,
            orientation_world_quat=orientation,
        )
    raise ConfigValidationError(
        "environment.kind must be free_field, half_space, shoebox, "
        "polygon_prism, or surface_set."
    )


def _parse_analytic_acoustics_options(raw_options: Any) -> tuple[int, bool, bool]:
    if raw_options is None:
        return 0, False, False
    if not isinstance(raw_options, dict):
        raise ConfigValidationError("[audio.analytic_acoustics] must be a table.")
    _reject_unknown_keys(
        raw_options,
        {"max_order", "air_absorption", "ray_tracing"},
        table="audio.analytic_acoustics",
    )
    max_order = raw_options.get("max_order", 0)
    if type(max_order) is not int or max_order < 0:
        raise ConfigValidationError(
            "audio.analytic_acoustics.max_order must be a non-negative integer."
        )
    air_absorption = raw_options.get("air_absorption", False)
    ray_tracing = raw_options.get("ray_tracing", False)
    if type(air_absorption) is not bool:
        raise ConfigValidationError(
            "audio.analytic_acoustics.air_absorption must be a boolean."
        )
    if type(ray_tracing) is not bool:
        raise ConfigValidationError(
            "audio.analytic_acoustics.ray_tracing must be a boolean."
        )
    return max_order, air_absorption, ray_tracing


def _validate_backend_requirements(
    *,
    arrays: dict[str, MicrophoneArraySpec],
    doa_estimator: str,
    environment: AcousticEnvironmentSpec,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
) -> None:
    for array in arrays.values():
        minimum = 3 if doa_estimator == "srp_phat" else 2
        if len(array.microphones) < minimum:
            raise ConfigValidationError(
                f"{doa_estimator} requires at least {minimum} microphones "
                f"for array {array.array_id!r}."
            )
        rank_xy = layout_rank_xy(array)
        if len(array.microphones) == 2 and rank_xy < 1:
            raise ConfigValidationError(
                f"Two-microphone array {array.array_id!r} requires distinct "
                "microphone positions in local XY."
            )
        if len(array.microphones) >= 3 and rank_xy < 2:
            raise ConfigValidationError(
                f"{doa_estimator} requires at least three non-collinear "
                f"microphones in local XY for array {array.array_id!r}."
            )
    if environment.kind == "surface_set":
        raise ConfigValidationError(
            "analytic_acoustics does not support environment.kind='surface_set' "
            "in R8.1; use GeometryAcoustics when it becomes available."
        )
    if environment.kind == "free_field" and max_order != 0:
        raise ConfigValidationError(
            "free_field analytic propagation requires max_order=0."
        )
    if environment.kind == "half_space" and max_order not in {0, 1}:
        raise ConfigValidationError(
            "half_space analytic propagation supports max_order 0 or 1."
        )
    if environment.kind in {"free_field", "half_space"} and air_absorption:
        raise ConfigValidationError(
            "air_absorption is available only for PyRoom analytic solvers in R8.1."
        )
    if environment.kind in {"free_field", "half_space"} and ray_tracing:
        raise ConfigValidationError(
            "ray_tracing is available only for PyRoom analytic solvers."
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


def _reject_unknown_keys(
    raw: dict[str, Any],
    allowed: set[str],
    *,
    table: str,
) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigValidationError(f"{table} contains unknown keys {unknown!r}.")
