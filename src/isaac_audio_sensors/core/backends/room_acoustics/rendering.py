"""pyroomacoustics adapter, room rendering, and RIR setup."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.environments import (
    world_to_environment_point,
)
from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
)
from isaac_audio_sensors.core.acoustics.occlusion import (
    occlusion_band_attenuation_db,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.backends.room_acoustics.diagnostics import (
    _environment_material_resolution,
)
from isaac_audio_sensors.core.backends.room_acoustics.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends.room_acoustics.signals import (
    _doppler_resampled_signal,
    _piecewise_phase_signal,
    _scheduled_window_signal,
    _ScheduledSignal,
)
from isaac_audio_sensors.core.directivity import (
    DIRECTIVITY_MODE,
    microphone_world_orientation,
    pair_directivity_gain,
)
from isaac_audio_sensors.core.effects.chain import ChannelEffectsChain
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import (
    norm,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import (
    microphone_world_positions,
)
from isaac_audio_sensors.core.motion import (
    WindowMotionPlan,
)
from isaac_audio_sensors.core.motion.doppler import source_doppler_factor
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
)


@dataclass(frozen=True, slots=True)
class _PiecewiseRoomResult:
    premix: np.ndarray
    scheduled: tuple[_ScheduledSignal, ...]
    last_room: Any
    source_environment_positions: dict[str, tuple[float, float, float]]
    microphone_environment_positions: dict[str, tuple[float, float, float]]
    doppler_factor_by_segment: tuple[dict[str, float], ...]


@dataclass(slots=True)
class RenderedRoom:
    """Rendered stems and mutable effect state for one prepared room frame."""

    room: Any | None
    scheduled: tuple[_ScheduledSignal, ...]
    doppler_factors: dict[str, float]
    premix: np.ndarray
    mixture: np.ndarray
    source_environment_positions: dict[str, tuple[float, float, float]]
    microphone_environment_positions: dict[str, tuple[float, float, float]]
    effect_diagnostics: dict[str, Any]
    segment_factor_rows: tuple[dict[str, float], ...]


def render_room(
    prepared: PreparedRoomFrame,
    *,
    effects: EffectsConfig,
    speed_of_sound_mps: float,
    window_motion: WindowMotionPlan | None,
) -> RenderedRoom:
    """Schedule, Doppler-render, and spatialize every active source stem."""

    mixture = np.zeros(
        (len(prepared.mic_ids), prepared.window_sample_count),
        dtype=float,
    )
    if not prepared.active:
        return RenderedRoom(
            room=None,
            scheduled=(),
            doppler_factors={},
            premix=np.zeros(
                (0, len(prepared.mic_ids), prepared.window_sample_count),
                dtype=float,
            ),
            mixture=mixture,
            source_environment_positions={},
            microphone_environment_positions={},
            effect_diagnostics={},
            segment_factor_rows=prepared.segment_factor_rows,
        )

    effect_diagnostics: dict[str, Any] = {}
    if prepared.segments_per_window > 1:
        assert window_motion is not None
        piecewise = _simulate_piecewise_room(
            pra=prepared.pra,
            environment=prepared.scene.environment,
            active=prepared.active,
            sensor=prepared.sensor,
            time_window=prepared.time_window,
            plan=window_motion,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=prepared.max_order,
            air_absorption=prepared.air_absorption,
            ray_tracing=prepared.ray_tracing,
        )
        room = piecewise.last_room
        scheduled = piecewise.scheduled
        doppler_factors: dict[str, float] = {}
        premix = piecewise.premix
        source_environment_positions = piecewise.source_environment_positions
        microphone_environment_positions = piecewise.microphone_environment_positions
        segment_factor_rows = piecewise.doppler_factor_by_segment
    else:
        source_positions = {
            f"source:{source.source_id}": source.position_world
            for source in prepared.active
        }
        microphone_positions = {
            f"mic:{mic_id}": position
            for mic_id, position in prepared.microphone_positions_world.items()
        }
        environment_positions = _world_to_environment_positions(
            environment=prepared.scene.environment,
            positions={**source_positions, **microphone_positions},
        )
        source_environment_positions = {
            source.source_id: environment_positions[f"source:{source.source_id}"]
            for source in prepared.active
        }
        microphone_environment_positions = {
            mic_id: environment_positions[f"mic:{mic_id}"]
            for mic_id in prepared.mic_ids
        }
        room = _build_shoebox_room(
            pra=prepared.pra,
            environment=prepared.scene.environment,
            sample_rate_hz=prepared.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=prepared.max_order,
            air_absorption=prepared.air_absorption,
            ray_tracing=prepared.ray_tracing,
        )
        scheduled_list: list[_ScheduledSignal] = []
        doppler_factors = {}
        for source in prepared.active:
            signal = _scheduled_window_signal(
                source,
                time_window=prepared.time_window,
            )
            factor = source_doppler_factor(
                source,
                prepared.sensor,
                speed_of_sound_mps=speed_of_sound_mps,
            )
            if factor is None and effects.motion.derive_velocity_from_poses:
                factor = 1.0
            if factor is not None:
                doppler_factors[source.source_id] = factor
                if abs(factor - 1.0) > 1e-9:
                    signal = replace(
                        signal,
                        signal=_doppler_resampled_signal(signal.signal, factor=factor),
                    )
            scheduled_list.append(signal)
            room.add_source(
                source_environment_positions[source.source_id],
                signal=signal.signal,
            )
        scheduled = tuple(scheduled_list)
        mic_matrix = np.asarray(
            [microphone_environment_positions[mic_id] for mic_id in prepared.mic_ids],
            dtype=float,
        ).T
        _add_microphone_array(
            prepared.pra,
            room,
            mic_matrix,
            sample_rate_hz=prepared.sample_rate_hz,
        )
        room.compute_rir()
        premix = _simulate_premix(
            room,
            source_count=len(prepared.active),
            mic_count=len(prepared.mic_ids),
        )
        premix = _apply_entity_directivity_to_premix(
            premix,
            active=prepared.active,
            sensor=prepared.sensor,
            microphone_positions_world=prepared.microphone_positions_world,
        )
        segment_factor_rows = prepared.segment_factor_rows
    effect_diagnostics["directivity"] = {
        "mode": DIRECTIVITY_MODE,
        "source_pattern": {
            source.source_id: source.directivity.value for source in prepared.active
        },
        "microphone_patterns": {
            microphone.mic_id: microphone.directivity.value
            for microphone in prepared.sensor.microphones
        },
    }
    effect_diagnostics["source_nominal_gain_db"] = {
        source.source_id: source.gain_db for source in prepared.active
    }
    effect_diagnostics["microphone_nominal_gain_db"] = {
        microphone.mic_id: microphone.gain_db
        for microphone in prepared.sensor.microphones
    }
    return RenderedRoom(
        room=room,
        scheduled=scheduled,
        doppler_factors=doppler_factors,
        premix=premix,
        mixture=mixture,
        source_environment_positions=source_environment_positions,
        microphone_environment_positions=microphone_environment_positions,
        effect_diagnostics=effect_diagnostics,
        segment_factor_rows=segment_factor_rows,
    )


def apply_room_effects(
    prepared: PreparedRoomFrame,
    rendered: RenderedRoom,
    *,
    effects: EffectsConfig,
    effects_chain: ChannelEffectsChain,
    backend_id: str,
    runtime_profile: str,
) -> None:
    """Apply stem effects, sum the room, then process the complete mixture."""

    if prepared.active:
        for index, source in enumerate(prepared.active):
            occlusion = prepared.scene.occlusion_for(
                prepared.sensor.array_id,
                source.source_id,
            )
            if occlusion is None:
                continue
            per_mic_gain_db = occlusion_per_mic_extra_gain_db(
                occlusion,
                prepared.mic_ids,
            )
            for mic_index, mic_id in enumerate(prepared.mic_ids):
                band = occlusion_band_attenuation_db(occlusion, mic_id)
                if band is not None:
                    rendered.premix[index, mic_index] = _apply_band_attenuation(
                        rendered.premix[index, mic_index],
                        sample_rate_hz=prepared.sample_rate_hz,
                        band_centers_hz=band[0],
                        band_attenuation_db=band[1],
                    )
                elif per_mic_gain_db[mic_id] != 0.0:
                    rendered.premix[index, mic_index] *= db_to_amplitude_gain(
                        per_mic_gain_db[mic_id],
                        f"occlusion_gain_delta_db.{mic_id}",
                    )
        for mic_index, microphone in enumerate(prepared.sensor.microphones):
            rendered.premix[:, mic_index] *= db_to_amplitude_gain(
                microphone.gain_db,
                f"MicrophoneSpec[{microphone.mic_id!r}].gain_db",
            )
        if effects.channel_response.enabled:
            for index in range(len(prepared.active)):
                processed, diagnostics = effects_chain.apply_premix(
                    rendered.premix[index],
                    mic_ids=prepared.mic_ids,
                    sample_rate_hz=prepared.sample_rate_hz,
                    frame_id=prepared.frame_id,
                    backend_id=backend_id,
                    runtime_profile=runtime_profile,
                    microphone_self_noise_db=prepared.microphone_self_noise_db,
                )
                rendered.premix[index] = processed
                if diagnostics:
                    rendered.effect_diagnostics.update(diagnostics)
        summed = np.sum(rendered.premix, axis=0)
        if summed.shape[1] >= prepared.window_sample_count:
            rendered.mixture = summed
        else:
            rendered.mixture[:, : summed.shape[1]] = summed
        if effects.noise.enabled or effects.electronics.enabled:
            rendered.mixture, diagnostics = effects_chain.apply_mixture(
                rendered.mixture,
                mic_ids=prepared.mic_ids,
                sample_rate_hz=prepared.sample_rate_hz,
                frame_id=prepared.frame_id,
                backend_id=backend_id,
                runtime_profile=runtime_profile,
                nominal_window_start_sample=prepared.nominal_window_start_sample,
                microphone_self_noise_db=prepared.microphone_self_noise_db,
            )
            if diagnostics:
                rendered.effect_diagnostics.update(diagnostics)
        return

    if effects.channel_response.enabled:
        rendered.mixture, diagnostics = effects_chain.apply_premix(
            rendered.mixture,
            mic_ids=prepared.mic_ids,
            sample_rate_hz=prepared.sample_rate_hz,
            frame_id=prepared.frame_id,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            microphone_self_noise_db=prepared.microphone_self_noise_db,
        )
        if diagnostics:
            rendered.effect_diagnostics.update(diagnostics)
    if effects.noise.enabled or effects.electronics.enabled:
        rendered.mixture, diagnostics = effects_chain.apply_mixture(
            rendered.mixture,
            mic_ids=prepared.mic_ids,
            sample_rate_hz=prepared.sample_rate_hz,
            frame_id=prepared.frame_id,
            backend_id=backend_id,
            runtime_profile=runtime_profile,
            nominal_window_start_sample=prepared.nominal_window_start_sample,
            microphone_self_noise_db=prepared.microphone_self_noise_db,
        )
        if diagnostics:
            rendered.effect_diagnostics.update(diagnostics)


def _simulate_piecewise_room(
    *,
    pra: Any,
    environment: AcousticEnvironmentSpec,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    time_window: AudioTimeWindow,
    plan: WindowMotionPlan,
    speed_of_sound_mps: float,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
) -> _PiecewiseRoomResult:
    """Simulate segment midpoint geometry and overlap-add every RIR tail."""

    mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
    scheduled = tuple(
        _scheduled_window_signal(source, time_window=time_window) for source in active
    )
    factor_rows: list[dict[str, float]] = []
    factors_by_source: dict[str, list[float]] = {
        source.source_id: [] for source in active
    }
    for segment in plan.segments:
        array_motion = segment.entities[sensor.array_id]
        segment_sensor = replace(
            sensor,
            position_world=array_motion.midpoint_position_world_m,
            velocity_world_mps=array_motion.velocity_world_mps,
        )
        row: dict[str, float] = {}
        for source in active:
            source_motion = segment.entities[source.source_id]
            segment_source = replace(
                source,
                position_world=source_motion.midpoint_position_world_m,
                velocity_world_mps=source_motion.velocity_world_mps,
            )
            if source_motion.velocity_source.startswith(
                "none:"
            ) or array_motion.velocity_source.startswith("none:"):
                factor = 1.0
            else:
                factor = source_doppler_factor(
                    segment_source,
                    segment_sensor,
                    speed_of_sound_mps=speed_of_sound_mps,
                )
                if factor is None:
                    factor = 1.0
            row[source.source_id] = factor
            factors_by_source[source.source_id].append(factor)
        factor_rows.append(row)

    lengths = tuple(segment.sample_count for segment in plan.segments)
    rendered = {
        source.source_id: _piecewise_phase_signal(
            scheduled[index].signal,
            factors=tuple(factors_by_source[source.source_id]),
            segment_lengths=lengths,
        )
        for index, source in enumerate(active)
    }
    assembled = np.zeros(
        (len(active), len(mic_ids), plan.window_sample_count),
        dtype=float,
    )
    last_room: Any = None
    last_source_environment: dict[str, tuple[float, float, float]] = {}
    last_mic_environment: dict[str, tuple[float, float, float]] = {}
    for segment in plan.segments:
        array_position = segment.entities[sensor.array_id].midpoint_position_world_m
        segment_sensor = replace(sensor, position_world=array_position)
        mic_world = microphone_world_positions(segment_sensor)
        segment_sources = tuple(
            replace(
                source,
                position_world=segment.entities[
                    source.source_id
                ].midpoint_position_world_m,
                velocity_world_mps=segment.entities[
                    source.source_id
                ].velocity_world_mps,
            )
            for source in active
        )
        source_positions = {
            f"source:{source.source_id}": source.position_world
            for source in segment_sources
        }
        microphone_positions = {
            f"mic:{mic_id}": position for mic_id, position in mic_world.items()
        }
        environment_positions = _world_to_environment_positions(
            environment=environment,
            positions={**source_positions, **microphone_positions},
        )
        source_environment = {
            source.source_id: environment_positions[f"source:{source.source_id}"]
            for source in active
        }
        mic_environment = {
            mic_id: environment_positions[f"mic:{mic_id}"] for mic_id in mic_ids
        }
        room = _build_shoebox_room(
            pra=pra,
            environment=environment,
            sample_rate_hz=plan.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=max_order,
            air_absorption=air_absorption,
            ray_tracing=ray_tracing,
        )
        for source in active:
            room.add_source(
                source_environment[source.source_id],
                signal=rendered[source.source_id][
                    segment.start_sample : segment.end_sample
                ],
            )
        mic_matrix = np.asarray(
            [mic_environment[mic_id] for mic_id in mic_ids], dtype=float
        ).T
        _add_microphone_array(
            pra,
            room,
            mic_matrix,
            sample_rate_hz=plan.sample_rate_hz,
        )
        room.compute_rir()
        segment_premix = _simulate_premix(
            room,
            source_count=len(active),
            mic_count=len(mic_ids),
        )
        segment_premix = _apply_entity_directivity_to_premix(
            segment_premix,
            active=segment_sources,
            sensor=segment_sensor,
            microphone_positions_world=mic_world,
        )
        required = segment.start_sample + segment_premix.shape[2]
        if required > assembled.shape[2]:
            expanded = np.zeros(
                (len(active), len(mic_ids), required),
                dtype=float,
            )
            expanded[:, :, : assembled.shape[2]] = assembled
            assembled = expanded
        assembled[
            :,
            :,
            segment.start_sample : required,
        ] += segment_premix
        last_room = room
        last_source_environment = source_environment
        last_mic_environment = mic_environment
    return _PiecewiseRoomResult(
        premix=assembled,
        scheduled=scheduled,
        last_room=last_room,
        source_environment_positions=last_source_environment,
        microphone_environment_positions=last_mic_environment,
        doppler_factor_by_segment=tuple(factor_rows),
    )


def _apply_entity_directivity_to_premix(
    premix: np.ndarray,
    *,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    microphone_positions_world: dict[str, tuple[float, float, float]],
) -> np.ndarray:
    """Weight every complete pair stem using its direct-path angle."""

    output = premix.copy()
    microphone_orientations = {
        microphone.mic_id: microphone_world_orientation(
            sensor.orientation_world_quat,
            microphone.relative_orientation_quat,
        )
        for microphone in sensor.microphones
    }
    for source_index, source in enumerate(active):
        for mic_index, microphone in enumerate(sensor.microphones):
            mic_id = microphone.mic_id
            gain = pair_directivity_gain(
                source_pattern=source.directivity,
                microphone_pattern=microphone.directivity,
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=microphone_positions_world[mic_id],
                microphone_orientation_world_xyzw=microphone_orientations[mic_id],
            )
            output[source_index, mic_index] *= gain
    return output


def _import_pyroomacoustics() -> Any:
    try:
        return importlib.import_module("pyroomacoustics")
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "room_acoustics backend requires the optional 'room' extra "
            "(pyroomacoustics, scipy, and soundfile)."
        ) from exc


def _build_shoebox_room(
    *,
    pra: Any,
    environment: AcousticEnvironmentSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
) -> Any:
    authored_absorption = environment.surfaces[0].absorption
    absorption, _evidence, resolution = _environment_material_resolution(environment)
    if resolution is not None:
        absorption = {
            "description": resolution.description,
            "coeffs": resolution.values,
            "center_freqs": MATERIAL_BAND_CENTERS_HZ,
        }
    materials = pra.Material(absorption) if hasattr(pra, "Material") else absorption
    kwargs: dict[str, Any] = {
        "fs": sample_rate_hz,
        "materials": materials,
        "max_order": max_order,
        "air_absorption": air_absorption,
        "ray_tracing": ray_tracing,
        "c": speed_of_sound_mps,
    }
    while True:
        try:
            assert environment.dimensions_m is not None
            return pra.ShoeBox(environment.dimensions_m, **kwargs)
        except TypeError as exc:
            removed = False
            optional_keys = ("c", "ray_tracing", "air_absorption")
            if not isinstance(authored_absorption, str):
                optional_keys = (*optional_keys, "materials")
            for optional_key in optional_keys:
                if optional_key in kwargs:
                    kwargs.pop(optional_key)
                    removed = True
                    break
            if not removed:
                raise exc


def _add_microphone_array(
    pra: Any,
    room: Any,
    mic_matrix: np.ndarray,
    *,
    sample_rate_hz: int,
) -> None:
    if hasattr(pra, "MicrophoneArray"):
        room.add_microphone_array(pra.MicrophoneArray(mic_matrix, fs=sample_rate_hz))
    else:
        room.add_microphone_array(mic_matrix)


def _apply_band_attenuation(
    waveform: np.ndarray,
    *,
    sample_rate_hz: int,
    band_centers_hz: tuple[float, ...],
    band_attenuation_db: tuple[float, ...],
) -> np.ndarray:
    """Apply per-band attenuation with a zero-phase rFFT gain curve.

    The per-bin gain interpolates the band gains over log2 frequency with
    flat extrapolation beyond the outermost band centers. Zero-phase
    filtering preserves GCC-PHAT delay estimates.
    """

    sample_count = int(waveform.size)
    if sample_count == 0 or not band_centers_hz:
        return waveform
    centers = np.asarray(band_centers_hz, dtype=float)
    gains_db = -np.asarray(band_attenuation_db, dtype=float)
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / float(sample_rate_hz))
    log_frequencies = np.log2(np.maximum(frequencies, centers[0] / 4.0))
    gain_curve = 10.0 ** (np.interp(log_frequencies, np.log2(centers), gains_db) / 20.0)
    spectrum = np.fft.rfft(waveform) * gain_curve
    return np.fft.irfft(spectrum, n=sample_count)


def _simulate_premix(
    room: Any,
    *,
    source_count: int,
    mic_count: int,
) -> np.ndarray:
    """Run the room simulation and return per-source microphone signals."""

    premix = np.asarray(room.simulate(return_premix=True), dtype=float)
    if (
        premix.ndim != 3
        or premix.shape[0] != source_count
        or premix.shape[1] != mic_count
    ):
        raise ValueError("pyroomacoustics returned an unexpected mic signal shape.")
    return premix


def _world_to_environment_positions(
    *,
    environment: AcousticEnvironmentSpec,
    positions: dict[str, tuple[float, float, float]],
) -> dict[str, tuple[float, float, float]]:
    """Transform world positions into the shoebox-local solver frame."""

    dimensions = environment.dimensions_m
    assert dimensions is not None
    environment_positions: dict[str, tuple[float, float, float]] = {}
    for key, position in positions.items():
        environment_position = world_to_environment_point(environment, position)
        out_of_bounds = any(
            environment_position[axis] < 0.0
            or environment_position[axis] > dimensions[axis]
            for axis in range(3)
        )
        if out_of_bounds:
            raise ValueError(
                f"room_acoustics position {key!r} at world "
                f"{tuple(float(value) for value in position)} maps to local "
                f"{environment_position}, outside shoebox environment "
                f"{environment.environment_id!r} bounds [(0, 0, 0), {dimensions}]."
            )
        environment_positions[key] = (
            environment_position[0],
            environment_position[1],
            environment_position[2],
        )
    return environment_positions


def _max_microphone_spacing(
    positions: dict[str, tuple[float, float, float]],
) -> float:
    max_spacing = 0.0
    values = tuple(positions.values())
    for left in values:
        for right in values:
            max_spacing = max(max_spacing, norm(subtract(left, right)))
    return max_spacing
