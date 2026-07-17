"""Fail-closed discovery and activation for private acoustic-pack installs."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import platform
import re
import sys
from pathlib import Path
from types import ModuleType

PACK_MANIFEST_SCHEMA = "ias.acoustic_pack_manifest.v1"
_PACK_ID = "acoustics-l2l3"
_LOCKED_TARGET = {
    "python_version": "3.12",
    "abi": "cp312",
    "os": "linux",
    "arch": "x86_64",
}
_PACK_DISTRIBUTION_NAMES = {
    "pyroomacoustics",
    "scipy",
    "soundfile",
    "cffi",
    "pycparser",
}
_CAPABILITY_IDS = {
    "room_acoustics",
    "room_acoustics_srp",
    "waveform_export_wav",
    "waveform_export_flac",
}
_CAPABILITY_CONTRACT = {
    "room_acoustics": ("backend", "L2", ["pyroomacoustics"], None),
    "room_acoustics_srp": ("backend", "L2", ["pyroomacoustics"], None),
    "waveform_export_wav": ("waveform_export", "L2", ["soundfile"], "WAV"),
    "waveform_export_flac": ("waveform_export", "L2", ["soundfile"], "FLAC"),
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ACTIVE_PACK_ROOT: Path | None = None
_ACTIVE_PACK_MANIFEST: dict[str, object] | None = None


class PackError(RuntimeError):
    """Base exception for actionable acoustic-pack failures."""


class PackValidationError(PackError):
    """Raised before activation when an installed pack is invalid."""


class PackActivationError(PackError):
    """Raised when process provenance prevents safe pack activation."""


def default_pack_root() -> Path:
    """Return the private sensor-project pack installation root."""

    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "isaac_audio_sensors" / "packs"
    return Path.home() / ".local" / "share" / "isaac_audio_sensors" / "packs"


def discover_pack_installs(root: str | Path | None = None) -> tuple[Path, ...]:
    """Return validated completed version roots in deterministic order.

    Hidden staging directories, partial trees, unreadable manifests, and
    runtime-incompatible installs are never candidates.
    """

    base = Path(root).expanduser() if root is not None else default_pack_root()
    if not base.is_dir():
        return ()
    candidates: list[Path] = []
    for pack_dir in sorted(base.iterdir(), key=lambda path: path.name):
        if not pack_dir.is_dir() or pack_dir.name.startswith("."):
            continue
        for version_dir in sorted(pack_dir.iterdir(), key=lambda path: path.name):
            if not version_dir.is_dir() or version_dir.name.startswith("."):
                continue
            if not (version_dir / "pack_manifest.json").is_file():
                continue
            try:
                validate_pack_install(version_dir)
            except PackValidationError:
                continue
            candidates.append(version_dir.resolve())
    return tuple(candidates)


def _current_sensor_version() -> str:
    from isaac_audio_sensors import __version__

    return __version__


def _runtime_target() -> dict[str, str]:
    machine = platform.machine().lower()
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "abi": f"cp{sys.version_info.major}{sys.version_info.minor}",
        "os": "linux" if sys.platform.startswith("linux") else sys.platform,
        "arch": {"amd64": "x86_64"}.get(machine, machine),
    }


def _load_manifest(root: Path) -> dict[str, object]:
    path = root / "pack_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackValidationError(
            f"pack manifest is missing or unreadable at {path}: {exc}; reinstall "
            "the acoustic pack from its verified archive"
        ) from exc
    if not isinstance(manifest, dict):
        raise PackValidationError(f"pack manifest at {path} must be a JSON object")
    return manifest


def _require_nonempty_string(
    mapping: dict[str, object], field: str, *, context: str
) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise PackValidationError(f"{context}.{field} must be a non-empty string")
    return value


def _validate_manifest_shape(root: Path, manifest: dict[str, object]) -> None:
    required = {
        "schema",
        "pack_id",
        "pack_version",
        "sensor_package_version",
        "python_version",
        "abi",
        "os",
        "arch",
        "host_requirements",
        "numpy_compatibility",
        "pack_distributions",
        "capabilities",
        "build_provenance",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise PackValidationError(f"pack manifest required fields missing: {missing}")
    if manifest.get("schema") != PACK_MANIFEST_SCHEMA:
        raise PackValidationError(
            f"unsupported pack manifest schema {manifest.get('schema')!r}; "
            f"expected {PACK_MANIFEST_SCHEMA!r}"
        )
    for field in (
        "pack_id",
        "pack_version",
        "sensor_package_version",
        "python_version",
        "abi",
        "os",
        "arch",
        "numpy_compatibility",
    ):
        _require_nonempty_string(manifest, field, context="manifest")
    pack_id = str(manifest["pack_id"])
    pack_version = str(manifest["pack_version"])
    if not _safe_path_component(pack_id) or not _safe_path_component(pack_version):
        raise PackValidationError("manifest pack_id/pack_version are unsafe")
    if pack_id != _PACK_ID:
        raise PackValidationError(
            f"unsupported acoustic pack id {pack_id!r}; expected {_PACK_ID!r}"
        )
    if manifest["numpy_compatibility"] != ">=2.0,<2.8":
        raise PackValidationError(
            "manifest numpy_compatibility must be the locked range '>=2.0,<2.8'"
        )
    for field, expected in _LOCKED_TARGET.items():
        if manifest[field] != expected:
            raise PackValidationError(
                f"manifest target {field} must be {expected!r}, got "
                f"{manifest[field]!r}"
            )
    if root.name != pack_version or root.parent.name != pack_id:
        raise PackValidationError(
            "pack root identity does not match manifest: expected path ending in "
            f"{pack_id}/{pack_version}, got {root}"
        )

    host_requirements = manifest["host_requirements"]
    pack_distributions = manifest["pack_distributions"]
    capabilities = manifest["capabilities"]
    if not isinstance(host_requirements, list) or not host_requirements:
        raise PackValidationError("manifest.host_requirements must be a non-empty list")
    if not isinstance(pack_distributions, list) or not pack_distributions:
        raise PackValidationError(
            "manifest.pack_distributions must be a non-empty list"
        )
    if not isinstance(capabilities, list) or not capabilities:
        raise PackValidationError("manifest.capabilities must be a non-empty list")
    for index, requirement in enumerate(host_requirements):
        if not isinstance(requirement, dict):
            raise PackValidationError(f"host_requirements[{index}] must be an object")
        for field in ("name", "version", "reason"):
            _require_nonempty_string(
                requirement, field, context=f"host_requirements[{index}]"
            )
    host_names = {
        _normalized_distribution_name(str(requirement["name"]))
        for requirement in host_requirements
        if isinstance(requirement, dict)
    }
    if "numpy" not in host_names:
        raise PackValidationError(
            "manifest.host_requirements must declare host-owned numpy"
        )
    wheel_names: set[str] = set()
    distribution_names: set[str] = set()
    for index, distribution in enumerate(pack_distributions):
        if not isinstance(distribution, dict):
            raise PackValidationError(
                f"pack_distributions[{index}] must be an object"
            )
        for field in ("name", "version", "wheel", "sha256"):
            _require_nonempty_string(
                distribution, field, context=f"pack_distributions[{index}]"
            )
        name = str(distribution["name"]).lower().replace("-", "_")
        wheel = str(distribution["wheel"])
        if name in distribution_names or wheel in wheel_names:
            raise PackValidationError(
                "duplicate pack distribution or wheel declaration"
            )
        distribution_names.add(name)
        wheel_names.add(wheel)
        if Path(wheel).name != wheel:
            raise PackValidationError(f"unsafe wheel filename in manifest: {wheel!r}")
        if _SHA256_RE.fullmatch(str(distribution["sha256"])) is None:
            raise PackValidationError(f"invalid wheel sha256 in manifest: {wheel}")
    if distribution_names != _PACK_DISTRIBUTION_NAMES:
        raise PackValidationError(
            "manifest pack_distributions names do not match the locked acoustic "
            f"set: {sorted(distribution_names)}"
        )
    capability_ids: set[str] = set()
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            raise PackValidationError(f"capabilities[{index}] must be an object")
        for field in ("id", "kind", "fidelity_level"):
            _require_nonempty_string(
                capability, field, context=f"capabilities[{index}]"
            )
        modules = capability.get("modules")
        if not isinstance(modules, list) or not modules or not all(
            isinstance(module, str) and module for module in modules
        ):
            raise PackValidationError(
                f"capabilities[{index}].modules must be a non-empty string list"
            )
        capability_id = str(capability["id"])
        if capability_id in capability_ids:
            raise PackValidationError(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)
        expected_kind, expected_level, expected_modules, expected_format = (
            _CAPABILITY_CONTRACT.get(capability_id, (None, None, None, None))
        )
        if (
            capability.get("kind") != expected_kind
            or capability.get("fidelity_level") != expected_level
            or capability.get("modules") != expected_modules
            or (
                expected_format is not None
                and capability.get("format") != expected_format
            )
        ):
            raise PackValidationError(
                f"capability declaration {capability_id!r} does not match the "
                "acoustic fidelity contract"
            )
    if capability_ids != _CAPABILITY_IDS:
        raise PackValidationError(
            "manifest capability ids do not match the acoustic-pack contract: "
            f"{sorted(capability_ids)}"
        )
    provenance = manifest["build_provenance"]
    if not isinstance(provenance, dict):
        raise PackValidationError("manifest.build_provenance must be an object")
    for field in ("git_revision", "build_tool_version"):
        _require_nonempty_string(provenance, field, context="build_provenance")


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _safe_path_component(value: str) -> bool:
    return (
        value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def _module_name(distribution_name: str) -> str:
    return distribution_name.lower().replace("-", "_")


def _is_under(path: str | Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _module_origin(module: ModuleType) -> Path | None:
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str) or not origin:
        return None
    try:
        return Path(origin).resolve()
    except OSError:
        return None


def _installed_distributions(root: Path) -> dict[str, str]:
    installed: dict[str, str] = {}
    try:
        distributions = importlib.metadata.distributions(path=[str(root)])
        for distribution in distributions:
            name = distribution.metadata.get("Name")
            if not name:
                continue
            normalized = _normalized_distribution_name(name)
            if normalized in installed:
                raise PackValidationError(
                    f"duplicate distribution metadata under pack root: {name}"
                )
            installed[normalized] = distribution.version
    except PackValidationError:
        raise
    except Exception as exc:
        raise PackValidationError(
            f"cannot inspect distribution metadata under {root}: {exc}"
        ) from exc
    return installed


def _validate_installed_distributions(
    root: Path, manifest: dict[str, object]
) -> None:
    installed = _installed_distributions(root)
    expected: dict[str, str] = {}
    pack_distributions = manifest["pack_distributions"]
    assert isinstance(pack_distributions, list)
    for distribution in pack_distributions:
        assert isinstance(distribution, dict)
        name = str(distribution["name"])
        normalized = _normalized_distribution_name(name)
        version = str(distribution["version"])
        expected[normalized] = version
        if installed.get(normalized) != version:
            raise PackValidationError(
                f"pack distribution {name}=={version} is missing or has version "
                f"{installed.get(normalized)!r} under {root}; reinstall the pack"
            )
        module_name = _module_name(name)
        if not (root / module_name).exists() and not (
            root / f"{module_name}.py"
        ).is_file():
            raise PackValidationError(
                f"pack distribution {name} has no importable top-level module "
                f"under {root}; reinstall the pack"
            )
    undeclared = sorted(set(installed) - set(expected))
    if undeclared:
        raise PackValidationError(
            f"undeclared distributions present under pack root: {undeclared}"
        )

    host_requirements = manifest["host_requirements"]
    assert isinstance(host_requirements, list)
    for requirement in host_requirements:
        assert isinstance(requirement, dict)
        name = str(requirement["name"])
        normalized = _normalized_distribution_name(name)
        module_name = _module_name(name)
        if normalized in installed or (root / module_name).exists() or (
            root / f"{module_name}.py"
        ).exists():
            raise PackValidationError(
                f"host requirement {name} is present under private pack root {root}; "
                "remove this invalid pack because host dependencies must never be "
                "installed or shadowed"
            )


def _validate_host_requirements(root: Path, manifest: dict[str, object]) -> None:
    host_requirements = manifest["host_requirements"]
    assert isinstance(host_requirements, list)
    for requirement in host_requirements:
        assert isinstance(requirement, dict)
        name = str(requirement["name"])
        version = str(requirement["version"])
        module_name = _module_name(name)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise PackValidationError(
                f"host requirement {name}=={version} is not importable; use the "
                "supported Kit runtime before activating this pack"
            ) from exc
        origin = _module_origin(module)
        if origin is None or _is_under(origin, root):
            raise PackValidationError(
                f"host requirement {name} has invalid import origin {origin}; "
                "it must be owned by the host outside the private pack root"
            )
        try:
            actual_version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual_version = getattr(module, "__version__", None)
        if actual_version != version:
            raise PackValidationError(
                f"host requirement {name} version mismatch: expected {version}, "
                f"got {actual_version!r} from {origin}; select the supported runtime"
            )


def validate_pack_install(path: str | Path) -> dict[str, object]:
    """Validate a completed private pack root without importing pack code."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir() or root.name.startswith("."):
        raise PackValidationError(
            f"pack root is not a completed selectable directory: {root}"
        )
    manifest = _load_manifest(root)
    _validate_manifest_shape(root, manifest)
    expected_version = _current_sensor_version()
    if manifest["sensor_package_version"] != expected_version:
        raise PackValidationError(
            "pack/package version mismatch: pack targets "
            f"{manifest['sensor_package_version']!r}, current package is "
            f"{expected_version!r}; install the matching pack artifact"
        )
    runtime = _runtime_target()
    for field, actual in runtime.items():
        if manifest[field] != actual:
            raise PackValidationError(
                f"pack runtime mismatch for {field}: expected {manifest[field]!r}, "
                f"running interpreter is {actual!r}; use the Linux cp312/x86_64 "
                "reference runtime"
            )
    _validate_installed_distributions(root, manifest)
    _validate_host_requirements(root, manifest)
    return manifest


