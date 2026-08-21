"""NumPy-only seeded waveform noise and timing metadata effects."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from isaac_audio_sensors.core.effects.channel_response import (
    fractional_delay,
    response_tap_count,
)
from isaac_audio_sensors.core.effects.config import (
    NoiseConfig,
    NoiseLevelSpecConfig,
    NoiseSpectrumPointConfig,
)
from isaac_audio_sensors.core.effects.streams import (
    SEED_DERIVATION_ID,
    named_generator,
    named_stream_descriptor,
)
from isaac_audio_sensors.core.exceptions import ConfigValidationError


def apply_noise(
    samples: np.ndarray,
    *,
    mic_ids: Sequence[str],
    sample_rate_hz: int,
    frame_id: str,
    nominal_window_start_sample: int,
    config: NoiseConfig,
    microphone_self_noise_db: Mapping[str, float | None] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply additive noise, drift, then jitter to one summed mixture."""

    if not config.enabled:
        return samples, {}
    _validate_nominal_start(nominal_window_start_sample)
    mic_ids = tuple(mic_ids)
    sample_count = samples.shape[1]
    self_specs = _resolved_self_noise_specs(
        config,
        mic_ids,
        microphone_self_noise_db or {},
    )
    ambient = config.ambient
    jitter_settings = _timing_settings(config.clock_jitter_std_s, mic_ids)
    drift_settings = dict(config.clock_drift_ppm or {})
    applicable = bool(
        self_specs
        or ambient is not None
        or config.clock_jitter_std_s is not None
        or config.clock_drift_ppm is not None
    )
    if not applicable:
        return samples, {}

    _require_runtime_seed(config, self_specs, ambient, jitter_settings)
    self_taps = {
        mic_id: design_noise_fir(spec.spectrum, sample_rate_hz=sample_rate_hz)
        for mic_id, spec in self_specs.items()
        if spec.level_db != -math.inf
    }
    ambient_taps = (
        None
        if ambient is None or ambient.level_db == -math.inf
        else design_noise_fir(ambient.spectrum, sample_rate_hz=sample_rate_hz)
    )

    for mic_id, ppm in drift_settings.items():
        _validate_drift_window(
            sample_count,
            q0=nominal_window_start_sample,
            ppm=float(ppm),
            mic_id=mic_id,
        )
    jitter_draws = _draw_jitter_values(
        config,
        jitter_settings,
        sample_rate_hz=sample_rate_hz,
        sample_count=sample_count,
        frame_id=frame_id,
    )

    additive = np.zeros((len(mic_ids), sample_count), dtype=np.float64)
    streams: dict[str, dict[str, Any]] = {}
    for mic_index, mic_id in enumerate(mic_ids):
        spec = self_specs.get(mic_id)
        if spec is None or spec.level_db == -math.inf:
            continue
        assert config.seed is not None
        streams[f"self_noise:{mic_id}"] = _stochastic_stream_record(
            config.seed,
            frame_id=frame_id,
            mic_id=mic_id,
            effect="self_noise",
        )
        additive[mic_index] += _noise_draw(
            sample_count,
            level_db=float(spec.level_db),
            taps=self_taps[mic_id],
            seed=config.seed,
            frame_id=frame_id,
            mic_id=mic_id,
            effect="self_noise",
        )

    if ambient is not None and ambient.level_db != -math.inf:
        assert config.seed is not None
        assert ambient_taps is not None
        coherent = (
            0.0
            if ambient.coherent_fraction is None
            else float(ambient.coherent_fraction)
        )
        common = np.zeros(sample_count, dtype=np.float64)
        if coherent > 0.0:
            streams["ambient_common"] = _stochastic_stream_record(
                config.seed,
                frame_id=frame_id,
                mic_id="__common__",
                effect="ambient_common",
            )
            common = _unit_noise_draw(
                sample_count,
                taps=ambient_taps,
                seed=config.seed,
                frame_id=frame_id,
                mic_id="__common__",
                effect="ambient_common",
            )
        scale = level_amplitude(float(ambient.level_db))
        for mic_index, mic_id in enumerate(mic_ids):
            independent = np.zeros(sample_count, dtype=np.float64)
            if coherent < 1.0:
                streams[f"ambient:{mic_id}"] = _stochastic_stream_record(
                    config.seed,
                    frame_id=frame_id,
                    mic_id=mic_id,
                    effect="ambient",
                )
                independent = _unit_noise_draw(
                    sample_count,
                    taps=ambient_taps,
                    seed=config.seed,
                    frame_id=frame_id,
                    mic_id=mic_id,
                    effect="ambient",
                )
            additive[mic_index] += scale * (
                math.sqrt(1.0 - coherent) * independent + math.sqrt(coherent) * common
            )

    output = np.asarray(samples, dtype=np.float64) + additive
    for mic_index, mic_id in enumerate(mic_ids):
        ppm = float(drift_settings.get(mic_id, 0.0))
        if mic_id in drift_settings:
            streams[f"clock_drift:{mic_id}"] = {
                "effect": "clock_drift",
                "mic_id": mic_id,
                "stochastic": False,
            }
        if ppm != 0.0:
            output[mic_index] = apply_clock_drift(
                output[mic_index],
                q0=nominal_window_start_sample,
                ppm=ppm,
            )
        jitter = jitter_draws.get(mic_id, 0.0)
        if jitter_settings.get(mic_id, 0.0) > 0.0:
            assert config.seed is not None
            streams[f"clock_jitter:{mic_id}"] = _stochastic_stream_record(
                config.seed,
                frame_id=frame_id,
                mic_id=mic_id,
                effect="clock_jitter",
            )
        if jitter != 0.0:
            output[mic_index] = fractional_delay(
                output[mic_index],
                delay_s=jitter,
                sample_rate_hz=sample_rate_hz,
            )

    per_mic_rms = {
        mic_id: (
            0.0
            if sample_count == 0
            else float(np.sqrt(np.mean(additive[index] * additive[index])))
        )
        for index, mic_id in enumerate(mic_ids)
    }
    return output, _noise_diagnostics(streams, per_mic_rms)


