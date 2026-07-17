"""Pure session-layout planning and validation for audio datasets.

This module implements the frozen ``ias.dataset_frame_record.v1`` and
``ias.shard_completion.v1`` dataset-layer contracts.  It deliberately has no
Isaac or optional audio-writer dependencies; WAV inspection uses the core
stdlib-capable reader.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from isaac_audio_sensors.core.dataset_manifest import AudioDatasetManifest
from isaac_audio_sensors.core.io.calibration import read_calibration_profile
from isaac_audio_sensors.core.io.manifests import read_dataset_manifest
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.io.wave_read import read_wav
from isaac_audio_sensors.core.types import AudioSensorFrame

DATASET_FRAME_RECORD_VERSION = "ias.dataset_frame_record.v1"
SHARD_COMPLETION_VERSION = "ias.shard_completion.v1"
ID_LIMIT = 100_000

_EPISODE_ID_RE = re.compile(r"^episode_[0-9]{5}$")
_SHARD_ID_RE = re.compile(r"^shard_[0-9]{5}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_ROOT_ENTRIES = frozenset(
    {"manifest.json", "config", "calibration", "shards", "_staging"}
)
_MARKER_FIELDS = frozenset(
    {
        "marker_version",
        "shard_id",
        "start_frame",
        "frame_count",
        "episode_ids",
        "files",
        "audio",
        "tail_samples",
        "dropped_frames",
        "writer_tool_version",
    }
)
_FILE_FIELDS = frozenset({"path", "sha256", "bytes"})
_AUDIO_FIELDS = frozenset(
    {
        "path",
        "container",
        "subtype",
        "channels",
        "sample_rate_hz",
        "dtype",
        "sample_count",
    }
)
_DROPPED_FIELDS = frozenset({"count", "producer_frame_ids"})


class DatasetLayoutError(ValueError):
    """A located session-layout contract violation."""


@dataclass(frozen=True, slots=True)
class LayoutWarning:
    """A non-fatal portability observation."""

    location: str
    message: str


@dataclass(frozen=True, slots=True)
class DatasetFrameRecord:
    """One frame-to-shard-audio join record."""

    dataset_frame_index: int
    episode_id: str
    audio_start_sample: int
    audio_end_sample: int
    frame: dict[str, Any]
    record_version: str = DATASET_FRAME_RECORD_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return the record without modifying its nested frame dictionary."""

        return {
            "record_version": self.record_version,
            "dataset_frame_index": self.dataset_frame_index,
            "episode_id": self.episode_id,
            "audio_start_sample": self.audio_start_sample,
            "audio_end_sample": self.audio_end_sample,
            "frame": self.frame,
        }


@dataclass(frozen=True, slots=True)
class ShardBoundary:
    """A deterministic half-open output shard boundary."""

    shard_id: str
    shard_ordinal: int
    start_frame: int
    frame_count: int
    episode_ids: tuple[str, ...]
    split_groups: tuple[str, ...]
    exclusive_oversized_episode: bool

    @property
    def end_frame(self) -> int:
        """Return the inclusive final dataset-frame index."""

        return self.start_frame + self.frame_count - 1


@dataclass(frozen=True, slots=True)
class VerifiedShard:
    """A verified marker together with its parsed records."""

    shard_dir: Path
    marker: dict[str, Any]
    records: tuple[DatasetFrameRecord, ...]
    warnings: tuple[LayoutWarning, ...]


@dataclass(frozen=True, slots=True)
class SessionLayoutResult:
    """Successful session-layout validation output."""

    session_root: Path
    lifecycle_state: str
    manifest: AudioDatasetManifest | None
    shards: tuple[VerifiedShard, ...]
    warnings: tuple[LayoutWarning, ...]


@dataclass(frozen=True, slots=True)
class _RecordFileScan:
    records: tuple[DatasetFrameRecord, ...]
    warnings: tuple[LayoutWarning, ...]
    line_count: int
    episode_ids: tuple[str, ...]
    max_audio_end: int
    index_error: DatasetLayoutError | None
    producer_error: DatasetLayoutError | None


def episode_id(ordinal: int) -> str:
    """Derive the fixed-width episode id for ``ordinal``."""

    return _ordinal_id("episode", ordinal)


def shard_id(ordinal: int) -> str:
    """Derive the fixed-width shard id for ``ordinal``."""

    return _ordinal_id("shard", ordinal)


def _ordinal_id(prefix: str, ordinal: int) -> str:
    _require_non_negative_int(ordinal, f"{prefix} ordinal")
    if ordinal >= ID_LIMIT:
        raise ValueError(
            f"{prefix} ordinal {ordinal} exceeds the five-digit limit (99999)."
        )
    return f"{prefix}_{ordinal:05d}"


class ShardPlanner:
    """Incrementally compute §3 boundaries without inspecting frame payloads.

    ``feed_frame`` and ``end_episode`` are explicit because an aligned writer
    cannot know that the last received frame ends an episode.  Returned tuples
    contain every boundary made final by that event.  ``finish`` returns the
    final non-empty open shard.
    """

    def __init__(
        self,
        *,
        shard_max_frames: int,
        shard_episode_aligned: bool = True,
    ) -> None:
        _require_positive_int(shard_max_frames, "shard_max_frames")
        if not isinstance(shard_episode_aligned, bool):
            raise ValueError("shard_episode_aligned must be a bool.")
        self.shard_max_frames = shard_max_frames
        self.shard_episode_aligned = shard_episode_aligned
        self._next_episode_ordinal = 0
        self._current_episode_ordinal: int | None = None
        self._current_split_group: str | None = None
        self._current_episode_frames = 0
        self._buffer_start = 0
        self._buffer_frames = 0
        self._episode_oversized = False
        self._open_start = 0
        self._open_frames = 0
        self._open_episode_ids: list[str] = []
        self._open_split_groups: list[str] = []
        self._next_dataset_frame = 0
        self._next_shard_ordinal = 0
        self._finished = False
        self._max_buffered_frames = 0
        self._max_open_shard_frames = 0

    @property
    def max_buffered_frames(self) -> int:
        """Largest aligned episode-buffer inventory observed."""

        return self._max_buffered_frames

    @property
    def max_open_shard_frames(self) -> int:
        """Largest completed-episode open-shard inventory observed."""

        return self._max_open_shard_frames

    @property
    def staging_inventory(self) -> tuple[int, int]:
        """Return ``(episode_buffer_frames, open_shard_frames)``."""

        return self._buffer_frames, self._open_frames

    def feed_frame(
        self,
        episode_ordinal: int,
        split_group: str,
        frame: object = None,
    ) -> tuple[ShardBoundary, ...]:
        """Feed one written frame and return newly finalized boundaries."""

        del frame
        if self._finished:
            raise RuntimeError("ShardPlanner is already finished.")
        self._start_or_validate_episode(episode_ordinal, split_group)
        self._current_episode_frames += 1
        emitted: list[ShardBoundary] = []
        if self.shard_episode_aligned:
            if self._buffer_frames == 0:
                self._buffer_start = self._next_dataset_frame
            self._buffer_frames += 1
            self._max_buffered_frames = max(
                self._max_buffered_frames, self._buffer_frames
            )
            self._next_dataset_frame += 1
            if self._buffer_frames == self.shard_max_frames:
                if self._open_frames:
                    emitted.append(self._emit_open(exclusive=False))
                emitted.append(
                    self._emit_range(
                        start_frame=self._buffer_start,
                        frame_count=self._buffer_frames,
                        episode_ids=(episode_id(episode_ordinal),),
                        split_groups=(split_group,),
                        exclusive=True,
                    )
                )
                self._buffer_frames = 0
                self._episode_oversized = True
        else:
            if self._open_frames == 0:
                self._open_start = self._next_dataset_frame
            current_id = episode_id(episode_ordinal)
            if current_id not in self._open_episode_ids:
                self._open_episode_ids.append(current_id)
            if split_group not in self._open_split_groups:
                self._open_split_groups.append(split_group)
            self._open_frames += 1
            self._max_open_shard_frames = max(
                self._max_open_shard_frames, self._open_frames
            )
            self._next_dataset_frame += 1
            if self._open_frames == self.shard_max_frames:
                emitted.append(self._emit_open(exclusive=False))
        return tuple(emitted)

    def end_episode(self, episode_ordinal: int) -> tuple[ShardBoundary, ...]:
        """End the current non-empty episode and return finalized boundaries."""

        if self._current_episode_ordinal is None:
            raise ValueError("No episode is open.")
        if episode_ordinal != self._current_episode_ordinal:
            raise ValueError(
                f"Cannot end episode {episode_ordinal}; episode "
                f"{self._current_episode_ordinal} is open."
            )
        if self._current_episode_frames == 0:
            raise ValueError(f"Episode {episode_id(episode_ordinal)} has no frames.")
        emitted: list[ShardBoundary] = []
        if self.shard_episode_aligned:
            assert self._current_split_group is not None
            if self._episode_oversized:
                if self._buffer_frames:
                    emitted.append(
                        self._emit_range(
                            start_frame=self._buffer_start,
                            frame_count=self._buffer_frames,
                            episode_ids=(episode_id(episode_ordinal),),
                            split_groups=(self._current_split_group,),
                            exclusive=True,
                        )
                    )
                    self._buffer_frames = 0
            else:
                if self._open_frames and (
                    self._open_frames + self._buffer_frames > self.shard_max_frames
                    or self._current_split_group not in self._open_split_groups
                ):
                    emitted.append(self._emit_open(exclusive=False))
                if self._open_frames == 0:
                    self._open_start = self._buffer_start
                self._open_frames += self._buffer_frames
                self._open_episode_ids.append(episode_id(episode_ordinal))
                if self._current_split_group not in self._open_split_groups:
                    self._open_split_groups.append(self._current_split_group)
                self._max_open_shard_frames = max(
                    self._max_open_shard_frames, self._open_frames
                )
                self._buffer_frames = 0
        self._current_episode_ordinal = None
        self._current_split_group = None
        self._current_episode_frames = 0
        self._episode_oversized = False
        self._next_episode_ordinal += 1
        return tuple(emitted)

    def finish(self) -> tuple[ShardBoundary, ...]:
        """Finish the stream, rejecting an unterminated episode."""

        if self._finished:
            return ()
        if self._current_episode_ordinal is not None:
            raise ValueError(
                f"Episode {episode_id(self._current_episode_ordinal)} is still open."
            )
        self._finished = True
        if self._open_frames:
            return (self._emit_open(exclusive=False),)
        return ()

    def _start_or_validate_episode(
        self, episode_ordinal: int, split_group: str
    ) -> None:
        _require_non_negative_int(episode_ordinal, "episode ordinal")
        episode_id(episode_ordinal)
        if not isinstance(split_group, str) or not split_group:
            raise ValueError("split_group must be a non-empty string.")
        if self._current_episode_ordinal is None:
            if episode_ordinal != self._next_episode_ordinal:
                raise ValueError(
                    "Episodes must be fed in contiguous ordinal order; expected "
                    f"{self._next_episode_ordinal}, got {episode_ordinal}."
                )
            self._current_episode_ordinal = episode_ordinal
            self._current_split_group = split_group
        elif (
            episode_ordinal != self._current_episode_ordinal
            or split_group != self._current_split_group
        ):
            raise ValueError("End the current episode before feeding another one.")

    def _emit_open(self, *, exclusive: bool) -> ShardBoundary:
        result = self._emit_range(
            start_frame=self._open_start,
            frame_count=self._open_frames,
            episode_ids=tuple(self._open_episode_ids),
            split_groups=tuple(self._open_split_groups),
            exclusive=exclusive,
        )
        self._open_frames = 0
        self._open_episode_ids.clear()
        self._open_split_groups.clear()
        return result

    def _emit_range(
        self,
        *,
        start_frame: int,
        frame_count: int,
        episode_ids: tuple[str, ...],
        split_groups: tuple[str, ...],
        exclusive: bool,
    ) -> ShardBoundary:
        if frame_count <= 0:
            raise AssertionError("Internal error: attempted to emit an empty shard.")
        result = ShardBoundary(
            shard_id=shard_id(self._next_shard_ordinal),
            shard_ordinal=self._next_shard_ordinal,
            start_frame=start_frame,
            frame_count=frame_count,
            episode_ids=episode_ids,
            split_groups=split_groups,
            exclusive_oversized_episode=exclusive,
        )
        self._next_shard_ordinal += 1
        return result


