"""Internal shard completion and streaming scan primitives."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from isaac_audio_sensors.recording._planning import shard_id
from isaac_audio_sensors.recording._records import (
    _EPISODE_ID_RE,
    DatasetFrameRecord,
    DatasetLayoutError,
    LayoutWarning,
    _located_non_negative_int,
    _located_positive_int,
    _prepare_sequence_validation,
    _require_non_negative_int,
    _validate_record_pair,
    parse_dataset_frame_record,
    validate_trace_projection,
)
from isaac_audio_sensors.recording.manifest import AudioDatasetManifest
from isaac_audio_sensors.recording.serialization import read_dataset_manifest

SHARD_COMPLETION_VERSION = "ias.shard_completion.v1"
MAX_STREAMING_WARNINGS_PER_SHARD = 100

_SHARD_ID_RE = re.compile(r"^shard_[0-9]{5}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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


@dataclass(frozen=True, slots=True)
class VerifiedShard:
    """A verified marker with bounded portability warnings."""

    marker: dict[str, Any]
    warnings: tuple[LayoutWarning, ...]
    warning_count: int


@dataclass(frozen=True, slots=True)
class _RecordFileScan:
    warnings: tuple[LayoutWarning, ...]
    warning_count: int
    line_count: int
    episode_ids: tuple[str, ...]
    max_audio_end: int
    index_error: DatasetLayoutError | None
    producer_error: DatasetLayoutError | None


def build_flac_shard_completion(
    shard_dir: str | Path,
    *,
    shard_id_value: str,
    start_frame: int,
    episode_ids: Sequence[str],
    writer_tool_version: str,
    dropped_frame_count: int = 0,
    dropped_producer_frame_ids: Sequence[str] = (),
    reset_frame_indices: Iterable[int] = (),
    max_overlap_samples: int | None = None,
) -> dict[str, Any]:
    """Build and fully self-verify a completion marker payload."""

    directory = Path(shard_dir)
    frames_path = directory / "frames.jsonl"
    audio_filename = "audio.flac"
    audio_path = directory / audio_filename
    header = _read_audio_header(audio_path)
    scan = _scan_record_file(
        frames_path,
        sample_count=header["sample_count"],
        session_root=directory.parent.parent,
        reset_frame_indices=reset_frame_indices,
        max_overlap_samples=max_overlap_samples,
        expected_start_frame=start_frame,
    )
    if directory.name != shard_id_value:
        raise DatasetLayoutError(
            f"shard {directory.name} file shard.complete.json: requested shard_id "
            f"{shard_id_value!r} does not equal containing directory."
        )
    if scan.index_error is not None:
        raise scan.index_error
    if scan.producer_error is not None:
        raise scan.producer_error
    if tuple(episode_ids) != scan.episode_ids:
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
    marker = {
        "marker_version": SHARD_COMPLETION_VERSION,
        "shard_id": shard_id_value,
        "start_frame": start_frame,
        "frame_count": scan.line_count,
        "episode_ids": list(episode_ids),
        "files": [
            _file_entry(frames_path),
            _file_entry(audio_path),
        ],
        "audio": {
            "path": audio_filename,
            "container": header["container"],
            "subtype": header["subtype"],
            "channels": header["channels"],
            "sample_rate_hz": header["sample_rate_hz"],
            "dtype": header["dtype"],
            "sample_count": header["sample_count"],
        },
        "tail_samples": header["sample_count"] - scan.max_audio_end,
        "dropped_frames": {
            "count": dropped_frame_count,
            "producer_frame_ids": list(ids),
        },
        "writer_tool_version": writer_tool_version,
    }
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
    verify_checksums: bool = True,
) -> VerifiedShard:
    """Stream and verify one complete shard with optional SHA-256 work."""

    if type(verify_checksums) is not bool:
        raise TypeError("verify_checksums must be a bool")

    directory = Path(shard_dir)
    marker_path = directory / "shard.complete.json"
    shard_label = directory.name
    try:
        marker_text = marker_path.read_text(encoding="utf-8")
        payload = json.loads(marker_text)
    except FileNotFoundError as exc:
        raise DatasetLayoutError(
            f"shard {shard_label} file shard.complete.json: missing completion marker.",
            code="missing_asset",
            location=f"shard {shard_label} file shard.complete.json",
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
            f"{sorted(expected_disk_entries)}; got {sorted(actual_disk_entries)}.",
            code="missing_asset",
            location=f"shard {shard_label}",
        )
    for name, entry in file_entries.items():
        path = directory / name
        if path.is_symlink():
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: symlink forbidden."
            )
        if not path.is_file():
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: missing file.",
                code="missing_asset",
                location=f"shard {shard_label} file {name}",
            )
        actual_size = path.stat().st_size
        if actual_size != entry["bytes"]:
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: bytes mismatch "
                f"({actual_size} != {entry['bytes']}).",
                code="file_size_mismatch",
                location=f"shard {shard_label} file {name}",
            )
        actual_sha = _sha256_file(path) if verify_checksums else entry["sha256"]
        if actual_sha != entry["sha256"]:
            raise DatasetLayoutError(
                f"shard {shard_label} file {name}: sha256 mismatch.",
                code="checksum_mismatch",
                location=f"shard {shard_label} file {name}",
            )
    audio_meta = payload["audio"]
    header = _read_audio_header(directory / audio_meta["path"])
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
    if scan.producer_error is not None:
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
        marker=payload,
        warnings=scan.warnings,
        warning_count=scan.warning_count,
    )


def _validate_marker_payload(payload: dict[str, Any], *, directory: Path) -> None:
    location = f"shard {directory.name} file shard.complete.json"
    if set(payload) != _MARKER_FIELDS:
        raise DatasetLayoutError(
            f"{location}: marker fields must be exactly {sorted(_MARKER_FIELDS)}."
        )
    if payload["marker_version"] != SHARD_COMPLETION_VERSION:
        raise DatasetLayoutError(
            f"{location}: marker_version must be {SHARD_COMPLETION_VERSION!r}.",
            code="unknown_version",
            location=location,
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
                "newline-terminated.",
                code="truncated_record_file",
                location=f"shard {shard_label} file frames.jsonl",
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
) -> _RecordFileScan:
    shard_label = path.parent.name
    warnings: list[LayoutWarning] = []
    warning_count = 0
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
            warning_count += len(record_warnings)
            remaining = MAX_STREAMING_WARNINGS_PER_SHARD - len(warnings)
            if remaining > 0:
                warnings.extend(record_warnings[:remaining])
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
                        f"{expected_index}.",
                        code="index_gap",
                        location=(
                            f"shard {shard_label} file frames.jsonl line {line_number}"
                        ),
                    )
            if record.episode_id not in episode_seen:
                episode_seen.add(record.episode_id)
                episode_ids.append(record.episode_id)
            max_audio_end = max(max_audio_end, record.audio_end_sample)
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
        producer_db.close()
    if sequence_error is not None:
        raise sequence_error
    return _RecordFileScan(
        warnings=tuple(warnings),
        warning_count=warning_count,
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
    """Classify the supported session lifecycle states."""

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
            f"extra={extra}.",
            code="manifest_marker_disagreement",
            location=f"shard {shard_value}",
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
                f"shard {shard_value} file {name}: manifest/marker sha256 mismatch.",
                code="manifest_marker_disagreement",
                location=f"shard {shard_value} file {name}",
            )
    if tuple(shard.episode_ids) != tuple(marker["episode_ids"]):
        raise DatasetLayoutError(
            f"shard {shard_value}: manifest/marker episode_ids mismatch.",
            code="manifest_marker_disagreement",
            location=f"shard {shard_value}",
        )


def _read_audio_header(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return _wav_header(path)
    if suffix == ".flac":
        return _flac_header(path)
    raise DatasetLayoutError(
        f"file {path}: audio filename must be audio.wav or audio.flac."
    )


def _wav_header(path: Path) -> dict[str, Any]:
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


def _flac_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        blob = stream.read(42)
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


def _reject_symlinks(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            relative = path.relative_to(root).as_posix()
            raise DatasetLayoutError(
                f"session {root} entry {relative}: symlink forbidden."
            )


__all__: list[str] = []
