"""S4.2 configuration, lifecycle, timing, and evidence validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import time
import uuid
import wave
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from isaac_audio_sensors.core.dataset.atomic import (
    CancellationToken,
    StagedFile,
    publish_file,
    write_json_atomic,
)

CONFIG_SCHEMA = "ias.s4_2.acquisition_config.v1"
ATTEMPT_SCHEMA = "ias.s4_2.attempt_manifest.v1"
VALIDATION_SCHEMA = "ias.s4_2.validation_report.v1"
ALIGNMENT_SCHEMA = "ias.s4_2.alignment.v1"
LIFECYCLE_SCHEMA = "ias.s4_2.lifecycle.v1"

EXPECTED_CHANNEL_ORDER = (
    "conference",
    "asr",
    "raw_microphone_0",
    "raw_microphone_1",
    "raw_microphone_2",
    "raw_microphone_3",
)
EXPECTED_PROJECT_AXES = {
    "x": "forward",
    "y": "operator_right_facing_camera_zed_camera_left",
    "z": "up",
}
EXPECTED_BEARING_DEFINITION = (
    "degrees counterclockwise from +X toward +Y viewed from above"
)
S42_ACCEPTANCE_AMENDMENT_ID = "S4.2-PRECAPTURE-AMENDMENT-2026-07-20-A"
ALLOWED_LIFECYCLE = {
    "preflight",
    "recording",
    "finalizing",
    "accepted",
    "rejected",
    "failed",
    "interrupted",
}
TERMINAL_LIFECYCLE = {"accepted", "rejected", "failed", "interrupted"}
_TRANSITIONS = {
    None: {"preflight"},
    "preflight": {"recording", "rejected", "failed", "interrupted"},
    "recording": {"finalizing", "rejected", "failed", "interrupted"},
    "finalizing": {"accepted", "rejected", "failed", "interrupted"},
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One located fail-closed finding."""

    code: str
    path: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Machine-readable semantic/integrity result."""

    checks: tuple[dict[str, Any], ...]
    issues: tuple[ValidationIssue, ...]

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VALIDATION_SCHEMA,
            "status": "passed" if self.passed else "failed",
            "checks": list(self.checks),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class S42Error(RuntimeError):
    """Located S4.2 acquisition or evidence failure."""


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 for one finalized file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    """Load one JSON object and reject other top-level types."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S42Error(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise S42Error(f"{path}: top-level JSON value must be an object")
    return payload


