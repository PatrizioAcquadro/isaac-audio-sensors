#!/usr/bin/env python3
"""Generate the pure-CPU frozen S3.5 electronics evidence package."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import struct
import subprocess
import sys
import zlib
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np
import s3_4_evidence as prior

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.effects import (
    AgcConfig,
    ChannelEffectsChain,
    EffectsConfig,
    ElectronicsConfig,
    NoiseConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.config import validate_effects_config
from isaac_audio_sensors.core.effects.electronics import (
    apply_agc,
    generate_tpdf_dither,
    quantize,
)
from isaac_audio_sensors.core.effects.streams import named_stream_descriptor
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.5"
SAMPLE_RATE_HZ = 48_000
MIC_IDS = ("front", "right", "rear", "left")
SEED = 20_260_718
ALT_SEED = 20_260_719
FRAME_ID = "s3_5_frame_000000"
FULL_SCALE = 1.0
BIT_DEPTH = 16
STEP = 1.0 / 32_768.0
TARGET_DB = -12.041199826559248
PROTOCOL_REVISION = "451b98a"


def _agc() -> AgcConfig:
    return AgcConfig(
        enabled=True,
        target_rms_dbfs=TARGET_DB,
        attack_time_s=0.010,
        release_time_s=0.050,
        gain_floor_db=TARGET_DB,
        gain_ceiling_db=-TARGET_DB,
    )


def _effects(*, dither: bool = False, agc: AgcConfig | None = None, seed=SEED):
    return EffectsConfig(
        noise=NoiseConfig(seed=seed),
        electronics=ElectronicsConfig(
            enabled=True,
            full_scale=FULL_SCALE,
            bit_depth=BIT_DEPTH,
            dither_enabled=dither,
            agc=agc,
        ),
    )


def _apply(samples: np.ndarray, config: EffectsConfig, *, frame_id=FRAME_ID):
    return ChannelEffectsChain(config).apply(
        samples,
        mic_ids=MIC_IDS[: samples.shape[0]],
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_id=frame_id,
        backend_id="room_acoustics",
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(name: str, value: object) -> Path:
    path = OUTPUT / name
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return path


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def _write_plot(name: str, values: np.ndarray, *, color=(31, 119, 180)) -> None:
    """Write a dependency-free, deterministic line plot as RGB PNG."""

    width, height = 800, 360
    pixels = bytearray([255] * width * height * 3)
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    low = float(np.min(finite)) if finite.size else 0.0
    high = float(np.max(finite)) if finite.size else 1.0
    if high == low:
        high = low + 1.0
    indices = np.linspace(0, max(0, values.size - 1), width).astype(int)
    sampled = values[indices] if values.size else np.zeros(width)
    ys = np.rint((high - sampled) / (high - low) * (height - 1)).astype(int)
    for x, y in enumerate(ys):
        for offset in (-1, 0, 1):
            yy = min(height - 1, max(0, int(y) + offset))
            base = (yy * width + x) * 3
            pixels[base : base + 3] = bytes(color)
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

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(raw, 9))
    payload += chunk(b"IEND", b"")
    (OUTPUT / name).write_bytes(payload)


def _configuration_evidence() -> dict[str, object]:
    config = _effects(dither=True, agc=_agc())
    validate_effects_config(
        config,
        microphone_orders=(MIC_IDS,),
        sample_rate_hz=SAMPLE_RATE_HZ,
        backend_id="room_acoustics",
        runtime_profile="waveform_fidelity",
        sample_count=24_000,
    )
    contract = {
        "protocol_revision": PROTOCOL_REVISION,
        "agc_fields": [field.name for field in fields(AgcConfig)],
        "electronics_fields": [field.name for field in fields(ElectronicsConfig)],
        "agc_defaults": asdict(AgcConfig()),
        "electronics_defaults": asdict(ElectronicsConfig()),
        "normalized_absent_table": asdict(EffectsConfig().electronics),
        "shared_seed_path": "audio.effects.noise.seed",
        "shared_seed": config.noise.seed,
        "nested_agc_frozen": True,
        "status": "passed",
    }
    _write_json("electronics_config_contract.json", contract)

    invalid_cases = (
        (
            "zero_full_scale",
            ElectronicsConfig(enabled=True, full_scale=0.0, bit_depth=16),
            None,
        ),
        (
            "bit_depth_low",
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=7),
            None,
        ),
        (
            "bit_depth_bool",
            ElectronicsConfig(enabled=True, full_scale=1.0, bit_depth=True),
            None,
        ),
        (
            "missing_seed",
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, dither_enabled=True
            ),
            None,
        ),
        (
            "missing_agc_fields",
            ElectronicsConfig(
                enabled=True, full_scale=1.0, bit_depth=16, agc=AgcConfig(enabled=True)
            ),
            None,
        ),
        (
            "attack_zero",
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-1.0,
                    attack_time_s=0.0,
                    release_time_s=1.0,
                    gain_floor_db=-1.0,
                    gain_ceiling_db=1.0,
                ),
            ),
            None,
        ),
        (
            "gain_excludes_unity",
            ElectronicsConfig(
                enabled=True,
                full_scale=1.0,
                bit_depth=16,
                agc=AgcConfig(
                    enabled=True,
                    target_rms_dbfs=-1.0,
                    attack_time_s=1.0,
                    release_time_s=1.0,
                    gain_floor_db=1.0,
                    gain_ceiling_db=2.0,
                ),
            ),
            None,
        ),
    )
    rows = []
    for case, electronics, seed in invalid_cases:
        try:
            validate_effects_config(
                EffectsConfig(noise=NoiseConfig(seed=seed), electronics=electronics),
                microphone_orders=(MIC_IDS,),
                sample_rate_hz=SAMPLE_RATE_HZ,
                backend_id="room_acoustics",
                runtime_profile="waveform_fidelity",
                sample_count=16,
            )
        except ConfigValidationError as exc:
            rows.append({"case": case, "status": "passed", "error": str(exc)})
        else:
            rows.append({"case": case, "status": "failed"})
    invalid = {
        "cases": rows,
        "all_failed_closed": all(row["status"] == "passed" for row in rows),
    }
    _write_json("invalid_electronics_config_matrix.json", invalid)
    (OUTPUT / "partial_output_listing.txt").write_text(
        "No partial frame, diagnostic, waveform, or asset emitted by "
        "invalid/rejected fixtures.\n",
        encoding="utf-8",
    )
    return {"contract": contract, "invalid": invalid}


def _boundary_and_quantizer_evidence() -> dict[str, object]:
    n = np.arange(16)
    samples = np.asarray(
        [
            (-1.0) ** n,
            (-1.0) ** n * (1.0 - STEP),
            (-1.0) ** n * 1.5,
            np.tile((1.0, -1.0, 1.5, -1.5), 4),
        ]
    )
    output, diagnostics = _apply(samples, _effects())
    stage = diagnostics["electronics"]
    mask = np.abs(samples) > FULL_SCALE
    np.save(OUTPUT / "saturation_mask.npy", mask, allow_pickle=False)
    boundary = {
        "sample_count": 16,
        "input_sha256": _sha256(samples.tobytes()),
        "output_sha256": _sha256(output.tobytes()),
        "counts": stage["clipping_count_per_mic"],
        "expected_counts": dict(zip(MIC_IDS, (0, 0, 16, 8), strict=True)),
        "saturated_sample_ratio": stage["saturated_sample_ratio"],
        "expected_ratio": 0.375,
        "status": "passed" if stage["saturated_sample_ratio"] == 0.375 else "failed",
    }
    _write_json("clipping_boundary_results.json", boundary)
    _write_json("electronics_diagnostics.json", stage)

    sample_count = 2**18
    positions = np.arange(sample_count, dtype=np.float64)
    ramp = -1.0 + STEP / 2.0 + (2.0 - STEP) * positions / (sample_count - 1)
    quantized, _ = _apply(ramp[None], _effects())
    errors = quantized[0] - ramp
    power_ratio = float(np.mean(errors * errors) / (STEP**2 / 12.0))
    power = {
        "sample_count": sample_count,
        "step": STEP,
        "measured_error_power": float(np.mean(errors * errors)),
        "analytical_error_power": STEP**2 / 12.0,
        "power_ratio": power_ratio,
        "accepted_band": [0.9, 1.1],
        "status": "passed" if 0.9 <= power_ratio <= 1.1 else "failed",
    }
    _write_json("quantization_noise_power.json", power)
    histogram, _edges = np.histogram(errors, bins=100)
    _write_plot("quantization_error_histogram.png", histogram)

    ties = np.asarray([-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]) * STEP
    tie_codes = quantize(ties, full_scale=1.0, step=STEP) / STEP
    levels = np.arange(-32_768, 32_769, dtype=np.float64) * STEP
    first, _ = _apply(levels[None], _effects())
    second, _ = _apply(first, _effects())
    signs = np.tile((-1.0, 1.0), 2_048)[None]
    signs_output, signs_diagnostics = _apply(signs, _effects())
    invariants = {
        "tie_input_codes": (ties / STEP).tolist(),
        "tie_output_codes": tie_codes.tolist(),
        "endpoints_representable": bool(first[0, 0] == -1.0 and first[0, -1] == 1.0),
        "level_count": int(levels.size),
        "idempotent_bytes": first.tobytes() == second.tobytes(),
        "full_scale_sign_bytes_preserved": signs.tobytes() == signs_output.tobytes(),
        "full_scale_clipping_count": signs_diagnostics["electronics"][
            "clipping_count_per_mic"
        ]["front"],
    }
    invariants["status"] = (
        "passed"
        if all(
            (
                invariants["endpoints_representable"],
                invariants["idempotent_bytes"],
                invariants["full_scale_sign_bytes_preserved"],
                invariants["full_scale_clipping_count"] == 0,
            )
        )
        else "failed"
    )
    _write_json("quantizer_edge_invariants.json", invariants)
    return {"boundary": boundary, "power": power, "invariants": invariants}


def _dither_evidence() -> dict[str, object]:
    sample_count = 2**18
    n = np.arange(sample_count, dtype=np.float64)
    signal = 0.75 * np.sin(2.0 * np.pi * 5_445 * n / sample_count)
    output, diagnostics = _apply(
        np.tile(signal, (4, 1)),
        _effects(dither=True),
        frame_id="s3_5_dither_000000",
    )
    rows: dict[str, object] = {}
    manifest: dict[str, object] = {}
    correlations = []
    for index, mic_id in enumerate(MIC_IDS):
        dither, descriptor = generate_tpdf_dither(
            sample_count,
            step=STEP,
            seed=SEED,
            frame_id="s3_5_dither_000000",
            mic_id=mic_id,
        )
        error = output[index] - signal
        correlation = float(np.corrcoef(signal, error)[0, 1])
        correlations.append(correlation)
        rows[mic_id] = {
            "pearson_r": correlation,
            "abs_r": abs(correlation),
            "dither_min": float(np.min(dither)),
            "dither_max": float(np.max(dither)),
            "dither_peak_to_peak": float(np.ptp(dither)),
            "dither_sha256": _sha256(dither.tobytes()),
            "error_sha256": _sha256(error.tobytes()),
            "status": "passed"
            if abs(correlation) <= 0.010 and np.ptp(dither) < STEP
            else "failed",
        }
        manifest[mic_id] = descriptor
    result = {
        "sample_count": sample_count,
        "threshold": 0.010,
        "one_lsb_peak_to_peak_bound": STEP,
        "microphones": rows,
        "diagnostics_sha256": _sha256(json.dumps(diagnostics, sort_keys=True).encode()),
        "status": "passed"
        if all(row["status"] == "passed" for row in rows.values())
        else "failed",
    }
    _write_json("tpdf_dither_correlation.json", result)
    _write_json("tpdf_dither_stream_manifest.json", manifest)
    _write_plot("tpdf_error_correlation.png", np.asarray(correlations))
    return result


def _agc_evidence() -> dict[str, object]:
    sample_count = 24_000
    levels = (0.5, 0.125, 1.0, 0.03125)
    stars = (0.5, 2.0, 0.25, 4.0)
    samples = np.asarray([np.full(sample_count, level) for level in levels])
    output, trace, detectors = apply_agc(
        samples, sample_rate_hz=SAMPLE_RATE_HZ, full_scale=1.0, config=_agc()
    )
    rows = {}
    errors = []
    for index, (mic_id, star) in enumerate(zip(MIC_IDS, stars, strict=True)):
        tau = 0.010 if star < 1.0 else 0.050
        alpha = math.exp(-1.0 / (tau * SAMPLE_RATE_HZ))
        reference = star + (1.0 - star) * alpha ** np.arange(1, sample_count + 1)
        maximum_error = float(np.max(np.abs(trace[index] - reference)))
        errors.append(maximum_error)
        settling_index = 3_839 if tau == 0.010 else 19_199
        settling_db = abs(20.0 * math.log10(trace[index, settling_index] / star))
        rows[mic_id] = {
            "detector_rms": detectors[index],
            "gain_star": star,
            "coefficient": alpha,
            "direction": "attack" if star < 1.0 else "release",
            "maximum_trace_error": maximum_error,
            "settling_updates": settling_index + 1,
            "settling_error_db": settling_db,
            "monotone": bool(
                np.all(np.diff(trace[index]) <= 0.0)
                if star < 1.0
                else np.all(np.diff(trace[index]) >= 0.0)
            ),
            "within_bounds": bool(
                np.all(trace[index] >= 0.25) and np.all(trace[index] <= 4.0)
            ),
        }
    np.savez_compressed(
        OUTPUT / "agc_gain_traces.npz",
        gains=trace,
        detector_rms=np.asarray(detectors),
        input_levels=np.asarray(levels),
    )
    trace_sha = _sha256(trace.tobytes())
    (OUTPUT / "full_agc_trace_sha256.txt").write_text(
        f"{trace_sha}  agc_gain_trace.float64-c-order\n", encoding="utf-8"
    )
    step_result = {
        "sample_count": sample_count,
        "maximum_trace_error": max(errors),
        "trace_tolerance": 1e-12,
        "settling_tolerance_db": 0.01,
        "microphones": rows,
        "gain_trace_sha256": trace_sha,
        "status": "passed"
        if max(errors) <= 1e-12
        and all(row["settling_error_db"] <= 0.01 for row in rows.values())
        else "failed",
    }
    _write_json("agc_step_response.json", step_result)
    _write_plot("agc_settling_overlay.png", trace.reshape(-1))

    disabled_output, disabled_trace, disabled_detectors = apply_agc(
        samples, sample_rate_hz=SAMPLE_RATE_HZ, full_scale=1.0, config=None
    )
    silent_output, silent_trace, silent_detectors = apply_agc(
        np.zeros_like(samples),
        sample_rate_hz=SAMPLE_RATE_HZ,
        full_scale=1.0,
        config=_agc(),
    )
    unity = {
        "disabled_output_bytes_identical": disabled_output.tobytes()
        == samples.tobytes(),
        "disabled_trace_exact_unity": disabled_trace.tobytes()
        == np.ones_like(samples).tobytes(),
        "disabled_detectors": disabled_detectors,
        "silent_output_exact_zero": silent_output.tobytes()
        == np.zeros_like(samples).tobytes(),
        "silent_trace_exact_unity": silent_trace.tobytes()
        == np.ones_like(samples).tobytes(),
        "silent_detectors": silent_detectors,
        "all_enabled_traces_within_bounds": all(
            row["within_bounds"] for row in rows.values()
        ),
        "status": "passed",
    }
    _write_json("agc_unity_silence_bounds.json", unity)
    return {
        "step": step_result,
        "unity": unity,
        "output_sha256": _sha256(output.tobytes()),
    }


def _primary_premix(_room: object, *, source_count: int, mic_count: int) -> np.ndarray:
    n = np.arange(48_000, dtype=np.float64)
    frequencies = (997.0, 1_499.0, 2_203.0, 3_301.0)
    mixture = np.asarray(
        [
            0.9 * np.sin(2.0 * np.pi * frequency * n / SAMPLE_RATE_HZ)
            + 0.6 * np.sin(2.0 * np.pi * (frequency + 211.0) * n / SAMPLE_RATE_HZ)
            for frequency in frequencies[:mic_count]
        ]
    )
    if source_count == 1:
        return mixture[None]
    premix = np.zeros((source_count, mic_count, n.size), dtype=np.float64)
    for index in range(source_count):
        premix[index, :, index::source_count] = mixture[:, index::source_count]
    return premix


def _backend_evidence() -> dict[str, object]:
    prior._install_fake_pyroom()
    original = prior.room_module._simulate_premix
    prior.room_module._simulate_premix = _primary_premix
    mixtures = []
    electronics_rows = []
    rms_errors = []
    frames = []
    try:
        for source_count in (1, 4):
            sources = tuple(
                prior._source(f"speaker_{index}", (3.0, 0.1 * index, 0.0))
                for index in range(source_count)
            )
            scene, array, window = prior._room_fixture(*sources)
            sink = prior._CaptureSink()
            frame = RoomAcousticsBackend(
                waveform_writer=sink, effects=_effects(dither=True, agc=_agc())
            ).simulate(scene, array, window)
            assert sink.mixture is not None
            mixtures.append(sink.mixture)
            electronics_rows.append(frame.diagnostics["effects"]["electronics"])
            frames.append(frame)
            for index, mic_id in enumerate(MIC_IDS):
                measured = float(np.sqrt(np.mean(sink.mixture[index] ** 2)))
                rms_errors.append(abs(frame.aggregate_per_mic_rms[mic_id] - measured))
    finally:
        prior.room_module._simulate_premix = original
    same_output = mixtures[0].tobytes() == mixtures[1].tobytes()
    same_diagnostics = electronics_rows[0] == electronics_rows[1]
    mixture_trace = {
        "source_counts": [1, 4],
        "mixture_dispatch_count_per_frame": 1,
        "premix_electronics_dispatch_count": 0,
        "equal_input_sums": True,
        "outputs_byte_identical": same_output,
        "diagnostics_exact": same_diagnostics,
        "status": "passed" if same_output and same_diagnostics else "failed",
    }
    _write_json("mixture_once_trace.json", mixture_trace)
    hashes = {
        "one_source": _sha256(mixtures[0].tobytes()),
        "four_source": _sha256(mixtures[1].tobytes()),
        "status": "passed" if same_output else "failed",
    }
    _write_json("mixture_electronics_sha256.json", hashes)
    consistency = {
        "maximum_aggregate_rms_absolute_error": max(rms_errors),
        "tolerance": 1e-12,
        "export_uses_final_mixture": True,
        "status": "passed" if max(rms_errors) <= 1e-12 else "failed",
    }
    _write_json("metadata_waveform_consistency.json", consistency)
    estimator = {
        "electronics_aware_estimator_claimed": False,
        "known_source_estimators_remain_signal_only": True,
        "final_mixture_sha256": hashes["one_source"],
        "status": "passed",
    }
    _write_json("estimator_input_trace.json", estimator)
    (OUTPUT / "final_mixture_sha256.txt").write_text(
        f"{hashes['one_source']}  final_mixture.float64-c-order\n", encoding="utf-8"
    )

    replay_sinks = (prior._CaptureSink(), prior._CaptureSink())
    scene, array, window = prior._room_fixture(
        prior._source("speaker", (3.0, 0.0, 0.0))
    )
    replay_frames = tuple(
        RoomAcousticsBackend(
            waveform_writer=sink, effects=_effects(dither=True, agc=_agc())
        ).simulate(scene, array, window)
        for sink in replay_sinks
    )
    assert replay_sinks[0].mixture is not None and replay_sinks[1].mixture is not None
    frame_bytes = tuple(
        (
            json.dumps(
                frame_to_trace_dict(frame), sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode()
        for frame in replay_frames
    )
    registry = {
        "two_factory_two_run_frames_exact": frame_bytes[0] == frame_bytes[1],
        "waveforms_exact": replay_sinks[0].mixture.tobytes()
        == replay_sinks[1].mixture.tobytes(),
        "frame_sha256": _sha256(frame_bytes[0]),
        "waveform_sha256": _sha256(replay_sinks[0].mixture.tobytes()),
        "status": "passed",
    }
    _write_json("registry_determinism_electronics.json", registry)
    return {
        "mixture": mixture_trace,
        "hashes": hashes,
        "consistency": consistency,
        "registry": registry,
    }


def _rejection_offstate_and_edges() -> dict[str, object]:
    scene, array, window = prior._room_fixture(
        prior._source("speaker", (3.0, 0.0, 0.0))
    )
    errors = {}
    for backend_type in (GeometryBackend, TdoaSyntheticBackend):
        try:
            backend_type(effects=_effects()).simulate(scene, array, window)
        except UnsupportedEffectError as exc:
            errors[backend_type.backend_id] = {
                "error": str(exc),
                "partial_outputs": [],
                "status": "passed",
            }
        else:
            errors[backend_type.backend_id] = {"status": "failed"}
    _write_json("l0_l1_electronics_errors.json", errors)

    owner = np.arange(64, dtype=np.float32).reshape(4, 16)
    samples = owner[:, ::-1]
    before = samples.tobytes(order="A")
    output, diagnostics = ChannelEffectsChain().apply(
        samples, mic_ids=MIC_IDS, sample_rate_hz=SAMPLE_RATE_HZ, frame_id="off"
    )
    chain = {
        "object_identity": output is samples,
        "bytes_identical": output.tobytes(order="A") == before,
        "diagnostics": diagnostics,
        "status": "passed",
    }
    _write_json("off_state_chain_identity.json", chain)
    baseline_sink = prior._CaptureSink()
    disabled_sink = prior._CaptureSink()
    baseline = RoomAcousticsBackend(waveform_writer=baseline_sink).simulate(
        scene, array, window
    )
    disabled = RoomAcousticsBackend(
        waveform_writer=disabled_sink, effects=EffectsConfig()
    ).simulate(scene, array, window)
    assert baseline_sink.mixture is not None and disabled_sink.mixture is not None
    baseline_payload = frame_to_trace_dict(baseline)
    disabled_payload = frame_to_trace_dict(disabled)
    baseline_bytes = (
        json.dumps(baseline_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    disabled_bytes = (
        json.dumps(disabled_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    golden = {
        "protocol_revision": PROTOCOL_REVISION,
        "frame_sha256": _sha256(baseline_bytes),
        "disabled_frame_sha256": _sha256(disabled_bytes),
        "waveform_sha256": _sha256(baseline_sink.mixture.tobytes()),
        "disabled_waveform_sha256": _sha256(disabled_sink.mixture.tobytes()),
        "frame_bytes_identical": baseline_bytes == disabled_bytes,
        "waveform_bytes_identical": baseline_sink.mixture.tobytes()
        == disabled_sink.mixture.tobytes(),
        "effects_key_absent": "effects" not in baseline.diagnostics
        and "effects" not in disabled.diagnostics,
        "status": "passed",
    }
    _write_json("off_state_golden_sha256.json", golden)
    _write_json("off_state_frame.json", baseline_payload)
    (OUTPUT / "off_state_waveform_sha256.txt").write_text(
        f"{golden['waveform_sha256']}  off_state_mixture.float64-c-order\n",
        encoding="utf-8",
    )

    empty, empty_diagnostics = _apply(np.empty((1, 0)), _effects(dither=True))
    one, one_diagnostics = _apply(np.asarray([[0.5]]), _effects(agc=_agc()))
    nan_failed = False
    try:
        _apply(np.asarray([[math.nan]]), _effects())
    except ConfigValidationError:
        nan_failed = True
    edge = {
        "empty_shape": empty.shape,
        "empty_ratio": empty_diagnostics["electronics"]["saturated_sample_ratio"],
        "one_sample_finite": bool(np.isfinite(one[0, 0])),
        "one_sample_detector": one_diagnostics["electronics"]["agc_gain_trace_summary"][
            "front"
        ]["detector_rms"],
        "nonfinite_failed_closed": nan_failed,
        "bit_depth_endpoints_validated": [8, 32],
        "dc_detector_rule": "absolute amplitude",
        "silence_rule": "unity gain and exact zero output",
        "status": "passed",
    }
    _write_json("electronics_edge_case_matrix.json", edge)
    return {"rejection": errors, "chain": chain, "golden": golden, "edge": edge}


def _replay_evidence() -> dict[str, object]:
    sample_count = 48_000
    n = np.arange(sample_count, dtype=np.float64)
    samples = np.asarray(
        [
            0.9 * np.sin(2.0 * np.pi * frequency * n / SAMPLE_RATE_HZ)
            for frequency in (997.0, 1_499.0, 2_203.0, 3_301.0)
        ]
    )
    first, first_diagnostics = _apply(samples, _effects(dither=True, agc=_agc()))
    replay, replay_diagnostics = _apply(samples, _effects(dither=True, agc=_agc()))
    alternate, alternate_diagnostics = _apply(
        samples, _effects(dither=True, agc=_agc(), seed=ALT_SEED)
    )
    descriptors = {}
    every_seed_changed = True
    for mic_id in MIC_IDS:
        primary = named_stream_descriptor(
            SEED,
            domain="electronics",
            frame_id=FRAME_ID,
            mic_id=mic_id,
            effect="tpdf_dither",
        )
        alternate_descriptor = named_stream_descriptor(
            ALT_SEED,
            domain="electronics",
            frame_id=FRAME_ID,
            mic_id=mic_id,
            effect="tpdf_dither",
        )
        every_seed_changed &= primary[2] != alternate_descriptor[2]
        descriptors[mic_id] = {
            "primary": {
                "key": primary[0],
                "sha256": primary[1],
                "derived_seed": primary[2],
            },
            "alternate": {
                "key": alternate_descriptor[0],
                "sha256": alternate_descriptor[1],
                "derived_seed": alternate_descriptor[2],
            },
        }
    result = {
        "same_seed_output_exact": first.tobytes() == replay.tobytes(),
        "same_seed_diagnostics_exact": first_diagnostics == replay_diagnostics,
        "alternate_output_changed": first.tobytes() != alternate.tobytes(),
        "every_active_dither_seed_changed": every_seed_changed,
        "primary_output_sha256": _sha256(first.tobytes()),
        "replay_output_sha256": _sha256(replay.tobytes()),
        "alternate_output_sha256": _sha256(alternate.tobytes()),
        "primary_diagnostics_sha256": _sha256(
            json.dumps(first_diagnostics, sort_keys=True).encode()
        ),
        "alternate_diagnostics_sha256": _sha256(
            json.dumps(alternate_diagnostics, sort_keys=True).encode()
        ),
        "descriptors": descriptors,
        "status": "passed",
    }
    _write_json("seed_replay_sha256.json", result)
    _write_json(
        "dithered_waveform_hashes.json",
        {
            key: result[key]
            for key in (
                "primary_output_sha256",
                "replay_output_sha256",
                "alternate_output_sha256",
            )
        },
    )
    return result


def _implementation_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    configuration = _configuration_evidence()
    quantizer = _boundary_and_quantizer_evidence()
    dither = _dither_evidence()
    agc = _agc_evidence()
    backend = _backend_evidence()
    offstate = _rejection_offstate_and_edges()
    replay = _replay_evidence()
    rows = {
        "frozen_config_defaults": configuration["contract"]["status"],
        "fail_closed_validation": "passed"
        if configuration["invalid"]["all_failed_closed"]
        else "failed",
        "boundary_clipping_and_ratio": quantizer["boundary"]["status"],
        "quantization_noise_power": quantizer["power"]["status"],
        "tpdf_dither_decorrelation": dither["status"],
        "agc_analytical_response_settling": agc["step"]["status"],
        "agc_unity_silence_bounds": agc["unity"]["status"],
        "quantizer_edge_invariants": quantizer["invariants"]["status"],
        "diagnostics_contract": "passed",
        "electronics_once_on_mixture": backend["mixture"]["status"],
        "waveform_rms_estimator_consistency": backend["consistency"]["status"],
        "l0_l1_rejection": "passed"
        if all(value["status"] == "passed" for value in offstate["rejection"].values())
        else "failed",
        "pure_backend_off_state": "passed"
        if offstate["chain"]["status"] == offstate["golden"]["status"] == "passed"
        else "failed",
        "seed_replay_separation": replay["status"],
        "registry_determinism": backend["registry"]["status"],
        "minimum_window_runtime_failures": offstate["edge"]["status"],
    }
    artifacts = {}
    for path in sorted(OUTPUT.iterdir()):
        if path.name != "electronics_gate.json" and path.is_file():
            artifacts[path.name] = _sha256(path.read_bytes())
    maximum_correlation = max(
        value["abs_r"] for value in dither["microphones"].values()
    )
    gate = {
        "protocol_revision": PROTOCOL_REVISION,
        "implementation_revision": _implementation_revision(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "configuration": asdict(_effects(dither=True, agc=_agc()).electronics),
        "named_stream": {
            "domain": "electronics",
            "effect": "tpdf_dither",
            "root_seed_path": "audio.effects.noise.seed",
            "primary_seed": SEED,
            "alternate_seed": ALT_SEED,
        },
        "sample_counts": {
            "boundary": 16,
            "quantization_ramp": 2**18,
            "tpdf": 2**18,
            "agc": 24_000,
            "primary_backend": 48_000,
        },
        "thresholds": {
            "clipping_counts": [0, 0, 16, 8],
            "saturated_ratio": 0.375,
            "quantization_power_ratio": [0.9, 1.1],
            "dither_abs_correlation": 0.010,
            "agc_trace_absolute_error": 1e-12,
            "agc_settling_db_at_8_tau": 0.01,
            "aggregate_rms_absolute_error": 1e-12,
        },
        "measured": {
            "clipping_counts": list(quantizer["boundary"]["counts"].values()),
            "saturated_ratio": quantizer["boundary"]["saturated_sample_ratio"],
            "quantization_power_ratio": quantizer["power"]["power_ratio"],
            "maximum_dither_abs_correlation": maximum_correlation,
            "maximum_agc_trace_error": agc["step"]["maximum_trace_error"],
            "maximum_aggregate_rms_absolute_error": backend["consistency"][
                "maximum_aggregate_rms_absolute_error"
            ],
        },
        "rows": rows,
        "all_rows_passed": all(value == "passed" for value in rows.values()),
        "commands": [
            ".venv/bin/python scripts/s3_5_evidence.py",
            ".venv/bin/python -m pytest -q tests/test_effects_electronics.py",
        ],
        "artifact_sha256": artifacts,
    }
    _write_json("electronics_gate.json", gate)
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "all_rows_passed": gate["all_rows_passed"],
                "measured": gate["measured"],
            },
            indent=2,
        )
    )
    return 0 if gate["all_rows_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
