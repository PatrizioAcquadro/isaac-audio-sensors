from __future__ import annotations

import json
import types

from isaac_audio_sensors.core import capabilities

OPTIONAL_MODULES = {"pyroomacoustics", "soundfile"}


def _module(name: str, origin) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(origin)
    return module


def test_missing_optional_dependencies_are_absent_and_actionable(monkeypatch):
    real_import = capabilities.importlib.import_module

    def blocked(name: str):
        if name in OPTIONAL_MODULES:
            raise ImportError(name)
        return real_import(name)

    monkeypatch.setattr(capabilities.importlib, "import_module", blocked)
    report = capabilities.discover_capabilities()

    assert report.get("L0").origin == "bundled"
    assert report.get("L1").origin == "bundled"
    assert report.get("L2").origin == "bundled"
    assert report.get("room_acoustics").origin == "absent"
    assert report.get("analytic_acoustics_closed_rooms").origin == "absent"
    assert report.get("waveform_export_flac").origin == "absent"
    assert "isaac-audio-sensors[room]" in (
        report.get("analytic_acoustics_closed_rooms").actionable_message
    )
    payload = report.to_dict()
    assert "active_pack" not in payload
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_optional_dependencies_outside_bundle_are_external(monkeypatch, tmp_path):
    modules = {
        name: _module(name, tmp_path / "external" / name / "__init__.py")
        for name in OPTIONAL_MODULES
    }
    monkeypatch.setattr(
        capabilities.importlib,
        "import_module",
        lambda name: modules[name],
    )

    report = capabilities.discover_capabilities()

    assert report.get("L2").origin == "bundled"
    assert report.get("room_acoustics").origin == "external"
    assert report.get("room_acoustics_srp").origin == "external"
    assert report.get("analytic_acoustics_closed_rooms").origin == "external"
    assert report.get("waveform_export_wav").origin == "external"


def test_optional_dependencies_inside_bundle_are_bundled(monkeypatch, tmp_path):
    bundled_root = tmp_path / "_bundled"
    modules = {
        name: _module(name, bundled_root / name / "__init__.py")
        for name in OPTIONAL_MODULES
    }
    monkeypatch.setattr(capabilities, "_BUNDLED_ROOT", bundled_root)
    monkeypatch.setattr(
        capabilities.importlib,
        "import_module",
        lambda name: modules[name],
    )

    report = capabilities.discover_capabilities()

    assert report.get("L2").origin == "bundled"
    assert report.get("room_acoustics").origin == "bundled"
    assert report.get("analytic_acoustics_closed_rooms").origin == "bundled"
    assert report.get("waveform_export_flac").origin == "bundled"
