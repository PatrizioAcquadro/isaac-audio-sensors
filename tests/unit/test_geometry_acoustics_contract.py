from __future__ import annotations

import copy
import json

import pytest

from tools.qualification.geometry_acoustics_contract import (
    CONTRACT_VERSION,
    CRITERIA,
    QualificationContractError,
    evaluate_report,
    main,
)


def _passing_evidence(criterion_id: str) -> dict[str, str]:
    if criterion_id == "licensing":
        kind = "official_license"
        origin = "documentation"
    elif criterion_id == "packaging":
        kind = "packaging_probe"
        origin = "provider_native"
    elif criterion_id in {
        "passive_audible_content",
        "isaac_runtime",
        "path_diagnostics",
    }:
        kind = "runtime_probe"
        origin = "provider_native"
    else:
        kind = "runtime_measurement"
        origin = "mixed"
    return {
        "kind": kind,
        "origin": origin,
        "reference": f"build/validation/r9/rev2/{criterion_id}.json",
        "summary": f"Measured evidence for {criterion_id}.",
    }


def _report() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "candidate": {"id": "candidate", "version": "1.2.3"},
        "runtime": {
            "hardware": "test host",
            "isaac_sim_version": "6.0.0",
            "kit_version": "110.1.2",
            "platform": "linux-x86_64",
        },
        "criteria": [
            {
                "criterion_id": criterion.criterion_id,
                "status": "pass",
                "summary": f"{criterion.title} passed.",
                "evidence": [_passing_evidence(criterion.criterion_id)],
            }
            for criterion in CRITERIA
        ],
    }


def _result(report: dict[str, object], criterion_id: str) -> dict[str, object]:
    criteria = report["criteria"]
    assert isinstance(criteria, list)
    return next(
        item
        for item in criteria
        if isinstance(item, dict) and item["criterion_id"] == criterion_id
    )


def test_contract_inventory_and_profiles_are_frozen() -> None:
    assert CONTRACT_VERSION == "r9.1-rev2"
    assert tuple(criterion.criterion_id for criterion in CRITERIA) == (
        "passive_audible_content",
        "phase_coherent_microphone_signals",
        "scene_geometry_and_dynamics",
        "direct_occlusion_transmission",
        "indirect_nlos_propagation",
        "relative_amplitude_coherence",
        "isaac_runtime",
        "packaging",
        "licensing",
        "audio_block_performance",
        "connected_space_propagation",
        "acoustic_assembly_identity",
        "frequency_dependent_transmission",
        "acoustic_refresh_performance",
        "path_diagnostics",
    )
    assert [criterion.profile for criterion in CRITERIA].count("core") == 10
    assert [criterion.profile for criterion in CRITERIA].count("full_r10") == 4
    assert CRITERIA[-1].profile == "diagnostic"


def test_all_gates_pass_qualifies_both_profiles() -> None:
    evaluation = evaluate_report(_report())
    assert evaluation.core_integration_outcome == "qualified"
    assert evaluation.full_r10_outcome == "qualified"
    assert evaluation.core_failed_gates == ()
    assert evaluation.full_r10_blocked_gates == ()


def test_full_failure_does_not_reject_core_profile() -> None:
    report = _report()
    _result(report, "acoustic_assembly_identity")["status"] = "fail"
    evaluation = evaluate_report(report)
    assert evaluation.core_integration_outcome == "qualified"
    assert evaluation.full_r10_outcome == "rejected"
    assert evaluation.core_failed_gates == ()
    assert evaluation.full_r10_failed_gates == ("acoustic_assembly_identity",)


def test_core_failure_rejects_both_profiles() -> None:
    report = _report()
    _result(report, "phase_coherent_microphone_signals")["status"] = "fail"
    evaluation = evaluate_report(report)
    assert evaluation.core_integration_outcome == "rejected"
    assert evaluation.full_r10_outcome == "rejected"


def test_blocked_full_gate_leaves_core_qualified_and_full_incomplete() -> None:
    report = _report()
    _result(report, "connected_space_propagation")["status"] = "blocked"
    evaluation = evaluate_report(report)
    assert evaluation.core_integration_outcome == "qualified"
    assert evaluation.full_r10_outcome == "incomplete"


@pytest.mark.parametrize("status", ("fail", "blocked"))
def test_diagnostics_never_change_readiness(status: str) -> None:
    report = _report()
    _result(report, "path_diagnostics")["status"] = status
    evaluation = evaluate_report(report)
    assert evaluation.core_integration_outcome == "qualified"
    assert evaluation.full_r10_outcome == "qualified"
    assert evaluation.diagnostic_limitations == ("path_diagnostics",)


def test_behavioral_fail_requires_executed_probe_or_measurement() -> None:
    report = _report()
    result = _result(report, "indirect_nlos_propagation")
    result["status"] = "fail"
    result["evidence"] = [
        {
            "kind": "official_documentation",
            "origin": "documentation",
            "reference": "provider/claim.html",
            "summary": "Not an executed failure.",
        }
    ]
    with pytest.raises(QualificationContractError, match="cannot fail"):
        evaluate_report(report)


@pytest.mark.parametrize("origin", (None, "marketing"))
def test_every_evidence_record_requires_a_known_origin(origin: str | None) -> None:
    report = _report()
    evidence = _result(report, "passive_audible_content")["evidence"][0]
    if origin is None:
        evidence.pop("origin")
    else:
        evidence["origin"] = origin
    with pytest.raises(QualificationContractError):
        evaluate_report(report)


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "unknown", "order"))
def test_criteria_inventory_fails_closed(mutation: str) -> None:
    report = _report()
    criteria = report["criteria"]
    assert isinstance(criteria, list)
    if mutation == "missing":
        criteria.pop()
    elif mutation == "duplicate":
        criteria[-1] = copy.deepcopy(criteria[0])
    elif mutation == "unknown":
        criteria[-1]["criterion_id"] = "marketing_claim"
    else:
        criteria[0], criteria[1] = criteria[1], criteria[0]
    with pytest.raises(QualificationContractError):
        evaluate_report(report)


def test_report_rejects_declared_outcomes_and_wrong_version() -> None:
    report = _report()
    report["core_integration_outcome"] = "qualified"
    with pytest.raises(QualificationContractError, match="core_integration_outcome"):
        evaluate_report(report)
    report = _report()
    report["contract_version"] = "r9.1"
    with pytest.raises(QualificationContractError, match="contract_version"):
        evaluate_report(report)


@pytest.mark.parametrize(
    ("profile_state", "expected_exit"),
    (("qualified", 0), ("core_fail", 1), ("full_blocked", 1)),
)
def test_cli_exit_codes_and_deterministic_summary(
    tmp_path, capsys, profile_state: str, expected_exit: int
) -> None:
    report = _report()
    if profile_state == "core_fail":
        _result(report, "audio_block_performance")["status"] = "fail"
    elif profile_state == "full_blocked":
        _result(report, "acoustic_refresh_performance")["status"] = "blocked"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert main([str(path)]) == expected_exit
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert output.err == ""
    assert output.out == json.dumps(summary, indent=2, sort_keys=True) + "\n"


def test_cli_returns_two_for_invalid_report(tmp_path, capsys) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    assert main([str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["outcome"] == "invalid"
