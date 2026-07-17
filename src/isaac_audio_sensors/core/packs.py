"""Fail-closed discovery and activation for private acoustic-pack installs."""

from __future__ import annotations

import hashlib
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
    owned_imports: set[str] = set()
    owned_files: set[str] = set()
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
        imports = distribution.get("top_level_imports")
        installed_files = distribution.get("installed_files")
        if (
            not isinstance(imports, list)
            or imports != sorted(set(imports))
            or not imports
            or not all(
                isinstance(module, str) and module.isidentifier()
                for module in imports
            )
        ):
            raise PackValidationError(
                f"pack distribution {name} has invalid top_level_imports"
            )
        if not isinstance(installed_files, dict) or not installed_files:
            raise PackValidationError(
                f"pack distribution {name} has invalid installed_files"
            )
        duplicate_imports = owned_imports.intersection(imports)
        duplicate_files = owned_files.intersection(installed_files)
        if duplicate_imports or duplicate_files:
            raise PackValidationError(
                "pack distribution ownership overlaps: "
                f"imports={sorted(duplicate_imports)}, files={sorted(duplicate_files)}"
            )
        owned_imports.update(imports)
        owned_files.update(installed_files)
        for relative, digest in installed_files.items():
            if (
                not isinstance(relative, str)
                or not _safe_relative_path(relative)
                or _SHA256_RE.fullmatch(str(digest)) is None
            ):
                raise PackValidationError(
                    f"pack distribution {name} has invalid installed-file hash"
                )
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


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        value not in {"", ".", ".."}
        and not path.is_absolute()
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in path.parts)
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


def _module_origins(module: ModuleType) -> tuple[Path, ...]:
    origin = _module_origin(module)
    if origin is not None:
        return (origin,)
    locations = getattr(module, "__path__", None)
    if locations is None:
        return ()
    resolved: list[Path] = []
    for location in locations:
        try:
            resolved.append(Path(location).resolve())
        except (OSError, TypeError):
            return ()
    return tuple(resolved)


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
        imports = distribution["top_level_imports"]
        assert isinstance(imports, list)
        for module_name in imports:
            assert isinstance(module_name, str)
            if not (root / module_name).exists() and not any(
                root.glob(f"{module_name}.*")
            ):
                raise PackValidationError(
                    f"pack distribution {name} has no importable top-level module "
                    f"{module_name!r} under {root}; reinstall the pack"
                )
    undeclared = sorted(set(installed) - set(expected))
    if undeclared:
        raise PackValidationError(
            f"undeclared distributions present under pack root: {undeclared}"
        )

    declared_imports = {
        module
        for distribution in pack_distributions
        if isinstance(distribution, dict)
        for module in distribution["top_level_imports"]
        if isinstance(module, str)
    }
    actual_imports = _installed_top_level_imports(root)
    if actual_imports != declared_imports:
        raise PackValidationError(
            "installed top-level import inventory mismatch: "
            f"missing={sorted(actual_imports - declared_imports)}, "
            f"stale={sorted(declared_imports - actual_imports)}; reinstall the pack"
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


def _installed_top_level_imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.iterdir():
        name = path.name
        if name.endswith((".dist-info", ".data")) or name == "__pycache__":
            continue
        if path.is_file():
            if name.endswith(".py"):
                candidate = name[:-3]
            elif name.endswith((".so", ".pyd")):
                candidate = name.split(".", 1)[0]
            else:
                continue
            if candidate.isidentifier():
                imports.add(candidate)
            continue
        if not path.is_dir() or not name.isidentifier():
            continue
        if any(
            child.is_file()
            and child.name.endswith((".py", ".so", ".pyd"))
            for child in path.rglob("*")
        ):
            imports.add(name)
    return imports


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_installed_file_integrity(
    root: Path, manifest: dict[str, object]
) -> None:
    rows = manifest["pack_distributions"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        installed_files = row["installed_files"]
        assert isinstance(installed_files, dict)
        for relative, expected in installed_files.items():
            assert isinstance(relative, str)
            path = root / relative
            if not path.is_file():
                raise PackValidationError(
                    f"installed pack file is missing: {relative}; reinstall the pack"
                )
            try:
                actual = _sha256_file(path)
            except OSError as exc:
                raise PackValidationError(
                    f"cannot verify installed pack file {relative}: {exc}"
                ) from exc
            if actual != expected:
                raise PackValidationError(
                    f"installed pack file integrity mismatch for {relative}: "
                    f"{actual} != {expected}; reinstall the pack"
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
    _validate_installed_file_integrity(root, manifest)
    _validate_host_requirements(root, manifest)
    return manifest


def _pack_module_names(manifest: dict[str, object]) -> tuple[str, ...]:
    rows = manifest["pack_distributions"]
    assert isinstance(rows, list)
    return tuple(
        module
        for row in rows
        if isinstance(row, dict)
        for module in row["top_level_imports"]
        if isinstance(module, str)
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
    module_names = _pack_module_names(manifest)
    owned_roots = set(module_names)
    for loaded_name, module in tuple(sys.modules.items()):
        if loaded_name.split(".", 1)[0] not in owned_roots or module is None:
            continue
        origins = _module_origins(module)
        if not origins or not all(_is_under(origin, root) for origin in origins):
            raise PackActivationError(
                f"provenance conflict for preloaded pack-managed module "
                f"{loaded_name!r} from {origins}; restart the process without the "
                "external/global/user-site module before activating this pack"
            )
    root_text = str(root)
    original_path = list(sys.path)
    original_modules = set(sys.modules)
    try:
        sys.path.insert(0, root_text)
        for module_name in module_names:
            module = importlib.import_module(module_name)
            origins = _module_origins(module)
            if not origins or not all(
                _is_under(origin, root) for origin in origins
            ):
                raise PackActivationError(
                    f"pack-managed module {module_name!r} imported from {origins}; "
                    f"expected an origin under {root}"
                )
        _ACTIVE_PACK_ROOT = root
        _ACTIVE_PACK_MANIFEST = manifest
        return manifest
    except Exception as exc:
        sys.path[:] = original_path
        for module_name in set(sys.modules) - original_modules:
            sys.modules.pop(module_name, None)
        _ACTIVE_PACK_ROOT = None
        _ACTIVE_PACK_MANIFEST = None
        if isinstance(exc, PackActivationError):
            raise
        raise PackActivationError(
            f"pack activation failed and was rolled back: {exc}"
        ) from exc


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
