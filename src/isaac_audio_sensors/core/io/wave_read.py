"""Read exported WAV files for GUI preview and audition.

Uses ``soundfile`` when available (the same library the waveform writers
require), and falls back to a small stdlib RIFF parser for the formats this
package writes (IEEE float32) plus PCM16, so the GUI panel can preview WAVs
without the optional ``room`` extra installed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_WAVE_FORMAT_PCM = 1
_WAVE_FORMAT_IEEE_FLOAT = 3
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


@dataclass(frozen=True, slots=True, kw_only=True)
class WaveData:
    """Decoded multichannel waveform (``samples`` is ``[channel, frame]``)."""

    samples: np.ndarray
    sample_rate_hz: int
    source_path: str

    @property
    def channel_count(self) -> int:
        return int(self.samples.shape[0])

    @property
    def frame_count(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration_s(self) -> float:
        if self.sample_rate_hz <= 0:
            return 0.0
        return self.frame_count / float(self.sample_rate_hz)


def read_wav(path: str | Path) -> WaveData:
    """Read a WAV file into float32 ``[channel, frame]`` samples."""

    wav_path = Path(path)
    try:
        import soundfile  # type: ignore
    except ImportError:
        return _read_wav_stdlib(wav_path)
    data, sample_rate = soundfile.read(
        str(wav_path), always_2d=True, dtype="float32"
    )
    return WaveData(
        samples=np.ascontiguousarray(data.T),
        sample_rate_hz=int(sample_rate),
        source_path=str(wav_path),
    )


def _read_wav_stdlib(path: Path) -> WaveData:
    blob = path.read_bytes()
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError(f"Not a RIFF/WAVE file: {path}")
    fmt: dict[str, int] | None = None
    data: bytes | None = None
    offset = 12
    while offset + 8 <= len(blob):
        chunk_id = blob[offset : offset + 4]
        (chunk_size,) = struct.unpack_from("<I", blob, offset + 4)
        body = blob[offset + 8 : offset + 8 + chunk_size]
        if chunk_id == b"fmt ":
            fmt = _parse_fmt_chunk(body)
        elif chunk_id == b"data":
            data = body
        offset += 8 + chunk_size + (chunk_size % 2)
    if fmt is None or data is None:
        raise ValueError(f"WAV file is missing fmt/data chunks: {path}")
    channels = max(1, fmt["channels"])
    audio_format = fmt["audio_format"]
    bits = fmt["bits_per_sample"]
    if audio_format == _WAVE_FORMAT_IEEE_FLOAT and bits == 32:
        flat = np.frombuffer(data, dtype="<f4").astype(np.float32)
    elif audio_format == _WAVE_FORMAT_PCM and bits == 16:
        flat = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    else:
        raise ValueError(
            "Unsupported WAV encoding for the stdlib reader "
            f"(format={audio_format}, bits={bits}); install the 'room' extra "
            "for full soundfile decoding."
        )
    frame_count = flat.size // channels
    samples = flat[: frame_count * channels].reshape(frame_count, channels).T
    return WaveData(
        samples=np.ascontiguousarray(samples),
        sample_rate_hz=fmt["sample_rate_hz"],
        source_path=str(path),
    )


def _parse_fmt_chunk(body: bytes) -> dict[str, int]:
    if len(body) < 16:
        raise ValueError("WAV fmt chunk is too short.")
    audio_format, channels, sample_rate, _, _, bits = struct.unpack_from(
        "<HHIIHH", body, 0
    )
    if audio_format == _WAVE_FORMAT_EXTENSIBLE and len(body) >= 26:
        (sub_format,) = struct.unpack_from("<H", body, 24)
        audio_format = sub_format
    return {
        "audio_format": int(audio_format),
        "channels": int(channels),
        "sample_rate_hz": int(sample_rate),
        "bits_per_sample": int(bits),
    }
