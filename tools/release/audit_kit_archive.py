"""Audit the standalone NVIDIA Community Registry archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    from .build_kit_extension import community_archive_name
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
    from build_kit_extension import community_archive_name
    from content_policy import ContentPolicyError, archive_entries, require_archive


EXTENSION_NAME = "isaac_audio_sensors.omni"
EXPECTED_TARGET = {
    "config": ["release"],
    "kit": ["110.1"],
    "platform": ["linux-x86_64"],
    "python": ["cp312"],
}
EXPECTED_RESOURCES = {
    "changelog": "docs/CHANGELOG.md",
    "icon": "data/icon.svg",
    "preview_image": "data/preview.png",
    "readme": "docs/README.md",
}
REQUIRED_MEMBERS = {
    "LICENSE",
    "NOTICE",
    "config/extension.toml",
    "data/icon.svg",
    "data/preview.png",
    "docs/CHANGELOG.md",
    "docs/README.md",
    "isaac_audio_sensors/__init__.py",
    "isaac_audio_sensors_omni/__init__.py",
}


def audit_kit_archive(path: Path) -> None:
    """Validate the Community Registry contract and shared content policy."""

    entries = archive_entries(path)
    findings: list[str] = []
    missing = sorted(REQUIRED_MEMBERS - entries.keys())
    if missing:
        findings.append(f"missing Kit members: {', '.join(missing)}")

    obsolete = sorted(
        name
        for name in entries
        if name.startswith("_vendor/") or name.endswith("DEVELOPMENT_MODE.json")
    )
    if obsolete:
        findings.append(f"obsolete Kit members: {', '.join(obsolete)}")

    manifest_bytes = entries.get("config/extension.toml")
    if manifest_bytes is not None:
        try:
            manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            findings.append(f"invalid Kit manifest: {exc}")
        else:
            package = manifest.get("package", {})
            version = package.get("version")
            if package.get("name") != EXTENSION_NAME:
                findings.append("Kit package.name must be isaac_audio_sensors.omni")
            if not isinstance(version, str) or not version:
                findings.append("Kit package.version must be a non-empty string")
            elif path.name != community_archive_name(version):
                findings.append(
                    "Kit archive filename does not match package.version: "
                    f"{path.name!r} != {community_archive_name(version)!r}"
                )
            if package.get("target") != EXPECTED_TARGET:
                findings.append(f"Kit package.target must equal {EXPECTED_TARGET!r}")
            for key, expected in EXPECTED_RESOURCES.items():
                if package.get(key) != expected:
                    findings.append(f"Kit package.{key} must be {expected!r}")
            if package.get("trusted") is not False:
                findings.append("Kit package.trusted must be false")

    if findings:
        raise ContentPolicyError("; ".join(findings))
    require_archive(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        audit_kit_archive(args.archive)
    except (ContentPolicyError, OSError) as exc:
        print(f"[kit-audit] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[kit-audit] OK {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
