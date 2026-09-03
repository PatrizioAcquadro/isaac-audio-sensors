"""Deterministic common fixtures for R9.2 candidate qualification."""

from __future__ import annotations

import json
import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE_HZ = 48_000
BLOCK_SAMPLES = 960
BLOCK_DURATION_MS = 20.0
REPEAT_COUNT = 5
QUAD_FRONT_SPACING_M = 0.16
MICROPHONE_IDS = ("front", "right", "rear", "left")
QUAD_FRONT_OFFSETS_M = (
    (0.08, 0.0, 0.0),
    (0.0, -0.08, 0.0),
    (-0.08, 0.0, 0.0),
    (0.0, 0.08, 0.0),
)
IAS_TRANSMISSION_FREQUENCIES_HZ = (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0)
STEAM_AUDIO_BAND_FREQUENCIES_HZ = (400.0, 2500.0, 15000.0)
IAS_REFERENCE_TRANSMISSION_LOSS_DB = (6.0, 12.0, 18.0, 24.0, 30.0, 36.0)


@dataclass(frozen=True, slots=True)
class BarrierSpec:
    """One authored physical partition or whole acoustic assembly."""

    assembly_id: str
    center_xyz_m: tuple[float, float, float]
    size_xyz_m: tuple[float, float, float]
    transmission_loss_db: tuple[float, ...] = (12.0,) * 6


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """Provider-neutral geometry and expected semantic role."""

    fixture_id: str
    category: str
    source_xyz_m: tuple[float, float, float]
    array_xyz_m: tuple[float, float, float]
    barriers: tuple[BarrierSpec, ...] = ()
    door_open: bool | None = None
    dynamic_target: str | None = None
    signal: str = "impulse"


def _partition(
    assembly_id: str,
    x_m: float,
    *,
    width_m: float = 4.0,
    y_m: float = 0.0,
    loss_db: float = 12.0,
) -> BarrierSpec:
    return BarrierSpec(
        assembly_id=assembly_id,
        center_xyz_m=(x_m, y_m, 1.5),
        size_xyz_m=(0.10, width_m, 3.0),
        transmission_loss_db=(loss_db,) * 6,
    )


def common_fixtures() -> tuple[FixtureSpec, ...]:
    """Return the complete ordered fixture inventory used by both adapters."""

    fragmented = tuple(
        _partition("partition", 1.5, width_m=1.0, y_m=y_m)
        for y_m in (-1.5, -0.5, 0.5, 1.5)
    )
    return (
        FixtureSpec("phase_impulse", "signal", (3.0, 0.6, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec(
            "phase_multitone",
            "signal",
            (3.0, 0.6, 1.2),
            (0.0, 0.0, 1.2),
            signal="multitone",
        ),
        FixtureSpec("distance_1_5m", "amplitude", (1.5, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("distance_3m", "amplitude", (3.0, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("distance_6m", "amplitude", (6.0, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec(
            "direct_path",
            "propagation",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            signal="multitone",
        ),
        FixtureSpec(
            "occlusion",
            "propagation",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5),),
        ),
        FixtureSpec(
            "reflection",
            "propagation",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("reflector", 1.5, y_m=2.0, loss_db=0.0),),
        ),
        FixtureSpec(
            "transmission",
            "propagation",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (
                BarrierSpec(
                    "partition",
                    (1.5, 0.0, 1.5),
                    (0.10, 4.0, 3.0),
                    IAS_REFERENCE_TRANSMISSION_LOSS_DB,
                ),
            ),
            signal="multitone",
        ),
        FixtureSpec(
            "l_corner",
            "propagation",
            (3.0, 2.0, 1.2),
            (0.0, 0.0, 1.2),
            (
                _partition("corner_x", 1.5),
                _partition("corner_y", 3.0, width_m=3.0, y_m=1.5),
            ),
        ),
        FixtureSpec(
            "connected_rooms_closed",
            "connected_space",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("shared_wall", 1.5),),
            door_open=False,
        ),
        FixtureSpec(
            "connected_rooms_open",
            "connected_space",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("shared_wall", 1.5),),
            door_open=True,
        ),
        FixtureSpec(
            "assembly_mono",
            "assembly",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5),),
            signal="multitone",
        ),
        FixtureSpec(
            "assembly_fragmented",
            "assembly",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            fragmented,
            signal="multitone",
        ),
        FixtureSpec(
            "assembly_two_partitions",
            "assembly",
            (4.5, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition_a", 1.5), _partition("partition_b", 3.0)),
            signal="multitone",
        ),
        FixtureSpec(
            "assembly_double_leaf",
            "assembly",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("double_leaf_whole", 1.5),),
            signal="multitone",
        ),
        FixtureSpec(
            "transmission_12db",
            "transmission",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5, loss_db=12.0),),
            signal="multitone",
        ),
        FixtureSpec(
            "transmission_60db",
            "transmission",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5, loss_db=60.0),),
            signal="multitone",
        ),
        FixtureSpec(
            "move_door",
            "dynamics",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("door", 1.5),),
            dynamic_target="door",
        ),
        FixtureSpec(
            "move_source",
            "dynamics",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            dynamic_target="source",
        ),
        FixtureSpec(
            "move_array",
            "dynamics",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            dynamic_target="array",
        ),
        FixtureSpec(
            "move_large_object",
            "dynamics",
            (4.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("large_object", 2.0),),
            dynamic_target="large_object",
        ),
    )


