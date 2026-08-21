"""Audit the complete local release outbox."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path, PurePosixPath

try:
    from .audit_kit_archive import audit_kit_archive
    from .build_kit_extension import (
        BUNDLED_ROOT,
        community_archive_name,
        read_project_version,
        stage_locked_dependencies,
    )
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
    from audit_kit_archive import audit_kit_archive
    from build_kit_extension import (
        BUNDLED_ROOT,
        community_archive_name,
        read_project_version,
        stage_locked_dependencies,
    )
    from content_policy import ContentPolicyError, archive_entries, require_archive

PACKAGE = "isaac_audio_sensors"
PROJECT = "isaac-audio-sensors"
SCHEMAS = frozenset(
    {
        "audio_calibration_profile.v1.schema.json",
        "audio_dataset_manifest.v1.schema.json",
        "audio_sensor_frame.v1.schema.json",
    }
)
ROOM_REQUIREMENTS = frozenset({"pyroomacoustics", "scipy", "soundfile"})


def audit_release_artifacts(
    *, dist_dir: Path, repo_root: Path, wheelhouse: Path
) -> tuple[Path, Path]:
    """Validate the exact wheel and Kit archive built from the current source."""

    version = read_project_version(repo_root)
    wheel_name = f"{PACKAGE}-{version}-py3-none-any.whl"
    kit_name = community_archive_name(version)
    expected_names = {wheel_name, kit_name}
    paths = {path.name: path for path in dist_dir.iterdir()}
    if set(paths) != expected_names or not all(
        path.is_file() for path in paths.values()
    ):
        raise ContentPolicyError(
            "dist root must contain exactly the synchronized Python wheel and Kit ZIP"
        )

    wheel = paths[wheel_name]
    kit_archive = paths[kit_name]
    audit_python_wheel(
        wheel,
        version=version,
        expected_package_files=_expected_wheel_package_files(repo_root),
    )
    first_party, bundled = _expected_kit_files(
        repo_root=repo_root,
        wheelhouse=wheelhouse,
    )
    audit_kit_archive(
        kit_archive,
        version=version,
        expected_first_party=first_party,
        expected_bundled=bundled,
    )
    return wheel, kit_archive


def audit_python_wheel(
    wheel: Path, *, version: str, expected_package_files: set[str]
) -> None:
    """Validate and install one universal Python wheel."""

    expected_name = f"{PACKAGE}-{version}-py3-none-any.whl"
    if wheel.name != expected_name:
        raise ContentPolicyError(f"wheel filename must be {expected_name}")
    require_archive(wheel)
    _require_wheel_inventory(wheel, version, expected_package_files)
    _require_installed_contract(wheel, version)


def _expected_wheel_package_files(repo_root: Path) -> set[str]:
    package_root = repo_root / "src" / PACKAGE
    source_files = _copyable_files(package_root)
    schema_files = {
        PurePosixPath(name).name
        for name in source_files
        if PurePosixPath(name).parent == PurePosixPath("schemas")
        and PurePosixPath(name).suffix == ".json"
    }
    if schema_files != SCHEMAS:
        raise ContentPolicyError("source schema inventory does not match R6")
    allowed = {
        name
        for name in source_files
        if PurePosixPath(name).suffix == ".py"
        or (
            PurePosixPath(name).parent == PurePosixPath("schemas")
            and PurePosixPath(name).name in SCHEMAS
        )
    }
    unexpected = sorted(source_files - allowed)
    if unexpected:
        raise ContentPolicyError(
            f"unsupported source package files: {', '.join(unexpected)}"
        )
    return {f"{PACKAGE}/{name}" for name in allowed}


def _expected_kit_files(
    *, repo_root: Path, wheelhouse: Path
) -> tuple[set[str], set[str]]:
    package_root = repo_root / "src" / PACKAGE
    extension_root = repo_root / "exts" / "isaac_audio_sensors.omni"
    if (package_root / "_bundled").exists():
        raise ContentPolicyError("source package must not contain _bundled")

    first_party = {
        f"{PACKAGE}/{name}" for name in _copyable_files(package_root)
    }
    for name in ("config", "data", "docs", "isaac_audio_sensors_omni"):
        first_party.update(
            f"{name}/{relative}"
            for relative in _copyable_files(extension_root / name)
        )
    first_party.update({"LICENSE", "NOTICE"})

    with tempfile.TemporaryDirectory(prefix="isaac-audio-sensors-kit-audit-") as root:
        destination = Path(root) / "bundle"
        stage_locked_dependencies(
            wheelhouse=wheelhouse.resolve(),
            destination=destination,
        )
        bundled = {
            f"{BUNDLED_ROOT.as_posix()}/{name}"
            for name in _regular_files(destination)
        }
    return first_party, bundled


def _copyable_files(root: Path) -> set[str]:
    return {
        name
        for name in _regular_files(root)
        if not any(
            part == "__pycache__" or part.endswith(".egg-info")
            for part in PurePosixPath(name).parts
        )
        and PurePosixPath(name).suffix not in {".pyc", ".pyo"}
    }


def _regular_files(root: Path) -> set[str]:
    if not root.is_dir():
        raise FileNotFoundError(f"required source directory not found: {root}")
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _require_wheel_inventory(
    wheel: Path, version: str, expected_package_files: set[str]
) -> None:
    entries = archive_entries(wheel)
    dist_info = f"{PACKAGE}-{version}.dist-info"
    expected_metadata = {
        "METADATA",
        "RECORD",
        "WHEEL",
        "entry_points.txt",
        "licenses/LICENSE",
        "licenses/NOTICE",
        "top_level.txt",
    }
    expected = expected_package_files | {
        f"{dist_info}/{name}" for name in expected_metadata
    }
    _require_exact_inventory(set(entries), expected, label="wheel")

    wheel_metadata = entries[f"{dist_info}/WHEEL"].decode("utf-8")
    if "Tag: py3-none-any" not in wheel_metadata.splitlines():
        raise ContentPolicyError("wheel metadata must declare Tag: py3-none-any")


def _require_exact_inventory(
    actual: set[str], expected: set[str], *, label: str
) -> None:
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if unexpected:
        details.append(f"unexpected: {', '.join(unexpected)}")
    raise ContentPolicyError(f"invalid {label} inventory ({'; '.join(details)})")


def _require_installed_contract(wheel: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="isaac-audio-sensors-wheel-") as root:
        root_path = Path(root)
        environment_path = root_path / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_path)
        scripts = environment_path / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / (f"{PROJECT}.exe" if os.name == "nt" else PROJECT)
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment.update(
            PIP_DISABLE_PIP_VERSION_CHECK="1",
            PIP_NO_CACHE_DIR="1",
            PIP_NO_INDEX="1",
            PYTHONNOUSERSITE="1",
        )

        _run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel.resolve()),
            ],
            cwd=root_path,
            env=environment,
        )
        _run([python, "-c", _INSTALLED_PROBE, version], cwd=root_path, env=environment)
        completed = _run([cli, "--version"], cwd=root_path, env=environment)
        if completed.stdout.strip() != version:
            raise ContentPolicyError("installed CLI version does not match the wheel")


def _run(
    command: list[Path | str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(item) for item in command],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "command failed").strip()
        raise ContentPolicyError(detail) from exc


_INSTALLED_PROBE = f"""
import importlib.metadata as metadata
import importlib.resources as resources
import json
import re
import sys

