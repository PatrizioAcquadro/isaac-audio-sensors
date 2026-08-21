"""Check every current-release version surface against pyproject.toml."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

try:  # pragma: no cover - Python 3.11+ path in CI
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def _read_project_version(repo_root: Path) -> str:
    path = repo_root / "pyproject.toml"
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{path}: missing [project].version")
    return version


def _regex_value(
    path: Path,
    pattern: str,
    *,
    label: str,
    flags: int = re.MULTILINE,
) -> tuple[str | None, str | None]:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(pattern, text, flags)
    if len(matches) != 1:
        return (
            None,
            f"{label}: expected exactly one current-release surface, "
            f"found {len(matches)}",
        )
    value = matches[0]
    if isinstance(value, tuple):
        value = value[0]
    return value, None


def _toml_version(path: Path, table: str) -> str:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    version = data.get(table, {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing [{table}].version")
    return version


def _toml_string(path: Path, table: str, key: str) -> str:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    value = data.get(table, {}).get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing [{table}].{key}")
    return value


def _top_changelog_version(path: Path) -> str:
    headings = re.findall(
        r"^##\s+(.+?)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not headings:
        raise ValueError("missing release heading")
    match = re.fullmatch(r"([^\s]+)(?:\s+-\s+Unreleased)?", headings[0])
    if match is None:
        raise ValueError(
            "top release heading must contain a version with only an optional "
            "'- Unreleased' suffix"
        )
    return match.group(1)


def check_version_sync(repo_root: Path) -> tuple[str, tuple[str, ...]]:
    """Return the authoritative version and all derived-surface findings."""

    repo_root = repo_root.resolve()
    version = _read_project_version(repo_root)
    findings: list[str] = []

    def check(
        label: str,
        reader: Callable[[], str],
        *,
        expected: str | None = None,
        noun: str = "version",
        expected_source: str = "pyproject.toml",
    ) -> None:
        try:
            actual = reader()
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            findings.append(f"{label}: cannot read current version: {exc}")
            return
        if expected is None:
            expected = version
        if actual != expected:
            findings.append(
                f"{label}: {noun} {actual!r} does not match "
                f"{expected_source} {expected!r}"
            )

    check(
        "src/isaac_audio_sensors/__init__.py __version__",
        lambda: _required_regex(
            repo_root / "src/isaac_audio_sensors/__init__.py",
            r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$',
            "src package __version__",
        ),
    )
    check(
        "exts/isaac_audio_sensors.omni/config/extension.toml package.version",
        lambda: _toml_version(
            repo_root / "exts/isaac_audio_sensors.omni/config/extension.toml",
            "package",
        ),
    )
    pack_manifest = repo_root / "packs/acoustics/pack.toml"
    check(
        "packs/acoustics/pack.toml pack.pack_version",
        lambda: _toml_string(pack_manifest, "pack", "pack_version"),
    )
    expected_pack_artifact = (
        "isaac_audio_sensors_acoustic_pack-l2l3-"
        f"{version}-linux_x86_64-cp312.tar.gz"
    )
    check(
        "packs/acoustics/pack.toml pack.artifact_name",
        lambda: _toml_string(pack_manifest, "pack", "artifact_name"),
        expected=expected_pack_artifact,
        noun="artifact name",
        expected_source="expected artifact name",
    )
    check(
        "Makefile EXPECTED_VERSION default",
        lambda: _required_regex(
            repo_root / "Makefile",
            r"^EXPECTED_VERSION\s*\?=\s*([^\s#]+)\s*$",
            "Makefile EXPECTED_VERSION",
        ),
    )
    check(
        "README.md current-release statement",
        lambda: _required_regex(
            repo_root / "README.md",
            r"^Current package release: `([^`]+)`\.",
            "README current release",
        ),
    )
    check(
        "knowledge/wiki/status.md package version",
        lambda: _required_regex(
            repo_root / "knowledge/wiki/status.md",
            r"^Updated: [^.]+\. Package version: `([^`]+)`\.$",
            "wiki status package version",
        ),
    )
    check(
        "CHANGELOG.md top release heading",
        lambda: _top_changelog_version(repo_root / "CHANGELOG.md"),
    )
    check(
        "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md top release heading",
        lambda: _top_changelog_version(
            repo_root / "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md"
        ),
    )
    return version, tuple(findings)


def _required_regex(path: Path, pattern: str, label: str) -> str:
    value, finding = _regex_value(path, pattern, label=label)
    if finding is not None or value is None:
        raise ValueError(finding or "version surface missing")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository layout to check (defaults to this script's checkout).",
    )
    args = parser.parse_args(argv)
    try:
        version, findings = check_version_sync(args.repo_root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"[version-sync] FAILED: authority unavailable: {exc}", file=sys.stderr)
        return 1
    if findings:
        print("[version-sync] FAILED", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"[version-sync] OK {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
