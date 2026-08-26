"""Build the standalone NVIDIA Community Registry archive."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    from .check_version_sync import read_project_version
except ImportError:
    from check_version_sync import read_project_version


EXTENSION_NAME = "isaac_audio_sensors.omni"
COMMUNITY_PREFIX = "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64"
BUNDLED_ROOT = PurePosixPath("isaac_audio_sensors/_bundled")
DEPENDENCY_LOCK = Path(__file__).with_name("kit_dependencies.lock")
EXPECTED_DISTRIBUTIONS = {
    "cffi",
    "pycparser",
    "pyroomacoustics",
    "scipy",
    "soundfile",
}
HOST_OWNED_DISTRIBUTIONS = {"numpy", "typing_extensions"}
_DEVELOPMENT_PARTS = {"benchmarks", "test", "testing", "tests"}
_LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+"
    r"--hash=sha256:(?P<sha256>[0-9a-f]{64})$"
)


@dataclass(frozen=True, slots=True)
class LockedDependency:
    name: str
    version: str
    sha256: str

    @property
    def normalized_name(self) -> str:
        return normalize_distribution_name(self.name)


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def read_dependency_lock(path: Path = DEPENDENCY_LOCK) -> tuple[LockedDependency, ...]:
    entries: list[LockedDependency] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: invalid locked requirement")
        entries.append(LockedDependency(**match.groupdict()))
    names = [entry.normalized_name for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError(f"{path}: duplicate locked distributions")
    if set(names) != EXPECTED_DISTRIBUTIONS:
        raise ValueError(
            f"{path}: locked distributions must equal "
            f"{sorted(EXPECTED_DISTRIBUTIONS)}"
        )
    return tuple(entries)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_extension_version(extension_dir: Path) -> str:
    path = extension_dir / "config" / "extension.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream).get("package", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing package.version in {path}")
    return version


def community_archive_name(version: str) -> str:
    return f"{COMMUNITY_PREFIX}-v{version}.zip"


def is_host_owned_path(path: str | PurePosixPath) -> bool:
    first = PurePosixPath(path).parts[0].lower()
    return any(
        first == name
        or first == f"{name}.py"
        or first.startswith(f"{name}-")
        or first.startswith(f"{name}.")
        for name in HOST_OWNED_DISTRIBUTIONS
    )


def validate_wheelhouse(
    wheelhouse: Path,
) -> tuple[tuple[LockedDependency, Path], ...]:
    """Validate and resolve the exact hash-locked Kit wheelhouse."""

    dependencies = read_dependency_lock()
    wheelhouse = wheelhouse.resolve()
    if not wheelhouse.is_dir():
        raise ValueError(f"wheelhouse directory not found: {wheelhouse}")
    available = tuple(path for path in wheelhouse.iterdir() if path.is_file())
    resolved: list[tuple[LockedDependency, Path]] = []
    for dependency in dependencies:
        prefix = f"{dependency.normalized_name}-{dependency.version}-"
        matches = tuple(path for path in available if path.name.startswith(prefix))
        if len(matches) != 1:
            raise ValueError(
                f"wheelhouse must contain one wheel for "
                f"{dependency.name}=={dependency.version}"
            )
        wheel = matches[0]
        actual = sha256_file(wheel)
        if actual != dependency.sha256:
            raise ValueError(
                f"wheel hash mismatch for {wheel.name}: "
                f"{actual} != {dependency.sha256}"
            )
        resolved.append((dependency, wheel))
    selected = {wheel for _, wheel in resolved}
    extras = sorted(path.name for path in available if path not in selected)
    if extras:
        raise ValueError(f"wheelhouse contains undeclared files: {extras}")
    return tuple(resolved)


def _installed_wheel_path(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or "\\" in name or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"unsafe wheel member: {name}")
    if len(path.parts) >= 2 and path.parts[0].endswith(".data"):
        if len(path.parts) < 3 or path.parts[1] not in {"purelib", "platlib"}:
            return None
        path = PurePosixPath(*path.parts[2:])
    if path.name == "RECORD" and path.parent.name.endswith(".dist-info"):
        return None
    if any(part.lower() in _DEVELOPMENT_PARTS for part in path.parts):
        return None
    if path.name == "conftest.py" or path.name.startswith("test_"):
        return None
    return path


def _extract_wheel(
    wheel: Path,
    destination: Path,
    *,
    installed_paths: set[str] | None = None,
) -> set[str]:
    installed = installed_paths if installed_paths is not None else set()
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
            if len(names) != len(set(names)):
                raise ValueError(f"wheel contains duplicate members: {wheel.name}")
            for name in names:
                relative = _installed_wheel_path(name)
                if relative is None:
                    continue
                relative_text = relative.as_posix()
                if is_host_owned_path(relative):
                    raise ValueError(
                        f"wheel {wheel.name} contains host-owned path {relative_text}"
                    )
                if relative_text in installed:
                    raise ValueError(f"wheel install collision: {relative_text}")
                target = destination / relative_text
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                installed.add(relative_text)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid wheel archive: {wheel}") from exc
    return installed


def stage_locked_dependencies(*, wheelhouse: Path, destination: Path) -> None:
    resolved = validate_wheelhouse(wheelhouse)
    if destination.exists():
        raise ValueError(f"bundled dependency root already exists: {destination}")
    destination.mkdir(parents=True)
    installed: set[str] = set()
    for _, wheel in resolved:
        _extract_wheel(wheel, destination, installed_paths=installed)


def build_kit_extension(
    *, repo_root: Path, output_dir: Path, wheelhouse: Path
) -> Path:
    """Build one self-contained Kit archive and return its path."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    extension_dir = repo_root / "exts" / EXTENSION_NAME
    package_dir = repo_root / "src" / "isaac_audio_sensors"

    for required in (extension_dir, package_dir):
        if not required.is_dir():
            raise FileNotFoundError(f"required source directory not found: {required}")
    if (package_dir / "_bundled").exists():
        raise ValueError("source package must not contain a bundled dependency tree")
    for required in (repo_root / "LICENSE", repo_root / "NOTICE", DEPENDENCY_LOCK):
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
    archive_path = output_dir / community_archive_name(version)
    with TemporaryDirectory(prefix="isaac-audio-sensors-kit-") as temporary:
        staging_dir = Path(temporary) / EXTENSION_NAME
        staging_dir.mkdir()
        for name in ("config", "data", "docs", "isaac_audio_sensors_omni"):
            _copy_tree(extension_dir / name, staging_dir / name)
        _copy_tree(package_dir, staging_dir / "isaac_audio_sensors")
        stage_locked_dependencies(
            wheelhouse=wheelhouse,
            destination=staging_dir / BUNDLED_ROOT,
        )
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
    parser.add_argument("--wheelhouse", required=True, type=Path)
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
            wheelhouse=args.wheelhouse,
        )
    except (OSError, ValueError) as exc:
        print(f"[kit-build] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[kit-build] OK {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
