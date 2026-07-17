"""Bounded-memory orchestration for one audio dataset session."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_UNITS,
)
from isaac_audio_sensors.core.dataset.atomic import (
    CancellationToken,
    CancelledWrite,
    FilesystemSeam,
    JsonlShardFile,
    StagedFile,
    publish_file,
    write_json_atomic,
)
from isaac_audio_sensors.core.dataset.audio_shards import (
    CarryState,
    StreamingWavShardWriter,
)
from isaac_audio_sensors.core.dataset.layout import (
    DatasetLayoutError,
    ShardBoundary,
    ShardPlanner,
    VerifiedShard,
    build_dataset_frame_record,
    canonical_configuration_bytes,
    configuration_sha256,
    episode_id,
    episode_seed,
    serialize_dataset_frame_record,
    shard_id,
    validate_trace_projection,
    verify_shard_completion,
    verify_shard_tiling,
)
from isaac_audio_sensors.core.dataset_manifest import (
    AssetRecord,
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ResetMarker,
    ShardRecord,
)
from isaac_audio_sensors.core.io.manifests import manifest_to_dict
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.types import AudioSensorFrame

_REQUIRED_CONFIGURATION_KEYS = frozenset(
    {
        "backend_id",
        "channel_order",
        "dataset_id",
        "dtype",
        "hop_sample_count",
        "runtime_profile",
        "sample_rate_hz",
        "session_seed",
        "shard_episode_aligned",
        "shard_max_frames",
        "split_grouping_key",
        "window_sample_count",
    }
)
_STATE_VERSION = "ias.session_recorder_state.v1"


class SessionRecorderError(RuntimeError):
    """Located session-writer failure."""


@dataclass(frozen=True, slots=True)
class AppendFrameResult:
    """Outcome of one producer append attempt."""

    accepted: bool
    dataset_frame_index: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ShardPromotion:
    """Notification emitted after a shard marker verifies."""

    shard_id: str
    shard_ordinal: int
    start_frame: int
    frame_count: int
    monotonic_timestamp_s: float


@dataclass(slots=True)
class _EpisodeState:
    ordinal: int
    scene_id: str
    environment_id: str
    split_group: str
    seed: int
    start_frame: int
    frame_count: int = 0
    last_timestamp_ms: int | None = None
    reset_frame_indices: list[int] = field(default_factory=list)
    ended: bool = False
    end_frame: int | None = None

    def state_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "scene_id": self.scene_id,
            "environment_id": self.environment_id,
            "split_group": self.split_group,
            "seed": self.seed,
            "start_frame": self.start_frame,
            "reset_frame_indices": list(self.reset_frame_indices),
            "ended": self.ended,
            "end_frame": self.end_frame,
        }


@dataclass(slots=True)
class _OpenShard:
    boundary_start: int
    shard_ordinal: int
    staging_dir: Path
    jsonl: JsonlShardFile
    wav: StreamingWavShardWriter
    episode_ids: list[str] = field(default_factory=list)
    frame_count: int = 0
    max_audio_end: int = 0


@dataclass(slots=True)
class _EpisodeBuffer:
    directory: Path
    metadata: StagedFile
    audio: StagedFile
    start_frame: int
    frame_count: int = 0


@dataclass(slots=True)
class _PendingRecord:
    frame_payload: dict[str, Any]
    dataset_frame_index: int
    episode_id_value: str
    audio_start: int
    desired_audio_end: int


class SessionRecorder:
    """Record and atomically publish one waveform-fidelity session.

    Construction starts a new session. Use :meth:`resume` (or module-level
    :func:`resume`) for an in-progress-or-aborted root.
    """

    def __init__(
        self,
        session_root: str | Path,
        configuration: Mapping[str, Any],
        *,
        creation: CreationProvenance,
        device: DeviceProvenance,
        license: str,
        source: str,
        coordinate_frames: Sequence[str],
        time_base: str,
        creation_timestamp_ms: int | None = None,
        seam: FilesystemSeam | None = None,
        cancellation_token: CancellationToken | None = None,
        promotion_callback: Callable[[ShardPromotion], None] | None = None,
        _resume_payload: dict[str, Any] | None = None,
    ) -> None:
        self.session_root = Path(session_root)
        self.seam = seam or FilesystemSeam()
        self.cancellation_token = cancellation_token or CancellationToken()
        self.creation = creation
        self.device = device
        self.license = license
        self.source = source
        self.coordinate_frames = tuple(coordinate_frames)
        self.time_base = time_base
        self._creation_timestamp_explicit = creation_timestamp_ms is not None
        self.creation_timestamp_ms = (
            int(time.time() * 1000)
            if creation_timestamp_ms is None
            else int(creation_timestamp_ms)
        )
        self._promotion_callback = promotion_callback
        self._configuration_bytes = canonical_configuration_bytes(configuration)
        self.configuration: dict[str, Any] = json.loads(self._configuration_bytes)
        self._validate_configuration()

        self._staging_root = self.session_root / "_staging"
        self._shards_root = self.session_root / "shards"
        self._state_path = self._staging_root / "recorder_state.json"
        self._planner = ShardPlanner(
            shard_max_frames=self.shard_max_frames,
            shard_episode_aligned=self.shard_episode_aligned,
        )
        self._episodes: list[_EpisodeState] = []
        self._current_episode: _EpisodeState | None = None
        self._next_dataset_frame = 0
        self._open_shard: _OpenShard | None = None
        self._episode_buffer: _EpisodeBuffer | None = None
        self._pending_boundary: ShardBoundary | None = None
        self._pending_record: _PendingRecord | None = None
        self._carry = CarryState(np.zeros((self.channels, 0), dtype=np.float32))
        self._pending_drop_count = 0
        self._pending_drop_ids: list[str] = []
        self._published: list[VerifiedShard] = []
        self._closed = False
        self._handling_cancellation = False
        self._producer_db: sqlite3.Connection | None = None

        if _resume_payload is None:
            self._start_new_session()
        else:
            self._restore_session(_resume_payload)

    @property
    def shard_max_frames(self) -> int:
        return int(self.configuration["shard_max_frames"])

    @property
    def shard_episode_aligned(self) -> bool:
        return bool(self.configuration["shard_episode_aligned"])

    @property
    def channels(self) -> int:
        return len(self.configuration["channel_order"])

    @property
    def sample_rate_hz(self) -> int:
        return int(self.configuration["sample_rate_hz"])

    @property
    def window_sample_count(self) -> int:
        return int(self.configuration["window_sample_count"])

    @property
    def hop_sample_count(self) -> int:
        return int(self.configuration["hop_sample_count"])

    @property
    def next_dataset_frame_index(self) -> int:
        """The next index the recorder will assign to an accepted frame."""

        return self._next_dataset_frame

    @property
    def promoted_shard_count(self) -> int:
        return len(self._published)

    def _validate_configuration(self) -> None:
        missing = sorted(_REQUIRED_CONFIGURATION_KEYS - self.configuration.keys())
        if missing:
            raise ValueError(f"configuration is missing required keys: {missing}")
        if self.configuration["runtime_profile"] != "waveform_fidelity":
            raise ValueError("unsupported runtime profile for dataset layout v1")
        if self.configuration["dtype"] != "float32":
            raise ValueError("dataset recorder requires dtype 'float32'")
        for key in (
            "sample_rate_hz",
            "shard_max_frames",
            "window_sample_count",
            "hop_sample_count",
        ):
            value = self.configuration[key]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"configuration.{key} must be a positive integer")
        seed = self.configuration["session_seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError(
                "configuration.session_seed must be a non-negative integer"
            )
        if not isinstance(self.configuration["shard_episode_aligned"], bool):
            raise ValueError("configuration.shard_episode_aligned must be a bool")
        channels = self.configuration["channel_order"]
        if (
            not isinstance(channels, list)
            or not channels
            or any(not isinstance(value, str) or not value for value in channels)
            or len(set(channels)) != len(channels)
        ):
            raise ValueError("configuration.channel_order must contain unique ids")
        for key in ("dataset_id", "split_grouping_key", "backend_id"):
            if (
                not isinstance(self.configuration[key], str)
                or not self.configuration[key]
            ):
                raise ValueError(f"configuration.{key} must be a non-empty string")
        if self.creation.backend_id != self.configuration["backend_id"]:
            raise ValueError("creation.backend_id must match configuration.backend_id")

    def _start_new_session(self) -> None:
        if self.session_root.exists() and any(self.session_root.iterdir()):
            raise SessionRecorderError(
                f"session {self.session_root}: new session root is not empty"
            )
        self.seam.mkdir(self.session_root, parents=True, exist_ok=True)
        self.seam.mkdir(self._staging_root, parents=True, exist_ok=True)
        self.seam.mkdir(self._shards_root, parents=True, exist_ok=True)
        self._open_producer_index()
        staged = StagedFile(
            self._staging_root / "config",
            "session_config.json",
            seam=self.seam,
            cancellation_token=self.cancellation_token,
        )
        try:
            staged.append(self._configuration_bytes)
            publish_file(staged, self.session_root / "config/session_config.json")
        except BaseException:
            staged.abort()
            raise
        self._write_state()

    def begin_episode(
        self,
        scene_id: str,
        environment_id: str,
        split_group: str,
        seed: int | None = None,
    ) -> str:
        """Open the next episode and return its deterministic dataset id."""

        try:
            self._check_open()
            self.cancellation_token.check()
            if self._current_episode is not None:
                raise RuntimeError("an episode is already open")
            for name, value in (
                ("scene_id", scene_id),
                ("environment_id", environment_id),
                ("split_group", split_group),
            ):
                if not isinstance(value, str) or not value:
                    raise ValueError(f"{name} must be a non-empty string")
            ordinal = len(self._episodes)
            episode_value = episode_id(ordinal)
            chosen_seed = (
                episode_seed(
                    self.configuration["dataset_id"],
                    self.configuration["session_seed"],
                    ordinal,
                )
                if seed is None
                else seed
            )
            if (
                isinstance(chosen_seed, bool)
                or not isinstance(chosen_seed, int)
                or chosen_seed < 0
            ):
                raise ValueError("episode seed must be a non-negative integer")
            episode = _EpisodeState(
                ordinal=ordinal,
                scene_id=scene_id,
                environment_id=environment_id,
                split_group=split_group,
                seed=chosen_seed,
                start_frame=self._next_dataset_frame,
            )
            self._episodes.append(episode)
            self._current_episode = episode
            self._write_state()
            return episode_value
        except CancelledWrite:
            self._cancel_and_finalize()
            raise

    def append_frame(
        self,
        frame: AudioSensorFrame | dict[str, Any],
        audio_block: np.ndarray | None,
        timestamp_ms: int,
        is_reset: bool = False,
    ) -> AppendFrameResult:
        """Validate and append one producer frame.

        Projection or payload validation failures are accounted as drops and
        return ``accepted=False`` without consuming a dataset frame index.
        """

        try:
            self._check_open()
            self.cancellation_token.check()
            if self._current_episode is None:
                raise RuntimeError("begin_episode() must be called first")
            payload, block, reason = self._validated_append_inputs(
                frame, audio_block, timestamp_ms, is_reset
            )
            if reason is not None:
                self._record_drop(frame)
                return AppendFrameResult(False, None, reason)
            assert payload is not None
            if self._pending_boundary is not None:
                self._resolve_pending_boundary(mid_episode=True)

            dataset_index = self._next_dataset_frame
            if is_reset:
                self._current_episode.reset_frame_indices.append(dataset_index)
                self._write_state()
            boundaries = self._planner.feed_frame(
                self._current_episode.ordinal,
                self._current_episode.split_group,
            )
            self._next_dataset_frame += 1
            self._current_episode.frame_count += 1
            self._current_episode.last_timestamp_ms = int(timestamp_ms)
            self._record_producer_id(
                self._current_episode.ordinal, str(payload["frame_id"])
            )

            if self.shard_episode_aligned:
                self._buffer_aligned_frame(
                    payload,
                    block,
                    dataset_index=dataset_index,
                    is_reset=is_reset,
                )
                self._handle_aligned_feed_boundaries(boundaries)
            else:
                self._append_unaligned_frame(
                    payload,
                    block,
                    dataset_index=dataset_index,
                    is_reset=is_reset,
                    boundaries=boundaries,
                )
            return AppendFrameResult(True, dataset_index)
        except CancelledWrite:
            self._cancel_and_finalize()
            raise

    def _validated_append_inputs(
        self,
        frame: AudioSensorFrame | dict[str, Any],
        audio_block: np.ndarray | None,
        timestamp_ms: int,
        is_reset: bool,
    ) -> tuple[dict[str, Any] | None, np.ndarray | None, str | None]:
        try:
            if not isinstance(is_reset, bool):
                raise ValueError("is_reset must be a bool")
            if isinstance(timestamp_ms, bool) or int(timestamp_ms) != timestamp_ms:
                raise ValueError("timestamp_ms must be an integer")
            payload = (
                frame_to_trace_dict(frame)
                if isinstance(frame, AudioSensorFrame)
                else frame
            )
            validate_trace_projection(
                payload,
                session_root=self.session_root,
                location="producer frame",
            )
            assert isinstance(payload, dict)
            if payload["timestamp_ms"] != int(timestamp_ms):
                raise ValueError("timestamp_ms disagrees with frame.timestamp_ms")
            if payload["backend_id"] != self.configuration["backend_id"]:
                raise ValueError("frame.backend_id disagrees with configuration")
            if payload.get("sample_rate_hz") not in (None, self.sample_rate_hz):
                raise ValueError("frame.sample_rate_hz disagrees with configuration")
            episode = self._current_episode
            assert episode is not None
            if (
                episode.last_timestamp_ms is not None
                and timestamp_ms < episode.last_timestamp_ms
            ):
                raise ValueError("timestamp_ms is non-monotonic within the episode")
            if self._producer_id_exists(episode.ordinal, str(payload["frame_id"])):
                raise ValueError("duplicate producer frame_id within the episode")
            block: np.ndarray | None = None
            if audio_block is not None:
                if not isinstance(audio_block, np.ndarray):
                    raise ValueError("audio_block must be a numpy ndarray or None")
                if audio_block.dtype != np.float32:
                    raise ValueError("audio_block dtype must be float32")
                if audio_block.ndim != 2 or audio_block.shape[0] != self.channels:
                    raise ValueError(
                        f"audio_block must have shape ({self.channels}, samples)"
                    )
                if not np.isfinite(audio_block).all():
                    raise ValueError("audio_block must contain finite samples")
                block = np.ascontiguousarray(audio_block)
            return payload, block, None
        except (DatasetLayoutError, KeyError, TypeError, ValueError) as exc:
            return None, None, str(exc)

    def _record_drop(self, frame: AudioSensorFrame | dict[str, Any]) -> None:
        producer_id: object
        if isinstance(frame, AudioSensorFrame):
            producer_id = frame.frame_id
        elif isinstance(frame, dict):
            producer_id = frame.get("frame_id", "<unknown>")
        else:
            producer_id = "<unknown>"
        text = str(producer_id) or "<unknown>"
        self._pending_drop_count += 1
        if len(self._pending_drop_ids) < 100:
            self._pending_drop_ids.append(text)

    def _new_episode_buffer(self, start_frame: int) -> _EpisodeBuffer:
        directory = self._staging_root / "episode_buffer"
        if directory.exists():
            shutil.rmtree(directory)
        return _EpisodeBuffer(
            directory=directory,
            metadata=StagedFile(
                directory,
                "frames.buffer.jsonl",
                seam=self.seam,
                cancellation_token=self.cancellation_token,
            ),
            audio=StagedFile(
                directory,
                "audio.buffer.f32",
                seam=self.seam,
                cancellation_token=self.cancellation_token,
            ),
            start_frame=start_frame,
        )

    def _buffer_aligned_frame(
        self,
        payload: dict[str, Any],
        block: np.ndarray | None,
        *,
        dataset_index: int,
        is_reset: bool,
    ) -> None:
        if self._episode_buffer is None:
            self._episode_buffer = self._new_episode_buffer(dataset_index)
        buffer = self._episode_buffer
        sample_count = 0 if block is None else int(block.shape[1])
        metadata = {
            "audio_sample_count": sample_count,
            "dataset_frame_index": dataset_index,
            "frame": payload,
            "is_reset": is_reset,
        }
        line = json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n"
        buffer.metadata.append(line.encode("utf-8"))
        if block is not None and sample_count:
            buffer.audio.append(np.asarray(block, dtype="<f4").tobytes(order="C"))
        buffer.frame_count += 1
        if buffer.frame_count > self.shard_max_frames:
            raise AssertionError("aligned episode buffer exceeded shard_max_frames")

    def _handle_aligned_feed_boundaries(
        self, boundaries: Sequence[ShardBoundary]
    ) -> None:
        if not boundaries:
            return
        buffer = self._episode_buffer
        assert buffer is not None
        for boundary in boundaries:
            if boundary.start_frame == buffer.start_frame:
                self._pending_boundary = boundary
            else:
                self._promote_open_shard(boundary, flush_carry=False)

    def _append_unaligned_frame(
        self,
        payload: dict[str, Any],
        block: np.ndarray | None,
        *,
        dataset_index: int,
        is_reset: bool,
        boundaries: Sequence[ShardBoundary],
    ) -> None:
        if self._open_shard is None:
            self._open_shard = self._new_open_shard(
                shard_ordinal=len(self._published), start_frame=dataset_index
            )
        open_shard = self._open_shard
        start, desired_end = self._mix_and_append_audio(
            open_shard.wav, block, is_reset=is_reset
        )
        open_shard.frame_count += 1
        episode_value = episode_id(self._current_episode.ordinal)  # type: ignore[union-attr]
        if episode_value not in open_shard.episode_ids:
            open_shard.episode_ids.append(episode_value)
        if boundaries:
            if len(boundaries) != 1:
                raise AssertionError("unaligned planner emitted multiple boundaries")
            self._pending_boundary = boundaries[0]
            self._pending_record = _PendingRecord(
                frame_payload=payload,
                dataset_frame_index=dataset_index,
                episode_id_value=episode_value,
                audio_start=start,
                desired_audio_end=desired_end,
            )
        else:
            self._append_record_line(
                open_shard,
                payload,
                dataset_index=dataset_index,
                episode_id_value=episode_value,
                audio_start=start,
                audio_end=desired_end,
            )

    def _new_open_shard(self, *, shard_ordinal: int, start_frame: int) -> _OpenShard:
        staging_dir = self._staging_root / shard_id(shard_ordinal)
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        return _OpenShard(
            boundary_start=start_frame,
            shard_ordinal=shard_ordinal,
            staging_dir=staging_dir,
            jsonl=JsonlShardFile(
                staging_dir,
                seam=self.seam,
                cancellation_token=self.cancellation_token,
            ),
            wav=StreamingWavShardWriter(
                staging_dir,
                channels=self.channels,
                sample_rate_hz=self.sample_rate_hz,
                seam=self.seam,
                carry_state=self._carry,
                cancellation_token=self.cancellation_token,
            ),
        )

    def _mix_and_append_audio(
        self,
        writer: StreamingWavShardWriter,
        block: np.ndarray | None,
        *,
        is_reset: bool,
    ) -> tuple[int, int]:
        if is_reset:
            self._flush_carry_to_writer(writer)
        start = writer.sample_count
        if block is None or block.shape[1] == 0:
            return start, start
        hop = self.hop_sample_count
        chunk = np.zeros((self.channels, hop), dtype=np.float32)
        head = block[:, :hop]
        chunk[:, : head.shape[1]] = head
        carry = self._carry.pending_samples
        overlap = min(carry.shape[1], hop)
        if overlap:
            chunk[:, :overlap] += carry[:, :overlap]
        leftover = carry[:, overlap:]
        tail = block[:, hop:]
        pending_length = max(leftover.shape[1], tail.shape[1])
        pending = np.zeros((self.channels, pending_length), dtype=np.float32)
        if leftover.shape[1]:
            pending[:, : leftover.shape[1]] += leftover
        if tail.shape[1]:
            pending[:, : tail.shape[1]] += tail
        self._carry.replace(pending)
        writer.append_samples(chunk)
        attributed = min(int(block.shape[1]), self.window_sample_count)
        return start, start + attributed

    def _flush_carry_to_writer(self, writer: StreamingWavShardWriter) -> None:
        pending = self._carry.pending_samples
        if pending.shape[1]:
            writer.append_samples(pending)
            self._carry.replace(np.zeros((self.channels, 0), dtype=np.float32))

    def _append_record_line(
        self,
        open_shard: _OpenShard,
        payload: dict[str, Any],
        *,
        dataset_index: int,
        episode_id_value: str,
        audio_start: int,
        audio_end: int,
    ) -> None:
        record = build_dataset_frame_record(
            dataset_frame_index=dataset_index,
            episode_id_value=episode_id_value,
            audio_start_sample=audio_start,
            audio_end_sample=audio_end,
            frame=payload,
            session_root=self.session_root,
            location=f"dataset frame {dataset_index}",
        )
        open_shard.jsonl.append(serialize_dataset_frame_record(record))
        open_shard.max_audio_end = max(open_shard.max_audio_end, audio_end)

    def _resolve_pending_boundary(self, *, mid_episode: bool) -> None:
        boundary = self._pending_boundary
        if boundary is None:
            return
        if self.shard_episode_aligned:
            self._assemble_aligned_buffer(boundary, flush_tail=not mid_episode)
        else:
            open_shard = self._open_shard
            pending = self._pending_record
            assert open_shard is not None and pending is not None
            end = (
                min(pending.desired_audio_end, open_shard.wav.sample_count)
                if mid_episode
                else pending.desired_audio_end
            )
            self._append_record_line(
                open_shard,
                pending.frame_payload,
                dataset_index=pending.dataset_frame_index,
                episode_id_value=pending.episode_id_value,
                audio_start=pending.audio_start,
                audio_end=end,
            )
            self._pending_record = None
            self._promote_open_shard(boundary, flush_carry=not mid_episode)
        self._pending_boundary = None

    def _assemble_aligned_buffer(
        self, boundary: ShardBoundary, *, flush_tail: bool
    ) -> None:
        buffer = self._episode_buffer
        if buffer is None:
            raise AssertionError("aligned boundary has no episode buffer")
        buffer.metadata.flush_and_fsync()
        buffer.audio.flush_and_fsync()
        buffer.metadata.close()
        buffer.audio.close()
        if self._open_shard is None:
            self._open_shard = self._new_open_shard(
                shard_ordinal=boundary.shard_ordinal,
                start_frame=boundary.start_frame,
            )
        open_shard = self._open_shard
        with (
            self.seam.open(buffer.metadata.path, "rb") as metadata_stream,
            self.seam.open(buffer.audio.path, "rb") as audio_stream,
        ):
            for line_number in range(buffer.frame_count):
                line = metadata_stream.readline()
                if not line:
                    raise SessionRecorderError(
                        f"session {self.session_root} episode buffer: missing metadata "
                        f"line {line_number + 1}"
                    )
                item = json.loads(line)
                sample_count = int(item["audio_sample_count"])
                block = self._read_buffer_block(audio_stream, sample_count)
                start, desired_end = self._mix_and_append_audio(
                    open_shard.wav,
                    block,
                    is_reset=bool(item["is_reset"]),
                )
                open_shard.frame_count += 1
                episode_value = episode_id(self._current_episode.ordinal)  # type: ignore[union-attr]
                if episode_value not in open_shard.episode_ids:
                    open_shard.episode_ids.append(episode_value)
                end = (
                    desired_end
                    if flush_tail
                    else min(desired_end, open_shard.wav.sample_count)
                )
                self._append_record_line(
                    open_shard,
                    item["frame"],
                    dataset_index=int(item["dataset_frame_index"]),
                    episode_id_value=episode_value,
                    audio_start=start,
                    audio_end=end,
                )
            if metadata_stream.readline():
                raise SessionRecorderError(
                    f"session {self.session_root} episode buffer: extra metadata"
                )
            if audio_stream.read(1):
                raise SessionRecorderError(
                    f"session {self.session_root} episode buffer: extra audio bytes"
                )
        buffer.metadata.abort()
        buffer.audio.abort()
        if buffer.directory.exists():
            buffer.directory.rmdir()
        self._episode_buffer = None
        self._promote_open_shard(boundary, flush_carry=flush_tail)

    def _read_buffer_block(
        self, stream: BinaryIO, sample_count: int
    ) -> np.ndarray | None:
        if sample_count == 0:
            return None
        byte_count = self.channels * sample_count * 4
        chunks: list[bytes] = []
        remaining = byte_count
        while remaining:
            chunk = self.seam.read(stream, min(remaining, 1024 * 1024))
            if not chunk:
                raise SessionRecorderError(
                    f"session {self.session_root} episode buffer: truncated audio"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return np.frombuffer(b"".join(chunks), dtype="<f4").reshape(
            self.channels, sample_count
        )

    def end_episode(self) -> EpisodeRecord | None:
        """Close the current episode, flushing its overlap/reverb tail."""

        try:
            self._check_open()
            self.cancellation_token.check()
            episode = self._current_episode
            if episode is None:
                raise RuntimeError("no episode is open")
            if episode.frame_count == 0:
                raise ValueError(f"{episode_id(episode.ordinal)} has no written frames")
            boundaries = self._planner.end_episode(episode.ordinal)
            if self._pending_boundary is not None:
                self._resolve_pending_boundary(mid_episode=False)
                boundaries = tuple(
                    item
                    for item in boundaries
                    if item.shard_id != shard_id(len(self._published) - 1)
                )
            if self.shard_episode_aligned:
                buffer = self._episode_buffer
                for boundary in boundaries:
                    if (
                        buffer is not None
                        and boundary.start_frame == buffer.start_frame
                    ):
                        self._assemble_aligned_buffer(boundary, flush_tail=True)
                        buffer = None
                    else:
                        self._promote_open_shard(boundary, flush_carry=False)
                if self._episode_buffer is not None:
                    self._append_aligned_buffer_to_open()
            elif self._open_shard is not None:
                self._flush_carry_to_writer(self._open_shard.wav)
            episode.ended = True
            episode.end_frame = self._next_dataset_frame - 1
            self._current_episode = None
            self._write_state()
            return None
        except CancelledWrite:
            self._cancel_and_finalize()
            raise

    def _append_aligned_buffer_to_open(self) -> None:
        buffer = self._episode_buffer
        assert buffer is not None
        synthetic = ShardBoundary(
            shard_id=shard_id(len(self._published)),
            shard_ordinal=len(self._published),
            start_frame=(
                self._open_shard.boundary_start
                if self._open_shard is not None
                else buffer.start_frame
            ),
            frame_count=(
                (self._open_shard.frame_count if self._open_shard else 0)
                + buffer.frame_count
            ),
            episode_ids=(),
            split_groups=(),
            exclusive_oversized_episode=False,
        )
        # Assembly normally promotes. For a packed open shard we stream the
        # episode buffer into staging and deliberately retain that staging.
        buffer.metadata.flush_and_fsync()
        buffer.audio.flush_and_fsync()
        buffer.metadata.close()
        buffer.audio.close()
        if self._open_shard is None:
            self._open_shard = self._new_open_shard(
                shard_ordinal=synthetic.shard_ordinal,
                start_frame=buffer.start_frame,
            )
        open_shard = self._open_shard
        with (
            self.seam.open(buffer.metadata.path, "rb") as metadata_stream,
            self.seam.open(buffer.audio.path, "rb") as audio_stream,
        ):
            for _ in range(buffer.frame_count):
                item = json.loads(metadata_stream.readline())
                block = self._read_buffer_block(
                    audio_stream, int(item["audio_sample_count"])
                )
                start, end = self._mix_and_append_audio(
                    open_shard.wav, block, is_reset=bool(item["is_reset"])
                )
                open_shard.frame_count += 1
                episode_value = episode_id(self._current_episode.ordinal)  # type: ignore[union-attr]
                if episode_value not in open_shard.episode_ids:
                    open_shard.episode_ids.append(episode_value)
                self._append_record_line(
                    open_shard,
                    item["frame"],
                    dataset_index=int(item["dataset_frame_index"]),
                    episode_id_value=episode_value,
                    audio_start=start,
                    audio_end=end,
                )
            self._flush_carry_to_writer(open_shard.wav)
        buffer.metadata.abort()
        buffer.audio.abort()
        if buffer.directory.exists():
            buffer.directory.rmdir()
        self._episode_buffer = None

    def _promote_open_shard(
        self, boundary: ShardBoundary, *, flush_carry: bool
    ) -> VerifiedShard:
        open_shard = self._open_shard
        if open_shard is None:
            raise AssertionError(f"{boundary.shard_id} has no staged shard")
        if (
            open_shard.boundary_start != boundary.start_frame
            or open_shard.frame_count != boundary.frame_count
            or open_shard.shard_ordinal != boundary.shard_ordinal
        ):
            raise AssertionError(
                f"staged shard disagrees with planner boundary {boundary.shard_id}"
            )
        final_dir = self._shards_root / boundary.shard_id
        try:
            wav_result = open_shard.wav.finalize(flush_carry=flush_carry)
            open_shard.jsonl.flush_and_fsync()
            self._write_carry_checkpoint(boundary.start_frame + boundary.frame_count)
            frames_result = open_shard.jsonl.publish(final_dir / "frames.jsonl")
            open_shard.wav.publish(final_dir / "audio.wav")
            marker = {
                "marker_version": "ias.shard_completion.v1",
                "shard_id": boundary.shard_id,
                "start_frame": boundary.start_frame,
                "frame_count": boundary.frame_count,
                "episode_ids": list(open_shard.episode_ids),
                "files": [
                    frames_result,
                    {
                        "path": "audio.wav",
                        "sha256": wav_result["sha256"],
                        "bytes": wav_result["bytes"],
                    },
                ],
                "audio": {
                    "path": "audio.wav",
                    "container": "wav",
                    "subtype": "FLOAT",
                    "channels": self.channels,
                    "sample_rate_hz": self.sample_rate_hz,
                    "dtype": "float32",
                    "sample_count": wav_result["sample_count"],
                },
                "tail_samples": wav_result["sample_count"] - open_shard.max_audio_end,
                "dropped_frames": {
                    "count": self._pending_drop_count,
                    "producer_frame_ids": list(self._pending_drop_ids),
                },
                "writer_tool_version": __version__,
            }
            write_json_atomic(
                final_dir / "shard.complete.json",
                marker,
                seam=self.seam,
                cancellation_token=self.cancellation_token,
            )
            verified = verify_shard_completion(
                final_dir,
                max_overlap_samples=self.window_sample_count - self.hop_sample_count,
            )
        except BaseException as exc:
            self._open_shard = None
            self._remove_failed_shard(final_dir, open_shard)
            if isinstance(exc, CancelledWrite):
                raise
            raise SessionRecorderError(
                f"session {self.session_root} shard {boundary.shard_id}: "
                f"promotion failed at {final_dir}: {exc}"
            ) from exc
        self._published.append(verified)
        self._pending_drop_count = 0
        self._pending_drop_ids.clear()
        self._open_shard = None
        self._carry = CarryState(self._carry.take())
        self._prune_carry_checkpoints(boundary.start_frame + boundary.frame_count)
        if open_shard.staging_dir.exists():
            open_shard.staging_dir.rmdir()
        event = ShardPromotion(
            shard_id=boundary.shard_id,
            shard_ordinal=boundary.shard_ordinal,
            start_frame=boundary.start_frame,
            frame_count=boundary.frame_count,
            monotonic_timestamp_s=time.monotonic(),
        )
        if self._promotion_callback is not None:
            self._promotion_callback(event)
        return verified

    def _remove_failed_shard(self, final_dir: Path, open_shard: _OpenShard) -> None:
        with suppress(OSError):
            open_shard.jsonl.abort()
        with suppress(OSError):
            open_shard.wav.abort()
        if final_dir.exists():
            for child in sorted(final_dir.iterdir(), key=lambda path: path.name):
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            with suppress(OSError):
                final_dir.rmdir()

    def _write_carry_checkpoint(self, next_frame: int) -> None:
        checkpoint_dir = self._staging_root / "checkpoints"
        pending = np.ascontiguousarray(self._carry.pending_samples, dtype="<f4")
        data_name = f"carry_{next_frame:012d}.f32"
        metadata_name = f"carry_{next_frame:012d}.json"
        staged = StagedFile(
            checkpoint_dir,
            f".{data_name}.tmp",
            seam=self.seam,
            cancellation_token=self.cancellation_token,
        )
        try:
            staged.append(pending.tobytes(order="C"))
            publish_file(staged, checkpoint_dir / data_name)
            write_json_atomic(
                checkpoint_dir / metadata_name,
                {
                    "channels": self.channels,
                    "next_dataset_frame_index": next_frame,
                    "sample_count": pending.shape[1],
                },
                seam=self.seam,
                cancellation_token=self.cancellation_token,
            )
        except BaseException:
            staged.abort()
            raise

    def _prune_carry_checkpoints(self, keep_frame: int) -> None:
        checkpoint_dir = self._staging_root / "checkpoints"
        if not checkpoint_dir.exists():
            return
        keep = f"carry_{keep_frame:012d}"
        for path in sorted(checkpoint_dir.iterdir(), key=lambda item: item.name):
            if not path.name.startswith(keep):
                path.unlink(missing_ok=True)

    def finalize(self) -> AudioDatasetManifest:
        """Publish all remaining work and atomically write a complete manifest."""

        try:
            self._check_open()
            self.cancellation_token.check()
            if self._current_episode is not None:
                raise RuntimeError("end_episode() must be called before finalize()")
            for boundary in self._planner.finish():
                self._promote_open_shard(boundary, flush_carry=True)
            if not self._published:
                raise ValueError("a zero-frame session can only finalize incomplete")
            return self._finalize_manifest(completion_state="complete")
        except CancelledWrite:
            self._cancel_and_finalize()
            raise

    def finalize_incomplete(self) -> AudioDatasetManifest:
        """Abandon unpublished staging and atomically finalize published shards."""

        if self._closed:
            manifest_path = self.session_root / "manifest.json"
            if manifest_path.exists():
                from isaac_audio_sensors.core.io.manifests import read_dataset_manifest

                return read_dataset_manifest(manifest_path)
            raise RuntimeError("session recorder is closed")
        self._abandon_unpublished()
        return self._finalize_manifest(completion_state="incomplete")

    def _cancel_and_finalize(self) -> None:
        if self._handling_cancellation or self._closed:
            return
        self._handling_cancellation = True
        try:
            self._abandon_unpublished()
            self._finalize_manifest(completion_state="incomplete")
        finally:
            self._handling_cancellation = False

    def _abandon_unpublished(self) -> None:
        if self._episode_buffer is not None:
            try:
                self._episode_buffer.metadata.abort()
            finally:
                self._episode_buffer.audio.abort()
            self._episode_buffer = None
        if self._open_shard is not None:
            open_shard = self._open_shard
            self._remove_failed_shard(
                self._shards_root / shard_id(open_shard.shard_ordinal), open_shard
            )
            self._open_shard = None
        self._pending_boundary = None
        self._pending_record = None

    def _finalize_manifest(self, *, completion_state: str) -> AudioDatasetManifest:
        verified = tuple(
            verify_shard_completion(
                path,
                max_overlap_samples=self.window_sample_count - self.hop_sample_count,
            )
            for path in sorted(
                self._shards_root.iterdir() if self._shards_root.exists() else (),
                key=lambda item: item.name,
            )
            if path.is_dir() and (path / "shard.complete.json").exists()
        )
        verify_shard_tiling(verified)
        if completion_state == "complete" and len(verified) != len(self._published):
            raise SessionRecorderError(
                f"session {self.session_root}: published shard inventory changed"
            )
        episodes = self._episode_records(verified)
        shards = tuple(self._manifest_shard(item) for item in verified)
        manifest = AudioDatasetManifest(
            dataset_id=self.configuration["dataset_id"],
            creation_timestamp_ms=self.creation_timestamp_ms,
            creation=self.creation,
            license=self.license,
            source=self.source,
            runtime_profile="waveform_fidelity",
            device=self.device,
            coordinate_convention=COORDINATE_CONVENTION,
            coordinate_frames=self.coordinate_frames,
            time_base=self.time_base,
            sample_rate_hz=self.sample_rate_hz,
            channel_order=tuple(self.configuration["channel_order"]),
            units=dict(DATASET_MANIFEST_UNITS),
            dtype="float32",
            episodes=episodes,
            shards=shards,
            calibration_profile=None,
            configuration_sha256=configuration_sha256(self._configuration_bytes),
            split_grouping_key=self.configuration["split_grouping_key"],
            splits=(),
            completion_state=completion_state,
        )
        self._close_producer_index()
        if self._staging_root.exists():
            shutil.rmtree(self._staging_root)
        write_json_atomic(
            self.session_root / "manifest.json",
            manifest_to_dict(manifest),
            seam=self.seam,
            cancellation_token=None,
        )
        self._closed = True
        return manifest

    def _episode_records(
        self, verified: Sequence[VerifiedShard]
    ) -> tuple[EpisodeRecord, ...]:
        records = [record for item in verified for record in item.records]
        if not records:
            return ()
        metadata_by_id = {episode_id(item.ordinal): item for item in self._episodes}
        grouped: list[tuple[str, list[Any]]] = []
        for record in records:
            if not grouped or grouped[-1][0] != record.episode_id:
                grouped.append((record.episode_id, []))
            grouped[-1][1].append(record)
        result: list[EpisodeRecord] = []
        for ordinal, (episode_value, episode_records) in enumerate(grouped):
            if episode_value != episode_id(ordinal):
                raise SessionRecorderError(
                    f"session {self.session_root}: published episodes do not tile"
                )
            try:
                metadata = metadata_by_id[episode_value]
            except KeyError as exc:
                raise SessionRecorderError(
                    f"session {self.session_root}: missing state for {episode_value}"
                ) from exc
            start = episode_records[0].dataset_frame_index
            end = episode_records[-1].dataset_frame_index
            timestamps = tuple(
                int(item.frame["timestamp_ms"]) for item in episode_records
            )
            first_step = episode_records[0].frame.get("frame_index")
            last_step = episode_records[-1].frame.get("frame_index")
            if (
                isinstance(first_step, int)
                and not isinstance(first_step, bool)
                and isinstance(last_step, int)
                and not isinstance(last_step, bool)
                and last_step >= first_step
            ):
                start_step, end_step = first_step, last_step
            else:
                start_step, end_step = start, end
            by_index = {item.dataset_frame_index: item for item in episode_records}
            resets: list[ResetMarker] = []
            for frame_index in metadata.reset_frame_indices:
                record = by_index.get(frame_index)
                if record is None:
                    continue
                step = record.frame.get("frame_index")
                resets.append(
                    ResetMarker(
                        step_index=(
                            step
                            if isinstance(step, int) and not isinstance(step, bool)
                            else frame_index
                        ),
                        frame_index=frame_index,
                        timestamp_ms=int(record.frame["timestamp_ms"]),
                    )
                )
            result.append(
                EpisodeRecord(
                    episode_id=episode_value,
                    scene_id=metadata.scene_id,
                    environment_id=metadata.environment_id,
                    seed=metadata.seed,
                    start_step=start_step,
                    end_step=end_step,
                    start_frame=start,
                    end_frame=end,
                    timestamps_ms=timestamps,
                    split_group=metadata.split_group,
                    reset_markers=tuple(resets),
                )
            )
        return tuple(result)

    @staticmethod
    def _manifest_shard(verified: VerifiedShard) -> ShardRecord:
        marker = verified.marker
        return ShardRecord(
            shard_id=marker["shard_id"],
            episode_ids=tuple(marker["episode_ids"]),
            assets=tuple(
                AssetRecord(
                    asset_id=(
                        f"{marker['shard_id']}."
                        f"{'frames' if entry['path'] == 'frames.jsonl' else 'audio'}"
                    ),
                    path=f"shards/{marker['shard_id']}/{entry['path']}",
                    kind=(
                        "frame_trace_jsonl"
                        if entry["path"] == "frames.jsonl"
                        else "audio_wav"
                    ),
                    sha256=entry["sha256"],
                )
                for entry in marker["files"]
            ),
            completion_state="complete",
        )

    def _write_state(self) -> None:
        payload = {
            "state_version": _STATE_VERSION,
            "configuration_sha256": configuration_sha256(self._configuration_bytes),
            "creation_timestamp_ms": self.creation_timestamp_ms,
            "episodes": [item.state_dict() for item in self._episodes],
        }
        write_json_atomic(
            self._state_path,
            payload,
            seam=self.seam,
            cancellation_token=self.cancellation_token,
        )

    def _open_producer_index(self) -> None:
        database_path = self._staging_root / "producer_ids.sqlite3"
        self._producer_db = sqlite3.connect(database_path)
        self._producer_db.execute("PRAGMA cache_size = -1024")
        self._producer_db.execute("PRAGMA temp_store = FILE")
        self._producer_db.execute(
            "CREATE TABLE producer_ids ("
            "episode_ordinal INTEGER NOT NULL, "
            "producer_frame_id TEXT NOT NULL, "
            "PRIMARY KEY (episode_ordinal, producer_frame_id)) WITHOUT ROWID"
        )
        self._producer_db.commit()

    def _producer_id_exists(self, episode_ordinal: int, producer_id: str) -> bool:
        if self._producer_db is None:
            raise RuntimeError("producer identity index is closed")
        row = self._producer_db.execute(
            "SELECT 1 FROM producer_ids "
            "WHERE episode_ordinal = ? AND producer_frame_id = ?",
            (episode_ordinal, producer_id),
        ).fetchone()
        return row is not None

    def _record_producer_id(self, episode_ordinal: int, producer_id: str) -> None:
        if self._producer_db is None:
            raise RuntimeError("producer identity index is closed")
        self._producer_db.execute(
            "INSERT INTO producer_ids (episode_ordinal, producer_frame_id) "
            "VALUES (?, ?)",
            (episode_ordinal, producer_id),
        )

    def _close_producer_index(self) -> None:
        if self._producer_db is not None:
            self._producer_db.rollback()
            self._producer_db.close()
            self._producer_db = None

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("session recorder is finalized")

    @classmethod
    def resume(
        cls,
        session_root: str | Path,
        configuration: Mapping[str, Any],
        *,
        creation: CreationProvenance,
        device: DeviceProvenance,
        license: str,
        source: str,
        coordinate_frames: Sequence[str],
        time_base: str,
        creation_timestamp_ms: int | None = None,
        seam: FilesystemSeam | None = None,
        cancellation_token: CancellationToken | None = None,
        promotion_callback: Callable[[ShardPromotion], None] | None = None,
    ) -> SessionRecorder:
        """Resume at the next published frame, replaying discarded producer input.

        The producer must replay every frame after ``next_dataset_frame_index``.
        Carry at the last published boundary is restored from the durable staging
        checkpoint written before that shard's marker.
        """

        root = Path(session_root)
        if (root / "manifest.json").exists():
            raise SessionRecorderError(f"session {root}: already finalized")
        state_path = root / "_staging/recorder_state.json"
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionRecorderError(
                f"session {root}: cannot read recorder resume state: {exc}"
            ) from exc
        return cls(
            root,
            configuration,
            creation=creation,
            device=device,
            license=license,
            source=source,
            coordinate_frames=coordinate_frames,
            time_base=time_base,
            creation_timestamp_ms=creation_timestamp_ms,
            seam=seam,
            cancellation_token=cancellation_token,
            promotion_callback=promotion_callback,
            _resume_payload=state_payload,
        )

    def _restore_session(self, state_payload: dict[str, Any]) -> None:
        if state_payload.get("state_version") != _STATE_VERSION:
            raise SessionRecorderError(
                f"session {self.session_root}: unsupported recorder state"
            )
        expected_hash = configuration_sha256(self._configuration_bytes)
        if state_payload.get("configuration_sha256") != expected_hash:
            raise SessionRecorderError(
                f"session {self.session_root}: resume configuration mismatch"
            )
        config_path = self.session_root / "config/session_config.json"
        if config_path.read_bytes() != self._configuration_bytes:
            raise SessionRecorderError(
                f"session {self.session_root}: on-disk configuration mismatch"
            )
        stored_timestamp = int(state_payload["creation_timestamp_ms"])
        if (
            self._creation_timestamp_explicit
            and self.creation_timestamp_ms != stored_timestamp
        ):
            raise SessionRecorderError(
                f"session {self.session_root}: creation timestamp mismatch"
            )
        self.creation_timestamp_ms = stored_timestamp

        state_episodes = {
            int(item["ordinal"]): item for item in state_payload.get("episodes", [])
        }
        verified = self._scan_published_for_resume()
        verify_shard_tiling(verified)
        committed_records = [record for item in verified for record in item.records]
        next_frame = sum(item.marker["frame_count"] for item in verified)
        self._next_dataset_frame = next_frame

        records_by_episode: dict[int, list[Any]] = {}
        for record in committed_records:
            ordinal = int(record.episode_id.rsplit("_", 1)[1])
            records_by_episode.setdefault(ordinal, []).append(record)
        committed_ordinals = sorted(records_by_episode)
        for ordinal in committed_ordinals:
            try:
                item = state_episodes[ordinal]
            except KeyError as exc:
                raise SessionRecorderError(
                    f"session {self.session_root}: missing resume state for "
                    f"{episode_id(ordinal)}"
                ) from exc
            episode_records = records_by_episode[ordinal]
            stored_end_frame = item.get("end_frame")
            stored_ended = bool(item.get("ended", False)) and (
                isinstance(stored_end_frame, int) and stored_end_frame < next_frame
            )
            later_episode_committed = ordinal != committed_ordinals[-1]
            episode = _EpisodeState(
                ordinal=ordinal,
                scene_id=str(item["scene_id"]),
                environment_id=str(item["environment_id"]),
                split_group=str(item["split_group"]),
                seed=int(item["seed"]),
                start_frame=episode_records[0].dataset_frame_index,
                frame_count=len(episode_records),
                last_timestamp_ms=int(episode_records[-1].frame["timestamp_ms"]),
                reset_frame_indices=[
                    int(value)
                    for value in item.get("reset_frame_indices", [])
                    if int(value) < next_frame
                ],
                ended=stored_ended or later_episode_committed,
                end_frame=(
                    int(stored_end_frame)
                    if stored_ended and isinstance(stored_end_frame, int)
                    else None
                ),
            )
            self._episodes.append(episode)

        for episode in self._episodes:
            for _record in records_by_episode[episode.ordinal]:
                self._planner.feed_frame(episode.ordinal, episode.split_group)
            if episode.ended:
                self._planner.end_episode(episode.ordinal)
        if self._episodes and not self._episodes[-1].ended:
            self._current_episode = self._episodes[-1]

        carry = self._read_carry_checkpoint(next_frame)
        self._carry.replace(carry)
        shutil.rmtree(self._staging_root)
        self._staging_root.mkdir(parents=True)
        self._open_producer_index()
        assert self._producer_db is not None
        self._producer_db.executemany(
            "INSERT INTO producer_ids (episode_ordinal, producer_frame_id) "
            "VALUES (?, ?)",
            (
                (
                    int(record.episode_id.rsplit("_", 1)[1]),
                    str(record.frame["frame_id"]),
                )
                for record in committed_records
            ),
        )
        self._published = list(verified)
        self._write_state()

    def _scan_published_for_resume(self) -> tuple[VerifiedShard, ...]:
        verified: list[VerifiedShard] = []
        if not self._shards_root.exists():
            self._shards_root.mkdir(parents=True)
        for path in sorted(self._shards_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                raise SessionRecorderError(
                    f"session {self.session_root}: non-directory under shards: {path}"
                )
            marker = path / "shard.complete.json"
            if not marker.exists():
                shutil.rmtree(path)
                continue
            verified.append(
                verify_shard_completion(
                    path,
                    max_overlap_samples=self.window_sample_count
                    - self.hop_sample_count,
                )
            )
        return tuple(verified)

    def _read_carry_checkpoint(self, next_frame: int) -> np.ndarray:
        checkpoint_dir = self._staging_root / "checkpoints"
        metadata_path = checkpoint_dir / f"carry_{next_frame:012d}.json"
        data_path = checkpoint_dir / f"carry_{next_frame:012d}.f32"
        if not metadata_path.exists() or not data_path.exists():
            return np.zeros((self.channels, 0), dtype=np.float32)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("next_dataset_frame_index") != next_frame
            or metadata.get("channels") != self.channels
        ):
            raise SessionRecorderError(
                f"session {self.session_root}: invalid carry checkpoint"
            )
        sample_count = int(metadata["sample_count"])
        data = data_path.read_bytes()
        if len(data) != self.channels * sample_count * 4:
            raise SessionRecorderError(
                f"session {self.session_root}: truncated carry checkpoint"
            )
        return (
            np.frombuffer(data, dtype="<f4").reshape(self.channels, sample_count).copy()
        )


def resume(
    session_root: str | Path,
    configuration: Mapping[str, Any],
    **kwargs: Any,
) -> SessionRecorder:
    """Public convenience entry point for :meth:`SessionRecorder.resume`."""

    return SessionRecorder.resume(session_root, configuration, **kwargs)


__all__ = [
    "AppendFrameResult",
    "SessionRecorder",
    "SessionRecorderError",
    "ShardPromotion",
    "resume",
]
