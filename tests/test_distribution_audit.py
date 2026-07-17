"""Tests for built-archive release hygiene auditing."""

from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path

RELEASE_VERSION = "1.9.0"


def _load_audit_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "audit_distribution.py"
    )
    spec = importlib.util.spec_from_file_location("audit_distribution", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_distribution_audit_accepts_required_sdist_and_wheel(tmp_path):
    audit = _load_audit_module()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _write_sdist(
        dist_dir / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz",
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n\n## 0." + "1.0 - historical\n",
            "LICENSE": "Apache-2.0\n",
            "NOTICE": "notice\n",
            "CITATION.cff": f'version: "{RELEASE_VERSION}"\n',
            "CODE_OF_CONDUCT.md": "# Code of Conduct\n",
            "CONTRIBUTING.md": "# Contributing\n",
            "SECURITY.md": "# Security\n",
            "MANIFEST.in": "include README.md\n",
            "pyproject.toml": (
                "[project]\n"
                "name = 'isaac-audio-sensors'\n"
                f"version = '{RELEASE_VERSION}'\n"
            ),
            "configs/isaac_audio_sensors_demo.toml": "[scene]\n",
            "packs/acoustics/pack.toml": "[pack]\n",
            "packs/acoustics/requirements.lock": "fake==1 --hash=sha256:abc\n",
            "docs/acoustic_fidelity.md": "# Acoustic Fidelity Ladder\n",
            "docs/api_freeze_0_1.md": _api_freeze_doc_text(),
            "docs/api_reference.md": "# API Reference\n",
            "docs/final_sensor_development_plan.md": (
                "# Final Sensor Development Plan\n\n"
                "See [V1 Public Scope](v1_scope.md).\n"
            ),
            "docs/installation.md": "# Installation\n",
            "docs/open_source_release_checklist.md": "# Checklist\n",
            "docs/quickstart.md": "# Quickstart\n",
            "docs/validation.md": "# Validation\n",
            "docs/versioning.md": f"package version: `{RELEASE_VERSION}`\n",
            "docs/v1_scope.md": _scope_doc_text(),
            "docs/schemas/audio_sensor_frame.v1.schema.json": "{}\n",
            "docs/schemas/audio_dataset_manifest.v1.schema.json": "{}\n",
            "docs/schemas/audio_calibration_profile.v1.schema.json": "{}\n",
            "examples/README.md": "# Examples\n",
            "examples/manifests/README.md": "# Manifest Examples\n",
            "examples/manifests/minimal_manifest.v1.json": "{}\n",
            "examples/manifests/multi_episode_manifest.v1.json": "{}\n",
            "examples/manifests/invalid/invalid_id_whitespace.json": "{}\n",
            "examples/manifests/invalid/invalid_units_position.json": "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_frame_range_nonmonotonic.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_timestamps_nonmonotonic.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_channel_order_duplicate.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_asset_checksum_format.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/invalid_checksum_format.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_complete_manifest_incomplete_shard.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_completion_state_unknown.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/invalid_coordinate_frame.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/invalid_split_unknown_group.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/"
                "invalid_runtime_profile_unknown.json"
            ): "{}\n",
            (
                "examples/manifests/invalid/invalid_timestamp_negative.json"
            ): "{}\n",
            "examples/manifests/invalid/invalid_path_absolute.json": "{}\n",
            (
                "examples/manifests/invalid/invalid_path_parent_traversal.json"
            ): "{}\n",
            "examples/calibration/README.md": "# Calibration Examples\n",
            (
                "examples/calibration/respeaker_xvf3800_nominal.v1.json"
            ): "{}\n",
            "examples/calibration/invalid/invalid_id_whitespace.json": "{}\n",
            "examples/calibration/invalid/invalid_units_gain.json": "{}\n",
            (
                "examples/calibration/invalid/invalid_coordinate_frame.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/invalid_timestamp_not_utc.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/"
                "invalid_channel_order_duplicate.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/invalid_checksum_format.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/invalid_schema_version.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/"
                "invalid_unmeasured_has_value.json"
            ): "{}\n",
            (
                "examples/calibration/invalid/invalid_path_parent_traversal.json"
            ): "{}\n",
            "examples/calibration/invalid/invalid_sample_rate.json": "{}\n",
            "examples/core/single_source_bearing.py": "print('example')\n",
            "examples/traces/ambiguity_frame.v1.json": "{}\n",
            "examples/traces/diagnostics_provenance_sequence.v1.ndjson": "{}\n",
            "examples/traces/minimal_frame.v1.json": "{}\n",
            "examples/traces/multi_detection_frame.v1.json": "{}\n",
            "exts/isaac_audio_sensors.omni/config/extension.toml": "[package]\n",
            "exts/isaac_audio_sensors.omni/data/icon.svg": "<svg></svg>\n",
            "exts/isaac_audio_sensors.omni/data/preview.png": "png\n",
            (
                "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md"
            ): "# Changelog\n",
            "exts/isaac_audio_sensors.omni/docs/README.md": "# Overview\n",
            (
                "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/"
                "DEVELOPMENT_MODE.json"
            ): '{"mode": "developer"}\n',
            "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py": "\n",
            "scripts/audit_kit_archive.py": "print('kit audit')\n",
            "scripts/audit_acoustic_pack.py": "print('pack audit')\n",
            "scripts/audit_distribution.py": "print('audit')\n",
            "scripts/build_acoustic_pack.py": "print('pack build')\n",
            "scripts/build_kit_extension.py": "print('kit build')\n",
            "scripts/check_version_sync.py": "print('version sync')\n",
            "scripts/regenerate_example_manifests.py": "print('regenerate')\n",
            "scripts/generate_live_evidence_report.py": "print('report')\n",
            "scripts/live_clean_install_gate.py": "print('clean gate')\n",
            "scripts/live_clean_install_probe.py": "print('clean probe')\n",
            "scripts/run_installed_consumer_gate.py": "print('consumer gate')\n",
            "scripts/live_isaac_sim_audio_smoke.py": "print('smoke')\n",
            "scripts/live_omniverse_extension_ux.py": "print('ux')\n",
            "scripts/install_pack.py": "print('pack install')\n",
            "src/isaac_audio_sensors/__init__.py": (
                f"__version__ = '{RELEASE_VERSION}'\n"
            ),
            "src/isaac_audio_sensors/__main__.py": "from .cli import main\n",
            "src/isaac_audio_sensors/cli.py": "def main(): return 0\n",
            "src/isaac_audio_sensors/core/fidelity.py": "LADDER = ()\n",
            "src/isaac_audio_sensors/core/capabilities.py": "\n",
            "src/isaac_audio_sensors/core/packs.py": "\n",
            "src/isaac_audio_sensors/core/dataset_manifest.py": "\n",
            "src/isaac_audio_sensors/core/calibration_profile.py": "\n",
            "src/isaac_audio_sensors/core/schema.py": "\n",
            "src/isaac_audio_sensors/core/types.py": "\n",
            "src/isaac_audio_sensors/core/plugins/__init__.py": "\n",
            "src/isaac_audio_sensors/core/plugins/adapters.py": "\n",
            "src/isaac_audio_sensors/core/plugins/declarations.py": "\n",
            "src/isaac_audio_sensors/core/plugins/protocols.py": "\n",
            "src/isaac_audio_sensors/core/plugins/registry.py": "\n",
            "src/isaac_audio_sensors/core/io/manifests.py": "\n",
            "src/isaac_audio_sensors/core/io/calibration.py": "\n",
            "src/isaac_audio_sensors/core/io/traces.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/__init__.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/controller.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/window.py": "\n",
            "src/isaac_audio_sensors/isaac/microphone_rig_profiles.py": "\n",
            "src/isaac_audio_sensors/isaac/replicator.py": "\n",
            "src/isaac_audio_sensors/isaac/sound_profiles.py": "\n",
            "tests/test_acoustic_fidelity.py": "def test_ladder():\n    assert True\n",
            "tests/test_acoustic_pack.py": "def test_pack():\n    assert True\n",
            "tests/test_capability_discovery.py": (
                "def test_capabilities():\n    assert True\n"
            ),
            "tests/test_isaac_audio_core.py": "def test_core():\n    assert True\n",
            "tests/test_dataset_manifest.py": "def test_manifest():\n    assert True\n",
            (
                "tests/test_calibration_profile.py"
            ): "def test_calibration():\n    assert True\n",
            "tests/test_runtime_profiles.py": "def test_profiles():\n    assert True\n",
            (
                "tests/test_live_evidence_report.py"
            ): "def test_report():\n    assert True\n",
            "tests/test_clean_install_harness.py": (
                "def test_clean_install():\n    assert True\n"
            ),
            "tests/test_v1_scope_docs.py": "def test_scope():\n    assert True\n",
        },
    )
    _write_wheel(
        dist_dir / f"isaac_audio_sensors-{RELEASE_VERSION}-py3-none-any.whl",
        {
            "isaac_audio_sensors/__init__.py": f"__version__ = '{RELEASE_VERSION}'\n",
            "isaac_audio_sensors/__main__.py": "from .cli import main\n",
            "isaac_audio_sensors/cli.py": "def main(): return 0\n",
            "isaac_audio_sensors/core/capabilities.py": "\n",
            "isaac_audio_sensors/core/packs.py": "\n",
            "isaac_audio_sensors/core/dataset_manifest.py": "\n",
            "isaac_audio_sensors/core/calibration_profile.py": "\n",
            "isaac_audio_sensors/core/schema.py": "\n",
            "isaac_audio_sensors/core/types.py": "\n",
            "isaac_audio_sensors/core/plugins/__init__.py": "\n",
            "isaac_audio_sensors/core/plugins/adapters.py": "\n",
            "isaac_audio_sensors/core/plugins/declarations.py": "\n",
            "isaac_audio_sensors/core/plugins/protocols.py": "\n",
            "isaac_audio_sensors/core/plugins/registry.py": "\n",
            "isaac_audio_sensors/core/io/manifests.py": "\n",
            "isaac_audio_sensors/core/io/calibration.py": "\n",
            "isaac_audio_sensors/core/io/traces.py": "\n",
            "isaac_audio_sensors/isaac/extension.py": "\n",
            "isaac_audio_sensors/isaac/extension_ui/__init__.py": "\n",
            "isaac_audio_sensors/isaac/extension_ui/controller.py": "\n",
            "isaac_audio_sensors/isaac/extension_ui/window.py": "\n",
            "isaac_audio_sensors/isaac/microphone_rig_profiles.py": "\n",
            "isaac_audio_sensors/isaac/replicator.py": "\n",
            "isaac_audio_sensors/isaac/sound_profiles.py": "\n",
            "isaac_audio_sensors/lab/audio_array_sensor.py": "\n",
            f"isaac_audio_sensors-{RELEASE_VERSION}.dist-info/METADATA": ("Name: x\n"),
            f"isaac_audio_sensors-{RELEASE_VERSION}.dist-info/entry_points.txt": "\n",
        },
    )

    audits = audit.audit_dist_dir(dist_dir)

    assert {item.kind for item in audits} == {"sdist", "wheel"}
    assert all(not item.findings for item in audits)


