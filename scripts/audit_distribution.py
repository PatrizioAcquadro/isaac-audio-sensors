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
ALLOWED_EXTENSION_ASSET_ENTRIES = frozenset(
    {
        "exts/isaac_audio_sensors.omni/data",
        "exts/isaac_audio_sensors.omni/data/icon.svg",
        "exts/isaac_audio_sensors.omni/data/preview.png",
    }
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
PACKAGE_VERSION = "1.3.0"
EXPECTED_SDIST_NAME = f"isaac_audio_sensors-{PACKAGE_VERSION}.tar.gz"
EXPECTED_WHEEL_NAME = f"isaac_audio_sensors-{PACKAGE_VERSION}-py3-none-any.whl"

V1_SCOPE_REQUIRED_PHRASES = (
    "Stable `AudioSensorFrame` v1 public contract",
    "Stable L0 `geometry_only` backend",
    "Stable L1 `tdoa_synthetic` backend",
    "Supported optional L2 `room_acoustics` backend",
    "Supported Isaac Sim live sensor path",
    "Supported Isaac Lab sensor path",
    "Omniverse extension as the reference UX",
    "Stable JSON/JSONL export",
    "Replicator as an optional extension capability",
    "SquadBot as a v1 release gate",
    "Sim-real calibration",
    "Real hardware benchmarks",
    "Complete L3/L4 acoustic fidelity",
    "Realistic occlusions or material acoustics",
    "Mandatory ROS 2 or downstream adapters",
    "Alex or SquadBot validation before releasing the sensor package",
)
V1_CONTRACT_REQUIRED_PHRASES = (
    "Renaming public fields is a breaking change",
    "Removing public fields is a breaking change",
    (
        "Changing `schema_version` away from `ias.audio_sensor_frame.v1` "
        "is a breaking change"
    ),
    "Changing bearing-sector semantics is a breaking change",
    (
        "`geometry_only`, `tdoa_synthetic`, and `room_acoustics` are stable "
        "backend identifiers"
    ),
    "Additive optional fields and additive diagnostics namespaces are compatible",
    "Corrected bearing-sector behavior is the stable v1 contract",
    "schema version is separate from the Python package version",
)
SCOPE_TOKEN_ALLOWLIST_ENTRIES = frozenset(
    {
        "CHANGELOG.md",
        "README.md",
        "docs/README.md",
        "docs/api_freeze_0_1.md",
        "docs/isaac_lab.md",
        "docs/limitations.md",
        "docs/open_source_release_checklist.md",
        "docs/v1_scope.md",
        "docs/validation.md",
        "docs/versioning.md",
        "scripts/audit_distribution.py",
        "scripts/generate_live_evidence_report.py",
        "tests/test_distribution_audit.py",
        "tests/test_v1_scope_docs.py",
    }
)
SCOPE_GUARDRAIL_CODE_ENTRIES = frozenset(
    {
        "scripts/audit_distribution.py",
        "tests/test_distribution_audit.py",
        "tests/test_v1_scope_docs.py",
    }
)
FORBIDDEN_SCOPE_OVERCLAIM_PHRASES = (
    "SquadBot validation is required",
    "Alex validation is required",
    "SquadBot release gate",
    "Alex release gate",
    "ROS 2 adapter is required",
    "ROS2 adapter is required",
    "downstream adapter is required",
    "real hardware benchmark is required",
    "sim-real calibration is required",
    "complete L3 runtime backend",
    "complete L4 runtime backend",
    "Replicator is required for core",
    "Replicator is a core dependency",
)

REQUIRED_SDIST_ENTRIES = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "MANIFEST.in",
    "pyproject.toml",
    "configs/isaac_audio_sensors_demo.toml",
    "docs/acoustic_fidelity.md",
    "docs/api_freeze_0_1.md",
    "docs/api_reference.md",
    "docs/installation.md",
    "docs/open_source_release_checklist.md",
    "docs/quickstart.md",
    "docs/validation.md",
    "docs/versioning.md",
    "docs/v1_scope.md",
    "docs/schemas/audio_sensor_frame.v1.schema.json",
    "examples/README.md",
    "examples/core/single_source_bearing.py",
    "examples/traces/ambiguity_frame.v1.json",
    "examples/traces/diagnostics_provenance_sequence.v1.ndjson",
    "examples/traces/minimal_frame.v1.json",
    "examples/traces/multi_detection_frame.v1.json",
    "exts/isaac_audio_sensors.omni/config/extension.toml",
    "exts/isaac_audio_sensors.omni/data/icon.svg",
    "exts/isaac_audio_sensors.omni/data/preview.png",
    "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md",
    "exts/isaac_audio_sensors.omni/docs/README.md",
    "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py",
    "scripts/audit_distribution.py",
    "scripts/generate_live_evidence_report.py",
    "scripts/live_omniverse_extension_ux.py",
    "scripts/live_isaac_sim_audio_smoke.py",
    "src/isaac_audio_sensors/__init__.py",
    "src/isaac_audio_sensors/__main__.py",
    "src/isaac_audio_sensors/cli.py",
    "src/isaac_audio_sensors/core/fidelity.py",
    "src/isaac_audio_sensors/core/schema.py",
    "src/isaac_audio_sensors/core/types.py",
    "src/isaac_audio_sensors/core/io/traces.py",
    "src/isaac_audio_sensors/isaac/extension_ui.py",
    "src/isaac_audio_sensors/isaac/microphone_rig_profiles.py",
    "src/isaac_audio_sensors/isaac/replicator.py",
    "src/isaac_audio_sensors/isaac/sound_profiles.py",
    "tests/test_acoustic_fidelity.py",
    "tests/test_isaac_audio_core.py",
    "tests/test_live_evidence_report.py",
    "tests/test_v1_scope_docs.py",
)
REQUIRED_WHEEL_ENTRIES = (
    "isaac_audio_sensors/__init__.py",
    "isaac_audio_sensors/__main__.py",
    "isaac_audio_sensors/cli.py",
    "isaac_audio_sensors/core/schema.py",
    "isaac_audio_sensors/core/types.py",
    "isaac_audio_sensors/core/io/traces.py",
    "isaac_audio_sensors/isaac/extension.py",
    "isaac_audio_sensors/isaac/extension_ui.py",
    "isaac_audio_sensors/isaac/microphone_rig_profiles.py",
    "isaac_audio_sensors/isaac/replicator.py",
    "isaac_audio_sensors/isaac/sound_profiles.py",
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
    findings.extend(_unsafe_archive_member_findings(archive_path, kind=kind))
    findings.extend(_archive_name_findings(archive_path, kind=kind))
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


def _archive_name_findings(path: Path, *, kind: str) -> tuple[str, ...]:
    expected = EXPECTED_SDIST_NAME if kind == "sdist" else EXPECTED_WHEEL_NAME
    if path.name != expected:
        return (f"unexpected {kind} filename: {path.name} != {expected}",)
    return ()


def _archive_entries(path: Path, *, kind: str) -> tuple[str, ...]:
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            return tuple(member.name for member in archive.getmembers())
    with zipfile.ZipFile(path) as archive:
        return tuple(archive.namelist())


def _normalize_entry(name: str, *, kind: str) -> str:
    normalized = name.replace("\\", "/").lstrip("./")
    parts = PurePosixPath(normalized).parts
    if kind == "sdist":
        parts = parts[1:]
    return "/".join(parts)


def _unsafe_archive_member_findings(path: Path, *, kind: str) -> tuple[str, ...]:
    findings: list[str] = []
    seen_entries: set[str] = set()

    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                findings.extend(_unsafe_archive_path_findings(member.name, kind=kind))
                if not member.isfile() and not member.isdir():
                    findings.append(
                        f"{path.name}: unsafe {kind} member type included: "
                        f"{member.name}"
                    )
                _check_duplicate_normalized_entry(
                    path,
                    kind=kind,
                    raw_name=member.name,
                    seen_entries=seen_entries,
                    findings=findings,
                )
        return tuple(findings)

    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            findings.extend(_unsafe_archive_path_findings(info.filename, kind=kind))
            _check_duplicate_normalized_entry(
                path,
                kind=kind,
                raw_name=info.filename,
                seen_entries=seen_entries,
                findings=findings,
            )
    return tuple(findings)


def _unsafe_archive_path_findings(name: str, *, kind: str) -> tuple[str, ...]:
    normalized = name.replace("\\", "/")
    stripped = normalized.rstrip("/")
    first_part = stripped.split("/", 1)[0]
    if (
        not stripped
        or stripped.startswith("/")
        or _has_windows_drive(first_part)
        or any(part in {"", ".", ".."} for part in stripped.split("/"))
    ):
        return (f"unsafe {kind} archive path included: {name!r}",)
    return ()


def _has_windows_drive(part: str) -> bool:
    return len(part) == 2 and part[1] == ":" and part[0].isalpha()


def _check_duplicate_normalized_entry(
    archive_path: Path,
    *,
    kind: str,
    raw_name: str,
    seen_entries: set[str],
    findings: list[str],
) -> None:
    normalized = _normalize_entry(raw_name, kind=kind)
    if not normalized:
        return
    if normalized in seen_entries:
        findings.append(
            f"{archive_path.name}: duplicate normalized archive entry included: "
            f"{normalized}"
        )
        return
    seen_entries.add(normalized)


def _forbidden_path_findings(entries: tuple[str, ...], *, kind: str) -> tuple[str, ...]:
    findings: list[str] = []
    for entry in entries:
        if entry in ALLOWED_EXTENSION_ASSET_ENTRIES:
            continue
        parts = PurePosixPath(entry).parts
        for part in parts:
            if part in FORBIDDEN_DIR_NAMES or (
                part.endswith(".egg-info") and kind != "sdist"
            ):
                findings.append(f"forbidden path included: {entry}")
                break
        else:
            lower_entry = entry.lower()
            if (
                lower_entry.endswith(FORBIDDEN_SUFFIXES)
                and entry not in ALLOWED_EXTENSION_ASSET_ENTRIES
            ):
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
    scope_text: str | None = None
    api_freeze_text: str | None = None
    for entry_name, content in _iter_text_members(path, kind=kind):
        if entry_name == "docs/v1_scope.md":
            scope_text = content
        if entry_name == "docs/api_freeze_0_1.md":
            api_freeze_text = content
        for token in _forbidden_text_tokens():
            if token in content:
                findings.append(
                    f"{entry_name}: forbidden public-package text token {token!r}"
                )
        findings.extend(_stale_version_findings(entry_name, content))
        findings.extend(_project_scope_token_findings(entry_name, content))
        findings.extend(_scope_overclaim_findings(entry_name, content))
    if kind == "sdist":
        findings.extend(_scope_doc_content_findings(scope_text))
        findings.extend(_api_freeze_contract_findings(api_freeze_text))
    return tuple(findings)


def _iter_text_members(path: Path, *, kind: str):
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
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
        "NS" + "MRL",
        "Pur" + "due",
        "prof" + "essor",
        "/home/" + "pacquadr",
    )


