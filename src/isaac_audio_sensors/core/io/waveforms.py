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
