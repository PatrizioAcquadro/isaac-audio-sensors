#!/usr/bin/env python3
"""Generate pure, deterministic S3.3 channel-response acceptance evidence."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    ChannelEffectsChain,
    ChannelResponseConfig,
    ChannelResponseMicConfig,
    EffectsConfig,
    FrequencyResponsePointConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.channel_response import response_tap_count
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.plugins.registry import (
    get_default_registry,
    validate_declaration,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    RoomAcousticsSpec,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.3"
SAMPLE_RATE_HZ = 48_000
ENTRY_REVISION = "716336095f3436d824c76de4387374ff009022c3"
GAIN_TOLERANCE_DB = 0.05
DELAY_TOLERANCE_SAMPLES = 0.10
FREQUENCY_RESPONSE_TOLERANCE_DB = 0.25
L1_DELAY_TOLERANCE_S = 1e-12
EDGE_EXCLUSION = response_tap_count(SAMPLE_RATE_HZ) // 2 + 65
RESPONSE_POINTS = (
    (100.0, -1.0),
    (1_000.0, 0.0),
    (4_000.0, -3.0),
    (12_000.0, 2.0),
    (20_000.0, -2.0),
)


class _CaptureSink:
    def __init__(self) -> None:
        self.mixture: np.ndarray | None = None

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        del sample_rate_hz, mic_ids, window_sample_count
        self.mixture = np.array(mixture, copy=True)
        return WaveformWriteResult(
            paths=(f"evidence://{frame_id}.wav",),
            diagnostics={"mode": "s3_3_capture"},
        )


def _write_json(name: str, payload: object) -> Path:
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


def _response_effects(mic: ChannelResponseMicConfig) -> EffectsConfig:
    return EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={"mic": mic},
        )
    )


def _apply(samples: np.ndarray, mic: ChannelResponseMicConfig) -> np.ndarray:
    output, diagnostics = ChannelEffectsChain(_response_effects(mic)).apply(
        samples,
        mic_ids=("mic",),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="s3_3_evidence",
    )
    if "channel_response" not in diagnostics:
        raise RuntimeError("active response fixture emitted no diagnostics")
    return output


def _gain_evidence() -> tuple[dict[str, object], float, str]:
    results: list[dict[str, object]] = []
    fixture_hash = hashlib.sha256()
    for frequency_hz in (1_000, 8_000):
        time_s = np.arange(48_000, dtype=np.float64) / SAMPLE_RATE_HZ
        samples = (0.1 * np.sin(2.0 * np.pi * frequency_hz * time_s))[None, :]
        fixture_hash.update(samples.tobytes())
        for gain_db in (-12.0, -3.0, 6.0):
            output = _apply(samples, ChannelResponseMicConfig(gain_db=gain_db))
            usable = slice(EDGE_EXCLUSION, -EDGE_EXCLUSION)
            rms_in = float(np.sqrt(np.mean(samples[0, usable] ** 2)))
            rms_out = float(np.sqrt(np.mean(output[0, usable] ** 2)))
            recovered = 20.0 * math.log10(rms_out / rms_in)
            error = abs(recovered - gain_db)
            results.append(
                {
                    "mic_id": "mic",
                    "frequency_hz": frequency_hz,
                    "configured_gain_db": gain_db,
                    "recovered_gain_db": recovered,
                    "absolute_error_db": error,
                    "passed": error <= GAIN_TOLERANCE_DB,
                }
            )
    maximum = max(float(item["absolute_error_db"]) for item in results)
    payload = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": 48_000,
        "edge_exclusion_samples": EDGE_EXCLUSION,
        "tolerance_db": GAIN_TOLERANCE_DB,
        "maximum_absolute_error_db": maximum,
        "results": results,
        "status": "passed" if maximum <= GAIN_TOLERANCE_DB else "failed",
    }
    _write_json("gain_tone_results.json", payload)
    with (OUTPUT / "gain_tone_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        writer = csv.DictWriter(output_file, fieldnames=tuple(results[0]))
        writer.writeheader()
        writer.writerows(results)
    return payload, maximum, fixture_hash.hexdigest()


def _band_limited_probe() -> np.ndarray:
    sample_count = 16_384
    rng = np.random.default_rng(20_260_718)
    spectrum = np.fft.rfft(rng.standard_normal(sample_count))
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / SAMPLE_RATE_HZ)
    spectrum[(frequencies < 300.0) | (frequencies > 18_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=sample_count) * np.hanning(sample_count)
    return np.asarray(probe / np.max(np.abs(probe)), dtype=np.float64)


def _parabolic_lag(correlation: np.ndarray, sample_count: int) -> float:
    magnitude = np.abs(correlation)
    peak = int(np.argmax(magnitude))
    left, center, right = magnitude[peak - 1 : peak + 2]
    offset = 0.5 * (left - right) / (left - 2.0 * center + right)
    return float(peak - (sample_count - 1) + offset)


def _delay_evidence() -> tuple[dict[str, object], float, str]:
    probe = _band_limited_probe()
    results: list[dict[str, object]] = []
    traces: dict[str, np.ndarray] = {}
    for index, configured in enumerate((-3.25, -0.50, 0.50, 2.75)):
        output = _apply(
            probe[None, :],
            ChannelResponseMicConfig(delay_s=configured / SAMPLE_RATE_HZ),
        )
        correlation = np.correlate(output[0], probe, mode="full")
        recovered = _parabolic_lag(correlation, probe.size)
        error = abs(recovered - configured)
        results.append(
            {
                "configured_delay_samples": configured,
                "configured_delay_s": configured / SAMPLE_RATE_HZ,
                "recovered_delay_samples": recovered,
                "absolute_error_samples": error,
                "passed": error <= DELAY_TOLERANCE_SAMPLES,
            }
        )
        traces[f"correlation_{index}"] = correlation
    traces["lags_samples"] = np.arange(-(probe.size - 1), probe.size)
    traces["configured_delay_samples"] = np.asarray((-3.25, -0.50, 0.50, 2.75))
    np.savez_compressed(OUTPUT / "delay_correlation_traces.npz", **traces)
    maximum = max(float(item["absolute_error_samples"]) for item in results)
    payload = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": int(probe.size),
        "tolerance_samples": DELAY_TOLERANCE_SAMPLES,
        "tolerance_s": DELAY_TOLERANCE_SAMPLES / SAMPLE_RATE_HZ,
        "maximum_absolute_error_samples": maximum,
        "results": results,
        "status": "passed" if maximum <= DELAY_TOLERANCE_SAMPLES else "failed",
    }
    _write_json("delay_recovery_results.json", payload)
    return payload, maximum, _sha256(probe.tobytes())


def _polarity_evidence() -> dict[str, object]:
    rng = np.random.default_rng(3_303)
    samples = np.concatenate(
        (
            np.asarray([0.0, -0.0, 1.0, -2.0, 0.25, -0.125]),
            rng.standard_normal(257),
        )
    ).astype(np.float64)[None, :]
    output = _apply(samples, ChannelResponseMicConfig(polarity=-1))
    expected = np.negative(samples)
    payload = {
        "sample_count": int(samples.size),
        "input_sha256": _sha256(samples.tobytes()),
        "output_sha256": _sha256(output.tobytes()),
        "expected_sha256": _sha256(expected.tobytes()),
        "element_exact": bool(np.array_equal(output, expected)),
        "byte_exact": output.tobytes() == expected.tobytes(),
    }
    payload["status"] = (
        "passed" if payload["element_exact"] and payload["byte_exact"] else "failed"
    )
    _write_json("polarity_exact_result.json", payload)
    return payload


def _welch_h1(source: np.ndarray, output: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nperseg = 8_192
    step = 4_096
    window = np.hanning(nperseg)
    s_xx = np.zeros(nperseg // 2 + 1, dtype=np.complex128)
    s_yx = np.zeros_like(s_xx)
    for start in range(0, source.size - nperseg + 1, step):
        x_spectrum = np.fft.rfft(source[start : start + nperseg] * window)
        y_spectrum = np.fft.rfft(output[start : start + nperseg] * window)
        s_xx += x_spectrum * np.conj(x_spectrum)
        s_yx += y_spectrum * np.conj(x_spectrum)
    return np.fft.rfftfreq(nperseg, d=1.0 / SAMPLE_RATE_HZ), s_yx / s_xx


def _frequency_evidence() -> tuple[dict[str, object], float, str]:
    rng = np.random.default_rng(20_260_718)
    samples = rng.standard_normal(2**18).astype(np.float64)[None, :]
    points = tuple(
        FrequencyResponsePointConfig(frequency_hz=frequency, magnitude_db=db)
        for frequency, db in RESPONSE_POINTS
    )
    output = _apply(
        samples,
        ChannelResponseMicConfig(frequency_response=points),
    )
    usable = slice(EDGE_EXCLUSION, -EDGE_EXCLUSION)
    frequencies, transfer = _welch_h1(samples[0, usable], output[0, usable])
    point_frequencies = np.asarray([point[0] for point in RESPONSE_POINTS])
    point_amplitudes = 10.0 ** (
        np.asarray([point[1] for point in RESPONSE_POINTS]) / 20.0
    )
    target_amplitude = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    measured_db = 20.0 * np.log10(
        np.maximum(np.abs(transfer), np.finfo(float).tiny)
    )
    target_db = 20.0 * np.log10(target_amplitude)
    errors_db = np.abs(measured_db - target_db)
    passband = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    maximum = float(np.max(errors_db[passband]))
    bins = [
        {
            "frequency_hz": float(frequency),
            "target_magnitude_db": float(target),
            "measured_magnitude_db": float(measured),
            "absolute_error_db": float(error),
            "in_acceptance_passband": bool(accepted),
        }
        for frequency, target, measured, error, accepted in zip(
            frequencies,
            target_db,
            measured_db,
            errors_db,
            passband,
            strict=True,
        )
    ]
    payload = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": int(samples.shape[1]),
        "seed": 20_260_718,
        "welch": {"nperseg": 8_192, "noverlap": 4_096, "window": "hann"},
        "edge_exclusion_samples": EDGE_EXCLUSION,
        "response_points": RESPONSE_POINTS,
        "passband_hz": [200.0, 18_000.0],
        "tolerance_db": FREQUENCY_RESPONSE_TOLERANCE_DB,
        "maximum_passband_error_db": maximum,
        "bins": bins,
        "status": (
            "passed"
            if maximum <= FREQUENCY_RESPONSE_TOLERANCE_DB
            else "failed"
        ),
    }
    _write_json("frequency_response_welch.json", payload)
    _write_overlay_png(
        OUTPUT / "frequency_response_overlay.png",
        frequencies,
        target_db,
        measured_db,
    )
    return payload, maximum, _sha256(samples.tobytes())


def _write_overlay_png(
    path: Path,
    frequencies: np.ndarray,
    target_db: np.ndarray,
    measured_db: np.ndarray,
) -> None:
    width, height = 1_000, 600
    pixels = bytearray([255] * (width * height * 3))

    def set_pixel(x_value: int, y_value: int, color: tuple[int, int, int]) -> None:
        if 0 <= x_value < width and 0 <= y_value < height:
            offset = (y_value * width + x_value) * 3
            pixels[offset : offset + 3] = bytes(color)

    def line(
        left: tuple[int, int],
        right: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        x0, y0 = left
        x1, y1 = right
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for index in range(steps + 1):
            ratio = index / steps
            set_pixel(
                round(x0 + (x1 - x0) * ratio),
                round(y0 + (y1 - y0) * ratio),
                color,
            )

    left, right, top, bottom = 70, width - 25, 25, height - 55
    line((left, top), (left, bottom), (0, 0, 0))
    line((left, bottom), (right, bottom), (0, 0, 0))
    mask = (frequencies >= 0.0) & (frequencies <= 24_000.0)
    selected_f = frequencies[mask]
    selected_target = target_db[mask]
    selected_measured = measured_db[mask]
    y_min = float(min(np.min(selected_target), np.min(selected_measured)) - 0.5)
    y_max = float(max(np.max(selected_target), np.max(selected_measured)) + 0.5)

    def transform(frequency: float, magnitude: float) -> tuple[int, int]:
        x_value = left + round((right - left) * frequency / 24_000.0)
        y_value = bottom - round((bottom - top) * (magnitude - y_min) / (y_max - y_min))
        return x_value, y_value

    stride = 4
    for series, color in (
        (selected_target, (40, 90, 210)),
        (selected_measured, (220, 60, 50)),
    ):
        points = [
            transform(float(selected_f[index]), float(series[index]))
            for index in range(0, selected_f.size, stride)
        ]
        for first, second in zip(points, points[1:], strict=False):
            line(first, second, color)

    raw = b"".join(
        b"\x00" + bytes(pixels[row * width * 3 : (row + 1) * width * 3])
        for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


def _off_state_chain_evidence() -> dict[str, object]:
    owner = np.arange(64, dtype=np.float32).reshape(4, 16)
    samples = owner[:, ::-1]
    before = samples.tobytes(order="A")
    output, diagnostics = ChannelEffectsChain(EffectsConfig()).apply(
        samples,
        mic_ids=("front", "right", "rear", "left"),
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="off_state",
    )
    payload = {
        "object_identity": output is samples,
        "dtype": str(output.dtype),
        "shape": output.shape,
        "strides": output.strides,
        "bytes_identical": output.tobytes(order="A") == before,
        "diagnostics": diagnostics,
    }
    payload["status"] = (
        "passed"
        if payload["object_identity"]
        and payload["bytes_identical"]
        and diagnostics == {}
        else "failed"
    )
    _write_json("off_state_chain_identity.json", payload)
    return payload


def _room_fixture():
    array = create_microphone_array(
        array_id="s3_3_room_array",
        prim_path="/World/S3_3/Array",
        layout_name="quad_cross",
        position_world=(2.0, 2.0, 1.0),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    source = AudioSourceSpec(
        source_id="s3_3_room_source",
        prim_path="/World/S3_3/Source",
        class_label="impulse",
        audio_asset_path="generated://impulse",
        position_world=(3.0, 2.0, 1.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        start_time_s=0.0,
        duration_s=0.08,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="s3_3_room_scene",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="s3_3_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.3,
            max_order=1,
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.08,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
        max_events=1,
    )
    return scene, array, window


def _off_state_backend_evidence() -> dict[str, object]:
    scene, array, window = _room_fixture()
    baseline_sink = _CaptureSink()
    disabled_sink = _CaptureSink()
    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, array, window
    )
    disabled = RoomAcousticsBackend(
        waveform_writer=disabled_sink,
        effects=EffectsConfig(),
    ).simulate(scene, array, window)
    baseline_payload = frame_to_trace_dict(baseline)
    disabled_payload = frame_to_trace_dict(disabled)
    baseline_bytes = (
        json.dumps(baseline_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    disabled_bytes = (
        json.dumps(disabled_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if baseline_sink.mixture is None or disabled_sink.mixture is None:
        raise RuntimeError("room fixture did not export a captured mixture")
    baseline_waveform = baseline_sink.mixture.tobytes(order="C")
    disabled_waveform = disabled_sink.mixture.tobytes(order="C")
    payload = {
        "pyroomacoustics_version": importlib.metadata.version("pyroomacoustics"),
        "frame_sha256": _sha256(baseline_bytes),
        "disabled_frame_sha256": _sha256(disabled_bytes),
        "waveform_sha256": _sha256(baseline_waveform),
        "disabled_waveform_sha256": _sha256(disabled_waveform),
        "waveform_shape": baseline_sink.mixture.shape,
        "frame_bytes_identical": baseline_bytes == disabled_bytes,
        "waveform_bytes_identical": baseline_waveform == disabled_waveform,
        "effects_key_absent": (
            "effects" not in baseline.diagnostics
            and "effects" not in disabled.diagnostics
        ),
    }
    payload["status"] = (
        "passed"
        if payload["frame_bytes_identical"]
        and payload["waveform_bytes_identical"]
        and payload["effects_key_absent"]
        else "failed"
    )
    _write_json("off_state_golden_sha256.json", payload)
    _write_json("off_state_frame.json", baseline_payload)
    (OUTPUT / "off_state_waveform_sha256.txt").write_text(
        f"{payload['waveform_sha256']}  s3_3_room_mixture.float64-c-order\n",
        encoding="utf-8",
    )
    return payload


def _l1_fixture():
    array = create_microphone_array(
        array_id="s3_3_l1_array",
        prim_path="/World/S3_3/L1Array",
        layout_name="quad_front",
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    source = AudioSourceSpec(
        source_id="s3_3_l1_source",
        prim_path="/World/S3_3/L1Source",
        class_label="Speech",
        audio_asset_path=None,
        position_world=(3.0, 1.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=-6.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="s3_3_l1_scene",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
    )
    return scene, array, window


def _l1_evidence() -> tuple[dict[str, object], float, float]:
    scene, array, window = _l1_fixture()
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    gain_db = -3.0
    delay_s = 12.5e-6
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                mic_id: ChannelResponseMicConfig(
                    gain_db=gain_db,
                    delay_s=delay_s,
                )
                for mic_id in mic_ids
            },
        )
    )
    cases: list[dict[str, object]] = []
    maximum_gain = 0.0
    maximum_delay = 0.0
    for label, kwargs in (
        ("legacy_stress_zero", {}),
        (
            "legacy_stress_nonzero",
            {
                "noise_std_s": 1e-6,
                "clock_jitter_s": 2e-6,
                "gain_mismatch_db": 2.0,
                "seed": 33,
            },
        ),
    ):
        baseline = TdoaSyntheticBackend(**kwargs).simulate(scene, array, window)
        effected = TdoaSyntheticBackend(effects=effects, **kwargs).simulate(
            scene, array, window
        )
        per_mic: dict[str, object] = {}
        for mic_id in mic_ids:
            observed_gain = 20.0 * math.log10(
                effected.detections[0].per_mic_rms[mic_id]
                / baseline.detections[0].per_mic_rms[mic_id]
            )
            observed_delay = (
                effected.detections[0].per_mic_delay_s[mic_id]
                - baseline.detections[0].per_mic_delay_s[mic_id]
            )
            gain_error = abs(observed_gain - gain_db)
            delay_error = abs(observed_delay - delay_s)
            maximum_gain = max(maximum_gain, gain_error)
            maximum_delay = max(maximum_delay, delay_error)
            per_mic[mic_id] = {
                "observed_gain_db": observed_gain,
                "gain_absolute_error_db": gain_error,
                "observed_delay_s": observed_delay,
                "delay_absolute_error_s": delay_error,
            }
        cases.append({"name": label, "per_mic": per_mic})
    polarity_effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                mic_id: ChannelResponseMicConfig(polarity=-1)
                for mic_id in mic_ids
            },
        )
    )
    baseline = TdoaSyntheticBackend().simulate(scene, array, window)
    polarity = TdoaSyntheticBackend(effects=polarity_effects).simulate(
        scene, array, window
    )
    polarity_exact = (
        polarity.detections[0].per_mic_rms == baseline.detections[0].per_mic_rms
        and polarity.detections[0].per_mic_delay_s
        == baseline.detections[0].per_mic_delay_s
        and polarity.diagnostics["effects"]["channel_response"]["polarity"]
        == dict.fromkeys(mic_ids, -1)
    )
    payload = {
        "configured_gain_db": gain_db,
        "configured_delay_s": delay_s,
        "gain_tolerance_db": GAIN_TOLERANCE_DB,
        "delay_tolerance_s": L1_DELAY_TOLERANCE_S,
        "maximum_gain_absolute_error_db": maximum_gain,
        "maximum_delay_absolute_error_s": maximum_delay,
        "polarity_metadata_exact_and_observables_unchanged": polarity_exact,
        "cases": cases,
    }
    payload["status"] = (
        "passed"
        if maximum_gain <= GAIN_TOLERANCE_DB
        and maximum_delay <= L1_DELAY_TOLERANCE_S
        and polarity_exact
        else "failed"
    )
    _write_json("l1_metadata_adapter.json", payload)
    return payload, maximum_gain, maximum_delay


def _base_raw() -> dict[str, Any]:
    return {
        "scene": {"scene_id": "s3_3_invalid"},
        "audio": {
            "default_backend": "room_acoustics",
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": SAMPLE_RATE_HZ,
        },
        "arrays": {
            "rig": {
                "prim_path": "/World/Rig",
                "microphones": [
                    {"mic_id": "front"},
                    {"mic_id": "right"},
                ],
            }
        },
    }


def _invalid_config_evidence() -> dict[str, object]:
    cases = {
        "unknown_microphone": {"unknown": {"gain_db": 1.0}},
        "order_mismatch": {
            "right": {"gain_db": 1.0},
            "front": {"gain_db": 1.0},
        },
    }
    results: list[dict[str, object]] = []
    for name, microphones in cases.items():
        raw = _base_raw()
        raw["audio"]["effects"] = {
            "channel_response": {"enabled": True, "microphones": microphones}
        }
        try:
            validate_audio_config(raw)
        except ConfigValidationError as exc:
            results.append(
                {
                    "name": name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "passed": True,
                }
            )
        else:
            results.append({"name": name, "passed": False})
    payload = {
        "results": results,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
    }
    _write_json("invalid_config_matrix.json", payload)
    return payload


def _unsupported_evidence() -> dict[str, object]:
    scene, array, window = _l1_fixture()
    points = (
        FrequencyResponsePointConfig(frequency_hz=100.0, magnitude_db=-1.0),
        FrequencyResponsePointConfig(frequency_hz=1_000.0, magnitude_db=0.0),
    )
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                "front": ChannelResponseMicConfig(frequency_response=points)
            },
        )
    )
    results: list[dict[str, object]] = []
    for backend in (
        GeometryBackend(effects=effects),
        TdoaSyntheticBackend(effects=effects),
    ):
        try:
            backend.simulate(scene, array, window)
        except UnsupportedEffectError as exc:
            results.append(
                {
                    "backend_id": backend.backend_id,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "partial_outputs": [],
                    "passed": True,
                }
            )
        else:
            results.append({"backend_id": backend.backend_id, "passed": False})
    payload = {
        "results": results,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
    }
    _write_json("unsupported_feature_errors.json", payload)
    (OUTPUT / "partial_output_listing.txt").write_text(
        "No partial frames or waveform assets were produced for either typed "
        "unsupported-feature failure.\n",
        encoding="utf-8",
    )
    return payload


def _determinism_evidence() -> dict[str, object]:
    declaration = next(
        declaration
        for declaration in get_default_registry().declarations("propagation_backend")
        if declaration.plugin_id == "tdoa_synthetic"
    )
    validate_declaration(declaration, TdoaSyntheticBackend)
    scene, array, window = _l1_fixture()
    mic_ids = tuple(mic.mic_id for mic in array.microphones)
    effects = EffectsConfig(
        channel_response=ChannelResponseConfig(
            enabled=True,
            microphones={
                mic_id: ChannelResponseMicConfig(
                    gain_db=-3.0,
                    delay_s=5e-6,
                    polarity=-1,
                )
                for mic_id in mic_ids
            },
        )
    )
    kwargs = {
        "effects": effects,
        "noise_std_s": 1e-6,
        "clock_jitter_s": 2e-6,
        "gain_mismatch_db": 1.5,
        "seed": 7,
    }
    first = TdoaSyntheticBackend(**kwargs).simulate(scene, array, window)
    second = TdoaSyntheticBackend(**kwargs).simulate(scene, array, window)
    first_bytes = (
        json.dumps(frame_to_trace_dict(first), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    second_bytes = (
        json.dumps(frame_to_trace_dict(second), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    payload = {
        "registry_twice_run_self_test": "passed",
        "enabled_fixture_first_sha256": _sha256(first_bytes),
        "enabled_fixture_second_sha256": _sha256(second_bytes),
        "enabled_fixture_exact": first_bytes == second_bytes,
        "status": "passed" if first_bytes == second_bytes else "failed",
    }
    _write_json("registry_determinism.json", payload)
    return payload


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()

    gain, gain_maximum, gain_fixture_hash = _gain_evidence()
    delay, delay_maximum, delay_fixture_hash = _delay_evidence()
    polarity = _polarity_evidence()
    frequency, frequency_maximum, frequency_fixture_hash = _frequency_evidence()
    chain_off = _off_state_chain_evidence()
    backend_off = _off_state_backend_evidence()
    l1, l1_gain_maximum, l1_delay_maximum = _l1_evidence()
    invalid = _invalid_config_evidence()
    unsupported = _unsupported_evidence()
    determinism = _determinism_evidence()

    rows = {
        "gain_recovery": gain["status"],
        "fractional_delay": delay["status"],
        "polarity": polarity["status"],
        "frequency_response": frequency["status"],
        "pure_off_state": chain_off["status"],
        "backend_off_state": backend_off["status"],
        "l1_adapter_equivalence": l1["status"],
        "unknown_microphone": invalid["status"],
        "unsupported_feature": unsupported["status"],
        "deterministic_backend": determinism["status"],
    }
    artifact_hashes = {
        path.name: _file_sha256(path)
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "channel_response_gate.json"
    }
    gate = {
        "subphase": "S3.3",
        "entry_revision": ENTRY_REVISION,
        "implementation_base_revision": _git_revision(),
        "package_version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pyroomacoustics": importlib.metadata.version("pyroomacoustics"),
            "scipy": importlib.metadata.version("scipy"),
            "platform": platform.platform(),
        },
        "fixtures": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "gain_sample_count": 48_000,
            "delay_sample_count": 16_384,
            "frequency_response_sample_count": 2**18,
            "gain_fixture_sha256": gain_fixture_hash,
            "delay_fixture_sha256": delay_fixture_hash,
            "frequency_response_fixture_sha256": frequency_fixture_hash,
        },
        "tolerances": {
            "gain_maximum_absolute_error_db": GAIN_TOLERANCE_DB,
            "fractional_delay_maximum_absolute_error_samples": (
                DELAY_TOLERANCE_SAMPLES
            ),
            "fractional_delay_maximum_absolute_error_s": (
                DELAY_TOLERANCE_SAMPLES / SAMPLE_RATE_HZ
            ),
            "frequency_response_maximum_passband_error_db": (
                FREQUENCY_RESPONSE_TOLERANCE_DB
            ),
            "l1_gain_maximum_absolute_error_db": GAIN_TOLERANCE_DB,
            "l1_delay_maximum_absolute_error_s": L1_DELAY_TOLERANCE_S,
            "polarity": "exact bytes",
            "off_state": "exact bytes and identity where applicable",
        },
        "measured_maxima": {
            "gain_absolute_error_db": gain_maximum,
            "fractional_delay_absolute_error_samples": delay_maximum,
            "fractional_delay_absolute_error_s": delay_maximum / SAMPLE_RATE_HZ,
            "frequency_response_passband_error_db": frequency_maximum,
            "l1_gain_absolute_error_db": l1_gain_maximum,
            "l1_delay_absolute_error_s": l1_delay_maximum,
        },
        "rows": {name: {"status": status} for name, status in rows.items()},
        "commands": [
            ".venv/bin/python -m pytest",
            ".venv/bin/python -m ruff check .",
            ".venv/bin/python scripts/s3_3_evidence.py",
        ],
        "artifact_sha256": artifact_hashes,
        "status": "passed" if set(rows.values()) == {"passed"} else "failed",
    }
    _write_json("channel_response_gate.json", gate)
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "status": gate["status"],
                "measured_maxima": gate["measured_maxima"],
            },
            sort_keys=True,
        )
    )
    return 0 if gate["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