def plan_shards(
    episodes: Iterable[tuple[int, str, Iterable[object] | int]],
    *,
    shard_max_frames: int,
    shard_episode_aligned: bool = True,
) -> tuple[ShardBoundary, ...]:
    """Compute a complete plan from ``(ordinal, group, frames-or-count)`` rows."""

    planner = ShardPlanner(
        shard_max_frames=shard_max_frames,
        shard_episode_aligned=shard_episode_aligned,
    )
    boundaries: list[ShardBoundary] = []
    for ordinal, split_group, frames in episodes:
        iterable: Iterable[object]
        if isinstance(frames, int) and not isinstance(frames, bool):
            if frames < 0:
                raise ValueError("Episode frame count must be non-negative.")
            iterable = range(frames)
        else:
            iterable = frames  # type: ignore[assignment]
        for frame in iterable:
            boundaries.extend(planner.feed_frame(ordinal, split_group, frame))
        boundaries.extend(planner.end_episode(ordinal))
    boundaries.extend(planner.finish())
    return tuple(boundaries)


def build_dataset_frame_record(
    *,
    dataset_frame_index: int,
    episode_id_value: str,
    audio_start_sample: int,
    audio_end_sample: int,
    frame: AudioSensorFrame | dict[str, Any],
    session_root: str | Path | None = None,
    location: str = "dataset frame record",
) -> DatasetFrameRecord:
    """Build a record around an unmodified canonical frame-v1 trace dict."""

    frame_dict = (
        frame_to_trace_dict(frame) if isinstance(frame, AudioSensorFrame) else frame
    )
    validate_trace_projection(frame_dict, session_root=session_root, location=location)
    record = DatasetFrameRecord(
        dataset_frame_index=dataset_frame_index,
        episode_id=episode_id_value,
        audio_start_sample=audio_start_sample,
        audio_end_sample=audio_end_sample,
        frame=frame_dict,
    )
    _validate_record_fields(record, location=location, sample_count=None)
    return record


def serialize_dataset_frame_record(record: DatasetFrameRecord) -> str:
    """Serialize one compact canonical, newline-terminated JSON record."""

    _validate_record_fields(record, location="dataset frame record", sample_count=None)
    return json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"


def parse_dataset_frame_record(
    line: str | bytes,
    *,
    location: str = "dataset frame record",
    sample_count: int | None = None,
    session_root: str | Path | None = None,
) -> DatasetFrameRecord:
    """Parse and locally validate one frame record with a located error."""

    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DatasetLayoutError(f"{location}: invalid UTF-8: {exc}") from exc
    else:
        text = line
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise DatasetLayoutError(
            f"{location}: record must be exactly one newline-terminated JSON line."
        )
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DatasetLayoutError(f"{location}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: record must be a JSON object.")
    expected = {
        "record_version",
        "dataset_frame_index",
        "episode_id",
        "audio_start_sample",
        "audio_end_sample",
        "frame",
    }
    if set(payload) != expected:
        raise DatasetLayoutError(
            f"{location}: record fields must be exactly {sorted(expected)}."
        )
    frame_payload = payload["frame"]
    if not isinstance(frame_payload, dict):
        raise DatasetLayoutError(f"{location}.frame: must be an object.")
    record = DatasetFrameRecord(
        record_version=payload["record_version"],
        dataset_frame_index=payload["dataset_frame_index"],
        episode_id=payload["episode_id"],
        audio_start_sample=payload["audio_start_sample"],
        audio_end_sample=payload["audio_end_sample"],
        frame=frame_payload,
    )
    _validate_record_fields(record, location=location, sample_count=sample_count)
    validate_trace_projection(
        record.frame,
        session_root=session_root,
        location=f"{location}.frame",
    )
    if serialize_dataset_frame_record(record) != text:
        raise DatasetLayoutError(f"{location}: record is not canonical JSON.")
    return record


def validate_record_sequence(
    records: Sequence[DatasetFrameRecord],
    *,
    sample_count: int,
    reset_frame_indices: Iterable[int] = (),
    max_overlap_samples: int | None = None,
    location: str = "frames.jsonl",
) -> None:
    """Validate local bounds, ordering, overlap, reset, and empty-range rules."""

    resets = _prepare_sequence_validation(
        sample_count=sample_count,
        reset_frame_indices=reset_frame_indices,
        max_overlap_samples=max_overlap_samples,
    )
    previous: DatasetFrameRecord | None = None
    for line_number, record in enumerate(records, start=1):
        _validate_record_pair(
            previous,
            record,
            line_number=line_number,
            sample_count=sample_count,
            reset_frame_indices=resets,
            max_overlap_samples=max_overlap_samples,
            location=location,
        )
        previous = record


