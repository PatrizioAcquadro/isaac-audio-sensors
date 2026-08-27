from __future__ import annotations

import hashlib

import pytest

import tools.release.build_kit_extension as kit_builder
from tools.release.audit_kit_archive import (
    REQUIRED_MEMBERS,
    audit_kit_archive,
    required_bundled_members,
)
from tools.release.build_kit_extension import (
    BUNDLED_ROOT,
    LockedDependency,
    _extract_wheel,
    community_archive_name,
    validate_wheelhouse,
)
from tools.release.content_policy import ContentPolicyError

VERSION = "3.0.0"
KIT_TARGET = "110.1"


def _manifest(*, kit: str = KIT_TARGET) -> str:
    return f"""
[package]
name = "isaac_audio_sensors.omni"
version = "{VERSION}"
readme = "docs/README.md"
changelog = "docs/CHANGELOG.md"
icon = "data/icon.svg"
preview_image = "data/preview.png"
trusted = false

[package.target]
config = ["release"]
kit = ["{kit}"]
platform = ["linux-x86_64"]
python = ["cp312"]
"""


def _valid_entries() -> dict[str, str]:
    prefix = f"{BUNDLED_ROOT.as_posix()}/"
    entries = {name: "" for name in REQUIRED_MEMBERS}
    entries.update({f"{prefix}{name}": "" for name in required_bundled_members()})
    entries.update(
        {
            f"{prefix}_cffi_backend.cpython-312-x86_64-linux-gnu.so": "",
            f"{prefix}_soundfile_data/libsndfile_x86_64.so": "",
            f"{prefix}pyroomacoustics/libroom.cpython-312-x86_64-linux-gnu.so": "",
            f"{prefix}scipy.libs/libscipy_openblas-test.so": "",
        }
    )
    entries["config/extension.toml"] = _manifest()
    return entries


def _audit(archive, expected_entries: dict[str, str]) -> None:
    prefix = f"{BUNDLED_ROOT.as_posix()}/"
    audit_kit_archive(
        archive,
        version=VERSION,
        expected_first_party={
            name for name in expected_entries if not name.startswith(prefix)
        },
        expected_bundled={name for name in expected_entries if name.startswith(prefix)},
    )


def test_wheel_staging_keeps_runtime_and_license_files(tmp_path, wheel_bytes):
    wheel = tmp_path / "sample-1.0.0-py3-none-any.whl"
    wheel.write_bytes(
        wheel_bytes(
            extra_entries={
                "sample/tests/test_only.py": "",
                "sample-1.0.0.dist-info/licenses/LICENSE": "MIT",
            }
        )
    )
    destination = tmp_path / "bundle"

    installed = _extract_wheel(wheel, destination)

    assert "sample/__init__.py" in installed
    assert "sample-1.0.0.dist-info/licenses/LICENSE" in installed
    assert "sample/tests/test_only.py" not in installed
    assert not any(name.endswith("/RECORD") for name in installed)


def test_wheel_staging_rejects_host_owned_numpy(tmp_path, wheel_bytes):
    wheel = tmp_path / "numpy-1.0.0-py3-none-any.whl"
    wheel.write_bytes(wheel_bytes(package="numpy"))

    with pytest.raises(ValueError, match="host-owned path"):
        _extract_wheel(wheel, tmp_path / "bundle")