def _at(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return None
        value = value[component]
    return value


def _required(
    payload: Mapping[str, Any],
    paths: Iterable[str],
    issues: list[ValidationIssue],
) -> None:
    for path in paths:
        value = _at(payload, path)
        if value is None or value == "" or value == []:
            issues.append(
                ValidationIssue(
                    "missing_required_metadata",
                    path,
                    "required S4.2 metadata is missing",
                )
            )


def _expect_equal(
    payload: Mapping[str, Any],
    path: str,
    expected: Any,
    issues: list[ValidationIssue],
    code: str = "frozen_value_mismatch",
) -> None:
    actual = _at(payload, path)
    if actual != expected:
        issues.append(
            ValidationIssue(code, path, f"expected {expected!r}, got {actual!r}")
        )


def _is_positive_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def validate_configuration(
    payload: Mapping[str, Any], *, require_ready: bool = True
) -> ValidationReport:
    """Validate the frozen S4.2 configuration before any hardware access."""

    issues: list[ValidationIssue] = []
    checks: list[dict[str, Any]] = []
    required = [
        "schema",
        "session.attempt_root",
        "session.duration_s",
        "session.minimum_local_free_bytes",
        "session.minimum_pi_free_bytes",
        "respeaker.ssh_alias",
        "respeaker.device",
        "respeaker.model",
        "respeaker.serial",
        "respeaker.firmware",
        "respeaker.channel_count",
        "respeaker.sample_rate_hz",
        "respeaker.sample_format",
        "respeaker.channel_order",
        "zed.model",
        "zed.serial",
        "zed.sdk_version",
        "zed.camera_firmware",
        "zed.sensor_firmware",
        "zed.resolution",
        "zed.fps",
        "zed.depth_mode",
        "zed.coordinate_units",
        "zed.coordinate_system",
        "mac.ssh_alias",
        "mac.inventory_path",
        "mac.inventory_sha256",
        "mac.model_identifier",
        "mac.os_version",
        "mac.os_build",
        "mac.output_device",
        "mac.system_volume_percent",
        "mac.afplay_gain",
        "mac.reference_path",
        "reference.local_path",
        "reference.metadata_path",
        "reference.sha256",
        "fixture.fixture_id",
        "fixture.room_id",
        "coordinate_frame.frame_name",
        "coordinate_frame.axes",
        "alignment.method",
        "alignment.maximum_uncertainty_ms",
        "acceptance_amendment.id",
        "acceptance_amendment.record_path",
        "raw_evidence.machine_local_root",
        "raw_evidence.retention",
        "raw_evidence.checksum_command",
        "raw_evidence.semantic_validation_command",
    ]
    if require_ready:
        required.extend(
            [
                "mac.preflight_report_path",
                "acceptance_amendment.record_sha256",
                "source.position_m",
                "source.distance_from_rig_origin_m",
                "source.distance_provenance",
                "source.bearing_deg_counterclockwise_from_positive_x",
                "source.speaker_height_m",
                "source.delta_x_m",
                "source.delta_y_m",
                "source.delta_z_m",
                "source.vertical_offset_uncertainty_m",
                "source.orientation_deg",
                "source.orientation_measurement_classification",
                "source.lid_angle_deg",
                "source.lid_state",
                "source.relative_side",
                "source.screen_heading",
                "alignment.event_object",
                "alignment.event_position_m",
                "alignment.impact_tool",
                "environment.occupancy",
                "environment.noise_state",
                "environment.operator_notes",
            ]
        )
    _required(payload, required, issues)

    frozen = {
        "schema": CONFIG_SCHEMA,
        "respeaker.ssh_alias": "elab-raspberrypi5",
        "respeaker.device": "hw:CARD=Array,DEV=0",
        "respeaker.model": "ReSpeaker XVF3800 USB 4-Mic Array",
        "respeaker.serial": "114993701261100454",
        "respeaker.firmware": "2.08",
        "respeaker.channel_count": 6,
        "respeaker.sample_rate_hz": 16_000,
        "respeaker.sample_format": "S16_LE",
        "respeaker.channel_order": list(EXPECTED_CHANNEL_ORDER),
        "zed.model": "ZED 2i",
        "zed.serial": "39011785",
        "zed.sdk_version": "5.4.0",
        "zed.camera_firmware": "1523",
        "zed.sensor_firmware": "777",
        "zed.resolution": "HD720",
        "zed.fps": 30,
        "zed.depth_mode": "PERFORMANCE",
        "zed.coordinate_units": "m",
        "zed.coordinate_system": "RIGHT_HANDED_Y_UP",
        "mac.ssh_alias": "patrizios-macbook",
        "mac.model_identifier": "MacBookPro18,1",
        "mac.os_version": "26.5.2",
        "mac.os_build": "25F84",
        "mac.output_device": "MacBook Pro Speakers",
        "mac.system_volume_percent": 63,
        "mac.afplay_gain": 1.0,
        "mac.inventory_sha256": (
            "2360b24977dd25e48ebe9b975a4158dd407151d7bb4de50a8f3ab7f6eb29466d"
        ),
        "fixture.fixture_id": "S4_TEMP_DESKTOP_FIXTURE_REV0",
        "fixture.room_id": "WANG_2022_DESK_NEAR_ENTRANCE",
        "coordinate_frame.frame_name": "F_project",
        "coordinate_frame.origin": "ZED stereo-lens midpoint",
        "coordinate_frame.axes": EXPECTED_PROJECT_AXES,
        "coordinate_frame.position_units": "m",
        "coordinate_frame.bearing_definition": EXPECTED_BEARING_DEFINITION,
        "acceptance_amendment.id": S42_ACCEPTANCE_AMENDMENT_ID,
        "acceptance_amendment.record_path": (
            "docs/development/specs/"
            "s4_2_pre_capture_acceptance_amendment.v1.json"
        ),
        "session.attempt_root": "dataset/S4.2/attempts",
        "raw_evidence.machine_local_root": "dataset/S4.2",
        "raw_evidence.retention": "machine_local_gitignored",
        "raw_evidence.fresh_clone_available": False,
        "raw_evidence.machine_loss_risk_acknowledged": True,
        "raw_evidence.off_machine_storage_authorized": False,
        "raw_evidence.replicated": False,
        "alignment.method": "visible_audible_impact",
        "alignment.maximum_uncertainty_ms": 50.0,
    }
    for path, expected in frozen.items():
        _expect_equal(payload, path, expected, issues)

    duration = _at(payload, "session.duration_s")
    if not _is_positive_number(duration) or not 15 <= float(duration) <= 60:
        issues.append(
            ValidationIssue(
                "invalid_duration",
                "session.duration_s",
                "bounded duration must be within [15, 60] seconds",
            )
        )
    for path in (
        "session.minimum_local_free_bytes",
        "session.minimum_pi_free_bytes",
    ):
        if not _is_positive_number(_at(payload, path)):
            issues.append(
                ValidationIssue(
                    "invalid_disk_threshold", path, "must be a positive number"
                )
            )
    checksum_paths = ["reference.sha256"]
    if require_ready:
        checksum_paths.append("acceptance_amendment.record_sha256")
    for checksum_path in checksum_paths:
        checksum = _at(payload, checksum_path)
        try:
            if not isinstance(checksum, str) or len(checksum) != 64:
                raise ValueError
            bytes.fromhex(checksum)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "invalid_checksum",
                    checksum_path,
                    "must be a 64-character SHA-256 hex digest",
                )
            )

    for path in (
        "session.attempt_root",
        "reference.local_path",
        "reference.metadata_path",
        "mac.inventory_path",
        "acceptance_amendment.record_path",
        "raw_evidence.machine_local_root",
    ):
        value = _at(payload, path)
        if isinstance(value, str) and ".." in Path(value).parts:
            issues.append(
                ValidationIssue(
                    "unsafe_path", path, "parent traversal is not permitted"
                )
            )

    if require_ready:
        ready_frozen = {
            "source.position_m": [0.0, 0.9, -0.135],
            "source.delta_x_m": 0.0,
            "source.delta_y_m": 0.9,
            "source.delta_z_m": -0.135,
            "source.bearing_deg_counterclockwise_from_positive_x": 90.0,
            "source.speaker_height_m": 0.710,
            "source.vertical_offset_uncertainty_m": 0.010,
            "source.orientation_deg": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
            "source.orientation_measurement_classification": (
                "practical_visual_placement_not_metrology"
            ),
            "source.lid_angle_deg": 90.0,
            "source.relative_side": "operator_right_facing_camera",
            "alignment.event_object": "plain unmarked blue wastebasket",
            "alignment.event_position_m": [1.15, 0.0, -0.4],
            "alignment.impact_tool": "long plain paper roll",
            "raw_evidence.machine_loss_risk_acknowledged": True,
            "raw_evidence.off_machine_storage_authorized": False,
            "raw_evidence.fresh_clone_available": False,
            "raw_evidence.replicated": False,
        }
        for path, expected in ready_frozen.items():
            _expect_equal(payload, path, expected, issues)

        for path in (
            "fixture.marked_footprint_confirmed",
            "fixture.no_component_moved",
            "fixture.microphone_openings_clear",
            "fixture.zed_fov_clear",
            "fixture.cables_safe",
            "environment.privacy_scene_cleared",
            "respeaker.channel_order_verified_each_take",
            "mac.balance_centered_confirmed",
            "mac.system_ui_sounds_disabled_or_prevented",
            "mac.work_focus_active_confirmed",
            "mac.notifications_suppressed_confirmed",
            "mac.mono_audio_off_confirmed",
            "mac.background_sounds_off_confirmed",
        ):
            if _at(payload, path) is not True:
                issues.append(
                    ValidationIssue(
                        "operator_confirmation_missing",
                        path,
                        "must be explicitly true for an accepted attempt",
                    )
                )

        position = _at(payload, "source.position_m")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or any(not isinstance(v, (int, float)) for v in position)
            or any(not math.isfinite(float(v)) for v in position)
        ):
            issues.append(
                ValidationIssue(
                    "invalid_position",
                    "source.position_m",
                    "must be three finite numbers in F_project meters",
                )
            )
        else:
            for index, path in enumerate(
                ("source.delta_x_m", "source.delta_y_m", "source.delta_z_m")
            ):
                declared = _at(payload, path)
                if not isinstance(declared, (int, float)) or not math.isclose(
                    float(declared), float(position[index]), abs_tol=1e-12
                ):
                    issues.append(
                        ValidationIssue(
                            "inconsistent_source_delta",
                            path,
                            f"must equal source.position_m[{index}]",
                        )
                    )
            declared_distance = _at(payload, "source.distance_from_rig_origin_m")
            computed_distance = math.sqrt(sum(float(v) ** 2 for v in position))
            if not _is_positive_number(declared_distance) or not math.isclose(
                computed_distance, float(declared_distance), abs_tol=0.02
            ):
                issues.append(
                    ValidationIssue(
                        "inconsistent_source_distance",
                        "source.distance_from_rig_origin_m",
                        f"position implies {computed_distance:.4f} m; "
                        "tolerance is 0.02 m",
                    )
                )
        orientation = _at(payload, "source.orientation_deg")
        if (
            not isinstance(orientation, Mapping)
            or set(orientation) != {"yaw", "pitch", "roll"}
            or any(
                not isinstance(value, (int, float)) or not math.isfinite(float(value))
                for value in orientation.values()
            )
        ):
            issues.append(
                ValidationIssue(
                    "invalid_orientation",
                    "source.orientation_deg",
                    "must contain finite yaw, pitch, and roll degrees",
                )
            )
        for path, minimum, maximum in (
            ("source.bearing_deg_counterclockwise_from_positive_x", 0.0, 360.0),
            ("source.lid_angle_deg", 0.0, 180.0),
        ):
            value = _at(payload, path)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                issues.append(
                    ValidationIssue(
                        "invalid_angle",
                        path,
                        f"must be finite and within [{minimum}, {maximum}] degrees",
                    )
                )
        if _at(payload, "source.relative_side") not in {
            "front",
            "behind",
            "left",
            "right",
            "operator_left_facing_camera",
            "operator_right_facing_camera",
        }:
            issues.append(
                ValidationIssue(
                    "invalid_relative_side",
                    "source.relative_side",
                    "must be front, behind, left, or right",
                )
            )
        if not _is_positive_number(_at(payload, "source.speaker_height_m")):
            issues.append(
                ValidationIssue(
                    "invalid_height",
                    "source.speaker_height_m",
                    "must be a positive finite number in meters",
                )
            )
        if not _is_positive_number(
            _at(payload, "source.vertical_offset_uncertainty_m")
        ):
            issues.append(
                ValidationIssue(
                    "invalid_uncertainty",
                    "source.vertical_offset_uncertainty_m",
                    "must be a positive finite number in meters",
                )
            )

    checks.append(
        {
            "id": "configuration_semantics",
            "status": "passed" if not issues else "failed",
            "require_ready": require_ready,
        }
    )
    return ValidationReport(tuple(checks), tuple(issues))


