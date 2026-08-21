"""Collect local Isaac Sim GPU, display, and audio diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from security_redaction import redact_text, redact_value_for_key

DEFAULT_OUT_DIR = Path("build/validation/isaac_audio_sensors/diagnostics")
MAX_TEXT_CHARS = 120_000


@dataclass(frozen=True, slots=True)
class CommandSpec:
    key: str
    argv: tuple[str, ...]
    timeout_s: int = 30


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect non-destructive GPU/display/audio probes for Isaac Sim "
            "5.1 troubleshooting."
        )
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    commands = _collect_commands(args.out_dir)
    path_probes = _collect_path_probes()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": _collect_environment(),
        "path_probes": path_probes,
        "commands": commands,
    }
    report["summary"] = _summarize(report)

    report_path = args.out_dir / "diagnostics.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(f"Wrote {report_path}")
    return 0


def _diagnostic_commands() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec("nvidia_smi", ("nvidia-smi",), timeout_s=20),
        CommandSpec("lspci_nn", ("lspci", "-nn")),
        CommandSpec("lsmod", ("lsmod",)),
        CommandSpec("ubuntu_drivers_devices", ("ubuntu-drivers", "devices")),
        CommandSpec("vulkaninfo_summary", ("vulkaninfo", "--summary"), timeout_s=20),
        CommandSpec("glxinfo_b", ("glxinfo", "-B"), timeout_s=20),
        CommandSpec("aplay_l", ("aplay", "-l")),
        CommandSpec("pactl_info", ("pactl", "info")),
        CommandSpec("pactl_sinks", ("pactl", "list", "short", "sinks")),
        CommandSpec("pipewire_version", ("pipewire", "--version")),
        CommandSpec("pw_cli_info_all", ("pw-cli", "info", "all"), timeout_s=20),
        CommandSpec("uname_a", ("uname", "-a")),
        CommandSpec("mokutil_sb_state", ("mokutil", "--sb-state")),
        CommandSpec("dkms_status", ("dkms", "status")),
        CommandSpec("id_groups", ("id", "-nG")),
        CommandSpec(
            "journalctl_kernel_tail",
            ("journalctl", "-k", "-b", "--no-pager", "-n", "250"),
            timeout_s=20,
        ),
        CommandSpec(
            "journalctl_user_tail",
            ("journalctl", "--user", "-b", "--no-pager", "-n", "160"),
            timeout_s=20,
        ),
    )


def _collect_commands(out_dir: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for spec in _diagnostic_commands():
        result = _run_command(spec)
        results[spec.key] = result
        _write_command_text(out_dir / f"{spec.key}.txt", spec, result)
    return results


def _run_command(spec: CommandSpec) -> dict[str, Any]:
    executable = shutil.which(spec.argv[0])
    if executable is None:
        return {
            "argv": list(spec.argv),
            "status": "missing",
            "exit_code": None,
            "stdout": "",
            "stderr": f"{spec.argv[0]} was not found on PATH.",
        }
    try:
        completed = subprocess.run(
            spec.argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=spec.timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": list(spec.argv),
            "status": "timeout",
            "exit_code": None,
            "stdout": _redact_and_clip(exc.stdout or ""),
            "stderr": _redact_and_clip(exc.stderr or ""),
        }
    except OSError as exc:
        return {
            "argv": list(spec.argv),
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": _redact_and_clip(f"{type(exc).__name__}: {exc}"),
        }
    return {
        "argv": list(spec.argv),
        "status": "ran",
        "exit_code": completed.returncode,
        "stdout": _redact_and_clip(completed.stdout),
        "stderr": _redact_and_clip(completed.stderr),
    }


def _write_command_text(
    path: Path,
    spec: CommandSpec,
    result: dict[str, Any],
) -> None:
    path.write_text(
        "\n".join(
            (
                f"$ {' '.join(spec.argv)}",
                f"status: {result['status']}",
                f"exit_code: {result['exit_code']}",
                "",
                "stdout:",
                _redact_and_clip(result["stdout"]),
                "",
                "stderr:",
                _redact_and_clip(result["stderr"]),
                "",
            )
        ),
        encoding="utf-8",
    )


def _collect_environment() -> dict[str, str | None]:
    names = (
        "DISPLAY",
        "XDG_SESSION_TYPE",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "PULSE_SERVER",
        "PIPEWIRE_REMOTE",
        "XDG_RUNTIME_DIR",
        "OMNI_KIT_ACCEPT_EULA",
    )
    return {name: redact_value_for_key(name, os.environ.get(name)) for name in names}


def _collect_path_probes() -> dict[str, dict[str, Any]]:
    uid = os.getuid()
    paths = [
        Path("/dev/nvidia0"),
        Path("/dev/nvidiactl"),
        Path("/dev/nvidia-uvm"),
        Path("/dev/dri"),
        Path("/dev/dri/card0"),
        Path("/dev/dri/renderD128"),
        Path("/dev/snd"),
        Path(f"/run/user/{uid}/pulse/native"),
        Path(f"/run/user/{uid}/pipewire-0"),
        Path("/proc/driver/nvidia/version"),
        Path("/sys/module/nvidia/version"),
        Path("/proc/cmdline"),
    ]
    for info_path in Path("/proc/driver/nvidia/gpus").glob("*/information"):
        paths.append(info_path)
    return {str(path): _probe_path(path) for path in paths}


def _probe_path(path: Path) -> dict[str, Any]:
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        return {"exists": False}
    except OSError as exc:
        return {"exists": False, "error": f"{type(exc).__name__}: {exc}"}

    mode = file_stat.st_mode
    kind = "other"
    if stat.S_ISDIR(mode):
        kind = "directory"
    elif stat.S_ISCHR(mode):
        kind = "char_device"
    elif stat.S_ISREG(mode):
        kind = "file"
    elif stat.S_ISSOCK(mode):
        kind = "socket"

    result: dict[str, Any] = {
        "exists": True,
        "kind": kind,
        "mode": stat.filemode(mode),
        "uid": file_stat.st_uid,
        "gid": file_stat.st_gid,
    }
    if kind == "file" and path.is_file():
        result["text"] = _read_text(path)
    return result


def _read_text(path: Path) -> str:
    try:
        return _redact_and_clip(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return _redact_and_clip(f"{type(exc).__name__}: {exc}")


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    commands: dict[str, dict[str, Any]] = report["commands"]
    env: dict[str, str | None] = report["environment"]
    paths: dict[str, dict[str, Any]] = report["path_probes"]

    nvidia_smi_ok = _exit_ok(commands, "nvidia_smi")
    pci_nvidia_present = "NVIDIA Corporation" in _combined_output(
        commands,
        "lspci_nn",
    )
    nvidia_modules_loaded = any(
        line.startswith("nvidia")
        for line in _combined_output(commands, "lsmod").splitlines()
    )
    nvidia_nodes_present = all(
        paths.get(path, {}).get("exists")
        for path in ("/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm")
    )
    dri_present = paths.get("/dev/dri/renderD128", {}).get("exists", False)
    secure_boot_enabled = (
        "enabled"
        in _combined_output(
            commands,
            "mokutil_sb_state",
        ).lower()
    )
    glx_ok = _exit_ok(commands, "glxinfo_b")
    vulkan_ok = _exit_ok(commands, "vulkaninfo_summary")
    aplay_output = _combined_output(commands, "aplay_l").lower()
    alsa_cards_visible = "card " in aplay_output and "no soundcards" not in aplay_output
    pactl_ok = _exit_ok(commands, "pactl_info")
    audio_socket_present = paths.get(
        f"/run/user/{os.getuid()}/pulse/native",
        {},
    ).get("exists", False) or paths.get(
        f"/run/user/{os.getuid()}/pipewire-0",
        {},
    ).get("exists", False)

    blockers = _blockers(
        pci_nvidia_present=pci_nvidia_present,
        nvidia_modules_loaded=nvidia_modules_loaded,
        nvidia_smi_ok=nvidia_smi_ok,
        nvidia_nodes_present=nvidia_nodes_present,
        dri_present=dri_present,
        display=env.get("DISPLAY"),
        glx_ok=glx_ok,
        vulkan_ok=vulkan_ok,
        secure_boot_enabled=secure_boot_enabled,
        alsa_cards_visible=alsa_cards_visible,
        pactl_ok=pactl_ok,
        audio_socket_present=audio_socket_present,
    )
    return {
        "gpu": {
            "pci_nvidia_present": pci_nvidia_present,
            "nvidia_modules_loaded": nvidia_modules_loaded,
            "nvidia_smi_ok": nvidia_smi_ok,
            "nvidia_device_nodes_present": nvidia_nodes_present,
            "dri_render_node_present": dri_present,
            "secure_boot_enabled": secure_boot_enabled,
        },
        "display": {
            "display": env.get("DISPLAY"),
            "xdg_session_type": env.get("XDG_SESSION_TYPE"),
            "glxinfo_ok": glx_ok,
            "vulkaninfo_ok": vulkan_ok,
        },
        "audio": {
            "alsa_cards_visible": alsa_cards_visible,
            "pactl_info_ok": pactl_ok,
            "audio_socket_present": audio_socket_present,
        },
        "blockers": blockers,
    }


def _blockers(
    *,
    pci_nvidia_present: bool,
    nvidia_modules_loaded: bool,
    nvidia_smi_ok: bool,
    nvidia_nodes_present: bool,
    dri_present: bool,
    display: str | None,
    glx_ok: bool,
    vulkan_ok: bool,
    secure_boot_enabled: bool,
    alsa_cards_visible: bool,
    pactl_ok: bool,
    audio_socket_present: bool,
) -> list[str]:
    blockers: list[str] = []
    if not nvidia_smi_ok:
        if pci_nvidia_present and nvidia_modules_loaded and not nvidia_nodes_present:
            blockers.append(
                "NVIDIA PCI device and kernel modules are visible, but the "
                "/dev/nvidia* nodes are absent or hidden. nvidia-smi cannot "
                "prove CUDA availability until host device-node visibility or "
                "driver initialization is fixed."
            )
        elif pci_nvidia_present and not nvidia_modules_loaded:
            blockers.append(
                "NVIDIA PCI device is visible, but NVIDIA kernel modules are "
                "not loaded for this kernel."
            )
        else:
            blockers.append("nvidia-smi failed; CUDA availability is unproven.")
    if secure_boot_enabled and not nvidia_smi_ok:
        blockers.append(
            "Secure Boot is enabled. If host logs show unsigned-module or "
            "NVRM initialization errors, module signing or a reboot may be "
            "required before Isaac Sim can use CUDA."
        )
    if not dri_present:
        blockers.append(
            "No /dev/dri render node is visible, so GL/Vulkan rendering cannot "
            "be proven from this session."
        )
    if display and (not glx_ok or not vulkan_ok):
        blockers.append(
            f"DISPLAY is set to {display!r}, but GLX or Vulkan probing failed. "
            "This points to display authorization, sandbox/container device "
            "visibility, or driver user-space initialization."
        )
    if not alsa_cards_visible:
        blockers.append(
            "ALSA reports no visible sound cards, so physical audio output is "
            "not available to this session."
        )
    if not pactl_ok:
        suffix = " even though an audio socket exists" if audio_socket_present else ""
        blockers.append(
            "PulseAudio/PipeWire pactl probing failed"
            f"{suffix}; Isaac/Kit will fall back to null audio output until a "
            "usable user audio server and sink are visible."
        )
    return blockers


def _exit_ok(commands: dict[str, dict[str, Any]], key: str) -> bool:
    return commands.get(key, {}).get("exit_code") == 0


def _combined_output(commands: dict[str, dict[str, Any]], key: str) -> str:
    result = commands.get(key, {})
    return f"{result.get('stdout', '')}\n{result.get('stderr', '')}"


def _redact_and_clip(value: Any) -> str:
    return _clip(redact_text(value))


def _clip(value: str | bytes) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= MAX_TEXT_CHARS:
        return value
    return value[:MAX_TEXT_CHARS] + "\n...[truncated]\n"


if __name__ == "__main__":
    raise SystemExit(main())
