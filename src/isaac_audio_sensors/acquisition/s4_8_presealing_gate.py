"""Outcome-independent S4.8 playback detector and pre-sealing controls.

This module is a forward-only engineering surface.  It does not create or
consume a holdout grant, run the S4.8 state machine, or publish official
evidence.  The legacy reused-holdout diagnostic remains unchanged and
reproducible in :mod:`s4_8_useful_sound_diagnostic`.
"""

from __future__ import annotations

import hashlib
import json
import math
import wave
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any

import jsonschema
import numpy as np

GENERALIZED_DETECTOR_METHOD = (
    "authenticated_background_and_looped_reference_activity_v1"
)

DEFAULT_GENERALIZED_DETECTOR_CONFIG: dict[str, float | int] = {
    "analysis_block_samples": 2_000,
    "basic_rms_floor": 0.002,
    "background_normalized_mad_scale": 1.4826,
    "background_mad_multiplier": 5.0,
    "minimum_reference_correlation": 0.20,
    "minimum_pair_coherence": 0.10,
    "minimum_correlated_channel_count": 3,
    "maximum_reference_lag_samples": 16,
    "minimum_detection_contiguous_blocks": 8,
}

PROCESS_RECORD_SCHEMA = "ias.s4_8.presealing_process_record.v1"
PRESEALING_REPORT_SCHEMA = "ias.s4_8.presealing_gate_report.v1"
CONFIG_PATH = Path("configs/s4_8_presealing_gate.v1.json")
CONFIG_SCHEMA_PATH = Path("docs/schemas/s4_8_presealing_gate_config.v1.schema.json")
REPORT_SCHEMA_PATH = Path("docs/schemas/s4_8_presealing_gate_report.v1.schema.json")
DEFAULT_PRESEALING_CONFIG: dict[str, Any] = {
    "schema": "ias.s4_8.presealing_gate_config.v1",
    "sample_rate_hz": 16_000,
    "channel_count": 6,
    "microphone_channel_indices": [2, 3, 4, 5],
    "capture_duration_s": 20.0,
    "capture_duration_tolerance_s": 0.05,
    "playback_start_s": 1.0,
    "playback_start_tolerance_s": 0.10,
    "playback_stop_s": 19.0,
    "evaluation_start_s": 1.25,
    "evaluation_stop_s": 18.75,
    "minimum_useful_sound_coverage": 0.90,
    "minimum_continuous_useful_s": 16.0,
    "maximum_non_applicable_gap_s": 0.5,
    "maximum_clip_run_samples": 8,
    "maximum_channel_rms_spread_db": 6.0,
    "maximum_negative_reference_correlation": -0.20,
    "detector": DEFAULT_GENERALIZED_DETECTOR_CONFIG,
}


class S48PresealingGateError(RuntimeError):
    """Malformed or unauthenticated pre-sealing input."""


