"""Forward-only S4.8 v2 acoustic alignment and engineering controls.

Version 1 remains implemented in :mod:`s4_8_presealing_gate`.  This module
uses process timing only to bound an acoustic search, establishes phase from
the waveform, and tracks bounded recorder/player clock drift block by block.
It reads no scientific outcome fields.
"""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

import jsonschema
import numpy as np

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (
    S48PresealingGateError,
    canonical_sha256,
)

TRACKED_DETECTOR_METHOD_V2 = "waveform_aligned_tracked_looped_reference_v2"

# The v1 energy, correlation, coherence, channel-count, continuity, coverage,
# and gap limits are copied unchanged.  The alignment fields are new technical
# limits, expressed in samples or ppm, and are intentionally broad relative to
# ordinary USB-audio buffering and independent device clock error.
DEFAULT_ALIGNMENT_CONFIG_V2: dict[str, float | int] = {
    "analysis_block_samples": 2_000,
    "basic_rms_floor": 0.002,
    "background_normalized_mad_scale": 1.4826,
    "background_mad_multiplier": 5.0,
    "minimum_reference_correlation": 0.20,
    "minimum_pair_coherence": 0.10,
    "minimum_correlated_channel_count": 3,
    "maximum_reference_lag_samples": 16,
    "minimum_detection_contiguous_blocks": 8,
    "initial_alignment_search_samples": 3_200,
    "initial_alignment_probe_samples": 2_000,
    "maximum_acoustic_start_delay_samples": 2_000,
    "stop_sentinel_block_samples": 2_000,
    "tracking_search_radius_samples": 16,
    "maximum_tracking_step_samples": 4,
    "maximum_total_drift_ppm": 1_000.0,
    "discontinuity_search_radius_samples": 512,
    "minimum_discontinuous_jump_samples": 64,
}
PRESEALING_CONFIG_PATH_V2 = Path("configs/s4_8_presealing_gate.v2.json")
PRESEALING_CONFIG_SCHEMA_PATH_V2 = Path(
    "docs/schemas/s4_8_presealing_gate_config.v2.schema.json"
)
DEFAULT_PRESEALING_CONFIG_V2: dict[str, Any] = {
    "schema": "ias.s4_8.presealing_gate_config.v2",
    "sample_rate_hz": 16_000,
    "channel_count": 6,
    "microphone_channel_indices": [2, 3, 4, 5],
    "expected_device_profile_id": "respeaker_usb_6ch_pcm16_v1",
    "expected_channel_map": [
        "Conference",
        "ASR",
        "raw microphone 0",
        "raw microphone 1",
        "raw microphone 2",
        "raw microphone 3",
    ],
    "reference_active_start_s": 2.25,
    "reference_active_stop_s": 7.25,
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
    "controller_requested_termination_signal": 15,
    "maximum_clip_run_samples": 8,
    "maximum_total_clipped_samples_per_channel": 64,
    "maximum_clipped_sample_rate": 0.0002,
    "repeated_buffer_block_samples": 2_000,
    "maximum_consecutive_identical_buffers": 2,
    "maximum_zero_lag_channel_correlation": 0.995,
    "maximum_channel_rms_spread_db": 6.0,
    "maximum_negative_reference_correlation": -0.20,
    "detector": DEFAULT_ALIGNMENT_CONFIG_V2,
}