def _stale_version_findings(entry_name: str, content: str) -> tuple[str, ...]:
    if entry_name == "CHANGELOG.md":
        return ()
    stale_tokens = ("0." + "1.0", "0." + "1.x")
    return tuple(
        f"{entry_name}: stale active release version token {token!r}"
        for token in stale_tokens
        if token in content
    )


def _project_scope_token_findings(entry_name: str, content: str) -> tuple[str, ...]:
    token = "Squad" + "Bot"
    if token not in content or entry_name in SCOPE_TOKEN_ALLOWLIST_ENTRIES:
        return ()
    return (f"{entry_name}: project token {token!r} outside scope docs",)


def _scope_overclaim_findings(entry_name: str, content: str) -> tuple[str, ...]:
    if entry_name in SCOPE_GUARDRAIL_CODE_ENTRIES:
        return ()
    lowered = content.lower()
    findings: list[str] = []
    for phrase in FORBIDDEN_SCOPE_OVERCLAIM_PHRASES:
        if phrase.lower() in lowered:
            findings.append(f"{entry_name}: forbidden v1 scope overclaim {phrase!r}")
    return tuple(findings)


def _scope_doc_content_findings(scope_text: str | None) -> tuple[str, ...]:
    if scope_text is None:
        return ()
    return tuple(
        f"docs/v1_scope.md: required v1 scope phrase missing: {phrase!r}"
        for phrase in V1_SCOPE_REQUIRED_PHRASES
        if phrase not in scope_text
    )


def _api_freeze_contract_findings(api_freeze_text: str | None) -> tuple[str, ...]:
    if api_freeze_text is None:
        return ()
    return tuple(
        f"docs/api_freeze_0_1.md: required v1 contract phrase missing: {phrase!r}"
        for phrase in V1_CONTRACT_REQUIRED_PHRASES
        if phrase not in api_freeze_text
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
