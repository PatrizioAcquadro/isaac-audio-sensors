"""Build the deterministic Linux acoustic-pack archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:  # pragma: no cover - Python 3.11+ path in CI
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


MANIFEST_SCHEMA = "ias.acoustic_pack_manifest.v1"
BUILD_TOOL_VERSION = "1"
FIXED_MTIME = 0
LOCKED_TARGET = {
    "python_version": "3.12",
    "abi": "cp312",
    "os": "linux",
    "arch": "x86_64",
}
LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+"
    r"--hash=sha256:(?P<sha256>[0-9a-f]{64})$"
)


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


@dataclass(frozen=True, slots=True)
class AcousticPackBuild:
    """Outputs from one acoustic-pack build."""

    archive_path: Path
    checksums_path: Path
    manifest: dict[str, object]


def read_project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        value = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(value, str) or not value:
        raise ValueError("pyproject.toml is missing project.version")
    return value


def read_pack_declaration(repo_root: Path) -> dict[str, object]:
    path = repo_root / "packs" / "acoustics" / "pack.toml"
    with path.open("rb") as stream:
        declaration = tomllib.load(stream)
    for key in (
        "pack",
        "target",
        "host_requirements",
        "pack_distributions",
        "capabilities",
    ):
        if key not in declaration:
            raise ValueError(f"{path}: required declaration {key!r} is missing")
    return declaration


def parse_requirements_lock(path: Path) -> tuple[dict[str, str], ...]:
    entries: list[dict[str, str]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: invalid hash-locked requirement")
        entries.append(match.groupdict())
    if not entries:
        raise ValueError(f"{path}: no locked requirements found")
    return tuple(entries)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _validated_inputs(
    repo_root: Path, wheelhouse: Path
) -> tuple[dict[str, object], tuple[dict[str, str], ...]]:
    declaration = read_pack_declaration(repo_root)
    pack = declaration["pack"]
    host_requirements = declaration["host_requirements"]
    distributions = declaration["pack_distributions"]
    if (
        not isinstance(pack, dict)
        or not isinstance(host_requirements, list)
        or not isinstance(distributions, list)
    ):
        raise ValueError(
            "pack.toml has invalid pack, host_requirements, or "
            "pack_distributions tables"
        )
    host_names = {
        _normalized_distribution_name(str(item.get("name")))
        for item in host_requirements
        if isinstance(item, dict)
    }
    version = read_project_version(repo_root)
    if pack.get("pack_version") != version:
        raise ValueError("pack.toml pack_version does not match pyproject.toml")
    expected_artifact = (
        "isaac_audio_sensors_acoustic_pack-l2l3-"
        f"{version}-linux_x86_64-cp312.tar.gz"
    )
    if pack.get("pack_id") != "acoustics-l2l3":
        raise ValueError("pack.toml has an unsupported pack_id")
    if pack.get("artifact_name") != expected_artifact:
        raise ValueError(
            f"pack.toml artifact_name must be {expected_artifact!r}"
        )
    if declaration.get("target") != LOCKED_TARGET:
        raise ValueError(f"pack.toml target must be {LOCKED_TARGET}")

    lock_name = pack.get("requirements_lock")
    if not isinstance(lock_name, str) or PurePosixPath(lock_name).name != lock_name:
        raise ValueError("pack.toml requirements_lock must be a local filename")
    lock_entries = parse_requirements_lock(
        repo_root / "packs" / "acoustics" / lock_name
    )
    expected_lock = {
        (str(item.get("name")), str(item.get("version")), str(item.get("sha256")))
        for item in distributions
        if isinstance(item, dict)
    }
    actual_lock = {
        (item["name"], item["version"], item["sha256"]) for item in lock_entries
    }
    if actual_lock != expected_lock or len(lock_entries) != len(distributions):
        raise ValueError(
            "requirements.lock entries do not exactly match pack_distributions"
        )
    locked_host_names = {
        item["name"]
        for item in lock_entries
        if _normalized_distribution_name(item["name"]) in host_names
    }
    if locked_host_names:
        raise ValueError(
            "host requirements must be absent from requirements.lock: "
            f"{sorted(locked_host_names)}"
        )

    if not wheelhouse.is_dir():
        raise ValueError(f"wheelhouse directory not found: {wheelhouse}")
    actual_names = {path.name for path in wheelhouse.iterdir()}
    expected_names = {
        str(item.get("wheel")) for item in distributions if isinstance(item, dict)
    }
    missing = sorted(expected_names - actual_names)
    extras = sorted(actual_names - expected_names)
    if missing:
        raise ValueError(f"wheelhouse is missing locked wheels: {missing}")
    if extras:
        host_wheels = [
            name
            for name in extras
            if _normalized_distribution_name(name.split("-", 1)[0]) in host_names
        ]
        if host_wheels:
            raise ValueError(
                f"host requirement wheels forbidden in wheelhouse: {host_wheels}"
            )
        raise ValueError(f"wheelhouse contains undeclared extra files: {extras}")
    for item in distributions:
        if not isinstance(item, dict):
            raise ValueError("pack_distributions entries must be tables")
        wheel_path = wheelhouse / str(item["wheel"])
        actual_sha256 = sha256_file(wheel_path)
        if actual_sha256 != item.get("sha256"):
            raise ValueError(
                f"wheel hash mismatch for {wheel_path.name}: "
                f"{actual_sha256} != {item.get('sha256')}"
            )
    return declaration, lock_entries


def _manifest(
    repo_root: Path, declaration: dict[str, object]
) -> dict[str, object]:
    pack = declaration["pack"]
    target = declaration["target"]
    assert isinstance(pack, dict)
    assert isinstance(target, dict)
    distributions = []
    for raw in declaration["pack_distributions"]:  # type: ignore[union-attr]
        distributions.append(
            {
                "name": raw["name"],
                "version": raw["version"],
                "wheel": raw["wheel"],
                "sha256": raw["sha256"],
            }
        )
    capabilities = []
    for raw in declaration["capabilities"]:  # type: ignore[union-attr]
        capability = {
            "id": raw["id"],
            "kind": raw["kind"],
            "fidelity_level": raw["fidelity_level"],
            "modules": list(raw["modules"]),
        }
        if "format" in raw:
            capability["format"] = raw["format"]
        capabilities.append(capability)
    return {
        "schema": MANIFEST_SCHEMA,
        "pack_id": pack["pack_id"],
        "pack_version": pack["pack_version"],
        "sensor_package_version": read_project_version(repo_root),
        "python_version": target["python_version"],
        "abi": target["abi"],
        "os": target["os"],
        "arch": target["arch"],
        "host_requirements": declaration["host_requirements"],
        "numpy_compatibility": pack["numpy_compatibility"],
        "pack_distributions": distributions,
        "capabilities": capabilities,
        "build_provenance": {
            "git_revision": resolve_git_revision(repo_root),
            "build_tool_version": BUILD_TOOL_VERSION,
        },
    }


def _write_deterministic_tar_gz(
    archive_path: Path, entries: dict[str, bytes]
) -> None:
    with (
        archive_path.open("wb") as raw_stream,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_stream, mtime=FIXED_MTIME
        ) as gzip_stream,
        tarfile.open(
            fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT
        ) as archive,
    ):
        for name in sorted(entries):
            info = tarfile.TarInfo(name)
            info.size = len(entries[name])
            info.mtime = FIXED_MTIME
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(entries[name]))


def _write_checksums(output_dir: Path, path: Path) -> None:
    lines = [
        f"{sha256_file(archive)}  {archive.name}\n"
        for archive in sorted(output_dir.glob("*.tar.gz"))
    ]
    path.write_text("".join(lines), encoding="utf-8")


def build_acoustic_pack(
    *, repo_root: Path, wheelhouse: Path, output_dir: Path
) -> AcousticPackBuild:
    repo_root = repo_root.resolve()
    wheelhouse = wheelhouse.resolve()
    output_dir = output_dir.resolve()
    declaration, _lock_entries = _validated_inputs(repo_root, wheelhouse)
    pack = declaration["pack"]
    assert isinstance(pack, dict)
    manifest = _manifest(repo_root, declaration)
    lock_path = repo_root / "packs" / "acoustics" / str(pack["requirements_lock"])
    installer_path = repo_root / "scripts" / "install_pack.py"
    if not installer_path.is_file():
        raise FileNotFoundError(f"canonical installer not found: {installer_path}")
    entries = {
        "pack_manifest.json": (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "requirements.lock": lock_path.read_bytes(),
        "install_pack.py": installer_path.read_bytes(),
    }
    for item in declaration["pack_distributions"]:  # type: ignore[union-attr]
        filename = str(item["wheel"])
        entries[f"wheels/{filename}"] = (wheelhouse / filename).read_bytes()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / str(pack["artifact_name"])
    _write_deterministic_tar_gz(archive_path, entries)
    checksums_path = output_dir / "SHA256SUMS"
    _write_checksums(output_dir, checksums_path)
    return AcousticPackBuild(archive_path, checksums_path, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("dist/packs"))
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        result = build_acoustic_pack(
            repo_root=repo_root,
            wheelhouse=args.wheelhouse,
            output_dir=args.output_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports precise build failure.
        print(f"[pack-build] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[pack-build] OK {result.archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
