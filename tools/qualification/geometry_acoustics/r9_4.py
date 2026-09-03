"""R9.4 selected-provider fixtures, scheduling, and report semantics."""

from __future__ import annotations

import math
import wave
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .fixtures import (
    BLOCK_SAMPLES,
    IAS_TRANSMISSION_FREQUENCIES_HZ,
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    AcousticSurfaceSpec,
    FixtureSpec,
    common_fixtures,
    generated_impulse,
    generated_multitone,
    surface_points,
)
from .models import DebugPathSample, RuntimeProbe
from .reporting import deterministic_json, write_deterministic_npz, write_json

REPORT_VERSION = "r9.4-v1"
SELECTED_PROVIDER_ID = "steam_audio"
SELECTED_PROVIDER_VERSION = "4.8.1"
SELECTED_SOURCE_COMMIT = "0da18255cca520771f363ee01f100572b39a308e"
GATE_IDS = (
    "provider_baseline",
    "acoustic_proxy_transmission",
    "baked_pathing_signal",
    "dynamic_path_validation",
    "arrival_time_scheduling",
    "operating_cost",
    "path_diagnostics",
)


@dataclass(frozen=True, slots=True)
class PathingFixtureSpec:
    """One deterministic native pathing scene and its probe graph."""

    fixture: FixtureSpec
    probes_xyz_m: tuple[tuple[float, float, float], ...]
    dynamic_translation_xyz_m: tuple[float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class PathingRun:
    """One provider-native pathing observation for every physical microphone."""

    fixture_id: str
    repetition: int
    disabled_samples: NDArray[np.float32]
    enabled_samples: NDArray[np.float32]
    validated_samples: NDArray[np.float32] | None
    alternate_samples: NDArray[np.float32] | None
    diagnostics: tuple[DebugPathSample, ...]
    measurements: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TimingRun:
    """Direct, reflected, and pathed arrival-time observations."""

    arrays: Mapping[str, NDArray[np.float32]]
    measurements: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PathingPerformanceRun:
    """Pathing audio and update timings for one environment count."""

    environment_count: int
    diagnostics_enabled: bool
    block_ms: tuple[float, ...]
    update_ms: tuple[float, ...]
    peak_memory_mib: float


@dataclass(frozen=True, slots=True)
class RiskObservation:
    """One measured R9.4 gate."""

    gate_id: str
    status: str
    summary: str
    evidence: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class RiskRetirementRun:
    """Complete selected-provider R9.4 result."""

    report: Mapping[str, object]
    evaluation: Mapping[str, object]
    measurements: Mapping[str, object]
    arrays: Mapping[str, NDArray[np.float32]]
    provenance: Mapping[str, object]
    log_lines: tuple[str, ...]


class StreamingDelayScheduler:
    """Apply bounded causal fractional delays without resetting at block edges."""

    _interpolation_radius = 16

    def __init__(
        self,
        *,
        channel_count: int,
        sample_rate_hz: int,
        max_delay_s: float = 0.1,
    ) -> None:
        if channel_count <= 0 or sample_rate_hz <= 0 or max_delay_s <= 0.0:
            raise ValueError("scheduler dimensions and maximum delay must be positive.")
        self.channel_count = channel_count
        self.sample_rate_hz = sample_rate_hz
        self.max_delay_samples = max_delay_s * sample_rate_hz
        self._history_size = (
            math.ceil(self.max_delay_samples) + self._interpolation_radius + 2
        )
        self._history = np.zeros((channel_count, self._history_size), dtype=np.float32)
        self._previous_delay_samples: NDArray[np.float64] | None = None

    def reset(self) -> None:
        self._history.fill(0.0)
        self._previous_delay_samples = None

    def process(
        self,
        samples: NDArray[np.float32],
        delays_s: Sequence[float],
    ) -> NDArray[np.float32]:
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 2 or values.shape[0] != self.channel_count:
            raise ValueError("samples must have shape [configured channel, sample].")
        target = np.asarray(delays_s, dtype=np.float64) * self.sample_rate_hz
        if target.shape != (self.channel_count,):
            raise ValueError("delays_s must contain one value per channel.")
        if np.any(~np.isfinite(target)) or np.any(target < 0.0):
            raise ValueError("delays must be finite and non-negative.")
        if np.any(target > self.max_delay_samples):
            raise ValueError("delay exceeds the configured scheduler bound.")
        if values.shape[1] == 0:
            return values.copy()

        previous = (
            target
            if self._previous_delay_samples is None
            else (self._previous_delay_samples)
        )
        output = np.empty_like(values)
        sample_index = np.arange(values.shape[1], dtype=np.float64)
        for channel in range(self.channel_count):
            extended = np.concatenate((self._history[channel], values[channel]))
            delay_curve = np.linspace(
                previous[channel],
                target[channel],
                values.shape[1] + 1,
                dtype=np.float64,
            )[1:]
            read_position = self._history_size + sample_index - delay_curve
            if np.min(delay_curve) >= self._interpolation_radius + 1:
                left = np.floor(read_position).astype(np.int64)
                tap_offsets = np.arange(
                    -self._interpolation_radius + 1,
                    self._interpolation_radius + 1,
                )
                indices = left[:, np.newaxis] + tap_offsets[np.newaxis, :]
                distances = read_position[:, np.newaxis] - indices
                weights = np.sinc(distances) * np.sinc(
                    distances / self._interpolation_radius
                )
                weights /= np.sum(weights, axis=1, keepdims=True)
                output[channel] = np.sum(extended[indices] * weights, axis=1).astype(
                    np.float32
                )
            else:
                left = np.floor(read_position).astype(np.int64)
                fraction = read_position - left
                right = np.minimum(left + 1, extended.size - 1)
                output[channel] = (
                    (1.0 - fraction) * extended[left] + fraction * extended[right]
                ).astype(np.float32)
            self._history[channel] = extended[-self._history_size :]
        self._previous_delay_samples = target.copy()
        return output


def _surface(
    assembly_id: str,
    center_xyz_m: tuple[float, float, float],
    size_xyz_m: tuple[float, float, float],
    *,
    loss_db: float = 12.0,
) -> AcousticSurfaceSpec:
    return AcousticSurfaceSpec(
        assembly_id,
        center_xyz_m,
        size_xyz_m,
        (loss_db,) * len(IAS_TRANSMISSION_FREQUENCIES_HZ),
    )


def paired_proxy_surfaces(
    assembly_id: str,
    *,
    center_xyz_m: tuple[float, float, float],
    size_xyz_m: tuple[float, float, float],
    loss_db: float = 12.0,
    face_fragments: int = 1,
) -> tuple[AcousticSurfaceSpec, ...]:
    """Represent one assembly as a closed provider-native paired-face proxy."""

    if any(size <= 0.0 for size in size_xyz_m):
        raise ValueError("proxy dimensions must be positive.")
    if face_fragments <= 0:
        raise ValueError("face_fragments must be positive.")
    cx, cy, cz = center_xyz_m
    sx, sy, sz = size_xyz_m
    x_faces: list[AcousticSurfaceSpec] = []
    fragment_width = sy / face_fragments
    for x_m in (cx - sx / 2.0, cx + sx / 2.0):
        for index in range(face_fragments):
            y_m = cy - sy / 2.0 + (index + 0.5) * fragment_width
            x_faces.append(
                _surface(
                    assembly_id,
                    (x_m, y_m, cz),
                    (0.0, fragment_width, sz),
                    loss_db=loss_db,
                )
            )
    return tuple(x_faces) + (
        _surface(
            assembly_id,
            (cx, cy - sy / 2.0, cz),
            (sx, 0.0, sz),
            loss_db=loss_db,
        ),
        _surface(
            assembly_id,
            (cx, cy + sy / 2.0, cz),
            (sx, 0.0, sz),
            loss_db=loss_db,
        ),
        _surface(
            assembly_id,
            (cx, cy, cz - sz / 2.0),
            (sx, sy, 0.0),
            loss_db=loss_db,
        ),
        _surface(
            assembly_id,
            (cx, cy, cz + sz / 2.0),
            (sx, sy, 0.0),
            loss_db=loss_db,
        ),
    )


def assembly_fixtures() -> tuple[FixtureSpec, ...]:
    """Return the R9.4 paired-proxy transmission matrix."""

    array = (0.0, 0.0, 1.2)
    source = (4.5, 0.35, 1.2)

    def proxies(
        count: int,
        *,
        thickness_m: float = 0.2,
        fragments: int = 1,
    ) -> tuple[AcousticSurfaceSpec, ...]:
        surfaces: list[AcousticSurfaceSpec] = []
        for index, x_m in enumerate((1.2, 2.4, 3.6)[:count], start=1):
            surfaces.extend(
                paired_proxy_surfaces(
                    f"assembly_{index}",
                    center_xyz_m=(x_m, 0.0, 1.5),
                    size_xyz_m=(thickness_m, 4.0, 3.0),
                    face_fragments=fragments,
                )
            )
        return tuple(surfaces)

    return (
        FixtureSpec(
            "proxy_one", "r9.4_assembly", source, array, proxies(1), signal="multitone"
        ),
        FixtureSpec(
            "proxy_two", "r9.4_assembly", source, array, proxies(2), signal="multitone"
        ),
        FixtureSpec(
            "proxy_three",
            "r9.4_assembly",
            source,
            array,
            proxies(3),
            signal="multitone",
        ),
        FixtureSpec(
            "proxy_oblique",
            "r9.4_assembly",
            (4.5, 1.25, 1.2),
            array,
            proxies(1),
            signal="multitone",
        ),
        FixtureSpec(
            "proxy_thin",
            "r9.4_assembly",
            source,
            array,
            proxies(1, thickness_m=0.05),
            signal="multitone",
        ),
        FixtureSpec(
            "proxy_thick",
            "r9.4_assembly",
            source,
            array,
            proxies(1, thickness_m=0.8),
            signal="multitone",
        ),
        FixtureSpec(
            "proxy_fragmented",
            "r9.4_assembly",
            source,
            array,
            proxies(1, fragments=4),
            signal="multitone",
        ),
    )


def _path_fixture(fixture_id: str) -> FixtureSpec:
    return next(
        fixture for fixture in common_fixtures() if fixture.fixture_id == fixture_id
    )


def pathing_fixtures() -> tuple[PathingFixtureSpec, ...]:
    """Return pathing scenes with deterministic primary and alternate probe routes."""

    corridor = _path_fixture("l_corridor_nlos")
    blocker = _surface(
        "path_blocker",
        (0.0, 6.0, 1.5),
        (0.0, 1.4, 3.0),
        loss_db=60.0,
    )
    dynamic_corridor = FixtureSpec(
        "l_corridor_pathing",
        "r9.4_pathing",
        corridor.source_xyz_m,
        corridor.array_xyz_m,
        corridor.surfaces + (blocker,),
        dynamic_target="path_blocker",
        signal="impulse",
    )
    connected = _path_fixture("connected_rooms_open")
    connected_pathing = FixtureSpec(
        "connected_rooms_pathing",
        "r9.4_pathing",
        connected.source_xyz_m,
        connected.array_xyz_m,
        connected.surfaces,
        signal="impulse",
    )
    return (
        PathingFixtureSpec(
            dynamic_corridor,
            (
                (2.0, -1.0, 1.2),
                (1.0, 0.6, 1.2),
                (-1.0, 0.6, 1.2),
                (1.8, 1.9, 1.2),
                (-1.8, 1.9, 1.2),
                (-2.0, -1.0, 1.2),
            ),
            (0.0, -5.2, 0.0),
        ),
        PathingFixtureSpec(
            connected_pathing,
            (
                (2.0, 0.0, 1.2),
                (0.6, 0.0, 1.2),
                (-0.6, 0.0, 1.2),
                (-2.0, 0.0, 1.2),
            ),
        ),
    )


def _fixture_usda(fixture: FixtureSpec) -> str:
    meshes = []
    for index, surface in enumerate(fixture.surfaces):
        points = ", ".join(str(point) for point in surface_points(surface))
        meshes.append(
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
    def Xform "source" {{ double3 xformOp:translate = ({sx}, {sy}, {sz}) }}
    def Xform "quad_front" {{ double3 xformOp:translate = ({ax}, {ay}, {az}) }}
{chr(10).join(meshes)}
}}
"""


def _write_wav(path: Path, samples: NDArray[np.float32]) -> None:
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE_HZ)
        output.writeframes(pcm.tobytes())


def write_fixture_assets(output_dir: Path) -> None:
    """Write the self-contained R9.4 fixture manifest and signal inputs."""

    fixtures_dir = output_dir / "fixtures"
    signals_dir = output_dir / "signals"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    signals_dir.mkdir(parents=True, exist_ok=True)
    assemblies = assembly_fixtures()
    pathing = pathing_fixtures()
    for fixture in (*assemblies, *(item.fixture for item in pathing)):
        (fixtures_dir / f"{fixture.fixture_id}.usda").write_text(
            _fixture_usda(fixture), encoding="utf-8"
        )
    _write_wav(signals_dir / "impulse.wav", generated_impulse())
    _write_wav(signals_dir / "multitone.wav", generated_multitone())
    manifest = {
        "assembly_fixtures": [asdict(fixture) for fixture in assemblies],
        "block_samples": BLOCK_SAMPLES,
        "microphone_ids": list(MICROPHONE_IDS),
        "pathing_fixtures": [asdict(fixture) for fixture in pathing],
        "quad_front_offsets_m": [list(offset) for offset in QUAD_FRONT_OFFSETS_M],
        "repeat_count": REPEAT_COUNT,
        "report_version": REPORT_VERSION,
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    (output_dir / "fixture_manifest.json").write_text(
        deterministic_json(manifest), encoding="utf-8"
    )


def build_report(
    *,
    runtime: Mapping[str, str],
    observations: Sequence[RiskObservation],
) -> dict[str, object]:
    """Build one exact, ordered R9.4 selected-provider report."""

    ids = tuple(observation.gate_id for observation in observations)
    if ids != GATE_IDS:
        raise ValueError(f"R9.4 gates must follow canonical order: {GATE_IDS}.")
    gates = []
    for observation in observations:
        if observation.status not in {"pass", "fail", "blocked"}:
            raise ValueError(f"invalid status for {observation.gate_id}.")
        if not observation.summary.strip() or not observation.evidence:
            raise ValueError("every R9.4 gate requires a summary and evidence.")
        gates.append(
            {
                "gate_id": observation.gate_id,
                "status": observation.status,
                "summary": observation.summary,
                "evidence": [dict(item) for item in observation.evidence],
            }
        )
    report = {
        "provider": {
            "id": SELECTED_PROVIDER_ID,
            "source_commit": SELECTED_SOURCE_COMMIT,
            "version": SELECTED_PROVIDER_VERSION,
        },
        "report_version": REPORT_VERSION,
        "runtime": dict(runtime),
        "gates": gates,
    }
    evaluate_report(report)
    return report


def evaluate_report(report: Mapping[str, object]) -> dict[str, object]:
    """Derive R10 admissions without reopening the selected-provider decision."""

    if report.get("report_version") != REPORT_VERSION:
        raise ValueError(f"report_version must be {REPORT_VERSION!r}.")
    provider = report.get("provider")
    expected_provider = {
        "id": SELECTED_PROVIDER_ID,
        "source_commit": SELECTED_SOURCE_COMMIT,
        "version": SELECTED_PROVIDER_VERSION,
    }
    if provider != expected_provider:
        raise ValueError("R9.4 report must retain the exact R9.3 provider baseline.")
    gates = report.get("gates")
    if not isinstance(gates, list):
        raise ValueError("R9.4 gates must be a list.")
    ids = tuple(item.get("gate_id") for item in gates if isinstance(item, Mapping))
    if ids != GATE_IDS or len(gates) != len(GATE_IDS):
        raise ValueError("R9.4 gate inventory or order is invalid.")
    statuses: dict[str, str] = {}
    for item in gates:
        if not isinstance(item, Mapping):
            raise ValueError("R9.4 gate entries must be objects.")
        status = item.get("status")
        if status not in {"pass", "fail", "blocked"}:
            raise ValueError("R9.4 gate status is invalid.")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("R9.4 gate evidence must be non-empty.")
        statuses[str(item["gate_id"])] = str(status)
    pathing_gates = (
        "baked_pathing_signal",
        "dynamic_path_validation",
        "arrival_time_scheduling",
        "operating_cost",
    )
    blocked = [gate_id for gate_id, status in statuses.items() if status == "blocked"]
    failed = [gate_id for gate_id, status in statuses.items() if status == "fail"]
    return {
        "admitted_capabilities": {
            "acoustic_proxy_transmission": (
                statuses["acoustic_proxy_transmission"] == "pass"
            ),
            "baked_pathing": all(
                statuses[gate_id] == "pass" for gate_id in pathing_gates
            ),
            "path_diagnostics": statuses["path_diagnostics"] == "pass",
            "private_arrival_scheduler": (
                statuses["arrival_time_scheduling"] == "pass"
            ),
        },
        "blocked_gates": blocked,
        "execution_status": "blocked" if blocked else "complete",
        "failed_gates": failed,
        "provider_selection": "unchanged",
        "report_version": REPORT_VERSION,
    }


def write_bundle(output_dir: Path, run: RiskRetirementRun) -> None:
    """Write a separate versioned bundle without touching R9.2 rev2 evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / f"{REPORT_VERSION}-report.json", run.report)
    write_json(output_dir / "evaluation.json", run.evaluation)
    write_json(output_dir / "measurements.json", run.measurements)
    write_deterministic_npz(output_dir / "signals.npz", run.arrays)
    write_json(output_dir / "provenance.json", run.provenance)
    (output_dir / "run.log").write_text(
        "\n".join(run.log_lines) + "\n", encoding="utf-8"
    )