def canonical_sha256(value: Any) -> str:
    """Hash a deterministic JSON value."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def array_sha256(value: np.ndarray) -> str:
    """Hash an array with its exact shape and canonical float64 bytes."""

    array = np.ascontiguousarray(np.asarray(value, dtype="<f8"))
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {"dtype": "<f8", "shape": list(array.shape)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    )
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def build_authenticated_process_record(
    *,
    capture_sha256: str,
    reference_sha256: str,
    capture_started_monotonic_ns: int,
    recorder_ready_monotonic_ns: int,
    playback_started_monotonic_ns: int,
    planned_playback_stop_monotonic_ns: int,
    playback_stopped_monotonic_ns: int,
    capture_stopped_monotonic_ns: int,
    recorder_started: bool,
    recorder_exit_status: int,
    producer_status: str,
    playback_loop_enabled: bool,
    playback_exit_status: int,
) -> dict[str, Any]:
    """Create the exact hash-bound process-event record consumed by the gate."""

    payload = {
        "schema": PROCESS_RECORD_SCHEMA,
        "capture_sha256": capture_sha256,
        "reference_sha256": reference_sha256,
        "capture_started_monotonic_ns": capture_started_monotonic_ns,
        "recorder_ready_monotonic_ns": recorder_ready_monotonic_ns,
        "playback_started_monotonic_ns": playback_started_monotonic_ns,
        "planned_playback_stop_monotonic_ns": (planned_playback_stop_monotonic_ns),
        "playback_stopped_monotonic_ns": playback_stopped_monotonic_ns,
        "capture_stopped_monotonic_ns": capture_stopped_monotonic_ns,
        "recorder_started": recorder_started,
        "recorder_exit_status": recorder_exit_status,
        "producer_status": producer_status,
        "playback_loop_enabled": playback_loop_enabled,
        "playback_exit_status": playback_exit_status,
    }
    return {**payload, "record_sha256": canonical_sha256(payload)}


def evaluate_presealing_gate(
    capture: np.ndarray,
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    process_record: Mapping[str, Any],
    expected_reference_sha256: str,
    config: Mapping[str, Any],
    dry_run: bool,
    capture_identity_sha256: str | None = None,
    reference_identity_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate a future take before sealing, without scientific outcomes."""

    gate = _validated_presealing_config(config)
    capture_array = np.asarray(capture, dtype=np.float64)
    reference_array = np.asarray(reference, dtype=np.float64)
    actual_capture_sha256 = (
        capture_identity_sha256
        if capture_identity_sha256 is not None
        else array_sha256(capture_array)
    )
    actual_reference_sha256 = (
        reference_identity_sha256
        if reference_identity_sha256 is not None
        else array_sha256(reference_array)
    )
    reasons: list[dict[str, Any]] = []
    seen_reasons: set[str] = set()

    def reject(
        code: str,
        category: str,
        message: str,
        **details: Any,
    ) -> None:
        if code in seen_reasons:
            return
        seen_reasons.add(code)
        reasons.append(
            {
                "code": code,
                "category": category,
                "message": message,
                "details": details,
            }
        )

    process_authenticated = _process_record_authenticates(process_record)
    if not process_authenticated:
        reject(
            "process_record_authentication_failed",
            "integrity",
            "process timing/status record fields or hash are invalid",
        )
    process = dict(process_record) if isinstance(process_record, Mapping) else {}

    if process.get("recorder_started") is not True:
        reject(
            "recorder_not_started",
            "integrity",
            "recorder did not report a successful start",
        )
    if process.get("recorder_exit_status") != 0:
        reject(
            "recorder_process_failed",
            "integrity",
            "recorder process exit status was nonzero",
            exit_status=process.get("recorder_exit_status"),
        )
    if process.get("producer_status") != "complete":
        reject(
            "producer_incomplete",
            "integrity",
            "capture producer did not report complete",
            producer_status=process.get("producer_status"),
        )
    if process.get("playback_loop_enabled") is not True:
        reject(
            "continuous_loop_not_confirmed",
            "continuity",
            "playback process did not authenticate continuous looping",
        )
    if process.get("playback_exit_status") != 0:
        reject(
            "playback_process_failed",
            "integrity",
            "playback process exit status was nonzero",
            exit_status=process.get("playback_exit_status"),
        )

    expected_reference_valid = _is_sha256(expected_reference_sha256)
    if (
        not expected_reference_valid
        or actual_reference_sha256 != expected_reference_sha256
        or process.get("reference_sha256") != expected_reference_sha256
    ):
        reject(
            "reference_hash_mismatch",
            "integrity",
            "reference bytes, frozen identity, and process record do not agree",
            expected_reference_sha256=expected_reference_sha256,
            actual_reference_sha256=actual_reference_sha256,
            process_reference_sha256=process.get("reference_sha256"),
        )
    if process.get("capture_sha256") != actual_capture_sha256:
        reject(
            "capture_hash_mismatch",
            "integrity",
            "captured waveform does not match the producer process record",
            actual_capture_sha256=actual_capture_sha256,
            process_capture_sha256=process.get("capture_sha256"),
        )

    if sample_rate_hz != gate["sample_rate_hz"]:
        reject(
            "sample_rate_mismatch",
            "integrity",
            "capture sample rate does not match the preregistered rate",
            expected=gate["sample_rate_hz"],
            actual=sample_rate_hz,
        )
    channel_count = int(capture_array.shape[1]) if capture_array.ndim == 2 else 0
    if channel_count != gate["channel_count"]:
        reject(
            "channel_count_mismatch",
            "channel_health",
            "capture channel count does not match the preregistered count",
            expected=gate["channel_count"],
            actual=channel_count,
        )
    actual_duration_s = (
        capture_array.shape[0] / sample_rate_hz
        if capture_array.ndim == 2 and sample_rate_hz > 0
        else 0.0
    )
    if (
        abs(actual_duration_s - gate["capture_duration_s"])
        > gate["capture_duration_tolerance_s"]
    ):
        reject(
            "duration_mismatch",
            "integrity",
            "capture duration is outside the preregistered tolerance",
            expected_s=gate["capture_duration_s"],
            tolerance_s=gate["capture_duration_tolerance_s"],
            actual_s=actual_duration_s,
        )

    timing = _process_timing(process) if process_authenticated else None
    if timing is None:
        reject(
            "process_timing_invalid",
            "integrity",
            "process events are not monotonic and complete",
        )
    else:
        playback_start_s = timing["playback_start_s"]
        planned_stop_s = timing["planned_playback_stop_s"]
        playback_stop_s = timing["playback_stop_s"]
        if (
            abs(playback_start_s - gate["playback_start_s"])
            > gate["playback_start_tolerance_s"]
        ):
            reject(
                "playback_start_outside_tolerance",
                "integrity",
                "playback start is outside the preregistered timing tolerance",
                planned_s=gate["playback_start_s"],
                tolerance_s=gate["playback_start_tolerance_s"],
                actual_s=playback_start_s,
            )
        if abs(planned_stop_s - gate["playback_stop_s"]) > 1e-9:
            reject(
                "planned_playback_stop_mismatch",
                "integrity",
                "process record planned stop differs from the frozen protocol",
                expected_s=gate["playback_stop_s"],
                actual_s=planned_stop_s,
            )
        if playback_stop_s < planned_stop_s:
            reject(
                "playback_stopped_early",
                "continuity",
                "playback process stopped before its planned stop time",
                planned_s=planned_stop_s,
                actual_s=playback_stop_s,
            )

    detector_report: dict[str, Any] | None = None
    structural_waveform_valid = (
        sample_rate_hz == gate["sample_rate_hz"]
        and channel_count == gate["channel_count"]
        and abs(actual_duration_s - gate["capture_duration_s"])
        <= gate["capture_duration_tolerance_s"]
        and timing is not None
        and reference_array.size > 0
    )
    if structural_waveform_valid:
        microphone_indices = gate["microphone_channel_indices"]
        microphones = capture_array[:, microphone_indices].T
        evaluation_start_sample = round(gate["evaluation_start_s"] * sample_rate_hz)
        evaluation_stop_sample = round(gate["evaluation_stop_s"] * sample_rate_hz)
        actual_playback_start_sample = round(
            timing["playback_start_s"] * sample_rate_hz
        )
        post_roll_start = max(
            round(timing["playback_stop_s"] * sample_rate_hz),
            round(gate["playback_stop_s"] * sample_rate_hz),
        )
        try:
            detector_report = detect_authenticated_reference_activity(
                microphones,
                reference_array,
                sample_rate_hz=sample_rate_hz,
                playback_start_sample=actual_playback_start_sample,
                evaluation_start_sample=evaluation_start_sample,
                evaluation_stop_sample=evaluation_stop_sample,
                background_intervals=(
                    (0, actual_playback_start_sample),
                    (post_roll_start, capture_array.shape[0]),
                ),
                config=gate["detector"],
            )
        except S48PresealingGateError as exc:
            reject(
                "detector_input_invalid",
                "integrity",
                "waveform detector could not authenticate its inputs",
                error=str(exc),
            )

    channel_metrics: dict[str, Any] = {
        "rms_by_channel": [],
        "rms_spread_db": None,
        "median_reference_correlation_by_channel": [],
        "maximum_clip_run_samples_by_channel": [],
    }
    if detector_report is not None:
        useful_count = int(detector_report["useful_block_count"])
        coverage = float(detector_report["useful_sound_coverage"])
        longest = detector_report["longest_continuous_useful_interval"]
        longest_s = float(longest["duration_s"]) if longest is not None else 0.0
        maximum_gap_s = float(detector_report["maximum_non_applicable_gap_s"])
        median_correlation = float(detector_report["median_reference_correlation"])
        if (
            useful_count == 0
            or median_correlation < gate["detector"]["minimum_reference_correlation"]
        ):
            reject(
                "reference_stimulus_missing",
                "playback_presence",
                "the authenticated reference is not present in the capture",
                median_reference_correlation=median_correlation,
            )
        if coverage < gate["minimum_useful_sound_coverage"]:
            reject(
                "useful_sound_coverage_below_minimum",
                "coverage",
                "useful reference-stimulus coverage is below the minimum",
                minimum=gate["minimum_useful_sound_coverage"],
                actual=coverage,
            )
        if longest_s < gate["minimum_continuous_useful_s"]:
            reject(
                "continuous_useful_interval_too_short",
                "continuity",
                "no useful interval meets the continuous-duration minimum",
                minimum_s=gate["minimum_continuous_useful_s"],
                actual_s=longest_s,
            )
        if maximum_gap_s > gate["maximum_non_applicable_gap_s"]:
            reject(
                "non_applicable_gap_too_long",
                "continuity",
                "a non-applicable gap exceeds the maximum",
                maximum_s=gate["maximum_non_applicable_gap_s"],
                actual_s=maximum_gap_s,
            )

        evaluation = capture_array[
            round(gate["evaluation_start_s"] * sample_rate_hz) : round(
                gate["evaluation_stop_s"] * sample_rate_hz
            ),
            gate["microphone_channel_indices"],
        ]
        rms = np.sqrt(np.mean(evaluation * evaluation, axis=0))
        positive_rms = rms[rms > 0.0]
        spread_db = (
            float(20.0 * np.log10(np.max(positive_rms) / np.min(positive_rms)))
            if positive_rms.size == len(rms)
            else math.inf
        )
        per_channel_correlations = [
            float(
                median(
                    decision["reference_correlation_by_channel"][channel]
                    for decision in detector_report["decisions"]
                )
            )
            for channel in range(len(gate["microphone_channel_indices"]))
        ]
        clip_runs = [
            _maximum_true_run(np.abs(capture_array[:, channel]) >= (32767.0 / 32768.0))
            for channel in gate["microphone_channel_indices"]
        ]
        channel_metrics = {
            "rms_by_channel": [float(value) for value in rms],
            "rms_spread_db": spread_db,
            "median_reference_correlation_by_channel": (per_channel_correlations),
            "maximum_clip_run_samples_by_channel": clip_runs,
        }
        if spread_db > gate["maximum_channel_rms_spread_db"]:
            reject(
                "channel_gain_imbalance",
                "channel_health",
                "channel RMS spread exceeds the preregistered limit",
                maximum_db=gate["maximum_channel_rms_spread_db"],
                actual_db=spread_db,
            )
        if any(
            value <= gate["maximum_negative_reference_correlation"]
            for value in per_channel_correlations
        ):
            reject(
                "channel_polarity_inversion",
                "channel_health",
                "a channel has stable negative reference correlation",
                correlations=per_channel_correlations,
            )
        maximum_clip_run = max(clip_runs, default=0)
        if maximum_clip_run > gate["maximum_clip_run_samples"]:
            reject(
                "clipping_limit_exceeded",
                "clipping",
                "full-scale clipping run exceeds the frozen readiness limit",
                maximum_samples=gate["maximum_clip_run_samples"],
                actual_samples=maximum_clip_run,
            )
    else:
        coverage = 0.0
        longest_s = 0.0
        maximum_gap_s = gate["evaluation_stop_s"] - gate["evaluation_start_s"]

    detector_config_sha256 = canonical_sha256(gate["detector"])
    config_sha256 = canonical_sha256(gate)
    return {
        "schema": PRESEALING_REPORT_SCHEMA,
        "decision": "PASS" if not reasons else "RETRY_REQUIRED",
        "reasons": reasons,
        "dry_run": dry_run,
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
            "seals_take": False,
        },
        "decision_basis": [
            "integrity",
            "playback_presence",
            "continuity",
            "coverage",
            "clipping",
            "channel_health",
        ],
        "counts": {
            "capture_sample_count": (
                int(capture_array.shape[0]) if capture_array.ndim == 2 else 0
            ),
            "capture_channel_count": channel_count,
            "evaluation_block_count": (
                int(detector_report["source_block_count"])
                if detector_report is not None
                else 0
            ),
            "useful_block_count": (
                int(detector_report["useful_block_count"])
                if detector_report is not None
                else 0
            ),
            "non_applicable_block_count": (
                int(detector_report["non_applicable_block_count"])
                if detector_report is not None
                else 0
            ),
        },
        "intervals": {
            "evaluation": {
                "start_s": gate["evaluation_start_s"],
                "end_s": gate["evaluation_stop_s"],
            },
            "useful": (
                detector_report["useful_intervals"]
                if detector_report is not None
                else []
            ),
            "non_applicable": (
                detector_report["non_applicable_intervals"]
                if detector_report is not None
                else []
            ),
        },
        "metrics": {
            "capture_duration_s": actual_duration_s,
            "useful_sound_coverage": coverage,
            "longest_continuous_useful_s": longest_s,
            "maximum_non_applicable_gap_s": maximum_gap_s,
            "channel_health": channel_metrics,
        },
        "input_provenance": {
            "capture_sha256": actual_capture_sha256,
            "reference_sha256": actual_reference_sha256,
            "expected_reference_sha256": expected_reference_sha256,
            "process_record_sha256": process.get("record_sha256"),
            "process_record_authenticated": process_authenticated,
            "sample_rate_hz": sample_rate_hz,
            "detector_input_fields": [
                "waveform_samples",
                "reference_samples",
                "authenticated_process_timing",
                "producer_status",
                "channel_layout",
            ],
            "outcome_fields_read": [],
        },
        "detector_configuration": gate["detector"],
        "detector_configuration_sha256": detector_config_sha256,
        "configuration": gate,
        "configuration_sha256": config_sha256,
        "detector": detector_report,
    }


