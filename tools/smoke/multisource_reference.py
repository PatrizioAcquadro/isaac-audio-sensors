"""Deterministic direct-path scenes for common consumer smoke checks."""

from pathlib import Path


def reference_scenes(root: Path):
    import numpy as np
    import soundfile as sf

    from isaac_audio_sensors.core.acoustics import free_field_environment
    from isaac_audio_sensors.core.types import (
        AudioSceneSnapshot,
        AudioSourceSpec,
        MicrophoneArraySpec,
        MicrophoneSpec,
    )

    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve().relative_to(Path.cwd().resolve())
    rng = np.random.default_rng(350)
    assets = []
    for index in range(2):
        path = root / f"source_{index}.wav"
        sf.write(path, rng.normal(0, 0.08, 16000), 16000, subtype="FLOAT")
        assets.append(str(path))
    layouts = {
        "triangle": ((-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0)),
        "square": (
            (-0.033, -0.033, 0),
            (-0.033, 0.033, 0),
            (0.033, 0.033, 0),
            (0.033, -0.033, 0),
        ),
        "raised": (
            (-0.03, -0.03, 0),
            (-0.03, 0.03, 0),
            (0.03, 0.03, 0),
            (0.03, -0.03, 0),
            (0, 0, 0.04),
        ),
        "tetra": (
            (0.03, 0.03, 0.03),
            (0.03, -0.03, -0.03),
            (-0.03, 0.03, -0.03),
            (-0.03, -0.03, 0.03),
        ),
    }
    scenes = []
    for name, positions in layouts.items():
        array = MicrophoneArraySpec(
            array_id=name,
            prim_path=f"/World/{name}",
            position_world=(0, 0, 0),
            orientation_world_quat=(0, 0, 0, 1),
            sample_rate_hz=16000,
            microphones=tuple(
                MicrophoneSpec(mic_id=f"m{i}", relative_position_m=p)
                for i, p in enumerate(positions)
            ),
        )
        sources = []
        for i, (az, el) in enumerate(((20, 15), (100, -25))):
            a, e = np.radians([az, el if name in ("raised", "tetra") else 0])
            position = tuple(
                1.5
                * np.array([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])
            )
            sources.append(
                AudioSourceSpec(
                    source_id=f"source_{i}",
                    prim_path=f"/World/Source{i}",
                    class_label="Sound",
                    audio_asset_path=assets[i],
                    position_world=position,
                    orientation_world_quat=(0, 0, 0, 1),
                    start_time_s=0,
                    duration_s=1,
                    gain_db=0,
                )
            )
        scenes.append(
            AudioSceneSnapshot(
                stage_id=name,
                arrays=(array,),
                sources=tuple(sources),
                environment=free_field_environment(environment_id=f"{name}_free_field"),
            )
        )
    return tuple(scenes)
