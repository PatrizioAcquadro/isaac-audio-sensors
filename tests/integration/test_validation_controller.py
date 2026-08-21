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
from isaac_audio_sensors.kit import (
    CurrentStageContext,
    ExtensionActionError,
    ExtensionController,
    ExtensionUiState,
)
from isaac_audio_sensors.kit.validation import ValidationController
from isaac_audio_sensors.kit.validation import controller as validation_controller
from isaac_audio_sensors.kit.validation.results import ValidationReport


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
    controller_message = _raised_message(controller_action)
    assert report.findings[0].message == controller_message


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
    repo = Path(__file__).resolve().parents[2]
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
        module = importlib.import_module("isaac_audio_sensors.kit.validation")
        assert module.ValidationController().validate_stage_present(True).ok
        report = module.ValidationController().validate_stage_present(False)
        assert not report.ok
        assert report.findings[0].message == "No USD stage is open."
        assert not any(
            name == blocked_name or name.startswith(blocked_name + ".")
            for name in sys.modules
            for blocked_name in blocked
        )
        print("validation-import-ok")
        """)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(repo / "src"), env.get("PYTHONPATH", "")))

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


def test_device_and_calibration_results_match_gui_and_headless(tmp_path):
    state = _state(compute_device="cuda")
    validation = ValidationController()
    controller = ExtensionController(state=state)

    _assert_parity(
        validation.validate_backend_device(state.backend, state.compute_device),
        controller._validate_backend_device,
    )

    missing = tmp_path / "missing-calibration.json"
    state.compute_device = "cpu"
    state.calibration_profile_path = str(missing)
    direct = validation.validate_calibration_profile(
        state.calibration_profile_path,
        controller._calibration_array_facts(),
    )
    _assert_parity(direct, controller._validate_calibration_profile)
    assert direct.findings[0].check_id == "calibration_profile_readable"


def test_device_and_calibration_checks_never_answer_from_stale_state(tmp_path):
    profile_path = (
        Path(__file__).resolve().parents[2]
        / "examples/calibration/respeaker_xvf3800_nominal.v1.json"
    )
    selected = tmp_path / "selected-calibration.json"
    selected.write_bytes(profile_path.read_bytes())
    facts = {
        "array_id": "xvf3800_array",
        "device_id": "respeaker_xvf3800_fixture",
        "microphones": tuple(
            {"mic_id": channel} for channel in ("ch0", "ch1", "ch2", "ch3")
        ),
        "sample_rate_hz": 48_000,
        "coordinate_convention": ("x_forward_y_right_z_up_clockwise_bearing"),
        "array_frame": "xvf3800_array",
    }
    validation = ValidationController()

    assert validation.validate_backend_device("tdoa_synthetic", "cpu").ok
    changed_device = validation.validate_backend_device("tdoa_synthetic", "cuda")
    assert not changed_device.ok
    assert changed_device.findings[0].check_id == "backend_device_supported"

    assert validation.validate_calibration_profile(str(selected), facts).ok
    selected.write_text("{}\n", encoding="utf-8")
    replaced = validation.validate_calibration_profile(str(selected), facts)
    assert not replaced.ok
    assert replaced.findings[0].check_id == "calibration_profile_readable"
    selected.unlink()
    deleted = validation.validate_calibration_profile(str(selected), facts)
    assert not deleted.ok
    assert "No such file" in deleted.findings[0].message


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
