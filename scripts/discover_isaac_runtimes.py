"""Discover likely Isaac Sim and Isaac Lab launch commands."""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    print(json.dumps(discover(), indent=2, sort_keys=True))
    return 0


def discover() -> dict[str, object]:
    home = Path.home()
    sim_candidates = _env_candidates(
        "ISAAC_SIM_PYTHON",
        "ISAACSIM_PYTHON",
    ) + _existing(
        [
            home / "Desktop/isaac_suitcase/miniforge3/envs/env_isaaclab/bin/python",
            home / "isaacsim" / "python.sh",
            home / ".local/share/ov/pkg/isaac-sim-5.1.0/python.sh",
            home / ".local/share/ov/pkg/isaac-sim-5.0.0/python.sh",
            Path("/opt/nvidia/isaacsim/python.sh"),
            Path("/isaac-sim/python.sh"),
        ]
    )
    for env_name in ("ISAAC_SIM_PATH", "ISAACSIM_PATH"):
        value = os.environ.get(env_name)
        if value:
            sim_candidates.extend(_existing([Path(value) / "python.sh"]))

    sim_launch_candidates = _env_candidates(
        "ISAAC_SIM_COMMAND",
        "ISAACSIM_COMMAND",
    ) + _existing(
        [
            home / "Desktop/isaac_suitcase/miniforge3/envs/env_isaaclab/bin/isaacsim",
            home / "isaacsim/isaac-sim.sh",
            home / ".local/share/ov/pkg/isaac-sim-5.1.0/isaac-sim.sh",
            home / ".local/share/ov/pkg/isaac-sim-5.0.0/isaac-sim.sh",
            Path("/opt/nvidia/isaacsim/isaac-sim.sh"),
            Path("/isaac-sim/isaac-sim.sh"),
        ]
    )

    lab_candidates = _env_candidates(
        "ISAAC_LAB_PYTHON",
        "ISAACLAB_PYTHON",
    ) + _existing(
        [
            home / "Desktop/isaac_suitcase/miniforge3/envs/env_isaaclab/bin/python",
            home / "Desktop/isaac_suitcase/IsaacLab/isaaclab.sh -p",
            home / "IsaacLab/isaaclab.sh -p",
            home / "isaaclab/isaaclab.sh -p",
            home / "IsaacLab/_isaac_sim/python.sh",
            home / "isaaclab/_isaac_sim/python.sh",
        ]
    )
    for env_name in ("ISAAC_LAB_PATH", "ISAACLAB_PATH"):
        value = os.environ.get(env_name)
        if value:
            lab_candidates.extend(
                _existing(
                    [
                        Path(value) / "isaaclab.sh -p",
                        Path(value) / "_isaac_sim/python.sh",
                    ]
                )
            )

    return {
        "environment": {
            key: os.environ[key]
            for key in sorted(os.environ)
            if key.startswith(("ISAAC", "OMNI", "EXP_PATH", "CARB_APP_PATH"))
        },
        "isaac_sim_launch_candidates": _dedupe(sim_launch_candidates),
        "isaac_sim_python_candidates": _dedupe(sim_candidates),
        "isaac_lab_python_candidates": _dedupe(lab_candidates),
    }


def _env_candidates(*names: str) -> list[str]:
    return [os.environ[name] for name in names if os.environ.get(name)]


def _existing(paths: list[Path]) -> list[str]:
    commands: list[str] = []
    for path in paths:
        path_text = str(path)
        command_path = path_text.split(" ", 1)[0]
        if Path(command_path).exists():
            commands.append(path_text)
    return commands


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


if __name__ == "__main__":
    raise SystemExit(main())
