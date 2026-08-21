"""Shared release archive policy."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

_FORBIDDEN_PARTS = {
    "__pycache__",
    "acquisition",
    "dataset",
    "datasets",
    "evidence",
    "outputs",
    "scripts",
    "tests",
    "tools",
}
_TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_PHASE_PATH = re.compile(r"(?:^|[/_.-])s[0-4](?:[._-]\d+)?(?:$|[/_.-])", re.I)
_PHASE_TEXT = re.compile(r"\bS[0-4](?:\.\d+)?\b")
_PROJECT_PATH = re.compile(
    r"(?:^|[/_.-])(?:alex|combinedscene|molmo|squadbot|unitree)(?:$|[/_.-])",
    re.I,
)
_ABSOLUTE_PATH = re.compile(rb"(?:/home|/Users)/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\")
_PROJECT_TEXT = re.compile(
    rb"isaac_audio_sensors\.acquisition|squadbot-av-phase1|"
    rb"alex_(?:head|chest)|unitree_(?:head|base)|molmo|combinedscene|"
    rb"/world/(?:alex|unitree)|ihmc_alex_isaaclab|desktop/alex",
    re.I,
)
_TEST_PATH = b"tests/" + b"test_"


class ContentPolicyError(RuntimeError):
    """Raised when an archive violates release policy."""


def archive_entries(path: Path) -> dict[str, bytes]:
    """Read regular files from a wheel or zip archive."""

    try:
        return _zip_entries(path.read_bytes())
    except zipfile.BadZipFile as exc:
        raise ContentPolicyError(f"unsupported archive: {path}") from exc


def require_archive(path: Path) -> None:
    """Raise when an archive violates the shared policy."""

    require_entries(archive_entries(path))


def require_entries(entries: Mapping[str, bytes]) -> None:
    """Raise when named archive entries violate the shared policy."""

    findings = tuple(_audit_entries(entries))
    if findings:
        raise ContentPolicyError("; ".join(findings))


def _zip_entries(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != len(set(names)):
            raise ContentPolicyError("archive contains duplicate members")
        return {name: archive.read(name) for name in names}


def _audit_entries(entries: Mapping[str, bytes], *, prefix: str = "") -> Iterable[str]:
    for raw_name, payload in entries.items():
        name = PurePosixPath(raw_name)
        display = f"{prefix}{raw_name}"
        if name.is_absolute() or any(part in {"", ".", ".."} for part in name.parts):
            yield f"unsafe path: {display}"
            continue
        if name.parts[:2] == ("isaac_audio_sensors", "_bundled"):
            continue
        lowered = tuple(part.lower() for part in name.parts)
        if any(part in _FORBIDDEN_PARTS for part in lowered):
            yield f"forbidden path: {display}"
        if name.suffix == ".pyc" or _PHASE_PATH.search(name.as_posix()):
            yield f"forbidden path: {display}"
        if _PROJECT_PATH.search(name.as_posix()):
            yield f"project-specific path: {display}"

        if name.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if _ABSOLUTE_PATH.search(payload):
            yield f"absolute workstation path: {display}"
        if _PROJECT_TEXT.search(payload):
            yield f"project-specific content: {display}"
        if _TEST_PATH in payload or b"tests\\" + b"test_" in payload:
            yield f"hard-coded test path: {display}"
        if name.name != "CHANGELOG.md":
            text = payload.decode("utf-8", errors="ignore")
            if _PHASE_TEXT.search(text):
                yield f"phase content: {display}"
