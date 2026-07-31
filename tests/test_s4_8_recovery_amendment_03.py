from __future__ import annotations

import copy
import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition import (
    s4_8_recovery_02_evaluator as historical_evaluator,
)
from isaac_audio_sensors.acquisition import s4_8_recovery_03 as recovery03
from isaac_audio_sensors.acquisition.s4_3 import _expected_tdoa
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as c2
from scripts import run_s4_8_recovery_03 as runner

ROOT = Path(__file__).resolve().parents[1]


def _domain() -> tuple[float, float]:
    domain = c2.load_corrective_config(ROOT)["physical_domains"]["tdoa_us"]
    return float(domain["minimum"]), float(domain["maximum"])


def _adverse_evaluation() -> dict[str, Any]:
    return {
        "schema": "ias.s4_8.recovery_02.criteria_evaluation_result.v2",
        "status": "failed",
        "readiness_passed": False,
        "failed_gating_criteria": ["evaluation_input_contract_rejected"],
        "criteria": [],
        "comparison_classifications": [],
        "categorical_take_results": [],
        "evaluation_error": "frozen adverse input",
        "identity_summary": {"input_contract_adverse": True},
        "config_identity": {},
        "holdout_observations_accessed_by_evaluator": 0,
        "evaluation_invocation_count": 1,
    }


def _full_evaluation() -> dict[str, Any]:
    criteria = [
        {
            "criterion_id": f"criterion_{index:02d}",
            "gating": True,
            "passed": True,
        }
        for index in range(17)
    ]
    return {
        "schema": "ias.s4_8.recovery_02.criteria_evaluation_result.v2",
        "status": "passed",
        "readiness_passed": True,
        "failed_gating_criteria": [],
        "criteria": criteria,
        "comparison_classifications": [],
        "categorical_take_results": [],
        "evaluation_error": None,
        "identity_summary": {},
        "config_identity": {},
        "holdout_observations_accessed_by_evaluator": 0,
        "evaluation_invocation_count": 1,
    }


def test_release_candidate_contracts_and_historical_bindings_validate() -> None:
    policy = recovery03.load_policy(ROOT)
    release_candidate = recovery03.load_release_candidate(ROOT)
    validation = recovery03.validate_release_candidate(ROOT)

    assert policy["policy_id"] == recovery03.POLICY_ID
    assert policy["canonicalization"]["allowance_ulps"] == 1
    assert (
        policy["canonicalization"]["measured_value_policy"]
        == "strict_no_canonicalization"
    )
    assert release_candidate["release_candidate_id"] == (
        recovery03.RELEASE_CANDIDATE_ID
    )
    assert release_candidate["status"] == "frozen_for_engineering_replay"
    assert validation["status"] == "passed"
    assert validation["historical_preservation_passed"] is True
    assert validation["ready_for_engineering_replay"] is True
    assert validation["ready_for_new_holdout_collection"] is False
    assert validation["raw_observations_read"] is False
    assert not any(validation["future_namespaces_present"].values())


def test_real_225_degree_reference_is_one_ulp_and_canonicalized() -> None:
    minimum, _maximum = _domain()
    positions = np.asarray(s4_8._profile_runtime(ROOT)["positions"], dtype=float)
    ids = tuple(f"raw_microphone_{index}" for index in range(4))
    pair_id = "raw_microphone_0->raw_microphone_2"
    reference = float(_expected_tdoa(positions, ids, 225.0, 343.0)[pair_id] * 1e6)
    take = {
        "tdoa": [
            {
                "pair_id": pair_id,
                "tdoa_us": 10.0,
                "reference_tdoa_us": reference,
                "absolute_error_us": abs(10.0 - reference),
            }
        ]
    }

    changed = recovery03.canonicalize_geometric_reference_tdoa(
        take,
        repo_root=ROOT,
        reference_origin=recovery03.REFERENCE_ORIGIN,
    )

    assert reference == math.nextafter(minimum, -math.inf)
    assert changed == 1
    assert take["tdoa"][0]["reference_tdoa_us"] == minimum
    assert take["tdoa"][0]["tdoa_us"] == 10.0
    assert take["tdoa"][0]["absolute_error_us"] == abs(10.0 - minimum)


