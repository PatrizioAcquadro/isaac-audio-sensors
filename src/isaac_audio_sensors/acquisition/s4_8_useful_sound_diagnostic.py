"""Isolated reused-holdout useful-directional-sound diagnostics for S4.8.

This module is not an official S4.8 state-machine surface.  It does not create
or consume grants, publish evidence, or change the historical full-capture
producer.  The pure detector below separates acoustic applicability from final
bearing confidence and correctness.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

import jsonschema
import numpy as np

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.core import acceptance_criteria_corrective_02 as corrective_02
from isaac_audio_sensors.core import acceptance_criteria_corrective_03 as corrective_03
from isaac_audio_sensors.core.doa.sector_mapping import (
    bearing_deg_to_sector_name,
)
from isaac_audio_sensors.core.doa.srp_phat import srp_phat_direction

DEFAULT_DETECTOR_CONFIG: dict[str, float | int] = {
    "sample_rate_hz": 16000,
    "window_samples": 4000,
    "hop_samples": 2000,
    "basic_rms_floor": 0.002,
    "background_lower_fraction": 0.5,
    "normalized_mad_scale": 1.4826,
    "coherence_mad_multiplier": 5.0,
    "minimum_contiguous_windows": 8,
}

CONFIG_PATH = Path("configs/s4_8_useful_sound_diagnostic.v1.json")
SCHEMA_PATH = Path(
    "docs/schemas/s4_8_useful_sound_diagnostic_config.v1.schema.json"
)
PAYLOAD_SCHEMA_PATH = Path(
    "docs/schemas/s4_8_useful_sound_diagnostic.v1.schema.json"
)
IMPLEMENTATION_PATH = Path(
    "src/isaac_audio_sensors/acquisition/s4_8_useful_sound_diagnostic.py"
)
DIAGNOSTIC_PAYLOAD_SCHEMA = "ias.s4_8.useful_sound_diagnostic_payload.v1"
DETECTOR_METHOD = (
    "capture_robust_lower_half_srp_absolute_coherence_with_energy_floor_"
    "and_minimum_continuity"
)
DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA = (
    "ias.s4_8.useful_sound_scientific_payload.v1"
)
DIAGNOSTIC_RESULT_SCHEMA = "ias.s4_8.useful_sound_diagnostic_result.v1"


class UsefulSoundDiagnosticError(RuntimeError):
    """A malformed or scientifically inapplicable diagnostic input."""


def load_diagnostic_config(repo_root: Path) -> dict[str, Any]:
    """Load the general detector contract and validate its non-authority."""

    root = repo_root.resolve()
    try:
        config = json.loads((root / CONFIG_PATH).read_text(encoding="utf-8"))
        schema = json.loads((root / SCHEMA_PATH).read_text(encoding="utf-8"))
        jsonschema.validate(config, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise UsefulSoundDiagnosticError(
            f"useful-sound diagnostic configuration failure: {exc}"
        ) from exc
    if config["detector"] != DEFAULT_DETECTOR_CONFIG:
        raise UsefulSoundDiagnosticError("detector configuration identity mismatch")
    return config


def validate_diagnostic_payload(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> None:
    """Validate truthful lane metadata and count reconciliation."""

    root = repo_root.resolve()
    try:
        schema = json.loads(
            (root / PAYLOAD_SCHEMA_PATH).read_text(encoding="utf-8")
        )
        jsonschema.validate(payload, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise UsefulSoundDiagnosticError(
            f"useful-sound diagnostic payload schema failure: {exc}"
        ) from exc
    if payload.get("reused_holdout") is not True:
        raise UsefulSoundDiagnosticError("reused_holdout must remain true")
    if payload.get("diagnostic_only") is not True:
        raise UsefulSoundDiagnosticError("diagnostic_only must remain true")
    source = int(payload["source_window_count"])
    useful = int(payload["applicable_useful_window_count"])
    non_applicable = int(payload["non_applicable_window_count"])
    if source != useful + non_applicable:
        raise UsefulSoundDiagnosticError("diagnostic window counts do not reconcile")
    rows = payload["per_take_applicability"]
    if (
        sum(int(row["source_window_count"]) for row in rows) != source
        or sum(int(row["useful_sound_window_count"]) for row in rows) != useful
        or sum(int(row["non_applicable_window_count"]) for row in rows)
        != non_applicable
    ):
        raise UsefulSoundDiagnosticError(
            "per-take applicability counts do not reconcile"
        )
    for row in rows:
        if (
            row["source_window_count"]
            != row["useful_sound_window_count"]
            + row["non_applicable_window_count"]
            or len(row["windows"]) not in {0, row["source_window_count"]}
        ):
            raise UsefulSoundDiagnosticError(
                f"{row['take_id']}: applicability counts do not reconcile"
            )


def run_reused_holdout_diagnostic(
    repo_root: Path,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run unchanged full-capture and isolated useful-sound evaluations."""

    root = repo_root.resolve()
    diagnostic_config = load_diagnostic_config(root)
    official_config = s4_8.load_contract(root)
    seal_path = root / official_config["holdout"]["seal_path"]
    seal = s4_8.load_json(seal_path)
    registry = s4_8.build_identity_registry(root)
    attempt_roots = s4_8._sealed_attempt_roots(root, seal, set(registry))
    profile = s4_8._profile_runtime(root)
    simulation = s4_8.build_simulation_comparisons(root)

    full_takes: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for position, take_id in enumerate(sorted(registry), start=1):
        take, record = s4_8._analyze_real_take(
            root,
            attempt_roots[take_id],
            registry[take_id],
            profile=profile,
            seal=seal,
        )
        full_takes.append(take)
        inventory.append(record)
        if progress_callback is not None:
            progress_callback(f"full_capture {position}/47 {take_id}")
    full_payload = s4_8._partial_payload(
        official_config,
        takes=full_takes,
        simulation=simulation,
    )
    full_evaluation = s4_8.evaluate_payload(full_payload, repo_root=root)
    if (
        full_evaluation.get("evaluation_error") is not None
        or len(full_evaluation.get("criteria", [])) != 29
    ):
        raise UsefulSoundDiagnosticError(
            "unchanged full-capture diagnostic did not evaluate all 29 criteria"
        )

    diagnostic_by_take = {
        take["identity"]["planned_take_id"]: deepcopy(take)
        for take in full_takes
    }
    applicability_rows: list[dict[str, Any]] = []
    applicable_strata = set(diagnostic_config["applicable_strata"])
    active_ids = [
        take_id
        for take_id in sorted(registry)
        if registry[take_id].stratum_id in applicable_strata
    ]
    for position, take_id in enumerate(active_ids, start=1):
        take, row = _diagnose_active_take(
            root,
            attempt_root=attempt_roots[take_id],
            identity=registry[take_id],
            base_take=diagnostic_by_take[take_id],
            profile=profile,
            seal=seal,
            detector_config=diagnostic_config["detector"],
        )
        diagnostic_by_take[take_id] = take
        applicability_rows.append(row)
        if progress_callback is not None:
            progress_callback(
                f"useful_sound {position}/{len(active_ids)} {take_id}"
            )

    scientific_payload = {
        **deepcopy(full_payload),
        "schema": DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA,
        "takes": [
            diagnostic_by_take[take_id]
            for take_id in sorted(diagnostic_by_take)
        ],
    }
    source_count = sum(
        int(row["source_window_count"]) for row in applicability_rows
    )
    useful_count = sum(
        int(row["useful_sound_window_count"]) for row in applicability_rows
    )
    payload = {
        "schema": DIAGNOSTIC_PAYLOAD_SCHEMA,
        "reused_holdout": True,
        "diagnostic_only": True,
        "useful_sound_applicability_method": DETECTOR_METHOD,
        "complete_capture_window_count": sum(
            int(take["window_summary"]["source_window_count"])
            for take in full_takes
        ),
        "source_window_count": source_count,
        "applicable_useful_window_count": useful_count,
        "non_applicable_window_count": source_count - useful_count,
        "detector_configuration": deepcopy(diagnostic_config["detector"]),
        "detector_provenance": {
            "config_path": CONFIG_PATH.as_posix(),
            "config_sha256": _sha256_file(root / CONFIG_PATH),
            "implementation_path": IMPLEMENTATION_PATH.as_posix(),
            "implementation_sha256": _sha256_file(root / IMPLEMENTATION_PATH),
            "holdout_seal_path": official_config["holdout"]["seal_path"],
            "holdout_seal_sha256": _sha256_file(seal_path),
            "source_full_capture_payload_sha256": s4_8.canonical_sha256(
                full_payload
            ),
            "authenticated_waveform_and_producer_status": True,
            "unsealed_playback_timing_used": False,
            "reference_audio_used": False,
            "outcome_fields_used_for_applicability": [],
        },
        "per_take_applicability": applicability_rows,
        "scientific_payload": scientific_payload,
    }
    validate_diagnostic_payload(payload, repo_root=root)
    useful_evaluation = evaluate_useful_sound_scientific_payload(
        scientific_payload,
        repo_root=root,
    )
    return {
        "schema": "ias.s4_8.reused_holdout_diagnostic_run.v1",
        "reused_holdout": True,
        "diagnostic_only": True,
        "official_state_machine_run": False,
        "full_capture_diagnostic": {
            "payload": full_payload,
            "evaluation": full_evaluation,
            "inventory": inventory,
        },
        "useful_sound_diagnostic": {
            "payload": payload,
            "evaluation": useful_evaluation,
        },
    }


