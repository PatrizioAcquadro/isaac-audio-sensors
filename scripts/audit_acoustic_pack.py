"""Audit a built Linux acoustic-pack tarball."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    from scripts.build_acoustic_pack import (
        BUILD_TOOL_VERSION,
        MANIFEST_SCHEMA,
        inspect_wheel_bytes,
        read_pack_declaration,
        read_project_version,
    )
    from scripts.release_provenance import (
        ReleaseProvenanceError,
        git_file_bytes,
        recorded_revision_findings,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_acoustic_pack import (  # type: ignore[no-redef]
        BUILD_TOOL_VERSION,
        MANIFEST_SCHEMA,
        inspect_wheel_bytes,
        read_pack_declaration,
        read_project_version,
    )
    from release_provenance import (  # type: ignore[no-redef]
        ReleaseProvenanceError,
        git_file_bytes,
        recorded_revision_findings,
    )


SHA256_RE = re.compile(r"[0-9a-f]{64}")
TEXT_MEMBERS = frozenset(
    {"pack_manifest.json", "requirements.lock", "install_pack.py"}
)


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


FORBIDDEN_PARTS = frozenset(
    {
        ".agents",
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "caches",
        "dist",
        "outputs",
        "runs",
        "src",
        "tests",
    }
)


@dataclass(frozen=True, slots=True)
class AcousticPackAudit:
    """Findings from one acoustic-pack archive."""

    path: Path
    entries: tuple[str, ...]
    findings: tuple[str, ...]


class AcousticPackAuditError(RuntimeError):
    """Raised when an acoustic pack fails its archive contract."""


def _expected_entries(declaration: dict[str, object]) -> set[str]:
    return {
        "pack_manifest.json",
        "requirements.lock",
        "install_pack.py",
        *(
            f"wheels/{item['wheel']}"
            for item in declaration["pack_distributions"]  # type: ignore[union-attr]
        ),
    }


def _unsafe_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    return (
        not normalized
        or normalized.startswith("/")
        or "\\" in name
        or any(part in {"", ".", ".."} for part in parts)
        or (parts and len(parts[0]) == 2 and parts[0][1] == ":")
    )


def _manifest_findings(
    manifest: object,
    *,
    declaration: dict[str, object],
    repo_root: Path,
    archive_path: Path,
    skip_version_check: bool,
    skip_revision_check: bool,
) -> list[str]:
    if not isinstance(manifest, dict):
        return ["pack_manifest.json must contain a JSON object"]
    findings: list[str] = []
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
        findings.append(f"manifest required fields missing: {missing}")
        return findings
    pack = declaration["pack"]
    target = declaration["target"]
    assert isinstance(pack, dict)
    assert isinstance(target, dict)
    expected_scalars = {
        "schema": MANIFEST_SCHEMA,
        "pack_id": pack["pack_id"],
        "pack_version": pack["pack_version"],
        "python_version": target["python_version"],
        "abi": target["abi"],
        "os": target["os"],
        "arch": target["arch"],
        "numpy_compatibility": pack["numpy_compatibility"],
    }
    for field, expected in expected_scalars.items():
        if manifest.get(field) != expected:
            findings.append(
                f"manifest {field} mismatch: {manifest.get(field)!r} != {expected!r}"
            )
    if archive_path.name != pack["artifact_name"]:
        findings.append(
            f"unexpected pack archive filename: {archive_path.name} != "
            f"{pack['artifact_name']}"
        )
    if not skip_version_check:
        version = read_project_version(repo_root)
        if manifest.get("sensor_package_version") != version:
            findings.append(
                "manifest sensor_package_version does not match pyproject.toml: "
                f"{manifest.get('sensor_package_version')!r} != {version!r}"
            )
    if manifest.get("host_requirements") != declaration["host_requirements"]:
        findings.append("manifest host_requirements do not match pack.toml")
    if manifest.get("capabilities") != declaration["capabilities"]:
        findings.append("manifest capabilities do not match pack.toml")

    expected_distributions = declaration["pack_distributions"]
    actual_distributions = manifest.get("pack_distributions")
    if not isinstance(actual_distributions, list):
        findings.append("manifest pack_distributions must be a list")
    else:
        expected_rows = {
            item["wheel"]: item
            for item in expected_distributions  # type: ignore[union-attr]
        }
        actual_rows = {
            item.get("wheel"): item
            for item in actual_distributions
            if isinstance(item, dict)
        }
        if set(actual_rows) != set(expected_rows):
            findings.append("manifest pack_distributions do not match locked set")
        for index, item in enumerate(actual_distributions):
            if not isinstance(item, dict) or SHA256_RE.fullmatch(
                str(item.get("sha256", ""))
            ) is None:
                findings.append(
                    f"manifest pack_distributions[{index}] has invalid sha256"
                )
                continue
            expected = expected_rows.get(item.get("wheel"))
            if expected is None or any(
                item.get(field) != expected.get(field)
                for field in ("name", "version", "wheel", "sha256")
            ):
                findings.append(
                    f"manifest pack_distributions[{index}] differs from locked row"
                )
            imports = item.get("top_level_imports")
            if (
                not isinstance(imports, list)
                or imports != sorted(set(imports))
                or not imports
                or not all(
                    isinstance(name, str) and name.isidentifier()
                    for name in imports
                )
            ):
                findings.append(
                    f"manifest pack_distributions[{index}] has invalid import inventory"
                )
            installed_files = item.get("installed_files")
            if not isinstance(installed_files, dict) or not installed_files:
                findings.append(
                    f"manifest pack_distributions[{index}] has invalid installed files"
                )
            else:
                for filename, digest in installed_files.items():
                    if (
                        not isinstance(filename, str)
                        or _unsafe_path(filename)
                        or SHA256_RE.fullmatch(str(digest)) is None
                    ):
                        findings.append(
                            f"manifest pack_distributions[{index}] has invalid "
                            "installed-file hash"
                        )
                        break
            findings.extend(_wheel_tag_findings(item))
    provenance = manifest.get("build_provenance")
    if not isinstance(provenance, dict):
        findings.append("manifest build_provenance must be an object")
    else:
        for field in ("git_revision", "build_tool_version"):
            if not isinstance(provenance.get(field), str) or not provenance[field]:
                findings.append(
                    f"manifest build_provenance.{field} must be a non-empty string"
                )
        if provenance.get("build_tool_version") != BUILD_TOOL_VERSION:
            findings.append("manifest build tool version is unsupported")
        if not skip_revision_check:
            findings.extend(
                recorded_revision_findings(repo_root, provenance.get("git_revision"))
            )
    return findings


def _wheel_tag_findings(distribution: dict[str, object]) -> list[str]:
    filename = str(distribution.get("wheel", ""))
    name = str(distribution.get("name", ""))
    if not filename.endswith(".whl"):
        return [f"wheel filename has no .whl suffix: {filename!r}"]
    try:
        _prefix, python_tag, abi_tag, platform_tag = filename[:-4].rsplit("-", 3)
    except ValueError:
        return [f"wheel filename has invalid tag structure: {filename!r}"]
    findings: list[str] = []
    if name in {"pyroomacoustics", "scipy", "cffi"}:
        if python_tag != "cp312" or abi_tag != "cp312":
            findings.append(
                f"binary wheel {filename} must use cp312-cp312 tags"
            )
    elif name == "soundfile":
        if python_tag != "py2.py3" or abi_tag != "none":
            findings.append(
                f"SoundFile wheel {filename} must use py2.py3-none tags"
            )
    elif name == "pycparser":
        if (python_tag, abi_tag, platform_tag) != ("py3", "none", "any"):
            findings.append(f"pycparser wheel {filename} must be py3-none-any")
        return findings
    if "manylinux" not in platform_tag or not platform_tag.endswith("x86_64"):
        findings.append(
            f"wheel {filename} must target manylinux on x86_64"
        )
    return findings


def audit_acoustic_pack(
    archive_path: Path,
    *,
    repo_root: Path,
    skip_version_check: bool = False,
    skip_revision_check: bool = False,
) -> AcousticPackAudit:
    """Return exact member, hygiene, manifest, and wheel-hash findings."""

    archive_path = archive_path.resolve()
    repo_root = repo_root.resolve()
    findings: list[str] = []
    declaration = read_pack_declaration(repo_root)
    host_requirements = declaration["host_requirements"]
    assert isinstance(host_requirements, list)
    host_names = {
        _normalized_distribution_name(str(item.get("name")))
        for item in host_requirements
        if isinstance(item, dict)
    }
    expected_entries = _expected_entries(declaration)
    entries: tuple[str, ...] = ()
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            entries = tuple(member.name for member in members)
            seen: set[str] = set()
            for member in members:
                if _unsafe_path(member.name):
                    findings.append(f"unsafe archive path: {member.name!r}")
                if member.name in seen:
                    findings.append(f"duplicate archive member: {member.name}")
                seen.add(member.name)
                if not member.isfile():
                    findings.append(
                        f"unsafe non-regular archive member: {member.name}"
                    )
                parts = PurePosixPath(member.name).parts
                if any(part in FORBIDDEN_PARTS for part in parts):
                    findings.append(f"forbidden cache/output path: {member.name}")
                if member.name.endswith((".pyc", ".pyo")):
                    findings.append(f"forbidden generated file: {member.name}")
                basename = PurePosixPath(member.name).name
                wheel_name = _normalized_distribution_name(
                    basename.split("-", 1)[0]
                )
                if basename.endswith(".whl") and wheel_name in host_names:
                    findings.append(
                        f"host requirement wheel forbidden in pack: {member.name}"
                    )
            actual_set = set(entries)
            if actual_set != expected_entries:
                findings.append(
                    "archive member set mismatch: "
                    f"missing={sorted(expected_entries - actual_set)}, "
                    f"extra={sorted(actual_set - expected_entries)}"
                )

            manifest: object = None
            if "pack_manifest.json" in actual_set:
                try:
                    stream = archive.extractfile("pack_manifest.json")
                    assert stream is not None
                    manifest = json.loads(stream.read().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
                    findings.append(f"pack_manifest.json is invalid: {exc}")
            findings.extend(
                _manifest_findings(
                    manifest,
                    declaration=declaration,
                    repo_root=repo_root,
                    archive_path=archive_path,
                    skip_version_check=skip_version_check,
                    skip_revision_check=skip_revision_check,
                )
            )

            private_tokens = (
                "/home/" + "pacquadr",
                "Squad" + "Bot",
                "NS" + "MRL",
                "Pur" + "due",
            )
            for name in sorted(TEXT_MEMBERS & actual_set):
                member = archive.getmember(name)
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                content = stream.read().decode("utf-8", errors="ignore")
                for token in private_tokens:
                    if token in content:
                        findings.append(
                            f"{name}: forbidden private/project text token {token!r}"
                        )

            pack = declaration["pack"]
            assert isinstance(pack, dict)
            canonical_members = {
                "requirements.lock": (
                    f"packs/acoustics/{pack['requirements_lock']}"
                ),
                "install_pack.py": "scripts/install_pack.py",
            }
            recorded_revision = None
            if isinstance(manifest, dict):
                provenance = manifest.get("build_provenance")
                if isinstance(provenance, dict):
                    recorded_revision = provenance.get("git_revision")
            for name, relative_path in canonical_members.items():
                if name not in actual_set:
                    continue
                stream = archive.extractfile(name)
                assert stream is not None
                expected_payload: bytes
                if (
                    not skip_revision_check
                    and isinstance(recorded_revision, str)
                    and not recorded_revision_findings(repo_root, recorded_revision)
                ):
                    try:
                        expected_payload = git_file_bytes(
                            repo_root, recorded_revision, relative_path
                        )
                    except ReleaseProvenanceError as exc:
                        findings.append(
                            f"cannot read {relative_path} at recorded revision: {exc}"
                        )
                        continue
                else:
                    expected_payload = (repo_root / relative_path).read_bytes()
                if stream.read() != expected_payload:
                    findings.append(
                        f"{name} differs from canonical source {relative_path}"
                    )

            if isinstance(manifest, dict):
                manifest_rows = {
                    item.get("wheel"): item.get("sha256")
                    for item in manifest.get("pack_distributions", [])
                    if isinstance(item, dict)
                }
                locked_rows = {
                    item["wheel"]: item["sha256"]
                    for item in declaration["pack_distributions"]  # type: ignore[union-attr]
                }
                for filename, expected_sha256 in locked_rows.items():
                    member_name = f"wheels/{filename}"
                    if member_name not in actual_set:
                        continue
                    stream = archive.extractfile(member_name)
                    assert stream is not None
                    import hashlib

                    wheel_payload = stream.read()
                    actual_sha256 = hashlib.sha256(wheel_payload).hexdigest()
                    if actual_sha256 != expected_sha256:
                        findings.append(
                            f"wheel hash mismatch for {filename}: "
                            f"{actual_sha256} != {expected_sha256}"
                        )
                    if manifest_rows.get(filename) != expected_sha256:
                        findings.append(
                            f"manifest wheel hash mismatch for {filename}: "
                            f"{manifest_rows.get(filename)!r} != {expected_sha256}"
                        )
                    try:
                        inventory = inspect_wheel_bytes(wheel_payload, filename)
                    except ValueError as exc:
                        findings.append(
                            f"invalid wheel inventory for {filename}: {exc}"
                        )
                    else:
                        rows = manifest.get("pack_distributions", [])
                        manifest_row = next(
                            (
                                item
                                for item in rows
                                if isinstance(item, dict)
                                and item.get("wheel") == filename
                            ),
                            None,
                        )
                        if manifest_row is None or any(
                            manifest_row.get(field) != inventory[field]
                            for field in ("top_level_imports", "installed_files")
                        ):
                            findings.append(
                                "manifest import/file inventory mismatch for "
                                f"{filename}"
                            )
    except (FileNotFoundError, tarfile.TarError, OSError) as exc:
        return AcousticPackAudit(
            archive_path, (), (f"cannot read acoustic-pack archive: {exc}",)
        )
    return AcousticPackAudit(archive_path, entries, tuple(findings))


def require_clean_audit(
    archive_path: Path,
    *,
    repo_root: Path,
    skip_version_check: bool = False,
    skip_revision_check: bool = False,
) -> AcousticPackAudit:
    result = audit_acoustic_pack(
        archive_path,
        repo_root=repo_root,
        skip_version_check=skip_version_check,
        skip_revision_check=skip_revision_check,
    )
    if result.findings:
        raise AcousticPackAuditError("\n".join(result.findings))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Allow an archive built for a foreign source revision/version.",
    )
    parser.add_argument(
        "--skip-revision-check",
        action="store_true",
        help="Do not verify build_provenance.git_revision against local Git history.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    result = audit_acoustic_pack(
        args.archive,
        repo_root=repo_root,
        skip_version_check=args.skip_version_check,
        skip_revision_check=args.skip_revision_check,
    )
    if result.findings:
        print("[pack-audit] FAILED", file=sys.stderr)
        for finding in result.findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"[pack-audit] OK {result.path} ({len(result.entries)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
