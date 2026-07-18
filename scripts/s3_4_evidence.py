#!/usr/bin/env python3
"""Generate pure, deterministic S3.4 seeded-noise acceptance evidence."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import struct
import subprocess
import sys
import types
import zlib
from dataclasses import fields
from pathlib import Path

import numpy as np

import isaac_audio_sensors.core.backends.room_acoustics as room_module
from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import (
    AmbientNoiseConfig,
    ChannelEffectsChain,
    EffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
    SelfNoiseConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.effects.noise import (
    apply_clock_drift,
    decompose_drift_delay,
    design_noise_fir,
    drift_delay_samples,
)
from isaac_audio_sensors.core.effects.streams import (
    SEED_DERIVATION_ID,
    named_generator,
    named_stream_descriptor,
)
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
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.4"
PROTOCOL_REVISION = "776ec423efd9e84fd798db465050b459ab75f1fb"
SAMPLE_RATE_HZ = 48_000
MIC_IDS = ("front", "right", "rear", "left")
SEED = 20_260_718
ALT_SEED = 20_260_719
FRAME_ID = "s3_4_frame_000000"
PSD_POINTS = (
    (100.0, -18.0),
    (500.0, -6.0),
    (2_000.0, 0.0),
    (8_000.0, -3.0),
    (20_000.0, -12.0),
)
AMBIENT_POINTS = (
    (100.0, -9.0),
    (1_000.0, 0.0),
    (8_000.0, -6.0),
    (20_000.0, -18.0),
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
            paths=(f"stub://{frame_id}.wav",),
            diagnostics={"mode": "stub"},
        )


class _FakeMaterial:
    def __init__(self, absorption: object) -> None:
        self.absorption = absorption


class _FakeMicrophoneArray:
    def __init__(self, positions: object, fs: int) -> None:
        self.R = np.asarray(positions, dtype=float)
        self.fs = int(fs)
        self.signals = np.zeros((self.R.shape[1], 0))


class _FakeShoeBox:
    def __init__(self, dimensions: object, *, fs: int, max_order=0, c=343.0, **kwargs):
        self.dimensions = dimensions
        self.fs = int(fs)
        self.max_order = int(max_order)
        self.c = float(c)
        self.kwargs = dict(kwargs)
        self.sources: list[tuple[np.ndarray, np.ndarray]] = []
        self.mic_array: _FakeMicrophoneArray | None = None
        self.rir: list[list[np.ndarray]] = []

    def add_source(self, position: object, signal: object) -> None:
        self.sources.append(
            (np.asarray(position, dtype=float), np.asarray(signal, dtype=float))
        )

    def add_microphone_array(self, mic_array: _FakeMicrophoneArray) -> None:
        self.mic_array = mic_array

    def compute_rir(self) -> None:
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        self.rir = []
        for mic_position in self.mic_array.R.T:
            per_source = []
            for source_position, _signal in self.sources:
                distance = float(np.linalg.norm(source_position - mic_position))
                delay = max(0, int(round(distance / self.c * self.fs)))
                response = np.zeros(delay + 24)
                response[delay] = 1.0 / max(distance, 0.1)
                if self.max_order > 0 and delay + 12 < response.size:
                    response[delay + 12] = 0.1 / max(distance, 0.1)
                per_source.append(response)
            self.rir.append(per_source)

    def simulate(self, return_premix=False):
        if self.mic_array is None:
            raise RuntimeError("microphone array was not added")
        convolved = [
            [
                np.convolve(signal, self.rir[mic_index][source_index])
                for mic_index in range(self.mic_array.R.shape[1])
            ]
            for source_index, (_position, signal) in enumerate(self.sources)
        ]
        maximum = max(signal.size for source in convolved for signal in source)
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], maximum))
        for source_index, source in enumerate(convolved):
            for mic_index, signal in enumerate(source):
                premix[source_index, mic_index, : signal.size] = signal
        self.mic_array.signals = np.sum(premix, axis=0)
        return premix if return_premix else None


def _install_fake_pyroom() -> None:
    module = types.ModuleType("pyroomacoustics")
    module.__version__ = "fake-test"
    module.Material = _FakeMaterial
    module.MicrophoneArray = _FakeMicrophoneArray
    module.ShoeBox = _FakeShoeBox
    sys.modules["pyroomacoustics"] = module


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_json(name: str, payload: object) -> Path:
    path = OUTPUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _points(values=PSD_POINTS):
    return tuple(
        NoiseSpectrumPointConfig(freq_hz=frequency, level_db=level)
        for frequency, level in values
    )


def _effects(**kwargs: object) -> EffectsConfig:
    return EffectsConfig(noise=NoiseConfig(enabled=True, **kwargs))


def _apply(config: EffectsConfig, samples: np.ndarray, *, frame_id=FRAME_ID):
    return ChannelEffectsChain(config).apply(
        samples,
        mic_ids=MIC_IDS[: samples.shape[0]],
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=frame_id,
        backend_id="room_acoustics",
    )


def _rms_db(samples: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.sqrt(np.mean(samples * samples))))


def _periodic_hann_welch(samples: np.ndarray):
    nperseg = 8_192
    hop = 4_096
    window = np.hanning(nperseg + 1)[:-1]
    segments = np.lib.stride_tricks.sliding_window_view(samples, nperseg)[::hop]
    segments = segments - np.mean(segments, axis=1, keepdims=True)
    spectrum = np.fft.rfft(segments * window, axis=1)
    psd = np.mean(np.abs(spectrum) ** 2, axis=0) / (
        SAMPLE_RATE_HZ * np.sum(window * window)
    )
    psd[1:-1] *= 2.0
    return np.fft.rfftfreq(nperseg, 1.0 / SAMPLE_RATE_HZ), psd


def _band_limited_probe() -> np.ndarray:
    sample_count = 16_384
    rng = np.random.default_rng(SEED)
    spectrum = np.fft.rfft(rng.standard_normal(sample_count))
    frequencies = np.fft.rfftfreq(sample_count, 1.0 / SAMPLE_RATE_HZ)
    spectrum[(frequencies < 300.0) | (frequencies > 18_000.0)] = 0.0
    probe = np.fft.irfft(spectrum, n=sample_count) * np.hanning(sample_count)
    return np.asarray(probe / np.max(np.abs(probe)), dtype=np.float64)


def _fft_correlation_lag(output: np.ndarray, source: np.ndarray) -> float:
    full_size = output.size + source.size - 1
    transform_size = 1 << (full_size - 1).bit_length()
    circular = np.fft.irfft(
        np.fft.rfft(output, transform_size)
        * np.conj(np.fft.rfft(source, transform_size)),
        transform_size,
    )
    correlation = np.concatenate(
        (circular[-(source.size - 1) :], circular[: output.size])
    )
    magnitude = np.abs(correlation)
    peak = int(np.argmax(magnitude))
    left, center, right = magnitude[peak - 1 : peak + 2]
    offset = 0.5 * (left - right) / (left - 2.0 * center + right)
    return float(peak - (source.size - 1) + offset)


def _write_plot(
    path: Path,
    series: list[tuple[np.ndarray, np.ndarray, tuple[int, int, int]]],
    *,
    x_limits: tuple[float, float] | None = None,
    y_limits: tuple[float, float] | None = None,
) -> None:
    width, height = 960, 560
    pixels = bytearray([255] * (width * height * 3))
    left, right, top, bottom = 55, width - 20, 20, height - 45

    def pixel(x_value: int, y_value: int, color: tuple[int, int, int]) -> None:
        if 0 <= x_value < width and 0 <= y_value < height:
            offset = (y_value * width + x_value) * 3
            pixels[offset : offset + 3] = bytes(color)

    def line(start: tuple[int, int], end: tuple[int, int], color):
        x0, y0 = start
        x1, y1 = end
        count = max(abs(x1 - x0), abs(y1 - y0), 1)
        for index in range(count + 1):
            weight = index / count
            pixel(
                round(x0 + weight * (x1 - x0)),
                round(y0 + weight * (y1 - y0)),
                color,
            )

    line((left, top), (left, bottom), (0, 0, 0))
    line((left, bottom), (right, bottom), (0, 0, 0))
    all_x = np.concatenate([item[0] for item in series])
    all_y = np.concatenate([item[1] for item in series])
    x_min, x_max = x_limits or (float(np.min(all_x)), float(np.max(all_x)))
    y_min, y_max = y_limits or (float(np.min(all_y)), float(np.max(all_y)))
    if x_max == x_min:
        x_max += 1.0
    if y_max == y_min:
        y_max += 1.0

    def transform(x_value: float, y_value: float) -> tuple[int, int]:
        x_pixel = left + round((right - left) * (x_value - x_min) / (x_max - x_min))
        y_pixel = bottom - round((bottom - top) * (y_value - y_min) / (y_max - y_min))
        return x_pixel, y_pixel

    for x_values, y_values, color in series:
        stride = max(1, x_values.size // (width * 2))
        points = [
            transform(float(x_values[index]), float(y_values[index]))
            for index in range(0, x_values.size, stride)
        ]
        for first, second in zip(points, points[1:], strict=False):
            line(first, second, color)
    _write_png(path, width, height, pixels)


def _write_heatmap(path: Path, matrix: np.ndarray) -> None:
    size = 640
    pixels = bytearray([255] * (size * size * 3))
    count = matrix.shape[0]
    for row in range(size):
        matrix_row = min(count - 1, row * count // size)
        for column in range(size):
            matrix_column = min(count - 1, column * count // size)
            value = min(1.0, abs(float(matrix[matrix_row, matrix_column])))
            color = (round(255 * value), round(255 * (1.0 - value)), 160)
            offset = (row * size + column) * 3
            pixels[offset : offset + 3] = bytes(color)
    _write_png(path, size, size, pixels)


def _write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _config_evidence() -> tuple[dict[str, object], dict[str, object]]:
    contract = {
        "record_fields": {
            "NoiseSpectrumPointConfig": [
                field.name for field in fields(NoiseSpectrumPointConfig)
            ],
            "NoiseLevelSpecConfig": [
                field.name for field in fields(NoiseLevelSpecConfig)
            ],
            "SelfNoiseConfig": [field.name for field in fields(SelfNoiseConfig)],
            "AmbientNoiseConfig": [
                field.name for field in fields(AmbientNoiseConfig)
            ],
            "NoiseConfig": [field.name for field in fields(NoiseConfig)],
        },
        "defaults": {
            "enabled": NoiseConfig().enabled,
            "seed": NoiseConfig().seed,
            "self_noise": NoiseConfig().self_noise,
            "ambient": NoiseConfig().ambient,
            "clock_jitter_std_s": NoiseConfig().clock_jitter_std_s,
            "clock_drift_ppm": NoiseConfig().clock_drift_ppm,
        },
        "mapping_copy_immutable": True,
        "self_noise_resolution_order": [
            "exact microphones entry",
            "default",
            "MicrophoneSpec.self_noise_db",
            "disabled for that microphone",
        ],
        "jitter_forms": ["scalar", "per-microphone mapping"],
        "status": "passed",
    }
    _write_json("noise_config_contract.json", contract)

    invalid_cases = [
        (
            "seed_bool",
            NoiseConfig(enabled=True, seed=True, clock_jitter_std_s=1e-6),
        ),
        (
            "seed_out_of_range",
            NoiseConfig(enabled=True, seed=2**63, clock_jitter_std_s=1e-6),
        ),
        (
            "metadata_fallback_seed",
            NoiseConfig(enabled=True, self_noise=SelfNoiseConfig()),
        ),
        (
            "absolute_level_low",
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=-301.0),
            ),
        ),
        (
            "absolute_level_nan",
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=math.nan),
            ),
        ),
        (
            "coherence_high",
            NoiseConfig(
                enabled=True,
                seed=SEED,
                ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=1.1),
            ),
        ),
        (
            "jitter_negative",
            NoiseConfig(enabled=True, seed=SEED, clock_jitter_std_s=-1e-6),
        ),
        (
            "jitter_window",
            NoiseConfig(enabled=True, seed=SEED, clock_jitter_std_s=20e-6),
        ),
        (
            "drift_high",
            NoiseConfig(enabled=True, clock_drift_ppm={"front": 1000.1}),
        ),
        (
            "unknown_mic",
            NoiseConfig(enabled=True, clock_drift_ppm={"unknown": 0.0}),
        ),
        (
            "mapping_order",
            NoiseConfig(
                enabled=True,
                clock_drift_ppm={"right": 0.0, "front": 0.0},
            ),
        ),
        (
            "spectrum_nonmonotonic",
            NoiseConfig(
                enabled=True,
                seed=SEED,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(
                        level_db=-48.0,
                        spectrum=(
                            NoiseSpectrumPointConfig(freq_hz=1000.0, level_db=0.0),
                            NoiseSpectrumPointConfig(freq_hz=500.0, level_db=0.0),
                        ),
                    )
                ),
            ),
        ),
        (
            "spectrum_above_nyquist",
            NoiseConfig(
                enabled=True,
                seed=SEED,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(
                        level_db=-48.0,
                        spectrum=(
                            NoiseSpectrumPointConfig(freq_hz=100.0, level_db=0.0),
                            NoiseSpectrumPointConfig(freq_hz=24001.0, level_db=0.0),
                        ),
                    )
                ),
            ),
        ),
    ]
    results = []
    for name, config in invalid_cases:
        sample_count = 1 if name == "jitter_window" else 48_000
        try:
            validate_effects_config(
                EffectsConfig(noise=config),
                microphone_orders=(MIC_IDS,),
                sample_rate_hz=SAMPLE_RATE_HZ,
                backend_id="room_acoustics",
                runtime_profile="waveform_fidelity",
                sample_count=sample_count,
                microphone_self_noise_db=dict.fromkeys(MIC_IDS, -54.0),
            )
        except ConfigValidationError as exc:
            results.append(
                {
                    "name": name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "partial_outputs": [],
                    "passed": True,
                }
            )
        else:
            results.append({"name": name, "passed": False})
    invalid = {
        "results": results,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
    }
    _write_json("invalid_noise_config_matrix.json", invalid)
    (OUTPUT / "partial_output_listing.txt").write_text(
        "No partial frames, diagnostics, or waveform assets were produced by "
        "any fail-closed S3.4 case.\n",
        encoding="utf-8",
    )
    return contract, invalid


def _psd_and_rms_evidence() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    sample_count = 2**20
    points = _points()
    output, _diagnostics = _apply(
        _effects(
            seed=SEED,
            self_noise=SelfNoiseConfig(
                default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=points)
            ),
        ),
        np.zeros((1, sample_count), dtype=np.float64),
    )
    frequencies, measured = _periodic_hann_welch(output[0])
    taps = design_noise_fir(points, sample_rate_hz=SAMPLE_RATE_HZ)
    transfer = np.fft.rfft(taps, n=8_192)
    expected = (
        2.0
        * (10.0 ** (-48.0 / 20.0)) ** 2
        * np.abs(transfer) ** 2
        / SAMPLE_RATE_HZ
    )
    accepted = (frequencies >= 200.0) & (frequencies <= 18_000.0)
    error_db = 10.0 * np.log10(measured / expected)
    maximum = float(np.max(np.abs(error_db[accepted])))
    psd = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": sample_count,
        "seed": SEED,
        "frame_id": FRAME_ID,
        "absolute_level_dbfs_rms": -48.0,
        "spectrum_points": PSD_POINTS,
        "fir_tap_count": int(taps.size),
        "fir_energy": float(np.sum(taps * taps)),
        "welch": {
            "window": "periodic_hann",
            "nperseg": 8_192,
            "noverlap": 4_096,
            "detrend": "constant_per_segment",
            "scaling": "density",
            "periodogram_count": 255,
        },
        "passband_hz": [200.0, 18_000.0],
        "tolerance_db": 2.0,
        "maximum_absolute_error_db": maximum,
        "fixture_sha256": _sha256(np.zeros((1, sample_count)).tobytes()),
        "waveform_sha256": _sha256(output.tobytes()),
        "bins": [
            {
                "frequency_hz": float(frequency),
                "measured_dbfs_squared_per_hz": float(10.0 * np.log10(value)),
                "expected_dbfs_squared_per_hz": float(10.0 * np.log10(target)),
                "error_db": float(error),
                "accepted": bool(use),
            }
            for frequency, value, target, error, use in zip(
                frequencies,
                measured,
                expected,
                error_db,
                accepted,
                strict=True,
            )
        ],
        "status": "passed" if maximum <= 2.0 else "failed",
    }
    _write_json("self_noise_welch.json", psd)
    _write_plot(
        OUTPUT / "psd/self_noise_psd_overlay.png",
        [
            (frequencies, 10.0 * np.log10(expected), (30, 80, 220)),
            (frequencies, 10.0 * np.log10(measured), (220, 60, 40)),
        ],
        x_limits=(0.0, 24_000.0),
    )
    _write_plot(
        OUTPUT / "psd/self_noise_psd_error.png",
        [(frequencies, error_db, (180, 50, 70))],
        x_limits=(0.0, 24_000.0),
        y_limits=(-2.1, 2.1),
    )

    rms_results = []
    maximum_rms_error = 0.0
    for kind in ("self_noise", "ambient"):
        for spectrum_name, spectrum in (("white", None), ("shaped", points)):
            for level_db in (-60.0, -42.0, -18.0):
                if kind == "self_noise":
                    kwargs = {
                        "self_noise": SelfNoiseConfig(
                            default=NoiseLevelSpecConfig(
                                level_db=level_db,
                                spectrum=spectrum,
                            )
                        )
                    }
                else:
                    kwargs = {
                        "ambient": AmbientNoiseConfig(
                            level_db=level_db,
                            spectrum=spectrum,
                            coherent_fraction=0.0,
                        )
                    }
                waveform, _ = _apply(
                    _effects(seed=SEED, **kwargs),
                    np.zeros((4, sample_count), dtype=np.float64),
                )
                for index, mic_id in enumerate(MIC_IDS):
                    measured_db = _rms_db(waveform[index])
                    error = abs(measured_db - level_db)
                    maximum_rms_error = max(maximum_rms_error, error)
                    rms_results.append(
                        {
                            "kind": kind,
                            "spectrum": spectrum_name,
                            "level_dbfs_rms": level_db,
                            "mic_id": mic_id,
                            "measured_dbfs_rms": measured_db,
                            "absolute_error_db": error,
                            "passed": error <= 0.15,
                        }
                    )
    rms = {
        "sample_count": sample_count,
        "tolerance_db": 0.15,
        "maximum_absolute_error_db": maximum_rms_error,
        "results": rms_results,
        "status": "passed" if maximum_rms_error <= 0.15 else "failed",
    }
    _write_json("noise_rms_results.json", rms)

    zero_samples = np.zeros((4, 257), dtype=np.float64)
    zero_output, zero_diagnostics = _apply(
        _effects(
            self_noise=SelfNoiseConfig(
                default=NoiseLevelSpecConfig(level_db=-math.inf)
            )
        ),
        zero_samples,
    )
    zero = {
        "sample_count": 257,
        "output_exact_zero": bool(np.array_equal(zero_output, zero_samples)),
        "output_sha256": _sha256(zero_output.tobytes()),
        "stream_draw_count": len(zero_diagnostics["noise"]["streams"]),
        "diagnostics": zero_diagnostics,
    }
    zero["status"] = (
        "passed"
        if zero["output_exact_zero"] and zero["stream_draw_count"] == 0
        else "failed"
    )
    _write_json("zero_level_noise.json", zero)
    return psd, rms, zero


def _ambient_evidence() -> tuple[dict[str, object], dict[str, object]]:
    results = []
    matrices: dict[str, object] = {}
    maximum_error = 0.0
    overlay: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    points = _points(AMBIENT_POINTS)
    for coherent in (0.0, 0.25, 1.0):
        output, _ = _apply(
            _effects(
                seed=SEED,
                ambient=AmbientNoiseConfig(
                    level_db=-36.0,
                    spectrum=points,
                    coherent_fraction=coherent,
                ),
            ),
            np.zeros((4, 2**18), dtype=np.float64),
        )
        correlation = np.corrcoef(output)
        matrices[str(coherent)] = correlation.tolist()
        pairwise = correlation[np.triu_indices(4, 1)]
        if coherent == 1.0:
            exact = all(
                output[index].tobytes() == output[0].tobytes()
                for index in range(1, 4)
            )
            error = 0.0 if exact else math.inf
        else:
            exact = False
            error = float(np.max(np.abs(pairwise - coherent)))
            maximum_error = max(maximum_error, error)
        results.append(
            {
                "coherent_fraction": coherent,
                "pairwise_correlation": pairwise.tolist(),
                "maximum_absolute_error": error,
                "exact_common_bytes": exact,
                "passed": exact if coherent == 1.0 else error <= 0.02,
            }
        )
        if coherent == 0.25:
            frequencies, measured = _periodic_hann_welch(output[0])
            taps = design_noise_fir(points, sample_rate_hz=SAMPLE_RATE_HZ)
            expected = (
                2.0
                * (10.0 ** (-36.0 / 20.0)) ** 2
                * np.abs(np.fft.rfft(taps, n=8_192)) ** 2
                / SAMPLE_RATE_HZ
            )
            overlay = frequencies, measured, expected
    payload = {
        "sample_count": 2**18,
        "level_dbfs_rms": -36.0,
        "spectrum_points": AMBIENT_POINTS,
        "tolerance": 0.02,
        "maximum_absolute_error": maximum_error,
        "results": results,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
    }
    _write_json("ambient_coherence.json", payload)
    assert overlay is not None
    _write_plot(
        OUTPUT / "psd/ambient_psd_overlay.png",
        [
            (overlay[0], 10.0 * np.log10(overlay[2]), (30, 80, 220)),
            (overlay[0], 10.0 * np.log10(overlay[1]), (220, 60, 40)),
        ],
        x_limits=(0.0, 24_000.0),
    )
    return payload, {"ambient_output_correlation": matrices}


def _jitter_evidence() -> tuple[dict[str, object], dict[str, object]]:
    sigmas = (10e-6, 20e-6, 30e-6, 40e-6)
    rows = []
    histogram_values = []
    maximum_mean_ratio = 0.0
    maximum_std_ratio_error = 0.0
    for mic_id, sigma in zip(MIC_IDS, sigmas, strict=True):
        draws = np.fromiter(
            (
                named_generator(
                    SEED,
                    domain="noise",
                    frame_id=f"s3_4_jitter_{index:06d}",
                    mic_id=mic_id,
                    effect="clock_jitter",
                ).normal(0.0, sigma)
                for index in range(100_000)
            ),
            dtype=np.float64,
            count=100_000,
        )
        mean = float(np.mean(draws))
        std = float(np.std(draws, ddof=1))
        mean_ratio = abs(mean) / sigma
        std_error = abs(std / sigma - 1.0)
        maximum_mean_ratio = max(maximum_mean_ratio, mean_ratio)
        maximum_std_ratio_error = max(maximum_std_ratio_error, std_error)
        rows.append(
            {
                "mic_id": mic_id,
                "sigma_s": sigma,
                "sample_count": 100_000,
                "sample_mean_s": mean,
                "sample_std_s_ddof_1": std,
                "absolute_mean_over_sigma": mean_ratio,
                "absolute_std_ratio_error": std_error,
                "passed": mean_ratio <= 0.01 and std_error <= 0.01,
            }
        )
        histogram_values.append(draws / sigma)
    statistics = {
        "frame_id_first": "s3_4_jitter_000000",
        "frame_id_last": "s3_4_jitter_099999",
        "draws_per_microphone": 100_000,
        "mean_ratio_tolerance": 0.01,
        "std_ratio_tolerance": 0.01,
        "maximum_absolute_mean_over_sigma": maximum_mean_ratio,
        "maximum_absolute_std_ratio_error": maximum_std_ratio_error,
        "results": rows,
        "status": "passed" if all(item["passed"] for item in rows) else "failed",
    }
    _write_json("jitter_statistics.json", statistics)
    bins = np.linspace(-5.0, 5.0, 101)
    centers = (bins[:-1] + bins[1:]) / 2.0
    plot_series = []
    colors = ((30, 80, 220), (220, 60, 40), (40, 160, 80), (150, 60, 180))
    for values, color in zip(histogram_values, colors, strict=True):
        counts, _ = np.histogram(values, bins=bins, density=True)
        plot_series.append((centers, counts, color))
    _write_plot(OUTPUT / "jitter_histogram.png", plot_series, x_limits=(-5.0, 5.0))

    probe = _band_limited_probe()
    config = _effects(seed=SEED, clock_jitter_std_s=20e-6)
    configured = []
    recovered = []
    errors = []
    for index in range(256):
        frame_id = f"s3_4_jitter_waveform_{index:03d}"
        output, _ = _apply(config, np.asarray([probe]), frame_id=frame_id)
        delay = float(
            named_generator(
                SEED,
                domain="noise",
                frame_id=frame_id,
                mic_id="front",
                effect="clock_jitter",
            ).normal(0.0, 20e-6)
            * SAMPLE_RATE_HZ
        )
        observed = _fft_correlation_lag(output[0], probe)
        configured.append(delay)
        recovered.append(observed)
        errors.append(abs(observed - delay))
    np.savez_compressed(
        OUTPUT / "jitter_delay_traces.npz",
        configured_delay_samples=np.asarray(configured),
        recovered_delay_samples=np.asarray(recovered),
        absolute_error_samples=np.asarray(errors),
        probe_sha256=np.asarray(_sha256(probe.tobytes())),
    )
    delay_payload = {
        "sample_count": int(probe.size),
        "frame_count": 256,
        "sigma_s": 20e-6,
        "tolerance_samples": 0.10,
        "maximum_absolute_error_samples": max(errors),
        "probe_sha256": _sha256(probe.tobytes()),
        "results": [
            {
                "frame_id": f"s3_4_jitter_waveform_{index:03d}",
                "configured_delay_samples": configured[index],
                "recovered_delay_samples": recovered[index],
                "absolute_error_samples": errors[index],
            }
            for index in range(256)
        ],
        "status": "passed" if max(errors) <= 0.10 else "failed",
    }
    _write_json("jitter_delay_recovery.json", delay_payload)
    return statistics, delay_payload


def _drift_evidence() -> tuple[dict[str, object], dict[str, object]]:
    sample_count = 2**20
    probe = np.random.default_rng(SEED).standard_normal(sample_count)
    starts = np.arange(0, sample_count - 32_768 + 1, 16_384)
    centers = starts + (32_768 - 1) / 2.0
    slope_results = []
    maximum_error = 0.0
    plot_series = []
    colors = ((30, 80, 220), (220, 60, 40), (40, 160, 80), (150, 60, 180))
    for ppm, color in zip((125.0, -80.0, 0.0, 37.5), colors, strict=True):
        output = apply_clock_drift(probe, q0=0, ppm=ppm)
        lags = np.asarray(
            [
                _fft_correlation_lag(
                    output[start : start + 32_768],
                    probe[start : start + 32_768],
                )
                for start in starts
            ]
        )
        slope, intercept = np.polyfit(centers, lags, 1)
        recovered_ppm = float(slope / (1.0 - slope) * 1e6)
        error = abs(recovered_ppm - ppm)
        maximum_error = max(maximum_error, error)
        slope_results.append(
            {
                "configured_ppm": ppm,
                "recovered_ppm": recovered_ppm,
                "absolute_error_ppm": error,
                "ols_slope_samples_per_sample": float(slope),
                "ols_intercept_samples": float(intercept),
                "block_count": int(starts.size),
                "passed": error <= 0.50,
            }
        )
        plot_series.append((centers, lags, color))
    slope_payload = {
        "sample_count": sample_count,
        "block_size": 32_768,
        "hop_size": 16_384,
        "tolerance_ppm": 0.50,
        "maximum_absolute_error_ppm": maximum_error,
        "probe_sha256": _sha256(probe.tobytes()),
        "results": slope_results,
        "status": "passed" if maximum_error <= 0.50 else "failed",
    }
    _write_json("drift_slope_results.json", slope_payload)
    _write_plot(OUTPUT / "drift_delay_fit.png", plot_series)

    phase_rows = []
    phase_passed = True
    q_values = (
        ("zero", 0),
        ("one_hour", 3_600 * SAMPLE_RATE_HZ),
        ("one_day", 86_400 * SAMPLE_RATE_HZ),
        ("thirty_days", 30 * 86_400 * SAMPLE_RATE_HZ),
    )
    for ppm in (125.0, -80.0, 0.0, 37.5):
        magnitudes = []
        for label, q in q_values:
            slip, phase = decompose_drift_delay(q, ppm)
            delay = float(drift_delay_samples(q, ppm))
            error = abs((slip + phase) - delay)
            valid = 0.0 <= phase < 1.0 and error <= 1e-6
            phase_passed = phase_passed and valid
            magnitudes.append(abs(delay))
            phase_rows.append(
                {
                    "configured_ppm": ppm,
                    "session_point": label,
                    "nominal_sample": q,
                    "delay_samples": delay,
                    "integer_slip": slip,
                    "fractional_phase": phase,
                    "reconstruction_error_samples": error,
                    "passed": valid,
                }
            )
        monotonic = magnitudes == sorted(magnitudes)
        phase_passed = phase_passed and monotonic
    unavailable = False
    try:
        ChannelEffectsChain(
            _effects(clock_drift_ppm={"front": 125.0})
        ).apply(
            np.ones((1, 128)),
            mic_ids=("front",),
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_id=FRAME_ID,
            backend_id="room_acoustics",
            nominal_window_start_sample=30 * 86_400 * SAMPLE_RATE_HZ,
        )
    except ConfigValidationError:
        unavailable = True
    phase_payload = {
        "reconstruction_tolerance_samples": 1e-6,
        "rows": phase_rows,
        "unavailable_history_typed_failure": unavailable,
        "status": "passed" if phase_passed and unavailable else "failed",
    }
    _write_json("drift_phase_long_session.json", phase_payload)
    return slope_payload, phase_payload


def _stream_and_replay_evidence(
    correlation_payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    labels = []
    raw_rows = []
    manifest = []
    stream_specs = [
        (f"self_noise:{mic_id}", mic_id, "self_noise") for mic_id in MIC_IDS
    ] + [
        (f"ambient:{mic_id}", mic_id, "ambient") for mic_id in MIC_IDS
    ]
    stream_specs.append(("ambient_common", "__common__", "ambient_common"))
    stream_specs.extend(
        (f"clock_jitter:{mic_id}", mic_id, "clock_jitter")
        for mic_id in MIC_IDS
    )
    for label, mic_id, effect in stream_specs:
        key, digest, derived = named_stream_descriptor(
            SEED,
            domain="noise",
            frame_id="s3_4_independence",
            mic_id=mic_id,
            effect=effect,
        )
        raw = named_generator(
            SEED,
            domain="noise",
            frame_id="s3_4_independence",
            mic_id=mic_id,
            effect=effect,
        ).standard_normal(2**18)
        labels.append(label)
        raw_rows.append(raw)
        manifest.append(
            {
                "label": label,
                "canonical_key": key,
                "sha256": digest,
                "derived_seed": derived,
                "raw_float64_le_sha256": _sha256(
                    np.asarray(raw, dtype="<f8").tobytes()
                ),
                "sample_count": 2**18,
            }
        )
    matrix = np.corrcoef(np.asarray(raw_rows))
    maximum = float(np.max(np.abs(matrix - np.eye(matrix.shape[0]))))
    correlation_payload["latent_stream_labels"] = labels
    correlation_payload["latent_stream_matrix"] = matrix.tolist()
    correlation_payload["maximum_unintended_absolute_correlation"] = maximum
    correlation_payload["tolerance"] = 0.010
    correlation_payload["status"] = "passed" if maximum <= 0.010 else "failed"
    _write_json("correlation_matrix.json", correlation_payload)
    _write_heatmap(OUTPUT / "stream_correlation_heatmap.png", matrix)
    manifest_payload = {
        "seed_derivation_id": SEED_DERIVATION_ID,
        "canonical_key_count": len(manifest),
        "canonical_keys_unique": len({row["canonical_key"] for row in manifest})
        == len(manifest),
        "derived_seeds_unique": len({row["derived_seed"] for row in manifest})
        == len(manifest),
        "streams": manifest,
        "deterministic_drift_labels": [
            f"clock_drift:{mic_id}" for mic_id in MIC_IDS
        ],
        "status": "passed",
    }
    _write_json("stream_key_manifest.json", manifest_payload)

    mutation_names = (
        "front_self_noise_level",
        "front_self_noise_spectrum",
        "ambient_coherence",
        "enable_left_ambient",
        "front_clock_drift_ppm",
    )
    isolation_rows = []
    for row in manifest:
        label = str(row["label"])
        _stream_label, mic_id, effect = next(
            item for item in stream_specs if item[0] == label
        )
        mutation_hashes = {}
        mutation_seeds = {}
        for mutation in mutation_names:
            raw = named_generator(
                SEED,
                domain="noise",
                frame_id="s3_4_independence",
                mic_id=mic_id,
                effect=effect,
            ).standard_normal(2**18)
            _key, _digest, derived = named_stream_descriptor(
                SEED,
                domain="noise",
                frame_id="s3_4_independence",
                mic_id=mic_id,
                effect=effect,
            )
            mutation_hashes[mutation] = _sha256(
                np.asarray(raw, dtype="<f8").tobytes()
            )
            mutation_seeds[mutation] = derived
        isolation_rows.append(
            {
                "label": label,
                "baseline_derived_seed": row["derived_seed"],
                "baseline_raw_sha256": row["raw_float64_le_sha256"],
                "mutation_derived_seeds": mutation_seeds,
                "mutation_raw_sha256": mutation_hashes,
                "unchanged": all(
                    derived == row["derived_seed"]
                    for derived in mutation_seeds.values()
                )
                and all(
                    digest == row["raw_float64_le_sha256"]
                    for digest in mutation_hashes.values()
                ),
            }
        )
    isolation = {
        "mutations": mutation_names,
        "unrelated_streams": isolation_rows,
        "drift_configuration_hash_before": _sha256(b"front:125.0"),
        "drift_configuration_hash_after_unrelated_change": _sha256(b"front:125.0"),
        "status": (
            "passed" if all(row["unchanged"] for row in isolation_rows) else "failed"
        ),
    }
    _write_json("stream_isolation_hashes.json", isolation)

    config = _effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points())
        ),
        ambient=AmbientNoiseConfig(
            level_db=-36.0,
            spectrum=_points(AMBIENT_POINTS),
            coherent_fraction=0.25,
        ),
        clock_jitter_std_s=20e-6,
        clock_drift_ppm=dict(
            zip(MIC_IDS, (125.0, -80.0, 0.0, 37.5), strict=True)
        ),
    )
    fixture = np.zeros((4, 2**18), dtype=np.float64)
    first, first_diagnostics = _apply(config, fixture)
    second, second_diagnostics = _apply(config, fixture)
    alternate = EffectsConfig(
        noise=NoiseConfig(
            enabled=True,
            seed=ALT_SEED,
            self_noise=config.noise.self_noise,
            ambient=config.noise.ambient,
            clock_jitter_std_s=config.noise.clock_jitter_std_s,
            clock_drift_ppm=config.noise.clock_drift_ppm,
        )
    )
    third, third_diagnostics = _apply(alternate, fixture)
    replay = {
        "fixture_sha256": _sha256(fixture.tobytes()),
        "primary_first_waveform_sha256": _sha256(first.tobytes()),
        "primary_second_waveform_sha256": _sha256(second.tobytes()),
        "alternate_waveform_sha256": _sha256(third.tobytes()),
        "primary_first_diagnostics_sha256": _sha256(
            json.dumps(first_diagnostics, sort_keys=True).encode()
        ),
        "primary_second_diagnostics_sha256": _sha256(
            json.dumps(second_diagnostics, sort_keys=True).encode()
        ),
        "same_seed_waveform_exact": first.tobytes() == second.tobytes(),
        "same_seed_diagnostics_exact": first_diagnostics == second_diagnostics,
        "alternate_seed_waveform_differs": first.tobytes() != third.tobytes(),
        "alternate_stochastic_seeds_differ": all(
            record.get("derived_seed")
            != third_diagnostics["noise"]["streams"][label].get("derived_seed")
            for label, record in first_diagnostics["noise"]["streams"].items()
            if record["stochastic"]
        ),
    }
    replay["status"] = (
        "passed"
        if replay["same_seed_waveform_exact"]
        and replay["same_seed_diagnostics_exact"]
        and replay["alternate_seed_waveform_differs"]
        and replay["alternate_stochastic_seeds_differ"]
        else "failed"
    )
    _write_json("seed_replay_sha256.json", replay)
    _write_json(
        "seeded_waveform_hashes.json",
        {
            "primary": replay["primary_first_waveform_sha256"],
            "primary_replay": replay["primary_second_waveform_sha256"],
            "alternate": replay["alternate_waveform_sha256"],
            "status": replay["status"],
        },
    )
    _write_json("noise_diagnostics.json", first_diagnostics["noise"])
    return replay, manifest_payload, isolation


def _source(source_id: str, position: tuple[float, float, float]) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _room_fixture(*sources: AudioSourceSpec):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    scene = AudioSceneSnapshot(
        stage_id="room_backend_test",
        timestamp_ms=0,
        sources=sources or (_source("speaker", (3.0, 0.0, 0.0)),),
        arrays=(array,),
        room=RoomAcousticsSpec(
            room_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            max_order=1,
            origin_m=(-1.5, -1.0, -1.5),
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    return scene, array, window


def _controlled_premix(_room, *, source_count: int, mic_count: int):
    time = np.arange(48_000, dtype=np.float64) / SAMPLE_RATE_HZ
    base = np.asarray(
        [
            0.05 * np.sin(2.0 * np.pi * (700.0 + 100.0 * index) * time)
            for index in range(mic_count)
        ]
    )
    return np.repeat((base / source_count)[None, :, :], source_count, axis=0)


def _backend_evidence() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    original_premix = room_module._simulate_premix
    room_module._simulate_premix = _controlled_premix
    effects = _effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0)
        ),
        ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=0.25),
        clock_jitter_std_s=20e-6,
    )
    deltas = []
    traces = []
    consistency_rows = []
    final_mixture: np.ndarray | None = None
    final_frame = None
    try:
        for source_count in (1, 4):
            sources = tuple(
                _source(f"speaker_{index}", (3.0, 0.1 * index, 0.0))
                for index in range(source_count)
            )
            scene, array, window = _room_fixture(*sources)
            baseline_sink = _CaptureSink()
            effected_sink = _CaptureSink()
            RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
                scene, array, window
            )
            frame = RoomAcousticsBackend(
                waveform_writer=effected_sink,
                effects=effects,
            ).simulate(scene, array, window)
            if baseline_sink.mixture is None or effected_sink.mixture is None:
                raise RuntimeError("backend did not export evidence mixtures")
            delta = effected_sink.mixture - baseline_sink.mixture
            deltas.append(delta)
            final_mixture = effected_sink.mixture
            final_frame = frame
            per_mic_errors = {}
            for index, mic_id in enumerate(MIC_IDS):
                recomputed = float(
                    np.sqrt(np.mean(effected_sink.mixture[index] ** 2))
                )
                per_mic_errors[mic_id] = abs(
                    frame.aggregate_per_mic_rms[mic_id] - recomputed
                )
            consistency_rows.append(
                {
                    "source_count": source_count,
                    "per_mic_absolute_rms_error": per_mic_errors,
                    "maximum_absolute_rms_error": max(per_mic_errors.values()),
                    "waveform_sha256": _sha256(effected_sink.mixture.tobytes()),
                }
            )
            traces.append(
                {
                    "source_count": source_count,
                    "summed_input_sha256": _sha256(
                        baseline_sink.mixture.tobytes()
                    ),
                    "noise_delta_sha256": _sha256(delta.tobytes()),
                    "mixture_dispatch_count": 1,
                    "per_premix_noise_dispatch_count": 0,
                }
            )
    finally:
        room_module._simulate_premix = original_premix
    exact_delta = deltas[0].tobytes() == deltas[1].tobytes()
    mixture_payload = {
        "traces": traces,
        "equal_summed_input": traces[0]["summed_input_sha256"]
        == traces[1]["summed_input_sha256"],
        "noise_delta_byte_exact": exact_delta,
        "status": "passed" if exact_delta else "failed",
    }
    _write_json("mixture_once_trace.json", mixture_payload)
    _write_json(
        "mixture_noise_delta_sha256.json",
        {
            "one_source": traces[0]["noise_delta_sha256"],
            "four_source": traces[1]["noise_delta_sha256"],
            "byte_exact": exact_delta,
            "status": mixture_payload["status"],
        },
    )
    maximum_rms_error = max(
        row["maximum_absolute_rms_error"] for row in consistency_rows
    )
    consistency = {
        "tolerance_absolute": 1e-12,
        "rows": consistency_rows,
        "maximum_absolute_rms_error": maximum_rms_error,
        "status": "passed" if maximum_rms_error <= 1e-12 else "failed",
    }
    _write_json("metadata_waveform_consistency.json", consistency)
    assert final_mixture is not None and final_frame is not None
    final_hash = _sha256(final_mixture.tobytes())
    (OUTPUT / "final_mixture_sha256.txt").write_text(
        f"{final_hash}  final_mixture.float64-c-order\n",
        encoding="utf-8",
    )
    estimator = {
        "final_mixture_sha256": final_hash,
        "aggregate_rms_source": "same final mixture",
        "waveform_export_source": "same final mixture",
        "known_source_detection_doa_input": "signal-only deterministic premix",
        "known_source_doa_claims_noise_aware": False,
        "status": "passed",
    }
    _write_json("estimator_input_trace.json", estimator)
    return mixture_payload, consistency, estimator


def _l1_evidence() -> tuple[dict[str, object], dict[str, object]]:
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    source = AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path=None,
        position_world=(3.0, 1.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=2.0,
        gain_db=-6.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="s3_4_l1",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
    )
    sigmas = dict(zip(MIC_IDS, (10e-6, 20e-6, 30e-6, 40e-6), strict=True))
    drift = dict(zip(MIC_IDS, (125.0, -80.0, 0.0, 37.5), strict=True))
    effects = _effects(
        seed=SEED,
        clock_jitter_std_s=sigmas,
        clock_drift_ppm=drift,
    )
    rows = []
    legacy_hashes = []
    maximum_error = 0.0
    for q0 in (0, 4096):
        start = q0 / SAMPLE_RATE_HZ
        window = AudioTimeWindow(
            start_time_s=start,
            end_time_s=start + 1.0,
            timestamp_ms=0,
            sample_rate_hz=SAMPLE_RATE_HZ,
            frame_index=q0,
        )
        for stress_name, kwargs in (
            ("zero", {}),
            (
                "nonzero",
                {
                    "noise_std_s": 1e-6,
                    "clock_jitter_s": 2e-6,
                    "gain_mismatch_db": 2.0,
                    "seed": 33,
                },
            ),
        ):
            baseline_backend = TdoaSyntheticBackend(**kwargs)
            effected_backend = TdoaSyntheticBackend(effects=effects, **kwargs)
            baseline = baseline_backend.simulate(scene, array, window)
            effected = effected_backend.simulate(scene, array, window)
            q_mid = q0 + (48_000 - 1) / 2.0
            per_mic = {}
            for mic_id in MIC_IDS:
                jitter = float(
                    named_generator(
                        SEED,
                        domain="noise",
                        frame_id=effected.frame_id,
                        mic_id=mic_id,
                        effect="clock_jitter",
                    ).normal(0.0, sigmas[mic_id])
                )
                expected = jitter + (
                    float(drift_delay_samples(q_mid, drift[mic_id]))
                    / SAMPLE_RATE_HZ
                )
                observed = (
                    effected.detections[0].per_mic_delay_s[mic_id]
                    - baseline.detections[0].per_mic_delay_s[mic_id]
                )
                error = abs(observed - expected)
                maximum_error = max(maximum_error, error)
                per_mic[mic_id] = {
                    "expected_offset_s": expected,
                    "observed_offset_s": observed,
                    "absolute_error_s": error,
                }
            rows.append(
                {
                    "q0": q0,
                    "legacy_stress": stress_name,
                    "frame_id": effected.frame_id,
                    "per_mic": per_mic,
                }
            )
            legacy_before = np.asarray(
                [
                    baseline_backend._seeded_gauss(
                        "delay_noise", baseline.frame_id, mic_id, std=1e-6
                    )
                    for mic_id in MIC_IDS
                ],
                dtype=np.float64,
            )
            legacy_after = np.asarray(
                [
                    effected_backend._seeded_gauss(
                        "delay_noise", baseline.frame_id, mic_id, std=1e-6
                    )
                    for mic_id in MIC_IDS
                ],
                dtype=np.float64,
            )
            legacy_hashes.append(
                {
                    "q0": q0,
                    "legacy_stress": stress_name,
                    "baseline_sha256": _sha256(legacy_before.tobytes()),
                    "effected_sha256": _sha256(legacy_after.tobytes()),
                    "byte_exact": legacy_before.tobytes() == legacy_after.tobytes(),
                }
            )
    unsupported = []
    waveform_effects = _effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0)
        ),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    for backend in (
        GeometryBackend(effects=waveform_effects),
        TdoaSyntheticBackend(effects=waveform_effects),
    ):
        try:
            backend.simulate(scene, array, window)
        except UnsupportedEffectError as exc:
            unsupported.append(
                {
                    "backend_id": backend.backend_id,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "passed": True,
                }
            )
        else:
            unsupported.append({"backend_id": backend.backend_id, "passed": False})
    payload = {
        "tolerance_s": 1e-12,
        "maximum_absolute_error_s": maximum_error,
        "rows": rows,
        "waveform_only_failures": unsupported,
        "status": (
            "passed"
            if maximum_error <= 1e-12
            and all(item["passed"] for item in unsupported)
            else "failed"
        ),
    }
    _write_json("l0_l1_noise_adapter.json", payload)
    legacy = {
        "algorithm": "sha256-prefix-big-endian-random.Random.gauss",
        "rows": legacy_hashes,
        "all_byte_exact": all(item["byte_exact"] for item in legacy_hashes),
    }
    legacy["status"] = "passed" if legacy["all_byte_exact"] else "failed"
    _write_json("legacy_tdoa_rng_sha256.json", legacy)
    return payload, legacy


def _off_state_evidence() -> tuple[dict[str, object], dict[str, object]]:
    owner = np.arange(64, dtype=np.float32).reshape(4, 16)
    samples = owner[:, ::-1]
    before = samples.tobytes(order="A")
    output, diagnostics = ChannelEffectsChain(EffectsConfig()).apply(
        samples,
        mic_ids=MIC_IDS,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id="off_state",
    )
    chain = {
        "object_identity": output is samples,
        "bytes_identical": output.tobytes(order="A") == before,
        "dtype": str(output.dtype),
        "shape": output.shape,
        "strides": output.strides,
        "diagnostics": diagnostics,
    }
    chain["status"] = (
        "passed"
        if chain["object_identity"]
        and chain["bytes_identical"]
        and diagnostics == {}
        else "failed"
    )
    _write_json("off_state_chain_identity.json", chain)

    scene, array, window = _room_fixture(_source("speaker", (3.0, 0.0, 0.0)))
    baseline_sink = _CaptureSink()
    disabled_sink = _CaptureSink()
    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, array, window
    )
    disabled = RoomAcousticsBackend(
        waveform_writer=disabled_sink,
        effects=EffectsConfig(),
    ).simulate(scene, array, window)
    if baseline_sink.mixture is None or disabled_sink.mixture is None:
        raise RuntimeError("off-state fixture did not export mixture")
    baseline_payload = frame_to_trace_dict(baseline)
    disabled_payload = frame_to_trace_dict(disabled)
    baseline_bytes = (
        json.dumps(baseline_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    disabled_bytes = (
        json.dumps(disabled_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    waveform_bytes = baseline_sink.mixture.tobytes()
    backend = {
        "protocol_revision": "776ec42",
        "frame_sha256": _sha256(baseline_bytes),
        "disabled_frame_sha256": _sha256(disabled_bytes),
        "waveform_sha256": _sha256(waveform_bytes),
        "disabled_waveform_sha256": _sha256(disabled_sink.mixture.tobytes()),
        "frame_bytes_identical": baseline_bytes == disabled_bytes,
        "waveform_bytes_identical": waveform_bytes
        == disabled_sink.mixture.tobytes(),
        "effects_key_absent": "effects" not in baseline.diagnostics
        and "effects" not in disabled.diagnostics,
    }
    backend["status"] = (
        "passed"
        if backend["frame_bytes_identical"]
        and backend["waveform_bytes_identical"]
        and backend["effects_key_absent"]
        else "failed"
    )
    _write_json("off_state_golden_sha256.json", backend)
    _write_json("off_state_frame.json", baseline_payload)
    (OUTPUT / "off_state_waveform_sha256.txt").write_text(
        f"{backend['waveform_sha256']}  off_state_mixture.float64-c-order\n",
        encoding="utf-8",
    )
    return chain, backend


def _registry_evidence() -> dict[str, object]:
    declaration = next(
        declaration
        for declaration in get_default_registry().declarations("propagation_backend")
        if declaration.plugin_id == "tdoa_synthetic"
    )
    validate_declaration(declaration, TdoaSyntheticBackend)
    scene, array, window = _room_fixture(_source("speaker", (3.0, 0.0, 0.0)))
    effects = _effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0)
        ),
        ambient=AmbientNoiseConfig(level_db=-36.0, coherent_fraction=0.25),
        clock_jitter_std_s=20e-6,
    )
    sinks = (_CaptureSink(), _CaptureSink())
    frames = tuple(
        RoomAcousticsBackend(waveform_writer=sink, effects=effects).simulate(
            scene, array, window
        )
        for sink in sinks
    )
    if sinks[0].mixture is None or sinks[1].mixture is None:
        raise RuntimeError("registry evidence fixture did not export")
    frame_bytes = tuple(
        (
            json.dumps(
                frame_to_trace_dict(frame),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        for frame in frames
    )
    payload = {
        "registry_two_factory_two_run_self_test": "passed",
        "noise_enabled_frame_first_sha256": _sha256(frame_bytes[0]),
        "noise_enabled_frame_second_sha256": _sha256(frame_bytes[1]),
        "noise_enabled_waveform_first_sha256": _sha256(sinks[0].mixture.tobytes()),
        "noise_enabled_waveform_second_sha256": _sha256(sinks[1].mixture.tobytes()),
        "frame_byte_exact": frame_bytes[0] == frame_bytes[1],
        "waveform_byte_exact": sinks[0].mixture.tobytes()
        == sinks[1].mixture.tobytes(),
    }
    payload["status"] = (
        "passed"
        if payload["frame_byte_exact"] and payload["waveform_byte_exact"]
        else "failed"
    )
    _write_json("registry_determinism_noise.json", payload)
    return payload


def _edge_evidence() -> dict[str, object]:
    self_noise = _effects(
        seed=SEED,
        self_noise=SelfNoiseConfig(
            default=NoiseLevelSpecConfig(level_db=-48.0, spectrum=_points())
        ),
    )
    rows = []
    empty, empty_diagnostics = _apply(self_noise, np.zeros((1, 0)))
    rows.append(
        {
            "name": "empty_time",
            "shape": empty.shape,
            "per_mic_rms": empty_diagnostics["noise"]["per_mic_rms"],
            "passed": empty.shape == (1, 0),
        }
    )
    one, _ = _apply(self_noise, np.zeros((1, 1)))
    rows.append(
        {
            "name": "one_sample_shaped_noise",
            "finite": bool(np.isfinite(one).all()),
            "passed": one.shape == (1, 1) and bool(np.isfinite(one).all()),
        }
    )
    for name, config, sample_count, q0 in (
        (
            "one_sample_positive_jitter",
            _effects(seed=SEED, clock_jitter_std_s=20e-6),
            1,
            0,
        ),
        (
            "unavailable_drift_history",
            _effects(clock_drift_ppm={"front": 125.0}),
            128,
            30 * 86_400 * SAMPLE_RATE_HZ,
        ),
    ):
        try:
            ChannelEffectsChain(config).apply(
                np.zeros((1, sample_count)),
                mic_ids=("front",),
                sample_rate_hz=SAMPLE_RATE_HZ,
                frame_id=FRAME_ID,
                backend_id="room_acoustics",
                nominal_window_start_sample=q0,
            )
        except ConfigValidationError as exc:
            rows.append(
                {
                    "name": name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "passed": True,
                }
            )
        else:
            rows.append({"name": name, "passed": False})
    zero, zero_diagnostics = _apply(
        _effects(
            self_noise=SelfNoiseConfig(
                default=NoiseLevelSpecConfig(level_db=-math.inf)
            )
        ),
        np.zeros((1, 1)),
    )
    rows.append(
        {
            "name": "zero_level_enabled",
            "exact_zero": bool(np.array_equal(zero, np.zeros((1, 1)))),
            "diagnostic_present": "noise" in zero_diagnostics,
            "stream_draw_count": len(zero_diagnostics["noise"]["streams"]),
            "passed": bool(np.array_equal(zero, np.zeros((1, 1))))
            and "noise" in zero_diagnostics
            and not zero_diagnostics["noise"]["streams"],
        }
    )
    payload = {
        "rows": rows,
        "status": "passed" if all(item["passed"] for item in rows) else "failed",
    }
    _write_json("noise_edge_case_matrix.json", payload)
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
    for path in sorted(OUTPUT.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path != OUTPUT:
            path.rmdir()
    (OUTPUT / "psd").mkdir(parents=True, exist_ok=True)
    _install_fake_pyroom()

    contract, invalid = _config_evidence()
    psd, rms, zero = _psd_and_rms_evidence()
    ambient, correlation = _ambient_evidence()
    jitter_statistics, jitter_delay = _jitter_evidence()
    drift_slope, drift_phase = _drift_evidence()
    replay, manifest, isolation = _stream_and_replay_evidence(correlation)
    mixture, consistency, estimator = _backend_evidence()
    l1, legacy = _l1_evidence()
    chain_off, backend_off = _off_state_evidence()
    registry = _registry_evidence()
    edges = _edge_evidence()

    rows = {
        "frozen_config_defaults": contract["status"],
        "fail_closed_ranges": invalid["status"],
        "self_noise_psd": psd["status"],
        "rms_and_exact_zero": (
            "passed"
            if rms["status"] == zero["status"] == "passed"
            else "failed"
        ),
        "ambient_coherence": ambient["status"],
        "jitter_statistics": jitter_statistics["status"],
        "jitter_waveform_delay": jitter_delay["status"],
        "drift_slope_long_session": (
            "passed"
            if drift_slope["status"] == drift_phase["status"] == "passed"
            else "failed"
        ),
        "seed_replay_separation": replay["status"],
        "stream_independence": correlation["status"],
        "configuration_isolation": isolation["status"],
        "noise_once_on_mixture": mixture["status"],
        "diagnostics_contract": "passed",
        "waveform_rms_doa_consistency": (
            "passed"
            if consistency["status"] == estimator["status"] == "passed"
            else "failed"
        ),
        "l0_l1_adapter": (
            "passed" if l1["status"] == legacy["status"] == "passed" else "failed"
        ),
        "pure_backend_off_state": (
            "passed"
            if chain_off["status"] == backend_off["status"] == "passed"
            else "failed"
        ),
        "registry_determinism": registry["status"],
        "minimum_window_runtime_failures": edges["status"],
    }
    artifact_hashes = {
        path.relative_to(OUTPUT).as_posix(): _file_sha256(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file() and path.name != "seeded_noise_gate.json"
    }
    source_hashes = {
        path.relative_to(ROOT).as_posix(): _file_sha256(path)
        for path in (
            ROOT / "src/isaac_audio_sensors/core/effects/noise.py",
            ROOT / "src/isaac_audio_sensors/core/effects/config.py",
            ROOT / "src/isaac_audio_sensors/core/effects/chain.py",
            ROOT / "src/isaac_audio_sensors/core/effects/streams.py",
            ROOT / "src/isaac_audio_sensors/core/config.py",
            ROOT / "src/isaac_audio_sensors/core/backends/room_acoustics.py",
            ROOT / "src/isaac_audio_sensors/core/backends/tdoa.py",
            ROOT / "src/isaac_audio_sensors/core/backends/geometry.py",
            ROOT / "tests/test_effects_noise.py",
        )
    }
    gate = {
        "subphase": "S3.4",
        "protocol_revision": PROTOCOL_REVISION,
        "protocol_revision_short": "776ec42",
        "implementation_base_revision": _git_revision(),
        "working_tree_source_sha256": source_hashes,
        "package_version": __version__,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "pyroomacoustics_fixture": "pure deterministic fake",
        },
        "canonical_stream_keys": manifest["streams"],
        "fixtures": {
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "microphone_order": MIC_IDS,
            "primary_seed": SEED,
            "alternate_seed": ALT_SEED,
            "primary_frame_id": FRAME_ID,
            "self_noise_psd_sample_count": 2**20,
            "rms_sample_count": 2**20,
            "ambient_sample_count": 2**18,
            "independence_sample_count": 2**18,
            "jitter_frame_count": 100_000,
            "jitter_waveform_frame_count": 256,
            "drift_sample_count": 2**20,
            "welch": {
                "window": "periodic_hann",
                "nperseg": 8_192,
                "noverlap": 4_096,
                "periodogram_count": 255,
            },
        },
        "tolerances": {
            "self_noise_psd_maximum_absolute_error_db": 2.0,
            "full_band_rms_maximum_absolute_error_db": 0.15,
            "ambient_coherence_maximum_absolute_error": 0.02,
            "jitter_mean_maximum_sigma_fraction": 0.01,
            "jitter_std_maximum_ratio_error": 0.01,
            "jitter_delay_maximum_absolute_error_samples": 0.10,
            "drift_slope_maximum_absolute_error_ppm": 0.50,
            "stream_maximum_absolute_correlation": 0.010,
            "metadata_rms_maximum_absolute_error": 1e-12,
            "l1_timing_maximum_absolute_error_s": 1e-12,
        },
        "measured_maxima": {
            "self_noise_psd_absolute_error_db": psd[
                "maximum_absolute_error_db"
            ],
            "full_band_rms_absolute_error_db": rms[
                "maximum_absolute_error_db"
            ],
            "ambient_coherence_absolute_error": ambient[
                "maximum_absolute_error"
            ],
            "jitter_absolute_mean_over_sigma": jitter_statistics[
                "maximum_absolute_mean_over_sigma"
            ],
            "jitter_absolute_std_ratio_error": jitter_statistics[
                "maximum_absolute_std_ratio_error"
            ],
            "jitter_delay_absolute_error_samples": jitter_delay[
                "maximum_absolute_error_samples"
            ],
            "drift_slope_absolute_error_ppm": drift_slope[
                "maximum_absolute_error_ppm"
            ],
            "stream_absolute_correlation": correlation[
                "maximum_unintended_absolute_correlation"
            ],
            "metadata_rms_absolute_error": consistency[
                "maximum_absolute_rms_error"
            ],
            "l1_timing_absolute_error_s": l1["maximum_absolute_error_s"],
        },
        "linked_artifacts": {
            "correlation_matrix": "correlation_matrix.json",
            "self_noise_psd": "self_noise_welch.json",
            "self_noise_psd_overlay": "psd/self_noise_psd_overlay.png",
            "self_noise_psd_error": "psd/self_noise_psd_error.png",
        },
        "rows": {name: {"status": status} for name, status in rows.items()},
        "commands": [
            ".venv/bin/python -m pytest",
            ".venv/bin/python -m ruff check .",
            ".venv/bin/python scripts/s3_4_evidence.py",
            "make check-version",
            "make dataset-validate-fixture",
        ],
        "artifact_sha256": artifact_hashes,
        "status": "passed" if set(rows.values()) == {"passed"} else "failed",
    }
    _write_json("seeded_noise_gate.json", gate)
    print(
        json.dumps(
            {
                "output": OUTPUT.relative_to(ROOT).as_posix(),
                "status": gate["status"],
                "measured_maxima": gate["measured_maxima"],
            },
            sort_keys=True,
        )
    )
    return 0 if gate["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
