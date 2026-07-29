"""Deterministic, synthetic, explicitly non-holdout S4.8 dress rehearsal."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    append_engineering_journal_event,
    build_engineering_precollection_manifest,
    create_candidate_engineering_clearance,
    run_presealing_gate_from_engineering_files,
    seal_engineering_candidate,
    validate_engineering_process_journal,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    array_sha256,
    canonical_sha256,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    DEFAULT_PRESEALING_CONFIG_V2,
    TRACKED_DETECTOR_METHOD_V2,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_03

RATE = 16_000
CAPTURE_DURATION_S = 20.0
REFERENCE_ACTIVE_START = round(2.25 * RATE)
REFERENCE_ACTIVE_STOP = round(7.25 * RATE)
REFERENCE_SAMPLE_COUNT = round(9.5 * RATE)


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
    valid_reports: list[dict[str, Any]] = []
    clearances: list[dict[str, Any]] = []
    candidate_seals: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ias_s4_8_rehearsal_") as temporary:
        temporary_root = Path(temporary)
        capture_path = temporary_root / "capture.wav"
        reference_path = temporary_root / "reference.wav"
        corrupted_path = temporary_root / "corrupted.wav"
        _write_pcm16(capture_path, capture)
        _write_pcm16(reference_path, reference[:, None])
        expected_reference_sha256 = _file_sha256(reference_path)
        manifest = build_engineering_precollection_manifest(
            code_head="0" * 40,
            environment_identity="deterministic_synthetic_non_holdout",
            reference_wav_sha256=expected_reference_sha256,
            gate_configuration_sha256=canonical_sha256(DEFAULT_PRESEALING_CONFIG_V2),
            detector_configuration_sha256=canonical_sha256(
                DEFAULT_PRESEALING_CONFIG_V2["detector"]
            ),
            device_profile_id=DEFAULT_PRESEALING_CONFIG_V2[
                "expected_device_profile_id"
            ],
            channel_map=DEFAULT_PRESEALING_CONFIG_V2["expected_channel_map"],
            protocol_id="s4_8_synthetic_engineering_rehearsal_v2",
            capture_controller_identity="ias.s4_8.engineering_controller",
            capture_controller_version="2.0",
        )
        for execution in range(gate_execution_count):
            journal = _engineering_journal(
                manifest,
                capture_sha256=_file_sha256(capture_path),
            )
            gate_report = run_presealing_gate_from_engineering_files(
                capture_path=capture_path,
                reference_path=reference_path,
                manifest=manifest,
                journal=journal,
                expected_manifest_sha256=manifest["manifest_sha256"],
                repo_root=root,
                dry_run=True,
            )
            append_engineering_journal_event(
                journal,
                manifest_anchor_sha256=manifest["manifest_sha256"],
                event_type="gate_evaluated",
                observed_monotonic_ns=21_070_000_000,
                data={
                    "report_sha256": canonical_sha256(gate_report),
                    "decision": gate_report["decision"],
                },
            )
            clearance = create_candidate_engineering_clearance(
                gate_report,
                manifest=manifest,
                journal=journal,
                expected_manifest_sha256=manifest["manifest_sha256"],
            )
            append_engineering_journal_event(
                journal,
                manifest_anchor_sha256=manifest["manifest_sha256"],
                event_type="candidate_clearance_created",
                observed_monotonic_ns=21_080_000_000,
                data={"clearance_sha256": clearance["clearance_sha256"]},
            )
            candidate_seal = seal_engineering_candidate(
                capture_path=capture_path,
                reference_path=reference_path,
                report=gate_report,
                clearance=clearance,
                manifest=manifest,
                journal=journal,
                expected_manifest_sha256=manifest["manifest_sha256"],
                candidate_seal_path=temporary_root / f"candidate_{execution}.json",
                clearance_registry_path=temporary_root / f"used_{execution}.json",
                dry_run=True,
            )
            valid_reports.append(gate_report)
            clearances.append(clearance)
            candidate_seals.append(candidate_seal)

        corrupted = capture.copy()
        corrupted[9 * RATE : 10 * RATE, 2:6] = 0.0
        _write_pcm16(corrupted_path, corrupted)
        retry_journal = _engineering_journal(
            manifest,
            capture_sha256=_file_sha256(corrupted_path),
        )
        retry_report = run_presealing_gate_from_engineering_files(
            capture_path=corrupted_path,
            reference_path=reference_path,
            manifest=manifest,
            journal=retry_journal,
            expected_manifest_sha256=manifest["manifest_sha256"],
            repo_root=root,
            dry_run=True,
        )
        validate_engineering_process_journal(
            manifest,
            retry_journal,
            expected_manifest_sha256=manifest["manifest_sha256"],
            required_terminal_event="capture_authenticated",
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
                report["input_provenance"]["process_journal_head_sha256"]
                for report in valid_reports
            ),
            "process_journal_chain_valid": True,
            "manifest_anchor_sha256": manifest["manifest_sha256"],
            "configuration_sha256": gate["configuration_sha256"],
            "detector_configuration_sha256": gate["detector_configuration_sha256"],
        },
        "presealing": {
            "method": TRACKED_DETECTOR_METHOD_V2,
            "all_valid_decisions": (
                "PASS"
                if all(report["decision"] == "PASS" for report in valid_reports)
                else "RETRY_REQUIRED"
            ),
            "valid_execution_count": len(valid_reports),
            "retry_decision": retry_report["decision"],
            "retry_reason_codes": [item["code"] for item in retry_report["reasons"]],
            "candidate_clearance_created": all(clearances),
            "candidate_seal_dry_run_only": all(
                item["dry_run"] and item["engineering_only"] for item in candidate_seals
            ),
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
            "useful_sound_coverage": gate["waveform"]["alignment"][
                "useful_sound_coverage"
            ],
            "longest_continuous_useful_s": gate["waveform"]["alignment"][
                "longest_continuous_useful_interval"
            ]["duration_s"],
            "maximum_non_applicable_gap_s": gate["waveform"]["alignment"][
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
    reference = np.zeros(REFERENCE_SAMPLE_COUNT, dtype=np.float64)
    reference[REFERENCE_ACTIVE_START:REFERENCE_ACTIVE_STOP] = (
        np.random.default_rng(483).normal(
            0.0,
            0.2,
            size=REFERENCE_ACTIVE_STOP - REFERENCE_ACTIVE_START,
        )
    )
    return reference


def _engineering_capture(reference: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(484)
    capture = np.zeros((round(CAPTURE_DURATION_S * RATE), 6), dtype=np.float64)
    microphones = rng.normal(0.0, 0.0005, size=(4, capture.shape[0]))
    start = RATE
    stop = 19 * RATE
    active = reference[REFERENCE_ACTIVE_START:REFERENCE_ACTIVE_STOP]
    for channel, delay in enumerate((0, 2, 4, 6)):
        indices = (np.arange(start, stop) - start - delay) % active.size
        microphones[channel, start:stop] += 0.04 * active[indices]
    capture[:, 2:6] = microphones.T
    return capture


def _engineering_journal(
    manifest: dict[str, Any],
    *,
    capture_sha256: str,
) -> list[dict[str, Any]]:
    journal: list[dict[str, Any]] = []
    events = (
        (
            "capture_controller_started",
            900_000_000,
            {
                "identity": manifest["capture_controller_identity"],
                "version": manifest["capture_controller_version"],
                "pid": 100,
            },
        ),
        (
            "recorder_started",
            1_000_000_000,
            {"pid": 101, "process_identity": "synthetic_recorder"},
        ),
        ("recorder_ready", 1_050_000_000, {"pid": 101, "ready": True}),
        ("playback_commanded", 1_990_000_000, {"command_sha256": "d" * 64}),
        (
            "playback_started",
            2_000_000_000,
            {"pid": 102, "process_identity": "synthetic_player"},
        ),
        (
            "playback_stop_planned",
            2_000_000_000,
            {"planned_monotonic_ns": 20_050_000_000},
        ),
        (
            "playback_terminated",
            20_060_000_000,
            {"pid": 102, "exit_status": 0},
        ),
        (
            "recorder_terminated",
            21_050_000_000,
            {"pid": 101, "exit_status": 0},
        ),
        (
            "capture_authenticated",
            21_060_000_000,
            {
                "capture_sha256": capture_sha256,
                "reference_sha256": manifest["reference_wav_sha256"],
                "device_profile_id": manifest["device_profile_id"],
                "channel_map": manifest["channel_map"],
                "gate_configuration_sha256": manifest["gate_configuration_sha256"],
                "detector_configuration_sha256": manifest[
                    "detector_configuration_sha256"
                ],
            },
        ),
    )
    for event_type, observed_ns, data in events:
        append_engineering_journal_event(
            journal,
            manifest_anchor_sha256=manifest["manifest_sha256"],
            event_type=event_type,
            observed_monotonic_ns=observed_ns,
            data=data,
        )
    return journal


def _write_pcm16(path: Path, samples: np.ndarray) -> None:
    encoded = np.rint(np.clip(samples, -1.0, 32767.0 / 32768.0) * 32768.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(encoded.tobytes())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _criterion(
    criteria: list[dict[str, Any]],
    criterion_id: str,
) -> dict[str, Any]:
    matches = [item for item in criteria if item["criterion_id"] == criterion_id]
    if len(matches) != 1:
        raise RuntimeError(f"criterion identity mismatch: {criterion_id}")
    return matches[0]
