"""Optional pyroomacoustics-backed room simulation path."""

from __future__ import annotations

import hashlib
import importlib
import math
from dataclasses import dataclass
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
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.math_utils import (
    angular_error_deg,
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

_SECONDARY_TONE_RATIO = 1.618033988749895
_SECONDARY_TONE_GAIN = 0.6
_TWO_TONE_PEAK = 1.0 + _SECONDARY_TONE_GAIN
_EDGE_RAMP_S = 0.004
_IMPULSE_SPIKES_S = ((0.004, 1.0),)
_PULSE_SPIKES_S = ((0.004, 1.0), (0.010, -0.65), (0.017, 0.4))


class RoomAcousticsBackend:
    """Optional shoebox-room backend using pyroomacoustics and GCC-PHAT.

    All active sources share one room per frame, so microphone signals are
    true mixtures; per-source diagnostics come from the simulation premix.
    """

    backend_id = "room_acoustics"

    def __init__(
        self,
        *,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        source_waveform_duration_s: float = 0.08,
        gcc_phat_interp: int = 8,
        waveform_writer: WaveformSink | None = None,
    ) -> None:
        if speed_of_sound_mps <= 0.0 or not math.isfinite(speed_of_sound_mps):
            raise ValueError("speed_of_sound_mps must be positive and finite.")
        if ambiguity_policy not in {"none", "front_hemisphere"}:
            raise ValueError("ambiguity_policy must be 'none' or 'front_hemisphere'.")
        if source_waveform_duration_s <= 0.0:
            raise ValueError("source_waveform_duration_s must be positive.")
        self.speed_of_sound_mps = float(speed_of_sound_mps)
        self.ambiguity_policy = ambiguity_policy
        # Retained for API compatibility: generated sources now emit
        # continuously over their scheduled interval instead of a fixed-length
        # per-window probe.
        self.source_waveform_duration_s = float(source_waveform_duration_s)
        self.gcc_phat_interp = int(gcc_phat_interp)
        self.waveform_writer = waveform_writer

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
        mic_ids = tuple(microphone.mic_id for microphone in sensor.microphones)
        sample_rate_hz = time_window.sample_rate_hz
        window_sample_count = max(
            1,
            int(
                round(
                    (time_window.end_time_s - time_window.start_time_s)
                    * sample_rate_hz
                )
            ),
        )

        detections: list[AudioDetection] = []
        active = active_sources(scene, time_window)
        room_config = _room_config_summary(scene.room)
        mic_world = microphone_world_positions(sensor)
        per_source_rir_summary: dict[str, dict[str, object]] = {}
        mixture = np.zeros((len(mic_ids), window_sample_count), dtype=float)

        if active:
            source_positions = {
                f"source:{source.source_id}": source.position_world
                for source in active
            }
            microphone_positions = {
                f"mic:{mic_id}": position for mic_id, position in mic_world.items()
            }
            room_positions = _fit_world_positions_to_room(
                room_spec=scene.room,
                positions={**source_positions, **microphone_positions},
            )
            source_room_positions = {
                source.source_id: room_positions[f"source:{source.source_id}"]
                for source in active
            }
            mic_room = {
                mic_id: room_positions[f"mic:{mic_id}"] for mic_id in mic_ids
            }

            room = _build_shoebox_room(
                pra=pra,
                room_spec=scene.room,
                sample_rate_hz=sample_rate_hz,
                speed_of_sound_mps=self.speed_of_sound_mps,
            )
            scheduled: list[_ScheduledSignal] = []
            for source in active:
                signal = _scheduled_window_signal(source, time_window=time_window)
                scheduled.append(signal)
                room.add_source(
                    source_room_positions[source.source_id],
                    signal=signal.signal,
                )
            mic_matrix = np.asarray(
                [mic_room[mic_id] for mic_id in mic_ids], dtype=float
            ).T
            _add_microphone_array(
                pra, room, mic_matrix, sample_rate_hz=sample_rate_hz
            )
            room.compute_rir()
            premix = _simulate_premix(
                room,
                source_count=len(active),
                mic_count=len(mic_ids),
            )
            summed = np.sum(premix, axis=0)
            if summed.shape[1] >= window_sample_count:
                mixture = summed
            else:
                mixture[:, : summed.shape[1]] = summed

            max_delay = (
                _max_microphone_spacing(mic_room) / self.speed_of_sound_mps + 0.002
            )
            for index, source in enumerate(active):
                source_waveforms = {
                    mic_id: premix[index, mic_index]
                    for mic_index, mic_id in enumerate(mic_ids)
                }
                if all(np.any(waveform) for waveform in source_waveforms.values()):
                    tdoa_matrix, gcc_peaks = estimate_tdoa_diagnostics(
                        source_waveforms,
                        sample_rate_hz=sample_rate_hz,
                        max_delay_s=max_delay,
                        interp=self.gcc_phat_interp,
                    )
                    per_mic_delay_s = relative_delays_from_tdoa_matrix(
                        tdoa_matrix,
                        mic_ids=mic_ids,
                        reference_mic_id=mic_ids[0],
                    )
                else:
                    # Active but silent in this window (e.g. an exhausted file
                    # asset): GCC-PHAT is undefined on all-zero signals.
                    tdoa_matrix = {
                        f"{left}->{right}": 0.0
                        for left in mic_ids
                        for right in mic_ids
                    }
                    gcc_peaks = {key: 0.0 for key in tdoa_matrix}
                    per_mic_delay_s = {mic_id: 0.0 for mic_id in mic_ids}
                per_mic_rms = rms_by_channel(source_waveforms)
                source_room = source_room_positions[source.source_id]
                rir_length_samples = _rir_lengths(
                    room, mic_ids, source_index=index
                )
                rir_peak_delay_s = _rir_peak_delays(
                    room, mic_ids, sample_rate_hz, source_index=index
                )
                waveform_sample_count = {
                    mic_id: int(premix.shape[2]) for mic_id in mic_ids
                }
                direct_path_delay_s = {
                    mic_id: norm(subtract(source_room, mic_room[mic_id]))
                    / self.speed_of_sound_mps
                    for mic_id in mic_ids
                }
                ground_truth_bearing = _ground_truth_bearing(
                    source.position_world, sensor
                )
                doa = estimate_doa_from_delays(
                    sensor=sensor,
                    per_mic_delay_s=per_mic_delay_s,
                    speed_of_sound_mps=self.speed_of_sound_mps,
                    ambiguity_policy=self.ambiguity_policy,
                )
                oracle_bearing_error = (
                    None
                    if doa.estimated_bearing_deg is None
                    or ground_truth_bearing is None
                    else angular_error_deg(
                        doa.estimated_bearing_deg,
                        ground_truth_bearing,
                    )
                )
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
                        per_mic_delay_s=per_mic_delay_s,
                        per_mic_rms=per_mic_rms,
                        audio_asset_path=source.audio_asset_path,
                        diagnostics={
                            "backend": self.backend_id,
                            "physical_waveform": True,
                            "room_id": scene.room.room_id,
                            "room_config": room_config,
                            "room_dimensions_m": scene.room.dimensions_m,
                            "absorption": scene.room.absorption,
                            "max_order": scene.room.max_order,
                            "air_absorption": scene.room.air_absorption,
                            "ray_tracing": scene.room.ray_tracing,
                            "pyroomacoustics_version": getattr(
                                pra, "__version__", "unknown"
                            ),
                            "speed_of_sound_mps": self.speed_of_sound_mps,
                            "sample_rate_hz": sample_rate_hz,
                            "array_geometry_rank_xy": layout_rank_xy(sensor),
                            "estimated_tdoa_matrix_s": tdoa_matrix,
                            "gcc_phat_peaks": gcc_peaks,
                            "gcc_phat_peak": gcc_peaks,
                            "direct_path_delay_s": direct_path_delay_s,
                            "oracle_bearing_error_deg": oracle_bearing_error,
                            "per_mic_rms": per_mic_rms,
                            "rir_length_samples": rir_length_samples,
                            "rir_peak_delay_s": rir_peak_delay_s,
                            "waveform_sample_count": waveform_sample_count,
                            "source_waveform_mode": scheduled[index].mode,
                            "scheduled_start_offset_samples": (
                                scheduled[index].start_offset_samples
                            ),
                            "scheduled_content_sample_count": (
                                scheduled[index].content_sample_count
                            ),
                            "room_source_position_m": source_room,
                            "room_microphone_positions_m": mic_room,
                        },
                    )
                )
                per_source_rir_summary[source.source_id] = {
                    "rir_length_samples": rir_length_samples,
                    "rir_peak_delay_s": rir_peak_delay_s,
                    "waveform_sample_count": waveform_sample_count,
                    "source_waveform_mode": scheduled[index].mode,
                    "room_source_position_m": source_room,
                    "room_microphone_positions_m": mic_room,
                }

        aggregate_per_mic_rms = rms_by_channel(
            {
                mic_id: mixture[mic_index]
                for mic_index, mic_id in enumerate(mic_ids)
            }
        )
        frame_diagnostics: dict[str, Any] = {
            "backend": self.backend_id,
            "active_source_count": len(detections),
            "scheduled_source_ids": tuple(source.source_id for source in active),
            "physical_waveform": True,
            "room_id": scene.room.room_id,
            "room_config": room_config,
            "pyroomacoustics_version": getattr(pra, "__version__", "unknown"),
            "speed_of_sound_mps": self.speed_of_sound_mps,
            "sample_rate_hz": sample_rate_hz,
            "ambiguity_policy": self.ambiguity_policy,
            "max_events": time_window.max_events,
            "time_window_s": (
                time_window.start_time_s,
                time_window.end_time_s,
            ),
            "window_sample_count": window_sample_count,
            "per_source_rir_summary": per_source_rir_summary,
            "per_source_rir_length_samples": {
                source_id: summary["rir_length_samples"]
                for source_id, summary in per_source_rir_summary.items()
            },
        }
        waveform_paths: tuple[str, ...] = ()
        if self.waveform_writer is not None:
            write_result = self.waveform_writer.write_frame_mixture(
                frame_id=frame_id,
                mixture=mixture,
                sample_rate_hz=sample_rate_hz,
                mic_ids=mic_ids,
                window_sample_count=window_sample_count,
            )
            waveform_paths = write_result.paths
            frame_diagnostics["waveform"] = dict(write_result.diagnostics)

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
            sample_rate_hz=sample_rate_hz,
            frame_index=time_window.frame_index,
            coordinate_convention=sensor.coordinate_convention,
            provenance="room_acoustics",
            max_events=time_window.max_events,
            detections=tuple(detections),
            aggregate_per_mic_rms=aggregate_per_mic_rms,
            waveform_paths=waveform_paths,
            diagnostics=frame_diagnostics,
        )


