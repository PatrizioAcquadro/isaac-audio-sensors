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
import tempfile
from pathlib import Path
from typing import Any

from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (
    S48EngineeringAcquisitionError,
    run_supported_engineering_acquisition,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_campaign import (
    PRELIMINARY_MANIFEST_SCHEMA,
    S48EngineeringCampaignError,
    append_attempt_ledger_record,
    build_preliminary_manifest,
    build_reference_take_manifest,
    build_stratum_aware_campaign_manifest,
    compact_passed_retry_ledger,
    derive_preliminary_design,
    derive_stratum_aware_design,
    run_supported_nonreference_acquisition,
    validate_attempt_ledger,
    validate_attempt_ledger_with_reprocessing,
    validate_attempt_request,
    validate_attempt_request_with_reprocessing,
    validate_engineering_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_physical_backend import (
    RemotePhysicalEngineeringBackend,
    S48PhysicalBackendError,
    build_continuous_playback_asset,
    evaluate_mac_preflight_acceptance,
)
from isaac_audio_sensors.acquisition.s4_8_preliminary import (
    load_workflow_config,
    validate_reprocessing_record,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    S48PresealingGateError,
    load_presealing_config_v2,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/s4_8_engineering_campaign.v1.json"
LOCAL_S4_8_ROOT = (ROOT / ".local" / "s4_8").resolve()
SOURCE_PATHS = (
    "configs/s4_8_engineering_campaign.v1.json",
    "configs/s4_8_preliminary_workflow.v1.json",
    "configs/s4_8_presealing_gate.v2.json",
    "docs/development/specs/s4_8_engineering_campaign.md",
    "docs/development/specs/s4_8_preliminary_workflow.md",
    "docs/development/specs/s4_8_presealing_gate_v2.md",
    "docs/schemas/s4_8_presealing_gate_report.v2.schema.json",
    "docs/schemas/s4_8_preliminary_workflow.v1.schema.json",
    "scripts/run_s4_8_physical_rehearsal.py",
    "scripts/s4_8_mac_playback.swift",
    "scripts/s4_2_pi_capture.py",
    "scripts/s4_2_mac_preflight.py",
    "scripts/preflight_s4_2_zed.py",
    "scripts/run_s4_2_zed_capture.py",
    "scripts/validate_s4_2_zed_svo.py",
    "src/isaac_audio_sensors/acquisition/s4_8_engineering_acquisition.py",
    "src/isaac_audio_sensors/acquisition/s4_8_engineering_campaign.py",
    "src/isaac_audio_sensors/acquisition/s4_8_physical_backend.py",
    "src/isaac_audio_sensors/acquisition/s4_8_preliminary.py",
    "src/isaac_audio_sensors/acquisition/s4_8_presealing_gate_v2.py",
)


class S48PhysicalRehearsalError(RuntimeError):
    """Top-level physical rehearsal command failure."""


def _repository_local_campaign_root(configured_root: str) -> Path:
    """Rebase a frozen campaign name into the repository-local runtime area."""

    campaign_name = Path(configured_root).name
    if not campaign_name.startswith("s4_8_"):
        raise S48PhysicalRehearsalError(
            "configured campaign root must end in an S4.8 campaign name"
        )
    root = (LOCAL_S4_8_ROOT / campaign_name).resolve()
    if root.parent != LOCAL_S4_8_ROOT:
        raise S48PhysicalRehearsalError(
            "configured campaign root escapes the repository-local runtime area"
        )
    return root


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


def _verify_mac_playback_runtime(config: dict[str, Any]) -> dict[str, Any]:
    playback = config["playback"]
    version = _run(
        [
            *playback["ssh_prefix"],
            playback["playback_runtime_path"],
            "--version",
        ],
        timeout=30,
    )
    if (
        version["return_code"] != 0
        or version["stdout"].strip()
        != playback["playback_runtime_stdout"]
        or version["stderr"].strip()
        != playback["playback_runtime_stderr"]
    ):
        raise S48PhysicalRehearsalError(
            "Mac Swift playback runtime identity mismatch"
        )
    typecheck = _run(
        [
            *playback["ssh_prefix"],
            playback["playback_typecheck_path"],
            "-typecheck",
            playback["playback_helper_mac_path"],
        ],
        timeout=60,
    )
    if typecheck["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            "Mac CoreAudio playback helper typecheck failed: "
            f"{typecheck['stderr'].strip()}"
        )
    return {
        "schema": "ias.s4_8.mac_playback_runtime.v1",
        "status": "passed",
        "runtime_path": playback["playback_runtime_path"],
        "typecheck_path": playback["playback_typecheck_path"],
        "runtime_stdout": version["stdout"].strip(),
        "runtime_stderr": version["stderr"].strip(),
        "helper_sha256": playback["playback_helper_sha256"],
        "helper_typecheck_exit_status": typecheck["return_code"],
        "start_observation": "coreaudio_first_nonzero_presented_frame",
        "clock_mapping": "causal_ssh_sync_interval_lower_bound",
    }


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
        source_start_s=float(config["reference"]["active_start_s"]),
        source_stop_s=float(config["reference"]["active_stop_s"]),
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
    playback_runtime = _verify_mac_playback_runtime(config)
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
    mac_acceptance = evaluate_mac_preflight_acceptance(mac_report)
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
        "playback_runtime": playback_runtime,
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
    preliminary = getattr(args, "preliminary", False)
    workflow = load_workflow_config(ROOT) if preliminary else None
    configured_root = (
        workflow["preliminary"]["campaign_root"]
        if workflow is not None
        else config["operational_locations"]["campaign_root"]
    )
    root = (
        args.campaign_root.resolve()
        if args.campaign_root is not None
        else _repository_local_campaign_root(configured_root)
    )
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
        source_start_s=float(config["reference"]["active_start_s"]),
        source_stop_s=float(config["reference"]["active_stop_s"]),
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
    playback_runtime = _verify_mac_playback_runtime(config)
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
    design = (
        derive_preliminary_design(template)
        if preliminary
        else derive_stratum_aware_design(template)
    )
    protocol_path = ROOT / (
        workflow["specification_path"]
        if workflow is not None
        else config["protocol"]["specification_path"]
    )
    controller_hash = canonical_sha256(
        {
            path: source_hashes[path]
            for path in SOURCE_PATHS
            if path.endswith(
                (
                    "s4_8_engineering_acquisition.py",
                    "s4_8_engineering_campaign.py",
                    "s4_8_physical_backend.py",
                    "s4_8_preliminary.py",
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
                "playback_runtime_path",
                "playback_typecheck_path",
                "playback_runtime_stdout",
                "playback_runtime_stderr",
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
    build_manifest = (
        build_preliminary_manifest
        if preliminary
        else build_stratum_aware_campaign_manifest
    )
    manifest = build_manifest(
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
            "identity": (
                "s4_8_four_take_preliminary_v1"
                if preliminary
                else config["protocol"]["identity"]
            ),
            "sha256": _sha256(protocol_path),
        },
        devices=devices,
        channel_map=config["channel_map"],
        design=design,
        retry_policy=config["retry_policy"],
        operational_locations={
            "campaign_root": str(root),
            "pi_capture_root": (
                workflow["preliminary"]["pi_capture_root"]
                if workflow is not None
                else config["operational_locations"]["pi_capture_root"]
            ),
        },
        template_manifest_sha256=_sha256(template_path),
    )
    manifest_path = freeze_root / "campaign_manifest.json"
    _write_new_json(manifest_path, manifest)
    payload = {
        "schema": (
            "ias.s4_8.preliminary_freeze.v1"
            if preliminary
            else "ias.s4_8.engineering_campaign_freeze.v1"
        ),
        "status": "frozen",
        "campaign_root": str(root),
        "campaign_manifest_path": str(manifest_path),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "source_archive_sha256": manifest["source_archive_sha256"],
        "preflight_report_sha256": environment["preflight_report_sha256"],
        "continuous_asset": asset,
        "continuous_asset_deployment": deployment,
        "playback_helper_deployment": helper_deployment,
        "playback_runtime": playback_runtime,
        "authority": config["authority"],
    }
    if preliminary:
        payload.update(
            {
                "classification": workflow["preliminary"]["classification"],
                "final_protocol_frozen": False,
                "official_acquisition_permitted": False,
            }
        )
    _write_new_json(freeze_root / "freeze_report.json", payload)
    return payload


def run_take(args: argparse.Namespace) -> dict[str, Any]:
    config = _config(args.config)
    campaign_manifest = _load_json(args.manifest.resolve())
    anchor = str(campaign_manifest.get("manifest_sha256"))
    validate_engineering_manifest(
        campaign_manifest,
        expected_manifest_sha256=anchor,
    )
    preliminary = (
        campaign_manifest.get("schema") == PRELIMINARY_MANIFEST_SCHEMA
    )
    if getattr(args, "require_preliminary", False) and not preliminary:
        raise S48PhysicalRehearsalError(
            "run-preliminary-take requires a four-case preliminary manifest"
        )
    _require_clean_head()
    _require_manifest_head_ancestor(
        str(campaign_manifest["code_head"]),
        _git_head(),
    )
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
    reprocessed_attempts = _load_reprocessed_attempts(
        getattr(args, "reprocessing_record", []),
        campaign_manifest_path=args.manifest.resolve(),
        campaign_manifest=campaign_manifest,
        ledger_path=ledger_path,
        ledger=ledger,
    )
    if not args.dry_run:
        if preliminary:
            validate_attempt_request_with_reprocessing(
                ledger,
                campaign_manifest=campaign_manifest,
                expected_campaign_manifest_sha256=anchor,
                take=take,
                attempt_number=args.attempt_number,
                reprocessed_attempts=reprocessed_attempts,
            )
        else:
            if reprocessed_attempts:
                raise S48PhysicalRehearsalError(
                    "additive reprocessing is restricted to preliminary takes"
                )
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
        f"{campaign_manifest['operational_locations']['pi_capture_root']}/"
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
    retained_result = dict(result)
    if preliminary:
        retained_result.update(
            {
                "preliminary_case_id": take["preliminary_case_id"],
                "classification": campaign_manifest["classification"],
                "counts_as_official_take": False,
                "official_evidence_eligible": False,
            }
        )
    _write_new_json(attempt_root / "controller_result.json", retained_result)
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
        if preliminary:
            validate_attempt_ledger_with_reprocessing(
                ledger,
                campaign_manifest=campaign_manifest,
                expected_campaign_manifest_sha256=anchor,
                reprocessed_attempts=reprocessed_attempts,
            )
        else:
            validate_attempt_ledger(
                ledger,
                campaign_manifest=campaign_manifest,
                expected_campaign_manifest_sha256=anchor,
            )
        _append_json_line(ledger_path, record)
        retired_failed_attempts = (
            _prepare_failed_attempt_retirement(
                campaign_root=campaign_root,
                take_id=str(take["engineering_take_id"]),
                replacement_attempt_root=attempt_root,
                ledger=ledger,
            )
            if result["decision"] == "PASS"
            else []
        )
        if retired_failed_attempts:
            retirement_notes = []
            for retired_root in retired_failed_attempts:
                note_path = Path(retired_root) / "failed_raw_note.json"
                note = _load_json(note_path)
                retirement_notes.append(
                    {
                        "attempt_number": note["attempt_number"],
                        "failure_note_path": note_path.relative_to(
                            campaign_root
                        ).as_posix(),
                        "failure_note_sha256": _sha256(note_path),
                    }
                )
            compact_passed_retry_ledger(
                ledger,
                campaign_manifest_sha256=anchor,
                take_id=str(take["engineering_take_id"]),
                retirement_notes=retirement_notes,
            )
            if preliminary:
                validate_attempt_ledger_with_reprocessing(
                    ledger,
                    campaign_manifest=campaign_manifest,
                    expected_campaign_manifest_sha256=anchor,
                    reprocessed_attempts=reprocessed_attempts,
                )
            else:
                validate_attempt_ledger(
                    ledger,
                    campaign_manifest=campaign_manifest,
                    expected_campaign_manifest_sha256=anchor,
                )
            _replace_json_lines(ledger_path, ledger)
            _finalize_failed_attempt_retirement(
                campaign_root=campaign_root,
                attempt_roots=retired_failed_attempts,
            )
    else:
        retired_failed_attempts = []
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
        "classification": (
            campaign_manifest.get("classification")
            if preliminary
            else {"engineering_only": True}
        ),
        "counts_as_official_take": False,
        "official_evidence_eligible": False,
        "retired_failed_attempts": retired_failed_attempts,
        "authority": config["authority"],
    }


def _load_reprocessed_attempts(
    record_paths: list[Path],
    *,
    campaign_manifest_path: Path,
    campaign_manifest: dict[str, Any],
    ledger_path: Path,
    ledger: list[dict[str, Any]],
) -> list[tuple[str, int]]:
    reprocessed: list[tuple[str, int]] = []
    design_by_id = {
        str(item["engineering_take_id"]): item
        for item in campaign_manifest["design"]
    }
    for path in record_paths:
        record = _load_json(path.resolve())
        validate_reprocessing_record(ROOT, record)
        historical = record["historical_result"]
        take_id = str(record["preliminary_take_id"])
        attempt_number = int(record["attempt_number"])
        take = design_by_id.get(take_id)
        if (
            Path(historical["campaign_manifest"]["path"]).resolve()
            != campaign_manifest_path
            or Path(historical["attempt_ledger"]["path"]).resolve()
            != ledger_path.resolve()
            or take is None
            or take.get("preliminary_case_id") != record.get("case_id")
            or not any(
                item.get("engineering_take_id") == take_id
                and item.get("attempt_number") == attempt_number
                and item.get("decision") == "RETRY_REQUIRED"
                for item in ledger
            )
        ):
            raise S48PhysicalRehearsalError(
                "additive reprocessing record targets another campaign history"
            )
        _require_manifest_head_ancestor(
            str(record["corrected_offline_result"]["corrective_commit"]),
            _git_head(),
        )
        reprocessed.append((take_id, attempt_number))
    if len(set(reprocessed)) != len(reprocessed):
        raise S48PhysicalRehearsalError(
            "duplicate additive reprocessing records are forbidden"
        )
    return reprocessed


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


def _require_manifest_head_ancestor(
    manifest_head: str,
    implementation_head: str,
) -> None:
    result = _run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            manifest_head,
            implementation_head,
        ],
        timeout=30,
    )
    if result["return_code"] != 0:
        raise S48PhysicalRehearsalError(
            "acquisition implementation does not descend from the frozen "
            "campaign source"
        )


def _prepare_failed_attempt_retirement(
    *,
    campaign_root: Path,
    take_id: str,
    replacement_attempt_root: Path,
    ledger: list[dict[str, Any]],
) -> list[str]:
    """Create prevention notes after PASS without deleting artifacts yet."""

    if (
        not (replacement_attempt_root / "respeaker_audio.wav").is_file()
        or not (replacement_attempt_root / "candidate_seal.json").is_file()
        or not ledger
        or ledger[-1].get("engineering_take_id") != take_id
        or ledger[-1].get("decision") != "PASS"
    ):
        raise S48PhysicalRehearsalError(
            "failed raws cannot be retired before the replacement is valid"
        )
    retired: list[str] = []
    for record in ledger[:-1]:
        if (
            record.get("engineering_take_id") != take_id
            or record.get("decision") != "RETRY_REQUIRED"
        ):
            continue
        attempt_number = record["attempt_number"]
        attempt_root = (
            campaign_root
            / "attempts"
            / take_id
            / f"{take_id}__attempt_{attempt_number:02d}"
        )
        if not attempt_root.is_dir():
            raise S48PhysicalRehearsalError(
                f"failed attempt directory is missing: {attempt_root}"
            )
        report_path = attempt_root / "retry_report.json"
        if not report_path.is_file():
            report_path = attempt_root / "gate_report.json"
        report = _load_json(report_path)
        reasons = report.get("reasons")
        codes = (
            [
                str(reason.get("code"))
                for reason in reasons
                if isinstance(reason, dict) and reason.get("code")
            ]
            if isinstance(reasons, list)
            else []
        )
        note = {
            "take_id": take_id,
            "attempt_number": attempt_number,
            "replacement_attempt_number": ledger[-1]["attempt_number"],
            "failure_cause": (
                ", ".join(dict.fromkeys(codes))
                or "technical validation failed"
            ),
            "prevention_guidance": _prevention_guidance(codes),
        }
        note_path = attempt_root / "failed_raw_note.json"
        _write_new_json(note_path, note)
        retired.append(str(attempt_root))
    return retired


def _prevention_guidance(codes: list[str]) -> str:
    if "zed_full_replay_failed" in codes:
        return (
            "Verify the canonical S4.2 SVO replay schema, full frame replay, "
            "end-of-SVO, and ZED identity before repeating the take."
        )
    return (
        "Remove uncontrolled noise and verify playback, capture timing, "
        "devices, and placement before repeating the take."
    )


def _finalize_failed_attempt_retirement(
    *,
    campaign_root: Path,
    attempt_roots: list[str],
) -> None:
    """Delete retired artifacts only after the compacted ledger is durable."""

    allowed_root = (campaign_root / "attempts").resolve()
    for attempt_root_value in attempt_roots:
        attempt_root = Path(attempt_root_value).resolve()
        if (
            attempt_root == allowed_root
            or not attempt_root.is_relative_to(allowed_root)
        ):
            raise S48PhysicalRehearsalError(
                f"retired attempt path escapes campaign attempts: {attempt_root}"
            )
        note_path = attempt_root / "failed_raw_note.json"
        if not note_path.is_file():
            raise S48PhysicalRehearsalError(
                f"retirement note is missing: {note_path}"
            )
        for child in attempt_root.iterdir():
            if child == note_path:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def _replace_json_lines(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    """Atomically replace a compacted operational ledger."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise S48PhysicalRehearsalError(
            f"compacted attempt ledger replacement failed: {exc}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--output", type=Path, required=True)
    preflight_parser.add_argument("--pi-probe-root", required=True)
    preflight_parser.set_defaults(function=preflight)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--preflight-report", type=Path, required=True)
    freeze_parser.add_argument(
        "--campaign-root",
        type=Path,
        default=None,
        help="override the default repository-local .local/s4_8 campaign root",
    )
    freeze_parser.set_defaults(preliminary=False)
    freeze_parser.set_defaults(function=freeze)
    preliminary_freeze_parser = subparsers.add_parser("freeze-preliminary")
    preliminary_freeze_parser.add_argument(
        "--preflight-report", type=Path, required=True
    )
    preliminary_freeze_parser.add_argument(
        "--campaign-root",
        type=Path,
        default=None,
        help="override the default repository-local .local/s4_8 campaign root",
    )
    preliminary_freeze_parser.set_defaults(
        function=freeze,
        preliminary=True,
    )
    take_parser = subparsers.add_parser("run-take")
    take_parser.add_argument("--manifest", type=Path, required=True)
    take_parser.add_argument("--take-id", required=True)
    take_parser.add_argument("--attempt-number", type=int, required=True)
    take_parser.add_argument("--dry-run", action="store_true")
    take_parser.add_argument("--dry-run-root", type=Path, default=None)
    take_parser.set_defaults(require_preliminary=False)
    take_parser.set_defaults(function=run_take)
    preliminary_take_parser = subparsers.add_parser("run-preliminary-take")
    preliminary_take_parser.add_argument("--manifest", type=Path, required=True)
    preliminary_take_parser.add_argument("--take-id", required=True)
    preliminary_take_parser.add_argument("--attempt-number", type=int, required=True)
    preliminary_take_parser.add_argument(
        "--reprocessing-record",
        action="append",
        default=[],
        type=Path,
    )
    preliminary_take_parser.set_defaults(
        function=run_take,
        dry_run=False,
        dry_run_root=None,
        require_preliminary=True,
    )
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
