"""Topology-routed analytic acoustic propagation."""

from __future__ import annotations

import importlib
import math
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.environments import (
    world_to_environment_point,
)
from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.backends.room_acoustics.assembly import assemble_frame
from isaac_audio_sensors.core.backends.room_acoustics.backend import (
    DOA_ESTIMATOR_IDS,
)
from isaac_audio_sensors.core.backends.room_acoustics.detections import (
    assemble_detections,
)
from isaac_audio_sensors.core.backends.room_acoustics.preparation import (
    PreparedRoomFrame,
    prepare_room_frame,
)
from isaac_audio_sensors.core.backends.room_acoustics.rendering import (
    RenderedRoom,
    _apply_band_attenuation,
    _apply_entity_directivity_to_premix,
    apply_room_effects,
    render_room,
)
from isaac_audio_sensors.core.backends.room_acoustics.signals import (
    _doppler_resampled_signal,
    _scheduled_window_signal,
)
from isaac_audio_sensors.core.constants import (
    DEFAULT_SPEED_OF_SOUND_MPS,
    EPSILON,
)
from isaac_audio_sensors.core.directivity import DIRECTIVITY_MODE
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.validation import UnsupportedEffectError
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.math_utils import norm, subtract
from isaac_audio_sensors.core.motion import WindowMotionPlan
from isaac_audio_sensors.core.motion.doppler import source_doppler_factor
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
)

ANALYTIC_SOLVER_BY_ENVIRONMENT = {
    "free_field": "free_field_direct",
    "half_space": "half_space_image_source",
    "shoebox": "pyroom_shoebox",
    "polygon_prism": "pyroom_polygon_prism",
}
_CORE_SOLVERS = frozenset({"free_field_direct", "half_space_image_source"})
_CORE_PROVIDER = SimpleNamespace(__version__="core")


