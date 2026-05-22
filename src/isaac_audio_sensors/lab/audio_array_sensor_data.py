"""Batch-friendly observation data for Isaac Lab workflows."""

from __future__ import annotations

from dataclasses import dataclass, field

from isaac_audio_sensors.core.types import AudioSensorFrame


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioArraySensorData:
    """Tensor-friendly fields without requiring torch at core import time."""

    event_presence: tuple[bool, ...] = field(default_factory=tuple)
    bearing_deg: tuple[float | None, ...] = field(default_factory=tuple)
    bearing_confidence: tuple[float, ...] = field(default_factory=tuple)
    ambiguity_mask: tuple[bool, ...] = field(default_factory=tuple)
    per_mic_rms: tuple[dict[str, float], ...] = field(default_factory=tuple)
    class_label: tuple[str | None, ...] = field(default_factory=tuple)
    waveform_paths: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_frame(cls, frame: AudioSensorFrame) -> AudioArraySensorData:
        """Convert one frame to observation fields."""

        return cls(
            event_presence=tuple(True for _ in frame.detections),
            bearing_deg=tuple(
                detection.doa.estimated_bearing_deg for detection in frame.detections
            ),
            bearing_confidence=tuple(
                detection.doa.bearing_confidence for detection in frame.detections
            ),
            ambiguity_mask=tuple(
                detection.doa.ambiguity_class is not None
                for detection in frame.detections
            ),
            per_mic_rms=tuple(detection.per_mic_rms for detection in frame.detections),
            class_label=tuple(detection.class_label for detection in frame.detections),
            waveform_paths=frame.waveform_paths,
        )

    @classmethod
    def empty(cls) -> AudioArraySensorData:
        """Return an empty observation buffer."""

        return cls()
