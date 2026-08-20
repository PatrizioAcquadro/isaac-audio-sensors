"""Install an acoustic pack offline into its private immutable version root.

The post-install self-check requires the invoking interpreter to provide the
manifest's host requirements. The installer never downloads or installs those
host-owned distributions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import uuid
from pathlib import Path

MANIFEST_SCHEMA = "ias.acoustic_pack_manifest.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class PackInstallError(RuntimeError):
    """Raised when an offline pack installation cannot complete safely."""


def _default_root() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "isaac_audio_sensors" / "packs"
    return Path.home() / ".local" / "share" / "isaac_audio_sensors" / "packs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackInstallError(f"cannot read pack manifest {path}: {exc}") from exc
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
    if not isinstance(value, dict):
        raise PackInstallError("pack_manifest.json must contain a JSON object")
    missing = sorted(required - value.keys())
    if missing:
        raise PackInstallError(f"pack manifest missing required fields: {missing}")
    if value.get("schema") != MANIFEST_SCHEMA:
        raise PackInstallError(
            f"unsupported pack manifest schema: {value.get('schema')!r}"
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
        if not isinstance(value.get(field), str) or not value[field]:
            raise PackInstallError(f"pack manifest field {field!r} must be a string")
    for field in ("host_requirements", "pack_distributions", "capabilities"):
        if not isinstance(value.get(field), list):
            raise PackInstallError(f"pack manifest field {field!r} must be a list")
    return value


def _runtime_abi() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _runtime_os() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def _runtime_arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x86_64"}.get(machine, machine)


def _validate_runtime(manifest: dict[str, object]) -> None:
    locked = {
        "python_version": "3.12",
        "abi": "cp312",
        "os": "linux",
        "arch": "x86_64",
    }
    declared = {key: manifest[key] for key in locked}
    if declared != locked:
        raise PackInstallError(
            f"pack target is not the supported Linux cp312/x86_64 target: {declared}"
        )
    actual = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "abi": _runtime_abi(),
        "os": _runtime_os(),
        "arch": _runtime_arch(),
    }
    if actual != locked:
        soabi = sysconfig.get_config_var("SOABI")
        raise PackInstallError(
            "unsupported interpreter for this acoustic pack: "
            f"expected {locked}, got {actual} (SOABI={soabi!r})"
        )


def _validate_wheels(pack_dir: Path, manifest: dict[str, object]) -> None:
    wheels_dir = pack_dir / "wheels"
    distributions = manifest["pack_distributions"]
    assert isinstance(distributions, list)
    expected: dict[str, str] = {}
    owned_imports: set[str] = set()
    owned_files: set[str] = set()
    for index, item in enumerate(distributions):
        if not isinstance(item, dict):
            raise PackInstallError(
                f"pack_distributions[{index}] must be a JSON object"
            )
        for field in ("name", "version", "wheel", "sha256"):
            if not isinstance(item.get(field), str) or not item[field]:
                raise PackInstallError(
                    f"pack_distributions[{index}].{field} must be a string"
                )
        imports = item.get("top_level_imports")
        installed_files = item.get("installed_files")
        if (
            not isinstance(imports, list)
            or imports != sorted(set(imports))
            or not imports
            or not all(
                isinstance(name, str) and name.isidentifier() for name in imports
            )
        ):
            raise PackInstallError(
                f"pack_distributions[{index}].top_level_imports is invalid"
            )
        if not isinstance(installed_files, dict) or not installed_files:
            raise PackInstallError(
                f"pack_distributions[{index}].installed_files is invalid"
            )
        duplicate_imports = owned_imports.intersection(imports)
        duplicate_files = owned_files.intersection(installed_files)
        if duplicate_imports or duplicate_files:
            raise PackInstallError(
                "pack distribution ownership overlaps: "
                f"imports={sorted(duplicate_imports)}, files={sorted(duplicate_files)}"
            )
        owned_imports.update(imports)
        owned_files.update(installed_files)
        for relative, digest in installed_files.items():
            if (
                not isinstance(relative, str)
                or not _safe_relative_path(relative)
                or SHA256_RE.fullmatch(str(digest)) is None
            ):
                raise PackInstallError(
                    f"pack_distributions[{index}] has invalid installed-file hash"
                )
        filename = item["wheel"]
        sha256 = item["sha256"]
        if Path(filename).name != filename or SHA256_RE.fullmatch(sha256) is None:
            raise PackInstallError(
                f"invalid wheel filename or sha256 in pack_distributions[{index}]"
            )
        if filename in expected:
            raise PackInstallError(f"duplicate wheel in manifest: {filename}")
        expected[filename] = sha256
    if not wheels_dir.is_dir():
        raise PackInstallError(f"pack wheels directory is missing: {wheels_dir}")
    actual = {path.name for path in wheels_dir.iterdir()}
    if actual != set(expected):
        raise PackInstallError(
            "wheel directory does not exactly match manifest: "
            f"missing={sorted(set(expected) - actual)}, "
            f"extra={sorted(actual - set(expected))}"
        )
    for filename, expected_sha256 in expected.items():
        if not (wheels_dir / filename).is_file():
            raise PackInstallError(f"locked wheel is not a regular file: {filename}")
        actual_sha256 = _sha256(wheels_dir / filename)
        if actual_sha256 != expected_sha256:
            raise PackInstallError(
                f"wheel sha256 mismatch for {filename}: "
                f"{actual_sha256} != {expected_sha256}"
            )


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        value not in {"", ".", ".."}
        and not path.is_absolute()
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _owned_imports(manifest: dict[str, object]) -> tuple[str, ...]:
    distributions = manifest["pack_distributions"]
    assert isinstance(distributions, list)
    return tuple(
        module
        for item in distributions
        if isinstance(item, dict)
        for module in item["top_level_imports"]
        if isinstance(module, str)
    )


def _validate_installed_files(staging: Path, manifest: dict[str, object]) -> None:
    distributions = manifest["pack_distributions"]
    assert isinstance(distributions, list)
    for item in distributions:
        assert isinstance(item, dict)
        installed_files = item["installed_files"]
        assert isinstance(installed_files, dict)
        for relative, expected in installed_files.items():
            assert isinstance(relative, str)
            path = staging / relative
            if not path.is_file():
                raise PackInstallError(
                    f"installed file missing after pip install: {relative}"
                )
            actual = _sha256(path)
            if actual != expected:
                raise PackInstallError(
                    f"installed file integrity mismatch for {relative}: "
                    f"{actual} != {expected}"
                )


def _self_check_script(staging: Path, manifest: dict[str, object]) -> str:
    host_requirements = manifest["host_requirements"]
    assert isinstance(host_requirements, list)
    return "\n".join(
        (
            "import importlib, importlib.metadata, json, pathlib, sys",
            f"root = pathlib.Path({str(staging)!r}).resolve()",
            "sys.path.insert(0, str(root))",
            f"pack_imports = {_owned_imports(manifest)!r}",
            f"host_requirements = json.loads({json.dumps(host_requirements)!r})",
            "def inside(path):",
            "    try: return pathlib.Path(path).resolve().is_relative_to(root)",
            "    except (AttributeError, ValueError):",
            "        try: pathlib.Path(path).resolve().relative_to(root); return True",
            "        except ValueError: return False",
            "def origins(module):",
            "    origin = getattr(module, '__file__', None)",
            "    if origin: return (origin,)",
            "    paths = getattr(module, '__path__', None)",
            "    return tuple(paths) if paths is not None else ()",
            "for name in pack_imports:",
            "    loaded = sys.modules.get(name)",
            "    loaded_origins = origins(loaded) if loaded else ()",
            "    if loaded is not None and (not loaded_origins or",
            "            not all(inside(origin) for origin in loaded_origins)):",
            "        raise RuntimeError(f'externally preloaded owned import {name}')",
            "    module = importlib.import_module(name)",
            "    module_origins = origins(module)",
            "    if not module_origins or not all(",
            "            inside(origin) for origin in module_origins):",
            "        raise RuntimeError(f'{name} not from staging: {module_origins}')",
            "for requirement in host_requirements:",
            "    name = requirement['name'].replace('-', '_')",
            "    module = importlib.import_module(name)",
            "    origin = getattr(module, '__file__', None)",
            "    if not origin or inside(origin):",
            "        raise RuntimeError(f'bad host origin {name}: {origin}')",
            "    try: actual = importlib.metadata.version(requirement['name'])",
            "    except importlib.metadata.PackageNotFoundError:",
            "        actual = getattr(module, '__version__', None)",
            "    if actual != requirement['version']:",
            "        expected = requirement['version']",
            "        raise RuntimeError(f'bad host version {name}: {actual!r}')",
        )
    )


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _staged_host_requirement(
    staging: Path, host_requirements: list[object]
) -> str | None:
    for requirement in host_requirements:
        if not isinstance(requirement, dict):
            continue
        name = requirement.get("name")
        if not isinstance(name, str) or not name:
            continue
        module_name = _normalized_distribution_name(name)
        if (staging / module_name).exists() or (
            staging / f"{module_name}.py"
        ).exists():
            return name
        dist_info_prefix = f"{module_name}-"
        for path in staging.iterdir():
            filename = path.name.lower()
            if filename.endswith(".dist-info") and filename.startswith(
                dist_info_prefix
            ):
                return name
    return None


def install_pack(
    *, pack_dir: Path, root: Path, python_executable: str | Path | None = None
) -> Path:
    """Install one unpacked acoustic pack and return its final version root."""

    pack_dir = pack_dir.resolve()
    manifest_path = pack_dir / "pack_manifest.json"
    lock_path = pack_dir / "requirements.lock"
    if not lock_path.is_file():
        raise PackInstallError(f"requirements lock is missing: {lock_path}")
    manifest = _load_manifest(manifest_path)
    _validate_runtime(manifest)
    _validate_wheels(pack_dir, manifest)

    pack_id = str(manifest["pack_id"])
    pack_version = str(manifest["pack_version"])
    if not _safe_path_component(pack_id) or not _safe_path_component(pack_version):
        raise PackInstallError("pack_id and pack_version must be safe path components")
    pack_parent = root.expanduser().resolve() / pack_id
    final_dir = pack_parent / pack_version
    if os.path.lexists(final_dir):
        raise PackInstallError(
            f"immutable pack version already exists: {final_dir}; remove it "
            "explicitly or choose another version"
        )
    pack_parent.mkdir(parents=True, exist_ok=True)
    staging = pack_parent / f".staging-{os.getpid()}-{uuid.uuid4().hex}"
    staging.mkdir()
    executable = str(python_executable or sys.executable)
    try:
        subprocess.run(
            [
                executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(staging),
                "--no-deps",
                "--no-index",
                "--require-hashes",
                "--find-links",
                str(pack_dir / "wheels"),
                "-r",
                str(lock_path),
            ],
            check=True,
        )
        host_requirements = manifest["host_requirements"]
        assert isinstance(host_requirements, list)
        staged_host = _staged_host_requirement(staging, host_requirements)
        if staged_host is not None:
            raise PackInstallError(
                f"host_requirements violation: {staged_host} was installed into "
                "staging"
            )
        _validate_installed_files(staging, manifest)
        subprocess.run(
            [executable, "-c", _self_check_script(staging, manifest)],
            check=True,
        )
        shutil.copyfile(manifest_path, staging / "pack_manifest.json")
        if os.path.lexists(final_dir):
            raise PackInstallError(
                f"immutable pack version appeared during install: {final_dir}"
            )
        os.replace(staging, final_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final_dir


def _safe_path_component(value: str) -> bool:
    return (
        value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="Override the private isaac_audio_sensors/packs root.",
    )
    args = parser.parse_args(argv)
    pack_dir = Path(__file__).resolve().parent
    try:
        final_dir = install_pack(pack_dir=pack_dir, root=args.root)
    except Exception as exc:  # noqa: BLE001 - CLI reports every safe failure.
        print(f"[pack-install] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[pack-install] OK {final_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