def _prepare_sequence_validation(
    *,
    sample_count: int,
    reset_frame_indices: Iterable[int],
    max_overlap_samples: int | None,
) -> set[int]:
    _require_non_negative_int(sample_count, "sample_count")
    if max_overlap_samples is not None:
        _require_non_negative_int(max_overlap_samples, "max_overlap_samples")
    resets = set(reset_frame_indices)
    for reset in resets:
        _require_non_negative_int(reset, "reset frame index")
    return resets


def _validate_record_pair(
    previous: DatasetFrameRecord | None,
    record: DatasetFrameRecord,
    *,
    line_number: int,
    sample_count: int,
    reset_frame_indices: set[int],
    max_overlap_samples: int | None,
    location: str,
) -> None:
    record_location = f"{location} line {line_number}"
    _validate_record_fields(record, location=record_location, sample_count=sample_count)
    if previous is None:
        return
    if record.audio_start_sample < previous.audio_start_sample:
        raise DatasetLayoutError(
            f"{record_location}: audio_start_sample is non-monotonic."
        )
    if record.audio_end_sample < previous.audio_end_sample:
        raise DatasetLayoutError(
            f"{record_location}: audio_end_sample is non-monotonic."
        )
    overlap = previous.audio_end_sample - record.audio_start_sample
    if record.dataset_frame_index in reset_frame_indices and overlap > 0:
        raise DatasetLayoutError(
            f"{record_location}: audio range overlaps across a reset boundary."
        )
    if max_overlap_samples is not None and overlap > max_overlap_samples:
        raise DatasetLayoutError(
            f"{record_location}: audio overlap {overlap} exceeds configured "
            f"maximum {max_overlap_samples}."
        )


def _validate_record_fields(
    record: DatasetFrameRecord,
    *,
    location: str,
    sample_count: int | None,
) -> None:
    if record.record_version != DATASET_FRAME_RECORD_VERSION:
        raise DatasetLayoutError(
            f"{location}: record_version must be {DATASET_FRAME_RECORD_VERSION!r}."
        )
    _located_non_negative_int(
        record.dataset_frame_index, f"{location}.dataset_frame_index"
    )
    if not isinstance(record.episode_id, str) or not _EPISODE_ID_RE.fullmatch(
        record.episode_id
    ):
        raise DatasetLayoutError(f"{location}.episode_id: expected episode_<NNNNN>.")
    _located_non_negative_int(
        record.audio_start_sample, f"{location}.audio_start_sample"
    )
    _located_non_negative_int(record.audio_end_sample, f"{location}.audio_end_sample")
    if record.audio_end_sample < record.audio_start_sample:
        raise DatasetLayoutError(f"{location}: audio sample range is inverted.")
    if sample_count is not None and record.audio_end_sample > sample_count:
        raise DatasetLayoutError(
            f"{location}: audio_end_sample {record.audio_end_sample} exceeds "
            f"sample_count {sample_count}."
        )


def validate_trace_projection(
    frame: AudioSensorFrame | dict[str, Any],
    *,
    session_root: str | Path | None = None,
    location: str = "frame",
) -> tuple[LayoutWarning, ...]:
    """Accept or reject the §4.5 projection without rewriting the frame."""

    payload = (
        frame_to_trace_dict(frame) if isinstance(frame, AudioSensorFrame) else frame
    )
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: frame must be an object.")
    try:
        rebuilt = frame_from_trace_dict(payload)
        canonical = frame_to_trace_dict(rebuilt)
    except (KeyError, TypeError, ValueError) as exc:
        raise DatasetLayoutError(f"{location}: invalid frame v1: {exc}") from exc
    if canonical != payload:
        raise DatasetLayoutError(
            f"{location}: frame is not an unmodified canonical frame v1 trace dict."
        )
    root = None if session_root is None else Path(session_root)
    waveform_paths = payload.get("waveform_paths", [])
    if not isinstance(waveform_paths, list):
        raise DatasetLayoutError(f"{location}.waveform_paths: must be an array.")
    for index, value in enumerate(waveform_paths):
        _validate_session_path(
            value,
            session_root=root,
            location=f"{location}.waveform_paths[{index}]",
        )
    detections = payload.get("detections", [])
    for index, detection in enumerate(detections):
        value = detection.get("audio_asset_path")
        if value is not None and not (isinstance(value, str) and _URI_RE.match(value)):
            _validate_session_path(
                value,
                session_root=root,
                location=f"{location}.detections[{index}].audio_asset_path",
            )
    warnings: list[LayoutWarning] = []
    warnings.extend(
        _diagnostic_path_warnings(
            payload.get("diagnostics", {}), f"{location}.diagnostics"
        )
    )
    for index, detection in enumerate(detections):
        warnings.extend(
            _diagnostic_path_warnings(
                detection.get("diagnostics", {}),
                f"{location}.detections[{index}].diagnostics",
            )
        )
    return tuple(warnings)


def _validate_session_path(
    value: object,
    *,
    session_root: Path | None,
    location: str,
) -> None:
    if not isinstance(value, str) or not value:
        raise DatasetLayoutError(f"{location}: must be a non-empty path string.")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "\\" in value
    ):
        raise DatasetLayoutError(
            f"{location}: must be a session-relative POSIX path without traversal."
        )
    if session_root is not None:
        candidate = session_root.joinpath(*posix.parts)
        try:
            root_resolved = session_root.resolve(strict=True)
            candidate_resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise DatasetLayoutError(
                f"{location}: referenced file does not exist."
            ) from exc
        if not candidate_resolved.is_relative_to(root_resolved):
            raise DatasetLayoutError(f"{location}: path escapes the session root.")
        if not candidate_resolved.is_file():
            raise DatasetLayoutError(f"{location}: referenced path is not a file.")
        current = session_root
        for part in posix.parts:
            current = current / part
            if current.is_symlink():
                raise DatasetLayoutError(f"{location}: symbolic links are forbidden.")


