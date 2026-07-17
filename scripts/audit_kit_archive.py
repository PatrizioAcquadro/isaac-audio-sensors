"""Audit a canonical self-contained Kit extension archive."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:  # pragma: no cover - Python 3.11+ path in CI
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    from scripts import audit_distribution
    from scripts.build_kit_extension import hash_source_tree, tree_sha256
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import audit_distribution  # type: ignore[no-redef]
    from build_kit_extension import (  # type: ignore[no-redef]
        hash_source_tree,
        tree_sha256,
    )


REQUIRED_ENTRIES = (
    "config/extension.toml",
    "isaac_audio_sensors_omni/__init__.py",
    "_vendor/VENDORED.json",
    "_vendor/isaac_audio_sensors/__init__.py",
    "docs/CHANGELOG.md",
    "data/icon.svg",
    "data/preview.png",
)
ALLOWED_MEDIA_ENTRIES = frozenset({"data/icon.svg", "data/preview.png"})
FORBIDDEN_DIR_NAMES = audit_distribution.FORBIDDEN_DIR_NAMES | {
    "cache",
    "caches",
}
VENDOR_PREFIX = "_vendor/isaac_audio_sensors/"


@dataclass(frozen=True, slots=True)
class KitArchiveAudit:
    """Audit findings for one Kit zip."""

    path: Path
    entries: tuple[str, ...]
    findings: tuple[str, ...]


class KitArchiveAuditError(RuntimeError):
    """Raised when a Kit archive does not satisfy the canonical-build contract."""


def parse_version_literal(source: str, *, entry_name: str) -> str:
    """Read a module-level __version__ string without importing the package."""

    try:
        module = ast.parse(source, filename=entry_name)
    except SyntaxError as exc:
        raise ValueError(f"{entry_name}: invalid Python syntax: {exc}") from exc
    values: list[str] = []
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in targets
        ):
            continue
        value_node = node.value
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            values.append(value_node.value)
        else:
            raise ValueError(f"{entry_name}: __version__ must be a string literal")
    if len(values) != 1:
        raise ValueError(
            f"{entry_name}: expected exactly one __version__ string literal, "
            f"found {len(values)}"
        )
    return values[0]


def audit_kit_archive(
    archive_path: Path,
    *,
    repo_root: Path,
    skip_worktree_drift: bool = False,
) -> KitArchiveAudit:
    """Return precise archive hygiene, provenance, drift, and version findings."""

    archive_path = archive_path.resolve()
    repo_root = repo_root.resolve()
    findings: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            entries = tuple(info.filename for info in infos if not info.is_dir())
            findings.extend(_entry_findings(archive_path, infos, entries))
            findings.extend(_text_findings(archive))
            findings.extend(
                _metadata_and_drift_findings(
                    archive,
                    entries,
                    archive_path=archive_path,
                    repo_root=repo_root,
                    skip_worktree_drift=skip_worktree_drift,
                )
            )
    except (FileNotFoundError, zipfile.BadZipFile, OSError) as exc:
        return KitArchiveAudit(archive_path, (), (f"cannot read Kit zip: {exc}",))
    return KitArchiveAudit(archive_path, entries, tuple(findings))


def require_clean_audit(
    archive_path: Path,
    *,
    repo_root: Path,
    skip_worktree_drift: bool = False,
) -> KitArchiveAudit:
    audit = audit_kit_archive(
        archive_path,
        repo_root=repo_root,
        skip_worktree_drift=skip_worktree_drift,
    )
    if audit.findings:
        raise KitArchiveAuditError("\n".join(audit.findings))
    return audit


def _entry_findings(
    archive_path: Path,
    infos: list[zipfile.ZipInfo],
    entries: tuple[str, ...],
) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    for info in infos:
        findings.extend(
            audit_distribution._unsafe_archive_path_findings(
                info.filename, kind="Kit zip"
            )
        )
        normalized = info.filename.replace("\\", "/").rstrip("/")
        if normalized in seen:
            findings.append(f"duplicate archive entry: {normalized}")
        seen.add(normalized)
        parts = PurePosixPath(normalized).parts
        if "DEVELOPMENT_MODE.json" in parts:
            findings.append(
                f"developer-mode sentinel forbidden in Kit archive: {normalized}"
            )
        if normalized not in ALLOWED_MEDIA_ENTRIES and any(
            part in FORBIDDEN_DIR_NAMES or part.endswith(".egg-info") for part in parts
        ):
            findings.append(f"forbidden path included: {normalized}")
        lower_entry = normalized.lower()
        if (
            lower_entry.endswith(audit_distribution.FORBIDDEN_SUFFIXES)
            and normalized not in ALLOWED_MEDIA_ENTRIES
        ):
            findings.append(f"forbidden generated/media file included: {normalized}")
    for required in REQUIRED_ENTRIES:
        if required not in entries:
            findings.append(f"required Kit archive entry missing: {required}")
    if archive_path.suffix != ".zip":
        findings.append(f"Kit archive must have a .zip suffix: {archive_path.name}")
    return findings


def _text_findings(archive: zipfile.ZipFile) -> list[str]:
    findings: list[str] = []
    for info in archive.infolist():
        if not audit_distribution._should_scan_text(info.filename, info.file_size):
            continue
        content = archive.read(info).decode("utf-8", errors="ignore")
        for token in audit_distribution._forbidden_text_tokens():
            if token in content:
                findings.append(
                    f"{info.filename}: forbidden public-package text token {token!r}"
                )
        findings.extend(
            audit_distribution._project_scope_token_findings(info.filename, content)
        )
    return findings


def _metadata_and_drift_findings(
    archive: zipfile.ZipFile,
    entries: tuple[str, ...],
    *,
    archive_path: Path,
    repo_root: Path,
    skip_worktree_drift: bool,
) -> list[str]:
    findings: list[str] = []
    required = set(REQUIRED_ENTRIES)
    if not required.issubset(entries):
        return findings
    try:
        metadata = json.loads(archive.read("_vendor/VENDORED.json"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"_vendor/VENDORED.json: invalid JSON: {exc}"]
    required_fields = ("mode", "version", "source_revision", "tree_sha256")
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(field), str) or not metadata[field]
        for field in required_fields
    ):
        return [
            "_vendor/VENDORED.json: expected non-empty string fields: "
            + ", ".join(required_fields)
        ]
    if metadata["mode"] != "packaged":
        findings.append(
            f"_vendor/VENDORED.json: mode must be 'packaged', got {metadata['mode']!r}"
        )
    if re.fullmatch(r"[0-9a-f]{64}", metadata["tree_sha256"]) is None:
        findings.append(
            "_vendor/VENDORED.json: tree_sha256 must be 64 lowercase hex characters"
        )

    try:
        manifest = tomllib.loads(archive.read("config/extension.toml").decode("utf-8"))
        extension_version = manifest.get("package", {}).get("version")
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        extension_version = None
        findings.append(f"config/extension.toml: invalid TOML: {exc}")
    try:
        package_version = parse_version_literal(
            archive.read("_vendor/isaac_audio_sensors/__init__.py").decode("utf-8"),
            entry_name="_vendor/isaac_audio_sensors/__init__.py",
        )
    except (UnicodeDecodeError, ValueError) as exc:
        package_version = None
        findings.append(str(exc))
    for surface, actual in (
        ("config/extension.toml package.version", extension_version),
        ("vendored package __version__", package_version),
    ):
        if actual != metadata["version"]:
            findings.append(
                f"version mismatch: VENDORED.json={metadata['version']!r}, "
                f"{surface}={actual!r}"
            )
    expected_name = f"isaac_audio_sensors.omni-{metadata['version']}.zip"
    if archive_path.name != expected_name:
        findings.append(
            f"unexpected Kit archive filename: {archive_path.name} != {expected_name}"
        )

    vendored_entries = [
        (entry.removeprefix(VENDOR_PREFIX), archive.read(entry))
        for entry in entries
        if entry.startswith(VENDOR_PREFIX)
    ]
    archive_tree_hash = tree_sha256(vendored_entries)
    if archive_tree_hash != metadata["tree_sha256"]:
        findings.append(
            "vendored tree hash mismatch: archive recomputed "
            f"{archive_tree_hash} != VENDORED.json {metadata['tree_sha256']}"
        )
    if not skip_worktree_drift:
        source_dir = repo_root / "src" / "isaac_audio_sensors"
        try:
            worktree_hash = hash_source_tree(source_dir)
        except OSError as exc:
            findings.append(f"cannot hash maintained source tree {source_dir}: {exc}")
        else:
            if archive_tree_hash != worktree_hash:
                findings.append(
                    "vendored tree drift from maintained source: archive "
                    f"{archive_tree_hash} != {source_dir} {worktree_hash}"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Kit extension zip to audit.")
    parser.add_argument(
        "--skip-worktree-drift",
        action="store_true",
        help="Do not compare the archive tree with the current checkout source.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    audit = audit_kit_archive(
        args.archive,
        repo_root=repo_root,
        skip_worktree_drift=args.skip_worktree_drift,
    )
    if audit.findings:
        print("[kit-audit] FAILED", file=sys.stderr)
        for finding in audit.findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"[kit-audit] OK {audit.path} ({len(audit.entries)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
