from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import s4_8_recovery_02 as recovery

ROOT = Path(__file__).resolve().parents[1]


def test_amendment_02_additive_revision_is_schema_valid_and_frozen() -> None:
    amendment = recovery.load_amendment(ROOT)

    assert amendment["status"] == "frozen_for_precollection"
    assert amendment["supersedes"] == {
        "path": "configs/s4_8_recovery_amendment_02.v1.json",
        "sha256": "ec8e16eb1f7ff606db18a2fbb26e183d27ea95dacf8f43138b8e4a8dfe059542",
        "historical_terminal_bindings_preserved": True,
        "historical_protocol_modified": False,
    }
    historical = recovery._load_historical_amendment(ROOT, amendment)
    assert [run["run_id"] for run in historical["prior_terminal_runs"]] == [
        "original_s4_8",
        "recovery_amendment_01",
    ]
    revision = amendment["protocol_revision"]
    assert revision["thresholds_unchanged"] is True
    assert revision["criteria_roles_amended_for_squadbot"] is True
    assert revision["primary_direction_metric"] == (
        "squadbot_categorical_direction_accuracy"
    )
    assert revision["categorical_take_aggregation_bound"] is True
    assert revision["continuous_bearing_error_gating"] is False
    assert revision["denominators_recomputed_for_37_take_design"] is True
    assert revision["readiness_criterion_count"] == 23
    assert revision["stretch_criterion_count"] == 6
    assert revision["planned_take_count"] == 37
    assert revision["leakage_group_count"] == 15
    assert revision["source_checkpoint_bound_in_precollection_seal"] is True
    assert amendment["preliminary_readiness"]["required_take_count"] == 4
    assert (
        amendment["preliminary_readiness"][
            "required_before_final_protocol_freeze"
        ]
        is True
    )


def test_protocol_manifest_is_exactly_37_takes_in_required_order() -> None:
    amendment = recovery.load_amendment(ROOT)
    path = ROOT / amendment["protocol_revision"]["design_manifest_path"]
    manifest = s4_8.load_json(path)
    takes = manifest["take_order"]

    assert len(takes) == manifest["planned_take_count"] == 37
    assert manifest["stratum_counts"] == {
        "A_controlled_boundary_sweep": 24,
        "B_center_nominal_level": 4,
        "C_center_low_level": 4,
        "D_silence": 3,
        "E_impact_audio_video": 2,
    }
    direction = [
        take
        for take in takes
        if take["stratum_id"] == "A_controlled_boundary_sweep"
    ]
    assert [
        (take["bearing_deg"], take["repetition"])
        for take in direction
    ] == [
        (bearing, repetition)
        for bearing in recovery.DIRECTION_BEARINGS
        for repetition in (1, 2, 3)
    ]
    assert all(take["radius_m"] == 0.8 for take in direction)
    assert all(take["playback_gain"] == 0.75 for take in direction)
    product = [
        take for take in takes if take["stratum_id"] == "B_center_nominal_level"
    ]
    low = [
        take for take in takes if take["stratum_id"] == "C_center_low_level"
    ]
    assert [take["bearing_deg"] for take in product] == list(
        recovery.PRODUCT_BEARINGS
    )
    assert [take["bearing_deg"] for take in low] == list(
        recovery.PRODUCT_BEARINGS
    )
    assert [take["condition_id"] for take in product] == list(
        recovery.PRODUCT_CONDITIONS
    )
    assert all(take["playback_gain"] == 0.75 for take in product)
    assert all(take["playback_gain"] == 0.35 for take in low)
    assert all(take["condition_id"] == "low_volume" for take in low)
    assert manifest["modality_contract"]["E_impact_audio_video"] == [
        "six_channel_audio",
        "zed_video",
    ]
    assert manifest["modality_contract"]["impact_scenarios"] == [
        "impact_position_01",
        "impact_position_02",
    ]
    assert manifest["direction_repeatability_contract"]["same_session_required"] is True
    assert manifest["direction_contract"]["take_aggregation"] == (
        recovery.SQUADBOT_TAKE_AGGREGATION_CONTRACT
    )


