"""Omniverse extension entrypoint for isaac_audio_sensors."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any


def _resolve_package_source() -> dict[str, str] | None:
    """Select exactly one explicit core-package source mode."""

    extension_dir = Path(__file__).resolve().parents[1]
    packaged_sentinel = extension_dir / "_vendor" / "VENDORED.json"
    developer_sentinel = Path(__file__).with_name("DEVELOPMENT_MODE.json")

    packaged_present = packaged_sentinel.is_file()
    developer_present = developer_sentinel.is_file()
    if packaged_present and developer_present:
        raise RuntimeError(
            "Ambiguous isaac_audio_sensors extension mode: both "
            f"{packaged_sentinel} and {developer_sentinel} are present. "
            "Remove the developer sentinel from packaged extensions."
        )
    if not packaged_present and not developer_present:
        raise RuntimeError(
            "No valid isaac_audio_sensors extension mode sentinel was found. "
            f"Expected packaged metadata at {packaged_sentinel} or the tracked "
            f"developer sentinel at {developer_sentinel}. Rebuild the Kit archive "
            "or restore the source checkout sentinel."
        )

    if packaged_present:
        try:
            raw_metadata = json.loads(packaged_sentinel.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Packaged isaac_audio_sensors metadata is unreadable or corrupt: "
                f"{packaged_sentinel}: {exc}. Rebuild the Kit archive."
            ) from exc
        required = ("mode", "version", "source_revision", "tree_sha256")
        if not isinstance(raw_metadata, dict) or any(
            not isinstance(raw_metadata.get(key), str) or not raw_metadata[key]
            for key in required
        ):
            raise RuntimeError(
                "Packaged isaac_audio_sensors metadata is incomplete: "
                f"{packaged_sentinel} must contain non-empty string values for "
                f"{', '.join(required)}. Rebuild the Kit archive."
            )
        if raw_metadata["mode"] != "packaged":
            raise RuntimeError(
                "Packaged isaac_audio_sensors metadata has an invalid mode: "
                f"{raw_metadata['mode']!r}. Rebuild the Kit archive."
            )
        vendored_init = (
            extension_dir / "_vendor" / "isaac_audio_sensors" / "__init__.py"
        )
        if not vendored_init.is_file():
            raise RuntimeError(
                "Packaged isaac_audio_sensors source is missing: "
                f"{vendored_init}. Rebuild the Kit archive."
            )
        vendor_root = extension_dir / "_vendor"
        sys.path.insert(0, str(vendor_root))
        return {key: raw_metadata[key] for key in required}

    try:
        developer_metadata = json.loads(developer_sentinel.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Developer-mode sentinel is unreadable or corrupt: "
            f"{developer_sentinel}: {exc}. Restore the tracked sentinel."
        ) from exc
    if not isinstance(developer_metadata, dict) or developer_metadata.get("mode") != (
        "developer"
    ):
        raise RuntimeError(
            "Developer-mode sentinel is invalid: "
            f"{developer_sentinel} must contain mode='developer'. Restore the "
            "tracked sentinel."
        )

    try:
        importlib.import_module("isaac_audio_sensors")
        return None
    except ImportError:
        pass

    repo_src = extension_dir.parent.parent / "src"
    if (repo_src / "isaac_audio_sensors").is_dir():
        repo_src_text = str(repo_src)
        if repo_src_text not in sys.path:
            sys.path.insert(0, repo_src_text)
        return None
    raise RuntimeError(
        "Developer-mode isaac_audio_sensors source is unavailable. Install the "
        "package or place the repository src directory at "
        f"{repo_src}."
    )


def _assert_packaged_package(metadata: dict[str, str] | None, package: Any) -> None:
    if metadata is None:
        return

    extension_dir = Path(__file__).resolve().parents[1]
    vendor_root = (extension_dir / "_vendor").resolve()
    module_file = getattr(package, "__file__", None)
    try:
        if module_file is None:
            raise ValueError("module has no __file__")
        Path(module_file).resolve().relative_to(vendor_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Packaged isaac_audio_sensors resolved outside the extension vendor "
            f"tree: {module_file!r}; expected a path under {vendor_root}. Remove "
            "the conflicting package and rebuild the Kit archive."
        ) from exc
    imported_version = getattr(package, "__version__", None)
    if imported_version != metadata["version"]:
        raise RuntimeError(
            "Packaged isaac_audio_sensors version mismatch: metadata declares "
            f"{metadata['version']!r}, imported package declares "
            f"{imported_version!r}. Rebuild the Kit archive."
        )


_PACKAGE_METADATA = _resolve_package_source()

import isaac_audio_sensors as _isaac_audio_sensors  # noqa: E402

_assert_packaged_package(_PACKAGE_METADATA, _isaac_audio_sensors)

from isaac_audio_sensors.kit import ExtensionController  # noqa: E402


def _i_ext_base() -> type:
    try:
        import omni.ext as omni_ext  # type: ignore
    except ImportError:
        return object
    return omni_ext.IExt


class Extension(_i_ext_base()):
    """Kit extension entrypoint backed by an import-safe controller."""

    def __init__(self) -> None:
        super().__init__()
        self.controller = ExtensionController()

    def on_startup(self, ext_id: str) -> None:
        """Kit startup hook."""

        self.controller.on_startup(ext_id)
        from .graph_node import register_omnigraph_node

        self.controller.state.omnigraph_status = register_omnigraph_node()
        self.controller.refresh_window()

    def on_shutdown(self) -> None:
        """Kit shutdown hook."""

        from .graph_node import deregister_omnigraph_node

        try:
            self.controller.state.omnigraph_status = deregister_omnigraph_node()
        finally:
            self.controller.on_shutdown()


__all__ = ["Extension"]
