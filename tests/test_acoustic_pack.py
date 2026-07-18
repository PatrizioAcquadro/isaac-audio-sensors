"""Hermetic tests for the Linux acoustic-pack toolchain."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest

from isaac_audio_sensors.core.packs import discover_pack_installs
from scripts.audit_acoustic_pack import audit_acoustic_pack
from scripts.build_acoustic_pack import build_acoustic_pack

VERSION = "1.10.0"
ARTIFACT = (
    "isaac_audio_sensors_acoustic_pack-l2l3-"
    f"{VERSION}-linux_x86_64-cp312.tar.gz"
)
WHEELS = (
    (
        "pyroomacoustics",
        "0.10.1",
        "pyroomacoustics-0.10.1-cp312-cp312-"
        "manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "pyroomacoustics/__init__.py",
    ),
    (
        "scipy",
        "1.18.0",
        "scipy-1.18.0-cp312-cp312-"
        "manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "scipy/__init__.py",
    ),
    (
        "soundfile",
        "0.14.0",
        "soundfile-0.14.0-py2.py3-none-manylinux_2_28_x86_64.whl",
        "soundfile.py",
    ),
    (
        "cffi",
        "2.1.0",
        "cffi-2.1.0-cp312-cp312-"
        "manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
        "cffi/__init__.py",
    ),
    (
        "pycparser",
        "3.0",
        "pycparser-3.0-py3-none-any.whl",
        "pycparser/__init__.py",
    ),
)


def _write_wheel(
    path: Path, *, name: str, version: str, module_path: str
) -> None:
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    top_level = module_path.split("/", 1)[0].removesuffix(".py")
    files = {
        module_path: f"__version__ = {version!r}\n",
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
        ),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: isaac-audio-sensors-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: cp312-cp312-manylinux_2_28_x86_64\n"
        ),
        f"{dist_info}/top_level.txt": f"{top_level}\n",
    }
    if name == "cffi":
        files["_cffi_backend.py"] = "BACKEND = 'synthetic'\n"
        files[f"{dist_info}/top_level.txt"] = "_cffi_backend\ncffi\n"
    elif name == "soundfile":
        files["licensing/license_notes.md"] = "data-only license notes\n"
        files[f"{dist_info}/top_level.txt"] = "licensing\nsoundfile\n"
    record_name = f"{dist_info}/RECORD"
    record = io.StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for filename, content in sorted(files.items()):
        payload = content.encode()
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
        writer.writerow(
            (filename, f"sha256={digest.decode().rstrip('=')}", len(payload))
        )
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, content)


def _write_typing_extensions_host(root: Path) -> Path:
    root.mkdir()
    module = root / "typing_extensions.py"
    module.write_text(
        "# Synthetic metadata-version-only host module.\n", encoding="utf-8"
    )
    dist_info = root / "typing_extensions-4.12.2.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        "Name: typing_extensions\n"
        "Version: 4.12.2\n",
        encoding="utf-8",
    )
    return module


def _fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    wheelhouse = repo / "wheelhouse"
    pack_dir = repo / "packs" / "acoustics"
    scripts_dir = repo / "scripts"
    wheelhouse.mkdir(parents=True)
    pack_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    (repo / "pyproject.toml").write_text(
        f"[project]\nname='synthetic-pack'\nversion='{VERSION}'\n",
        encoding="utf-8",
    )
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "scripts" / "install_pack.py",
        scripts_dir / "install_pack.py",
    )
    rows = []
    lock_lines = [
        "# NumPy is host-owned and deliberately absent from this lock.\n"
    ]
    for name, version, filename, module_path in WHEELS:
        path = wheelhouse / filename
        _write_wheel(path, name=name, version=version, module_path=module_path)
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append((name, version, filename, sha256))
        lock_lines.append(
            f"{name}=={version} --hash=sha256:{sha256}\n"
        )
    (pack_dir / "requirements.lock").write_text(
        "".join(lock_lines), encoding="utf-8"
    )
    declaration = [
        "[pack]",
        'pack_id = "acoustics-l2l3"',
        f'pack_version = "{VERSION}"',
        f'artifact_name = "{ARTIFACT}"',
        'requirements_lock = "requirements.lock"',
        'numpy_compatibility = ">=2.0,<2.8"',
        "",
        "[target]",
        'python_version = "3.12"',
        'abi = "cp312"',
        'os = "linux"',
        'arch = "x86_64"',
        "",
        "[[host_requirements]]",
        'name = "numpy"',
        f'version = "{np.__version__}"',
        'reason = "host-owned test NumPy"',
        "",
        "[[host_requirements]]",
        'name = "typing_extensions"',
        'version = "4.12.2"',
        'reason = "host-owned test typing_extensions"',
        "",
    ]
    for name, version, filename, sha256 in rows:
        declaration.extend(
            (
                "[[pack_distributions]]",
                f'name = "{name}"',
                f'version = "{version}"',
                f'wheel = "{filename}"',
                f'sha256 = "{sha256}"',
                "",
            )
        )
    for capability_id, kind, module, format_name in (
        ("room_acoustics", "backend", "pyroomacoustics", None),
        ("room_acoustics_srp", "backend", "pyroomacoustics", None),
        ("waveform_export_wav", "waveform_export", "soundfile", "WAV"),
        ("waveform_export_flac", "waveform_export", "soundfile", "FLAC"),
    ):
        declaration.extend(
            (
                "[[capabilities]]",
                f'id = "{capability_id}"',
                f'kind = "{kind}"',
                'fidelity_level = "L2"',
                f'modules = ["{module}"]',
            )
        )
        if format_name is not None:
            declaration.append(f'format = "{format_name}"')
        declaration.append("")
    (pack_dir / "pack.toml").write_text(
        "\n".join(declaration), encoding="utf-8"
    )
    return repo, wheelhouse


def _build(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo, wheelhouse = _fixture_repo(tmp_path)
    output = tmp_path / "out"
    result = build_acoustic_pack(
        repo_root=repo,
        wheelhouse=wheelhouse,
        output_dir=output,
        source_revision="test-revision",
        verify_source=False,
    )
    return repo, wheelhouse, result.archive_path


def _rewrite_tar(
    source: Path,
    destination: Path,
    *,
    replacements: dict[str, bytes] | None = None,
    additions: dict[str, bytes] | None = None,
) -> None:
    replacements = replacements or {}
    additions = additions or {}
    payloads: dict[str, bytes] = {}
    with tarfile.open(source, "r:gz") as archive:
        for member in archive.getmembers():
            stream = archive.extractfile(member)
            assert stream is not None
            payloads[member.name] = stream.read()
    payloads.update(replacements)
    payloads.update(additions)
    with tarfile.open(destination, "w:gz") as archive:
        for name, payload in sorted(payloads.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _tar_json(path: Path, member_name: str) -> dict[str, object]:
    with tarfile.open(path, "r:gz") as archive:
        stream = archive.extractfile(member_name)
        assert stream is not None
        value = json.loads(stream.read())
    assert isinstance(value, dict)
    return value


def test_release_lock_contains_exactly_five_wheels_and_no_host_requirements():
    lock = Path("packs/acoustics/requirements.lock").read_text(encoding="utf-8")
    expected = {
        "pyroomacoustics==0.10.1": (
            "c1b1077cfcafed9775d1b826dbbaf25fb4090aa95d21e9bc6dac795f88e8875c"
        ),
        "scipy==1.18.0": (
            "1f55797419e16e7f30cf88ffb3113ce0467f00cfe3f70d5c281730b21769bfc2"
        ),
        "soundfile==0.14.0": (
            "1e38bac1853412871318e82a1ba69a8be677619b56025bbfcccdb41b6cafe82d"
        ),
        "cffi==2.1.0": (
            "1e9f50d192a3e525b15a75ab5114e442d83d657b7ec29182a991bc9a88fd3a66"
        ),
        "pycparser==3.0": (
            "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992"
        ),
    }
    for requirement, sha256 in expected.items():
        assert f"{requirement} --hash=sha256:{sha256}" in lock
    assert "numpy==" not in lock
    assert "typing_extensions==" not in lock


@pytest.mark.parametrize("failure", ["missing", "extra", "hash", "host"])
def test_builder_rejects_invalid_wheelhouse(tmp_path, failure):
    repo, wheelhouse = _fixture_repo(tmp_path)
    if failure == "missing":
        (wheelhouse / WHEELS[0][2]).unlink()
    elif failure == "extra":
        (wheelhouse / "extra.whl").write_bytes(b"extra")
    elif failure == "hash":
        with (wheelhouse / WHEELS[0][2]).open("ab") as stream:
            stream.write(b"tamper")
    else:
        (wheelhouse / "typing_extensions-4.12.2-py3-none-any.whl").write_bytes(
            b"x"
        )
    with pytest.raises(
        ValueError, match="missing|extra|hash mismatch|host requirement"
    ):
        build_acoustic_pack(
            repo_root=repo,
            wheelhouse=wheelhouse,
            output_dir=tmp_path / "out",
            source_revision="test-revision",
            verify_source=False,
        )


def test_builder_is_byte_deterministic_and_audit_accepts(tmp_path):
    repo, wheelhouse = _fixture_repo(tmp_path)
    first = build_acoustic_pack(
        repo_root=repo,
        wheelhouse=wheelhouse,
        output_dir=tmp_path / "first",
        source_revision="test-revision",
        verify_source=False,
    )
    second = build_acoustic_pack(
        repo_root=repo,
        wheelhouse=wheelhouse,
        output_dir=tmp_path / "second",
        source_revision="test-revision",
        verify_source=False,
    )
    assert first.archive_path.read_bytes() == second.archive_path.read_bytes()
    result = audit_acoustic_pack(
        first.archive_path,
        repo_root=repo,
        skip_revision_check=True,
    )
    assert result.findings == ()
    manifest = _tar_json(first.archive_path, "pack_manifest.json")
    distributions = manifest["pack_distributions"]
    assert isinstance(distributions, list)
    cffi = next(item for item in distributions if item["name"] == "cffi")
    assert cffi["top_level_imports"] == ["_cffi_backend", "cffi"]
    assert "_cffi_backend.py" in cffi["installed_files"]
    assert all(cffi["installed_files"].values())
    soundfile = next(
        item for item in distributions if item["name"] == "soundfile"
    )
    assert soundfile["top_level_imports"] == ["soundfile"]
    assert "licensing/license_notes.md" in soundfile["installed_files"]


@pytest.mark.parametrize("failure", ["extra", "private", "host", "wheel_hash"])
def test_audit_rejects_archive_hygiene_and_hash_failures(tmp_path, failure):
    repo, _wheelhouse, archive = _build(tmp_path)
    broken = tmp_path / ARTIFACT
    additions: dict[str, bytes] = {}
    replacements: dict[str, bytes] = {}
    if failure == "extra":
        additions["outputs/cache.txt"] = b"generated"
    elif failure == "private":
        replacements["install_pack.py"] = b"# /home/" + b"pacquadr/private\n"
    elif failure == "host":
        additions["wheels/typing_extensions-4.12.2-py3-none-any.whl"] = b"host"
    else:
        replacements[f"wheels/{WHEELS[0][2]}"] = b"tampered-wheel"
    _rewrite_tar(
        archive, broken, replacements=replacements, additions=additions
    )
    result = audit_acoustic_pack(broken, repo_root=repo)
    assert result.findings
    assert any(
        token in "\n".join(result.findings)
        for token in ("member set", "private", "host requirement", "hash mismatch")
    )


@pytest.mark.parametrize("failure", ["unsafe", "manifest", "tag", "lock"])
def test_audit_rejects_contract_and_canonical_source_failures(tmp_path, failure):
    repo, _wheelhouse, archive = _build(tmp_path)
    broken = tmp_path / ARTIFACT
    additions: dict[str, bytes] = {}
    replacements: dict[str, bytes] = {}
    expected = ""
    if failure == "unsafe":
        additions["../escape.txt"] = b"escape"
        expected = "unsafe archive path"
    elif failure == "lock":
        replacements["requirements.lock"] = b"tampered==1\n"
        expected = "differs from canonical source"
    else:
        manifest = _tar_json(archive, "pack_manifest.json")
        if failure == "manifest":
            del manifest["host_requirements"]
            expected = "required fields missing"
        else:
            distributions = manifest["pack_distributions"]
            assert isinstance(distributions, list)
            first = distributions[0]
            assert isinstance(first, dict)
            first["wheel"] = str(first["wheel"]).replace("cp312", "cp311")
            expected = "must use cp312-cp312 tags"
        replacements["pack_manifest.json"] = (
            json.dumps(manifest, sort_keys=True) + "\n"
        ).encode()
    _rewrite_tar(
        archive, broken, replacements=replacements, additions=additions
    )
    findings = audit_acoustic_pack(broken, repo_root=repo).findings
    assert expected in "\n".join(findings)


def test_audit_version_check_can_be_skipped_for_foreign_revision(tmp_path):
    repo, _wheelhouse, archive = _build(tmp_path)
    broken = tmp_path / ARTIFACT
    manifest = _tar_json(archive, "pack_manifest.json")
    manifest["sensor_package_version"] = "9.9.9"
    _rewrite_tar(
        archive,
        broken,
        replacements={
            "pack_manifest.json": (
                json.dumps(manifest, sort_keys=True) + "\n"
            ).encode()
        },
    )
    strict = audit_acoustic_pack(broken, repo_root=repo)
    foreign = audit_acoustic_pack(
        broken,
        repo_root=repo,
        skip_version_check=True,
        skip_revision_check=True,
    )
    assert "sensor_package_version" in "\n".join(strict.findings)
    assert foreign.findings == ()


def test_offline_installer_is_atomic_and_refuses_overwrite(tmp_path, monkeypatch):
    repo, _wheelhouse, archive = _build(tmp_path)
    host_module = _write_typing_extensions_host(tmp_path / "host-runtime")
    monkeypatch.syspath_prepend(str(host_module.parent))
    synthetic_module = types.ModuleType("typing_extensions")
    synthetic_module.__file__ = str(host_module)
    monkeypatch.setitem(sys.modules, "typing_extensions", synthetic_module)
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(archive, "r:gz") as pack:
        pack.extractall(unpacked, filter="data")
    root = tmp_path / "packs-root"
    command = [sys.executable, str(unpacked / "install_pack.py"), "--root", str(root)]
    env = os.environ.copy()
    prior_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(host_module.parent)
    if prior_pythonpath:
        env["PYTHONPATH"] += os.pathsep + prior_pythonpath
    first = subprocess.run(
        command, check=False, capture_output=True, text=True, env=env
    )
    assert first.returncode == 0, first.stderr
    final = root / "acoustics-l2l3" / VERSION
    assert (final / "pack_manifest.json").is_file()
    assert not list((root / "acoustics-l2l3").glob(".staging-*"))
    assert discover_pack_installs(root) == (final.resolve(),)

    second = subprocess.run(
        command, check=False, capture_output=True, text=True, env=env
    )
    assert second.returncode != 0
    assert "already exists" in second.stderr
    assert discover_pack_installs(root) == (final.resolve(),)
    assert audit_acoustic_pack(
        archive, repo_root=repo, skip_revision_check=True
    ).findings == ()


def test_installer_hash_mismatch_never_creates_selectable_root(tmp_path):
    _repo, _wheelhouse, archive = _build(tmp_path)
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(archive, "r:gz") as pack:
        pack.extractall(unpacked, filter="data")
    with (unpacked / "wheels" / WHEELS[0][2]).open("ab") as stream:
        stream.write(b"tampered")
    root = tmp_path / "packs-root"
    result = subprocess.run(
        [sys.executable, str(unpacked / "install_pack.py"), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr
    assert discover_pack_installs(root) == ()
    assert not list(root.rglob(".staging-*")) if root.exists() else True


def test_partial_and_staging_directories_are_never_discovered(tmp_path):
    root = tmp_path / "packs-root"
    pack_parent = root / "acoustics-l2l3"
    (pack_parent / ".staging-123").mkdir(parents=True)
    (pack_parent / "missing-manifest").mkdir()
    invalid = pack_parent / "1.10.0"
    invalid.mkdir()
    (invalid / "pack_manifest.json").write_text(
        json.dumps({"schema": "ias.acoustic_pack_manifest.v1"}),
        encoding="utf-8",
    )
    assert discover_pack_installs(root) == ()