def test_reference_policy_is_exactly_one_ulp_and_error_is_conditional() -> None:
    minimum, maximum = _domain()
    lower_ulp = math.nextafter(minimum, -math.inf)
    upper_ulp = math.nextafter(maximum, math.inf)
    lower_two_ulp = math.nextafter(lower_ulp, -math.inf)
    upper_two_ulp = math.nextafter(upper_ulp, math.inf)
    take = {
        "tdoa": [
            {
                "pair_id": "lower",
                "tdoa_us": 10.0,
                "reference_tdoa_us": lower_ulp,
                "absolute_error_us": -1.0,
            },
            {
                "pair_id": "upper",
                "tdoa_us": -10.0,
                "reference_tdoa_us": upper_ulp,
                "absolute_error_us": -1.0,
            },
            {
                "pair_id": "lower_two",
                "tdoa_us": 0.0,
                "reference_tdoa_us": lower_two_ulp,
                "absolute_error_us": 123.0,
            },
            {
                "pair_id": "upper_two",
                "tdoa_us": 0.0,
                "reference_tdoa_us": upper_two_ulp,
                "absolute_error_us": 456.0,
            },
            {
                "pair_id": "inside",
                "tdoa_us": 1.0,
                "reference_tdoa_us": 0.0,
                "absolute_error_us": 789.0,
            },
        ]
    }
    measured_before = [record["tdoa_us"] for record in take["tdoa"]]

    changed = recovery03.canonicalize_geometric_reference_tdoa(
        take,
        repo_root=ROOT,
        reference_origin=recovery03.REFERENCE_ORIGIN,
    )

    lower, upper, lower_two, upper_two, inside = take["tdoa"]
    assert changed == 2
    assert [record["tdoa_us"] for record in take["tdoa"]] == measured_before
    assert lower["reference_tdoa_us"] == minimum
    assert lower["absolute_error_us"] == abs(lower["tdoa_us"] - minimum)
    assert upper["reference_tdoa_us"] == maximum
    assert upper["absolute_error_us"] == abs(upper["tdoa_us"] - maximum)
    assert lower_two["reference_tdoa_us"] == lower_two_ulp
    assert lower_two["absolute_error_us"] == 123.0
    assert upper_two["reference_tdoa_us"] == upper_two_ulp
    assert upper_two["absolute_error_us"] == 456.0
    assert inside["absolute_error_us"] == 789.0


@pytest.mark.parametrize("side", ["lower", "upper"])
def test_two_ulp_reference_remains_rejected_by_frozen_validator(
    side: str,
) -> None:
    minimum, maximum = _domain()
    boundary = minimum if side == "lower" else maximum
    direction = -math.inf if side == "lower" else math.inf
    one_ulp = math.nextafter(boundary, direction)
    two_ulp = math.nextafter(one_ulp, direction)
    payload = historical_evaluator.build_synthetic_payload(ROOT)
    take = next(
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == "A_controlled_boundary_sweep"
    )
    record = take["tdoa"][0]
    record["reference_tdoa_us"] = two_ulp
    record["absolute_error_us"] = abs(record["tdoa_us"] - two_ulp)

    changed = recovery03.apply_reference_policy(
        payload,
        repo_root=ROOT,
        reference_origin=recovery03.REFERENCE_ORIGIN,
    )
    report = historical_evaluator.evaluate_payload(payload, repo_root=ROOT).report()

    assert changed == 0
    assert record["reference_tdoa_us"] == two_ulp
    assert report["failed_gating_criteria"] == [
        "evaluation_input_contract_rejected"
    ]


def test_measured_one_ulp_outside_is_never_canonicalized() -> None:
    minimum, _maximum = _domain()
    measured = math.nextafter(minimum, -math.inf)
    payload = historical_evaluator.build_synthetic_payload(ROOT)
    take = next(
        item
        for item in payload["takes"]
        if item["identity"]["stratum_id"] == "A_controlled_boundary_sweep"
    )
    record = take["tdoa"][0]
    record["tdoa_us"] = measured
    record["reference_tdoa_us"] = 0.0
    record["absolute_error_us"] = abs(measured)
    measured_before = struct.pack(">d", record["tdoa_us"])

    changed = recovery03.apply_reference_policy(
        payload,
        repo_root=ROOT,
        reference_origin=recovery03.REFERENCE_ORIGIN,
    )
    report = historical_evaluator.evaluate_payload(payload, repo_root=ROOT).report()

    assert changed == 0
    assert record["tdoa_us"] == measured
    assert struct.pack(">d", record["tdoa_us"]) == measured_before
    assert report["failed_gating_criteria"] == [
        "evaluation_input_contract_rejected"
    ]


