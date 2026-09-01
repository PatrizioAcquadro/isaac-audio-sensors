"""PyRoom adapter, analytic rendering, and RIR setup."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.environments import (
    world_to_environment_point,
)
from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
    resolve_material_coefficients,
)
from isaac_audio_sensors.core.acoustics.occlusion import (
    occlusion_band_attenuation_db,
    occlusion_per_mic_extra_gain_db,
)
from isaac_audio_sensors.core.backends._analytic.diagnostics import (
    _environment_material_resolution,
)
from isaac_audio_sensors.core.backends._analytic.preparation import (
    PreparedRoomFrame,
)
from isaac_audio_sensors.core.backends._analytic.signals import (
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
    direct_premix: np.ndarray | None
    indirect_premix: np.ndarray | None
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
    direct_premix: np.ndarray | None
    indirect_premix: np.ndarray | None
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
    split_stems: bool = False,
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
            direct_premix=np.zeros(
                (0, len(prepared.mic_ids), prepared.window_sample_count),
                dtype=float,
            ),
            indirect_premix=np.zeros(
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
            per_surface_materials=prepared.per_surface_materials,
            split_stems=split_stems,
        )
        room = piecewise.last_room
        scheduled = piecewise.scheduled
        doppler_factors: dict[str, float] = {}
        premix = piecewise.premix
        direct_premix = piecewise.direct_premix
        indirect_premix = piecewise.indirect_premix
        source_environment_positions = piecewise.source_environment_positions
        microphone_environment_positions = piecewise.microphone_environment_positions
        segment_factor_rows = piecewise.doppler_factor_by_segment
    else:
        room = _build_pyroom_room(
            pra=prepared.pra,
            environment=prepared.scene.environment,
            sample_rate_hz=prepared.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=prepared.max_order,
            air_absorption=prepared.air_absorption,
            ray_tracing=prepared.ray_tracing,
            per_surface_materials=prepared.per_surface_materials,
        )
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
            room=room,
        )
        source_environment_positions = {
            source.source_id: environment_positions[f"source:{source.source_id}"]
            for source in prepared.active
        }
        microphone_environment_positions = {
            mic_id: environment_positions[f"mic:{mic_id}"]
            for mic_id in prepared.mic_ids
        }
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
        full_raw = _simulate_premix(
            room,
            source_count=len(prepared.active),
            mic_count=len(prepared.mic_ids),
        )
        premix = _apply_entity_directivity_to_premix(
            full_raw,
            active=prepared.active,
            sensor=prepared.sensor,
            microphone_positions_world=prepared.microphone_positions_world,
        )
        direct_premix: np.ndarray | None = None
        indirect_premix: np.ndarray | None = None
        if split_stems:
            if prepared.max_order == 0 and not prepared.ray_tracing:
                direct_raw = full_raw.copy()
                indirect_raw = np.zeros_like(full_raw)
            else:
                direct_room = _build_pyroom_room(
                    pra=prepared.pra,
                    environment=prepared.scene.environment,
                    sample_rate_hz=prepared.sample_rate_hz,
                    speed_of_sound_mps=speed_of_sound_mps,
                    max_order=0,
                    air_absorption=prepared.air_absorption,
                    ray_tracing=False,
                    per_surface_materials=prepared.per_surface_materials,
                )
                for source, signal in zip(prepared.active, scheduled, strict=True):
                    direct_room.add_source(
                        source_environment_positions[source.source_id],
                        signal=signal.signal,
                    )
                _add_microphone_array(
                    prepared.pra,
                    direct_room,
                    mic_matrix,
                    sample_rate_hz=prepared.sample_rate_hz,
                )
                direct_room.compute_rir()
                direct_raw = _simulate_premix(
                    direct_room,
                    source_count=len(prepared.active),
                    mic_count=len(prepared.mic_ids),
                )
                full_raw, direct_raw = _align_premixes(full_raw, direct_raw)
                indirect_raw = full_raw - direct_raw
                premix = _pad_premix(premix, full_raw.shape[2])
            direct_premix = _apply_entity_directivity_to_premix(
                direct_raw,
                active=prepared.active,
                sensor=prepared.sensor,
                microphone_positions_world=prepared.microphone_positions_world,
            )
            indirect_premix = _apply_entity_directivity_to_premix(
                indirect_raw,
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
        direct_premix=direct_premix,
        indirect_premix=indirect_premix,
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
            if rendered.direct_premix is None or rendered.indirect_premix is None:
                raise ValueError(
                    f"{backend_id} requires separated propagation stems when "
                    "SourceOcclusion is present."
                )
            per_mic_gain_db = occlusion_per_mic_extra_gain_db(
                occlusion,
                prepared.mic_ids,
            )
            for mic_index, mic_id in enumerate(prepared.mic_ids):
                band = occlusion_band_attenuation_db(occlusion, mic_id)
                direct = rendered.direct_premix[index, mic_index]
                if band is not None and any(value != 0.0 for value in band[1]):
                    attenuated_direct = _apply_band_attenuation(
                        direct,
                        sample_rate_hz=prepared.sample_rate_hz,
                        band_centers_hz=band[0],
                        band_attenuation_db=band[1],
                    )
                elif per_mic_gain_db[mic_id] != 0.0:
                    attenuated_direct = direct * db_to_amplitude_gain(
                        per_mic_gain_db[mic_id],
                        f"occlusion_gain_delta_db.{mic_id}",
                    )
                else:
                    continue
                rendered.premix[index, mic_index] = (
                    attenuated_direct
                    + rendered.indirect_premix[index, mic_index]
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
    per_surface_materials: bool = False,
    split_stems: bool = False,
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
    assembled_direct = np.zeros_like(assembled) if split_stems else None
    assembled_indirect = np.zeros_like(assembled) if split_stems else None
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
        room = _build_pyroom_room(
            pra=pra,
            environment=environment,
            sample_rate_hz=plan.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=max_order,
            air_absorption=air_absorption,
            ray_tracing=ray_tracing,
            per_surface_materials=per_surface_materials,
        )
        environment_positions = _world_to_environment_positions(
            environment=environment,
            positions={**source_positions, **microphone_positions},
            room=room,
        )
        source_environment = {
            source.source_id: environment_positions[f"source:{source.source_id}"]
            for source in active
        }
        mic_environment = {
            mic_id: environment_positions[f"mic:{mic_id}"] for mic_id in mic_ids
        }
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
        segment_full_raw = _simulate_premix(
            room,
            source_count=len(active),
            mic_count=len(mic_ids),
        )
        segment_premix = _apply_entity_directivity_to_premix(
            segment_full_raw,
            active=segment_sources,
            sensor=segment_sensor,
            microphone_positions_world=mic_world,
        )
        segment_direct_premix: np.ndarray | None = None
        segment_indirect_premix: np.ndarray | None = None
        if split_stems:
            if max_order == 0 and not ray_tracing:
                segment_direct_raw = segment_full_raw.copy()
                segment_indirect_raw = np.zeros_like(segment_full_raw)
            else:
                direct_room = _build_pyroom_room(
                    pra=pra,
                    environment=environment,
                    sample_rate_hz=plan.sample_rate_hz,
                    speed_of_sound_mps=speed_of_sound_mps,
                    max_order=0,
                    air_absorption=air_absorption,
                    ray_tracing=False,
                    per_surface_materials=per_surface_materials,
                )
                for source in active:
                    direct_room.add_source(
                        source_environment[source.source_id],
                        signal=rendered[source.source_id][
                            segment.start_sample : segment.end_sample
                        ],
                    )
                _add_microphone_array(
                    pra,
                    direct_room,
                    mic_matrix,
                    sample_rate_hz=plan.sample_rate_hz,
                )
                direct_room.compute_rir()
                segment_direct_raw = _simulate_premix(
                    direct_room,
                    source_count=len(active),
                    mic_count=len(mic_ids),
                )
                segment_full_raw, segment_direct_raw = _align_premixes(
                    segment_full_raw,
                    segment_direct_raw,
                )
                segment_indirect_raw = segment_full_raw - segment_direct_raw
                segment_premix = _pad_premix(
                    segment_premix,
                    segment_full_raw.shape[2],
                )
            segment_direct_premix = _apply_entity_directivity_to_premix(
                segment_direct_raw,
                active=segment_sources,
                sensor=segment_sensor,
                microphone_positions_world=mic_world,
            )
            segment_indirect_premix = _apply_entity_directivity_to_premix(
                segment_indirect_raw,
                active=segment_sources,
                sensor=segment_sensor,
                microphone_positions_world=mic_world,
            )
        required = segment.start_sample + segment_premix.shape[2]
        if required > assembled.shape[2]:
            assembled = _pad_premix(assembled, required)
            if assembled_direct is not None and assembled_indirect is not None:
                assembled_direct = _pad_premix(assembled_direct, required)
                assembled_indirect = _pad_premix(assembled_indirect, required)
        assembled[
            :,
            :,
            segment.start_sample : required,
        ] += segment_premix
        if segment_direct_premix is not None and segment_indirect_premix is not None:
            assert assembled_direct is not None and assembled_indirect is not None
            assembled_direct[
                :,
                :,
                segment.start_sample : required,
            ] += segment_direct_premix
            assembled_indirect[
                :,
                :,
                segment.start_sample : required,
            ] += segment_indirect_premix
        last_room = room
        last_source_environment = source_environment
        last_mic_environment = mic_environment
    return _PiecewiseRoomResult(
        premix=assembled,
        direct_premix=assembled_direct,
        indirect_premix=assembled_indirect,
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


def _build_shoebox_room(
    *,
    pra: Any,
    environment: AcousticEnvironmentSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
    per_surface_materials: bool = False,
) -> Any:
    authored_absorption = environment.surfaces[0].absorption
    if per_surface_materials:
        by_id = {surface.surface_id: surface for surface in environment.surfaces}
        materials = {
            pyroom_name: _pyroom_material(
                pra,
                by_id[surface_id].absorption,
                application=f"surface {surface_id!r}",
            )
            for pyroom_name, surface_id in {
                "west": "wall_x_min",
                "east": "wall_x_max",
                "south": "wall_y_min",
                "north": "wall_y_max",
                "floor": "floor",
                "ceiling": "ceiling",
            }.items()
        }
    else:
        absorption, _evidence, resolution = _environment_material_resolution(
            environment
        )
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
            if not per_surface_materials and not isinstance(authored_absorption, str):
                optional_keys = (*optional_keys, "materials")
            for optional_key in optional_keys:
                if optional_key in kwargs:
                    kwargs.pop(optional_key)
                    removed = True
                    break
            if not removed:
                raise exc


def _build_pyroom_room(
    *,
    pra: Any,
    environment: AcousticEnvironmentSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
    per_surface_materials: bool,
) -> Any:
    if environment.kind == "shoebox":
        room = _build_shoebox_room(
            pra=pra,
            environment=environment,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=max_order,
            air_absorption=air_absorption,
            ray_tracing=ray_tracing,
            per_surface_materials=per_surface_materials,
        )
    elif environment.kind == "polygon_prism":
        room = _build_polygon_room(
            pra=pra,
            environment=environment,
            sample_rate_hz=sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
            max_order=max_order,
            air_absorption=air_absorption,
            ray_tracing=ray_tracing,
        )
    else:
        raise ValueError(
            f"PyRoom solver does not support environment.kind={environment.kind!r}."
        )
    _set_pyroom_sound_speed(room, speed_of_sound_mps)
    return room


def _set_pyroom_sound_speed(room: Any, speed_of_sound_mps: float) -> None:
    """Set one room's sound speed without mutating PyRoom global state."""

    setter = getattr(room, "set_sound_speed", None)
    if callable(setter):
        setter(float(speed_of_sound_mps))
    actual = getattr(room, "c", None)
    if actual is None or not np.isclose(
        float(actual),
        float(speed_of_sound_mps),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError(
            "The selected PyRoom provider cannot apply speed_of_sound_mps via "
            "Room.set_sound_speed() or its room constructor."
        )


def _build_polygon_room(
    *,
    pra: Any,
    environment: AcousticEnvironmentSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
    max_order: int,
    air_absorption: bool,
    ray_tracing: bool,
) -> Any:
    floor = next(surface for surface in environment.surfaces if surface.role == "floor")
    ceiling = next(
        surface for surface in environment.surfaces if surface.role == "ceiling"
    )
    walls = tuple(surface for surface in environment.surfaces if surface.role == "wall")
    floor_vertices = tuple(floor.vertices_local_m)
    floor_z = {round(vertex[2], 12) for vertex in floor_vertices}
    ceiling_z = {round(vertex[2], 12) for vertex in ceiling.vertices_local_m}
    if floor_z != {0.0} or len(ceiling_z) != 1:
        raise ValueError(
            "polygon_prism PyRoom routing requires a local z=0 floor and one "
            "horizontal ceiling."
        )
    height = float(next(iter(ceiling_z)))
    if height <= 0.0 or len(walls) != len(floor_vertices):
        raise ValueError(
            "polygon_prism PyRoom routing requires one wall per floor edge and "
            "a positive ceiling height."
        )
    ceiling_xy = {(round(x, 12), round(y, 12)) for x, y, _z in ceiling.vertices_local_m}
    floor_xy = {(round(x, 12), round(y, 12)) for x, y, _z in floor_vertices}
    if ceiling_xy != floor_xy:
        raise ValueError(
            "polygon_prism floor and ceiling must have the same local XY footprint."
        )
    _validate_simple_polygon_xy(floor_vertices)
    wall_by_edge = _validated_prism_walls(
        walls,
        floor_vertices=floor_vertices,
        height=height,
    )
    ordered_vertices = floor_vertices
    if _signed_polygon_area_xy(ordered_vertices) < 0.0:
        ordered_vertices = tuple(reversed(ordered_vertices))
    ordered_walls = tuple(
        wall_by_edge[
            frozenset(
                {
                    (left[0], left[1]),
                    (right[0], right[1]),
                }
            )
        ]
        for left, right in zip(
            ordered_vertices,
            ordered_vertices[1:] + ordered_vertices[:1],
            strict=True,
        )
    )
    corners = np.asarray([(x, y) for x, y, _z in ordered_vertices], dtype=float).T
    wall_materials = [
        _pyroom_material(
            pra,
            wall.absorption,
            application=f"surface {wall.surface_id!r}",
        )
        for wall in ordered_walls
    ]
    kwargs: dict[str, Any] = {
        "fs": sample_rate_hz,
        "max_order": max_order,
        "materials": wall_materials,
        "air_absorption": air_absorption,
        "ray_tracing": ray_tracing,
        "c": speed_of_sound_mps,
    }
    while True:
        try:
            room = pra.Room.from_corners(corners, **kwargs)
            break
        except TypeError as exc:
            for optional_key in ("c", "ray_tracing", "air_absorption"):
                if optional_key in kwargs:
                    kwargs.pop(optional_key)
                    break
            else:
                raise exc
    room.extrude(
        height,
        materials={
            "floor": _pyroom_material(
                pra,
                floor.absorption,
                application=f"surface {floor.surface_id!r}",
            ),
            "ceiling": _pyroom_material(
                pra,
                ceiling.absorption,
                application=f"surface {ceiling.surface_id!r}",
            ),
        },
    )
    return room


def _pyroom_material(pra: Any, absorption: object, *, application: str) -> Any:
    if isinstance(absorption, str):
        resolution = resolve_material_coefficients(
            absorption,
            "absorption",
            application=application,
        )
        value: object = {
            "description": resolution.description,
            "coeffs": resolution.values,
            "center_freqs": MATERIAL_BAND_CENTERS_HZ,
        }
    elif isinstance(absorption, dict):
        try:
            pairs = sorted(
                (float(key), float(value)) for key, value in absorption.items()
            )
        except ValueError as exc:
            raise ValueError(
                f"{application} absorption mapping keys must be frequencies in Hz."
            ) from exc
        value = {
            "coeffs": [coefficient for _frequency, coefficient in pairs],
            "center_freqs": [frequency for frequency, _coefficient in pairs],
        }
    else:
        value = float(absorption)
    return pra.Material(value) if hasattr(pra, "Material") else value


def _signed_polygon_area_xy(
    vertices: tuple[tuple[float, float, float], ...],
) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(vertices, vertices[1:] + vertices[:1], strict=True)
    )


