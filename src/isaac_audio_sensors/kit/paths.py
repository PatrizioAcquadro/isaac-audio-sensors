"""Output-path resolution helpers for GUI file fields."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from .constants import DEFAULT_OUTPUT_ROOT, OUTPUT_ROOT_ENV_VAR, PROJECT_NAME
from .state import ExtensionActionError


def _gui_output_root() -> Path:
    """Return the absolute output root used by GUI file fields."""

    override = os.environ.get(OUTPUT_ROOT_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    repo_root = _find_project_root_from_module()
    if repo_root is not None:
        return (repo_root / DEFAULT_OUTPUT_ROOT).resolve()
    return (Path.cwd() / DEFAULT_OUTPUT_ROOT).resolve()


def _resolve_gui_output_path(path: str | Path) -> Path:
    """Resolve a GUI file field relative to the package output root."""

    raw = os.fspath(path).strip()
    if not raw:
        raise ExtensionActionError("Output path is empty.")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return _gui_output_root() / candidate


def _find_project_root_from_module() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.is_file():
            continue
        with suppress(OSError, UnicodeDecodeError):
            text = pyproject.read_text(encoding="utf-8")
            if f'name = "{PROJECT_NAME}"' in text or f"name = '{PROJECT_NAME}'" in text:
                return parent
    return None
