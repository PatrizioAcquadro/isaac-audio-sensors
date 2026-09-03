"""Deterministic trace serialization for audio sensor frames."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.constants import (
    DOA_FIELDS,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    OBSERVATION_FIELDS,
    POSE3D_FIELDS,
)
from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSensorFrame,
    DoaEstimate,
    ObservationOrigin,
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
        output_file.write(
            json.dumps(
                frame_to_trace_dict(frame),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        output_file.write("\n")
    return output_path


def frame_from_trace_dict(payload: dict[str, Any]) -> AudioSensorFrame:
    """Rebuild an ``AudioSensorFrame`` from a trace dictionary."""

    if payload.get("schema_version") != FRAME_SCHEMA_VERSION:
        raise ValueError(
            f"AudioSensorFrame.schema_version must be {FRAME_SCHEMA_VERSION!r}."
        )
    _require_exact_fields(payload, FRAME_TOP_LEVEL_FIELDS, "AudioSensorFrame")
    observations = tuple(
        _observation_from_dict(item) for item in payload["observations"]
    )
    frame = AudioSensorFrame(
        frame_id=str(payload["frame_id"]),
        producer_id=str(payload["producer_id"]),
        array_id=str(payload["array_id"]),
        channel_validity=dict(payload["channel_validity"]),
        start_time_s=float(payload["start_time_s"]),
        end_time_s=float(payload["end_time_s"]),
        sample_rate_hz=int(payload["sample_rate_hz"]),
        frame_index=int(payload["frame_index"]),
        schema_version=str(payload["schema_version"]),
        frame_name=str(payload["frame_name"]),
        array_pose=_pose_from_dict(payload["array_pose"]),
        coordinate_convention=str(payload["coordinate_convention"]),
        units=dict(payload["units"]),
        provenance=str(payload["provenance"]),
        max_observations=_optional_int(payload["max_observations"]),
        observations=observations,
        aggregate_per_mic_rms=dict(payload["aggregate_per_mic_rms"]),
        waveform_paths=tuple(payload["waveform_paths"]),
        diagnostics=dict(payload["diagnostics"]),
    )
    if int(payload["timestamp_ms"]) != frame.timestamp_ms:
        raise ValueError(
            "AudioSensorFrame.timestamp_ms must equal round(start_time_s * 1000)."
        )
    return frame


def read_frame_trace(path: str | Path) -> AudioSensorFrame:
    """Read one pretty JSON frame trace."""

    return frame_from_trace_dict(json.loads(Path(path).read_text(encoding="utf-8")))


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


def _observation_from_dict(payload: dict[str, Any]) -> AudioObservation:
    _require_exact_fields(payload, OBSERVATION_FIELDS, "AudioObservation")
    doa_payload = payload["doa"]
    doa = None
    if doa_payload is not None:
        doa_payload = dict(doa_payload)
        _require_exact_fields(doa_payload, DOA_FIELDS, "DoaEstimate")
        doa = DoaEstimate(
            estimated_bearing_deg=_optional_float(
                doa_payload["estimated_bearing_deg"]
            ),
            candidate_bearing_deg=tuple(
                float(value) for value in doa_payload["candidate_bearing_deg"]
            ),
            bearing_sector=doa_payload["bearing_sector"],
            bearing_confidence=float(doa_payload["bearing_confidence"]),
            ambiguity_class=doa_payload["ambiguity_class"],
            ambiguity_reason=doa_payload["ambiguity_reason"],
            estimated_elevation_deg=_optional_float(
                doa_payload["estimated_elevation_deg"]
            ),
            candidate_elevation_deg=tuple(
                float(value)
                for value in doa_payload["candidate_elevation_deg"]
            ),
        )
    return AudioObservation(
        observation_id=str(payload["observation_id"]),
        origin=ObservationOrigin(str(payload["origin"])),
        detector_id=str(payload["detector_id"]),
        detection_score=_optional_float(payload["detection_score"]),
        doa=doa,
        diagnostics=dict(payload["diagnostics"]),
    )


def _pose_from_dict(payload: dict[str, Any] | None) -> Pose3D | None:
    if payload is None:
        return None
    _require_exact_fields(payload, POSE3D_FIELDS, "Pose3D")
    return Pose3D(
        position_m=tuple(payload["position_m"]),
        orientation_xyzw=(
            None
            if payload["orientation_xyzw"] is None
            else tuple(payload["orientation_xyzw"])
        ),
        frame=str(payload["frame"]),
        coordinate_convention=str(payload["coordinate_convention"]),
    )


def _require_exact_fields(
    payload: dict[str, Any],
    expected_fields: tuple[str, ...],
    label: str,
) -> None:
    actual = set(payload)
    expected = set(expected_fields)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{label} fields must be exactly {sorted(expected)!r}; "
            f"missing={missing!r}, extra={extra!r}."
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
