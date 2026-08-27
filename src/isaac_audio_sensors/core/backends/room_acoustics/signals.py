"""Source scheduling and waveform preparation for room acoustics."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.types import (
    AudioSourceSpec,
    AudioTimeWindow,
)

_SECONDARY_TONE_RATIO = 1.618033988749895
_SECONDARY_TONE_GAIN = 0.6
_TWO_TONE_PEAK = 1.0 + _SECONDARY_TONE_GAIN
_EDGE_RAMP_S = 0.004
_IMPULSE_SPIKES_S = ((0.004, 1.0),)
_PULSE_SPIKES_S = ((0.004, 1.0), (0.010, -0.65), (0.017, 0.4))


@dataclass(frozen=True, slots=True)
class _ScheduledSignal:
    """One source's window-relative signal with sample-accurate scheduling."""

    signal: np.ndarray
    mode: str
    start_offset_samples: int
    content_sample_count: int


def _piecewise_phase_signal(
    waveform: np.ndarray,
    *,
    factors: tuple[float, ...],
    segment_lengths: tuple[int, ...],
) -> np.ndarray:
    """Render sample-exact segments with one cumulative float64 phase cursor."""

    if len(factors) != len(segment_lengths) or not factors:
        raise ValueError("piecewise factors and segment lengths must match")
    if any(length <= 0 for length in segment_lengths):
        raise ValueError("piecewise segment lengths must be positive")
    source = np.asarray(waveform, dtype=float)
    output = np.zeros(sum(segment_lengths), dtype=float)
    cursor = 0.0
    output_index = 0
    for factor, length in zip(factors, segment_lengths, strict=True):
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("piecewise Doppler factors must be positive and finite")
        for _ in range(length):
            lower = math.floor(cursor)
            fraction = cursor - lower
            first = source[lower] if 0 <= lower < source.size else 0.0
            second_index = lower + 1
            second = source[second_index] if 0 <= second_index < source.size else 0.0
            output[output_index] = first + fraction * (second - first)
            output_index += 1
            cursor += factor
    return output


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
        round(max(0.0, source.start_time_s - time_window.start_time_s) * sample_rate_hz)
    )
    elapsed_samples = int(
        round(max(0.0, time_window.start_time_s - source.start_time_s) * sample_rate_hz)
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
        content = _file_source_content(
            base,
            elapsed_samples=elapsed_samples,
            content_samples=content_samples,
            loop_count=source.loop_count,
        )
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
    content = np.asarray(
        content
        * db_to_amplitude_gain(source.gain_db, "AudioSourceSpec.gain_db"),
        dtype=float,
    )
    signal = np.concatenate([np.zeros(start_offset_samples, dtype=float), content])
    if signal.size == 0:
        signal = np.zeros(1, dtype=float)
    return _ScheduledSignal(
        signal=signal,
        mode=mode,
        start_offset_samples=start_offset_samples,
        content_sample_count=content_samples,
    )


def _file_source_content(
    waveform: np.ndarray,
    *,
    elapsed_samples: int,
    content_samples: int,
    loop_count: int,
) -> np.ndarray:
    """Return a scheduled slice using Kit-compatible file loop semantics."""

    content = np.zeros(content_samples, dtype=float)
    base = np.asarray(waveform, dtype=float)
    if content_samples <= 0 or base.size == 0:
        return content
    if loop_count == -1:
        available_samples = content_samples
    else:
        total_samples = base.size * (loop_count + 1)
        available_samples = max(
            0,
            min(content_samples, total_samples - elapsed_samples),
        )
    if available_samples <= 0:
        return content
    indices = (elapsed_samples + np.arange(available_samples)) % base.size
    content[:available_samples] = base[indices]
    return content


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
    time_s = (elapsed_samples + np.arange(content_samples, dtype=float)) / float(
        sample_rate_hz
    )
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
    return np.asarray(waveform, dtype=float)


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
            "Resampling audio_asset_path files requires scipy from the 'room' extra."
        ) from exc
    divisor = math.gcd(from_hz, to_hz)
    return np.asarray(
        resample_poly(waveform, to_hz // divisor, from_hz // divisor),
        dtype=float,
    )


def _doppler_resampled_signal(
    waveform: np.ndarray,
    *,
    factor: float,
) -> np.ndarray:
    """Time-compress a window signal by the Doppler factor.

    The output plays the same content over ``len(waveform) / factor`` samples
    at the unchanged frame sample rate, scaling all frequencies by ``factor``.
    One factor applies to the whole window (computed at the array center at
    the snapshot pose), so intra-window motion and the compression of leading
    scheduling silence are deliberate approximations of a continuously moving
    source.
    """

    try:
        from fractions import Fraction

        from scipy.signal import resample_poly  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Doppler waveform resampling requires scipy from the 'room' extra."
        ) from exc
    ratio = Fraction(factor).limit_denominator(10_000)
    return np.asarray(
        resample_poly(waveform, ratio.denominator, ratio.numerator),
        dtype=float,
    )
