"""Canonical Kit-extension build, audit, and startup tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    script_path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build(tmp_path: Path):
    builder = _load_script("build_kit_extension")
    output_dir = tmp_path / "kit"
    result = builder.build_kit_extension(
        repo_root=REPO_ROOT,
        output_dir=output_dir,
        source_revision="test-revision",
    )
    return builder, result


def _extract(result, destination: Path) -> Path:
    with zipfile.ZipFile(result.archive_path) as archive:
        archive.extractall(destination)
    return destination


def _clean_subprocess(
    code: str,
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _startup_code(extension_root: Path) -> str:
    return f"""
import json
import pathlib
import sys
sys.path.insert(0, {str(extension_root)!r})
import isaac_audio_sensors_omni
import isaac_audio_sensors
extension_root = pathlib.Path({str(extension_root)!r}).resolve()
vendor_root = (extension_root / "_vendor").resolve()
package_file = pathlib.Path(isaac_audio_sensors.__file__).resolve()
package_file.relative_to(vendor_root)
metadata = json.loads((vendor_root / "VENDORED.json").read_text())
assert isaac_audio_sensors.__version__ == metadata["version"]
print(package_file)
"""


def _expect_runtime_error(extension_root: Path) -> None:
    result = _clean_subprocess(
        f"""
import sys
sys.path.insert(0, {str(extension_root)!r})
try:
    import isaac_audio_sensors_omni
except RuntimeError as exc:
    print(exc)
else:
    raise AssertionError("expected RuntimeError")
""",
        cwd=extension_root.parent,
    )
    assert result.stdout.strip()


def test_build_produces_deterministic_staging_zip_checksums_and_clean_audit(
    tmp_path,
):
    builder, result = _build(tmp_path)
    audit = _load_script("audit_kit_archive")

    assert result.staging_dir.is_dir()
    assert result.archive_path.is_file()
    assert result.checksums_path.is_file()
    assert not list(result.staging_dir.rglob("DEVELOPMENT_MODE.json"))
    metadata = json.loads(
        (result.staging_dir / "_vendor/VENDORED.json").read_text(encoding="utf-8")
    )
    assert metadata["mode"] == "packaged"
    assert metadata["tree_sha256"] == builder.hash_source_tree(
        REPO_ROOT / "src/isaac_audio_sensors"
    )
    checksum = hashlib.sha256(result.archive_path.read_bytes()).hexdigest()
    assert result.checksums_path.read_text(encoding="utf-8") == (
        f"{checksum}  {result.archive_path.name}\n"
    )
    clean = audit.audit_kit_archive(result.archive_path, repo_root=REPO_ROOT)
    assert clean.findings == ()

    first_bytes = result.archive_path.read_bytes()
    rebuilt = builder.build_kit_extension(
        repo_root=REPO_ROOT,
        output_dir=result.archive_path.parent,
        source_revision="test-revision",
    )
    assert rebuilt.archive_path.read_bytes() == first_bytes


def test_packaged_startup_uses_only_vendored_source(tmp_path):
    _, result = _build(tmp_path)
    extension_root = _extract(result, tmp_path / "extracted")
    process = _clean_subprocess(
        _startup_code(extension_root),
        cwd=tmp_path,
    )

    package_file = Path(process.stdout.strip()).resolve()
    package_file.relative_to((extension_root / "_vendor").resolve())
    repo_src = (REPO_ROOT / "src").resolve()
    assert repo_src not in package_file.parents


def test_packaged_startup_never_adds_checkout_src(tmp_path):
    _, result = _build(tmp_path)
    extension_root = _extract(result, tmp_path / "extracted")
    repo_src = (REPO_ROOT / "src").resolve()
    process = _clean_subprocess(
        f"""
import pathlib
import sys
repo_src = pathlib.Path({str(repo_src)!r}).resolve()
sys.path[:] = [
    item
    for item in sys.path
    if pathlib.Path(item or ".").resolve() != repo_src
]
sys.path.insert(0, {str(extension_root)!r})
import isaac_audio_sensors_omni
import isaac_audio_sensors
resolved_paths = []
for item in sys.path:
    try:
        resolved_paths.append(pathlib.Path(item or ".").resolve())
    except OSError:
        pass
