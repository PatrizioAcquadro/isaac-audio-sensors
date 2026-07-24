"""Frozen static contract checks for the S4.7 acceptance preregistration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_7_holdout_acceptance.v1.json"
SCHEMA = ROOT / "docs/schemas/s4_7_holdout_acceptance.v1.schema.json"
SPEC = ROOT / "docs/development/specs/s4_holdout_acceptance.md"
AMENDMENT = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.4/amendments"
    / "s4_4_data_expansion_amendment_03"
)
SEAL = AMENDMENT / "holdout_seal.v1.json"
PARTITION = AMENDMENT / "manifests/prospective_holdout_manifest.v1.json"
SESSION = AMENDMENT / "manifests/sessions/prospective_holdout.json"
HISTORICAL_SEAL = ROOT / "outputs/isaac_audio_sensors/S4/S4.4/holdout_seal.json"

REQUIRED_CONTRACT_FIELDS = {
    "method",
    "reference",
    "units",
    "uncertainty",
    "aggregation",
    "exclusions",
    "missing",
    "applicability",
    "limitations",
}
REQUIRED_METRIC_COVERAGE = {
    "bearing_doa_error",
    "sector_accuracy",
    "candidate_bearing",
    "tdoa",
    "capture_to_frame_latency",
    "frame_to_adapter_latency",
    "acquisition_analysis_failures",
    "channel_presence_order_health",
    "major_polarity_anomaly",
    "confidence",
    "ambiguity",
    "abstention",
    "coarse_audio_video_association",
    "sim_versus_real",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_configuration_validates_against_its_own_schema() -> None:
    import jsonschema

    jsonschema.validate(_json(CONFIG), _json(SCHEMA))
    config = _json(CONFIG)
    assert config["schema"] == "ias.s4_7.holdout_acceptance_config.v1"
    assert config["status"] == "frozen"
    assert config["spec_path"] == SPEC.relative_to(ROOT).as_posix()
    assert SPEC.is_file()


def test_criteria_are_bound_to_the_only_unopened_seal() -> None:
    binding = _json(CONFIG)["holdout_binding"]
    seal = _json(SEAL)

    assert binding["seal_path"] == SEAL.relative_to(ROOT).as_posix()
    assert binding["seal_file_sha256"] == _sha256(SEAL)
    assert binding["seal_payload_sha256"] == seal["seal_payload_sha256"]
    assert binding["seal_schema"] == seal["schema"]
    assert binding["partition_manifest_sha256"] == _sha256(PARTITION)
    assert binding["session_manifest_sha256"] == _sha256(SESSION)
    assert binding["planned_take_count"] == len(seal["planned_take_ids"]) == 47
    assert binding["scientifically_opened"] is False
    assert seal["scientifically_opened"] is False
    assert seal["scientific_outputs_included"] is False


def test_historical_holdout_is_excluded_from_gating() -> None:
    excluded = _json(CONFIG)["holdout_binding"]["excluded_historical_holdout"]
    assert excluded["seal_path"] == HISTORICAL_SEAL.relative_to(ROOT).as_posix()
    assert excluded["seal_file_sha256"] == _sha256(HISTORICAL_SEAL)
    assert excluded["gating_power"] == "none"
    assert excluded["retained_as"] == "archived_diagnostic_evidence"


def test_strata_partition_the_sealed_takes_exactly() -> None:
    config = _json(CONFIG)
    strata = config["strata"]
    session = _json(SESSION)
    seal = _json(SEAL)

    assert len({item["stratum_id"] for item in strata}) == len(strata) == 5
    assert sum(item["take_count"] for item in strata) == 47
    assert sorted(seal["planned_take_ids"]) == sorted(
        take["planned_take_id"] for take in session["takes"]
    )

    observed: dict[str, int] = {}
    for take in session["takes"]:
        category = take["category"]
        gain = take["playback_gain"]
        if category == "silence":
            stratum = "D_silence"
        elif category == "audio_video":
            stratum = "E_impact_audio_video"
        elif category == "controlled":
            stratum = "A_controlled_boundary_sweep"
        else:
            stratum = "B_center_nominal_level" if gain == 0.75 else "C_center_low_level"
        observed[stratum] = observed.get(stratum, 0) + 1

    assert observed == {item["stratum_id"]: item["take_count"] for item in strata}


def test_stratum_bearings_match_the_sealed_manifest() -> None:
    strata = {item["stratum_id"]: item for item in _json(CONFIG)["strata"]}
    session = _json(SESSION)
    bearings: dict[str, set[float]] = {}
    for take in session["takes"]:
        bearing = take["group_identity"]["target_bearing_deg_f_project"]
        if bearing is None:
            continue
        key = "boundary" if take["category"] == "controlled" else "center"
        bearings.setdefault(key, set()).add(float(bearing))

    assert (
        set(strata["A_controlled_boundary_sweep"]["target_bearings_deg_f_project"])
        == bearings["boundary"]
    )
    for stratum_id in ("B_center_nominal_level", "C_center_low_level"):
        assert (
            set(strata[stratum_id]["target_bearings_deg_f_project"])
            == bearings["center"]
        )


def test_sector_accuracy_is_gated_only_on_the_sector_center_stratum() -> None:
    config = _json(CONFIG)
    strata = {item["stratum_id"]: item for item in config["strata"]}

    assert strata["A_controlled_boundary_sweep"]["sector_geometry"] == (
        "sector_boundary"
    )
    assert strata["A_controlled_boundary_sweep"]["sector_accuracy_gated"] is False
    assert strata["B_center_nominal_level"]["sector_geometry"] == "sector_center"
    assert strata["B_center_nominal_level"]["sector_accuracy_gated"] is True

    gated = {
        stratum
        for criterion in config["criteria"]
        if criterion["metric"] == "sector_accuracy"
        for stratum in criterion["strata"]
    }
    assert gated == {"B_center_nominal_level"}


def test_every_criterion_states_complete_metric_semantics() -> None:
    criteria = _json(CONFIG)["criteria"]
    identifiers = [criterion["criterion_id"] for criterion in criteria]
    assert len(identifiers) == len(set(identifiers))

    for criterion in criteria:
        label = criterion["criterion_id"]
        assert set(criterion["metric_contract"]) == REQUIRED_CONTRACT_FIELDS, label
        assert all(criterion["metric_contract"].values()), label
        assert criterion["decision_rationale"].strip(), label
        assert criterion["failure_logic"].strip(), label
        assert criterion["tier"] in {"readiness", "stretch"}, label
        assert criterion["gating"] is (criterion["tier"] == "readiness"), label
        assert isinstance(criterion["threshold"], (int, float)), label


def test_required_metrics_all_carry_at_least_one_gating_criterion() -> None:
    criteria = _json(CONFIG)["criteria"]
    gating_metrics = {
        criterion["metric"] for criterion in criteria if criterion["gating"]
    }
    assert gating_metrics >= REQUIRED_METRIC_COVERAGE


def test_robustness_is_declared_not_evaluable_with_no_gating_criterion() -> None:
    config = _json(CONFIG)
    strata_ids = {item["stratum_id"] for item in config["strata"]}

    for criterion in config["criteria"]:
        for stratum in criterion["strata"]:
            assert stratum in strata_ids or stratum == "all"

    conditions = config["not_evaluable"]["conditions"]
    assert "alternate rooms" in conditions
    assert "occlusion" in conditions
    assert "source overlap" in conditions
    assert config["envelope"]["claimed_envelope"] == (
        "controlled_source_single_room_single_mount"
    )
    assert config["envelope"]["room_ids"] == ["WANG_2022_DESK_NEAR_ENTRANCE"]


def test_failure_denominator_uses_the_planned_take_count() -> None:
    criteria = {
        criterion["criterion_id"]: criterion for criterion in _json(CONFIG)["criteria"]
    }
    failure = criteria["take_failure_rate"]
    assert failure["denominator"] == {"basis": "planned_takes", "expected_count": 47}
    assert "planned count" in failure["metric_contract"]["aggregation"]


def test_freeze_declares_no_holdout_access_and_no_opening_workflow() -> None:
    config = _json(CONFIG)
    assert config["authority"]["opens_holdout_observations"] is False
    assert config["authority"]["implements_holdout_opening_workflow"] is False
    assert config["authority"]["holdout_opening_belongs_to"] == "S4.8"
    assert config["authority"]["interlock_artifact_schema"] == (
        "ias.s4_7.holdout_acceptance.v1"
    )
    assert config["phase_boundary"]["holdout_observations_accessed"] == 0
    assert config["phase_boundary"]["holdout_access_grant_created"] is False
    assert config["phase_boundary"]["s4_8_started"] is False


def test_amendment_03_holdout_opening_workflow_remains_unimplemented() -> None:
    closeout = _json(AMENDMENT / "holdout_closeout.v1.json")
    policy = _json(AMENDMENT / "access_policy.v1.json")
    assert closeout["future_holdout_opening_workflow_implemented"] is False
    assert policy["future_S4.7_or_S4.8_opening_workflow_implemented"] is False


def test_public_profile_schema_is_unchanged() -> None:
    schema = ROOT / "docs/schemas/audio_calibration_profile.v1.schema.json"
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == (
        "fb56c9024bfa16ce25a999ed8e2552ab19189459f44801f33edd9f0d75d1ff46"
    )
