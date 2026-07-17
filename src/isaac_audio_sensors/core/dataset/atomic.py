"""Atomic, injectable filesystem primitives for dataset writers."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO

OperationHook = Callable[[str, int], None]
WriteHook = Callable[[BinaryIO, bytes, int], int | None]

_TRANSIENT_WRITE_ERRNOS = {
    errno.EAGAIN,
    errno.EBUSY,
    errno.EINTR,
    errno.ETIMEDOUT,
}
if errno.EWOULDBLOCK != errno.EAGAIN:
    _TRANSIENT_WRITE_ERRNOS.add(errno.EWOULDBLOCK)


class CancelledWrite(RuntimeError):
    """Raised when a cooperative dataset write is cancelled."""


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation."""

        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""

        return self._event.is_set()

    def check(self) -> None:
        """Raise :class:`CancelledWrite` if cancellation was requested."""

        if self.cancelled:
            raise CancelledWrite("dataset write was cancelled")


class FilesystemSeam:
    """Small filesystem boundary used by writers and fault-injection tests.

    Hooks run immediately before an operation. Their index is one-based and
    local to the operation name, which makes fault schedules independent of
    unrelated filesystem calls. ``write_hook`` may return a prefix length to
    force a short write; ``None`` writes the full input.
    """

    def __init__(
        self,
        *,
        operation_hook: OperationHook | None = None,
        delay_hook: OperationHook | None = None,
        write_hook: WriteHook | None = None,
    ) -> None:
        self._operation_hook = operation_hook
        self._delay_hook = delay_hook
        self._write_hook = write_hook
        self._counts: defaultdict[str, int] = defaultdict(int)

    def operation_count(self, operation: str) -> int:
        """Return how many times ``operation`` has crossed this seam."""

        return self._counts[operation]

    def _before(self, operation: str) -> int:
        self._counts[operation] += 1
        index = self._counts[operation]
        if self._delay_hook is not None:
            self._delay_hook(operation, index)
        if self._operation_hook is not None:
            self._operation_hook(operation, index)
        return index

    def open(self, path: str | Path, mode: str) -> BinaryIO:
        """Open a binary file."""

        self._before("open")
        if "b" not in mode:
            raise ValueError("FilesystemSeam.open requires binary mode")
        return open(path, mode)  # noqa: SIM115 - caller owns the stream lifetime

    def open_directory(self, path: str | Path) -> int:
        """Open a directory descriptor for durability fsync."""

        self._before("open_directory")
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        return os.open(path, flags)

    def write(self, stream: BinaryIO, data: bytes) -> int:
        """Write bytes, allowing an injected short-write result."""

        index = self._before("write")
        if self._write_hook is not None:
            result = self._write_hook(stream, data, index)
            if result is not None:
                if result < 0 or result > len(data):
                    raise OSError(errno.EIO, f"invalid write-hook result: {result}")
                return stream.write(data[:result])
        return stream.write(data)

    def read(self, stream: BinaryIO, size: int) -> bytes:
        """Read at most ``size`` bytes."""

        self._before("read")
        return stream.read(size)

    def seek(self, stream: BinaryIO, offset: int, whence: int = os.SEEK_SET) -> int:
        """Seek a binary stream."""

        self._before("seek")
        return stream.seek(offset, whence)

    def flush(self, stream: BinaryIO) -> None:
        """Flush Python buffering."""

        self._before("flush")
        stream.flush()

    def fsync(self, stream_or_fd: BinaryIO | int) -> None:
        """Synchronize a file or directory descriptor."""

        self._before("fsync")
        descriptor = (
            stream_or_fd
            if isinstance(stream_or_fd, int)
            else stream_or_fd.fileno()
        )
        os.fsync(descriptor)

    def close(self, stream_or_fd: BinaryIO | int) -> None:
        """Close a file object or raw descriptor."""

        self._before("close")
        if isinstance(stream_or_fd, int):
            os.close(stream_or_fd)
        else:
            stream_or_fd.close()

    def replace(self, source: str | Path, destination: str | Path) -> None:
        """Atomically replace ``destination`` with ``source``."""

        self._before("replace")
        os.replace(source, destination)

    def mkdir(
        self,
        path: str | Path,
        *,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Create a directory."""

        self._before("mkdir")
        Path(path).mkdir(parents=parents, exist_ok=exist_ok)

    def remove(self, path: str | Path, *, missing_ok: bool = False) -> None:
        """Remove one file."""

        self._before("remove")
        try:
            os.remove(path)
        except FileNotFoundError:
            if not missing_ok:
                raise


def write_with_retry(
    seam: FilesystemSeam,
    stream: BinaryIO,
    data: bytes | bytearray | memoryview,
    *,
    max_attempts: int = 3,
    cancellation_token: CancellationToken | None = None,
) -> int:
    """Write all bytes, retrying only transient errors a bounded number of times.

    Short writes are completed without treating them as failures. ENOSPC and
    all non-transient errors surface immediately.
    """

    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    payload = bytes(data)
    offset = 0
    failures = 0
    while offset < len(payload):
        if cancellation_token is not None:
            cancellation_token.check()
        try:
            written = seam.write(stream, payload[offset:])
        except OSError as exc:
            if exc.errno == errno.ENOSPC or exc.errno not in _TRANSIENT_WRITE_ERRNOS:
                raise
            failures += 1
            if failures >= max_attempts:
                raise
            continue
        if (
            not isinstance(written, int)
            or written < 0
            or written > len(payload) - offset
        ):
            raise OSError(errno.EIO, f"invalid short-write result: {written!r}")
        if written == 0:
            raise OSError(errno.EIO, "write made no progress")
        offset += written
    return offset


class StagedFile:
    """Append-only staged file with an incremental SHA-256 and byte count."""

    def __init__(
        self,
        staging_dir: str | Path,
        filename: str,
        *,
        seam: FilesystemSeam | None = None,
        retry_attempts: int = 3,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        if not filename or Path(filename).name != filename:
            raise ValueError("filename must be one non-empty path component")
        if retry_attempts <= 0:
            raise ValueError("retry_attempts must be positive")
        self.seam = seam or FilesystemSeam()
        self.staging_dir = Path(staging_dir)
        self.path = self.staging_dir / filename
        self.retry_attempts = retry_attempts
        self.cancellation_token = cancellation_token
        self._sha256 = hashlib.sha256()
        self._byte_count = 0
        self._failed = False
        self._closed = False
        self._published = False
        self.seam.mkdir(self.staging_dir, parents=True, exist_ok=True)
        self._stream = self.seam.open(self.path, "wb")

    @property
    def byte_count(self) -> int:
        """Number of successfully appended payload bytes."""

        return self._byte_count

    @property
    def sha256(self) -> str:
        """Digest of successfully appended payload bytes."""

        return self._sha256.hexdigest()

    @property
    def failed(self) -> bool:
        """Whether an append or durability operation failed."""

        return self._failed

    @property
    def closed(self) -> bool:
        """Whether the staged stream is closed."""

        return self._closed

    def append(self, data: bytes | bytearray | memoryview) -> int:
        """Append bytes and update the rolling metadata after full success."""

        if self._closed:
            raise RuntimeError("staged file is closed")
        if self._failed:
            raise RuntimeError("staged file is in a failed state")
        payload = bytes(data)
        try:
            if self.cancellation_token is not None:
                self.cancellation_token.check()
            written = write_with_retry(
                self.seam,
                self._stream,
                payload,
                max_attempts=self.retry_attempts,
                cancellation_token=self.cancellation_token,
            )
        except BaseException:
            self._failed = True
            raise
        self._sha256.update(payload)
        self._byte_count += written
        return written

    def flush_and_fsync(self) -> None:
        """Flush and synchronize the staged payload."""

        if self._closed:
            raise RuntimeError("staged file is closed")
        if self._failed:
            raise RuntimeError("staged file is in a failed state")
        try:
            self.seam.flush(self._stream)
            self.seam.fsync(self._stream)
        except BaseException:
            self._failed = True
            raise

    def close(self) -> None:
        """Close the staged stream without publishing it."""

        if not self._closed:
            self.seam.close(self._stream)
            self._closed = True

    def abort(self) -> None:
        """Close and remove the unpublished staged file."""

        if not self._closed:
            try:
                self.seam.close(self._stream)
            finally:
                self._closed = True
        if not self._published:
            self.seam.remove(self.path, missing_ok=True)


def _fsync_directory(path: Path, seam: FilesystemSeam) -> None:
    descriptor = seam.open_directory(path)
    try:
        seam.fsync(descriptor)
    finally:
        seam.close(descriptor)


def _publish_path(staged_path: Path, final_path: Path, seam: FilesystemSeam) -> None:
    seam.mkdir(final_path.parent, parents=True, exist_ok=True)
    seam.replace(staged_path, final_path)
    _fsync_directory(final_path.parent, seam)


def publish_file(staged: StagedFile, final_path: str | Path) -> dict[str, Any]:
    """Durably publish one fully written staged file with atomic replacement."""

    if staged.failed:
        raise RuntimeError("cannot publish a failed staged file")
    if staged._published:
        raise RuntimeError("staged file is already published")
    staged.flush_and_fsync()
    staged.close()
    destination = Path(final_path)
    _publish_path(staged.path, destination, staged.seam)
    staged._published = True
    return {
        "path": destination.name,
        "sha256": staged.sha256,
        "bytes": staged.byte_count,
    }


def write_json_atomic(
    final_path: str | Path,
    payload: Mapping[str, Any],
    *,
    seam: FilesystemSeam | None = None,
    cancellation_token: CancellationToken | None = None,
    retry_attempts: int = 3,
) -> dict[str, Any]:
    """Write deterministic pretty JSON through a same-directory temp file."""

    destination = Path(final_path)
    filesystem = seam or FilesystemSeam()
    filesystem.mkdir(destination.parent, parents=True, exist_ok=True)
    staged = StagedFile(
        destination.parent,
        f".{destination.name}.tmp",
        seam=filesystem,
        retry_attempts=retry_attempts,
        cancellation_token=cancellation_token,
    )
    try:
        data = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        staged.append(data)
        result = publish_file(staged, destination)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise
    return result


class JsonlShardFile:
    """Streaming writer for one shard's canonical ``frames.jsonl``."""

    def __init__(
        self,
        staging_dir: str | Path,
        *,
        seam: FilesystemSeam | None = None,
        cancellation_token: CancellationToken | None = None,
        retry_attempts: int = 3,
        filename: str = "frames.jsonl",
    ) -> None:
        self._staged = StagedFile(
            staging_dir,
            filename,
            seam=seam,
            cancellation_token=cancellation_token,
            retry_attempts=retry_attempts,
        )
        self.line_count = 0

    @property
    def path(self) -> Path:
        """Path of the in-flight staged JSONL file."""

        return self._staged.path

    @property
    def byte_count(self) -> int:
        """Number of fully appended bytes."""

        return self._staged.byte_count

    @property
    def sha256(self) -> str:
        """Rolling digest of fully appended lines."""

        return self._staged.sha256

    def append(self, line: str) -> int:
        """Append one already-canonical, newline-terminated record line."""

        if not isinstance(line, str):
            raise TypeError("JSONL record line must be text")
        if (
            not line.endswith("\n")
            or len(line) == 1
            or "\n" in line[:-1]
            or "\r" in line
        ):
            raise ValueError(
                "JSONL record must be non-empty, single-line, and newline-terminated"
            )
        written = self._staged.append(line.encode("utf-8"))
        self.line_count += 1
        return written

    def flush_and_fsync(self) -> None:
        """Flush and synchronize the staged JSONL file."""

        self._staged.flush_and_fsync()

    def publish(self, final_path: str | Path) -> dict[str, Any]:
        """Atomically publish the complete JSONL file."""

        return publish_file(self._staged, final_path)

    def abort(self) -> None:
        """Remove the unpublished staged JSONL file."""

        self._staged.abort()


__all__ = [
    "CancellationToken",
    "CancelledWrite",
    "FilesystemSeam",
    "JsonlShardFile",
    "StagedFile",
    "publish_file",
    "write_json_atomic",
    "write_with_retry",
]
