"""Omniverse extension entrypoint."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_EXTENSION_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = _EXTENSION_ROOT / "isaac_audio_sensors"
_BUNDLED_ROOT = _PACKAGE_ROOT / "_bundled"


def _load_bundled_cffi(bundled_root: Path) -> None:
    # Kit's pip importer preloads CFFI; load the locked copies by exact path.
    for root_name in (
        "pycparser",
        "_cffi_backend",
        "cffi",
    ):
        module = sys.modules.get(root_name)
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str):
            try:
                Path(origin).resolve().relative_to(bundled_root.resolve())
                continue
            except (OSError, ValueError):
                pass
        for name in tuple(sys.modules):
            if name == root_name or name.startswith(f"{root_name}."):
                sys.modules.pop(name, None)
        spec = importlib.machinery.PathFinder.find_spec(
            root_name,
            [str(bundled_root)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"bundled dependency is unavailable: {root_name}")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[root_name] = loaded
        try:
            spec.loader.exec_module(loaded)
        except Exception:
            sys.modules.pop(root_name, None)
            raise


if _PACKAGE_ROOT.is_dir():
    if _BUNDLED_ROOT.is_dir():
        sys.path.insert(0, str(_BUNDLED_ROOT))
        _load_bundled_cffi(_BUNDLED_ROOT)
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
        if _BUNDLED_ROOT.is_dir():
            _load_bundled_cffi(_BUNDLED_ROOT)
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
