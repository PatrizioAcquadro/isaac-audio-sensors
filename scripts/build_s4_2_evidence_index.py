#!/usr/bin/env python3
"""Assemble immutable S4.2 evidence records without modifying capture attempts."""

from __future__ import annotations

import argparse
import json
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any

from verify_s4_2_local_dataset import verify_local_dataset

from isaac_audio_sensors.acquisition.s4_2 import load_json, sha256_file
from isaac_audio_sensors.core.dataset.atomic import (
    StagedFile,
    publish_file,
    write_json_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path("outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721")
DATASET_ROOT = Path("dataset/S4.2")
ACCEPTED_ATTEMPT = Path(
    "dataset/S4.2/attempts/s4_2_20260721T153800Z_optimized_candidate_014"
)
SUPERSEDED_ATTEMPTS = {"s4_2_20260721T002805Z_accepted_candidate_004"}
DATASET_CHECKSUM_NAME = "SHA256SUMS.remediation_20260721"

ACCEPTED_COPIES = {
    "mac_preflight.json": "mac_preflight.json",
    "session_manifest.json": "manifest.json",
    "validation_report.json": "capture_validation.json",
    "alignment_report.json": "alignment.json",
    "gate.json": "gate.json",
    "lifecycle.json": "lifecycle.json",
    "event_observation_confirmation.json": "event_observation_confirmation.json",
    "stable_session_preflight.json": "stable_session_preflight.json",
    "mac_dynamic_preflight.json": "mac_dynamic_preflight.json",
    "producer_readiness_validation.json": "producer_readiness_validation.json",
    "operator_remove_cue.json": "operator_remove_cue.json",
    "operator_cue.json": "operator_cue.json",
    "chat_cue_handshake_ready.json": "chat_cue_handshake_ready.json",
    "chat_removal_cue_target.json": "chat_removal_cue_target.json",
    "playback.json": "playback.json",
    "producer_readiness.json": "producer_readiness.json",
    "finalization_validation.json": "finalization_validation.json",
    "alignment_recomputed.json": "alignment_recomputed.json",
    "svo_replay_finalization_validation.json": (
        "svo_replay_finalization_validation.json"
    ),
    "normalized_configuration.json": "normalized_configuration.json",
}

TRACKED_INPUTS = [
    (".gitignore", "raw_evidence_ignore_policy"),
    ("pyproject.toml", "test_configuration"),
    ("configs/s4_2_acquisition.v1.json", "acquisition_configuration"),
    ("configs/s4_2_accepted_dry_run.v1.json", "accepted_configuration"),
    ("docs/development/specs/s4_2_acquisition.md", "s4_2_specification"),
    ("docs/development/s4_2_operator_runbook.md", "operator_runbook"),
    ("docs/reference_rig_hardware_environment.md", "reference_rig_status"),
    (
        "docs/development/specs/s4_2_mac_source_inventory.v1.json",
        "mac_source_inventory",
    ),
    (
        "docs/development/specs/s4_2_pre_capture_acceptance_amendment.v1.json",
        "pre_capture_acceptance_amendment",
    ),
    (
        "docs/development/specs/s4_2_remediation_acceptance.v1.json",
        "remediation_acceptance",
    ),
    ("docs/development/closeouts/S4/s4_2_acquisition.md", "s4_2_closeout"),
    (
        "docs/development/closeouts/S4/s4_2_evidence_index.md",
        "evidence_index_documentation",
    ),
    ("src/isaac_audio_sensors/cli.py", "workstation_cli"),
    (
        "src/isaac_audio_sensors/acquisition/__init__.py",
        "acquisition_implementation",
    ),
    (
        "src/isaac_audio_sensors/acquisition/s4_2.py",
        "semantic_validator",
    ),
    (
        "src/isaac_audio_sensors/acquisition/s4_2_reference.py",
        "reference_implementation",
    ),
    (
        "src/isaac_audio_sensors/acquisition/s4_2_orchestrator.py",
        "acquisition_implementation",
    ),
    ("scripts/generate_s4_2_reference_wav.py", "reference_generator"),
    ("scripts/s4_2_mac_preflight.py", "mac_preflight_helper"),
    ("scripts/s4_2_pi_capture.py", "pi_helper"),
    ("scripts/run_s4_2_zed_capture.py", "zed_capture_helper"),
    ("scripts/validate_s4_2_zed_svo.py", "zed_svo_validator"),
    ("scripts/s4_2_alignment_candidates.py", "alignment_helper"),
    ("scripts/s4_2_extract_alignment_frames.py", "alignment_review_helper"),
    ("scripts/s4_2_delete_privacy_visuals.py", "privacy_deletion_helper"),
    ("scripts/validate_s4_2_integrity.py", "semantic_validator"),
    ("scripts/verify_s4_2_local_dataset.py", "semantic_validator"),
    ("scripts/build_s4_2_evidence_index.py", "evidence_index_builder"),
    ("tests/test_s4_2_acquisition.py", "tests"),
    (
        "outputs/isaac_audio_sensors/S4/S4.2/reference/s4_2_reference_v1.0.0.wav",
        "reference_wav",
    ),
    (
        "outputs/isaac_audio_sensors/S4/S4.2/reference/reference_wav.json",
        "reference_metadata",
    ),
    (
        "outputs/isaac_audio_sensors/S4/S4.2/mac_preflight_current.json",
        "retained_mac_preflight",
    ),
    (
        "outputs/isaac_audio_sensors/S4/S4.2/failures/"
        "pi_preflight_firmware_representation_20260720T230747Z.json",
        "retained_failure",
    ),
    (
        "outputs/isaac_audio_sensors/S4/S4.2/failures/"
        "pi_preflight_firmware_representation_rerun_20260720T230901Z.json",
        "retained_failure",
    ),
]


def _write_bytes_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {path}")
    staged = StagedFile(path.parent, f".{path.name}.staged")
    try:
        staged.append(payload)
        publish_file(staged, path)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise


def _copy_immutable(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {destination}")
    if not source.is_file():
        raise FileNotFoundError(source)
    staged = StagedFile(destination.parent, f".{destination.name}.staged")
    try:
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                staged.append(block)
        publish_file(staged, destination)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise


def _jsonl_count(path: Path) -> int:
    with path.open("rb") as stream:
        return sum(1 for line in stream if line.strip())


def _media_properties(path: Path, relative: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        try:
            with wave.open(str(path), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return {
                    "container": "RIFF/WAVE",
                    "encoding": "PCM",
                    "channel_count": wav_file.getnchannels(),
                    "sample_rate_hz": rate,
                    "sample_width_bytes": wav_file.getsampwidth(),
                    "frame_count": frames,
                    "duration_s": frames / rate,
                }
        except (EOFError, wave.Error):
            return {"container": "RIFF/WAVE", "status": "partial_or_malformed"}
    if suffix == ".svo2":
        return {
            "container": "SVO2",
            "encoding": "ZED SDK H265 recording",
            "resolution": "HD720",
            "fps": 30,
            "depth_mode": "PERFORMANCE",
        }
    if suffix == ".jsonl":
        return {
            "encoding": "UTF-8 JSONL",
            "record_count": _jsonl_count(path),
        }
    if suffix == ".json":
        schema = None
        with suppress(OSError, ValueError, json.JSONDecodeError):
            schema = load_json(path).get("schema")
        return {"encoding": "UTF-8 JSON", "schema": schema}
    if suffix == ".png":
        return {"container": "PNG", "purpose": "manual alignment/privacy review"}
    if path.name == "SHA256SUMS":
        return {"encoding": "UTF-8 sha256sum manifest"}
    return {"encoding": "binary or role-specific record", "suffix": suffix}


def _attempt_context(relative: str) -> tuple[str | None, str | None]:
    parts = Path(relative).parts
    if len(parts) < 4 or parts[:3] != ("dataset", "S4.2", "attempts"):
        return None, None
    attempt_id = parts[3]
    lifecycle_path = (
        REPO_ROOT / DATASET_ROOT / "attempts" / attempt_id / "lifecycle.json"
    )
    state = None
    if lifecycle_path.is_file():
        state = load_json(lifecycle_path).get("state")
    return attempt_id, state


def _machine_role(relative: str) -> str:
    if (
        relative.endswith("/raw/respeaker_audio.wav")
        and ACCEPTED_ATTEMPT.name in relative
    ):
        return "raw_respeaker_wav"
    if relative.endswith("/raw/zed_capture.svo2") and ACCEPTED_ATTEMPT.name in relative:
        return "raw_zed_svo2"
    if relative.endswith("/raw/zed_frames.jsonl") and ACCEPTED_ATTEMPT.name in relative:
        return "raw_zed_frame_records"
    attempt_id, state = _attempt_context(relative)
    if attempt_id in SUPERSEDED_ATTEMPTS:
        return "retained_failure"
    if attempt_id and state != "accepted":
        return "retained_failure"
    if relative.startswith("dataset/S4.2/failures/"):
        return "retained_failure"
    if "/alignment_review_" in relative:
        return "accepted_alignment_visual_review"
    if relative.endswith("/event_observation_confirmation.json"):
        return "event_observation_confirmation"
    if relative.endswith("/alignment.json"):
        return "accepted_alignment_report"
    if relative.endswith("/manifest.json"):
        return "accepted_attempt_manifest"
    if relative.endswith("/capture_validation.json"):
        return "accepted_validation_report"
    if relative.endswith("/gate.json"):
        return "accepted_gate"
    if relative.startswith("dataset/S4.2/preflight/"):
        return "retained_mac_preflight"
    if relative.endswith("SHA256SUMS"):
        return "machine_local_checksums"
    return "accepted_attempt_supporting_evidence"


def _machine_entry(path: Path) -> dict[str, Any]:
    relative = path.relative_to(REPO_ROOT).as_posix()
    attempt_id, lifecycle = _attempt_context(relative)
    contract: dict[str, Any] = {
        "s4_2_acceptance_amendment": "S4.2-PRECAPTURE-AMENDMENT-2026-07-20-A",
        "retention": "machine_local_gitignored",
        "replicated": False,
        "fresh_clone_available": False,
        "no_repair_or_reordering": True,
    }
    if attempt_id is not None:
        contract.update(
            {
                "attempt_id": attempt_id,
                "lifecycle_state": lifecycle,
                "normalized_configuration": (
                    f"dataset/S4.2/attempts/{attempt_id}/normalized_configuration.json"
                ),
            }
        )
    role = _machine_role(relative)
    if role == "raw_respeaker_wav":
        contract.update(
            {
                "duration_s": 35.0,
                "sample_rate_hz": 16000,
                "sample_format": "S16_LE",
                "channel_count": 6,
                "channel_order": [
                    "conference",
                    "asr",
                    "raw_microphone_0",
                    "raw_microphone_1",
                    "raw_microphone_2",
                    "raw_microphone_3",
                ],
            }
        )
    if role in {"raw_zed_svo2", "raw_zed_frame_records"}:
        contract.update(
            {
                "duration_s": 35.0,
                "fps": 30,
                "resolution": "HD720",
                "depth_mode": "PERFORMANCE",
                "coordinate_system": "RIGHT_HANDED_Y_UP",
                "coordinate_units": "m",
            }
        )
    return {
        "path": relative,
        "local_relative_path": relative,
        "role": role,
        "retention": "machine_local_gitignored",
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "media_properties": _media_properties(path, relative),
        "acquisition_contract": contract,
    }


def _tracked_entry(relative: str, role: str) -> dict[str, Any]:
    path = REPO_ROOT / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative,
        "role": role,
        "retention": "tracked",
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _dataset_checksum_payload(paths: list[Path]) -> bytes:
    lines = [
        f"{sha256_file(path)}  "
        f"{path.relative_to(REPO_ROOT / DATASET_ROOT).as_posix()}\n"
        for path in paths
    ]
    return "".join(lines).encode("utf-8")


def _repository_gate_payload() -> dict[str, Any]:
    return {
        "schema": "ias.s4_2.repository_gate_candidate.v1",
        "status": "no_go_pending_frozen_commit_validation",
        "accepted_capture_gate": "passed",
        "completed_checks": {
            "targeted_unit_and_integration": (
                "94 passed, 2 explicit hardware/real-SVO-fixture skips"
            ),
            "make_test": "1204 passed, 80 optional-dependency/hardware skips",
            "make_lint": "passed",
            "make_build": "passed",
            "make_check_version": "passed (1.10.0)",
            "make_audit_dist": "passed",
            "git_diff_check": "passed before evidence assembly",
        },
        "pending_checks": {
            "make_build_kit_and_audit_kit": (
                "blocked as designed until release source is a clean frozen commit"
            ),
            "make_build_pack_and_audit_pack": (
                "blocked as designed until release source is a clean frozen commit"
            ),
            "clean_checkout_s4_2_integrity": "requires authorized frozen commit",
        },
        "raw_policy": {
            "machine_local_root": "dataset/S4.2",
            "required_in_clean_checkout": False,
            "required_on_capture_workstation": True,
        },
        "s4_3_started": False,
    }


def build() -> dict[str, Any]:
    output_root = REPO_ROOT / OUTPUT_ROOT
    dataset_root = REPO_ROOT / DATASET_ROOT
    if not dataset_root.is_dir():
        raise FileNotFoundError(dataset_root)

    accepted_output = output_root / "accepted"
    for destination_name, source_name in ACCEPTED_COPIES.items():
        _copy_immutable(
            REPO_ROOT / ACCEPTED_ATTEMPT / source_name,
            accepted_output / destination_name,
        )

    dataset_checksum_path = dataset_root / DATASET_CHECKSUM_NAME
    dataset_files_before_checksum = sorted(
        path for path in dataset_root.rglob("*") if path.is_file()
    )
    _write_bytes_immutable(
        dataset_checksum_path,
        _dataset_checksum_payload(dataset_files_before_checksum),
    )

    machine_files = sorted(path for path in dataset_root.rglob("*") if path.is_file())
    machine_entries = [_machine_entry(path) for path in machine_files]
    snapshot_path = output_root / "machine_local_index_snapshot.json"
    if snapshot_path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {snapshot_path}")
    write_json_atomic(
        snapshot_path,
        {
            "schema": "ias.s4_2.evidence_index.v1",
            "status": "machine_local_snapshot",
            "artifacts": machine_entries,
        },
    )

    validation_path = output_root / "machine_local_validation.json"
    verify_local_dataset(snapshot_path, REPO_ROOT, validation_path)
    if load_json(validation_path).get("status") != "passed":
        raise RuntimeError(f"machine-local validation failed: {validation_path}")

    gate_path = output_root / "candidate_repository_gate.json"
    if gate_path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {gate_path}")
    write_json_atomic(gate_path, _repository_gate_payload())

    tracked_inputs = [
        *TRACKED_INPUTS,
        *[
            (
                f"{OUTPUT_ROOT.as_posix()}/accepted/{name}",
                {
                    "mac_preflight.json": "accepted_mac_preflight",
                    "session_manifest.json": "accepted_attempt_manifest",
                    "validation_report.json": "accepted_validation_report",
                    "alignment_report.json": "accepted_alignment_report",
                    "gate.json": "accepted_gate",
                    "lifecycle.json": "accepted_lifecycle",
                    "event_observation_confirmation.json": (
                        "event_observation_confirmation"
                    ),
                    "stable_session_preflight.json": "stable_session_preflight",
                    "mac_dynamic_preflight.json": "mac_dynamic_preflight",
                    "producer_readiness_validation.json": (
                        "producer_readiness_validation"
                    ),
                    "operator_remove_cue.json": "operator_remove_cue",
                    "operator_cue.json": "operator_cue",
                    "chat_cue_handshake_ready.json": "chat_cue_handshake_ready",
                    "chat_removal_cue_target.json": "chat_removal_cue_target",
                    "playback.json": "playback_record",
                    "producer_readiness.json": "producer_readiness",
                    "finalization_validation.json": "finalization_validation",
                    "alignment_recomputed.json": "alignment_recomputed",
                    "svo_replay_finalization_validation.json": (
                        "svo_replay_validation"
                    ),
                    "normalized_configuration.json": "accepted_configuration_copy",
                }[name],
            )
            for name in ACCEPTED_COPIES
        ],
        (
            f"{OUTPUT_ROOT.as_posix()}/machine_local_index_snapshot.json",
            "machine_local_index_contract",
        ),
        (
            f"{OUTPUT_ROOT.as_posix()}/machine_local_validation.json",
            "machine_local_validation_record",
        ),
        (
            f"{OUTPUT_ROOT.as_posix()}/candidate_repository_gate.json",
            "repository_gate_candidate",
        ),
    ]
    tracked_entries = [_tracked_entry(path, role) for path, role in tracked_inputs]

    checksum_relative = f"{OUTPUT_ROOT.as_posix()}/SHA256SUMS"
    checksum_path = REPO_ROOT / checksum_relative
    indexed_without_checksums = [*tracked_entries, *machine_entries]
    checksum_lines = "".join(
        f"{entry['sha256']}  {entry['path']}\n"
        for entry in sorted(indexed_without_checksums, key=lambda item: item["path"])
    ).encode("utf-8")
    _write_bytes_immutable(checksum_path, checksum_lines)
    checksum_entry = _tracked_entry(checksum_relative, "evidence_checksums")

    index_path = output_root / "evidence_index.json"
    if index_path.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {index_path}")
    artifacts = sorted(
        [*indexed_without_checksums, checksum_entry], key=lambda item: item["path"]
    )
    payload = {
        "schema": "ias.s4_2.evidence_index.v1",
        "status": "passed",
        "scope": "S4.2 acquisition only",
        "accepted_attempt_id": ACCEPTED_ATTEMPT.name,
        "checksum_manifest": checksum_relative,
        "raw_evidence_policy": {
            "root": DATASET_ROOT.as_posix(),
            "retention": "machine_local_gitignored",
            "replicated": False,
            "fresh_clone_available": False,
            "machine_loss_is_data_loss": True,
        },
        "artifacts": artifacts,
    }
    write_json_atomic(index_path, payload)
    return {
        "index": index_path.relative_to(REPO_ROOT).as_posix(),
        "artifact_count": len(artifacts),
        "machine_local_artifact_count": len(machine_entries),
        "checksum_manifest": checksum_relative,
        "index_sha256": sha256_file(index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    try:
        result = build()
    except (
        FileExistsError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"S4.2 evidence assembly failed: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
