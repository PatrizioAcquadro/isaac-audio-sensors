from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from isaac_audio_sensors.core.constants import (
    DETECTION_FIELDS,
    DOA_FIELDS,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OPTIONAL_DETECTION_FIELDS,
    OPTIONAL_DOA_FIELDS,
    POSE3D_FIELDS,
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

TRACE_DIR = Path("examples/traces")


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


def test_json_and_ndjson_trace_corpus_matches_v2_contract_and_round_trips():
    payloads = list(_iter_corpus_payloads())

    assert payloads
    assert any(path.suffix == ".json" for path, _ in payloads)
    assert any(path.suffix == ".ndjson" for path, _ in payloads)

    optional_detection_defaults = {}
    assert set(optional_detection_defaults) == set(OPTIONAL_DETECTION_FIELDS)
    optional_doa_defaults = {}
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
    assert any(payload["provenance"] == "replay/trace" for payload in payloads)
    assert not tuple(TRACE_DIR.glob("*.v1.json"))
    assert not tuple(TRACE_DIR.glob("*.v1.ndjson"))


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
        _minimal_frame(
            frame_id="bad_schema",
            schema_version="ias.audio_sensor_frame.v1",
        )

    with pytest.raises(ValueError, match="coordinate_convention"):
        Pose3D(
            position_m=(0.0, 0.0, 0.0),
            coordinate_convention="legacy_y_forward",
        )

    with pytest.raises(ValueError, match="coordinate_convention"):
        _minimal_frame(
            frame_id="bad_coordinate",
            coordinate_convention="legacy_y_forward",
        )

    changed_units = dict(FRAME_UNITS)
    changed_units["position"] = "ft"
    with pytest.raises(ValueError, match="stable unit values"):
        _minimal_frame(
            frame_id="bad_units",
            units=changed_units,
        )

    missing_units = dict(FRAME_UNITS)
    del missing_units["timestamp"]
    with pytest.raises(ValueError, match="missing required keys"):
        _minimal_frame(
            frame_id="missing_units",
            units=missing_units,
        )

    with pytest.raises(ValueError, match="provenance"):
        _minimal_frame(
            frame_id="bad_provenance",
            provenance="private_capture",
        )

    with pytest.raises(ValueError, match="end time"):
        _minimal_frame(
            frame_id="bad_time",
            start_time_s=1.0,
            end_time_s=1.0,
        )

    with pytest.raises(ValueError, match="frame_index"):
        _minimal_frame(
            frame_id="bad_index",
            frame_index=-1,
        )


def test_frame_timestamp_is_derived_and_detection_overflow_is_rejected():
    frame = _minimal_frame(start_time_s=1.234, end_time_s=1.334)
    assert frame.timestamp_ms == 1_234
    with pytest.raises(TypeError, match="timestamp_ms"):
        _minimal_frame(timestamp_ms=99)

    detection = _contract_frame().detections[0]
    with pytest.raises(ValueError, match="exceeds max_detections"):
        replace(
            _contract_frame(),
            detections=(detection, replace(detection, detection_id="det_2")),
        )


def test_trace_reader_rejects_inconsistent_derived_timestamp():
    payload = frame_to_trace_dict(_contract_frame())
    payload["timestamp_ms"] += 1

    with pytest.raises(ValueError, match=r"round\(start_time_s"):
        frame_from_trace_dict(payload)


def test_trace_reader_rejects_v1_and_removed_detection_timestamp():
    payload = frame_to_trace_dict(_contract_frame())
    payload["schema_version"] = "ias.audio_sensor_frame.v1"
    with pytest.raises(ValueError, match="schema_version"):
        frame_from_trace_dict(payload)

    payload = frame_to_trace_dict(_contract_frame())
    payload["detections"][0]["timestamp_ms"] = 0
    with pytest.raises(ValueError, match="extra=.*timestamp_ms"):
        frame_from_trace_dict(payload)


def _contract_frame() -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id="contract",
        frame_name="contract/frame",
        start_time_s=0.0,
        end_time_s=0.1,
        sample_rate_hz=48_000,
        frame_index=0,
        backend_id="geometry_only",
        array_id="rig_front",
        array_pose=Pose3D(position_m=(0.0, 0.0, 0.0)),
        max_detections=1,
        detections=(
            AudioDetection(
                detection_id="det_1",
                source_id="speaker",
                class_label="Speech",
                detection_mode="scheduled_known_source",
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


def _minimal_frame(**overrides) -> AudioSensorFrame:
    values = {
        "frame_id": "frame",
        "backend_id": "geometry_only",
        "array_id": "rig",
        "start_time_s": 0.0,
        "end_time_s": 0.1,
        "sample_rate_hz": 48_000,
        "frame_index": 0,
    }
    values.update(overrides)
    return AudioSensorFrame(**values)


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
