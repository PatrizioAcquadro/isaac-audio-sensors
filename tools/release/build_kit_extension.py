"""Build the standalone NVIDIA Community Registry archive."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


EXTENSION_NAME = "isaac_audio_sensors.omni"
COMMUNITY_PREFIX = "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64"


def read_project_version(repo_root: Path) -> str:
    path = repo_root / "pyproject.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing project.version in {path}")
    return version


def read_extension_version(extension_dir: Path) -> str:
    path = extension_dir / "config" / "extension.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream).get("package", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing package.version in {path}")
    return version


def community_archive_name(version: str) -> str:
    return f"{COMMUNITY_PREFIX}-v{version}.zip"


def build_kit_extension(*, repo_root: Path, output_dir: Path) -> Path:
    """Build one self-contained Kit archive and return its path."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    extension_dir = repo_root / "exts" / EXTENSION_NAME
    package_dir = repo_root / "src" / "isaac_audio_sensors"

    for required in (extension_dir, package_dir):
        if not required.is_dir():
            raise FileNotFoundError(f"required source directory not found: {required}")
    for required in (repo_root / "LICENSE", repo_root / "NOTICE"):
        if not required.is_file():
            raise FileNotFoundError(f"required release file not found: {required}")

    version = read_project_version(repo_root)
    extension_version = read_extension_version(extension_dir)
    if extension_version != version:
        raise ValueError(
            "extension version does not match pyproject.toml: "
            f"{extension_version!r} != {version!r}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_output = output_dir / "kit"
    if legacy_output.exists():
        shutil.rmtree(legacy_output)
    for previous in output_dir.glob(f"{COMMUNITY_PREFIX}-v*.zip"):
        previous.unlink()

    archive_path = output_dir / community_archive_name(version)
    with TemporaryDirectory(prefix="isaac-audio-sensors-kit-") as temporary:
        staging_dir = Path(temporary) / EXTENSION_NAME
        staging_dir.mkdir()
        for name in ("config", "data", "docs", "isaac_audio_sensors_omni"):
            _copy_tree(extension_dir / name, staging_dir / name)
        _copy_tree(package_dir, staging_dir / "isaac_audio_sensors")
        shutil.copyfile(repo_root / "LICENSE", staging_dir / "LICENSE")
        shutil.copyfile(repo_root / "NOTICE", staging_dir / "NOTICE")
        shutil.make_archive(
            str(archive_path.with_suffix("")),
            "zip",
            root_dir=staging_dir,
        )
    return archive_path


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"required source directory not found: {source}")
    shutil.copytree(
        source,
        destination,
        copy_function=shutil.copyfile,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Directory for the Community Registry zip.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        archive_path = build_kit_extension(
            repo_root=repo_root,
            output_dir=args.output_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports build failures
        print(f"[kit-build] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[kit-build] OK {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
