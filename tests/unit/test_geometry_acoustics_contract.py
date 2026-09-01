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
    elif criterion_id == "packaging":
        kind = "packaging_probe"
    elif criterion_id in {
        "raw_phase_coherent_microphones",
        "geometry_propagation",
        "connected_space_propagation",
        "relative_amplitude_coherence",
        "acoustic_assembly_identity",
        "frequency_dependent_transmission",
        "performance",
    }:
        kind = "runtime_measurement"
    else:
        kind = "runtime_probe"
    return {
        "kind": kind,
        "reference": f"build/validation/r9/{criterion_id}.json",
        "summary": f"Measured evidence for {criterion_id}.",
    }


def _report() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "candidate": {"id": "candidate", "version": "1.2.3"},
        "runtime": {
            "hardware": "RTX test host",
            "isaac_sim_version": "6.0.0",
            "kit_version": "110.0",
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
        result
        for result in criteria
        if isinstance(result, dict) and result["criterion_id"] == criterion_id
    )


def test_contract_inventory_and_order_are_frozen() -> None:
    assert tuple(criterion.criterion_id for criterion in CRITERIA) == (
        "passive_audible_content",
        "raw_phase_coherent_microphones",
        "scene_geometry_and_dynamics",
        "geometry_propagation",
        "connected_space_propagation",
        "relative_amplitude_coherence",
        "acoustic_assembly_identity",
        "frequency_dependent_transmission",
        "isaac_runtime",
        "packaging",
        "licensing",
        "performance",
        "path_diagnostics",
    )
    assert all(criterion.blocking for criterion in CRITERIA[:-1])
    assert not CRITERIA[-1].blocking


def test_all_gates_pass_qualifies_candidate() -> None:
    evaluation = evaluate_report(_report())
    assert evaluation.outcome == "qualified"
    assert evaluation.failed_gates == ()
    assert evaluation.blocked_gates == ()
    assert evaluation.to_dict()["counts"] == {
        "pass": len(CRITERIA),
        "fail": 0,
        "blocked": 0,
    }


@pytest.mark.parametrize("diagnostic_status", ("fail", "blocked"))
def test_missing_optional_path_diagnostics_do_not_block(
    diagnostic_status: str,
) -> None:
    report = _report()
    diagnostics = _result(report, "path_diagnostics")
    diagnostics["status"] = diagnostic_status
    diagnostics["evidence"] = [
        {
            "kind": "official_documentation",
            "reference": "provider/path-api.html",
            "summary": "No supported bounded path diagnostics were found.",
        }
    ]
    evaluation = evaluate_report(report)
    assert evaluation.outcome == "qualified"
    assert evaluation.diagnostic_limitations == ("path_diagnostics",)


def test_required_failure_rejects_and_takes_precedence_over_blocked() -> None:
    report = _report()
    _result(report, "raw_phase_coherent_microphones")["status"] = "fail"
    _result(report, "performance")["status"] = "blocked"
    evaluation = evaluate_report(report)
    assert evaluation.outcome == "rejected"
    assert evaluation.failed_gates == ("raw_phase_coherent_microphones",)
    assert evaluation.blocked_gates == ("performance",)


def test_required_blocker_produces_incomplete_outcome() -> None:
    report = _report()
    _result(report, "isaac_runtime")["status"] = "blocked"
    evaluation = evaluate_report(report)
    assert evaluation.outcome == "incomplete"
    assert evaluation.blocked_gates == ("isaac_runtime",)


@pytest.mark.parametrize(
    ("criterion_id", "kind"),
    (
        ("raw_phase_coherent_microphones", "official_documentation"),
        ("packaging", "official_documentation"),
        ("licensing", "runtime_probe"),
        ("performance", "runtime_probe"),
    ),
)
def test_pass_requires_criterion_specific_evidence(
    criterion_id: str,
    kind: str,
) -> None:
    report = _report()
    result = _result(report, criterion_id)
    result["evidence"] = [
        {
            "kind": kind,
            "reference": "provider/claim.html",
            "summary": "Insufficient evidence kind.",
        }
    ]
    with pytest.raises(QualificationContractError, match="cannot pass"):
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


def test_report_rejects_declared_outcome_and_wrong_version() -> None:
    report = _report()
    report["outcome"] = "qualified"
    with pytest.raises(QualificationContractError, match=r"unknown=\['outcome'\]"):
        evaluate_report(report)
    report = _report()
    report["contract_version"] = "r9.2"
    with pytest.raises(QualificationContractError, match="contract_version"):
        evaluate_report(report)


@pytest.mark.parametrize(
    "field_mutation",
    ("empty_identity", "empty_evidence", "unknown_evidence", "invalid_status"),
)
def test_malformed_report_fields_are_rejected(field_mutation: str) -> None:
    report = _report()
    first = _result(report, "passive_audible_content")
    if field_mutation == "empty_identity":
        report["candidate"]["id"] = ""
    elif field_mutation == "empty_evidence":
        first["evidence"] = []
    elif field_mutation == "unknown_evidence":
        first["evidence"][0]["kind"] = "marketing"
    else:
        first["status"] = "unknown"
    with pytest.raises(QualificationContractError):
        evaluate_report(report)


@pytest.mark.parametrize(
    ("outcome", "expected_exit"),
    (("qualified", 0), ("rejected", 1), ("incomplete", 1)),
)
def test_cli_exit_codes_and_deterministic_summary(
    tmp_path,
    capsys,
    outcome: str,
    expected_exit: int,
) -> None:
    report = _report()
    if outcome == "rejected":
        _result(report, "performance")["status"] = "fail"
    elif outcome == "incomplete":
        _result(report, "performance")["status"] = "blocked"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert main([str(path)]) == expected_exit
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert summary["outcome"] == outcome
    assert output.err == ""
    assert output.out == json.dumps(summary, indent=2, sort_keys=True) + "\n"


def test_cli_returns_two_for_invalid_report(tmp_path, capsys) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    assert main([str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["outcome"] == "invalid"