def test_non_geometric_reference_origin_is_rejected_without_mutation() -> None:
    minimum, _maximum = _domain()
    take = {
        "tdoa": [
            {
                "pair_id": "measured",
                "tdoa_us": 0.0,
                "reference_tdoa_us": math.nextafter(minimum, -math.inf),
                "absolute_error_us": 1.0,
            }
        ]
    }
    before = copy.deepcopy(take)

    with pytest.raises(recovery03.S48Recovery03Error, match="not geometric"):
        recovery03.canonicalize_geometric_reference_tdoa(
            take,
            repo_root=ROOT,
            reference_origin="measured_observation",
        )

    assert take == before


def test_package_profiles_are_explicit_and_version_bound() -> None:
    full = {
        "evaluation_state": "evaluation_completed",
        "evaluation": _full_evaluation(),
        "run_failure": None,
    }
    adverse = {
        "evaluation_state": "evaluation_completed",
        "evaluation": _adverse_evaluation(),
        "run_failure": None,
    }
    pre_evaluation = {
        "evaluation_state": "not_evaluated",
        "evaluation": {
            "status": "not_evaluated",
            "readiness_passed": False,
            "failed_gating_criteria": [],
            "criteria": [],
            "holdout_observations_accessed_by_evaluator": 0,
            "evaluation_invocation_count": 0,
        },
        "run_failure": {
            "stage": "observation_analysis",
            "terminal": True,
            "automatic_retry_forbidden": True,
        },
    }

    assert recovery03.classify_package_profile(full) == (
        recovery03.FULL_EVALUATED_PROFILE
    )
    assert recovery03.classify_package_profile(adverse) == (
        recovery03.INPUT_CONTRACT_REJECTION_PROFILE
    )
    assert recovery03.classify_package_profile(pre_evaluation) == (
        recovery03.PRE_EVALUATION_FAILURE_PROFILE
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "ias.s4_8.recovery_02.criteria_evaluation_result.v1"),
        ("status", "passed"),
        ("evaluation_invocation_count", 0),
        ("evaluation_invocation_count", 2),
        ("readiness_passed", True),
        ("criteria", [{"gating": True}]),
        ("comparison_classifications", [{"comparison_id": "unexpected"}]),
        ("categorical_take_results", [{"take_id": "unexpected"}]),
        ("failed_gating_criteria", []),
        ("evaluation_error", ""),
        ("config_identity", []),
        ("holdout_observations_accessed_by_evaluator", 1),
    ],
)
def test_adverse_profile_rejects_every_structural_mutation(
    field: str,
    value: Any,
) -> None:
    evaluation = _adverse_evaluation()
    evaluation[field] = value

    with pytest.raises(recovery03.S48Recovery03Error):
        recovery03.classify_package_profile(
            {
                "evaluation_state": "evaluation_completed",
                "evaluation": evaluation,
                "run_failure": None,
            }
        )


def test_adverse_profile_rejects_missing_adverse_identity() -> None:
    evaluation = _adverse_evaluation()
    evaluation["identity_summary"]["input_contract_adverse"] = False

    with pytest.raises(recovery03.S48Recovery03Error):
        recovery03.classify_package_profile(
            {
                "evaluation_state": "evaluation_completed",
                "evaluation": evaluation,
                "run_failure": None,
            }
        )


def test_adverse_profile_rejects_an_extra_evaluation_field() -> None:
    evaluation = _adverse_evaluation()
    evaluation["unexpected"] = None

    with pytest.raises(recovery03.S48Recovery03Error, match="profile mismatch"):
        recovery03.classify_package_profile(
            {
                "evaluation_state": "evaluation_completed",
                "evaluation": evaluation,
                "run_failure": None,
            }
        )


def test_unprofiled_evaluator_failure_is_rejected() -> None:
    with pytest.raises(recovery03.S48Recovery03Error, match="no release-candidate"):
        recovery03.classify_package_profile(
            {
                "evaluation_state": "evaluation_failed",
                "evaluation": {
                    "status": "failed",
                    "evaluation_invocation_count": 1,
                },
                "run_failure": {
                    "terminal": True,
                    "automatic_retry_forbidden": True,
                },
            }
        )


