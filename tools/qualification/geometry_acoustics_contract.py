"""Validate corrected R9.1 geometry-acoustics qualification reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONTRACT_VERSION = "r9.1-rev2"
RESULT_STATUSES = ("pass", "fail", "blocked")
EVIDENCE_ORIGINS = frozenset(
    {"provider_native", "ias_bridge", "mixed", "documentation"}
)
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
    """Raised when a candidate report does not satisfy R9.1 rev2."""


@dataclass(frozen=True, slots=True)
class CriterionDefinition:
    """One canonical R9.1 rev2 qualification criterion."""

    criterion_id: str
    title: str
    profile: str
    pass_evidence_kinds: frozenset[str]
    fail_evidence_kinds: frozenset[str]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One typed and attributed reference supporting a criterion result."""

    kind: str
    origin: str
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
    """Computed core and full-R10 outcomes; reports cannot declare them."""

    candidate_id: str
    candidate_version: str
    runtime: Mapping[str, str]
    core_integration_outcome: str
    full_r10_outcome: str
    results: tuple[CriterionResult, ...]
    core_failed_gates: tuple[str, ...]
    core_blocked_gates: tuple[str, ...]
    full_r10_failed_gates: tuple[str, ...]
    full_r10_blocked_gates: tuple[str, ...]
    diagnostic_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        counts = Counter(result.status for result in self.results)
        return {
            "candidate": {
                "id": self.candidate_id,
                "version": self.candidate_version,
            },
            "contract_version": CONTRACT_VERSION,
            "core_integration_outcome": self.core_integration_outcome,
            "counts": {status: counts[status] for status in RESULT_STATUSES},
            "diagnostic_limitations": list(self.diagnostic_limitations),
            "full_r10_outcome": self.full_r10_outcome,
            "gates": {
                "core_integration": {
                    "blocked": list(self.core_blocked_gates),
                    "failed": list(self.core_failed_gates),
                },
                "full_r10": {
                    "blocked": list(self.full_r10_blocked_gates),
                    "failed": list(self.full_r10_failed_gates),
                },
            },
            "runtime": dict(self.runtime),
        }


_RUNTIME_OR_MEASUREMENT = frozenset({"runtime_probe", "runtime_measurement"})
_MEASUREMENT = frozenset({"runtime_measurement"})

CRITERIA = (
    CriterionDefinition(
        "passive_audible_content",
        "Arbitrary file-backed and generated passive audible content",
        "core",
        _RUNTIME_OR_MEASUREMENT,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "phase_coherent_microphone_signals",
        "Separate phase-coherent signal output for every physical microphone",
        "core",
        _MEASUREMENT,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "scene_geometry_and_dynamics",
        "Relevant static materials and runtime geometry changes",
        "core",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "direct_occlusion_transmission",
        "Direct-path distance, opaque occlusion, and material transmission",
        "core",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "indirect_nlos_propagation",
        "Provider-native reflected or pathed non-line-of-sight propagation",
        "core",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "relative_amplitude_coherence",
        "Physically coherent relative amplitudes without universal SPL calibration",
        "core",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "isaac_runtime",
        "Viable execution path in the intended Isaac runtime",
        "core",
        _RUNTIME_OR_MEASUREMENT,
        _RUNTIME_OR_MEASUREMENT,
    ),
    CriterionDefinition(
        "packaging",
        "Maintainable build and distribution path for the intended integration",
        "core",
        frozenset({"packaging_probe"}),
        frozenset({"packaging_probe"}),
    ),
    CriterionDefinition(
        "licensing",
        "License permits the intended open-source and Isaac distribution path",
        "core",
        frozenset({"official_license"}),
        frozenset({"official_license"}),
    ),
    CriterionDefinition(
        "audio_block_performance",
        "Persistent complete four-microphone audio rendering meets its deadline",
        "core",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "connected_space_propagation",
        "Propagation through real rooms, walls, doors, and openings",
        "full_r10",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "acoustic_assembly_identity",
        "One physical barrier is invariant to mesh or collider fragmentation",
        "full_r10",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "frequency_dependent_transmission",
        "Authored assembly transmission is reproduced across provider bands",
        "full_r10",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "acoustic_refresh_performance",
        "Direct, reflections, and dynamic-geometry refresh meets its budget",
        "full_r10",
        _MEASUREMENT,
        _MEASUREMENT,
    ),
    CriterionDefinition(
        "path_diagnostics",
        "Bounded optional provider-native path or ray diagnostics",
        "diagnostic",
        _RUNTIME_OR_MEASUREMENT,
        _RUNTIME_OR_MEASUREMENT,
    ),
)