class AnalyticAcoustics:
    """Deterministic propagation selected from the canonical environment."""

    backend_id = "analytic_acoustics"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        gcc_phat_interp: int = 8,
        waveform_writer: WaveformSink | None = None,
        doa_estimator: str = "tdoa_least_squares",
        max_order: int = 0,
        air_absorption: bool = False,
        ray_tracing: bool = False,
        effects: EffectsConfig | None = None,
        runtime_profile: str = "waveform_fidelity",
        window_motion: WindowMotionPlan | None = None,
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if doa_estimator not in DOA_ESTIMATOR_IDS:
            raise ValueError(
                f"doa_estimator must be one of {sorted(DOA_ESTIMATOR_IDS)}."
            )
        if isinstance(max_order, bool) or not isinstance(max_order, int):
            raise TypeError("max_order must be an integer.")
        if max_order < 0:
            raise ValueError("max_order must be non-negative.")
        if not isinstance(air_absorption, bool):
            raise TypeError("air_absorption must be a boolean.")
        if not isinstance(ray_tracing, bool):
            raise TypeError("ray_tracing must be a boolean.")
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
        self.gcc_phat_interp = int(gcc_phat_interp)
        self.waveform_writer = waveform_writer
        self.doa_estimator = doa_estimator
        self.max_order = max_order
        self.air_absorption = air_absorption
        self.ray_tracing = ray_tracing
        self.effects = EffectsConfig() if effects is None else effects
        self.runtime_profile = runtime_profile
        self.window_motion = window_motion
        self.effects_chain = ChannelEffectsChain(self.effects)

    @staticmethod
    def is_available() -> bool:
        """The Core direct and half-space solvers are always available."""

        return True

    @staticmethod
    def closed_rooms_available() -> bool:
        """Return whether the optional closed-room provider imports."""

        try:
            importlib.import_module("pyroomacoustics")
        except ImportError:
            return False
        return True

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        array_id: str,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        sensor = scene.array_by_id(array_id)
        environment = scene.environment
        if environment is None:
            raise ValueError(
                "analytic_acoustics requires AudioSceneSnapshot.environment."
            )
        solver_id = self._solver_for(environment)
        self._validate_solver_options(solver_id)
        if scene.occlusion:
            raise UnsupportedEffectError(
                "analytic_acoustics rejects SourceOcclusion during R8.1; "
                "direct-stem-only occlusion belongs to R8.2."
            )
        if (
            solver_id in _CORE_SOLVERS
            and self.effects.motion.segments_per_window > 1
        ):
            raise UnsupportedEffectError(
                "R8.1 Core analytic solvers do not support "
                "audio.effects.motion.segments_per_window>1."
            )
        provider_factory = (
            (lambda: _CORE_PROVIDER)
            if solver_id in _CORE_SOLVERS
            else _import_pyroomacoustics
        )
        prepared = prepare_room_frame(
            scene,
            sensor,
            time_window,
            backend_id=self.backend_id,
            effects=self.effects,
            runtime_profile=self.runtime_profile,
            max_order=self.max_order,
            air_absorption=self.air_absorption,
            ray_tracing=self.ray_tracing,
            window_motion=self.window_motion,
            import_pyroomacoustics=provider_factory,
            allowed_environment_kinds=tuple(ANALYTIC_SOLVER_BY_ENVIRONMENT),
            per_surface_materials=True,
            require_three_mics=self.doa_estimator == "srp_phat",
        )
        if solver_id in _CORE_SOLVERS:
            rendered = _render_core(
                prepared,
                speed_of_sound_mps=self.speed_of_sound_mps,
            )
        else:
            rendered = render_room(
                prepared,
                effects=self.effects,
                speed_of_sound_mps=self.speed_of_sound_mps,
                window_motion=self.window_motion,
            )
        apply_room_effects(
            prepared,
            rendered,
            effects=self.effects,
            effects_chain=self.effects_chain,
            backend_id=self.backend_id,
            runtime_profile=self.runtime_profile,
        )
        detections, per_source_rir_summary = assemble_detections(
            prepared,
            rendered,
            backend_id=self.backend_id,
            speed_of_sound_mps=self.speed_of_sound_mps,
            ambiguity_policy=self.ambiguity_policy,
            gcc_phat_interp=self.gcc_phat_interp,
            doa_estimator=self.doa_estimator,
        )
        frame = assemble_frame(
            prepared,
            rendered,
            detections,
            per_source_rir_summary,
            backend_id=self.backend_id,
            speed_of_sound_mps=self.speed_of_sound_mps,
            ambiguity_policy=self.ambiguity_policy,
            doa_estimator=self.doa_estimator,
            waveform_writer=self.waveform_writer,
            window_motion=self.window_motion,
            provenance=(
                "synthetic/core" if solver_id in _CORE_SOLVERS else "room_acoustics"
            ),
        )
        return _with_solver_diagnostics(frame, solver_id=solver_id)

    def _solver_for(self, environment: AcousticEnvironmentSpec) -> str:
        if environment.kind == "surface_set":
            raise UnsupportedEffectError(
                "analytic_acoustics does not support environment.kind='surface_set' "
                "in R8.1; use GeometryAcoustics when it becomes available."
            )
        try:
            return ANALYTIC_SOLVER_BY_ENVIRONMENT[environment.kind]
        except KeyError as exc:
            raise UnsupportedEffectError(
                f"Unsupported analytic environment topology {environment.kind!r}; "
                "use GeometryAcoustics."
            ) from exc

    def _validate_solver_options(self, solver_id: str) -> None:
        if solver_id == "free_field_direct" and self.max_order != 0:
            raise UnsupportedEffectError(
                "free_field analytic propagation requires max_order=0."
            )
        if solver_id == "half_space_image_source" and self.max_order not in {0, 1}:
            raise UnsupportedEffectError(
                "half_space analytic propagation supports max_order 0 or 1."
            )
        if solver_id in _CORE_SOLVERS and self.air_absorption:
            raise UnsupportedEffectError(
                "air_absorption is available only for PyRoom analytic solvers in R8.1."
            )
        if solver_id in _CORE_SOLVERS and self.ray_tracing:
            raise UnsupportedEffectError(
                "ray_tracing is available only for PyRoom analytic solvers."
            )


class _CoreRoom:
    def __init__(self, rir: list[list[np.ndarray]]) -> None:
        self.rir = rir


