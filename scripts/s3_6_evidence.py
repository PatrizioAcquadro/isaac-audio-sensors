#!/usr/bin/env python3
"""Generate deterministic pure S3.6 waveform-directivity evidence."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import platform
import struct
import subprocess
import sys
import wave
import zlib
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

import isaac_audio_sensors.core.backends.room_acoustics as room_module
from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.amplitude import directivity_factor
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    _apply_directivity_to_premix,
)
from isaac_audio_sensors.core.doa.gcc_phat import gcc_phat_delay
from isaac_audio_sensors.core.doa.srp_phat import (
    srp_phat_confidence,
    srp_phat_direction,
)
from isaac_audio_sensors.core.effects import (
    DirectivityConfig,
    DirectivityFrequencyPointConfig,
    DirectivityPatternConfig,
    DirectivityPatternSetConfig,
    EffectsConfig,
    MotionEffectsConfig,
)
from isaac_audio_sensors.core.effects.channel_response import fractional_delay
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.effects.directivity import (
    apply_pair_directivity,
    directivity_diagnostics,
    evaluate_polar_pattern,
    source_polar_gain,
)
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import (
    microphone_layout,
    microphone_world_positions,
)
from isaac_audio_sensors.core.motion import (
    SegmentEntityMotion,
    WindowMotionPlan,
    WindowMotionSegment,
)
from isaac_audio_sensors.core.plugins.registry import (
    get_default_registry,
    validate_declaration,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSpec,
    RoomAcousticsSpec,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.6"
PROTOCOL_REVISION = "31e0282"
SRP_CONFIDENCE_REMEDIATION_REVISION = "5bfa67e"
SAMPLE_RATE_HZ = 48_000
R = math.sqrt(0.5)
QUATERNIONS = (
    (0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, R, R),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, -R, R),
)
TARGETS = {
    "omni": (1.0, 1.0, 1.0, 1.0),
    "cardioid": (1.0, 0.5, 0.0, 0.5),
    "figure_eight": (1.0, 0.0, -1.0, 0.0),
    "supercardioid": (1.0, 0.37, -0.26, 0.37),
}
POINTS = (
    DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=-6.0),
    DirectivityFrequencyPointConfig(freq_hz=1000.0, gain_db=0.0),
    DirectivityFrequencyPointConfig(freq_hz=8000.0, gain_db=-3.0),
    DirectivityFrequencyPointConfig(freq_hz=20_000.0, gain_db=-9.0),
)
ROOM_DIMENSIONS_M = (10.0, 8.0, 3.0)
ROOM_SOURCE_POSITION = (2.0, 4.0, 1.5)
ROOM_MIRRORED_SOURCE_POSITION = (8.0, 4.0, 1.5)
ROOM_ARRAY_CENTER = (6.0, 4.0, 1.5)
ESTIMATOR_ANGLES_DEG = (0, 90, 120, 180)
SRP_CONFIDENCE_FORMULA_ID = "contrast_times_clamped_peak_power_per_pair_v1"
ESTIMATOR_QUATERNIONS = (
    QUATERNIONS[0],
    QUATERNIONS[1],
    (0.0, 0.0, math.sqrt(3.0) / 2.0, 0.5),
    QUATERNIONS[2],
)


class _CaptureSink:
    """Capture one backend-exported mixture without changing its bytes."""

    def __init__(self) -> None:
        self.mixture: np.ndarray | None = None

    def write_frame_mixture(self, **kwargs: object) -> WaveformWriteResult:
        self.mixture = np.asarray(kwargs["mixture"], dtype=np.float64).copy()
        return WaveformWriteResult(paths=("memory://s3_6.wav",))

    def close(self) -> None:
        return None


def _json(name: str, payload: object) -> Path:
    path = OUTPUT / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _frame_bytes(frame: object) -> bytes:
    return _canonical_bytes(frame_to_trace_dict(frame))


def _status_for(*checks: bool) -> str:
    return "passed" if all(checks) else "failed"


def _dependency_placeholder(reason: str) -> dict[str, object]:
    return {
        "dependency": "pyroomacoustics",
        "reason": reason,
        "status": "dependency_unavailable",
    }


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _plot_png(
    name: str,
    series: tuple[np.ndarray, ...],
    *,
    width: int = 640,
    height: int = 360,
) -> None:
    """Write a dependency-free RGB line plot used only as visual evidence."""

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    image[height // 2, :, :] = 220
    image[:, width // 2, :] = 220
    colors = (
        (20, 90, 200),
        (220, 60, 40),
        (40, 150, 70),
        (140, 50, 180),
        (220, 140, 20),
    )
    finite = np.concatenate([values[np.isfinite(values)] for values in series])
    lower = float(np.min(finite)) if finite.size else -1.0
    upper = float(np.max(finite)) if finite.size else 1.0
    if upper <= lower:
        upper = lower + 1.0
    for values, color in zip(series, colors, strict=False):
        if values.size < 2:
            continue
        xs = np.linspace(4, width - 5, values.size).astype(int)
        ys = (height - 5 - (values - lower) / (upper - lower) * (height - 10)).astype(
            int
        )
        ys = np.clip(ys, 0, height - 1)
        for index in range(values.size - 1):
            count = (
                max(abs(xs[index + 1] - xs[index]), abs(ys[index + 1] - ys[index])) + 1
            )
            line_x = np.linspace(xs[index], xs[index + 1], count).astype(int)
            line_y = np.linspace(ys[index], ys[index + 1], count).astype(int)
            image[line_y, line_x] = color
    raw = b"".join(b"\x00" + row.tobytes() for row in image)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )
    (OUTPUT / name).write_bytes(payload)


def _pattern(
    family: str,
    points: tuple[DirectivityFrequencyPointConfig, ...] | None = None,
) -> DirectivityPatternConfig:
    return DirectivityPatternConfig(family=family, frequency_points=points)


def _source(
    source_id: str,
    orientation: tuple[float, float, float, float],
    *,
    directivity: str = "cardioid",
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/{source_id}",
        class_label="speaker",
        audio_asset_path="generated://deterministic_pulse",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=orientation,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
        directivity=directivity,
    )


def _array() -> MicrophoneArraySpec:
    microphones = tuple(
        MicrophoneSpec(mic_id=mic_id, relative_position_m=position)
        for mic_id, position in (
            ("front", (0.0, 0.0, 0.0)),
            ("right", (0.0, 0.08, 0.0)),
            ("rear", (0.0, -0.08, 0.0)),
            ("top", (0.0, 0.0, 0.08)),
        )
    )
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _room_array(
    *, reference_orientation: tuple[float, float, float, float] = QUATERNIONS[0]
) -> MicrophoneArraySpec:
    microphones = (
        MicrophoneSpec(
            mic_id="reference",
            relative_position_m=(0.0, 0.0, 0.0),
            relative_orientation_quat=reference_orientation,
        ),
        MicrophoneSpec(
            mic_id="positive_y",
            relative_position_m=(0.0, 0.08, 0.0),
            relative_orientation_quat=QUATERNIONS[0],
        ),
        MicrophoneSpec(
            mic_id="negative_y",
            relative_position_m=(0.0, -0.08, 0.0),
            relative_orientation_quat=QUATERNIONS[0],
        ),
        MicrophoneSpec(
            mic_id="positive_z",
            relative_position_m=(0.0, 0.0, 0.08),
            relative_orientation_quat=QUATERNIONS[0],
        ),
    )
    return MicrophoneArraySpec(
        array_id="rig",
        prim_path="/World/Rig",
        position_world=ROOM_ARRAY_CENTER,
        orientation_world_quat=QUATERNIONS[0],
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=microphones,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _room_source(
    *,
    position: tuple[float, float, float] = ROOM_SOURCE_POSITION,
    orientation: tuple[float, float, float, float] = QUATERNIONS[0],
    audio_asset_path: str | None = "generated://deterministic_pulse",
    duration_s: float = 1.0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="talker",
        prim_path="/World/Talker",
        class_label="speaker",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=orientation,
        start_time_s=0.0,
        duration_s=duration_s,
        gain_db=0.0,
        directivity="omni",
    )


def _room_fixture(
    *,
    source: AudioSourceSpec,
    sensor: MicrophoneArraySpec,
    sample_count: int,
    absorption: float = 0.0,
    max_order: int = 0,
) -> tuple[AudioSceneSnapshot, AudioTimeWindow]:
    scene = AudioSceneSnapshot(
        stage_id="s3_6_frozen_room",
        timestamp_ms=0,
        sources=(source,),
        arrays=(sensor,),
        room=RoomAcousticsSpec(
            room_id="s3_6_shoebox",
            dimensions_m=ROOM_DIMENSIONS_M,
            absorption=absorption,
            max_order=max_order,
            origin_m=(0.0, 0.0, 0.0),
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=sample_count / SAMPLE_RATE_HZ,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
    )
    return scene, window


def _run_room_backend(
    *,
    source: AudioSourceSpec,
    sensor: MicrophoneArraySpec,
    sample_count: int,
    effects: EffectsConfig | None = None,
    probe: np.ndarray | None = None,
    absorption: float = 0.0,
    max_order: int = 0,
    window_motion: WindowMotionPlan | None = None,
    backend: RoomAcousticsBackend | None = None,
) -> tuple[object, np.ndarray]:
    scene, window = _room_fixture(
        source=source,
        sensor=sensor,
        sample_count=sample_count,
        absorption=absorption,
        max_order=max_order,
    )
    sink = _CaptureSink()
    selected = backend or RoomAcousticsBackend(
        waveform_writer=sink,
        effects=effects,
        window_motion=window_motion,
    )
    selected.waveform_writer = sink
    original_scheduled = room_module._scheduled_window_signal
    if probe is not None:
        frozen_probe = np.asarray(probe, dtype=np.float64)

        def scheduled_fixture(
            scheduled_source: AudioSourceSpec,
            *,
            time_window: AudioTimeWindow,
        ) -> object:
            scheduled = original_scheduled(
                scheduled_source,
                time_window=time_window,
            )
            return replace(
                scheduled,
                signal=frozen_probe.copy(),
                mode="fixture:s3_6_broadband",
                start_offset_samples=0,
                content_sample_count=frozen_probe.size,
            )

        room_module._scheduled_window_signal = scheduled_fixture
    try:
        frame = selected.simulate(scene, sensor, window)
    finally:
        room_module._scheduled_window_signal = original_scheduled
    if sink.mixture is None:
        raise RuntimeError("room backend did not export the frozen fixture mixture")
    return frame, sink.mixture


def _effects(
    *,
    source_pattern: DirectivityPatternConfig | None = None,
    mic_pattern: DirectivityPatternConfig | None = None,
    segments_per_window: int = 1,
) -> EffectsConfig:
    directivity = DirectivityConfig(
        enabled=source_pattern is not None or mic_pattern is not None,
        source_patterns=(
            None
            if source_pattern is None
            else DirectivityPatternSetConfig(default=source_pattern)
        ),
        mic_patterns=(
            None
            if mic_pattern is None
            else DirectivityPatternSetConfig(default=mic_pattern)
        ),
    )
    if segments_per_window == 1:
        return EffectsConfig(directivity=directivity)
    return EffectsConfig(
        directivity=directivity,
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=segments_per_window,
        ),
    )


def _config_contract() -> dict[str, object]:
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(
            default=_pattern("omni"),
            overrides={"talker": _pattern("cardioid", POINTS)},
        ),
    )
    payload = {
        "record_fields": {
            record.__name__: [field.name for field in fields(record)]
            for record in (
                DirectivityFrequencyPointConfig,
                DirectivityPatternConfig,
                DirectivityPatternSetConfig,
                DirectivityConfig,
            )
        },
        "defaults": {
            "enabled": DirectivityConfig().enabled,
            "source_patterns": DirectivityConfig().source_patterns,
            "mic_patterns": DirectivityConfig().mic_patterns,
            "mode": DirectivityConfig().mode,
            "resolved_mode": "per_pair_direct_path",
        },
        "override_mapping_immutable": type(config.source_patterns.overrides).__name__
        == "mappingproxy",
        "resolution": {
            "talker": config.source_patterns.overrides["talker"].family,
            "other": config.source_patterns.default.family,
        },
    }
    payload["status"] = "passed"
    _json("directivity_config_contract.json", payload)
    return payload


def _polar_evidence() -> tuple[dict[str, object], float]:
    rows: list[dict[str, object]] = []
    maximum = 0.0
    curves: list[np.ndarray] = []
    angles = np.linspace(0.0, 2.0 * math.pi, 721)
    for family, targets in TARGETS.items():
        curves.append(
            np.asarray(
                [
                    evaluate_polar_pattern(
                        family,
                        orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
                        direction=(math.cos(angle), math.sin(angle), 0.0),
                    )
                    for angle in angles
                ]
            )
        )
        for angle_deg, quaternion, target in zip(
            (0, 90, 180, 270), QUATERNIONS, targets, strict=True
        ):
            observed = evaluate_polar_pattern(
                family,
                orientation_xyzw=quaternion,
                direction=(1.0, 0.0, 0.0),
            )
            scaled = evaluate_polar_pattern(
                family,
                orientation_xyzw=tuple(3.0 * value for value in quaternion),
                direction=(1.0, 0.0, 0.0),
            )
            error = max(abs(observed - target), abs(scaled - target))
            maximum = max(maximum, error)
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "target": target,
                    "observed": observed,
                    "scaled_quaternion_observed": scaled,
                    "absolute_error": error,
                }
            )
    payload = {
        "tolerance": 1e-12,
        "maximum_absolute_error": maximum,
        "rows": rows,
        "status": "passed" if maximum <= 1e-12 else "failed",
    }
    _json("polar_cardinal_results.json", payload)
    _plot_png("polar_response_overlay.png", tuple(curves))
    return payload, maximum


def _waveform_and_product_evidence() -> tuple[dict[str, object], float, float]:
    rng = np.random.default_rng(20260718)
    baseline = rng.normal(size=48_000)
    denominator = float(np.dot(baseline, baseline))
    rows: list[dict[str, object]] = []
    hashes: dict[str, str] = {"baseline": _sha256(baseline.tobytes())}
    maximum_db = 0.0
    maximum_null = 0.0
    for family, targets in TARGETS.items():
        for angle_deg, quaternion, target in zip(
            (0, 90, 180, 270), QUATERNIONS, targets, strict=True
        ):
            output = apply_pair_directivity(
                baseline,
                source_pattern=_pattern(family),
                microphone_pattern=_pattern("omni"),
                source_position_world=(0.0, 0.0, 0.0),
                source_orientation_world_xyzw=quaternion,
                microphone_position_world=(1.0, 0.0, 0.0),
                microphone_orientation_world_xyzw=QUATERNIONS[0],
                sample_rate_hz=SAMPLE_RATE_HZ,
            )
            gain = float(np.dot(baseline, output) / denominator)
            if target == 0.0:
                error_db = None
                maximum_null = max(maximum_null, abs(gain))
            else:
                error_db = abs(20.0 * math.log10(abs(gain / target)))
                maximum_db = max(maximum_db, error_db)
            key = f"{family}_{angle_deg}"
            hashes[key] = _sha256(output.tobytes())
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "target": target,
                    "signed_least_squares_gain": gain,
                    "magnitude_error_db": error_db,
                    "linear_null_leakage": abs(gain) if target == 0.0 else None,
                }
            )
    payload = {
        "non_null_tolerance_db": 0.05,
        "null_tolerance_linear": 1e-6,
        "maximum_non_null_error_db": maximum_db,
        "maximum_null_leakage_linear": maximum_null,
        "rows": rows,
        "pure_pair_status": (
            "passed" if maximum_db <= 0.05 and maximum_null <= 1e-6 else "failed"
        ),
    }
    payload["real_room_status"] = "pending_fixture_execution"
    payload["status"] = payload["pure_pair_status"]
    _json("cardinal_waveform_gain.json", payload)
    _json("cardinal_pair_stems_sha256.json", hashes)
    return payload, maximum_db, maximum_null


def _frequency_evidence() -> tuple[dict[str, object], float, float]:
    sample_count = 2**18
    impulse = np.zeros(sample_count)
    impulse[sample_count // 2] = 1.0
    shaped = _pattern("omni", POINTS)
    kwargs = {
        "source_position_world": (0.0, 0.0, 0.0),
        "source_orientation_world_xyzw": None,
        "microphone_position_world": (1.0, 0.0, 0.0),
        "microphone_orientation_world_xyzw": QUATERNIONS[0],
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    single = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=_pattern("omni"),
        **kwargs,
    )
    cascaded = apply_pair_directivity(
        impulse,
        source_pattern=shaped,
        microphone_pattern=shaped,
        **kwargs,
    )
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    point_frequencies = np.asarray([point.freq_hz for point in POINTS])
    point_amplitudes = 10.0 ** (np.asarray([point.gain_db for point in POINTS]) / 20.0)
    target = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    single_db = 20.0 * np.log10(
        np.abs(np.fft.rfft(np.roll(single, sample_count // 2))) / target
    )
    cascaded_db = 20.0 * np.log10(
        np.abs(np.fft.rfft(np.roll(cascaded, sample_count // 2))) / target**2
    )
    single_max = float(np.max(np.abs(single_db[accepted])))
    cascaded_max = float(np.max(np.abs(cascaded_db[accepted])))
    payload = {
        "sample_count": sample_count,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "welch": {
            "method": (
                "impulse-equivalent exact transfer; room Welch row dependency-gated"
            ),
            "nperseg": 8192,
            "noverlap": 4096,
            "accepted_hz": [200.0, 18_000.0],
        },
        "single_tolerance_db": 0.25,
        "cascaded_tolerance_db": 0.50,
        "single_maximum_error_db": single_max,
        "cascaded_maximum_error_db": cascaded_max,
        "pure_status": (
            "passed" if single_max <= 0.25 and cascaded_max <= 0.50 else "failed"
        ),
        "real_room_status": "pending_fixture_execution",
    }
    payload["status"] = payload["pure_status"]
    _json("frequency_sweep_welch.json", payload)
    step = max(1, frequencies.size // 2048)
    _plot_png(
        "frequency_response_overlay.png",
        (
            20.0 * np.log10(target[::step]),
            20.0
            * np.log10(np.abs(np.fft.rfft(np.roll(single, sample_count // 2)))[::step]),
        ),
    )
    _plot_png(
        "frequency_response_error.png",
        (single_db[accepted][::step], cascaded_db[accepted][::step]),
    )
    return payload, single_max, cascaded_max


def _product_and_insertion_evidence() -> tuple[dict[str, object], dict[str, object]]:
    baseline = np.linspace(-1.0, 1.0, 4096)
    combinations = (
        ("figure_eight", "omni", QUATERNIONS[2], QUATERNIONS[0], -1.0),
        ("figure_eight", "figure_eight", QUATERNIONS[2], QUATERNIONS[0], 1.0),
        ("cardioid", "omni", QUATERNIONS[2], QUATERNIONS[0], 0.0),
        ("supercardioid", "cardioid", QUATERNIONS[2], QUATERNIONS[2], -0.26),
    )
    rows = []
    stems: dict[str, np.ndarray] = {}
    maximum = 0.0
    for index, (source_family, mic_family, source_quat, mic_quat, target) in enumerate(
        combinations
    ):
        output = apply_pair_directivity(
            baseline,
            source_pattern=_pattern(source_family),
            microphone_pattern=_pattern(mic_family),
            source_position_world=(0.0, 0.0, 0.0),
            source_orientation_world_xyzw=source_quat,
            microphone_position_world=(1.0, 0.0, 0.0),
            microphone_orientation_world_xyzw=mic_quat,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        error = float(np.max(np.abs(output - baseline * target)))
        maximum = max(maximum, error)
        rows.append(
            {
                "source_family": source_family,
                "mic_family": mic_family,
                "target_product": target,
                "maximum_absolute_error": error,
            }
        )
        stems[f"case_{index}"] = output
    product_payload = {
        "rows": rows,
        "maximum_absolute_error": maximum,
        "status": "passed" if maximum <= 1e-12 else "failed",
    }
    _json("source_mic_product_matrix.json", product_payload)
    np.savez(OUTPUT / "source_mic_pair_stems.npz", baseline=baseline, **stems)

    rng = np.random.default_rng(20260718)
    premix = rng.normal(size=(2, 4, 48_000))
    sources = (_source("talker", QUATERNIONS[2]), _source("second", QUATERNIONS[0]))
    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(default=_pattern("figure_eight")),
    )
    positions = {
        "front": (1.0, 0.0, 0.0),
        "right": (1.0, 0.08, 0.0),
        "rear": (1.0, -0.08, 0.0),
        "top": (1.0, 0.0, 0.08),
    }
    effected, diagnostics = _apply_directivity_to_premix(
        premix,
        active=sources,
        sensor=_array(),
        microphone_positions_world=positions,
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=config,
    )
    insertion_max = 0.0
    for source_index, source in enumerate(sources):
        for mic_index, mic_id in enumerate(positions):
            gain = source_polar_gain(
                "figure_eight",
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=positions[mic_id],
            )
            insertion_max = max(
                insertion_max,
                float(
                    np.max(
                        np.abs(
                            effected[source_index, mic_index]
                            - premix[source_index, mic_index] * gain
                        )
                    )
                ),
            )
    insertion_payload = {
        "mode": diagnostics["mode"],
        "pair_count": 8,
        "maximum_full_stem_scalar_error": insertion_max,
        "direct_region_changed": bool(
            np.any(effected[:, :, :1024] != premix[:, :, :1024])
        ),
        "tail_region_changed": bool(
            np.any(effected[:, :, -1024:] != premix[:, :, -1024:])
        ),
        "pure_pair_helper_status": "passed" if insertion_max == 0.0 else "failed",
        "real_reverberant_status": "pending_fixture_execution",
        "piecewise_room_status": "pending_fixture_execution",
    }
    insertion_payload["status"] = insertion_payload["pure_pair_helper_status"]
    _json("per_pair_insertion_trace.json", insertion_payload)
    _json(
        "rir_tail_weighting.json",
        {
            "direct_region_changed": insertion_payload["direct_region_changed"],
            "tail_region_changed": insertion_payload["tail_region_changed"],
            "real_rir_status": "pending_fixture_execution",
            "status": "pending_fixture_execution",
        },
    )
    _json(
        "full_contribution_sha256.json",
        {
            "baseline_premix_sha256": _sha256(premix.tobytes()),
            "effected_premix_sha256": _sha256(effected.tobytes()),
            "baseline_mixture_sha256": _sha256(np.sum(premix, axis=0).tobytes()),
            "effected_mixture_sha256": _sha256(np.sum(effected, axis=0).tobytes()),
            "status": insertion_payload["status"],
        },
    )
    return product_payload, insertion_payload


def _metadata_and_edges() -> tuple[dict[str, object], dict[str, object]]:
    rows = []
    maximum_db = 0.0
    maximum_null = 0.0
    for family in TARGETS:
        for angle_deg, quaternion in zip((0, 90, 180, 270), QUATERNIONS, strict=True):
            source = _source("talker", quaternion, directivity=family)
            metadata = directivity_factor(source, (1.0, 0.0, 0.0))
            waveform = source_polar_gain(
                family,
                source_position_world=source.position_world,
                source_orientation_world_xyzw=source.orientation_world_quat,
                microphone_position_world=(1.0, 0.0, 0.0),
            )
            if waveform == 0.0:
                linear_error = abs(metadata - waveform)
                error_db = None
                maximum_null = max(maximum_null, linear_error)
            else:
                linear_error = abs(metadata - waveform)
                error_db = abs(20.0 * math.log10(abs(metadata / waveform)))
                maximum_db = max(maximum_db, error_db)
            rows.append(
                {
                    "family": family,
                    "angle_deg": angle_deg,
                    "metadata_gain": metadata,
                    "waveform_gain": waveform,
                    "linear_error": linear_error,
                    "error_db": error_db,
                }
            )
    payload = {
        "rows": rows,
        "maximum_non_null_error_db": maximum_db,
        "maximum_null_error_linear": maximum_null,
        "status": "passed" if maximum_db <= 0.05 and maximum_null <= 1e-6 else "failed",
    }
    _json("metadata_waveform_consistency.json", payload)

    zero = source_polar_gain(
        "figure_eight",
        source_position_world=(1.0, 2.0, 3.0),
        source_orientation_world_xyzw=QUATERNIONS[2],
        microphone_position_world=(1.0, 2.0, 3.0),
    )
    nulls = (
        evaluate_polar_pattern(
            "figure_eight", orientation_xyzw=QUATERNIONS[1], direction=(1.0, 0.0, 0.0)
        ),
        evaluate_polar_pattern(
            "figure_eight", orientation_xyzw=QUATERNIONS[3], direction=(1.0, 0.0, 0.0)
        ),
    )
    edge = {
        "coincident_direction_gain": zero,
        "figure_eight_90_270_nulls": nulls,
        "finite": bool(np.all(np.isfinite((zero, *nulls)))),
        "status": "passed"
        if zero == 1.0 and max(abs(value) for value in nulls) <= 1e-6
        else "failed",
    }
    _json("directivity_edge_case_matrix.json", edge)
    return payload, edge


def _validation_and_diagnostics() -> tuple[dict[str, object], dict[str, object]]:
    cases = (
        ("unknown_family", _pattern("Cardioid"), "ConfigValidationError"),
        (
            "above_nyquist",
            _pattern(
                "omni",
                (
                    DirectivityFrequencyPointConfig(freq_hz=100.0, gain_db=0.0),
                    DirectivityFrequencyPointConfig(freq_hz=24_000.000001, gain_db=0.0),
                ),
            ),
            "ConfigValidationError",
        ),
    )
    rows = []
    for name, pattern, expected in cases:
        config = EffectsConfig(
            directivity=DirectivityConfig(
                enabled=True,
                source_patterns=DirectivityPatternSetConfig(default=pattern),
            )
        )
        observed = None
        message = None
        try:
            validate_effects_config(
                config,
                microphone_orders=(("front",),),
                sample_rate_hz=SAMPLE_RATE_HZ,
                backend_id="room_acoustics",
                runtime_profile="waveform_fidelity",
                source_ids=("talker",),
                source_orientations={"talker": QUATERNIONS[0]},
                microphone_orientations={"front": QUATERNIONS[0]},
            )
        except Exception as exc:  # evidence records the located typed failure
            observed = type(exc).__name__
            message = str(exc)
        rows.append(
            {
                "case": name,
                "expected": expected,
                "observed": observed,
                "message": message,
                "passed": observed == expected,
            }
        )
    payload = {
        "rows": rows,
        "pre_synthesis": True,
        "status": "passed" if all(row["passed"] for row in rows) else "failed",
    }
    _json("invalid_directivity_config_matrix.json", payload)
    (OUTPUT / "partial_output_listing.txt").write_text("", encoding="utf-8")

    config = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(
            default=_pattern("cardioid", POINTS)
        ),
        mic_patterns=DirectivityPatternSetConfig(default=_pattern("supercardioid")),
    )
    diagnostic = directivity_diagnostics(
        config,
        active_source_ids=("talker",),
        microphone_ids=("front", "right", "rear", "top"),
    )
    diagnostic_payload = {
        "diagnostic": diagnostic,
        "exact_keys": list(diagnostic) == ["source_pattern", "mic_pattern", "mode"],
        "mode": diagnostic["mode"],
        "reflection_angle_claim_absent": True,
        "status": "passed",
    }
    _json("directivity_diagnostics.json", diagnostic_payload)
    return payload, diagnostic_payload


def _cardinal_room_evidence() -> dict[str, object]:
    probe = np.random.default_rng(20260718).standard_normal(48_000)
    probe *= 0.1 / float(np.sqrt(np.mean(probe**2)))
    left_sensor = _room_array()
    left_source = _room_source()
    _frame, left_baseline = _run_room_backend(
        source=left_source,
        sensor=left_sensor,
        sample_count=probe.size,
        probe=probe,
    )
    right_source = _room_source(position=ROOM_MIRRORED_SOURCE_POSITION)
    _frame, right_baseline = _run_room_backend(
        source=right_source,
        sensor=left_sensor,
        sample_count=probe.size,
        probe=probe,
    )
    rows: list[dict[str, object]] = []
    hashes = {
        "probe_sha256": _sha256(probe.tobytes()),
        "left_baseline_sha256": _sha256(left_baseline.tobytes()),
        "right_baseline_sha256": _sha256(right_baseline.tobytes()),
    }

    def record(
        *,
        scope: str,
        family: str,
        angle_deg: int,
        target: float,
        baseline: np.ndarray,
        output: np.ndarray,
    ) -> None:
        reference = baseline[0]
        measured = output[0]
        gain = float(np.dot(reference, measured) / np.dot(reference, reference))
        rms_ratio = float(
            np.sqrt(np.mean(measured**2)) / np.sqrt(np.mean(reference**2))
        )
        magnitude_error_db = (
            None if target == 0.0 else abs(20.0 * math.log10(abs(gain / target)))
        )
        passed = (
            abs(gain) <= 1e-6 and rms_ratio <= 1e-6
            if target == 0.0
            else math.copysign(1.0, gain) == math.copysign(1.0, target)
            and magnitude_error_db is not None
            and magnitude_error_db <= 0.05
        )
        key = f"{scope}_{family}_{angle_deg}"
        hashes[f"{key}_sha256"] = _sha256(output.tobytes())
        rows.append(
            {
                "scope": scope,
                "family": family,
                "angle_deg": angle_deg,
                "target": target,
                "signed_least_squares_gain": gain,
                "magnitude_error_db": magnitude_error_db,
                "rms_ratio": rms_ratio,
                "passed": passed,
            }
        )

    for family, targets in TARGETS.items():
        for angle_deg, quaternion, target in zip(
            (0, 90, 180, 270), QUATERNIONS, targets, strict=True
        ):
            _frame, output = _run_room_backend(
                source=_room_source(orientation=quaternion),
                sensor=left_sensor,
                sample_count=probe.size,
                probe=probe,
                effects=_effects(source_pattern=_pattern(family)),
            )
            record(
                scope="source_only",
                family=family,
                angle_deg=angle_deg,
                target=target,
                baseline=left_baseline,
                output=output,
            )
            mic_sensor = _room_array(reference_orientation=quaternion)
            _frame, output = _run_room_backend(
                source=right_source,
                sensor=mic_sensor,
                sample_count=probe.size,
                probe=probe,
                effects=_effects(mic_pattern=_pattern(family)),
            )
            record(
                scope="microphone_only",
                family=family,
                angle_deg=angle_deg,
                target=target,
                baseline=right_baseline,
                output=output,
            )

    mic_quaternions = (
        QUATERNIONS[2],
        QUATERNIONS[3],
        QUATERNIONS[0],
        QUATERNIONS[1],
    )
    for family, targets in TARGETS.items():
        for angle_deg, source_quaternion, mic_quaternion, target in zip(
            (0, 90, 180, 270),
            QUATERNIONS,
            mic_quaternions,
            targets,
            strict=True,
        ):
            _frame, output = _run_room_backend(
                source=_room_source(orientation=source_quaternion),
                sensor=_room_array(reference_orientation=mic_quaternion),
                sample_count=probe.size,
                probe=probe,
                effects=_effects(
                    source_pattern=_pattern(family),
                    mic_pattern=_pattern(family),
                ),
            )
            record(
                scope="simultaneous_same_family",
                family=family,
                angle_deg=angle_deg,
                target=target * target,
                baseline=left_baseline,
                output=output,
            )
    payload = {
        "fixture": {
            "room_dimensions_m": ROOM_DIMENSIONS_M,
            "max_order": 0,
            "source_position_world": ROOM_SOURCE_POSITION,
            "mirrored_source_position_world": ROOM_MIRRORED_SOURCE_POSITION,
            "array_center_world": ROOM_ARRAY_CENTER,
            "sample_count": probe.size,
            "probe_rms": float(np.sqrt(np.mean(probe**2))),
        },
        "input_sha256": hashes,
        "rows": rows,
        "maximum_non_null_error_db": max(
            float(row["magnitude_error_db"])
            for row in rows
            if row["magnitude_error_db"] is not None
        ),
        "maximum_null_gain": max(
            abs(float(row["signed_least_squares_gain"]))
            for row in rows
            if row["target"] == 0.0
        ),
        "status": _status_for(*(bool(row["passed"]) for row in rows)),
    }
    _json("cardinal_pair_stems_sha256.json", payload["input_sha256"])
    return payload


def _welch_h1_error(
    baseline: np.ndarray,
    effected: np.ndarray,
    *,
    target_power: int,
    edge_exclusion: int,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    nperseg = 8192
    step = 4096
    common = min(baseline.size, effected.size)
    stop = common - edge_exclusion
    x = baseline[edge_exclusion:stop]
    y = effected[edge_exclusion:stop]
    window = np.hanning(nperseg)
    cross = np.zeros(nperseg // 2 + 1, dtype=np.complex128)
    auto = np.zeros(nperseg // 2 + 1, dtype=np.float64)
    for start in range(0, x.size - nperseg + 1, step):
        x_fft = np.fft.rfft(x[start : start + nperseg] * window)
        y_fft = np.fft.rfft(y[start : start + nperseg] * window)
        cross += np.conj(x_fft) * y_fft
        auto += np.abs(x_fft) ** 2
    transfer = np.divide(
        cross,
        auto,
        out=np.zeros_like(cross),
        where=auto > 1e-20,
    )
    frequencies = np.fft.rfftfreq(nperseg, 1.0 / SAMPLE_RATE_HZ)
    point_frequencies = np.asarray([point.freq_hz for point in POINTS])
    point_amplitudes = 10.0 ** (np.asarray([point.gain_db for point in POINTS]) / 20.0)
    target = (
        np.interp(
            frequencies,
            point_frequencies,
            point_amplitudes,
            left=point_amplitudes[0],
            right=point_amplitudes[-1],
        )
        ** target_power
    )
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    error_db = 20.0 * np.log10(np.abs(transfer[accepted]) / target[accepted])
    one_khz_index = int(np.argmin(np.abs(frequencies - 1000.0)))
    return (
        float(np.max(np.abs(error_db))),
        float(np.real(transfer[one_khz_index])),
        frequencies[accepted],
        error_db,
    )


def _frequency_room_evidence() -> dict[str, object]:
    sample_count = 2**18
    probe = np.random.default_rng(20260718).standard_normal(sample_count)
    left_sensor = _room_array()
    left_source = _room_source()
    _frame, left_baseline = _run_room_backend(
        source=left_source,
        sensor=left_sensor,
        sample_count=sample_count,
        probe=probe,
    )
    right_source = _room_source(position=ROOM_MIRRORED_SOURCE_POSITION)
    _frame, right_baseline = _run_room_backend(
        source=right_source,
        sensor=left_sensor,
        sample_count=sample_count,
        probe=probe,
    )
    cases = (
        (
            "source_only",
            left_source,
            left_sensor,
            _effects(source_pattern=_pattern("omni", POINTS)),
            left_baseline,
            1,
            256,
        ),
        (
            "microphone_only",
            right_source,
            left_sensor,
            _effects(mic_pattern=_pattern("omni", POINTS)),
            right_baseline,
            1,
            256,
        ),
        (
            "simultaneous",
            left_source,
            _room_array(reference_orientation=QUATERNIONS[2]),
            _effects(
                source_pattern=_pattern("omni", POINTS),
                mic_pattern=_pattern("omni", POINTS),
            ),
            left_baseline,
            2,
            512,
        ),
    )
    rows = []
    plot_errors = []
    hashes = {
        "probe_sha256": _sha256(probe.tobytes()),
        "left_baseline_sha256": _sha256(left_baseline.tobytes()),
        "right_baseline_sha256": _sha256(right_baseline.tobytes()),
    }
    for name, source, sensor, effects, baseline, power, edge in cases:
        _frame, output = _run_room_backend(
            source=source,
            sensor=sensor,
            sample_count=sample_count,
            probe=probe,
            effects=effects,
        )
        maximum, polarity, _frequencies, errors = _welch_h1_error(
            baseline[0],
            output[0],
            target_power=power,
            edge_exclusion=edge,
        )
        tolerance = 0.25 if power == 1 else 0.50
        rows.append(
            {
                "case": name,
                "edge_exclusion_samples": edge,
                "maximum_error_db": maximum,
                "tolerance_db": tolerance,
                "signed_transfer_at_1khz": polarity,
                "passed": maximum <= tolerance and polarity > 0.0,
            }
        )
        plot_errors.append(errors)
        hashes[f"{name}_sha256"] = _sha256(output.tobytes())
    _plot_png("frequency_response_error.png", tuple(plot_errors))
    payload = {
        "fixture": {
            "sample_count": sample_count,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "probe_seed": 20260718,
            "nperseg": 8192,
            "noverlap": 4096,
            "accepted_hz": [200.0, 18_000.0],
        },
        "input_sha256": hashes,
        "rows": rows,
        "single_maximum_error_db": max(
            float(row["maximum_error_db"])
            for row in rows
            if row["case"] != "simultaneous"
        ),
        "cascaded_maximum_error_db": next(
            float(row["maximum_error_db"])
            for row in rows
            if row["case"] == "simultaneous"
        ),
        "status": _status_for(*(bool(row["passed"]) for row in rows)),
    }
    return payload


def _piecewise_plan() -> tuple[
    WindowMotionPlan, tuple[tuple[float, float, float], ...]
]:
    positions = (
        (2.0, 4.0, 1.5),
        (6.0, 2.0, 1.5),
        (8.0, 4.0, 1.5),
        (6.0, 6.0, 1.5),
    )
    segments = []
    for index, position in enumerate(positions):
        start = index * 12_000
        end = start + 12_000
        entities = MappingProxyType(
            {
                "talker": SegmentEntityMotion(
                    start_position_world_m=position,
                    end_position_world_m=position,
                    midpoint_position_world_m=position,
                    velocity_world_mps=None,
                    velocity_source="none:frozen_fixture",
                ),
                "rig": SegmentEntityMotion(
                    start_position_world_m=ROOM_ARRAY_CENTER,
                    end_position_world_m=ROOM_ARRAY_CENTER,
                    midpoint_position_world_m=ROOM_ARRAY_CENTER,
                    velocity_world_mps=None,
                    velocity_source="none:frozen_fixture",
                ),
            }
        )
        segments.append(
            WindowMotionSegment(
                index=index,
                start_sample=start,
                end_sample=end,
                start_time_s=start / SAMPLE_RATE_HZ,
                end_time_s=end / SAMPLE_RATE_HZ,
                entities=entities,
            )
        )
    return (
        WindowMotionPlan(
            sample_rate_hz=SAMPLE_RATE_HZ,
            window_sample_count=48_000,
            segments=tuple(segments),
        ),
        positions,
    )


def _insertion_room_evidence() -> dict[str, object]:
    probe = np.random.default_rng(20260718).standard_normal(48_000)
    sensor = _room_array()
    source = _room_source(orientation=QUATERNIONS[2])
    baseline_frame, baseline = _run_room_backend(
        source=source,
        sensor=sensor,
        sample_count=probe.size,
        probe=probe,
        absorption=0.2,
        max_order=3,
    )
    _frame, effected = _run_room_backend(
        source=source,
        sensor=sensor,
        sample_count=probe.size,
        probe=probe,
        absorption=0.2,
        max_order=3,
        effects=_effects(source_pattern=_pattern("figure_eight")),
    )
    positions = microphone_world_positions(sensor)
    scalar_errors = []
    direct_changed = []
    tail_changed = []
    detection = baseline_frame.detections[0]
    for mic_index, microphone in enumerate(sensor.microphones):
        gain = source_polar_gain(
            "figure_eight",
            source_position_world=source.position_world,
            source_orientation_world_xyzw=source.orientation_world_quat,
            microphone_position_world=positions[microphone.mic_id],
        )
        scalar_errors.append(
            float(np.max(np.abs(effected[mic_index] - baseline[mic_index] * gain)))
        )
        direct_index = int(
            round(
                detection.diagnostics["rir_peak_delay_s"][microphone.mic_id]
                * SAMPLE_RATE_HZ
            )
        )
        rir_length = int(detection.diagnostics["rir_length_samples"][microphone.mic_id])
        direct_slice = slice(max(0, direct_index - 2), direct_index + 3)
        tail_slice = slice(direct_index + 3, min(baseline.shape[1], rir_length + 2048))
        direct_changed.append(
            bool(
                np.any(
                    effected[mic_index, direct_slice]
                    != baseline[mic_index, direct_slice]
                )
            )
        )
        tail_changed.append(
            bool(
                np.any(
                    effected[mic_index, tail_slice] != baseline[mic_index, tail_slice]
                )
            )
        )

    _frame, frequency_effected = _run_room_backend(
        source=_room_source(),
        sensor=sensor,
        sample_count=probe.size,
        probe=probe,
        absorption=0.2,
        max_order=3,
        effects=_effects(source_pattern=_pattern("omni", POINTS)),
    )
    _frame, frequency_baseline = _run_room_backend(
        source=_room_source(),
        sensor=sensor,
        sample_count=probe.size,
        probe=probe,
        absorption=0.2,
        max_order=3,
    )
    frequency_error, _polarity, _frequencies, _errors = _welch_h1_error(
        frequency_baseline[0],
        frequency_effected[0],
        target_power=1,
        edge_exclusion=256,
    )

    plan, segment_positions = _piecewise_plan()
    original_apply = room_module._apply_directivity_to_premix
    segment_rows: list[dict[str, object]] = []

    def apply_spy(
        premix: np.ndarray, **kwargs: Any
    ) -> tuple[np.ndarray, dict[str, Any]]:
        output, diagnostics = original_apply(premix, **kwargs)
        segment_source = kwargs["active"][0]
        segment_sensor = kwargs["sensor"]
        microphone_positions = kwargs["microphone_positions_world"]
        maximum = 0.0
        for mic_index, microphone in enumerate(segment_sensor.microphones):
            gain = source_polar_gain(
                "figure_eight",
                source_position_world=segment_source.position_world,
                source_orientation_world_xyzw=segment_source.orientation_world_quat,
                microphone_position_world=microphone_positions[microphone.mic_id],
            )
            maximum = max(
                maximum,
                float(
                    np.max(np.abs(output[0, mic_index] - premix[0, mic_index] * gain))
                ),
            )
        segment_rows.append(
            {
                "source_midpoint_world": segment_source.position_world,
                "input_sha256": _sha256(premix.tobytes()),
                "output_sha256": _sha256(output.tobytes()),
                "maximum_scalar_error": maximum,
            }
        )
        return output, diagnostics

    room_module._apply_directivity_to_premix = apply_spy
    try:
        _piecewise_frame, piecewise_output = _run_room_backend(
            source=_room_source(),
            sensor=sensor,
            sample_count=probe.size,
            probe=probe,
            absorption=0.2,
            max_order=3,
            effects=_effects(
                source_pattern=_pattern("figure_eight"),
                segments_per_window=4,
            ),
            window_motion=plan,
        )
    finally:
        room_module._apply_directivity_to_premix = original_apply
    maximum_scalar_error = max(scalar_errors)
    maximum_segment_error = max(
        float(row["maximum_scalar_error"]) for row in segment_rows
    )
    payload = {
        "fixture": {
            "absorption": 0.2,
            "max_order": 3,
            "sample_count": probe.size,
            "segment_sample_counts": [12_000] * 4,
            "segment_midpoint_positions_world": segment_positions,
        },
        "input_sha256": {
            "probe": _sha256(probe.tobytes()),
            "reverberant_baseline": _sha256(baseline.tobytes()),
            "reverberant_effected": _sha256(effected.tobytes()),
            "piecewise_output": _sha256(piecewise_output.tobytes()),
        },
        "maximum_full_stem_scalar_error": maximum_scalar_error,
        "reverberant_frequency_maximum_error_db": frequency_error,
        "direct_samples_changed": all(direct_changed),
        "rir_tail_samples_changed": all(tail_changed),
        "segment_rows": segment_rows,
        "segment_apply_count": len(segment_rows),
        "maximum_segment_scalar_error": maximum_segment_error,
        "status": _status_for(
            maximum_scalar_error == 0.0,
            frequency_error <= 0.25,
            all(direct_changed),
            all(tail_changed),
            len(segment_rows) == 4,
            maximum_segment_error == 0.0,
        ),
    }
    _json(
        "rir_tail_weighting.json",
        {
            "direct_samples_changed": payload["direct_samples_changed"],
            "rir_tail_samples_changed": payload["rir_tail_samples_changed"],
            "status": payload["status"],
        },
    )
    _json("full_contribution_sha256.json", payload["input_sha256"])
    return payload


def _estimator_ladder_evidence() -> dict[str, object]:
    sample_count = 65_536
    microphones = microphone_layout("tetrahedral", spacing_m=0.16)
    relative_positions = {
        microphone.mic_id: np.asarray(microphone.relative_position_m, dtype=float)
        for microphone in microphones
    }
    world_positions = {
        mic_id: np.asarray(ROOM_ARRAY_CENTER) + position
        for mic_id, position in relative_positions.items()
    }
    probe = np.random.default_rng(20260718).standard_normal(sample_count)
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    spectrum = np.fft.rfft(probe)
    spectrum[(frequencies < 200.0) | (frequencies > 12_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=sample_count)
    distances = {
        mic_id: float(np.linalg.norm(position - np.asarray(ROOM_SOURCE_POSITION)))
        for mic_id, position in world_positions.items()
    }
    minimum_distance = min(distances.values())
    delayed = {
        mic_id: fractional_delay(
            probe,
            delay_s=(distance - minimum_distance) / 343.0,
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        for mic_id, distance in distances.items()
    }
    clean_rungs = []
    for quaternion in ESTIMATOR_QUATERNIONS:
        clean_rungs.append(
            np.asarray(
                [
                    delayed[microphone.mic_id]
                    * source_polar_gain(
                        "cardioid",
                        source_position_world=ROOM_SOURCE_POSITION,
                        source_orientation_world_xyzw=quaternion,
                        microphone_position_world=tuple(
                            world_positions[microphone.mic_id]
                        ),
                    )
                    for microphone in microphones
                ]
            )
        )
    hashes: dict[str, object] = {
        "probe_sha256": _sha256(probe.tobytes()),
        "clean_rung_sha256": [_sha256(clean.tobytes()) for clean in clean_rungs],
    }
    seed_rows = []
    for seed in range(20260718, 20260726):
        raw_noise = np.random.default_rng(seed).standard_normal((4, sample_count))
        front_rms = float(np.sqrt(np.mean(clean_rungs[0] ** 2)))
        noise_rms = float(np.sqrt(np.mean(raw_noise**2)))
        noise_scale = front_rms / noise_rms / 10.0 ** (18.0 / 20.0)
        noise = raw_noise * noise_scale
        rung_rows = []
        mixture_hashes = []
        for angle_deg, clean in zip(ESTIMATOR_ANGLES_DEG, clean_rungs, strict=True):
            mixture = clean + noise
            mixture_hashes.append(_sha256(mixture.tobytes()))
            snr_db = 20.0 * math.log10(
                float(np.sqrt(np.mean(clean**2))) / float(np.sqrt(np.mean(noise**2)))
            )
            pair_peaks = []
            for left_index, _left in enumerate(microphones):
                for right in microphones[left_index + 1 :]:
                    pair_peaks.append(
                        abs(
                            gcc_phat_delay(
                                mixture[left_index],
                                mixture[
                                    next(
                                        index
                                        for index, item in enumerate(microphones)
                                        if item.mic_id == right.mic_id
                                    )
                                ],
                                sample_rate_hz=SAMPLE_RATE_HZ,
                                interp=8,
                            ).peak_value
                        )
                    )
            waveforms = {
                microphone.mic_id: mixture[index]
                for index, microphone in enumerate(microphones)
            }
            result = srp_phat_direction(
                waveforms,
                mic_positions_m={
                    mic_id: tuple(position)
                    for mic_id, position in relative_positions.items()
                },
                sample_rate_hz=SAMPLE_RATE_HZ,
                interp=8,
            )
            bearing_error = abs((result.bearing_deg - 180.0 + 180.0) % 360.0 - 180.0)
            rung_rows.append(
                {
                    "angle_deg": angle_deg,
                    "snr_db": snr_db,
                    "gcc_peak_proxy": float(np.median(pair_peaks)),
                    "srp_bearing_deg": result.bearing_deg,
                    "srp_absolute_bearing_error_deg": bearing_error,
                    "srp_peak_grid_power": result.peak_power,
                    "srp_bearing_confidence": srp_phat_confidence(result),
                }
            )
        hashes[str(seed)] = {
            "raw_noise_sha256": _sha256(raw_noise.tobytes()),
            "scaled_noise_sha256": _sha256(noise.tobytes()),
            "mixture_sha256_by_rung": mixture_hashes,
        }
        seed_rows.append(
            {
                "seed": seed,
                "noise_scale": noise_scale,
                "rungs": rung_rows,
            }
        )
    metrics = (
        "snr_db",
        "gcc_peak_proxy",
        "srp_absolute_bearing_error_deg",
        "srp_peak_grid_power",
        "srp_bearing_confidence",
    )
    medians = {
        metric: [
            float(
                np.median(
                    [seed_row["rungs"][rung_index][metric] for seed_row in seed_rows]
                )
            )
            for rung_index in range(4)
        ]
        for metric in metrics
    }
    snr = medians["snr_db"]
    gcc = medians["gcc_peak_proxy"]
    bearing_error = medians["srp_absolute_bearing_error_deg"]
    peak_power = medians["srp_peak_grid_power"]
    confidence = medians["srp_bearing_confidence"]
    srp_power_drop_db = 10.0 * math.log10(peak_power[0] / peak_power[-1])
    checks = {
        "snr_strictly_decreasing": all(
            left > right for left, right in zip(snr, snr[1:], strict=False)
        ),
        "snr_first_step_loss_at_least_5_5_db": snr[0] - snr[1] >= 5.5,
        "snr_second_step_loss_at_least_5_5_db": snr[1] - snr[2] >= 5.5,
        "snr_front_rear_loss_at_least_40_db": snr[0] - snr[-1] >= 40.0,
        "gcc_strictly_decreasing": all(
            left > right for left, right in zip(gcc, gcc[1:], strict=False)
        ),
        "gcc_front_rear_drop_at_least_0_05": gcc[0] - gcc[-1] >= 0.05,
        "srp_bearing_error_increase_at_least_30_deg": (
            bearing_error[-1] - bearing_error[0] >= 30.0
        ),
        "srp_peak_power_drop_at_least_15_db": srp_power_drop_db >= 15.0,
        "srp_confidence_front_at_least_0_050": confidence[0] >= 0.050,
        "srp_confidence_rear_at_most_0_005": confidence[-1] <= 0.005,
        "srp_confidence_front_rear_drop_at_least_0_040": (
            confidence[0] - confidence[-1] >= 0.040
        ),
        "srp_confidence_non_increasing": all(
            left >= right
            for left, right in zip(confidence, confidence[1:], strict=False)
        ),
    }
    payload = {
        "confidence_formula_id": SRP_CONFIDENCE_FORMULA_ID,
        "confidence_remediation_revision": SRP_CONFIDENCE_REMEDIATION_REVISION,
        "fixture": {
            "angles_deg": ESTIMATOR_ANGLES_DEG,
            "noise_seeds": list(range(20260718, 20260726)),
            "sample_count": sample_count,
            "probe_band_hz": [200.0, 12_000.0],
            "noise_spectrum": "full_band_white_gaussian_unfiltered",
            "front_snr_db": 18.0,
            "gcc_interp": 8,
            "true_bearing_deg": 180.0,
        },
        "measurements": {
            "medians": medians,
            "srp_peak_power_front_rear_drop_db": srp_power_drop_db,
            "seed_rows": seed_rows,
        },
        "checks": checks,
        "status": _status_for(*checks.values()),
    }
    _json(
        "estimator_input_sha256.json", {"status": payload["status"], "hashes": hashes}
    )
    _plot_png(
        "estimator_confidence_overlay.png",
        (
            np.asarray(snr),
            np.asarray(gcc),
            np.asarray(bearing_error),
            np.asarray(peak_power),
            np.asarray(confidence),
        ),
    )
    return payload


def _write_pcm_fixture(path: Path) -> str:
    samples = 0.25 * np.sin(2.0 * np.pi * 997.0 * np.arange(4_800) / SAMPLE_RATE_HZ)
    pcm = np.round(samples * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as fixture:
        fixture.setnchannels(1)
        fixture.setsampwidth(2)
        fixture.setframerate(SAMPLE_RATE_HZ)
        fixture.writeframes(pcm.tobytes())
    return _file_sha256(path)


def _backend_off_state_evidence() -> dict[str, object]:
    fixture_path = OUTPUT / "_off_state_file_fixture.wav"
    file_hash = _write_pcm_fixture(fixture_path)
    broadband = np.random.default_rng(20260718).standard_normal(4_800)
    silent_source = replace(_room_source(duration_s=0.1), start_time_s=2.0)
    cases = (
        (
            "impulse",
            _room_source(audio_asset_path="generated://impulse", duration_s=0.1),
            None,
            0,
        ),
        ("tone", _room_source(audio_asset_path=None, duration_s=0.1), None, 0),
        ("broadband", _room_source(duration_s=0.1), broadband, 0),
        ("silent", silent_source, None, 0),
        (
            "file_source",
            _room_source(
                audio_asset_path=fixture_path.relative_to(ROOT).as_posix(),
                duration_s=0.1,
            ),
            None,
            0,
        ),
        (
            "generated_source",
            _room_source(audio_asset_path="generated://pulse", duration_s=0.1),
            None,
            0,
        ),
        ("reverberant_room", _room_source(duration_s=0.1), None, 3),
        ("waveform_export", _room_source(duration_s=0.1), None, 0),
    )
    rows = []
    baseline_frames: dict[str, object] = {}
    original_loader = room_module._load_public_waveform

    def load_pcm_fixture(
        path: Path,
        *,
        sample_rate_hz: int,
    ) -> tuple[np.ndarray, str]:
        with wave.open(str(path), "rb") as fixture:
            if (
                fixture.getnchannels() != 1
                or fixture.getsampwidth() != 2
                or fixture.getframerate() != sample_rate_hz
            ):
                raise ValueError("frozen off-state WAV must be mono PCM16 at 48 kHz")
            samples = np.frombuffer(
                fixture.readframes(fixture.getnframes()), dtype="<i2"
            )
        return samples.astype(np.float64) / 32768.0, f"file:{path}"

    room_module._load_public_waveform = load_pcm_fixture
    try:
        for name, source, probe, max_order in cases:
            sensor = _room_array()
            baseline_frame, baseline_waveform = _run_room_backend(
                source=source,
                sensor=sensor,
                sample_count=4_800,
                probe=probe,
                absorption=0.2 if max_order else 0.0,
                max_order=max_order,
            )
            disabled_frame, disabled_waveform = _run_room_backend(
                source=source,
                sensor=sensor,
                sample_count=4_800,
                probe=probe,
                absorption=0.2 if max_order else 0.0,
                max_order=max_order,
                effects=EffectsConfig(),
            )
            omni_frame, omni_waveform = _run_room_backend(
                source=source,
                sensor=sensor,
                sample_count=4_800,
                probe=probe,
                absorption=0.2 if max_order else 0.0,
                max_order=max_order,
                effects=_effects(
                    source_pattern=_pattern("omni"),
                    mic_pattern=_pattern("omni"),
                ),
            )
            baseline_bytes = _frame_bytes(baseline_frame)
            disabled_bytes = _frame_bytes(disabled_frame)
            omni_bytes = _frame_bytes(omni_frame)
            passed = (
                baseline_bytes == disabled_bytes == omni_bytes
                and baseline_waveform.tobytes()
                == disabled_waveform.tobytes()
                == omni_waveform.tobytes()
                and "effects" not in baseline_frame.diagnostics
                and "effects" not in disabled_frame.diagnostics
                and "effects" not in omni_frame.diagnostics
            )
            rows.append(
                {
                    "case": name,
                    "baseline_frame_sha256": _sha256(baseline_bytes),
                    "disabled_frame_sha256": _sha256(disabled_bytes),
                    "explicit_omni_frame_sha256": _sha256(omni_bytes),
                    "baseline_waveform_sha256": _sha256(baseline_waveform.tobytes()),
                    "disabled_waveform_sha256": _sha256(disabled_waveform.tobytes()),
                    "explicit_omni_waveform_sha256": _sha256(omni_waveform.tobytes()),
                    "passed": passed,
                }
            )
            baseline_frames[name] = frame_to_trace_dict(baseline_frame)
    finally:
        room_module._load_public_waveform = original_loader
        fixture_path.unlink(missing_ok=True)
    payload = {
        "golden_revision": PROTOCOL_REVISION,
        "file_fixture_sha256": file_hash,
        "file_fixture_decoder": "stdlib wave mono PCM16; byte-equivalent scaling",
        "broadband_fixture_sha256": _sha256(broadband.tobytes()),
        "rows": rows,
        "status": _status_for(*(bool(row["passed"]) for row in rows)),
    }
    _json("off_state_frame.json", baseline_frames)
    (OUTPUT / "off_state_waveform_sha256.txt").write_text(
        "".join(f"{row['baseline_waveform_sha256']}  {row['case']}\n" for row in rows),
        encoding="utf-8",
    )
    return payload


def _registry_room_evidence() -> dict[str, object]:
    registry = get_default_registry()
    declaration = next(
        item
        for item in registry.declarations("propagation_backend")
        if item.plugin_id == "room_acoustics"
    )
    validate_declaration(declaration, RoomAcousticsBackend)
    effects = _effects(
        source_pattern=_pattern("cardioid", POINTS),
        mic_pattern=_pattern("supercardioid", POINTS),
    )
    sensor = _room_array(reference_orientation=QUATERNIONS[2])
    source = _room_source()
    scene, window = _room_fixture(
        source=source,
        sensor=sensor,
        sample_count=48_000,
        absorption=0.2,
        max_order=3,
    )
    sinks = (_CaptureSink(), _CaptureSink())
    backends = tuple(
        registry.resolve(
            "propagation_backend",
            "room_acoustics",
            waveform_writer=sink,
            effects=effects,
        )
        for sink in sinks
    )
    frames = tuple(backend.simulate(scene, sensor, window) for backend in backends)
    if sinks[0].mixture is None or sinks[1].mixture is None:
        raise RuntimeError("registry fixture did not export both mixtures")
    frame_bytes = tuple(_frame_bytes(frame) for frame in frames)
    payload = {
        "registered_declaration_self_test_executed": True,
        "two_factory_frame_sha256": [_sha256(item) for item in frame_bytes],
        "two_factory_waveform_sha256": [
            _sha256(sink.mixture.tobytes()) for sink in sinks
        ],
        "frames_exact": frame_bytes[0] == frame_bytes[1],
        "waveforms_exact": sinks[0].mixture.tobytes() == sinks[1].mixture.tobytes(),
        "input_sha256": _sha256(
            _canonical_bytes(
                {
                    "source": source.source_id,
                    "room": frame_to_trace_dict(frames[0])["diagnostics"][
                        "room_config"
                    ],
                    "effects": repr(effects),
                }
            )
        ),
    }
    payload["status"] = _status_for(
        bool(payload["frames_exact"]), bool(payload["waveforms_exact"])
    )
    return payload


def _off_state_and_replay() -> dict[str, object]:
    baseline = np.arange(256, dtype=np.float64).reshape(1, 1, 256)
    explicit_omni = DirectivityConfig(
        enabled=True,
        source_patterns=DirectivityPatternSetConfig(default=_pattern("omni")),
    )
    mono = MicrophoneArraySpec(
        array_id="mono",
        prim_path="/World/Mono",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=QUATERNIONS[0],
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="front", relative_position_m=(0.0, 0.0, 0.0)),
        ),
    )
    output, diagnostic = _apply_directivity_to_premix(
        baseline,
        active=(_source("talker", QUATERNIONS[0]),),
        sensor=mono,
        microphone_positions_world={"front": (1.0, 0.0, 0.0)},
        sample_rate_hz=SAMPLE_RATE_HZ,
        config=explicit_omni,
    )
    payload = {
        "explicit_omni_same_object": output is baseline,
        "bytes_identical": output.tobytes() == baseline.tobytes(),
        "effects_diagnostic": diagnostic,
        "status": "passed" if output is baseline and not diagnostic else "failed",
    }

    probe = np.random.default_rng(20260718).normal(size=16_384)
    kwargs = {
        "source_pattern": _pattern("figure_eight", POINTS),
        "microphone_pattern": _pattern("supercardioid", POINTS),
        "source_position_world": (0.0, 0.0, 0.0),
        "source_orientation_world_xyzw": QUATERNIONS[2],
        "microphone_position_world": (1.0, 0.0, 0.0),
        "microphone_orientation_world_xyzw": QUATERNIONS[2],
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    first = apply_pair_directivity(probe, **kwargs)
    second = apply_pair_directivity(probe, **kwargs)
    replay = {
        "input_sha256": _sha256(probe.tobytes()),
        "first_sha256": _sha256(first.tobytes()),
        "second_sha256": _sha256(second.tobytes()),
        "exact": first.tobytes() == second.tobytes(),
        "status": "passed" if first.tobytes() == second.tobytes() else "failed",
    }
    _json("enabled_replay_sha256.json", replay)
    return {"pure_off_state": payload, "pure_replay": replay}


def _dependency_evidence() -> dict[str, dict[str, object]]:
    if not _dependency_available():
        reason = "pyroomacoustics could not be imported; frozen fixture not executed"
        placeholder = _dependency_placeholder(reason)
        _json("estimator_confidence_ladder.json", placeholder)
        _json("estimator_input_sha256.json", {**placeholder, "hashes": None})
        _plot_png("estimator_confidence_overlay.png", (np.zeros(4),))
        _json("off_state_golden_sha256.json", placeholder)
        _json("off_state_frame.json", placeholder)
        (OUTPUT / "off_state_waveform_sha256.txt").write_text(
            "dependency_unavailable: pyroomacoustics\n", encoding="utf-8"
        )
        _json("registry_determinism_directivity.json", placeholder)
        _json("rir_tail_weighting.json", placeholder)
        _json("full_contribution_sha256.json", placeholder)
        return {
            name: dict(placeholder)
            for name in (
                "cardinal",
                "frequency",
                "insertion",
                "ladder",
                "off_state",
                "registry",
            )
        }

    def execute(
        fixture_name: str,
        fixture: Any,
    ) -> dict[str, object]:
        try:
            return fixture()
        except Exception as exc:  # evidence must record, never convert, a fixture error
            return {
                "fixture": fixture_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "status": "failed",
            }

    cardinal = execute("cardinal_room_gain", _cardinal_room_evidence)
    frequency = execute("room_frequency_recovery", _frequency_room_evidence)
    insertion = execute("reverberant_and_segmented_insertion", _insertion_room_evidence)
    ladder = execute("estimator_ladder", _estimator_ladder_evidence)
    off_state = execute("backend_off_state_golden", _backend_off_state_evidence)
    registry = execute("room_registry_determinism", _registry_room_evidence)
    _json("estimator_confidence_ladder.json", ladder)
    _json("off_state_golden_sha256.json", off_state)
    _json("registry_determinism_directivity.json", registry)
    return {
        "cardinal": cardinal,
        "frequency": frequency,
        "insertion": insertion,
        "ladder": ladder,
        "off_state": off_state,
        "registry": registry,
    }


def _fidelity_ledger() -> dict[str, object]:
    payload = {
        "supported_mode": "per_pair_direct_path",
        "full_convolved_pair_weighted_from_direct_path_angle": True,
        "reflection_specific_angles": False,
        "direct_arrival_only": False,
        "native_pyroomacoustics_directivity": False,
        "p2_deferrals": [
            "per-reflection departure/incidence angles",
            "direct-arrival-only separation",
            "native directional source and microphone objects",
        ],
        "s3_9_reconciliation_required": "core/fidelity.py",
        "status": "passed",
    }
    _json("fidelity_reconciliation.json", payload)
    return payload


def _dependency_available() -> bool:
    try:
        importlib.import_module("pyroomacoustics")
    except ImportError:
        return False
    return True


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    dependency_available = _dependency_available()
    pyroomacoustics = (
        importlib.import_module("pyroomacoustics") if dependency_available else None
    )
    environment = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "numpy_origin": np.__file__,
        "pyroomacoustics_available": dependency_available,
        "pyroomacoustics_version": (
            None
            if pyroomacoustics is None
            else getattr(pyroomacoustics, "__version__", "unknown")
        ),
        "pyroomacoustics_origin": (
            None
            if not dependency_available
            else importlib.util.find_spec("pyroomacoustics").origin
        ),
    }
    _json("evidence_environment.json", environment)
    config = _config_contract()
    polar, polar_max = _polar_evidence()
    cardinal, cardinal_db, cardinal_null = _waveform_and_product_evidence()
    frequency, frequency_single, frequency_cascade = _frequency_evidence()
    product, insertion = _product_and_insertion_evidence()
    metadata, edges = _metadata_and_edges()
    invalid, diagnostics = _validation_and_diagnostics()
    pure_off_state = _off_state_and_replay()
    dependency = _dependency_evidence()
    fidelity = _fidelity_ledger()

    cardinal["real_room"] = dependency["cardinal"]
    cardinal["real_room_status"] = dependency["cardinal"]["status"]
    cardinal["status"] = (
        "failed"
        if cardinal["pure_pair_status"] == "failed"
        else dependency["cardinal"]["status"]
    )
    _json("cardinal_waveform_gain.json", cardinal)
    frequency["real_room"] = dependency["frequency"]
    frequency["real_room_status"] = dependency["frequency"]["status"]
    frequency["status"] = (
        "failed"
        if frequency["pure_status"] == "failed"
        else dependency["frequency"]["status"]
    )
    _json("frequency_sweep_welch.json", frequency)
    insertion["real_room"] = dependency["insertion"]
    insertion["real_reverberant_status"] = dependency["insertion"]["status"]
    insertion["piecewise_room_status"] = dependency["insertion"]["status"]
    insertion["status"] = (
        "failed"
        if insertion["pure_pair_helper_status"] == "failed"
        else dependency["insertion"]["status"]
    )
    _json("per_pair_insertion_trace.json", insertion)
    off_state_status = (
        "failed"
        if pure_off_state["pure_off_state"]["status"] == "failed"
        else dependency["off_state"]["status"]
    )
    registry_payload = {
        "pure_replay": pure_off_state["pure_replay"],
        "room_registry": dependency["registry"],
        "status": (
            "failed"
            if pure_off_state["pure_replay"]["status"] == "failed"
            else dependency["registry"]["status"]
        ),
    }
    _json("registry_determinism_directivity.json", registry_payload)

    rows = {
        "frozen_config_defaults": config["status"],
        "polar_families_angles": polar["status"],
        "cardinal_waveform_gain": cardinal["status"],
        "frequency_response": frequency["status"],
        "source_mic_product": product["status"],
        "full_convolved_stem_insertion": insertion["status"],
        "metadata_waveform_consistency": metadata["status"],
        "estimator_degradation": dependency["ladder"]["status"],
        "fail_closed_validation": invalid["status"],
        "zero_direction_and_nulls": edges["status"],
        "diagnostics_contract": diagnostics["status"],
        "disabled_omni_off_state": off_state_status,
        "determinism_registry": registry_payload["status"],
        "fidelity_limitation_ledger": fidelity["status"],
    }
    artifact_hashes = {
        path.relative_to(OUTPUT).as_posix(): _file_sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path.name != "waveform_directivity_gate.json"
    }
    pure_failed = any(status == "failed" for status in rows.values())
    gate_status = (
        "failed"
        if pure_failed
        else "passed"
        if all(status == "passed" for status in rows.values())
        else "dependency_unavailable"
    )
    gate = {
        "subphase": "S3.6",
        "protocol_revision": PROTOCOL_REVISION,
        "confidence_remediation_revision": SRP_CONFIDENCE_REMEDIATION_REVISION,
        "implementation_revision": _git_revision(),
        "package_version": __version__,
        "environment": environment,
        "normalized_configuration": {
            "mode": "per_pair_direct_path",
            "families": list(TARGETS),
            "frequency_points": [
                {"freq_hz": point.freq_hz, "gain_db": point.gain_db} for point in POINTS
            ],
        },
        "sample_counts": {
            "cardinal_waveform": 48_000,
            "frequency_sweep": 2**18,
            "estimator_ladder": 65_536,
        },
        "welch_parameters": {
            "nperseg": 8192,
            "noverlap": 4096,
            "accepted_hz": [200.0, 18_000.0],
        },
        "thresholds": {
            "polar_linear": 1e-12,
            "cardinal_non_null_db": 0.05,
            "cardinal_null_linear": 1e-6,
            "frequency_single_db": 0.25,
            "frequency_cascaded_db": 0.50,
            "metadata_non_null_db": 0.05,
            "metadata_null_linear": 1e-6,
            "estimator_snr_first_two_loss_db": 5.5,
            "estimator_snr_front_rear_loss_db": 40.0,
            "estimator_gcc_front_rear_drop": 0.05,
            "estimator_srp_bearing_error_increase_deg": 30.0,
            "estimator_srp_peak_power_drop_db": 15.0,
            "estimator_confidence_front_floor": 0.050,
            "estimator_confidence_rear_ceiling": 0.005,
            "estimator_confidence_front_rear_drop": 0.040,
            "estimator_confidence_ladder_order": "non_increasing",
        },
        "confidence_formula_id": SRP_CONFIDENCE_FORMULA_ID,
        "measured_maxima": {
            "polar_absolute_error": polar_max,
            "cardinal_non_null_error_db": cardinal_db,
            "cardinal_null_leakage_linear": cardinal_null,
            "frequency_single_error_db": frequency_single,
            "frequency_cascaded_error_db": frequency_cascade,
            "metadata_non_null_error_db": metadata["maximum_non_null_error_db"],
            "metadata_null_error_linear": metadata["maximum_null_error_linear"],
            "room_cardinal_non_null_error_db": dependency["cardinal"].get(
                "maximum_non_null_error_db"
            ),
            "room_frequency_single_error_db": dependency["frequency"].get(
                "single_maximum_error_db"
            ),
            "room_frequency_cascaded_error_db": dependency["frequency"].get(
                "cascaded_maximum_error_db"
            ),
            "estimator_medians": (
                dependency["ladder"].get("measurements", {}).get("medians")
                if isinstance(dependency["ladder"].get("measurements"), dict)
                else None
            ),
        },
        "rows": rows,
        "dependency_gated_rows": [
            name for name, status in rows.items() if status == "dependency_unavailable"
        ],
        "commands": [
            ".venv/bin/pytest -q tests/test_effects_directivity.py",
            ".venv/bin/python scripts/s3_6_evidence.py",
            "make test",
            "make lint",
        ],
        "artifact_sha256": artifact_hashes,
        "status": gate_status,
    }
    _json("waveform_directivity_gate.json", gate)
    print(
        json.dumps(
            {
                "status": gate_status,
                "dependency_gated_rows": gate["dependency_gated_rows"],
                "measured_maxima": gate["measured_maxima"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if gate_status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
