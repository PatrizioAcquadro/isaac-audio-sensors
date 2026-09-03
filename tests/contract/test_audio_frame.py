from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from isaac_audio_sensors.core.constants import (
    DOA_FIELDS,
    FRAME_TOP_LEVEL_FIELDS,
    FRAME_UNITS,
    OBSERVATION_FIELDS,
    POSE3D_FIELDS,
)
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSensorFrame,
    DoaEstimate,
    ObservationOrigin,
    Pose3D,
)

TRACE_DIR = Path("examples/traces")


def test_serialized_fields_match_v3_dataclass_contracts() -> None:
    payload = frame_to_trace_dict(_contract_frame())

    assert set(payload) == set(FRAME_TOP_LEVEL_FIELDS)
    assert set(payload["observations"][0]) == set(OBSERVATION_FIELDS)
    assert set(payload["observations"][0]["doa"]) == set(DOA_FIELDS)
    assert set(payload["array_pose"]) == set(POSE3D_FIELDS)
    assert set(field.name for field in fields(AudioSensorFrame)) == set(
        FRAME_TOP_LEVEL_FIELDS
    )
    assert set(field.name for field in fields(AudioObservation)) == set(
        OBSERVATION_FIELDS
    )


def test_json_and_ndjson_trace_corpus_round_trips_byte_for_byte() -> None:
    payloads = list(_iter_corpus_payloads())

    assert payloads
    assert any(path.suffix == ".json" for path, _ in payloads)
    assert any(path.suffix == ".ndjson" for path, _ in payloads)
    for path, payload in payloads:
        assert frame_to_trace_dict(frame_from_trace_dict(payload)) == payload, path


def test_trace_corpus_has_v3_observation_cases_only() -> None:
    payloads = [payload for _, payload in _iter_corpus_payloads()]

    assert any(not payload["observations"] for payload in payloads)
    assert any(
        observation["doa"] is None
        for payload in payloads
        for observation in payload["observations"]
    )
    assert any(
        observation["doa"] is not None
        and observation["doa"]["estimated_bearing_deg"] is None
        for payload in payloads
        for observation in payload["observations"]
    )
    assert not tuple(TRACE_DIR.glob("*.v2.json"))
    assert not tuple(TRACE_DIR.glob("*.v2.ndjson"))


def test_trace_corpus_files_are_deterministically_formatted() -> None:
    for path in TRACE_DIR.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert path.read_text(encoding="utf-8") == (
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
    for path in TRACE_DIR.glob("*.ndjson"):
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            assert line == json.dumps(payload, separators=(",", ":"), sort_keys=True)


def test_observation_origin_and_score_validation() -> None:
    assert tuple(origin.value for origin in ObservationOrigin) == (
        "signal_derived",
        "external_system",
    )
    with pytest.raises(ValueError, match="origin"):
        _observation(origin="oracle")
    assert _observation(detection_score=3.5).detection_score == 3.5
    assert _observation(detection_score=-2.0).detection_score == -2.0
    for invalid in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="detection_score"):
            _observation(detection_score=invalid)


def test_observation_doa_states_and_diagnostics_copy() -> None:
    diagnostics = {"window_energy": 2.0}
    absent = _observation(diagnostics=diagnostics)
    diagnostics["window_energy"] = 9.0
    assert absent.doa is None
    assert absent.diagnostics == {"window_energy": 2.0}

    resolved = _observation(
        doa=DoaEstimate(
            estimated_bearing_deg=30.0,
            candidate_bearing_deg=(30.0,),
            bearing_confidence=0.8,
        )
    )
    unresolved_doa = DoaEstimate(
        estimated_bearing_deg=None,
        candidate_bearing_deg=(45.0, 315.0),
        bearing_confidence=0.0,
        ambiguity_class="two_mic_front_back",
        ambiguity_reason="two compatible bearings",
    )
    unresolved = _observation(doa=unresolved_doa)
    assert resolved.doa is not None and resolved.doa.estimated_bearing_deg == 30.0
    assert unresolved.doa is unresolved_doa


