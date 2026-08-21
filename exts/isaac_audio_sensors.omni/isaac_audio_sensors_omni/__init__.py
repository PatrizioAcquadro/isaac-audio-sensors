"""Omniverse extension entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

_EXTENSION_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = _EXTENSION_ROOT / "isaac_audio_sensors"
if _PACKAGE_ROOT.is_dir():
    bundled_root = _PACKAGE_ROOT / "_bundled"
    if bundled_root.is_dir():
        sys.path.insert(0, str(bundled_root))
else:
    repo_src = _EXTENSION_ROOT.parent.parent / "src"
    if not (repo_src / "isaac_audio_sensors").is_dir():
        raise RuntimeError(
            "isaac_audio_sensors is unavailable; use the packaged extension or "
            "restore the repository src directory."
        )
    sys.path.insert(0, str(repo_src))

from isaac_audio_sensors.kit import ExtensionController  # noqa: E402


def _i_ext_base() -> type:
    try:
        import omni.ext as omni_ext  # type: ignore
    except ImportError:
        return object
    return omni_ext.IExt


class Extension(_i_ext_base()):
    """Kit extension backed by the package controller."""

    def __init__(self) -> None:
        super().__init__()
        self.controller = ExtensionController()

    def on_startup(self, ext_id: str) -> None:
        self.controller.on_startup(ext_id)
        from .graph_node import register_omnigraph_node

        self.controller.state.omnigraph_status = register_omnigraph_node()
        self.controller.refresh_window()

    def on_shutdown(self) -> None:
        from .graph_node import deregister_omnigraph_node

        try:
            self.controller.state.omnigraph_status = deregister_omnigraph_node()
        finally:
            self.controller.on_shutdown()


__all__ = ["Extension"]
