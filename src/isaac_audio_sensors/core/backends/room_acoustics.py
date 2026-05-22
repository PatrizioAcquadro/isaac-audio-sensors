"""Optional pyroomacoustics-backed room simulation path."""

from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.core.backends.tdoa import estimate_doa_from_delays
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.doa.gcc_phat import (
    estimate_tdoa_diagnostics,
    relative_delays_from_tdoa_matrix,
    rms_by_channel,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.math_utils import (
    bearing_from_components,
    dot,
    norm,
    subtract,
)
from isaac_audio_sensors.core.microphone_array import (
    layout_rank_xy,
    microphone_world_positions,
    validate_tdoa_array,
)
from isaac_audio_sensors.core.scene import (
    active_sources,
    deterministic_detection_id,
    deterministic_frame_id,
    deterministic_frame_name,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    Pose3D,
    RoomAcousticsSpec,
)


class RoomAcousticsBackend:
    """Optional shoebox-room backend using pyroomacoustics and GCC-PHAT."""

    backend_id = "room_acoustics"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        source_waveform_duration_s: float = 0.08,
        gcc_phat_interp: int = 8,
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if source_waveform_duration_s <= 0.0:
            raise ValueError("source_waveform_duration_s must be positive.")
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
        self.source_waveform_duration_s = float(source_waveform_duration_s)
        self.gcc_phat_interp = int(gcc_phat_interp)

    @staticmethod
    def is_available() -> bool:
        """Return whether the optional pyroomacoustics dependency imports."""

        try:
            importlib.import_module("pyroomacoustics")
        except ImportError:
            return False
        return True

    def simulate(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> AudioSensorFrame:
        validate_tdoa_array(sensor)
        if scene.room is None:
            raise ValueError("room_acoustics requires scene.room to be configured.")
        pra = _import_pyroomacoustics()
        frame_id = deterministic_frame_id(
            backend_id=self.backend_id,
            stage_id=scene.stage_id,
            array_id=sensor.array_id,
            timestamp_ms=time_window.timestamp_ms,
            frame_index=time_window.frame_index,
        )

        detections: list[AudioDetection] = []
        aggregate_rms = {microphone.mic_id: 0.0 for microphone in sensor.microphones}
        per_source_rir_lengths: dict[str, dict[str, int]] = {}
        active = active_sources(scene, time_window)
        for index, source in enumerate(active):
            result = self._simulate_one_source(
                pra=pra,
                room_spec=scene.room,
                source=source,
                sensor=sensor,
                time_window=time_window,
            )
            ground_truth_bearing = _ground_truth_bearing(source.position_world, sensor)
            doa = estimate_doa_from_delays(
                sensor=sensor,
                per_mic_delay_s=result.per_mic_delay_s,
                speed_of_sound_mps=self.speed_of_sound_mps,
                ambiguity_policy=self.ambiguity_policy,
                ground_truth_bearing_deg=ground_truth_bearing,
            )
            for mic_id, rms in result.per_mic_rms.items():
                aggregate_rms[mic_id] += rms

            detections.append(
                AudioDetection(
                    detection_id=deterministic_detection_id(
                        frame_id=frame_id,
                        source_id=source.source_id,
                        index=index,
                    ),
                    source_id=source.source_id,
                    class_label=source.class_label,
                    detection_mode="scheduled_known_source",
                    timestamp_ms=time_window.timestamp_ms,
                    ground_truth_bearing_deg=ground_truth_bearing,
                    source_distance_m=norm(
                        subtract(source.position_world, sensor.position_world)
                    ),
                    doa=doa,
                    source_pose=Pose3D.from_source(source),
                    per_mic_delay_s=result.per_mic_delay_s,
                    per_mic_rms=result.per_mic_rms,
                    audio_asset_path=source.audio_asset_path,
                    diagnostics={
                        "backend": self.backend_id,
                        "physical_waveform": True,
                        "room_id": scene.room.room_id,
                        "room_dimensions_m": scene.room.dimensions_m,
                        "absorption": scene.room.absorption,
                        "max_order": scene.room.max_order,
                        "air_absorption": scene.room.air_absorption,
                        "ray_tracing": scene.room.ray_tracing,
                        "speed_of_sound_mps": self.speed_of_sound_mps,
                        "sample_rate_hz": time_window.sample_rate_hz,
                        "array_geometry_rank_xy": layout_rank_xy(sensor),
                        "estimated_tdoa_matrix_s": result.tdoa_matrix_s,
                        "gcc_phat_peak": result.gcc_phat_peak,
                        "direct_path_delay_s": result.direct_path_delay_s,
                        "rir_length_samples": result.rir_length_samples,
                        "rir_peak_delay_s": result.rir_peak_delay_s,
                        "waveform_sample_count": result.waveform_sample_count,
                        "source_waveform_mode": result.source_waveform_mode,
                        "room_source_position_m": result.room_source_position_m,
                        "room_microphone_positions_m": (
                            result.room_microphone_positions_m
                        ),
                    },
                )
            )
            per_source_rir_lengths[source.source_id] = result.rir_length_samples

        return AudioSensorFrame(
            frame_id=frame_id,
            frame_name=deterministic_frame_name(
                backend_id=self.backend_id,
                stage_id=scene.stage_id,
                array_id=sensor.array_id,
                timestamp_ms=time_window.timestamp_ms,
                frame_index=time_window.frame_index,
            ),
            timestamp_ms=time_window.timestamp_ms,
            backend_id=self.backend_id,
            array_id=sensor.array_id,
            array_pose=Pose3D.from_array(sensor),
            start_time_s=time_window.start_time_s,
            end_time_s=time_window.end_time_s,
            sample_rate_hz=time_window.sample_rate_hz,
            frame_index=time_window.frame_index,
            coordinate_convention=sensor.coordinate_convention,
            provenance="room_acoustics",
            max_events=time_window.max_events,
            detections=tuple(detections),
            aggregate_per_mic_rms=aggregate_rms,
            waveform_paths=(),
            diagnostics={
                "backend": self.backend_id,
                "active_source_count": len(detections),
                "physical_waveform": True,
                "room_id": scene.room.room_id,
                "pyroomacoustics_version": getattr(pra, "__version__", "unknown"),
                "ambiguity_policy": self.ambiguity_policy,
                "per_source_rir_length_samples": per_source_rir_lengths,
            },
        )

    def _simulate_one_source(
        self,
        *,
        pra: Any,
        room_spec: RoomAcousticsSpec,
        source: AudioSourceSpec,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> _RoomSourceResult:
        source_signal, waveform_mode = _source_waveform(
            source,
            sample_rate_hz=time_window.sample_rate_hz,
            duration_s=min(
                self.source_waveform_duration_s,
                time_window.end_time_s - time_window.start_time_s,
            ),
        )
        mic_world = microphone_world_positions(sensor)
        room_positions = _fit_world_positions_to_room(
            room_spec=room_spec,
            positions={"__source__": source.position_world, **mic_world},
        )
        source_room = room_positions["__source__"]
        mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
        mic_room = {mic_id: room_positions[mic_id] for mic_id in mic_ids}

        room = _build_shoebox_room(
            pra=pra,
            room_spec=room_spec,
            sample_rate_hz=time_window.sample_rate_hz,
            speed_of_sound_mps=self.speed_of_sound_mps,
        )
        room.add_source(source_room, signal=source_signal)
        mic_matrix = np.asarray([mic_room[mic_id] for mic_id in mic_ids], dtype=float).T
        _add_microphone_array(
            pra, room, mic_matrix, sample_rate_hz=time_window.sample_rate_hz
        )
        room.compute_rir()
        room.simulate()

        waveforms = _extract_microphone_waveforms(room, mic_ids)
        max_delay = _max_microphone_spacing(mic_room) / self.speed_of_sound_mps + 0.002
        tdoa_matrix, gcc_peaks = estimate_tdoa_diagnostics(
            waveforms,
            sample_rate_hz=time_window.sample_rate_hz,
            max_delay_s=max_delay,
            interp=self.gcc_phat_interp,
        )
        per_mic_delay_s = relative_delays_from_tdoa_matrix(
            tdoa_matrix,
            mic_ids=mic_ids,
            reference_mic_id=mic_ids[0],
        )
        return _RoomSourceResult(
            per_mic_delay_s=per_mic_delay_s,
            per_mic_rms=rms_by_channel(waveforms),
            tdoa_matrix_s=tdoa_matrix,
            gcc_phat_peak=gcc_peaks,
            direct_path_delay_s={
                mic_id: norm(subtract(source_room, mic_room[mic_id]))
                / self.speed_of_sound_mps
                for mic_id in mic_ids
            },
            rir_length_samples=_rir_lengths(room, mic_ids),
            rir_peak_delay_s=_rir_peak_delays(
                room, mic_ids, time_window.sample_rate_hz
            ),
            waveform_sample_count={
                mic_id: int(len(waveforms[mic_id])) for mic_id in mic_ids
            },
            source_waveform_mode=waveform_mode,
            room_source_position_m=source_room,
            room_microphone_positions_m=mic_room,
        )


class _RoomSourceResult:
    def __init__(
        self,
        *,
        per_mic_delay_s: dict[str, float],
        per_mic_rms: dict[str, float],
        tdoa_matrix_s: dict[str, float],
        gcc_phat_peak: dict[str, float],
        direct_path_delay_s: dict[str, float],
        rir_length_samples: dict[str, int],
        rir_peak_delay_s: dict[str, float],
        waveform_sample_count: dict[str, int],
        source_waveform_mode: str,
        room_source_position_m: tuple[float, float, float],
        room_microphone_positions_m: dict[str, tuple[float, float, float]],
    ) -> None:
        self.per_mic_delay_s = per_mic_delay_s
        self.per_mic_rms = per_mic_rms
        self.tdoa_matrix_s = tdoa_matrix_s
        self.gcc_phat_peak = gcc_phat_peak
        self.direct_path_delay_s = direct_path_delay_s
        self.rir_length_samples = rir_length_samples
        self.rir_peak_delay_s = rir_peak_delay_s
        self.waveform_sample_count = waveform_sample_count
        self.source_waveform_mode = source_waveform_mode
        self.room_source_position_m = room_source_position_m
        self.room_microphone_positions_m = room_microphone_positions_m


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
    materials = (
        pra.Material(room_spec.absorption)
        if hasattr(pra, "Material")
        else room_spec.absorption
    )
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
            for optional_key in ("c", "ray_tracing", "air_absorption", "materials"):
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


def _extract_microphone_waveforms(
    room: Any, mic_ids: tuple[str, ...]
) -> dict[str, np.ndarray]:
    signals = np.asarray(room.mic_array.signals, dtype=float)
    if signals.ndim != 2 or signals.shape[0] != len(mic_ids):
        raise ValueError("pyroomacoustics returned an unexpected mic signal shape.")
    return {
        mic_id: np.asarray(signals[index], dtype=float)
        for index, mic_id in enumerate(mic_ids)
    }


def _source_waveform(
    source: AudioSourceSpec,
    *,
    sample_rate_hz: int,
    duration_s: float,
) -> tuple[np.ndarray, str]:
    if source.audio_asset_path and not source.audio_asset_path.startswith(
        "generated://"
    ):
        return _load_public_waveform(
            Path(source.audio_asset_path),
            sample_rate_hz=sample_rate_hz,
        )
    mode = source.audio_asset_path or "generated://deterministic_pulse"
    sample_count = max(256, int(round(duration_s * sample_rate_hz)))
    seed = int(hashlib.sha256(source.source_id.encode("utf-8")).hexdigest()[:8], 16)
    time_s = np.arange(sample_count, dtype=float) / float(sample_rate_hz)
    frequency_hz = 550.0 + float(seed % 700)
    waveform = np.sin(2.0 * math.pi * frequency_hz * time_s)
    waveform *= np.hanning(sample_count)
    if mode == "generated://impulse":
        waveform *= 0.2
        impulse_index = max(1, int(round(0.004 * sample_rate_hz)))
        if impulse_index < sample_count:
            waveform[impulse_index] += 1.0
    elif mode == "generated://pulse":
        waveform *= 0.15
        for offset_s, amplitude in ((0.004, 1.0), (0.010, -0.65), (0.017, 0.4)):
            pulse_index = max(1, int(round(offset_s * sample_rate_hz)))
            if pulse_index < sample_count:
                waveform[pulse_index] += amplitude
    peak = float(np.max(np.abs(waveform)))
    if peak > 0.0:
        waveform = waveform / peak
    gain = 10.0 ** (source.gain_db / 20.0)
    return np.asarray(waveform * gain, dtype=float), mode


def _load_public_waveform(
    path: Path,
    *,
    sample_rate_hz: int,
) -> tuple[np.ndarray, str]:
    if not path.exists():
        raise ValueError(f"Audio asset {str(path)!r} does not exist.")
    try:
        import soundfile as sf  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Reading audio_asset_path files requires soundfile from the 'room' extra."
        ) from exc
    data, file_rate = sf.read(path, always_2d=False)
    waveform = np.asarray(data, dtype=float)
    if waveform.ndim == 2:
        waveform = np.mean(waveform, axis=1)
    if int(file_rate) != int(sample_rate_hz):
        raise ValueError(
            "audio_asset_path sample rate must match the sensor sample rate for "
            "the MVP room_acoustics backend."
        )
    return waveform, f"file:{path}"


def _fit_world_positions_to_room(
    *,
    room_spec: RoomAcousticsSpec,
    positions: dict[str, tuple[float, float, float]],
) -> dict[str, tuple[float, float, float]]:
    dimensions = room_spec.dimensions_m
    margin = 0.25
    axes = tuple(zip(*positions.values(), strict=True))
    offsets: list[float] = []
    for axis_index, axis_values in enumerate(axes):
        min_value = min(axis_values)
        max_value = max(axis_values)
        span = max_value - min_value
        max_span = dimensions[axis_index] - 2.0 * margin
        if span > max_span:
            raise ValueError(
                "room_acoustics positions do not fit inside room dimensions "
                f"on axis {axis_index}: span={span:.3f}m, capacity={max_span:.3f}m."
            )
        offsets.append(margin - min_value)
    room_positions: dict[str, tuple[float, float, float]] = {}
    for key, position in positions.items():
        room_positions[key] = (
            float(position[0] + offsets[0]),
            float(position[1] + offsets[1]),
            float(position[2] + offsets[2]),
        )
    return room_positions


def _max_microphone_spacing(
    positions: dict[str, tuple[float, float, float]],
) -> float:
    max_spacing = 0.0
    values = tuple(positions.values())
    for left in values:
        for right in values:
            max_spacing = max(max_spacing, norm(subtract(left, right)))
    return max_spacing


def _rir_lengths(room: Any, mic_ids: tuple[str, ...]) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, index)
        lengths[mic_id] = 0 if rir is None else int(len(rir))
    return lengths


def _rir_peak_delays(
    room: Any,
    mic_ids: tuple[str, ...],
    sample_rate_hz: int,
) -> dict[str, float]:
    delays: dict[str, float] = {}
    for index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, index)
        if rir is None or len(rir) == 0:
            delays[mic_id] = 0.0
        else:
            delays[mic_id] = float(np.argmax(np.abs(rir))) / float(sample_rate_hz)
    return delays


def _rir_for(room: Any, mic_index: int) -> np.ndarray | None:
    rir = getattr(room, "rir", None)
    if rir is None:
        return None
    try:
        return np.asarray(rir[mic_index][0], dtype=float)
    except (IndexError, TypeError):
        return None


def _ground_truth_bearing(
    source_position_world: tuple[float, float, float],
    sensor: MicrophoneArraySpec,
) -> float | None:
    delta = subtract(source_position_world, sensor.position_world)
    bearing = bearing_from_components(
        dot(delta, sensor.forward_vec_world),
        dot(delta, sensor.right_vec_world),
    )
    if bearing is None:
        return None
    return bearing
