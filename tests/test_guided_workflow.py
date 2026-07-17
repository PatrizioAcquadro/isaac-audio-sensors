from __future__ import annotations

from typing import Any

import pytest

from isaac_audio_sensors.isaac.extension_ui.controller import ExtensionController
from isaac_audio_sensors.isaac.extension_ui.sections import build_guided_section
from isaac_audio_sensors.isaac.extension_ui.state import (
    CurrentStageContext,
    ExtensionUiState,
)
from isaac_audio_sensors.isaac.extension_ui.window import OmniReferenceWindow
from isaac_audio_sensors.isaac.extension_ui.workflow import (
    GUIDED_STAGE_ORDER,
    SAFE_PRESET_LIBRARY,
    SAFE_PRESETS,
    GuidedStage,
    GuidedWorkflow,
    StageStatus,
)
from isaac_audio_sensors.isaac.validation import (
    ValidationController,
    ValidationReport,
)


class _FakeStage:
    def GetPrimAtPath(self, _path: object) -> object:
        return object()


class _FakeModel:
    def __init__(self, value: object = None) -> None:
        self.value = value
        self.changed: list[Any] = []

    @property
    def as_int(self) -> int:
        return int(self.value or 0)

    def get_item_value_model(self) -> _FakeModel:
        return self

    def add_item_changed_fn(self, callback: Any) -> Any:
        self.changed.append(callback)
        return callback

    def add_value_changed_fn(self, callback: Any) -> Any:
        self.changed.append(callback)
        return callback

    def set_value(self, value: object) -> None:
        self.value = value
        for callback in self.changed:
            callback(self)


class _FakeWidget:
    stack: list[_FakeWidget] = []

    def __init__(self, *args: object, kind: str, **kwargs: object) -> None:
        self.kind = kind
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.model = kwargs.get("model") or _FakeModel(
            args[0] if args and isinstance(args[0], int) else None
        )
        self.visible = True
        self.kwargs = kwargs
        self.children: list[_FakeWidget] = []
        if self.stack:
            self.stack[-1].children.append(self)

    def __enter__(self) -> _FakeWidget:
        self.stack.append(self)
        return self

    def __exit__(self, *_args: object) -> bool:
        self.stack.pop()
        return False


class _FakeUi:
    def __init__(self) -> None:
        _FakeWidget.stack = []
        self.created: list[_FakeWidget] = []
        self.VStack = self._factory("VStack")
        self.HStack = self._factory("HStack")
        self.Label = self._factory("Label")
        self.ComboBox = self._factory("ComboBox")
        self.Button = self._factory("Button")

    def _factory(self, kind: str) -> Any:
        def _create(*args: object, **kwargs: object) -> _FakeWidget:
            widget = _FakeWidget(*args, kind=kind, **kwargs)
            self.created.append(widget)
            return widget

        return _create


def _controller(stage_box: dict[str, object | None]) -> ExtensionController:
    return ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage_box["stage"], ())
    )


def test_stage_machine_enforces_order_and_records_blocked_transitions() -> None:
    state = ExtensionUiState()
    changes: list[tuple[GuidedStage, StageStatus]] = []
    workflow = GuidedWorkflow(
        ValidationController(),
        state,
        on_change=lambda: changes.append(
            (workflow.current_stage, workflow.current_status)
        ),
    )

    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.current_status is StageStatus.IN_PROGRESS
    assert workflow.goto(GuidedStage.VALIDATE) is False
    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.status(GuidedStage.VALIDATE) is StageStatus.BLOCKED
    assert workflow.findings_for_stage(GuidedStage.VALIDATE)[0].field == (
        "guided_stage"
    )

    applied: list[str] = []
    workflow.apply_preset(
        SAFE_PRESETS[0].preset_id,
        lambda preset: applied.append(preset.preset_id),
        stage_present=True,
    )
    assert applied == [SAFE_PRESETS[0].preset_id]
    assert workflow.status(GuidedStage.SETUP) is StageStatus.COMPLETE
    assert workflow.advance() is True
    assert state.guided_stage == "validate"
    assert workflow.back() is True
    assert workflow.current_stage is GuidedStage.SETUP
    assert workflow.goto(GuidedStage.EXPORT) is False
    assert workflow.status(GuidedStage.EXPORT) is StageStatus.BLOCKED
    assert len(changes) == 5


def test_stage_machine_can_progress_in_order_after_each_stage_completes() -> None:
    workflow = GuidedWorkflow(ValidationController(), ExtensionUiState())
    workflow.apply_preset(
        SAFE_PRESETS[0].preset_id,
        lambda _preset: None,
        stage_present=True,
    )
    assert workflow.advance()
    workflow.record_validation(ValidationReport(), capabilities_fresh=True)

    for expected in GUIDED_STAGE_ORDER[2:]:
        assert workflow.advance()
        assert workflow.current_stage is expected
        assert workflow.mark_complete(expected)