def _render_core(
    prepared: PreparedRoomFrame,
    *,
    speed_of_sound_mps: float,
) -> RenderedRoom:
    mic_count = len(prepared.mic_ids)
    mixture = np.zeros((mic_count, prepared.window_sample_count), dtype=float)
    if not prepared.active:
        return RenderedRoom(
            room=None,
            scheduled=(),
            doppler_factors={},
            premix=np.zeros((0, mic_count, prepared.window_sample_count), dtype=float),
            mixture=mixture,
            source_environment_positions={},
            microphone_environment_positions={},
            effect_diagnostics={},
            segment_factor_rows=(),
        )
    environment = prepared.scene.environment
    source_positions = {
        source.source_id: world_to_environment_point(environment, source.position_world)
        for source in prepared.active
    }
    microphone_positions = {
        mic_id: world_to_environment_point(environment, position)
        for mic_id, position in prepared.microphone_positions_world.items()
    }
    if environment.kind == "half_space":
        _validate_half_space_positions(
            environment,
            source_positions=source_positions,
            microphone_positions=microphone_positions,
        )
    scheduled_list = []
    doppler_factors: dict[str, float] = {}
    for source in prepared.active:
        signal = _scheduled_window_signal(source, time_window=prepared.time_window)
        factor = source_doppler_factor(
            source,
            prepared.sensor,
            speed_of_sound_mps=speed_of_sound_mps,
        )
        if factor is not None:
            doppler_factors[source.source_id] = factor
            if abs(factor - 1.0) > 1e-9:
                signal = replace(
                    signal,
                    signal=_doppler_resampled_signal(signal.signal, factor=factor),
                )
        scheduled_list.append(signal)
    scheduled = tuple(scheduled_list)
    rir = [
        [
            _core_rir(
                environment,
                source_position=source_positions[source.source_id],
                microphone_position=microphone_positions[mic_id],
                sample_rate_hz=prepared.sample_rate_hz,
                speed_of_sound_mps=speed_of_sound_mps,
                max_order=prepared.max_order,
            )
            for source in prepared.active
        ]
        for mic_id in prepared.mic_ids
    ]
    max_length = max(
        prepared.window_sample_count,
        *(
            scheduled[source_index].signal.size + rir[mic_index][source_index].size - 1
            for source_index in range(len(prepared.active))
            for mic_index in range(mic_count)
        ),
    )
    premix = np.zeros((len(prepared.active), mic_count, max_length), dtype=float)
    for source_index, signal in enumerate(scheduled):
        for mic_index in range(mic_count):
            convolved = np.convolve(signal.signal, rir[mic_index][source_index])
            premix[source_index, mic_index, : convolved.size] = convolved
    premix = _apply_entity_directivity_to_premix(
        premix,
        active=prepared.active,
        sensor=prepared.sensor,
        microphone_positions_world=prepared.microphone_positions_world,
    )
    effect_diagnostics = {
        "directivity": {
            "mode": DIRECTIVITY_MODE,
            "source_pattern": {
                source.source_id: source.directivity.value for source in prepared.active
            },
            "microphone_patterns": {
                microphone.mic_id: microphone.directivity.value
                for microphone in prepared.sensor.microphones
            },
        },
        "source_nominal_gain_db": {
            source.source_id: source.gain_db for source in prepared.active
        },
        "microphone_nominal_gain_db": {
            microphone.mic_id: microphone.gain_db
            for microphone in prepared.sensor.microphones
        },
    }
    return RenderedRoom(
        room=_CoreRoom(rir),
        scheduled=scheduled,
        doppler_factors=doppler_factors,
        premix=premix,
        mixture=mixture,
        source_environment_positions=source_positions,
        microphone_environment_positions=microphone_positions,
        effect_diagnostics=effect_diagnostics,
        segment_factor_rows=(),
    )


def _core_rir(
    environment: AcousticEnvironmentSpec,
    *,
    source_position: tuple[float, float, float],
    microphone_position: tuple[float, float, float],
    sample_rate_hz: int,
    speed_of_sound_mps: float,
    max_order: int,
) -> np.ndarray:
    direct_distance = norm(subtract(source_position, microphone_position))
    direct = _path_impulse(
        direct_distance,
        sample_rate_hz=sample_rate_hz,
        speed_of_sound_mps=speed_of_sound_mps,
    )
    if environment.kind == "free_field" or max_order == 0:
        return direct
    floor = environment.surfaces[0]
    image_source = (source_position[0], source_position[1], -source_position[2])
    reflected_distance = norm(subtract(image_source, microphone_position))
    reflected = _path_impulse(
        reflected_distance,
        sample_rate_hz=sample_rate_hz,
        speed_of_sound_mps=speed_of_sound_mps,
    )
    reflected = _apply_reflection_absorption(
        reflected,
        absorption=floor.absorption,
        sample_rate_hz=sample_rate_hz,
        application=f"surface {floor.surface_id!r}",
    )
    if not np.any(reflected):
        return direct
    combined = np.zeros(max(direct.size, reflected.size), dtype=float)
    combined[: direct.size] += direct
    combined[: reflected.size] += reflected
    return combined