def load_presealing_config(repo_root: Path) -> dict[str, Any]:
    """Load the tracked gate configuration and reject identity drift."""

    root = repo_root.resolve()
    try:
        config = json.loads((root / CONFIG_PATH).read_text(encoding="utf-8"))
        schema = json.loads((root / CONFIG_SCHEMA_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(config, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise S48PresealingGateError(
            f"pre-sealing configuration failure: {exc}"
        ) from exc
    if config != DEFAULT_PRESEALING_CONFIG:
        raise S48PresealingGateError("pre-sealing configuration identity mismatch")
    return config


def validate_presealing_report(
    report: Mapping[str, Any],
    *,
    repo_root: Path,
) -> None:
    """Validate report shape plus non-authority and decision consistency."""

    root = repo_root.resolve()
    try:
        schema = json.loads((root / REPORT_SCHEMA_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(report, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise S48PresealingGateError(
            f"pre-sealing report validation failure: {exc}"
        ) from exc
    reasons = report["reasons"]
    if (report["decision"] == "PASS") != (reasons == []):
        raise S48PresealingGateError(
            "pre-sealing decision contradicts structured reasons"
        )
    if any(report["authority"].values()):
        raise S48PresealingGateError(
            "pre-sealing dry-run report claims forbidden authority"
        )
    if report["input_provenance"]["outcome_fields_read"] != []:
        raise S48PresealingGateError(
            "pre-sealing report used scientific outcome fields"
        )


def require_presealing_pass(
    report: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Fail closed unless a candidate-seal input is bound to a passing gate."""

    validate_presealing_report(report, repo_root=repo_root)
    if report["decision"] != "PASS":
        raise S48PresealingGateError(
            "a take with RETRY_REQUIRED cannot be sealed"
        )
    return {
        "schema": "ias.s4_8.presealing_clearance.v1",
        "status": "presealing_pass_required_before_seal",
        "report_sha256": canonical_sha256(report),
        "capture_sha256": report["input_provenance"]["capture_sha256"],
        "reference_sha256": report["input_provenance"]["reference_sha256"],
        "process_record_sha256": report["input_provenance"][
            "process_record_sha256"
        ],
        "configuration_sha256": report["configuration_sha256"],
        "detector_configuration_sha256": report[
            "detector_configuration_sha256"
        ],
        "scientific_outcome_fields_used": [],
    }


def run_presealing_gate_from_files(
    *,
    capture_wav_path: Path,
    reference_wav_path: Path,
    process_record_path: Path,
    expected_reference_sha256: str,
    repo_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the gate on exact WAV/process files without sealing or grants."""

    capture, capture_rate = _read_pcm16_wav(capture_wav_path)
    reference_channels, reference_rate = _read_pcm16_wav(reference_wav_path)
    if reference_rate != capture_rate:
        raise S48PresealingGateError("reference and capture sample rates differ")
    reference = np.mean(reference_channels, axis=1)
    try:
        process_record = json.loads(process_record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise S48PresealingGateError(f"process record load failure: {exc}") from exc
    report = evaluate_presealing_gate(
        capture,
        reference,
        sample_rate_hz=capture_rate,
        process_record=process_record,
        expected_reference_sha256=expected_reference_sha256,
        config=load_presealing_config(repo_root),
        dry_run=dry_run,
        capture_identity_sha256=_sha256_file(capture_wav_path),
        reference_identity_sha256=_sha256_file(reference_wav_path),
    )
    validate_presealing_report(report, repo_root=repo_root)
    return report


def detect_authenticated_reference_activity(
    microphones: np.ndarray,
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    playback_start_sample: int,
    evaluation_start_sample: int,
    evaluation_stop_sample: int,
    background_intervals: Sequence[tuple[int, int]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Detect the authenticated looped stimulus without scientific outcomes.

    Background is estimated only from timing-authenticated pre-roll/post-roll
    intervals.  Each 125 ms block must clear the unchanged basic RMS floor, a
    robust background RMS threshold, positive correlation with the exact
    looped reference on at least three channels, and coherent multichannel
    energy.  Runs shorter than one second are excluded.
    """

    detector = _validated_detector_config(config)
    if (
        isinstance(sample_rate_hz, bool)
        or not isinstance(sample_rate_hz, int)
        or sample_rate_hz <= 0
    ):
        raise S48PresealingGateError("sample_rate_hz must be positive")
    mic = np.asarray(microphones, dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    if mic.ndim != 2 or mic.shape[0] < 2 or mic.shape[1] == 0:
        raise S48PresealingGateError("microphones must have shape (channels, samples)")
    if ref.ndim == 2:
        ref = np.mean(ref, axis=1)
    if ref.ndim != 1 or ref.size == 0:
        raise S48PresealingGateError("reference must be non-empty mono samples")
    if not np.all(np.isfinite(mic)) or not np.all(np.isfinite(ref)):
        raise S48PresealingGateError("waveform samples must be finite")
    block = detector["analysis_block_samples"]
    if (
        playback_start_sample < 0
        or evaluation_start_sample < playback_start_sample
        or evaluation_stop_sample <= evaluation_start_sample
        or evaluation_stop_sample > mic.shape[1]
        or (evaluation_stop_sample - evaluation_start_sample) % block != 0
    ):
        raise S48PresealingGateError("evaluation sample interval is invalid")

    background_rms: list[float] = []
    normalized_background_intervals: list[dict[str, float | int]] = []
    for position, raw_interval in enumerate(background_intervals):
        if (
            not isinstance(raw_interval, Sequence)
            or len(raw_interval) != 2
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in raw_interval
            )
        ):
            raise S48PresealingGateError(f"background_intervals[{position}] is invalid")
        start, stop = raw_interval
        if (
            start < 0
            or stop <= start
            or stop > mic.shape[1]
            or start < playback_start_sample < stop
        ):
            raise S48PresealingGateError(
                f"background_intervals[{position}] is outside authenticated background"
            )
        for offset in range(start, stop - block + 1, block):
            background_rms.append(_median_channel_rms(mic[:, offset : offset + block]))
        normalized_background_intervals.append(
            {
                "start_sample": start,
                "end_sample": stop,
                "start_s": start / sample_rate_hz,
                "end_s": stop / sample_rate_hz,
            }
        )
    if len(background_rms) < 2:
        raise S48PresealingGateError(
            "authenticated background must contain at least two complete blocks"
        )
    background_median = float(median(background_rms))
    background_mad = float(
        median(abs(value - background_median) for value in background_rms)
    )
    robust_rms_threshold = max(
        detector["basic_rms_floor"],
        background_median
        + detector["background_mad_multiplier"]
        * detector["background_normalized_mad_scale"]
        * background_mad,
    )

    decisions: list[dict[str, Any]] = []
    raw_candidates: list[bool] = []
    reason_sets: list[list[str]] = []
    for index, start in enumerate(
        range(evaluation_start_sample, evaluation_stop_sample, block)
    ):
        stop = start + block
        frame = mic[:, start:stop]
        reference_frame = _looped_reference(
            ref,
            start_sample=start,
            stop_sample=stop,
            playback_start_sample=playback_start_sample,
        )
        rms_by_channel = np.sqrt(np.mean(frame * frame, axis=1))
        correlations = [
            _best_signed_correlation(
                channel,
                reference_frame,
                detector["maximum_reference_lag_samples"],
            )
            for channel in frame
        ]
        pair_coherences = [
            abs(
                _best_signed_correlation(
                    frame[left],
                    frame[right],
                    detector["maximum_reference_lag_samples"] * 2,
                )
            )
            for left in range(frame.shape[0])
            for right in range(left + 1, frame.shape[0])
        ]
        rms_median = float(np.median(rms_by_channel))
        reference_correlation = float(np.median(correlations))
        pair_coherence = float(np.median(pair_coherences))
        correlated_channels = sum(
            value >= detector["minimum_reference_correlation"] for value in correlations
        )
        reasons: list[str] = []
        if rms_median <= detector["basic_rms_floor"]:
            reasons.append("basic_energy")
        if rms_median <= robust_rms_threshold:
            reasons.append("background_energy")
        if (
            reference_correlation < detector["minimum_reference_correlation"]
            or correlated_channels < detector["minimum_correlated_channel_count"]
        ):
            reasons.append("reference_correlation")
        if pair_coherence < detector["minimum_pair_coherence"]:
            reasons.append("multichannel_coherence")
        candidate = not reasons
        raw_candidates.append(candidate)
        reason_sets.append(reasons)
        decisions.append(
            {
                "block_index": index,
                "start_sample": start,
                "end_sample": stop,
                "start_s": start / sample_rate_hz,
                "end_s": stop / sample_rate_hz,
                "rms_median": rms_median,
                "rms_by_channel": [float(value) for value in rms_by_channel],
                "reference_correlation": reference_correlation,
                "reference_correlation_by_channel": correlations,
                "correlated_channel_count": correlated_channels,
                "pair_coherence": pair_coherence,
                "candidate": candidate,
            }
        )

    useful = [False] * len(raw_candidates)
    candidate_runs = _boolean_runs(raw_candidates)
    useful_runs: list[tuple[int, int]] = []
    for start, stop in candidate_runs:
        if stop - start >= detector["minimum_detection_contiguous_blocks"]:
            useful[start:stop] = [True] * (stop - start)
            useful_runs.append((start, stop))
        else:
            for index in range(start, stop):
                reason_sets[index].append("insufficient_continuity")

    for decision, selected, reasons in zip(
        decisions,
        useful,
        reason_sets,
        strict=True,
    ):
        decision["useful"] = selected
        decision["exclusion_reasons"] = [] if selected else sorted(set(reasons))

    non_applicable_runs = _boolean_runs([not item for item in useful])
    useful_intervals = [
        _block_interval(decisions, run, sample_rate_hz) for run in useful_runs
    ]
    non_applicable_intervals = [
        _block_interval(decisions, run, sample_rate_hz) for run in non_applicable_runs
    ]
    reason_counts = Counter(
        reason
        for selected, reasons in zip(useful, reason_sets, strict=True)
        if not selected
        for reason in set(reasons)
    )
    useful_count = sum(useful)
    correlations = [float(item["reference_correlation"]) for item in decisions]
    return {
        "method": GENERALIZED_DETECTOR_METHOD,
        "source_block_count": len(decisions),
        "candidate_block_count": sum(raw_candidates),
        "useful_block_count": useful_count,
        "non_applicable_block_count": len(decisions) - useful_count,
        "useful_sound_coverage": useful_count / len(decisions),
        "background_intervals": normalized_background_intervals,
        "background_block_count": len(background_rms),
        "background_rms_median": background_median,
        "background_rms_mad": background_mad,
        "robust_rms_threshold": robust_rms_threshold,
        "median_reference_correlation": float(median(correlations)),
        "minimum_reference_correlation": min(correlations),
        "useful_intervals": useful_intervals,
        "non_applicable_intervals": non_applicable_intervals,
        "first_useful_interval": useful_intervals[0] if useful_intervals else None,
        "last_useful_interval": useful_intervals[-1] if useful_intervals else None,
        "longest_continuous_useful_interval": (
            max(useful_intervals, key=lambda item: item["duration_s"])
            if useful_intervals
            else None
        ),
        "maximum_non_applicable_gap_s": max(
            (float(item["duration_s"]) for item in non_applicable_intervals),
            default=0.0,
        ),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "decisions": decisions,
    }


def _validated_detector_config(
    value: Mapping[str, Any],
) -> dict[str, float | int]:
    if not isinstance(value, Mapping) or set(value) != set(
        DEFAULT_GENERALIZED_DETECTOR_CONFIG
    ):
        raise S48PresealingGateError("detector configuration fields mismatch")
    integer_fields = {
        "analysis_block_samples",
        "minimum_correlated_channel_count",
        "maximum_reference_lag_samples",
        "minimum_detection_contiguous_blocks",
    }
    output: dict[str, float | int] = {}
    for key, raw in value.items():
        if key in integer_fields:
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise S48PresealingGateError(f"{key} must be a positive integer")
            output[key] = raw
        else:
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(float(raw))
                or float(raw) < 0.0
            ):
                raise S48PresealingGateError(f"{key} must be finite and non-negative")
            output[key] = float(raw)
    for key in ("minimum_reference_correlation", "minimum_pair_coherence"):
        if float(output[key]) > 1.0:
            raise S48PresealingGateError(f"{key} must not exceed one")
    return output


def _validated_presealing_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(DEFAULT_PRESEALING_CONFIG):
        raise S48PresealingGateError("pre-sealing gate configuration fields mismatch")
    config = {
        key: (
            list(raw)
            if key == "microphone_channel_indices"
            else _validated_detector_config(raw)
            if key == "detector"
            else raw
        )
        for key, raw in value.items()
    }
    if config["schema"] != DEFAULT_PRESEALING_CONFIG["schema"]:
        raise S48PresealingGateError("pre-sealing config schema mismatch")
    integer_fields = (
        "sample_rate_hz",
        "channel_count",
        "maximum_clip_run_samples",
    )
    for key in integer_fields:
        raw = config[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise S48PresealingGateError(f"{key} must be a positive integer")
    microphone_indices = config["microphone_channel_indices"]
    if (
        not microphone_indices
        or any(
            isinstance(item, bool)
            or not isinstance(item, int)
            or item < 0
            or item >= config["channel_count"]
            for item in microphone_indices
        )
        or len(set(microphone_indices)) != len(microphone_indices)
    ):
        raise S48PresealingGateError("microphone_channel_indices are invalid")
    numeric_fields = (
        "capture_duration_s",
        "capture_duration_tolerance_s",
        "playback_start_s",
        "playback_start_tolerance_s",
        "playback_stop_s",
        "evaluation_start_s",
        "evaluation_stop_s",
        "minimum_useful_sound_coverage",
        "minimum_continuous_useful_s",
        "maximum_non_applicable_gap_s",
        "maximum_channel_rms_spread_db",
        "maximum_negative_reference_correlation",
    )
    for key in numeric_fields:
        raw = config[key]
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw))
        ):
            raise S48PresealingGateError(f"{key} must be finite numeric")
        config[key] = float(raw)
    if not (
        0.0
        <= config["playback_start_s"]
        < config["evaluation_start_s"]
        < config["evaluation_stop_s"]
        < config["playback_stop_s"]
        <= config["capture_duration_s"]
        and 0.0 <= config["minimum_useful_sound_coverage"] <= 1.0
        and config["minimum_continuous_useful_s"] > 0.0
        and config["maximum_non_applicable_gap_s"] >= 0.0
        and config["maximum_negative_reference_correlation"] < 0.0
    ):
        raise S48PresealingGateError("pre-sealing gate configuration domain failure")
    return config


def _process_record_authenticates(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    expected_fields = {
        "schema",
        "capture_sha256",
        "reference_sha256",
        "capture_started_monotonic_ns",
        "recorder_ready_monotonic_ns",
        "playback_started_monotonic_ns",
        "planned_playback_stop_monotonic_ns",
        "playback_stopped_monotonic_ns",
        "capture_stopped_monotonic_ns",
        "recorder_started",
        "recorder_exit_status",
        "producer_status",
        "playback_loop_enabled",
        "playback_exit_status",
        "record_sha256",
    }
    if set(value) != expected_fields or value.get("schema") != PROCESS_RECORD_SCHEMA:
        return False
    payload = {key: raw for key, raw in value.items() if key != "record_sha256"}
    if value.get("record_sha256") != canonical_sha256(payload):
        return False
    if not _is_sha256(value.get("capture_sha256")) or not _is_sha256(
        value.get("reference_sha256")
    ):
        return False
    for key in (
        "capture_started_monotonic_ns",
        "recorder_ready_monotonic_ns",
        "playback_started_monotonic_ns",
        "planned_playback_stop_monotonic_ns",
        "playback_stopped_monotonic_ns",
        "capture_stopped_monotonic_ns",
        "recorder_exit_status",
        "playback_exit_status",
    ):
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            return False
    if not isinstance(value.get("recorder_started"), bool) or not isinstance(
        value.get("playback_loop_enabled"), bool
    ):
        return False
    return isinstance(value.get("producer_status"), str)


def _process_timing(value: Mapping[str, Any]) -> dict[str, float] | None:
    try:
        capture_start = int(value["capture_started_monotonic_ns"])
        recorder_ready = int(value["recorder_ready_monotonic_ns"])
        playback_start = int(value["playback_started_monotonic_ns"])
        planned_stop = int(value["planned_playback_stop_monotonic_ns"])
        playback_stop = int(value["playback_stopped_monotonic_ns"])
        capture_stop = int(value["capture_stopped_monotonic_ns"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (
        capture_start
        <= recorder_ready
        <= playback_start
        <= planned_stop
        <= capture_stop
        and playback_start <= playback_stop <= capture_stop
    ):
        return None
    return {
        "recorder_ready_s": (recorder_ready - capture_start) / 1_000_000_000.0,
        "playback_start_s": (playback_start - capture_start) / 1_000_000_000.0,
        "planned_playback_stop_s": (planned_stop - capture_start) / 1_000_000_000.0,
        "playback_stop_s": (playback_stop - capture_start) / 1_000_000_000.0,
        "capture_stop_s": (capture_stop - capture_start) / 1_000_000_000.0,
    }


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _maximum_true_run(values: np.ndarray) -> int:
    maximum = 0
    current = 0
    for value in values:
        if bool(value):
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _read_pcm16_wav(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getsampwidth() != 2:
                raise S48PresealingGateError(f"{path}: expected signed 16-bit PCM WAV")
            channel_count = stream.getnchannels()
            sample_rate = stream.getframerate()
            frames = stream.readframes(stream.getnframes())
    except (OSError, wave.Error) as exc:
        raise S48PresealingGateError(f"{path}: WAV read failure: {exc}") from exc
    values = np.frombuffer(frames, dtype="<i2")
    if channel_count <= 0 or values.size % channel_count:
        raise S48PresealingGateError(f"{path}: invalid interleaved WAV shape")
    return (
        values.reshape(-1, channel_count).astype(np.float64) / 32768.0,
        sample_rate,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _median_channel_rms(frame: np.ndarray) -> float:
    return float(np.median(np.sqrt(np.mean(frame * frame, axis=1))))


def _looped_reference(
    reference: np.ndarray,
    *,
    start_sample: int,
    stop_sample: int,
    playback_start_sample: int,
) -> np.ndarray:
    indices = (
        np.arange(start_sample, stop_sample) - playback_start_sample
    ) % reference.size
    return reference[indices]


def _best_signed_correlation(
    left: np.ndarray,
    right: np.ndarray,
    maximum_lag_samples: int,
) -> float:
    best = 0.0
    for lag in range(-maximum_lag_samples, maximum_lag_samples + 1):
        if lag < 0:
            x = left[-lag:]
            y = right[:lag]
        elif lag > 0:
            x = left[:-lag]
            y = right[lag:]
        else:
            x = left
            y = right
        x_centered = x - float(np.mean(x))
        y_centered = y - float(np.mean(y))
        denominator = float(
            np.sqrt(np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered))
        )
        value = (
            float(np.dot(x_centered, y_centered) / denominator)
            if denominator > 0.0
            else 0.0
        )
        if abs(value) > abs(best):
            best = value
    return best


def _boolean_runs(values: Sequence[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(values):
        if not values[cursor]:
            cursor += 1
            continue
        stop = cursor + 1
        while stop < len(values) and values[stop]:
            stop += 1
        runs.append((cursor, stop))
        cursor = stop
    return runs


def _block_interval(
    decisions: Sequence[Mapping[str, Any]],
    run: tuple[int, int],
    sample_rate_hz: int,
) -> dict[str, float | int]:
    start, stop = run
    start_sample = int(decisions[start]["start_sample"])
    end_sample = int(decisions[stop - 1]["end_sample"])
    return {
        "first_block_index": start,
        "last_block_index": stop - 1,
        "start_sample": start_sample,
        "end_sample": end_sample,
        "start_s": start_sample / sample_rate_hz,
        "end_s": end_sample / sample_rate_hz,
        "duration_s": (end_sample - start_sample) / sample_rate_hz,
        "block_count": stop - start,
    }
