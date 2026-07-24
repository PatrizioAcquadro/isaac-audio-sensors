"""Focused S4.5 fitting, access-control, and profile tests."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from isaac_audio_sensors.acquisition.s4_5 import (
    S45_CONFIG,
    FitEvidenceAccessor,
    FitObservation,
    S45Error,
    _attempt_roots,
    _validate_attempt,
    build_partial_profile,
    detect_later_phase_artifacts,
    extract_fit_observations,
    fit_parameter_decisions,
    load_fitting_contract,
    load_json,
    pretty_json,
    safe_relative,
    synthetic_recovery,
    validate_profile_policy,
    validate_s4_4_preservation,
)

ROOT = Path(__file__).resolve().parents[1]
MACHINE_FIT_A = (
    ROOT / "dataset/S4.4/amendments/s4_4_data_expansion_amendment_02/attempts"
)


def _accessor() -> FitEvidenceAccessor:
    if not MACHINE_FIT_A.is_dir():
        pytest.skip("machine-local sealed S4.4 fit evidence is unavailable")
    return FitEvidenceAccessor(ROOT)


def _synthetic_observations() -> tuple[FitObservation, ...]:
    rows = []
    bearings = (0.0, 45.0, 90.0, 135.0, 225.0, 315.0)
    for session_index, session in enumerate(("fit_a", "fit_b")):
        for index in range(12):
            jitter = ((index % 3) - 1) * 0.02
            target = bearings[index % len(bearings)]
            rows.append(
                FitObservation(
                    planned_take_id=f"{session}_{index:03d}",
                    session_id=session,
                    group_id=f"{session}_group_{index:03d}",
                    category="controlled",
                    target_bearing_deg=target,
                    gain_db=(0.0, 2.0 + jitter, -1.5 + jitter, 0.8 - jitter),
                    delay_samples=(
                        0.0,
                        1.0 + jitter,
                        -0.75 + jitter,
                        0.5 - jitter,
                    ),
                    correlation_sign=(1, 1, 1, -1),
                    srp_bearing_deg=(target - 10.0) % 360.0,
                    srp_confidence=0.8 - 0.01 * session_index,
                )
            )
    return tuple(rows)


def test_contract_is_frozen_and_all_bound_hashes_validate() -> None:
    contract = load_fitting_contract(ROOT / S45_CONFIG, ROOT)
    assert contract["schema"] == "ias.s4_5.fitting_contract.v1"
    assert contract["purposes"] == ["S4.5_fit", "S4.5_validation"]
    assert contract["fit_sessions"] == ["fit_a", "fit_b"]


def test_synthetic_recovery_passes_every_implemented_candidate() -> None:
    contract = load_fitting_contract(ROOT / S45_CONFIG, ROOT)
    result = synthetic_recovery(contract)
    for candidate in (
        "relative_gain",
        "relative_delay",
        "polarity",
        "bearing_correction",
        "confidence_calibration",
        "relative_timing",
    ):
        assert result[candidate]["status"] == "passed", result[candidate]


def test_grouped_fit_only_validation_uncertainty_and_decisions() -> None:
    contract = load_fitting_contract(ROOT / S45_CONFIG, ROOT)
    synthetic = synthetic_recovery(contract)
    result = fit_parameter_decisions(_synthetic_observations(), contract, synthetic)
    assert result["status"] == "passed"
    assert result["holdout_observations"] == 0
    retained = {
        (item["candidate"], item.get("channel_id"))
        for item in result["decisions"]
        if item["retained"]
    }
    assert ("relative_gain", "ch1") in retained
    assert ("relative_delay", "ch2") in retained
    assert ("polarity", "ch3") in retained
    assert ("bearing_correction", None) in retained
    for item in result["decisions"]:
        if item["candidate"] in {"relative_gain", "relative_delay"}:
            assert item["group_count"] == item["observation_count"]
            assert item["uncertainty_95_half_width"] >= 0.0


def test_partial_profile_round_trip_schema_and_unsupported_policy() -> None:
    contract = load_fitting_contract(ROOT / S45_CONFIG, ROOT)
    decisions = fit_parameter_decisions(
        _synthetic_observations(), contract, synthetic_recovery(contract)
    )
    inventory = {
        "session_counts": {"fit_a": 12, "fit_b": 12},
        "records": [],
    }
    profile = build_partial_profile(contract, inventory, decisions)
    assert profile["schema_version"] == "ias.audio_calibration_profile.v1"
    assert profile["holdout_metrics"] == []
    assert validate_profile_policy(profile)["status"] == "passed"
    assert all(
        geometry["status"] == "nominal_not_measured"
        for geometry in profile["microphone_geometry"]
    )


def test_profile_policy_rejects_holdout_metrics_and_unsupported_values() -> None:
    profile = {
        "holdout_metrics": [{"name": "leak", "value": 1.0, "unit": "x"}],
        "fitted_model_parameters": [
            {
                "name": "absolute_spl",
                "unit": "dB_SPL",
                "estimate": {"status": "measured", "value": 80.0},
            }
        ],
        "channels": [
            {
                "frequency_response": {
                    "status": "measured",
                    "points": [{"frequency_hz": 1000.0, "magnitude_db": 0.0}],
                    "uncertainty_db": 0.1,
                },
                "self_noise_db_spl": {"status": "measured", "value": 20.0},
            }
        ],
    }
    result = validate_profile_policy(profile)
    assert result["status"] == "failed"
    assert "holdout_metrics must be empty" in result["issues"]
    assert "unsupported field contains a fitted value" in result["issues"]


@pytest.mark.parametrize(
    "value",
    ("/absolute/path", "../escape", "safe/../../escape", "C:\\unsafe"),
)
def test_unsafe_or_unknown_paths_fail_closed(value: str) -> None:
    with pytest.raises(S45Error, match="unsafe path"):
        safe_relative(value, "fixture")


def test_malformed_json_record_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(S45Error, match="must contain one object"):
        load_json(path)
    path.write_text("{broken\n", encoding="utf-8")
    with pytest.raises(S45Error, match="cannot read"):
        load_json(path)


def test_unknown_purpose_identity_and_holdout_access_fail_closed() -> None:
    accessor = _accessor()
    fit_id = sorted(accessor.fit_ids)[0]
    holdout_id = sorted(accessor.holdout_ids)[0]
    assert accessor.authorize(fit_id, "S4.5_fit")["mode"] == "fit_only"
    with pytest.raises(S45Error, match="unknown purpose"):
        accessor.authorize(fit_id, "tune")
    with pytest.raises(S45Error, match="unknown planned take"):
        accessor.authorize("unknown", "S4.5_fit")
    with pytest.raises(S45Error, match="holdout access denied"):
        accessor.authorize(holdout_id, "S4.5_validation")


def test_fit_inventory_is_complete_grouped_and_holdout_free() -> None:
    accessor = _accessor()
    inventory, records = accessor.inventory(purpose="S4.5_validation")
    assert inventory["status"] == "passed"
    assert inventory["valid_fit_cells"] == 102
    assert inventory["retained_attempts"] == 104
    assert inventory["retained_failures"] == 2
    assert inventory["replacements"] == 2
    assert inventory["holdout_attempts_accessed"] == 0
    assert len(records) == 102
    assert {record.session_id for record in records} == {"fit_a", "fit_b"}


def test_fit_observation_extraction_is_grouped_and_holdout_free() -> None:
    accessor = _accessor()
    _inventory, records = accessor.inventory(purpose="S4.5_validation")
    measurements, observations = extract_fit_observations(accessor, records)
    assert measurements["status"] == "passed"
    assert measurements["holdout_observations"] == 0
    assert measurements["observation_count"] == len(observations)
    assert measurements["group_count"] == len(observations)
    assert {item.session_id for item in observations} == {"fit_a", "fit_b"}


def _copied_attempt(
    tmp_path: Path,
) -> tuple[dict, Path, set[str], Path]:
    accessor = _accessor()
    take = copy.deepcopy(accessor.takes[sorted(accessor.fit_ids)[0]])
    source_roots = _attempt_roots(ROOT, take)
    source_cell = source_roots[0].parent
    target_cell = tmp_path / source_cell.relative_to(ROOT)
    target_cell.parent.mkdir(parents=True)
    shutil.copytree(source_cell, target_cell)
    attempt = target_cell / source_roots[-1].name
    expected = take["expected_artifact_paths"]
    prefix = source_cell.relative_to(ROOT).as_posix()
    target_prefix = target_cell.relative_to(tmp_path).as_posix()
    for key, value in list(expected.items()):
        if isinstance(value, str) and value.startswith(prefix):
            expected[key] = target_prefix + value[len(prefix) :]
    allowed = {
        load_json(attempt / "attempt_contract.json")["precollection_seal_sha256"]
    }
    return take, attempt, allowed, tmp_path


def test_wrong_group_fails_closed(tmp_path: Path) -> None:
    take, attempt, allowed, repo = _copied_attempt(tmp_path)
    planned = attempt.parent / "planned_cell.json"
    value = load_json(planned)
    value["group_id"] = "wrong_group"
    planned.write_text(pretty_json(value), encoding="utf-8")
    with pytest.raises(S45Error, match="wrong group"):
        _validate_attempt(repo, take, attempt, allowed_seal_hashes=allowed)


def test_altered_hash_fails_closed(tmp_path: Path) -> None:
    take, attempt, allowed, repo = _copied_attempt(tmp_path)
    wav = attempt / "raw/respeaker_audio.wav"
    with wav.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(S45Error, match="altered hash"):
        _validate_attempt(repo, take, attempt, allowed_seal_hashes=allowed)


def test_provenance_mismatch_fails_closed(tmp_path: Path) -> None:
    take, attempt, allowed, repo = _copied_attempt(tmp_path)
    contract_path = attempt / "attempt_contract.json"
    contract = load_json(contract_path)
    contract["precollection_seal_sha256"] = "0" * 64
    contract_path.write_text(pretty_json(contract), encoding="utf-8")
    with pytest.raises(S45Error, match="provenance seal mismatch"):
        _validate_attempt(repo, take, attempt, allowed_seal_hashes=allowed)


def test_wrong_attempt_path_fails_closed(tmp_path: Path) -> None:
    accessor = _accessor()
    take = copy.deepcopy(accessor.takes[sorted(accessor.fit_ids)[0]])
    take["expected_artifact_paths"]["attempt_01_root"] = "../holdout"
    with pytest.raises(S45Error, match="unsafe path"):
        _attempt_roots(tmp_path, take)


def test_deterministic_json_is_byte_identical() -> None:
    payload = {"b": [2, 1], "a": {"z": False}}
    first = pretty_json(payload).encode()
    second = pretty_json(copy.deepcopy(payload)).encode()
    assert first == second


def test_s4_6_or_later_artifact_detection(tmp_path: Path) -> None:
    path = tmp_path / "outputs/isaac_audio_sensors/S4/S4.6"
    path.mkdir(parents=True)
    (path / "application.json").write_text("{}\n", encoding="utf-8")
    assert detect_later_phase_artifacts(tmp_path) == [
        "outputs/isaac_audio_sensors/S4/S4.6"
    ]


def test_s4_4_preservation_and_holdout_unopened(pre_s4_6_root: Path) -> None:
    if not MACHINE_FIT_A.is_dir():
        pytest.skip("machine-local sealed S4.4 evidence is unavailable")
    result = validate_s4_4_preservation(pre_s4_6_root)
    assert result["status"] == "passed", result
    assert result["holdout_scientifically_opened"] is False
    assert result["s4_8_grants"] == []
    assert result["later_phase_artifacts"] == []