def load_presealing_config_v2(repo_root: Path) -> dict[str, Any]:
    """Load and schema-check the exact tracked v2 technical configuration."""

    root = repo_root.resolve()
    try:
        raw = json.loads((root / PRESEALING_CONFIG_PATH_V2).read_text(encoding="utf-8"))
        schema = json.loads(
            (root / PRESEALING_CONFIG_SCHEMA_PATH_V2).read_text(encoding="utf-8")
        )
        jsonschema.validate(raw, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise S48PresealingGateError(f"v2 configuration failure: {exc}") from exc
    if raw != DEFAULT_PRESEALING_CONFIG_V2:
        raise S48PresealingGateError("v2 configuration identity mismatch")
    return raw


def read_pcm16_wav_strict(path: Path) -> tuple[np.ndarray, int]:
    """Read an internally consistent, uncompressed signed PCM16 RIFF/WAV."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise S48PresealingGateError(f"{path}: WAV read failure: {exc}") from exc
    if (
        len(raw) < 12
        or raw[:4] != b"RIFF"
        or raw[8:12] != b"WAVE"
        or struct.unpack_from("<I", raw, 4)[0] != len(raw) - 8
    ):
        raise S48PresealingGateError(f"{path}: malformed or inconsistent RIFF header")
    offset = 12
    fmt: bytes | None = None
    audio: bytes | None = None
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise S48PresealingGateError(f"{path}: incomplete WAV chunk header")
        chunk_id = raw[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", raw, offset + 4)[0]
        start = offset + 8
        stop = start + chunk_size
        padded_stop = stop + (chunk_size % 2)
        if stop > len(raw) or padded_stop > len(raw):
            raise S48PresealingGateError(f"{path}: incomplete WAV chunk or frame")
        chunk = raw[start:stop]
        if chunk_id == b"fmt ":
            if fmt is not None:
                raise S48PresealingGateError(f"{path}: duplicate WAV fmt chunk")
            fmt = chunk
        elif chunk_id == b"data":
            if audio is not None:
                raise S48PresealingGateError(f"{path}: duplicate WAV data chunk")
            audio = chunk
        offset = padded_stop
    if offset != len(raw) or fmt is None or audio is None or len(fmt) < 16:
        raise S48PresealingGateError(f"{path}: incomplete WAV structure")
    (
        audio_format,
        channel_count,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    ) = struct.unpack_from("<HHIIHH", fmt, 0)
    expected_align = channel_count * 2
    if (
        audio_format != 1
        or bits_per_sample != 16
        or channel_count <= 0
        or sample_rate <= 0
        or block_align != expected_align
        or byte_rate != sample_rate * expected_align
    ):
        raise S48PresealingGateError(
            f"{path}: expected signed 16-bit uncompressed PCM WAV"
        )
    if len(audio) % block_align:
        raise S48PresealingGateError(f"{path}: incomplete or inconsistent WAV frames")
    values = np.frombuffer(audio, dtype="<i2")
    if values.size != (len(audio) // block_align) * channel_count:
        raise S48PresealingGateError(f"{path}: inconsistent WAV frame count")
    return (
        values.reshape(-1, channel_count).astype(np.float64) / 32768.0,
        sample_rate,
    )


def normalize_reference_for_capture_rate(
    reference: np.ndarray,
    *,
    reference_sample_rate_hz: int,
    capture_sample_rate_hz: int,
) -> np.ndarray:
    """Deterministically normalize an exact higher-rate reference.

    Only an exact integer downsampling ratio is supported.  Each output sample
    is the mean of one non-overlapping source-rate block, which provides a
    fixed boxcar anti-alias filter without adding an environment dependency.
    The authenticated input remains the original reference file.
    """

    array = np.asarray(reference, dtype=np.float64)
    if (
        array.ndim not in {1, 2}
        or array.shape[0] == 0
        or isinstance(reference_sample_rate_hz, bool)
        or isinstance(capture_sample_rate_hz, bool)
        or not isinstance(reference_sample_rate_hz, int)
        or not isinstance(capture_sample_rate_hz, int)
        or reference_sample_rate_hz <= 0
        or capture_sample_rate_hz <= 0
        or reference_sample_rate_hz < capture_sample_rate_hz
        or reference_sample_rate_hz % capture_sample_rate_hz
        or array.shape[0]
        % (reference_sample_rate_hz // capture_sample_rate_hz)
    ):
        raise S48PresealingGateError(
            "reference/capture sample rates require an exact integer ratio"
        )
    ratio = reference_sample_rate_hz // capture_sample_rate_hz
    if ratio == 1:
        return array.copy()
    if array.ndim == 1:
        return array.reshape(-1, ratio).mean(axis=1)
    return array.reshape(-1, ratio, array.shape[1]).mean(axis=1)


def select_active_reference_interval_v2(
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    config: Mapping[str, Any],
) -> np.ndarray:
    """Select the preregistered active interval from the exact reference."""

    if dict(config) != DEFAULT_PRESEALING_CONFIG_V2:
        raise S48PresealingGateError("v2 gate configuration mismatch")
    array = np.asarray(reference, dtype=np.float64)
    start = round(float(config["reference_active_start_s"]) * sample_rate_hz)
    stop = round(float(config["reference_active_stop_s"]) * sample_rate_hz)
    if (
        isinstance(sample_rate_hz, bool)
        or not isinstance(sample_rate_hz, int)
        or sample_rate_hz <= 0
        or array.ndim not in {1, 2}
        or start < 0
        or stop <= start
        or stop > array.shape[0]
    ):
        raise S48PresealingGateError(
            "exact reference active interval is invalid"
        )
    return array[start:stop].copy()


def evaluate_capture_integrity_v2(
    capture: np.ndarray,
    *,
    sample_rate_hz: int,
    device_profile_id: str | None,
    channel_map: Sequence[str] | None,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate outcome-independent capture, channel, and device integrity."""

    if dict(config) != DEFAULT_PRESEALING_CONFIG_V2:
        raise S48PresealingGateError("v2 capture-integrity configuration mismatch")
    gate = DEFAULT_PRESEALING_CONFIG_V2
    array = np.asarray(capture, dtype=np.float64)
    reasons: list[dict[str, Any]] = []

    def reject(code: str, category: str, message: str, **details: Any) -> None:
        reasons.append(
            {
                "code": code,
                "category": category,
                "message": message,
                "details": details,
            }
        )

    if array.ndim != 2 or array.shape[0] == 0:
        reject(
            "capture_shape_invalid",
            "integrity",
            "capture must be frames by channels",
        )
        channel_count = 0
    else:
        channel_count = int(array.shape[1])
    if not np.all(np.isfinite(array)):
        reject("capture_non_finite", "integrity", "capture contains non-finite samples")
    if sample_rate_hz != gate["sample_rate_hz"]:
        reject(
            "sample_rate_mismatch",
            "integrity",
            "capture sample rate does not match the frozen profile",
            expected=gate["sample_rate_hz"],
            actual=sample_rate_hz,
        )
    if channel_count != gate["channel_count"]:
        reject(
            "channel_count_mismatch",
            "channel_health",
            "capture channel count does not match the frozen profile",
            expected=gate["channel_count"],
            actual=channel_count,
        )
    if device_profile_id is None:
        reject(
            "device_profile_identity_missing",
            "integrity",
            "capture device/profile identity is required",
        )
    elif device_profile_id != gate["expected_device_profile_id"]:
        reject(
            "device_profile_identity_mismatch",
            "integrity",
            "capture device/profile identity does not match",
            expected=gate["expected_device_profile_id"],
            actual=device_profile_id,
        )
    if channel_map is None:
        reject(
            "channel_map_identity_missing",
            "channel_health",
            "authenticated channel map is required",
        )
    elif list(channel_map) != gate["expected_channel_map"]:
        reject(
            "channel_map_identity_mismatch",
            "channel_health",
            "authenticated channel map does not match",
            expected=gate["expected_channel_map"],
            actual=list(channel_map),
        )

    metrics: dict[str, Any] = {
        "maximum_identical_buffer_run": 0,
        "maximum_zero_lag_channel_correlation": None,
        "maximum_clip_run_samples_by_channel": [],
        "total_clipped_samples_by_channel": [],
        "clipped_sample_rate_by_channel": [],
        "rms_by_channel": [],
        "rms_spread_db": None,
    }
    structurally_valid = (
        array.ndim == 2
        and channel_count == gate["channel_count"]
        and np.all(np.isfinite(array))
        and sample_rate_hz > 0
    )
    if structurally_valid:
        microphone_indices = gate["microphone_channel_indices"]
        microphones = array[:, microphone_indices]
        block = gate["repeated_buffer_block_samples"]
        buffer_keys = [
            microphones[start : start + block].tobytes(order="C")
            for start in range(0, microphones.shape[0] - block + 1, block)
        ]
        identical_run = _maximum_identical_item_run(buffer_keys)
        metrics["maximum_identical_buffer_run"] = identical_run
        if identical_run > gate["maximum_consecutive_identical_buffers"]:
            reject(
                "frozen_or_repeated_capture_buffer",
                "integrity",
                "identical microphone buffers repeat beyond the frozen limit",
                maximum=gate["maximum_consecutive_identical_buffers"],
                actual=identical_run,
            )

        evaluation = microphones[
            round(gate["evaluation_start_s"] * sample_rate_hz) : round(
                gate["evaluation_stop_s"] * sample_rate_hz
            )
        ]
        pair_correlations = [
            abs(_signed_correlation(evaluation[:, left], evaluation[:, right]))
            for left in range(evaluation.shape[1])
            for right in range(left + 1, evaluation.shape[1])
        ]
        maximum_pair = max(pair_correlations, default=0.0)
        metrics["maximum_zero_lag_channel_correlation"] = maximum_pair
        if maximum_pair >= gate["maximum_zero_lag_channel_correlation"]:
            reject(
                "suspicious_duplicate_microphone_channels",
                "channel_health",
                "microphone channels are duplicated or exhibit extreme crosstalk",
                maximum=gate["maximum_zero_lag_channel_correlation"],
                actual=maximum_pair,
            )

        clipped = np.abs(microphones) >= (32767.0 / 32768.0)
        clip_runs = [
            _maximum_true_run(clipped[:, channel])
            for channel in range(clipped.shape[1])
        ]
        clip_counts = [
            int(np.count_nonzero(clipped[:, channel]))
            for channel in range(clipped.shape[1])
        ]
        clip_rates = [count / microphones.shape[0] for count in clip_counts]
        metrics["maximum_clip_run_samples_by_channel"] = clip_runs
        metrics["total_clipped_samples_by_channel"] = clip_counts
        metrics["clipped_sample_rate_by_channel"] = clip_rates
        if max(clip_runs, default=0) > gate["maximum_clip_run_samples"]:
            reject(
                "clipping_limit_exceeded",
                "clipping",
                "consecutive full-scale clipping exceeds the frozen v1 limit",
                maximum=gate["maximum_clip_run_samples"],
                actual=max(clip_runs),
            )
        if any(
            count > gate["maximum_total_clipped_samples_per_channel"]
            or rate > gate["maximum_clipped_sample_rate"]
            for count, rate in zip(clip_counts, clip_rates, strict=True)
        ):
            reject(
                "distributed_clipping_limit_exceeded",
                "clipping",
                "total full-scale clipping exceeds the v2 distributed limit",
                maximum_samples=gate["maximum_total_clipped_samples_per_channel"],
                maximum_rate=gate["maximum_clipped_sample_rate"],
                actual_samples=clip_counts,
                actual_rates=clip_rates,
            )

        rms = np.sqrt(np.mean(evaluation * evaluation, axis=0))
        positive = rms[rms > 0.0]
        spread_db = (
            float(20.0 * np.log10(np.max(positive) / np.min(positive)))
            if positive.size == rms.size
            else math.inf
        )
        metrics["rms_by_channel"] = [float(value) for value in rms]
        metrics["rms_spread_db"] = spread_db
        if spread_db > gate["maximum_channel_rms_spread_db"]:
            reject(
                "channel_gain_imbalance",
                "channel_health",
                "channel RMS spread exceeds the unchanged v1 limit",
                maximum_db=gate["maximum_channel_rms_spread_db"],
                actual_db=spread_db,
            )
    return {
        "schema": "ias.s4_8.capture_integrity.v2",
        "decision": "PASS" if not reasons else "RETRY_REQUIRED",
        "reasons": reasons,
        "metrics": metrics,
        "device_profile_id": device_profile_id,
        "channel_map": list(channel_map) if channel_map is not None else None,
    }


def evaluate_presealing_gate_v2(
    capture: np.ndarray,
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    observed_process: Mapping[str, Any],
    manifest_sha256: str,
    process_journal_head_sha256: str,
    config: Mapping[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    """Evaluate the complete v2 technical gate from validated journal facts."""

    if dict(config) != DEFAULT_PRESEALING_CONFIG_V2:
        raise S48PresealingGateError("v2 gate configuration mismatch")
    gate = DEFAULT_PRESEALING_CONFIG_V2
    capture_array = np.asarray(capture, dtype=np.float64)
    reference_array = np.asarray(reference, dtype=np.float64)
    if reference_array.ndim == 2:
        reference_array = np.mean(reference_array, axis=1)
    integrity = evaluate_capture_integrity_v2(
        capture_array,
        sample_rate_hz=sample_rate_hz,
        device_profile_id=observed_process.get("device_profile_id"),
        channel_map=observed_process.get("channel_map"),
        config=gate,
    )
    reasons = [dict(item) for item in integrity["reasons"]]
    seen = {str(item["code"]) for item in reasons}

    def reject(code: str, category: str, message: str, **details: Any) -> None:
        if code not in seen:
            seen.add(code)
            reasons.append(
                {
                    "code": code,
                    "category": category,
                    "message": message,
                    "details": details,
                }
            )

    required_process_fields = {
        "capture_sha256",
        "reference_sha256",
        "capture_started_monotonic_ns",
        "recorder_ready_monotonic_ns",
        "playback_started_monotonic_ns",
        "planned_playback_stop_monotonic_ns",
        "playback_terminated_monotonic_ns",
        "recorder_terminated_monotonic_ns",
        "recorder_exit_status",
        "playback_exit_status",
        "device_profile_id",
        "channel_map",
    }
    if not required_process_fields.issubset(observed_process):
        reject(
            "process_journal_incomplete",
            "integrity",
            "validated process journal lacks required observed events",
        )
        timing_valid = False
    else:
        timing_values = [
            observed_process["capture_started_monotonic_ns"],
            observed_process["recorder_ready_monotonic_ns"],
            observed_process["playback_started_monotonic_ns"],
            observed_process["planned_playback_stop_monotonic_ns"],
            observed_process["playback_terminated_monotonic_ns"],
            observed_process["recorder_terminated_monotonic_ns"],
        ]
        timing_valid = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in timing_values
        ) and all(left <= right for left, right in pairwise(timing_values))
        if not timing_valid:
            reject(
                "process_timing_invalid",
                "integrity",
                "validated process events are not complete and monotonic",
            )
    if not _successful_process_termination(
        observed_process,
        prefix="recorder",
        configured_signal=gate["controller_requested_termination_signal"],
    ):
        reject(
            "recorder_process_failed",
            "integrity",
            (
                "recorder termination status was not successful "
                "or controller-authenticated"
            ),
            exit_status=observed_process.get("recorder_exit_status"),
        )
    if not _successful_process_termination(
        observed_process,
        prefix="playback",
        configured_signal=gate["controller_requested_termination_signal"],
    ):
        reject(
            "playback_process_failed",
            "integrity",
            "player termination status was not successful or controller-authenticated",
            exit_status=observed_process.get("playback_exit_status"),
        )
    if observed_process.get("process_identity_consistent") is not True:
        reject(
            "process_identity_mismatch",
            "integrity",
            "recorder/player process identities changed across observed events",
        )
    if (
        observed_process.get("capture_sha256") is None
        or observed_process.get("reference_sha256") is None
    ):
        reject(
            "capture_reference_authentication_missing",
            "integrity",
            "capture/reference hashes are absent from the process journal",
        )

    waveform: dict[str, Any] | None = None
    if (
        timing_valid
        and capture_array.ndim == 2
        and capture_array.shape[1] == gate["channel_count"]
        and sample_rate_hz == gate["sample_rate_hz"]
        and reference_array.ndim == 1
        and reference_array.size > 0
    ):
        capture_start = int(observed_process["capture_started_monotonic_ns"])
        process_start_s = (
            int(observed_process["playback_started_monotonic_ns"]) - capture_start
        ) / 1_000_000_000.0
        planned_stop_s = (
            int(observed_process["planned_playback_stop_monotonic_ns"]) - capture_start
        ) / 1_000_000_000.0
        playback_terminated_s = (
            int(observed_process["playback_terminated_monotonic_ns"]) - capture_start
        ) / 1_000_000_000.0
        recorder_terminated_s = (
            int(observed_process["recorder_terminated_monotonic_ns"]) - capture_start
        ) / 1_000_000_000.0
        actual_duration_s = capture_array.shape[0] / sample_rate_hz
        if (
            abs(process_start_s - gate["playback_start_s"])
            > gate["playback_start_tolerance_s"]
        ):
            reject(
                "playback_start_outside_tolerance",
                "integrity",
                "observed player start is outside the process timing boundary",
                expected_s=gate["playback_start_s"],
                actual_s=process_start_s,
            )
        if abs(planned_stop_s - gate["playback_stop_s"]) > 1e-9:
            reject(
                "planned_playback_stop_mismatch",
                "integrity",
                "planned player stop contradicts the protocol",
                expected_s=gate["playback_stop_s"],
                actual_s=planned_stop_s,
            )
        if playback_terminated_s < planned_stop_s:
            reject(
                "playback_stopped_early",
                "continuity",
                "player terminated before its planned stop",
                planned_s=planned_stop_s,
                actual_s=playback_terminated_s,
            )
        if (
            abs(recorder_terminated_s - actual_duration_s)
            > gate["capture_duration_tolerance_s"]
        ):
            reject(
                "capture_stop_timing_mismatch",
                "integrity",
                "recorder termination contradicts waveform duration",
                process_duration_s=recorder_terminated_s,
                waveform_duration_s=actual_duration_s,
            )
        process_start_sample = round(process_start_s * sample_rate_hz)
        planned_stop_sample = round(planned_stop_s * sample_rate_hz)
        post_roll_start = max(
            planned_stop_sample,
            round(playback_terminated_s * sample_rate_hz),
        )
        try:
            waveform = evaluate_presealing_waveform_v2(
                capture_array[:, gate["microphone_channel_indices"]].T,
                reference_array,
                sample_rate_hz=sample_rate_hz,
                process_playback_start_sample=process_start_sample,
                planned_playback_stop_sample=planned_stop_sample,
                evaluation_start_sample=round(
                    gate["evaluation_start_s"] * sample_rate_hz
                ),
                evaluation_stop_sample=round(
                    gate["evaluation_stop_s"] * sample_rate_hz
                ),
                background_intervals=(
                    (0, process_start_sample),
                    (post_roll_start, capture_array.shape[0]),
                ),
                config=gate["detector"],
            )
        except S48PresealingGateError as exc:
            reject(
                "detector_input_invalid",
                "integrity",
                "v2 waveform detector rejected its input",
                error=str(exc),
            )
        if waveform is not None:
            for item in waveform["reasons"]:
                reject(
                    str(item["code"]),
                    str(item["category"]),
                    str(item["message"]),
                    **dict(item["details"]),
                )
            alignment = waveform["alignment"]
            coverage = float(alignment["useful_sound_coverage"])
            longest = alignment["longest_continuous_useful_interval"]
            longest_s = float(longest["duration_s"]) if longest else 0.0
            maximum_gap_s = float(alignment["maximum_non_applicable_gap_s"])
            if coverage < gate["minimum_useful_sound_coverage"]:
                reject(
                    "useful_sound_coverage_below_minimum",
                    "coverage",
                    "useful reference coverage is below the unchanged v1 minimum",
                    minimum=gate["minimum_useful_sound_coverage"],
                    actual=coverage,
                )
            if longest_s < gate["minimum_continuous_useful_s"]:
                reject(
                    "continuous_useful_interval_too_short",
                    "continuity",
                    "continuous useful interval is below the unchanged v1 minimum",
                    minimum_s=gate["minimum_continuous_useful_s"],
                    actual_s=longest_s,
                )
            if maximum_gap_s > gate["maximum_non_applicable_gap_s"]:
                reject(
                    "non_applicable_gap_too_long",
                    "continuity",
                    "non-applicable gap exceeds the unchanged v1 maximum",
                    maximum_s=gate["maximum_non_applicable_gap_s"],
                    actual_s=maximum_gap_s,
                )
            per_channel_correlations = [
                float(
                    median(
                        decision["reference_correlation_by_channel"][channel]
                        for decision in alignment["decisions"]
                    )
                )
                for channel in range(len(gate["microphone_channel_indices"]))
            ]
            if any(
                value <= gate["maximum_negative_reference_correlation"]
                for value in per_channel_correlations
            ):
                reject(
                    "channel_polarity_inversion",
                    "channel_health",
                    "a microphone has stable negative reference correlation",
                    correlations=per_channel_correlations,
                )

    detector_hash = canonical_sha256(gate["detector"])
    configuration_hash = canonical_sha256(gate)
    return {
        "schema": "ias.s4_8.presealing_gate_report.v2",
        "decision": "PASS" if not reasons else "RETRY_REQUIRED",
        "reasons": reasons,
        "dry_run": dry_run,
        "input_provenance": {
            "capture_sha256": observed_process.get("capture_sha256"),
            "reference_sha256": observed_process.get("reference_sha256"),
            "manifest_sha256": manifest_sha256,
            "process_journal_head_sha256": process_journal_head_sha256,
            "configuration_sha256": configuration_hash,
            "detector_configuration_sha256": detector_hash,
            "outcome_fields_read": [],
        },
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
            "official_take_seal": False,
        },
        "configuration": gate,
        "configuration_sha256": configuration_hash,
        "detector_configuration_sha256": detector_hash,
        "capture_integrity": integrity,
        "waveform": waveform,
    }


def _maximum_true_run(values: np.ndarray) -> int:
    maximum = 0
    current = 0
    for value in values:
        current = current + 1 if bool(value) else 0
        maximum = max(maximum, current)
    return maximum


def _successful_process_termination(
    observed_process: Mapping[str, Any],
    *,
    prefix: str,
    configured_signal: int,
) -> bool:
    status = observed_process.get(f"{prefix}_exit_status")
    if status == 0:
        return True
    return (
        observed_process.get(f"{prefix}_controller_requested_termination") is True
        and observed_process.get(f"{prefix}_controller_requested_signal")
        == configured_signal
        and status == -configured_signal
    )


def _maximum_identical_item_run(values: Sequence[bytes]) -> int:
    maximum = 0
    current = 0
    previous: bytes | None = None
    for value in values:
        current = current + 1 if value == previous else 1
        maximum = max(maximum, current)
        previous = value
    return maximum


def evaluate_presealing_waveform_v2(
    microphones: np.ndarray,
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    process_playback_start_sample: int,
    planned_playback_stop_sample: int,
    evaluation_start_sample: int,
    evaluation_stop_sample: int,
    background_intervals: Sequence[tuple[int, int]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply v2 alignment plus independent acoustic start/stop sentinels."""

    detector = _validated_alignment_config(config)
    alignment = detect_tracked_reference_activity_v2(
        microphones,
        reference,
        sample_rate_hz=sample_rate_hz,
        process_playback_start_sample=process_playback_start_sample,
        planned_playback_stop_sample=planned_playback_stop_sample,
        evaluation_start_sample=evaluation_start_sample,
        evaluation_stop_sample=evaluation_stop_sample,
        background_intervals=background_intervals,
        config=detector,
    )
    reasons: list[dict[str, Any]] = []

    def reject(code: str, message: str, **details: Any) -> None:
        reasons.append(
            {
                "code": code,
                "category": "playback_presence",
                "message": message,
                "details": details,
            }
        )

    latency_samples = int(alignment["initial_acoustic_latency_samples"])
    if "initial_alignment_not_established" in alignment[
        "alignment_failure_reasons"
    ] or latency_samples > int(detector["maximum_acoustic_start_delay_samples"]):
        reject(
            "acoustic_playback_started_late",
            "waveform onset is outside the technical acoustic-start sentinel",
            maximum_delay_samples=detector["maximum_acoustic_start_delay_samples"],
            observed_delay_samples=latency_samples,
        )
    other_alignment_failures = [
        reason
        for reason in alignment["alignment_failure_reasons"]
        if reason != "initial_alignment_not_established"
    ]
    if other_alignment_failures:
        reject(
            "reference_alignment_failed",
            "waveform-derived reference alignment was not maintained",
            failure_reasons=other_alignment_failures,
        )

    stop_sentinel = _evaluate_stop_sentinel(
        np.asarray(microphones, dtype=np.float64),
        np.asarray(reference, dtype=np.float64),
        alignment=alignment,
        planned_playback_stop_sample=planned_playback_stop_sample,
        config=detector,
    )
    if not stop_sentinel["present"]:
        reject(
            "acoustic_playback_stopped_early",
            "waveform reference is absent from the final playback sentinel",
            **stop_sentinel,
        )
    return {
        "schema": "ias.s4_8.presealing_waveform.v2",
        "decision": "PASS" if not reasons else "RETRY_REQUIRED",
        "reasons": reasons,
        "sentinels": {
            "start": {
                "process_start_sample": process_playback_start_sample,
                "acoustic_start_sample": alignment["initial_acoustic_start_sample"],
                "delay_samples": latency_samples,
                "maximum_delay_samples": detector[
                    "maximum_acoustic_start_delay_samples"
                ],
                "present": not any(
                    item["code"] == "acoustic_playback_started_late" for item in reasons
                ),
            },
            "stop": stop_sentinel,
        },
        "alignment": alignment,
    }


def detect_tracked_reference_activity_v2(
    microphones: np.ndarray,
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    process_playback_start_sample: int,
    planned_playback_stop_sample: int,
    evaluation_start_sample: int,
    evaluation_stop_sample: int,
    background_intervals: Sequence[tuple[int, int]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Detect and track a looped acoustic reference without exact-phase trust."""

    detector = _validated_alignment_config(config)
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
    block = int(detector["analysis_block_samples"])
    if (
        process_playback_start_sample < 0
        or planned_playback_stop_sample <= process_playback_start_sample
        or planned_playback_stop_sample > mic.shape[1]
        or evaluation_start_sample < process_playback_start_sample
        or evaluation_stop_sample <= evaluation_start_sample
        or evaluation_stop_sample > planned_playback_stop_sample
        or (evaluation_stop_sample - evaluation_start_sample) % block != 0
    ):
        raise S48PresealingGateError("playback/evaluation sample interval is invalid")

    background_rms, normalized_background = _authenticated_background(
        mic,
        background_intervals=background_intervals,
        block_samples=block,
        process_playback_start_sample=process_playback_start_sample,
        sample_rate_hz=sample_rate_hz,
    )
    background_median = float(median(background_rms))
    background_mad = float(
        median(abs(value - background_median) for value in background_rms)
    )
    robust_rms_threshold = max(
        float(detector["basic_rms_floor"]),
        background_median
        + float(detector["background_mad_multiplier"])
        * float(detector["background_normalized_mad_scale"])
        * background_mad,
    )

    acoustic_start, initial_correlation = _estimate_initial_acoustic_start(
        mic,
        ref,
        process_start=process_playback_start_sample,
        search_samples=int(detector["initial_alignment_search_samples"]),
        probe_samples=int(detector["initial_alignment_probe_samples"]),
    )
    alignment_failure_reasons: list[str] = []
    if acoustic_start is None or initial_correlation < float(
        detector["minimum_reference_correlation"]
    ):
        alignment_failure_reasons.append("initial_alignment_not_established")
        acoustic_start = process_playback_start_sample

    decisions: list[dict[str, Any]] = []
    raw_candidates: list[bool] = []
    reason_sets: list[list[str]] = []
    tracked_adjustment = 0
    tracked_samples: list[float] = []
    tracked_adjustments: list[float] = []
    alignment_maintained = not alignment_failure_reasons
    for index, start in enumerate(
        range(evaluation_start_sample, evaluation_stop_sample, block)
    ):
        stop = start + block
        frame = mic[:, start:stop]
        nominal_phase = start - acoustic_start
        adjustment, tracking_correlation = _best_common_phase_adjustment(
            frame,
            ref,
            nominal_phase=nominal_phase,
            center_adjustment=tracked_adjustment,
            radius=int(detector["tracking_search_radius_samples"]),
        )
        step = adjustment - tracked_adjustment
        local_reasons: list[str] = []
        if tracking_correlation < float(detector["minimum_reference_correlation"]):
            wide_adjustment, wide_correlation = _best_common_phase_adjustment(
                frame,
                ref,
                nominal_phase=nominal_phase,
                center_adjustment=tracked_adjustment,
                radius=int(detector["discontinuity_search_radius_samples"]),
            )
            if wide_correlation >= float(
                detector["minimum_reference_correlation"]
            ) and abs(wide_adjustment - tracked_adjustment) >= int(
                detector["minimum_discontinuous_jump_samples"]
            ):
                local_reasons.append("phase_discontinuity")
            else:
                local_reasons.append("reference_alignment_lost")
        elif abs(step) > int(detector["maximum_tracking_step_samples"]):
            local_reasons.append("implausible_alignment_step")
        if local_reasons:
            alignment_maintained = False
            for reason in local_reasons:
                if reason not in alignment_failure_reasons:
                    alignment_failure_reasons.append(reason)
        else:
            tracked_adjustment = adjustment
            tracked_samples.append(float(start - acoustic_start))
            tracked_adjustments.append(float(tracked_adjustment))

        reference_frame = _reference_frame(
            ref,
            phase_start=nominal_phase + tracked_adjustment,
            sample_count=block,
        )
        rms_by_channel = np.sqrt(np.mean(frame * frame, axis=1))
        correlations = [
            _best_signed_correlation(
                channel,
                reference_frame,
                int(detector["maximum_reference_lag_samples"]),
            )
            for channel in frame
        ]
        pair_coherences = [
            abs(
                _best_signed_correlation(
                    frame[left],
                    frame[right],
                    int(detector["maximum_reference_lag_samples"]) * 2,
                )
            )
            for left in range(frame.shape[0])
            for right in range(left + 1, frame.shape[0])
        ]
        rms_median = float(np.median(rms_by_channel))
        reference_correlation = float(np.median(correlations))
        pair_coherence = float(np.median(pair_coherences))
        correlated_channels = sum(
            value >= float(detector["minimum_reference_correlation"])
            for value in correlations
        )
        reasons = list(local_reasons)
        if rms_median <= float(detector["basic_rms_floor"]):
            reasons.append("basic_energy")
        if rms_median <= robust_rms_threshold:
            reasons.append("background_energy")
        if reference_correlation < float(
            detector["minimum_reference_correlation"]
        ) or correlated_channels < int(detector["minimum_correlated_channel_count"]):
            reasons.append("reference_correlation")
        if pair_coherence < float(detector["minimum_pair_coherence"]):
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
                "alignment_adjustment_samples": tracked_adjustment,
                "alignment_step_samples": step,
                "tracking_correlation": tracking_correlation,
                "rms_median": rms_median,
                "rms_by_channel": [float(value) for value in rms_by_channel],
                "reference_correlation": reference_correlation,
                "reference_correlation_by_channel": correlations,
                "correlated_channel_count": correlated_channels,
                "pair_coherence": pair_coherence,
                "candidate": candidate,
            }
        )

    estimated_drift_ppm = _estimate_drift_ppm(
        tracked_samples,
        tracked_adjustments,
    )
    if abs(estimated_drift_ppm) > float(detector["maximum_total_drift_ppm"]):
        alignment_maintained = False
        alignment_failure_reasons.append("implausible_clock_drift")

    useful = [False] * len(raw_candidates)
    useful_runs: list[tuple[int, int]] = []
    for start, stop in _boolean_runs(raw_candidates):
        if stop - start >= int(detector["minimum_detection_contiguous_blocks"]):
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
    correlations = [float(item["reference_correlation"]) for item in decisions]
    useful_count = sum(useful)
    return {
        "method": TRACKED_DETECTOR_METHOD_V2,
        "alignment_status": "maintained" if alignment_maintained else "failed",
        "alignment_failure_reasons": alignment_failure_reasons,
        "process_playback_start_sample": process_playback_start_sample,
        "initial_acoustic_start_sample": acoustic_start,
        "initial_acoustic_latency_samples": (
            acoustic_start - process_playback_start_sample
        ),
        "initial_alignment_correlation": initial_correlation,
        "estimated_drift_ppm": estimated_drift_ppm,
        "maximum_observed_tracking_step_samples": max(
            (abs(int(item["alignment_step_samples"])) for item in decisions),
            default=0,
        ),
        "source_block_count": len(decisions),
        "candidate_block_count": sum(raw_candidates),
        "useful_block_count": useful_count,
        "non_applicable_block_count": len(decisions) - useful_count,
        "useful_sound_coverage": useful_count / len(decisions),
        "background_intervals": normalized_background,
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


def _validated_alignment_config(
    value: Mapping[str, Any],
) -> dict[str, float | int]:
    if not isinstance(value, Mapping) or set(value) != set(DEFAULT_ALIGNMENT_CONFIG_V2):
        raise S48PresealingGateError("v2 alignment configuration fields mismatch")
    integer_fields = {
        "analysis_block_samples",
        "minimum_correlated_channel_count",
        "maximum_reference_lag_samples",
        "minimum_detection_contiguous_blocks",
        "initial_alignment_search_samples",
        "initial_alignment_probe_samples",
        "maximum_acoustic_start_delay_samples",
        "stop_sentinel_block_samples",
        "tracking_search_radius_samples",
        "maximum_tracking_step_samples",
        "discontinuity_search_radius_samples",
        "minimum_discontinuous_jump_samples",
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
    if (
        float(output["minimum_reference_correlation"]) > 1.0
        or float(output["minimum_pair_coherence"]) > 1.0
        or int(output["maximum_tracking_step_samples"])
        > int(output["tracking_search_radius_samples"])
        or int(output["minimum_discontinuous_jump_samples"])
        > int(output["discontinuity_search_radius_samples"])
    ):
        raise S48PresealingGateError("v2 alignment configuration domain failure")
    return output


def _evaluate_stop_sentinel(
    microphones: np.ndarray,
    reference: np.ndarray,
    *,
    alignment: Mapping[str, Any],
    planned_playback_stop_sample: int,
    config: Mapping[str, float | int],
) -> dict[str, Any]:
    block = int(config["stop_sentinel_block_samples"])
    start = planned_playback_stop_sample - block
    frame = microphones[:, start:planned_playback_stop_sample]
    if frame.shape[1] != block:
        return {
            "present": False,
            "start_sample": start,
            "end_sample": planned_playback_stop_sample,
            "reference_correlation": 0.0,
            "correlated_channel_count": 0,
        }
    acoustic_start = int(alignment["initial_acoustic_start_sample"])
    decisions = alignment["decisions"]
    last_adjustment = (
        int(decisions[-1]["alignment_adjustment_samples"]) if decisions else 0
    )
    elapsed = start - acoustic_start
    predicted_adjustment = round(
        last_adjustment
        + (start - int(decisions[-1]["start_sample"]) if decisions else 0)
        * float(alignment["estimated_drift_ppm"])
        / 1_000_000.0
    )
    adjustment, tracking_correlation = _best_common_phase_adjustment(
        frame,
        reference,
        nominal_phase=elapsed,
        center_adjustment=predicted_adjustment,
        radius=int(config["tracking_search_radius_samples"]),
    )
    reference_frame = _reference_frame(
        reference,
        phase_start=elapsed + adjustment,
        sample_count=block,
    )
    correlations = [
        _best_signed_correlation(
            channel,
            reference_frame,
            int(config["maximum_reference_lag_samples"]),
        )
        for channel in frame
    ]
    correlated_count = sum(
        value >= float(config["minimum_reference_correlation"])
        for value in correlations
    )
    rms_median = float(np.median(np.sqrt(np.mean(frame * frame, axis=1))))
    present = (
        alignment["alignment_status"] == "maintained"
        and tracking_correlation >= float(config["minimum_reference_correlation"])
        and float(median(correlations))
        >= float(config["minimum_reference_correlation"])
        and correlated_count >= int(config["minimum_correlated_channel_count"])
        and rms_median > float(config["basic_rms_floor"])
    )
    return {
        "present": present,
        "start_sample": start,
        "end_sample": planned_playback_stop_sample,
        "reference_correlation": float(median(correlations)),
        "tracking_correlation": tracking_correlation,
        "correlated_channel_count": correlated_count,
        "alignment_adjustment_samples": adjustment,
        "rms_median": rms_median,
    }


def _authenticated_background(
    microphones: np.ndarray,
    *,
    background_intervals: Sequence[tuple[int, int]],
    block_samples: int,
    process_playback_start_sample: int,
    sample_rate_hz: int,
) -> tuple[list[float], list[dict[str, float | int]]]:
    values: list[float] = []
    normalized: list[dict[str, float | int]] = []
    for position, raw_interval in enumerate(background_intervals):
        if (
            not isinstance(raw_interval, Sequence)
            or len(raw_interval) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, int)
                for item in raw_interval
            )
        ):
            raise S48PresealingGateError(f"background_intervals[{position}] is invalid")
        start, stop = raw_interval
        if (
            start < 0
            or stop <= start
            or stop > microphones.shape[1]
            or start < process_playback_start_sample < stop
        ):
            raise S48PresealingGateError(
                f"background_intervals[{position}] is outside authenticated background"
            )
        for offset in range(start, stop - block_samples + 1, block_samples):
            frame = microphones[:, offset : offset + block_samples]
            values.append(float(np.median(np.sqrt(np.mean(frame * frame, axis=1)))))
        normalized.append(
            {
                "start_sample": start,
                "end_sample": stop,
                "start_s": start / sample_rate_hz,
                "end_s": stop / sample_rate_hz,
            }
        )
    if len(values) < 2:
        raise S48PresealingGateError(
            "authenticated background must contain at least two complete blocks"
        )
    return values, normalized


def _estimate_initial_acoustic_start(
    microphones: np.ndarray,
    reference: np.ndarray,
    *,
    process_start: int,
    search_samples: int,
    probe_samples: int,
) -> tuple[int | None, float]:
    probe_count = min(probe_samples, reference.size)
    probe = reference[:probe_count]
    search_stop = min(
        microphones.shape[1],
        process_start + search_samples + probe_count,
    )
    segment = microphones[:, process_start:search_stop]
    if segment.shape[1] < probe_count:
        return None, 0.0
    channel_correlations = [_sliding_correlation(channel, probe) for channel in segment]
    peak_indices = [int(np.argmax(values)) for values in channel_correlations]
    peak_values = [
        float(values[index])
        for values, index in zip(channel_correlations, peak_indices, strict=True)
    ]
    # The earliest channel peak is the acoustic wavefront. Later per-channel
    # propagation delays remain covered by the unchanged v1 per-channel lag.
    return process_start + min(peak_indices), float(median(peak_values))


def _sliding_correlation(samples: np.ndarray, template: np.ndarray) -> np.ndarray:
    centered_template = template - float(np.mean(template))
    template_energy = float(np.dot(centered_template, centered_template))
    if template_energy <= 0.0:
        return np.zeros(samples.size - template.size + 1, dtype=np.float64)
    numerator = np.correlate(samples, centered_template, mode="valid")
    kernel = np.ones(template.size, dtype=np.float64)
    sums = np.convolve(samples, kernel, mode="valid")
    sums_sq = np.convolve(samples * samples, kernel, mode="valid")
    centered_energy = np.maximum(
        sums_sq - (sums * sums) / template.size,
        0.0,
    )
    denominator = np.sqrt(centered_energy * template_energy)
    return np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > 0.0,
    )


