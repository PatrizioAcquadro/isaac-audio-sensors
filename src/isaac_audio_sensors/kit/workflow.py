"""Import-safe guided workflow state for the reference extension.

Inspect completion is deliberately an explicit user action: the instrument
readouts provide evidence, but deciding that the observation is acceptable is
human judgment. Guided recording consumes the Isaac simulator and sensor reset
lifecycle, while timestamp/frame-index rollback remains a fallback; every reset
starts a new episode whose first frame is reset-marked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from isaac_audio_sensors.kit.validation import (
    ValidationFinding,
    ValidationReport,
)
from isaac_audio_sensors.kit.validation.checks import check_stage_present


class GuidedStage(str, Enum):
    """Ordered stages in the v1 guided workflow."""

    SETUP = "setup"
    VALIDATE = "validate"
    RUN = "run"
    INSPECT = "inspect"
    RECORD = "record"
    EXPORT = "export"


class StageStatus(str, Enum):
    """Lifecycle status retained independently for every guided stage."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"


GUIDED_STAGE_ORDER = tuple(GuidedStage)


@dataclass(frozen=True, slots=True)
class SafePreset:
    """Known-safe state values applied through the controller config path."""

    preset_id: str
    label: str
    summary: str
    values: Mapping[str, Any]

    def config_summary(self) -> dict[str, Any]:
        """Translate flat UI-state values to the established config shape."""

        values = self.values
        return {
            "backend": values["backend"],
            "array": {
                "prim_path": values["array_prim_path"],
                "array_id": values["array_id"],
                "layout_name": values["layout_name"],
                "sample_rate_hz": values["sample_rate_hz"],
                "coordinate_convention": values["coordinate_convention"],
                "position_world": values["array_position_world"],
                "orientation_world_quat": values["array_orientation_world_quat"],
            },
            "source": {
                "prim_path": values["source_prim_path"],
                "source_id": values["source_id"],
                "class_label": values["source_class_label"],
                "audio_asset_path": values["audio_asset_path"],
                "position_world": values["source_position_world"],
                "start_time_s": values["source_start_time_s"],
                "duration_s": values["source_duration_s"],
                "gain_db": values["source_gain_db"],
                "loop_count": values["source_loop_count"],
                "directivity": values["source_directivity"],
            },
            "stage_binding": {
                "robot_base_prim_path": None,
                "discovery_roots": ("/World",),
            },
            "lifecycle": {
                "update_period_s": values["update_period_s"],
                "max_events": values["max_events"],
                "ambiguity_policy": values["ambiguity_policy"],
            },
        }


_CONVENTION = "x_forward_y_right_z_up_clockwise_bearing"

SAFE_PRESETS = (
    SafePreset(
        preset_id="xvf3800_quad_demo",
        label="XVF3800 quad demo",
        summary=(
            "48 kHz quad_front array with the first deterministic demo source "
            "and tdoa_synthetic backend."
        ),
        values={
            "backend": "tdoa_synthetic",
            "array_prim_path": "/World/Rig/AudioArray",
            "array_id": "rig_front",
            "layout_name": "quad_front",
            "sample_rate_hz": 48000,
            "coordinate_convention": _CONVENTION,
            "array_position_world": (0.0, 0.0, 0.0),
            "array_orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
            "source_prim_path": "/World/Sources/SpeakerFrontRight",
            "source_id": "speaker_front_right",
            "source_class_label": "Speech",
            "audio_asset_path": "generated://impulse",
            "source_position_world": (4.0, 2.0, 0.0),
            "source_start_time_s": 0.0,
            "source_duration_s": 1.0,
            "source_gain_db": 0.0,
            "source_loop_count": 0,
            "source_directivity": "omni",
            "update_period_s": 0.05,
            "max_events": 8,
            "ambiguity_policy": "none",
        },
    ),
    SafePreset(
        preset_id="minimal_single_source",
        label="Minimal single source",
        summary="One mono array and one generated impulse source using geometry_only.",
        values={
            "backend": "geometry_only",
            "array_prim_path": "/World/AudioArray",
            "array_id": "minimal_array",
            "layout_name": "mono",
            "sample_rate_hz": 48000,
            "coordinate_convention": _CONVENTION,
            "array_position_world": (0.0, 0.0, 0.0),
            "array_orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
            "source_prim_path": "/World/Source",
            "source_id": "source",
            "source_class_label": "Speech",
            "audio_asset_path": "generated://impulse",
            "source_position_world": (2.0, 0.0, 0.0),
            "source_start_time_s": 0.0,
            "source_duration_s": 1.0,
            "source_gain_db": 0.0,
            "source_loop_count": 0,
            "source_directivity": "omni",
            "update_period_s": 0.05,
            "max_events": 8,
            "ambiguity_policy": "none",
        },
    ),
)
SAFE_PRESET_LIBRARY = {preset.preset_id: preset for preset in SAFE_PRESETS}


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    """A user-facing recovery label paired with an invokable callback."""

    label: str
    callback: Callable[[], None]

    def __call__(self) -> None:
        self.callback()


