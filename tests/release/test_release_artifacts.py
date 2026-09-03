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

VERSION = "1.0.0"
PACKAGE = "isaac_audio_sensors"
DIST_INFO = f"{PACKAGE}-{VERSION}.dist-info"
SDIST_ROOT = f"{PACKAGE}-{VERSION}"
SDIST_NAME = f"{SDIST_ROOT}.tar.gz"
WHEEL_NAME = f"{PACKAGE}-{VERSION}-py3-none-any.whl"
KIT_NAME = f"PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v{VERSION}.zip"
SCHEMA_ROOT = f"{PACKAGE}/schemas"
EXPECTED_PACKAGE_FILES = {
    f"{PACKAGE}/__init__.py",
    f"{PACKAGE}/cli.py",
    f"{SCHEMA_ROOT}/__init__.py",
    f"{SCHEMA_ROOT}/audio_calibration_profile.v1.schema.json",
    f"{SCHEMA_ROOT}/audio_dataset_manifest.v1.schema.json",
    f"{SCHEMA_ROOT}/audio_sensor_frame.v3.schema.json",
}


def _wheel(wheel_bytes, extra_entries: dict[str, bytes | str] | None = None) -> bytes:
    entries: dict[str, bytes | str] = {
        f"{PACKAGE}/cli.py": (
            "def main():\n"
            "    from isaac_audio_sensors import __version__\n"
            "    print(__version__)\n"
        ),
        f"{SCHEMA_ROOT}/__init__.py": "",
        f"{SCHEMA_ROOT}/audio_calibration_profile.v1.schema.json": "{}\n",
        f"{SCHEMA_ROOT}/audio_dataset_manifest.v1.schema.json": "{}\n",
        f"{SCHEMA_ROOT}/audio_sensor_frame.v3.schema.json": "{}\n",
        f"{DIST_INFO}/entry_points.txt": (
            "[console_scripts]\nisaac-audio-sensors = isaac_audio_sensors.cli:main\n"
        ),
        f"{DIST_INFO}/licenses/LICENSE": "license\n",
        f"{DIST_INFO}/licenses/NOTICE": "notice\n",
    }
    entries.update(extra_entries or {})
    metadata = f"""Metadata-Version: 2.4
Name: isaac-audio-sensors
Version: {VERSION}
License-Expression: Apache-2.0
Requires-Python: >=3.10
Requires-Dist: auditok<0.6,>=0.5.2
Requires-Dist: numpy>=1.26
Provides-Extra: room
Requires-Dist: pyroomacoustics>=0.7; extra == "room"
Requires-Dist: scipy>=1.11; extra == "room"
Requires-Dist: soundfile>=0.12; extra == "room"
"""
    return wheel_bytes(
        package=PACKAGE,
        version=VERSION,
        source=f'__version__ = "{VERSION}"\n',
        metadata=metadata,
        extra_entries=entries,
    )


