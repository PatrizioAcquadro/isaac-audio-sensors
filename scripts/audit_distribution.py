"""Audit built source and wheel archives for release hygiene."""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FORBIDDEN_DIR_NAMES = frozenset(
    {
        ".agents",
        ".codex",
        ".local-goals",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "data",
        "dist",
        "generated",
        "outputs",
        "runs",
        "venv",
    }
)
FORBIDDEN_SUFFIXES = (
    ".env",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp4",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".wav",
)
TEXT_SUFFIXES = (
    ".cfg",
    ".in",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
)
MAX_TEXT_SCAN_BYTES = 1_000_000

REQUIRED_SDIST_ENTRIES = (
    "README.md",
    "CHANGELOG.md",
    "MANIFEST.in",
    "pyproject.toml",
    "docs/api_freeze_0_1.md",
    "docs/api_reference.md",
    "docs/schemas/audio_sensor_frame.v1.schema.json",
    "examples/traces/minimal_frame.v1.json",
    "exts/isaac_audio_sensors.omni/config/extension.toml",
    "scripts/audit_distribution.py",
    "scripts/live_isaac_sim_audio_smoke.py",
    "src/isaac_audio_sensors/__init__.py",
    "tests/test_isaac_audio_core.py",
)
REQUIRED_WHEEL_ENTRIES = (
    "isaac_audio_sensors/__init__.py",
    "isaac_audio_sensors/core/types.py",
    "isaac_audio_sensors/isaac/extension.py",
    "isaac_audio_sensors/lab/audio_array_sensor.py",
)
REQUIRED_WHEEL_SUFFIXES = (
    ".dist-info/METADATA",
    ".dist-info/entry_points.txt",
)


class DistributionAuditError(RuntimeError):
    """Raised when one or more archives fail release hygiene checks."""


@dataclass(frozen=True, slots=True)
class ArchiveAudit:
    """Audit result for one built archive."""

    path: Path
    kind: str
    entries: tuple[str, ...]
    findings: tuple[str, ...]


def audit_dist_dir(dist_dir: str | Path) -> tuple[ArchiveAudit, ...]:
    """Audit all source and wheel archives in a dist directory."""

    dist_path = Path(dist_dir)
    archives = sorted(dist_path.glob("*.tar.gz")) + sorted(dist_path.glob("*.whl"))
    if not archives:
        raise DistributionAuditError(
            f"No .tar.gz or .whl archives found in {dist_path}."
        )

    audits = tuple(audit_archive(path) for path in archives)
    kinds = {audit.kind for audit in audits}
    findings: list[str] = []
    if "sdist" not in kinds:
        findings.append("dist directory is missing a source distribution (.tar.gz).")
    if "wheel" not in kinds:
        findings.append("dist directory is missing a wheel (.whl).")
    for audit in audits:
        findings.extend(f"{audit.path.name}: {finding}" for finding in audit.findings)

    if findings:
        raise DistributionAuditError("\n".join(findings))
    return audits


def audit_archive(path: str | Path) -> ArchiveAudit:
    """Inspect one built archive and return any release-hygiene findings."""

    archive_path = Path(path)
    kind = _archive_kind(archive_path)
    raw_entries = _archive_entries(archive_path, kind=kind)
    entries = tuple(
        entry
        for entry in (_normalize_entry(name, kind=kind) for name in raw_entries)
        if entry
    )

    findings: list[str] = []
    findings.extend(_forbidden_path_findings(entries, kind=kind))
    findings.extend(_required_entry_findings(entries, kind=kind))
    findings.extend(_forbidden_content_findings(archive_path, kind=kind))
    return ArchiveAudit(
        path=archive_path,
        kind=kind,
        entries=entries,
        findings=tuple(findings),
    )


def _archive_kind(path: Path) -> str:
    if path.name.endswith(".tar.gz"):
        return "sdist"
    if path.suffix == ".whl":
        return "wheel"
    raise ValueError(f"Unsupported archive type: {path}")


def _archive_entries(path: Path, *, kind: str) -> tuple[str, ...]:
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            return tuple(member.name for member in archive.getmembers())
    with zipfile.ZipFile(path) as archive:
        return tuple(archive.namelist())


def _normalize_entry(name: str, *, kind: str) -> str:
    normalized = name.replace("\\", "/").lstrip("./")
    parts = PurePosixPath(normalized).parts
    if kind == "sdist" and len(parts) > 1:
        parts = parts[1:]
    return "/".join(parts)


def _forbidden_path_findings(entries: tuple[str, ...], *, kind: str) -> tuple[str, ...]:
    findings: list[str] = []
    for entry in entries:
        parts = PurePosixPath(entry).parts
        for part in parts:
            if part in FORBIDDEN_DIR_NAMES or (
                part.endswith(".egg-info") and kind != "sdist"
            ):
                findings.append(f"forbidden path included: {entry}")
                break
        else:
            lower_entry = entry.lower()
            if lower_entry.endswith(FORBIDDEN_SUFFIXES):
                findings.append(f"forbidden generated/media file included: {entry}")
    return tuple(findings)


def _required_entry_findings(entries: tuple[str, ...], *, kind: str) -> tuple[str, ...]:
    findings: list[str] = []
    if kind == "sdist":
        for required in REQUIRED_SDIST_ENTRIES:
            if required not in entries:
                findings.append(f"required sdist entry missing: {required}")
        return tuple(findings)

    for required in REQUIRED_WHEEL_ENTRIES:
        if required not in entries:
            findings.append(f"required wheel entry missing: {required}")
    for suffix in REQUIRED_WHEEL_SUFFIXES:
        if not any(entry.endswith(suffix) for entry in entries):
            findings.append(f"required wheel metadata missing: *{suffix}")
    return tuple(findings)


def _forbidden_content_findings(path: Path, *, kind: str) -> tuple[str, ...]:
    findings: list[str] = []
    for entry_name, content in _iter_text_members(path, kind=kind):
        for token in _forbidden_text_tokens():
            if token in content:
                findings.append(
                    f"{entry_name}: forbidden public-package text token {token!r}"
                )
    return tuple(findings)


def _iter_text_members(path: Path, *, kind: str):
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                entry = _normalize_entry(member.name, kind=kind)
                if not _should_scan_text(entry, member.size):
                    continue
                file_obj = archive.extractfile(member)
                if file_obj is None:
                    continue
                yield entry, file_obj.read().decode("utf-8", errors="ignore")
        return

    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            entry = _normalize_entry(info.filename, kind=kind)
            if not _should_scan_text(entry, info.file_size):
                continue
            yield entry, archive.read(info).decode("utf-8", errors="ignore")


def _should_scan_text(entry: str, size: int) -> bool:
    return (
        size <= MAX_TEXT_SCAN_BYTES
        and not entry.endswith("/")
        and entry.lower().endswith(TEXT_SUFFIXES)
    )


def _forbidden_text_tokens() -> tuple[str, ...]:
    return (
        "Phase " + "5.5",
        "phase" + "55",
        "phase_5" + "_5",
        "Squad" + "Bot",
        "NS" + "MRL",
        "Pur" + "due",
        "prof" + "essor",
        "/home/" + "pacquadr",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        default="dist",
        help="Directory containing built .tar.gz and .whl artifacts.",
    )
    args = parser.parse_args(argv)

    try:
        audits = audit_dist_dir(args.dist_dir)
    except DistributionAuditError as exc:
        print(f"[dist-audit] FAILED\n{exc}", file=sys.stderr)
        return 1

    for audit in audits:
        print(
            f"[dist-audit] OK {audit.path} "
            f"({audit.kind}, {len(audit.entries)} files)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