assert repo_src not in resolved_paths
package_file = pathlib.Path(isaac_audio_sensors.__file__).resolve()
assert repo_src not in package_file.parents
""",
        cwd=tmp_path,
    )
    assert process.returncode == 0


@pytest.mark.parametrize("failure", ["missing_vendor", "corrupt_metadata", "ambiguous"])
def test_packaged_startup_fails_loudly_on_invalid_mode_state(tmp_path, failure):
    _, result = _build(tmp_path)
    extension_root = _extract(result, tmp_path / "extracted")
    if failure == "missing_vendor":
        shutil.rmtree(extension_root / "_vendor/isaac_audio_sensors")
    elif failure == "corrupt_metadata":
        (extension_root / "_vendor/VENDORED.json").write_text(
            "{not-json\n", encoding="utf-8"
        )
    else:
        (extension_root / "isaac_audio_sensors_omni/DEVELOPMENT_MODE.json").write_text(
            json.dumps({"mode": "developer"}), encoding="utf-8"
        )
    _expect_runtime_error(extension_root)


def test_corrupt_packaged_metadata_never_imports_conflicting_global_wheel(tmp_path):
    _, result = _build(tmp_path)
    extension_root = _extract(result, tmp_path / "extracted")
    (extension_root / "_vendor/VENDORED.json").write_text(
        "{corrupt\n", encoding="utf-8"
    )
    fake_root = tmp_path / "site-packages"
    fake_package = fake_root / "isaac_audio_sensors"
    fake_package.mkdir(parents=True)
    marker = tmp_path / "fake-imported"
    (fake_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "__version__ = '9.9.9'\n",
        encoding="utf-8",
    )

    process = _clean_subprocess(
        f"""
import pathlib
import sys
sys.path[:0] = [{str(extension_root)!r}, {str(fake_root)!r}]
try:
    import isaac_audio_sensors_omni
except RuntimeError:
    pass
else:
    raise AssertionError("expected RuntimeError")
assert "isaac_audio_sensors" not in sys.modules
assert not pathlib.Path({str(marker)!r}).exists()
""",
        cwd=tmp_path,
    )
    assert process.returncode == 0
    assert not marker.exists()


def test_developer_mode_preserves_checkout_src_fallback(tmp_path):
    extension_dir = REPO_ROOT / "exts/isaac_audio_sensors.omni"
    repo_src = (REPO_ROOT / "src").resolve()
    process = _clean_subprocess(
        f"""
import pathlib
import sys
sys.path.insert(0, {str(extension_dir)!r})
import isaac_audio_sensors_omni
import isaac_audio_sensors
package_file = pathlib.Path(isaac_audio_sensors.__file__).resolve()
package_file.relative_to(pathlib.Path({str(repo_src)!r}))
assert not (pathlib.Path({str(extension_dir)!r}) / "_vendor").exists()
print(package_file)
""",
        cwd=tmp_path,
    )
    assert Path(process.stdout.strip()).resolve().is_relative_to(repo_src)


def test_version_sync_cli_and_synthetic_disagreement(tmp_path):
    script = REPO_ROOT / "scripts/check_version_sync.py"
    current = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert current.returncode == 0, current.stderr

    synthetic = tmp_path / "repo"
    surfaces = (
        "pyproject.toml",
        "Makefile",
        "README.md",
        "CITATION.cff",
        "CHANGELOG.md",
        "docs/versioning.md",
        "src/isaac_audio_sensors/__init__.py",
        "exts/isaac_audio_sensors.omni/config/extension.toml",
        "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md",
        "scripts/audit_distribution.py",
        "tests/test_isaac_audio_core.py",
        "tests/test_distribution_audit.py",
    )
    for relative in surfaces:
        source = REPO_ROOT / relative
        destination = synthetic / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    makefile = synthetic / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace(
            "EXPECTED_VERSION ?= 1.8.0", "EXPECTED_VERSION ?= 9.9.9"
        ),
        encoding="utf-8",
    )
    mismatch = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(synthetic)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatch.returncode != 0
    assert "Makefile EXPECTED_VERSION default" in mismatch.stderr


def test_archive_audit_rejects_vendored_tree_tampering(tmp_path):
    _, result = _build(tmp_path)
    audit = _load_script("audit_kit_archive")
    tampered = tmp_path / result.archive_path.name
    with (
        zipfile.ZipFile(result.archive_path) as source,
        zipfile.ZipFile(tampered, "w") as destination,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "_vendor/isaac_audio_sensors/core/constants.py":
                content += b"\n# tampered\n"
            destination.writestr(info, content)

    result = audit.audit_kit_archive(tampered, repo_root=REPO_ROOT)

    assert any("vendored tree hash mismatch" in item for item in result.findings)
    assert any("vendored tree drift" in item for item in result.findings)