def test_observation_contract_excludes_privileged_fields() -> None:
    removed = {
        "source_id",
        "source_pose",
        "class_label",
        "audio_asset_path",
        "ground_truth_bearing_deg",
        "ground_truth_elevation_deg",
        "source_distance_m",
        "per_mic_delay_s",
        "per_mic_rms",
        "occluded",
    }
    assert removed.isdisjoint(OBSERVATION_FIELDS)
    payload = frame_to_trace_dict(_contract_frame())
    assert removed.isdisjoint(payload["observations"][0])


def test_frame_policy_and_observation_overflow() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _minimal_frame(schema_version="ias.audio_sensor_frame.v2")
    with pytest.raises(ValueError, match="channel_validity"):
        _minimal_frame(channel_validity={})
    with pytest.raises(ValueError, match="channel_validity"):
        _minimal_frame(channel_validity={"front": 1})
    changed_units = dict(FRAME_UNITS)
    changed_units["position"] = "ft"
    with pytest.raises(ValueError, match="stable unit values"):
        _minimal_frame(units=changed_units)
    with pytest.raises(ValueError, match="provenance"):
        _minimal_frame(provenance="private_capture")

    frame = _minimal_frame(start_time_s=1.234, end_time_s=1.334)
    assert frame.timestamp_ms == 1_234
    with pytest.raises(TypeError, match="timestamp_ms"):
        _minimal_frame(timestamp_ms=99)
    observation = _contract_frame().observations[0]
    with pytest.raises(ValueError, match="exceeds max_observations"):
        replace(
            _contract_frame(),
            observations=(
                observation,
                replace(observation, observation_id="observation_2"),
            ),
        )


def test_trace_reader_rejects_v2_extra_fields_and_bad_timestamp() -> None:
    payload = frame_to_trace_dict(_contract_frame())
    payload["timestamp_ms"] += 1
    with pytest.raises(ValueError, match=r"round\(start_time_s"):
        frame_from_trace_dict(payload)

    payload = frame_to_trace_dict(_contract_frame())
    payload["schema_version"] = "ias.audio_sensor_frame.v2"
    with pytest.raises(ValueError, match="schema_version"):
        frame_from_trace_dict(payload)

    payload = frame_to_trace_dict(_contract_frame())
    payload["observations"][0]["source_id"] = "speaker"
    with pytest.raises(ValueError, match="extra=.*source_id"):
        frame_from_trace_dict(payload)


def _observation(**overrides: object) -> AudioObservation:
    values: dict[str, object] = {
        "observation_id": "observation_1",
        "origin": ObservationOrigin.SIGNAL_DERIVED,
        "detector_id": "fake_activity",
    }
    values.update(overrides)
    return AudioObservation(**values)


def _contract_frame() -> AudioSensorFrame:
    return AudioSensorFrame(
        frame_id="contract",
        frame_name="contract/frame",
        producer_id="analytic_acoustics",
        array_id="rig_front",
        channel_validity={"front": True, "right": True},
        array_pose=Pose3D(position_m=(0.0, 0.0, 0.0)),
        start_time_s=0.0,
        end_time_s=0.1,
        sample_rate_hz=48_000,
        frame_index=0,
        max_observations=1,
        observations=(
            _observation(
                doa=DoaEstimate(
                    estimated_bearing_deg=0.0,
                    candidate_bearing_deg=(0.0,),
                    bearing_confidence=1.0,
                )
            ),
        ),
    )


def _minimal_frame(**overrides: object) -> AudioSensorFrame:
    values: dict[str, object] = {
        "frame_id": "frame",
        "producer_id": "analytic_acoustics",
        "array_id": "rig",
        "channel_validity": {"front": True},
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
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            assert line.strip(), (path, line_number)
            yield path, json.loads(line)
