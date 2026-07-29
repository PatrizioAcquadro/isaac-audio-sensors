"""Mandatory engineering-only S4.8 acquisition journal and sealing interlock.

The structures here are SHA-256 tamper-evident records, not digital
signatures.  They create no grant, invoke no official state machine, publish
no official evidence, and cannot create an official take seal.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from collections.abc import Mapping, MutableSequence, Sequence
from pathlib import Path
from typing import Any

import jsonschema

from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (
    evaluate_presealing_gate_v2,
    load_presealing_config_v2,
    normalize_reference_for_capture_rate,
    read_pcm16_wav_strict,
    select_active_reference_interval_v2,
)

MANIFEST_SCHEMA = "ias.s4_8.engineering_precollection_manifest.v2"
JOURNAL_EVENT_SCHEMA = "ias.s4_8.engineering_process_journal_event.v2"
CLEARANCE_SCHEMA = "ias.s4_8.engineering_candidate_clearance.v2"
CANDIDATE_SEAL_SCHEMA = "ias.s4_8.engineering_candidate_seal.v2"

_MANIFEST_FIELDS = {
    "schema",
    "code_head",
    "environment_identity",
    "reference_wav_sha256",
    "gate_configuration_sha256",
    "detector_configuration_sha256",
    "device_profile_id",
    "channel_map",
    "protocol_id",
    "capture_controller_identity",
    "capture_controller_version",
}
_EVENT_ORDER = (
    "capture_controller_started",
    "recorder_started",
    "recorder_ready",
    "playback_commanded",
    "playback_started",
    "playback_stop_planned",
    "playback_terminated",
    "recorder_terminated",
    "capture_authenticated",
    "gate_evaluated",
    "candidate_clearance_created",
)
REPORT_SCHEMA_PATH_V2 = Path("docs/schemas/s4_8_presealing_gate_report.v2.schema.json")


class S48EngineeringAcquisitionError(RuntimeError):
    """Engineering acquisition provenance or interlock failure."""


class SubprocessEngineeringBackend:
    """Concrete backend for explicit recorder/player argument vectors."""

    def __init__(
        self,
        *,
        recorder_command: Sequence[str],
        playback_command: Sequence[str],
        readiness_delay_s: float = 0.25,
        termination_timeout_s: float = 5.0,
    ) -> None:
        if (
            not recorder_command
            or not playback_command
            or readiness_delay_s < 0.0
            or termination_timeout_s <= 0.0
        ):
            raise S48EngineeringAcquisitionError(
                "subprocess engineering backend configuration is invalid"
            )
        self._recorder_template = list(recorder_command)
        self._playback_template = list(playback_command)
        self._readiness_delay_s = readiness_delay_s
        self._termination_timeout_s = termination_timeout_s
        self._recorder_process: subprocess.Popen[bytes] | None = None
        self._playback_process: subprocess.Popen[bytes] | None = None
        self._playback_args: list[str] | None = None
        self._recorder_termination_observed_ns: int | None = None
        self._playback_termination_observed_ns: int | None = None

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def start_recorder(self, capture_path: Path) -> dict[str, Any]:
        if self._recorder_process is not None:
            raise S48EngineeringAcquisitionError("recorder already started")
        arguments = [
            item.replace("{capture_wav}", capture_path.as_posix())
            for item in self._recorder_template
        ]
        self._recorder_process = _start_process(arguments)
        return {
            "pid": self._recorder_process.pid,
            "process_identity": arguments[0],
        }

    def wait_recorder_ready(self, recorder: object) -> bool:
        del recorder
        time.sleep(self._readiness_delay_s)
        return (
            self._recorder_process is not None and self._recorder_process.poll() is None
        )

    def prepare_playback(self, reference_path: Path) -> dict[str, Any]:
        if self._playback_process is not None or self._playback_args is not None:
            raise S48EngineeringAcquisitionError("playback already prepared")
        self._playback_args = [
            item.replace("{reference_wav}", reference_path.as_posix())
            for item in self._playback_template
        ]
        return {"command_sha256": canonical_sha256(self._playback_args)}

    def start_playback(self, command: object) -> dict[str, Any]:
        del command
        if self._playback_args is None or self._playback_process is not None:
            raise S48EngineeringAcquisitionError("playback command was not prepared")
        self._playback_process = _start_process(self._playback_args)
        return {
            "pid": self._playback_process.pid,
            "process_identity": self._playback_args[0],
        }

    def wait_until(self, monotonic_ns: int) -> None:
        while True:
            observed = time.monotonic_ns()
            if (
                self._playback_process is not None
                and self._playback_termination_observed_ns is None
                and self._playback_process.poll() is not None
            ):
                self._playback_termination_observed_ns = observed
            if (
                self._recorder_process is not None
                and self._recorder_termination_observed_ns is None
                and self._recorder_process.poll() is not None
            ):
                self._recorder_termination_observed_ns = observed
            remaining_ns = monotonic_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                return
            time.sleep(min(remaining_ns / 1_000_000_000.0, 0.05))

    def stop_playback(self, playback: object) -> dict[str, Any]:
        del playback
        process = self._playback_process
        if process is None:
            raise S48EngineeringAcquisitionError("playback was not started")
        exit_status, requested = _terminate_process(
            process,
            self._termination_timeout_s,
        )
        observed = self._playback_termination_observed_ns or time.monotonic_ns()
        return {
            "pid": process.pid,
            "exit_status": exit_status,
            "controller_requested_termination": requested,
            "controller_requested_signal": signal.SIGTERM if requested else None,
            "observed_termination_monotonic_ns": observed,
        }

    def stop_recorder(self, recorder: object) -> dict[str, Any]:
        del recorder
        process = self._recorder_process
        if process is None:
            raise S48EngineeringAcquisitionError("recorder was not started")
        exit_status, requested = _terminate_process(
            process,
            self._termination_timeout_s,
        )
        observed = self._recorder_termination_observed_ns or time.monotonic_ns()
        return {
            "pid": process.pid,
            "exit_status": exit_status,
            "controller_requested_termination": requested,
            "controller_requested_signal": signal.SIGTERM if requested else None,
            "observed_termination_monotonic_ns": observed,
        }


def build_engineering_precollection_manifest(
    *,
    code_head: str,
    environment_identity: str,
    reference_wav_sha256: str,
    gate_configuration_sha256: str,
    detector_configuration_sha256: str,
    device_profile_id: str,
    channel_map: Sequence[str],
    protocol_id: str,
    capture_controller_identity: str,
    capture_controller_version: str,
) -> dict[str, Any]:
    """Freeze the external anchor for one engineering collection attempt."""

    payload = {
        "schema": MANIFEST_SCHEMA,
        "code_head": code_head,
        "environment_identity": environment_identity,
        "reference_wav_sha256": reference_wav_sha256,
        "gate_configuration_sha256": gate_configuration_sha256,
        "detector_configuration_sha256": detector_configuration_sha256,
        "device_profile_id": device_profile_id,
        "channel_map": list(channel_map),
        "protocol_id": protocol_id,
        "capture_controller_identity": capture_controller_identity,
        "capture_controller_version": capture_controller_version,
    }
    _validate_manifest_payload(payload)
    return {**payload, "manifest_sha256": canonical_sha256(payload)}


def append_engineering_journal_event(
    journal: MutableSequence[dict[str, Any]],
    *,
    manifest_anchor_sha256: str,
    event_type: str,
    observed_monotonic_ns: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one event whose predecessor is the frozen manifest or event."""

    if (
        event_type not in _EVENT_ORDER
        or len(journal) >= len(_EVENT_ORDER)
        or event_type != _EVENT_ORDER[len(journal)]
    ):
        raise S48EngineeringAcquisitionError(
            "engineering process event is missing, duplicated, or out of order"
        )
    if not _is_sha256(manifest_anchor_sha256):
        raise S48EngineeringAcquisitionError("engineering manifest anchor is invalid")
    if (
        isinstance(observed_monotonic_ns, bool)
        or not isinstance(observed_monotonic_ns, int)
        or observed_monotonic_ns < 0
    ):
        raise S48EngineeringAcquisitionError("event monotonic time is invalid")
    previous = (
        manifest_anchor_sha256 if not journal else str(journal[-1].get("event_sha256"))
    )
    payload = {
        "schema": JOURNAL_EVENT_SCHEMA,
        "sequence": len(journal),
        "manifest_anchor_sha256": manifest_anchor_sha256,
        "previous_event_sha256": previous,
        "event_type": event_type,
        "observed_monotonic_ns": observed_monotonic_ns,
        "data": dict(data),
    }
    event = {**payload, "event_sha256": canonical_sha256(payload)}
    journal.append(event)
    return event


