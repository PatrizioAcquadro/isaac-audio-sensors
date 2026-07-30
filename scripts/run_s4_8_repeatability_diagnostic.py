#!/usr/bin/env python3
"""Run an additive three-take S4.8 engineering repeatability diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_3 import (
    _circular_range,
    load_pilot_configuration,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    build_engineering_precollection_manifest,
    run_supported_engineering_acquisition,
)
from isaac_audio_sensors.acquisition.s4_8_physical_backend import (
    RemotePhysicalEngineeringBackend,
    S48PhysicalBackendError,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    S48PresealingGateError,
    load_presealing_config_v2,
)
from isaac_audio_sensors.core import acceptance_criteria_corrective_03

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = (ROOT / ".local" / "s4_8").resolve()
DEFAULT_CONFIG = ROOT / "configs/s4_8_engineering_campaign.v1.json"
DEFAULT_CAMPAIGN_ROOT = LOCAL_ROOT / "s4_8_repeatability_22p5_v1"
PILOT_CONFIG = ROOT / "configs/s4_3_pilot.v1.json"
REFERENCE_PATH = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.2/reference/"
    "s4_2_reference_v1.0.0.wav"
)
SCHEMA = "ias.s4_8.additive_repeatability_campaign.v1"
LEDGER_SCHEMA = "ias.s4_8.additive_repeatability_ledger_record.v1"
TAKE_COUNT = 3
TARGET_BEARING_DEG = 22.5
TARGET_RADIUS_M = 0.8
PLAYBACK_GAIN = 0.75
PAIR_IDS = tuple(
    f"raw_microphone_{left}->raw_microphone_{right}"
    for left in range(4)
    for right in range(left + 1, 4)
)
SOURCE_PATHS = (
    "configs/s4_3_pilot.v1.json",
    "configs/s4_6_profile_application.v1.json",
    "configs/s4_8_engineering_campaign.v1.json",
    "configs/s4_8_presealing_gate.v2.json",
    "docs/schemas/s4_8_presealing_gate_config.v2.schema.json",
    "scripts/run_s4_8_repeatability_diagnostic.py",
    "scripts/s4_8_mac_playback.swift",
    "outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json",
    "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json",
    "src/isaac_audio_sensors/acquisition/s4_3.py",
    "src/isaac_audio_sensors/acquisition/s4_8.py",
    "src/isaac_audio_sensors/acquisition/s4_8_engineering_acquisition.py",
    "src/isaac_audio_sensors/acquisition/s4_8_physical_backend.py",
    "src/isaac_audio_sensors/acquisition/s4_8_presealing_gate.py",
    "src/isaac_audio_sensors/acquisition/s4_8_presealing_gate_v2.py",
    "src/isaac_audio_sensors/core/acceptance_criteria_corrective_03.py",
)
AUTHORITY_NONE = {
    "final_protocol_frozen": False,
    "official_acquisition": False,
    "official_evaluation": False,
    "creates_grant": False,
    "consumes_grant": False,
    "opens_holdout": False,
    "publishes_official_evidence": False,
}
CLASSIFICATION = {
    "engineering_only": True,
    "pre_holdout": True,
    "additive": True,
    "uncounted": True,
    "diagnostic_results_only": True,
    "official_evidence_eligible": False,
    "full_s4_8_pass_claimed": False,
}


class RepeatabilityError(RuntimeError):
    """Fail-closed repeatability workflow error."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepeatabilityError(f"JSON read failure for {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepeatabilityError(f"JSON object required: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise RepeatabilityError(f"refusing to overwrite {path}") from exc


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _require_bound_source_state(expected_head: str | None = None) -> str:
    head = _git_head()
    if expected_head is not None and head != expected_head:
        raise RepeatabilityError("repository HEAD differs from the campaign binding")
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *SOURCE_PATHS],
        cwd=ROOT,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or untracked.stdout.strip():
        raise RepeatabilityError(
            "repeatability controller, detector, gate, or analysis source is not "
            "committed byte-for-byte"
        )
    return head


def _campaign_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == LOCAL_ROOT or LOCAL_ROOT not in resolved.parents:
        raise RepeatabilityError("campaign root must be a child of .local/s4_8")
    if resolved.name in {
        "s4_8_preliminary",
        "s4_8_preliminary_confirmation_02",
        "s4_8_engineering_rehearsal_v9",
    }:
        raise RepeatabilityError("campaign root collides with historical evidence")
    return resolved


def _take_definitions() -> list[dict[str, Any]]:
    x_m = TARGET_RADIUS_M * math.cos(math.radians(TARGET_BEARING_DEG))
    y_m = TARGET_RADIUS_M * math.sin(math.radians(TARGET_BEARING_DEG))
    return [
        {
            "take_number": number,
            "take_id": f"s48eng_repeatability_22p5_take_{number:02d}",
            "duration_s": 20,
            "source_frame": "F_project",
            "source_bearing_deg": TARGET_BEARING_DEG,
            "source_radius_m": TARGET_RADIUS_M,
            "source_xy_m": [x_m, y_m],
            "playback_gain": PLAYBACK_GAIN,
            "reference_wav_sha256": _sha256(REFERENCE_PATH),
            "independent_recording": True,
            "rig_fixed": True,
            "mac_removal_and_exact_reposition_before_take": number > 1,
        }
        for number in range(1, TAKE_COUNT + 1)
    ]


def _validate_preflight(report: Mapping[str, Any]) -> None:
    asset = report.get("continuous_asset", {})
    deployment = report.get("continuous_asset_deployment", {})
    if (
        report.get("schema") != "ias.s4_8.physical_rig_preflight.v1"
        or report.get("status") != "passed"
        or report.get("read_only_hardware_checks") is not True
        or report.get("recorder_started") is not False
        or report.get("playback_started") is not False
        or report.get("zed_recording_started") is not False
        or asset.get("source_sha256") != _sha256(REFERENCE_PATH)
        or deployment.get("action") not in {"deployed", "verified_existing"}
        or deployment.get("sha256") != asset.get("asset_sha256")
        or report.get("mac_acceptance", {}).get("status") != "passed"
        or report.get("pi", {}).get("status") != "passed"
        or report.get("zed", {}).get("status") != "passed"
    ):
        raise RepeatabilityError("physical rig preflight is absent, stale, or failed")


def _validate_campaign(manifest: Mapping[str, Any]) -> None:
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("classification") != CLASSIFICATION
        or manifest.get("authority") != AUTHORITY_NONE
        or manifest.get("take_count") != TAKE_COUNT
        or manifest.get("takes") != _take_definitions()
        or manifest.get("limits")
        != {
            "bearing_circular_range_deg_max": 20.0,
            "pair_tdoa_median_range_us_max": 125.0,
        }
    ):
        raise RepeatabilityError("campaign manifest identity or scope is invalid")


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_json(args.config.resolve())
    gate = load_presealing_config_v2(ROOT)
    pilot = load_pilot_configuration(PILOT_CONFIG, repo_root=ROOT)
    head = _require_bound_source_state()
    root = _campaign_root(args.campaign_root)
    if root.exists():
        raise RepeatabilityError(f"refusing to reuse campaign root: {root}")
    preflight = _load_json(args.preflight_report.resolve())
    _validate_preflight(preflight)
    root.mkdir(parents=True)
    freeze = root / "freeze"
    freeze.mkdir()
    preflight_copy = freeze / "preflight_report.json"
    shutil.copyfile(args.preflight_report.resolve(), preflight_copy)
    archive = freeze / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    source_hashes = {path: _sha256(ROOT / path) for path in SOURCE_PATHS}
    repeatability = pilot["repeatability_acceptance"]
    payload = {
        "schema": SCHEMA,
        "campaign_id": root.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_head": head,
        "source_archive_sha256": _sha256(archive),
        "source_files_sha256": source_hashes,
        "preflight_report_sha256": _sha256(preflight_copy),
        "reference_wav_sha256": _sha256(REFERENCE_PATH),
        "continuous_asset_sha256": preflight["continuous_asset"]["asset_sha256"],
        "gate_configuration_sha256": canonical_sha256(gate),
        "detector_configuration_sha256": canonical_sha256(gate["detector"]),
        "analysis_configuration_sha256": canonical_sha256(pilot),
        "device_profile_id": config["respeaker"]["profile_id"],
        "channel_map": config["channel_map"],
        "take_count": TAKE_COUNT,
        "takes": _take_definitions(),
        "between_take_contract": {
            "stop_playback": True,
            "stop_recording": True,
            "move_mac_slightly": True,
            "reposition_exactly": True,
            "rig_remains_fixed": True,
            "new_explicit_authorization_required": True,
            "automatic_continuation_forbidden": True,
        },
        "limits": {
            "bearing_circular_range_deg_max": float(
                repeatability["trial_median_bearing_circular_range_deg_max"]
            ),
            "pair_tdoa_median_range_us_max": float(
                repeatability["pair_tdoa_trial_median_range_us_max"]
            ),
        },
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    manifest = {**payload, "manifest_sha256": canonical_sha256(payload)}
    _write_new_json(freeze / "campaign_manifest.json", manifest)
    return {
        "status": "prepared",
        "campaign_root": str(root),
        "manifest_sha256": manifest["manifest_sha256"],
        "take_count": TAKE_COUNT,
        "acquisition_started": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RepeatabilityError("ledger line must be a JSON object")
        records.append(value)
    return records


def _validate_ledger(
    records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> None:
    previous = manifest["manifest_sha256"]
    for sequence, record in enumerate(records):
        payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if (
            record.get("schema") != LEDGER_SCHEMA
            or record.get("sequence") != sequence
            or record.get("take_number") != sequence + 1
            or record.get("take_id") != manifest["takes"][sequence]["take_id"]
            or record.get("campaign_manifest_sha256") != manifest["manifest_sha256"]
            or record.get("previous_record_sha256") != previous
            or record.get("decision") not in {"PASS", "RETRY_REQUIRED"}
            or record.get("record_sha256") != canonical_sha256(payload)
        ):
            raise RepeatabilityError("repeatability ledger is invalid")
        previous = record["record_sha256"]


def run_take(args: argparse.Namespace) -> dict[str, Any]:
    root = _campaign_root(args.campaign_root)
    manifest = _load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign(manifest)
    _require_bound_source_state(str(manifest["code_head"]))
    config = _load_json(args.config.resolve())
    ledger_path = root / "attempt_ledger.jsonl"
    records = _ledger(ledger_path)
    _validate_ledger(records, manifest)
    if args.take_number != len(records) + 1:
        raise RepeatabilityError("requested take is not the exact next take")
    if any(record["decision"] != "PASS" for record in records):
        raise RepeatabilityError("a prior take requires operator review")
    take = manifest["takes"][args.take_number - 1]
    attempt_root = root / "takes" / take["take_id"]
    if attempt_root.exists():
        raise RepeatabilityError(f"take artifact root already exists: {attempt_root}")
    attempt_root.mkdir(parents=True)
    take_definition_sha256 = canonical_sha256(take)
    precollection = build_engineering_precollection_manifest(
        code_head=str(manifest["code_head"]),
        environment_identity=(
            f"campaign:{manifest['manifest_sha256']}:"
            f"preflight:{manifest['preflight_report_sha256']}:"
            f"take:{take_definition_sha256}"
        ),
        reference_wav_sha256=str(manifest["reference_wav_sha256"]),
        gate_configuration_sha256=str(manifest["gate_configuration_sha256"]),
        detector_configuration_sha256=str(
            manifest["detector_configuration_sha256"]
        ),
        device_profile_id=str(manifest["device_profile_id"]),
        channel_map=manifest["channel_map"],
        protocol_id=(
            "s4_8_additive_preholdout_repeatability_22p5_v1:"
            f"{manifest['manifest_sha256']}:{take_definition_sha256}"
        ),
        capture_controller_identity=str(config["controller"]["identity"]),
        capture_controller_version=str(config["controller"]["version"]),
    )
    _write_new_json(attempt_root / "take_definition.json", take)
    _write_new_json(attempt_root / "take_precollection_manifest.json", precollection)
    backend = RemotePhysicalEngineeringBackend(
        pi_ssh_prefix=config["respeaker"]["ssh_prefix"],
        pi_scp_prefix=config["respeaker"]["scp_prefix"],
        pi_scp_target=config["respeaker"]["scp_target"],
        pi_helper_path=config["respeaker"]["helper_path"],
        pi_remote_attempt=(
            f"S4.8/repeatability_22p5_v1/"
            f"{manifest['manifest_sha256'][:16]}/{take['take_id']}"
        ),
        pi_device=config["respeaker"]["device"],
        capture_duration_s=float(take["duration_s"]),
        mac_ssh_prefix=config["playback"]["ssh_prefix"],
        mac_playback_helper_path=config["playback"]["playback_helper_mac_path"],
        mac_continuous_asset_path=config["reference"]["continuous_asset_mac_path"],
        mac_continuous_asset_sha256=str(manifest["continuous_asset_sha256"]),
        playback_gain=float(take["playback_gain"]),
        zed_helper_path=ROOT / "scripts/run_s4_2_zed_capture.py",
        zed_replay_path=ROOT / "scripts/validate_s4_2_zed_svo.py",
        expected_zed_serial=config["zed"]["serial"],
        expected_zed_sdk=config["zed"]["sdk_version_reference"],
        expected_zed_camera_firmware=config["zed"]["camera_firmware_reference"],
        expected_zed_sensor_firmware=config["zed"]["sensor_firmware_reference"],
    )
    try:
        result = run_supported_engineering_acquisition(
            backend=backend,
            repo_root=ROOT,
            capture_path=attempt_root / "respeaker_audio.wav",
            reference_path=REFERENCE_PATH,
            manifest=precollection,
            expected_manifest_sha256=str(precollection["manifest_sha256"]),
            journal_path=attempt_root / "process_journal.jsonl",
            retry_report_path=attempt_root / "retry_report.json",
            candidate_seal_path=attempt_root / "candidate_seal.json",
            clearance_registry_path=attempt_root / "clearance_consumed.json",
            dry_run=False,
        )
    except BaseException as exc:
        try:
            cleanup = backend.abort()
        except Exception as cleanup_exc:
            cleanup = {
                "error_type": type(cleanup_exc).__name__,
                "error": str(cleanup_exc),
            }
        _write_new_json(
            attempt_root / "controller_failure.json",
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "cleanup": cleanup,
                "retained": True,
                "classification": dict(CLASSIFICATION),
                "authority": dict(AUTHORITY_NONE),
            },
        )
        raise
    _write_new_json(attempt_root / "gate_report.json", result["report"])
    if result["clearance"] is not None:
        _write_new_json(attempt_root / "candidate_clearance.json", result["clearance"])
    controller_result = {
        **result,
        "take": take,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    _write_new_json(attempt_root / "controller_result.json", controller_result)
    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(attempt_root.iterdir())
        if path.is_file()
    }
    payload = {
        "schema": LEDGER_SCHEMA,
        "sequence": len(records),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "previous_record_sha256": (
            manifest["manifest_sha256"]
            if not records
            else records[-1]["record_sha256"]
        ),
        "take_number": take["take_number"],
        "take_id": take["take_id"],
        "decision": result["decision"],
        "artifact_sha256": artifact_hashes,
    }
    record = {**payload, "record_sha256": canonical_sha256(payload)}
    _append_json_line(ledger_path, record)
    return {
        "status": "complete",
        "decision": result["decision"],
        "take_number": take["take_number"],
        "take_id": take["take_id"],
        "attempt_root": str(attempt_root),
        "record_sha256": record["record_sha256"],
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _pair_medians_us(analysis: Mapping[str, Any]) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for window in analysis["windows"]:
        if window.get("abstained"):
            continue
        for pair, value in window.get("tdoa_s", {}).items():
            grouped.setdefault(str(pair), []).append(float(value) * 1e6)
    return {
        pair: float(statistics.median(values))
        for pair, values in sorted(grouped.items())
        if values
    }


def _confidence_summary(values: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise RepeatabilityError("current analysis produced no confidence values")
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "median": float(statistics.median(ordered)),
        "p95_nearest_rank": ordered[p95_index],
        "minimum": ordered[0],
        "maximum": ordered[-1],
    }


def _current_pipeline_analysis(
    *,
    campaign_root: Path,
    take: Mapping[str, Any],
    identity: Any,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    source = campaign_root / "takes" / take["take_id"] / "respeaker_audio.wav"
    runs_root = ROOT / "runs"
    runs_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="s4_8_repeatability_processing_", dir=runs_root
    ) as temporary:
        attempt = Path(temporary) / "attempt"
        raw_root = attempt / "raw"
        raw_root.mkdir(parents=True)
        wav = raw_root / "respeaker_audio.wav"
        shutil.copyfile(source, wav)
        qa = attempt / "technical_qa.json"
        qa.write_text(
            json.dumps(
                {
                    "schema": "ias.s4_8.repeatability_technical_qa_adapter.v1",
                    "overall_technical_pass": True,
                    "diagnostic_only": True,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        seal = {
            "artifacts": [
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "byte_size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in (wav, qa)
            ]
        }
        derived, inventory = s4_8._analyze_real_take(
            ROOT,
            attempt,
            identity,
            profile=profile,
            seal=seal,
        )
        samples, rate = s4_8._read_pcm16(wav)
        raw = samples[:, 2:6].T
        adjusted = raw * np.asarray(profile["gain_multipliers"])[:, None]
        positions = np.asarray(profile["positions"], dtype=float)
        ids = tuple(f"raw_microphone_{index}" for index in range(4))
        position_map = dict(zip(ids, map(tuple, positions), strict=True))
        aperture = max(
            float(np.linalg.norm(positions[left] - positions[right]))
            for left in range(4)
            for right in range(left + 1, 4)
        )
        max_delay = aperture / 343.0 + 1.0 / rate
        confidences = []
        replay_windows = []
        for index in range(159):
            start = index * 2000
            (
                record,
                confidence,
                _tdoa,
                _correlations,
                _elapsed_ms,
                _adapter_ms,
            ) = s4_8._analyze_window(
                adjusted[:, start : start + 4000],
                ids=ids,
                position_map=position_map,
                sample_rate_hz=rate,
                max_delay_s=max_delay,
                index=index,
                start=start,
                take_id=str(take["take_id"]),
            )
            confidences.append(confidence)
            replay_windows.append(record)
        if replay_windows != derived["bearing_windows"]:
            raise RepeatabilityError(
                "current S4.8 confidence replay differs from derived windows"
            )
    scientific_derived = {
        key: value for key, value in derived.items() if key != "latency"
    }
    stable_inventory = {
        key: value for key, value in inventory.items() if key != "attempt_root"
    }
    confidence = _confidence_summary(confidences)
    scientific_payload = {
        "derived": scientific_derived,
        "confidence": confidence,
        "capture_sha256": _sha256(source),
    }
    return {
        "schema": "ias.s4_8.current_repeatability_take_analysis.v1",
        "status": "PASS" if not derived["failed"] else "FAIL",
        "take_number": take["take_number"],
        "take_id": take["take_id"],
        "diagnostic_template_identity": identity.payload_identity(),
        "derived": derived,
        "inventory": stable_inventory,
        "confidence": confidence,
        "abstention_rate": (
            derived["window_summary"]["abstained_window_count"]
            / derived["window_summary"]["source_window_count"]
        ),
        "capture_sha256": _sha256(source),
        "scientific_replay_sha256": canonical_sha256(scientific_payload),
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _accuracy_thresholds() -> dict[str, float]:
    register = _load_json(
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.7_corrective_03/"
        "criteria_register.json"
    )
    wanted = {
        "bearing_median_absolute_error_stratum_a": "median",
        "bearing_p95_absolute_error_stratum_a": "p95_nearest_rank",
        "bearing_worst_absolute_error_stratum_a": "worst",
    }
    result = {}
    for criterion in register["details"]["criteria"]:
        key = wanted.get(criterion.get("criterion_id"))
        if key is not None:
            result[key] = float(criterion["threshold"])
    if set(result) != set(wanted.values()):
        raise RepeatabilityError("current bearing-accuracy thresholds are incomplete")
    return result


def _unique_pair_ranges(
    all_pairs: Mapping[str, Sequence[float]],
) -> dict[str, float]:
    if set(all_pairs) != set(PAIR_IDS) or any(
        len(values) != TAKE_COUNT for values in all_pairs.values()
    ):
        raise RepeatabilityError(
            "repeatability TDOA input must contain exactly six unique pairs "
            "with three values each"
        )
    return {
        pair: max(float(value) for value in all_pairs[pair])
        - min(float(value) for value in all_pairs[pair])
        for pair in PAIR_IDS
    }


def diagnose(args: argparse.Namespace) -> dict[str, Any]:
    root = _campaign_root(args.campaign_root)
    manifest = _load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign(manifest)
    diagnostic_head = _require_bound_source_state()
    records = _ledger(root / "attempt_ledger.jsonl")
    _validate_ledger(records, manifest)
    if len(records) != TAKE_COUNT or any(
        record["decision"] != "PASS" for record in records
    ):
        raise RepeatabilityError("diagnostic requires exactly three passing takes")
    output = root / "diagnostics/reduced_repeatability_v2"
    if output.exists():
        raise RepeatabilityError(f"refusing to overwrite diagnostic root: {output}")
    prior_output = root / "diagnostics/reduced_repeatability_v1"
    prior_report = prior_output / "repeatability_report.json"
    prior_package = prior_output / "package_manifest.json"
    if not prior_report.is_file() or not prior_package.is_file():
        raise RepeatabilityError("preserved v1 diagnostic is required before v2")
    output.mkdir(parents=True)
    registry = acceptance_criteria_corrective_03.build_identity_registry(ROOT)
    identities = sorted(
        (
            identity
            for identity in registry.values()
            if identity.stratum_id == "A_controlled_boundary_sweep"
            and identity.target_bearing_deg_f_project == TARGET_BEARING_DEG
        ),
        key=lambda identity: identity.planned_take_id,
    )
    if len(identities) != TAKE_COUNT:
        raise RepeatabilityError("current S4.8 registry lacks three 22.5-degree cells")
    profile = s4_8._profile_runtime(ROOT)
    take_results = []
    replay_results = []
    all_pairs: dict[str, list[float]] = {}
    for take, identity, record in zip(
        manifest["takes"], identities, records, strict=True
    ):
        first = _current_pipeline_analysis(
            campaign_root=root,
            take=take,
            identity=identity,
            profile=profile,
        )
        second = _current_pipeline_analysis(
            campaign_root=root,
            take=take,
            identity=identity,
            profile=profile,
        )
        replay_pass = (
            first["status"] == "PASS"
            and second["status"] == "PASS"
            and first["scientific_replay_sha256"]
            == second["scientific_replay_sha256"]
        )
        first["deterministic_replay"] = replay_pass
        _write_new_json(output / f"{take['take_id']}.analysis.json", first)
        pair_medians = {
            str(item["pair_id"]): float(item["tdoa_us"])
            for item in first["derived"]["tdoa"]
        }
        for pair, value in pair_medians.items():
            all_pairs.setdefault(pair, []).append(value)
        channels = first["derived"]["channels"]
        take_results.append(
            {
                "take_number": take["take_number"],
                "take_id": take["take_id"],
                "analysis_status": first["status"],
                "bearing_deg": first["derived"][
                    "estimated_bearing_deg_f_project"
                ],
                "bearing_error_deg": first["derived"][
                    "bearing_absolute_error_deg"
                ],
                "confidence": first["confidence"],
                "abstained_window_count": first["derived"]["window_summary"][
                    "abstained_window_count"
                ],
                "window_count": first["derived"]["window_summary"][
                    "source_window_count"
                ],
                "abstention_rate": first["abstention_rate"],
                "tdoa_median_us": pair_medians,
                "capture_sha256": first["capture_sha256"],
                "capture_hash_matches_ledger": (
                    record["artifact_sha256"].get("respeaker_audio.wav")
                    == first["capture_sha256"]
                ),
                "channel_integrity": channels,
                "channel_health_failure_count": sum(
                    bool(channel["health_failure"]) for channel in channels
                ),
                "acquisition_gate": record["decision"],
                "deterministic_replay": replay_pass,
                "scientific_replay_sha256": first[
                    "scientific_replay_sha256"
                ],
            }
        )
        replay_results.append(
            {
                "take_id": take["take_id"],
                "status": "PASS" if replay_pass else "FAIL",
                "first_scientific_replay_sha256": first[
                    "scientific_replay_sha256"
                ],
                "second_scientific_replay_sha256": second[
                    "scientific_replay_sha256"
                ],
            }
        )
    bearings = [float(item["bearing_deg"]) for item in take_results]
    errors = [float(item["bearing_error_deg"]) for item in take_results]
    bearing_range = _circular_range(bearings)
    pair_ranges = _unique_pair_ranges(all_pairs)
    bearing_limit = float(manifest["limits"]["bearing_circular_range_deg_max"])
    tdoa_limit = float(manifest["limits"]["pair_tdoa_median_range_us_max"])
    checks = {
        "three_authenticated_passes": all(
            record["decision"] == "PASS" for record in records
        ),
        "three_current_pipeline_analyses": all(
            item["analysis_status"] == "PASS" for item in take_results
        ),
        "bearing_circular_range": bearing_range is not None
        and bearing_range <= bearing_limit,
        "six_pair_tdoa_ranges": len(pair_ranges) == 6
        and all(value <= tdoa_limit for value in pair_ranges.values()),
        "capture_and_channel_integrity": all(
            item["capture_hash_matches_ledger"]
            and item["channel_health_failure_count"] == 0
            and item["acquisition_gate"] == "PASS"
            for item in take_results
        ),
        "deterministic_scientific_replay": all(
            item["deterministic_replay"] for item in take_results
        ),
    }
    accuracy_limits = _accuracy_thresholds()
    sorted_errors = sorted(errors)
    accuracy_observed = {
        "median": float(statistics.median(errors)),
        "p95_nearest_rank": sorted_errors[
            max(0, math.ceil(0.95 * len(sorted_errors)) - 1)
        ],
        "worst": max(errors),
    }
    accuracy_checks = {
        key: accuracy_observed[key] <= limit
        for key, limit in accuracy_limits.items()
    }
    report_payload = {
        "schema": "ias.s4_8.reduced_repeatability_diagnostic.v2",
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "acquisition_code_head": manifest["code_head"],
        "diagnostic_code_head": diagnostic_head,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "target": {
            "bearing_deg_f_project": TARGET_BEARING_DEG,
            "radius_m": TARGET_RADIUS_M,
            "playback_gain": PLAYBACK_GAIN,
        },
        "take_results": take_results,
        "bearing_circular_range_deg": bearing_range,
        "bearing_circular_range_limit_deg": bearing_limit,
        "pair_tdoa_median_range_us": pair_ranges,
        "pair_tdoa_median_range_limit_us": tdoa_limit,
        "checks": checks,
        "bearing_accuracy_context": {
            "observed_deg": accuracy_observed,
            "current_stratum_a_limits_deg": accuracy_limits,
            "checks": accuracy_checks,
            "gating_in_reduced_repeatability_verdict": False,
        },
        "deterministic_replay": replay_results,
        "corrects_preserved_diagnostic": {
            "version": "v1",
            "report_path": prior_report.relative_to(root).as_posix(),
            "report_sha256": _sha256(prior_report),
            "package_path": prior_package.relative_to(root).as_posix(),
            "package_sha256": _sha256(prior_package),
            "correction": (
                "replace legacy S4.3 geometry with current S4.8 profile "
                "application and restrict TDOA to six unique microphone pairs"
            ),
        },
        "diagnostic_source_files_sha256": {
            path: _sha256(ROOT / path) for path in SOURCE_PATHS
        },
        "profile_canonical_sha256": canonical_sha256(profile),
        "classification": dict(CLASSIFICATION),
        "full_s4_8_pass_claimed": False,
        "authority": dict(AUTHORITY_NONE),
    }
    report = {
        **report_payload,
        "report_sha256": canonical_sha256(report_payload),
    }
    _write_new_json(output / "repeatability_report.json", report)
    package_files = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and output not in path.parents
            and path.name != "package_manifest.json"
        ):
            package_files[path.relative_to(root).as_posix()] = _sha256(path)
    for path in sorted(output.glob("*.analysis.json")):
        package_files[path.relative_to(root).as_posix()] = _sha256(path)
    report_relative = (
        "diagnostics/reduced_repeatability_v2/repeatability_report.json"
    )
    package_files[report_relative] = _sha256(output / "repeatability_report.json")
    package_payload = {
        "schema": "ias.s4_8.reduced_repeatability_package.v2",
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "repeatability_report_sha256": report["report_sha256"],
        "files_sha256": package_files,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    package = {
        **package_payload,
        "package_sha256": canonical_sha256(package_payload),
    }
    _write_new_json(output / "package_manifest.json", package)
    checksum_lines = [
        f"{digest}  {relative}\n" for relative, digest in sorted(package_files.items())
    ]
    checksum_lines.append(
        f"{_sha256(output / 'package_manifest.json')}  "
        "diagnostics/reduced_repeatability_v2/package_manifest.json\n"
    )
    (output / "SHA256SUMS").write_text("".join(checksum_lines), encoding="utf-8")
    authenticated = all(
        _sha256(root / path) == digest
        for path, digest in package_files.items()
    )
    return {
        "status": report["status"] if authenticated else "FAIL",
        "report": str(output / "repeatability_report.json"),
        "package": str(output / "package_manifest.json"),
        "package_sha256": package["package_sha256"],
        "package_authenticated": authenticated,
        "classification": dict(CLASSIFICATION),
        "full_s4_8_pass_claimed": False,
        "authority": dict(AUTHORITY_NONE),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_CAMPAIGN_ROOT)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--preflight-report", type=Path, required=True)
    prepare_parser.set_defaults(function=prepare)
    take_parser = subparsers.add_parser("run-take")
    take_parser.add_argument(
        "--take-number", type=int, choices=(1, 2, 3), required=True
    )
    take_parser.set_defaults(function=run_take)
    diagnose_parser = subparsers.add_parser("diagnose")
    diagnose_parser.set_defaults(function=diagnose)
    args = parser.parse_args()
    try:
        result = args.function(args)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        RepeatabilityError,
        S48EngineeringAcquisitionError,
        S48PhysicalBackendError,
        S48PresealingGateError,
    ) as exc:
        print(f"S4.8 repeatability workflow failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    terminal = result.get("decision", result.get("status"))
    return 0 if terminal in {"PASS", "prepared"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
