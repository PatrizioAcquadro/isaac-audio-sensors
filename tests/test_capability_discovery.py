"""Capability provenance and pack-activation tests."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core import packs
from isaac_audio_sensors.core.capabilities import discover_capabilities
from isaac_audio_sensors.core.packs import discover_pack_installs

VERSION = "1.8.0"
ARTIFACT = (
    "isaac_audio_sensors_acoustic_pack-l2l3-"
    f"{VERSION}-linux_x86_64-cp312.tar.gz"
)
PACK_DISTRIBUTIONS = (
    ("pyroomacoustics", "0.10.1"),
    ("scipy", "1.18.0"),
    ("soundfile", "0.14.0"),
    ("cffi", "2.1.0"),
    ("pycparser", "3.0"),
)


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


def _synthetic_pack(root: Path) -> Path:
    pack_root = root / "acoustics-l2l3" / VERSION
    pack_root.mkdir(parents=True)
    distributions = []
    for name, version in PACK_DISTRIBUTIONS:
        module_name = name.replace("-", "_")
        if name == "soundfile":
            (pack_root / "soundfile.py").write_text(
                f"__version__ = {version!r}\n", encoding="utf-8"
            )
        else:
            module_dir = pack_root / module_name
            module_dir.mkdir()
            (module_dir / "__init__.py").write_text(
                f"__version__ = {version!r}\n", encoding="utf-8"
            )
        dist_info = pack_root / f"{module_name}-{version}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\n"
            f"Name: {name}\n"
            f"Version: {version}\n",
            encoding="utf-8",
        )
        distributions.append(
            {
                "name": name,
                "version": version,
                "wheel": f"{name}-{version}-synthetic.whl",
                "sha256": "a" * 64,
            }
        )
    capabilities = [
        {
            "id": "room_acoustics",
            "kind": "backend",
            "fidelity_level": "L2",
            "modules": ["pyroomacoustics"],
        },
        {
            "id": "room_acoustics_srp",
            "kind": "backend",
            "fidelity_level": "L2",
            "modules": ["pyroomacoustics"],
        },
        {
            "id": "waveform_export_wav",
            "kind": "waveform_export",
            "fidelity_level": "L2",
            "format": "WAV",
            "modules": ["soundfile"],
        },
        {
            "id": "waveform_export_flac",
            "kind": "waveform_export",
            "fidelity_level": "L2",
            "format": "FLAC",
            "modules": ["soundfile"],
        },
    ]
    manifest = {
        "schema": "ias.acoustic_pack_manifest.v1",
        "pack_id": "acoustics-l2l3",
        "pack_version": VERSION,
        "sensor_package_version": VERSION,
        "python_version": "3.12",
        "abi": "cp312",
        "os": "linux",
        "arch": "x86_64",
        "host_requirements": [
            {
                "name": "numpy",
                "version": np.__version__,
                "reason": "host-owned test NumPy",
            },
            {
                "name": "typing_extensions",
                "version": "4.12.2",
                "reason": "host-owned test typing_extensions",
            },
        ],
        "numpy_compatibility": ">=2.0,<2.8",
        "pack_distributions": distributions,
        "capabilities": capabilities,
        "build_provenance": {
            "git_revision": "synthetic-test",
            "build_tool_version": "1",
        },
    }
    (pack_root / "pack_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return pack_root


def _run_script(script: str, *args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_base_report_stays_healthy_and_missing_pack_is_actionable():
    report = discover_capabilities()

    assert report.get("L0").status == "available"
    assert report.get("L0").origin == "base"
    assert report.get("L1").status == "available"
    assert report.get("L1").origin == "base"
    assert report.get("L2").status == "unavailable"
    assert report.get("room_acoustics").origin == "absent"
    assert ARTIFACT in report.get("L2").actionable_message
    assert ARTIFACT in report.get("waveform_export_wav").actionable_message
    payload = report.to_dict()
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_external_optional_module_is_never_mislabeled_as_pack(monkeypatch, tmp_path):
    external = tmp_path / "external" / "pyroomacoustics" / "__init__.py"
    external.parent.mkdir(parents=True)
    external.write_text("# external synthetic module\n", encoding="utf-8")
    module = types.ModuleType("pyroomacoustics")
    module.__file__ = str(external)
    monkeypatch.setitem(sys.modules, "pyroomacoustics", module)

    report = discover_capabilities()

    assert report.get("room_acoustics").status == "available"
    assert report.get("room_acoustics").origin == "external-unmanaged"
    assert report.get("room_acoustics_srp").origin == "external-unmanaged"
    assert not report.get("room_acoustics").origin.startswith("pack:")


def test_base_import_then_activation_keeps_numpy_host_owned(tmp_path):
    pack_root = _synthetic_pack(tmp_path / "packs")
    host_module = _write_typing_extensions_host(tmp_path / "host-runtime")
    result = _run_script(
        """
        import json, pathlib, sys
        sys.path.insert(0, str(pathlib.Path(sys.argv[2]).resolve()))
        import isaac_audio_sensors
        import numpy
        from isaac_audio_sensors.core.capabilities import discover_capabilities
        from isaac_audio_sensors.core.packs import activate_pack

        root = pathlib.Path(sys.argv[1]).resolve()
        before = pathlib.Path(numpy.__file__).resolve()
        activate_pack(root)
        report = discover_capabilities()
        after = pathlib.Path(numpy.__file__).resolve()
        print(json.dumps({
            "before": str(before),
            "after": str(after),
            "numpy_under_root": root in after.parents,
            "l0": report.get("L0").origin,
            "l2": report.get("L2").origin,
            "room": report.get("room_acoustics").origin,
            "wav": report.get("waveform_export_wav").origin,
            "active_pack": report.active_pack,
        }, sort_keys=True))
        """,
        pack_root,
        host_module.parent,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == payload["after"]
    assert payload["numpy_under_root"] is False
    assert payload["l0"] == "base"
    assert payload["l2"] == "pack:acoustics-l2l3@1.8.0"
    assert payload["room"] == "pack:acoustics-l2l3@1.8.0"
    assert payload["wav"] == "pack:acoustics-l2l3@1.8.0"
    assert payload["active_pack"] == "acoustics-l2l3@1.8.0"


def test_conflicting_preloaded_pack_module_fails_closed(tmp_path):
    pack_root = _synthetic_pack(tmp_path / "packs")
    host_module = _write_typing_extensions_host(tmp_path / "host-runtime")
    external_dir = tmp_path / "external"
    module_dir = external_dir / "pyroomacoustics"
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text(
        "__version__ = '0.10.1'\n", encoding="utf-8"
    )
    result = _run_script(
        """
        import pathlib, sys
        root = pathlib.Path(sys.argv[1]).resolve()
        external = pathlib.Path(sys.argv[2]).resolve()
        host = pathlib.Path(sys.argv[3]).resolve()
        sys.path.insert(0, str(host))
        sys.path.insert(0, str(external))
        import pyroomacoustics
        from isaac_audio_sensors.core.packs import PackActivationError, activate_pack
        try:
            activate_pack(root)
        except PackActivationError as exc:
            assert "provenance conflict" in str(exc)
            assert "pyroomacoustics" in str(exc)
            assert str(root) not in sys.path
            print("rejected")
        else:
            raise AssertionError("activation unexpectedly succeeded")
        """,
        pack_root,
        external_dir,
        host_module.parent,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


def test_host_requirement_version_uses_metadata_without_module_attribute(
    tmp_path, monkeypatch
):
    pack_root = tmp_path / "pack-root"
    pack_root.mkdir()
    host_module = _write_typing_extensions_host(tmp_path / "host-runtime")
    monkeypatch.syspath_prepend(str(host_module.parent))
    synthetic_module = types.ModuleType("typing_extensions")
    synthetic_module.__file__ = str(host_module)
    monkeypatch.setitem(sys.modules, "typing_extensions", synthetic_module)

    packs._validate_host_requirements(
        pack_root,
        {
            "host_requirements": [
                {
                    "name": "typing_extensions",
                    "version": "4.12.2",
                    "reason": "metadata-only test host",
                }
            ]
        },
    )

    assert not hasattr(synthetic_module, "__version__")


def test_interrupted_partial_install_is_not_selectable(tmp_path):
    root = tmp_path / "packs"
    pack_dir = root / "acoustics-l2l3"
    (pack_dir / ".staging-999").mkdir(parents=True)
    (pack_dir / "1.8.0").mkdir()
    broken = pack_dir / "hash-mismatch"
    broken.mkdir()
    (broken / "pack_manifest.json").write_text(
        json.dumps(
            {
                "schema": "ias.acoustic_pack_manifest.v1",
                "pack_id": "acoustics-l2l3",
                "pack_version": "hash-mismatch",
            }
        ),
        encoding="utf-8",
    )
    assert discover_pack_installs(root) == ()
