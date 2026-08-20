"""Shared release archive policy."""

from __future__ import annotations

import io
import re
import tarfile
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
_ABSOLUTE_PATH = re.compile(rb"(?:/home|/Users)/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\")
_PROJECT_TEXT = re.compile(
    rb"isaac_audio_sensors\." rb"acquisition|squadbot-" rb"av-phase1|"
    rb"Alex" rb"003|live_" rb"alex|ihmc_" rb"alex_isaaclab|Desktop/" rb"Alex"
)
_TEST_PATH = b"tests/" + b"test_"


class ContentPolicyError(RuntimeError):
    """Raised when an archive violates release policy."""


def archive_entries(path: Path) -> dict[str, bytes]:
    """Read regular files from a zip-compatible or tar archive."""

    payload = path.read_bytes()
    try:
        return _zip_entries(payload)
    except zipfile.BadZipFile:
        try:
            return _tar_entries(payload)
        except tarfile.TarError as exc:
            raise ContentPolicyError(f"unsupported archive: {path}") from exc


def find_violations(path: Path) -> tuple[str, ...]:
    """Return all path and content policy violations."""

    return tuple(_audit_entries(archive_entries(path)))


def require_archive(path: Path) -> None:
    """Raise when an archive violates the shared policy."""

    findings = find_violations(path)
    if findings:
        raise ContentPolicyError("; ".join(findings))


def _zip_entries(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != len(set(names)):
            raise ContentPolicyError("archive contains duplicate members")
        return {name: archive.read(name) for name in names}


def _tar_entries(payload: bytes) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name in entries:
                raise ContentPolicyError("archive contains duplicate members")
            stream = archive.extractfile(member)
            if stream is None:
                raise ContentPolicyError(f"cannot read archive member: {member.name}")
            entries[member.name] = stream.read()
    return entries


def _audit_entries(
    entries: Mapping[str, bytes], *, prefix: str = ""
) -> Iterable[str]:
    for raw_name, payload in entries.items():
        name = PurePosixPath(raw_name)
        display = f"{prefix}{raw_name}"
        if name.is_absolute() or any(part in {"", ".", ".."} for part in name.parts):
            yield f"unsafe path: {display}"
            continue
        lowered = tuple(part.lower() for part in name.parts)
        if any(part in _FORBIDDEN_PARTS for part in lowered):
            yield f"forbidden path: {display}"
        if name.suffix == ".pyc" or _PHASE_PATH.search(name.as_posix()):
            yield f"forbidden path: {display}"
        if any(token in lowered for token in {"alex", "squadbot"}):
            yield f"project-specific path: {display}"

        nested = _nested_entries(name, payload)
        if nested is not None:
            yield from _audit_entries(nested, prefix=f"{display}!/")
            continue
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


def _nested_entries(name: PurePosixPath, payload: bytes) -> dict[str, bytes] | None:
    lowered = name.name.lower()
    try:
        if lowered.endswith((".whl", ".zip")):
            return _zip_entries(payload)
        if lowered.endswith((".tar", ".tar.gz", ".tgz")):
            return _tar_entries(payload)
    except (ContentPolicyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ContentPolicyError(f"invalid nested archive: {name}") from exc
    return None


__all__ = [
    "ContentPolicyError",
    "archive_entries",
    "find_violations",
    "require_archive",
]