def _diagnose_active_take(
    repo_root: Path,
    *,
    attempt_root: Path,
    identity: Any,
    base_take: Mapping[str, Any],
    profile: Mapping[str, Any],
    seal: Mapping[str, Any],
    detector_config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    wav_path = attempt_root / "raw/respeaker_audio.wav"
    producer_path = attempt_root / "raw/pi_producer_status.json"
    s4_8._verify_sealed_file(repo_root, wav_path, seal)
    s4_8._verify_sealed_file(repo_root, producer_path, seal)
    samples, rate = s4_8._read_pcm16(wav_path)
    raw = samples[:, 2:6].T
    adjusted = raw * np.asarray(profile["gain_multipliers"], dtype=float)[:, None]
    positions = np.asarray(profile["positions"], dtype=float)
    ids = tuple(f"raw_microphone_{index}" for index in range(4))
    position_map = dict(zip(ids, map(tuple, positions), strict=True))
    aperture = max(
        float(np.linalg.norm(positions[left] - positions[right]))
        for left in range(4)
        for right in range(left + 1, 4)
    )
    max_delay = aperture / 343.0 + 1.0 / rate
    window_count = 1 + (
        adjusted.shape[1] - int(detector_config["window_samples"])
    ) // int(detector_config["hop_samples"])
    analyzed: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for index in range(window_count):
        start = index * int(detector_config["hop_samples"])
        frame = adjusted[:, start : start + int(detector_config["window_samples"])]
        record, confidence, tdoa, _correlations, _elapsed, _adapter = (
            s4_8._analyze_window(
                frame,
                ids=ids,
                position_map=position_map,
                sample_rate_hz=rate,
                max_delay_s=max_delay,
                index=index,
                start=start,
                take_id=identity.planned_take_id,
            )
        )
        srp = srp_phat_direction(
            {
                mic_id: frame[channel]
                for channel, mic_id in enumerate(ids)
            },
            mic_positions_m=position_map,
            sample_rate_hz=rate,
            speed_of_sound_mps=343.0,
            azimuth_step_deg=2.0,
            max_delay_s=max_delay,
            interp=8,
        )
        rms = np.sqrt(np.mean(frame * frame, axis=1))
        coherence = max(0.0, min(1.0, srp.peak_power / srp.pair_count))
        analyzed.append(
            {
                "record": record,
                "confidence": confidence,
                "tdoa_s": tdoa,
            }
        )
        features.append(
            {
                "window_index": index,
                "start_sample": start,
                "rms_median": float(np.median(rms)),
                "srp_coherence": coherence,
                # Detector ignores the following performance outputs.
                "confidence": confidence,
                "srp_bearing_deg_f_project": record[
                    "srp_bearing_deg_f_project"
                ],
            }
        )
    detection = detect_useful_sound_windows(features, config=detector_config)
    selected_indices = detection["applicable_window_indices"]
    aggregated = aggregate_useful_sound_take(
        base_take,
        identity=identity,
        analyzed_windows=analyzed,
        applicable_window_indices=selected_indices,
    )
    selected = [analyzed[index] for index in selected_indices]
    confidences = np.asarray(
        [float(item["confidence"]) for item in selected],
        dtype=float,
    )
    abstained = sum(bool(item["record"]["abstained"]) for item in selected)
    decisions = []
    for decision, analysis in zip(
        detection["decisions"],
        analyzed,
        strict=True,
    ):
        decisions.append(
            {
                **decision,
                "confidence": float(analysis["confidence"]),
                "abstained": bool(analysis["record"]["abstained"]),
            }
        )
    source_count = int(detection["source_window_count"])
    useful_count = int(detection["applicable_window_count"])
    return aggregated, {
        "take_id": identity.planned_take_id,
        "stratum": identity.stratum_id,
        "source_window_count": source_count,
        "useful_sound_window_count": useful_count,
        "non_applicable_window_count": int(
            detection["non_applicable_window_count"]
        ),
        "useful_window_coverage": useful_count / source_count,
        "abstained_useful_window_count": abstained,
        "useful_window_abstention_rate": abstained / useful_count,
        "confidence_quantiles": {
            "p25": float(np.quantile(confidences, 0.25)),
            "median": float(np.quantile(confidences, 0.5)),
            "p75": float(np.quantile(confidences, 0.75)),
            "p90": float(np.quantile(confidences, 0.9)),
            "maximum": float(np.max(confidences)),
        },
        "longest_continuous_useful_sound_interval": detection[
            "longest_continuous_interval"
        ],
        "coherence_background_lower_window_count": detection[
            "coherence_background_lower_window_count"
        ],
        "coherence_background_median": detection[
            "coherence_background_median"
        ],
        "coherence_background_mad": detection["coherence_background_mad"],
        "coherence_background_normalized_mad": detection[
            "coherence_background_normalized_mad"
        ],
        "coherence_threshold": detection["coherence_threshold"],
        "exclusion_reason_counts": detection["exclusion_reason_counts"],
        "windows": decisions,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def detect_useful_sound_windows(
    windows: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Select sustained directional acoustic activity without outcome inputs.

    The baseline is estimated from the lower half of capture-wide absolute SRP
    coherence.  A raw candidate must exceed a robust upper threshold and the
    pre-existing calibrated RMS floor.  Only sustained candidate runs are
    applicable.  Confidence, emitted bearing, target bearing, correctness,
    take identity, and acceptance results are deliberately not read.
    """

    detector = _validated_detector_config(config)
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes)):
        raise UsefulSoundDiagnosticError("windows must be a sequence")
    if not windows:
        raise UsefulSoundDiagnosticError("windows must not be empty")

    normalized: list[dict[str, float | int]] = []
    for position, window in enumerate(windows):
        if not isinstance(window, Mapping):
            raise UsefulSoundDiagnosticError(f"windows[{position}] must be an object")
        index = _integer(
            window.get("window_index"),
            f"windows[{position}].window_index",
        )
        start = _integer(
            window.get("start_sample"),
            f"windows[{position}].start_sample",
        )
        expected_start = index * detector["hop_samples"]
        if index != position or start != expected_start:
            raise UsefulSoundDiagnosticError(
                "windows must have consecutive identities and exact hop starts"
            )
        normalized.append(
            {
                "window_index": index,
                "start_sample": start,
                "rms_median": _finite(
                    window.get("rms_median"),
                    f"windows[{position}].rms_median",
                    minimum=0.0,
                ),
                "srp_coherence": _finite(
                    window.get("srp_coherence"),
                    f"windows[{position}].srp_coherence",
                    minimum=0.0,
                    maximum=1.0,
                ),
            }
        )

    coherences = sorted(float(item["srp_coherence"]) for item in normalized)
    lower_count = max(
        1,
        int(math.ceil(len(coherences) * detector["background_lower_fraction"])),
    )
    background = coherences[:lower_count]
    background_median = float(median(background))
    background_mad = float(
        median(abs(value - background_median) for value in background)
    )
    normalized_mad = detector["normalized_mad_scale"] * background_mad
    threshold = (
        background_median
        + detector["coherence_mad_multiplier"] * normalized_mad
    )

    raw_candidates = [
        float(item["rms_median"]) > detector["basic_rms_floor"]
        and float(item["srp_coherence"]) > threshold
        for item in normalized
    ]
    applicable = [False] * len(normalized)
    runs: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(raw_candidates):
        if not raw_candidates[cursor]:
            cursor += 1
            continue
        stop = cursor + 1
        while stop < len(raw_candidates) and raw_candidates[stop]:
            stop += 1
        if stop - cursor >= detector["minimum_contiguous_windows"]:
            applicable[cursor:stop] = [True] * (stop - cursor)
            runs.append((cursor, stop))
        cursor = stop

    reasons: list[str | None] = []
    for item, raw_candidate, selected in zip(
        normalized,
        raw_candidates,
        applicable,
        strict=True,
    ):
        if selected:
            reason = None
        elif float(item["rms_median"]) <= detector["basic_rms_floor"]:
            reason = "below_basic_rms_floor"
        elif not raw_candidate:
            reason = "insufficient_directional_coherence"
        else:
            reason = "insufficient_directional_continuity"
        reasons.append(reason)

    longest = max(runs, key=lambda item: item[1] - item[0]) if runs else None
    return {
        "method": DETECTOR_METHOD,
        "source_window_count": len(normalized),
        "applicable_window_count": sum(applicable),
        "non_applicable_window_count": len(normalized) - sum(applicable),
        "applicable_window_indices": [
            item["window_index"]
            for item, selected in zip(normalized, applicable, strict=True)
            if selected
        ],
        "coherence_background_lower_window_count": len(background),
        "coherence_background_median": background_median,
        "coherence_background_mad": background_mad,
        "coherence_background_normalized_mad": normalized_mad,
        "coherence_threshold": threshold,
        "exclusion_reason_counts": dict(
            sorted(Counter(reason for reason in reasons if reason is not None).items())
        ),
        "longest_continuous_interval": (
            None
            if longest is None
            else _interval_record(normalized, longest, detector)
        ),
        "decisions": [
            {
                "window_index": item["window_index"],
                "start_sample": item["start_sample"],
                "rms_median": item["rms_median"],
                "srp_coherence": item["srp_coherence"],
                "applicable": selected,
                "exclusion_reason": reason,
            }
            for item, selected, reason in zip(
                normalized,
                applicable,
                reasons,
                strict=True,
            )
        ],
    }


def aggregate_useful_sound_take(
    base_take: Mapping[str, Any],
    *,
    identity: Any,
    analyzed_windows: Sequence[Mapping[str, Any]],
    applicable_window_indices: Sequence[int],
) -> dict[str, Any]:
    """Re-aggregate one A/B take from detector-selected windows only."""

    stratum = identity.stratum_id
    if stratum not in {
        "A_controlled_boundary_sweep",
        "B_center_nominal_level",
    }:
        raise UsefulSoundDiagnosticError(
            "useful-sound aggregation is applicable only to A/B takes"
        )
    by_index: dict[int, Mapping[str, Any]] = {}
    for position, analysis in enumerate(analyzed_windows):
        if not isinstance(analysis, Mapping):
            raise UsefulSoundDiagnosticError(
                f"analyzed_windows[{position}] must be an object"
            )
        record = analysis.get("record")
        if not isinstance(record, Mapping):
            raise UsefulSoundDiagnosticError(
                f"analyzed_windows[{position}].record must be an object"
            )
        index = _integer(record.get("window_index"), "record.window_index")
        if index in by_index:
            raise UsefulSoundDiagnosticError("duplicate analyzed window index")
        by_index[index] = analysis
    selected_indices = [
        _integer(value, "applicable_window_indices")
        for value in applicable_window_indices
    ]
    if (
        not selected_indices
        or len(set(selected_indices)) != len(selected_indices)
        or selected_indices != sorted(selected_indices)
        or any(index not in by_index for index in selected_indices)
    ):
        raise UsefulSoundDiagnosticError("invalid applicable window identity set")

    selected = [by_index[index] for index in selected_indices]
    records = [dict(item["record"]) for item in selected]
    valid_bearings = [
        float(record["srp_bearing_deg_f_project"])
        for record in records
        if record["srp_bearing_deg_f_project"] is not None
    ]
    if not valid_bearings:
        raise UsefulSoundDiagnosticError(
            f"{identity.planned_take_id}: no useful window emitted a bearing"
        )
    target = float(identity.target_bearing_deg_f_project)
    errors = [
        corrective_03._circular_absolute_difference(target, bearing)
        for bearing in valid_bearings
    ]
    representative = float(median(valid_bearings))
    output = deepcopy(dict(base_take))
    output.update(
        {
            "window_summary": {
                "source_window_count": len(records),
                "abstained_window_count": sum(
                    bool(record["abstained"]) for record in records
                ),
                "sub_floor_direction_emission_count": sum(
                    bool(record["sub_floor_direction_emitted"])
                    for record in records
                ),
            },
            "bearing_absolute_error_deg": float(median(errors)),
            "estimated_bearing_deg_f_project": representative,
            "sector_correct": (
                corrective_03._majority_sector(valid_bearings)
                == bearing_deg_to_sector_name(target)
                if stratum == "B_center_nominal_level"
                else None
            ),
            "candidate_covered": any(
                corrective_03._circular_absolute_difference(target, bearing)
                <= 20.0
                for bearing in [representative]
            ),
            "candidate_bearings_deg_f_project": [representative],
            "confidence": (
                float(median(float(item["confidence"]) for item in selected))
                if stratum == "B_center_nominal_level"
                else None
            ),
            "bearing_windows": records,
        }
    )

    reference_by_pair = {
        item["pair_id"]: float(item["reference_tdoa_us"])
        for item in base_take.get("tdoa", [])
    }
    if stratum == "A_controlled_boundary_sweep":
        values_by_pair: dict[str, list[float]] = defaultdict(list)
        for item in selected:
            if item["record"]["abstained"]:
                continue
            tdoa = item.get("tdoa_s")
            if not isinstance(tdoa, Mapping):
                raise UsefulSoundDiagnosticError(
                    "selected non-abstained window lacks TDOA diagnostics"
                )
            for pair_id in reference_by_pair:
                values_by_pair[pair_id].append(float(tdoa[pair_id]) * 1_000_000.0)
        if set(values_by_pair) != set(reference_by_pair) or any(
            not values for values in values_by_pair.values()
        ):
            raise UsefulSoundDiagnosticError(
                f"{identity.planned_take_id}: incomplete useful-window TDOA"
            )
        output["tdoa"] = [
            {
                "pair_id": pair_id,
                "tdoa_us": float(median(values_by_pair[pair_id])),
                "reference_tdoa_us": reference_by_pair[pair_id],
                "absolute_error_us": abs(
                    float(median(values_by_pair[pair_id]))
                    - reference_by_pair[pair_id]
                ),
            }
            for pair_id in sorted(reference_by_pair)
        ]
    else:
        output["tdoa"] = []
    return output


def evaluate_useful_sound_scientific_payload(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Evaluate all frozen criteria with only A/B applicability relaxed."""

    root = repo_root.resolve()
    if (
        not isinstance(payload, Mapping)
        or set(payload) != corrective_03._PAYLOAD_FIELDS
        or payload.get("schema") != DIAGNOSTIC_SCIENTIFIC_PAYLOAD_SCHEMA
    ):
        raise UsefulSoundDiagnosticError(
            "diagnostic scientific payload fields or schema mismatch"
        )
    config_03 = corrective_03.load_corrective_config(root)
    registry = corrective_03.build_identity_registry(root, config_03)
    corrective_03._validate_contract_identity(
        payload["contract"],
        config_03,
        root,
    )
    takes = payload["takes"]
    if not isinstance(takes, Sequence) or isinstance(takes, (str, bytes)):
        raise UsefulSoundDiagnosticError("takes must be a sequence")

    config_02 = corrective_02.load_corrective_config(root)
    normalized: dict[str, dict[str, Any]] = {}
    derived_by_take: dict[str, dict[str, Any]] = {}
    selected_window_count = 0
    abstained_window_count = 0
    for position, raw in enumerate(takes):
        label = f"takes[{position}]"
        if (
            not isinstance(raw, Mapping)
            or set(raw) != corrective_03._TAKE_FIELDS
        ):
            raise UsefulSoundDiagnosticError(f"{label} fields mismatch")
        identity_payload = raw.get("identity")
        if not isinstance(identity_payload, Mapping):
            raise UsefulSoundDiagnosticError(f"{label}.identity must be an object")
        take_id = identity_payload.get("planned_take_id")
        identity = registry.get(take_id)
        if identity is None or dict(identity_payload) != identity.payload_identity():
            raise UsefulSoundDiagnosticError(f"{label} identity mismatch")
        if take_id in normalized:
            raise UsefulSoundDiagnosticError(f"duplicate take identity: {take_id}")

        record = deepcopy(dict(raw))
        windows = record.pop("bearing_windows")
        if identity.stratum_id in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
        }:
            derived = _validate_useful_bearing_windows(
                windows,
                take=record,
                identity=identity,
                config=config_03,
            )
            derived_by_take[take_id] = derived
            selected_window_count += derived["source_window_count"]
            abstained_window_count += derived["abstained_window_count"]
            target = float(identity.target_bearing_deg_f_project)
            surrogate = (target + derived["per_take_error_deg"]) % 360.0
            record["estimated_bearing_deg_f_project"] = surrogate
            if identity.stratum_id == "B_center_nominal_level":
                record["sector_correct"] = (
                    bearing_deg_to_sector_name(surrogate)
                    == bearing_deg_to_sector_name(target)
                )
        elif windows != []:
            raise UsefulSoundDiagnosticError(
                f"{take_id}.bearing_windows is not applicable and must be empty"
            )

        take_config = deepcopy(config_02)
        if identity.stratum_id in {
            "A_controlled_boundary_sweep",
            "B_center_nominal_level",
        }:
            take_config["window_contract"]["expected_count_by_duration_s"][
                str(identity.duration_s)
            ] = record["window_summary"]["source_window_count"]
        corrective_02._validate_take_values(record, identity, take_config)
        normalized[take_id] = record

    if set(normalized) != set(registry):
        raise UsefulSoundDiagnosticError("diagnostic payload exact take set mismatch")
    comparisons = corrective_02._validate_comparisons(
        payload["sim_vs_real"],
        normalized,
        registry,
        config_02,
    )
    sector_accuracy = sum(
        bool(derived_by_take[take_id]["sector_correct"])
        for take_id, identity in registry.items()
        if identity.stratum_id == "B_center_nominal_level"
    ) / 8.0
    sector_comparison = next(
        item
        for item in comparisons
        if item["comparison_id"] == "sector_accuracy_b"
    )
    sector_comparison["real"] = sector_accuracy
    representatives_by_cell: dict[str, list[float]] = defaultdict(list)
    for take_id, identity in registry.items():
        if identity.stratum_id != "A_controlled_boundary_sweep":
            continue
        representatives_by_cell[str(identity.bearing_cell_id)].append(
            derived_by_take[take_id]["representative_bearing_deg"]
        )
    repeatability = max(
        corrective_03._circular_range(values)
        for values in representatives_by_cell.values()
    )
    values = corrective_02._derive_criterion_values(
        normalized,
        registry,
        comparisons,
        config_02,
    )
    frozen = corrective_02._load_json(root / corrective_02.V1_CONFIG_PATH)
    delegated_outcomes = tuple(
        corrective_02._evaluate_threshold(
            item,
            values[item["criterion_id"]],
        )
        for item in frozen["criteria"]
    )
    outcomes = tuple(
        corrective_03._replace_derived_outcome(
            item,
            sector_accuracy,
            repeatability,
        )
        for item in delegated_outcomes
    )
    readiness_passed = all(item.passed for item in outcomes if item.gating)
    source_window_count = sum(
        int(item["window_summary"]["source_window_count"])
        for item in normalized.values()
    )
    return {
        "schema": DIAGNOSTIC_RESULT_SCHEMA,
        "status": "passed" if readiness_passed else "failed",
        "readiness_passed": readiness_passed,
        "failed_gating_criteria": [
            item.criterion_id
            for item in outcomes
            if item.gating and not item.passed
        ],
        "criteria": [item.report() for item in outcomes],
        "comparison_classifications": comparisons,
        "identity_summary": {
            "take_count": len(normalized),
            "group_count": len({item.group_id for item in registry.values()}),
            "window_source_count": source_window_count,
            "useful_bearing_window_count": selected_window_count,
            "abstained_useful_bearing_window_count": abstained_window_count,
            "valid_useful_bearing_window_count": (
                selected_window_count - abstained_window_count
            ),
            "bearing_window_derivation": (
                "corrective_03_exact_windows_after_independent_useful_sound_"
                "applicability"
            ),
        },
        "config_identity": {
            "schema": config_03["schema"],
            "corrective_id": config_03["corrective_id"],
            "config_sha256": corrective_03.sha256_file(
                root / corrective_03.CONFIG_PATH
            ),
            "bound_holdout_id": payload["contract"]["bound_holdout_id"],
            "seal_payload_sha256": payload["contract"]["seal_payload_sha256"],
            "planned_take_count": 47,
            "frozen_at_utc": config_03["frozen_at_utc"],
        },
        "evaluation_error": None,
        "reused_holdout": True,
        "diagnostic_only": True,
        "criteria_thresholds_unchanged": True,
        "holdout_observations_accessed_by_evaluator": 0,
    }


def _validate_useful_bearing_windows(
    windows: Any,
    *,
    take: Mapping[str, Any],
    identity: Any,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    take_id = identity.planned_take_id
    if (
        not isinstance(windows, Sequence)
        or isinstance(windows, (str, bytes))
        or not windows
    ):
        raise UsefulSoundDiagnosticError(
            f"{take_id}.bearing_windows must be a non-empty sequence"
        )
    expected_count = config["window_observation_contract"][
        "expected_count_by_duration_s"
    ][str(identity.duration_s)]
    indices: set[int] = set()
    valid: list[float] = []
    abstained = 0
    sub_floor = 0
    for position, item in enumerate(windows):
        label = f"{take_id}.bearing_windows[{position}]"
        if (
            not isinstance(item, Mapping)
            or set(item) != corrective_03._WINDOW_FIELDS
        ):
            raise UsefulSoundDiagnosticError(f"{label} fields mismatch")
        index = _integer(item["window_index"], f"{label}.window_index")
        if index >= expected_count or index in indices:
            raise UsefulSoundDiagnosticError(f"{label} identity mismatch")
        indices.add(index)
        if (
            item["window_id"] != f"window_{index:03d}"
            or item["start_sample"]
            != index * config["window_observation_contract"]["hop_samples"]
        ):
            raise UsefulSoundDiagnosticError(f"{label} identity mismatch")
        if not isinstance(item["abstained"], bool) or not isinstance(
            item["sub_floor_direction_emitted"], bool
        ):
            raise UsefulSoundDiagnosticError(f"{label} boolean fields mismatch")
        sub_floor += int(item["sub_floor_direction_emitted"])
        bearing = item["srp_bearing_deg_f_project"]
        if item["abstained"]:
            if bearing is not None:
                raise UsefulSoundDiagnosticError(
                    f"{label} abstention requires a null bearing"
                )
            abstained += 1
        else:
            valid.append(corrective_03._bearing(bearing, f"{label}.bearing"))
    if not valid:
        raise UsefulSoundDiagnosticError(f"{take_id} has no useful bearing")
    summary = {
        "source_window_count": len(windows),
        "abstained_window_count": abstained,
        "sub_floor_direction_emission_count": sub_floor,
    }
    if take.get("window_summary") != summary:
        raise UsefulSoundDiagnosticError(
            f"{take_id}.window_summary contradicts useful windows"
        )
    target = float(identity.target_bearing_deg_f_project)
    errors = [
        corrective_03._circular_absolute_difference(target, bearing)
        for bearing in valid
    ]
    derived_error = float(median(errors))
    if take.get("bearing_absolute_error_deg") != derived_error:
        raise UsefulSoundDiagnosticError(
            f"{take_id}.bearing_absolute_error_deg contradicts useful windows"
        )
    representative = float(median(valid))
    if take.get("estimated_bearing_deg_f_project") != representative:
        raise UsefulSoundDiagnosticError(
            f"{take_id}.estimated bearing contradicts useful windows"
        )
    if identity.stratum_id == "B_center_nominal_level":
        expected_sector = (
            corrective_03._majority_sector(valid)
            == bearing_deg_to_sector_name(target)
        )
        if take.get("sector_correct") is not expected_sector:
            raise UsefulSoundDiagnosticError(
                f"{take_id}.sector correctness contradicts useful windows"
            )
    return {
        "source_window_count": len(windows),
        "abstained_window_count": abstained,
        "per_take_error_deg": derived_error,
        "representative_bearing_deg": representative,
        "sector_correct": (
            corrective_03._majority_sector(valid)
            == bearing_deg_to_sector_name(target)
        ),
    }


def _interval_record(
    windows: Sequence[Mapping[str, float | int]],
    run: tuple[int, int],
    config: Mapping[str, float | int],
) -> dict[str, float | int]:
    first, stop = run
    last = stop - 1
    start_sample = int(windows[first]["start_sample"])
    end_sample = int(windows[last]["start_sample"]) + int(config["window_samples"])
    return {
        "first_window_index": int(windows[first]["window_index"]),
        "last_window_index": int(windows[last]["window_index"]),
        "start_sample": start_sample,
        "end_sample": end_sample,
        "duration_s": (end_sample - start_sample) / float(config["sample_rate_hz"]),
        "window_count": stop - first,
    }


def _validated_detector_config(
    value: Mapping[str, Any],
) -> dict[str, float | int]:
    if not isinstance(value, Mapping) or set(value) != set(DEFAULT_DETECTOR_CONFIG):
        raise UsefulSoundDiagnosticError("detector configuration fields mismatch")
    config = {
        "sample_rate_hz": _integer(value["sample_rate_hz"], "sample_rate_hz"),
        "window_samples": _integer(value["window_samples"], "window_samples"),
        "hop_samples": _integer(value["hop_samples"], "hop_samples"),
        "basic_rms_floor": _finite(
            value["basic_rms_floor"], "basic_rms_floor", minimum=0.0
        ),
        "background_lower_fraction": _finite(
            value["background_lower_fraction"],
            "background_lower_fraction",
            minimum=0.0,
            maximum=1.0,
        ),
        "normalized_mad_scale": _finite(
            value["normalized_mad_scale"], "normalized_mad_scale", minimum=0.0
        ),
        "coherence_mad_multiplier": _finite(
            value["coherence_mad_multiplier"],
            "coherence_mad_multiplier",
            minimum=0.0,
        ),
        "minimum_contiguous_windows": _integer(
            value["minimum_contiguous_windows"],
            "minimum_contiguous_windows",
        ),
    }
    if (
        config["sample_rate_hz"] <= 0
        or config["window_samples"] <= 0
        or config["hop_samples"] <= 0
        or config["minimum_contiguous_windows"] <= 0
        or not 0.0 < config["background_lower_fraction"] <= 0.5
    ):
        raise UsefulSoundDiagnosticError("detector configuration domain failure")
    return config


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UsefulSoundDiagnosticError(f"{name} must be a non-negative integer")
    return value


def _finite(
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsefulSoundDiagnosticError(f"{name} must be numeric")
    number = float(value)
    if (
        not math.isfinite(number)
        or number < minimum
        or (maximum is not None and number > maximum)
    ):
        raise UsefulSoundDiagnosticError(f"{name} is outside its numeric domain")
    return number
