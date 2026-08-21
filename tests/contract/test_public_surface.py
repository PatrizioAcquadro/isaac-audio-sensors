from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from isaac_audio_sensors import __version__
from isaac_audio_sensors.cli import main

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "isaac_audio_sensors"
ALLOWED_DEPENDENCIES = {
    "core": frozenset(),
    "recording": frozenset({"core"}),
    "isaac": frozenset({"core"}),
    "lab": frozenset({"core", "isaac"}),
    "kit": frozenset({"core", "recording", "isaac"}),
    "schemas": frozenset({"core", "recording"}),
    "cli": frozenset({"core", "recording", "kit", "schemas"}),
}


def _package_dependencies(package: str) -> set[str]:
    dependencies: set[str] = set()
    target = PACKAGE_ROOT / package
    paths = (target.with_suffix(".py"),) if package == "cli" else target.rglob("*.py")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = (node.module or "",)
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if len(parts) > 1 and parts[0] == "isaac_audio_sensors":
                    dependency = parts[1]
                    if dependency != package:
                        dependencies.add(dependency)
    return dependencies


def _run_fresh_process(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        (str(PACKAGE_ROOT.parent), env.get("PYTHONPATH", ""))
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_public_package_and_cli_version_match():
    result = subprocess.run(
        [sys.executable, "-m", "isaac_audio_sensors", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert __version__ == "1.10.0"
    assert result.stdout.strip() == __version__


def test_semantic_packages_follow_the_r5_dependency_graph():
    for package, allowed in ALLOWED_DEPENDENCIES.items():
        assert _package_dependencies(package) <= allowed


def test_minimal_root_and_v2_public_surfaces_in_fresh_process():
    completed = _run_fresh_process(
        """
        import importlib
        import sys

        package = importlib.import_module("isaac_audio_sensors")
        assert package.__all__ == ["__version__"]
        assert not hasattr(package, "AudioSensorFrame")
        assert not any(
            name.startswith("isaac_audio_sensors.") for name in sys.modules
        )

        core = importlib.import_module("isaac_audio_sensors.core")
        assert core.AudioSensorFrame.__module__ == "isaac_audio_sensors.core.types"
        assert not hasattr(core, "AudioDatasetManifest")
        assert "isaac_audio_sensors.recording" not in sys.modules

        recording = importlib.import_module("isaac_audio_sensors.recording")
        assert recording.AudioDatasetManifest.__module__.endswith(".manifest")
        assert callable(recording.manifest_from_dict)
        assert callable(recording.manifest_to_dict)

        schemas = importlib.import_module("isaac_audio_sensors.schemas.generate")
        assert callable(schemas.audio_sensor_frame_json_schema)

        for optional in ("omni", "pxr", "isaaclab", "torch"):
            assert optional not in sys.modules
        """
    )
    assert completed.stderr == ""


def test_removed_v1_surfaces_are_unavailable():
    completed = _run_fresh_process(
        """
        import importlib

        removed_modules = (
            "isaac_audio_sensors.core.schema",
            "isaac_audio_sensors.isaac.headless_workflow",
            "isaac_audio_sensors.usd_bounds",
            "isaac_audio_sensors.examples",
        )
        for name in removed_modules:
            try:
                importlib.import_module(name)
            except ModuleNotFoundError:
                pass
            else:
                raise AssertionError(f"removed module remains importable: {name}")
        """
    )
    assert completed.stderr == ""


def test_cli_exposes_current_product_operations(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for command in (
        "validate-config",
        "simulate",
        "export-trace",
        "export-schema",
        "capabilities",
        "dataset",
        "guided",
    ):
        assert command in help_text
    assert "s4" + "-2" not in help_text


def test_isaac_and_lab_import_without_loading_optional_runtimes():
    _run_fresh_process(
        """
        import sys
        import isaac_audio_sensors.isaac
        import isaac_audio_sensors.lab
        assert "omni.usd" not in sys.modules
        assert "isaaclab" not in sys.modules
        assert "torch" not in sys.modules
        """
    )