def generated_impulse() -> NDArray[np.float32]:
    signal = np.zeros(BLOCK_SAMPLES, dtype=np.float32)
    signal[128] = 1.0
    return signal


def generated_multitone() -> NDArray[np.float32]:
    time_s = np.arange(BLOCK_SAMPLES, dtype=np.float64) / SAMPLE_RATE_HZ
    signal = sum(
        np.sin(2.0 * math.pi * frequency_hz * time_s)
        for frequency_hz in (250.0, 1000.0, 4000.0)
    )
    signal = np.asarray(signal / 3.0, dtype=np.float32)
    signal.setflags(write=False)
    return signal


def _write_wav(path: Path, samples: NDArray[np.float32]) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE_HZ)
        output.writeframes(pcm.tobytes())


def _fixture_usda(fixture: FixtureSpec) -> str:
    barrier_prims = []
    for index, barrier in enumerate(fixture.barriers):
        cx, cy, cz = barrier.center_xyz_m
        sx, sy, sz = barrier.size_xyz_m
        barrier_prims.append(
            f'''    def Cube "barrier_{index:02d}" (
        customData = {{ string assembly_id = "{barrier.assembly_id}" }}
    )
    {{
        double size = 1
        double3 xformOp:scale = ({sx}, {sy}, {sz})
        double3 xformOp:translate = ({cx}, {cy}, {cz})
        uniform token[] xformOpOrder = ["xformOp:scale", "xformOp:translate"]
        custom double[] ias:transmissionLossDb = {list(barrier.transmission_loss_db)}
    }}'''
        )
    sx, sy, sz = fixture.source_xyz_m
    ax, ay, az = fixture.array_xyz_m
    return f"""#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{{
    def Xform "source"
    {{
        double3 xformOp:translate = ({sx}, {sy}, {sz})
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }}
    def Xform "quad_front"
    {{
        double3 xformOp:translate = ({ax}, {ay}, {az})
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }}
{chr(10).join(barrier_prims)}
}}
"""


def write_fixture_assets(output_dir: Path) -> dict[str, Path]:
    """Write common USD, signal, and manifest assets below ``output_dir``."""

    fixtures_dir = output_dir / "fixtures"
    signals_dir = output_dir / "signals"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    signals_dir.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Path] = {}
    fixtures = common_fixtures()
    for fixture in fixtures:
        path = fixtures_dir / f"{fixture.fixture_id}.usda"
        path.write_text(_fixture_usda(fixture), encoding="utf-8")
        assets[fixture.fixture_id] = path
    impulse_path = signals_dir / "impulse.wav"
    multitone_path = signals_dir / "multitone.wav"
    _write_wav(impulse_path, generated_impulse())
    _write_wav(multitone_path, generated_multitone())
    manifest = {
        "block_samples": BLOCK_SAMPLES,
        "fixtures": [asdict(fixture) for fixture in fixtures],
        "microphone_ids": list(MICROPHONE_IDS),
        "quad_front_offsets_m": [list(offset) for offset in QUAD_FRONT_OFFSETS_M],
        "repeat_count": REPEAT_COUNT,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "signals": {"impulse": str(impulse_path), "multitone": str(multitone_path)},
    }
    manifest_path = output_dir / "fixture_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assets["manifest"] = manifest_path
    return assets