def _write_wheel(tmp_path, payload: bytes):
    path = tmp_path / WHEEL_NAME
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
    metadata_version: str = VERSION,
    extra_entries: dict[str, bytes | str] | None = None,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root_files = {
        "LICENSE": b"license\n",
        "NOTICE": b"notice\n",
        "README.md": b"# Package\n",
        "pyproject.toml": (
            f'[project]\nname = "isaac-audio-sensors"\nversion = "{VERSION}"\n'.encode()
        ),
    }
    for name, payload in root_files.items():
        (repo / name).write_bytes(payload)

    package_files = {
        "__init__.py": f'__version__ = "{VERSION}"\n'.encode(),
        "cli.py": b"def main():\n    pass\n",
        "schemas/__init__.py": b"",
        "schemas/audio_calibration_profile.v1.schema.json": b"{}\n",
        "schemas/audio_dataset_manifest.v1.schema.json": b"{}\n",
        "schemas/audio_sensor_frame.v3.schema.json": b"{}\n",
    }
    egg_info = f"src/{PACKAGE}.egg-info"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: isaac-audio-sensors\n"
        f"Version: {metadata_version}\n"
        "License-Expression: Apache-2.0\n"
        "Requires-Python: >=3.10\n"
        "License-File: LICENSE\n"
        "License-File: NOTICE\n"
        "Requires-Dist: auditok<0.6,>=0.5.2\n"
        "Requires-Dist: numpy>=1.26\n"
        "\n"
        "# Package\n"
    ).encode()
    manifest = {
        "LICENSE",
        "NOTICE",
        "README.md",
        "pyproject.toml",
        *(f"src/{PACKAGE}/{name}" for name in package_files),
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
        **{f"src/{PACKAGE}/{name}": payload for name, payload in package_files.items()},
        f"{egg_info}/PKG-INFO": metadata,
        f"{egg_info}/SOURCES.txt": "\n".join(sorted(manifest)) + "\n",
        f"{egg_info}/dependency_links.txt": "\n",
        f"{egg_info}/entry_points.txt": (
            "[console_scripts]\nisaac-audio-sensors = isaac_audio_sensors.cli:main\n"
        ),
        f"{egg_info}/requires.txt": "auditok<0.6,>=0.5.2\nnumpy>=1.26\n",
        f"{egg_info}/top_level.txt": f"{PACKAGE}\n",
    }
    entries.update(extra_entries or {})
    path = tmp_path / SDIST_NAME
    with tarfile.open(path, mode="w:gz") as archive:
        for name, raw in entries.items():
            payload = raw.encode() if isinstance(raw, str) else raw
            info = tarfile.TarInfo(f"{SDIST_ROOT}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path, repo, set(package_files)


def test_python_wheel_audit_installs_exact_artifact(tmp_path, wheel_bytes):
    wheel = _write_wheel(tmp_path, _wheel(wheel_bytes))

    audit_python_wheel(
        wheel,
        version=VERSION,
        expected_package_files=EXPECTED_PACKAGE_FILES,
    )


def test_python_sdist_audit_accepts_exact_source_distribution(tmp_path):
    sdist, repo, package_files = _write_sdist(tmp_path)

    audit_python_sdist(
        sdist,
        version=VERSION,
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
            version=VERSION,
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
            version=VERSION,
            repo_root=repo,
            expected_package_files=package_files,
        )


@pytest.mark.parametrize(
    "artifact_names",
    (
        {WHEEL_NAME, KIT_NAME},
        {SDIST_NAME, WHEEL_NAME, KIT_NAME, "unexpected.txt"},
    ),
    ids=("missing", "extra"),
)
def test_release_audit_requires_exact_outbox(tmp_path, artifact_names):
    repo = tmp_path / "repo"
    dist = repo / "dist"
    dist.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        f'[project]\nversion = "{VERSION}"\n', encoding="utf-8"
    )
    for name in artifact_names:
        (dist / name).write_bytes(b"artifact")

    with pytest.raises(ContentPolicyError, match="dist root"):
        audit_release_artifacts(
            dist_dir=dist,
            repo_root=repo,
            wheelhouse=tmp_path / "wheelhouse",
        )


def test_python_wheel_audit_rejects_unexpected_content(tmp_path, wheel_bytes):
    wheel = _write_wheel(
        tmp_path,
        _wheel(wheel_bytes, {f"{PACKAGE}/unused.py": ""}),
    )

    with pytest.raises(ContentPolicyError, match="invalid wheel inventory"):
        audit_python_wheel(
            wheel,
            version=VERSION,
            expected_package_files=EXPECTED_PACKAGE_FILES,
        )


@pytest.mark.parametrize(
    "member",
    (
        f"{DIST_INFO}/METADATA",
        f"{DIST_INFO}/licenses/LICENSE",
        f"{SCHEMA_ROOT}/audio_sensor_frame.v3.schema.json",
    ),
)
def test_python_wheel_audit_requires_metadata_licenses_and_schemas(
    tmp_path, wheel_bytes, member
):
    wheel = _write_wheel(tmp_path, _without_member(_wheel(wheel_bytes), member))

    with pytest.raises(ContentPolicyError, match="invalid wheel inventory"):
        audit_python_wheel(
            wheel,
            version=VERSION,
            expected_package_files=EXPECTED_PACKAGE_FILES,
        )