@dataclass(frozen=True, slots=True)
class _ScheduledSignal:
    """One source's window-relative signal with sample-accurate scheduling."""

    signal: np.ndarray
    mode: str
    start_offset_samples: int
    content_sample_count: int


def _scheduled_window_signal(
    source: AudioSourceSpec,
    *,
    time_window: AudioTimeWindow,
) -> _ScheduledSignal:
    """Position a source's emission inside a window with sample accuracy.

    A source starting mid-window gets leading zero-padding; a source that
    started before the window resumes from its elapsed offset. Content is
    truncated at whichever comes first of the source end and the window end.
    """

    sample_rate_hz = time_window.sample_rate_hz
    start_offset_samples = int(
        round(
            max(0.0, source.start_time_s - time_window.start_time_s)
            * sample_rate_hz
        )
    )
    elapsed_samples = int(
        round(
            max(0.0, time_window.start_time_s - source.start_time_s)
            * sample_rate_hz
        )
    )
    source_end_s = (
        math.inf
        if source.duration_s is None
        else source.start_time_s + float(source.duration_s)
    )
    effective_start_s = max(source.start_time_s, time_window.start_time_s)
    content_samples = max(
        0,
        int(
            round(
                (min(source_end_s, time_window.end_time_s) - effective_start_s)
                * sample_rate_hz
            )
        ),
    )

    if source.audio_asset_path and not source.audio_asset_path.startswith(
        "generated://"
    ):
        base, mode = _load_public_waveform(
            Path(source.audio_asset_path),
            sample_rate_hz=sample_rate_hz,
        )
        content = np.zeros(content_samples, dtype=float)
        available = base[elapsed_samples : elapsed_samples + content_samples]
        content[: available.size] = available
    else:
        mode = source.audio_asset_path or "generated://deterministic_pulse"
        content = _generated_source_content(
            source,
            mode=mode,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
            content_samples=content_samples,
            source_end_s=source_end_s,
        )
    signal = np.concatenate(
        [np.zeros(start_offset_samples, dtype=float), content]
    )
    if signal.size == 0:
        signal = np.zeros(1, dtype=float)
    return _ScheduledSignal(
        signal=signal,
        mode=mode,
        start_offset_samples=start_offset_samples,
        content_sample_count=content_samples,
    )