def _diagnostic_path_warnings(value: object, location: str) -> list[LayoutWarning]:
    warnings: list[LayoutWarning] = []
    if isinstance(value, dict):
        for key in sorted(value):
            warnings.extend(_diagnostic_path_warnings(value[key], f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            warnings.extend(_diagnostic_path_warnings(item, f"{location}[{index}]"))
    elif isinstance(value, str) and (
        value.startswith("/") or _WINDOWS_ABSOLUTE_RE.match(value)
    ):
        warnings.append(
            LayoutWarning(
                location=location,
                message="diagnostic string looks like an absolute filesystem path",
            )
        )
    return warnings


def canonical_configuration_bytes(configuration: Mapping[str, Any]) -> bytes:
    """Return the exact UTF-8 canonical configuration byte contract."""

    normalized = _normalize_configuration(configuration, key=None, location="config")
    try:
        text = (
            json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"configuration is not canonical JSON data: {exc}") from exc
    return text.encode("utf-8")


def configuration_sha256(configuration: Mapping[str, Any] | bytes) -> str:
    """Hash canonical configuration bytes, or exact already-canonical bytes."""

    data = (
        canonical_configuration_bytes(configuration)
        if isinstance(configuration, Mapping)
        else configuration
    )
    if not isinstance(data, bytes):
        raise TypeError("configuration_sha256 expects a mapping or bytes.")
    return hashlib.sha256(data).hexdigest()


def _normalize_configuration(value: Any, *, key: str | None, location: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): _normalize_configuration(
                child_value,
                key=str(child_key),
                location=f"{location}.{child_key}",
            )
            for child_key, child_value in sorted(
                value.items(), key=lambda item: str(item[0])
            )
        }
    if isinstance(value, (tuple, list)):
        return [
            _normalize_configuration(item, key=key, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Path):
        value = value.as_posix()
    if isinstance(value, str) and key is not None and _is_path_key(key):
        if _URI_RE.match(value):
            return value
        _validate_portable_relative_path(value, location)
    return value


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered == "path" or lowered.endswith("_path") or lowered.endswith("_paths")


def episode_seed(dataset_id: str, session_seed: int, n: int) -> int:
    """Derive the §4.3 reproducible 63-bit episode seed."""

    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("dataset_id must be a non-empty string.")
    _require_non_negative_int(session_seed, "session_seed")
    _require_non_negative_int(n, "episode ordinal")
    digest = hashlib.sha256(f"{dataset_id}:{session_seed}:{n}".encode()).digest()[:8]
    return int.from_bytes(digest, "big") >> 1


def build_shard_completion(
    shard_dir: str | Path,
    *,
    shard_id_value: str,
    start_frame: int,
    episode_ids: Sequence[str],
    writer_tool_version: str,
    audio_filename: str = "audio.wav",
    audio_subtype: str | None = None,
    dropped_frame_count: int = 0,
    dropped_producer_frame_ids: Sequence[str] = (),
    reset_frame_indices: Iterable[int] = (),
    max_overlap_samples: int | None = None,
) -> dict[str, Any]:
    """Build and fully self-verify a completion marker payload."""

    directory = Path(shard_dir)
    frames_path = directory / "frames.jsonl"
    audio_path = directory / audio_filename
    header = _read_audio_header(audio_path)
    records, warnings = _read_record_file(
        frames_path,
        sample_count=header["sample_count"],
        session_root=directory.parent.parent,
        reset_frame_indices=reset_frame_indices,
        max_overlap_samples=max_overlap_samples,
    )
    if directory.name != shard_id_value:
        raise DatasetLayoutError(
            f"shard {directory.name} file shard.complete.json: requested shard_id "
            f"{shard_id_value!r} does not equal containing directory."
        )
    for offset, record in enumerate(records):
        expected_index = start_frame + offset
        if record.dataset_frame_index != expected_index:
            raise DatasetLayoutError(
                f"shard {shard_id_value} file frames.jsonl line {offset + 1}: "
                f"dataset_frame_index {record.dataset_frame_index} != "
                f"{expected_index}."
            )
    actual_episode_ids = _first_appearance(record.episode_id for record in records)
    if tuple(episode_ids) != actual_episode_ids:
        raise DatasetLayoutError(
            f"shard {shard_id_value} file frames.jsonl: episode_ids do not match "
            "record first-appearance order."
        )
    if not isinstance(writer_tool_version, str) or not writer_tool_version:
        raise ValueError("writer_tool_version must be a non-empty string.")
    _require_non_negative_int(dropped_frame_count, "dropped_frame_count")
    ids = tuple(dropped_producer_frame_ids)
    if len(ids) > 100 or len(ids) > dropped_frame_count:
        raise ValueError(
            "dropped producer ids must contain at most 100 ids and no more than count."
        )
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError("dropped producer frame ids must be non-empty strings.")
    max_end = max((record.audio_end_sample for record in records), default=0)
    subtype = header["subtype"] if audio_subtype is None else audio_subtype
    if subtype != header["subtype"]:
        raise DatasetLayoutError(
            f"shard {shard_id_value} file {audio_filename}: subtype {subtype!r} "
            f"disagrees with decoded header {header['subtype']!r}."
        )
    _validate_producer_ids(records, shard_id_value)
    marker = {
        "marker_version": SHARD_COMPLETION_VERSION,
        "shard_id": shard_id_value,
        "start_frame": start_frame,
        "frame_count": len(records),
        "episode_ids": list(episode_ids),
        "files": [
            _file_entry(frames_path),
            _file_entry(audio_path),
        ],
        "audio": {
            "path": audio_filename,
            "container": header["container"],
            "subtype": subtype,
            "channels": header["channels"],
            "sample_rate_hz": header["sample_rate_hz"],
            "dtype": header["dtype"],
            "sample_count": header["sample_count"],
        },
        "tail_samples": header["sample_count"] - max_end,
        "dropped_frames": {
            "count": dropped_frame_count,
            "producer_frame_ids": list(ids),
        },
        "writer_tool_version": writer_tool_version,
    }
    del warnings
    _validate_marker_payload(marker, directory=directory)
    return marker


def serialize_shard_completion(marker: Mapping[str, Any]) -> str:
    """Serialize one pretty canonical, newline-terminated marker."""

    payload = dict(marker)
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def verify_shard_completion(
    shard_dir: str | Path,
    *,
    manifest: AudioDatasetManifest | None = None,
    max_overlap_samples: int | None = None,
    retain_records: bool = True,
) -> VerifiedShard:
    """Verify every per-shard invariant and optional manifest agreement."""

    directory = Path(shard_dir)
    marker_path = directory / "shard.complete.json"
    shard_label = directory.name
    try:
        marker_text = marker_path.read_text(encoding="utf-8")
        payload = json.loads(marker_text)
    except FileNotFoundError as exc:
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: missing completion marker."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: marker must be an object."
        )
    _validate_marker_payload(payload, directory=directory)
    if marker_text != serialize_shard_completion(payload):
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: marker is not "
            "canonical JSON."
        )
    if payload["shard_id"] != shard_label:
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: marker shard_id "
            f"{payload['shard_id']!r} does not equal containing directory."
        )
    file_entries = {entry["path"]: entry for entry in payload["files"]}
    expected_disk_entries = {
        "frames.jsonl",
        payload["audio"]["path"],
        "shard.complete.json",
    }
    actual_disk_entries = {path.name for path in directory.iterdir()}
    if actual_disk_entries != expected_disk_entries:
        raise DatasetLayoutError(
            f"shard {shard_label}: on-disk entries must be exactly "
            f"{sorted(expected_disk_entries)}; got {sorted(actual_disk_entries)}."
        )
    for name, entry in file_entries.items():
        path = directory / name
        if path.is_symlink():
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: symlink forbidden."
            )
        if not path.is_file():
            raise DatasetLayoutError(f"shard {shard_label} file {name}: missing file.")
        actual_size = path.stat().st_size
        if actual_size != entry["bytes"]:
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: bytes mismatch "
                f"({actual_size} != {entry['bytes']})."
            )
        actual_sha = _sha256_file(path)
        if actual_sha != entry["sha256"]:
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: sha256 mismatch."
            )
    audio_meta = payload["audio"]
    header = _read_audio_header(
        directory / audio_meta["path"], streaming=not retain_records
    )
    for field in (
        "container",
        "subtype",
        "channels",
        "sample_rate_hz",
        "dtype",
        "sample_count",
    ):
        if audio_meta[field] != header[field]:
            raise DatasetLayoutError(
                f"shard {shard_label} file {audio_meta['path']}: decoded audio "
                f"header {field}={header[field]!r} disagrees with marker "
                f"{audio_meta[field]!r}."
            )
    if max_overlap_samples is None:
        max_overlap_samples = _configured_max_overlap(directory.parent.parent)
    reset_indices: tuple[int, ...] = ()
    if manifest is not None:
        reset_indices = tuple(
            reset.frame_index
            for episode in manifest.episodes
            if episode.episode_id in payload["episode_ids"]
            for reset in episode.reset_markers
        )
    scan = _scan_record_file(
        directory / "frames.jsonl",
        sample_count=audio_meta["sample_count"],
        session_root=directory.parent.parent,
        reset_frame_indices=reset_indices,
        max_overlap_samples=max_overlap_samples,
        expected_start_frame=payload["start_frame"],
        retain_records=retain_records,
    )
    if scan.line_count != payload["frame_count"]:
        raise DatasetLayoutError(
            f"shard {shard_label} file frames.jsonl: line count {scan.line_count} "
            f"does not equal frame_count {payload['frame_count']}."
        )
    if scan.index_error is not None:
        raise scan.index_error
    if scan.episode_ids != tuple(payload["episode_ids"]):
        raise DatasetLayoutError(
            f"shard {shard_label} file frames.jsonl: episode_ids do not exactly "
            "match record first-appearance order."
        )
    expected_tail = audio_meta["sample_count"] - scan.max_audio_end
    if payload["tail_samples"] != expected_tail:
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: tail_samples "
            f"{payload['tail_samples']} != {expected_tail}."
        )
    if retain_records:
        _validate_producer_ids(scan.records, shard_label)
    elif scan.producer_error is not None:
        raise scan.producer_error
    if manifest is not None:
        _verify_manifest_marker_agreement(manifest, payload, directory)
        if audio_meta["channels"] != len(manifest.channel_order):
            raise DatasetLayoutError(
                f"shard {shard_label} file {audio_meta['path']}: channel count "
                "disagrees with manifest channel_order."
            )
        for field in ("sample_rate_hz", "dtype"):
            if audio_meta[field] != getattr(manifest, field):
                raise DatasetLayoutError(
                    f"shard {shard_label} file {audio_meta['path']}: {field} "
                    "disagrees with manifest."
                )
    return VerifiedShard(
        shard_dir=directory,
        marker=payload,
        records=scan.records,
        warnings=scan.warnings,
    )


