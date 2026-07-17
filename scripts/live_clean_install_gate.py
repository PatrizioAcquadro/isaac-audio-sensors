"""Run the S1.6 clean-install gate against immutable release artifacts.

This script intentionally runs outside Kit and uses only the Python standard
library.  It temporarily neutralizes known developer-install side effects,
stages the release extension in an output-local folder, and always attempts to
restore the original host state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import time
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

EXTENSION_NAME = "isaac_audio_sensors.omni"
PACKAGE_NAME = "isaac_audio_sensors"
PACKAGE_VERSION = "1.8.0"
DEFAULT_SCENARIOS = "headless,reinstall,wheel-venv"
SCENARIO_NAMES = frozenset({"headless", "reinstall", "gui", "wheel-venv"})
PROVENANCE_MODULES = (
    "isaac_audio_sensors",
    "numpy",
    "scipy",
    "soundfile",
    "pyroomacoustics",
)


class CleanInstallGateError(RuntimeError):
    """Raised when an S1.6 gate invariant is not satisfied."""


def utc_now() -> str:
    """Return an evidence-friendly UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def parse_sha256sums(path: str | Path) -> dict[str, str]:
    """Parse a GNU-style SHA256SUMS file and reject ambiguous entries."""

    checksum_path = Path(path)
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise CleanInstallGateError(
                f"{checksum_path}:{line_number}: malformed checksum entry"
            )
        digest, raw_name = parts
        name = raw_name.lstrip("*")
        if len(digest) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in digest
        ):
            raise CleanInstallGateError(
                f"{checksum_path}:{line_number}: invalid SHA-256 digest"
            )
        pure_name = PurePosixPath(name)
        if pure_name.is_absolute() or ".." in pure_name.parts or name in {"", "."}:
            raise CleanInstallGateError(
                f"{checksum_path}:{line_number}: unsafe artifact path {name!r}"
            )
        normalized = pure_name.as_posix()
        if normalized in entries:
            raise CleanInstallGateError(
                f"{checksum_path}:{line_number}: duplicate artifact {normalized!r}"
            )
        entries[normalized] = digest.lower()
    if not entries:
        raise CleanInstallGateError(f"no checksums found in {checksum_path}")
    return entries


def sha256_file(path: str | Path) -> str:
    """Hash one file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_release_artifacts(dist_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Verify and return the exact wheel and Kit zip named by SHA256SUMS."""

    root = Path(dist_dir).expanduser().resolve()
    checksums_path = root / "SHA256SUMS"
    checksums = parse_sha256sums(checksums_path)
    expected_wheel = f"{PACKAGE_NAME}-{PACKAGE_VERSION}-py3-none-any.whl"
    expected_zip = f"{EXTENSION_NAME}-{PACKAGE_VERSION}.zip"

    def select(expected_name: str, kind: str) -> dict[str, Any]:
        matches = [
            name for name in checksums if PurePosixPath(name).name == expected_name
        ]
        if len(matches) != 1:
            raise CleanInstallGateError(
                f"SHA256SUMS must contain exactly one {kind} named {expected_name}; "
                f"found {len(matches)}"
            )
        relative = matches[0]
        artifact = (root / relative).resolve()
        try:
            artifact.relative_to(root)
        except ValueError as exc:
            raise CleanInstallGateError(
                f"{kind} resolves outside dist directory: {artifact}"
            ) from exc
        if not artifact.is_file():
            raise CleanInstallGateError(f"missing {kind}: {artifact}")
        actual = sha256_file(artifact)
        expected = checksums[relative]
        if actual != expected:
            raise CleanInstallGateError(
                f"SHA-256 mismatch for {artifact}: expected {expected}, got {actual}"
            )
        return {
            "path": str(artifact),
            "relative_path": relative,
            "sha256": actual,
            "size_bytes": artifact.stat().st_size,
            "verified": True,
        }

    return {
        "checksums": {
            "path": str(checksums_path),
            "sha256": sha256_file(checksums_path),
            "entry_count": len(checksums),
        },
        "kit_zip": select(expected_zip, "Kit extension archive"),
        "wheel": select(expected_wheel, "wheel"),
    }


def _entry_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    return "other"


def _extension_entry_record(path: Path, *, exts_user: Path) -> dict[str, Any]:
    target = os.readlink(path) if path.is_symlink() else None
    return {
        "path": str(path),
        "relative_path": path.relative_to(exts_user).as_posix(),
        "type": _entry_type(path),
        "target": target,
    }