import {PACKAGE} as package

version = sys.argv[1]
distribution = metadata.distribution({PROJECT!r})
if package.__version__ != version or distribution.version != version:
    raise SystemExit("installed package version mismatch")
if distribution.metadata["Name"] != {PROJECT!r}:
    raise SystemExit("installed distribution name mismatch")
if distribution.metadata["Requires-Python"] != ">=3.10":
    raise SystemExit("installed Requires-Python mismatch")
if distribution.metadata["License-Expression"] != "Apache-2.0":
    raise SystemExit("installed license expression mismatch")

entry_points = {{
    (entry.name, entry.value)
    for entry in distribution.entry_points
    if entry.group == "console_scripts"
}}
if ({PROJECT!r}, "isaac_audio_sensors.cli:main") not in entry_points:
    raise SystemExit("installed console entry point mismatch")

room = set()
for requirement in distribution.requires or ():
    marker = requirement.replace("'", '"')
    if 'extra == "room"' not in marker:
        continue
    match = re.match(r"[A-Za-z0-9_.-]+", requirement)
    if match is not None:
        room.add(match.group(0).lower().replace("_", "-"))
if room != {set(ROOM_REQUIREMENTS)!r}:
    raise SystemExit("installed room extra mismatch")

schema_root = resources.files("isaac_audio_sensors.schemas")
schemas = {{item.name for item in schema_root.iterdir() if item.name.endswith(".json")}}
if schemas != {set(SCHEMAS)!r}:
    raise SystemExit("installed schema inventory mismatch")
for name in schemas:
    json.loads(schema_root.joinpath(name).read_text(encoding="utf-8"))
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--wheelhouse", required=True, type=Path)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        wheel, kit_archive = audit_release_artifacts(
            dist_dir=args.dist_dir,
            repo_root=repo_root,
            wheelhouse=args.wheelhouse,
        )
    except (ContentPolicyError, OSError, ValueError) as exc:
        print(f"[release-artifact-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[release-artifact-audit] OK {wheel.name} {kit_archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
