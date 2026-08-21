"""pyroomacoustics adapter, room rendering, and RIR setup."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_BAND_CENTERS_HZ,
)
from isaac_audio_sensors.core.backends.room_acoustics.diagnostics import (
    _room_material_resolution,
)
from isaac_audio_sensors.core.backends.room_acoustics.signals import (
    _piecewise_phase_signal,
    _scheduled_window_signal,
    _ScheduledSignal,
)
from isaac_audio_sensors.core.constants import (
    ROOM_CLAMP_MARGIN_M,
)
from isaac_audio_sensors.core.doppler import source_doppler_factor
from isaac_audio_sensors.core.effects.config import (
    DirectivityConfig,
)
from isaac_audio_sensors.core.effects.directivity import (
    apply_pair_directivity,
    directivity_diagnostics,
    microphone_world_orientation,
    resolve_pattern,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
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
from isaac_audio_sensors.core.types import (
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    RoomAcousticsSpec,
)


@dataclass(frozen=True, slots=True)
class _PiecewiseRoomResult:
    premix: np.ndarray
    scheduled: tuple[_ScheduledSignal, ...]
    last_room: Any
    source_room_positions: dict[str, tuple[float, float, float]]
    microphone_room_positions: dict[str, tuple[float, float, float]]
    clamped_position_ids: tuple[str, ...]
    doppler_factor_by_segment: tuple[dict[str, float], ...]


def _simulate_piecewise_room(
    *,
    pra: Any,
    room_spec: RoomAcousticsSpec,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    time_window: AudioTimeWindow,
    plan: WindowMotionPlan,
    speed_of_sound_mps: float,
    directivity_config: DirectivityConfig,
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
    clamped: set[str] = set()
    last_room: Any = None
    last_source_room: dict[str, tuple[float, float, float]] = {}
    last_mic_room: dict[str, tuple[float, float, float]] = {}
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
        room_positions, clamped_ids = _world_to_room_positions(
            room_spec=room_spec,
            positions={**source_positions, **microphone_positions},
        )
        clamped.update(clamped_ids)
        source_room = {
            source.source_id: room_positions[f"source:{source.source_id}"]
            for source in active
        }
        mic_room = {mic_id: room_positions[f"mic:{mic_id}"] for mic_id in mic_ids}
        room = _build_shoebox_room(
            pra=pra,
            room_spec=room_spec,
            sample_rate_hz=plan.sample_rate_hz,
            speed_of_sound_mps=speed_of_sound_mps,
        )
        for source in active:
            room.add_source(
                source_room[source.source_id],
                signal=rendered[source.source_id][
                    segment.start_sample : segment.end_sample
                ],
            )
        mic_matrix = np.asarray([mic_room[mic_id] for mic_id in mic_ids], dtype=float).T
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
        if directivity_config.enabled:
            segment_premix, _diagnostics = _apply_directivity_to_premix(
                segment_premix,
                active=segment_sources,
                sensor=segment_sensor,
                microphone_positions_world=mic_world,
                sample_rate_hz=plan.sample_rate_hz,
                config=directivity_config,
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
        last_source_room = source_room
        last_mic_room = mic_room
    return _PiecewiseRoomResult(
        premix=assembled,
        scheduled=scheduled,
        last_room=last_room,
        source_room_positions=last_source_room,
        microphone_room_positions=last_mic_room,
        clamped_position_ids=tuple(sorted(clamped)),
        doppler_factor_by_segment=tuple(factor_rows),
    )


def _apply_directivity_to_premix(
    premix: np.ndarray,
    *,
    active: tuple[AudioSourceSpec, ...],
    sensor: MicrophoneArraySpec,
    microphone_positions_world: dict[str, tuple[float, float, float]],
    sample_rate_hz: int,
    config: DirectivityConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Weight every complete pair stem using its direct-path angle."""

    mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
    diagnostics = directivity_diagnostics(
        config,
        active_source_ids=tuple(source.source_id for source in active),
        microphone_ids=mic_ids,
    )
    if not diagnostics:
        return premix, {}
    output = premix.copy()
    microphone_orientations = {
        microphone.mic_id: microphone_world_orientation(
            sensor.orientation_world_quat,
            microphone.relative_orientation_quat,
        )
        for microphone in sensor.microphones
    }
    for source_index, source in enumerate(active):
        source_pattern = resolve_pattern(config.source_patterns, source.source_id)
        for mic_index, mic_id in enumerate(mic_ids):
            microphone_pattern = resolve_pattern(config.mic_patterns, mic_id)
            output[source_index, mic_index] = apply_pair_directivity(
                output[source_index, mic_index],
                source_pattern=source_pattern,
                microphone_pattern=microphone_pattern,
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=microphone_positions_world[mic_id],
                microphone_orientation_world_xyzw=microphone_orientations[mic_id],
                sample_rate_hz=sample_rate_hz,
            )
    return output, diagnostics


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
    room_spec: RoomAcousticsSpec,
    sample_rate_hz: int,
    speed_of_sound_mps: float,
) -> Any:
    absorption, _evidence, resolution = _room_material_resolution(room_spec)
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
        "max_order": room_spec.max_order,
        "air_absorption": room_spec.air_absorption,
        "ray_tracing": room_spec.ray_tracing,
        "c": speed_of_sound_mps,
    }
    while True:
        try:
            return pra.ShoeBox(room_spec.dimensions_m, **kwargs)
        except TypeError as exc:
            removed = False
            optional_keys = ("c", "ray_tracing", "air_absorption")
            if not isinstance(room_spec.absorption, str):
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