def _find_extension_entries(exts_user: Path) -> list[Path]:
    if not exts_user.is_dir():
        return []
    return sorted(
        (path for path in exts_user.rglob(EXTENSION_NAME)),
        key=lambda path: path.as_posix(),
    )


def _contains_package_reference(value: Any) -> bool:
    if isinstance(value, str):
        return PACKAGE_NAME in value
    if isinstance(value, list):
        return any(_contains_package_reference(item) for item in value)
    if isinstance(value, dict):
        return any(
            PACKAGE_NAME in str(key) or _contains_package_reference(item)
            for key, item in value.items()
        )
    return False


def _json_path_key(parent: str, key: str) -> str:
    if key.isidentifier():
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key)}]"


def remove_package_references(value: Any, *, path: str = "$") -> tuple[Any, list[str]]:
    """Recursively remove JSON entries that reference isaac_audio_sensors."""

    removed: list[str] = []
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            item_path = _json_path_key(path, str(key))
            if PACKAGE_NAME in str(key) or (
                not isinstance(item, (dict, list)) and _contains_package_reference(item)
            ):
                removed.append(item_path)
                continue
            cleaned_item, nested_removed = remove_package_references(
                item, path=item_path
            )
            cleaned[key] = cleaned_item
            removed.extend(nested_removed)
        return cleaned, removed
    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if not isinstance(item, (dict, list)) and _contains_package_reference(item):
                removed.append(item_path)
                continue
            cleaned_item, nested_removed = remove_package_references(
                item, path=item_path
            )
            cleaned_list.append(cleaned_item)
            removed.extend(nested_removed)
        return cleaned_list, removed
    return value, removed


