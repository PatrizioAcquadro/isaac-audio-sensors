"""Checked, incremental loading for finalized dataset sessions.

Record payloads are not opened by :meth:`SessionDataset.open`.  Each shard is
verified once, when iteration or an audio read first enters it, and JSONL
records are then reconstructed one line at a time.  Setting
``verify_checksums=False`` skips SHA-256 work for large trusted-data fast
paths; marker, size, header, record, join, and episode checks remain enabled.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from isaac_audio_sensors.core.constants import DATASET_MANIFEST_SCHEMA_VERSION
from isaac_audio_sensors.core.dataset import layout as _layout
from isaac_audio_sensors.core.dataset.layout import (
    DATASET_FRAME_RECORD_VERSION,
    SHARD_COMPLETION_VERSION,
    DatasetLayoutError,
    canonical_configuration_bytes,
    classify_session_lifecycle,
    configuration_sha256,
    parse_dataset_frame_record,
    serialize_shard_completion,
    verify_shard_completion,
)
from isaac_audio_sensors.core.dataset_manifest import (
    AudioDatasetManifest,
    EpisodeRecord,
    ShardRecord,
)
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.io.manifests import (
    manifest_to_dict,
    read_dataset_manifest,
)
from isaac_audio_sensors.core.io.traces import frame_from_trace_dict
from isaac_audio_sensors.core.types import AudioSensorFrame

_ROOT_ENTRIES = frozenset(
    {"manifest.json", "config", "calibration", "shards", "_staging"}
)
_WAV_HEADER_BYTES = 44
_FLOAT32_BYTES = 4


@dataclass(frozen=True, slots=True, weakref_slot=True)
class LoadedFrame:
    """One typed frame and its authoritative shard-audio join."""

    dataset_frame_index: int
    episode_id: str
    audio_start_sample: int
    audio_end_sample: int
    frame: AudioSensorFrame
    shard_id: str
    line_number: int


class SessionDataset:
    """Read-only checked access to one finalized dataset session."""

    def __init__(
        self,
        session_root: Path,
        manifest: AudioDatasetManifest,
        shards: tuple[ShardRecord, ...],
        *,
        lifecycle_state: str,
        verify_checksums: bool,
        configuration: dict[str, Any],
    ) -> None:
        self.session_root = session_root
        self.manifest = manifest
        self.lifecycle_state = lifecycle_state
        self.verify_checksums = verify_checksums
        self.configuration = configuration
        self._shards = shards
        self._shards_by_id = {shard.shard_id: shard for shard in shards}
        self._verified_markers: dict[str, dict[str, Any]] = {}
        self._max_overlap_samples = _layout._find_overlap(configuration)

    @classmethod
    def open(
        cls,
        session_root: str | Path,
        *,
        allow_incomplete: bool = False,
        verify_checksums: bool = True,
    ) -> SessionDataset:
        """Open metadata without reading any JSONL or audio record payload."""

        if not isinstance(allow_incomplete, bool):
            raise TypeError("allow_incomplete must be a bool.")
        if not isinstance(verify_checksums, bool):
            raise TypeError("verify_checksums must be a bool.")
        root = Path(session_root)
        if root.is_symlink():
            raise DatasetLayoutError(
                f"session {root}: session root may not be a symlink."
            )
        if not root.is_dir():
            raise DatasetLayoutError(
                f"session {root}: session root is not a directory."
            )
        _layout._reject_symlinks(root)
        unknown = sorted(
            path.name for path in root.iterdir() if path.name not in _ROOT_ENTRIES
        )
        if unknown:
            raise DatasetLayoutError(f"session {root}: unknown root entries {unknown}.")

        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            lifecycle = classify_session_lifecycle(root)
            if lifecycle == "in-progress-or-aborted":
                raise DatasetLayoutError(
                    f"session {root}: in-progress or aborted session."
                )
        payload = _read_json_object(manifest_path, f"session {root} file manifest.json")
        version = payload.get("schema_version", "<missing>")
        if version != DATASET_MANIFEST_SCHEMA_VERSION:
            raise DatasetLayoutError(
                f"session {root} file manifest.json: schema_version {version!r}; "
                f"expected {DATASET_MANIFEST_SCHEMA_VERSION!r}."
            )
        try:
            manifest = read_dataset_manifest(manifest_path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DatasetLayoutError(
                f"session {root} file manifest.json: invalid manifest: {exc}"
            ) from exc
        if manifest_to_dict(manifest) != payload:
            raise DatasetLayoutError(
                f"session {root} file manifest.json: values are not an exact "
                "manifest-v1 projection (silent coercion or omitted fields)."
            )

        lifecycle = classify_session_lifecycle(root)
        if lifecycle == "in-progress-or-aborted":
            raise DatasetLayoutError(f"session {root}: in-progress or aborted session.")
        if lifecycle == "finalized-incomplete" and not allow_incomplete:
            raise DatasetLayoutError(
                f"session {root}: finalized-incomplete session refused."
            )
        if manifest.runtime_profile != "waveform_fidelity":
            raise DatasetLayoutError(
                f"session {root} file manifest.json: unsupported runtime profile "
                "for dataset layout v1."
            )

        for ordinal, episode in enumerate(manifest.episodes):
            expected = f"episode_{ordinal:05d}"
            if episode.episode_id != expected:
                raise DatasetLayoutError(
                    f"session {root} episode {episode.episode_id}: expected {expected}."
                )
        for ordinal, shard in enumerate(manifest.shards):
            expected = f"shard_{ordinal:05d}"
            if shard.shard_id != expected:
                raise DatasetLayoutError(
                    f"session {root} shard {shard.shard_id}: expected {expected}."
                )
            if lifecycle == "complete" and shard.completion_state != "complete":
                raise DatasetLayoutError(
                    f"session {root} shard {shard.shard_id}: complete session "
                    "lists an incomplete shard."
                )

        configuration = _read_configuration(root, manifest)
        shards = tuple(
            shard for shard in manifest.shards if shard.completion_state == "complete"
        )
        _check_shard_directory_inventory(root, manifest.shards)
        _check_calibration_reference(root, manifest)
        return cls(
            root,
            manifest,
            shards,
            lifecycle_state=lifecycle,
            verify_checksums=verify_checksums,
            configuration=configuration,
        )

    def iter_records(self, episode_id: str | None = None) -> Iterator[LoadedFrame]:
        """Yield checked frames in exact dataset order, retaining only one record."""

        if episode_id is not None and episode_id not in {
            episode.episode_id for episode in self.manifest.episodes
        }:
            raise DatasetLayoutError(
                f"session {self.session_root} episode {episode_id}: "
                "absent from manifest."
            )
        for item in self._iter_all_records():
            if episode_id is None or item.episode_id == episode_id:
                yield item

    def iter_episodes(self) -> Iterator[tuple[EpisodeRecord, Iterator[LoadedFrame]]]:
        """Yield manifest episodes with their single-pass streamed frame iterator.

        The episode iterator shares the outer session stream and must be consumed
        before requesting the next episode.  Unconsumed frames are checked and
        drained when the outer iterator advances.
        """

        records = self._iter_all_records()
        for episode in self.manifest.episodes:
            remaining = episode.end_frame - episode.start_frame + 1

            def episode_frames(count: int = remaining) -> Iterator[LoadedFrame]:
                for _ in range(count):
                    yield next(records)

            frames = episode_frames()
            yield episode, frames
            for _ in frames:
                pass
        try:
            extra = next(records)
        except StopIteration:
            return
        raise DatasetLayoutError(
            f"session {self.session_root}: extra dataset record at frame "
            f"{extra.dataset_frame_index}."
        )

    def read_frame_audio(self, item: LoadedFrame) -> np.ndarray:
        """Read only ``item``'s half-open shard sample range."""

        if not isinstance(item, LoadedFrame):
            raise TypeError("item must be a LoadedFrame.")
        if item.shard_id not in self._shards_by_id:
            raise DatasetLayoutError(
                f"session {self.session_root} shard {item.shard_id}: unknown shard "
                f"for frame {item.dataset_frame_index}."
            )
        return self.read_shard_audio(
            item.shard_id, item.audio_start_sample, item.audio_end_sample
        )

    def read_shard_audio(
        self, shard_id: str, start_sample: int, end_sample: int
    ) -> np.ndarray:
        """Seek-read one bounded channel-first WAV or FLAC sample window."""

        shard = self._shards_by_id.get(shard_id)
        if shard is None:
            raise DatasetLayoutError(
                f"session {self.session_root} shard {shard_id}: "
                "absent from loadable shards."
            )
        marker = self._ensure_shard(shard)
        location = f"shard {shard_id} file {marker['audio']['path']}"
        for name, value in (("start_sample", start_sample), ("end_sample", end_sample)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DatasetLayoutError(
                    f"{location}: {name} must be a non-negative integer; got {value!r}."
                )
        if end_sample < start_sample:
            raise DatasetLayoutError(
                f"{location}: requested range [{start_sample}, {end_sample}) "
                "is inverted."
            )
        sample_count = marker["audio"]["sample_count"]
        if end_sample > sample_count:
            raise DatasetLayoutError(
                f"{location}: requested range [{start_sample}, {end_sample}) exceeds "
                f"sample_count {sample_count}."
            )
        channels = marker["audio"]["channels"]
        if start_sample == end_sample:
            return np.zeros(
                (channels, 0),
                dtype=_decoded_audio_dtype(marker["audio"]["dtype"]),
            )
        if marker["audio"]["path"] == "audio.flac":
            return _read_flac_range(
                self.session_root / "shards" / shard_id / "audio.flac",
                start_sample=start_sample,
                end_sample=end_sample,
                channels=channels,
                declared_dtype=str(marker["audio"]["dtype"]),
                location=location,
            )
        if (
            marker["audio"]["path"] != "audio.wav"
            or marker["audio"]["dtype"] != "float32"
        ):
            raise DatasetLayoutError(
                f"{location}: bounded range reads require float32 audio.wav."
            )
        path = self.session_root / "shards" / shard_id / "audio.wav"
        byte_count = (end_sample - start_sample) * channels * _FLOAT32_BYTES
        try:
            with path.open("rb") as stream:
                stream.seek(
                    _WAV_HEADER_BYTES + start_sample * channels * _FLOAT32_BYTES
                )
                payload = stream.read(byte_count)
        except OSError as exc:
            raise DatasetLayoutError(f"{location}: range read failed: {exc}") from exc
        if len(payload) != byte_count:
            raise DatasetLayoutError(
                f"{location}: truncated range payload "
                f"({len(payload)} != {byte_count} bytes)."
            )
        interleaved = np.frombuffer(payload, dtype="<f4")
        return np.ascontiguousarray(interleaved.reshape(-1, channels).T)


    def _iter_all_records(self) -> Iterator[LoadedFrame]:
        episodes = self.manifest.episodes
        expected_episode_start = 0
        for episode in episodes:
            if episode.start_frame != expected_episode_start:
                raise DatasetLayoutError(
                    f"session {self.session_root} episode {episode.episode_id}: "
                    f"start_frame {episode.start_frame} breaks episode tiling at "
                    f"frame {expected_episode_start}."
                )
            count = episode.end_frame - episode.start_frame + 1
            if len(episode.timestamps_ms) != count:
                raise DatasetLayoutError(
                    f"session {self.session_root} episode {episode.episode_id}: "
                    f"timestamps_ms length {len(episode.timestamps_ms)} != {count} "
                    f"at frame {episode.start_frame}."
                )
            expected_episode_start = episode.end_frame + 1

        expected_index = 0
        episode_ordinal = 0
        previous_timestamp: int | None = None
        producer_db = sqlite3.connect("")
        producer_db.execute("PRAGMA cache_size = -1024")
        producer_db.execute("PRAGMA temp_store = FILE")
        producer_db.execute(
            "CREATE TABLE producer_ids (episode_id TEXT NOT NULL, "
            "producer_frame_id TEXT NOT NULL, PRIMARY KEY "
            "(episode_id, producer_frame_id)) WITHOUT ROWID"
        )
        try:
            for shard_ordinal, shard in enumerate(self._shards):
                marker = self._ensure_shard(shard)
                expected_shard_id = f"shard_{shard_ordinal:05d}"
                if marker["shard_id"] != expected_shard_id:
                    raise DatasetLayoutError(
                        f"shard {marker['shard_id']}: expected ordinal id "
                        f"{expected_shard_id} at frame {expected_index}."
                    )
                if marker["start_frame"] != expected_index:
                    raise DatasetLayoutError(
                        f"shard {shard.shard_id}: start_frame {marker['start_frame']} "
                        f"breaks tiling at expected frame {expected_index}."
                    )
                frames_path = (
                    self.session_root / "shards" / shard.shard_id / "frames.jsonl"
                )
                line_count = 0
                try:
                    stream = frames_path.open("rb")
                except OSError as exc:
                    raise DatasetLayoutError(
                        f"shard {shard.shard_id} file frames.jsonl: cannot open: {exc}"
                    ) from exc
                with stream:
                    for line_number, line in enumerate(stream, start=1):
                        line_count = line_number
                        location = (
                            f"shard {shard.shard_id} file frames.jsonl line "
                            f"{line_number}"
                        )
                        record = _parse_record(
                            line, location, marker, self.session_root
                        )
                        if record.dataset_frame_index != expected_index:
                            raise DatasetLayoutError(
                                f"{location}: dataset_frame_index "
                                f"{record.dataset_frame_index} != {expected_index}."
                            )
                        while (
                            episode_ordinal < len(episodes)
                            and expected_index > episodes[episode_ordinal].end_frame
                        ):
                            episode_ordinal += 1
                            previous_timestamp = None
                        if episode_ordinal >= len(episodes):
                            raise DatasetLayoutError(
                                f"session {self.session_root}: extra dataset record "
                                f"at frame {expected_index} ({location})."
                            )
                        episode = episodes[episode_ordinal]
                        if expected_index < episode.start_frame:
                            raise DatasetLayoutError(
                                f"session {self.session_root} episode "
                                f"{episode.episode_id}: missing record at frame "
                                f"{expected_index} ({location})."
                            )
                        if record.episode_id != episode.episode_id:
                            raise DatasetLayoutError(
                                f"session {self.session_root} episode "
                                f"{episode.episode_id}: boundary crossing by "
                                f"{record.episode_id} at frame {expected_index} "
                                f"({location})."
                            )
                        offset = expected_index - episode.start_frame
                        timestamp = record.frame.get("timestamp_ms")
                        if (
                            previous_timestamp is not None
                            and timestamp < previous_timestamp
                        ):
                            raise DatasetLayoutError(
                                f"session {self.session_root} episode "
                                f"{episode.episode_id}: non-monotonic timestamp at "
                                f"frame {expected_index} ({location})."
                            )
                        if timestamp != episode.timestamps_ms[offset]:
                            raise DatasetLayoutError(
                                f"session {self.session_root} episode "
                                f"{episode.episode_id}: timestamp mismatch at frame "
                                f"{expected_index} ({location}); record={timestamp!r}, "
                                f"manifest={episode.timestamps_ms[offset]!r}."
                            )
                        previous_timestamp = timestamp
                        producer_id = record.frame["frame_id"]
                        try:
                            producer_db.execute(
                                "INSERT INTO producer_ids VALUES (?, ?)",
                                (record.episode_id, producer_id),
                            )
                        except sqlite3.IntegrityError as exc:
                            raise DatasetLayoutError(
                                f"session {self.session_root} episode "
                                f"{episode.episode_id}: duplicate producer frame_id "
                                f"{producer_id!r} at frame {expected_index} "
                                f"({location})."
                            ) from exc
                        try:
                            frame = frame_from_trace_dict(record.frame)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise DatasetLayoutError(
                                f"{location}.frame: cannot reconstruct "
                                f"AudioSensorFrame: {exc}"
                            ) from exc
                        yield LoadedFrame(
                            dataset_frame_index=expected_index,
                            episode_id=record.episode_id,
                            audio_start_sample=record.audio_start_sample,
                            audio_end_sample=record.audio_end_sample,
                            frame=frame,
                            shard_id=shard.shard_id,
                            line_number=line_number,
                        )
                        expected_index += 1
                if line_count != marker["frame_count"]:
                    raise DatasetLayoutError(
                        f"shard {shard.shard_id} file frames.jsonl: line count "
                        f"{line_count} does not equal frame_count "
                        f"{marker['frame_count']}."
                    )
        finally:
            producer_db.close()

        expected_total = episodes[-1].end_frame + 1 if episodes else 0
        if expected_index != expected_total:
            episode_id = episodes[-1].episode_id if episodes else "<none>"
            raise DatasetLayoutError(
                f"session {self.session_root} episode {episode_id}: missing record "
                f"at frame {expected_index}; expected {expected_total} total records."
            )

    def _ensure_shard(self, shard: ShardRecord) -> dict[str, Any]:
        cached = self._verified_markers.get(shard.shard_id)
        if cached is not None:
            return cached
        shard_dir = self.session_root / "shards" / shard.shard_id
        marker = _read_marker(shard_dir)
        try:
            if self.verify_checksums:
                verified = verify_shard_completion(
                    shard_dir,
                    manifest=self.manifest,
                    max_overlap_samples=self._max_overlap_samples,
                    retain_records=False,
                )
                marker = verified.marker
            else:
                _verify_without_sha256(
                    shard_dir,
                    marker,
                    self.manifest,
                    self._max_overlap_samples,
                )
        except DatasetLayoutError as exc:
            if "record_version" in str(exc):
                _raise_located_record_version(shard_dir)
            raise
        self._verified_markers[shard.shard_id] = marker
        return marker


def _decoded_audio_dtype(declared_dtype: str) -> np.dtype[Any]:
    if declared_dtype == "float32":
        return np.dtype(np.float32)
    if declared_dtype == "int16":
        return np.dtype(np.int16)
    if declared_dtype == "int24":
        # libsndfile exposes 24-bit PCM left-aligned in int32 containers.
        return np.dtype(np.int32)
    raise DatasetLayoutError(f"unsupported replay dtype {declared_dtype!r}")


def _read_flac_range(
    path: Path,
    *,
    start_sample: int,
    end_sample: int,
    channels: int,
    declared_dtype: str,
    location: str,
) -> np.ndarray:
    try:
        import soundfile  # type: ignore
    except ImportError as exc:
        raise OptionalDependencyUnavailable(
            "FLAC dataset export and replay require soundfile from the 'room' extra."
        ) from exc
    dtype = "int16" if declared_dtype == "int16" else "int32"
    if declared_dtype not in {"int16", "int24"}:
        raise DatasetLayoutError(
            f"{location}: FLAC replay requires declared dtype int16 or int24."
        )
    try:
        with soundfile.SoundFile(path, mode="r") as stream:
            stream.seek(start_sample)
            data = stream.read(
                end_sample - start_sample,
                dtype=dtype,
                always_2d=True,
            )
    except (OSError, RuntimeError) as exc:
        raise DatasetLayoutError(f"{location}: FLAC range read failed: {exc}") from exc
    expected_shape = (end_sample - start_sample, channels)
    if data.shape != expected_shape:
        raise DatasetLayoutError(
            f"{location}: truncated FLAC range {data.shape} != {expected_shape}."
        )
    return np.ascontiguousarray(data.T)


def _read_json_object(path: Path, location: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_bytes())
    except FileNotFoundError as exc:
        raise DatasetLayoutError(f"{location}: missing file.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLayoutError(f"{location}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: must be a JSON object.")
    return payload


def _read_configuration(root: Path, manifest: AudioDatasetManifest) -> dict[str, Any]:
    path = root / "config" / "session_config.json"
    location = f"session {root} file config/session_config.json"
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except FileNotFoundError as exc:
        raise DatasetLayoutError(f"{location}: missing file.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetLayoutError(f"{location}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetLayoutError(f"{location}: must be an object.")
    try:
        canonical = canonical_configuration_bytes(payload)
    except ValueError as exc:
        raise DatasetLayoutError(f"{location}: {exc}") from exc
    if canonical != raw:
        raise DatasetLayoutError(f"{location}: bytes are not canonical.")
    actual = configuration_sha256(raw)
    if actual != manifest.configuration_sha256:
        raise DatasetLayoutError(
            f"{location}: configuration_sha256 mismatch "
            f"({actual} != {manifest.configuration_sha256})."
        )
    if payload.get("runtime_profile") != "waveform_fidelity":
        raise DatasetLayoutError(
            f"{location}: unsupported runtime profile for dataset layout v1."
        )
    return payload


def _check_shard_directory_inventory(
    root: Path, shards: tuple[ShardRecord, ...]
) -> None:
    shards_root = root / "shards"
    if not shards_root.exists():
        return
    if not shards_root.is_dir():
        raise DatasetLayoutError(f"session {root}: shards is not a directory.")
    entries = tuple(shards_root.iterdir())
    non_dirs = sorted(path.name for path in entries if not path.is_dir())
    if non_dirs:
        raise DatasetLayoutError(
            f"session {root}: non-directory entries under shards {non_dirs}."
        )
    listed = {shard.shard_id for shard in shards}
    unlisted = sorted(path.name for path in entries if path.name not in listed)
    if unlisted:
        raise DatasetLayoutError(
            f"session {root}: unlisted shard directories {unlisted}."
        )


def _check_calibration_reference(root: Path, manifest: AudioDatasetManifest) -> None:
    reference = manifest.calibration_profile
    if reference is None:
        return
    path = root.joinpath(*PurePosixPath(reference.path).parts)
    if not path.is_file():
        raise DatasetLayoutError(
            f"session {root} file {reference.path}: missing calibration profile."
        )
    if _layout._sha256_file(path) != reference.sha256:
        raise DatasetLayoutError(
            f"session {root} file {reference.path}: calibration sha256 mismatch."
        )


def _read_marker(shard_dir: Path) -> dict[str, Any]:
    location = f"shard {shard_dir.name} file shard.complete.json"
    path = shard_dir / "shard.complete.json"
    payload = _read_json_object(path, location)
    version = payload.get("marker_version", "<missing>")
    if version != SHARD_COMPLETION_VERSION:
        raise DatasetLayoutError(
            f"{location}: marker_version {version!r}; "
            f"expected {SHARD_COMPLETION_VERSION!r}."
        )
    _layout._validate_marker_payload(payload, directory=shard_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetLayoutError(f"{location}: cannot read: {exc}") from exc
    if text != serialize_shard_completion(payload):
        raise DatasetLayoutError(f"{location}: marker is not canonical JSON.")
    if payload["shard_id"] != shard_dir.name:
        raise DatasetLayoutError(
            f"{location}: marker shard_id {payload['shard_id']!r} does not equal "
            "containing directory."
        )
    return payload


def _verify_without_sha256(
    shard_dir: Path,
    marker: dict[str, Any],
    manifest: AudioDatasetManifest,
    max_overlap_samples: int | None,
) -> None:
    shard_id = shard_dir.name
    expected_entries = {"frames.jsonl", marker["audio"]["path"], "shard.complete.json"}
    try:
        actual_entries = {path.name for path in shard_dir.iterdir()}
    except OSError as exc:
        raise DatasetLayoutError(
            f"shard {shard_id}: cannot inspect directory: {exc}"
        ) from exc
    if actual_entries != expected_entries:
        raise DatasetLayoutError(
            f"shard {shard_id}: on-disk entries must be exactly "
            f"{sorted(expected_entries)}; got {sorted(actual_entries)}."
        )
    for entry in marker["files"]:
        path = shard_dir / entry["path"]
        location = f"shard {shard_id} file {entry['path']}"
        if path.is_symlink():
            raise DatasetLayoutError(f"{location}: symlink forbidden.")
        if not path.is_file():
            raise DatasetLayoutError(f"{location}: missing file.")
        actual_size = path.stat().st_size
        if actual_size != entry["bytes"]:
            raise DatasetLayoutError(
                f"{location}: bytes mismatch ({actual_size} != {entry['bytes']})."
            )
    audio = marker["audio"]
    header = _layout._read_audio_header(shard_dir / audio["path"], streaming=True)
    for field in (
        "container",
        "subtype",
        "channels",
        "sample_rate_hz",
        "dtype",
        "sample_count",
    ):
        if header[field] != audio[field]:
            raise DatasetLayoutError(
                f"shard {shard_id} file {audio['path']}: decoded audio header "
                f"{field}={header[field]!r} disagrees with marker {audio[field]!r}."
            )
    resets = tuple(
        reset.frame_index
        for episode in manifest.episodes
        if episode.episode_id in marker["episode_ids"]
        for reset in episode.reset_markers
    )
    scan = _layout._scan_record_file(
        shard_dir / "frames.jsonl",
        sample_count=audio["sample_count"],
        session_root=shard_dir.parent.parent,
        reset_frame_indices=resets,
        max_overlap_samples=max_overlap_samples,
        expected_start_frame=marker["start_frame"],
        retain_records=False,
    )
    if scan.line_count != marker["frame_count"]:
        raise DatasetLayoutError(
            f"shard {shard_id} file frames.jsonl: line count {scan.line_count} "
            f"does not equal frame_count {marker['frame_count']}."
        )
    if scan.index_error is not None:
        raise scan.index_error
    if scan.producer_error is not None:
        raise scan.producer_error
    if scan.episode_ids != tuple(marker["episode_ids"]):
        raise DatasetLayoutError(
            f"shard {shard_id} file frames.jsonl: episode_ids do not exactly "
            "match marker first-appearance order."
        )
    expected_tail = audio["sample_count"] - scan.max_audio_end
    if marker["tail_samples"] != expected_tail:
        raise DatasetLayoutError(
            f"shard {shard_id} file shard.complete.json: tail_samples "
            f"{marker['tail_samples']} != {expected_tail}."
        )
    _layout._verify_manifest_marker_agreement(manifest, marker, shard_dir)
    if audio["channels"] != len(manifest.channel_order):
        raise DatasetLayoutError(
            f"shard {shard_id} file {audio['path']}: channel count disagrees "
            "with manifest channel_order."
        )
    for field in ("sample_rate_hz", "dtype"):
        if audio[field] != getattr(manifest, field):
            raise DatasetLayoutError(
                f"shard {shard_id} file {audio['path']}: {field} "
                "disagrees with manifest."
            )


def _parse_record(
    line: bytes,
    location: str,
    marker: Mapping[str, Any],
    session_root: Path,
) -> _layout.DatasetFrameRecord:
    try:
        payload = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        version = payload.get("record_version", "<missing>")
        if version != DATASET_FRAME_RECORD_VERSION:
            raise DatasetLayoutError(
                f"{location}: record_version {version!r}; "
                f"expected {DATASET_FRAME_RECORD_VERSION!r}."
            )
    return parse_dataset_frame_record(
        line,
        location=location,
        sample_count=marker["audio"]["sample_count"],
        session_root=session_root,
    )


def _raise_located_record_version(shard_dir: Path) -> None:
    path = shard_dir / "frames.jsonl"
    try:
        with path.open("rb") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                version = payload.get("record_version", "<missing>")
                if version != DATASET_FRAME_RECORD_VERSION:
                    raise DatasetLayoutError(
                        f"shard {shard_dir.name} file frames.jsonl line "
                        f"{line_number}: record_version {version!r}; expected "
                        f"{DATASET_FRAME_RECORD_VERSION!r}."
                    )
    except OSError:
        return
