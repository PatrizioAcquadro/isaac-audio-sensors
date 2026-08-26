"""JSON Schema generation for public audio contracts."""

from __future__ import annotations

import json
from pathlib import Path

from isaac_audio_sensors.schemas._calibration_profile import (
    audio_calibration_profile_json_schema,
)
from isaac_audio_sensors.schemas._dataset_manifest import (
    audio_dataset_manifest_json_schema,
)
from isaac_audio_sensors.schemas._frame import audio_sensor_frame_json_schema

__all__ = [
    "audio_calibration_profile_json_schema",
    "audio_dataset_manifest_json_schema",
    "audio_sensor_frame_json_schema",
    "write_json_schema",
]

_SCHEMAS = {
    "frame": (
        audio_sensor_frame_json_schema,
        "audio_sensor_frame.v1.schema.json",
    ),
    "dataset-manifest": (
        audio_dataset_manifest_json_schema,
        "audio_dataset_manifest.v1.schema.json",
    ),
    "calibration-profile": (
        audio_calibration_profile_json_schema,
        "audio_calibration_profile.v1.schema.json",
    ),
}


def write_json_schema(schema_name: str, path: str | Path | None = None) -> Path:
    """Write a generated public schema as deterministic JSON."""

    try:
        generator, filename = _SCHEMAS[schema_name]
    except KeyError as exc:
        raise ValueError(f"Unknown schema {schema_name!r}.") from exc

    output_path = Path(filename if path is None else path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(generator(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