@dataclass(frozen=True, slots=True)
class InlineIssue:
    """One finding indexed by the widget field where it should be rendered."""

    field: str
    finding: ValidationFinding
    recovery: RecoveryAction

    @property
    def message(self) -> str:
        return self.finding.message


@dataclass(frozen=True, slots=True)
class RunStatus:
    """Immutable guided Run lifecycle snapshot."""

    configured: bool = False
    running: bool = False
    stopped: bool = True
    frame_count: int = 0
    last_timestamp_ms: int | None = None

    @property
    def lifecycle(self) -> str:
        if self.running:
            return "running"
        if self.configured and not self.stopped:
            return "configured"
        return "stopped"


@dataclass(frozen=True, slots=True)
class RecordingStatus:
    """Immutable guided recording progress snapshot."""

    active: bool = False
    cancelled: bool = False
    session_dir: str | None = None
    dataset_id: str | None = None
    frames: int = 0
    dropped_frames: int = 0
    shards_promoted: int = 0
    bytes_written: int = 0
    current_episode: str | None = None
    reset_count: int = 0
    validation_status: str | None = None

    @property
    def frame_count(self) -> int:
        return self.frames

    @property
    def promoted_shard_count(self) -> int:
        return self.shards_promoted

    @property
    def byte_count(self) -> int:
        return self.bytes_written

    @property
    def current_episode_id(self) -> str | None:
        return self.current_episode


@dataclass(frozen=True, slots=True)
class ExportStatus:
    """Immutable guided export result and inventory totals."""

    destination_dir: str | None = None
    validation_status: str | None = None
    split_status: str = "not_requested"
    note: str | None = None
    inventory_entries: int = 0
    inventory_bytes: int = 0


@dataclass(frozen=True, slots=True)
class _RecoveryRule:
    match_kind: str
    match_value: str
    handler_id: str
    label: str


_RECOVERY_RULES = (
    _RecoveryRule("check", "setup_preset_applied", "preset", "Apply preset"),
    _RecoveryRule("check", "stage_present", "stage", "Open stage"),
    _RecoveryRule("field", "backend", "preset", "Use safe backend"),
    _RecoveryRule("field_suffix", "_path", "preset", "Fix path"),
    _RecoveryRule("field", "guided_preset_id", "preset", "Apply preset"),
    _RecoveryRule(
        "check",
        "guided_recording_cancelled",
        "recording",
        "Start new recording",
    ),
    _RecoveryRule(
        "check",
        "guided_run_sensor_not_running",
        "run",
        "Start Guided Run",
    ),
    _RecoveryRule(
        "check",
        "guided_run_stopped",
        "run",
        "Start Guided Run",
    ),
    _RecoveryRule(
        "check",
        "guided_inspect_complete",
        "inspect",
        "Mark Inspected",
    ),
    _RecoveryRule(
        "check",
        "guided_record_complete",
        "finish_recording",
        "Finish Recording",
    ),
    _RecoveryRule(
        "check_prefix",
        "dataset_",
        "recording",
        "Retry Recording",
    ),
    _RecoveryRule(
        "field",
        "guided_split_ratios",
        "focus",
        "Adjust ratios",
    ),
    _RecoveryRule("default", "", "focus", "Focus field"),
)


