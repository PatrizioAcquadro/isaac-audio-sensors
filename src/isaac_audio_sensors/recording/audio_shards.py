"""Dependency-light streaming WAV primitives for dataset shards."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors.recording.atomic import (
    CancellationToken,
    FilesystemSeam,
    _publish_path,
    write_with_retry,
)

_WAV_HEADER_BYTES = 44
_WAV_FORMAT_IEEE_FLOAT = 3
_FLOAT32_BYTES = 4
_UINT32_MAX = (1 << 32) - 1


class CarryState:
    """Explicit channel-first overlap/reverb samples awaiting later output."""

    def __init__(self, pending_samples: np.ndarray | None = None) -> None:
        if pending_samples is None:
            self._pending = np.zeros((0, 0), dtype=np.float32)
        else:
            self._pending = self._validated(pending_samples)

    @staticmethod
    def _validated(samples: np.ndarray) -> np.ndarray:
        pending = np.asarray(samples, dtype=np.float32)
        if pending.ndim != 2:
            raise ValueError("carry samples must have shape (channels, samples)")
        return np.ascontiguousarray(pending)

    @property
    def pending_samples(self) -> np.ndarray:
        """Current channel-first pending samples."""

        return self._pending

    def take(self) -> np.ndarray:
        """Transfer ownership of the pending samples and leave an empty carry."""

        pending = self._pending
        self._pending = np.zeros((pending.shape[0], 0), dtype=np.float32)
        return pending

    def replace(self, pending_samples: np.ndarray) -> None:
        """Replace the pending samples with a contiguous float32 array."""

        self._pending = self._validated(pending_samples)


class StreamingWavShardWriter:
    """Stream one deterministic IEEE-float32 WAV asset into shard staging.

    Input blocks and carry are channel-first arrays with shape
    ``(channels, samples)``. The on-disk payload is frame-major interleaved
    little-endian float32.
    """

    def __init__(
        self,
        staging_dir: str | Path,
        *,
        channels: int,
        sample_rate_hz: int,
        seam: FilesystemSeam | None = None,
        carry_state: CarryState | None = None,
        cancellation_token: CancellationToken | None = None,
        retry_attempts: int = 3,
        filename: str = "audio.wav",
        checksum_chunk_size: int = 1024 * 1024,
    ) -> None:
        if isinstance(channels, bool) or not isinstance(channels, int) or channels <= 0:
            raise ValueError("channels must be a positive integer")
        if (
            isinstance(sample_rate_hz, bool)
            or not isinstance(sample_rate_hz, int)
            or sample_rate_hz <= 0
        ):
            raise ValueError("sample_rate_hz must be a positive integer")
        if channels * _FLOAT32_BYTES > 0xFFFF:
            raise ValueError("channels exceed the WAV block-align limit")
        if sample_rate_hz > _UINT32_MAX:
            raise ValueError("sample_rate_hz exceeds the WAV uint32 limit")
        if sample_rate_hz * channels * _FLOAT32_BYTES > _UINT32_MAX:
            raise ValueError("WAV byte rate exceeds the uint32 limit")
        if not filename or Path(filename).name != filename or filename != "audio.wav":
            raise ValueError("filename must be 'audio.wav'")
        if retry_attempts <= 0:
            raise ValueError("retry_attempts must be positive")
        if checksum_chunk_size <= 0:
            raise ValueError("checksum_chunk_size must be positive")

        self.seam = seam or FilesystemSeam()
        self.staging_dir = Path(staging_dir)
        self.path = self.staging_dir / filename
        self.channels = channels
        self.sample_rate_hz = sample_rate_hz
        self.cancellation_token = cancellation_token
        self.retry_attempts = retry_attempts
        self.checksum_chunk_size = checksum_chunk_size
        self.carry_state = carry_state or CarryState(
            np.zeros((channels, 0), dtype=np.float32)
        )
        pending = self.carry_state.pending_samples
        if pending.shape[0] == 0 and pending.shape[1] == 0:
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
        self.seam.mkdir(self.staging_dir, parents=True, exist_ok=True)
        self._stream: BinaryIO = self.seam.open(self.path, "w+b")
        try:
            self._write_bytes(self._header(riff_size=0, data_size=0))
        except BaseException:
            self._failed = True
            try:
                self.seam.close(self._stream)
            finally:
                self._closed = True
            raise

    @property
    def sample_count(self) -> int:
        """Number of multichannel sample frames currently written."""

        return self._sample_count

    @property
    def failed(self) -> bool:
        """Whether a streaming or finalization operation failed."""

        return self._failed

    def _header(self, *, riff_size: int, data_size: int) -> bytes:
        block_align = self.channels * _FLOAT32_BYTES
        byte_rate = self.sample_rate_hz * block_align
        fmt = struct.pack(
            "<HHIIHH",
            _WAV_FORMAT_IEEE_FLOAT,
            self.channels,
            self.sample_rate_hz,
            byte_rate,
            block_align,
            32,
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
        return write_with_retry(
            self.seam,
            self._stream,
            payload,
            max_attempts=self.retry_attempts,
            cancellation_token=self.cancellation_token,
        )

    def append(self, samples: np.ndarray) -> int:
        """Append one channel-first multichannel float sample block."""

        return self.append_samples(samples)

    def append_samples(self, samples: np.ndarray) -> int:
        """Append one channel-first multichannel float sample block."""

        if self._closed or self._finalized:
            raise RuntimeError("WAV shard writer is finalized or closed")
        if self._failed:
            raise RuntimeError("WAV shard writer is in a failed state")
        block = np.asarray(samples, dtype=np.float32)
        if block.ndim != 2 or block.shape[0] != self.channels:
            raise ValueError(
                f"samples must have shape ({self.channels}, sample_count)"
            )
        frame_count = int(block.shape[1])
        payload_size = frame_count * self.channels * _FLOAT32_BYTES
        new_data_bytes = self._data_bytes + payload_size
        if new_data_bytes > _UINT32_MAX or 36 + new_data_bytes > _UINT32_MAX:
            raise ValueError("WAV shard exceeds the RIFF 32-bit size limit")
        if frame_count == 0:
            if self.cancellation_token is not None:
                self.cancellation_token.check()
            return 0
        interleaved = np.ascontiguousarray(block.T, dtype="<f4")
        try:
            self._write_bytes(interleaved.tobytes(order="C"))
        except BaseException:
            self._failed = True
            raise
        self._sample_count += frame_count
        self._data_bytes = new_data_bytes
        return frame_count

    def _patch_sizes(self) -> None:
        self.seam.seek(self._stream, 4)
        self._write_bytes(struct.pack("<I", 36 + self._data_bytes))
        self.seam.seek(self._stream, 40)
        self._write_bytes(struct.pack("<I", self._data_bytes))

    def _hash_patched_file(self) -> tuple[str, int]:
        digest = hashlib.sha256()
        byte_count = 0
        self.seam.seek(self._stream, 0)
        while True:
            chunk = self.seam.read(self._stream, self.checksum_chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
        return digest.hexdigest(), byte_count

    def finalize(self, *, flush_carry: bool) -> dict[str, Any]:
        """Optionally append carry, patch sizes, hash once, and fsync staging.

        With ``flush_carry=False`` the carry state is not read or modified, so
        its exact samples remain available to ``CarryState.take()`` for the
        next shard.
        """

        if not isinstance(flush_carry, bool):
            raise TypeError("flush_carry must be a bool")
        if self._finalized:
            assert self._result is not None
            return dict(self._result)
        if self._closed:
            raise RuntimeError("WAV shard writer is closed")
        if self._failed:
            raise RuntimeError("WAV shard writer is in a failed state")
        try:
            if self.cancellation_token is not None:
                self.cancellation_token.check()
            if flush_carry and self.carry_state.pending_samples.shape[1] > 0:
                self.append_samples(self.carry_state.pending_samples)
                self.carry_state.replace(
                    np.zeros((self.channels, 0), dtype=np.float32)
                )
            self._patch_sizes()
            self.seam.flush(self._stream)
            sha256, byte_count = self._hash_patched_file()
            expected_bytes = _WAV_HEADER_BYTES + self._data_bytes
            if byte_count != expected_bytes:
                raise OSError(
                    f"staged WAV byte count {byte_count} != expected {expected_bytes}"
                )
            self.seam.fsync(self._stream)
            self.seam.close(self._stream)
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
        """Atomically publish a finalized WAV and fsync its parent directory."""

        if not self._finalized or self._result is None:
            raise RuntimeError("WAV shard must be finalized before publication")
        if self._failed:
            raise RuntimeError("cannot publish a failed WAV shard")
        if self._published:
            raise RuntimeError("WAV shard is already published")
        destination = Path(final_path)
        _publish_path(self.path, destination, self.seam)
        self._published = True
        return dict(self._result)

    def abort(self) -> None:
        """Close and remove the unpublished staged WAV."""

        if not self._closed:
            try:
                self.seam.close(self._stream)
            finally:
                self._closed = True
        if not self._published:
            self.seam.remove(self.path, missing_ok=True)


__all__ = ["CarryState", "StreamingWavShardWriter"]
