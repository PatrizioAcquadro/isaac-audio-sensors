from __future__ import annotations

from pathlib import Path

import pytest

from tools.release.audit_kit_archive import REQUIRED_MEMBERS, audit_kit_archive
from tools.release.build_kit_extension import (
    build_kit_extension,
    community_archive_name,
)
from tools.release.content_policy import ContentPolicyError, archive_entries

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_kit_build_is_the_single_community_archive(tmp_path):
    archive = build_kit_extension(repo_root=REPO_ROOT, output_dir=tmp_path)

    assert archive.name == community_archive_name("2.0.0")
    assert list(tmp_path.iterdir()) == [archive]
    entries = archive_entries(archive)
    assert entries.keys() >= REQUIRED_MEMBERS
    assert not any(
        name.startswith("_vendor/") or name.endswith("DEVELOPMENT_MODE.json")
        for name in entries
    )
    audit_kit_archive(archive)


def test_kit_audit_rejects_wrong_registry_target(tmp_path, write_zip):
    entries = {name: "" for name in REQUIRED_MEMBERS}
    entries["config/extension.toml"] = """
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
kit = ["999.0"]
platform = ["linux-x86_64"]
python = ["cp312"]
"""
    archive = write_zip(tmp_path / community_archive_name("2.0.0"), entries)

    with pytest.raises(ContentPolicyError, match="package.target"):
        audit_kit_archive(archive)
