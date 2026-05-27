"""Install the local Omniverse extension into an Isaac Sim user extension dir."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:  # pragma: no cover - py311 path in CI
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py310 fallback
    import tomli as tomllib  # type: ignore[no-redef]


EXTENSION_NAME = "isaac_audio_sensors.omni"
DEFAULT_USER_CONFIG = (
    Path.home() / ".local/share/ov/data/Kit/Isaac-Sim Full/5.1/user.config.json"
)


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Filesystem and Kit settings targets for a local Isaac Sim install."""

    repo_root: Path
    extension_dir: Path
    extension_id: str
    exts_user_dir: Path
    link_path: Path
    user_config: Path | None


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def load_extension_id(extension_dir: Path) -> str:
    manifest_path = extension_dir / "config" / "extension.toml"
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    version = manifest.get("package", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"missing package.version in {manifest_path}")
    return f"{extension_dir.name}-{version}"


def resolve_isaacsim_root_from_command(command: Path) -> Path:
    command = command.expanduser()
    if not command.is_absolute():
        resolved = shutil.which(str(command))
        if resolved is None:
            raise FileNotFoundError(f"could not find isaacsim command: {command}")
        command = Path(resolved)
    command = command.resolve()

    candidates: list[Path] = []
    if command.parent.name == "bin":
        env_root = command.parent.parent
        site_package_roots = (env_root / "lib").glob(
            "python*/site-packages/isaacsim"
        )
        candidates.extend(sorted(site_package_roots))
    candidates.extend(command.parents)

    for candidate in candidates:
        if (candidate / "extsUser").is_dir():
            return candidate
    raise FileNotFoundError(
        "could not locate an Isaac Sim package root with extsUser from "
        f"{command}; pass --isaacsim-root or --exts-user-dir"
    )


def build_plan(
    *,
    repo_root: Path,
    isaacsim_command: Path | None,
    isaacsim_root: Path | None,
    exts_user_dir: Path | None,
    user_config: Path | None,
) -> InstallPlan:
    repo_root = repo_root.expanduser().resolve()
    extension_dir = repo_root / "exts" / EXTENSION_NAME
    if not extension_dir.is_dir():
        raise FileNotFoundError(f"extension directory not found: {extension_dir}")

    if exts_user_dir is None:
        if isaacsim_root is None:
            if isaacsim_command is None:
                isaacsim_command = Path(os.environ.get("ISAAC_SIM_COMMAND", "isaacsim"))
            isaacsim_root = resolve_isaacsim_root_from_command(isaacsim_command)
        exts_user_dir = isaacsim_root.expanduser().resolve() / "extsUser"
    else:
        exts_user_dir = exts_user_dir.expanduser().resolve()

    return InstallPlan(
        repo_root=repo_root,
        extension_dir=extension_dir,
        extension_id=load_extension_id(extension_dir),
        exts_user_dir=exts_user_dir,
        link_path=exts_user_dir / EXTENSION_NAME,
        user_config=user_config.expanduser().resolve() if user_config else None,
    )


def install_link(plan: InstallPlan, *, dry_run: bool, replace: bool) -> str:
    if plan.link_path.is_symlink():
        current_target = plan.link_path.resolve(strict=False)
        if current_target == plan.extension_dir:
            return "already linked"
        if not replace:
            raise FileExistsError(
                f"{plan.link_path} already points to {current_target}; "
                "rerun with --replace to update it"
            )
        if not dry_run:
            plan.link_path.unlink()
    elif plan.link_path.exists():
        raise FileExistsError(
            f"{plan.link_path} exists and is not a symlink; refusing to overwrite it"
        )

    if dry_run:
        return "would link"

    plan.exts_user_dir.mkdir(parents=True, exist_ok=True)
    plan.link_path.symlink_to(plan.extension_dir, target_is_directory=True)
    return "linked"


def _enabled_entries(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        return [key for key, item in value.items() if item or value == {}]
    return []


def set_autoload(plan: InstallPlan, *, dry_run: bool) -> str:
    if plan.user_config is None:
        return "skipped"

    data: dict[str, object]
    if plan.user_config.exists():
        data = json.loads(plan.user_config.read_text(encoding="utf-8"))
    else:
        data = {}

    persistent = data.setdefault("persistent", {})
    if not isinstance(persistent, dict):
        raise ValueError(f"{plan.user_config}: persistent must be an object")
    app = persistent.setdefault("app", {})
    if not isinstance(app, dict):
        raise ValueError(f"{plan.user_config}: persistent.app must be an object")
    exts = app.setdefault("exts", {})
    if not isinstance(exts, dict):
        raise ValueError(f"{plan.user_config}: persistent.app.exts must be an object")

    current = _enabled_entries(exts.get("enabled", []))
    next_entries = [
        item
        for item in current
        if item != EXTENSION_NAME and not item.startswith(f"{EXTENSION_NAME}-")
    ]
    next_entries.append(plan.extension_id)

    if current == next_entries and exts.get("enabled") == next_entries:
        return "already enabled"

    exts["enabled"] = next_entries
    if dry_run:
        return "would enable"

    plan.user_config.parent.mkdir(parents=True, exist_ok=True)
    if plan.user_config.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = plan.user_config.with_suffix(
            plan.user_config.suffix + f".bak-{timestamp}"
        )
        shutil.copy2(plan.user_config, backup)
    plan.user_config.write_text(
        json.dumps(data, indent=4, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return "enabled"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install this checkout's Isaac Audio Sensors Omniverse extension "
            "into Isaac Sim's persistent extsUser folder."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root_from_script(),
        help="repository checkout root; defaults to this script's parent repo",
    )
    parser.add_argument(
        "--isaacsim-command",
        type=Path,
        default=None,
        help="Isaac Sim launcher used to auto-detect the isaacsim package root",
    )
    parser.add_argument(
        "--isaacsim-root",
        type=Path,
        default=None,
        help="path to the isaacsim Python package root containing extsUser",
    )
    parser.add_argument(
        "--exts-user-dir",
        type=Path,
        default=None,
        help="explicit Isaac Sim extsUser directory",
    )
    parser.add_argument(
        "--user-config",
        type=Path,
        default=DEFAULT_USER_CONFIG,
        help="Kit user.config.json to update for autoload",
    )
    parser.add_argument(
        "--no-autoload",
        action="store_true",
        help="only add the extension to Isaac's search path; do not autoload it",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing symlink for this extension",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned changes without writing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_plan(
            repo_root=args.repo_root,
            isaacsim_command=args.isaacsim_command,
            isaacsim_root=args.isaacsim_root,
            exts_user_dir=args.exts_user_dir,
            user_config=None if args.no_autoload else args.user_config,
        )
        link_status = install_link(plan, dry_run=args.dry_run, replace=args.replace)
        autoload_status = set_autoload(plan, dry_run=args.dry_run)
    except Exception as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1

    print(f"extension: {plan.extension_id}")
    print(f"source: {plan.extension_dir}")
    print(f"extsUser link: {plan.link_path} ({link_status})")
    if plan.user_config is None:
        print("autoload: skipped")
    else:
        print(f"autoload: {plan.user_config} ({autoload_status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