def normalize_configuration(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Round-trip a configuration through canonical JSON-compatible values."""

    return json.loads(json.dumps(dict(payload), sort_keys=True))


def validate_mac_preflight(
    report: Mapping[str, Any], configuration: Mapping[str, Any]
) -> ValidationReport:
    """Compare one current read-only Mac report to the frozen configuration."""

    issues: list[ValidationIssue] = []
    _expect_equal(report, "schema", "ias.s4_2.mac_preflight.v1", issues)
    _expect_equal(report, "read_only", True, issues)
    comparisons = {
        "hardware.model_identifier": _at(configuration, "mac.model_identifier"),
        "os.version": _at(configuration, "mac.os_version"),
        "os.build": _at(configuration, "mac.os_build"),
        "audio_output.device_name": _at(configuration, "mac.output_device"),
        "audio_output.channel_count": 2,
        "audio_output.nominal_sample_rate_hz": 48_000,
        "volume.output_volume": _at(configuration, "mac.system_volume_percent"),
        "volume.output_muted": False,
        "power.on_ac_power": True,
        "reference_wav.sha256": _at(configuration, "reference.sha256"),
        "reference_wav.hash_matches": True,
        "reference_wav.channel_count": 1,
        "reference_wav.sample_rate_hz": 48_000,
        "reference_wav.bits_per_sample": 16,
        "reference_wav.duration_s": 9.5,
        "reference_wav.afinfo_exit_status": 0,
        "reference_wav.afinfo_lpcm_detected": True,
        "focus_and_notifications.work_focus_active": True,
        "focus_and_notifications.notifications_suppressed": True,
        "controllable_audio_settings.background_sounds": False,
    }
    for path, expected in comparisons.items():
        _expect_equal(report, path, expected, issues, "mac_preflight_mismatch")
    collected_at = report.get("collected_at")
    try:
        collected = datetime.fromisoformat(str(collected_at))
        age_s = (
            datetime.now(timezone.utc) - collected.astimezone(timezone.utc)
        ).total_seconds()
        if age_s < 0 or age_s > 600:
            issues.append(
                ValidationIssue(
                    "stale_mac_preflight",
                    "collected_at",
                    f"report age {age_s:.3f} s is outside [0, 600] s",
                )
            )
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "invalid_mac_preflight_timestamp",
                "collected_at",
                repr(collected_at),
            )
        )
    manual = {
        "mac.balance_centered_confirmed": True,
        "mac.system_ui_sounds_disabled_or_prevented": True,
        "mac.work_focus_active_confirmed": True,
        "mac.notifications_suppressed_confirmed": True,
        "mac.mono_audio_off_confirmed": True,
        "mac.background_sounds_off_confirmed": True,
    }
    for path, expected in manual.items():
        _expect_equal(
            configuration,
            path,
            expected,
            issues,
            "manual_mac_confirmation_missing",
        )
    return ValidationReport(
        (
            {
                "id": "mac_preflight",
                "status": "passed" if not issues else "failed",
            },
        ),
        tuple(issues),
    )


class AttemptLifecycle:
    """Atomic, append-preserving lifecycle for one never-overwritten attempt."""

    def __init__(
        self,
        attempts_root: str | Path,
        *,
        attempt_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self.attempt_id = attempt_id or self.new_attempt_id()
        if not self.valid_attempt_id(self.attempt_id):
            raise ValueError("attempt_id contains unsupported characters")
        self.root = Path(attempts_root) / self.attempt_id
        if self.root.exists():
            raise FileExistsError(f"attempt already exists: {self.root}")
        self.root.mkdir(parents=True, exist_ok=False)
        self.cancellation_token = cancellation_token or CancellationToken()
        self._events: list[dict[str, Any]] = []
        self._state: str | None = None
        self.transition("preflight", reason="attempt directory created")

    @classmethod
    def open_existing(cls, attempt_root: str | Path) -> AttemptLifecycle:
        """Resume lifecycle bookkeeping without altering retained evidence."""

        root = Path(attempt_root)
        payload = load_json(root / "lifecycle.json")
        if payload.get("schema") != LIFECYCLE_SCHEMA:
            raise S42Error(f"{root}: incompatible lifecycle schema")
        attempt_id = payload.get("attempt_id")
        state = payload.get("state")
        events = payload.get("events")
        if (
            not isinstance(attempt_id, str)
            or root.name != attempt_id
            or state not in ALLOWED_LIFECYCLE
            or not isinstance(events, list)
        ):
            raise S42Error(f"{root}: malformed lifecycle")
        instance = cls.__new__(cls)
        instance.attempt_id = attempt_id
        instance.root = root
        instance.cancellation_token = CancellationToken()
        instance._events = list(events)
        instance._state = state
        return instance

    @staticmethod
    def valid_attempt_id(value: str) -> bool:
        return bool(value) and all(
            character.isalnum() or character in "-_." for character in value
        )

    @staticmethod
    def new_attempt_id() -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"s4_2_{stamp}_{uuid.uuid4().hex[:12]}"

    @property
    def state(self) -> str:
        if self._state is None:
            raise RuntimeError("lifecycle has no state")
        return self._state

    def transition(self, state: str, *, reason: str) -> None:
        if state not in ALLOWED_LIFECYCLE:
            raise ValueError(f"unknown lifecycle state: {state}")
        if self._state in TERMINAL_LIFECYCLE:
            raise S42Error(f"terminal attempt cannot transition from {self._state}")
        if state not in _TRANSITIONS.get(self._state, set()):
            raise S42Error(f"invalid lifecycle transition {self._state!r} -> {state!r}")
        now = datetime.now().astimezone()
        self._state = state
        self._events.append(
            {
                "state": state,
                "reason": reason,
                "wall_time_utc": now.astimezone(timezone.utc).isoformat(),
                "wall_time_local": now.isoformat(),
                "monotonic_ns": time.monotonic_ns(),
            }
        )
        write_json_atomic(
            self.root / "lifecycle.json",
            {
                "schema": LIFECYCLE_SCHEMA,
                "attempt_id": self.attempt_id,
                "state": state,
                "events": self._events,
            },
            cancellation_token=self.cancellation_token,
        )

    def write_configuration(self, payload: Mapping[str, Any]) -> None:
        write_json_atomic(
            self.root / "normalized_configuration.json",
            normalize_configuration(payload),
            cancellation_token=self.cancellation_token,
        )


def promote_finalized_file(
    source: str | Path,
    destination: str | Path,
    *,
    cancellation_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Stream a finalized producer file through an S2.2 staged publication."""

    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise S42Error(f"finalized source is missing: {source_path}")
    if destination_path.exists():
        raise FileExistsError(f"destination already exists: {destination_path}")
    staged = StagedFile(
        destination_path.parent / "_staging",
        f"{destination_path.name}.incoming",
        cancellation_token=cancellation_token,
    )
    try:
        with source_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                staged.append(block)
        record = publish_file(staged, destination_path)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise
    record["path"] = destination_path.as_posix()
    return record


def disk_space_check(path: str | Path, minimum_free_bytes: int) -> dict[str, Any]:
    """Return a fail-closed local disk-space observation."""

    destination = Path(path)
    probe = destination if destination.exists() else destination.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {
        "path": str(destination),
        "free_bytes": usage.free,
        "minimum_free_bytes": int(minimum_free_bytes),
        "passed": usage.free >= int(minimum_free_bytes),
    }


def inspect_six_channel_wav(
    path: str | Path,
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    """Stream-validate the frozen six-channel ReSpeaker PCM contract."""

    wav_path = Path(path)
    issues: list[ValidationIssue] = []
    if not wav_path.is_file():
        return {}, (ValidationIssue("missing_audio", str(wav_path), "WAV is missing"),)
    sums = [0] * 6
    peaks = [0] * 6
    frames = 0
    current_clip_runs = [0] * 6
    maximum_clip_runs = [0] * 6
    try:
        with wave.open(str(wav_path), "rb") as reader:
            properties = {
                "channel_count": reader.getnchannels(),
                "sample_rate_hz": reader.getframerate(),
                "sample_width_bytes": reader.getsampwidth(),
                "compression": reader.getcomptype(),
                "declared_frame_count": reader.getnframes(),
            }
            if properties["channel_count"] != 6:
                issues.append(
                    ValidationIssue(
                        "wrong_channel_count",
                        str(wav_path),
                        f"expected 6, got {properties['channel_count']}",
                    )
                )
            if properties["sample_rate_hz"] != 16_000:
                issues.append(
                    ValidationIssue(
                        "wrong_sample_rate",
                        str(wav_path),
                        f"expected 16000, got {properties['sample_rate_hz']}",
                    )
                )
            if (
                properties["sample_width_bytes"] != 2
                or properties["compression"] != "NONE"
            ):
                issues.append(
                    ValidationIssue(
                        "wrong_sample_format",
                        str(wav_path),
                        "expected uncompressed signed PCM16 little-endian",
                    )
                )
            if issues:
                return properties, tuple(issues)
            while True:
                raw = reader.readframes(4096)
                if not raw:
                    break
                frame_bytes = 6 * 2
                if len(raw) % frame_bytes:
                    issues.append(
                        ValidationIssue(
                            "truncated_wav",
                            str(wav_path),
                            "decoded payload ends inside an interleaved frame",
                        )
                    )
                    break
                sample_values = struct.unpack(f"<{len(raw) // 2}h", raw)
                for offset in range(0, len(sample_values), 6):
                    frames += 1
                    for channel in range(6):
                        sample = sample_values[offset + channel]
                        absolute = abs(sample)
                        sums[channel] += sample * sample
                        peaks[channel] = max(peaks[channel], absolute)
                        if absolute >= 32_734:
                            current_clip_runs[channel] += 1
                            maximum_clip_runs[channel] = max(
                                maximum_clip_runs[channel],
                                current_clip_runs[channel],
                            )
                        else:
                            current_clip_runs[channel] = 0
            if frames != properties["declared_frame_count"]:
                issues.append(
                    ValidationIssue(
                        "truncated_wav",
                        str(wav_path),
                        "header declares "
                        f"{properties['declared_frame_count']} frames; "
                        f"decoded {frames}",
                    )
                )
    except (EOFError, OSError, wave.Error) as exc:
        return {}, (
            ValidationIssue(
                "malformed_wav", str(wav_path), f"{type(exc).__name__}: {exc}"
            ),
        )

    rms = [math.sqrt(total / frames) if frames else 0.0 for total in sums]
    for channel, value in enumerate(rms):
        if value < 1.0:
            issues.append(
                ValidationIssue(
                    "silent_channel",
                    f"audio.channel[{channel}]",
                    f"RMS {value:.6f} PCM16 count is below 1.0",
                )
            )
    for channel, run in enumerate(maximum_clip_runs):
        if run >= 4_000:
            issues.append(
                ValidationIssue(
                    "sustained_clipping",
                    f"audio.channel[{channel}]",
                    f"{run} consecutive samples at or above 0.999 full scale",
                )
            )
    properties.update(
        {
            "decoded_frame_count": frames,
            "duration_s": frames / 16_000,
            "per_channel_rms_pcm16": rms,
            "per_channel_peak_pcm16": peaks,
            "per_channel_maximum_clip_run_samples": maximum_clip_runs,
            "sha256": sha256_file(wav_path),
            "byte_size": wav_path.stat().st_size,
        }
    )
    return properties, tuple(issues)


def read_jsonl(
    path: str | Path,
) -> tuple[list[dict[str, Any]], tuple[ValidationIssue, ...]]:
    """Read JSONL without accepting blank, partial, or non-object records."""

    records: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    jsonl_path = Path(path)
    if not jsonl_path.is_file():
        return [], (
            ValidationIssue("missing_jsonl", str(jsonl_path), "JSONL is missing"),
        )
    try:
        with jsonl_path.open("rb") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.endswith(b"\n"):
                    issues.append(
                        ValidationIssue(
                            "partial_jsonl_line",
                            f"{jsonl_path}:{line_number}",
                            "line is not newline-terminated",
                        )
                    )
                    continue
                if not raw.strip():
                    issues.append(
                        ValidationIssue(
                            "blank_jsonl_line",
                            f"{jsonl_path}:{line_number}",
                            "blank lines are forbidden",
                        )
                    )
                    continue
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    issues.append(
                        ValidationIssue(
                            "corrupt_jsonl",
                            f"{jsonl_path}:{line_number}",
                            str(exc),
                        )
                    )
                    continue
                if not isinstance(record, dict):
                    issues.append(
                        ValidationIssue(
                            "invalid_jsonl_record",
                            f"{jsonl_path}:{line_number}",
                            "record must be an object",
                        )
                    )
                    continue
                records.append(record)
    except OSError as exc:
        issues.append(ValidationIssue("jsonl_io_error", str(jsonl_path), str(exc)))
    return records, tuple(issues)


def validate_zed_records(
    records: Sequence[Mapping[str, Any]], *, duration_s: float, fps: int
) -> ValidationReport:
    """Validate ZED image/depth/IMU/pose sidecar records."""

    issues: list[ValidationIssue] = []
    expected_minimum = math.floor(duration_s * fps * 0.90)
    if len(records) < expected_minimum:
        issues.append(
            ValidationIssue(
                "incomplete_zed_output",
                "zed.frames",
                f"expected at least {expected_minimum} records, got {len(records)}",
            )
        )
    device_timestamps: list[int] = []
    pose_timestamps: list[int] = []
    signatures: list[str] = []
    required = {
        "frame_index",
        "device_timestamp_ns",
        "host_wall_time_utc",
        "host_monotonic_ns",
        "image_status",
        "image_signature_sha256",
        "depth_status",
        "depth_finite_ratio",
        "depth_sample_grid_m",
        "depth_sample_grid_shape",
        "depth_sample_stride_px",
        "imu_status",
        "imu_timestamp_ns",
        "pose_status",
        "pose_timestamp_ns",
        "pose",
        "frame_name",
        "units",
    }
    for index, record in enumerate(records):
        missing = sorted(required - record.keys())
        if missing:
            issues.append(
                ValidationIssue(
                    "missing_zed_metadata",
                    f"zed.frames[{index}]",
                    f"missing keys: {missing}",
                )
            )
            continue
        if record["frame_index"] != index:
            issues.append(
                ValidationIssue(
                    "nonsequential_frame_index",
                    f"zed.frames[{index}].frame_index",
                    f"expected {index}, got {record['frame_index']!r}",
                )
            )
        for key, code in (
            ("image_status", "failed_image_retrieval"),
            ("depth_status", "failed_depth_retrieval"),
            ("imu_status", "failed_imu_retrieval"),
        ):
            if record[key] != "SUCCESS":
                issues.append(
                    ValidationIssue(
                        code, f"zed.frames[{index}].{key}", str(record[key])
                    )
                )
        if record["pose_status"] not in {"OK", "SEARCHING", "FPS_TOO_LOW"}:
            issues.append(
                ValidationIssue(
                    "failed_pose_retrieval",
                    f"zed.frames[{index}].pose_status",
                    str(record["pose_status"]),
                )
            )
        if record["frame_name"] != "F_zed_world_y_up":
            issues.append(
                ValidationIssue(
                    "invalid_coordinate_frame",
                    f"zed.frames[{index}].frame_name",
                    repr(record["frame_name"]),
                )
            )
        depth_grid = record["depth_sample_grid_m"]
        depth_shape = record["depth_sample_grid_shape"]
        if (
            not isinstance(depth_grid, list)
            or not isinstance(depth_shape, list)
            or len(depth_shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in depth_shape)
            or len(depth_grid) != depth_shape[0] * depth_shape[1]
            or not any(
                isinstance(value, (int, float)) and math.isfinite(float(value))
                for value in depth_grid
            )
        ):
            issues.append(
                ValidationIssue(
                    "invalid_depth_record",
                    f"zed.frames[{index}].depth_sample_grid_m",
                    "must be a shaped grid containing at least one finite depth "
                    "in meters",
                )
            )
        if record["depth_sample_stride_px"] != [60, 64]:
            issues.append(
                ValidationIssue(
                    "invalid_depth_stride",
                    f"zed.frames[{index}].depth_sample_stride_px",
                    repr(record["depth_sample_stride_px"]),
                )
            )
        if record["units"] != {"position": "m", "time": "ns", "angle": "rad"}:
            issues.append(
                ValidationIssue(
                    "invalid_units",
                    f"zed.frames[{index}].units",
                    repr(record["units"]),
                )
            )
        try:
            device_timestamps.append(int(record["device_timestamp_ns"]))
            pose_timestamps.append(int(record["pose_timestamp_ns"]))
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    "invalid_timestamp",
                    f"zed.frames[{index}]",
                    "device and pose timestamps must be integers",
                )
            )
        signature = record["image_signature_sha256"]
        if not isinstance(signature, str) or len(signature) != 64:
            issues.append(
                ValidationIssue(
                    "invalid_image_signature",
                    f"zed.frames[{index}].image_signature_sha256",
                    repr(signature),
                )
            )
        else:
            signatures.append(signature)
    for name, timestamps in (
        ("device", device_timestamps),
        ("pose", pose_timestamps),
    ):
        for index, (earlier, later) in enumerate(
            zip(timestamps, timestamps[1:], strict=False), 1
        ):
            if later == earlier:
                issues.append(
                    ValidationIssue(
                        "duplicate_timestamp",
                        f"zed.frames[{index}].{name}_timestamp_ns",
                        str(later),
                    )
                )
            elif later < earlier:
                issues.append(
                    ValidationIssue(
                        "nonmonotonic_timestamp",
                        f"zed.frames[{index}].{name}_timestamp_ns",
                        f"{later} follows {earlier}",
                    )
                )
    if device_timestamps and pose_timestamps:
        frame_intervals = [
            later - earlier
            for earlier, later in zip(
                device_timestamps, device_timestamps[1:], strict=False
            )
            if later > earlier
        ]
        allowed_age = max(frame_intervals, default=math.ceil(1e9 / fps))
        for index, (device, pose) in enumerate(
            zip(device_timestamps, pose_timestamps, strict=False)
        ):
            if abs(device - pose) > allowed_age:
                issues.append(
                    ValidationIssue(
                        "stale_pose",
                        f"zed.frames[{index}].pose_timestamp_ns",
                        f"pose/image timestamp difference exceeds {allowed_age} ns",
                    )
                )
    same_run = 1
    for index, (earlier, later) in enumerate(
        zip(signatures, signatures[1:], strict=False), 1
    ):
        same_run = same_run + 1 if later == earlier else 1
        if same_run > 2:
            issues.append(
                ValidationIssue(
                    "stale_zed_frame",
                    f"zed.frames[{index}].image_signature_sha256",
                    f"same content signature repeated for {same_run} frames",
                )
            )
            break
    return ValidationReport(
        (
            {
                "id": "zed_records",
                "status": "passed" if not issues else "failed",
                "record_count": len(records),
                "minimum_record_count": expected_minimum,
            },
        ),
        tuple(issues),
    )


