"""Deterministic semantic fixtures for corrected R9.2 qualification."""

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
class AcousticSurfaceSpec:
    """One zero-thickness acoustic boundary belonging to an assembly."""

    assembly_id: str
    center_xyz_m: tuple[float, float, float]
    size_xyz_m: tuple[float, float, float]
    transmission_loss_db: tuple[float, ...] = (60.0,) * 6
    absorption: tuple[float, float, float] = (0.1, 0.1, 0.1)
    scattering: float = 0.05

    def __post_init__(self) -> None:
        if len(self.transmission_loss_db) != len(IAS_TRANSMISSION_FREQUENCIES_HZ):
            raise ValueError("transmission loss must use the six IAS bands.")
        if sum(size == 0.0 for size in self.size_xyz_m) != 1 or any(
            size < 0.0 for size in self.size_xyz_m
        ):
            raise ValueError(
                "an acoustic surface must have exactly one zero dimension."
            )


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """Provider-neutral geometry and expected semantic role."""

    fixture_id: str
    category: str
    source_xyz_m: tuple[float, float, float]
    array_xyz_m: tuple[float, float, float]
    surfaces: tuple[AcousticSurfaceSpec, ...] = ()
    door_open: bool | None = None
    dynamic_target: str | None = None
    signal: str = "impulse"
    reflections: bool = False


def _surface(
    assembly_id: str,
    center_xyz_m: tuple[float, float, float],
    size_xyz_m: tuple[float, float, float],
    *,
    loss_db: float | tuple[float, ...] = 60.0,
) -> AcousticSurfaceSpec:
    losses = (loss_db,) * 6 if isinstance(loss_db, float) else loss_db
    return AcousticSurfaceSpec(assembly_id, center_xyz_m, size_xyz_m, losses)


def _partition(
    assembly_id: str,
    x_m: float,
    *,
    width_m: float = 4.0,
    y_m: float = 0.0,
    height_m: float = 3.0,
    z_m: float = 1.5,
    loss_db: float | tuple[float, ...] = 60.0,
) -> AcousticSurfaceSpec:
    return _surface(
        assembly_id,
        (x_m, y_m, z_m),
        (0.0, width_m, height_m),
        loss_db=loss_db,
    )


def _room_shell(
    assembly_id: str,
    *,
    x_bounds: tuple[float, float] = (-3.0, 3.0),
    y_bounds: tuple[float, float] = (-2.0, 2.0),
    z_bounds: tuple[float, float] = (0.0, 3.0),
) -> tuple[AcousticSurfaceSpec, ...]:
    x0, x1 = x_bounds
    y0, y1 = y_bounds
    z0, z1 = z_bounds
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    sx, sy, sz = x1 - x0, y1 - y0, z1 - z0
    return (
        _surface(assembly_id, (x0, cy, cz), (0.0, sy, sz)),
        _surface(assembly_id, (x1, cy, cz), (0.0, sy, sz)),
        _surface(assembly_id, (cx, y0, cz), (sx, 0.0, sz)),
        _surface(assembly_id, (cx, y1, cz), (sx, 0.0, sz)),
        _surface(assembly_id, (cx, cy, z0), (sx, sy, 0.0)),
        _surface(assembly_id, (cx, cy, z1), (sx, sy, 0.0)),
    )


def _shared_wall(*, door_open: bool) -> tuple[AcousticSurfaceSpec, ...]:
    surfaces = (
        _partition("shared_wall", 0.0, width_m=1.5, y_m=-1.25),
        _partition("shared_wall", 0.0, width_m=1.5, y_m=1.25),
        _partition("shared_wall", 0.0, width_m=1.0, y_m=0.0, height_m=0.8, z_m=2.6),
    )
    if door_open:
        return surfaces
    return surfaces + (
        _partition("door", 0.0, width_m=1.0, y_m=0.0, height_m=2.2, z_m=1.1),
    )


def _connected_room_surfaces(*, door_open: bool) -> tuple[AcousticSurfaceSpec, ...]:
    return _room_shell("connected_room_shell") + _shared_wall(door_open=door_open)


def _corridor_surfaces() -> tuple[AcousticSurfaceSpec, ...]:
    return _room_shell("corridor_shell") + (
        _partition("corner_partition", 0.0, width_m=2.5, y_m=-0.75),
    )