def _world_to_room_positions(
    *,
    room_spec: RoomAcousticsSpec,
    positions: dict[str, tuple[float, float, float]],
) -> tuple[dict[str, tuple[float, float, float]], tuple[str, ...]]:
    """Translate world positions into the room's corner-origin frame.

    The room is anchored in world space at ``room_spec.origin_m``; positions
    outside ``[origin, origin + dimensions]`` follow the spec's out-of-bounds
    policy: ``"error"`` raises naming the offending entity, ``"clamp"`` pulls
    it just inside the nearest wall and reports it.
    """

    dimensions = room_spec.dimensions_m
    origin = room_spec.origin_m
    room_positions: dict[str, tuple[float, float, float]] = {}
    clamped_ids: list[str] = []
    for key, position in positions.items():
        room_position = [float(position[axis] - origin[axis]) for axis in range(3)]
        out_of_bounds = any(
            room_position[axis] < 0.0 or room_position[axis] > dimensions[axis]
            for axis in range(3)
        )
        if out_of_bounds:
            if room_spec.out_of_bounds == "clamp":
                room_position = [
                    min(
                        max(room_position[axis], ROOM_CLAMP_MARGIN_M),
                        dimensions[axis] - ROOM_CLAMP_MARGIN_M,
                    )
                    for axis in range(3)
                ]
                clamped_ids.append(key)
            else:
                anchor = (
                    f" (room anchored to {room_spec.anchor_prim_path!r})"
                    if room_spec.anchor_prim_path is not None
                    else ""
                )
                max_corner = tuple(origin[axis] + dimensions[axis] for axis in range(3))
                raise ValueError(
                    f"room_acoustics position {key!r} at world "
                    f"{tuple(float(value) for value in position)} is outside "
                    f"room {room_spec.room_id!r} world bounds "
                    f"[{room_spec.origin_m}, {max_corner}]{anchor}. Move the "
                    "prim inside the room or set out_of_bounds='clamp'."
                )
        room_positions[key] = (
            room_position[0],
            room_position[1],
            room_position[2],
        )
    return room_positions, tuple(clamped_ids)


def _max_microphone_spacing(
    positions: dict[str, tuple[float, float, float]],
) -> float:
    max_spacing = 0.0
    values = tuple(positions.values())
    for left in values:
        for right in values:
            max_spacing = max(max_spacing, norm(subtract(left, right)))
    return max_spacing
