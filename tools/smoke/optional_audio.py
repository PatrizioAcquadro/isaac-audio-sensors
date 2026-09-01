from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import scipy
import soundfile

from isaac_audio_sensors.core.acoustics import (
    polygon_prism_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)


def main() -> int:
    samples = np.linspace(-0.5, 0.5, 256, dtype=np.float32)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "codec.flac"
        soundfile.write(path, samples, 16_000, format="FLAC")
        restored, sample_rate_hz = soundfile.read(path, dtype="float32")
    room = pra.ShoeBox((3.0, 3.0, 2.5), fs=16_000, max_order=0)
    room.add_source((1.0, 1.0, 1.0), signal=samples)
    room.add_microphone((2.0, 1.0, 1.0))
    room.simulate()
    assert sample_rate_hz == 16_000
    assert restored.shape == samples.shape
    assert np.asarray(room.mic_array.signals).size > 0
    analytic_solvers = _exercise_analytic_rooms()
    print(
        json.dumps(
            {
                "pyroomacoustics": pra.__version__,
                "scipy": scipy.__version__,
                "soundfile": soundfile.__version__,
                "analytic_solvers": analytic_solvers,
                "status": "passed",
            },
            sort_keys=True,
        )
    )
    return 0


def _exercise_analytic_rooms() -> list[str]:
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=(1.0, 1.0, 1.0),
        sample_rate_hz=16_000,
    )
    source = AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=(2.0, 1.0, 1.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=0.05,
        gain_db=0.0,
    )
    window = AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.05,
        timestamp_ms=0,
        sample_rate_hz=16_000,
        frame_index=0,
    )
    environments = (
        shoebox_environment(
            environment_id="optional_shoebox",
            dimensions_m=(4.0, 3.0, 2.5),
            absorption=0.3,
        ),
        polygon_prism_environment(
            environment_id="optional_concave_prism",
            floor_vertices_local_m=(
                (0.0, 0.0, 0.0),
                (4.0, 0.0, 0.0),
                (4.0, 3.0, 0.0),
                (2.0, 2.0, 0.0),
                (0.0, 3.0, 0.0),
            ),
            height_m=2.5,
            absorption="pra.rough_concrete",
        ),
    )
    solver_ids: list[str] = []
    for environment in environments:
        scene = AudioSceneSnapshot(
            stage_id="optional_audio_smoke",
            timestamp_ms=0,
            sources=(source,),
            arrays=(array,),
            environment=environment,
        )
        frame = AnalyticAcoustics(max_order=1).simulate(scene, "rig", window)
        solver_ids.append(str(frame.diagnostics["analytic_solver"]["solver_id"]))
        assert frame.detections
        assert all(value > 0.0 for value in frame.aggregate_per_mic_rms.values())
    return solver_ids


if __name__ == "__main__":
    raise SystemExit(main())