def _validate_marker_payload(payload: dict[str, Any], *, directory: Path) -> None:
    location = f"shard {directory.name} file shard.complete.json"
    if set(payload) != _MARKER_FIELDS:
        raise DatasetLayoutError(
            f"{location}: marker fields must be exactly {sorted(_MARKER_FIELDS)}."
        )
    if payload["marker_version"] != SHARD_COMPLETION_VERSION:
        raise DatasetLayoutError(
            f"{location}: marker_version must be {SHARD_COMPLETION_VERSION!r}."
        )
    if not isinstance(payload["shard_id"], str) or not _SHARD_ID_RE.fullmatch(
        payload["shard_id"]
    ):
        raise DatasetLayoutError(f"{location}: shard_id must be shard_<NNNNN>.")
    _located_non_negative_int(payload["start_frame"], f"{location}.start_frame")
    _located_positive_int(payload["frame_count"], f"{location}.frame_count")
    episode_ids_value = payload["episode_ids"]
    if not isinstance(episode_ids_value, list) or not episode_ids_value:
        raise DatasetLayoutError(f"{location}.episode_ids: must be a non-empty array.")
    if any(
        not isinstance(value, str) or not _EPISODE_ID_RE.fullmatch(value)
        for value in episode_ids_value
    ) or len(set(episode_ids_value)) != len(episode_ids_value):
        raise DatasetLayoutError(
            f"{location}.episode_ids: ids must be unique episode_<NNNNN> values."
        )
    files = payload["files"]
    if not isinstance(files, list):
        raise DatasetLayoutError(f"{location}.files: must be an array.")
    names: list[str] = []
    for index, entry in enumerate(files):
        entry_location = f"{location}.files[{index}]"
        if not isinstance(entry, dict) or set(entry) != _FILE_FIELDS:
            raise DatasetLayoutError(
                f"{entry_location}: fields must be exactly {sorted(_FILE_FIELDS)}."
            )
        name = entry["path"]
        if (
            not isinstance(name, str)
            or not name
            or name not in {"frames.jsonl", "audio.wav", "audio.flac"}
            or "/" in name
            or "\\" in name
            or name == ".."
        ):
            raise DatasetLayoutError(
                f"{entry_location}.path: must be one fixed single-component asset name."
            )
        names.append(name)
        if not isinstance(entry["sha256"], str) or not _SHA256_RE.fullmatch(
            entry["sha256"]
        ):
            raise DatasetLayoutError(
                f"{entry_location}.sha256: must be lowercase SHA-256."
            )
        _located_non_negative_int(entry["bytes"], f"{entry_location}.bytes")
    if len(names) != len(set(names)):
        raise DatasetLayoutError(f"{location}.files: duplicate path entry.")
    audio_names = [name for name in names if name in {"audio.wav", "audio.flac"}]
    if names.count("frames.jsonl") != 1 or len(audio_names) != 1 or len(names) != 2:
        raise DatasetLayoutError(
            f"{location}.files: require exactly frames.jsonl and one of "
            "audio.wav/audio.flac."
        )
    audio = payload["audio"]
    if not isinstance(audio, dict) or set(audio) != _AUDIO_FIELDS:
        raise DatasetLayoutError(
            f"{location}.audio: fields must be exactly {sorted(_AUDIO_FIELDS)}."
        )
    if audio["path"] != audio_names[0]:
        raise DatasetLayoutError(
            f"{location}.audio.path: must equal the audio file entry."
        )
    expected_container = "wav" if audio["path"] == "audio.wav" else "flac"
    if audio["container"] != expected_container:
        raise DatasetLayoutError(
            f"{location}.audio.container: does not match the filename suffix."
        )
    if not isinstance(audio["subtype"], str) or not audio["subtype"]:
        raise DatasetLayoutError(f"{location}.audio.subtype: must be non-empty.")
    _located_positive_int(audio["channels"], f"{location}.audio.channels")
    _located_positive_int(audio["sample_rate_hz"], f"{location}.audio.sample_rate_hz")
    if not isinstance(audio["dtype"], str) or audio["dtype"] not in {
        "float32",
        "float64",
        "int16",
        "int24",
        "int32",
    }:
        raise DatasetLayoutError(f"{location}.audio.dtype: unsupported dtype.")
    _located_non_negative_int(audio["sample_count"], f"{location}.audio.sample_count")
    _located_non_negative_int(payload["tail_samples"], f"{location}.tail_samples")
    if payload["tail_samples"] > audio["sample_count"]:
        raise DatasetLayoutError(f"{location}.tail_samples: exceeds sample_count.")
    dropped = payload["dropped_frames"]
    if not isinstance(dropped, dict) or set(dropped) != _DROPPED_FIELDS:
        raise DatasetLayoutError(
            f"{location}.dropped_frames: fields must be exactly "
            f"{sorted(_DROPPED_FIELDS)}."
        )
    _located_non_negative_int(dropped["count"], f"{location}.dropped_frames.count")
    dropped_ids = dropped["producer_frame_ids"]
    if (
        not isinstance(dropped_ids, list)
        or len(dropped_ids) > 100
        or len(dropped_ids) > dropped["count"]
        or any(not isinstance(value, str) or not value for value in dropped_ids)
    ):
        raise DatasetLayoutError(
            f"{location}.dropped_frames.producer_frame_ids: invalid truncated id list."
        )
    if (
        not isinstance(payload["writer_tool_version"], str)
        or not payload["writer_tool_version"]
    ):
        raise DatasetLayoutError(f"{location}.writer_tool_version: must be non-empty.")


def _read_record_file(
    path: Path,
    *,
    sample_count: int,
    session_root: Path,
    reset_frame_indices: Iterable[int],
    max_overlap_samples: int | None,
) -> tuple[tuple[DatasetFrameRecord, ...], tuple[LayoutWarning, ...]]:
    scan = _scan_record_file(
        path,
        sample_count=sample_count,
        session_root=session_root,
        reset_frame_indices=reset_frame_indices,
        max_overlap_samples=max_overlap_samples,
        expected_start_frame=None,
        retain_records=True,
    )
    return scan.records, scan.warnings


def _iter_record_file(
    path: Path,
    *,
    sample_count: int,
    session_root: Path,
) -> Iterable[tuple[int, DatasetFrameRecord, tuple[LayoutWarning, ...]]]:
    shard_label = path.parent.name
    try:
        stream = path.open("rb")
    except FileNotFoundError as exc:
        raise DatasetLayoutError(
            f"shard {shard_label} file frames.jsonl: missing file."
        ) from exc
    with stream:
        stream.seek(0, 2)
        size = stream.tell()
        if size == 0:
            terminated = False
        else:
            stream.seek(-1, 2)
            terminated = stream.read(1) == b"\n"
        if not terminated:
            raise DatasetLayoutError(
                f"shard {shard_label} file frames.jsonl: final line is not "
                "newline-terminated."
            )
        stream.seek(0)
        for line_number, line in enumerate(stream, start=1):
            location = f"shard {shard_label} file frames.jsonl line {line_number}"
            if line in {b"\n", b"\r\n"}:
                raise DatasetLayoutError(f"{location}: blank lines are forbidden.")
            record = parse_dataset_frame_record(
                line,
                location=location,
                sample_count=sample_count,
                session_root=session_root,
            )
            warnings = validate_trace_projection(
                record.frame,
                session_root=session_root,
                location=f"{location}.frame",
            )
            yield line_number, record, warnings


def _scan_record_file(
    path: Path,
    *,
    sample_count: int,
    session_root: Path,
    reset_frame_indices: Iterable[int],
    max_overlap_samples: int | None,
    expected_start_frame: int | None,
    retain_records: bool,
) -> _RecordFileScan:
    shard_label = path.parent.name
    records: list[DatasetFrameRecord] = []
    warnings: list[LayoutWarning] = []
    episode_ids: list[str] = []
    episode_seen: set[str] = set()
    max_audio_end = 0
    line_count = 0
    index_error: DatasetLayoutError | None = None
    producer_error: DatasetLayoutError | None = None
    sequence_error: Exception | None = None
    try:
        resets = _prepare_sequence_validation(
            sample_count=sample_count,
            reset_frame_indices=reset_frame_indices,
            max_overlap_samples=max_overlap_samples,
        )
    except (TypeError, ValueError) as exc:
        resets = set()
        sequence_error = exc
    producer_db: sqlite3.Connection | None = None
    if not retain_records:
        producer_db = sqlite3.connect("")
        producer_db.execute("PRAGMA cache_size = -1024")
        producer_db.execute("PRAGMA temp_store = FILE")
        producer_db.execute(
            "CREATE TABLE producer_ids ("
            "episode_id TEXT NOT NULL, producer_frame_id TEXT NOT NULL, "
            "PRIMARY KEY (episode_id, producer_frame_id)) WITHOUT ROWID"
        )
    previous: DatasetFrameRecord | None = None
    try:
        for line_number, record, record_warnings in _iter_record_file(
            path, sample_count=sample_count, session_root=session_root
        ):
            line_count = line_number
            if retain_records:
                records.append(record)
            warnings.extend(record_warnings)
            if sequence_error is None:
                try:
                    _validate_record_pair(
                        previous,
                        record,
                        line_number=line_number,
                        sample_count=sample_count,
                        reset_frame_indices=resets,
                        max_overlap_samples=max_overlap_samples,
                        location=f"shard {shard_label} file frames.jsonl",
                    )
                except DatasetLayoutError as exc:
                    sequence_error = exc
            previous = record
            if expected_start_frame is not None and index_error is None:
                expected_index = expected_start_frame + line_number - 1
                if record.dataset_frame_index != expected_index:
                    index_error = DatasetLayoutError(
                        f"shard {shard_label} file frames.jsonl line {line_number}: "
                        f"dataset_frame_index {record.dataset_frame_index} != "
                        f"{expected_index}."
                    )
            if record.episode_id not in episode_seen:
                episode_seen.add(record.episode_id)
                episode_ids.append(record.episode_id)
            max_audio_end = max(max_audio_end, record.audio_end_sample)
            if producer_db is not None:
                producer_id = record.frame["frame_id"]
                try:
                    producer_db.execute(
                        "INSERT INTO producer_ids VALUES (?, ?)",
                        (record.episode_id, producer_id),
                    )
                except sqlite3.IntegrityError:
                    if producer_error is None:
                        producer_error = DatasetLayoutError(
                            f"shard {shard_label} file frames.jsonl line "
                            f"{line_number}: duplicate producer frame_id "
                            f"{producer_id!r} within {record.episode_id}."
                        )
    finally:
        if producer_db is not None:
            producer_db.close()
    if sequence_error is not None:
        raise sequence_error
    return _RecordFileScan(
        records=tuple(records),
        warnings=tuple(warnings),
        line_count=line_count,
        episode_ids=tuple(episode_ids),
        max_audio_end=max_audio_end,
        index_error=index_error,
        producer_error=producer_error,
    )


