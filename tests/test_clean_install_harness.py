"""Pure tests for the S1.6 clean-install harness."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest


def _load_gate_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "live_clean_install_gate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "live_clean_install_gate", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_release_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    wheel = dist_dir / "isaac_audio_sensors-1.8.0-py3-none-any.whl"
    kit_dir = dist_dir / "kit"
    kit_dir.mkdir(parents=True)
    kit_zip = kit_dir / "isaac_audio_sensors.omni-1.8.0.zip"
    wheel.write_bytes(b"wheel bytes")
    kit_zip.write_bytes(b"kit bytes")
    (dist_dir / "SHA256SUMS").write_text(
        f"{_sha256(wheel)}  {wheel.name}\n{_sha256(kit_zip)}  kit/{kit_zip.name}\n",
        encoding="utf-8",
    )
    return wheel, kit_zip


def test_sha256sums_parse_and_exact_artifact_verification(tmp_path):
    gate = _load_gate_module()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel, kit_zip = _write_release_artifacts(dist_dir)

    checksums = gate.parse_sha256sums(dist_dir / "SHA256SUMS")
    artifacts = gate.verify_release_artifacts(dist_dir)

    assert checksums[wheel.name] == _sha256(wheel)
    assert checksums[f"kit/{kit_zip.name}"] == _sha256(kit_zip)
    assert artifacts["wheel"]["path"] == str(wheel)
    assert artifacts["kit_zip"]["path"] == str(kit_zip)
    assert artifacts["wheel"]["verified"] is True


def test_artifact_verification_fails_closed_on_mismatch(tmp_path):
    gate = _load_gate_module()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel, _ = _write_release_artifacts(dist_dir)
    wheel.write_bytes(b"changed after checksums")

    with pytest.raises(gate.CleanInstallGateError, match="SHA-256 mismatch"):
        gate.verify_release_artifacts(dist_dir)


def test_preflight_neutralize_and_restore_round_trip(tmp_path):
    gate = _load_gate_module()
    isaac_root = tmp_path / "isaacsim"
    exts_user = isaac_root / "extsUser"
    exts_user.mkdir(parents=True)
    checkout = tmp_path / "checkout" / "exts" / "isaac_audio_sensors.omni"
    checkout.mkdir(parents=True)
    extension_link = exts_user / "isaac_audio_sensors.omni"
    extension_link.symlink_to(checkout, target_is_directory=True)

    kit_data = tmp_path / "kit-data"
    config = kit_data / "Isaac-Sim Full" / "6.0" / "user.config.json"
    config.parent.mkdir(parents=True)
    original = {
        "persistent": {
            "app": {
                "exts": {
                    "enabled": [
                        "omni.example-1.0.0",
                        "isaac_audio_sensors.omni-1.8.0",
                    ],
                    "isaac_audio_sensors.omni": {"autoload": True},
                }
            }
        },
        "unrelated": {"value": 7},
    }
    original_text = json.dumps(original, indent=2) + "\n"
    config.write_text(original_text, encoding="utf-8")
    clean_config = kit_data / "Isaac-Sim Full" / "6.1" / "user.config.json"
    clean_config.parent.mkdir(parents=True)
    clean_config.write_text('{"unrelated": true}\n', encoding="utf-8")

    inventory = gate.neutralize_preflight(
        isaac_root=isaac_root,
        kit_data_root=kit_data,
        backup_dir=tmp_path / "backup",
    )

    assert inventory["status"] == "neutralized"
    assert not extension_link.exists()
    moved = inventory["neutralized"]["extension_entries"][0]
    assert moved["type"] == "symlink"
    assert Path(moved["backup_path"]).is_symlink()
    scrubbed = json.loads(config.read_text(encoding="utf-8"))
    assert scrubbed["persistent"]["app"]["exts"]["enabled"] == ["omni.example-1.0.0"]
    assert "isaac_audio_sensors.omni" not in scrubbed["persistent"]["app"]["exts"]
    config_record = inventory["neutralized"]["user_configs"][0]
    assert config_record["removed_keys"] == [
        "$.persistent.app.exts.enabled[1]",
        '$.persistent.app.exts["isaac_audio_sensors.omni"]',
    ]
    assert Path(config_record["backup_path"]).read_text() == original_text
    assert inventory["after"]["extension_entries"] == []
    assert not any(
        item["contains_reference"] for item in inventory["after"]["user_configs"]
    )

    restore = gate.restore_preflight(inventory)

    assert restore == {"status": "restored", "errors": []}
    assert extension_link.is_symlink()
    assert os.readlink(extension_link) == str(checkout)
    assert config.read_text(encoding="utf-8") == original_text
    assert inventory["after_restore"]["extension_entries"][0]["type"] == "symlink"
    assert any(
        item["contains_reference"]
        for item in inventory["after_restore"]["user_configs"]
    )


def test_stage_extension_recreates_clean_tree_and_hashes_inventory(tmp_path):
    gate = _load_gate_module()
    archive = tmp_path / "extension.zip"
    # The real Kit zip stores the extension content at the archive root; the
    # stager creates the id-version folder itself.
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "config/extension.toml",
            '[package]\nversion = "1.8.0"\n',
        )
        bundle.writestr(
            "_vendor/VENDORED.json",
            '{"mode": "packaged", "version": "1.8.0"}\n',
        )
        bundle.writestr(
            "_vendor/isaac_audio_sensors/__init__.py",
            '__version__ = "1.8.0"\n',
        )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    clean_env = out_dir / "clean_env"

    first = gate.stage_kit_extension(
        archive_path=archive, clean_env=clean_env, out_dir=out_dir
    )
    stale = clean_env / "extsUser" / "stale.txt"
    stale.write_text("stale", encoding="utf-8")
    second = gate.stage_kit_extension(
        archive_path=archive, clean_env=clean_env, out_dir=out_dir
    )

    assert first["tree_sha256"] == second["tree_sha256"]
    assert first["entry_count"] == second["entry_count"]
    assert not stale.exists()
    assert (
        clean_env
        / "extsUser"
        / "isaac_audio_sensors.omni-1.8.0"
        / "_vendor"
        / "isaac_audio_sensors"
        / "__init__.py"
    ).is_file()


def test_scenario_environment_is_sanitized():
    gate = _load_gate_module()
    source = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/checkout/src",
        "PYTHONHOME": "/python",
        "PIP_INDEX_URL": "https://example.invalid/simple",
        "PIP_REQUIRE_VIRTUALENV": "1",
        "KEEP_ME": "yes",
    }

    clean, delta = gate.build_sanitized_env(
        source, additions={"IAS_CLEAN_INSTALL_GUI": "0"}
    )

    assert clean["PYTHONNOUSERSITE"] == "1"
    assert clean["IAS_CLEAN_INSTALL_GUI"] == "0"
    assert clean["KEEP_ME"] == "yes"
    assert "PYTHONPATH" not in clean
    assert "PYTHONHOME" not in clean
    assert not any(key.startswith("PIP_") for key in clean)
    assert delta["removed"] == [
        "PIP_INDEX_URL",
        "PIP_REQUIRE_VIRTUALENV",
        "PYTHONHOME",
        "PYTHONPATH",
    ]
    compile(gate._wheel_provenance_code(), "<wheel-provenance>", "exec")


@pytest.mark.parametrize(
    ("scenario_statuses", "artifacts", "preflight", "restore", "expected"),
    [
        ({"headless": "passed", "wheel-venv": "passed"}, True, True, True, "passed"),
        ({"headless": "failed", "wheel-venv": "passed"}, True, True, True, "failed"),
        ({"headless": "passed", "wheel-venv": "passed"}, False, True, True, "failed"),
        ({"headless": "passed", "wheel-venv": "passed"}, True, False, True, "failed"),
        ({"headless": "passed", "wheel-venv": "passed"}, True, True, False, "failed"),
    ],
)
def test_verdict_aggregation(
    scenario_statuses, artifacts, preflight, restore, expected
):
    gate = _load_gate_module()
    records = {name: {"status": status} for name, status in scenario_statuses.items()}

    assert (
        gate.aggregate_verdict(
            requested_scenarios=["headless", "wheel-venv"],
            scenario_records=records,
            artifacts_verified=artifacts,
            preflight_completed=preflight,
            restore_completed=restore,
        )
        == expected
    )