def test_validate_wheelhouse_returns_exact_locked_wheel(tmp_path, monkeypatch):
    payload = b"locked wheel"
    wheel = tmp_path / "sample-1.0.0-py3-none-any.whl"
    wheel.write_bytes(payload)
    dependency = LockedDependency(
        name="sample",
        version="1.0.0",
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(kit_builder, "read_dependency_lock", lambda: (dependency,))

    assert validate_wheelhouse(tmp_path) == ((dependency, wheel),)


def test_validate_wheelhouse_rejects_missing_wheel(tmp_path, monkeypatch):
    dependency = LockedDependency("sample", "1.0.0", "0" * 64)
    monkeypatch.setattr(kit_builder, "read_dependency_lock", lambda: (dependency,))

    with pytest.raises(ValueError, match="must contain one wheel"):
        validate_wheelhouse(tmp_path)


def test_validate_wheelhouse_rejects_extra_file(tmp_path, monkeypatch):
    payload = b"locked wheel"
    (tmp_path / "sample-1.0.0-py3-none-any.whl").write_bytes(payload)
    (tmp_path / "extra.whl").write_bytes(b"extra")
    dependency = LockedDependency(
        "sample",
        "1.0.0",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(kit_builder, "read_dependency_lock", lambda: (dependency,))

    with pytest.raises(ValueError, match="undeclared files"):
        validate_wheelhouse(tmp_path)


def test_validate_wheelhouse_rejects_wrong_hash(tmp_path, monkeypatch):
    (tmp_path / "sample-1.0.0-py3-none-any.whl").write_bytes(b"wrong")
    dependency = LockedDependency("sample", "1.0.0", "0" * 64)
    monkeypatch.setattr(kit_builder, "read_dependency_lock", lambda: (dependency,))

    with pytest.raises(ValueError, match="wheel hash mismatch"):
        validate_wheelhouse(tmp_path)


def test_required_bundled_members_use_lock_versions():
    versions = {
        "cffi": "9.1",
        "pycparser": "9.2",
        "pyroomacoustics": "9.3",
        "scipy": "9.4",
        "soundfile": "9.5",
    }
    dependencies = tuple(
        LockedDependency(name, version, "0" * 64) for name, version in versions.items()
    )

    members = required_bundled_members(dependencies)

    for name, version in versions.items():
        assert f"{name}-{version}.dist-info/METADATA" in members
    assert "cffi-2.1.0.dist-info/METADATA" not in members


def test_kit_audit_accepts_bundled_dependencies(tmp_path, write_zip):
    entries = _valid_entries()
    archive = write_zip(
        tmp_path / community_archive_name(VERSION),
        entries,
    )

    _audit(archive, entries)


def test_kit_audit_rejects_wrong_registry_target(tmp_path, write_zip):
    expected = _valid_entries()
    entries = dict(expected)
    entries["config/extension.toml"] = _manifest(kit="999.0")
    archive = write_zip(tmp_path / community_archive_name(VERSION), entries)

    with pytest.raises(ContentPolicyError, match="package.target"):
        _audit(archive, expected)


def test_kit_audit_rejects_bundled_numpy(tmp_path, write_zip):
    expected = _valid_entries()
    entries = dict(expected)
    prefix = f"{BUNDLED_ROOT.as_posix()}/"
    entries[f"{prefix}numpy/__init__.py"] = ""
    archive = write_zip(tmp_path / community_archive_name(VERSION), entries)

    with pytest.raises(ContentPolicyError, match="host-owned bundled"):
        _audit(archive, expected)


def test_kit_audit_requires_critical_bundled_member(tmp_path, write_zip):
    entries = _valid_entries()
    prefix = f"{BUNDLED_ROOT.as_posix()}/"
    del entries[f"{prefix}cffi/__init__.py"]
    archive = write_zip(tmp_path / community_archive_name(VERSION), entries)

    with pytest.raises(ContentPolicyError, match="missing bundled dependency members"):
        _audit(archive, entries)


@pytest.mark.parametrize(
    "member",
    (
        "isaac_audio_sensors/unused.py",
        f"{BUNDLED_ROOT.as_posix()}/scipy/unused.py",
    ),
)
def test_kit_audit_rejects_unexpected_inventory(tmp_path, write_zip, member):
    expected = _valid_entries()
    entries = dict(expected)
    entries[member] = ""
    archive = write_zip(tmp_path / community_archive_name(VERSION), entries)

    with pytest.raises(ContentPolicyError, match="unexpected Kit"):
        _audit(archive, expected)
