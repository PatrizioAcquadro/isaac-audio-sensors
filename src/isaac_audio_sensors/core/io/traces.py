"""Deterministic trace serialization for audio sensor frames."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    FRAME_SCHEMA_VERSION,
    FRAME_UNITS,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
    Pose3D,
)


def frame_to_trace_dict(frame: AudioSensorFrame) -> dict[str, Any]:
    """Return a JSON-ready trace dictionary for one frame."""

    return _serialize(frame)


def write_frame_trace(frame: AudioSensorFrame, path: str | Path) -> Path:
    """Write a deterministic JSON trace for one frame."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(frame_to_trace_dict(frame), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def append_frame_jsonl(frame: AudioSensorFrame, path: str | Path) -> Path:
    """Append one frame to a deterministic JSONL trace."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(json.dumps(frame_to_trace_dict(frame), sort_keys=True))
        output_file.write("\n")
    return output_path


def frame_from_trace_dict(payload: dict[str, Any]) -> AudioSensorFrame:
    """Rebuild an ``AudioSensorFrame`` from a trace dictionary."""

    detections = tuple(_detection_from_dict(item) for item in payload["detections"])
    return AudioSensorFrame(
        frame_id=str(payload["frame_id"]),
        timestamp_ms=int(payload["timestamp_ms"]),
        backend_id=str(payload["backend_id"]),
        array_id=str(payload["array_id"]),
        schema_version=str(payload.get("schema_version", FRAME_SCHEMA_VERSION)),
        frame_name=payload.get("frame_name"),
        array_pose=_pose_from_dict(payload.get("array_pose")),
        start_time_s=_optional_float(payload.get("start_time_s")),
        end_time_s=_optional_float(payload.get("end_time_s")),
        sample_rate_hz=_optional_int(payload.get("sample_rate_hz")),
        frame_index=_optional_int(payload.get("frame_index")),
        coordinate_convention=str(
            payload.get(
                "coordinate_convention",
                COORDINATE_CONVENTION,
            )
        ),
        units=dict(payload.get("units", FRAME_UNITS)),
        provenance=str(payload.get("provenance", "replay/trace")),
        max_events=_optional_int(payload.get("max_events")),
        detections=detections,
        aggregate_per_mic_rms=dict(payload.get("aggregate_per_mic_rms", {})),
        waveform_paths=tuple(payload.get("waveform_paths", ())),
        diagnostics=dict(payload.get("diagnostics", {})),
    )


def read_frame_trace(path: str | Path) -> AudioSensorFrame:
    """Read one pretty JSON frame trace."""

    return frame_from_trace_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class AudioFrameJsonlWriter:
    """Small package-level writer fallback for Isaac/update-loop recordings."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False

    def write(self, frame: AudioSensorFrame) -> Path:
        """Append ``frame`` unless the writer has been closed."""

        if self._closed:
            raise RuntimeError("AudioFrameJsonlWriter is closed.")
        return append_frame_jsonl(frame, self.path)

    def close(self) -> None:
        """Close the writer interface."""

        self._closed = True


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field_info.name: _serialize(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _serialize(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _detection_from_dict(payload: dict[str, Any]) -> AudioDetection:
    doa_payload = dict(payload["doa"])
    return AudioDetection(
        detection_id=str(payload["detection_id"]),
        source_id=payload.get("source_id"),
        class_label=payload.get("class_label"),
        detection_mode=str(payload["detection_mode"]),
        timestamp_ms=int(payload["timestamp_ms"]),
        ground_truth_bearing_deg=_optional_float(
            payload.get("ground_truth_bearing_deg")
        ),
        source_distance_m=_optional_float(payload.get("source_distance_m")),
        doa=DoaEstimate(
            estimated_bearing_deg=_optional_float(
                doa_payload.get("estimated_bearing_deg")
            ),
            candidate_bearing_deg=tuple(
                float(value) for value in doa_payload.get("candidate_bearing_deg", ())
            ),
            bearing_sector=doa_payload.get("bearing_sector"),
            bearing_confidence=float(doa_payload.get("bearing_confidence", 0.0)),
            ambiguity_class=doa_payload.get("ambiguity_class"),
            ambiguity_reason=doa_payload.get("ambiguity_reason"),
        ),
        source_pose=_pose_from_dict(payload.get("source_pose")),
        per_mic_delay_s=dict(payload.get("per_mic_delay_s", {})),
        per_mic_rms=dict(payload.get("per_mic_rms", {})),
        audio_asset_path=payload.get("audio_asset_path"),
        diagnostics=dict(payload.get("diagnostics", {})),
    )


def _pose_from_dict(payload: dict[str, Any] | None) -> Pose3D | None:
    if payload is None:
        return None
    return Pose3D(
        position_m=tuple(payload["position_m"]),
        orientation_xyzw=(
            None
            if payload.get("orientation_xyzw") is None
            else tuple(payload["orientation_xyzw"])
        ),
        frame=str(payload.get("frame", "world")),
        coordinate_convention=str(
            payload.get(
                "coordinate_convention",
                COORDINATE_CONVENTION,
            )
        ),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
