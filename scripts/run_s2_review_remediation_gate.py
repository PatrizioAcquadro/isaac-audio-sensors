#!/usr/bin/env python3
"""Regenerate pure S2 review-remediation evidence from executable gates."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = (
    REPO_ROOT / "outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json"
)


def _run_gate(
    name: str,
    command: list[str],
    *,
    log_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_path = log_dir / f"{name}.txt"
    log_path.write_text(result.stdout, encoding="utf-8")
    return {
        "name": name,
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "duration_s": round(time.monotonic() - started, 6),
        "command": command,
        "log": str(log_path.relative_to(REPO_ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--python",
        type=Path,
        default=REPO_ROOT / ".venv/bin/python",
    )
    parser.add_argument(
        "--flac-python",
        type=Path,
        default=Path(
            os.environ.get(
                "ISAAC_SIM_COMMAND",
                str(Path.home() / "isaacsim/python.sh"),
            )
        ),
    )
    args = parser.parse_args()
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    log_dir = output.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    python = str(args.python.expanduser().absolute())
    flac_python = str(args.flac_python.expanduser().absolute())
    definitions = (
        (
            "manifest_finalization_recovery",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/test_dataset_recorder.py::"
                "test_fresh_process_recovers_enospc_during_manifest_finalization",
            ],
        ),
        (
            "device_calibration_shared_validation",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/test_validation_controller.py::"
                "test_device_and_calibration_results_match_gui_and_headless",
                "tests/test_validation_controller.py::"
                "test_device_and_calibration_checks_never_answer_from_stale_state",
            ],
        ),
        (
            "flac_export_replay",
            [flac_python, "-m", "pytest", "-q", "tests/test_dataset_flac.py"],
        ),
        (
            "guided_reset_boundaries",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/test_guided_workflow.py::"
                "test_guided_recording_marks_explicit_and_detected_simulator_resets",
            ],
        ),
        (
            "audio_parity_metrics",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/test_headless_parity.py::"
                "test_semantic_diff_equal_sessions_exit_zero_and_normalizes_provenance",
            ],
        ),
    )
    gates = [
        _run_gate(name, command, log_dir=log_dir)
        for name, command in definitions
    ]
    manifest_bytes = (REPO_ROOT / "MANIFEST.in").read_bytes()
    manifest_format = {
        "name": "manifest_in_trailing_blank_line",
        "status": (
            "passed"
            if manifest_bytes.endswith(b"\n")
            and not manifest_bytes.endswith(b"\n\n")
            else "failed"
        ),
        "ends_with_one_newline": (
            manifest_bytes.endswith(b"\n")
            and not manifest_bytes.endswith(b"\n\n")
        ),
    }
    gates.append(manifest_format)
    passed = all(gate["status"] == "passed" for gate in gates)
    evidence = {
        "status": "passed" if passed else "failed",
        "acceptance_criteria_changed": False,
        "manifest_failure_phases": [
            "manifest temporary-file write",
            "manifest atomic replace",
            "manifest temporary-file fsync",
            "session-root directory fsync after replace",
        ],
        "fresh_process_recovery": True,
        "flac_declared_dtypes": ["int16", "int24"],
        "gates": gates,
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
