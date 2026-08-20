from __future__ import annotations

import hashlib
import json

import pytest

from tools.release.audit_acoustic_pack import audit_acoustic_pack
from tools.release.build_acoustic_pack import build_acoustic_pack
from tools.release.content_policy import ContentPolicyError


def _pack_entries(wheel: bytes) -> dict[str, bytes | str]:
    manifest = {"artifacts": [{"filename": "sample.whl"}]}
    return {
        "pack_manifest.json": json.dumps(manifest),
        "requirements.lock": "sample==1.0 --hash=sha256:" + "0" * 64,
        "install_pack.py": "print('install')\n",
        "wheels/sample.whl": wheel,
    }


def test_pack_audit_accepts_declared_wheel(tmp_path, wheel_bytes, write_tar):
    archive = write_tar(tmp_path / "pack.tar.gz", _pack_entries(wheel_bytes()))

    audit_acoustic_pack(archive)


def test_pack_audit_rejects_missing_declared_wheel(tmp_path, write_tar):
    entries = _pack_entries(b"")
    del entries["wheels/sample.whl"]
    archive = write_tar(tmp_path / "pack.tar.gz", entries)

    with pytest.raises(ContentPolicyError, match="missing pack wheels"):
        audit_acoustic_pack(archive)


def test_pack_builder_uses_deterministic_wheelhouse(
    tmp_path, wheel_bytes
):
    repo = tmp_path / "repo"
    wheelhouse = tmp_path / "wheelhouse"
    pack_dir = repo / "packs" / "acoustics"
    tools_dir = repo / "tools" / "release"
    pack_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    wheelhouse.mkdir()
    wheel_name = "sample-1.0.0-py3-none-any.whl"
    wheel = wheel_bytes()
    wheel_sha = hashlib.sha256(wheel).hexdigest()
    (wheelhouse / wheel_name).write_bytes(wheel)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nversion = '1.0.0'\n", encoding="utf-8"
    )
    (tools_dir / "install_pack.py").write_text("print('install')\n", encoding="utf-8")
    (pack_dir / "requirements.lock").write_text(
        f"sample==1.0.0 --hash=sha256:{wheel_sha}\n", encoding="utf-8"
    )
    (pack_dir / "pack.toml").write_text(
        """
[pack]
pack_id = "acoustics-l2l3"
pack_version = "1.0.0"
artifact_name = "isaac_audio_sensors_acoustic_pack-l2l3-1.0.0-linux_x86_64-cp312.tar.gz"
requirements_lock = "requirements.lock"
numpy_compatibility = ">=2,<3"

[target]
python_version = "3.12"
abi = "cp312"
os = "linux"
arch = "x86_64"

[[host_requirements]]
name = "numpy"
version = "2.5.0"
reason = "host-owned"

[[pack_distributions]]
name = "sample"
version = "1.0.0"
wheel = """ + f'"{wheel_name}"\nsha256 = "{wheel_sha}"\n' + """

[[capabilities]]
id = "room"
kind = "backend"
fidelity_level = "L2"
modules = ["sample"]
""".lstrip(),
        encoding="utf-8",
    )

    first = build_acoustic_pack(
        repo_root=repo,
        wheelhouse=wheelhouse,
        output_dir=tmp_path / "first",
        source_revision="0" * 40,
        verify_source=False,
    )
    second = build_acoustic_pack(
        repo_root=repo,
        wheelhouse=wheelhouse,
        output_dir=tmp_path / "second",
        source_revision="0" * 40,
        verify_source=False,
    )

    assert first.archive_path.read_bytes() == second.archive_path.read_bytes()
    audit_acoustic_pack(first.archive_path)
