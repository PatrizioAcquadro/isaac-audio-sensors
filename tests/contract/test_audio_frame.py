"""Contract tests for the public ``AudioSensorFrame`` v1 trace shape."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DETECTION_FIELDS,
    DETECTION_MODES,
    DOA_FIELDS,
    FRAME_PROVENANCE_VALUES,
    FRAME_SCHEMA_VERSION,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OPTIONAL_DETECTION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    OPTIONAL_FRAME_UNIT_KEYS,
    POSE3D_FIELDS,
    STABLE_DIAGNOSTIC_NAMESPACES,
)
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.schema import audio_sensor_frame_json_schema
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
    Pose3D,
)
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData

SCHEMA_PATH = Path("docs/schemas/audio_sensor_frame.v1.schema.json")
TRACE_DIR = Path("examples/traces")

def test_generated_schema_matches_checked_in_schema_exactly():
    generated = (
        json.dumps(audio_sensor_frame_json_schema(), indent=2, sort_keys=True) + "\n"
    )

    assert SCHEMA_PATH.read_text(encoding="utf-8") == generated


def test_backend_identifiers_are_stable_public_v1_ids():
    assert GeometryBackend.backend_id == "geometry_only"
    assert TdoaSyntheticBackend.backend_id == "tdoa_synthetic"
    assert RoomAcousticsBackend.backend_id == "room_acoustics"
    assert RoomAcousticsSrpBackend.backend_id == "room_acoustics_srp"

    for backend_id, backend_cls in (
        ("geometry_only", GeometryBackend),
        ("tdoa_synthetic", TdoaSyntheticBackend),
        ("room_acoustics", RoomAcousticsBackend),
        ("room_acoustics_srp", RoomAcousticsSrpBackend),
    ):
        assert isinstance(get_backend(backend_id), backend_cls)


def test_schema_exposes_serialized_frame_semantics():
    schema = _checked_in_schema()

    assert schema["properties"]["schema_version"]["const"] == (
        FRAME_SCHEMA_VERSION
    )
    assert "separate from the Python package version" in schema["description"]
    assert "bearing-sector semantics" in schema["description"]
    assert "stable backend identifiers" in schema["description"]
    assert schema["properties"]["backend_id"]["description"].endswith(
        "room_acoustics_srp."
    )
    assert "half-open v1 sector semantics" in (
        schema["properties"]["detections"]["items"]["properties"]["doa"]["properties"][
            "bearing_sector"
        ]["description"]
    )


def test_schema_required_keys_match_dataclasses_and_trace_serialization():
    payload = frame_to_trace_dict(_contract_frame())
    schema = _checked_in_schema()
    detection_schema = schema["properties"]["detections"]["items"]
    doa_schema = detection_schema["properties"]["doa"]

    assert schema["required"] == list(FRAME_TOP_LEVEL_FIELDS)
    assert detection_schema["required"] == [
        name for name in DETECTION_FIELDS if name not in OPTIONAL_DETECTION_FIELDS
    ]
    assert "occluded" in detection_schema["properties"]
    assert doa_schema["required"] == [
        name for name in DOA_FIELDS if name not in OPTIONAL_DOA_FIELDS
    ]
    assert "estimated_elevation_deg" in doa_schema["properties"]
    assert "candidate_elevation_deg" in doa_schema["properties"]
    assert set(payload) == set(FRAME_TOP_LEVEL_FIELDS)
    assert set(payload["detections"][0]) == set(DETECTION_FIELDS)
    assert set(payload["detections"][0]["doa"]) == set(DOA_FIELDS)
    assert set(payload["array_pose"]) == set(POSE3D_FIELDS)
    assert set(payload["detections"][0]["source_pose"]) == set(POSE3D_FIELDS)

    assert set(field.name for field in fields(AudioSensorFrame)) == set(
        FRAME_TOP_LEVEL_FIELDS
    )
    assert set(field.name for field in fields(AudioDetection)) == set(DETECTION_FIELDS)
    assert set(field.name for field in fields(DoaEstimate)) == set(DOA_FIELDS)
    assert set(field.name for field in fields(Pose3D)) == set(POSE3D_FIELDS)


def test_schema_allows_additive_optional_fields_without_dropping_required_fields():
    schema = _checked_in_schema()
    detection_schema = schema["properties"]["detections"]["items"]
    doa_schema = detection_schema["properties"]["doa"]
    pose_schema = schema["properties"]["array_pose"]["oneOf"][1]

    assert schema["additionalProperties"] is True
    assert detection_schema["additionalProperties"] is True
    assert doa_schema["additionalProperties"] is True
    assert pose_schema["additionalProperties"] is True
    assert set(schema["required"]) == set(FRAME_TOP_LEVEL_FIELDS)


def test_json_and_ndjson_trace_corpus_matches_v1_contract_and_round_trips():
    schema = _checked_in_schema()
    payloads = list(_iter_corpus_payloads())

    assert payloads
    assert any(path.suffix == ".json" for path, _ in payloads)
    assert any(path.suffix == ".ndjson" for path, _ in payloads)

    # Optional additive detection/DOA fields and the defaults a round-trip
    # adds to traces written before the fields existed.
    optional_detection_defaults = {
        "occluded": False,
        "ground_truth_elevation_deg": None,
    }
    assert set(optional_detection_defaults) == set(OPTIONAL_DETECTION_FIELDS)
    optional_doa_defaults = {
        "estimated_elevation_deg": None,
        "candidate_elevation_deg": [],
    }
    assert set(optional_doa_defaults) == set(OPTIONAL_DOA_FIELDS)

    for path, payload in payloads:
        _assert_payload_matches_contract(payload, schema, path=path)
        rebuilt_payload = frame_to_trace_dict(frame_from_trace_dict(payload))
        expected_payload = dict(payload)
        expected_payload["detections"] = [
            {
                **optional_detection_defaults,
                **detection,
                "doa": {**optional_doa_defaults, **detection["doa"]},
            }
            for detection in payload["detections"]
        ]
        for field_name in schema["required"]:
            assert rebuilt_payload[field_name] == expected_payload[field_name], (
                path,
                field_name,
            )


def test_trace_corpus_has_required_representative_cases():
    payloads = [payload for _, payload in _iter_corpus_payloads()]

    assert any(not payload["detections"] for payload in payloads)
    assert any(len(payload["detections"]) > 1 for payload in payloads)
    assert any(
        detection["doa"]["ambiguity_class"] is not None
        for payload in payloads
        for detection in payload["detections"]
    )
    assert any(
        payload["provenance"] in {"isaac_live", "replay/trace"}
        and any(
            namespace in payload["diagnostics"]
            for namespace in STABLE_DIAGNOSTIC_NAMESPACES
        )
        for payload in payloads
    )


def test_trace_corpus_files_are_deterministically_formatted():
    for path in TRACE_DIR.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        assert path.read_text(encoding="utf-8") == expected

    for path in TRACE_DIR.glob("*.ndjson"):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines
        for line in lines:
            payload = json.loads(line)
            assert line == json.dumps(
                payload,
                separators=(",", ":"),
                sort_keys=True,
            )


def test_dataclasses_enforce_contract_policy_values():
    with pytest.raises(ValueError, match="schema_version"):
        AudioSensorFrame(
            frame_id="bad_schema",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            schema_version="ias.audio_sensor_frame.v2",
        )

    with pytest.raises(ValueError, match="coordinate_convention"):
        Pose3D(
            position_m=(0.0, 0.0, 0.0),
            coordinate_convention="legacy_y_forward",
        )

    with pytest.raises(ValueError, match="coordinate_convention"):
        AudioSensorFrame(
            frame_id="bad_coordinate",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            coordinate_convention="legacy_y_forward",
        )

    changed_units = dict(FRAME_UNITS)
    changed_units["position"] = "ft"
    with pytest.raises(ValueError, match="stable unit values"):
        AudioSensorFrame(
            frame_id="bad_units",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            units=changed_units,
        )

    missing_units = dict(FRAME_UNITS)
    del missing_units["timestamp"]
    with pytest.raises(ValueError, match="missing required keys"):
        AudioSensorFrame(
            frame_id="missing_units",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            units=missing_units,
        )

    with pytest.raises(ValueError, match="provenance"):
        AudioSensorFrame(
            frame_id="bad_provenance",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            provenance="private_capture",
        )

    with pytest.raises(ValueError, match="end time"):
        AudioSensorFrame(
            frame_id="bad_time",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            start_time_s=1.0,
            end_time_s=1.0,
        )

    with pytest.raises(ValueError, match="frame_index"):
        AudioSensorFrame(
            frame_id="bad_index",
            timestamp_ms=0,
            backend_id="geometry_only",
            array_id="rig",
            frame_index=-1,
        )


def test_ambiguity_fields_drive_import_safe_lab_ambiguity_mask():
    frame = AudioSensorFrame(
        frame_id="ambiguous",
        timestamp_ms=0,
        backend_id="tdoa_synthetic",
        array_id="stereo",
        detections=(
            AudioDetection(
                detection_id="det_ambiguous",
                source_id="tone",
                class_label="Tone",
                detection_mode="scheduled_known_source",
                timestamp_ms=0,
                ground_truth_bearing_deg=0.0,
                source_distance_m=5.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=None,
                    candidate_bearing_deg=(0.0, 180.0),
                    bearing_confidence=0.35,
                    ambiguity_class="ambiguous_front_back",
                    ambiguity_reason=(
                        "Two-mic TDOA cannot distinguish mirrored bearings."
                    ),
                ),
            ),
        ),
    )

    data = AudioArraySensorData.from_frame(frame)

    assert frame.detections[0].doa.candidate_bearing_deg == pytest.approx((0.0, 180.0))
    assert data.ambiguity_mask == (True,)


def _contract_frame() -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id="contract",
        frame_name="contract/frame",
        timestamp_ms=10,
        start_time_s=0.0,
        end_time_s=0.1,
        sample_rate_hz=48_000,
        frame_index=0,
        backend_id="geometry_only",
        array_id="rig_front",
        array_pose=Pose3D(position_m=(0.0, 0.0, 0.0)),
        max_events=1,
        detections=(
            AudioDetection(
                detection_id="det_1",
                source_id="speaker",
                class_label="Speech",
                detection_mode="scheduled_known_source",
                timestamp_ms=10,
                ground_truth_bearing_deg=0.0,
                source_distance_m=1.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=0.0,
                    candidate_bearing_deg=(0.0,),
                    bearing_confidence=1.0,
                ),
                source_pose=Pose3D(position_m=(1.0, 0.0, 0.0)),
            ),
        ),
    )


def _checked_in_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _iter_corpus_payloads():
    for path in sorted(TRACE_DIR.glob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(TRACE_DIR.glob("*.ndjson")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            assert line.strip(), (path, line_number)
            yield path, json.loads(line)


def _assert_payload_matches_contract(
    payload: dict[str, Any],
    schema: dict[str, Any],
    *,
    path: Path,
) -> None:
    assert set(schema["required"]) <= set(payload), path
    assert payload["schema_version"] == FRAME_SCHEMA_VERSION
    assert payload["coordinate_convention"] == COORDINATE_CONVENTION
    for key, value in FRAME_UNITS.items():
        if key in OPTIONAL_FRAME_UNIT_KEYS and key not in payload["units"]:
            # Additive unit keys may be absent in older v1 traces.
            continue
        assert payload["units"][key] == value, (path, key)
    assert payload["provenance"] in FRAME_PROVENANCE_VALUES
    assert isinstance(payload["timestamp_ms"], int), path
    if payload["sample_rate_hz"] is not None:
        assert payload["sample_rate_hz"] > 0, path
    if payload["frame_index"] is not None:
        assert payload["frame_index"] >= 0, path
    if payload["max_events"] is not None:
        assert payload["max_events"] >= 0, path
        assert len(payload["detections"]) <= payload["max_events"], path
    if payload["start_time_s"] is not None and payload["end_time_s"] is not None:
        assert payload["end_time_s"] > payload["start_time_s"], path
    assert isinstance(payload["diagnostics"], dict), path
    _assert_pose_payload(payload["array_pose"], path=path)

    for detection in payload["detections"]:
        required_detection_fields = set(DETECTION_FIELDS) - set(
            OPTIONAL_DETECTION_FIELDS
        )
        assert required_detection_fields <= set(detection), path
        assert detection["detection_mode"] in DETECTION_MODES
        assert isinstance(detection["timestamp_ms"], int), path
        if detection["source_distance_m"] is not None:
            assert detection["source_distance_m"] >= 0.0, path
        assert isinstance(detection["diagnostics"], dict), path
        assert isinstance(detection["per_mic_delay_s"], dict), path
        assert isinstance(detection["per_mic_rms"], dict), path
        _assert_pose_payload(detection["source_pose"], path=path)

        doa = detection["doa"]
        assert set(DOA_FIELDS) - set(OPTIONAL_DOA_FIELDS) <= set(doa), path
        assert 0.0 <= doa["bearing_confidence"] <= 1.0, path
        assert isinstance(doa["candidate_bearing_deg"], list), path
        if doa["ambiguity_class"] is not None:
            assert doa["ambiguity_reason"], path
            assert doa["candidate_bearing_deg"], path


def _assert_pose_payload(payload: dict[str, Any] | None, *, path: Path) -> None:
    if payload is None:
        return
    assert set(POSE3D_FIELDS) <= set(payload), path
    assert payload["coordinate_convention"] == COORDINATE_CONVENTION, path
    assert len(payload["position_m"]) == 3, path
    orientation = payload["orientation_xyzw"]
    if orientation is not None:
        assert len(orientation) == 4, path