def calculate_alignment(
    *,
    audio_event_sample_index: int,
    audio_sample_rate_hz: int,
    zed_first_timestamp_ns: int,
    zed_event_timestamp_ns: int,
    audio_localization_half_width_samples: int,
    zed_frame_interval_ns: int,
    zed_localization_half_width_frames: float,
    extra_uncertainty_ms: float = 0.0,
    event_unique: bool,
    event_visible: bool,
    event_audible: bool,
    maximum_uncertainty_ms: float = 50.0,
) -> dict[str, Any]:
    """Compute cross-system elapsed-time offset and frozen RSS uncertainty."""

    if audio_event_sample_index < 0 or audio_localization_half_width_samples < 0:
        raise ValueError("audio sample indices and half-width must be non-negative")
    if audio_sample_rate_hz <= 0 or zed_frame_interval_ns <= 0:
        raise ValueError("sample rate and ZED frame interval must be positive")
    if zed_event_timestamp_ns < zed_first_timestamp_ns:
        raise ValueError("ZED event timestamp precedes first ZED timestamp")
    if zed_localization_half_width_frames < 0 or extra_uncertainty_ms < 0:
        raise ValueError("uncertainty components must be non-negative")
    audio_elapsed_s = audio_event_sample_index / audio_sample_rate_hz
    zed_elapsed_s = (zed_event_timestamp_ns - zed_first_timestamp_ns) / 1e9
    audio_sample_ms = 1000.0 / audio_sample_rate_hz
    audio_localization_ms = (
        audio_localization_half_width_samples * 1000.0 / audio_sample_rate_hz
    )
    zed_half_frame_ms = zed_frame_interval_ns / 2e6
    zed_localization_ms = (
        zed_localization_half_width_frames * zed_frame_interval_ns / 1e6
    )
    components = {
        "audio_sample_quantization_ms": audio_sample_ms,
        "audio_localization_ms": audio_localization_ms,
        "zed_half_frame_ms": zed_half_frame_ms,
        "zed_visual_localization_ms": zed_localization_ms,
        "extra_readout_quantization_ms": extra_uncertainty_ms,
    }
    total_uncertainty_ms = math.sqrt(
        sum(component * component for component in components.values())
    )
    reasons: list[str] = []
    if not event_unique:
        reasons.append("alignment event is not unique")
    if not event_visible:
        reasons.append("alignment event is not visible in ZED evidence")
    if not event_audible:
        reasons.append("alignment event is not audible in six-channel WAV")
    if total_uncertainty_ms > maximum_uncertainty_ms:
        reasons.append(
            f"uncertainty {total_uncertainty_ms:.6f} ms exceeds "
            f"{maximum_uncertainty_ms:.6f} ms"
        )
    return {
        "schema": ALIGNMENT_SCHEMA,
        "status": "passed" if not reasons else "failed",
        "method": "visible_audible_impact",
        "audio_event_sample_index": audio_event_sample_index,
        "audio_sample_rate_hz": audio_sample_rate_hz,
        "audio_event_elapsed_s": audio_elapsed_s,
        "zed_first_timestamp_ns": zed_first_timestamp_ns,
        "zed_event_timestamp_ns": zed_event_timestamp_ns,
        "zed_event_elapsed_s": zed_elapsed_s,
        "offset_s": zed_elapsed_s - audio_elapsed_s,
        "offset_definition": "zed_event_elapsed_s - audio_event_elapsed_s",
        "uncertainty_components": components,
        "total_uncertainty_ms": total_uncertainty_ms,
        "maximum_uncertainty_ms": maximum_uncertainty_ms,
        "event_unique": event_unique,
        "event_visible": event_visible,
        "event_audible": event_audible,
        "failure_reasons": reasons,
        "supported_claims": [
            "coarse audio-video association",
            "metrics with decision margin greater than total_uncertainty_ms",
        ],
        "unsupported_claims": [
            "sample-accurate synchronization",
            "acoustic time-of-flight",
            "absolute capture latency",
            "host clock synchronization",
            "calibrated optical-acoustic extrinsics",
        ],
        "ssh_timing_is_synchronization": False,
    }