def _best_common_phase_adjustment(
    frame: np.ndarray,
    reference: np.ndarray,
    *,
    nominal_phase: int,
    center_adjustment: int,
    radius: int,
) -> tuple[int, float]:
    # Channel-map authentication fixes microphone zero as the phase-tracking
    # channel. Other microphones remain independent correlation/coherence
    # witnesses and are not averaged into a phase-smeared tracking waveform.
    aggregate = frame[0]
    best_adjustment = center_adjustment
    best_correlation = -1.0
    for adjustment in range(center_adjustment - radius, center_adjustment + radius + 1):
        candidate = _reference_frame(
            reference,
            phase_start=nominal_phase + adjustment,
            sample_count=frame.shape[1],
        )
        correlation = _signed_correlation(aggregate, candidate)
        if correlation > best_correlation:
            best_adjustment = adjustment
            best_correlation = correlation
    return best_adjustment, best_correlation


def _reference_frame(
    reference: np.ndarray,
    *,
    phase_start: int,
    sample_count: int,
) -> np.ndarray:
    indices = (np.arange(sample_count) + phase_start) % reference.size
    return reference[indices]


def _signed_correlation(left: np.ndarray, right: np.ndarray) -> float:
    x = left - float(np.mean(left))
    y = right - float(np.mean(right))
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    return float(np.dot(x, y) / denominator) if denominator > 0.0 else 0.0


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
        value = _signed_correlation(x, y)
        if abs(value) > abs(best):
            best = value
    return best


def _estimate_drift_ppm(
    sample_offsets: Sequence[float],
    phase_adjustments: Sequence[float],
) -> float:
    if len(sample_offsets) < 2:
        return 0.0
    slope = float(np.polyfit(sample_offsets, phase_adjustments, 1)[0])
    return slope * 1_000_000.0


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
