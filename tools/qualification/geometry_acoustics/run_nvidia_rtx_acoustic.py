"""Run RTX Acoustic R9.2 qualification in an Isaac Sim application."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

import tomllib


def _default_root() -> Path:
    return Path(os.environ.get("IAS_R9_OUTPUT_ROOT", "build/validation/r9"))


def _gpu_identity(active_gpu: int) -> str:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            f"--id={active_gpu}",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ],
        text=True,
        timeout=10,
    ).strip()
    if not output:
        raise RuntimeError(f"GPU {active_gpu} was not visible from the Isaac runtime.")
    return f"{output}; activeGpu={active_gpu}"


def _package_version(extension_root: Path) -> str:
    manifest = extension_root / "config/extension.toml"
    with manifest.open("rb") as stream:
        payload = tomllib.load(stream)
    try:
        return str(payload["package"]["version"])
    except (KeyError, TypeError) as error:
        raise RuntimeError(f"Missing package.version in {manifest}.") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=_default_root())
    parser.add_argument("--isaac-version", required=True)
    parser.add_argument("--kit-version", required=True)
    parser.add_argument("--hardware", help="Optional expected GPU name fragment.")
    parser.add_argument("--active-gpu", type=int, default=0)
    parser.add_argument("--extension-root", type=Path, required=True)
    args, _ = parser.parse_known_args(argv)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(
        {
            "active_gpu": args.active_gpu,
            "enable_motion_bvh": True,
            "headless": True,
            "physics_gpu": args.active_gpu,
        }
    )
    adapter = None
    try:
        from tools.qualification.geometry_acoustics.evaluation import (
            qualify_nvidia_rtx_acoustic,
        )
        from tools.qualification.geometry_acoustics.fixtures import (
            write_fixture_assets,
        )
        from tools.qualification.geometry_acoustics.nvidia_rtx_acoustic import (
            RtxAcousticAdapter,
        )
        from tools.qualification.geometry_acoustics.reporting import (
            write_candidate_bundle,
        )
        from tools.qualification.geometry_acoustics_contract import evaluate_report

        observed_hardware = _gpu_identity(args.active_gpu)
        if args.hardware and args.hardware.lower() not in observed_hardware.lower():
            raise RuntimeError(
                f"Expected GPU {args.hardware!r}, observed {observed_hardware!r}."
            )
        write_fixture_assets(args.output_root / "common")
        adapter = RtxAcousticAdapter(
            simulation_app=simulation_app,
            runtime={
                "hardware": observed_hardware,
                "isaac_sim_version": args.isaac_version,
                "kit_version": args.kit_version,
                "platform": f"{platform.system().lower()}-{platform.machine()}",
            },
            motion_bvh_enabled=True,
        )
        result = qualify_nvidia_rtx_acoustic(
            adapter,
            license_reference=str(
                args.extension_root
                / "PACKAGE-LICENSES/omni.sensors.nv.acoustic-LICENSE.md"
            ),
            package_reference=str(args.extension_root / "config/extension.toml"),
            package_version=_package_version(args.extension_root),
            captured_arrays=adapter.captured_arrays,
        )
        output_dir = args.output_root / adapter.candidate_id
        write_candidate_bundle(
            output_dir,
            report=result.report,
            measurements=result.measurements,
            arrays=result.arrays,
            provenance=result.provenance,
            log_lines=result.log_lines,
        )
        evaluation = evaluate_report(result.report)
        print(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True))
        return 0 if not evaluation.blocked_gates else 1
    finally:
        if adapter is not None:
            adapter.close()
        simulation_app.close()


if __name__ == "__main__":
    raise SystemExit(main())
