"""Pure float-domain electronics models for the summed microphone mixture."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from isaac_audio_sensors.core.effects.config import AgcConfig, ElectronicsConfig
from isaac_audio_sensors.core.effects.streams import (
    named_generator,
    named_stream_descriptor,
)


def quantization_step(config: ElectronicsConfig) -> float:
    """Return the frozen mid-tread quantization interval."""

    assert config.full_scale is not None
    assert config.bit_depth is not None
    return float(2.0 * config.full_scale / 2**config.bit_depth)


def scaled_rms(samples: np.ndarray) -> float:
    """Compute float64 RMS without overflowing while squaring finite input."""

    maximum = float(np.max(np.abs(samples)))
    if maximum == 0.0:
        return 0.0
    scaled = np.asarray(samples, dtype=np.float64) / maximum
    return float(maximum * np.sqrt(np.mean(scaled * scaled, dtype=np.float64)))


def apply_agc(
    samples: np.ndarray,
    *,
    sample_rate_hz: int,
    full_scale: float,
    config: AgcConfig | None,
) -> tuple[np.ndarray, np.ndarray, tuple[float | None, ...]]:
    """Apply the stateless per-window AGC and return its complete gain trace."""

    microphone_count, sample_count = samples.shape
    enabled = config is not None and config.enabled
    gains = np.ones((microphone_count, sample_count), dtype=np.float64)
    if not enabled:
        return np.asarray(samples, dtype=np.float64), gains, (None,) * microphone_count
    if sample_count == 0:
        raise ValueError("enabled AGC requires a non-empty time axis")

    assert config is not None
    assert config.target_rms_dbfs is not None
    assert config.attack_time_s is not None
    assert config.release_time_s is not None
    assert config.gain_floor_db is not None
    assert config.gain_ceiling_db is not None
    target = full_scale * 10.0 ** (config.target_rms_dbfs / 20.0)
    gain_floor = 10.0 ** (config.gain_floor_db / 20.0)
    gain_ceiling = 10.0 ** (config.gain_ceiling_db / 20.0)
    alpha_attack = np.float64(np.exp(-1.0 / (config.attack_time_s * sample_rate_hz)))
    alpha_release = np.float64(np.exp(-1.0 / (config.release_time_s * sample_rate_hz)))
    powers = np.arange(1, sample_count + 1, dtype=np.float64)
    detectors: list[float] = []
    for mic_index in range(microphone_count):
        detector = scaled_rms(samples[mic_index])
        detectors.append(detector)
        gain_star = (
            1.0
            if detector == 0.0
            else float(np.clip(target / detector, gain_floor, gain_ceiling))
        )
        if gain_star == 1.0:
            continue
        alpha = alpha_attack if gain_star < 1.0 else alpha_release
        gains[mic_index] = gain_star + (1.0 - gain_star) * np.power(alpha, powers)
    return np.asarray(samples, dtype=np.float64) * gains, gains, tuple(detectors)


def generate_tpdf_dither(
    sample_count: int,
    *,
    step: float,
    seed: int,
    frame_id: str,
    mic_id: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generate one microphone's one-LSB peak-to-peak named TPDF dither."""

    key, digest, derived_seed = named_stream_descriptor(
        seed,
        domain="electronics",
        frame_id=frame_id,
        mic_id=mic_id,
        effect="tpdf_dither",
    )
    descriptor = {
        "key": key,
        "sha256": digest,
        "derived_seed": derived_seed,
        "domain": "electronics",
        "effect": "tpdf_dither",
        "mic_id": mic_id,
    }
    if sample_count == 0:
        return np.empty(0, dtype=np.float64), descriptor
    draws = named_generator(
        seed,
        domain="electronics",
        frame_id=frame_id,
        mic_id=mic_id,
        effect="tpdf_dither",
    ).random(2 * sample_count)
    return (step / 2.0) * (draws[:sample_count] - draws[sample_count:]), descriptor


def quantize(
    samples: np.ndarray,
    *,
    full_scale: float,
    step: float,
    dither: np.ndarray | None = None,
) -> np.ndarray:
    """Apply frozen ties-to-even float reconstruction and endpoint clipping."""

    values = samples if dither is None else samples + dither
    reconstructed = step * np.rint(values / step)
    return np.clip(reconstructed, -full_scale, full_scale)


def apply_electronics(
    samples: np.ndarray,
    *,
    mic_ids: Sequence[str],
    sample_rate_hz: int,
    frame_id: str,
    config: ElectronicsConfig,
    seed: int | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Run AGC, hard saturation, and quantization in the frozen order."""

    assert config.enabled
    assert config.full_scale is not None
    assert config.bit_depth is not None
    full_scale = float(config.full_scale)
    step = quantization_step(config)
    agc_output, gain_trace, detectors = apply_agc(
        samples,
        sample_rate_hz=sample_rate_hz,
        full_scale=full_scale,
        config=config.agc,
    )
    clipping_mask = np.abs(agc_output) > full_scale
    saturated = np.clip(agc_output, -full_scale, full_scale)
    output = np.empty_like(saturated, dtype=np.float64)
    for mic_index, mic_id in enumerate(mic_ids):
        dither = None
        if config.dither_enabled and saturated.shape[1] > 0:
            assert seed is not None
            dither, _descriptor = generate_tpdf_dither(
                saturated.shape[1],
                step=step,
                seed=seed,
                frame_id=frame_id,
                mic_id=mic_id,
            )
        output[mic_index] = quantize(
            saturated[mic_index],
            full_scale=full_scale,
            step=step,
            dither=dither,
        )

    counts = {
        mic_id: int(np.count_nonzero(clipping_mask[mic_index]))
        for mic_index, mic_id in enumerate(mic_ids)
    }
    denominator = len(mic_ids) * samples.shape[1]
    ratio = 0.0 if denominator == 0 else sum(counts.values()) / denominator
    agc_enabled = config.agc is not None and config.agc.enabled
    summary: dict[str, dict[str, float | None]] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        trace = gain_trace[mic_index]
        summary[mic_id] = {
            "initial_gain": 1.0,
            "final_gain": 1.0 if trace.size == 0 else float(trace[-1]),
            "minimum_gain": (
                1.0 if trace.size == 0 else min(1.0, float(np.min(trace)))
            ),
            "maximum_gain": (
                1.0 if trace.size == 0 else max(1.0, float(np.max(trace)))
            ),
            "detector_rms": detectors[mic_index] if agc_enabled else None,
        }
    diagnostics = {
        "clipping_count_per_mic": counts,
        "saturated_sample_ratio": float(ratio),
        "agc_gain_trace_summary": summary,
        "quantization_step": step,
    }
    return output, diagnostics


__all__ = [
    "apply_agc",
    "apply_electronics",
    "generate_tpdf_dither",
    "quantization_step",
    "quantize",
    "scaled_rms",
]