def validate_engineering_process_journal(
    manifest: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    *,
    expected_manifest_sha256: str,
    required_terminal_event: str,
) -> None:
    """Validate the external anchor and every complete ordered chain link."""

    _validate_manifest(manifest, expected_manifest_sha256)
    if required_terminal_event not in _EVENT_ORDER:
        raise S48EngineeringAcquisitionError("unsupported terminal journal event")
    required_count = _EVENT_ORDER.index(required_terminal_event) + 1
    if len(journal) != required_count:
        raise S48EngineeringAcquisitionError(
            "engineering process journal is missing or duplicates required events"
        )
    previous = expected_manifest_sha256
    previous_time = -1
    for sequence, (event, expected_type) in enumerate(
        zip(journal, _EVENT_ORDER[:required_count], strict=True)
    ):
        expected_fields = {
            "schema",
            "sequence",
            "manifest_anchor_sha256",
            "previous_event_sha256",
            "event_type",
            "observed_monotonic_ns",
            "data",
            "event_sha256",
        }
        payload = {key: value for key, value in event.items() if key != "event_sha256"}
        observed_time = event.get("observed_monotonic_ns")
        if (
            set(event) != expected_fields
            or event.get("schema") != JOURNAL_EVENT_SCHEMA
            or event.get("sequence") != sequence
            or event.get("manifest_anchor_sha256") != expected_manifest_sha256
            or event.get("previous_event_sha256") != previous
            or event.get("event_type") != expected_type
            or not isinstance(event.get("data"), Mapping)
            or isinstance(observed_time, bool)
            or not isinstance(observed_time, int)
            or observed_time < previous_time
            or event.get("event_sha256") != canonical_sha256(payload)
        ):
            raise S48EngineeringAcquisitionError(
                "engineering process journal hash chain or event sequence is invalid"
            )
        previous = str(event["event_sha256"])
        previous_time = observed_time
    controller = journal[0]["data"]
    if (
        controller.get("identity") != manifest["capture_controller_identity"]
        or controller.get("version") != manifest["capture_controller_version"]
    ):
        raise S48EngineeringAcquisitionError(
            "capture controller identity/version contradicts manifest"
        )
    if required_count >= _EVENT_ORDER.index("capture_authenticated") + 1:
        capture = journal[_EVENT_ORDER.index("capture_authenticated")]["data"]
        expected_capture_fields = {
            "reference_sha256": manifest["reference_wav_sha256"],
            "device_profile_id": manifest["device_profile_id"],
            "channel_map": manifest["channel_map"],
            "gate_configuration_sha256": manifest["gate_configuration_sha256"],
            "detector_configuration_sha256": manifest["detector_configuration_sha256"],
        }
        if not _is_sha256(capture.get("capture_sha256")) or any(
            capture.get(key) != value for key, value in expected_capture_fields.items()
        ):
            raise S48EngineeringAcquisitionError(
                "capture authentication event contradicts precollection manifest"
            )


