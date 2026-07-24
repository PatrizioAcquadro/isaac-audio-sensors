"""Frozen static contract checks for S4.6 profile application."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_6_profile_application.v1.json"
MATRIX = ROOT / "examples/s4_6/incompatible_fixture_matrix.v1.json"
POINTER = ROOT / "outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json"
HANDOFF = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.5_handoff_01/active_handoff.v1.json"
)
PROFILE = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_config_resolves_the_only_authorized_bundle() -> None:
    config = _json(CONFIG)
    pointer = _json(POINTER)
    profile = _json(PROFILE)
    context = config["application_context"]

    assert config["schema"] == "ias.s4_6.profile_application_config.v1"
    assert config["status"] == "frozen"
    assert config["mode"] == "apply"
    assert config["active_pointer_path"] == POINTER.relative_to(ROOT).as_posix()
    assert pointer["status"] == "active"
    assert pointer["active_profile_count"] == 1
    assert pointer["active_profile_version"] == "v2"
    assert pointer["historical_v1_active"] is False
    assert pointer["active_profile_sha256"] == _sha256(PROFILE)
    assert pointer["active_handoff_sha256"] == _sha256(HANDOFF)
    assert context["device_id"] == profile["device_id"]
    assert context["device_model"] == profile["device_model"]
    assert context["array_id"] == profile["array_id"]
    assert context["sample_rate_hz"] == profile["sample_rate_hz"]
    assert context["channel_order"] == profile["channel_order"]
    assert context["array_frame"] == profile["array_frame"]
    assert context["source_frame"] == profile["source_frame"]
    assert context["coordinate_convention"] == profile["coordinate_convention"]
    assert context["environment_tags"] == (
        profile["applicability_limits"]["environment_tags"]
    )


def test_functional_association_identity_and_nominal_status_are_frozen() -> None:
    config = _json(CONFIG)
    handoff = _json(HANDOFF)
    context = config["application_context"]
    association = handoff["functional_channel_position_association"]
    mapping_bytes = json.dumps(
        association["mapping"], sort_keys=True, separators=(",", ":")
    ).encode()

    assert context["mount_fixture_id"] in context["environment_tags"]
    assert context["functional_association_id"] == (
        association["selected_hypothesis_id"]
    )
    assert context["functional_association_frame"] == association["frame"]
    assert context["geometry_measurement_status"] == (
        association["geometry_measurement_status"]
    )
    assert context["functional_association_sha256"] == (
        hashlib.sha256(mapping_bytes).hexdigest()
    )
    assert association["not_measured_geometry"] is True
    assert association["not_physically_traced_wiring"] is True
    assert association["not_scalar_bearing_correction"] is True
    assert association["not_mirrored_f_project"] is True


def test_supported_fields_and_corrected_retained_counts_are_exact() -> None:
    handoff = _json(HANDOFF)
    assert handoff["supported_for_later_application"] == [
        "channels.ch1.gain_db",
        "channels.ch2.gain_db",
        "channels.ch3.gain_db",
        "channels.ch1.polarity",
        "channels.ch2.polarity",
        "channels.ch3.polarity",
        "functional_channel_position_association",
    ]
    assert handoff["retained_count_semantics"] == {
        "legacy_profile_metric_name": "retained_parameter_count",
        "legacy_profile_metric_status": "superseded_ambiguous_total_do_not_apply",
        "legacy_profile_metric_value": 7,
        "retained_functional_association_count": 1,
        "retained_scalar_profile_parameter_count": 6,
        "retained_scientific_component_count": 7,
    }


def test_incompatible_fixture_matrix_covers_static_contract_failures() -> None:
    matrix = _json(MATRIX)
    case_ids = [case["case_id"] for case in matrix["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert {
        "swapped_channel_order",
        "wrong_channel_count",
        "wrong_device_identity",
        "wrong_array_identity",
        "wrong_sample_rate",
        "wrong_array_frame",
        "wrong_source_frame",
        "wrong_coordinate_convention",
        "wrong_mount_fixture",
        "wrong_geometry_identity",
        "wrong_environment",
        "historical_v1_selection",
        "inactive_configuration",
        "unknown_mode",
        "unsafe_parent_path",
        "unsafe_absolute_path",
    } == set(case_ids)


def test_public_profile_schema_is_unchanged() -> None:
    schema = ROOT / "docs/schemas/audio_calibration_profile.v1.schema.json"
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == (
        "fb56c9024bfa16ce25a999ed8e2552ab19189459f44801f33edd9f0d75d1ff46"
    )
