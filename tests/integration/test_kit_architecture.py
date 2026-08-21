"""Single contract for Kit service and presentation boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "src/isaac_audio_sensors/kit"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_kit_architecture_boundaries() -> None:
    view_imports = _imports(KIT / "window.py") | _imports(KIT / "sections.py")
    forbidden_view_roots = {
        "json",
        "os",
        "pathlib",
        "shutil",
        "tempfile",
        "pxr",
        "isaac_audio_sensors.isaac",
        "isaac_audio_sensors.recording",
    }
    assert not {
        name
        for name in view_imports
        if any(
            name == root or name.startswith(root + ".") for root in forbidden_view_roots
        )
    }

    controller_imports = _imports(KIT / "controller.py")
    assert not {
        name
        for name in controller_imports
        if name.startswith(
            (
                "isaac_audio_sensors.core",
                "isaac_audio_sensors.isaac",
                "isaac_audio_sensors.recording",
            )
        )
    }

    entrypoint = ast.parse(
        (
            ROOT / "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py"
        ).read_text(encoding="utf-8")
    )
    extension = next(
        node
        for node in entrypoint.body
        if isinstance(node, ast.ClassDef) and node.name == "Extension"
    )
    methods = {
        node.name for node in extension.body if isinstance(node, ast.FunctionDef)
    }
    assert methods == {"__init__", "on_startup", "on_shutdown"}
