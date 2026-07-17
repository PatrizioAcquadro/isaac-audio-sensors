"""Import-safe guided workflow state for the reference extension."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from isaac_audio_sensors.isaac.validation import (
    ValidationController,
    ValidationFinding,
    ValidationReport,
)


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
class _RecoveryRule:
    match_kind: str
    match_value: str
    handler_id: str
    label: str


_RECOVERY_RULES = (
    _RecoveryRule("check", "setup_preset_applied", "preset", "Apply preset"),
    _RecoveryRule("check", "stage_present", "stage", "Open stage"),
    _RecoveryRule(
        "check",
        "capabilities_fresh",
        "capabilities",
        "Refresh capabilities",
    ),
    _RecoveryRule("field", "backend", "preset", "Use safe backend"),
    _RecoveryRule("field_suffix", "_path", "preset", "Fix path"),
    _RecoveryRule("field", "guided_preset_id", "preset", "Apply preset"),
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
        validation: ValidationController,
        state: Any,
        *,
        on_change: Callable[[], None] | None = None,
        recovery_handlers: Mapping[
            str, Callable[[ValidationFinding], None]
        ] | None = None,
    ) -> None:
        self.validation = validation
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

    def stage_gate(
        self, stage: GuidedStage | str
    ) -> tuple[ValidationFinding, ...]:
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
        findings = (
            ()
            if stage_present
            else self.validation.validate_stage_present(False).findings
        )
        self._findings[GuidedStage.SETUP] = findings
        self._statuses[GuidedStage.SETUP] = (
            StageStatus.COMPLETE if not findings else StageStatus.BLOCKED
        )
        self._emit_change()
        return preset

    def record_validation(
        self,
        report: ValidationReport,
        *,
        capabilities_fresh: bool,
    ) -> ValidationReport:
        """Record a Validate pass and enforce its freshness prerequisite."""

        findings = [*self.stage_gate(GuidedStage.VALIDATE), *report.findings]
        if not capabilities_fresh:
            findings.append(
                _finding(
                    "capabilities_fresh",
                    "Capability state is stale; refresh capabilities and "
                    "validate again.",
                    "backend",
                )
            )
        recorded = ValidationReport(tuple(dict.fromkeys(findings)))
        self._findings[GuidedStage.VALIDATE] = recorded.findings
        self._statuses[GuidedStage.VALIDATE] = (
            StageStatus.COMPLETE if recorded.ok else StageStatus.BLOCKED
        )
        self._emit_change()
        return recorded

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
    "GUIDED_STAGE_ORDER",
    "SAFE_PRESET_LIBRARY",
    "SAFE_PRESETS",
    "GuidedStage",
    "GuidedWorkflow",
    "InlineIssue",
    "RecoveryAction",
    "SafePreset",
    "StageStatus",
]
