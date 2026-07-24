"""Focused fail-closed S4.5 active-handoff contract tests."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from isaac_audio_sensors.acquisition.s4_5_handoff import (
    ACTIVE_POINTER_PATH,
    EXACT_REPLAY_COMMAND,
    OUTPUT_PATH,
    ROUTING_TEXT,
    S45HandoffError,
    _handoff_payload,
    active_pointer_payload,
    load_contract,
    load_json,
    refresh_package_integrity,
    validate_active_pointer_payload,
    validate_closeout_routing_text,
    validate_handoff_package,
    validate_handoff_payload,
    validate_package_location_amendment_payload,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / OUTPUT_PATH


def _canonical() -> Path:
    if not (CANONICAL / "active_handoff.v1.json").is_file():
        pytest.skip("canonical S4.5 handoff has not been generated")
    return CANONICAL


def _profile() -> dict[str, Any]:
    contract = load_contract(ROOT)
    return load_json(ROOT / contract["active_profile"]["path"], label="profile")


def _valid_handoff() -> dict[str, Any]:
    return _handoff_payload(load_contract(ROOT))


def test_exactly_one_active_v2_profile_resolves() -> None:
    package = _canonical()
    pointer = load_json(ROOT / ACTIVE_POINTER_PATH, label="active pointer")
    assert pointer == active_pointer_payload(ROOT, package)
    assert pointer["active_profile_count"] == 1
    assert pointer["active_profile_version"] == "v2"
    assert pointer["historical_v1_active"] is False


def test_v1_is_rejected_as_active_s4_6_input() -> None:
    handoff = _valid_handoff()
    handoff["active_profile"]["profile_version"] = "v1"
    with pytest.raises(S45HandoffError, match="v1"):
        validate_handoff_payload(_profile(), handoff)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        (
            "active_profile_path",
            "outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json",
        ),
        ("active_profile_sha256", "0" * 64),
        ("active_profile_version", "v1"),
        ("active_profile_count", 2),
        ("status", "historical"),
    ),
)
def test_active_pointer_path_hash_identity_and_status_tampering_fails(
    field: str, value: Any
) -> None:
    package = _canonical()
    pointer = active_pointer_payload(ROOT, package)
    pointer[field] = value
    with pytest.raises(S45HandoffError, match="active pointer"):
        validate_active_pointer_payload(ROOT, package, pointer)


def test_v2_exposes_gains_polarities_and_separate_functional_binding() -> None:
    profile = _profile()
    handoff = _valid_handoff()
    validate_handoff_payload(profile, handoff)
    assert len(profile["fitted_model_parameters"]) == 6
    assert handoff["functional_channel_position_association"]["mapping"] == [
        {"channel_id": "ch0", "position_m": [-0.033, -0.033, 0.0]},
        {"channel_id": "ch1", "position_m": [-0.033, 0.033, 0.0]},
        {"channel_id": "ch2", "position_m": [0.033, 0.033, 0.0]},
        {"channel_id": "ch3", "position_m": [0.033, -0.033, 0.0]},
    ]


def test_geometry_is_machine_distinct_and_nominal_not_measured() -> None:
    profile = _profile()
    handoff = _valid_handoff()
    assert {row["status"] for row in profile["microphone_geometry"]} == {
        "nominal_not_measured"
    }
    binding = handoff["functional_channel_position_association"]
    assert binding["evidence_status"] == "supported_fitted_functional_evidence"
    assert binding["geometry_measurement_status"] == "nominal_not_measured"
    assert binding["not_measured_geometry"] is True
    assert binding["not_scalar_bearing_correction"] is True
    assert binding["not_mirrored_f_project"] is True


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        ("absent", lambda value: value.pop("functional_channel_position_association")),
        (
            "swapped",
            lambda value: (
                value["functional_channel_position_association"]["mapping"]
                .__getitem__(0)
                .__setitem__("position_m", [0.033, -0.033, 0.0])
            ),
        ),
        (
            "stale_status",
            lambda value: value["functional_channel_position_association"].__setitem__(
                "evidence_status", "nominal_not_measured"
            ),
        ),
        (
            "measured_geometry",
            lambda value: value["functional_channel_position_association"].__setitem__(
                "geometry_measurement_status", "measured"
            ),
        ),
        (
            "malformed",
            lambda value: value.__setitem__(
                "functional_channel_position_association", []
            ),
        ),
        (
            "channel_order",
            lambda value: value["active_profile"].__setitem__(
                "channel_order", ["ch1", "ch0", "ch2", "ch3"]
            ),
        ),
        (
            "array_frame",
            lambda value: value["active_profile"].__setitem__(
                "array_frame", "F_project"
            ),
        ),
        (
            "source_frame",
            lambda value: value["active_profile"].__setitem__("source_frame", "wrong"),
        ),
    ),
)
def test_absent_swapped_stale_malformed_or_incompatible_binding_fails_closed(
    case: str, mutate: Callable[[dict[str, Any]], Any]
) -> None:
    del case
    handoff = _valid_handoff()
    mutate(handoff)
    with pytest.raises(S45HandoffError):
        validate_handoff_payload(_profile(), handoff)


def test_retained_counts_are_internally_consistent() -> None:
    handoff = _valid_handoff()
    counts = handoff["retained_count_semantics"]
    assert counts["retained_scalar_profile_parameter_count"] == 6
    assert counts["retained_functional_association_count"] == 1
    assert counts["retained_scientific_component_count"] == 7
    assert counts["legacy_profile_metric_status"] == (
        "superseded_ambiguous_total_do_not_apply"
    )
    bad = copy.deepcopy(handoff)
    bad["retained_count_semantics"]["retained_scalar_profile_parameter_count"] = 7
    with pytest.raises(S45HandoffError, match="count"):
        validate_handoff_payload(_profile(), bad)


def test_relocation_amendment_and_closeout_routing_tampering_fail() -> None:
    amendment = load_json(
        ROOT / "configs/s4_5_corrective_01_package_location_amendment.v1.json"
    )
    validate_package_location_amendment_payload(amendment)
    amendment["package_root"] = "outputs/isaac_audio_sensors/S4/S4.5"
    with pytest.raises(S45HandoffError, match="package-location"):
        validate_package_location_amendment_payload(amendment)
    validate_closeout_routing_text(
        "# S4.5 supported functional fitting closeout\n\n"
        + ROUTING_TEXT
        + "\n## Final status\n"
    )
    with pytest.raises(S45HandoffError, match="routing"):
        validate_closeout_routing_text(
            ("# S4.5\n\n" + ROUTING_TEXT).replace(
                "S4.5_active_profile.v1.json", "calibration_profile.v1.json"
            )
        )


def _mutate_pointer_to_v1(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["active_profile"]["profile_version"] = "v1"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _remove_binding(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    del payload["functional_channel_position_association"]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _swap_mapping(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["functional_channel_position_association"]["mapping"][0]["position_m"] = [
        0.033,
        -0.033,
        0.0,
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _change_count(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["retained_count_semantics"]["retained_scalar_profile_parameter_count"] = 7
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _stale_replay(package: Path) -> None:
    path = package / "reproduction.v1.json"
    payload = load_json(path)
    payload["command"] = (
        "python3 scripts/validate_s4_5_corrective.py "
        "--evidence outputs/isaac_audio_sensors/S4/S4.5/correctives/"
        "s4_5_corrective_01"
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _change_profile_hash(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["active_profile"]["sha256"] = "0" * 64
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _change_binding_status(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["functional_channel_position_association"]["evidence_status"] = (
        "unsupported"
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _change_channel_order(package: Path) -> None:
    path = package / "active_handoff.v1.json"
    payload = load_json(path)
    payload["active_profile"]["channel_order"] = ["ch1", "ch0", "ch2", "ch3"]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _remove_relocation_provenance(package: Path) -> None:
    path = package / "provenance.v1.json"
    payload = load_json(path)
    del payload["package_location_amendment"]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _change_closeout_profile(package: Path) -> None:
    path = package / "closeout_amendment.v1.json"
    payload = load_json(path)
    payload["active_profile_path"] = (
        "outputs/isaac_audio_sensors/S4/S4.5/calibration_profile.v1.json"
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


@pytest.mark.parametrize(
    "mutator",
    (
        _mutate_pointer_to_v1,
        _remove_binding,
        _swap_mapping,
        _change_count,
        _stale_replay,
        _change_profile_hash,
        _change_binding_status,
        _change_channel_order,
        _remove_relocation_provenance,
        _change_closeout_profile,
    ),
    ids=(
        "v1",
        "missing_binding",
        "swapped_mapping",
        "count",
        "stale_replay",
        "profile_hash",
        "binding_status",
        "channel_order",
        "relocation_provenance",
        "closeout_profile",
    ),
)
def test_validator_rejects_rechecksummed_handoff_tampering(
    tmp_path: Path, mutator: Callable[[Path], None]
) -> None:
    package = tmp_path / "package"
    shutil.copytree(_canonical(), package)
    mutator(package)
    refresh_package_integrity(package)
    result = validate_handoff_package(ROOT, package)
    assert result["status"] == "failed"
    assert not any("checksum mismatch" in issue for issue in result["issues"])
    assert any("semantic regeneration" in issue for issue in result["issues"])


def test_exact_recorded_replay_command_is_byte_identical(
    pre_s4_6_root: Path,
) -> None:
    canonical = pre_s4_6_root / OUTPUT_PATH
    reproduction = load_json(canonical / "reproduction.v1.json")
    assert reproduction["command"] == EXACT_REPLAY_COMMAND
    result = subprocess.run(
        EXACT_REPLAY_COMMAND.split(),
        cwd=pre_s4_6_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["byte_identical"] is True
    assert payload["holdout_observations_accessed"] == 0


def test_existing_scientific_values_and_package_hashes_remain_unchanged() -> None:
    assert load_contract(ROOT)["active_profile"]["sha256"] == (
        "944dda1df3a2de720ab86a3f07f0ea545aa9abca676a003423b29221ca0d47c8"
    )
    assert load_contract(ROOT)["historical_profile"]["sha256"] == (
        "32dfcbb90a95c342226b81a9ed94a8b4fa6550a1bfab783e1f27538b548bb622"
    )
    profile = _profile()
    values = [
        (row["name"], row["estimate"]["value"])
        for row in profile["fitted_model_parameters"]
    ]
    assert values == [
        ("relative_gain_db.ch1", -1.6020864972841506),
        ("polarity.ch1", 1.0),
        ("relative_gain_db.ch2", -1.2795753710282032),
        ("polarity.ch2", 1.0),
        ("relative_gain_db.ch3", -1.2135862725210074),
        ("polarity.ch3", 1.0),
    ]
