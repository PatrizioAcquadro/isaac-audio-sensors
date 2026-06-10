"""Regenerate the deterministic JSON frame traces under examples/traces/.

The three ``.json`` traces are real backend outputs and must be regenerated
whenever backend physics change. ``diagnostics_provenance_sequence.v1.ndjson``
is hand-authored illustrative replay/live metadata and is not touched here.
"""

from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import build_scene_snapshot, load_audio_config
from isaac_audio_sensors.core.io.traces import write_frame_trace
from isaac_audio_sensors.core.microphone_array import arbitrary_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = REPO_ROOT / "examples" / "traces"
DEMO_CONFIG = REPO_ROOT / "configs" / "isaac_audio_sensors_demo.toml"


def _demo_geometry_frame(
    *,
    timestamp_ms: int,
    start_time_s: float,
    end_time_s: float,
    max_events: int | None,
) -> AudioSensorFrame:
    config = load_audio_config(DEMO_CONFIG)
    scene = build_scene_snapshot(config, timestamp_ms=timestamp_ms)
    sensor = scene.array_by_id("rig_front")
    window = AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        timestamp_ms=timestamp_ms,
        sample_rate_hz=sensor.sample_rate_hz,
        frame_index=0,
        max_events=max_events,
    )
    return get_backend("geometry_only").simulate(scene, sensor, window)


def _two_mic_ambiguity_frame() -> AudioSensorFrame:
    array = arbitrary_microphone_array(
        array_id="stereo_rig",
        prim_path="/World/Rig/StereoAudioArray",
        relative_positions_m=(
            ("left", (0.0, -0.08, 0.0)),
            ("right", (0.0, 0.08, 0.0)),
        ),
    )
    source = AudioSourceSpec(
        source_id="tone_front",
        prim_path="/World/Sources/ToneFront",
        class_label="Tone",
        audio_asset_path="generated://impulse",
        position_world=(5.0, 0.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )
    scene = AudioSceneSnapshot(
        stage_id="two_mic_ambiguity",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.1,
        timestamp_ms=0,
        sample_rate_hz=array.sample_rate_hz,
        frame_index=0,
        max_events=1,
    )
    backend = get_backend("tdoa_synthetic", ambiguity_policy="none")
    return backend.simulate(scene, array, window)


def main() -> int:
    frames = {
        "minimal_frame.v1.json": _demo_geometry_frame(
            timestamp_ms=0,
            start_time_s=0.0,
            end_time_s=0.1,
            max_events=0,
        ),
        "multi_detection_frame.v1.json": _demo_geometry_frame(
            timestamp_ms=500,
            start_time_s=0.5,
            end_time_s=0.75,
            max_events=None,
        ),
        "ambiguity_frame.v1.json": _two_mic_ambiguity_frame(),
    }
    for name, frame in frames.items():
        path = write_frame_trace(frame, TRACE_DIR / name)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
