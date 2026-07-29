#!/usr/bin/env python3
"""Freeze, preflight, and run the supported physical S4.8 rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    run_supported_engineering_acquisition,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_campaign import (
    S48EngineeringCampaignError,
    append_attempt_ledger_record,
    build_reference_take_manifest,
    build_stratum_aware_campaign_manifest,
    derive_stratum_aware_design,
    run_supported_nonreference_acquisition,
    validate_attempt_ledger,
    validate_attempt_request,
    validate_campaign_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_physical_backend import (
    RemotePhysicalEngineeringBackend,
    S48PhysicalBackendError,
    build_continuous_playback_asset,
    evaluate_mac_preflight_acceptance,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    S48PresealingGateError,
    load_presealing_config_v2,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_8_engineering_campaign.v1.json"
SOURCE_PATHS = (
    "configs/s4_8_engineering_campaign.v1.json",
    "docs/development/specs/s4_8_engineering_campaign.md",
    "docs/development/specs/s4_8_presealing_gate_v2.md",
    "docs/schemas/s4_8_presealing_gate_report.v2.schema.json",
    "scripts/run_s4_8_physical_rehearsal.py",
    "scripts/s4_8_mac_playback.py",
    "scripts/s4_2_pi_capture.py",
    "scripts/s4_2_mac_preflight.py",
    "scripts/preflight_s4_2_zed.py",
    "scripts/run_s4_2_zed_capture.py",
    "scripts/validate_s4_2_zed_svo.py",
    "src/isaac_audio_sensors/acquisition/s4_8_engineering_acquisition.py",
    "src/isaac_audio_sensors/acquisition/s4_8_engineering_campaign.py",
    "src/isaac_audio_sensors/acquisition/s4_8_physical_backend.py",
    "src/isaac_audio_sensors/acquisition/s4_8_presealing_gate_v2.py",
)


class S48PhysicalRehearsalError(RuntimeError):
    """Top-level physical rehearsal command failure."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S48PhysicalRehearsalError(f"JSON read failure for {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S48PhysicalRehearsalError(f"JSON object required: {path}")
    return value


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise S48PhysicalRehearsalError(f"refusing to overwrite {path}") from exc


def _run(command: list[str], *, timeout: float) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _command_json(
    observation: dict[str, Any],
    label: str,
    *,
    require_success: bool = True,
) -> dict[str, Any]:
    if require_success and observation["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            f"{label} failed ({observation['return_code']}): "
            f"{observation['stderr'].strip()}"
        )
    try:
        payload = json.loads(observation["stdout"])
    except json.JSONDecodeError as exc:
        raise S48PhysicalRehearsalError(
            f"{label} did not return one JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise S48PhysicalRehearsalError(f"{label} JSON must be an object")
    return payload


def _config(path: Path) -> dict[str, Any]:
    config = _load_json(path.resolve())
    if (
        config.get("schema") != "ias.s4_8.engineering_campaign_config.v1"
        or config.get("authority")
        != {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
        }
    ):
        raise S48PhysicalRehearsalError("engineering campaign config is invalid")
    for section, key in (("template", "path"), ("reference", "local_path")):
        target = ROOT / config[section][key]
        if _sha256(target) != config[section]["sha256"]:
            raise S48PhysicalRehearsalError(
                f"{section} file contradicts the campaign config"
            )
    helper_path = ROOT / config["playback"]["playback_helper_local_path"]
    if _sha256(helper_path) != config["playback"]["playback_helper_sha256"]:
        raise S48PhysicalRehearsalError(
            "Mac playback helper contradicts the campaign config"
        )
    gate = load_presealing_config_v2(ROOT)
    if (
        canonical_sha256(gate)
        != config["gate"]["configuration_canonical_sha256"]
        or canonical_sha256(gate["detector"])
        != config["gate"]["detector_canonical_sha256"]
    ):
        raise S48PhysicalRehearsalError(
            "v2 gate or detector configuration hash mismatch"
        )
    return config


def _deploy_continuous_asset(
    config: dict[str, Any],
    *,
    local_asset_path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    return _deploy_mac_file(
        config,
        local_path=local_asset_path,
        remote_path=config["reference"]["continuous_asset_mac_path"],
        expected_sha256=expected_sha256,
        label="continuous playback asset",
    )


def _deploy_mac_file(
    config: dict[str, Any],
    *,
    local_path: Path,
    remote_path: str,
    expected_sha256: str,
    label: str,
) -> dict[str, Any]:
    playback = config["playback"]
    remote_parent = str(Path(remote_path).parent)
    mkdir = _run(
        [*playback["ssh_prefix"], "/bin/mkdir", "-p", remote_parent],
        timeout=30,
    )
    if mkdir["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            f"Mac {label} directory creation failed: {mkdir['stderr'].strip()}"
        )
    existing = _run(
        [*playback["ssh_prefix"], "/usr/bin/shasum", "-a", "256", remote_path],
        timeout=30,
    )
    if existing["return_code"] == 0:
        observed = existing["stdout"].split()[0]
        if observed != expected_sha256:
            raise S48PhysicalRehearsalError(
                f"existing Mac {label} has a different hash"
            )
        return {"action": "verified_existing", "sha256": observed}
    transfer = _run(
        [
            *playback["scp_prefix"],
            str(local_path),
            f"{playback['scp_target']}:{remote_path}",
        ],
        timeout=120,
    )
    if transfer["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            f"Mac {label} transfer failed: {transfer['stderr'].strip()}"
        )
    verify = _run(
        [*playback["ssh_prefix"], "/usr/bin/shasum", "-a", "256", remote_path],
        timeout=30,
    )
    if (
        verify["return_code"] != 0
        or not verify["stdout"].split()
        or verify["stdout"].split()[0] != expected_sha256
    ):
        raise S48PhysicalRehearsalError(
            f"Mac {label} authentication failed after transfer"
        )
    return {"action": "transferred_and_verified", "sha256": expected_sha256}


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    config = _config(args.config)
    output = args.output.resolve()
    if output.exists():
        raise S48PhysicalRehearsalError(f"refusing to overwrite {output}")
    asset_path = output.with_name("continuous_reference_18s.preflight.wav")
    asset = build_continuous_playback_asset(
        reference_path=ROOT / config["reference"]["local_path"],
        output_path=asset_path,
        duration_s=float(config["reference"]["continuous_asset_duration_s"]),
    )
    deployment = _deploy_continuous_asset(
        config,
        local_asset_path=asset_path,
        expected_sha256=asset["asset_sha256"],
    )
    helper_deployment = _deploy_mac_file(
        config,
        local_path=ROOT / config["playback"]["playback_helper_local_path"],
        remote_path=config["playback"]["playback_helper_mac_path"],
        expected_sha256=config["playback"]["playback_helper_sha256"],
        label="playback helper",
    )
    pi = config["respeaker"]
    pi_observation = _run(
        [
            *pi["ssh_prefix"],
            "/usr/bin/python3",
            pi["helper_path"],
            "preflight",
            "--output-root",
            args.pi_probe_root,
            "--device",
            pi["device"],
            "--minimum-free-bytes",
            "1073741824",
        ],
        timeout=60,
    )
    pi_report = _command_json(pi_observation, "Pi/ReSpeaker preflight")
    if (
        pi_report.get("status") != "passed"
        or pi_report.get("helper_sha256") != pi["helper_sha256"]
    ):
        raise S48PhysicalRehearsalError(
            "Pi/ReSpeaker preflight failed the frozen identity contract"
        )
    playback = config["playback"]
    mac_observation = _run(
        [
            *playback["ssh_prefix"],
            "/usr/bin/python3",
            playback["mac_preflight_path"],
            "--wav",
            config["reference"]["mac_path"],
            "--expected-sha256",
            config["reference"]["sha256"],
            "--expected-volume-percent",
            str(playback["system_volume_percent"]),
        ],
        timeout=60,
    )
    mac_report = _command_json(
        mac_observation,
        "Mac playback preflight",
        require_success=False,
    )
    mac_acceptance = evaluate_mac_preflight_acceptance(
        mac_report,
        power_policy=playback["power_policy"],
        operator_work_focus_confirmed=(
            args.operator_work_focus_confirmed
        ),
    )
    zed = config["zed"]
    zed_observation = _run(
        [
            sys.executable,
            str(ROOT / "scripts/preflight_s4_2_zed.py"),
            "--expected-serial",
            zed["serial"],
            "--expected-sdk",
            zed["sdk_version_reference"],
            "--expected-camera-firmware",
            zed["camera_firmware_reference"],
            "--expected-sensor-firmware",
            zed["sensor_firmware_reference"],
            "--minimum-usb-speed-mbps",
            str(zed["minimum_usb_speed_mbps"]),
        ],
        timeout=90,
    )
    zed_report = _command_json(zed_observation, "ZED preflight")
    if zed_report.get("status") != "passed":
        raise S48PhysicalRehearsalError("ZED preflight failed")
    payload = {
        "schema": "ias.s4_8.physical_rig_preflight.v1",
        "status": "passed",
        "read_only_hardware_checks": True,
        "recorder_started": False,
        "playback_started": False,
        "zed_recording_started": False,
        "continuous_asset": asset,
        "continuous_asset_deployment": deployment,
        "playback_helper_deployment": helper_deployment,
        "pi": pi_report,
        "mac": mac_report,
        "mac_acceptance": mac_acceptance,
        "zed": zed_report,
        "authority": config["authority"],
    }
    _write_new_json(output, payload)
    return payload


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    config = _config(args.config)
    root = Path(config["operational_locations"]["campaign_root"]).resolve()
    if args.campaign_root is not None:
        root = args.campaign_root.resolve()
    if root.exists():
        raise S48PhysicalRehearsalError(
            f"refusing to reuse campaign root: {root}"
        )
    _require_clean_head()
    freeze_root = root / "freeze"
    freeze_root.mkdir(parents=True, exist_ok=False)
    preflight_copy = freeze_root / "preflight_report.json"
    shutil.copyfile(args.preflight_report.resolve(), preflight_copy)
    archive_path = freeze_root / "source.tar"
    archive = _run(
        [
            "git",
            "archive",
            "--format=tar",
            "-o",
            str(archive_path),
            "HEAD",
        ],
        timeout=120,
    )
    if archive["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            f"source archive failed: {archive['stderr'].strip()}"
        )
    asset_path = freeze_root / "continuous_reference_18s.wav"
    asset = build_continuous_playback_asset(
        reference_path=ROOT / config["reference"]["local_path"],
        output_path=asset_path,
        duration_s=float(config["reference"]["continuous_asset_duration_s"]),
    )
    deployment = _deploy_continuous_asset(
        config,
        local_asset_path=asset_path,
        expected_sha256=asset["asset_sha256"],
    )
    helper_deployment = _deploy_mac_file(
        config,
        local_path=ROOT / config["playback"]["playback_helper_local_path"],
        remote_path=config["playback"]["playback_helper_mac_path"],
        expected_sha256=config["playback"]["playback_helper_sha256"],
        label="playback helper",
    )
    source_hashes = {
        relative: _sha256(ROOT / relative) for relative in SOURCE_PATHS
    }
    dependencies = sorted(
        f"{distribution.metadata['Name']}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    )
    environment = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "dependencies": dependencies,
        "dependencies_canonical_sha256": canonical_sha256(dependencies),
        "preflight_report_sha256": _sha256(preflight_copy),
    }
    template_path = ROOT / config["template"]["path"]
    template = _load_json(template_path)
    design = derive_stratum_aware_design(template)
    protocol_path = ROOT / config["protocol"]["specification_path"]
    controller_hash = canonical_sha256(
        {
            path: source_hashes[path]
            for path in SOURCE_PATHS
            if path.endswith(
                (
                    "s4_8_engineering_acquisition.py",
                    "s4_8_engineering_campaign.py",
                    "s4_8_physical_backend.py",
                    "run_s4_8_physical_rehearsal.py",
                )
            )
        }
    )
    devices = {
        "respeaker": {
            key: config["respeaker"][key]
            for key in (
                "profile_id",
                "serial",
                "model",
                "firmware",
                "sample_rate_hz",
                "sample_format",
                "channel_count",
            )
        },
        "playback": {
            key: config["playback"][key]
            for key in (
                "model",
                "output_device",
                "channel_count",
                "nominal_sample_rate_hz",
                "system_volume_percent",
                "muted",
                "power_policy",
                "playback_helper_mac_path",
                "playback_helper_sha256",
            )
        }
        | {
            "continuous_asset_sha256": asset["asset_sha256"],
            "continuous_asset_duration_s": asset["duration_s"],
        },
        "zed": {
            "model": config["zed"]["model"],
            "serial": config["zed"]["serial"],
            "sdk_version_reference": config["zed"]["sdk_version_reference"],
            "camera_firmware_reference": config["zed"][
                "camera_firmware_reference"
            ],
            "sensor_firmware_reference": config["zed"][
                "sensor_firmware_reference"
            ],
            "resolution": config["zed"]["resolution"],
            "fps": config["zed"]["fps"],
            "depth_mode": config["zed"]["depth_mode"],
        },
    }
    head = _git_head()
    manifest = build_stratum_aware_campaign_manifest(
        code_head=head,
        source_archive_sha256=_sha256(archive_path),
        source_package_hashes=source_hashes,
        environment=environment,
        reference_wav_sha256=config["reference"]["sha256"],
        gate_configuration_sha256=config["gate"][
            "configuration_canonical_sha256"
        ],
        detector_configuration_sha256=config["gate"][
            "detector_canonical_sha256"
        ],
        controller={
            "identity": config["controller"]["identity"],
            "version": config["controller"]["version"],
            "sha256": controller_hash,
        },
        protocol={
            "identity": config["protocol"]["identity"],
            "sha256": _sha256(protocol_path),
        },
        devices=devices,
        channel_map=config["channel_map"],
        design=design,
        retry_policy=config["retry_policy"],
        operational_locations={
            "campaign_root": str(root),
            "pi_capture_root": config["operational_locations"]["pi_capture_root"],
        },
        template_manifest_sha256=_sha256(template_path),
    )
    manifest_path = freeze_root / "campaign_manifest.json"
    _write_new_json(manifest_path, manifest)
    payload = {
        "schema": "ias.s4_8.engineering_campaign_freeze.v1",
        "status": "frozen",
        "campaign_root": str(root),
        "campaign_manifest_path": str(manifest_path),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "source_archive_sha256": manifest["source_archive_sha256"],
        "preflight_report_sha256": environment["preflight_report_sha256"],
        "continuous_asset": asset,
        "continuous_asset_deployment": deployment,
        "playback_helper_deployment": helper_deployment,
        "authority": config["authority"],
    }
    _write_new_json(freeze_root / "freeze_report.json", payload)
    return payload


def run_take(args: argparse.Namespace) -> dict[str, Any]:
    config = _config(args.config)
    campaign_manifest = _load_json(args.manifest.resolve())
    anchor = str(campaign_manifest.get("manifest_sha256"))
    validate_campaign_manifest(
        campaign_manifest,
        expected_manifest_sha256=anchor,
    )
    _require_clean_head(expected_head=str(campaign_manifest["code_head"]))
    matches = [
        item
        for item in campaign_manifest["design"]
        if item["engineering_take_id"] == args.take_id
    ]
    if len(matches) != 1:
        raise S48PhysicalRehearsalError("take id is not in the frozen campaign")
    take = matches[0]
    campaign_root = Path(
        campaign_manifest["operational_locations"]["campaign_root"]
    )
    ledger_path = campaign_root / "attempt_ledger.jsonl"
    ledger = _read_json_lines(ledger_path)
    if not args.dry_run:
        validate_attempt_request(
            ledger,
            campaign_manifest=campaign_manifest,
            expected_campaign_manifest_sha256=anchor,
            take=take,
            attempt_number=args.attempt_number,
        )
    if args.dry_run:
        if args.dry_run_root is None:
            raise S48PhysicalRehearsalError("--dry-run-root is required for dry-run")
        attempt_root = args.dry_run_root.resolve()
    else:
        attempt_root = (
            campaign_root
            / "attempts"
            / take["engineering_take_id"]
            / f"{take['engineering_take_id']}__attempt_{args.attempt_number:02d}"
        )
    attempt_root.mkdir(parents=True, exist_ok=False)
    remote_attempt = (
        f"{config['respeaker']['remote_campaign_root']}/"
        f"{anchor[:16]}/{take['engineering_take_id']}"
        f"__attempt_{args.attempt_number:02d}"
        + ("__dry_run" if args.dry_run else "")
    )
    backend = RemotePhysicalEngineeringBackend(
        pi_ssh_prefix=config["respeaker"]["ssh_prefix"],
        pi_scp_prefix=config["respeaker"]["scp_prefix"],
        pi_scp_target=config["respeaker"]["scp_target"],
        pi_helper_path=config["respeaker"]["helper_path"],
        pi_remote_attempt=remote_attempt,
        pi_device=config["respeaker"]["device"],
        capture_duration_s=float(take["duration_s"]),
        mac_ssh_prefix=config["playback"]["ssh_prefix"],
        mac_playback_helper_path=config["playback"][
            "playback_helper_mac_path"
        ],
        mac_continuous_asset_path=config["reference"][
            "continuous_asset_mac_path"
        ],
        mac_continuous_asset_sha256=campaign_manifest["devices"][
            "playback"
        ]["continuous_asset_sha256"],
        playback_gain=take["playback_gain"],
        zed_helper_path=ROOT / "scripts/run_s4_2_zed_capture.py",
        zed_replay_path=ROOT / "scripts/validate_s4_2_zed_svo.py",
        expected_zed_serial=config["zed"]["serial"],
        expected_zed_sdk=config["zed"]["sdk_version_reference"],
        expected_zed_camera_firmware=config["zed"][
            "camera_firmware_reference"
        ],
        expected_zed_sensor_firmware=config["zed"][
            "sensor_firmware_reference"
        ],
    )
    capture_path = attempt_root / "respeaker_audio.wav"
    journal_path = attempt_root / "process_journal.jsonl"
    retry_path = attempt_root / "retry_report.json"
    seal_path = attempt_root / "candidate_seal.json"
    registry_path = attempt_root / "clearance_consumed.json"
    try:
        if take["acquisition_mode"] == "reference":
            take_manifest = build_reference_take_manifest(
                campaign_manifest=campaign_manifest,
                take=take,
                expected_campaign_manifest_sha256=anchor,
            )
            take_manifest_path = attempt_root / "take_precollection_manifest.json"
            _write_new_json(take_manifest_path, take_manifest)
            result = run_supported_engineering_acquisition(
                backend=backend,
                repo_root=ROOT,
                capture_path=capture_path,
                reference_path=ROOT / config["reference"]["local_path"],
                manifest=take_manifest,
                expected_manifest_sha256=take_manifest["manifest_sha256"],
                journal_path=journal_path,
                retry_report_path=retry_path,
                candidate_seal_path=seal_path,
                clearance_registry_path=registry_path,
                dry_run=args.dry_run,
            )
        else:
            result = run_supported_nonreference_acquisition(
                backend=backend,
                repo_root=ROOT,
                take=take,
                campaign_manifest=campaign_manifest,
                expected_campaign_manifest_sha256=anchor,
                capture_path=capture_path,
                zed_artifact_root=(
                    attempt_root / "zed"
                    if take["acquisition_mode"] == "impact_av"
                    else None
                ),
                journal_path=journal_path,
                retry_report_path=retry_path,
                candidate_seal_path=seal_path,
                clearance_registry_path=registry_path,
                dry_run=args.dry_run,
            )
    except BaseException as exc:
        try:
            cleanup = backend.abort()
        except Exception as cleanup_exc:  # cleanup evidence must not mask root cause
            cleanup = {
                "cleanup_error_type": type(cleanup_exc).__name__,
                "cleanup_error": str(cleanup_exc),
            }
        _write_new_json(
            attempt_root / "controller_failure.json",
            {
                "schema": "ias.s4_8.engineering_controller_failure.v1",
                "take_id": take["engineering_take_id"],
                "attempt_number": args.attempt_number,
                "dry_run": args.dry_run,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "cleanup": cleanup,
                "retained": True,
                "authority": config["authority"],
            },
        )
        raise
    _write_new_json(attempt_root / "gate_report.json", result["report"])
    if result["clearance"] is not None:
        _write_new_json(attempt_root / "candidate_clearance.json", result["clearance"])
    _write_new_json(attempt_root / "controller_result.json", result)
    if not args.dry_run:
        record = append_attempt_ledger_record(
            ledger,
            campaign_manifest_sha256=anchor,
            planned_take=take,
            attempt_number=args.attempt_number,
            decision=result["decision"],
            report_sha256=canonical_sha256(result["report"]),
            candidate_seal_sha256=(
                None
                if result["candidate_seal"] is None
                else result["candidate_seal"]["seal_sha256"]
            ),
        )
        validate_attempt_ledger(
            ledger,
            campaign_manifest=campaign_manifest,
            expected_campaign_manifest_sha256=anchor,
        )
        _append_json_line(ledger_path, record)
    return {
        "status": "complete",
        "decision": result["decision"],
        "dry_run": args.dry_run,
        "take_id": take["engineering_take_id"],
        "attempt_number": args.attempt_number,
        "attempt_root": str(attempt_root),
        "candidate_seal_sha256": (
            None
            if result["candidate_seal"] is None
            else result["candidate_seal"]["seal_sha256"]
        ),
        "authority": config["authority"],
    }


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise S48PhysicalRehearsalError("ledger line is not a JSON object")
        records.append(value)
    return records


def _append_json_line(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def _git_head() -> str:
    result = _run(["git", "rev-parse", "HEAD"], timeout=30)
    if result["return_code"] != 0:
        raise S48PhysicalRehearsalError("unable to resolve Git HEAD")
    return result["stdout"].strip()


def _require_clean_head(expected_head: str | None = None) -> None:
    head = _git_head()
    status = _run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        timeout=30,
    )
    if (
        status["return_code"] != 0
        or status["stdout"].strip()
        or (expected_head is not None and head != expected_head)
    ):
        raise S48PhysicalRehearsalError(
            "acquisition checkout is dirty or at the wrong frozen HEAD"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--output", type=Path, required=True)
    preflight_parser.add_argument("--pi-probe-root", required=True)
    preflight_parser.add_argument(
        "--operator-work-focus-confirmed",
        action="store_true",
    )
    preflight_parser.set_defaults(function=preflight)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--preflight-report", type=Path, required=True)
    freeze_parser.add_argument("--campaign-root", type=Path, default=None)
    freeze_parser.set_defaults(function=freeze)
    take_parser = subparsers.add_parser("run-take")
    take_parser.add_argument("--manifest", type=Path, required=True)
    take_parser.add_argument("--take-id", required=True)
    take_parser.add_argument(
        "--attempt-number",
        type=int,
        choices=(1, 2),
        required=True,
    )
    take_parser.add_argument("--dry-run", action="store_true")
    take_parser.add_argument("--dry-run-root", type=Path, default=None)
    take_parser.set_defaults(function=run_take)
    args = parser.parse_args()
    try:
        result = args.function(args)
    except (
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        S48EngineeringAcquisitionError,
        S48EngineeringCampaignError,
        S48PhysicalBackendError,
        S48PhysicalRehearsalError,
        S48PresealingGateError,
    ) as exc:
        print(f"S4.8 physical rehearsal failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("decision", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
