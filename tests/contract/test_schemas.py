from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from isaac_audio_sensors.schemas.generate import (
    audio_calibration_profile_json_schema,
    audio_dataset_manifest_json_schema,
    audio_sensor_frame_json_schema,
    write_json_schema,
)

SchemaGenerator = Callable[[], dict[str, Any]]
SCHEMAS: dict[str, tuple[SchemaGenerator, str]] = {
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


@pytest.mark.parametrize(("schema_name", "entry"), SCHEMAS.items())
def test_generators_are_draft_2020_12_and_match_packaged_json(schema_name, entry):
    generator, filename = entry
    schema = generator()
    packaged = files("isaac_audio_sensors.schemas").joinpath(filename)

    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert packaged.read_text(encoding="utf-8") == _schema_text(schema), schema_name


@pytest.mark.parametrize(("schema_name", "entry"), SCHEMAS.items())
def test_schema_export_is_deterministic(schema_name, entry, tmp_path, monkeypatch):
    generator, filename = entry
    monkeypatch.chdir(tmp_path)

    output = write_json_schema(schema_name)
    first = output.read_bytes()
    write_json_schema(schema_name)

    assert output == Path(filename)
    assert first == output.read_bytes()
    assert first.decode() == _schema_text(generator())


def test_preserved_v1_payloads_conform_to_generated_schemas():
    frame_payloads = list(_trace_payloads())
    assert any("elevation" not in payload["units"] for payload in frame_payloads)

    _validate_all(audio_sensor_frame_json_schema(), frame_payloads)
    _validate_all(
        audio_calibration_profile_json_schema(),
        _json_payloads(Path("examples/calibration")),
    )
    _validate_all(
        audio_dataset_manifest_json_schema(),
        (
            *_json_payloads(Path("examples/manifests")),
            json.loads(
                Path("tests/fixtures/recording/session/manifest.json").read_text(
                    encoding="utf-8"
                )
            ),
        ),
    )


def _schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _validate_all(schema: dict[str, Any], payloads) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for payload in payloads:
        validator.validate(payload)


def _json_payloads(directory: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    )


def _trace_payloads() -> Iterator[dict[str, Any]]:
    directory = Path("examples/traces")
    yield from _json_payloads(directory)
    for path in sorted(directory.glob("*.ndjson")):
        for line in path.read_text(encoding="utf-8").splitlines():
            yield json.loads(line)
