from __future__ import annotations

import io
import tarfile
import zipfile

import pytest

from tools.release.audit_release_artifacts import (
    audit_python_sdist,
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
            "[console_scripts]\nisaac-audio-sensors = isaac_audio_sensors.cli:main\n"
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


def _write_sdist(
    tmp_path,
    *,
    metadata_version: str = "1.0.0",
    extra_entries: dict[str, bytes | str] | None = None,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root_files = {
        "LICENSE": b"license\n",
        "NOTICE": b"notice\n",
        "README.md": b"# Package\n",
        "pyproject.toml": (
            b'[project]\nname = "isaac-audio-sensors"\nversion = "1.0.0"\n'
        ),
    }
    for name, payload in root_files.items():
        (repo / name).write_bytes(payload)

    package_files = {
        "__init__.py": b'__version__ = "1.0.0"\n',
        "cli.py": b"def main():\n    pass\n",
        "schemas/__init__.py": b"",
        "schemas/audio_calibration_profile.v1.schema.json": b"{}\n",
        "schemas/audio_dataset_manifest.v1.schema.json": b"{}\n",
        "schemas/audio_sensor_frame.v1.schema.json": b"{}\n",
    }
    egg_info = "src/isaac_audio_sensors.egg-info"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: isaac-audio-sensors\n"
        f"Version: {metadata_version}\n"
        "License-Expression: Apache-2.0\n"
        "Requires-Python: >=3.10\n"
        "License-File: LICENSE\n"
        "License-File: NOTICE\n"
        "\n"
        "# Package\n"
    ).encode()
    manifest = {
        "LICENSE",
        "NOTICE",
        "README.md",
        "pyproject.toml",
        *(f"src/isaac_audio_sensors/{name}" for name in package_files),
        *(
            f"{egg_info}/{name}"
            for name in (
                "PKG-INFO",
                "SOURCES.txt",
                "dependency_links.txt",
                "entry_points.txt",
                "requires.txt",
                "top_level.txt",
            )
        ),
    }
    entries: dict[str, bytes | str] = {
        **root_files,
        "PKG-INFO": metadata,
        "setup.cfg": "[egg_info]\ntag_build =\ntag_date = 0\n",
        **{
            f"src/isaac_audio_sensors/{name}": payload
            for name, payload in package_files.items()
        },
        f"{egg_info}/PKG-INFO": metadata,
        f"{egg_info}/SOURCES.txt": "\n".join(sorted(manifest)) + "\n",
        f"{egg_info}/dependency_links.txt": "\n",
        f"{egg_info}/entry_points.txt": (
            "[console_scripts]\nisaac-audio-sensors = isaac_audio_sensors.cli:main\n"
        ),
        f"{egg_info}/requires.txt": "numpy>=1.26\n",
        f"{egg_info}/top_level.txt": "isaac_audio_sensors\n",
    }
    entries.update(extra_entries or {})
    path = tmp_path / "isaac_audio_sensors-1.0.0.tar.gz"
    with tarfile.open(path, mode="w:gz") as archive:
        for name, raw in entries.items():
            payload = raw.encode() if isinstance(raw, str) else raw
            info = tarfile.TarInfo(f"isaac_audio_sensors-1.0.0/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path, repo, set(package_files)


def test_python_wheel_audit_installs_exact_artifact(tmp_path, wheel_bytes):
    wheel = _write_wheel(tmp_path, _wheel(wheel_bytes))

    audit_python_wheel(
        wheel,
        version="1.0.0",
        expected_package_files=EXPECTED_PACKAGE_FILES,
    )


def test_python_sdist_audit_accepts_exact_source_distribution(tmp_path):
    sdist, repo, package_files = _write_sdist(tmp_path)

    audit_python_sdist(
        sdist,
        version="1.0.0",
        repo_root=repo,
        expected_package_files=package_files,
    )


def test_python_sdist_audit_rejects_unexpected_content(tmp_path):
    sdist, repo, package_files = _write_sdist(
        tmp_path,
        extra_entries={"tests/test_bad.py": "def test_bad():\n    pass\n"},
    )

    with pytest.raises(ContentPolicyError, match="invalid sdist inventory"):
        audit_python_sdist(
            sdist,
            version="1.0.0",
            repo_root=repo,
            expected_package_files=package_files,
        )


def test_python_sdist_audit_rejects_wrong_metadata(tmp_path):
    sdist, repo, package_files = _write_sdist(
        tmp_path,
        metadata_version="2.0.0",
    )

    with pytest.raises(ContentPolicyError, match="name or version metadata"):
        audit_python_sdist(
            sdist,
            version="1.0.0",
            repo_root=repo,
            expected_package_files=package_files,
        )


def test_release_audit_rejects_missing_sdist(tmp_path):
    repo = tmp_path / "repo"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (dist / "isaac_audio_sensors-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v1.0.0.zip").write_bytes(
        b"kit"
    )

    with pytest.raises(ContentPolicyError, match="dist root"):
        audit_release_artifacts(
            dist_dir=dist,
            repo_root=repo,
            wheelhouse=tmp_path / "wheelhouse",
        )


def test_release_audit_rejects_extra_outbox_artifact(tmp_path):
    repo = tmp_path / "repo"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (dist / "isaac_audio_sensors-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v1.0.0.zip").write_bytes(
        b"kit"
    )
    (dist / "isaac_audio_sensors-1.0.0.tar.gz").write_bytes(b"sdist")
    (dist / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

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