def _pack_module_names(manifest: dict[str, object]) -> tuple[str, ...]:
    rows = manifest["pack_distributions"]
    assert isinstance(rows, list)
    return tuple(
        _module_name(str(row["name"])) for row in rows if isinstance(row, dict)
    )


def activate_pack(path: str | Path) -> dict[str, object]:
    """Validate and atomically apply one pack root to process import precedence."""

    global _ACTIVE_PACK_MANIFEST, _ACTIVE_PACK_ROOT
    root = Path(path).expanduser().resolve()
    if _ACTIVE_PACK_ROOT is not None:
        if root == _ACTIVE_PACK_ROOT:
            assert _ACTIVE_PACK_MANIFEST is not None
            return _ACTIVE_PACK_MANIFEST
        raise PackActivationError(
            f"pack {_ACTIVE_PACK_ROOT} is already active; activation is "
            f"once-per-process and cannot switch to {root}"
        )
    manifest = validate_pack_install(root)
    for module_name in _pack_module_names(manifest):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        origin = _module_origin(module)
        if origin is None or not _is_under(origin, root):
            raise PackActivationError(
                f"provenance conflict for preloaded pack-managed module "
                f"{module_name!r} from {origin}; restart the process without the "
                "external/global/user-site module before activating this pack"
            )
    root_text = str(root)
    sys.path.insert(0, root_text)
    _ACTIVE_PACK_ROOT = root
    _ACTIVE_PACK_MANIFEST = manifest
    return manifest


def active_pack_root() -> Path | None:
    """Return the active validated pack root, if any."""

    return _ACTIVE_PACK_ROOT


def active_pack_manifest() -> dict[str, object] | None:
    """Return the active validated pack manifest, if any."""

    return _ACTIVE_PACK_MANIFEST


__all__ = [
    "PACK_MANIFEST_SCHEMA",
    "PackActivationError",
    "PackError",
    "PackValidationError",
    "activate_pack",
    "active_pack_manifest",
    "active_pack_root",
    "default_pack_root",
    "discover_pack_installs",
    "validate_pack_install",
]
