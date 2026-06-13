"""Multichannel waveform export for simulated microphone-array audio."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable

WAVEFORM_WAV_SUBTYPE = "FLOAT"

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _import_soundfile() -> Any:
    try:
        import soundfile  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "Waveform export requires soundfile from the 'room' extra."
        ) from exc
    return soundfile


def write_multichannel_wav(
    path: str | Path,
    samples: np.ndarray,
    *,
    sample_rate_hz: int,
    subtype: str = WAVEFORM_WAV_SUBTYPE,
) -> Path:
    """Write one ``(n_channels, n_samples)`` float array as a multichannel WAV."""

    soundfile = _import_soundfile()
    data = np.asarray(samples, dtype=float)
    if data.ndim != 2:
        raise ValueError(
            "write_multichannel_wav expects a (n_channels, n_samples) array."
        )
    if int(sample_rate_hz) <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(output_path, data.T, int(sample_rate_hz), subtype=subtype)
    return output_path


@dataclass(frozen=True, slots=True, kw_only=True)
class WaveformWriteResult:
    """Written waveform artifact paths plus frame diagnostics."""

    paths: tuple[str, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class WaveformSink(Protocol):
    """Destination for per-frame microphone mixtures rendered by a backend."""

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        """Persist one frame's ``(n_mics, n_samples)`` mixture."""

    def close(self) -> None:
        """Flush and release any held resources."""


class FrameWaveformWriter:
    """Write one deterministic multichannel WAV per frame under ``output_dir``."""

    def __init__(self, output_dir: str | Path) -> None:
        _import_soundfile()
        self.output_dir = Path(output_dir)
        self._closed = False

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        """Write ``mixture`` to ``{output_dir}/{frame_id}.wav`` deterministically."""

        if self._closed:
            raise RuntimeError("FrameWaveformWriter is closed.")
        data = _validated_mixture(mixture, mic_ids=mic_ids)
        path = write_multichannel_wav(
            self.output_dir / f"{waveform_safe_filename(frame_id)}.wav",
            data,
            sample_rate_hz=sample_rate_hz,
        )
        return WaveformWriteResult(
            paths=(str(path),),
            diagnostics={
                "mode": "per_frame",
                "channel_mic_ids": list(mic_ids),
                "sample_count": int(data.shape[1]),
                "window_sample_count": int(window_sample_count),
                "sample_rate_hz": int(sample_rate_hz),
                "subtype": WAVEFORM_WAV_SUBTYPE,
            },
        )

    def close(self) -> None:
        """Mark the writer closed; subsequent writes raise."""

        self._closed = True


class ContinuousWaveformWriter:
    """Append window-exact chunks to one growing session WAV.

    Each frame contributes exactly ``window_sample_count`` samples to the
    stream; the convolution/reverb tail past the window is carried and
    overlap-added into subsequent chunks, so concatenated windows stay
    gapless and energy-conserving. ``close()`` flushes the remaining tail.

    Doppler is not applied here: the room backend resamples each source's
    window signal by its per-window Doppler factor (from the optional
    ``velocity_world_mps`` spec fields) before simulation, so the frame
    mixtures this writer consumes already carry the frequency shift.
    """

    def __init__(self, path: str | Path) -> None:
        self._soundfile = _import_soundfile()
        self.path = Path(path)
        self._file: Any | None = None
        self._carry: np.ndarray | None = None
        self._cursor = 0
        self._sample_rate_hz: int | None = None
        self._mic_ids: tuple[str, ...] | None = None
        self._closed = False

    def write_frame_mixture(
        self,
        *,
        frame_id: str,
        mixture: np.ndarray,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
        window_sample_count: int,
    ) -> WaveformWriteResult:
        """Append one frame's window to the session stream.

        Returns the session path plus the frame's half-open
        ``[start_sample, end_sample)`` slice of the stream.
        """

        del frame_id
        if self._closed:
            raise RuntimeError("ContinuousWaveformWriter is closed.")
        data = _validated_mixture(mixture, mic_ids=mic_ids)
        window = int(window_sample_count)
        if window <= 0:
            raise ValueError("window_sample_count must be positive.")
        self._ensure_session(
            sample_rate_hz=int(sample_rate_hz),
            mic_ids=tuple(mic_ids),
        )

        chunk = np.zeros((len(mic_ids), window), dtype=float)
        head = data[:, :window]
        chunk[:, : head.shape[1]] = head
        carry = (
            self._carry
            if self._carry is not None
            else np.zeros((len(mic_ids), 0), dtype=float)
        )
        overlap = min(carry.shape[1], window)
        chunk[:, :overlap] += carry[:, :overlap]
        leftover = carry[:, overlap:]
        tail = data[:, window:]
        new_carry = np.zeros(
            (len(mic_ids), max(leftover.shape[1], tail.shape[1])),
            dtype=float,
        )
        new_carry[:, : leftover.shape[1]] += leftover
        new_carry[:, : tail.shape[1]] += tail
        self._carry = new_carry

        assert self._file is not None
        self._file.write(chunk.T)
        start_sample = self._cursor
        self._cursor += window
        return WaveformWriteResult(
            paths=(str(self.path),),
            diagnostics={
                "mode": "session",
                "path": str(self.path),
                "start_sample": start_sample,
                "end_sample": self._cursor,
                "channel_mic_ids": list(mic_ids),
                "sample_rate_hz": int(sample_rate_hz),
                "window_sample_count": window,
                "subtype": WAVEFORM_WAV_SUBTYPE,
            },
        )

    def close(self) -> None:
        """Flush the carried tail and close the session file."""

        if self._closed:
            return
        self._closed = True
        if self._file is not None:
            if self._carry is not None and self._carry.shape[1] > 0:
                self._file.write(self._carry.T)
                self._cursor += self._carry.shape[1]
            self._carry = None
            self._file.close()
            self._file = None

    def _ensure_session(
        self,
        *,
        sample_rate_hz: int,
        mic_ids: tuple[str, ...],
    ) -> None:
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self._soundfile.SoundFile(
                self.path,
                mode="w",
                samplerate=sample_rate_hz,
                channels=len(mic_ids),
                subtype=WAVEFORM_WAV_SUBTYPE,
            )
            self._sample_rate_hz = sample_rate_hz
            self._mic_ids = mic_ids
            return
        if sample_rate_hz != self._sample_rate_hz or mic_ids != self._mic_ids:
            raise ValueError(
                "ContinuousWaveformWriter session parameters changed "
                "between frames."
            )


def waveform_safe_filename(name: str) -> str:
    """Collapse characters that are unsafe in waveform file names."""

    return _UNSAFE_FILENAME_CHARS.sub("_", name)


def _validated_mixture(
    mixture: np.ndarray,
    *,
    mic_ids: tuple[str, ...],
) -> np.ndarray:
    data = np.asarray(mixture, dtype=float)
    if data.ndim != 2 or data.shape[0] != len(mic_ids):
        raise ValueError("Waveform mixture must have shape (n_mics, n_samples).")
    return data