def blocked_observations(probe: RuntimeProbe) -> tuple[RiskObservation, ...]:
    blocker = probe.external_blocker or "selected provider runtime is inaccessible"
    evidence = (
        {
            "kind": "runtime_probe",
            "origin": "provider_native",
            "reference": "run.log",
            "summary": blocker,
        },
    )
    return tuple(
        RiskObservation(gate_id, "blocked", "The gate was not exercised.", evidence)
        for gate_id in GATE_IDS
    )


def evidence(
    kind: str,
    origin: str,
    reference: str,
    summary: str,
) -> tuple[Mapping[str, str], ...]:
    return (
        {
            "kind": kind,
            "origin": origin,
            "reference": reference,
            "summary": summary,
        },
    )


def json_safe(value: object) -> object:
    """Convert NumPy scalars and arrays in measurement payloads to JSON values."""

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


__all__ = [
    "GATE_IDS",
    "REPORT_VERSION",
    "SELECTED_PROVIDER_ID",
    "SELECTED_PROVIDER_VERSION",
    "SELECTED_SOURCE_COMMIT",
    "PathingFixtureSpec",
    "PathingPerformanceRun",
    "PathingRun",
    "RiskObservation",
    "RiskRetirementRun",
    "StreamingDelayScheduler",
    "TimingRun",
    "assembly_fixtures",
    "blocked_observations",
    "build_report",
    "evaluate_report",
    "evidence",
    "json_safe",
    "paired_proxy_surfaces",
    "pathing_fixtures",
    "write_bundle",
    "write_fixture_assets",
]
