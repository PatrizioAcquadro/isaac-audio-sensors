"""Vectorized observation buffers for Isaac Lab audio sensors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from isaac_audio_sensors.core.constants import SECTOR_ORDER
from isaac_audio_sensors.core.doa.sector_mapping import bearing_deg_to_sector_name
from isaac_audio_sensors.core.types import AudioSensorFrame


@dataclass(slots=True, kw_only=True)
class AudioArraySensorData:
    """RL-oriented audio observation buffers.

    In Isaac Lab mode these fields are torch tensors on the sensor device. The
    tuple defaults keep the class importable without torch and preserve a small
    compatibility path for offline frame conversion.
    """

    event_presence: Any = field(default_factory=tuple)
    bearing_deg: Any = field(default_factory=tuple)
    confidence: Any = field(default_factory=tuple)
    sector_onehot: Any = field(default_factory=tuple)
    per_mic_rms: Any = field(default_factory=tuple)
    ambiguity_mask: Any = field(default_factory=tuple)
    frame_ids: tuple[str | None, ...] = field(default_factory=tuple)
    frame_names: tuple[str | None, ...] = field(default_factory=tuple)
    source_ids: tuple[tuple[str | None, ...], ...] = field(default_factory=tuple)
    class_labels: tuple[tuple[str | None, ...], ...] = field(default_factory=tuple)
    latest_frames: tuple[AudioSensorFrame | None, ...] = field(default_factory=tuple)
    last_update_time_s: Any = field(default_factory=tuple)
    microphone_ids: tuple[str, ...] = field(default_factory=tuple)
    sector_order: tuple[str, ...] = SECTOR_ORDER
    waveform_paths: tuple[tuple[str, ...], ...] = field(default_factory=tuple)

    @property
    def bearing_confidence(self) -> Any:
        """Backward-compatible alias for the confidence tensor."""

        return self.confidence

    @property
    def class_label(self) -> tuple[str | None, ...]:
        """Backward-compatible one-env class label view."""

        if not self.class_labels:
            return ()
        return self.class_labels[0]

    @classmethod
    def empty(cls) -> AudioArraySensorData:
        """Return an empty observation buffer without importing torch."""

        return cls()

    @classmethod
    def allocate(
        cls,
        *,
        num_envs: int,
        max_events: int,
        num_mics: int,
        device: str,
        sector_order: tuple[str, ...] = SECTOR_ORDER,
    ) -> AudioArraySensorData:
        """Allocate tensor buffers with deterministic padding values."""

        torch = _require_torch()
        data = cls(
            event_presence=torch.zeros(
                (num_envs, max_events),
                dtype=torch.bool,
                device=device,
            ),
            bearing_deg=torch.full(
                (num_envs, max_events),
                float("nan"),
                dtype=torch.float32,
                device=device,
            ),
            confidence=torch.zeros(
                (num_envs, max_events),
                dtype=torch.float32,
                device=device,
            ),
            sector_onehot=torch.zeros(
                (num_envs, max_events, len(sector_order)),
                dtype=torch.float32,
                device=device,
            ),
            per_mic_rms=torch.zeros(
                (num_envs, max_events, num_mics),
                dtype=torch.float32,
                device=device,
            ),
            ambiguity_mask=torch.zeros(
                (num_envs, max_events),
                dtype=torch.bool,
                device=device,
            ),
            frame_ids=tuple(None for _ in range(num_envs)),
            frame_names=tuple(None for _ in range(num_envs)),
            source_ids=tuple(
                tuple(None for _ in range(max_events)) for _ in range(num_envs)
            ),
            class_labels=tuple(
                tuple(None for _ in range(max_events)) for _ in range(num_envs)
            ),
            latest_frames=tuple(None for _ in range(num_envs)),
            last_update_time_s=torch.full(
                (num_envs,),
                float("nan"),
                dtype=torch.float32,
                device=device,
            ),
            microphone_ids=tuple("" for _ in range(num_mics)),
            sector_order=sector_order,
            waveform_paths=tuple(() for _ in range(num_envs)),
        )
        data.reset_envs(range(num_envs))
        return data

    @classmethod
    def from_frame(
        cls,
        frame: AudioSensorFrame,
        *,
        max_events: int | None = None,
        microphone_ids: Sequence[str] | None = None,
        device: str | None = None,
        sector_order: tuple[str, ...] = SECTOR_ORDER,
    ) -> AudioArraySensorData:
        """Convert one frame into either compatibility tuples or tensors."""

        if max_events is None or microphone_ids is None or device is None:
            return cls(
                event_presence=tuple(True for _ in frame.detections),
                bearing_deg=tuple(
                    detection.doa.estimated_bearing_deg
                    for detection in frame.detections
                ),
                confidence=tuple(
                    detection.doa.bearing_confidence for detection in frame.detections
                ),
                ambiguity_mask=tuple(
                    detection.doa.ambiguity_class is not None
                    for detection in frame.detections
                ),
                per_mic_rms=tuple(
                    detection.per_mic_rms for detection in frame.detections
                ),
                class_labels=(
                    tuple(detection.class_label for detection in frame.detections),
                ),
                source_ids=(
                    tuple(detection.source_id for detection in frame.detections),
                ),
                frame_ids=(frame.frame_id,),
                frame_names=(frame.frame_name,),
                latest_frames=(frame,),
                waveform_paths=(frame.waveform_paths,),
                sector_order=sector_order,
            )

        data = cls.allocate(
            num_envs=1,
            max_events=max_events,
            num_mics=len(tuple(microphone_ids)),
            device=device,
            sector_order=sector_order,
        )
        data.write_frame(
            env_id=0,
            frame=frame,
            microphone_ids=tuple(microphone_ids),
            timestamp_s=frame.start_time_s,
        )
        return data

    def reset_envs(self, env_ids: Sequence[int] | range) -> None:
        """Reset selected environments to padded sentinel values."""

        ids = tuple(int(env_id) for env_id in env_ids)
        if not ids:
            return

        rows = list(ids)
        self.event_presence[rows, :] = False
        self.bearing_deg[rows, :] = float("nan")
        self.confidence[rows, :] = 0.0
        self.sector_onehot[rows, :, :] = 0.0
        self.per_mic_rms[rows, :, :] = 0.0
        self.ambiguity_mask[rows, :] = False
        self.last_update_time_s[rows] = float("nan")

        frame_ids = list(self.frame_ids)
        frame_names = list(self.frame_names)
        source_ids = [list(row) for row in self.source_ids]
        class_labels = [list(row) for row in self.class_labels]
        latest_frames = list(self.latest_frames)
        waveform_paths = list(self.waveform_paths)
        for env_id in ids:
            frame_ids[env_id] = None
            frame_names[env_id] = None
            source_ids[env_id] = [None for _ in source_ids[env_id]]
            class_labels[env_id] = [None for _ in class_labels[env_id]]
            latest_frames[env_id] = None
            waveform_paths[env_id] = ()
        self.frame_ids = tuple(frame_ids)
        self.frame_names = tuple(frame_names)
        self.source_ids = tuple(tuple(row) for row in source_ids)
        self.class_labels = tuple(tuple(row) for row in class_labels)
        self.latest_frames = tuple(latest_frames)
        self.waveform_paths = tuple(waveform_paths)

    def write_frame(
        self,
        *,
        env_id: int,
        frame: AudioSensorFrame,
        microphone_ids: tuple[str, ...],
        timestamp_s: float | None,
    ) -> None:
        """Write one frame into one environment row."""

        env_id = int(env_id)
        self.reset_envs((env_id,))
        max_events = int(self.event_presence.shape[1])
        event_count = min(len(frame.detections), max_events)
        source_ids = [list(row) for row in self.source_ids]
        class_labels = [list(row) for row in self.class_labels]
        frame_ids = list(self.frame_ids)
        frame_names = list(self.frame_names)
        latest_frames = list(self.latest_frames)
        waveform_paths = list(self.waveform_paths)
        sector_index_by_name = {
            sector_name: index for index, sector_name in enumerate(self.sector_order)
        }

        self.microphone_ids = microphone_ids
        for event_index, detection in enumerate(frame.detections[:event_count]):
            self.event_presence[env_id, event_index] = True
            bearing = detection.doa.estimated_bearing_deg
            if bearing is not None:
                self.bearing_deg[env_id, event_index] = float(bearing)
                sector_name = detection.doa.bearing_sector
                if sector_name is None:
                    sector_name = bearing_deg_to_sector_name(float(bearing))
                sector_index = sector_index_by_name.get(sector_name)
                if sector_index is not None:
                    self.sector_onehot[env_id, event_index, sector_index] = 1.0
            self.confidence[env_id, event_index] = float(
                detection.doa.bearing_confidence
            )
            self.ambiguity_mask[env_id, event_index] = (
                detection.doa.ambiguity_class is not None
            )
            for mic_index, mic_id in enumerate(microphone_ids):
                self.per_mic_rms[env_id, event_index, mic_index] = float(
                    detection.per_mic_rms.get(mic_id, 0.0)
                )
            source_ids[env_id][event_index] = detection.source_id
            class_labels[env_id][event_index] = detection.class_label

        frame_ids[env_id] = frame.frame_id
        frame_names[env_id] = frame.frame_name
        latest_frames[env_id] = frame
        waveform_paths[env_id] = frame.waveform_paths
        if timestamp_s is not None:
            self.last_update_time_s[env_id] = float(timestamp_s)
        self.frame_ids = tuple(frame_ids)
        self.frame_names = tuple(frame_names)
        self.source_ids = tuple(tuple(row) for row in source_ids)
        self.class_labels = tuple(tuple(row) for row in class_labels)
        self.latest_frames = tuple(latest_frames)
        self.waveform_paths = tuple(waveform_paths)


def _require_torch() -> Any:
    try:
        import torch  # type: ignore

        return torch
    except ImportError as exc:
        raise RuntimeError(
            "AudioArraySensor tensor buffers require torch. Install torch or use "
            "AudioArraySensorData.empty()/from_frame() without tensor allocation."
        ) from exc