def _config_inventory(path: Path, *, kit_data_root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return {
        "path": str(path),
        "relative_path": path.relative_to(kit_data_root).as_posix(),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "contains_reference": PACKAGE_NAME in text,
    }


def neutralize_preflight(
    *,
    isaac_root: str | Path,
    kit_data_root: str | Path,
    backup_dir: str | Path,
    inventory_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inventory and back up developer-install side effects, then neutralize."""

    isaac_path = Path(isaac_root).expanduser().resolve()
    kit_data_path = Path(kit_data_root).expanduser().resolve()
    backup_path = Path(backup_dir).expanduser().resolve()
    exts_user = isaac_path / "extsUser"
    initial: dict[str, Any] = {
        "status": "started",
        "started_at": utc_now(),
        "isaac_root": str(isaac_path),
        "kit_data_root": str(kit_data_path),
        "backup_dir": str(backup_path),
        "before": {"extension_entries": [], "user_configs": []},
        "neutralized": {"extension_entries": [], "user_configs": []},
        "after": {},
        "after_restore": None,
    }
    inventory = inventory_record if inventory_record is not None else {}
    inventory.clear()
    inventory.update(initial)
    unresolved_backup = backup_path / "extsUser"
    if backup_path.exists():
        unresolved_entries = _find_extension_entries(unresolved_backup)
        if unresolved_entries:
            raise CleanInstallGateError(
                "preflight backup contains an unrestored extension entry; restore "
                f"it before rerunning: {unresolved_entries[0]}"
            )
        shutil.rmtree(backup_path)
    backup_path.mkdir(parents=True, exist_ok=True)

    extension_entries = _find_extension_entries(exts_user)
    inventory["before"]["extension_entries"] = [
        _extension_entry_record(path, exts_user=exts_user) for path in extension_entries
    ]
    for entry in extension_entries:
        relative = entry.relative_to(exts_user)
        destination = backup_path / "extsUser" / relative
        if destination.exists() or destination.is_symlink():
            raise CleanInstallGateError(
                f"preflight backup already exists: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        record = _extension_entry_record(entry, exts_user=exts_user)
        shutil.move(str(entry), str(destination))
        record["backup_path"] = str(destination)
        inventory["neutralized"]["extension_entries"].append(record)

    config_paths = (
        sorted(kit_data_path.glob("*/*/user.config.json"))
        if kit_data_path.is_dir()
        else []
    )
    for config_path in config_paths:
        before_record = _config_inventory(config_path, kit_data_root=kit_data_path)
        inventory["before"]["user_configs"].append(before_record)
        if not before_record["contains_reference"]:
            continue
        relative = config_path.relative_to(kit_data_path)
        destination = backup_path / "user_configs" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise CleanInstallGateError(
                f"preflight backup already exists: {destination}"
            )
        shutil.copy2(config_path, destination)
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CleanInstallGateError(
                f"cannot safely neutralize invalid JSON in {config_path}: {exc}"
            ) from exc
        cleaned, removed = remove_package_references(data)
        if not removed:
            raise CleanInstallGateError(
                f"{config_path} contains {PACKAGE_NAME!r}, but no JSON entry could "
                "be safely identified for removal"
            )
        config_path.write_text(
            json.dumps(cleaned, indent=4, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        inventory["neutralized"]["user_configs"].append(
            {
                **before_record,
                "backup_path": str(destination),
                "removed_keys": removed,
                "after_sha256": sha256_file(config_path),
            }
        )

    inventory["after"] = preflight_state_inventory(
        isaac_root=isaac_path, kit_data_root=kit_data_path
    )
    if inventory["after"]["extension_entries"] or any(
        item["contains_reference"] for item in inventory["after"]["user_configs"]
    ):
        raise CleanInstallGateError(
            "preflight decontamination did not reach a clean state"
        )
    inventory["status"] = "neutralized"
    inventory["neutralized_at"] = utc_now()
    return inventory


def preflight_state_inventory(
    *, isaac_root: str | Path, kit_data_root: str | Path
) -> dict[str, Any]:
    """Record the current extension/autoload contamination state."""

    isaac_path = Path(isaac_root).expanduser().resolve()
    kit_data_path = Path(kit_data_root).expanduser().resolve()
    exts_user = isaac_path / "extsUser"
    configs = (
        sorted(kit_data_path.glob("*/*/user.config.json"))
        if kit_data_path.is_dir()
        else []
    )
    return {
        "extension_entries": [
            _extension_entry_record(path, exts_user=exts_user)
            for path in _find_extension_entries(exts_user)
        ],
        "user_configs": [
            _config_inventory(path, kit_data_root=kit_data_path) for path in configs
        ],
    }


def restore_preflight(inventory: dict[str, Any]) -> dict[str, Any]:
    """Restore every filesystem item recorded by ``neutralize_preflight``."""

    errors: list[str] = []
    for record in reversed(inventory["neutralized"]["extension_entries"]):
        original = Path(record["path"])
        backup = Path(record["backup_path"])
        try:
            if original.exists() or original.is_symlink():
                raise CleanInstallGateError(
                    "refusing to overwrite new extension entry during restore: "
                    f"{original}"
                )
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(original))
        except Exception as exc:  # noqa: BLE001 - all restore failures are evidence.
            errors.append(f"{type(exc).__name__}: {exc}")

    for record in inventory["neutralized"]["user_configs"]:
        original = Path(record["path"])
        backup = Path(record["backup_path"])
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, original)
        except Exception as exc:  # noqa: BLE001 - all restore failures are evidence.
            errors.append(f"{type(exc).__name__}: {exc}")

    try:
        after_restore = preflight_state_inventory(
            isaac_root=inventory["isaac_root"],
            kit_data_root=inventory["kit_data_root"],
        )
    except Exception as exc:  # noqa: BLE001 - restoration evidence must survive.
        message = f"{type(exc).__name__}: {exc}"
        errors.append(f"after-restore inventory failed: {message}")
        after_restore = {"inventory_error": message}
    if "extension_entries" in after_restore:
        restored_extensions = {
            item["path"]: item for item in after_restore["extension_entries"]
        }
        for expected in inventory["before"]["extension_entries"]:
            actual = restored_extensions.get(expected["path"])
            if actual is None or any(
                actual.get(key) != expected.get(key) for key in ("type", "target")
            ):
                errors.append(
                    "restored extension entry does not match before state: "
                    f"{expected['path']}"
                )
        restored_configs = {
            item["path"]: item for item in after_restore["user_configs"]
        }
        for expected in inventory["neutralized"]["user_configs"]:
            actual = restored_configs.get(expected["path"])
            if actual is None or actual.get("sha256") != expected.get("sha256"):
                errors.append(
                    "restored user config does not match before state: "
                    f"{expected['path']}"
                )
    inventory["after_restore"] = after_restore
    inventory["restore_errors"] = errors
    inventory["restored_at"] = utc_now()
    inventory["restore_status"] = "failed" if errors else "restored"
    return {"status": inventory["restore_status"], "errors": errors}


def build_sanitized_env(
    source: Mapping[str, str] | None = None,
    *,
    additions: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Build the clean subprocess environment and describe its exact deltas."""

    original = dict(os.environ if source is None else source)
    removed = sorted(
        key
        for key in original
        if key in {"PYTHONPATH", "PYTHONHOME"} or key.startswith("PIP_")
    )
    clean = {key: value for key, value in original.items() if key not in removed}
    changed: dict[str, str] = {"PYTHONNOUSERSITE": "1"}
    if additions:
        changed.update({str(key): str(value) for key, value in additions.items()})
    clean.update(changed)
    return clean, {"removed": removed, "set": changed}


def _safe_remove_runtime_tree(path: Path, *, out_dir: Path) -> None:
    resolved_parent = path.parent.resolve()
    try:
        resolved_parent.relative_to(out_dir.resolve())
    except ValueError as exc:
        raise CleanInstallGateError(
            f"refusing to remove runtime tree outside output directory: {path}"
        ) from exc
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def extracted_tree_inventory(root: str | Path) -> dict[str, Any]:
    """Return a deterministic content inventory hash for an extracted tree."""

    tree_root = Path(root).resolve()
    digest = hashlib.sha256()
    entries: list[dict[str, Any]] = []
    for path in sorted(tree_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(tree_root).as_posix()
        if path.is_symlink():
            kind = "symlink"
            item_hash = hashlib.sha256(os.readlink(path).encode()).hexdigest()
        elif path.is_dir():
            kind = "dir"
            item_hash = None
        elif path.is_file():
            kind = "file"
            item_hash = sha256_file(path)
        else:
            kind = "other"
            item_hash = None
        line = f"{relative}\0{kind}\0{item_hash or ''}\n".encode()
        digest.update(line)
        entries.append({"path": relative, "type": kind, "sha256": item_hash})
    return {
        "root": str(tree_root),
        "tree_sha256": digest.hexdigest(),
        "entry_count": len(entries),
        "entries": entries,
    }


def stage_kit_extension(
    *, archive_path: str | Path, clean_env: str | Path, out_dir: str | Path
) -> dict[str, Any]:
    """Recreate the clean extension folder and safely extract the exact archive."""

    archive = Path(archive_path).resolve()
    clean_root = Path(clean_env).resolve()
    output_root = Path(out_dir).resolve()
    _safe_remove_runtime_tree(clean_root, out_dir=output_root)
    exts_user = clean_root / "extsUser"
    # The Kit zip stores the extension content at the archive root; Kit
    # discovers it from an id-version folder the stager creates itself.
    extension_root = exts_user / f"{EXTENSION_NAME}-{PACKAGE_VERSION}"
    extension_root.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts:
                raise CleanInstallGateError(
                    f"unsafe member in Kit extension archive: {member.filename!r}"
                )
            destination = (extension_root / name.as_posix()).resolve()
            try:
                destination.relative_to(extension_root.resolve())
            except ValueError as exc:
                raise CleanInstallGateError(
                    f"archive member escapes staging folder: {member.filename!r}"
                ) from exc
        bundle.extractall(extension_root)
    inventory = extracted_tree_inventory(exts_user)
    required = (
        f"{EXTENSION_NAME}-{PACKAGE_VERSION}/config/extension.toml",
        f"{EXTENSION_NAME}-{PACKAGE_VERSION}/_vendor/VENDORED.json",
    )
    present = {item["path"] for item in inventory["entries"]}
    for entry in required:
        if entry not in present:
            raise CleanInstallGateError(
                f"Kit archive staging is missing required entry {entry!r}"
            )
    return inventory


def run_subprocess(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    env_delta: Mapping[str, Any],
    cwd: Path,
    timeout_s: int,
    log_path: Path,
) -> dict[str, Any]:
    """Run one scenario, terminating its process group on timeout."""

    started = time.monotonic()
    record: dict[str, Any] = {
        "command": list(command),
        "cwd": str(cwd),
        "env_delta": dict(env_delta),
        "started_at": utc_now(),
        "timeout_s": timeout_s,
        "log_path": str(log_path),
    }
    try:
        process = subprocess.Popen(  # noqa: S603 - exact gate commands are intentional.
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        message = f"{type(exc).__name__}: {exc}\n"
        log_path.write_text(message, encoding="utf-8")
        record.update(
            {
                "finished_at": utc_now(),
                "duration_s": round(time.monotonic() - started, 3),
                "returncode": None,
                "timed_out": False,
                "status": "failed",
                "launch_error": message.strip(),
            }
        )
        return record
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
    log_path.write_text(output or "", encoding="utf-8")
    record.update(
        {
            "finished_at": utc_now(),
            "duration_s": round(time.monotonic() - started, 3),
            "returncode": process.returncode,
            "timed_out": timed_out,
            "status": "passed"
            if process.returncode == 0 and not timed_out
            else "failed",
        }
    )
    return record


def probe_isaac_python(
    *, isaac_root: Path, out_dir: Path, timeout_s: int
) -> dict[str, Any]:
    """Require isaac_audio_sensors to be absent from Isaac's base Python."""

    env, delta = build_sanitized_env()
    command = [
        str(isaac_root / "python.sh"),
        "-c",
        """import json
import site
import sys

try:
    import isaac_audio_sensors as module
except Exception as exc:
    print(json.dumps({
        "import_status": "absent",
        "origin": None,
        "site_ENABLE_USER_SITE": site.ENABLE_USER_SITE,
        "error": f"{type(exc).__name__}: {exc}",
    }, sort_keys=True))
    sys.exit(3)
print(json.dumps({
    "import_status": "present",
    "origin": getattr(module, "__file__", None),
    "site_ENABLE_USER_SITE": site.ENABLE_USER_SITE,
}, sort_keys=True))
""",
    ]
    record = run_subprocess(
        command,
        env=env,
        env_delta=delta,
        cwd=out_dir,
        timeout_s=min(timeout_s, 120),
        log_path=out_dir / "preflight_isaac_python_import.log",
    )
    # python.sh appends wrapper noise (e.g. "There was an error running
    # python") after the probe's JSON line, so parse the first JSON line.
    probe: dict[str, Any] = {"import_status": "unknown"}
    try:
        for line in Path(record["log_path"]).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                probe = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        probe = {"import_status": "unknown", "parse_error": str(exc)}
    record["probe"] = probe
    record["import_status"] = probe.get("import_status", "unknown")
    record["status"] = (
        "passed"
        if record["import_status"] == "absent"
        and probe.get("site_ENABLE_USER_SITE") is False
        and record["returncode"] != 0
        and not record["timed_out"]
        else "failed"
    )
    return record


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanInstallGateError(
            f"could not read scenario evidence {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CleanInstallGateError(f"scenario evidence must be a JSON object: {path}")
    return value


def _is_under(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def validate_kit_probe(
    *, probe_path: Path, clean_env: Path, require_screenshot: bool
) -> dict[str, Any]:
    """Validate the Kit-side JSON and installed-artifact provenance."""

    probe = _load_json(probe_path)
    errors: list[str] = []
    if probe.get("status") != "passed":
        errors.append(f"probe status is {probe.get('status')!r}")
    package_record = probe.get("imports", {}).get(PACKAGE_NAME, {})
    origin = package_record.get("origin")
    if package_record.get("status") != "present" or not origin:
        errors.append("isaac_audio_sensors origin is not present")
    elif "_vendor" not in Path(origin).parts or not _is_under(origin, clean_env):
        errors.append(f"isaac_audio_sensors origin is outside staged _vendor: {origin}")
    manager_path = probe.get("extension_manager", {}).get("path")
    if not manager_path or not _is_under(manager_path, clean_env / "extsUser"):
        errors.append(f"extension manager path is outside clean env: {manager_path}")
    if require_screenshot:
        screenshot = probe_path.parent / "gui_screenshot.png"
        if not screenshot.is_file() or screenshot.stat().st_size <= 10 * 1024:
            errors.append(
                f"GUI screenshot is missing or not larger than 10 KiB: {screenshot}"
            )
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "probe": probe,
    }


def run_kit_scenario(
    *,
    scenario: str,
    isaac_root: Path,
    app_path: Path,
    repo_root: Path,
    out_dir: Path,
    clean_env: Path,
    timeout_s: int,
) -> dict[str, Any]:
    """Run and validate one headless or GUI Kit scenario."""

    probe_name = {
        "headless": "probe_headless.json",
        "reinstall": "probe_reinstall.json",
        "gui": "probe_gui.json",
    }[scenario]
    probe_path = out_dir / probe_name
    if probe_path.exists():
        probe_path.unlink()
    gui = scenario == "gui"
    additions = {
        "IAS_CLEAN_EXT_FOLDER": str(clean_env / "extsUser"),
        "IAS_CLEAN_INSTALL_GUI": "1" if gui else "0",
    }
    env, delta = build_sanitized_env(additions=additions)
    command = [str(isaac_root / "kit" / "kit"), str(app_path)]
    if not gui:
        command.append("--no-window")
    command.extend(
        [
            "--ext-folder",
            str(clean_env / "extsUser"),
            "--enable",
            EXTENSION_NAME,
            "--exec",
            shlex.join(
                [
                    str(repo_root / "scripts" / "live_clean_install_probe.py"),
                    str(probe_path),
                ]
            ),
        ]
    )
    process = run_subprocess(
        command,
        env=env,
        env_delta=delta,
        cwd=out_dir,
        timeout_s=timeout_s,
        log_path=out_dir / f"{scenario}.log",
    )
    if process["status"] == "passed" and probe_path.is_file():
        validation = validate_kit_probe(
            probe_path=probe_path,
            clean_env=clean_env,
            require_screenshot=gui,
        )
    else:
        validation = {
            "status": "failed",
            "errors": ["Kit process failed or did not write probe JSON"],
        }
    process["probe_path"] = str(probe_path)
    process["validation"] = validation
    process["status"] = (
        "passed"
        if process["status"] == "passed" and validation["status"] == "passed"
        else "failed"
    )
    return process


def _wheel_provenance_code() -> str:
    return f"""import importlib
import json
import site

names = {PROVENANCE_MODULES!r}
records = {{}}
for name in names:
    try:
        module = importlib.import_module(name)
        records[name] = {{
            "status": "present",
            "origin": getattr(module, "__file__", None),
            "version": getattr(module, "__version__", None),
        }}
    except Exception as exc:
        records[name] = {{
            "status": "absent",
            "origin": None,
            "error": f"{{type(exc).__name__}}: {{exc}}",
        }}
print(json.dumps({{
    "site_ENABLE_USER_SITE": site.ENABLE_USER_SITE,
    "imports": records,
}}, sort_keys=True))
"""


def run_wheel_venv_scenario(
    *,
    wheel_record: Mapping[str, Any],
    repo_root: Path,
    out_dir: Path,
    timeout_s: int,
) -> dict[str, Any]:
    """Install and probe the exact wheel in a separate fresh virtualenv."""

    scenario_started = time.monotonic()
    deadline = scenario_started + timeout_s
    wheel = Path(str(wheel_record["path"])).resolve()
    actual_hash = sha256_file(wheel)
    if actual_hash != wheel_record["sha256"]:
        raise CleanInstallGateError(
            "wheel changed after Phase A: expected "
            f"{wheel_record['sha256']}, got {actual_hash}"
        )
    venv_dir = out_dir / "wheel_venv"
    _safe_remove_runtime_tree(venv_dir, out_dir=out_dir)
    env, delta = build_sanitized_env()
    record: dict[str, Any] = {
        "status": "started",
        "wheel": str(wheel),
        "wheel_sha256_reverified": actual_hash,
        "venv": str(venv_dir),
        "commands": [],
        "started_at": utc_now(),
        "timeout_s": timeout_s,
    }

    def run(name: str, command: Sequence[str]) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log_path = out_dir / f"wheel_venv_{name}.log"
            log_path.write_text("scenario timeout expired before launch\n")
            result = {
                "command": list(command),
                "cwd": str(out_dir),
                "env_delta": delta,
                "started_at": utc_now(),
                "finished_at": utc_now(),
                "duration_s": 0.0,
                "returncode": None,
                "timed_out": True,
                "timeout_s": 0,
                "log_path": str(log_path),
                "status": "failed",
            }
            record["commands"].append(result)
            return result
        result = run_subprocess(
            command,
            env=env,
            env_delta=delta,
            cwd=out_dir,
            timeout_s=max(1, math.ceil(remaining)),
            log_path=out_dir / f"wheel_venv_{name}.log",
        )
        record["commands"].append(result)
        return result

    def finish(status: str) -> dict[str, Any]:
        record["status"] = status
        record["finished_at"] = utc_now()
        record["duration_s"] = round(time.monotonic() - scenario_started, 3)
        return record

    create = run(
        "create",
        [shutil.which("python3") or "python3", "-m", "venv", str(venv_dir)],
    )
    if create["status"] != "passed":
        return finish("failed")
    python = venv_dir / "bin" / "python"
    install = run(
        "install", [str(python), "-m", "pip", "install", "--no-cache-dir", str(wheel)]
    )
    if install["status"] != "passed":
        return finish("failed")

    capabilities = run(
        "capabilities",
        [str(python), "-m", PACKAGE_NAME, "capabilities", "--json"],
    )
    provenance = run("provenance", [str(python), "-c", _wheel_provenance_code()])
    version = run("version", [str(python), "-m", PACKAGE_NAME, "--version"])
    freeze = run("pip_freeze", [str(python), "-m", "pip", "freeze", "--all"])
    freeze_path = out_dir / "wheel_venv_pip_freeze.txt"
    shutil.copyfile(freeze["log_path"], freeze_path)
    record["pip_freeze_path"] = str(freeze_path)

    errors: list[str] = []
    try:
        capabilities_payload = json.loads(Path(capabilities["log_path"]).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        capabilities_payload = None
        errors.append(f"invalid capabilities JSON: {exc}")
    record["capabilities"] = capabilities_payload
    try:
        provenance_payload = json.loads(Path(provenance["log_path"]).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        provenance_payload = None
        errors.append(f"invalid provenance JSON: {exc}")
    record["provenance"] = provenance_payload

    if any(item["status"] != "passed" for item in record["commands"]):
        errors.append("one or more wheel-venv subprocesses failed")
    if provenance_payload is not None:
        if provenance_payload.get("site_ENABLE_USER_SITE") is not False:
            errors.append("wheel venv site.ENABLE_USER_SITE is not false")
        imports = provenance_payload.get("imports", {})
        for name in (PACKAGE_NAME, "numpy"):
            item = imports.get(name, {})
            origin = item.get("origin")
            if (
                item.get("status") != "present"
                or not origin
                or not _is_under(origin, venv_dir)
            ):
                errors.append(f"{name} did not resolve inside the wheel venv: {origin}")
            if (
                origin
                and _is_under(origin, repo_root)
                and not _is_under(origin, venv_dir)
            ):
                errors.append(f"{name} resolved from the repository checkout: {origin}")
        for name in ("scipy", "soundfile", "pyroomacoustics"):
            if imports.get(name, {}).get("status") != "absent":
                errors.append(
                    f"{name} must be explicitly absent in the base wheel venv"
                )
    version_text = Path(version["log_path"]).read_text(encoding="utf-8").strip()
    record["version_output"] = version_text
    if version_text != PACKAGE_VERSION:
        errors.append(
            f"wheel version output is {version_text!r}, expected {PACKAGE_VERSION!r}"
        )
    record["errors"] = errors
    return finish("failed" if errors else "passed")


def aggregate_verdict(
    *,
    requested_scenarios: Sequence[str],
    scenario_records: Mapping[str, Mapping[str, Any]],
    artifacts_verified: bool,
    preflight_completed: bool,
    restore_completed: bool,
) -> str:
    """Return passed only when all mandatory phases and requested scenarios pass."""

    scenarios_passed = all(
        scenario_records.get(name, {}).get("status") == "passed"
        for name in requested_scenarios
    )
    return (
        "passed"
        if artifacts_verified
        and preflight_completed
        and restore_completed
        and scenarios_passed
        else "failed"
    )


def _parse_scenarios(value: str) -> list[str]:
    scenarios = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(scenarios) - SCENARIO_NAMES)
    if not scenarios or unknown:
        allowed = ", ".join(sorted(SCENARIO_NAMES))
        raise argparse.ArgumentTypeError(
            "scenarios must be a non-empty comma-list from "
            f"{{{allowed}}}; unknown={unknown}"
        )
    if len(scenarios) != len(set(scenarios)):
        raise argparse.ArgumentTypeError("scenario names must not be repeated")
    return scenarios


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--isaac-root", type=Path, default=Path("/home/pacquadr/isaacsim")
    )
    parser.add_argument("--app", type=Path, default=Path("apps/isaacsim.exp.base.kit"))
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/S1/S1.6"),
    )
    parser.add_argument(
        "--scenarios",
        type=_parse_scenarios,
        default=_parse_scenarios(DEFAULT_SCENARIOS),
    )
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--skip-restore", action="store_true")
    parser.add_argument("--keep-clean-env", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")
    return args


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    isaac_root = args.isaac_root.expanduser().resolve()
    app_path = args.app if args.app.is_absolute() else isaac_root / args.app
    app_path = app_path.resolve()
    dist_dir = args.dist_dir.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_env = out_dir / "clean_env"
    inventory_path = out_dir / "preflight_inventory.json"
    verdict_path = out_dir / "clean_install_gate.json"
    evidence: dict[str, Any] = {
        "status": "started",
        "phase": "A",
        "started_at": utc_now(),
        "repo_root": str(repo_root),
        "isaac_root": str(isaac_root),
        "app": str(app_path),
        "dist_dir": str(dist_dir),
        "out_dir": str(out_dir),
        "requested_scenarios": args.scenarios,
        "timeout_s": args.timeout_s,
        "artifacts": {},
        "preflight": {},
        "staging": [],
        "scenarios": {},
        "errors": [],
    }
    inventory: dict[str, Any] | None = None
    artifacts_verified = False
    preflight_completed = False
    restore_completed = False

    try:
        artifacts = verify_release_artifacts(dist_dir)
        evidence["artifacts"] = artifacts
        artifacts_verified = True

        evidence["phase"] = "B"
        inventory = {}
        neutralize_preflight(
            isaac_root=isaac_root,
            kit_data_root=Path.home() / ".local/share/ov/data/Kit",
            backup_dir=out_dir / "preflight_backup",
            inventory_record=inventory,
        )
        _write_json(inventory_path, inventory)
        inventory["isaac_python_probe"] = probe_isaac_python(
            isaac_root=isaac_root, out_dir=out_dir, timeout_s=args.timeout_s
        )
        if inventory["isaac_python_probe"]["import_status"] != "absent":
            raise CleanInstallGateError(
                "isaac_audio_sensors is installed in Isaac Python; uninstall it "
                "before rerunning the gate. Provenance is recorded in "
                f"{inventory['isaac_python_probe']['log_path']}. The gate "
                "deliberately does not modify Isaac Python."
            )
        if inventory["isaac_python_probe"]["status"] != "passed":
            raise CleanInstallGateError(
                "Isaac Python absence probe did not complete successfully; see "
                f"{inventory['isaac_python_probe']['log_path']}"
            )
        preflight_completed = True
        evidence["preflight"] = {
            "status": "completed",
            "inventory_path": str(inventory_path),
            "extension_entries_neutralized": len(
                inventory["neutralized"]["extension_entries"]
            ),
            "user_configs_neutralized": len(inventory["neutralized"]["user_configs"]),
            "isaac_python_import": "absent",
        }
        _write_json(inventory_path, inventory)

        evidence["phase"] = "C"
        staging = stage_kit_extension(
            archive_path=artifacts["kit_zip"]["path"],
            clean_env=clean_env,
            out_dir=out_dir,
        )
        evidence["staging"].append({"reason": "initial", **staging})

        evidence["phase"] = "D"
        for scenario in args.scenarios:
            if scenario in {"reinstall", "gui"}:
                staging = stage_kit_extension(
                    archive_path=artifacts["kit_zip"]["path"],
                    clean_env=clean_env,
                    out_dir=out_dir,
                )
                evidence["staging"].append({"reason": scenario, **staging})
            if scenario == "wheel-venv":
                result = run_wheel_venv_scenario(
                    wheel_record=artifacts["wheel"],
                    repo_root=repo_root,
                    out_dir=out_dir,
                    timeout_s=args.timeout_s,
                )
            else:
                result = run_kit_scenario(
                    scenario=scenario,
                    isaac_root=isaac_root,
                    app_path=app_path,
                    repo_root=repo_root,
                    out_dir=out_dir,
                    clean_env=clean_env,
                    timeout_s=args.timeout_s,
                )
            evidence["scenarios"][scenario] = result
            if result.get("status") != "passed":
                raise CleanInstallGateError(f"scenario {scenario!r} failed")
    except Exception as exc:  # noqa: BLE001 - verdict records every gate failure.
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        evidence["phase"] = "E"
        if inventory is None:
            evidence["restore"] = {
                "status": "not_required",
                "reason": "preflight did not begin",
            }
            restore_completed = True
        elif args.skip_restore:
            inventory["restore_status"] = "skipped_by_request"
            inventory["after_restore"] = None
            evidence["restore"] = {"status": "skipped_by_request"}
            restore_completed = False
        else:
            restore = restore_preflight(inventory)
            evidence["restore"] = restore
            restore_completed = restore["status"] == "restored"
            if not restore_completed:
                evidence["errors"].append(
                    "preflight restoration failed: " + "; ".join(restore["errors"])
                )
        if inventory is not None:
            _write_json(inventory_path, inventory)

        if not args.keep_clean_env:
            cleanup: dict[str, Any] = {"status": "passed", "removed": []}
            for path in (clean_env, out_dir / "wheel_venv"):
                try:
                    if path.exists() or path.is_symlink():
                        _safe_remove_runtime_tree(path, out_dir=out_dir)
                        cleanup["removed"].append(str(path))
                except Exception as exc:  # noqa: BLE001 - cleanup is evidence.
                    cleanup["status"] = "failed"
                    cleanup.setdefault("errors", []).append(
                        f"{type(exc).__name__}: {exc}"
                    )
            evidence["clean_env_cleanup"] = cleanup

        evidence["phase"] = "F"
        evidence["finished_at"] = utc_now()
        evidence["status"] = aggregate_verdict(
            requested_scenarios=args.scenarios,
            scenario_records=evidence["scenarios"],
            artifacts_verified=artifacts_verified,
            preflight_completed=preflight_completed,
            restore_completed=restore_completed,
        )
        _write_json(verdict_path, evidence)

    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
