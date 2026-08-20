"""Tests for installing the Omniverse extension into Isaac Sim."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_install_module():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "install_isaac_sim_extension.py"
    )
    spec = importlib.util.spec_from_file_location(
        "install_isaac_sim_extension", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_extension(repo_root: Path, version: str = "1.2.3") -> Path:
    extension_dir = repo_root / "exts" / "isaac_audio_sensors.omni"
    config_dir = extension_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "extension.toml").write_text(
        "[package]\n"
        f'version = "{version}"\n'
        'title = "Isaac Audio Sensors"\n',
        encoding="utf-8",
    )
    return extension_dir


def test_install_creates_exts_user_link_and_autoload_entry(tmp_path):
    installer = _load_install_module()
    repo_root = tmp_path / "repo"
    extension_dir = _write_extension(repo_root)
    isaacsim_root = tmp_path / "isaacsim"
    user_config = tmp_path / "Kit" / "Isaac-Sim Full" / "5.1" / "user.config.json"

    plan = installer.build_plan(
        repo_root=repo_root,
        isaacsim_command=None,
        isaacsim_root=isaacsim_root,
        exts_user_dir=None,
        user_config=user_config,
    )

    assert installer.install_link(plan, dry_run=False, replace=False) == "linked"
    assert plan.link_path.is_symlink()
    assert plan.link_path.resolve() == extension_dir.resolve()

    assert installer.set_autoload(plan, dry_run=False) == "enabled"
    data = json.loads(user_config.read_text(encoding="utf-8"))
    assert data["persistent"]["app"]["exts"]["enabled"] == [
        "isaac_audio_sensors.omni-1.2.3"
    ]


def test_autoload_replaces_old_extension_versions_and_preserves_others(tmp_path):
    installer = _load_install_module()
    repo_root = tmp_path / "repo"
    _write_extension(repo_root, version="1.2.3")
    user_config = tmp_path / "user.config.json"
    user_config.write_text(
        json.dumps(
            {
                "persistent": {
                    "app": {
                        "exts": {
                            "enabled": [
                                "isaac_audio_sensors.omni-0.9.0",
                                "omni.example-1.0.0",
                            ]
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    plan = installer.build_plan(
        repo_root=repo_root,
        isaacsim_command=None,
        isaacsim_root=tmp_path / "isaacsim",
        exts_user_dir=None,
        user_config=user_config,
    )

    assert installer.set_autoload(plan, dry_run=False) == "enabled"

    data = json.loads(user_config.read_text(encoding="utf-8"))
    assert data["persistent"]["app"]["exts"]["enabled"] == [
        "omni.example-1.0.0",
        "isaac_audio_sensors.omni-1.2.3",
    ]
    assert list(user_config.parent.glob("user.config.json.bak-*"))


def test_install_refuses_existing_non_symlink_path(tmp_path):
    installer = _load_install_module()
    repo_root = tmp_path / "repo"
    _write_extension(repo_root)
    exts_user_dir = tmp_path / "isaacsim" / "extsUser"
    exts_user_dir.mkdir(parents=True)
    (exts_user_dir / "isaac_audio_sensors.omni").write_text(
        "not a link\n", encoding="utf-8"
    )
    plan = installer.build_plan(
        repo_root=repo_root,
        isaacsim_command=None,
        isaacsim_root=None,
        exts_user_dir=exts_user_dir,
        user_config=None,
    )

    try:
        installer.install_link(plan, dry_run=False, replace=False)
    except FileExistsError as exc:
        assert "is not a symlink" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("expected FileExistsError")


def test_default_user_config_picks_highest_installed_kit_version(
    tmp_path, monkeypatch
):
    installer = _load_install_module()
    kit_data_dir = tmp_path / "Kit" / "Isaac-Sim Full"
    for version in ("5.1", "6.0", "10.0"):
        config_dir = kit_data_dir / version
        config_dir.mkdir(parents=True)
        (config_dir / "user.config.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(installer, "KIT_DATA_DIR", kit_data_dir)

    assert installer._default_user_config() == (
        kit_data_dir / "10.0" / "user.config.json"
    )


def test_default_user_config_falls_back_when_no_kit_data(tmp_path, monkeypatch):
    installer = _load_install_module()
    kit_data_dir = tmp_path / "Kit" / "Isaac-Sim Full"
    monkeypatch.setattr(installer, "KIT_DATA_DIR", kit_data_dir)

    assert installer._default_user_config() == (
        kit_data_dir / "6.0" / "user.config.json"
    )