@pytest.mark.parametrize("preset", SAFE_PRESETS, ids=lambda preset: preset.preset_id)
def test_each_safe_preset_drives_controller_to_validator_clean_state(
    preset: Any,
) -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)

    assert controller.guided_apply_preset(preset.preset_id) is preset
    assert controller.guided_workflow.status(GuidedStage.SETUP) is StageStatus.COMPLETE
    assert controller.guided_advance()
    assert controller.guided_validate().ok


def test_xvf3800_preset_matches_demo_config_claims() -> None:
    preset = SAFE_PRESET_LIBRARY["xvf3800_quad_demo"]

    assert preset.values["backend"] == "tdoa_synthetic"
    assert preset.values["sample_rate_hz"] == 48000
    assert preset.values["layout_name"] == "quad_front"
    assert preset.values["array_prim_path"] == "/World/Rig/AudioArray"
    assert preset.values["source_id"] == "speaker_front_right"
    assert preset.values["source_prim_path"] == (
        "/World/Sources/SpeakerFrontRight"
    )
    assert preset.values["source_position_world"] == (4.0, 2.0, 0.0)


@pytest.mark.parametrize(
    ("field", "bad_value", "check_id", "action_label"),
    (
        ("backend", "not_a_backend", "backend_supported", "Use safe backend"),
        (
            "source_prim_path",
            "World/Source",
            "source_prim_path_absolute",
            "Fix path",
        ),
    ),
)
def test_invalid_field_maps_to_exact_widget_and_recovery_unblocks(
    field: str,
    bad_value: object,
    check_id: str,
    action_label: str,
) -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    controller.guided_apply_preset("xvf3800_quad_demo")
    controller.guided_advance()
    setattr(controller.state, field, bad_value)

    report = controller.guided_validate()

    finding = next(item for item in report.findings if item.check_id == check_id)
    issues = controller.guided_workflow.issues_for_field(field)
    assert [issue.finding for issue in issues] == [
        item for item in report.findings if item.field == field
    ]
    action = controller.guided_workflow.recovery_action(finding)
    assert action.label == action_label
    action()
    assert controller.guided_validate().ok


def test_absent_stage_has_open_stage_recovery() -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    controller.guided_apply_preset("minimal_single_source")
    controller.guided_advance()
    stage_box["stage"] = None

    report = controller.guided_validate()
    finding = next(item for item in report.findings if item.check_id == "stage_present")
    assert controller.guided_workflow.issues_for_field("stage")[0].finding is finding
    action = controller.guided_workflow.recovery_action(finding)
    assert action.label == "Open stage"

    stage_box["stage"] = _FakeStage()
    action()
    assert controller.guided_validate().ok


def test_stale_capabilities_block_once_and_refresh_recovery_unblocks() -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    controller.guided_apply_preset("minimal_single_source")
    controller.guided_advance()
    assert controller.guided_validate().ok
    controller._validation.invalidate("planted stale capability state")

    report = controller.guided_validate()

    finding = next(
        item for item in report.findings if item.check_id == "capabilities_fresh"
    )
    assert controller.guided_workflow.current_status is StageStatus.BLOCKED
    assert controller.guided_workflow.issues_for_field("backend")[0].finding is finding
    action = controller.guided_workflow.recovery_action(finding)
    assert action.label == "Refresh capabilities"
    action()
    assert controller.guided_validate().ok


def test_guided_section_builds_and_refreshes_on_workflow_change() -> None:
    stage_box: dict[str, object | None] = {"stage": _FakeStage()}
    controller = _controller(stage_box)
    ui = _FakeUi()
    window = OmniReferenceWindow(controller, ui)

    build_guided_section(window)

    labels = [widget.text for widget in ui.created if widget.kind == "Label"]
    buttons = [widget.text for widget in ui.created if widget.kind == "Button"]
    assert "Guided Workflow" in labels
    assert any("Setup [in_progress]" in text for text in labels)
    assert "Apply Guided Preset" in buttons
    assert "Validate now" in buttons
    assert len([widget for widget in ui.created if widget.kind == "ComboBox"]) == 1

    controller.guided_apply_preset("minimal_single_source")
    controller.guided_advance()

    assert window._guided_panel["setup_panel"].visible is False
    assert window._guided_panel["validate_panel"].visible is True
    assert "Validate [in_progress]" in window._guided_panel["breadcrumb"].text
