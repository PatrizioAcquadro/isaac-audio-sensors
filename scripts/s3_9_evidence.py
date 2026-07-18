#!/usr/bin/env python3
"""Build the S3.9 fidelity-envelope claim/evidence map and gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/isaac_audio_sensors/S3/S3.9"
ENVELOPE = ROOT / "docs/development/specs/s3_fidelity_envelope.md"
ENTRY_REVISION = "a54b7f6f0d8f5833612224d5db4cdb6cc5fddc23"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    subphase: str
    gate_name: str
    gate_row: str
    artifact_name: str


@dataclass(frozen=True, slots=True)
class ClaimSpec:
    claim_id: str
    claim: str
    validating_test_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    off_state_test_ids: tuple[str, ...]
    off_state_evidence: tuple[EvidenceRef, ...]


def _ref(subphase: str, gate: str, row: str, artifact: str) -> EvidenceRef:
    return EvidenceRef(subphase, gate, row, artifact)


CLAIMS = (
    ClaimSpec(
        "S3C-01",
        "Timestamped live poses derive bounded world-frame linear velocity under "
        "the frozen policy.",
        (
            "tests/test_pose_history.py::test_raw_constant_velocity_recovery_frozen_fixture",
            "tests/test_pose_history.py::test_smoothed_constant_velocity_settles_after_exactly_40_updates",
            "tests/test_motion_stage_snapshot.py::test_authored_precedence_preserves_bits_while_history_stays_current",
            "tests/test_motion_doppler_integration.py::test_tdoa_teleport_frame_has_exact_unity_central_and_per_mic_factors",
        ),
        (
            _ref(
                "S3.1",
                "pose_velocity_gate.json",
                "raw_constant_velocity",
                "constant_velocity_results.json",
            ),
            _ref(
                "S3.1",
                "pose_velocity_gate.json",
                "smoothing_settling",
                "smoothing_settling_results.json",
            ),
            _ref(
                "S3.1",
                "pose_velocity_gate.json",
                "authored_precedence_bits",
                "authored_precedence_bits.json",
            ),
            _ref(
                "S3.1",
                "pose_velocity_gate.json",
                "tdoa_teleport_no_spike",
                "tdoa_teleport_no_spike.json",
            ),
        ),
        (
            "tests/test_motion_stage_snapshot.py::test_disabled_motion_enrichment_is_literal_identity_and_no_history_update",
            "tests/test_motion_doppler_integration.py::test_tdoa_motion_off_state_is_byte_identical_and_omits_doppler",
        ),
        (
            _ref(
                "S3.1",
                "pose_velocity_gate.json",
                "motion_off_state",
                "motion_off_state_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-02",
        "The opt-in recorder preserves eligible gaps with bounded streaming and "
        "sample-for-sample carry advancement.",
        (
            "tests/test_dataset_time_gaps.py::test_pause_inserts_exact_16800_samples_and_validator_reconciles",
            "tests/test_dataset_time_gaps.py::test_carry_advances_through_gap_then_remainder_is_exact_zero",
            "tests/test_dataset_time_gaps.py::test_long_gap_allocations_obey_sample_and_one_mib_caps",
        ),
        (
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "pause_throttle_accounting",
                "pause_sample_accounting.json",
            ),
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "carry_bounded_streaming",
                "gap_carry_results.json",
            ),
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "carry_bounded_streaming",
                "gap_memory_telemetry.json",
            ),
        ),
        (
            "tests/test_dataset_time_gaps.py::test_absent_and_explicit_false_use_identical_public_append_bytes",
        ),
        (
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "off_state_segments_one",
                "time_gap_off_state_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-03",
        "The validated L2 fixture uses eight bounded midpoint segments, "
        "phase-continuous Doppler assembly, and cross-segment RIR tails.",
        (
            "tests/test_intra_window_motion.py::test_linear_interpolation_and_midpoint_hold_obey_frozen_bound",
            "tests/test_intra_window_motion.py::test_phase_cursor_continuity_residual_is_below_two_e_minus_six",
            "tests/test_intra_window_motion.py::test_piecewise_room_assembles_exact_window_and_segment_diagnostics",
        ),
        (
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "analytical_motion_bounds",
                "interpolation_error_results.json",
            ),
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "boundary_continuity",
                "segment_continuity_results.json",
            ),
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "doppler_rir_assembly",
                "piecewise_room_results.json",
            ),
        ),
        (
            "tests/test_intra_window_motion.py::test_segments_one_selects_literal_room_branch_and_is_byte_identical",
        ),
        (
            _ref(
                "S3.2",
                "time_motion_gate.json",
                "off_state_segments_one",
                "segments_one_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-04",
        "Configured L2 channel magnitude response, gain, fractional delay, and "
        "polarity meet the frozen recovery tolerances.",
        (
            "tests/test_channel_response.py::test_tone_gain_recovery_meets_frozen_maximum_error",
            "tests/test_channel_response.py::test_fractional_delay_recovery_meets_frozen_maximum_error",
            "tests/test_channel_response.py::test_polarity_is_exact_for_asymmetric_values_and_signed_zero",
            "tests/test_channel_response.py::test_frequency_response_welch_h1_meets_frozen_passband_error",
            "tests/test_effects_backend_integration.py::test_l1_gain_and_delay_adapter_is_difference_of_matching_baselines",
            "tests/test_effects_backend_integration.py::test_l1_polarity_is_honest_metadata_only_and_leaves_observables_exact",
        ),
        (
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "gain_recovery",
                "gain_tone_results.json",
            ),
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "fractional_delay",
                "delay_recovery_results.json",
            ),
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "polarity",
                "polarity_exact_result.json",
            ),
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "frequency_response",
                "frequency_response_welch.json",
            ),
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "l1_adapter_equivalence",
                "l1_metadata_adapter.json",
            ),
        ),
        (
            "tests/test_channel_effects_chain.py::test_chain_all_disabled_returns_exact_input_identity_and_empty_diagnostics",
            "tests/test_effects_backend_integration.py::test_room_backend_off_state_matches_pristine_self_reference_and_head_hashes",
        ),
        (
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "pure_off_state",
                "off_state_chain_identity.json",
            ),
            _ref(
                "S3.3",
                "channel_response_gate.json",
                "backend_off_state",
                "off_state_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-05",
        "Seeded L2 self-noise, ambient mixture, jitter, and deterministic drift "
        "meet the frozen statistical and replay bounds.",
        (
            "tests/test_effects_noise.py::test_self_noise_psd_meets_exact_frozen_welch_protocol",
            "tests/test_effects_noise.py::test_full_band_rms_levels_meet_frozen_bound",
            "tests/test_effects_noise.py::test_ambient_coherent_power_fraction_matches_pairwise_correlation",
            "tests/test_effects_noise.py::test_jitter_named_draw_mean_and_std_over_exactly_100000_frames",
            "tests/test_effects_noise.py::test_drift_slope_and_long_session_phase_arithmetic_meet_frozen_bounds",
            "tests/test_effects_noise.py::test_seed_replay_separation_diagnostics_and_configuration_isolation",
        ),
        (
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "self_noise_psd",
                "self_noise_welch.json",
            ),
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "rms_and_exact_zero",
                "noise_rms_results.json",
            ),
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "ambient_coherence",
                "ambient_coherence.json",
            ),
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "jitter_statistics",
                "jitter_statistics.json",
            ),
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "drift_slope_long_session",
                "drift_slope_results.json",
            ),
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "seed_replay_separation",
                "seed_replay_sha256.json",
            ),
        ),
        (
            "tests/test_effects_noise.py::test_backend_off_state_golden_and_enabled_registry_style_determinism",
        ),
        (
            _ref(
                "S3.4",
                "seeded_noise_gate.json",
                "pure_backend_off_state",
                "off_state_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-06",
        "L2 electronics applies stateless AGC, hard clipping, float-domain "
        "quantization, and optional deterministic TPDF dither once per mixture.",
        (
            "tests/test_effects_electronics.py::test_boundary_clipping_counts_ratio_and_diagnostics_contract_are_exact",
            "tests/test_effects_electronics.py::test_quantization_noise_power_frozen_ramp",
            "tests/test_effects_electronics.py::test_tpdf_dither_named_stream_peak_to_peak_and_decorrelation",
            "tests/test_effects_electronics.py::test_agc_analytical_trace_settling_direction_silence_and_bounds",
            "tests/test_effects_electronics.py::test_room_electronics_once_on_mixture_rms_export_and_seed_replay",
        ),
        (
            _ref(
                "S3.5",
                "electronics_gate.json",
                "boundary_clipping_and_ratio",
                "clipping_boundary_results.json",
            ),
            _ref(
                "S3.5",
                "electronics_gate.json",
                "quantization_noise_power",
                "quantization_noise_power.json",
            ),
            _ref(
                "S3.5",
                "electronics_gate.json",
                "tpdf_dither_decorrelation",
                "tpdf_dither_correlation.json",
            ),
            _ref(
                "S3.5",
                "electronics_gate.json",
                "agc_analytical_response_settling",
                "agc_step_response.json",
            ),
            _ref(
                "S3.5",
                "electronics_gate.json",
                "electronics_once_on_mixture",
                "mixture_once_trace.json",
            ),
        ),
        (
            "tests/test_effects_electronics.py::test_off_state_identity_backend_golden_and_no_effects_key",
        ),
        (
            _ref(
                "S3.5",
                "electronics_gate.json",
                "pure_backend_off_state",
                "off_state_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-07",
        "L2 per_pair_direct_path directivity applies signed polar and magnitude "
        "response to each full convolved pair stem before summation.",
        (
            "tests/test_effects_directivity.py::test_cardinal_waveform_gain_sign_and_null_leakage",
            "tests/test_effects_directivity.py::test_frequency_response_single_and_cascaded_recovery",
            "tests/test_effects_directivity.py::test_full_pair_stem_weighted_once_before_sum_and_tail_changes",
            "tests/test_effects_directivity.py::test_real_room_cardinal_gain_and_small_estimator_ladder_direction",
        ),
        (
            _ref(
                "S3.6",
                "waveform_directivity_gate.json",
                "cardinal_waveform_gain",
                "cardinal_waveform_gain.json",
            ),
            _ref(
                "S3.6",
                "waveform_directivity_gate.json",
                "frequency_response",
                "frequency_sweep_welch.json",
            ),
            _ref(
                "S3.6",
                "waveform_directivity_gate.json",
                "full_convolved_stem_insertion",
                "per_pair_insertion_trace.json",
            ),
            _ref(
                "S3.6",
                "waveform_directivity_gate.json",
                "estimator_degradation",
                "estimator_confidence_ladder.json",
            ),
        ),
        (
            "tests/test_effects_directivity.py::test_diagnostics_exact_schema_order_and_explicit_omni_off_state",
        ),
        (
            _ref(
                "S3.6",
                "waveform_directivity_gate.json",
                "disabled_omni_off_state",
                "off_state_golden_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-08",
        "L2 shoebox rooms resolve frozen measured absorption and recompute current "
        "room/RIR output after acoustic-state changes.",
        (
            "tests/test_acoustic_materials.py::test_frozen_material_table_rows_and_source_provenance_are_exact",
            "tests/test_dynamic_rooms_invalidation.py::test_room_hash_and_output_diverge_for_geometry_and_material_mutations",
            "tests/test_dynamic_rooms_invalidation.py::test_source_and_array_motion_use_current_endpoints_without_stale_output",
        ),
        (
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "material_source_provenance",
                "material_table_provenance.json",
            ),
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "dynamic_room_material",
                "dynamic_room_results.json",
            ),
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "moving_source_array",
                "moving_endpoint_results.json",
            ),
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "recompute_always",
                "recompute_baseline_results.json",
            ),
        ),
        (
            "tests/test_dynamic_rooms_invalidation.py::test_off_state_frame_has_no_acoustics_namespace_and_is_byte_deterministic",
        ),
        (
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "off_state_predecessors",
                "acoustics_off_state_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-09",
        "The live Isaac adapter resolves current direct rays and applies ordered "
        "per-surface transmission consistently across observables.",
        (
            "tests/test_isaac_occlusion.py::test_live_sensor_occlusion_attenuates_flags_and_reports_diagnostics",
            "tests/test_isaac_occlusion.py::test_room_backend_band_attenuation_shows_in_exported_wav",
            "tests/test_dynamic_rooms_invalidation.py::test_live_extension_tracks_occluder_move_and_anchor_refresh_without_stale_state",
            "make live-isaac-occlusion",
        ),
        (
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "clear_blocked_partial_material",
                "occlusion_consistency_results.json",
            ),
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "live_moving_occluder",
                "live_moving_occluder_summary.json",
            ),
        ),
        (
            "tests/test_isaac_occlusion.py::test_live_sensor_occlusion_disabled_by_default",
            "tests/test_dynamic_rooms_invalidation.py::test_off_state_frame_has_no_acoustics_namespace_and_is_byte_deterministic",
        ),
        (
            _ref(
                "S3.7",
                "dynamic_rooms_gate.json",
                "off_state_predecessors",
                "acoustics_off_state_sha256.json",
            ),
        ),
    ),
    ClaimSpec(
        "S3C-10",
        "The supported combined matrix retains finite values, current state, "
        "determinism, explicit ambiguity, and identity under motion and 2/4/8 "
        "source stress.",
        (
            "tests/test_s3_stress_matrix.py::test_p03_overlap_ladder_keeps_every_source",
            "tests/test_s3_stress_matrix.py::test_p07_p08_current_occlusion_and_moving_mount_state",
            "tests/test_s3_stress_matrix.py::test_p09_identity_persistence_under_256_frame_churn",
            "tests/test_s3_stress_matrix.py::test_p10_all_effects_l2_and_complete_live_forwarding",
            "tests/test_s3_stress_matrix.py::test_p12_gap_preservation_and_p13_determinism_replay",
        ),
        (
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "multi_source_overlap",
                "multi_source_stress.json",
            ),
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "occluder_mount_current_state",
                "dynamic_state_stress.json",
            ),
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "identity_churn_ambiguity",
                "identity_ambiguity_stress.json",
            ),
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "reverb_and_all_effects",
                "l2_effects_stress.json",
            ),
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "determinism",
                "determinism_replay.json",
            ),
        ),
        (
            "tests/test_s3_stress_matrix.py::test_matrix_profiles_and_explicit_unsupported_cells",
            "S3.8/live_s3_stress:effects_off",
        ),
        (
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "matrix_capability_audit",
                "matrix_capabilities.json",
            ),
            _ref(
                "S3.8",
                "stress_matrix_gate.json",
                "live_s3_stress",
                "live_stress_summary.json",
            ),
        ),
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _passed(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        value = value.get("status")
    return str(value).strip().lower() == "passed"


def _gate_row(gate: dict[str, object], row_id: str) -> object:
    rows = gate.get("rows")
    if isinstance(rows, dict) and row_id in rows:
        return rows[row_id]
    scenarios = gate.get("scenarios")
    if isinstance(scenarios, dict) and row_id in scenarios:
        return scenarios[row_id]
    raise KeyError(f"gate row {row_id!r} is absent")


def _test_id_failure(test_id: str) -> str | None:
    if "::" not in test_id or not test_id.startswith("tests/"):
        return None
    path_text, function_name = test_id.split("::", 1)
    path = ROOT / path_text
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"test file unavailable for {test_id}: {exc}"
    pattern = rf"^def {re.escape(function_name)}(?:\[|\()"
    if re.search(pattern, content, flags=re.MULTILINE) is None:
        return f"test function unavailable for {test_id}"
    return None


def _resolve_evidence(
    reference: EvidenceRef,
    gate_cache: dict[Path, dict[str, object]],
) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    base = ROOT / "outputs/isaac_audio_sensors/S3" / reference.subphase
    gate_path = base / reference.gate_name
    artifact_path = base / reference.artifact_name
    relative_gate = gate_path.relative_to(ROOT).as_posix()
    relative_artifact = artifact_path.relative_to(ROOT).as_posix()

    try:
        gate = gate_cache.setdefault(
            gate_path, json.loads(gate_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"unreadable gate {relative_gate}: {exc}")
        gate = {}

    if gate and not _passed(gate.get("status", gate.get("all_rows_passed"))):
        failures.append(f"owning gate is not passed: {relative_gate}")
    try:
        row = _gate_row(gate, reference.gate_row)
    except KeyError as exc:
        failures.append(f"{relative_gate}: {exc}")
    else:
        if not _passed(row):
            failures.append(
                f"owning gate row is not passed: {relative_gate}#{reference.gate_row}"
            )

    expected_hash: object = None
    artifact_hashes = gate.get("artifact_sha256")
    if isinstance(artifact_hashes, dict):
        expected_hash = artifact_hashes.get(reference.artifact_name)
    if not isinstance(expected_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        failures.append(f"missing valid owning-gate SHA-256 for {relative_artifact}")

    actual_hash: str | None = None
    try:
        actual_hash = _sha256(artifact_path)
    except OSError as exc:
        failures.append(f"unhashable evidence {relative_artifact}: {exc}")
    if actual_hash is not None and actual_hash != expected_hash:
        failures.append(
            f"SHA-256 mismatch for {relative_artifact}: expected "
            f"{expected_hash}, observed {actual_hash}"
        )

    record = {
        "artifact_path": relative_artifact,
        "gate_path": relative_gate,
        "gate_row": reference.gate_row,
        "sha256": actual_hash,
        "expected_sha256": expected_hash,
        "hash_matches": actual_hash is not None and actual_hash == expected_hash,
        "status": "passed" if not failures else "failed",
    }
    return record, failures


def main() -> int:
    gate_cache: dict[Path, dict[str, object]] = {}
    global_failures: list[str] = []
    try:
        envelope_text = ENVELOPE.read_text(encoding="utf-8")
        envelope_hash = _sha256(ENVELOPE)
    except OSError as exc:
        envelope_text = ""
        envelope_hash = None
        global_failures.append(f"unreadable fidelity envelope: {exc}")

    mandatory_strings = (
        "Ray/transmission occlusion is NOT diffraction",
        "is NOT a complete wave solver",
        "does not expand `docs/v1_scope.md`",
        "P1 owns the scaled effects-on 20 ms gate",
    )
    for required in mandatory_strings:
        if required not in envelope_text:
            global_failures.append(f"envelope is missing mandatory text: {required}")

    rows: list[dict[str, object]] = []
    for claim in CLAIMS:
        failures: list[str] = []
        if envelope_text.count(f"`{claim.claim_id}`") != 1:
            failures.append(
                f"envelope must contain claim id {claim.claim_id} exactly once"
            )
        for test_id in (*claim.validating_test_ids, *claim.off_state_test_ids):
            failure = _test_id_failure(test_id)
            if failure is not None:
                failures.append(failure)

        evidence_records = []
        for reference in claim.evidence:
            record, evidence_failures = _resolve_evidence(reference, gate_cache)
            evidence_records.append(record)
            failures.extend(evidence_failures)

        off_state_records = []
        for reference in claim.off_state_evidence:
            record, evidence_failures = _resolve_evidence(reference, gate_cache)
            off_state_records.append(record)
            failures.extend(evidence_failures)

        rows.append(
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "validating_test_ids": list(claim.validating_test_ids),
                "evidence": evidence_records,
                "off_state_test_ids": list(claim.off_state_test_ids),
                "off_state_evidence": off_state_records,
                "failures": failures,
                "status": "passed" if not failures else "failed",
            }
        )

    claim_map = {
        "schema": "ias.s3_claim_evidence_map.v1",
        "subphase": "S3.9",
        "entry_revision": ENTRY_REVISION,
        "envelope_path": ENVELOPE.relative_to(ROOT).as_posix(),
        "envelope_sha256": envelope_hash,
        "row_count": len(rows),
        "rows": rows,
        "failed_rows": [row["claim_id"] for row in rows if row["status"] != "passed"],
        "global_failures": global_failures,
        "status": (
            "passed"
            if not global_failures and all(row["status"] == "passed" for row in rows)
            else "failed"
        ),
    }
    claim_map_path = OUTPUT / "claim_evidence_map.json"
    _write_json(claim_map_path, claim_map)

    gate = {
        "schema": "ias.s3_fidelity_envelope_gate.v1",
        "subphase": "S3.9",
        "entry_revision": ENTRY_REVISION,
        "envelope_path": ENVELOPE.relative_to(ROOT).as_posix(),
        "envelope_sha256": envelope_hash,
        "claim_map_path": claim_map_path.relative_to(ROOT).as_posix(),
        "claim_map_sha256": _sha256(claim_map_path),
        "claim_row_count": len(rows),
        "rows": {row["claim_id"]: row["status"] for row in rows},
        "checks": {
            "all_claim_ids_published_once": all(
                envelope_text.count(f"`{claim.claim_id}`") == 1 for claim in CLAIMS
            ),
            "all_referenced_tests_exist": not any(
                "test file unavailable" in failure
                or "test function unavailable" in failure
                for row in rows
                for failure in row["failures"]
            ),
            "all_evidence_exists_and_hashes_match": all(
                item["hash_matches"]
                for row in rows
                for item in (*row["evidence"], *row["off_state_evidence"])
            ),
            "all_owning_gate_rows_passed": not any(
                "gate row" in failure or "owning gate" in failure
                for row in rows
                for failure in row["failures"]
            ),
            "mandatory_boundary_text_present": not global_failures,
        },
        "failed_rows": claim_map["failed_rows"],
        "failures": global_failures,
        "status": claim_map["status"],
    }
    _write_json(OUTPUT / "fidelity_envelope_gate.json", gate)
    print(f"S3.9 fidelity envelope: {gate['status']} ({len(rows)} claim-map rows)")
    return 0 if gate["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
