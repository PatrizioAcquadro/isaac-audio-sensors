from __future__ import annotations

import io
import zipfile

import pytest

from tools.release.audit_release_artifacts import (
    audit_python_wheel,
    audit_release_artifacts,
)
from tools.release.content_policy import ContentPolicyError

DIST_INFO = "isaac_audio_sensors-1.0.0.dist-info"
SCHEMA_ROOT = "isaac_audio_sensors/schemas"
EXPECTED_PACKAGE_FILES = {
    "isaac_audio_sensors/__init__.py",
    "isaac_audio_sensors/cli.py",
    f"{SCHEMA_ROOT}/__init__.py",
    f"{SCHEMA_ROOT}/audio_calibration_profile.v1.schema.json",
    f"{SCHEMA_ROOT}/audio_dataset_manifest.v1.schema.json",
    f"{SCHEMA_ROOT}/audio_sensor_frame.v1.schema.json",
}


def _wheel(wheel_bytes, extra_entries: dict[str, bytes | str] | None = None) -> bytes:
    entries: dict[str, bytes | str] = {
        "isaac_audio_sensors/cli.py": (
            "def main():\n"
            "    from isaac_audio_sensors import __version__\n"
            "    print(__version__)\n"
        ),
        f"{SCHEMA_ROOT}/__init__.py": "",
        f"{SCHEMA_ROOT}/audio_calibration_profile.v1.schema.json": "{}\n",
        f"{SCHEMA_ROOT}/audio_dataset_manifest.v1.schema.json": "{}\n",
        f"{SCHEMA_ROOT}/audio_sensor_frame.v1.schema.json": "{}\n",
        f"{DIST_INFO}/entry_points.txt": (
            "[console_scripts]\n"
            "isaac-audio-sensors = isaac_audio_sensors.cli:main\n"
        ),
        f"{DIST_INFO}/licenses/LICENSE": "license\n",
        f"{DIST_INFO}/licenses/NOTICE": "notice\n",
    }
    entries.update(extra_entries or {})
    metadata = """Metadata-Version: 2.4
Name: isaac-audio-sensors
Version: 1.0.0
License-Expression: Apache-2.0
Requires-Python: >=3.10
Provides-Extra: room
Requires-Dist: pyroomacoustics>=0.7; extra == "room"
Requires-Dist: scipy>=1.11; extra == "room"
Requires-Dist: soundfile>=0.12; extra == "room"
"""
    return wheel_bytes(
        package="isaac_audio_sensors",
        source='__version__ = "1.0.0"\n',
        metadata=metadata,
        extra_entries=entries,
    )


def _write_wheel(tmp_path, payload: bytes):
    path = tmp_path / "isaac_audio_sensors-1.0.0-py3-none-any.whl"
    path.write_bytes(payload)
    return path


def _without_member(payload: bytes, member: str) -> bytes:
    source = io.BytesIO(payload)
    result = io.BytesIO()
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(result, "w") as output:
        for name in archive.namelist():
            if name != member:
                output.writestr(name, archive.read(name))
    return result.getvalue()


def test_python_wheel_audit_installs_exact_artifact(tmp_path, wheel_bytes):
    wheel = _write_wheel(tmp_path, _wheel(wheel_bytes))

    audit_python_wheel(
        wheel,
        version="1.0.0",
        expected_package_files=EXPECTED_PACKAGE_FILES,
    )


def test_release_audit_rejects_extra_outbox_artifact(tmp_path):
    repo = tmp_path / "repo"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (dist / "isaac_audio_sensors-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    (
        dist / "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v1.0.0.zip"
    ).write_bytes(b"kit")
    (dist / "isaac_audio_sensors-1.0.0.tar.gz").write_bytes(b"sdist")

    with pytest.raises(ContentPolicyError, match="dist root"):
        audit_release_artifacts(
            dist_dir=dist,
            repo_root=repo,
            wheelhouse=tmp_path / "wheelhouse",
        )


def test_python_wheel_audit_rejects_unexpected_content(tmp_path, wheel_bytes):
    wheel = _write_wheel(
        tmp_path,
        _wheel(wheel_bytes, {"isaac_audio_sensors/unused.py": ""}),
    )

    with pytest.raises(ContentPolicyError, match="invalid wheel inventory"):
        audit_python_wheel(
            wheel,
            version="1.0.0",
            expected_package_files=EXPECTED_PACKAGE_FILES,
        )


@pytest.mark.parametrize(
    "member",
    (
        f"{DIST_INFO}/METADATA",
        f"{DIST_INFO}/licenses/LICENSE",
        f"{SCHEMA_ROOT}/audio_sensor_frame.v1.schema.json",
    ),
)
def test_python_wheel_audit_requires_metadata_licenses_and_schemas(
    tmp_path, wheel_bytes, member
):
    wheel = _write_wheel(tmp_path, _without_member(_wheel(wheel_bytes), member))

    with pytest.raises(ContentPolicyError, match="invalid wheel inventory"):
        audit_python_wheel(
            wheel,
            version="1.0.0",
            expected_package_files=EXPECTED_PACKAGE_FILES,
        )
