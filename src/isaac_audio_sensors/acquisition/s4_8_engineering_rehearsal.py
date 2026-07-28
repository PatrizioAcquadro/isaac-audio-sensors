"""Deterministic, synthetic, explicitly non-holdout S4.8 dress rehearsal."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    DEFAULT_PRESEALING_CONFIG,
    array_sha256,
    build_authenticated_process_record,
    canonical_sha256,
    evaluate_presealing_gate,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_03

RATE = 16_000
CAPTURE_DURATION_S = 20.0
REFERENCE_SAMPLE_COUNT = 4_000


def run_synthetic_engineering_rehearsal(
    repo_root: Path,
    *,
    gate_execution_count: int = 47,
) -> dict[str, Any]:
    """Exercise every software-only stage without old or new holdout data."""

    if (
        isinstance(gate_execution_count, bool)
        or not isinstance(gate_execution_count, int)
        or gate_execution_count <= 0
        or gate_execution_count > 47
    ):
        raise ValueError("gate_execution_count must be in [1, 47]")
    root = repo_root.resolve()
    reference = _engineering_reference()
    capture = _engineering_capture(reference)
    expected_reference_sha256 = array_sha256(reference)
    valid_reports = []
    for _ in range(gate_execution_count):
        record = _process_record(capture, reference)
        valid_reports.append(
            evaluate_presealing_gate(
                capture,
                reference,
                sample_rate_hz=RATE,
                process_record=record,
                expected_reference_sha256=expected_reference_sha256,
                config=DEFAULT_PRESEALING_CONFIG,
                dry_run=True,
            )
        )

    corrupted = capture.copy()
    corrupted[9 * RATE : 10 * RATE, 2:6] = 0.0
    retry_report = evaluate_presealing_gate(
        corrupted,
        reference,
        sample_rate_hz=RATE,
        process_record=_process_record(corrupted, reference),
        expected_reference_sha256=expected_reference_sha256,
        config=DEFAULT_PRESEALING_CONFIG,
        dry_run=True,
    )

    payload = acceptance_criteria_corrective_03.build_synthetic_payload(root)
    evaluation = acceptance_criteria_corrective_03.evaluate_corrective(
        payload,
        repo_root=root,
    ).report()
    repeated_payload = acceptance_criteria_corrective_03.build_synthetic_payload(root)
    repeated_evaluation = acceptance_criteria_corrective_03.evaluate_corrective(
        repeated_payload,
        repo_root=root,
    ).report()
    criteria = evaluation["criteria"]
    mandatory = [item for item in criteria if item["gating"]]
    active_abstention = _criterion(
        criteria,
        "active_abstention_rate_strata_ab",
    )
    confidence = _criterion(criteria, "confidence_median_stratum_b")
    gate = valid_reports[0]
    source_path = Path(__file__).resolve()
    return {
        "schema": "ias.s4_8.synthetic_engineering_rehearsal.v1",
        "non_holdout": True,
        "synthetic": True,
        "physical_hardware_used": False,
        "old_holdout_observations_used": 0,
        "acquisition": {
            "protocol_duration_s": CAPTURE_DURATION_S,
            "pre_roll_s": 1.0,
            "playback_start_s": 1.0,
            "playback_stop_s": 19.0,
            "post_roll_s": 1.0,
            "evaluation_start_s": 1.25,
            "evaluation_stop_s": 18.75,
            "planned_take_count": 47,
            "gate_execution_count": gate_execution_count,
            "source": "deterministic_in_memory_engineering_fixture",
            "recordings_persisted": False,
        },
        "authentication": {
            "reference_sha256": expected_reference_sha256,
            "capture_sha256": array_sha256(capture),
            "all_process_records_authenticated": all(
                report["input_provenance"]["process_record_authenticated"]
                for report in valid_reports
            ),
            "configuration_sha256": gate["configuration_sha256"],
            "detector_configuration_sha256": gate["detector_configuration_sha256"],
        },
        "presealing": {
            "all_valid_decisions": (
                "PASS"
                if all(report["decision"] == "PASS" for report in valid_reports)
                else "RETRY_REQUIRED"
            ),
            "valid_execution_count": len(valid_reports),
            "retry_decision": retry_report["decision"],
            "retry_reason_codes": [item["code"] for item in retry_report["reasons"]],
        },
        "producer": {
            "status": "complete",
            "implementation": (
                "corrective_03 deterministic synthetic fixture producer"
            ),
            "manually_edited_outputs": False,
        },
        "payload": {
            "schema": payload["schema"],
            "planned_take_count": len(payload["takes"]),
            "payload_sha256": canonical_sha256(payload),
        },
        "evaluation": {
            "status": evaluation["status"],
            "readiness_passed": evaluation["readiness_passed"],
            "criterion_count": len(criteria),
            "evaluated_criterion_count": sum(
                item["status"] == "evaluated" for item in criteria
            ),
            "mandatory_criterion_count": len(mandatory),
            "mandatory_passed_count": sum(item["passed"] for item in mandatory),
            "failed_gating_criteria": evaluation["failed_gating_criteria"],
            "criteria": criteria,
        },
        "metrics": {
            "useful_sound_coverage": gate["metrics"]["useful_sound_coverage"],
            "longest_continuous_useful_s": gate["metrics"][
                "longest_continuous_useful_s"
            ],
            "maximum_non_applicable_gap_s": gate["metrics"][
                "maximum_non_applicable_gap_s"
            ],
            "active_abstention_rate": active_abstention["observed"],
            "stratum_b_median_confidence": confidence["observed"],
        },
        "determinism": {
            "payload_sha256_first": canonical_sha256(payload),
            "payload_sha256_second": canonical_sha256(repeated_payload),
            "evaluation_sha256_first": canonical_sha256(evaluation),
            "evaluation_sha256_second": canonical_sha256(repeated_evaluation),
            "byte_equivalent": (
                canonical_sha256(payload) == canonical_sha256(repeated_payload)
                and canonical_sha256(evaluation)
                == canonical_sha256(repeated_evaluation)
            ),
        },
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "implementation_path": source_path.relative_to(root).as_posix(),
            "implementation_sha256": hashlib.sha256(
                source_path.read_bytes()
            ).hexdigest(),
        },
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
        },
        "remaining_hardware_gate": (
            "Run the identical 47-take engineering protocol with the physical "
            "ReSpeaker, playback host/reference WAV, ZED path where applicable, "
            "and acquisition process-event recorder; freeze the passing code, "
            "environment, configuration, and exact reference WAV before any "
            "new official holdout is collected."
        ),
    }


def _engineering_reference() -> np.ndarray:
    return np.random.default_rng(483).normal(
        0.0,
        0.2,
        size=REFERENCE_SAMPLE_COUNT,
    )


def _engineering_capture(reference: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(484)
    capture = np.zeros((round(CAPTURE_DURATION_S * RATE), 6), dtype=np.float64)
    microphones = rng.normal(0.0, 0.0005, size=(4, capture.shape[0]))
    start = RATE
    stop = 19 * RATE
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (np.arange(start, stop) - start - delay) % reference.size
        microphones[channel, start:stop] += 0.04 * reference[indices]
    capture[:, 2:6] = microphones.T
    return capture


def _process_record(
    capture: np.ndarray,
    reference: np.ndarray,
) -> dict[str, Any]:
    return build_authenticated_process_record(
        capture_sha256=array_sha256(capture),
        reference_sha256=array_sha256(reference),
        capture_started_monotonic_ns=1_000_000_000,
        recorder_ready_monotonic_ns=1_050_000_000,
        playback_started_monotonic_ns=2_000_000_000,
        planned_playback_stop_monotonic_ns=20_000_000_000,
        playback_stopped_monotonic_ns=20_010_000_000,
        capture_stopped_monotonic_ns=21_000_000_000,
        recorder_started=True,
        recorder_exit_status=0,
        producer_status="complete",
        playback_loop_enabled=True,
        playback_exit_status=0,
    )


def _criterion(
    criteria: list[dict[str, Any]],
    criterion_id: str,
) -> dict[str, Any]:
    matches = [item for item in criteria if item["criterion_id"] == criterion_id]
    if len(matches) != 1:
        raise RuntimeError(f"criterion identity mismatch: {criterion_id}")
    return matches[0]