def _mock_release_candidate() -> dict[str, Any]:
    return {
        "engineering_replay": {
            "output_root": (
                ".local/s4_8/"
                "s4_8_recovery_amendment_03_rc1_engineering_replay"
            ),
            "planned_take_count": 37,
            "source_raw_observation_root": "frozen/raw/attempts",
        }
    }


def _mock_payload() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return (
        {
            "takes": [
                {"identity": {"planned_take_id": f"take_{index:02d}"}, "tdoa": []}
                for index in range(37)
            ]
        },
        [{"planned_take_id": f"take_{index:02d}"} for index in range(37)],
    )


def _install_replay_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshots: list[dict[str, str]] | None = None,
) -> dict[str, int]:
    calls = {"build": 0, "evaluate": 0}

    def build(_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        calls["build"] += 1
        return _mock_payload()

    def evaluate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["evaluate"] += 1
        return _full_evaluation()

    monkeypatch.setattr(
        recovery03,
        "validate_release_candidate",
        lambda _root: {
            "status": "passed",
            "raw_observations_read": False,
        },
    )
    monkeypatch.setattr(
        recovery03,
        "load_release_candidate",
        lambda _root: _mock_release_candidate(),
    )
    snapshot_values = iter(snapshots or [{"official": "same"}, {"official": "same"}])
    monkeypatch.setattr(
        recovery03,
        "_snapshot_historical_state",
        lambda *_args: next(snapshot_values),
    )
    monkeypatch.setattr(
        recovery03,
        "_build_engineering_payload",
        build,
    )
    monkeypatch.setattr(
        recovery03,
        "apply_reference_policy",
        lambda *_args, **_kwargs: 2,
    )
    monkeypatch.setattr(
        recovery03,
        "_evaluate_engineering_payload",
        evaluate,
    )
    monkeypatch.setattr(s4_8, "_git", lambda *_args: "a" * 40)
    return calls


def test_engineering_replay_is_isolated_non_official_and_non_overwriting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = _install_replay_mocks(monkeypatch)

    result = recovery03.run_engineering_replay(tmp_path)
    output = tmp_path / result["output"]

    assert result["official_evidence"] is False
    assert result["raw_take_read_count"] == 37
    assert result["evaluator_invocation_count"] == 1
    assert calls == {"build": 1, "evaluate": 1}
    assert result["package_profile_preview"] == (
        recovery03.FULL_EVALUATED_PROFILE
    )
    assert result["grant_created"] is False
    assert result["grant_consumed"] is False
    assert result["existing_raw_observations_read"] is True
    assert result["new_holdout_opening_event_created"] is False
    assert result["official_evaluation_executed"] is False
    assert output.parent == tmp_path / ".local/s4_8"
    assert {path.name for path in output.iterdir()} == {
        "SHA256SUMS",
        "criteria_results.v1.json",
        "derived_evaluation_input.v1.json",
        "engineering_replay_report.v1.json",
    }
    report = json.loads(
        (output / "engineering_replay_report.v1.json").read_text()
    )
    assert report["official_evidence"] is False
    assert not (tmp_path / "dataset/S4.8/recovery_amendment_03").exists()
    assert not (
        tmp_path / "outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_03"
    ).exists()

    monkeypatch.setattr(
        recovery03,
        "_snapshot_historical_state",
        lambda *_args: {"official": "same"},
    )
    with pytest.raises(recovery03.S48Recovery03Error, match="already exists"):
        recovery03.run_engineering_replay(tmp_path)


def test_engineering_replay_refuses_historical_mutation_before_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_replay_mocks(
        monkeypatch,
        snapshots=[{"official": "before"}, {"official": "after"}],
    )

    with pytest.raises(recovery03.S48Recovery03Error, match="evidence changed"):
        recovery03.run_engineering_replay(tmp_path)

    assert not (
        tmp_path
        / ".local/s4_8/s4_8_recovery_amendment_03_rc1_engineering_replay"
    ).exists()


def test_cli_exposes_no_official_or_authority_actions() -> None:
    option_strings = {
        option
        for action in runner.build_parser()._actions
        for option in action.option_strings
    }

    assert "--validate-rc" in option_strings
    assert "--engineering-replay" in option_strings
    assert not {
        "--create-grant",
        "--consume-grant",
        "--execute",
        "--collect",
        "--open-holdout",
    } & option_strings
