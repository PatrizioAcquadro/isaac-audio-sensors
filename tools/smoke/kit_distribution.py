"""Live extension registration, metadata and dependency provenance."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from kit_capture import (
    _settle_kit_ui,
)
from kit_common import (
    _pump_kit_app,
)

from isaac_audio_sensors.kit.constants import (
    OMNI_WINDOW_TITLE,
)

EXTENSION_ID = "isaac_audio_sensors.omni"


BUNDLED_DEPENDENCIES = (
    "auditok",
    "pyroomacoustics",
    "scipy",
    "soundfile",
    "cffi",
    "pycparser",
)


HOST_DEPENDENCIES = ("numpy", "typing_extensions")


def _probe_package_origin(extension_path: Path) -> dict[str, Any]:
    package = sys.modules.get("isaac_audio_sensors")
    module_file = getattr(package, "__file__", None)
    packaged_root = extension_path / "isaac_audio_sensors"
    expected_root = (
        packaged_root
        if packaged_root.is_dir()
        else extension_path.parent.parent / "src" / "isaac_audio_sensors"
    )
    try:
        if module_file is None:
            raise ValueError("package has no __file__")
        Path(module_file).resolve().relative_to(expected_root.resolve())
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "module_file": str(module_file),
            "expected_root": str(expected_root),
            "reason": str(exc),
        }
    return {
        "status": "passed",
        "mode": "packaged" if packaged_root.is_dir() else "source",
        "module_file": str(Path(module_file).resolve()),
        "expected_root": str(expected_root.resolve()),
    }


def _probe_dependency_origins(extension_path: Path) -> dict[str, Any]:
    bundled_root = extension_path / "isaac_audio_sensors" / "_bundled"
    packaged = bundled_root.is_dir()
    record: dict[str, Any] = {
        "mode": "packaged" if packaged else "source",
        "bundled_root": str(bundled_root),
        "modules": {},
    }
    for name in (*BUNDLED_DEPENDENCIES, *HOST_DEPENDENCIES):
        try:
            module = importlib.import_module(name)
            module_file = getattr(module, "__file__", None)
        except Exception as exc:  # noqa: BLE001 - evidence records exact import failure
            record["modules"][name] = {
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        inside_bundle = False
        if isinstance(module_file, str):
            try:
                Path(module_file).resolve().relative_to(bundled_root.resolve())
                inside_bundle = True
            except (OSError, ValueError):
                pass
        record["modules"][name] = {
            "status": "available",
            "module_file": str(module_file),
            "inside_bundle": inside_bundle,
        }

    from isaac_audio_sensors.core.capabilities import discover_capabilities

    report = discover_capabilities()
    record["capabilities"] = {
        name: report.get(name).origin
        for name in (
            "L2",
            "analytic_acoustics_closed_rooms",
            "waveform_export_flac",
        )
    }
    try:
        import numpy as np

        from isaac_audio_sensors.core.plugins import AuditokActivityDetector

        detector = AuditokActivityDetector(
            energy_threshold_dbfs=-20.0,
            analysis_window_s=0.01,
            min_activity_s=0.01,
            max_silence_s=0.0,
        )
        decision = detector.detect(
            np.full((1, 10), 0.2, dtype=np.float32),
            1_000,
        )
        record["auditok_detector"] = {
            "status": "passed" if decision.active else "failed",
            "active": decision.active,
            "version": decision.diagnostics.get("auditok_version"),
        }
    except Exception as exc:  # noqa: BLE001 - evidence records exact failure
        record["auditok_detector"] = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not packaged:
        record["status"] = record["auditok_detector"]["status"]
        return record

    bundled_ok = all(
        record["modules"].get(name, {}).get("inside_bundle") is True
        for name in BUNDLED_DEPENDENCIES
    )
    host_ok = all(
        record["modules"].get(name, {}).get("status") == "available"
        and record["modules"][name].get("inside_bundle") is False
        for name in HOST_DEPENDENCIES
    )
    capabilities_ok = set(record["capabilities"].values()) == {"bundled"}
    detector_ok = record["auditok_detector"]["status"] == "passed"
    record["status"] = (
        "passed"
        if bundled_ok and host_ok and capabilities_ok and detector_ok
        else "failed"
    )
    return record


def _probe_extension_manager_metadata(
    ext_path: Path,
    *,
    extension_id: str,
) -> dict[str, Any]:
    manifest_path = ext_path / "config" / "extension.toml"
    try:
        import tomllib

        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        package = manifest.get("package", {})
    except Exception as exc:  # noqa: BLE001 - evidence records exact runtime issue.
        return {
            "status": "failed",
            "manifest_path": str(manifest_path),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    if package.get("exchange", False):
        author_group = "COMMUNITY_VERIFIED"
    elif not package.get("trusted", True):
        author_group = "COMMUNITY_UNVERIFIED"
    else:
        author_group = "NVIDIA"
    ext_source = "NVIDIA" if author_group == "NVIDIA" else "THIRD PARTY"

    resources = {}
    for key in ("readme", "changelog", "icon", "preview_image"):
        relative_path = package.get(key, "")
        path = ext_path / relative_path
        resources[key] = {
            "relative_path": relative_path,
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }

    required_keywords = {"audio", "microphone", "sensor", "robotics", "tdoa"}
    keywords = set(package.get("keywords", ()))
    missing_keywords = sorted(required_keywords - keywords)
    missing_resources = [
        key
        for key, value in resources.items()
        if not value["exists"] or int(value["size_bytes"]) <= 0
    ]
    kit_common_info = _probe_kit_extension_common_info(
        extension_id=extension_id,
        ext_path=ext_path,
        manifest_package=package,
    )
    kit_source_status = kit_common_info.get("status")
    kit_source = kit_common_info.get("ext_source")
    passed = (
        ext_source == "THIRD PARTY"
        and package.get("category", "").lower() == "simulation"
        and bool(package.get("repository"))
        and not missing_keywords
        and not missing_resources
        and (
            kit_source_status == "unavailable"
            or (kit_source_status == "passed" and kit_source == "THIRD PARTY")
        )
    )
    return {
        "status": "passed" if passed else "failed",
        "manifest_path": str(manifest_path),
        "ext_source": ext_source,
        "author_group": author_group,
        "category": package.get("category", ""),
        "repository": package.get("repository", ""),
        "keywords": sorted(keywords),
        "missing_keywords": missing_keywords,
        "resources": resources,
        "missing_resources": missing_resources,
        "kit_window_extensions_common": kit_common_info,
    }


def _probe_kit_extension_common_info(
    *,
    extension_id: str,
    ext_path: Path,
    manifest_package: dict[str, Any],
) -> dict[str, Any]:
    try:
        from omni.kit.window.extensions.common import (  # type: ignore
            ExtensionCommonInfo,
        )
    except Exception as exc:  # noqa: BLE001 - unavailable outside Kit.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}

    package = dict(manifest_package)
    package.setdefault("name", extension_id)
    package.setdefault("id", f"{extension_id}-{package.get('version', '0.0.0')}")
    package.setdefault("packageId", package["id"])
    ext_info = {
        "package": package,
        "path": str(ext_path),
        "configPath": str(ext_path / "config" / "extension.toml"),
        "isInCache": False,
        "isUser": False,
        "isKitFile": False,
        "state": {
            "enabled": True,
            "reloadable": True,
            "failed": False,
        },
    }
    try:
        common_info = ExtensionCommonInfo(package["id"], ext_info, is_local=True)
    except Exception as exc:  # noqa: BLE001 - evidence should capture API drift.
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}

    ext_source = getattr(common_info, "ext_source", None)
    author_group = getattr(common_info, "author_group", None)
    return {
        "status": "passed",
        "ext_source": _enum_ui_name(ext_source),
        "author_group": _enum_ui_name(author_group),
        "is_untrusted": getattr(common_info, "is_untrusted", None),
        "category": getattr(common_info, "category", ""),
        "repository": getattr(common_info, "repository", ""),
        "icon_path": getattr(common_info, "icon_path", ""),
        "preview_image_path": getattr(common_info, "preview_image_path", ""),
    }


def _enum_ui_name(value: Any) -> str:
    get_ui_name = getattr(value, "get_ui_name", None)
    if callable(get_ui_name):
        return str(get_ui_name())
    name = getattr(value, "name", None)
    if name is not None:
        return str(name)
    return str(value)


def _try_enable_extension_manager(
    *,
    extension_id: str,
    extension_path: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "requested_extension_id": extension_id,
        "extension_path": str(extension_path),
    }
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        manager = app.get_extension_manager() if app is not None else None
        if manager is None:
            return {"status": "unavailable", "reason": "no extension manager"}
        result["manager_type"] = type(manager).__name__
        manager.add_path(str(extension_path.parent))
        result["search_path_method"] = "add_path"
        result["enable_result"] = str(
            manager.set_extension_enabled_immediate(extension_id, True)
        )
        result["enable_method"] = "set_extension_enabled_immediate"
        result["kit_update_after_enable"] = _pump_kit_app(app)
        enabled_id = manager.get_enabled_extension_id(extension_id)
        enabled = bool(manager.is_extension_enabled(extension_id) and enabled_id)
        result["verification"] = {
            "enabled": enabled,
            "enabled_extension_id": str(enabled_id) if enabled_id else None,
        }
        result["status"] = "enabled" if enabled else "enable_called_unverified"
        return result
    except Exception as exc:  # noqa: BLE001 - evidence records exact runtime issue.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _destroy_workspace_extension_window() -> dict[str, Any]:
    """Release the manual window before the manager lifecycle probe."""

    try:
        import omni.ui  # type: ignore

        workspace = getattr(omni.ui, "Workspace", None)
        getter = getattr(workspace, "get_window", None)
        window = getter(OMNI_WINDOW_TITLE) if callable(getter) else None
        if window is None:
            return {"status": "not_found"}
        destroy = getattr(window, "destroy", None)
        if not callable(destroy):
            window.visible = False
            status = "hidden"
        else:
            destroy()
            status = "destroyed"
        _settle_kit_ui(updates=8)
        return {"status": status}
    except Exception as exc:  # noqa: BLE001 - smoke records UI ownership drift.
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}


def _try_disable_extension_manager(*, extension_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"requested_extension_id": extension_id}
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        manager = app.get_extension_manager() if app is not None else None
        if manager is None:
            return {"status": "unavailable", "reason": "no extension manager"}
        result["disable_result"] = str(
            manager.set_extension_enabled_immediate(extension_id, False)
        )
        result["disable_method"] = "set_extension_enabled_immediate"
        result["kit_update_after_disable"] = _pump_kit_app(app)
        requested_enabled = bool(manager.is_extension_enabled(extension_id))
        base_enabled = bool(manager.is_extension_enabled(EXTENSION_ID))
        enabled_id = manager.get_enabled_extension_id(EXTENSION_ID)
        result["verification"] = {
            "disabled": not requested_enabled and not base_enabled and not enabled_id,
            "requested_extension_enabled": requested_enabled,
            "base_extension_enabled": base_enabled,
            "enabled_extension_id": str(enabled_id) if enabled_id else None,
        }
        result["status"] = (
            "disabled" if result["verification"]["disabled"] else "disable_failed"
        )
        return result
    except Exception as exc:  # noqa: BLE001 - evidence records exact failure.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def _enabled_extension_id(evidence: dict[str, Any]) -> str | None:
    value = (
        evidence.get("kit_extension_manager", {})
        .get("verification", {})
        .get("enabled_extension_id")
    )
    if value:
        return str(value)
    return None
