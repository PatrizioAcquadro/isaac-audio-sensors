"""Audit and install the Python wheel."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path, PurePosixPath

try:
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
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
WHEEL_NAME = re.compile(
    r"^isaac_audio_sensors-(?P<version>[^-]+)-py3-none-any\.whl$"
)


def audit_python_wheel(dist_dir: Path) -> Path:
    """Validate and install the single Python wheel in ``dist_dir``."""

    root_files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in root_files if path.suffix == ".whl"]
    if len(wheels) != 1 or root_files != wheels:
        raise ContentPolicyError("dist root must contain exactly one Python wheel")

    wheel = wheels[0]
    match = WHEEL_NAME.fullmatch(wheel.name)
    if match is None:
        raise ContentPolicyError(
            "wheel filename must use isaac_audio_sensors-<version>-py3-none-any.whl"
        )
    version = match.group("version")
    require_archive(wheel)
    _require_minimal_inventory(wheel, version)
    _require_installed_contract(wheel, version)
    return wheel


def _require_minimal_inventory(wheel: Path, version: str) -> None:
    entries = archive_entries(wheel)
    dist_info = f"{PACKAGE}-{version}.dist-info"
    roots = {PurePosixPath(name).parts[0] for name in entries}
    if roots != {PACKAGE, dist_info}:
        raise ContentPolicyError(
            f"unexpected wheel roots: {', '.join(sorted(roots))}"
        )

    schema_paths = {f"{PACKAGE}/schemas/{name}" for name in SCHEMAS}
    package_data = {
        name
        for name in entries
        if name.startswith(f"{PACKAGE}/") and not name.endswith(".py")
    }
    if package_data != schema_paths:
        missing = sorted(schema_paths - package_data)
        unexpected = sorted(package_data - schema_paths)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise ContentPolicyError(f"invalid package data ({'; '.join(details)})")

    expected_dist_info = {
        "METADATA",
        "RECORD",
        "WHEEL",
        "entry_points.txt",
        "licenses/LICENSE",
        "licenses/NOTICE",
        "top_level.txt",
    }
    actual_dist_info = {
        PurePosixPath(name).relative_to(dist_info).as_posix()
        for name in entries
        if name.startswith(f"{dist_info}/")
    }
    if actual_dist_info != expected_dist_info:
        missing = sorted(expected_dist_info - actual_dist_info)
        unexpected = sorted(actual_dist_info - expected_dist_info)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise ContentPolicyError(f"invalid wheel metadata ({'; '.join(details)})")

    wheel_metadata = entries[f"{dist_info}/WHEEL"].decode("utf-8")
    if "Tag: py3-none-any" not in wheel_metadata.splitlines():
        raise ContentPolicyError("wheel metadata must declare Tag: py3-none-any")


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
            PYTHONNOUSERSITE="1",
        )

        _run(
            [python, "-m", "pip", "install", "--no-deps", str(wheel.resolve())],
            cwd=root_path,
            env=environment,
        )
        _run(
            [python, "-c", _INSTALLED_PROBE, version],
            cwd=root_path,
            env=environment,
        )
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
    if not re.search(r"extra\\s*==\\s*[\\\"']room[\\\"']", requirement):
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
    args = parser.parse_args(argv)
    try:
        wheel = audit_python_wheel(args.dist_dir)
    except (ContentPolicyError, OSError) as exc:
        print(f"[python-wheel-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[python-wheel-audit] OK {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
