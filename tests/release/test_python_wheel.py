from __future__ import annotations

import io
import zipfile

import pytest

from tools.release.audit_python_wheel import audit_python_wheel
from tools.release.content_policy import ContentPolicyError

DIST_INFO = "isaac_audio_sensors-1.0.0.dist-info"
SCHEMA_ROOT = "isaac_audio_sensors/schemas"


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


def test_python_wheel_audit_installs_minimal_artifact(tmp_path, wheel_bytes):
    wheel = _write_wheel(tmp_path, _wheel(wheel_bytes))
    kit_archive = (
        tmp_path
        / "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v1.0.0.zip"
    )
    kit_archive.write_bytes(b"kit")

    assert audit_python_wheel(tmp_path) == wheel


def test_python_wheel_audit_rejects_source_distribution(tmp_path, wheel_bytes):
    _write_wheel(tmp_path, _wheel(wheel_bytes))
    (tmp_path / "isaac_audio_sensors-1.0.0.tar.gz").write_bytes(b"sdist")

    with pytest.raises(ContentPolicyError, match="exactly one Python wheel"):
        audit_python_wheel(tmp_path)


def test_python_wheel_audit_rejects_unexpected_content(tmp_path, wheel_bytes):
    payload = _wheel(wheel_bytes, {"examples/demo.py": "print('demo')\n"})
    _write_wheel(tmp_path, payload)

    with pytest.raises(ContentPolicyError, match="unexpected wheel roots"):
        audit_python_wheel(tmp_path)


@pytest.mark.parametrize(
    "member",
    ("isaac_audio_sensors/_bundled/sample.py", "isaac_audio_sensors/core/packs.py"),
)
def test_python_wheel_audit_rejects_kit_only_members(
    tmp_path, wheel_bytes, member
):
    _write_wheel(tmp_path, _wheel(wheel_bytes, {member: ""}))

    with pytest.raises(ContentPolicyError, match="forbidden wheel members"):
        audit_python_wheel(tmp_path)


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
    payload = _without_member(_wheel(wheel_bytes), member)
    _write_wheel(tmp_path, payload)

    with pytest.raises(ContentPolicyError):
        audit_python_wheel(tmp_path)
