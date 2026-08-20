from __future__ import annotations

from pathlib import Path

import pytest

from tools.release.audit_kit_archive import audit_kit_archive
from tools.release.build_kit_extension import build_kit_extension
from tools.release.content_policy import ContentPolicyError

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "config/extension.toml": "[package]\nversion = '1.0.0'\n",
    "isaac_audio_sensors_omni/__init__.py": "",
    "_vendor/VENDORED.json": "{}\n",
    "_vendor/isaac_audio_sensors/__init__.py": "",
}


def test_kit_audit_accepts_required_members(tmp_path, write_zip):
    archive = write_zip(tmp_path / "kit.zip", REQUIRED)

    audit_kit_archive(archive)


def test_kit_audit_rejects_missing_entrypoint(tmp_path, write_zip):
    archive = write_zip(
        tmp_path / "kit.zip",
        {
            name: value
            for name, value in REQUIRED.items()
            if name != "config/extension.toml"
        },
    )

    with pytest.raises(ContentPolicyError, match="missing Kit members"):
        audit_kit_archive(archive)


def test_real_kit_build_is_deterministic_and_policy_clean(tmp_path):
    first = build_kit_extension(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "first",
        source_revision="0" * 40,
        verify_source=False,
    )
    second = build_kit_extension(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "second",
        source_revision="0" * 40,
        verify_source=False,
    )

    assert first.archive_path.read_bytes() == second.archive_path.read_bytes()
    audit_kit_archive(first.archive_path)
