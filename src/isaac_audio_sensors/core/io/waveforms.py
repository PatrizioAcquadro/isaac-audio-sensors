"""Multichannel waveform export for simulated microphone-array audio."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.types import MicrophoneSignalBlock

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
    """Destination for exact-window microphone signal blocks."""

    def write_signal_block(
        self,
        *,
        frame_id: str,
        block: MicrophoneSignalBlock,
    ) -> WaveformWriteResult:
        """Persist one frame's exact immutable signal block."""

    def close(self) -> None:
        """Flush and release any held resources."""


class FrameWaveformWriter:
    """Write one deterministic multichannel WAV per frame under ``output_dir``."""

    def __init__(self, output_dir: str | Path) -> None:
        _import_soundfile()
        self.output_dir = Path(output_dir)
        self._closed = False

    def write_signal_block(
        self,
        *,
        frame_id: str,
        block: MicrophoneSignalBlock,
    ) -> WaveformWriteResult:
        """Write ``block`` to ``{output_dir}/{frame_id}.wav`` deterministically."""

        if self._closed:
            raise RuntimeError("FrameWaveformWriter is closed.")
        _require_signal_block(block)
        path = write_multichannel_wav(
            self.output_dir / f"{waveform_safe_filename(frame_id)}.wav",
            block.samples,
            sample_rate_hz=block.sample_rate_hz,
        )
        return WaveformWriteResult(
            paths=(str(path),),
            diagnostics={
                "mode": "per_frame",
                "channel_mic_ids": list(block.microphone_ids),
                "sample_count": int(block.samples.shape[1]),
                "sample_rate_hz": block.sample_rate_hz,
                "subtype": WAVEFORM_WAV_SUBTYPE,
            },
        )

    def close(self) -> None:
        """Mark the writer closed; subsequent writes raise."""

        self._closed = True


class ContinuousWaveformWriter:
    """Append exact signal blocks to one growing session WAV."""

    def __init__(self, path: str | Path) -> None:
        self._soundfile = _import_soundfile()
        self.path = Path(path)
        self._file: Any | None = None
        self._cursor = 0
        self._sample_rate_hz: int | None = None
        self._mic_ids: tuple[str, ...] | None = None
        self._closed = False

    def write_signal_block(
        self,
        *,
        frame_id: str,
        block: MicrophoneSignalBlock,
    ) -> WaveformWriteResult:
        """Append one exact signal block to the session stream.

        Returns the session path plus the frame's half-open
        ``[start_sample, end_sample)`` slice of the stream.
        """

        del frame_id
        if self._closed:
            raise RuntimeError("ContinuousWaveformWriter is closed.")
        _require_signal_block(block)
        window = int(block.samples.shape[1])
        self._ensure_session(
            sample_rate_hz=block.sample_rate_hz,
            mic_ids=block.microphone_ids,
        )

        assert self._file is not None
        self._file.write(block.samples.T)
        start_sample = self._cursor
        self._cursor += window
        return WaveformWriteResult(
            paths=(str(self.path),),
            diagnostics={
                "mode": "session",
                "start_sample": start_sample,
                "end_sample": self._cursor,
                "channel_mic_ids": list(block.microphone_ids),
                "sample_rate_hz": block.sample_rate_hz,
                "window_sample_count": window,
                "subtype": WAVEFORM_WAV_SUBTYPE,
            },
        )

    def close(self) -> None:
        """Close the session file without synthesizing additional samples."""

        if self._closed:
            return
        self._closed = True
        if self._file is not None:
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


def _require_signal_block(block: MicrophoneSignalBlock) -> None:
    if not isinstance(block, MicrophoneSignalBlock):
        raise TypeError("block must be a MicrophoneSignalBlock.")
