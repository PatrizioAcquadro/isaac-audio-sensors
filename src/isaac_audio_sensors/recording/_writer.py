"""Internal streaming state and WAV shard writer."""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors.recording._atomic import _publish_path, _write_all

_WAV_HEADER_BYTES = 44
_FLOAT32_BYTES = 4
_UINT32_MAX = (1 << 32) - 1


class CarryState:
    """Channel-first overlap samples awaiting later output."""

    def __init__(self, pending_samples: np.ndarray | None = None) -> None:
        samples = (
            np.zeros((0, 0), dtype=np.float32)
            if pending_samples is None
            else pending_samples
        )
        self._pending = self._validated(samples)

    @staticmethod
    def _validated(samples: np.ndarray) -> np.ndarray:
        pending = np.asarray(samples, dtype=np.float32)
        if pending.ndim != 2:
            raise ValueError("carry samples must have shape (channels, samples)")
        return np.ascontiguousarray(pending)

    @property
    def pending_samples(self) -> np.ndarray:
        return self._pending

    def take(self) -> np.ndarray:
        pending = self._pending
        self._pending = np.zeros((pending.shape[0], 0), dtype=np.float32)
        return pending

    def replace(self, pending_samples: np.ndarray) -> None:
        self._pending = self._validated(pending_samples)


class StreamingWavShardWriter:
    """Write deterministic channel-first float32 blocks as interleaved WAV."""

    def __init__(
        self,
        staging_dir: str | Path,
        *,
        channels: int,
        sample_rate_hz: int,
        carry_state: CarryState | None = None,
        filename: str = "audio.wav",
        checksum_chunk_size: int = 1024 * 1024,
    ) -> None:
        if type(channels) is not int or channels <= 0:
            raise ValueError("channels must be a positive integer")
        if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be a positive integer")
        if channels * _FLOAT32_BYTES > 0xFFFF:
            raise ValueError("channels exceed the WAV block-align limit")
        if sample_rate_hz > _UINT32_MAX:
            raise ValueError("sample_rate_hz exceeds the WAV uint32 limit")
        if sample_rate_hz * channels * _FLOAT32_BYTES > _UINT32_MAX:
            raise ValueError("WAV byte rate exceeds the uint32 limit")
        if filename != "audio.wav":
            raise ValueError("filename must be 'audio.wav'")
        if checksum_chunk_size <= 0:
            raise ValueError("checksum_chunk_size must be positive")

        self.staging_dir = Path(staging_dir)
        self.path = self.staging_dir / filename
        self.channels = channels
        self.sample_rate_hz = sample_rate_hz
        self.checksum_chunk_size = checksum_chunk_size
        self.carry_state = carry_state or CarryState(
            np.zeros((channels, 0), dtype=np.float32)
        )
        pending = self.carry_state.pending_samples
        if pending.shape == (0, 0):
            self.carry_state.replace(np.zeros((channels, 0), dtype=np.float32))
        elif pending.shape[0] != channels:
            raise ValueError("carry channel count does not match WAV channel count")

        self._sample_count = 0
        self._data_bytes = 0
        self._failed = False
        self._closed = False
        self._finalized = False
        self._published = False
        self._result: dict[str, Any] | None = None
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._stream: BinaryIO = self.path.open("w+b")
        try:
            self._write_bytes(self._header(0, 0))
        except BaseException:
            self._failed = True
            self._stream.close()
            self._closed = True
            raise

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def failed(self) -> bool:
        return self._failed

    def _header(self, riff_size: int, data_size: int) -> bytes:
        block_align = self.channels * _FLOAT32_BYTES
        byte_rate = self.sample_rate_hz * block_align
        fmt = struct.pack(
            "<HHIIHH", 3, self.channels, self.sample_rate_hz, byte_rate, block_align, 32
        )
        return (
            b"RIFF"
            + struct.pack("<I", riff_size)
            + b"WAVEfmt "
            + struct.pack("<I", len(fmt))
            + fmt
            + b"data"
            + struct.pack("<I", data_size)
        )

    def _write_bytes(self, payload: bytes) -> int:
        return _write_all(self._stream, payload)

    def append(self, samples: np.ndarray) -> int:
        return self.append_samples(samples)

    def append_samples(self, samples: np.ndarray) -> int:
        if self._closed or self._finalized:
            raise RuntimeError("WAV shard writer is finalized or closed")
        if self._failed:
            raise RuntimeError("WAV shard writer is in a failed state")
        block = np.asarray(samples, dtype=np.float32)
        if block.ndim != 2 or block.shape[0] != self.channels:
            raise ValueError(f"samples must have shape ({self.channels}, sample_count)")
        frame_count = int(block.shape[1])
        payload_size = frame_count * self.channels * _FLOAT32_BYTES
        new_size = self._data_bytes + payload_size
        if new_size > _UINT32_MAX or 36 + new_size > _UINT32_MAX:
            raise ValueError("WAV shard exceeds the RIFF 32-bit size limit")
        if frame_count == 0:
            return 0
        try:
            self._write_bytes(np.ascontiguousarray(block.T, dtype="<f4").tobytes())
        except BaseException:
            self._failed = True
            raise
        self._sample_count += frame_count
        self._data_bytes = new_size
        return frame_count

    def _patch_sizes(self) -> None:
        self._stream.seek(4)
        self._write_bytes(struct.pack("<I", 36 + self._data_bytes))
        self._stream.seek(40)
        self._write_bytes(struct.pack("<I", self._data_bytes))

    def _hash_patched_file(self) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_count = 0
        self._stream.seek(0)
        while chunk := self._stream.read(self.checksum_chunk_size):
            digest.update(chunk)
            byte_count += len(chunk)
        return digest.hexdigest(), byte_count

    def finalize(self, *, flush_carry: bool) -> dict[str, Any]:
        if type(flush_carry) is not bool:
            raise TypeError("flush_carry must be a bool")
        if self._finalized:
            assert self._result is not None
            return dict(self._result)
        if self._closed or self._failed:
            raise RuntimeError("WAV shard writer is closed or failed")
        try:
            if flush_carry and self.carry_state.pending_samples.shape[1]:
                self.append_samples(self.carry_state.pending_samples)
                self.carry_state.replace(np.zeros((self.channels, 0), dtype=np.float32))
            self._patch_sizes()
            self._stream.flush()
            sha256, byte_count = self._hash_patched_file()
            expected = _WAV_HEADER_BYTES + self._data_bytes
            if byte_count != expected:
                raise OSError(
                    f"staged WAV byte count {byte_count} != expected {expected}"
                )
            os.fsync(self._stream.fileno())
            self._stream.close()
            self._closed = True
        except BaseException:
            self._failed = True
            raise
        self._finalized = True
        self._result = {
            "sample_count": self._sample_count,
            "sha256": sha256,
            "bytes": byte_count,
        }
        return dict(self._result)

    def publish(self, final_path: str | Path) -> dict[str, Any]:
        if not self._finalized or self._result is None:
            raise RuntimeError("WAV shard must be finalized before publication")
        if self._failed or self._published:
            raise RuntimeError("WAV shard is failed or already published")
        _publish_path(self.path, Path(final_path))
        self._published = True
        return dict(self._result)

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True
        if not self._published:
            self.path.unlink(missing_ok=True)


__all__: list[str] = []