def metadata_noise_timing_values(
    config: NoiseConfig,
    *,
    mic_ids: Sequence[str],
    sample_rate_hz: int,
    frame_id: str,
    nominal_window_start_sample: int,
    sample_count: int,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Return the L0/L1 additive jitter/drift midpoint delay offsets."""

    if not config.enabled:
        return {}, {}
    _validate_nominal_start(nominal_window_start_sample)
    mic_ids = tuple(mic_ids)
    jitter_settings = _timing_settings(config.clock_jitter_std_s, mic_ids)
    drift_settings = dict(config.clock_drift_ppm or {})
    if config.clock_jitter_std_s is None and config.clock_drift_ppm is None:
        return {}, {}
    _require_runtime_seed(config, {}, None, jitter_settings)
    jitter_draws = _draw_jitter_values(
        config,
        jitter_settings,
        sample_rate_hz=sample_rate_hz,
        sample_count=sample_count,
        frame_id=frame_id,
    )
    streams: dict[str, dict[str, Any]] = {}
    offsets: dict[str, float] = {}
    q_mid = nominal_window_start_sample + (sample_count - 1) / 2.0
    for mic_id in mic_ids:
        jitter = jitter_draws.get(mic_id, 0.0)
        if jitter_settings.get(mic_id, 0.0) > 0.0:
            assert config.seed is not None
            streams[f"clock_jitter:{mic_id}"] = _stochastic_stream_record(
                config.seed,
                frame_id=frame_id,
                mic_id=mic_id,
                effect="clock_jitter",
            )
        ppm = float(drift_settings.get(mic_id, 0.0))
        if mic_id in drift_settings:
            streams[f"clock_drift:{mic_id}"] = {
                "effect": "clock_drift",
                "mic_id": mic_id,
                "stochastic": False,
            }
        if (
            mic_id in jitter_settings
            or mic_id in drift_settings
            or config.clock_jitter_std_s is not None
        ):
            offsets[mic_id] = jitter + (
                float(drift_delay_samples(q_mid, ppm)) / float(sample_rate_hz)
            )
    per_mic_rms = dict.fromkeys(mic_ids, 0.0)
    return offsets, _noise_diagnostics(streams, per_mic_rms)


def design_noise_fir(
    points: Sequence[NoiseSpectrumPointConfig] | None,
    *,
    sample_rate_hz: int,
) -> np.ndarray:
    """Design and energy-normalize the frozen spectral-noise FIR."""

    if points is None:
        return np.ones(1, dtype=np.float64)
    tap_count = response_tap_count(sample_rate_hz)
    dense_size = _next_power_of_two(max(16_384, tap_count * 16))
    frequencies = np.fft.rfftfreq(dense_size, d=1.0 / float(sample_rate_hz))
    point_frequencies = np.asarray(
        [float(point.freq_hz) for point in points], dtype=np.float64
    )
    point_amplitudes = 10.0 ** (
        np.asarray([float(point.level_db) for point in points], dtype=np.float64) / 20.0
    )
    target = np.interp(
        frequencies,
        point_frequencies,
        point_amplitudes,
        left=point_amplitudes[0],
        right=point_amplitudes[-1],
    )
    zero_phase = np.fft.irfft(target, n=dense_size)
    centered = np.fft.fftshift(zero_phase)
    midpoint = dense_size // 2
    half = tap_count // 2
    taps = centered[midpoint - half : midpoint + half + 1].copy()
    taps *= np.hanning(tap_count)
    energy = float(np.sum(taps * taps))
    if not math.isfinite(energy) or energy <= 0.0:
        raise ConfigValidationError(
            "audio.effects.noise spectrum produced non-finite or zero FIR energy."
        )
    return np.asarray(taps / math.sqrt(energy), dtype=np.float64)


def level_amplitude(level_db: float) -> float:
    """Convert a full-band dBFS RMS level to linear amplitude."""

    return 0.0 if level_db == -math.inf else 10.0 ** (level_db / 20.0)


def drift_delay_samples(q: float | np.ndarray, ppm: float) -> Any:
    """Evaluate the frozen accumulated clock-drift delay in samples."""

    epsilon = float(ppm) * 1e-6
    return np.asarray(q) * epsilon / (1.0 + epsilon)


def decompose_drift_delay(q: float, ppm: float) -> tuple[int, float]:
    """Split accumulated drift into integer slip and phase in ``[0, 1)``."""

    delay = float(drift_delay_samples(q, ppm))
    slip = math.floor(delay)
    return slip, delay - slip


def apply_clock_drift(samples: np.ndarray, *, q0: int, ppm: float) -> np.ndarray:
    """Resample one finite window with zero-extended first-order interpolation."""

    if samples.size == 0 or ppm == 0.0:
        return samples.copy()
    indices = np.arange(samples.size, dtype=np.float64)
    delay = drift_delay_samples(q0 + indices, ppm)
    source_positions = indices - delay
    lower = np.floor(source_positions).astype(np.int64)
    alpha = source_positions - lower
    result = np.zeros(samples.size, dtype=np.float64)
    valid_lower = (lower >= 0) & (lower < samples.size)
    result[valid_lower] += (1.0 - alpha[valid_lower]) * samples[lower[valid_lower]]
    upper = lower + 1
    valid_upper = (upper >= 0) & (upper < samples.size)
    result[valid_upper] += alpha[valid_upper] * samples[upper[valid_upper]]
    return result


def _resolved_self_noise_specs(
    config: NoiseConfig,
    mic_ids: tuple[str, ...],
    metadata: Mapping[str, float | None],
) -> dict[str, NoiseLevelSpecConfig]:
    if config.self_noise is None:
        return {}
    microphones = config.self_noise.microphones or {}
    result: dict[str, NoiseLevelSpecConfig] = {}
    for mic_id in mic_ids:
        spec = microphones.get(mic_id, config.self_noise.default)
        if spec is None and metadata.get(mic_id) is not None:
            level = _validated_metadata_level(metadata[mic_id], mic_id)
            spec = NoiseLevelSpecConfig(level_db=level)
        if spec is not None:
            result[mic_id] = spec
    return result


def _validated_metadata_level(value: object, mic_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigValidationError(
            "audio.effects.noise.self_noise fallback MicrophoneSpec.self_noise_db "
            f"for microphone {mic_id!r} must be a number; received {value!r}."
        )
    level = float(value)
    if level == -math.inf:
        return level
    if not math.isfinite(level) or not -300.0 <= level <= 60.0:
        raise ConfigValidationError(
            "audio.effects.noise.self_noise fallback MicrophoneSpec.self_noise_db "
            f"for microphone {mic_id!r} must be -inf or finite in "
            f"[-300.0, 60.0]; received {value!r}."
        )
    return level


def _require_runtime_seed(
    config: NoiseConfig,
    self_specs: Mapping[str, NoiseLevelSpecConfig],
    ambient: object,
    jitter: Mapping[str, float],
) -> None:
    stochastic = any(spec.level_db != -math.inf for spec in self_specs.values())
    stochastic = stochastic or (
        ambient is not None and getattr(ambient, "level_db", -math.inf) != -math.inf
    )
    stochastic = stochastic or any(value > 0.0 for value in jitter.values())
    if stochastic and config.seed is None:
        raise ConfigValidationError(
            "audio.effects.noise.seed is required after self-noise metadata "
            "resolution produced a nonzero stochastic contribution."
        )


def _timing_settings(
    value: float | Mapping[str, float] | None,
    mic_ids: tuple[str, ...],
) -> dict[str, float]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {mic_id: float(setting) for mic_id, setting in value.items()}
    return dict.fromkeys(mic_ids, float(value))


def _draw_jitter_values(
    config: NoiseConfig,
    settings: Mapping[str, float],
    *,
    sample_rate_hz: int,
    sample_count: int,
    frame_id: str,
) -> dict[str, float]:
    draws: dict[str, float] = {}
    if sample_count == 0:
        return draws
    for mic_id, sigma in settings.items():
        if sigma == 0.0:
            draws[mic_id] = 0.0
            continue
        assert config.seed is not None
        draw = float(
            named_generator(
                config.seed,
                domain="noise",
                frame_id=frame_id,
                mic_id=mic_id,
                effect="clock_jitter",
            ).normal(0.0, sigma)
        )
        if math.ceil(abs(draw * sample_rate_hz)) >= sample_count:
            raise ConfigValidationError(
                "audio.effects.noise.clock_jitter_std_s seeded draw "
                f"{draw!r} s for microphone {mic_id!r} leaves no non-empty "
                f"valid region in a {sample_count}-sample window at "
                f"{sample_rate_hz} Hz."
            )
        draws[mic_id] = draw
    return draws


def _validate_drift_window(
    sample_count: int,
    *,
    q0: int,
    ppm: float,
    mic_id: str,
) -> None:
    if sample_count == 0 or ppm == 0.0:
        return
    indices = np.arange(sample_count, dtype=np.float64)
    positions = indices - drift_delay_samples(q0 + indices, ppm)
    lower = np.floor(positions)
    alpha = positions - lower
    lower_valid = (lower >= 0) & (lower < sample_count) & ((1.0 - alpha) != 0.0)
    upper = lower + 1.0
    upper_valid = (upper >= 0) & (upper < sample_count) & (alpha != 0.0)
    if not np.any(lower_valid | upper_valid):
        raise ConfigValidationError(
            "audio.effects.noise.clock_drift_ppm."
            f"{mic_id}={ppm!r} at nominal start sample {q0} leaves no non-empty "
            f"valid source region for a {sample_count}-sample window."
        )


def _noise_draw(
    sample_count: int,
    *,
    level_db: float,
    taps: np.ndarray,
    seed: int,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> np.ndarray:
    return level_amplitude(level_db) * _unit_noise_draw(
        sample_count,
        taps=taps,
        seed=seed,
        frame_id=frame_id,
        mic_id=mic_id,
        effect=effect,
    )


def _unit_noise_draw(
    sample_count: int,
    *,
    taps: np.ndarray,
    seed: int,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> np.ndarray:
    if sample_count == 0:
        return np.zeros(0, dtype=np.float64)
    generator = named_generator(
        seed,
        domain="noise",
        frame_id=frame_id,
        mic_id=mic_id,
        effect=effect,
    )
    white = generator.standard_normal(sample_count + taps.size - 1)
    return np.asarray(np.convolve(white, taps, mode="valid"), dtype=np.float64)


def _stochastic_stream_record(
    seed: int,
    *,
    frame_id: str,
    mic_id: str,
    effect: str,
) -> dict[str, Any]:
    _key, digest, derived_seed = named_stream_descriptor(
        seed,
        domain="noise",
        frame_id=frame_id,
        mic_id=mic_id,
        effect=effect,
    )
    return {
        "effect": effect,
        "mic_id": mic_id,
        "stochastic": True,
        "sha256": digest,
        "derived_seed": derived_seed,
    }


def _noise_diagnostics(
    streams: Mapping[str, Mapping[str, Any]],
    per_mic_rms: Mapping[str, float],
) -> dict[str, Any]:
    return {
        "streams": dict(streams),
        "per_mic_rms": dict(per_mic_rms),
        "seed_derivation_id": SEED_DERIVATION_ID,
    }


def _validate_nominal_start(value: object) -> None:
    if type(value) is not int:
        raise ConfigValidationError(
            "audio.effects.noise nominal_window_start_sample must be an exact "
            f"integer; received {value!r}."
        )


def _next_power_of_two(value: int) -> int:
    return 1 if value <= 1 else 1 << (value - 1).bit_length()


__all__ = [
    "apply_clock_drift",
    "apply_noise",
    "decompose_drift_delay",
    "design_noise_fir",
    "drift_delay_samples",
    "level_amplitude",
    "metadata_noise_timing_values",
]