@pytest.mark.parametrize(
    ("bearing", "expected"),
    [
        (0.0, "forward"),
        (44.999, "forward"),
        (45.0, "right"),
        (164.999, "right"),
        (165.0, "None"),
        (180.0, "None"),
        (194.999, "None"),
        (195.0, "left"),
        (314.999, "left"),
        (315.0, "forward"),
        (-45.0, "forward"),
        (405.0, "right"),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_squadbot_mapping_matches_adapter_boundaries_and_abstention(
    bearing: float | None,
    expected: str | None,
) -> None:
    assert recovery.bearing_to_squadbot_direction(bearing) == expected


def test_engineering_reclassification_keeps_bearing_diagnostic_only() -> None:
    result = recovery.reclassify_engineering_take(
        take_id="engineering_045",
        target_bearing_deg=45.0,
        estimated_bearing_deg=88.0,
        bearing_absolute_error_deg=43.0,
    )

    assert result["expected_direction"] == "right"
    assert result["observed_direction"] == "right"
    assert result["categorical_correct"] is True
    assert result["categorical_metric_role"] == "primary_gating"
    assert result["categorical_aggregation"] == (
        recovery.SQUADBOT_TAKE_AGGREGATION_CONTRACT
    )
    assert result["bearing_absolute_error_deg"] == 43.0
    assert result["continuous_bearing_metric_role"] == "diagnostic_non_gating"


@pytest.mark.parametrize(
    ("target", "estimated", "take_failed", "expected"),
    [
        (0.0, None, False, False),
        (180.0, None, False, True),
        (180.0, 182.0, False, True),
        (180.0, 90.0, False, False),
        (180.0, None, True, False),
        (0.0, 358.0, True, False),
    ],
)
def test_take_aggregation_unavailable_and_failure_precedence(
    target: float,
    estimated: float | None,
    take_failed: bool,
    expected: bool,
) -> None:
    result = recovery.reclassify_engineering_take(
        take_id="engineering_take",
        target_bearing_deg=target,
        estimated_bearing_deg=estimated,
        bearing_absolute_error_deg=None,
        take_failed=take_failed,
    )

    assert result["categorical_correct"] is expected
    assert result["take_failed"] is take_failed


def test_protocol_manifest_rejects_nonconsecutive_or_dependent_takes() -> None:
    amendment = recovery.load_amendment(ROOT)
    path = ROOT / amendment["protocol_revision"]["design_manifest_path"]
    manifest = s4_8.load_json(path)
    altered = copy.deepcopy(manifest)
    altered["take_order"][2], altered["take_order"][5] = (
        altered["take_order"][5],
        altered["take_order"][2],
    )
    for index, take in enumerate(altered["take_order"], start=1):
        take["sequence_index"] = index
    with pytest.raises(s4_8.S48Error, match="geometry, gain, repetition, or order"):
        recovery._validate_design_manifest(altered)

    altered = copy.deepcopy(manifest)
    altered["direction_repeatability_contract"][
        "each_repetition_is_an_independent_take"
    ] = False
    with pytest.raises(s4_8.S48Error, match="direction repeatability contract"):
        recovery._validate_design_manifest(altered)

    altered = copy.deepcopy(manifest)
    altered["direction_repeatability_contract"]["same_session_required"] = False
    with pytest.raises(s4_8.S48Error, match="direction repeatability contract"):
        recovery._validate_design_manifest(altered)

    altered = copy.deepcopy(manifest)
    altered["direction_contract"]["take_aggregation"]["mapping_application"] = (
        "per_window_vote"
    )
    with pytest.raises(s4_8.S48Error, match="categorical take aggregation"):
        recovery._validate_design_manifest(altered)

    altered = copy.deepcopy(manifest)
    altered["take_order"][1]["radius_m"] = 0.81
    with pytest.raises(s4_8.S48Error, match="geometry, gain, repetition, or order"):
        recovery._validate_design_manifest(altered)

    altered = copy.deepcopy(manifest)
    altered["take_order"][30]["playback_gain"] = 0.36
    with pytest.raises(s4_8.S48Error, match="geometry, gain, repetition, or order"):
        recovery._validate_design_manifest(altered)


def test_protocol_denominators_cover_all_criteria_without_threshold_changes() -> None:
    result = recovery.validate_protocol_revision(ROOT)
    amendment = recovery.load_amendment(ROOT)
    denominator_path = (
        ROOT / amendment["protocol_revision"]["denominators_path"]
    )
    denominators = s4_8.load_json(denominator_path)
    source = s4_8.load_json(
        ROOT / denominators["source_criteria_register_path"]
    )

    assert result["readiness"] == "frozen_for_precollection"
    assert result["planned_take_count"] == 37
    assert result["thresholds_unchanged"] is True
    assert result["criterion_count"] == 29
    assert result["primary_direction_metric"] == (
        "squadbot_categorical_direction_accuracy"
    )
    assert result["primary_direction_threshold"] == 0.75
    assert result["categorical_take_aggregation_bound"] is True
    assert result["continuous_bearing_error_gating"] is False
    assert denominators["planned_take_denominator"] == 37
    assert denominators["derived_denominators"]["raw_channel_take_records"] == 148
    assert denominators["direction_metric_denominators"] == {
        "primary_applicable_takes": 28,
        "front_expected_takes": 7,
        "right_expected_takes": 10,
        "left_expected_takes": 7,
        "rear_unavailable_expected_takes": 4,
        "low_volume_diagnostic_takes": 4,
        "silence_unavailable_takes": 3,
        "impact_direction_not_applicable_takes": 2,
    }
    assert len(source["details"]["criteria"]) == 29
    assert all(
        criterion["threshold"] is not None
        for criterion in source["details"]["criteria"]
    )


def test_protocol_denominator_drift_fails_closed() -> None:
    amendment = recovery.load_amendment(ROOT)
    revision = amendment["protocol_revision"]
    denominators = s4_8.load_json(ROOT / revision["denominators_path"])
    manifest = s4_8.load_json(ROOT / revision["design_manifest_path"])
    altered = copy.deepcopy(denominators)
    altered["criterion_expected_count_overrides"][
        "take_failure_rate"
    ] = 36

    with pytest.raises(s4_8.S48Error, match="denominator override"):
        recovery._validate_denominators(ROOT, altered, manifest)

    altered = copy.deepcopy(denominators)
    altered["source_criteria_register_sha256"] = "0" * 64
    with pytest.raises(s4_8.S48Error, match="register identity"):
        recovery._validate_denominators(ROOT, altered, manifest)


def test_protocol_criteria_bindings_cannot_redirect_from_frozen_history() -> None:
    amendment = recovery.load_amendment(ROOT)
    historical = recovery._load_historical_amendment(ROOT, amendment)
    altered = copy.deepcopy(amendment)
    altered["protocol_revision"]["criteria_config_path"] = (
        "configs/s4_8_recovery_amendment_02.v1.json"
    )
    altered["protocol_revision"]["criteria_config_sha256"] = (
        "ec8e16eb1f7ff606db18a2fbb26e183d27ea95dacf8f43138b8e4a8dfe059542"
    )

    with pytest.raises(s4_8.S48Error, match="preserve frozen history"):
        recovery._validate_protocol_bindings(ROOT, altered, historical)


def test_terminal_history_authenticates_both_failed_runs_hash_only() -> None:
    result = recovery.validate_terminal_history(ROOT)

    assert result["status"] == "passed"
    assert result["terminal_run_count"] == 2
    assert result["terminal_statuses"] == {
        "original_s4_8": "failed",
        "recovery_amendment_01": "failed",
    }
    assert result["artifact_count"] == 18
    assert result["package_manifest_sha256"] == {
        "original_s4_8": (
            "bb3e57bdac2cdf545f9adf39e867db3bf5b35831892c66b101e57913af9e59e2"
        ),
        "recovery_amendment_01": (
            "3ebcaf1070f5d8d53f878ea666cb8c63a4b9f1350d84e70ae68405a9652e3cbb"
        ),
    }
    assert result["raw_holdout_read"] is False
    assert result["scientific_payload_loaded"] is False


def test_terminal_artifact_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amendment = recovery.load_amendment(ROOT)
    historical = recovery._load_historical_amendment(ROOT, amendment)
    record = historical["prior_terminal_runs"][1]["artifacts"]["journal"]
    path = (ROOT / record["path"]).resolve()
    original = s4_8.sha256_file

    def changed(candidate: Path) -> str:
        if candidate.resolve() == path:
            return "0" * 64
        return original(candidate)

    monkeypatch.setattr(s4_8, "sha256_file", changed)
    with pytest.raises(s4_8.S48Error, match="terminal artifact mismatch"):
        recovery.validate_terminal_history(ROOT, amendment)


def test_unseen_holdout_namespace_cannot_reuse_consumed_observations() -> None:
    amendment = recovery.load_amendment(ROOT)
    altered = copy.deepcopy(amendment)
    altered["unseen_holdout"]["observation_root"] = (
        "dataset/S4.4/amendments/s4_4_data_expansion_amendment_03/attempts/reused"
    )
    historical = recovery._load_historical_amendment(ROOT, amendment)

    with pytest.raises(s4_8.S48Error, match="reuses consumed data"):
        recovery._validate_namespaces(altered, historical)

    altered["unseen_holdout"]["observation_root"] = (
        "dataset/S4.4/amendments"
    )
    with pytest.raises(s4_8.S48Error, match="reuses consumed data"):
        recovery._validate_namespaces(altered, historical)


def test_future_state_paths_are_disjoint_and_absent() -> None:
    amendment = recovery.load_amendment(ROOT)
    historical_amendment = recovery._load_historical_amendment(ROOT, amendment)
    historical = {
        record["path"]
        for run in historical_amendment["prior_terminal_runs"]
        for record in run["artifacts"].values()
    }
    future = amendment["future_attempt"]
    future_paths = {
        future[key]
        for key in (
            "grant_path",
            "ledger_path",
            "journal_path",
            "derived_input_path",
            "output_path",
            "closeout_path",
            "independent_review_path",
        )
    }

    assert historical.isdisjoint(future_paths)
    assert all(not (ROOT / path).exists() for path in future_paths)


def test_future_namespace_cannot_cover_a_frozen_terminal_package() -> None:
    amendment = recovery.load_amendment(ROOT)
    historical = recovery._load_historical_amendment(ROOT, amendment)
    altered = copy.deepcopy(amendment)
    altered["future_attempt"]["output_path"] = (
        "outputs/isaac_audio_sensors/S4/S4.8"
    )

    with pytest.raises(s4_8.S48Error, match="overlap terminal history"):
        recovery._validate_namespaces(altered, historical)

    altered["future_attempt"]["output_path"] = (
        "outputs/isaac_audio_sensors/S4"
    )
    with pytest.raises(s4_8.S48Error, match="overlap terminal history"):
        recovery._validate_namespaces(altered, historical)

    altered["future_attempt"]["output_path"] = (
        "outputs/isaac_audio_sensors/S4/S4.8/nested_future_output"
    )
    with pytest.raises(s4_8.S48Error, match="overlap terminal history"):
        recovery._validate_namespaces(altered, historical)


def test_amendment_02_exposes_no_grant_or_execution_function() -> None:
    amendment = recovery.load_amendment(ROOT)
    future = amendment["future_attempt"]

    assert future["grant_creation_authorized"] is False
    assert future["grant_consumption_authorized"] is False
    assert future["evaluation_execution_authorized"] is False
    assert future["automatic_retry_of_prior_runs"] is False
    assert not hasattr(recovery, "create_recovery_grant")
    assert not hasattr(recovery, "run_recovery_evaluation_once")


def test_authority_cannot_be_enabled_inside_preregistration_schema() -> None:
    amendment = recovery.load_amendment(ROOT)
    schema = s4_8.load_json(ROOT / recovery.AMENDMENT_SCHEMA_PATH)
    altered = copy.deepcopy(amendment)
    altered["future_attempt"]["grant_creation_authorized"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(altered, schema)


def test_future_binding_schema_requires_sealed_unopened_state() -> None:
    schema = s4_8.load_json(ROOT / recovery.HOLDOUT_BINDING_SCHEMA_PATH)
    binding = {
        "schema": "ias.s4_8.recovery_unseen_holdout_binding.v2",
        "amendment_id": "s4_8_recovery_amendment_02",
        "holdout_id": "s4_8_recovery_amendment_02_unseen_holdout",
        "status": "sealed_unopened",
        "preregistration_commit": "a" * 40,
        "precollection_seal": {"path": "future/pre.json", "sha256": "a" * 64},
        "partition_manifest": {"path": "future/part.json", "sha256": "b" * 64},
        "session_manifest": {"path": "future/session.json", "sha256": "c" * 64},
        "holdout_seal": {"path": "future/seal.json", "sha256": "d" * 64},
        "observation_root": (
            "dataset/S4.4/amendments/s4_4_data_expansion_amendment_04/attempts"
        ),
        "planned_take_count": 37,
        "leakage_group_count": 15,
        "scientifically_opened": False,
    }
    jsonschema.validate(binding, schema)
    wrong_count = copy.deepcopy(binding)
    wrong_count["planned_take_count"] = 47
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(wrong_count, schema)
    opened = copy.deepcopy(binding)
    opened["scientifically_opened"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(opened, schema)


def test_preopen_separates_acquisition_readiness_from_evaluation_no_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        s4_8,
        "preopen_validate",
        lambda *_args, **_kwargs: pytest.fail(
            "consumed-holdout preopen path must not run"
        ),
    )
    result = recovery.recovery_preopen_validate(ROOT)
    amendment = recovery.load_amendment(ROOT)
    readiness_present = (
        ROOT / amendment["preliminary_readiness"]["readiness_path"]
    ).is_file()

    assert result["status"] == "passed"
    assert result["protocol_revision_readiness"] == "frozen_for_precollection"
    assert result["official_readiness"] == "no_go"
    expected_blockers = [
        "evaluator_not_bound_to_37_take_protocol",
        "independent_review_not_present",
        "explicit_authorization_not_granted",
    ]
    if not result["holdout_collection_complete"]:
        expected_blockers.insert(0, "new_unseen_holdout_not_collected_or_bound")
    if not result["source_commit_binds_protocol_revision"]:
        expected_blockers.insert(0, "source_commit_does_not_bind_37_take_protocol")
    if not readiness_present:
        expected_blockers.insert(0, "preliminary_readiness_not_established")
    assert result["blockers"] == expected_blockers
    assert result["criteria_set_unchanged"] is False
    assert result["criteria_roles_amended_for_squadbot"] is True
    assert result["primary_direction_metric"] == (
        "squadbot_categorical_direction_accuracy"
    )
    assert result["categorical_take_aggregation_bound"] is True
    assert result["continuous_bearing_error_gating"] is False
    assert result["thresholds_unchanged"] is True
    assert result["denominators_updated_for_design"] is True
    assert result["planned_take_count"] == 37
    assert result["preliminary_take_count"] == 4
    assert result["preliminary_readiness_present"] is readiness_present
    assert result["preliminary_readiness_passed"] is readiness_present
    assert result["final_protocol_frozen"] is True
    assert result["candidate_grant_id"] == (
        amendment["future_attempt"]["grant_id_template"].format(
            source_commit=result["source_commit"]
        )
        if result["source_commit_binds_protocol_revision"]
        else None
    )
    assert result["official_acquisition_permitted"] is (
        result["source_commit_binds_protocol_revision"]
        and readiness_present
        and result["official_precollection_freeze"]["valid"]
    )
    assert result["leakage_group_count"] == 15
    assert result["grant_creation_authorized"] is False
    assert result["grant_consumption_authorized"] is False
    assert result["evaluation_execution_authorized"] is False
    assert result["new_grant_present"] is False
    assert result["new_ledger_present"] is False
    assert result["holdout_observation_opened"] is False
    assert result["content_derived_values_returned"] is False


def test_preopen_does_not_load_terminal_derived_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original = s4_8.load_json

    def record(path: Path):
        loaded_paths.append(path.resolve())
        return original(path)

    monkeypatch.setattr(s4_8, "load_json", record)
    recovery.recovery_preopen_validate(ROOT)
    amendment = recovery.load_amendment(ROOT)
    historical = recovery._load_historical_amendment(ROOT, amendment)
    derived = {
        (ROOT / run["artifacts"]["derived_terminal_state"]["path"]).resolve()
        for run in historical["prior_terminal_runs"]
    }

    assert derived.isdisjoint(loaded_paths)


def test_preopen_requires_source_containing_producer_fix() -> None:
    with pytest.raises(s4_8.S48Error, match="does not contain producer fix"):
        recovery.recovery_preopen_validate(
            ROOT,
            source_commit="b0d5575feded9f37316bff8ed4b62483084587bd",
        )


def test_preopen_does_not_attribute_protocol_to_stale_source_commit() -> None:
    amendment = recovery.load_amendment(ROOT)

    assert recovery._source_binds_protocol_revision(
        ROOT,
        amendment=amendment,
        source_commit="5897e7d054097c4672d70f69fbcea20049ab8fff",
    ) is False


def test_preopen_cli_reports_no_go_without_writing_state() -> None:
    before = recovery.recovery_preopen_validate(ROOT)
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "scripts/run_s4_8_recovery_02.py",
            "--preopen",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report == before
    assert report["protocol_revision_readiness"] == "frozen_for_precollection"
    assert report["official_readiness"] == "no_go"
    assert report["new_grant_present"] is False