def verify_shard_tiling(shards: Sequence[VerifiedShard | Mapping[str, Any]]) -> None:
    """Require shard_00000 start zero and every consecutive half-open tile."""

    expected_start = 0
    for ordinal, item in enumerate(shards):
        marker = item.marker if isinstance(item, VerifiedShard) else item
        expected_id = shard_id(ordinal)
        if marker["shard_id"] != expected_id:
            raise DatasetLayoutError(
                f"shard {marker['shard_id']}: expected ordinal id {expected_id}."
            )
        if marker["start_frame"] != expected_start:
            raise DatasetLayoutError(
                f"shard {marker['shard_id']}: start_frame {marker['start_frame']} "
                f"breaks tiling at expected frame {expected_start}."
            )
        expected_start += marker["frame_count"]


def classify_session_lifecycle(session_root: str | Path) -> str:
    """Classify the three structural signatures from §7."""

    root = Path(session_root)
    manifest_path = root / "manifest.json"
    staging_path = root / "_staging"
    if manifest_path.exists() and staging_path.exists():
        raise DatasetLayoutError(
            f"session {root}: _staging is present alongside manifest.json."
        )
    if not manifest_path.exists():
        return "in-progress-or-aborted"
    try:
        manifest = read_dataset_manifest(manifest_path)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ) as exc:
        raise DatasetLayoutError(f"session {root} file manifest.json: {exc}") from exc
    return (
        "complete"
        if manifest.completion_state == "complete"
        else "finalized-incomplete"
    )


def validate_session_layout(
    session_root: str | Path,
    *,
    allow_incomplete: bool = True,
    retain_records: bool = True,
) -> SessionLayoutResult:
    """Validate lifecycle, portability, correspondence, and complete publication."""

    root = Path(session_root)
    if root.is_symlink():
        raise DatasetLayoutError(f"session {root}: session root may not be a symlink.")
    if not root.is_dir():
        raise DatasetLayoutError(f"session {root}: session root is not a directory.")
    _reject_symlinks(root)
    unknown = sorted(
        path.name for path in root.iterdir() if path.name not in _ROOT_ENTRIES
    )
    if unknown:
        raise DatasetLayoutError(f"session {root}: unknown root entries {unknown}.")
    lifecycle = classify_session_lifecycle(root)
    if lifecycle == "in-progress-or-aborted":
        raise DatasetLayoutError(f"session {root}: in-progress or aborted session.")
    manifest = read_dataset_manifest(root / "manifest.json")
    if manifest.runtime_profile != "waveform_fidelity":
        raise DatasetLayoutError(
            f"session {root} file manifest.json: unsupported runtime profile for "
            "dataset layout v1."
        )
    for ordinal, episode in enumerate(manifest.episodes):
        expected = episode_id(ordinal)
        if episode.episode_id != expected:
            raise DatasetLayoutError(
                f"session {root} episode {episode.episode_id}: expected {expected}."
            )
    for ordinal, shard in enumerate(manifest.shards):
        expected = shard_id(ordinal)
        if shard.shard_id != expected:
            raise DatasetLayoutError(
                f"session {root} shard {shard.shard_id}: expected {expected}."
            )
    if lifecycle == "finalized-incomplete" and not allow_incomplete:
        raise DatasetLayoutError(
            f"session {root}: finalized-incomplete session refused."
        )
    if lifecycle == "finalized-incomplete":
        config_path = root / "config" / "session_config.json"
        if config_path.exists():
            _read_and_validate_configuration(root, manifest, required=False)
        return SessionLayoutResult(
            session_root=root,
            lifecycle_state=lifecycle,
            manifest=manifest,
            shards=(),
            warnings=(),
        )
    config = _read_and_validate_configuration(root, manifest, required=True)
    shards_root = root / "shards"
    listed = {shard.shard_id for shard in manifest.shards}
    shard_entries = tuple(shards_root.iterdir()) if shards_root.is_dir() else ()
    non_directories = sorted(path.name for path in shard_entries if not path.is_dir())
    if non_directories:
        raise DatasetLayoutError(
            f"session {root}: non-directory entries under shards {non_directories}."
        )
    actual_dirs = {path.name for path in shard_entries}
    unlisted = sorted(actual_dirs - listed)
    if unlisted:
        raise DatasetLayoutError(
            f"session {root}: unlisted shard directories {unlisted}."
        )
    missing_dirs = sorted(listed - actual_dirs)
    if missing_dirs:
        raise DatasetLayoutError(
            f"session {root}: missing shard directories {missing_dirs}."
        )
    max_overlap = _configured_max_overlap(root)
    verified = tuple(
        verify_shard_completion(
            shards_root / shard.shard_id,
            manifest=manifest,
            max_overlap_samples=max_overlap,
            retain_records=retain_records,
        )
        for shard in manifest.shards
    )
    verify_shard_tiling(verified)
    _validate_split_groups(manifest, verified, root)
    _validate_boundary_policy(config, manifest, verified, root)
    _validate_episode_correspondence(
        manifest, verified, root, retain_records=retain_records
    )
    for current, following in zip(verified, verified[1:], strict=False):
        if (
            current.marker["episode_ids"][-1] == following.marker["episode_ids"][0]
            and current.marker["tail_samples"] != 0
        ):
            raise DatasetLayoutError(
                f"session {root} shard {current.marker['shard_id']}: "
                "mid-episode-rotated shard must have tail_samples == 0."
            )
    if manifest.calibration_profile is not None:
        reference = manifest.calibration_profile
        calibration_path = root.joinpath(*PurePosixPath(reference.path).parts)
        if not calibration_path.is_file():
            raise DatasetLayoutError(
                f"session {root} file {reference.path}: missing calibration profile."
            )
        if _sha256_file(calibration_path) != reference.sha256:
            raise DatasetLayoutError(
                f"session {root} file {reference.path}: calibration sha256 mismatch."
            )
        try:
            read_calibration_profile(calibration_path)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise DatasetLayoutError(
                f"session {root} file {reference.path}: invalid calibration "
                f"profile: {exc}"
            ) from exc
    warnings = tuple(warning for shard in verified for warning in shard.warnings)
    return SessionLayoutResult(
        session_root=root,
        lifecycle_state=lifecycle,
        manifest=manifest,
        shards=verified,
        warnings=warnings,
    )


def _read_and_validate_configuration(
    root: Path,
    manifest: AudioDatasetManifest,
    *,
    required: bool,
) -> dict[str, Any]:
    config_path = root / "config" / "session_config.json"
    try:
        config_bytes = config_path.read_bytes()
        config = json.loads(config_bytes)
    except FileNotFoundError as exc:
        if not required:
            return {}
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: missing file."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: invalid JSON: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: must be an object."
        )
    try:
        canonical = canonical_configuration_bytes(config)
    except ValueError as exc:
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: {exc}"
        ) from exc
    if canonical != config_bytes:
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: bytes are not canonical."
        )
    actual_config_sha = configuration_sha256(config_bytes)
    if actual_config_sha != manifest.configuration_sha256:
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: "
            "configuration_sha256 mismatch."
        )
    if config.get("runtime_profile") != "waveform_fidelity":
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: unsupported runtime "
            "profile for dataset layout v1."
        )
    return config