_CRITERIA_BY_ID = {criterion.criterion_id: criterion for criterion in CRITERIA}
_CANDIDATE_FIELDS = frozenset({"id", "version"})
_RUNTIME_FIELDS = frozenset(
    {"hardware", "isaac_sim_version", "kit_version", "platform"}
)
_REPORT_FIELDS = frozenset({"candidate", "contract_version", "criteria", "runtime"})
_RESULT_FIELDS = frozenset({"criterion_id", "evidence", "status", "summary"})
_EVIDENCE_FIELDS = frozenset({"kind", "origin", "reference", "summary"})


def _derive_outcome(
    results: tuple[CriterionResult, ...], profiles: frozenset[str]
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    scoped = tuple(
        result
        for result in results
        if _CRITERIA_BY_ID[result.criterion_id].profile in profiles
    )
    failed = tuple(result.criterion_id for result in scoped if result.status == "fail")
    blocked = tuple(
        result.criterion_id for result in scoped if result.status == "blocked"
    )
    if failed:
        outcome = "rejected"
    elif blocked:
        outcome = "incomplete"
    else:
        outcome = "qualified"
    return outcome, failed, blocked


def evaluate_report(payload: object) -> QualificationEvaluation:
    """Validate a report and independently derive core and full-R10 outcomes."""

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
        _parse_result(item, index=index) for index, item in enumerate(criteria_payload)
    )
    _validate_inventory(results)
    for result in results:
        _validate_status_evidence(result)

    core_outcome, core_failed, core_blocked = _derive_outcome(
        results, frozenset({"core"})
    )
    full_outcome, full_failed, full_blocked = _derive_outcome(
        results, frozenset({"core", "full_r10"})
    )
    diagnostic_limitations = tuple(
        result.criterion_id
        for result in results
        if _CRITERIA_BY_ID[result.criterion_id].profile == "diagnostic"
        and result.status != "pass"
    )
    return QualificationEvaluation(
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        runtime=runtime,
        core_integration_outcome=core_outcome,
        full_r10_outcome=full_outcome,
        results=results,
        core_failed_gates=core_failed,
        core_blocked_gates=core_blocked,
        full_r10_failed_gates=full_failed,
        full_r10_blocked_gates=full_blocked,
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
    origin = _require_text(evidence["origin"], f"{location}.origin")
    if origin not in EVIDENCE_ORIGINS:
        raise QualificationContractError(
            f"{location}.origin must be one of {sorted(EVIDENCE_ORIGINS)}."
        )
    return EvidenceRecord(
        kind=kind,
        origin=origin,
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
            f"criteria must follow canonical R9.1 rev2 order: {list(expected)}."
        )


def _validate_status_evidence(result: CriterionResult) -> None:
    if result.status == "blocked":
        return
    definition = _CRITERIA_BY_ID[result.criterion_id]
    required = (
        definition.pass_evidence_kinds
        if result.status == "pass"
        else definition.fail_evidence_kinds
    )
    actual_kinds = {evidence.kind for evidence in result.evidence}
    if not actual_kinds & required:
        raise QualificationContractError(
            f"criterion {result.criterion_id!r} cannot {result.status} without "
            f"at least one of {sorted(required)}; received {sorted(actual_kinds)}."
        )


def _require_mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
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
        "report", type=Path, help="Candidate qualification JSON report."
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
    return 0 if evaluation.full_r10_outcome == "qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
