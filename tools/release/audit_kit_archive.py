"""Audit the standalone NVIDIA Community Registry archive."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

try:
    from .build_kit_extension import (
        BUNDLED_ROOT,
        EXTENSION_NAME,
        LockedDependency,
        community_archive_name,
        is_host_owned_path,
        read_dependency_lock,
    )
    from .content_policy import ContentPolicyError, archive_entries, require_archive
except ImportError:
    from build_kit_extension import (
        BUNDLED_ROOT,
        EXTENSION_NAME,
        LockedDependency,
        community_archive_name,
        is_host_owned_path,
        read_dependency_lock,
    )
    from content_policy import ContentPolicyError, archive_entries, require_archive


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
_BUNDLE_PREFIX = f"{BUNDLED_ROOT.as_posix()}/"
_REQUIRED_BUNDLED_TEMPLATES = {
    "cffi": (
        "cffi/__init__.py",
        "{dist_info}/METADATA",
        "{dist_info}/licenses/LICENSE",
    ),
    "pycparser": (
        "pycparser/__init__.py",
        "{dist_info}/METADATA",
        "{dist_info}/licenses/LICENSE",
    ),
    "pyroomacoustics": (
        "pyroomacoustics/__init__.py",
        "{dist_info}/METADATA",
        "{dist_info}/licenses/LICENSE",
    ),
    "scipy": (
        "scipy/__init__.py",
        "{dist_info}/LICENSE.txt",
        "{dist_info}/METADATA",
    ),
    "soundfile": (
        "soundfile.py",
        "{dist_info}/LICENSE",
        "{dist_info}/METADATA",
    ),
}
_REQUIRED_UNVERSIONED_BUNDLED_MEMBERS = {
    "_soundfile_data/COPYING",
    "licensing/license_notes.md",
}


def required_bundled_members(
    dependencies: tuple[LockedDependency, ...] | None = None,
) -> frozenset[str]:
    """Return critical bundled paths using versions from the dependency lock."""

    locked = dependencies if dependencies is not None else read_dependency_lock()
    by_name = {dependency.normalized_name: dependency for dependency in locked}
    if set(by_name) != set(_REQUIRED_BUNDLED_TEMPLATES):
        raise ValueError("locked distributions do not match bundled audit policy")

    members = set(_REQUIRED_UNVERSIONED_BUNDLED_MEMBERS)
    for name, templates in _REQUIRED_BUNDLED_TEMPLATES.items():
        dependency = by_name[name]
        dist_info = f"{dependency.normalized_name}-{dependency.version}.dist-info"
        members.update(
            template.format(dist_info=dist_info) for template in templates
        )
    return frozenset(members)


def audit_kit_archive(
    path: Path,
    *,
    version: str,
    expected_first_party: set[str],
    expected_bundled: set[str],
) -> None:
    """Validate the Community Registry and bundled-dependency contracts."""

    entries = archive_entries(path)
    findings: list[str] = []
    actual_first_party = {
        name for name in entries if not name.startswith(_BUNDLE_PREFIX)
    }
    actual_bundled = {
        name for name in entries if name.startswith(_BUNDLE_PREFIX)
    }
    _append_inventory_findings(
        findings,
        actual_first_party,
        expected_first_party,
        label="Kit first-party",
    )
    _append_inventory_findings(
        findings,
        actual_bundled,
        expected_bundled,
        label="Kit bundled",
    )
    missing = sorted(REQUIRED_MEMBERS - entries.keys())
    if missing:
        findings.append(f"missing Kit members: {', '.join(missing)}")

    bundle_entries = {
        name[len(_BUNDLE_PREFIX) :]
        for name in entries
        if name.startswith(_BUNDLE_PREFIX)
    }
    missing_bundled = sorted(required_bundled_members() - bundle_entries)
    if missing_bundled:
        findings.append(
            f"missing bundled dependency members: {', '.join(missing_bundled)}"
        )
    native_requirements = {
        "CFFI": any(name.startswith("_cffi_backend.") for name in bundle_entries),
        "libsndfile": any(
            name.startswith("_soundfile_data/libsndfile_")
            for name in bundle_entries
        ),
        "pyroomacoustics": any(
            name.startswith("pyroomacoustics/libroom.") for name in bundle_entries
        ),
        "SciPy": any(
            name.startswith("scipy.libs/libscipy_openblas-")
            for name in bundle_entries
        ),
    }
    missing_native = sorted(
        name for name, present in native_requirements.items() if not present
    )
    if missing_native:
        findings.append(
            f"missing bundled native libraries: {', '.join(missing_native)}"
        )

    host_owned = sorted(name for name in bundle_entries if is_host_owned_path(name))
    if host_owned:
        findings.append(f"host-owned bundled members: {', '.join(host_owned)}")

    obsolete = sorted(
        name
        for name in entries
        if name.startswith(("_vendor/", "packs/", "wheels/"))
        or name.endswith(
            (
                "DEVELOPMENT_MODE.json",
                "core/packs.py",
                "install_pack.py",
                "pack_manifest.json",
                "requirements.lock",
            )
        )
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
            manifest_version = package.get("version")
            if package.get("name") != EXTENSION_NAME:
                findings.append("Kit package.name must be isaac_audio_sensors.omni")
            if manifest_version != version:
                findings.append(
                    "Kit package.version does not match pyproject.toml: "
                    f"{manifest_version!r} != {version!r}"
                )
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


def _append_inventory_findings(
    findings: list[str], actual: set[str], expected: set[str], *, label: str
) -> None:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        findings.append(f"missing {label} members: {', '.join(missing)}")
    if unexpected:
        findings.append(f"unexpected {label} members: {', '.join(unexpected)}")
