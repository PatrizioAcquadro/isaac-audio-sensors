"""Contract tests for the public ``AudioSensorFrame`` v1 trace shape."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from isaac_audio_sensors.core.backends.base import get_backend, registered_backend_ids
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import (
    RoomAcousticsBackend,
    RoomAcousticsSrpBackend,
)
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.constants import (
    DETECTION_FIELDS,
    DOA_FIELDS,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OPTIONAL_DETECTION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    POSE3D_FIELDS,
    STABLE_DIAGNOSTIC_NAMESPACES,
)
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSensorFrame,
    DoaEstimate,
    Pose3D,
)
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData

TRACE_DIR = Path("examples/traces")


def test_backend_identifiers_are_stable_public_v1_ids():
    assert GeometryBackend.backend_id == "geometry_only"
    assert TdoaSyntheticBackend.backend_id == "tdoa_synthetic"
    assert RoomAcousticsBackend.backend_id == "room_acoustics"
    assert RoomAcousticsSrpBackend.backend_id == "room_acoustics_srp"

    assert registered_backend_ids() == (
        "geometry_only",
        "tdoa_synthetic",
        "room_acoustics",
        "room_acoustics_srp",
    )
    for backend_id, backend_cls in (
        ("geometry_only", GeometryBackend),
        ("tdoa_synthetic", TdoaSyntheticBackend),
    ):
        assert isinstance(get_backend(backend_id), backend_cls)


def test_serialized_fields_match_dataclass_contracts():
    payload = frame_to_trace_dict(_contract_frame())

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


def test_json_and_ndjson_trace_corpus_matches_v1_contract_and_round_trips():
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
        for field_name in FRAME_TOP_LEVEL_FIELDS:
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
