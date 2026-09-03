"""Deterministic R9.2 report construction and local evidence bundles."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike

from tools.qualification.geometry_acoustics_contract import CRITERIA, evaluate_report

_CANDIDATE_ORDER = ("steam_audio", "nvidia_rtx_acoustic")


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    reference: str
    summary: str


@dataclass(frozen=True, slots=True)
class CriterionObservation:
    criterion_id: str
    compatible: bool | None
    summary: str
    evidence: tuple[Evidence, ...]
    external_blocker: str | None = None


def derive_status(observation: CriterionObservation) -> str:
    """Map only external access failures to blocked; incompatibility is fail."""

    if observation.external_blocker:
        return "blocked"
    if observation.compatible is None:
        raise ValueError(
            f"{observation.criterion_id}: compatibility is unknown "
            "without an external blocker."
        )
    return "pass" if observation.compatible else "fail"


class QualificationReportBuilder:
    """Build an ordered report accepted by the unchanged R9.1 validator."""

    def __init__(
        self,
        *,
        candidate_id: str,
        candidate_version: str,
        runtime: Mapping[str, str],
    ) -> None:
        self._candidate_id = candidate_id
        self._candidate_version = candidate_version
        self._runtime = dict(runtime)
        self._observations: dict[str, CriterionObservation] = {}

    def record(self, observation: CriterionObservation) -> None:
        known = {criterion.criterion_id for criterion in CRITERIA}
        if observation.criterion_id not in known:
            raise ValueError(f"unknown R9.1 criterion: {observation.criterion_id}")
        if observation.criterion_id in self._observations:
            raise ValueError(f"duplicate criterion: {observation.criterion_id}")
        if not observation.evidence:
            raise ValueError("every observation requires evidence.")
        self._observations[observation.criterion_id] = observation

    def build(self) -> dict[str, object]:
        missing = [
            criterion.criterion_id
            for criterion in CRITERIA
            if criterion.criterion_id not in self._observations
        ]
        if missing:
            raise ValueError(f"missing R9.1 criteria: {missing}")
        report = {
            "candidate": {"id": self._candidate_id, "version": self._candidate_version},
            "contract_version": "r9.1",
            "criteria": [
                _observation_payload(self._observations[criterion.criterion_id])
                for criterion in CRITERIA
            ],
            "runtime": self._runtime,
        }
        evaluate_report(report)
        return report


def _observation_payload(observation: CriterionObservation) -> dict[str, object]:
    summary = observation.summary
    if observation.external_blocker:
        summary = f"{summary} External blocker: {observation.external_blocker}"
    return {
        "criterion_id": observation.criterion_id,
        "evidence": [
            {
                "kind": item.kind,
                "reference": item.reference,
                "summary": item.summary,
            }
            for item in observation.evidence
        ],
        "status": derive_status(observation),
        "summary": summary,
    }


def deterministic_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deterministic_json(payload), encoding="utf-8")


def write_deterministic_npz(path: Path, arrays: Mapping[str, ArrayLike]) -> None:
    """Write NPZ data with stable entry ordering and ZIP metadata."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(arrays):
            if not name or "/" in name or "\\" in name:
                raise ValueError(f"unsafe NPZ entry name: {name!r}")
            buffer = io.BytesIO()
            np.lib.format.write_array(
                buffer, np.asarray(arrays[name]), allow_pickle=False
            )
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, buffer.getvalue())


def write_candidate_bundle(
    output_dir: Path,
    *,
    report: Mapping[str, object],
    measurements: Mapping[str, object],
    arrays: Mapping[str, ArrayLike],
    provenance: Mapping[str, object],
    log_lines: Sequence[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluation = evaluate_report(report)
    write_json(output_dir / "r9.1-report.json", report)
    write_json(output_dir / "evaluation.json", evaluation.to_dict())
    write_json(output_dir / "measurements.json", measurements)
    write_deterministic_npz(output_dir / "signals.npz", arrays)
    write_json(output_dir / "provenance.json", provenance)
    (output_dir / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def build_coverage_summary(
    reports: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compare criterion coverage without ranking or selecting a provider."""

    evaluations = {
        evaluation.candidate_id: evaluation
        for evaluation in map(evaluate_report, reports)
    }
    if set(evaluations) != set(_CANDIDATE_ORDER):
        raise ValueError(f"reports must cover exactly {list(_CANDIDATE_ORDER)}")
    rows = []
    for candidate_id in _CANDIDATE_ORDER:
        evaluation = evaluations[candidate_id]
        rows.append(
            {
                "blocked_gates": list(evaluation.blocked_gates),
                "candidate": {
                    "id": candidate_id,
                    "version": evaluation.candidate_version,
                },
                "criteria": {
                    result.criterion_id: result.status for result in evaluation.results
                },
                "failed_gates": list(evaluation.failed_gates),
                "outcome": evaluation.outcome,
            }
        )
    return {
        "candidates": rows,
        "complete": all(not row["blocked_gates"] for row in rows),
        "contract_version": "r9.2-coverage-v1",
        "scope": "coverage comparison only; no ranking or provider selection",
    }