def test_distribution_audit_reports_forbidden_paths_and_content(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n\n## 0." + "1.0 - historical\n",
            "LICENSE": "Apache-2.0\n",
            "NOTICE": "notice\n",
            "CITATION.cff": f'version: "{RELEASE_VERSION}"\n',
            "CODE_OF_CONDUCT.md": "# Code of Conduct\n",
            "CONTRIBUTING.md": "# Contributing\n",
            "SECURITY.md": "# Security\n",
            "MANIFEST.in": "include README.md\n",
            "pyproject.toml": (
                "[project]\n"
                "name = 'isaac-audio-sensors'\n"
                f"version = '{RELEASE_VERSION}'\n"
            ),
            "configs/isaac_audio_sensors_demo.toml": "[scene]\n",
            "docs/acoustic_fidelity.md": "# Acoustic Fidelity Ladder\n",
            "docs/api_freeze_0_1.md": _api_freeze_doc_text(),
            "docs/api_reference.md": "# API Reference\n",
            "docs/final_sensor_development_plan.md": (
                "# Final Sensor Development Plan\n\n"
                "See [V1 Public Scope](v1_scope.md).\n"
            ),
            "docs/installation.md": "# Installation\n",
            "docs/open_source_release_checklist.md": "# Checklist\n",
            "docs/quickstart.md": "# Quickstart\n",
            "docs/validation.md": "# Validation\n",
            "docs/versioning.md": f"package version: `{RELEASE_VERSION}`\n",
            "docs/v1_scope.md": _scope_doc_text(),
            "docs/schemas/audio_sensor_frame.v1.schema.json": "{}\n",
            "examples/README.md": "# Examples\n",
            "examples/core/single_source_bearing.py": "print('example')\n",
            "examples/traces/ambiguity_frame.v1.json": "{}\n",
            "examples/traces/diagnostics_provenance_sequence.v1.ndjson": "{}\n",
            "examples/traces/minimal_frame.v1.json": "{}\n",
            "examples/traces/multi_detection_frame.v1.json": "{}\n",
            "exts/isaac_audio_sensors.omni/config/extension.toml": "[package]\n",
            "exts/isaac_audio_sensors.omni/data/icon.svg": "<svg></svg>\n",
            "exts/isaac_audio_sensors.omni/data/preview.png": "png\n",
            (
                "exts/isaac_audio_sensors.omni/docs/CHANGELOG.md"
            ): "# Changelog\n",
            "exts/isaac_audio_sensors.omni/docs/README.md": "# Overview\n",
            "exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py": "\n",
            "scripts/audit_distribution.py": "print('audit')\n",
            "scripts/generate_live_evidence_report.py": "print('report')\n",
            "scripts/live_clean_install_gate.py": "print('clean gate')\n",
            "scripts/live_clean_install_probe.py": "print('clean probe')\n",
            "scripts/live_isaac_sim_audio_smoke.py": "print('smoke')\n",
            "scripts/live_omniverse_extension_ux.py": "print('ux')\n",
            "src/isaac_audio_sensors/__init__.py": (
                f"__version__ = '{RELEASE_VERSION}'\n"
            ),
            "src/isaac_audio_sensors/__main__.py": "from .cli import main\n",
            "src/isaac_audio_sensors/cli.py": "def main(): return 0\n",
            "src/isaac_audio_sensors/core/fidelity.py": "LADDER = ()\n",
            "src/isaac_audio_sensors/core/schema.py": "\n",
            "src/isaac_audio_sensors/core/types.py": "\n",
            "src/isaac_audio_sensors/core/io/traces.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/__init__.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/controller.py": "\n",
            "src/isaac_audio_sensors/isaac/extension_ui/window.py": "\n",
            "src/isaac_audio_sensors/isaac/microphone_rig_profiles.py": "\n",
            "src/isaac_audio_sensors/isaac/replicator.py": "\n",
            "src/isaac_audio_sensors/isaac/sound_profiles.py": "\n",
            "tests/test_acoustic_fidelity.py": "def test_ladder():\n    assert True\n",
            "tests/test_isaac_audio_core.py": "def test_core():\n    assert True\n",
            (
                "tests/test_live_evidence_report.py"
            ): "def test_report():\n    assert True\n",
            "tests/test_v1_scope_docs.py": "def test_scope():\n    assert True\n",
            ".local-goals/private.md": "local notes\n",
            "docs/private.md": "/home/" + "pacquadr/Desktop/private\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(".local-goals" in finding for finding in result.findings)
    assert any(
        "forbidden public-package text token" in finding for finding in result.findings
    )


def test_distribution_audit_rejects_unexpected_archive_version(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / "isaac_audio_sensors-9.9.9.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any("unexpected sdist filename" in finding for finding in result.findings)


def test_distribution_audit_rejects_stale_active_version_text(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "current release remains " + "0." + "1.0\n",
            "CHANGELOG.md": "# Changelog\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(
        "stale active release version token" in finding for finding in result.findings
    )


def test_distribution_audit_rejects_missing_api_freeze_contract_lock(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "# isaac-audio-sensors\n",
            "CHANGELOG.md": "# Changelog\n",
            "docs/api_freeze_0_1.md": "# API Freeze\n",
            "docs/v1_scope.md": _scope_doc_text(),
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(
        "required v1 contract phrase missing" in finding for finding in result.findings
    )


def test_distribution_audit_rejects_sdist_traversal_member(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    _write_sdist(
        archive_path,
        {
            "README.md": "# isaac-audio-sensors\n",
            "../outside_package.py": "print('poisoned')\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(
        "unsafe sdist archive path included" in finding
        and "outside_package.py" in finding
        for finding in result.findings
    )


def test_distribution_audit_rejects_wheel_traversal_member(tmp_path):
    audit = _load_audit_module()
    archive_path = (
        tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}-py3-none-any.whl"
    )
    _write_wheel(
        archive_path,
        {
            "isaac_audio_sensors/__init__.py": "\n",
            "../outside_wheel.py": "print('poisoned')\n",
        },
    )

    result = audit.audit_archive(archive_path)

    assert any(
        "unsafe wheel archive path included" in finding
        and "outside_wheel.py" in finding
        for finding in result.findings
    )


def test_distribution_audit_rejects_sdist_links(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    root = f"isaac_audio_sensors-{RELEASE_VERSION}"
    with tarfile.open(archive_path, "w:gz") as archive:
        _add_tar_text(archive, f"{root}/README.md", "# isaac-audio-sensors\n")
        symlink = tarfile.TarInfo(f"{root}/linked_secret.py")
        symlink.type = tarfile.SYMTYPE
        symlink.linkname = "README.md"
        archive.addfile(symlink)
        hardlink = tarfile.TarInfo(f"{root}/hardlinked_secret.py")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = f"{root}/README.md"
        archive.addfile(hardlink)

    result = audit.audit_archive(archive_path)

    assert any(
        "unsafe sdist member type included" in finding
        and "linked_secret.py" in finding
        for finding in result.findings
    )
    assert any(
        "unsafe sdist member type included" in finding
        and "hardlinked_secret.py" in finding
        for finding in result.findings
    )


def test_distribution_audit_rejects_duplicate_normalized_entries(tmp_path):
    audit = _load_audit_module()
    archive_path = tmp_path / f"isaac_audio_sensors-{RELEASE_VERSION}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        _add_tar_text(archive, "first-root/README.md", "first\n")
        _add_tar_text(archive, "second-root/README.md", "second\n")

    result = audit.audit_archive(archive_path)

    assert any(
        "duplicate normalized archive entry included" in finding
        and "README.md" in finding
        for finding in result.findings
    )


def test_distribution_audit_classifies_final_plan_as_scope_document():
    audit = _load_audit_module()

    assert audit._project_scope_token_findings(
        "docs/final_sensor_development_plan.md",
        "SquadBot readiness remains an external adapter concern.",
    ) == ()
    assert audit._project_scope_token_findings(
        "docs/architecture.md",
        "SquadBot implementation detail.",
    ) == (
        "docs/architecture.md: project token 'SquadBot' outside scope docs",
    )


def _api_freeze_doc_text() -> str:
    return "\n".join(
        (
            "# API Freeze",
            "The schema version is separate from the Python package version.",
            "Renaming public fields is a breaking change.",
            "Removing public fields is a breaking change.",
            (
                "Changing `schema_version` away from "
                "`ias.audio_sensor_frame.v1` is a breaking change."
            ),
            "Changing bearing-sector semantics is a breaking change.",
            (
                "`geometry_only`, `tdoa_synthetic`, and `room_acoustics` "
                "are stable backend identifiers."
            ),
            (
                "Additive optional fields and additive diagnostics namespaces "
                "are compatible."
            ),
            "Corrected bearing-sector behavior is the stable v1 contract.",
            "",
        )
    )


def _scope_doc_text() -> str:
    return "\n".join(
        (
            "# V1 Public Scope",
            "Stable `AudioSensorFrame` v1 public contract",
            "Stable L0 `geometry_only` backend",
            "Stable L1 `tdoa_synthetic` backend",
            "Supported optional L2 `room_acoustics` backend",
            "Supported Isaac Sim live sensor path",
            "Supported Isaac Lab sensor path",
            "Omniverse extension as the reference UX",
            "Stable JSON/JSONL export",
            "Replicator as an optional extension capability",
            "SquadBot as a v1 release gate",
            "Sim-real calibration",
            "Real hardware benchmarks",
            "Complete L3/L4 acoustic fidelity",
            "Realistic occlusions or material acoustics",
            "Mandatory ROS 2 or downstream adapters",
            "Alex or SquadBot validation before releasing the sensor package",
            "",
        )
    )


def _write_sdist(path: Path, files: dict[str, str]) -> None:
    root = f"isaac_audio_sensors-{RELEASE_VERSION}"
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            _add_tar_text(archive, f"{root}/{name}", content)


def _write_wheel(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _add_tar_text(archive: tarfile.TarFile, name: str, content: str) -> None:
    payload = content.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))
