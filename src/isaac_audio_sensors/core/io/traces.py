"""Deterministic trace serialization for audio sensor frames."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.types import AudioSensorFrame


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