def artifact_record(
    path: str | Path,
    *,
    role: str,
    root: str | Path,
    media_properties: Mapping[str, Any] | None = None,
    acquisition_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe one finalized artifact relative to an attempt root."""

    artifact = Path(path)
    relative = artifact.relative_to(Path(root))
    record = {
        "path": relative.as_posix(),
        "local_relative_path": relative.as_posix(),
        "role": role,
        "retention": "machine_local_gitignored",
        "byte_size": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
        "acquisition_contract": dict(
            acquisition_contract
            or {
                "configuration": "normalized_configuration.json",
                "lifecycle": "lifecycle.json",
                "publication": "S2.2 atomic writer/session lifecycle",
            }
        ),
        "media_properties": dict(
            media_properties
            or {
                "format": "role-specific record; see role and acquisition contract"
            }
        ),
    }
    return record


def verify_artifact_records(
    root: str | Path, records: Sequence[Mapping[str, Any]]
) -> ValidationReport:
    """Reject missing, unsafe, duplicate, or checksum-mismatched artifacts."""

    evidence_root = Path(root).resolve()
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value:
            issues.append(
                ValidationIssue(
                    "invalid_artifact_path",
                    f"artifacts[{index}].path",
                    repr(path_value),
                )
            )
            continue
        if path_value in seen:
            issues.append(
                ValidationIssue(
                    "duplicate_artifact", f"artifacts[{index}].path", path_value
                )
            )
            continue
        seen.add(path_value)
        candidate = (evidence_root / path_value).resolve()
        try:
            candidate.relative_to(evidence_root)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "unsafe_artifact_path", f"artifacts[{index}].path", path_value
                )
            )
            continue
        if not candidate.is_file():
            issues.append(
                ValidationIssue("missing_artifact", path_value, "file is missing")
            )
            continue
        expected_bytes = record.get("byte_size")
        if expected_bytes != candidate.stat().st_size:
            issues.append(
                ValidationIssue(
                    "artifact_size_mismatch",
                    path_value,
                    f"expected {expected_bytes!r}, got {candidate.stat().st_size}",
                )
            )
        expected_hash = record.get("sha256")
        actual_hash = sha256_file(candidate)
        if expected_hash != actual_hash:
            issues.append(
                ValidationIssue(
                    "checksum_mismatch",
                    path_value,
                    f"expected {expected_hash!r}, got {actual_hash}",
                )
            )
    return ValidationReport(
        (
            {
                "id": "artifact_integrity",
                "status": "passed" if not issues else "failed",
                "artifact_count": len(records),
            },
        ),
        tuple(issues),
    )


def write_checksums(
    output: str | Path, root: str | Path, records: Sequence[Mapping[str, Any]]
) -> None:
    """Write sorted GNU-compatible SHA-256 lines through an S2.2 staged file."""

    destination = Path(output)
    staged = StagedFile(destination.parent / "_staging", destination.name + ".incoming")
    try:
        for record in sorted(records, key=lambda item: str(item["path"])):
            line = f"{record['sha256']}  {record['path']}\n".encode()
            staged.append(line)
        publish_file(staged, destination)
    except BaseException:
        if not staged.closed:
            staged.close()
        raise


def fsync_file(stream: BinaryIO) -> None:
    """Explicitly flush and fsync a producer-owned stream before inspection."""

    stream.flush()
    os.fsync(stream.fileno())


__all__ = [
    "ALIGNMENT_SCHEMA",
    "ATTEMPT_SCHEMA",
    "AttemptLifecycle",
    "CONFIG_SCHEMA",
    "EXPECTED_CHANNEL_ORDER",
    "LIFECYCLE_SCHEMA",
    "S42Error",
    "ValidationIssue",
    "ValidationReport",
    "artifact_record",
    "calculate_alignment",
    "disk_space_check",
    "inspect_six_channel_wav",
    "load_json",
    "normalize_configuration",
    "promote_finalized_file",
    "read_jsonl",
    "sha256_file",
    "validate_configuration",
    "validate_mac_preflight",
    "validate_zed_records",
    "verify_artifact_records",
    "write_checksums",
]
