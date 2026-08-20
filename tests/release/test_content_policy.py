from __future__ import annotations

import io
import zipfile

import pytest

from tools.release.content_policy import ContentPolicyError, require_archive


def test_policy_accepts_minimal_archive(tmp_path, write_zip):
    archive = write_zip(tmp_path / "valid.zip", {"package/__init__.py": ""})

    require_archive(archive)


@pytest.mark.parametrize(
    "name",
    [
        "te" + "sts/check.py",
        "dataset/frame.json",
        "outputs/result.json",
        "package/acquisition/run.py",
        "package/alex_profile.json",
        "package/unitree-profile.json",
        "package/molmo/scene.usda",
        "package/" + "s" + "3_7_gate.py",
    ],
)
def test_policy_rejects_forbidden_paths(tmp_path, write_zip, name):
    archive = write_zip(tmp_path / "invalid.zip", {name: ""})

    with pytest.raises(ContentPolicyError):
        require_archive(archive)


@pytest.mark.parametrize(
    "content",
    [
        "/home/user/private/file.wav",
        "from isaac_audio_sensors." + "acquisition import run",
        "from ihmc_" + "alex_isaaclab import robot",
        "profile_id = alex_head_quad",
        "profile_id = unitree_base_quad",
        "fixture = ~/Desktop/CombinedScene/scene.usda",
        "scene = /World/Unitree/base_link",
        "see tests/" + "test_contract.py",
        "S" + "4.8 acceptance",
    ],
)
def test_policy_rejects_forbidden_content(tmp_path, write_zip, content):
    archive = write_zip(tmp_path / "invalid.zip", {"package/info.txt": content})

    with pytest.raises(ContentPolicyError):
        require_archive(archive)


def test_policy_allows_phase_history_only_in_changelog(tmp_path, write_zip):
    archive = write_zip(
        tmp_path / "history.zip", {"CHANGELOG.md": "Removed " + "S" + "4.8.\n"}
    )

    require_archive(archive)


def test_policy_audits_nested_wheels(tmp_path, write_tar):
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("te" + "sts/leak.py", "")
    pack = write_tar(tmp_path / "pack.tar.gz", {"wheels/leak.whl": wheel.getvalue()})

    with pytest.raises(ContentPolicyError):
        require_archive(pack)