def _finding(
    check_id: str,
    message: str,
    field: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(check_id, "error", message, field)


class GuidedWorkflow:
    """Pure-Python state machine for the operational guided workflow."""

    def __init__(
        self,
        state: Any,
        *,
        on_change: Callable[[], None] | None = None,
        recovery_handlers: Mapping[str, Callable[[ValidationFinding], None]]
        | None = None,
    ) -> None:
        self.state = state
        try:
            current = GuidedStage(str(state.guided_stage))
        except (AttributeError, ValueError):
            current = GuidedStage.SETUP
        self.current_stage = current
        self._statuses = {
            stage: StageStatus.NOT_STARTED for stage in GUIDED_STAGE_ORDER
        }
        current_index = GUIDED_STAGE_ORDER.index(current)
        for prior in GUIDED_STAGE_ORDER[:current_index]:
            self._statuses[prior] = StageStatus.COMPLETE
        self._statuses[current] = StageStatus.IN_PROGRESS
        self._findings = {stage: () for stage in GUIDED_STAGE_ORDER}
        self._run_status = RunStatus()
        self._recording_status = RecordingStatus()
        self._export_status = ExportStatus()
        self.on_change = on_change
        self._recovery_handlers = dict(recovery_handlers or {})
        self.focused_field: str | None = None
        self._mirror_stage()

    @property
    def statuses(self) -> Mapping[GuidedStage, StageStatus]:
        return dict(self._statuses)

    @property
    def current_status(self) -> StageStatus:
        return self._statuses[self.current_stage]

    @property
    def current_findings(self) -> tuple[ValidationFinding, ...]:
        return self._findings[self.current_stage]

    def status(self, stage: GuidedStage | str) -> StageStatus:
        return self._statuses[GuidedStage(stage)]

    def findings_for_stage(
        self, stage: GuidedStage | str
    ) -> tuple[ValidationFinding, ...]:
        return self._findings[GuidedStage(stage)]

    @property
    def run_status(self) -> RunStatus:
        return self._run_status

    @property
    def recording_status(self) -> RecordingStatus:
        return self._recording_status

    @property
    def export_status(self) -> ExportStatus:
        return self._export_status

    def stage_gate(self, stage: GuidedStage | str) -> tuple[ValidationFinding, ...]:
        """Return ordered findings preventing entry to ``stage``."""

        target = GuidedStage(stage)
        target_index = GUIDED_STAGE_ORDER.index(target)
        findings = []
        for prior in GUIDED_STAGE_ORDER[:target_index]:
            if self._statuses[prior] is StageStatus.COMPLETE:
                continue
            findings.append(
                _finding(
                    f"guided_{prior.value}_complete",
                    f"Complete {prior.value.title()} before entering "
                    f"{target.value.title()}.",
                    "guided_stage",
                )
            )
        return tuple(findings)

    def goto(self, stage: GuidedStage | str) -> bool:
        """Enter a stage when all preceding stages are complete."""

        target = GuidedStage(stage)
        gate = self.stage_gate(target)
        if gate:
            self._statuses[target] = StageStatus.BLOCKED
            self._findings[target] = gate
            self._emit_change()
            return False
        if target is self.current_stage:
            return True
        self.current_stage = target
        if self._statuses[target] is not StageStatus.COMPLETE:
            self._statuses[target] = StageStatus.IN_PROGRESS
            self._findings[target] = ()
        self._mirror_stage()
        self._emit_change()
        return True

    def advance(self) -> bool:
        index = GUIDED_STAGE_ORDER.index(self.current_stage)
        if index == len(GUIDED_STAGE_ORDER) - 1:
            return False
        return self.goto(GUIDED_STAGE_ORDER[index + 1])

    def back(self) -> bool:
        index = GUIDED_STAGE_ORDER.index(self.current_stage)
        if index == 0:
            return False
        target = GUIDED_STAGE_ORDER[index - 1]
        self.current_stage = target
        self._mirror_stage()
        self._emit_change()
        return True

    def mark_complete(self, stage: GuidedStage | str) -> bool:
        """Complete an entered stage; later runs use this generic hook."""

        target = GuidedStage(stage)
        if target is GuidedStage.SETUP:
            if self._statuses[target] is StageStatus.COMPLETE:
                return True
            findings = self._findings[target] or (
                _finding(
                    "setup_preset_applied",
                    "Apply a safe preset while a USD stage is open.",
                    "guided_preset_id",
                ),
            )
            self._statuses[target] = StageStatus.BLOCKED
            self._findings[target] = findings
            self._emit_change()
            return False
        if target is GuidedStage.VALIDATE:
            if self._statuses[target] is StageStatus.COMPLETE:
                return True
            self._statuses[target] = StageStatus.BLOCKED
            self._findings[target] = self._findings[target] or (
                _finding(
                    "guided_validation_required",
                    "Run a clean validation pass before completing Validate.",
                    "guided_stage",
                ),
            )
            self._emit_change()
            return False
        gate = self.stage_gate(target)
        if gate:
            self._statuses[target] = StageStatus.BLOCKED
            self._findings[target] = gate
            self._emit_change()
            return False
        self._statuses[target] = StageStatus.COMPLETE
        self._findings[target] = ()
        self._emit_change()
        return True

    def apply_preset(
        self,
        preset_id: str,
        apply: Callable[[SafePreset], None],
        *,
        stage_present: bool,
    ) -> SafePreset:
        """Apply a built-in preset and update Setup completion state."""

        preset = SAFE_PRESET_LIBRARY.get(preset_id)
        if preset is None:
            self._statuses[GuidedStage.SETUP] = StageStatus.BLOCKED
            self._findings[GuidedStage.SETUP] = (
                _finding(
                    "setup_preset_applied",
                    f"Unknown guided preset: {preset_id!r}.",
                    "guided_preset_id",
                ),
            )
            self._emit_change()
            raise KeyError(preset_id)
        apply(preset)
        self.state.guided_preset_id = preset.preset_id
        findings = () if stage_present else check_stage_present(False)
        self._findings[GuidedStage.SETUP] = findings
        self._statuses[GuidedStage.SETUP] = (
            StageStatus.COMPLETE if not findings else StageStatus.BLOCKED
        )
        self._emit_change()
        return preset

    def record_validation(
        self,
        report: ValidationReport,
    ) -> ValidationReport:
        """Record one Validate pass."""

        findings = [*self.stage_gate(GuidedStage.VALIDATE), *report.findings]
        recorded = ValidationReport(tuple(dict.fromkeys(findings)))
        self._findings[GuidedStage.VALIDATE] = recorded.findings
        self._statuses[GuidedStage.VALIDATE] = (
            StageStatus.COMPLETE if recorded.ok else StageStatus.BLOCKED
        )
        self._emit_change()
        return recorded

    def start_run(self, *, configured: bool, running: bool) -> RunStatus:
        """Begin a fresh Run observation window."""

        self._run_status = RunStatus(
            configured=bool(configured),
            running=bool(running),
            stopped=not bool(configured or running),
        )
        self._statuses[GuidedStage.RUN] = StageStatus.IN_PROGRESS
        self._findings[GuidedStage.RUN] = ()
        self._emit_change()
        return self._run_status

    def update_run_lifecycle(
        self,
        *,
        configured: bool,
        running: bool,
    ) -> RunStatus:
        """Update configuration/running facts without losing observations."""

        previous = self._run_status
        self._run_status = RunStatus(
            configured=bool(configured),
            running=bool(running),
            stopped=False,
            frame_count=previous.frame_count,
            last_timestamp_ms=previous.last_timestamp_ms,
        )
        self._emit_change()
        return self._run_status

    def observe_run_frame(self, timestamp_ms: int | None) -> RunStatus:
        """Count one new live frame and complete Run when the sensor is live."""

        previous = self._run_status
        self._run_status = RunStatus(
            configured=previous.configured,
            running=previous.running,
            stopped=previous.stopped,
            frame_count=previous.frame_count + 1,
            last_timestamp_ms=(None if timestamp_ms is None else int(timestamp_ms)),
        )
        if self._run_status.running:
            self._statuses[GuidedStage.RUN] = StageStatus.COMPLETE
            self._findings[GuidedStage.RUN] = ()
        self._emit_change()
        return self._run_status

    def stop_run(self) -> RunStatus:
        """Regress Run after its guided sensor is stopped."""

        previous = self._run_status
        self._run_status = RunStatus(
            configured=previous.configured,
            running=False,
            stopped=True,
            frame_count=previous.frame_count,
            last_timestamp_ms=previous.last_timestamp_ms,
        )
        self._statuses[GuidedStage.RUN] = StageStatus.BLOCKED
        self._findings[GuidedStage.RUN] = (
            _finding(
                "guided_run_stopped",
                "Sensor stopped; start Run and observe another frame.",
                "guided_stage",
            ),
        )
        self._emit_change()
        return self._run_status

    def fail_run(self, message: str, *, check_id: str) -> None:
        self._statuses[GuidedStage.RUN] = StageStatus.BLOCKED
        self._findings[GuidedStage.RUN] = (_finding(check_id, message, "guided_stage"),)
        self._emit_change()

    def mark_inspected(self) -> bool:
        """Record the operator's explicit acceptance of instrument evidence."""

        return self.mark_complete(GuidedStage.INSPECT)

    def start_recording(self, status: RecordingStatus) -> RecordingStatus:
        self._recording_status = status
        self._statuses[GuidedStage.RECORD] = StageStatus.IN_PROGRESS
        self._findings[GuidedStage.RECORD] = ()
        self._emit_change()
        return status

    def update_recording(self, status: RecordingStatus) -> RecordingStatus:
        self._recording_status = status
        self._emit_change()
        return status

    def cancel_recording(self, status: RecordingStatus) -> RecordingStatus:
        self._recording_status = status
        self._statuses[GuidedStage.RECORD] = StageStatus.BLOCKED
        self._findings[GuidedStage.RECORD] = (
            _finding(
                "guided_recording_cancelled",
                "recording cancelled",
                "guided_session_dir",
            ),
        )
        self._emit_change()
        return status

    def finish_recording(
        self,
        status: RecordingStatus,
        findings: tuple[ValidationFinding, ...] = (),
    ) -> RecordingStatus:
        self._recording_status = status
        self._findings[GuidedStage.RECORD] = findings
        self._statuses[GuidedStage.RECORD] = (
            StageStatus.COMPLETE if not findings else StageStatus.BLOCKED
        )
        self._emit_change()
        return status

    def fail_recording(
        self,
        message: str,
        *,
        check_id: str = "guided_recording_failed",
    ) -> None:
        self._statuses[GuidedStage.RECORD] = StageStatus.BLOCKED
        self._findings[GuidedStage.RECORD] = (
            _finding(check_id, message, "guided_session_dir"),
        )
        self._emit_change()

    def start_export(self, destination_dir: str) -> ExportStatus:
        """Begin Export after the normal preceding-stage gate has opened."""

        self._export_status = ExportStatus(destination_dir=destination_dir)
        self._statuses[GuidedStage.EXPORT] = StageStatus.IN_PROGRESS
        self._findings[GuidedStage.EXPORT] = ()
        self._emit_change()
        return self._export_status

    def finish_export(self, status: ExportStatus) -> ExportStatus:
        """Complete Export only for a canonical passed copy validation."""

        self._export_status = status
        passed = status.validation_status in {"passed", "passed_with_warnings"}
        self._statuses[GuidedStage.EXPORT] = (
            StageStatus.COMPLETE if passed else StageStatus.BLOCKED
        )
        self._findings[GuidedStage.EXPORT] = ()
        self._emit_change()
        return status

    def fail_export(
        self,
        message: str,
        *,
        check_id: str,
        field: str = "guided_export_dir",
        note: str | None = None,
    ) -> None:
        """Block Export with one located, recoverable finding."""

        self._export_status = ExportStatus(
            destination_dir=self._export_status.destination_dir,
            validation_status="failed",
            split_status=(
                "blocked"
                if check_id == "guided_export_split_impossible"
                else self._export_status.split_status
            ),
            note=note or message,
        )
        self._statuses[GuidedStage.EXPORT] = StageStatus.BLOCKED
        self._findings[GuidedStage.EXPORT] = (_finding(check_id, message, field),)
        self._emit_change()

    def issues_for_field(self, field: str) -> tuple[InlineIssue, ...]:
        """Return current-stage findings for one exact widget field hint."""

        return tuple(
            InlineIssue(
                field=self._field_for_finding(finding),
                finding=finding,
                recovery=self.recovery_action(finding),
            )
            for finding in self.current_findings
            if self._field_for_finding(finding) == field
        )

    def recovery_action(self, finding: ValidationFinding) -> RecoveryAction:
        """Resolve a finding through the extensible recovery-rule registry."""

        rule = next(
            rule for rule in _RECOVERY_RULES if self._rule_matches(rule, finding)
        )
        handler = self._recovery_handlers.get(rule.handler_id)

        def _recover() -> None:
            self.focused_field = self._field_for_finding(finding)
            if handler is not None:
                handler(finding)
            self._emit_change()

        return RecoveryAction(rule.label, _recover)

    def _rule_matches(
        self,
        rule: _RecoveryRule,
        finding: ValidationFinding,
    ) -> bool:
        if rule.match_kind == "check":
            return finding.check_id == rule.match_value
        if rule.match_kind == "field":
            return finding.field == rule.match_value
        if rule.match_kind == "field_suffix":
            return bool(finding.field and finding.field.endswith(rule.match_value))
        if rule.match_kind == "check_prefix":
            return finding.check_id.startswith(rule.match_value)
        return rule.match_kind == "default"

    @staticmethod
    def _field_for_finding(finding: ValidationFinding) -> str:
        if finding.field:
            return finding.field
        if finding.check_id == "stage_present":
            return "stage"
        return "guided_stage"

    def _mirror_stage(self) -> None:
        self.state.guided_stage = self.current_stage.value

    def _emit_change(self) -> None:
        if self.on_change is not None:
            self.on_change()


__all__ = [
    "ExportStatus",
    "GUIDED_STAGE_ORDER",
    "SAFE_PRESET_LIBRARY",
    "SAFE_PRESETS",
    "GuidedStage",
    "GuidedWorkflow",
    "InlineIssue",
    "RecoveryAction",
    "RecordingStatus",
    "RunStatus",
    "SafePreset",
    "StageStatus",
]