def _validate_boundary_policy(
    config: Mapping[str, Any],
    manifest: AudioDatasetManifest,
    shards: Sequence[VerifiedShard],
    root: Path,
) -> None:
    maximum = config.get("shard_max_frames")
    aligned = config.get("shard_episode_aligned", True)
    try:
        expected = plan_shards(
            (
                (
                    ordinal,
                    episode.split_group,
                    episode.end_frame - episode.start_frame + 1,
                )
                for ordinal, episode in enumerate(manifest.episodes)
            ),
            shard_max_frames=maximum,
            shard_episode_aligned=aligned,
        )
    except (TypeError, ValueError) as exc:
        raise DatasetLayoutError(
            f"session {root} file config/session_config.json: invalid shard policy: "
            f"{exc}"
        ) from exc
    actual = tuple(
        (
            shard.marker["start_frame"],
            shard.marker["frame_count"],
            tuple(shard.marker["episode_ids"]),
        )
        for shard in shards
    )
    planned = tuple(
        (boundary.start_frame, boundary.frame_count, boundary.episode_ids)
        for boundary in expected
    )
    if actual != planned:
        raise DatasetLayoutError(
            f"session {root}: shard boundaries disagree with configured §3 policy; "
            f"expected {planned}, got {actual}."
        )


def _validate_episode_correspondence(
    manifest: AudioDatasetManifest,
    shards: Sequence[VerifiedShard],
    root: Path,
    *,
    retain_records: bool,
) -> None:
    records = iter(_iter_verified_records(shards, root))
    total_records = sum(shard.marker["frame_count"] for shard in shards)
    expected_start = 0
    for ordinal, episode in enumerate(manifest.episodes):
        if episode.start_frame != expected_start:
            raise DatasetLayoutError(
                f"session {root} episode {episode.episode_id}: start_frame "
                f"{episode.start_frame} breaks episode tiling at {expected_start}."
            )
        frame_count = episode.end_frame - episode.start_frame + 1
        if len(episode.timestamps_ms) != frame_count:
            raise DatasetLayoutError(
                f"session {root} episode {episode.episode_id}: timestamps_ms length "
                f"does not equal frame count at frame {episode.start_frame}."
            )
        if episode.end_frame >= total_records:
            raise DatasetLayoutError(
                f"session {root} episode {episode.episode_id}: missing record at frame "
                f"{total_records}."
            )
        producer_ids: set[str] | None = set() if retain_records else None
        producer_db: sqlite3.Connection | None = None
        if not retain_records:
            producer_db = sqlite3.connect("")
            producer_db.execute("PRAGMA cache_size = -1024")
            producer_db.execute("PRAGMA temp_store = FILE")
            producer_db.execute(
                "CREATE TABLE producer_ids (producer_frame_id TEXT PRIMARY KEY) "
                "WITHOUT ROWID"
            )
        previous_timestamp: int | None = None
        try:
            for offset, dataset_index in enumerate(
                range(episode.start_frame, episode.end_frame + 1)
            ):
                record = next(records)
                if record.dataset_frame_index != dataset_index:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: misordered "
                        f"record at frame {dataset_index}."
                    )
                if record.episode_id != episode.episode_id:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: interleaved "
                        f"record {record.episode_id} at frame {dataset_index}."
                    )
                timestamp = record.frame["timestamp_ms"]
                if timestamp != episode.timestamps_ms[offset]:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: timestamp "
                        f"mismatch at frame {dataset_index}."
                    )
                if timestamp < 0 or (
                    previous_timestamp is not None and timestamp < previous_timestamp
                ):
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: non-monotonic "
                        f"timestamp at frame {dataset_index}."
                    )
                previous_timestamp = timestamp
                producer_id = record.frame["frame_id"]
                duplicate = False
                if producer_ids is not None:
                    duplicate = producer_id in producer_ids
                    producer_ids.add(producer_id)
                else:
                    assert producer_db is not None
                    try:
                        producer_db.execute(
                            "INSERT INTO producer_ids VALUES (?)", (producer_id,)
                        )
                    except sqlite3.IntegrityError:
                        duplicate = True
                if duplicate:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: duplicate "
                        f"producer frame_id {producer_id!r} at frame {dataset_index}."
                    )
                frame_rate = record.frame.get("sample_rate_hz")
                if frame_rate is not None and frame_rate != manifest.sample_rate_hz:
                    raise DatasetLayoutError(
                        f"session {root} episode {episode.episode_id}: sample rate "
                        f"changed at frame {dataset_index}."
                    )
        finally:
            if producer_db is not None:
                producer_db.close()
        expected_start = episode.end_frame + 1
        del ordinal
    if total_records != expected_start:
        offending = expected_start
        raise DatasetLayoutError(
            f"session {root}: extra dataset record at frame {offending}."
        )
    if manifest.episodes and expected_start == 0:
        raise AssertionError("Internal episode tiling error.")


def _iter_verified_records(
    shards: Sequence[VerifiedShard], root: Path
) -> Iterable[DatasetFrameRecord]:
    for shard in shards:
        if shard.records:
            yield from shard.records
            continue
        for _, record, _ in _iter_record_file(
            shard.shard_dir / "frames.jsonl",
            sample_count=shard.marker["audio"]["sample_count"],
            session_root=root,
        ):
            yield record


def _validate_split_groups(
    manifest: AudioDatasetManifest,
    shards: Sequence[VerifiedShard],
    root: Path,
) -> None:
    group_by_episode = {
        episode.episode_id: episode.split_group for episode in manifest.episodes
    }
    for shard in shards:
        groups = {
            group_by_episode[episode_value]
            for episode_value in shard.marker["episode_ids"]
        }
        if len(groups) > 1:
            raise DatasetLayoutError(
                f"session {root} shard {shard.marker['shard_id']}: spans multiple "
                f"split_group values {sorted(groups)}."
            )


def _verify_manifest_marker_agreement(
    manifest: AudioDatasetManifest,
    marker: Mapping[str, Any],
    directory: Path,
) -> None:
    shard_value = marker["shard_id"]
    matches = [shard for shard in manifest.shards if shard.shard_id == shard_value]
    if len(matches) != 1:
        raise DatasetLayoutError(
            f"shard {shard_value} file shard.complete.json: no unique manifest shard."
        )
    shard = matches[0]
    marker_files = {entry["path"]: entry for entry in marker["files"]}
    assets_by_name: dict[str, Any] = {}
    for asset in shard.assets:
        expected_prefix = f"shards/{shard_value}/"
        if not asset.path.startswith(expected_prefix):
            raise DatasetLayoutError(
                f"shard {shard_value} file {asset.path}: manifest asset path is not "
                "inside its shard."
            )
        name = asset.path[len(expected_prefix) :]
        if "/" in name or name in assets_by_name:
            raise DatasetLayoutError(
                f"shard {shard_value} file {asset.path}: invalid or duplicate asset."
            )
        assets_by_name[name] = asset
    if set(assets_by_name) != set(marker_files):
        missing = sorted(set(marker_files) - set(assets_by_name))
        extra = sorted(set(assets_by_name) - set(marker_files))
        raise DatasetLayoutError(
            f"shard {shard_value}: manifest/marker file mismatch; missing={missing}, "
            f"extra={extra}."
        )
    for name, entry in marker_files.items():
        asset = assets_by_name[name]
        expected_kind = {
            "frames.jsonl": "frame_trace_jsonl",
            "audio.wav": "audio_wav",
            "audio.flac": "audio_flac",
        }[name]
        expected_asset_id = (
            f"{shard_value}.{'frames' if name == 'frames.jsonl' else 'audio'}"
        )
        if asset.asset_id != expected_asset_id:
            raise DatasetLayoutError(
                f"shard {shard_value} file {name}: asset_id must be "
                f"{expected_asset_id!r}."
            )
        if asset.kind != expected_kind:
            raise DatasetLayoutError(
                f"shard {shard_value} file {name}: manifest kind {asset.kind!r} "
                f"must be {expected_kind!r}."
            )
        if asset.sha256 != entry["sha256"]:
            raise DatasetLayoutError(
                f"shard {shard_value} file {name}: manifest/marker sha256 mismatch."
            )
    if tuple(shard.episode_ids) != tuple(marker["episode_ids"]):
        raise DatasetLayoutError(
            f"shard {shard_value}: manifest/marker episode_ids mismatch."
        )


