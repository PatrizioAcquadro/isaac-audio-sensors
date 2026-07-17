"""Contract tests for ``ias.audio_calibration_profile.v1``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.calibration_profile import check_profile_compatibility
from isaac_audio_sensors.core.constants import CALIBRATION_PROFILE_SCHEMA_VERSION
from isaac_audio_sensors.core.io.calibration import (
    calibration_profile_from_dict,
    calibration_profile_to_dict,
    read_calibration_profile,
    write_calibration_profile,
)
from isaac_audio_sensors.core.schema import audio_calibration_profile_json_schema
from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec

SCHEMA_PATH = Path("docs/schemas/audio_calibration_profile.v1.schema.json")
FIXTURE_DIR = Path("examples/calibration")

INVALID_MESSAGES = {
    "invalid_channel_order_duplicate.json": "channel_order must not contain duplicates",
    "invalid_checksum_format.json": "64 lowercase hexadecimal",
    "invalid_coordinate_frame.json": "geometry frame",
    "invalid_id_whitespace.json": "profile_id",
    "invalid_path_parent_traversal.json": "relative POSIX path",
    "invalid_sample_rate.json": "sample_rate_hz must be positive",
    "invalid_schema_version.json": "schema_version",
    "invalid_timestamp_not_utc.json": "UTC timestamp",
    "invalid_units_gain.json": "canonical unit values",
    "invalid_unmeasured_has_value.json": "must be null",
}


def test_generated_schema_matches_checked_in_schema_exactly():
    generated = (
        json.dumps(audio_calibration_profile_json_schema(), indent=2, sort_keys=True)
        + "\n"
    )

    assert SCHEMA_PATH.read_text(encoding="utf-8") == generated
    assert (
        audio_calibration_profile_json_schema()["properties"]["schema_version"][
            "const"
        ]
        == CALIBRATION_PROFILE_SCHEMA_VERSION
    )


def test_nominal_fixture_is_explicit_and_round_trips(tmp_path):
    path = FIXTURE_DIR / "respeaker_xvf3800_nominal.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    profile = read_calibration_profile(path)

    assert profile.evidence_status == "nominal_not_measured"
    assert profile.unmeasured_fields
    assert all(
        geometry.status == "nominal_not_measured"
        for geometry in profile.microphone_geometry
    )
    assert calibration_profile_to_dict(profile) == payload
    assert calibration_profile_from_dict(payload) == profile
    written = write_calibration_profile(profile, tmp_path / path.name)
    assert written.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("filename", "message"), sorted(INVALID_MESSAGES.items()))
def test_invalid_calibration_fixtures_fail_closed(filename, message):
    with pytest.raises(ValueError, match=message):
        read_calibration_profile(FIXTURE_DIR / "invalid" / filename)


def test_profile_compatibility_accepts_an_exact_array():
    profile = read_calibration_profile(
        FIXTURE_DIR / "respeaker_xvf3800_nominal.v1.json"
    )
    check_profile_compatibility(profile, _array_spec())


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("array_id", "array identity"),
        ("device_id", "device identity"),
        ("channel_count", "channel count"),
        ("channel_order", "channel order"),
        ("sample_rate", "sample rate"),
        ("coordinate_convention", "coordinate frame convention"),
        ("array_frame", "array frame"),
    ),
)
def test_profile_compatibility_rejects_each_mismatch(case, message):
    profile = read_calibration_profile(
        FIXTURE_DIR / "respeaker_xvf3800_nominal.v1.json"
    )
    compatible = {
        "array_id": profile.array_id,
        "device_id": profile.device_id,
        "microphones": _microphones(),
        "sample_rate_hz": profile.sample_rate_hz,
        "coordinate_convention": profile.coordinate_convention,
        "array_frame": profile.array_frame,
    }
    overrides = {
        "array_id": {"array_id": "other_array"},
        "device_id": {"device_id": "other_device"},
        "channel_count": {"microphones": _microphones()[:3]},
        "channel_order": {"microphones": tuple(reversed(_microphones()))},
        "sample_rate": {"sample_rate_hz": 44_100},
        "coordinate_convention": {"coordinate_convention": "legacy"},
        "array_frame": {"array_frame": "other_frame"},
    }
    compatible.update(overrides[case])

    with pytest.raises(ValueError, match=message):
        check_profile_compatibility(profile, SimpleNamespace(**compatible))


def _microphones() -> tuple[MicrophoneSpec, ...]:
    return tuple(
        MicrophoneSpec(mic_id=f"ch{index}", relative_position_m=(0.0, 0.0, 0.0))
        for index in range(4)
    )


def _array_spec() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="xvf3800_array",
        prim_path="/World/Array",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
        microphones=_microphones(),
        sample_rate_hz=48_000,
    )