def _generated_source_content(
    source: AudioSourceSpec,
    *,
    mode: str,
    sample_rate_hz: int,
    elapsed_samples: int,
    content_samples: int,
    source_end_s: float,
) -> np.ndarray:
    """Synthesize a deterministic, phase-continuous slice of a source.

    The base signal is a seeded two-tone (the second tone at an irrational
    frequency ratio keeps GCC-PHAT correlation aperiodic) evaluated at
    absolute source-relative time, so consecutive windows concatenate without
    discontinuities.
    """

    if content_samples <= 0:
        return np.zeros(0, dtype=float)
    seed = int(hashlib.sha256(source.source_id.encode("utf-8")).hexdigest()[:8], 16)
    frequency_hz = 550.0 + float(seed % 700)
    time_s = (
        elapsed_samples + np.arange(content_samples, dtype=float)
    ) / float(sample_rate_hz)
    waveform = (
        np.sin(2.0 * math.pi * frequency_hz * time_s)
        + _SECONDARY_TONE_GAIN
        * np.sin(2.0 * math.pi * frequency_hz * _SECONDARY_TONE_RATIO * time_s)
    ) / _TWO_TONE_PEAK
    waveform *= _emission_edge_envelope(
        time_s,
        source=source,
        source_end_s=source_end_s,
    )
    if mode == "generated://impulse":
        waveform *= 0.2
        _add_source_relative_spikes(
            waveform,
            _IMPULSE_SPIKES_S,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
        )
        waveform /= 1.2
    elif mode == "generated://pulse":
        waveform *= 0.15
        _add_source_relative_spikes(
            waveform,
            _PULSE_SPIKES_S,
            sample_rate_hz=sample_rate_hz,
            elapsed_samples=elapsed_samples,
        )
        waveform /= 1.15
    gain = 10.0 ** (source.gain_db / 20.0)
    return np.asarray(waveform * gain, dtype=float)