def create_candidate_engineering_clearance(
    report: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Create exact-input candidate clearance only for a journaled PASS."""

    validate_engineering_process_journal(
        manifest,
        journal,
        expected_manifest_sha256=expected_manifest_sha256,
        required_terminal_event="gate_evaluated",
    )
    _validate_report_for_clearance(report)
    report_sha256 = canonical_sha256(report)
    gate_event = journal[-1]
    provenance = report["input_provenance"]
    capture_event = journal[-2]
    if (
        report["decision"] != "PASS"
        or report["reasons"] != []
        or gate_event["data"].get("decision") != report["decision"]
        or gate_event["data"].get("report_sha256") != report_sha256
        or provenance.get("manifest_sha256") != expected_manifest_sha256
        or provenance.get("process_journal_head_sha256")
        != capture_event.get("event_sha256")
        or provenance.get("capture_sha256")
        != capture_event["data"].get("capture_sha256")
        or provenance.get("reference_sha256")
        != capture_event["data"].get("reference_sha256")
        or provenance.get("configuration_sha256")
        != manifest["gate_configuration_sha256"]
        or provenance.get("detector_configuration_sha256")
        != manifest["detector_configuration_sha256"]
    ):
        decision = report.get("decision")
        if decision == "RETRY_REQUIRED":
            raise S48EngineeringAcquisitionError(
                "a RETRY_REQUIRED report cannot create candidate clearance"
            )
        raise S48EngineeringAcquisitionError(
            "gate report, journal, manifest, or exact input binding mismatch"
        )
    payload = {
        "schema": CLEARANCE_SCHEMA,
        "status": "cleared_for_engineering_candidate_seal",
        "manifest_sha256": expected_manifest_sha256,
        "process_journal_head_sha256": gate_event["event_sha256"],
        "report_sha256": report_sha256,
        "capture_sha256": provenance["capture_sha256"],
        "reference_sha256": provenance["reference_sha256"],
        "configuration_sha256": provenance["configuration_sha256"],
        "detector_configuration_sha256": provenance["detector_configuration_sha256"],
        "scientific_outcome_fields_used": [],
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
            "official_take_seal": False,
        },
    }
    return {**payload, "clearance_sha256": canonical_sha256(payload)}


def seal_engineering_candidate(
    *,
    capture_path: Path,
    reference_path: Path,
    report: Mapping[str, Any],
    clearance: Mapping[str, Any],
    manifest: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    expected_manifest_sha256: str,
    candidate_seal_path: Path,
    clearance_registry_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """The only supported engineering candidate-seal API; clearance is mandatory."""

    validate_engineering_process_journal(
        manifest,
        journal,
        expected_manifest_sha256=expected_manifest_sha256,
        required_terminal_event="candidate_clearance_created",
    )
    _validate_report_for_clearance(report)
    payload = {
        key: value for key, value in clearance.items() if key != "clearance_sha256"
    }
    clearance_sha256 = canonical_sha256(payload)
    gate_event = journal[-2]
    clearance_event = journal[-1]
    if (
        clearance.get("schema") != CLEARANCE_SCHEMA
        or clearance.get("status") != "cleared_for_engineering_candidate_seal"
        or clearance.get("clearance_sha256") != clearance_sha256
        or clearance_event["data"].get("clearance_sha256") != clearance_sha256
        or clearance.get("process_journal_head_sha256")
        != gate_event.get("event_sha256")
        or clearance.get("manifest_sha256") != expected_manifest_sha256
        or clearance.get("report_sha256") != canonical_sha256(report)
        or clearance.get("configuration_sha256")
        != report["input_provenance"].get("configuration_sha256")
        or clearance.get("detector_configuration_sha256")
        != report["input_provenance"].get("detector_configuration_sha256")
        or report.get("decision") != "PASS"
        or report.get("reasons") != []
    ):
        raise S48EngineeringAcquisitionError(
            "candidate clearance is stale, altered, or mismatched"
        )
    capture_sha256 = _sha256_file(capture_path)
    reference_sha256 = _sha256_file(reference_path)
    if capture_sha256 != clearance.get("capture_sha256"):
        raise S48EngineeringAcquisitionError(
            "candidate clearance cannot seal a different capture"
        )
    if reference_sha256 != clearance.get("reference_sha256"):
        raise S48EngineeringAcquisitionError("candidate clearance reference mismatch")
    if clearance_registry_path.exists():
        raise S48EngineeringAcquisitionError("candidate clearance was already reused")
    seal_payload = {
        "schema": CANDIDATE_SEAL_SCHEMA,
        "status": "engineering_candidate_sealed",
        "engineering_only": True,
        "dry_run": dry_run,
        "capture_sha256": capture_sha256,
        "reference_sha256": reference_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "process_journal_sha256": journal[-1]["event_sha256"],
        "report_sha256": canonical_sha256(report),
        "clearance_sha256": clearance_sha256,
        "authority": {
            "creates_grant": False,
            "consumes_grant": False,
            "official_state_machine": False,
            "publishes_official_evidence": False,
            "official_take_seal": False,
        },
    }
    seal = {**seal_payload, "seal_sha256": canonical_sha256(seal_payload)}
    if dry_run:
        return seal
    _write_new_json(
        clearance_registry_path,
        {
            "schema": "ias.s4_8.engineering_clearance_consumption.v2",
            "clearance_sha256": clearance_sha256,
            "candidate_seal_sha256": seal["seal_sha256"],
        },
    )
    _write_new_json(candidate_seal_path, seal)
    return seal


def run_presealing_gate_from_engineering_files(
    *,
    capture_path: Path,
    reference_path: Path,
    manifest: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    expected_manifest_sha256: str,
    repo_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Validate journal/file provenance and evaluate the complete v2 gate."""

    validate_engineering_process_journal(
        manifest,
        journal,
        expected_manifest_sha256=expected_manifest_sha256,
        required_terminal_event="capture_authenticated",
    )
    config = load_presealing_config_v2(repo_root)
    if manifest["gate_configuration_sha256"] != canonical_sha256(config) or manifest[
        "detector_configuration_sha256"
    ] != canonical_sha256(config["detector"]):
        raise S48EngineeringAcquisitionError(
            "precollection manifest configuration hashes are stale"
        )
    capture, capture_rate = read_pcm16_wav_strict(capture_path)
    reference_channels, reference_rate = read_pcm16_wav_strict(reference_path)
    reference_channels = normalize_reference_for_capture_rate(
        reference_channels,
        reference_sample_rate_hz=reference_rate,
        capture_sample_rate_hz=capture_rate,
    )
    reference_channels = select_active_reference_interval_v2(
        reference_channels,
        sample_rate_hz=capture_rate,
        config=config,
    )
    capture_sha256 = _sha256_file(capture_path)
    reference_sha256 = _sha256_file(reference_path)
    capture_event = journal[_EVENT_ORDER.index("capture_authenticated")]
    if (
        capture_event["data"].get("capture_sha256") != capture_sha256
        or capture_event["data"].get("reference_sha256") != reference_sha256
    ):
        raise S48EngineeringAcquisitionError(
            "capture/reference files contradict authenticated journal hashes"
        )
    recorder_started = journal[_EVENT_ORDER.index("recorder_started")]
    recorder_ready = journal[_EVENT_ORDER.index("recorder_ready")]
    playback_started = journal[_EVENT_ORDER.index("playback_started")]
    planned = journal[_EVENT_ORDER.index("playback_stop_planned")]
    playback_terminated = journal[_EVENT_ORDER.index("playback_terminated")]
    recorder_terminated = journal[_EVENT_ORDER.index("recorder_terminated")]
    observed_process = {
        "capture_sha256": capture_sha256,
        "reference_sha256": reference_sha256,
        "capture_started_monotonic_ns": recorder_ready["observed_monotonic_ns"],
        "recorder_ready_monotonic_ns": recorder_ready["observed_monotonic_ns"],
        "playback_started_monotonic_ns": playback_started["observed_monotonic_ns"],
        "planned_playback_stop_monotonic_ns": planned["data"].get(
            "planned_monotonic_ns"
        ),
        "playback_terminated_monotonic_ns": playback_terminated[
            "observed_monotonic_ns"
        ],
        "recorder_terminated_monotonic_ns": recorder_terminated[
            "observed_monotonic_ns"
        ],
        "recorder_exit_status": recorder_terminated["data"].get("exit_status"),
        "playback_exit_status": playback_terminated["data"].get("exit_status"),
        "recorder_controller_requested_termination": recorder_terminated["data"].get(
            "controller_requested_termination"
        ),
        "recorder_controller_requested_signal": recorder_terminated["data"].get(
            "controller_requested_signal"
        ),
        "playback_controller_requested_termination": playback_terminated["data"].get(
            "controller_requested_termination"
        ),
        "playback_controller_requested_signal": playback_terminated["data"].get(
            "controller_requested_signal"
        ),
        "device_profile_id": capture_event["data"].get("device_profile_id"),
        "channel_map": capture_event["data"].get("channel_map"),
        "process_identity_consistent": (
            recorder_started["data"].get("pid")
            == recorder_ready["data"].get("pid")
            == recorder_terminated["data"].get("pid")
            and playback_started["data"].get("pid")
            == playback_terminated["data"].get("pid")
        ),
    }
    report = evaluate_presealing_gate_v2(
        capture,
        reference_channels,
        sample_rate_hz=capture_rate,
        observed_process=observed_process,
        manifest_sha256=expected_manifest_sha256,
        process_journal_head_sha256=str(capture_event["event_sha256"]),
        config=config,
        dry_run=dry_run,
    )
    try:
        schema = json.loads(
            (repo_root.resolve() / REPORT_SCHEMA_PATH_V2).read_text(encoding="utf-8")
        )
        jsonschema.validate(report, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise S48EngineeringAcquisitionError(
            f"v2 pre-sealing report validation failure: {exc}"
        ) from exc
    return report


def run_supported_engineering_acquisition(
    *,
    backend: Any,
    repo_root: Path,
    capture_path: Path,
    reference_path: Path,
    manifest: Mapping[str, Any],
    expected_manifest_sha256: str,
    journal_path: Path,
    retry_report_path: Path,
    candidate_seal_path: Path,
    clearance_registry_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the one supported recorder-to-engineering-candidate-seal path."""

    root = repo_root.resolve()
    _validate_manifest(manifest, expected_manifest_sha256)
    for operational_path in (
        capture_path,
        journal_path,
        retry_report_path,
        candidate_seal_path,
        clearance_registry_path,
    ):
        if operational_path.resolve().is_relative_to(root):
            raise S48EngineeringAcquisitionError(
                "engineering operational files must remain outside the repository"
            )
    if journal_path.exists():
        raise S48EngineeringAcquisitionError(
            "refusing to reuse an existing engineering process journal"
        )
    if _sha256_file(reference_path) != manifest["reference_wav_sha256"]:
        raise S48EngineeringAcquisitionError(
            "reference WAV does not match the frozen precollection manifest"
        )
    journal: list[dict[str, Any]] = []

    def observe(
        event_type: str,
        data: Mapping[str, Any],
        *,
        observed_monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        event = append_engineering_journal_event(
            journal,
            manifest_anchor_sha256=expected_manifest_sha256,
            event_type=event_type,
            observed_monotonic_ns=(
                int(backend.monotonic_ns())
                if observed_monotonic_ns is None
                else observed_monotonic_ns
            ),
            data=data,
        )
        _append_json_line(journal_path, event)
        return event

    observe(
        "capture_controller_started",
        {
            "identity": manifest["capture_controller_identity"],
            "version": manifest["capture_controller_version"],
            "pid": os.getpid(),
        },
    )
    command = backend.prepare_playback(reference_path)
    recorder = backend.start_recorder(capture_path)
    observe("recorder_started", recorder)
    ready = backend.wait_recorder_ready(recorder)
    recorder_ready_event = observe(
        "recorder_ready",
        {"pid": recorder.get("pid"), "ready": bool(ready)},
    )
    if ready is not True:
        raise S48EngineeringAcquisitionError("recorder did not become ready")
    capture_start_ns = int(recorder_ready_event["observed_monotonic_ns"])
    config = load_presealing_config_v2(root)
    playback_start_ns = capture_start_ns + round(
        config["playback_start_s"] * 1_000_000_000
    )
    planned_stop_ns = capture_start_ns + round(
        config["playback_stop_s"] * 1_000_000_000
    )
    capture_stop_ns = capture_start_ns + round(
        config["capture_duration_s"] * 1_000_000_000
    )
    observe("playback_commanded", command)
    backend.wait_until(playback_start_ns)
    playback = backend.start_playback(command)
    playback_observed_ns = playback.pop(
        "observed_start_monotonic_ns",
        None,
    )
    observe(
        "playback_started",
        playback,
        observed_monotonic_ns=playback_observed_ns,
    )
    observe(
        "playback_stop_planned",
        {"planned_monotonic_ns": planned_stop_ns},
    )
    backend.wait_until(planned_stop_ns)
    playback_status = backend.stop_playback(playback)
    playback_observed_ns = playback_status.pop(
        "observed_termination_monotonic_ns",
        None,
    )
    observe(
        "playback_terminated",
        playback_status,
        observed_monotonic_ns=playback_observed_ns,
    )
    backend.wait_until(capture_stop_ns)
    recorder_status = backend.stop_recorder(recorder)
    recorder_observed_ns = recorder_status.pop(
        "observed_termination_monotonic_ns",
        None,
    )
    if recorder_observed_ns is None:
        producer_duration_ns = recorder_status.get(
            "producer_capture_duration_ns"
        )
        if (
            isinstance(producer_duration_ns, bool)
            or not isinstance(producer_duration_ns, int)
            or producer_duration_ns <= 0
        ):
            raise S48EngineeringAcquisitionError(
                "recorder omitted authenticated producer duration"
            )
        recorder_observed_ns = capture_start_ns + producer_duration_ns
    observe(
        "recorder_terminated",
        recorder_status,
        observed_monotonic_ns=recorder_observed_ns,
    )
    if not capture_path.is_file():
        raise S48EngineeringAcquisitionError("recorder produced no capture WAV")
    observe(
        "capture_authenticated",
        {
            "capture_sha256": _sha256_file(capture_path),
            "reference_sha256": _sha256_file(reference_path),
            "device_profile_id": manifest["device_profile_id"],
            "channel_map": manifest["channel_map"],
            "gate_configuration_sha256": manifest["gate_configuration_sha256"],
            "detector_configuration_sha256": manifest["detector_configuration_sha256"],
        },
    )
    report = run_presealing_gate_from_engineering_files(
        capture_path=capture_path,
        reference_path=reference_path,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=expected_manifest_sha256,
        repo_root=root,
        dry_run=dry_run,
    )
    observe(
        "gate_evaluated",
        {
            "report_sha256": canonical_sha256(report),
            "decision": report["decision"],
        },
    )
    if report["decision"] != "PASS":
        _write_new_json(retry_report_path, report)
        return {
            "decision": "RETRY_REQUIRED",
            "report": report,
            "clearance": None,
            "candidate_seal": None,
            "journal_head_sha256": journal[-1]["event_sha256"],
        }
    clearance = create_candidate_engineering_clearance(
        report,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    observe(
        "candidate_clearance_created",
        {"clearance_sha256": clearance["clearance_sha256"]},
    )
    candidate_seal = seal_engineering_candidate(
        capture_path=capture_path,
        reference_path=reference_path,
        report=report,
        clearance=clearance,
        manifest=manifest,
        journal=journal,
        expected_manifest_sha256=expected_manifest_sha256,
        candidate_seal_path=candidate_seal_path,
        clearance_registry_path=clearance_registry_path,
        dry_run=dry_run,
    )
    return {
        "decision": "PASS",
        "report": report,
        "clearance": clearance,
        "candidate_seal": candidate_seal,
        "journal_head_sha256": journal[-1]["event_sha256"],
    }


def _validate_manifest(
    manifest: Mapping[str, Any],
    expected_manifest_sha256: str,
) -> None:
    if not _is_sha256(expected_manifest_sha256):
        raise S48EngineeringAcquisitionError("expected manifest anchor is invalid")
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    _validate_manifest_payload(payload)
    if (
        set(manifest) != _MANIFEST_FIELDS | {"manifest_sha256"}
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or manifest.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise S48EngineeringAcquisitionError(
            "precollection manifest does not match the external anchor"
        )


def _validate_manifest_payload(payload: Mapping[str, Any]) -> None:
    if (
        set(payload) != _MANIFEST_FIELDS
        or payload.get("schema") != MANIFEST_SCHEMA
        or not isinstance(payload.get("code_head"), str)
        or len(payload["code_head"]) != 40
        or not all(
            character in "0123456789abcdef" for character in payload["code_head"]
        )
        or not all(
            _is_sha256(payload.get(key))
            for key in (
                "reference_wav_sha256",
                "gate_configuration_sha256",
                "detector_configuration_sha256",
            )
        )
        or not isinstance(payload.get("channel_map"), list)
        or not payload["channel_map"]
        or not all(isinstance(item, str) and item for item in payload["channel_map"])
        or not all(
            isinstance(payload.get(key), str) and payload[key]
            for key in (
                "environment_identity",
                "device_profile_id",
                "protocol_id",
                "capture_controller_identity",
                "capture_controller_version",
            )
        )
    ):
        raise S48EngineeringAcquisitionError(
            "engineering precollection manifest payload is invalid"
        )


def _validate_report_for_clearance(report: Mapping[str, Any]) -> None:
    provenance = report.get("input_provenance")
    authority = report.get("authority")
    if (
        report.get("schema") != "ias.s4_8.presealing_gate_report.v2"
        or report.get("decision") not in {"PASS", "RETRY_REQUIRED"}
        or not isinstance(report.get("reasons"), list)
        or not isinstance(provenance, Mapping)
        or provenance.get("outcome_fields_read") != []
        or not isinstance(authority, Mapping)
        or any(authority.values())
    ):
        raise S48EngineeringAcquisitionError(
            "pre-sealing v2 report is invalid or claims forbidden authority"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise S48EngineeringAcquisitionError(
            f"engineering input read failure: {exc}"
        ) from exc
    return digest.hexdigest()


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise S48EngineeringAcquisitionError(
            f"refusing to overwrite engineering operational file: {path}"
        ) from exc


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise S48EngineeringAcquisitionError(
            f"engineering journal append failure: {exc}"
        ) from exc


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _start_process(arguments: Sequence[str]) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise S48EngineeringAcquisitionError(
            f"engineering subprocess start failure: {exc}"
        ) from exc


def _terminate_process(
    process: subprocess.Popen[bytes],
    timeout_s: float,
) -> tuple[int, bool]:
    status = process.poll()
    if status is not None:
        return int(status), False
    process.terminate()
    try:
        return int(process.wait(timeout=timeout_s)), True
    except subprocess.TimeoutExpired:
        process.kill()
        return int(process.wait(timeout=timeout_s)), True
