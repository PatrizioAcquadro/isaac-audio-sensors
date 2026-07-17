"""Build a deterministic self-contained Kit extension archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:  # pragma: no cover - Python 3.11+ path in CI
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    from scripts.release_provenance import (
        ReleaseProvenanceError,
        head_revision,
        require_clean_source,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_provenance import (  # type: ignore[no-redef]
        ReleaseProvenanceError,
        head_revision,
        require_clean_source,
    )


EXTENSION_NAME = "isaac_audio_sensors.omni"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class KitBuild:
    """Paths and provenance produced by one Kit build."""

    staging_dir: Path
    archive_path: Path
    checksums_path: Path
    version: str
    source_revision: str
    tree_sha256: str


def tree_sha256(entries: Iterable[tuple[str, bytes]]) -> str:
    """Hash sorted relative paths and the SHA-256 of each file's bytes."""

    digest = hashlib.sha256()
    for relative_path, content in sorted(entries):
        content_sha256 = hashlib.sha256(content).hexdigest()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def source_tree_entries(root: Path) -> Iterator[tuple[str, bytes]]:
    """Yield maintained-package files using the Kit vendoring exclusions."""

    for path in sorted(root.rglob("*")):
        if not path.is_file() or _excluded_source_path(path, root):
            continue
        yield path.relative_to(root).as_posix(), path.read_bytes()


def hash_source_tree(root: Path) -> str:
    """Compute the canonical maintained-package tree hash."""

    return tree_sha256(source_tree_entries(root))


def read_project_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "pyproject.toml"
    with pyproject_path.open("rb") as stream:
        data = tomllib.load(stream)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing project.version in {pyproject_path}")
    return version


def read_extension_version(extension_dir: Path) -> str:
    manifest_path = extension_dir / "config" / "extension.toml"
    with manifest_path.open("rb") as stream:
        data = tomllib.load(stream)
    version = data.get("package", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing package.version in {manifest_path}")
    return version


def resolve_source_revision(
    repo_root: Path,
    override: str | None = None,
    *,
    verify_source: bool = True,
) -> str:
    if override is not None and not override.strip():
        raise ValueError("--source-revision must not be empty")
    if verify_source:
        return require_clean_source(repo_root, expected_revision=override)
    if override is not None:
        return override
    try:
        return head_revision(repo_root)
    except ReleaseProvenanceError:
        return "unknown"


def build_kit_extension(
    *,
    repo_root: Path,
    output_dir: Path,
    source_revision: str | None = None,
    verify_source: bool = True,
) -> KitBuild:
    """Assemble the staging tree, deterministic zip, and checksum file."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    extension_dir = repo_root / "exts" / EXTENSION_NAME
    source_dir = repo_root / "src" / "isaac_audio_sensors"
    if not extension_dir.is_dir():
        raise FileNotFoundError(
            f"extension source directory not found: {extension_dir}"
        )
    if not source_dir.is_dir():
        raise FileNotFoundError(f"maintained package source not found: {source_dir}")

    version = read_project_version(repo_root)
    extension_version = read_extension_version(extension_dir)
    if extension_version != version:
        raise ValueError(
            "extension version does not match pyproject.toml: "
            f"{extension_version!r} != {version!r}"
        )
    revision = resolve_source_revision(
        repo_root,
        source_revision,
        verify_source=verify_source,
    )
    staging_dir = output_dir / f"{EXTENSION_NAME}-{version}"
    archive_path = output_dir / f"{EXTENSION_NAME}-{version}.zip"
    checksums_path = output_dir / "SHA256SUMS"

    output_dir.mkdir(parents=True, exist_ok=True)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir()

    for source_name in ("config", "data", "docs", "isaac_audio_sensors_omni"):
        _copy_tree(
            extension_dir / source_name,
            staging_dir / source_name,
            exclude_developer_sentinel=True,
        )

    vendored_dir = staging_dir / "_vendor" / "isaac_audio_sensors"
    _copy_tree(source_dir, vendored_dir, exclude_developer_sentinel=False)
    vendored_hash = hash_source_tree(vendored_dir)
    metadata = {
        "mode": "packaged",
        "source_revision": revision,
        "tree_sha256": vendored_hash,
        "version": version,
    }
    metadata_path = staging_dir / "_vendor" / "VENDORED.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _write_deterministic_zip(staging_dir, archive_path)
    _write_checksums(output_dir, checksums_path)
    return KitBuild(
        staging_dir=staging_dir,
        archive_path=archive_path,
        checksums_path=checksums_path,
        version=version,
        source_revision=revision,
        tree_sha256=vendored_hash,
    )


def _excluded_source_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (
        "__pycache__" in relative.parts
        or path.suffix == ".pyc"
        or any(part.endswith(".egg-info") for part in relative.parts)
    )


def _copy_tree(
    source: Path, destination: Path, *, exclude_developer_sentinel: bool
) -> None:
    if not source.is_dir():
        raise FileNotFoundError(
            f"required extension source directory not found: {source}"
        )
    for path in sorted(source.rglob("*")):
        if not path.is_file() or _excluded_source_path(path, source):
            continue
        if exclude_developer_sentinel and path.name == "DEVELOPMENT_MODE.json":
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _write_deterministic_zip(source_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(item for item in source_dir.rglob("*") if item.is_file()):
            relative = PurePosixPath(path.relative_to(source_dir).as_posix())
            info = zipfile.ZipInfo(str(relative), date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def _write_checksums(output_dir: Path, checksums_path: Path) -> None:
    lines = []
    for archive_path in sorted(output_dir.glob("*.zip")):
        checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        lines.append(f"{checksum}  {archive_path.name}\n")
    checksums_path.write_text("".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/kit"),
        help="Directory for the staging tree, zip, and SHA256SUMS.",
    )
    parser.add_argument(
        "--source-revision",
        help="Override the source revision recorded in VENDORED.json.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = build_kit_extension(
            repo_root=repo_root,
            output_dir=args.output_dir,
            source_revision=args.source_revision,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports all build failures.
        print(f"[kit-build] FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"[kit-build] OK {result.archive_path} "
        f"(version={result.version}, revision={result.source_revision}, "
        f"tree_sha256={result.tree_sha256})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