def _validate_producer_ids(
    records: Sequence[DatasetFrameRecord], shard_label: str
) -> None:
    seen: dict[str, set[str]] = {}
    for line_number, record in enumerate(records, start=1):
        producer_id = record.frame["frame_id"]
        episode_seen = seen.setdefault(record.episode_id, set())
        if producer_id in episode_seen:
            raise DatasetLayoutError(
                f"shard {shard_label} file frames.jsonl line {line_number}: duplicate "
                f"producer frame_id {producer_id!r} within {record.episode_id}."
            )
        episode_seen.add(producer_id)


def _read_audio_header(path: Path, *, streaming: bool = False) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        if streaming:
            return _stream_wav_header(path)
        try:
            wave = read_wav(path)
        except (OSError, ValueError) as exc:
            raise DatasetLayoutError(
                f"file {path}: cannot decode WAV header: {exc}"
            ) from exc
        audio_format, bits = _wav_format(path)
        encodings = {
            (3, 32): ("FLOAT", "float32"),
            (1, 16): ("PCM_16", "int16"),
            (1, 24): ("PCM_24", "int24"),
            (1, 32): ("PCM_32", "int32"),
        }
        if (audio_format, bits) not in encodings:
            raise DatasetLayoutError(
                f"file {path}: unsupported WAV encoding format={audio_format}, "
                f"bits={bits}."
            )
        subtype, dtype = encodings[(audio_format, bits)]
        return {
            "container": "wav",
            "subtype": subtype,
            "channels": wave.channel_count,
            "sample_rate_hz": wave.sample_rate_hz,
            "dtype": dtype,
            "sample_count": wave.frame_count,
        }
    if suffix == ".flac":
        return _flac_header(path)
    raise DatasetLayoutError(
        f"file {path}: audio filename must be audio.wav or audio.flac."
    )


def _stream_wav_header(path: Path) -> dict[str, Any]:
    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
                raise DatasetLayoutError(f"file {path}: not a RIFF/WAVE file.")
            fmt: tuple[int, int, int, int] | None = None
            data_size: int | None = None
            while True:
                chunk_header = stream.read(8)
                if not chunk_header:
                    break
                if len(chunk_header) != 8:
                    break
                chunk_id = chunk_header[:4]
                size = struct.unpack_from("<I", chunk_header, 4)[0]
                if stream.tell() + size > file_size:
                    raise DatasetLayoutError(
                        f"file {path}: WAV chunk exceeds the file size."
                    )
                if chunk_id == b"fmt ":
                    body = stream.read(min(size, 40))
                    if len(body) < 16:
                        break
                    audio_format, channels, sample_rate, _, _block_align, bits = (
                        struct.unpack_from("<HHIIHH", body)
                    )
                    if audio_format == 0xFFFE and len(body) >= 26:
                        audio_format = struct.unpack_from("<H", body, 24)[0]
                    fmt = (
                        int(audio_format),
                        int(channels),
                        int(sample_rate),
                        int(bits),
                    )
                    stream.seek(size - len(body), 1)
                else:
                    if chunk_id == b"data":
                        data_size = size
                    stream.seek(size, 1)
                if size % 2:
                    stream.seek(1, 1)
                if fmt is not None and data_size is not None:
                    break
    except OSError as exc:
        raise DatasetLayoutError(
            f"file {path}: cannot decode WAV header: {exc}"
        ) from exc
    if fmt is None:
        raise DatasetLayoutError(f"file {path}: WAV fmt chunk is missing or invalid.")
    if data_size is None:
        raise DatasetLayoutError(f"file {path}: WAV data chunk is missing or invalid.")
    audio_format, channels, sample_rate, bits = fmt
    encodings = {
        (3, 32): ("FLOAT", "float32"),
        (1, 16): ("PCM_16", "int16"),
        (1, 24): ("PCM_24", "int24"),
        (1, 32): ("PCM_32", "int32"),
    }
    if (audio_format, bits) not in encodings:
        raise DatasetLayoutError(
            f"file {path}: unsupported WAV encoding format={audio_format}, bits={bits}."
        )
    bytes_per_frame = channels * bits // 8
    if channels <= 0 or sample_rate <= 0 or bytes_per_frame <= 0:
        raise DatasetLayoutError(f"file {path}: WAV fmt chunk is missing or invalid.")
    subtype, dtype = encodings[(audio_format, bits)]
    return {
        "container": "wav",
        "subtype": subtype,
        "channels": channels,
        "sample_rate_hz": sample_rate,
        "dtype": dtype,
        "sample_count": data_size // bytes_per_frame,
    }


def _wav_format(path: Path) -> tuple[int, int]:
    blob = path.read_bytes()
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise DatasetLayoutError(f"file {path}: not a RIFF/WAVE file.")
    offset = 12
    while offset + 8 <= len(blob):
        chunk_id = blob[offset : offset + 4]
        size = struct.unpack_from("<I", blob, offset + 4)[0]
        body = blob[offset + 8 : offset + 8 + size]
        if chunk_id == b"fmt ":
            if len(body) < 16:
                break
            audio_format, _, _, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if audio_format == 0xFFFE and len(body) >= 26:
                audio_format = struct.unpack_from("<H", body, 24)[0]
            return int(audio_format), int(bits)
        offset += 8 + size + size % 2
    raise DatasetLayoutError(f"file {path}: WAV fmt chunk is missing or invalid.")


def _flac_header(path: Path) -> dict[str, Any]:
    blob = path.read_bytes()
    if len(blob) < 42 or blob[:4] != b"fLaC":
        raise DatasetLayoutError(f"file {path}: invalid FLAC stream.")
    block_type = blob[4] & 0x7F
    block_length = int.from_bytes(blob[5:8], "big")
    if block_type != 0 or block_length != 34 or len(blob) < 8 + block_length:
        raise DatasetLayoutError(f"file {path}: FLAC STREAMINFO block is missing.")
    packed = int.from_bytes(blob[18:26], "big")
    sample_rate = (packed >> 44) & 0xFFFFF
    channels = ((packed >> 41) & 0x7) + 1
    bits = ((packed >> 36) & 0x1F) + 1
    sample_count = packed & ((1 << 36) - 1)
    if bits not in {16, 24}:
        raise DatasetLayoutError(f"file {path}: layout v1 FLAC must be 16- or 24-bit.")
    return {
        "container": "flac",
        "subtype": f"PCM_{bits}",
        "channels": channels,
        "sample_rate_hz": sample_rate,
        "dtype": f"int{bits}",
        "sample_count": sample_count,
    }


def _configured_max_overlap(session_root: Path) -> int | None:
    path = session_root / "config" / "session_config.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _find_overlap(payload)


def _find_overlap(value: object) -> int | None:
    if isinstance(value, dict):
        for window_key, hop_key in (
            ("window_sample_count", "hop_sample_count"),
            ("audio_window_samples", "audio_hop_samples"),
        ):
            if window_key in value and hop_key in value:
                window = value[window_key]
                hop = value[hop_key]
                if (
                    isinstance(window, int)
                    and not isinstance(window, bool)
                    and isinstance(hop, int)
                    and not isinstance(hop, bool)
                    and window >= hop >= 0
                ):
                    return window - hop
        for key in sorted(value):
            result = _find_overlap(value[key])
            if result is not None:
                return result
    return None


def _file_entry(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_appearance(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return tuple(result)


def _reject_symlinks(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            relative = path.relative_to(root).as_posix()
            raise DatasetLayoutError(
                f"session {root} entry {relative}: symlink forbidden."
            )


def _validate_portable_relative_path(value: str, location: str) -> None:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "\\" in value
    ):
        raise ValueError(
            f"{location} must be a relative POSIX path without parent traversal."
        )


def _require_non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def _located_non_negative_int(value: object, location: str) -> None:
    try:
        _require_non_negative_int(value, location)
    except ValueError as exc:
        raise DatasetLayoutError(str(exc)) from exc


def _located_positive_int(value: object, location: str) -> None:
    try:
        _require_positive_int(value, location)
    except ValueError as exc:
        raise DatasetLayoutError(str(exc)) from exc


__all__ = [
    "DATASET_FRAME_RECORD_VERSION",
    "SHARD_COMPLETION_VERSION",
    "DatasetFrameRecord",
    "DatasetLayoutError",
    "LayoutWarning",
    "SessionLayoutResult",
    "ShardBoundary",
    "ShardPlanner",
    "VerifiedShard",
    "build_dataset_frame_record",
    "build_shard_completion",
    "canonical_configuration_bytes",
    "classify_session_lifecycle",
    "configuration_sha256",
    "episode_id",
    "episode_seed",
    "parse_dataset_frame_record",
    "plan_shards",
    "serialize_dataset_frame_record",
    "serialize_shard_completion",
    "shard_id",
    "validate_record_sequence",
    "validate_session_layout",
    "validate_trace_projection",
    "verify_shard_completion",
    "verify_shard_tiling",
]
