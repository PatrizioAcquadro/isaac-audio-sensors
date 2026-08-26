"""Bounded-memory orchestration for one audio dataset session."""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.types import AudioSensorFrame
from isaac_audio_sensors.recording._atomic import (
    JsonlShardFile,
    StagedFile,
    publish_file,
    write_json_atomic,
)
from isaac_audio_sensors.recording._manifest_builder import build_manifest
from isaac_audio_sensors.recording._planning import (
    ShardBoundary,
    ShardPlanner,
    episode_id,
    episode_seed,
    shard_id,
)
from isaac_audio_sensors.recording._records import (
    DatasetLayoutError,
    build_dataset_frame_record,
    canonical_configuration_bytes,
    configuration_sha256,
    serialize_dataset_frame_record,
    validate_trace_projection,
)
from isaac_audio_sensors.recording._recovery import RecoveryStore
from isaac_audio_sensors.recording._shards import (
    verify_shard_completion,
    verify_shard_tiling,
)
from isaac_audio_sensors.recording._time_gaps import (
    TimeGapCursor,
    TimeGapPlan,
    advance_time_gap_cursor,
)
from isaac_audio_sensors.recording._time_gaps import (
    plan_time_gap as compute_time_gap_plan,
)
from isaac_audio_sensors.recording._writer import (
    CarryState,
    StreamingWavShardWriter,
)
from isaac_audio_sensors.recording.manifest import (
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ResetMarker,
)
from isaac_audio_sensors.recording.serialization import manifest_to_dict

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
    timestamps_ms: list[int] = field(default_factory=list)
    first_producer_step: int | None = None
    last_producer_step: int | None = None
    reset_markers: list[ResetMarker] = field(default_factory=list)
    published_frame_count: int = 0
    published_last_step: int | None = None
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
            "frame_count": self.frame_count,
            "last_timestamp_ms": self.last_timestamp_ms,
            "timestamps_ms": list(self.timestamps_ms),
            "first_producer_step": self.first_producer_step,
            "last_producer_step": self.last_producer_step,
            "reset_markers": [
                {
                    "step_index": marker.step_index,
                    "frame_index": marker.frame_index,
                    "timestamp_ms": marker.timestamp_ms,
                }
                for marker in self.reset_markers
            ],
            "published_frame_count": self.published_frame_count,
            "published_last_step": self.published_last_step,
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


_TIME_GAP_COUNTER_NAMES = (
    "gap_event_count",
    "inserted_silence_samples",
    "absorbed_drift_count",
    "absorbed_drift_samples_signed",
)


