"""Parity and import-safety tests for shared Isaac validation."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from isaac_audio_sensors.core.capabilities import CapabilityReport, CapabilityStatus
from isaac_audio_sensors.isaac.extension_ui import (
    CurrentStageContext,
    ExtensionActionError,
    ExtensionController,
    ExtensionUiState,
)
from isaac_audio_sensors.isaac.validation import ValidationController
from isaac_audio_sensors.isaac.validation import checks as validation_checks
from isaac_audio_sensors.isaac.validation import controller as validation_controller
from isaac_audio_sensors.isaac.validation.results import ValidationReport


class _FakePrim:
    def __init__(self, path: str) -> None:
        self.path = path
        self.type_name = "Xform"
        self.attributes: dict[str, object] = {}


class _FakeStage:
    def __init__(self, *paths: str) -> None:
        self._prims = [_FakePrim(path) for path in paths]

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)

    def GetPrimAtPath(self, path: object) -> _FakePrim | None:
        return next((prim for prim in self._prims if prim.path == str(path)), None)


def _state(**changes: Any) -> ExtensionUiState:
    state = ExtensionUiState()
    for field_name, value in changes.items():
        setattr(state, field_name, value)
    return state


def _raised_message(action: Any) -> str:
    with pytest.raises(ExtensionActionError) as exc_info:
        action()
    return str(exc_info.value)


def _assert_parity(report: ValidationReport, controller_action: Any) -> None:
    assert report.ok is False
    direct_message = _raised_message(report.raise_first)
    controller_message = _raised_message(controller_action)
    assert direct_message == controller_message


def _capability(
    capability_id: str,
    *,
    kind: str,
    fidelity_level: str,
    available: bool,
) -> CapabilityStatus:
    return CapabilityStatus(
        capability_id=capability_id,
        kind=kind,
        fidelity_level=fidelity_level,
        status="available" if available else "unavailable",
        origin="pack:test@1" if available else "absent",
        missing_dependencies=() if available else ("pyroomacoustics",),
        actionable_message=(
            "" if available else "Activate the matching acoustic pack."
        ),
    )


def _capability_report(*, pack_present: bool) -> CapabilityReport:
    return CapabilityReport(
        fidelity_levels=(
            _capability(
                "L0",
                kind="fidelity_level",
                fidelity_level="L0",
                available=True,
            ),
            _capability(
                "L1",
                kind="fidelity_level",
                fidelity_level="L1",
                available=True,
            ),
            _capability(
                "L2",
                kind="fidelity_level",
                fidelity_level="L2",
                available=pack_present,
            ),
        ),
        optional_features=(
            _capability(
                "room_acoustics",
                kind="backend",
                fidelity_level="L2",
                available=pack_present,
            ),
            _capability(
                "room_acoustics_srp",
                kind="backend",
                fidelity_level="L2",
                available=pack_present,
            ),
        ),
        active_pack="test@1" if pack_present else None,
    )


def test_validation_package_imports_without_isaac_runtime_dependencies():
    repo = Path(__file__).resolve().parents[1]
    code = textwrap.dedent("""
        import importlib
        import importlib.abc
        import sys

        blocked = ("omni", "pxr", "carb", "torch")

        class IsaacRuntimeBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                for module_name in blocked:
                    if fullname == module_name or fullname.startswith(
                        module_name + "."
                    ):
                        raise ImportError(f"blocked runtime module {fullname}")
                return None

        sys.meta_path.insert(0, IsaacRuntimeBlocker())
        module = importlib.import_module("isaac_audio_sensors.isaac.validation")
        assert module.ValidationController().validate_stage_present(True).ok
        try:
            module.ValidationController().validate_stage_present(False).raise_first()
        except RuntimeError as exc:
            assert type(exc).__name__ == "ExtensionActionError"
            assert str(exc) == "No USD stage is open."
        else:
            raise AssertionError("invalid stage unexpectedly passed")
        print("validation-import-ok")
        """)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(repo / "src"), env.get("PYTHONPATH", ""))
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.stdout.strip() == "validation-import-ok"


def test_capability_state_refreshes_once_after_invalidation(monkeypatch):
    calls = 0

    def _discover() -> CapabilityReport:
        nonlocal calls
        calls += 1
        return _capability_report(pack_present=True)

    monkeypatch.setattr(validation_controller, "discover_capabilities", _discover)
    controller = ValidationController()

    with pytest.raises(RuntimeError, match="has never been refreshed"):
        _ = controller.capability_state

    first = controller.refresh_capabilities("test setup")
    assert calls == 1
    assert first.captured_at_generation == 1
    assert first.active_pack == "test@1"
    assert first.available_backend_ids == (
        "geometry_only",
        "tdoa_synthetic",
        "room_acoustics",
        "room_acoustics_srp",
    )
    assert controller.capability_state is first
    assert calls == 1

    controller.invalidate("dependency changed")
    assert calls == 1
    second = controller.capability_state
    assert calls == 2
    assert second.captured_at_generation == 2
    assert controller.capability_state is second
    assert calls == 2


def test_backend_validation_refreshes_stale_state_before_answering(monkeypatch):
    reports = iter(
        (
            _capability_report(pack_present=True),
            _capability_report(pack_present=False),
        )
    )
    calls = 0

    def _discover() -> CapabilityReport:
        nonlocal calls
        calls += 1
        return next(reports)

    monkeypatch.setattr(validation_controller, "discover_capabilities", _discover)
    controller = ValidationController()
    controller.refresh_capabilities("pack present")
    controller.invalidate("pack deactivated")

    report = controller.validate_backend_available("room_acoustics")

    assert calls == 2
    assert report.ok is False
    assert report.findings[0].check_id == "backend_available"
    assert "Activate the matching acoustic pack." in report.findings[0].message


def test_dependency_change_flips_only_after_triggered_invalidation(monkeypatch):
    pack_present = True
    calls = 0

    def _discover() -> CapabilityReport:
        nonlocal calls
        calls += 1
        return _capability_report(pack_present=pack_present)

    monkeypatch.setattr(validation_controller, "discover_capabilities", _discover)
    controller = ValidationController()
    controller.refresh_capabilities("pack activation")
    assert controller.validate_backend_available("room_acoustics").ok
    assert calls == 1

    # Freshness follows the trigger contract; dependency changes are not magic.
    pack_present = False
    assert controller.validate_backend_available("room_acoustics").ok
    assert calls == 1

    controller.invalidate("pack deactivation")
    assert not controller.validate_backend_available("room_acoustics").ok
    assert calls == 2


def test_backend_availability_messages_match_gui_and_headless(monkeypatch):
    calls = 0

    def _discover() -> CapabilityReport:
        nonlocal calls
        calls += 1
        return _capability_report(pack_present=False)

    monkeypatch.setattr(validation_controller, "discover_capabilities", _discover)
    state = _state(backend="room_acoustics")
    headless = ValidationController()
    gui = ExtensionController(state=state)

    report = headless.validate_backend_available(state.backend)
    _assert_parity(report, gui._validate_backend_available)

    assert calls == 2
    assert report.findings[0].message == (
        "Backend 'room_acoustics' is unavailable in the current capability state. "
        "Activate the matching acoustic pack."
    )


def test_gui_invalidates_existing_startup_stage_and_config_paths(monkeypatch):
    reasons: list[str] = []
    controller = ExtensionController()
    monkeypatch.setattr(controller._validation, "invalidate", reasons.append)
    monkeypatch.setattr(controller, "build_ui_if_available", lambda: None)
    monkeypatch.setattr(controller, "register_kit_integrations", lambda: None)

    controller.on_startup("test.extension")

    callbacks: list[Any] = []
    stream = SimpleNamespace(
        create_subscription_to_pop=lambda callback, name=None: (
            callbacks.append(callback) or SimpleNamespace(name=name)
        )
    )
    omni = ModuleType("omni")
    omni.__path__ = []
    omni_usd = ModuleType("omni.usd")
    omni_usd.StageEventType = SimpleNamespace(
        OPENED=1,
        CLOSED=2,
        SELECTION_CHANGED=3,
    )
    omni_usd.get_context = lambda: SimpleNamespace(
        get_stage_event_stream=lambda: stream
    )
    omni.usd = omni_usd
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)

    controller._register_stage_event_subscription()
    callbacks[0](SimpleNamespace(type=1))
    controller._apply_config_summary({})

    assert reasons == (
        [
            "extension startup",
            "USD stage opened",
            "configuration summary apply",
        ]
    )


@pytest.mark.parametrize(
    ("field_name", "value", "workflow"),
    (
        ("backend", "not_a_backend", "runtime"),
        ("ambiguity_policy", "maybe", "runtime"),
        ("update_period_s", 0.0, "runtime"),
        ("max_events", -1, "runtime"),
        ("array_prim_path", "World/Array", "runtime"),
        ("audio_asset_path", "", "source_metadata"),
        ("source_start_time_s", float("nan"), "source_metadata"),
        ("source_position_x_m", float("inf"), "source_position"),
        ("source_local_offset_z_m", float("nan"), "source_local_offset"),
        ("array_position_y_m", float("nan"), "array_position"),
        ("array_yaw_deg", float("inf"), "array_orientation"),
        ("array_local_offset_x_m", float("nan"), "array_local_offset"),
        (
            "array_local_roll_deg",
            float("inf"),
            "array_local_orientation",
        ),
        ("layout_name", "unknown", "layout"),
        ("sample_rate_hz", 0, "layout"),
    ),
)
def test_state_validation_messages_match_extension_controller(
    field_name: str,
    value: object,
    workflow: str,
):
    state = _state(**{field_name: value})
    validation = ValidationController()
    controller = ExtensionController(state=state)

    if workflow == "runtime":
        report = validation.validate_runtime(state)
        action = controller._validate_runtime_state
    elif workflow == "source_metadata":
        report = validation.validate_source_metadata(state)
        action = controller._validate_source_metadata_state
    elif workflow == "source_position":
        report = validation.validate_source_geometry(state)
        action = controller._source_position_from_state
    elif workflow == "source_local_offset":
        report = validation.validate_source_geometry(state)
        action = controller._source_local_offset_from_state
    elif workflow == "array_position":
        report = validation.validate_array_geometry(state)
        action = controller._array_position_from_state
    elif workflow == "array_orientation":
        report = validation.validate_array_geometry(state)
        action = controller._array_orientation_from_state
    elif workflow == "array_local_offset":
        report = validation.validate_array_geometry(state)
        action = controller._array_local_offset_from_state
    elif workflow == "array_local_orientation":
        report = validation.validate_array_geometry(state)
        action = controller._array_local_orientation_from_state
    else:
        assert workflow == "layout"
        report = validation.validate_layout(state)
        action = controller._validate_layout_state

    _assert_parity(report, action)


def test_valid_state_passes_shared_and_extension_controller_checks():
    state = ExtensionUiState()
    validation = ValidationController()
    controller = ExtensionController(state=state)

    assert validation.validate_runtime(state).ok
    assert validation.validate_source_metadata(state).ok
    assert validation.validate_source_geometry(state).ok
    assert validation.validate_array_geometry(state).ok
    assert validation.validate_layout(state).ok
    controller._validate_runtime_state()
    controller._validate_source_metadata_state()
    controller._source_position_from_state()
    controller._source_local_offset_from_state()
    controller._array_position_from_state()
    controller._array_orientation_from_state()
    controller._array_local_offset_from_state()
    controller._array_local_orientation_from_state()
    controller._validate_layout_state()


def test_stage_selection_path_and_attach_messages_match_controller_shims():
    validation = ValidationController()
    controller = ExtensionController(
        stage_context_provider=lambda: CurrentStageContext(stage=None)
    )

    _assert_parity(
        validation.validate_stage_present(False),
        lambda: controller._stage_or_error(None),
    )
    _assert_parity(
        validation.validate_selection(None, False),
        lambda: controller._validate_selection(None, exists=False),
    )
    _assert_parity(
        validation.validate_selection("/World/Missing", False),
        lambda: controller._validate_selection("/World/Missing", exists=False),
    )
    _assert_parity(
        validation.validate_abs_prim_path("World/Array", "array_prim_path"),
        lambda: controller._validate_abs_path("World/Array", "array_prim_path"),
    )
    _assert_parity(
        validation.validate_attach_target("/World/Source", "/World/Source"),
        lambda: controller._validate_attach_target(
            "/World/Source",
            "/World/Source",
        ),
    )
    _assert_parity(
        validation.validate_attach_target(
            "/World/Array",
            "/World/Array",
            kind="array",
        ),
        lambda: controller._validate_attach_target(
            "/World/Array",
            "/World/Array",
            kind="array",
        ),
    )


def test_stage_shims_preserve_public_controller_error_side_effects():
    stage = _FakeStage("/World/Source")
    controller = ExtensionController()
    controller.state.source_prim_path = "/World/Source"

    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Source",),
        )
        is None
    )
    assert controller.state.error_message == (
        "Object selection failed: Cannot attach a source to itself."
    )

    assert (
        controller.use_selected_as_object(
            stage=stage,
            selected_paths=("/World/Missing",),
        )
        is None
    )
    assert controller.state.error_message == (
        "Object selection failed: Selected object does not exist: /World/Missing."
    )


def test_check_id_inventory_is_stable_and_unique():
    reports = [
        ValidationController().validate_runtime(_state(backend="bad")),
        ValidationController().validate_runtime(_state(ambiguity_policy="bad")),
        ValidationController().validate_runtime(_state(update_period_s=0.0)),
        ValidationController().validate_runtime(_state(max_events=-1)),
        ValidationController().validate_runtime(
            _state(array_prim_path="World/Array")
        ),
        ValidationController().validate_runtime(
            _state(robot_base_prim_path="World/Base")
        ),
        ValidationController().validate_source_metadata(
            _state(audio_asset_path="")
        ),
        ValidationController().validate_source_metadata(
            _state(source_directivity="")
        ),
        ValidationController().validate_source_metadata(
            _state(source_start_time_s=float("nan"))
        ),
        ValidationController().validate_source_metadata(
            _state(source_duration_s=float("nan"))
        ),
        ValidationController().validate_source_metadata(
            _state(source_gain_db=float("nan"))
        ),
        ValidationController().validate_source_metadata(
            _state(source_duration_s=0.0)
        ),
        ValidationController().validate_source_geometry(
            _state(source_position_x_m=float("nan"))
        ),
        ValidationController().validate_source_geometry(
            _state(source_local_offset_x_m=float("nan"))
        ),
        ValidationController().validate_array_geometry(
            _state(array_position_x_m=float("nan"))
        ),
        ValidationController().validate_array_geometry(
            _state(array_roll_deg=float("nan"))
        ),
        ValidationController().validate_array_geometry(
            _state(array_local_offset_x_m=float("nan"))
        ),
        ValidationController().validate_array_geometry(
            _state(array_local_roll_deg=float("nan"))
        ),
        ValidationController().validate_layout(_state(layout_name="bad")),
        ValidationController().validate_layout(_state(sample_rate_hz=0)),
        ValidationReport(validation_checks.check_stage_present(False)),
        ValidationReport(validation_checks.check_selection(None, False)),
        ValidationReport(
            validation_checks.check_selection("/World/Missing", False)
        ),
        ValidationReport(
            validation_checks.check_abs_prim_path("World/Object", "object_prim_path")
        ),
        ValidationReport(
            validation_checks.check_abs_prim_path("World/Source", "source_prim_path")
        ),
        ValidationReport(
            validation_checks.check_attach_target("/World/S", "/World/S")
        ),
        ValidationReport(
            validation_checks.check_attach_target(
                "/World/A", "/World/A", kind="array"
            )
        ),
        ValidationReport(validation_checks.check_array_pose_editable(True)),
        ValidationReport(validation_checks.check_source_position_preset("bad")),
        ValidationReport(validation_checks.check_profile_labels(())),
        ValidationReport(validation_checks.check_profile_match(("Oven",), None)),
        ValidationReport(
            validation_checks.check_room_anchor_exists("/World/Room", False)
        ),
        ValidationReport(validation_checks.check_config_schema_version("v0")),
        ValidationReport(
            validation_checks.check_object_profile_mapping_known(
                "oven", "missing", False
            )
        ),
        ValidationReport(validation_checks.check_sound_profile_id_present("")),
        ValidationReport(
            validation_checks.check_sound_profile_id_known("missing", False)
        ),
        ValidationReport(validation_checks.check_rig_profile_id_present("")),
        ValidationReport(
            validation_checks.check_rig_profile_id_known("missing", False)
        ),
        ValidationReport(
            validation_checks.check_sound_profile_config_container(False)
        ),
        ValidationReport(
            validation_checks.check_sound_profile_library_present(False)
        ),
        ValidationReport(
            validation_checks.check_object_profile_mappings_present(False)
        ),
        ValidationReport(
            validation_checks.check_object_profile_mappings_mapping(False)
        ),
        ValidationReport(
            validation_checks.check_sound_profile_library_sequence(False)
        ),
        ValidationReport(
            validation_checks.check_object_profile_mappings_non_empty(False)
        ),
        ValidationReport(
            validation_checks.check_object_profile_mapping_known(
                "oven", "missing", False, config=True
            )
        ),
        ValidationReport(
            validation_checks.check_sound_profile_id_known(
                "missing", False, config=True
            )
        ),
        ValidationReport(
            validation_checks.check_rig_profile_config_container(False)
        ),
        ValidationReport(
            validation_checks.check_rig_profile_library_present(False)
        ),
        ValidationReport(
            validation_checks.check_rig_profile_library_sequence(False)
        ),
        ValidationReport(
            validation_checks.check_rig_profile_id_known(
                "missing", False, config=True
            )
        ),
        ValidationReport(
            validation_checks.check_source_attach_target_exists(
                "/World/Object", False
            )
        ),
        ValidationReport(
            validation_checks.check_array_attach_target_exists(
                "/World/Mount", False
            )
        ),
        ValidationReport(
            validation_checks.check_attached_source_target(True, "", None)
        ),
        ValidationReport(
            validation_checks.check_attached_source_target(
                True, "/World/Object", False
            )
        ),
        ValidationReport(
            validation_checks.check_attached_array_target(True, "", None)
        ),
        ValidationReport(
            validation_checks.check_attached_array_target(
                True, "/World/Mount", False
            )
        ),
    ]
    check_ids = tuple(report.findings[0].check_id for report in reports)

    assert check_ids == (
        "backend_supported",
        "ambiguity_policy_supported",
        "update_period_positive_finite",
        "max_events_non_negative",
        "array_prim_path_absolute",
        "robot_base_prim_path_absolute",
        "audio_asset_path_non_empty",
        "source_directivity_non_empty",
        "source_start_time_finite",
        "source_duration_finite",
        "source_gain_db_finite",
        "source_duration_positive",
        "source_position_finite",
        "source_local_offset_finite",
        "array_position_finite",
        "array_orientation_finite",
        "array_local_offset_finite",
        "array_local_orientation_finite",
        "array_layout_known",
        "sample_rate_positive",
        "stage_present",
        "selection_present",
        "selected_object_exists",
        "object_prim_path_absolute",
        "source_prim_path_absolute",
        "source_attach_target_distinct",
        "array_attach_target_distinct",
        "array_pose_editable",
        "source_position_preset_known",
        "profile_object_label_available",
        "sound_profile_match_available",
        "room_anchor_exists",
        "config_schema_version_supported",
        "object_profile_mapping_known",
        "selected_profile_id_non_empty",
        "sound_profile_id_known",
        "selected_rig_profile_id_non_empty",
        "rig_profile_id_known",
        "sound_profiles_config_object",
        "sound_profile_library_present",
        "object_profile_mappings_present",
        "object_profile_mappings_object",
        "sound_profile_library_sequence",
        "object_profile_mappings_non_empty",
        "config_object_profile_mapping_known",
        "config_selected_sound_profile_known",
        "rig_profiles_config_object",
        "rig_profile_library_present",
        "rig_profile_library_sequence",
        "config_selected_rig_profile_known",
        "source_attach_target_exists",
        "array_attach_target_exists",
        "attached_source_target_configured",
        "attached_source_target_exists",
        "attached_array_target_configured",
        "attached_array_target_exists",
    )
    assert len(check_ids) == len(set(check_ids))
    assert all(
        finding.severity == "error"
        for report in reports
        for finding in report.findings
    )
