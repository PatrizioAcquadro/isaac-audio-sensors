from __future__ import annotations

import pytest

from tools.release.audit_kit_archive import (
    REQUIRED_BUNDLED_MEMBERS,
    REQUIRED_MEMBERS,
    audit_kit_archive,
)
from tools.release.build_kit_extension import (
    BUNDLED_ROOT,
    _extract_wheel,
    community_archive_name,
)
from tools.release.content_policy import ContentPolicyError


def _manifest(*, kit: str = "110.1") -> str:
    return f"""
[package]
name = "isaac_audio_sensors.omni"
version = "2.0.0"
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
    entries.update({f"{prefix}{name}": "" for name in REQUIRED_BUNDLED_MEMBERS})
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
        version="2.0.0",
        expected_first_party={
            name for name in expected_entries if not name.startswith(prefix)
        },
        expected_bundled={
            name for name in expected_entries if name.startswith(prefix)
        },
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


def test_kit_audit_accepts_bundled_dependencies(tmp_path, write_zip):
    entries = _valid_entries()
    archive = write_zip(
        tmp_path / community_archive_name("2.0.0"),
        entries,
    )

    _audit(archive, entries)


def test_kit_audit_rejects_wrong_registry_target(tmp_path, write_zip):
    expected = _valid_entries()
    entries = dict(expected)
    entries["config/extension.toml"] = _manifest(kit="999.0")
    archive = write_zip(tmp_path / community_archive_name("2.0.0"), entries)

    with pytest.raises(ContentPolicyError, match="package.target"):
        _audit(archive, expected)


def test_kit_audit_rejects_bundled_numpy(tmp_path, write_zip):
    expected = _valid_entries()
    entries = dict(expected)
    prefix = f"{BUNDLED_ROOT.as_posix()}/"
    entries[f"{prefix}numpy/__init__.py"] = ""
    archive = write_zip(tmp_path / community_archive_name("2.0.0"), entries)

    with pytest.raises(ContentPolicyError, match="host-owned bundled"):
        _audit(archive, expected)


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
    archive = write_zip(tmp_path / community_archive_name("2.0.0"), entries)

    with pytest.raises(ContentPolicyError, match="unexpected Kit"):
        _audit(archive, expected)
