#!/usr/bin/env python3
"""Run the additive engineering-only S4.8 0/0/45/45 bias diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.acquisition.s4_3 import load_pilot_configuration
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

try:
    from scripts import run_s4_8_repeatability_diagnostic as repeatability
except ModuleNotFoundError:
    import run_s4_8_repeatability_diagnostic as repeatability

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = (ROOT / ".local" / "s4_8").resolve()
DEFAULT_CONFIG = ROOT / "configs/s4_8_engineering_campaign.v1.json"
DEFAULT_CAMPAIGN_ROOT = LOCAL_ROOT / "s4_8_bias_disambiguation_0_45_v1"
PILOT_CONFIG = ROOT / "configs/s4_3_pilot.v1.json"
REFERENCE_PATH = (
    ROOT
    / "outputs/isaac_audio_sensors/S4/S4.2/reference/"
    "s4_2_reference_v1.0.0.wav"
)
SCHEMA = "ias.s4_8.bias_disambiguation_campaign.v1"
LEDGER_SCHEMA = "ias.s4_8.bias_disambiguation_ledger_record.v1"
AUTHORIZATION_SCHEMA = "ias.s4_8.bias_disambiguation_take_authorization.v1"
TAKE_BEARINGS_DEG = (0.0, 0.0, 45.0, 45.0)
TARGET_RADIUS_M = 0.8
PLAYBACK_GAIN = 0.75
CONTROLLER_SOURCE_PATH = "scripts/run_s4_8_bias_disambiguation.py"
PROTOCOL_ID_PREFIX = "s4_8_additive_bias_disambiguation_0_45_v1"
PI_REMOTE_CAMPAIGN_NAME = "bias_disambiguation_0_45_v1"
SOURCE_PATHS = (
    "configs/s4_3_pilot.v1.json",
    "configs/s4_6_profile_application.v1.json",
    "configs/s4_8_engineering_campaign.v1.json",
    "configs/s4_8_presealing_gate.v2.json",
    "docs/schemas/s4_8_presealing_gate_config.v2.schema.json",
    "scripts/run_s4_8_bias_disambiguation.py",
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
)
AUTHORITY_NONE = dict(repeatability.AUTHORITY_NONE)
CLASSIFICATION = {
    **repeatability.CLASSIFICATION,
    "bias_disambiguation_only": True,
}


class BiasDisambiguationError(RuntimeError):
    """Fail-closed bias-disambiguation workflow error."""


class EngineeringIdentity:
    def __init__(
        self,
        *,
        planned_take_id: str,
        stratum_id: str,
        duration_s: int,
        target_bearing_deg_f_project: float,
        repetition: int,
    ) -> None:
        self.planned_take_id = planned_take_id
        self.stratum_id = stratum_id
        self.duration_s = duration_s
        self.target_bearing_deg_f_project = target_bearing_deg_f_project
        self.repetition = repetition

    def payload_identity(self) -> dict[str, Any]:
        return {
            "planned_take_id": self.planned_take_id,
            "condition_id": self.planned_take_id,
            "group_id": f"bias_disambiguation|{self.target_bearing_deg_f_project}",
            "stratum_id": self.stratum_id,
            "bearing_cell_id": (
                f"{self.stratum_id}|{self.target_bearing_deg_f_project}"
            ),
            "target_bearing_deg_f_project": self.target_bearing_deg_f_project,
            "repetition": self.repetition,
            "paired_counterpart_take_id": None,
        }


def _take_definitions() -> list[dict[str, Any]]:
    takes = []
    repetitions: dict[float, int] = {}
    for number, bearing in enumerate(TAKE_BEARINGS_DEG, start=1):
        repetitions[bearing] = repetitions.get(bearing, 0) + 1
        angle = math.radians(bearing)
        takes.append(
            {
                "take_number": number,
                "take_id": (
                    f"s48eng_bias_{int(bearing):03d}_take_"
                    f"{repetitions[bearing]:02d}"
                ),
                "duration_s": 20,
                "source_frame": "F_project",
                "source_bearing_deg": bearing,
                "source_radius_m": TARGET_RADIUS_M,
                "source_xy_m": [
                    TARGET_RADIUS_M * math.cos(angle),
                    TARGET_RADIUS_M * math.sin(angle),
                ],
                "playback_gain": PLAYBACK_GAIN,
                "reference_wav_sha256": repeatability._sha256(REFERENCE_PATH),
                "independent_recording": True,
                "rig_fixed": True,
                "mac_heading_fixed": True,
                "mac_removal_and_exact_reposition_before_take": number > 1,
                "new_explicit_authorization_required": True,
            }
        )
    return takes


def _campaign_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != DEFAULT_CAMPAIGN_ROOT:
        raise BiasDisambiguationError(
            "bias-disambiguation campaign root must use the fixed additive path"
        )
    return resolved


def _require_bound_source_state(expected_head: str | None = None) -> str:
    head = repeatability._git_head()
    changed = subprocess.run(
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
    if changed.returncode != 0 or untracked.stdout.strip():
        raise BiasDisambiguationError(
            "bias controller or scientific dependencies are not committed"
        )
    if expected_head is not None and head != expected_head:
        raise BiasDisambiguationError(
            "repository HEAD differs from the campaign binding"
        )
    return head


def _require_additive_controller_state(
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    head = _require_bound_source_state()
    source_hashes = manifest["source_files_sha256"]
    for path in SOURCE_PATHS:
        if path == CONTROLLER_SOURCE_PATH:
            continue
        if repeatability._sha256(ROOT / path) != source_hashes[path]:
            raise BiasDisambiguationError(
                f"scientific campaign source changed after freeze: {path}"
            )
    return head, repeatability._sha256(ROOT / CONTROLLER_SOURCE_PATH)


def _validate_campaign(manifest: Mapping[str, Any]) -> None:
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("campaign_id") != DEFAULT_CAMPAIGN_ROOT.name
        or manifest.get("classification") != CLASSIFICATION
        or manifest.get("authority") != AUTHORITY_NONE
        or manifest.get("take_count") != len(TAKE_BEARINGS_DEG)
        or manifest.get("takes") != _take_definitions()
        or manifest.get("authorization_policy")
        != {
            "automatic_continuation_forbidden": True,
            "explicit_authorization_required_before_each_take": True,
            "authorized_take_numbers": [1],
        }
    ):
        raise BiasDisambiguationError("campaign manifest identity or scope is invalid")


def _ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _validate_ledger(
    records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> None:
    previous = str(manifest["manifest_sha256"])
    for sequence, record in enumerate(records):
        payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if (
            record.get("schema") != LEDGER_SCHEMA
            or record.get("sequence") != sequence
            or record.get("take_number") != sequence + 1
            or record.get("take_id") != manifest["takes"][sequence]["take_id"]
            or record.get("campaign_manifest_sha256")
            != manifest["manifest_sha256"]
            or record.get("previous_record_sha256") != previous
            or record.get("decision") not in {"PASS", "RETRY_REQUIRED"}
            or record.get("record_sha256") != canonical_sha256(payload)
            or (
                sequence == 0
                and "authorization_sha256" in record
            )
            or (
                sequence > 0
                and not isinstance(record.get("authorization_sha256"), str)
            )
        ):
            raise BiasDisambiguationError("bias-disambiguation ledger is invalid")
        previous = str(record["record_sha256"])


def _authorization_path(root: Path, take_number: int) -> Path:
    return root / "authorizations" / f"take_{take_number:02d}.json"


def _validate_authorization(
    authorization: Mapping[str, Any],
    manifest: Mapping[str, Any],
    prior_records: Sequence[Mapping[str, Any]],
    take_number: int,
) -> None:
    payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_sha256"
    }
    take = manifest["takes"][take_number - 1]
    expected_previous = (
        manifest["manifest_sha256"]
        if not prior_records
        else prior_records[-1]["record_sha256"]
    )
    if (
        authorization.get("schema") != AUTHORIZATION_SCHEMA
        or authorization.get("campaign_manifest_sha256")
        != manifest["manifest_sha256"]
        or authorization.get("base_code_head") != manifest["code_head"]
        or authorization.get("take_number") != take_number
        or authorization.get("take_id") != take["take_id"]
        or authorization.get("target_bearing_deg_f_project")
        != take["source_bearing_deg"]
        or authorization.get("previous_record_sha256") != expected_previous
        or authorization.get("scope") != "single_engineering_take_only"
        or authorization.get("automatic_continuation_authorized") is not False
        or authorization.get("retry_authorized") is not False
        or authorization.get("classification") != CLASSIFICATION
        or authorization.get("authority") != AUTHORITY_NONE
        or not isinstance(authorization.get("controller_head"), str)
        or not isinstance(authorization.get("controller_source_sha256"), str)
        or authorization.get("authorization_sha256")
        != canonical_sha256(payload)
    ):
        raise BiasDisambiguationError("take authorization is invalid")


def _load_authorization(
    root: Path,
    manifest: Mapping[str, Any],
    prior_records: Sequence[Mapping[str, Any]],
    take_number: int,
) -> dict[str, Any] | None:
    if take_number == 1:
        if take_number not in manifest["authorization_policy"][
            "authorized_take_numbers"
        ]:
            raise BiasDisambiguationError(
                "requested take lacks baseline authorization"
            )
        _require_bound_source_state(str(manifest["code_head"]))
        return None
    path = _authorization_path(root, take_number)
    if not path.is_file():
        raise BiasDisambiguationError(
            "requested take lacks an additive explicit authorization"
        )
    authorization = repeatability._load_json(path)
    _validate_authorization(
        authorization, manifest, prior_records, take_number
    )
    head, controller_sha256 = _require_additive_controller_state(manifest)
    if (
        authorization["controller_head"] != head
        or authorization["controller_source_sha256"] != controller_sha256
    ):
        raise BiasDisambiguationError(
            "take authorization does not bind the active controller"
        )
    return authorization


def authorize_take(args: argparse.Namespace) -> dict[str, Any]:
    root = _campaign_root(args.campaign_root)
    manifest = repeatability._load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign(manifest)
    records = _ledger(root / "attempt_ledger.jsonl")
    _validate_ledger(records, manifest)
    if args.take_number == 1:
        raise BiasDisambiguationError(
            "Take 1 authorization is frozen in the campaign manifest"
        )
    if args.take_number != len(records) + 1:
        raise BiasDisambiguationError(
            "authorization is permitted only for the exact next take"
        )
    if any(record["decision"] != "PASS" for record in records):
        raise BiasDisambiguationError("a prior take requires operator review")
    path = _authorization_path(root, args.take_number)
    if path.exists():
        raise BiasDisambiguationError(f"refusing to overwrite {path}")
    head, controller_sha256 = _require_additive_controller_state(manifest)
    take = manifest["takes"][args.take_number - 1]
    payload = {
        "schema": AUTHORIZATION_SCHEMA,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "base_code_head": manifest["code_head"],
        "controller_head": head,
        "controller_source_sha256": controller_sha256,
        "take_number": args.take_number,
        "take_id": take["take_id"],
        "target_bearing_deg_f_project": take["source_bearing_deg"],
        "previous_record_sha256": records[-1]["record_sha256"],
        "scope": "single_engineering_take_only",
        "automatic_continuation_authorized": False,
        "retry_authorized": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    authorization = {
        **payload,
        "authorization_sha256": canonical_sha256(payload),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    repeatability._write_new_json(path, authorization)
    return {
        "status": "authorized",
        "take_number": args.take_number,
        "take_id": take["take_id"],
        "authorization": str(path),
        "authorization_sha256": authorization["authorization_sha256"],
        "automatic_continuation_authorized": False,
        "retry_authorized": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    config = repeatability._load_json(args.config.resolve())
    gate = load_presealing_config_v2(ROOT)
    pilot = load_pilot_configuration(PILOT_CONFIG, repo_root=ROOT)
    head = _require_bound_source_state()
    root = _campaign_root(args.campaign_root)
    if root.exists():
        raise BiasDisambiguationError(f"refusing to reuse campaign root: {root}")
    preflight = repeatability._load_json(args.preflight_report.resolve())
    repeatability._validate_preflight(preflight)
    freeze = root / "freeze"
    freeze.mkdir(parents=True)
    preflight_copy = freeze / "preflight_report.json"
    shutil.copyfile(args.preflight_report.resolve(), preflight_copy)
    archive = freeze / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    payload = {
        "schema": SCHEMA,
        "campaign_id": root.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_head": head,
        "source_archive_sha256": repeatability._sha256(archive),
        "source_files_sha256": {
            path: repeatability._sha256(ROOT / path) for path in SOURCE_PATHS
        },
        "preflight_report_sha256": repeatability._sha256(preflight_copy),
        "reference_wav_sha256": repeatability._sha256(REFERENCE_PATH),
        "continuous_asset_sha256": preflight["continuous_asset"]["asset_sha256"],
        "gate_configuration_sha256": canonical_sha256(gate),
        "detector_configuration_sha256": canonical_sha256(gate["detector"]),
        "analysis_configuration_sha256": canonical_sha256(pilot),
        "device_profile_id": config["respeaker"]["profile_id"],
        "channel_map": config["channel_map"],
        "take_count": len(TAKE_BEARINGS_DEG),
        "takes": _take_definitions(),
        "authorization_policy": {
            "automatic_continuation_forbidden": True,
            "explicit_authorization_required_before_each_take": True,
            "authorized_take_numbers": [1],
        },
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    manifest = {**payload, "manifest_sha256": canonical_sha256(payload)}
    repeatability._write_new_json(freeze / "campaign_manifest.json", manifest)
    return {
        "status": "prepared",
        "campaign_root": str(root),
        "manifest_sha256": manifest["manifest_sha256"],
        "authorized_take_numbers": [1],
        "acquisition_started": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def run_take(args: argparse.Namespace) -> dict[str, Any]:
    root = _campaign_root(args.campaign_root)
    manifest = repeatability._load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign(manifest)
    config = repeatability._load_json(args.config.resolve())
    ledger_path = root / "attempt_ledger.jsonl"
    records = _ledger(ledger_path)
    _validate_ledger(records, manifest)
    if args.take_number != len(records) + 1:
        raise BiasDisambiguationError("requested take is not the exact next take")
    if any(record["decision"] != "PASS" for record in records):
        raise BiasDisambiguationError("a prior take requires operator review")
    authorization = _load_authorization(
        root, manifest, records, args.take_number
    )
    take = manifest["takes"][args.take_number - 1]
    attempt_root = root / "takes" / take["take_id"]
    if attempt_root.exists():
        raise BiasDisambiguationError(f"take root already exists: {attempt_root}")
    attempt_root.mkdir(parents=True)
    take_sha256 = canonical_sha256(take)
    precollection = build_engineering_precollection_manifest(
        code_head=str(manifest["code_head"]),
        environment_identity=(
            f"campaign:{manifest['manifest_sha256']}:"
            f"preflight:{manifest['preflight_report_sha256']}:"
            f"take:{take_sha256}"
        ),
        reference_wav_sha256=str(manifest["reference_wav_sha256"]),
        gate_configuration_sha256=str(manifest["gate_configuration_sha256"]),
        detector_configuration_sha256=str(
            manifest["detector_configuration_sha256"]
        ),
        device_profile_id=str(manifest["device_profile_id"]),
        channel_map=manifest["channel_map"],
        protocol_id=(
            f"{PROTOCOL_ID_PREFIX}:"
            f"{manifest['manifest_sha256']}:{take_sha256}"
        ),
        capture_controller_identity=str(config["controller"]["identity"]),
        capture_controller_version=str(config["controller"]["version"]),
    )
    repeatability._write_new_json(attempt_root / "take_definition.json", take)
    repeatability._write_new_json(
        attempt_root / "take_precollection_manifest.json", precollection
    )
    backend = RemotePhysicalEngineeringBackend(
        pi_ssh_prefix=config["respeaker"]["ssh_prefix"],
        pi_scp_prefix=config["respeaker"]["scp_prefix"],
        pi_scp_target=config["respeaker"]["scp_target"],
        pi_helper_path=config["respeaker"]["helper_path"],
        pi_remote_attempt=(
            f"S4.8/{PI_REMOTE_CAMPAIGN_NAME}/"
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
        repeatability._write_new_json(
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
    repeatability._write_new_json(
        attempt_root / "gate_report.json", result["report"]
    )
    if result["clearance"] is not None:
        repeatability._write_new_json(
            attempt_root / "candidate_clearance.json", result["clearance"]
        )
    repeatability._write_new_json(
        attempt_root / "controller_result.json",
        {
            **result,
            "take": take,
            "classification": dict(CLASSIFICATION),
            "authority": dict(AUTHORITY_NONE),
        },
    )
    artifact_hashes = {
        path.name: repeatability._sha256(path)
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
    if authorization is not None:
        payload["authorization_sha256"] = authorization[
            "authorization_sha256"
        ]
    record = {**payload, "record_sha256": canonical_sha256(payload)}
    repeatability._append_json_line(ledger_path, record)
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


def analyze_take(args: argparse.Namespace) -> dict[str, Any]:
    root = _campaign_root(args.campaign_root)
    manifest = repeatability._load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign(manifest)
    records = _ledger(root / "attempt_ledger.jsonl")
    _validate_ledger(records, manifest)
    if args.take_number > len(records):
        raise BiasDisambiguationError("requested take has not been acquired")
    record = records[args.take_number - 1]
    if record["decision"] != "PASS":
        raise BiasDisambiguationError("scientific analysis requires a passing gate")
    authorization = _load_authorization(
        root, manifest, records[: args.take_number - 1], args.take_number
    )
    if (
        authorization is not None
        and record.get("authorization_sha256")
        != authorization["authorization_sha256"]
    ):
        raise BiasDisambiguationError(
            "take ledger does not bind the additive authorization"
        )
    take = manifest["takes"][args.take_number - 1]
    identity = EngineeringIdentity(
        planned_take_id=str(take["take_id"]),
        stratum_id="A_controlled_boundary_sweep",
        duration_s=int(take["duration_s"]),
        target_bearing_deg_f_project=float(take["source_bearing_deg"]),
        repetition=(
            1
            + sum(
                prior["source_bearing_deg"] == take["source_bearing_deg"]
                for prior in manifest["takes"][: args.take_number - 1]
            )
        ),
    )
    profile = s4_8._profile_runtime(ROOT)
    first = repeatability._current_pipeline_analysis(
        campaign_root=root,
        take=take,
        identity=identity,
        profile=profile,
    )
    second = repeatability._current_pipeline_analysis(
        campaign_root=root,
        take=take,
        identity=identity,
        profile=profile,
    )
    deterministic = (
        first["status"] == "PASS"
        and second["status"] == "PASS"
        and first["scientific_replay_sha256"]
        == second["scientific_replay_sha256"]
    )
    output = root / "diagnostics" / f"take_{args.take_number:02d}_analysis_v1"
    if output.exists():
        raise BiasDisambiguationError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    first["deterministic_replay"] = deterministic
    repeatability._write_new_json(output / "analysis.json", first)
    pair_tdoa = {
        str(item["pair_id"]): {
            "observed_us": float(item["tdoa_us"]),
            "expected_us": float(item["reference_tdoa_us"]),
            "absolute_error_us": float(item["absolute_error_us"]),
        }
        for item in first["derived"]["tdoa"]
    }
    payload = {
        "schema": "ias.s4_8.bias_disambiguation_take_analysis.v1",
        "status": "PASS" if deterministic else "FAIL",
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "take_number": args.take_number,
        "take_id": take["take_id"],
        "target_bearing_deg_f_project": take["source_bearing_deg"],
        "estimated_bearing_deg_f_project": first["derived"][
            "estimated_bearing_deg_f_project"
        ],
        "bearing_absolute_error_deg": first["derived"][
            "bearing_absolute_error_deg"
        ],
        "window_summary": first["derived"]["window_summary"],
        "channel_integrity": first["derived"]["channels"],
        "pair_tdoa": pair_tdoa,
        "confidence": first["confidence"],
        "capture_sha256": first["capture_sha256"],
        "capture_hash_matches_ledger": (
            first["capture_sha256"]
            == record["artifact_sha256"]["respeaker_audio.wav"]
        ),
        "scientific_replay_sha256": first["scientific_replay_sha256"],
        "deterministic_replay": deterministic,
        "profile_canonical_sha256": canonical_sha256(profile),
        "authorization_sha256": (
            None
            if authorization is None
            else authorization["authorization_sha256"]
        ),
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    report = {**payload, "report_sha256": canonical_sha256(payload)}
    repeatability._write_new_json(output / "report.json", report)
    files = {
        path.name: repeatability._sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    package_payload = {
        "schema": "ias.s4_8.bias_disambiguation_take_package.v1",
        "report_sha256": report["report_sha256"],
        "files_sha256": files,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    package = {
        **package_payload,
        "package_sha256": canonical_sha256(package_payload),
    }
    repeatability._write_new_json(output / "package_manifest.json", package)
    return {
        "status": report["status"],
        "report": str(output / "report.json"),
        "package": str(output / "package_manifest.json"),
        "package_sha256": package["package_sha256"],
        "estimated_bearing_deg_f_project": report[
            "estimated_bearing_deg_f_project"
        ],
        "bearing_absolute_error_deg": report["bearing_absolute_error_deg"],
        "deterministic_replay": deterministic,
        "capture_hash_matches_ledger": report["capture_hash_matches_ledger"],
        "classification": dict(CLASSIFICATION),
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
    authorization_parser = subparsers.add_parser("authorize-take")
    authorization_parser.add_argument(
        "--take-number", type=int, choices=(2, 3, 4), required=True
    )
    authorization_parser.set_defaults(function=authorize_take)
    take_parser = subparsers.add_parser("run-take")
    take_parser.add_argument(
        "--take-number", type=int, choices=(1, 2, 3, 4), required=True
    )
    take_parser.set_defaults(function=run_take)
    analysis_parser = subparsers.add_parser("analyze-take")
    analysis_parser.add_argument(
        "--take-number", type=int, choices=(1, 2, 3, 4), required=True
    )
    analysis_parser.set_defaults(function=analyze_take)
    args = parser.parse_args()
    try:
        result = args.function(args)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        BiasDisambiguationError,
        repeatability.RepeatabilityError,
        S48EngineeringAcquisitionError,
        S48PhysicalBackendError,
        S48PresealingGateError,
    ) as exc:
        print(f"S4.8 bias-disambiguation workflow failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    terminal = result.get("decision", result.get("status"))
    return 0 if terminal in {"PASS", "prepared", "authorized", "complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