def _emission_edge_envelope(
    time_s: np.ndarray,
    *,
    source: AudioSourceSpec,
    source_end_s: float,
) -> np.ndarray:
    """Short attack/release ramps at the source-relative emission edges."""

    ramp_s = _EDGE_RAMP_S
    if source.duration_s is not None:
        ramp_s = min(ramp_s, float(source.duration_s) / 4.0)
    if ramp_s <= 0.0:
        return np.ones_like(time_s)
    envelope = np.clip(time_s / ramp_s, 0.0, 1.0)
    if math.isfinite(source_end_s):
        emission_s = source_end_s - source.start_time_s
        envelope *= np.clip((emission_s - time_s) / ramp_s, 0.0, 1.0)
    return envelope


def _add_source_relative_spikes(
    waveform: np.ndarray,
    spikes: tuple[tuple[float, float], ...],
    *,
    sample_rate_hz: int,
    elapsed_samples: int,
) -> None:
    """Add transient spikes positioned in source-relative time, in place."""

    for offset_s, amplitude in spikes:
        spike_sample = max(1, int(round(offset_s * sample_rate_hz)))
        window_index = spike_sample - elapsed_samples
        if 0 <= window_index < waveform.size:
            waveform[window_index] += amplitude


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


def _load_public_waveform(
    path: Path,
    *,
    sample_rate_hz: int,
) -> tuple[np.ndarray, str]:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(
            "audio_asset_path for room_acoustics must be a relative public "
            "package path."
        )
    resolved = path.resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
    except ValueError as exc:
        raise ValueError(
            "audio_asset_path for room_acoustics must stay under the current "
            "package checkout."
        ) from exc
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
        waveform = _resample_waveform(
            waveform,
            from_hz=int(file_rate),
            to_hz=int(sample_rate_hz),
        )
    return waveform, f"file:{path}"


def _resample_waveform(
    waveform: np.ndarray,
    *,
    from_hz: int,
    to_hz: int,
) -> np.ndarray:
    """Resample a mono waveform between sample rates with polyphase filtering."""

    try:
        from scipy.signal import resample_poly  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Resampling audio_asset_path files requires scipy from the "
            "'room' extra."
        ) from exc
    divisor = math.gcd(from_hz, to_hz)
    return np.asarray(
        resample_poly(waveform, to_hz // divisor, from_hz // divisor),
        dtype=float,
    )


def _room_config_summary(room_spec: RoomAcousticsSpec) -> dict[str, object]:
    return {
        "room_id": room_spec.room_id,
        "dimensions_m": room_spec.dimensions_m,
        "absorption": _absorption_summary(room_spec.absorption),
        "max_order": room_spec.max_order,
        "air_absorption": room_spec.air_absorption,
        "ray_tracing": room_spec.ray_tracing,
    }


def _absorption_summary(
    absorption: float | dict[str, float],
) -> float | dict[str, float]:
    if isinstance(absorption, dict):
        return {str(key): float(value) for key, value in sorted(absorption.items())}
    return float(absorption)


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


def _rir_lengths(
    room: Any,
    mic_ids: tuple[str, ...],
    *,
    source_index: int,
) -> dict[str, int]:
    lengths: dict[str, int] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        lengths[mic_id] = 0 if rir is None else int(len(rir))
    return lengths


def _rir_peak_delays(
    room: Any,
    mic_ids: tuple[str, ...],
    sample_rate_hz: int,
    *,
    source_index: int,
) -> dict[str, float]:
    delays: dict[str, float] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        rir = _rir_for(room, mic_index, source_index)
        if rir is None or len(rir) == 0:
            delays[mic_id] = 0.0
        else:
            delays[mic_id] = float(np.argmax(np.abs(rir))) / float(sample_rate_hz)
    return delays


def _rir_for(room: Any, mic_index: int, source_index: int) -> np.ndarray | None:
    rir = getattr(room, "rir", None)
    if rir is None:
        return None
    try:
        return np.asarray(rir[mic_index][source_index], dtype=float)
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
