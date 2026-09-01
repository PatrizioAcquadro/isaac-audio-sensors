"""Validate R9.1 geometry-acoustics provider qualification reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONTRACT_VERSION = "r9.1"
RESULT_STATUSES = ("pass", "fail", "blocked")
EVIDENCE_KINDS = frozenset(
    {
        "artifact",
        "official_documentation",
        "official_license",
        "packaging_probe",
        "runtime_measurement",
        "runtime_probe",
    }
)


class QualificationContractError(ValueError):
    """Raised when a candidate report does not satisfy the R9.1 format."""


@dataclass(frozen=True, slots=True)
class CriterionDefinition:
    """One canonical R9.1 qualification criterion."""

    criterion_id: str
    title: str
    blocking: bool
    pass_evidence_kinds: frozenset[str]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One typed reference supporting a criterion result."""

    kind: str
    reference: str
    summary: str


@dataclass(frozen=True, slots=True)
class CriterionResult:
    """Validated result for one canonical criterion."""

    criterion_id: str
    status: str
    summary: str
    evidence: tuple[EvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class QualificationEvaluation:
    """Computed qualification outcome; reports cannot declare this value."""

    candidate_id: str
    candidate_version: str
    runtime: Mapping[str, str]
    outcome: str
    results: tuple[CriterionResult, ...]
    failed_gates: tuple[str, ...]
    blocked_gates: tuple[str, ...]
    diagnostic_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        counts = Counter(result.status for result in self.results)
        return {
            "blocked_gates": list(self.blocked_gates),
            "candidate": {
                "id": self.candidate_id,
                "version": self.candidate_version,
            },
            "contract_version": CONTRACT_VERSION,
            "counts": {status: counts[status] for status in RESULT_STATUSES},
            "diagnostic_limitations": list(self.diagnostic_limitations),
            "failed_gates": list(self.failed_gates),
            "outcome": self.outcome,
            "runtime": dict(self.runtime),
        }


_RUNTIME_OR_MEASUREMENT = frozenset({"runtime_probe", "runtime_measurement"})
_MEASUREMENT = frozenset({"runtime_measurement"})

CRITERIA = (
    CriterionDefinition(
        "passive_audible_content",
        "Arbitrary file-backed and generated passive audible content",
        True,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "raw_phase_coherent_microphones",
        "Separate phase-coherent raw output for every physical microphone",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "scene_geometry_and_dynamics",
        "Relevant materials, geometry, static objects, and dynamic objects",
        True,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "geometry_propagation",
        "Occlusion, reflection, transmission, indirect pathing, and diffraction",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "connected_space_propagation",
        "Propagation through connected rooms, corridors, doors, and openings",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "relative_amplitude_coherence",
        "Physically coherent relative amplitudes without universal SPL calibration",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "acoustic_assembly_identity",
        "One physical barrier is invariant to mesh or collider fragmentation",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "frequency_dependent_transmission",
        "Authored assembly transmission has no undocumented total-loss clamp",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "isaac_runtime",
        "Viable execution path in the intended Isaac runtime",
        True,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "packaging",
        "Viable maintainable packaging and distribution path",
        True,
        frozenset({"packaging_probe"}),
    ),
    CriterionDefinition(
        "licensing",
        "License permits the intended open-source and Isaac distribution path",
        True,
        frozenset({"official_license"}),
    ),
    CriterionDefinition(
        "performance",
        "Measured performance is viable for one or a few Isaac environments",
        True,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "path_diagnostics",
        "Bounded optional provider-native path or ray diagnostics",
        False,
        _RUNTIME_OR_MEASUREMENT,
    ),
)

_CRITERIA_BY_ID = {criterion.criterion_id: criterion for criterion in CRITERIA}
_CANDIDATE_FIELDS = frozenset({"id", "version"})
_RUNTIME_FIELDS = frozenset(
    {"hardware", "isaac_sim_version", "kit_version", "platform"}
)
_REPORT_FIELDS = frozenset(
    {"candidate", "contract_version", "criteria", "runtime"}
)
_RESULT_FIELDS = frozenset({"criterion_id", "evidence", "status", "summary"})
_EVIDENCE_FIELDS = frozenset({"kind", "reference", "summary"})


def evaluate_report(payload: object) -> QualificationEvaluation:
    """Validate a report and derive its qualification outcome."""

    report = _require_mapping(payload, "report")
    _require_exact_fields(report, _REPORT_FIELDS, "report")
    version = _require_text(report["contract_version"], "contract_version")
    if version != CONTRACT_VERSION:
        raise QualificationContractError(
            f"contract_version must be {CONTRACT_VERSION!r}; received {version!r}."
        )

    candidate = _require_mapping(report["candidate"], "candidate")
    _require_exact_fields(candidate, _CANDIDATE_FIELDS, "candidate")
    candidate_id = _require_text(candidate["id"], "candidate.id")
    candidate_version = _require_text(candidate["version"], "candidate.version")

    runtime_payload = _require_mapping(report["runtime"], "runtime")
    _require_exact_fields(runtime_payload, _RUNTIME_FIELDS, "runtime")
    runtime = {
        field: _require_text(runtime_payload[field], f"runtime.{field}")
        for field in sorted(_RUNTIME_FIELDS)
    }

    criteria_payload = report["criteria"]
    if not isinstance(criteria_payload, list):
        raise QualificationContractError("criteria must be a list.")
    results = tuple(
        _parse_result(item, index=index)
        for index, item in enumerate(criteria_payload)
    )
    _validate_inventory(results)
    for result in results:
        _validate_pass_evidence(result)

    failed_gates = tuple(
        result.criterion_id
        for result in results
        if _CRITERIA_BY_ID[result.criterion_id].blocking
        and result.status == "fail"
    )
    blocked_gates = tuple(
        result.criterion_id
        for result in results
        if _CRITERIA_BY_ID[result.criterion_id].blocking
        and result.status == "blocked"
    )
    diagnostic_limitations = tuple(
        result.criterion_id
        for result in results
        if not _CRITERIA_BY_ID[result.criterion_id].blocking
        and result.status != "pass"
    )
    if failed_gates:
        outcome = "rejected"
    elif blocked_gates:
        outcome = "incomplete"
    else:
        outcome = "qualified"
    return QualificationEvaluation(
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        runtime=runtime,
        outcome=outcome,
        results=results,
        failed_gates=failed_gates,
        blocked_gates=blocked_gates,
        diagnostic_limitations=diagnostic_limitations,
    )


def _parse_result(payload: object, *, index: int) -> CriterionResult:
    result = _require_mapping(payload, f"criteria[{index}]")
    _require_exact_fields(result, _RESULT_FIELDS, f"criteria[{index}]")
    criterion_id = _require_text(
        result["criterion_id"], f"criteria[{index}].criterion_id"
    )
    status = _require_text(result["status"], f"criteria[{index}].status")
    if status not in RESULT_STATUSES:
        raise QualificationContractError(
            f"criteria[{index}].status must be one of {list(RESULT_STATUSES)}."
        )
    summary = _require_text(result["summary"], f"criteria[{index}].summary")
    evidence_payload = result["evidence"]
    if not isinstance(evidence_payload, list) or not evidence_payload:
        raise QualificationContractError(
            f"criteria[{index}].evidence must be a non-empty list."
        )
    evidence = tuple(
        _parse_evidence(item, criterion_index=index, evidence_index=evidence_index)
        for evidence_index, item in enumerate(evidence_payload)
    )
    return CriterionResult(criterion_id, status, summary, evidence)


def _parse_evidence(
    payload: object,
    *,
    criterion_index: int,
    evidence_index: int,
) -> EvidenceRecord:
    location = f"criteria[{criterion_index}].evidence[{evidence_index}]"
    evidence = _require_mapping(payload, location)
    _require_exact_fields(evidence, _EVIDENCE_FIELDS, location)
    kind = _require_text(evidence["kind"], f"{location}.kind")
    if kind not in EVIDENCE_KINDS:
        raise QualificationContractError(
            f"{location}.kind must be one of {sorted(EVIDENCE_KINDS)}."
        )
    return EvidenceRecord(
        kind=kind,
        reference=_require_text(evidence["reference"], f"{location}.reference"),
        summary=_require_text(evidence["summary"], f"{location}.summary"),
    )


def _validate_inventory(results: tuple[CriterionResult, ...]) -> None:
    ids = tuple(result.criterion_id for result in results)
    counts = Counter(ids)
    duplicates = sorted(
        criterion_id for criterion_id, count in counts.items() if count > 1
    )
    if duplicates:
        raise QualificationContractError(
            f"criteria contains duplicate criterion ids: {duplicates}."
        )
    expected = tuple(criterion.criterion_id for criterion in CRITERIA)
    missing = sorted(set(expected) - set(ids))
    unknown = sorted(set(ids) - set(expected))
    if missing or unknown:
        raise QualificationContractError(
            f"criteria inventory mismatch; missing={missing}, unknown={unknown}."
        )
    if ids != expected:
        raise QualificationContractError(
            "criteria must follow canonical R9.1 order: " f"{list(expected)}."
        )


def _validate_pass_evidence(result: CriterionResult) -> None:
    if result.status != "pass":
        return
    definition = _CRITERIA_BY_ID[result.criterion_id]
    actual_kinds = {evidence.kind for evidence in result.evidence}
    if not actual_kinds & definition.pass_evidence_kinds:
        raise QualificationContractError(
            f"criterion {result.criterion_id!r} cannot pass without at least one "
            f"of {sorted(definition.pass_evidence_kinds)}; received "
            f"{sorted(actual_kinds)}."
        )


def _require_mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise QualificationContractError(f"{location} must be an object.")
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: frozenset[str],
    location: str,
) -> None:
    actual = set(payload)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise QualificationContractError(
            f"{location} fields mismatch; missing={missing}, unknown={unknown}."
        )


def _require_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualificationContractError(f"{location} must be a non-empty string.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report",
        type=Path,
        help="Candidate qualification JSON report.",
    )
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        evaluation = evaluate_report(payload)
    except (OSError, json.JSONDecodeError, QualificationContractError) as exc:
        print(
            json.dumps(
                {
                    "contract_version": CONTRACT_VERSION,
                    "error": str(exc),
                    "outcome": "invalid",
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True))
    return 0 if evaluation.outcome == "qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