def _validate_simple_polygon_xy(
    vertices: tuple[tuple[float, float, float], ...],
) -> None:
    if len(vertices) < 3 or len({(x, y) for x, y, _z in vertices}) != len(vertices):
        raise ValueError(
            "polygon_prism PyRoom routing requires at least three distinct floor "
            "vertices."
        )
    if abs(_signed_polygon_area_xy(vertices)) <= 1e-9:
        raise ValueError("polygon_prism floor polygon has zero area.")
    for left_index in range(len(vertices)):
        a = vertices[left_index]
        b = vertices[(left_index + 1) % len(vertices)]
        for right_index in range(left_index + 1, len(vertices)):
            if right_index in {
                left_index,
                (left_index + 1) % len(vertices),
                (left_index - 1) % len(vertices),
            }:
                continue
            c = vertices[right_index]
            d = vertices[(right_index + 1) % len(vertices)]
            if _segments_cross_xy(a, b, c, d):
                raise ValueError(
                    "polygon_prism floor polygon must not self-intersect."
                )


def _segments_cross_xy(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> bool:
    def orientation(
        left: tuple[float, float, float],
        middle: tuple[float, float, float],
        right: tuple[float, float, float],
    ) -> float:
        return (middle[1] - left[1]) * (right[0] - middle[0]) - (
            middle[0] - left[0]
        ) * (right[1] - middle[1])

    return (
        orientation(a, b, c) * orientation(a, b, d) < 0.0
        and orientation(c, d, a) * orientation(c, d, b) < 0.0
    )


def _validated_prism_walls(
    walls: tuple[Any, ...],
    *,
    floor_vertices: tuple[tuple[float, float, float], ...],
    height: float,
) -> dict[frozenset[tuple[float, float]], Any]:
    expected_edges = {
        frozenset({(left[0], left[1]), (right[0], right[1])})
        for left, right in zip(
            floor_vertices,
            floor_vertices[1:] + floor_vertices[:1],
            strict=True,
        )
    }
    wall_by_edge: dict[frozenset[tuple[float, float]], Any] = {}
    for wall in walls:
        vertices = tuple(wall.vertices_local_m)
        bottom = {(x, y) for x, y, z in vertices if abs(z) <= 1e-9}
        top = {(x, y) for x, y, z in vertices if abs(z - height) <= 1e-9}
        if len(vertices) != 4 or len(bottom) != 2 or bottom != top:
            raise ValueError(
                f"polygon_prism wall {wall.surface_id!r} must be one vertical "
                "quad spanning the floor and ceiling."
            )
        edge = frozenset(bottom)
        if edge not in expected_edges or edge in wall_by_edge:
            raise ValueError(
                f"polygon_prism wall {wall.surface_id!r} does not map uniquely "
                "to a floor edge."
            )
        wall_by_edge[edge] = wall
    if set(wall_by_edge) != expected_edges:
        raise ValueError("polygon_prism requires exactly one wall per floor edge.")
    return wall_by_edge


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


def _pad_premix(premix: np.ndarray, sample_count: int) -> np.ndarray:
    if premix.shape[2] >= sample_count:
        return premix
    padded = np.zeros((*premix.shape[:2], sample_count), dtype=premix.dtype)
    padded[:, :, : premix.shape[2]] = premix
    return padded


def _align_premixes(
    left: np.ndarray,
    right: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if left.shape[:2] != right.shape[:2]:
        raise ValueError("PyRoom direct and full premix shapes do not align.")
    sample_count = max(left.shape[2], right.shape[2])
    return _pad_premix(left, sample_count), _pad_premix(right, sample_count)


def _world_to_environment_positions(
    *,
    environment: AcousticEnvironmentSpec,
    positions: dict[str, tuple[float, float, float]],
    room: Any | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Transform world positions into a supported closed solver frame."""

    dimensions = environment.dimensions_m
    environment_positions: dict[str, tuple[float, float, float]] = {}
    for key, position in positions.items():
        environment_position = world_to_environment_point(environment, position)
        if environment.kind == "shoebox":
            assert dimensions is not None
            out_of_bounds = any(
                environment_position[axis] < 0.0
                or environment_position[axis] > dimensions[axis]
                for axis in range(3)
            )
            boundary = f"shoebox bounds [(0, 0, 0), {dimensions}]"
        else:
            if room is None or not hasattr(room, "is_inside"):
                raise ValueError(
                    "polygon_prism PyRoom routing requires room containment support."
                )
            out_of_bounds = not bool(room.is_inside(environment_position))
            boundary = "polygon-prism boundary"
        if out_of_bounds:
            prefix = (
                "outside shoebox environment"
                if environment.kind == "shoebox"
                else "outside polygon-prism environment"
            )
            raise ValueError(
                f"analytic_acoustics position {key!r} at world "
                f"{tuple(float(value) for value in position)} maps to local "
                f"{environment_position}, {prefix} {environment.environment_id!r} "
                f"{boundary}."
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