def common_fixtures() -> tuple[FixtureSpec, ...]:
    """Return the corrected fixture inventory in canonical execution order."""

    fragmented = tuple(
        _partition("partition", 1.5, width_m=1.0, y_m=y_m, loss_db=12.0)
        for y_m in (-1.5, -0.5, 0.5, 1.5)
    )
    reflective_room = _room_shell("reflective_room_shell")
    return (
        FixtureSpec("phase_impulse_a", "phase", (3.0, 0.6, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("phase_impulse_b", "phase", (2.4, -1.1, 1.4), (0.0, 0.0, 1.2)),
        FixtureSpec(
            "passive_multitone",
            "signal",
            (3.0, 0.6, 1.2),
            (0.0, 0.0, 1.2),
            signal="multitone",
        ),
        FixtureSpec("distance_1_5m", "amplitude", (1.5, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("distance_3m", "amplitude", (3.0, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("distance_6m", "amplitude", (6.0, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec("direct_path", "direct", (3.0, 0.0, 1.2), (0.0, 0.0, 1.2)),
        FixtureSpec(
            "occlusion_opaque",
            "direct",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("opaque_partition", 1.5),),
        ),
        FixtureSpec(
            "transmission_curve",
            "direct",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5, loss_db=IAS_REFERENCE_TRANSMISSION_LOSS_DB),),
            signal="multitone",
        ),
        FixtureSpec(
            "reflection_control",
            "indirect",
            (2.0, 1.0, 1.2),
            (-2.0, -1.0, 1.2),
            reflections=True,
        ),
        FixtureSpec(
            "reflective_room",
            "indirect",
            (2.0, 1.0, 1.2),
            (-2.0, -1.0, 1.2),
            reflective_room,
            reflections=True,
        ),
        FixtureSpec(
            "l_corridor_nlos",
            "indirect",
            (2.0, -1.0, 1.2),
            (-2.0, -1.0, 1.2),
            _corridor_surfaces(),
            reflections=True,
        ),
        FixtureSpec(
            "connected_rooms_closed",
            "connected_space",
            (1.5, 0.0, 1.2),
            (-1.5, 0.0, 1.2),
            _connected_room_surfaces(door_open=False),
            door_open=False,
            reflections=True,
        ),
        FixtureSpec(
            "connected_rooms_open",
            "connected_space",
            (1.5, 0.0, 1.2),
            (-1.5, 0.0, 1.2),
            _connected_room_surfaces(door_open=True),
            door_open=True,
            reflections=True,
        ),
        FixtureSpec(
            "assembly_mono",
            "assembly",
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            (_partition("partition", 1.5, loss_db=12.0),),
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
            (
                _partition("partition_a", 1.5, loss_db=12.0),
                _partition("partition_b", 3.0, loss_db=12.0),
            ),
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
            (1.5, 0.0, 1.2),
            (-1.5, 0.0, 1.2),
            _connected_room_surfaces(door_open=False),
            dynamic_target="door",
            reflections=True,
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
            (3.0, 0.0, 1.2),
            (0.0, 0.0, 1.2),
            _room_shell("dynamic_room_shell", x_bounds=(-4.0, 4.0))
            + (_partition("large_object", 1.5),),
            dynamic_target="large_object",
            reflections=True,
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
        for frequency_hz in STEAM_AUDIO_BAND_FREQUENCIES_HZ
    )
    signal = np.asarray(signal / 3.0, dtype=np.float32)
    signal.setflags(write=False)
    return signal


def surface_points(
    surface: AcousticSurfaceSpec,
) -> tuple[tuple[float, float, float], ...]:
    """Return the four corners of a zero-thickness boundary."""

    cx, cy, cz = surface.center_xyz_m
    sx, sy, sz = surface.size_xyz_m
    if sx == 0.0:
        return (
            (cx, cy - sy / 2, cz - sz / 2),
            (cx, cy + sy / 2, cz - sz / 2),
            (cx, cy + sy / 2, cz + sz / 2),
            (cx, cy - sy / 2, cz + sz / 2),
        )
    if sy == 0.0:
        return (
            (cx - sx / 2, cy, cz - sz / 2),
            (cx + sx / 2, cy, cz - sz / 2),
            (cx + sx / 2, cy, cz + sz / 2),
            (cx - sx / 2, cy, cz + sz / 2),
        )
    return (
        (cx - sx / 2, cy - sy / 2, cz),
        (cx + sx / 2, cy - sy / 2, cz),
        (cx + sx / 2, cy + sy / 2, cz),
        (cx - sx / 2, cy + sy / 2, cz),
    )


def _write_wav(path: Path, samples: NDArray[np.float32]) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE_HZ)
        output.writeframes(pcm.tobytes())


def _fixture_usda(fixture: FixtureSpec) -> str:
    surface_prims = []
    for index, surface in enumerate(fixture.surfaces):
        points = ", ".join(str(point) for point in surface_points(surface))
        surface_prims.append(
            f'''    def Mesh "surface_{index:02d}" (
        customData = {{ string assembly_id = "{surface.assembly_id}" }}
    )
    {{
        int[] faceVertexCounts = [3, 3]
        int[] faceVertexIndices = [0, 1, 2, 0, 2, 3]
        point3f[] points = [{points}]
        custom double[] ias:transmissionLossDb = {list(surface.transmission_loss_db)}
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
{chr(10).join(surface_prims)}
}}
"""


def write_fixture_assets(output_dir: Path) -> dict[str, Path]:
    """Write corrected USD, signal, and manifest assets below ``output_dir``."""

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
        "fixture_revision": 2,
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