def _path_impulse(
    distance_m: float,
    *,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
) -> np.ndarray:
    if distance_m <= EPSILON:
        raise ValueError(
            "analytic_acoustics requires distinct source and microphone positions."
        )
    delay_samples = distance_m / speed_of_sound_mps * sample_rate_hz
    lower = int(math.floor(delay_samples))
    fraction = delay_samples - lower
    impulse = np.zeros(lower + 2, dtype=float)
    amplitude = 1.0 / (4.0 * math.pi * distance_m)
    impulse[lower] = amplitude * (1.0 - fraction)
    impulse[lower + 1] = amplitude * fraction
    return impulse


def _apply_reflection_absorption(
    impulse: np.ndarray,
    *,
    absorption: float | dict[str, float] | str,
    sample_rate_hz: int,
    application: str,
) -> np.ndarray:
    if isinstance(absorption, str):
        coefficients = resolve_material_coefficients(
            absorption,
            "absorption",
            application=application,
        ).values
        centers = MATERIAL_BAND_CENTERS_HZ
    elif isinstance(absorption, dict):
        try:
            pairs = sorted(
                (float(key), float(value)) for key, value in absorption.items()
            )
        except ValueError as exc:
            raise ValueError(
                f"{application} absorption mapping keys must be frequencies in Hz."
            ) from exc
        centers = tuple(frequency for frequency, _value in pairs)
        coefficients = tuple(value for _frequency, value in pairs)
    else:
        return impulse * math.sqrt(max(0.0, 1.0 - float(absorption)))
    attenuation_db = tuple(
        -20.0 * math.log10(max(math.sqrt(1.0 - value), 1e-15))
        for value in coefficients
    )
    return _apply_band_attenuation(
        impulse,
        sample_rate_hz=sample_rate_hz,
        band_centers_hz=centers,
        band_attenuation_db=attenuation_db,
    )


def _validate_half_space_positions(
    environment: AcousticEnvironmentSpec,
    *,
    source_positions: dict[str, tuple[float, float, float]],
    microphone_positions: dict[str, tuple[float, float, float]],
) -> None:
    for label, positions in (
        ("source", source_positions),
        ("microphone", microphone_positions),
    ):
        below = {
            identifier: position
            for identifier, position in positions.items()
            if position[2] < 0.0
        }
        if below:
            identifier, position = next(iter(below.items()))
            raise ValueError(
                f"analytic_acoustics {label} {identifier!r} maps to local "
                f"{position}, below half_space environment "
                f"{environment.environment_id!r}."
            )


def _with_solver_diagnostics(
    frame: AudioSensorFrame,
    *,
    solver_id: str,
) -> AudioSensorFrame:
    environment_kind = frame.diagnostics["environment_config"]["kind"]
    provider = "core" if solver_id in _CORE_SOLVERS else "pyroomacoustics"
    solver = {
        "solver_id": solver_id,
        "provider": provider,
        "environment_kind": environment_kind,
    }
    frame_diagnostics = dict(frame.diagnostics)
    frame_diagnostics["analytic_solver"] = solver
    if provider == "core":
        frame_diagnostics.pop("pyroomacoustics_version", None)
    detections: list[AudioDetection] = []
    for detection in frame.detections:
        diagnostics = dict(detection.diagnostics)
        diagnostics["analytic_solver"] = solver
        if provider == "core":
            diagnostics.pop("pyroomacoustics_version", None)
        detections.append(replace(detection, diagnostics=diagnostics))
    return replace(
        frame,
        detections=tuple(detections),
        diagnostics=frame_diagnostics,
    )


def _import_pyroomacoustics() -> Any:
    try:
        return importlib.import_module("pyroomacoustics")
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "analytic_acoustics closed-room solvers require the optional 'room' "
            "extra (pyroomacoustics, scipy, and soundfile)."
        ) from exc


__all__ = ["AnalyticAcoustics"]
