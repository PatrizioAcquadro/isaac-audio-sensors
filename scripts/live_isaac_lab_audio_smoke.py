"""Live Isaac Lab smoke validation for isaac_audio_sensors."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
)
from isaac_audio_sensors.lab import AudioArraySensor, AudioArraySensorCfg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("outputs/isaac_audio_sensors/isaac_lab_live_smoke.json"),
    )
    args = parser.parse_args()
    evidence: dict[str, object] = {
        "python_executable": sys.executable,
        "argv": sys.argv,
        "status": "started",
    }
    try:
        lab_module = _import_lab_runtime()
        evidence["lab_module"] = lab_module
        array = create_microphone_array(
            array_id="rig_front",
            prim_path="/World/Rig/AudioArray",
            layout_name="quad_front",
        )
        snapshot = AudioSceneSnapshot(
            stage_id="isaac_lab_live_smoke",
            timestamp_ms=0,
            sources=(
                AudioSourceSpec(
                    source_id="speaker_front",
                    prim_path="/World/Sources/SpeakerFront",
                    class_label="Speech",
                    audio_asset_path="generated://impulse",
                    position_world=(4.0, 0.0, 0.0),
                    orientation_world_quat=None,
                    start_time_s=0.0,
                    duration_s=1.0,
                    gain_db=0.0,
                ),
            ),
            arrays=(array,),
        )
        scene = SimpleNamespace(
            audio_scene_snapshot=snapshot,
            audio_array_spec=array,
        )
        wrapper = AudioArraySensor.from_lab_scene(
            cfg=AudioArraySensorCfg(
                prim_path="{ENV_REGEX_NS}/Robot/audio_array",
                update_period=0.05,
                backend="tdoa_synthetic",
                microphone_layout="quad_front",
                debug_vis=True,
            ),
            scene=scene,
        )
        data = wrapper.update(sim_time_s=0.0, timestamp_ms=0)
        evidence.update(
            {
                "status": "passed",
                "event_presence": data.event_presence,
                "bearing_deg": data.bearing_deg,
                "bearing_confidence": data.bearing_confidence,
                "ambiguity_mask": data.ambiguity_mask,
                "per_mic_rms": data.per_mic_rms,
            }
        )
    except Exception as exc:  # noqa: BLE001 - smoke evidence records exact error.
        evidence.update(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        _write_evidence(args.out, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 2

    _write_evidence(args.out, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


def _import_lab_runtime() -> str:
    try:
        import isaaclab  # type: ignore

        return f"isaaclab:{getattr(isaaclab, '__file__', 'built-in')}"
    except ImportError:
        pass
    try:
        import omni.isaac.lab  # type: ignore  # noqa: F401

        return "omni.isaac.lab"
    except ImportError as exc:
        raise RuntimeError(
            "Neither isaaclab nor omni.isaac.lab imported in this Python runtime."
        ) from exc


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
