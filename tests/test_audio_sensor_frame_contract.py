"""Contract tests for the public ``AudioSensorFrame`` v1 trace shape."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
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
    KNOWN_BACKENDS,
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

CANONICAL_FRAME_SCHEMA_VERSION = "ias.audio_sensor_frame.v1"
CANONICAL_COORDINATE_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"
CANONICAL_FRAME_TOP_LEVEL_FIELDS = (
    "schema_version",
    "frame_id",
    "frame_name",
    "timestamp_ms",
    "start_time_s",
    "end_time_s",
    "sample_rate_hz",
    "frame_index",
    "backend_id",
    "array_id",
    "array_pose",
    "coordinate_convention",
    "units",
    "provenance",
    "max_events",
    "detections",
    "aggregate_per_mic_rms",
    "waveform_paths",
    "diagnostics",
)
CANONICAL_DETECTION_FIELDS = (
    "detection_id",
    "source_id",
    "class_label",
    "detection_mode",
    "timestamp_ms",
    "ground_truth_bearing_deg",
    "source_distance_m",
    "doa",
    "ground_truth_elevation_deg",
    "source_pose",
    "per_mic_delay_s",
    "per_mic_rms",
    "audio_asset_path",
    "occluded",
    "diagnostics",
)
CANONICAL_OPTIONAL_DETECTION_FIELDS = ("occluded", "ground_truth_elevation_deg")
CANONICAL_DOA_FIELDS = (
    "estimated_bearing_deg",
    "candidate_bearing_deg",
    "bearing_sector",
    "bearing_confidence",
    "ambiguity_class",
    "ambiguity_reason",
    "estimated_elevation_deg",
    "candidate_elevation_deg",
)
CANONICAL_OPTIONAL_DOA_FIELDS = (
    "estimated_elevation_deg",
    "candidate_elevation_deg",
)
CANONICAL_POSE3D_FIELDS = (
    "position_m",
    "orientation_xyzw",
    "frame",
    "coordinate_convention",
)
CANONICAL_FRAME_UNITS = {
    "position": "m",
    "orientation": "quaternion_xyzw",
    "bearing": "deg_clockwise_from_array_forward",
    "elevation": "deg_up_from_array_horizontal",
    "distance": "m",
    "time": "s",
    "timestamp": "ms",
    "sample_rate": "Hz",
    "rms": "linear",
    "gain": "dB",
}
CANONICAL_OPTIONAL_FRAME_UNIT_KEYS = ("elevation",)
CANONICAL_PROVENANCE_VALUES = frozenset(
    {
        "synthetic/core",
        "room_acoustics",
        "isaac_live",
        "replay/trace",
    }
)
CANONICAL_DETECTION_MODES = frozenset(
    {
        "scheduled_known_source",
        "external_metadata",
        "signal_energy",
        "manual_annotation",
    }
)
CANONICAL_STABLE_DIAGNOSTIC_NAMESPACES = (
    "stage_snapshot",
    "stage_binding",
    "entity_binding",
)
CANONICAL_BACKEND_IDS = frozenset({"geometry_only", "tdoa_synthetic", "room_acoustics"})


def test_generated_schema_matches_checked_in_schema_exactly():
    generated = (
        json.dumps(audio_sensor_frame_json_schema(), indent=2, sort_keys=True) + "\n"
    )

    assert SCHEMA_PATH.read_text(encoding="utf-8") == generated


def test_v1_contract_snapshots_guard_public_names_and_semantics():
    assert FRAME_SCHEMA_VERSION == CANONICAL_FRAME_SCHEMA_VERSION
    assert COORDINATE_CONVENTION == CANONICAL_COORDINATE_CONVENTION
    assert FRAME_TOP_LEVEL_FIELDS == CANONICAL_FRAME_TOP_LEVEL_FIELDS
    assert DETECTION_FIELDS == CANONICAL_DETECTION_FIELDS
    assert OPTIONAL_DETECTION_FIELDS == CANONICAL_OPTIONAL_DETECTION_FIELDS
    assert set(OPTIONAL_DETECTION_FIELDS) < set(DETECTION_FIELDS)
    assert DOA_FIELDS == CANONICAL_DOA_FIELDS
    assert OPTIONAL_DOA_FIELDS == CANONICAL_OPTIONAL_DOA_FIELDS
    assert set(OPTIONAL_DOA_FIELDS) < set(DOA_FIELDS)
    assert POSE3D_FIELDS == CANONICAL_POSE3D_FIELDS
    assert FRAME_UNITS == CANONICAL_FRAME_UNITS
    assert OPTIONAL_FRAME_UNIT_KEYS == CANONICAL_OPTIONAL_FRAME_UNIT_KEYS
    assert set(OPTIONAL_FRAME_UNIT_KEYS) < set(FRAME_UNITS)
    assert FRAME_PROVENANCE_VALUES == CANONICAL_PROVENANCE_VALUES
    assert DETECTION_MODES == CANONICAL_DETECTION_MODES
    assert STABLE_DIAGNOSTIC_NAMESPACES == CANONICAL_STABLE_DIAGNOSTIC_NAMESPACES
    assert KNOWN_BACKENDS == CANONICAL_BACKEND_IDS


def test_backend_identifiers_are_stable_public_v1_ids():
    assert GeometryBackend.backend_id == "geometry_only"
    assert TdoaSyntheticBackend.backend_id == "tdoa_synthetic"
    assert RoomAcousticsBackend.backend_id == "room_acoustics"

    for backend_id, backend_cls in (
        ("geometry_only", GeometryBackend),
        ("tdoa_synthetic", TdoaSyntheticBackend),
        ("room_acoustics", RoomAcousticsBackend),
    ):
        assert isinstance(get_backend(backend_id), backend_cls)


def test_schema_documents_v1_contract_lock_semantics():
    schema = _checked_in_schema()

    assert schema["properties"]["schema_version"]["const"] == (
        CANONICAL_FRAME_SCHEMA_VERSION
    )
    assert "separate from the Python package version" in schema["description"]
    assert "bearing-sector semantics" in schema["description"]
    assert "stable backend identifiers" in schema["description"]
    assert schema["properties"]["backend_id"]["description"].endswith("room_acoustics.")
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


def test_contract_policy_is_documented_in_public_docs():
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("docs/api_freeze_0_1.md"),
            Path("docs/api_reference.md"),
            Path("docs/versioning.md"),
            Path("docs/validation.md"),
        )
    )

    assert FRAME_SCHEMA_VERSION in docs
    assert COORDINATE_CONVENTION in docs
    for key, value in FRAME_UNITS.items():
        assert f"`{key}`" in docs
        assert f"`{value}`" in docs
    for provenance in FRAME_PROVENANCE_VALUES:
        assert f"`{provenance}`" in docs
    for field_name in DOA_FIELDS:
        assert f"`{field_name}`" in docs
    for namespace in STABLE_DIAGNOSTIC_NAMESPACES:
        assert f"`{namespace}`" in docs
    for backend_id in CANONICAL_BACKEND_IDS:
        assert f"`{backend_id}`" in docs
    for phrase in (
        "Renaming public fields is a breaking change",
        "Removing public fields is a breaking change",
        "Changing bearing-sector semantics is a breaking change",
        "Corrected bearing-sector behavior is the stable v1 contract",
        "Additive optional fields and additive diagnostics namespaces",
        "schema version is separate from the Python package version",
        "milliseconds",
        "seconds",
        "non-negative",
        "ambiguity_mask",
        "optional fields",
        "337.5 <= bearing < 360.0",
    ):
        assert phrase in docs


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
