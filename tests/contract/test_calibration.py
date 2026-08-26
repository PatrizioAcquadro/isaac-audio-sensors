from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.calibration_profile import check_profile_compatibility
from isaac_audio_sensors.core.io.calibration import (
    calibration_profile_from_dict,
    calibration_profile_to_dict,
    read_calibration_profile,
    write_calibration_profile,
)
from isaac_audio_sensors.core.types import MicrophoneArraySpec, MicrophoneSpec

FIXTURE_DIR = Path("examples/calibration")

INVALID_MESSAGES = {
    "channel_order": "channel_order must not contain duplicates",
    "checksum": "64 lowercase hexadecimal",
    "coordinate_frame": "geometry frame",
    "profile_id": "profile_id",
    "path": "relative POSIX path",
    "sample_rate": "sample_rate_hz must be positive",
    "schema_version": "schema_version",
    "timestamp": "UTC timestamp",
    "units": "canonical unit values",
    "unmeasured_value": "must be null",
}


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


@pytest.mark.parametrize(("case", "message"), sorted(INVALID_MESSAGES.items()))
def test_invalid_calibration_payloads_fail_closed(case, message):
    with pytest.raises(ValueError, match=message):
        calibration_profile_from_dict(_invalid_profile(case))


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
        microphones=_microphones(),
        sample_rate_hz=48_000,
    )


def _invalid_profile(case: str) -> dict:
    payload = json.loads(
        (FIXTURE_DIR / "respeaker_xvf3800_nominal.v1.json").read_text()
    )
    mutations = {
        "channel_order": lambda value: value["channel_order"].__setitem__(1, "ch0"),
        "checksum": lambda value: value["raw_measurements"].append(
            {"path": "raw/data.json", "sha256": "bad"}
        ),
        "coordinate_frame": lambda value: value["microphone_geometry"][0].__setitem__(
            "frame", "other_frame"
        ),
        "profile_id": lambda value: value.__setitem__("profile_id", "bad id"),
        "path": lambda value: value.__setitem__(
            "reference_rig_bom_path", "../bom.json"
        ),
        "sample_rate": lambda value: value.__setitem__("sample_rate_hz", 0),
        "schema_version": lambda value: value.__setitem__(
            "schema_version", "ias.audio_calibration_profile.v2"
        ),
        "timestamp": lambda value: value.__setitem__("created_at", "2026-01-01"),
        "units": lambda value: value["units"].__setitem__("gain", "linear"),
        "unmeasured_value": lambda value: value["channels"][0][
            "self_noise_db_spl"
        ].__setitem__("value", 20.0),
    }
    result = deepcopy(payload)
    mutations[case](result)
    return result
