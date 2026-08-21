"""Internal durable file publication primitives."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO


def _write_all(stream: BinaryIO, data: bytes) -> int:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = stream.write(view[written:])
        if not isinstance(count, int) or count <= 0:
            raise OSError("write made no progress")
        written += count
    return written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_path(staged_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_path, final_path)
    _fsync_directory(final_path.parent)


class StagedFile:
    """Append-only staged file with rolling size and SHA-256."""

    def __init__(self, staging_dir: str | Path, filename: str) -> None:
        if not filename or Path(filename).name != filename:
            raise ValueError("filename must be one non-empty path component")
        self.staging_dir = Path(staging_dir)
        self.path = self.staging_dir / filename
        self._sha256 = hashlib.sha256()
        self._byte_count = 0
        self._failed = False
        self._closed = False
        self._published = False
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("wb")

    @property
    def byte_count(self) -> int:
        return self._byte_count

    @property
    def sha256(self) -> str:
        return self._sha256.hexdigest()

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def closed(self) -> bool:
        return self._closed

    def append(self, data: bytes | bytearray | memoryview) -> int:
        if self._closed:
            raise RuntimeError("staged file is closed")
        if self._failed:
            raise RuntimeError("staged file is in a failed state")
        payload = bytes(data)
        try:
            written = _write_all(self._stream, payload)
        except BaseException:
            self._failed = True
            raise
        self._sha256.update(payload)
        self._byte_count += written
        return written

    def flush_and_fsync(self) -> None:
        if self._closed:
            raise RuntimeError("staged file is closed")
        if self._failed:
            raise RuntimeError("staged file is in a failed state")
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except BaseException:
            self._failed = True
            raise

    def close(self) -> None:
        if not self._closed:
            self._stream.close()
            self._closed = True

    def abort(self) -> None:
        self.close()
        if not self._published:
            self.path.unlink(missing_ok=True)


def publish_file(staged: StagedFile, final_path: str | Path) -> dict[str, Any]:
    """Fsync and atomically publish a complete staged file."""

    if staged.failed:
        raise RuntimeError("cannot publish a failed staged file")
    if staged._published:
        raise RuntimeError("staged file is already published")
    staged.flush_and_fsync()
    staged.close()
    destination = Path(final_path)
    _publish_path(staged.path, destination)
    staged._published = True
    return {
        "path": destination.name,
        "sha256": staged.sha256,
        "bytes": staged.byte_count,
    }


def write_json_atomic(
    final_path: str | Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Write deterministic JSON through a same-directory temporary file."""

    destination = Path(final_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = StagedFile(destination.parent, f".{destination.name}.tmp")
    try:
        staged.append(
            (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode()
        )
        return publish_file(staged, destination)
    except BaseException:
        staged.abort()
        raise


def write_bytes_atomic(final_path: str | Path, data: bytes) -> dict[str, Any]:
    """Atomically publish exact bytes."""

    destination = Path(final_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = StagedFile(destination.parent, f".{destination.name}.tmp")
    try:
        staged.append(data)
        return publish_file(staged, destination)
    except BaseException:
        staged.abort()
        raise


class JsonlShardFile:
    """Streaming writer for canonical ``frames.jsonl``."""

    def __init__(
        self,
        staging_dir: str | Path,
        *,
        filename: str = "frames.jsonl",
    ) -> None:
        self._staged = StagedFile(staging_dir, filename)
        self.line_count = 0

    @property
    def path(self) -> Path:
        return self._staged.path

    @property
    def byte_count(self) -> int:
        return self._staged.byte_count

    @property
    def sha256(self) -> str:
        return self._staged.sha256

    def append(self, line: str) -> int:
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
        written = self._staged.append(line.encode())
        self.line_count += 1
        return written

    def flush_and_fsync(self) -> None:
        self._staged.flush_and_fsync()

    def publish(self, final_path: str | Path) -> dict[str, Any]:
        return publish_file(self._staged, final_path)

    def abort(self) -> None:
        self._staged.abort()


__all__: list[str] = []
