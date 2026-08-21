"""Stateful validation cache, device, and calibration tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from isaac_audio_sensors.core.capabilities import CapabilityReport, CapabilityStatus
from isaac_audio_sensors.kit.validation import ValidationController
from isaac_audio_sensors.kit.validation import controller as validation_controller


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


def test_validation_package_is_import_safe() -> None:
    repo = Path(__file__).resolve().parents[2]
    code = """
import importlib
import importlib.abc
import sys

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in {'omni', 'pxr', 'carb', 'torch'}:
            raise ImportError(fullname)
        return None

sys.meta_path.insert(0, Blocker())
module = importlib.import_module('isaac_audio_sensors.kit.validation')
assert module.check_stage_present(True) == ()
assert module.check_stage_present(False)[0].check_id == 'stage_present'
print('validation-import-ok')
"""
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


def test_capability_cache_refreshes_once_after_invalidation(monkeypatch) -> None:
    calls = 0

    def _discover() -> CapabilityReport:
        nonlocal calls
        calls += 1
        return _capability_report(pack_present=True)

    monkeypatch.setattr(validation_controller, "discover_capabilities", _discover)
    validation = ValidationController()
    with pytest.raises(RuntimeError, match="never been refreshed"):
        _ = validation.capability_state

    first = validation.refresh_capabilities("initial")
    validation.invalidate("dependency change")
    second = validation.capability_state

    assert calls == 2
    assert first.captured_at_generation == 1
    assert second.captured_at_generation == 2
    assert validation.capability_state is second


def test_backend_validation_uses_refreshed_capability_state(monkeypatch) -> None:
    reports = iter(
        (_capability_report(pack_present=True), _capability_report(pack_present=False))
    )
    monkeypatch.setattr(
        validation_controller,
        "discover_capabilities",
        lambda: next(reports),
    )
    validation = ValidationController()
    validation.refresh_capabilities("pack active")
    validation.invalidate("pack inactive")

    report = validation.validate_backend_available("room_acoustics")

    assert not report.ok
    assert report.findings[0].check_id == "backend_available"
    assert "Activate the matching acoustic pack." in report.findings[0].message


def test_backend_device_is_evaluated_on_every_call() -> None:
    validation = ValidationController()
    assert validation.validate_backend_device("tdoa_synthetic", "cpu").ok
    report = validation.validate_backend_device("tdoa_synthetic", "cuda")
    assert not report.ok
    assert report.findings[0].check_id == "backend_device_supported"


def test_calibration_file_is_not_cached(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "examples/calibration/respeaker_xvf3800_nominal.v1.json"
    )
    selected = tmp_path / "calibration.json"
    selected.write_bytes(source.read_bytes())
    facts = {
        "array_id": "xvf3800_array",
        "device_id": "respeaker_xvf3800_fixture",
        "microphones": tuple(
            {"mic_id": channel} for channel in ("ch0", "ch1", "ch2", "ch3")
        ),
        "sample_rate_hz": 48_000,
        "coordinate_convention": "x_forward_y_right_z_up_clockwise_bearing",
        "array_frame": "xvf3800_array",
    }
    validation = ValidationController()

    assert validation.validate_calibration_profile(str(selected), facts).ok
    selected.write_text("{}\n", encoding="utf-8")
    replaced = validation.validate_calibration_profile(str(selected), facts)
    selected.unlink()
    deleted = validation.validate_calibration_profile(str(selected), facts)

    assert replaced.findings[0].check_id == "calibration_profile_readable"
    assert deleted.findings[0].check_id == "calibration_profile_readable"