class SessionRecorder:
    """Record and atomically publish one waveform-fidelity session."""

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
        _resume_payload: dict[str, Any] | None = None,
        _recover_finalization: bool = False,
    ) -> None:
        self.session_root = Path(session_root)
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
        self._configuration_bytes = canonical_configuration_bytes(configuration)
        self.configuration: dict[str, Any] = json.loads(self._configuration_bytes)
        self._validate_configuration()

        self._staging_root = self.session_root / "_staging"
        self._shards_root = self.session_root / "shards"
        self._recovery_store = RecoveryStore(self._staging_root)
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
        self._published: list[dict[str, Any]] = []
        self._closed = False
        self._pending_finalization_state: str | None = None
        self._time_gap_cursor = TimeGapCursor()
        self._planned_session_audio_samples = 0
        self._time_gap_counters = {name: 0 for name in _TIME_GAP_COUNTER_NAMES}

        if _resume_payload is None:
            self._start_new_session()
        elif _recover_finalization:
            self._restore_finalization(_resume_payload)
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
    def preserve_time_gaps(self) -> bool:
        """Whether sample-gap preservation is active."""

        return bool(self.configuration.get("preserve_time_gaps", False))

    @property
    def time_gap_summary(self) -> dict[str, int]:
        """Return cumulative sample-gap counters."""

        return dict(self._time_gap_counters)

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
        preserve = self.configuration.get("preserve_time_gaps", False)
        if type(preserve) is not bool:
            raise ValueError("configuration.preserve_time_gaps must be a bool")
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
        self.session_root.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._shards_root.mkdir(parents=True, exist_ok=True)
        self._recovery_store.open_producer_index()
        staged = StagedFile(
            self._staging_root / "config",
            "session_config.json",
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

        self._check_open()
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
        if type(chosen_seed) is not int or chosen_seed < 0:
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
        if self.preserve_time_gaps:
            self._time_gap_cursor = TimeGapCursor()
        self._write_state()
        return episode_value

    def append_frame(
        self,
        frame: AudioSensorFrame,
        audio_block: np.ndarray | None,
        *,
        is_reset: bool = False,
    ) -> AppendFrameResult:
        """Append one typed frame; invalid payloads are accounted as drops."""

        if not isinstance(frame, AudioSensorFrame):
            raise TypeError("frame must be an AudioSensorFrame")
        self._check_open()
        if self._current_episode is None:
            raise RuntimeError("begin_episode() must be called first")
        timestamp_ms = frame.timestamp_ms
        gap_plan: TimeGapPlan | None = None
        if self.preserve_time_gaps:
            payload, block, gap_plan, reason = self._validated_gap_append_inputs(
                frame, audio_block, timestamp_ms, is_reset
            )
        else:
            payload, block, reason = self._validated_append_inputs(
                frame, audio_block, timestamp_ms, is_reset
            )
        if reason is not None:
            self._record_drop(frame)
            return AppendFrameResult(False, None, reason)
        assert payload is not None
        if gap_plan is not None:
            diagnostics = dict(payload["diagnostics"])
            recording = dict(diagnostics.get("recording", {}))
            if "time_gap" in recording:
                self._record_drop(frame)
                return AppendFrameResult(
                    False, None, "frame contains reserved recording.time_gap"
                )
            recording["time_gap"] = gap_plan.diagnostic()
            diagnostics["recording"] = recording
            payload["diagnostics"] = diagnostics
        if self._pending_boundary is not None:
            self._resolve_pending_boundary(mid_episode=True)

        dataset_index = self._next_dataset_frame
        producer_step = payload.get("frame_index")
        if type(producer_step) is not int:
            producer_step = None
        episode = self._current_episode
        episode.timestamps_ms.append(timestamp_ms)
        if episode.frame_count == 0:
            episode.first_producer_step = producer_step
        episode.last_producer_step = producer_step
        if is_reset:
            episode.reset_markers.append(
                ResetMarker(
                    step_index=producer_step
                    if producer_step is not None
                    else dataset_index,
                    frame_index=dataset_index,
                    timestamp_ms=timestamp_ms,
                )
            )
        boundaries = self._planner.feed_frame(episode.ordinal, episode.split_group)
        self._next_dataset_frame += 1
        episode.frame_count += 1
        episode.last_timestamp_ms = timestamp_ms
        self._recovery_store.record_producer_id(
            episode.ordinal, str(payload["frame_id"])
        )
        if gap_plan is not None:
            self._commit_time_gap_plan(gap_plan, timestamp_ms=timestamp_ms)

        gap_samples = 0 if gap_plan is None else gap_plan.inserted_silence_samples
        if self.shard_episode_aligned:
            self._buffer_aligned_frame(
                payload,
                block,
                dataset_index=dataset_index,
                is_reset=is_reset,
                gap_samples=gap_samples,
            )
            self._handle_aligned_feed_boundaries(boundaries)
        else:
            self._append_unaligned_frame(
                payload,
                block,
                dataset_index=dataset_index,
                is_reset=is_reset,
                boundaries=boundaries,
                gap_samples=gap_samples,
            )
        return AppendFrameResult(True, dataset_index)

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
            if self._recovery_store.contains_producer_id(
                episode.ordinal, str(payload["frame_id"])
            ):
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

    def _validated_gap_append_inputs(
        self,
        frame: AudioSensorFrame | dict[str, Any],
        audio_block: np.ndarray | None,
        timestamp_ms: int,
        is_reset: bool,
    ) -> tuple[
        dict[str, Any] | None,
        np.ndarray | None,
        TimeGapPlan | None,
        str | None,
    ]:
        payload, block, reason = self._validated_append_inputs(
            frame, audio_block, timestamp_ms, is_reset
        )
        if reason is not None:
            if "timestamp_ms is non-monotonic" in reason:
                reason = "non-monotonic timestamp within the episode"
            return None, None, None, reason
        assert payload is not None
        try:
            if type(timestamp_ms) is not int or timestamp_ms < 0:
                raise ValueError("timestamp_ms must be a non-negative integer")
            if block is None or block.shape != (
                self.channels,
                self.window_sample_count,
            ):
                raise ValueError(
                    "audio_block must be finite float32 with exact shape "
                    f"({self.channels}, {self.window_sample_count})"
                )
            if 4 * self.channels > 1_048_576:
                raise ValueError(
                    "audio_block channel row exceeds the 1 MiB gap allocation cap"
                )
            plan = self._compute_time_gap_plan(payload, timestamp_ms)
            return payload, block, plan, None
        except (KeyError, TypeError, ValueError) as exc:
            return None, None, None, str(exc)

    def _compute_time_gap_plan(
        self,
        payload: Mapping[str, Any],
        timestamp_ms: object,
    ) -> TimeGapPlan:
        return compute_time_gap_plan(
            self._time_gap_cursor,
            placement_sequence=self._next_dataset_frame,
            start_time_s=payload.get("start_time_s"),
            end_time_s=payload.get("end_time_s"),
            timestamp_ms=timestamp_ms,  # type: ignore[arg-type]
            sample_rate_hz=self.sample_rate_hz,
            window_sample_count=self.window_sample_count,
            hop_sample_count=self.hop_sample_count,
            session_audio_start_sample=self._planned_session_audio_samples,
        )

    def _commit_time_gap_plan(
        self,
        plan: TimeGapPlan,
        *,
        timestamp_ms: int,
    ) -> None:
        self._time_gap_cursor = advance_time_gap_cursor(
            self._time_gap_cursor,
            plan,
            timestamp_ms=timestamp_ms,
            hop_sample_count=self.hop_sample_count,
        )
        inserted = plan.inserted_silence_samples
        absorbed = plan.absorbed_drift_samples
        if inserted:
            self._time_gap_counters["gap_event_count"] += 1
            self._time_gap_counters["inserted_silence_samples"] += inserted
        if absorbed:
            self._time_gap_counters["absorbed_drift_count"] += 1
            self._time_gap_counters["absorbed_drift_samples_signed"] += absorbed
        self._planned_session_audio_samples += inserted + self.hop_sample_count

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
            ),
            audio=StagedFile(
                directory,
                "audio.buffer.f32",
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
        gap_samples: int,
    ) -> None:
        if self._episode_buffer is None:
            self._episode_buffer = self._new_episode_buffer(dataset_index)
        buffer = self._episode_buffer
        sample_count = 0 if block is None else int(block.shape[1])
        metadata = {
            "audio_sample_count": sample_count,
            "dataset_frame_index": dataset_index,
            "frame": payload,
            "gap_samples": gap_samples,
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
        gap_samples: int,
    ) -> None:
        if self._open_shard is None:
            self._open_shard = self._new_open_shard(
                shard_ordinal=len(self._published), start_frame=dataset_index
            )
        open_shard = self._open_shard
        if gap_samples:
            self._stream_time_gap(open_shard.wav, gap_samples)
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
            ),
            wav=StreamingWavShardWriter(
                staging_dir,
                channels=self.channels,
                sample_rate_hz=self.sample_rate_hz,
                carry_state=self._carry,
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

    def _stream_time_gap(
        self,
        writer: StreamingWavShardWriter,
        sample_count: int,
    ) -> None:
        """Advance zero acoustic input and carry in bounded float32 blocks."""

        if sample_count <= 0:
            return
        block_cap = min(
            65_536,
            max(1, 1_048_576 // (4 * self.channels)),
        )
        remaining = sample_count
        while remaining:
            count = min(remaining, block_cap)
            chunk = np.zeros((self.channels, count), dtype=np.float32)
            carry = self._carry.pending_samples
            overlap = min(carry.shape[1], count)
            if overlap:
                chunk[:, :overlap] += carry[:, :overlap]
            self._carry.replace(carry[:, overlap:])
            writer.append_samples(chunk)
            remaining -= count

    def _flush_carry_to_writer(self, writer: StreamingWavShardWriter) -> None:
        pending = self._carry.pending_samples
        if pending.shape[1]:
            writer.append_samples(pending)
            if self.preserve_time_gaps:
                self._planned_session_audio_samples += int(pending.shape[1])
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
            buffer.metadata.path.open("rb") as metadata_stream,
            buffer.audio.path.open("rb") as audio_stream,
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
                gap_samples = int(item.get("gap_samples", 0))
                if gap_samples:
                    self._stream_time_gap(open_shard.wav, gap_samples)
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
            chunk = stream.read(min(remaining, 1024 * 1024))
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

        self._check_open()
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
                if buffer is not None and boundary.start_frame == buffer.start_frame:
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
        if self.preserve_time_gaps:
            self._time_gap_cursor = TimeGapCursor()
        self._write_state()
        return None

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
        # Retain staging when packing this episode into an open shard.
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
            buffer.metadata.path.open("rb") as metadata_stream,
            buffer.audio.path.open("rb") as audio_stream,
        ):
            for _ in range(buffer.frame_count):
                item = json.loads(metadata_stream.readline())
                block = self._read_buffer_block(
                    audio_stream, int(item["audio_sample_count"])
                )
                gap_samples = int(item.get("gap_samples", 0))
                if gap_samples:
                    self._stream_time_gap(open_shard.wav, gap_samples)
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
    ) -> dict[str, Any]:
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
            # Persist episode state before the marker makes this boundary durable.
            self._write_state()
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
            )
            verified = verify_shard_completion(
                final_dir,
                max_overlap_samples=self.window_sample_count - self.hop_sample_count,
            )
        except BaseException as exc:
            self._open_shard = None
            self._remove_failed_shard(final_dir, open_shard)
            raise SessionRecorderError(
                f"session {self.session_root} shard {boundary.shard_id}: "
                f"promotion failed at {final_dir}: {exc}"
            ) from exc
        marker_payload = verified.marker
        self._published.append(marker_payload)
        self._mark_published_boundary(boundary)
        self._pending_drop_count = 0
        self._pending_drop_ids.clear()
        self._open_shard = None
        self._carry = CarryState(self._carry.take())
        self._prune_carry_checkpoints(boundary.start_frame + boundary.frame_count)
        if open_shard.staging_dir.exists():
            open_shard.staging_dir.rmdir()
        return marker_payload

    def _mark_published_boundary(self, boundary: ShardBoundary) -> None:
        published_end = boundary.start_frame + boundary.frame_count
        for episode in self._episodes:
            count = min(
                episode.frame_count,
                max(0, published_end - episode.start_frame),
            )
            if count <= episode.published_frame_count:
                continue
            if count != episode.frame_count:
                raise AssertionError(
                    "published boundary step is unavailable for a staged frame"
                )
            episode.published_frame_count = count
            episode.published_last_step = episode.last_producer_step

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
        )
        try:
            staged.append(pending.tobytes(order="C"))
            publish_file(staged, checkpoint_dir / data_name)
            metadata: dict[str, Any] = {
                "channels": self.channels,
                "next_dataset_frame_index": next_frame,
                "sample_count": pending.shape[1],
            }
            if self.preserve_time_gaps:
                metadata["time_gap_state"] = self._time_gap_state_dict()
            write_json_atomic(
                checkpoint_dir / metadata_name,
                metadata,
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

        self._check_open()
        if self._current_episode is not None:
            raise RuntimeError("end_episode() must be called before finalize()")
        for boundary in self._planner.finish():
            self._promote_open_shard(boundary, flush_carry=True)
        if not self._published:
            raise ValueError("a zero-frame session can only finalize incomplete")
        return self._finalize_manifest(completion_state="complete")

    def cancel(self) -> AudioDatasetManifest:
        """Abandon unpublished staging and atomically finalize published shards."""

        if self._closed:
            manifest_path = self.session_root / "manifest.json"
            if manifest_path.exists():
                from isaac_audio_sensors.recording.serialization import (
                    read_dataset_manifest,
                )

                return read_dataset_manifest(manifest_path)
            raise RuntimeError("session recorder is closed")
        self._abandon_unpublished()
        return self._finalize_manifest(completion_state="incomplete")

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
        if completion_state not in {"complete", "incomplete"}:
            raise ValueError("completion_state must be 'complete' or 'incomplete'")
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
        markers = tuple(item.marker for item in verified)
        episodes = self._episode_records(markers)
        manifest = build_manifest(
            configuration=self.configuration,
            configuration_sha256=configuration_sha256(self._configuration_bytes),
            creation_timestamp_ms=self.creation_timestamp_ms,
            creation=self.creation,
            device=self.device,
            license=self.license,
            source=self.source,
            coordinate_frames=self.coordinate_frames,
            time_base=self.time_base,
            episodes=episodes,
            markers=markers,
            completion_state=completion_state,
        )
        # Keep recovery state until manifest replacement and directory fsync finish.
        self._write_state(finalization_state=completion_state)
        self._recovery_store.close_producer_index()
        write_json_atomic(
            self.session_root / "manifest.json",
            manifest_to_dict(manifest),
        )
        if self._staging_root.exists():
            shutil.rmtree(self._staging_root)
        self._pending_finalization_state = None
        self._closed = True
        return manifest

    def _episode_records(
        self, markers: Sequence[Mapping[str, Any]]
    ) -> tuple[EpisodeRecord, ...]:
        if not markers:
            return ()
        metadata_by_id = {episode_id(item.ordinal): item for item in self._episodes}
        published_episode_ids: list[str] = []
        for marker in markers:
            for episode_value in marker["episode_ids"]:
                if (
                    not published_episode_ids
                    or published_episode_ids[-1] != episode_value
                ):
                    published_episode_ids.append(episode_value)
        published_frame_count = sum(marker["frame_count"] for marker in markers)
        result: list[EpisodeRecord] = []
        for ordinal, episode_value in enumerate(published_episode_ids):
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
            start = metadata.start_frame
            end = (
                metadata_by_id[published_episode_ids[ordinal + 1]].start_frame - 1
                if ordinal + 1 < len(published_episode_ids)
                else published_frame_count - 1
            )
            frame_count = end - start + 1
            if frame_count <= 0 or len(metadata.timestamps_ms) < frame_count:
                raise SessionRecorderError(
                    f"session {self.session_root}: incomplete state for {episode_value}"
                )
            timestamps = tuple(metadata.timestamps_ms[:frame_count])
            first_step = metadata.first_producer_step
            last_step = (
                metadata.published_last_step
                if metadata.published_frame_count == frame_count
                else (
                    metadata.last_producer_step
                    if metadata.frame_count == frame_count
                    else None
                )
            )
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
            resets = tuple(
                marker
                for marker in metadata.reset_markers
                if start <= marker.frame_index <= end
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
                    reset_markers=resets,
                )
            )
        return tuple(result)

    def _write_state(self, *, finalization_state: str | None = None) -> None:
        if finalization_state not in {None, "complete", "incomplete"}:
            raise ValueError(
                "finalization_state must be None, 'complete', or 'incomplete'"
            )
        payload = {
            "state_version": _STATE_VERSION,
            "configuration_sha256": configuration_sha256(self._configuration_bytes),
            "creation_timestamp_ms": self.creation_timestamp_ms,
            "finalization_state": finalization_state,
            "recovery_metadata": {
                "creation": asdict(self.creation),
                "device": asdict(self.device),
                "license": self.license,
                "source": self.source,
                "coordinate_frames": list(self.coordinate_frames),
                "time_base": self.time_base,
            },
            "episodes": [item.state_dict() for item in self._episodes],
        }
        if self.preserve_time_gaps:
            payload["time_gap_state"] = self._time_gap_state_dict()
        self._recovery_store.write_state(payload)
        self._pending_finalization_state = finalization_state

    def _time_gap_state_dict(self) -> dict[str, Any]:
        return {
            "cursor": self._time_gap_cursor.to_dict(),
            "planned_session_audio_samples": self._planned_session_audio_samples,
            "summary": dict(self._time_gap_counters),
        }

    def _restore_time_gap_state(self, value: object) -> None:
        if not isinstance(value, dict):
            raise SessionRecorderError(
                f"session {self.session_root}: invalid time-gap checkpoint"
            )
        try:
            cursor = TimeGapCursor.from_dict(value.get("cursor"))
            planned = value.get("planned_session_audio_samples")
            summary = value.get("summary")
            if type(planned) is not int or planned < 0:
                raise ValueError("planned_session_audio_samples must be non-negative")
            if not isinstance(summary, dict):
                raise ValueError("summary must be an object")
            counters = {name: summary.get(name) for name in _TIME_GAP_COUNTER_NAMES}
            if any(type(item) is not int for item in counters.values()):
                raise ValueError("time-gap summary counters must be integers")
            if any(counters[name] < 0 for name in _TIME_GAP_COUNTER_NAMES[:-1]):
                raise ValueError("time-gap summary counts must be non-negative")
        except (TypeError, ValueError) as exc:
            raise SessionRecorderError(
                f"session {self.session_root}: invalid time-gap checkpoint: {exc}"
            ) from exc
        self._time_gap_cursor = cursor
        self._planned_session_audio_samples = planned
        self._time_gap_counters = counters

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
    ) -> SessionRecorder:
        """Resume at the next published frame, replaying discarded producer input.

        The producer must replay every frame after ``next_dataset_frame_index``.
        Carry at the last published boundary is restored from the durable staging
        checkpoint written before that shard's marker.
        """

        root = Path(session_root)
        if (root / "manifest.json").exists():
            raise SessionRecorderError(f"session {root}: already finalized")
        try:
            state_payload = RecoveryStore(root / "_staging").read_state()
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
            _resume_payload=state_payload,
        )

    @classmethod
    def recover_finalization(
        cls,
        session_root: str | Path,
    ) -> AudioDatasetManifest:
        """Retry an interrupted manifest finalization from durable state.

        This path is intentionally separate from :meth:`resume`: once a
        finalization intent is durable, no producer input may be appended.
        The manifest may already be visible when its parent-directory fsync
        failed; recovery rewrites and fsyncs it before removing ``_staging``.
        """

        root = Path(session_root)
        try:
            state_payload = RecoveryStore(root / "_staging").read_state()
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionRecorderError(
                f"session {root}: cannot read finalization recovery state: {exc}"
            ) from exc
        try:
            configuration = json.loads(
                (root / "config/session_config.json").read_text(encoding="utf-8")
            )
            recovery = state_payload["recovery_metadata"]
            creation = CreationProvenance(**recovery["creation"])
            device = DeviceProvenance(**recovery["device"])
            license_text = str(recovery["license"])
            source = str(recovery["source"])
            coordinate_frames = tuple(recovery["coordinate_frames"])
            time_base = str(recovery["time_base"])
            creation_timestamp_ms = int(state_payload["creation_timestamp_ms"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SessionRecorderError(
                f"session {root}: invalid durable finalization recovery state: {exc}"
            ) from exc
        recorder = cls(
            root,
            configuration,
            creation=creation,
            device=device,
            license=license_text,
            source=source,
            coordinate_frames=coordinate_frames,
            time_base=time_base,
            creation_timestamp_ms=creation_timestamp_ms,
            _resume_payload=state_payload,
            _recover_finalization=True,
        )
        state = recorder._pending_finalization_state
        if state is None:
            raise SessionRecorderError(
                f"session {root}: no durable finalization intent is present"
            )
        return recorder._finalize_manifest(completion_state=state)

    def _validate_restore_state(self, state_payload: Mapping[str, Any]) -> None:
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

    @staticmethod
    def _episode_from_state_payload(item: Mapping[str, Any]) -> _EpisodeState:
        episode = _EpisodeState(
            ordinal=int(item["ordinal"]),
            scene_id=str(item["scene_id"]),
            environment_id=str(item["environment_id"]),
            split_group=str(item["split_group"]),
            seed=int(item["seed"]),
            start_frame=int(item["start_frame"]),
            frame_count=int(item.get("frame_count", 0)),
            last_timestamp_ms=(
                None
                if item.get("last_timestamp_ms") is None
                else int(item["last_timestamp_ms"])
            ),
            timestamps_ms=[int(value) for value in item.get("timestamps_ms", ())],
            first_producer_step=(
                None
                if item.get("first_producer_step") is None
                else int(item["first_producer_step"])
            ),
            last_producer_step=(
                None
                if item.get("last_producer_step") is None
                else int(item["last_producer_step"])
            ),
            reset_markers=[
                ResetMarker(
                    step_index=int(marker["step_index"]),
                    frame_index=int(marker["frame_index"]),
                    timestamp_ms=int(marker["timestamp_ms"]),
                )
                for marker in item.get("reset_markers", ())
            ],
            published_frame_count=int(item.get("published_frame_count", 0)),
            published_last_step=(
                None
                if item.get("published_last_step") is None
                else int(item["published_last_step"])
            ),
            ended=bool(item.get("ended", False)),
            end_frame=(
                None if item.get("end_frame") is None else int(item["end_frame"])
            ),
        )
        return episode

    def _restore_finalization(self, state_payload: dict[str, Any]) -> None:
        self._validate_restore_state(state_payload)
        state = state_payload.get("finalization_state")
        if state not in {"complete", "incomplete"}:
            raise SessionRecorderError(
                f"session {self.session_root}: no durable finalization intent"
            )
        self._episodes = [
            self._episode_from_state_payload(item)
            for item in state_payload.get("episodes", ())
        ]
        if self.preserve_time_gaps:
            self._restore_time_gap_state(state_payload.get("time_gap_state"))
        published = self._scan_published_for_resume()
        verify_shard_tiling(published)
        self._published = list(published)
        self._next_dataset_frame = sum(item["frame_count"] for item in published)
        self._pending_finalization_state = state

    def _restore_session(self, state_payload: dict[str, Any]) -> None:
        self._validate_restore_state(state_payload)
        if state_payload.get("finalization_state") is not None:
            raise SessionRecorderError(
                f"session {self.session_root}: finalization recovery is required"
            )

        state_episodes = {
            int(item["ordinal"]): item for item in state_payload.get("episodes", [])
        }
        published = self._scan_published_for_resume()
        verify_shard_tiling(published)
        next_frame = sum(item["frame_count"] for item in published)
        self._next_dataset_frame = next_frame

        committed_ids: list[str] = []
        for marker in published:
            for episode_value in marker["episode_ids"]:
                if not committed_ids or committed_ids[-1] != episode_value:
                    committed_ids.append(episode_value)
        committed_ordinals = [int(value.rsplit("_", 1)[1]) for value in committed_ids]
        reset_indices_by_ordinal: dict[int, set[int]] = {}
        for ordinal in committed_ordinals:
            try:
                item = state_episodes[ordinal]
            except KeyError as exc:
                raise SessionRecorderError(
                    f"session {self.session_root}: missing resume state for "
                    f"{episode_id(ordinal)}"
                ) from exc
            episode = _EpisodeState(
                ordinal=ordinal,
                scene_id=str(item["scene_id"]),
                environment_id=str(item["environment_id"]),
                split_group=str(item["split_group"]),
                seed=int(item["seed"]),
                start_frame=int(item["start_frame"]),
            )
            self._episodes.append(episode)
            reset_indices_by_ordinal[ordinal] = {
                int(value)
                for value in item.get("reset_frame_indices", [])
                if int(value) < next_frame
            } | {
                int(marker["frame_index"])
                for marker in item.get("reset_markers", [])
                if int(marker["frame_index"]) < next_frame
            }

        carry = self._read_carry_checkpoint(next_frame)
        self._carry.replace(carry)
        shutil.rmtree(self._staging_root)
        self._staging_root.mkdir(parents=True)
        self._recovery_store.open_producer_index()
        episodes_by_ordinal = {item.ordinal: item for item in self._episodes}
        for marker in published:
            frames_path = self._shards_root / marker["shard_id"] / "frames.jsonl"
            with frames_path.open("rb") as stream:
                for line in stream:
                    record = json.loads(line)
                    ordinal = int(record["episode_id"].rsplit("_", 1)[1])
                    episode = episodes_by_ordinal[ordinal]
                    frame = record["frame"]
                    dataset_index = int(record["dataset_frame_index"])
                    timestamp = int(frame["timestamp_ms"])
                    producer_step = frame.get("frame_index")
                    if not isinstance(producer_step, int) or isinstance(
                        producer_step, bool
                    ):
                        producer_step = None
                    if episode.frame_count == 0:
                        episode.first_producer_step = producer_step
                    episode.last_producer_step = producer_step
                    episode.timestamps_ms.append(timestamp)
                    episode.frame_count += 1
                    episode.last_timestamp_ms = timestamp
                    if dataset_index in reset_indices_by_ordinal[ordinal]:
                        episode.reset_markers.append(
                            ResetMarker(
                                step_index=(
                                    producer_step
                                    if producer_step is not None
                                    else dataset_index
                                ),
                                frame_index=dataset_index,
                                timestamp_ms=timestamp,
                            )
                        )
                    self._recovery_store.record_producer_id(
                        ordinal, str(frame["frame_id"])
                    )

        for episode in self._episodes:
            episode.published_frame_count = episode.frame_count
            episode.published_last_step = episode.last_producer_step
            stored = state_episodes[episode.ordinal]
            stored_end_frame = stored.get("end_frame")
            stored_ended = bool(stored.get("ended", False)) and (
                isinstance(stored_end_frame, int) and stored_end_frame < next_frame
            )
            later_episode_committed = episode.ordinal != committed_ordinals[-1]
            episode.ended = stored_ended or later_episode_committed
            episode.end_frame = (
                int(stored_end_frame)
                if stored_ended and isinstance(stored_end_frame, int)
                else None
            )
            for _ in range(episode.frame_count):
                self._planner.feed_frame(episode.ordinal, episode.split_group)
            if episode.ended:
                self._planner.end_episode(episode.ordinal)
        if self._episodes and not self._episodes[-1].ended:
            self._current_episode = self._episodes[-1]
        elif self.preserve_time_gaps and next_frame:
            self._restore_time_gap_state(state_payload.get("time_gap_state"))

        self._published = list(published)
        self._write_state()

    def _scan_published_for_resume(self) -> tuple[dict[str, Any], ...]:
        verified: list[dict[str, Any]] = []
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
                ).marker
            )
        return tuple(verified)

    def _read_carry_checkpoint(self, next_frame: int) -> np.ndarray:
        checkpoint_dir = self._staging_root / "checkpoints"
        metadata_path = checkpoint_dir / f"carry_{next_frame:012d}.json"
        data_path = checkpoint_dir / f"carry_{next_frame:012d}.f32"
        if not metadata_path.exists() or not data_path.exists():
            if self.preserve_time_gaps and next_frame:
                raise SessionRecorderError(
                    f"session {self.session_root}: missing time-gap carry checkpoint"
                )
            return np.zeros((self.channels, 0), dtype=np.float32)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("next_dataset_frame_index") != next_frame
            or metadata.get("channels") != self.channels
        ):
            raise SessionRecorderError(
                f"session {self.session_root}: invalid carry checkpoint"
            )
        if self.preserve_time_gaps:
            self._restore_time_gap_state(metadata.get("time_gap_state"))
        sample_count = int(metadata["sample_count"])
        data = data_path.read_bytes()
        if len(data) != self.channels * sample_count * 4:
            raise SessionRecorderError(
                f"session {self.session_root}: truncated carry checkpoint"
            )
        return (
            np.frombuffer(data, dtype="<f4").reshape(self.channels, sample_count).copy()
        )


__all__ = [
    "AppendFrameResult",
    "SessionRecorder",
    "SessionRecorderError",
]
