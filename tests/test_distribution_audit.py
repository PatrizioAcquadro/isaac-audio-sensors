"""Tests for built-archive release hygiene auditing."""

from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path


def _load_audit_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "audit_distribution.py"
    )
    spec = importlib.util.spec_from_file_location("audit_distribution", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_distribution_audit_accepts_required_sdist_and_wheel(tmp_path):
    audit = _load_audit_module()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _write_sdist(
        dist_dir / "isaac_audio_sensors-0.1.0.tar.gz",
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n",
            "MANIFEST.in": "include README.md\n",
            "pyproject.toml": "[project]\nname = 'isaac-audio-sensors'\n",
            "docs/acoustic_fidelity.md": "# Acoustic Fidelity Ladder\n",
            "docs/api_freeze_0_1.md": "# API Freeze 0.1\n",
            "docs/api_reference.md": "# API Reference\n",
            "docs/v1_scope.md": _scope_doc_text(),
            "docs/schemas/audio_sensor_frame.v1.schema.json": "{}\n",
            "examples/traces/ambiguity_frame.v1.json": "{}\n",
            "examples/traces/diagnostics_provenance_sequence.v1.ndjson": "{}\n",
            "examples/traces/minimal_frame.v1.json": "{}\n",
            "examples/traces/multi_detection_frame.v1.json": "{}\n",
            "exts/isaac_audio_sensors.omni/config/extension.toml": "[package]\n",
            "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py": "\n",
            "scripts/audit_distribution.py": "print('audit')\n",
            "scripts/live_isaac_sim_audio_smoke.py": "print('smoke')\n",
            "scripts/live_omniverse_extension_ux.py": "print('ux')\n",
            "src/isaac_audio_sensors/__init__.py": "__version__ = '0.1.0'\n",
            "src/isaac_audio_sensors/core/fidelity.py": "LADDER = ()\n",
            "src/isaac_audio_sensors/isaac/extension_ui.py": "\n",
            "src/isaac_audio_sensors/isaac/replicator.py": "\n",
            "tests/test_acoustic_fidelity.py": "def test_ladder():\n    assert True\n",
            "tests/test_isaac_audio_core.py": "def test_core():\n    assert True\n",
            "tests/test_v1_scope_docs.py": "def test_scope():\n    assert True\n",
        },
    )
    _write_wheel(
        dist_dir / "isaac_audio_sensors-0.1.0-py3-none-any.whl",
        {
            "isaac_audio_sensors/__init__.py": "__version__ = '0.1.0'\n",
            "isaac_audio_sensors/core/types.py": "\n",
            "isaac_audio_sensors/isaac/extension.py": "\n",
            "isaac_audio_sensors/isaac/extension_ui.py": "\n",
            "isaac_audio_sensors/isaac/replicator.py": "\n",
            "isaac_audio_sensors/lab/audio_array_sensor.py": "\n",
            "isaac_audio_sensors-0.1.0.dist-info/METADATA": "Name: x\n",
            "isaac_audio_sensors-0.1.0.dist-info/entry_points.txt": "\n",
        },
    )

    audits = audit.audit_dist_dir(dist_dir)

    assert {item.kind for item in audits} == {"sdist", "wheel"}
    assert all(not item.findings for item in audits)


def test_distribution_audit_reports_forbidden_paths_and_content(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / "isaac_audio_sensors-0.1.0.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n",
            "MANIFEST.in": "include README.md\n",
            "pyproject.toml": "[project]\nname = 'isaac-audio-sensors'\n",
            "docs/acoustic_fidelity.md": "# Acoustic Fidelity Ladder\n",
            "docs/api_freeze_0_1.md": "# API Freeze 0.1\n",
            "docs/api_reference.md": "# API Reference\n",
            "docs/v1_scope.md": _scope_doc_text(),
            "docs/schemas/audio_sensor_frame.v1.schema.json": "{}\n",
            "examples/traces/ambiguity_frame.v1.json": "{}\n",
            "examples/traces/diagnostics_provenance_sequence.v1.ndjson": "{}\n",
            "examples/traces/minimal_frame.v1.json": "{}\n",
            "examples/traces/multi_detection_frame.v1.json": "{}\n",
            "exts/isaac_audio_sensors.omni/config/extension.toml": "[package]\n",
            "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py": "\n",
            "scripts/audit_distribution.py": "print('audit')\n",
            "scripts/live_isaac_sim_audio_smoke.py": "print('smoke')\n",
            "scripts/live_omniverse_extension_ux.py": "print('ux')\n",
            "src/isaac_audio_sensors/__init__.py": "__version__ = '0.1.0'\n",
            "src/isaac_audio_sensors/core/fidelity.py": "LADDER = ()\n",
            "src/isaac_audio_sensors/isaac/extension_ui.py": "\n",
            "src/isaac_audio_sensors/isaac/replicator.py": "\n",
            "tests/test_acoustic_fidelity.py": "def test_ladder():\n    assert True\n",
            "tests/test_isaac_audio_core.py": "def test_core():\n    assert True\n",
            "tests/test_v1_scope_docs.py": "def test_scope():\n    assert True\n",
            ".local-goals/private.md": "local notes\n",
            "docs/private.md": "/home/" + "pacquadr/Desktop/private\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(".local-goals" in finding for finding in result.findings)
    assert any(
        "forbidden public-package text token" in finding
        for finding in result.findings
    )


def _scope_doc_text() -> str:
    return "\n".join(
        (
            "# V1 Public Scope",
            "Stable `AudioSensorFrame` v1 public contract",
            "Stable L0 `geometry_only` backend",
            "Stable L1 `tdoa_synthetic` backend",
            "Supported optional L2 `room_acoustics` backend",
            "Supported Isaac Sim live sensor path",
            "Supported Isaac Lab sensor path",
            "Omniverse extension as the reference UX",
            "Stable JSON/JSONL export",
            "Replicator as an optional extension capability",
            "SquadBot as a v1 release gate",
            "Sim-real calibration",
            "Real hardware benchmarks",
            "Complete L3/L4 acoustic fidelity",
            "Realistic occlusions or material acoustics",
            "Mandatory ROS 2 or downstream adapters",
            "Alex or SquadBot validation before releasing the sensor package",
            "",
        )
    )


def _write_sdist(path: Path, files: dict[str, str]) -> None:
    root = "isaac_audio_sensors-0.1.0"
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _write_wheel(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
