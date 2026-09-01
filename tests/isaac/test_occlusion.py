from __future__ import annotations

from dataclasses import replace

import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSpec,
    SourceOcclusion,
)
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
)
from isaac_audio_sensors.isaac.occlusion import (
    DEFAULT_MATERIAL_TRANSMISSION_DB,
    OcclusionHit,
    TransmissionLoss,
    UsdTransmissionLossResolver,
    compute_scene_occlusion,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.viz.overlays import (
    CLEAR_BEARING_RAY_COLOR,
    OCCLUDED_BEARING_RAY_COLOR,
    PARTIAL_OCCLUSION_BEARING_RAY_COLOR,
    build_debug_primitives,
    debug_primitives_to_dicts,
)
from tests.helpers import FakeUsdPrim, FakeUsdStage

ARRAY_PRIM_PATH = "/World/Rig/AudioArray"
SOURCE_PRIM_PATH = "/World/Sources/SpeakerA"
WALL_PRIM_PATH = "/World/Wall"


class FakeRaycaster:
    """Raycaster with configurable X-plane walls and optional Y bounds."""

    def __init__(
        self,
        walls: tuple[tuple[str, float, tuple[float, float] | None], ...] = (),
    ) -> None:
        self.walls = walls
        self.casts: list[tuple[tuple[float, ...], tuple[float, ...], float]] = []

    def raycast_closest(self, origin, direction, max_distance_m):
        self.casts.append((tuple(origin), tuple(direction), float(max_distance_m)))
        best: tuple[str, float] | None = None
        for prim_path, x_plane, y_range in self.walls:
            if abs(direction[0]) < 1e-12:
                continue
            travel = (x_plane - origin[0]) / direction[0]
            if not 0.0 < travel <= max_distance_m:
                continue
            if y_range is not None:
                y_cross = origin[1] + travel * direction[1]
                if not y_range[0] <= y_cross <= y_range[1]:
                    continue
            if best is None or travel < best[1]:
                best = (prim_path, travel)
        if best is None:
            return None
        return OcclusionHit(prim_path=best[0], distance_m=best[1])


class UnavailableRaycaster:
    def raycast_closest(self, origin, direction, max_distance_m):
        raise IsaacIntegrationUnavailable("no PhysX in this test environment")


def _array() -> MicrophoneArraySpec:
    return MicrophoneArraySpec(
        array_id="rig_front",
        prim_path=ARRAY_PRIM_PATH,
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphones=(
            MicrophoneSpec(mic_id="front", relative_position_m=(0.08, 0.0, 0.0)),
            MicrophoneSpec(mic_id="right", relative_position_m=(0.0, 0.08, 0.0)),
        ),
    )


def _source(position=(4.0, 0.0, 0.0)) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker_a",
        prim_path=SOURCE_PRIM_PATH,
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=10.0,
        gain_db=0.0,
    )


def _quad_array() -> MicrophoneArraySpec:
    base = _array()
    return replace(
        base,
        microphones=(
            *base.microphones,
            MicrophoneSpec(mic_id="rear", relative_position_m=(-0.08, 0.0, 0.0)),
            MicrophoneSpec(mic_id="left", relative_position_m=(0.0, -0.08, 0.0)),
        ),
    )


def _scene(**overrides) -> AudioSceneSnapshot:
    base = AudioSceneSnapshot(
        stage_id="occlusion_test",
        sources=(_source(),),
        arrays=(_array(),),
        environment=free_field_environment(environment_id="occlusion_free_field"),
    )
    return replace(base, **overrides) if overrides else base


def _occlusion_record(
    *,
    factor: float = 1.0,
    attenuation_db: float = 20.0,
) -> SourceOcclusion:
    mic_ids = ("front", "right", "rear", "left")
    blocked_count = int(round(factor * len(mic_ids)))
    blocked_ids = set(mic_ids[:blocked_count])
    return SourceOcclusion(
        array_id="rig_front",
        source_id="speaker_a",
        per_mic_blocked={mic_id: mic_id in blocked_ids for mic_id in mic_ids},
        per_mic_attenuation_db={
            mic_id: attenuation_db if mic_id in blocked_ids else 0.0
            for mic_id in mic_ids
        },
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        frame_index=0,
    )


def test_compute_scene_occlusion_clear_path_yields_zero_factor():
    raycaster = FakeRaycaster()
    records = compute_scene_occlusion(_scene(), raycaster)

    assert len(records) == 1
    record = records[0]
    assert record.array_id == "rig_front"
    assert record.source_id == "speaker_a"
    assert record.per_mic_blocked == {"front": False, "right": False}
    assert record.per_mic_attenuation_db == {"front": 0.0, "right": 0.0}
    assert len(raycaster.casts) == 2


def test_compute_scene_occlusion_single_wall_preserves_scalar_and_per_mic_values():
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),))
    records = compute_scene_occlusion(_scene(), raycaster)

    record = records[0]
    assert record.per_mic_blocked == {"front": True, "right": True}
    assert record.per_mic_attenuation_db == {"front": 20.0, "right": 20.0}


def test_compute_scene_occlusion_partial_wall_yields_fractional_factor():
    # Wall segment only covers the crossing point of the ray toward the
    # offset "right" microphone, not the on-axis "front" microphone.
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, (0.02, 1.0)),))
    records = compute_scene_occlusion(
        _scene(),
        raycaster,
        unknown_material_loss_db=30.0,
    )

    record = records[0]
    assert record.per_mic_blocked == {"front": False, "right": True}
    assert record.per_mic_attenuation_db == {"front": 0.0, "right": 30.0}


def test_occlusion_loss_does_not_depend_on_obstacle_distance() -> None:
    near = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((WALL_PRIM_PATH, 1.0, None),)),
    )[0]
    far = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((WALL_PRIM_PATH, 3.0, None),)),
    )[0]

    assert near.per_mic_attenuation_db == far.per_mic_attenuation_db


def test_compute_scene_occlusion_skips_source_and_array_hits_with_recast():
    self_hits = (
        (f"{SOURCE_PRIM_PATH}/collider", 3.95, None),
        (f"{ARRAY_PRIM_PATH}/mount", 0.05, None),
    )
    clear = FakeRaycaster(walls=self_hits)
    records = compute_scene_occlusion(_scene(), clear)
    assert not any(records[0].per_mic_blocked.values())
    assert len(clear.casts) > 2

    walled = FakeRaycaster(walls=(*self_hits, (WALL_PRIM_PATH, 2.0, None)))
    records = compute_scene_occlusion(_scene(), walled)
    assert all(records[0].per_mic_blocked.values())


def test_compute_scene_occlusion_degenerate_short_ray_is_clear():
    # The front ray is within endpoint epsilon; the right ray still hits.
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 0.04, None),))
    scene = _scene(sources=(_source(position=(0.085, 0.0, 0.0)),))
    records = compute_scene_occlusion(scene, raycaster)

    assert records[0].per_mic_blocked == {"front": False, "right": True}
    assert len(raycaster.casts) == 2


@pytest.mark.parametrize(
    ("record", "expected_color", "expected_factor"),
    [
        (None, CLEAR_BEARING_RAY_COLOR, None),
        (
            _occlusion_record(factor=0.25, attenuation_db=5.0),
            PARTIAL_OCCLUSION_BEARING_RAY_COLOR,
            0.25,
        ),
        (_occlusion_record(), OCCLUDED_BEARING_RAY_COLOR, 1.0),
    ],
    ids=["clear", "partial", "occluded"],
)
def test_debug_primitives_color_bearing_rays_by_occlusion(
    record, expected_color, expected_factor
):
    array = _quad_array()
    scene = _scene(
        arrays=(array,),
        occlusion=None if record is None else (record,),
    )
    frame = AnalyticAcoustics().simulate(scene, "rig_front", _window())
    primitives = build_debug_primitives(
        frame=frame,
        scene=scene,
        sensor=array,
    )
    rays = [primitive for primitive in primitives if primitive.kind == "bearing_ray"]
    assert rays[0].color_rgba == expected_color
    assert rays[0].metadata["occlusion_factor"] == expected_factor


def _fake_stage() -> FakeUsdStage:
    return FakeUsdStage(
        (
            FakeUsdPrim(
                SOURCE_PRIM_PATH,
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker_a",
                    "ias:class_label": "Speech",
                    "ias:position_world": (4.0, 0.0, 0.0),
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 10.0,
                },
            ),
            FakeUsdPrim(
                ARRAY_PRIM_PATH,
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            FakeUsdPrim(
                f"{ARRAY_PRIM_PATH}/front",
                "Xform",
                {
                    "ias:microphone_id": "front",
                    "ias:relative_position_m": (0.08, 0.0, 0.0),
                },
            ),
            FakeUsdPrim(
                f"{ARRAY_PRIM_PATH}/right",
                "Xform",
                {
                    "ias:microphone_id": "right",
                    "ias:relative_position_m": (0.0, 0.08, 0.0),
                },
            ),
        )
    )


def _live_sensor(
    stage,
    *,
    backend: str = "analytic_acoustics",
    **kwargs,
) -> IsaacAudioArraySensor:
    return IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path=ARRAY_PRIM_PATH,
        environment_resolution_cfg=IsaacEnvironmentResolutionCfg(mode="manual"),
        environment=free_field_environment(environment_id="live_occlusion_free_field"),
        backend=backend,
        update_period_s=0.1,
        **kwargs,
    ).start()


def test_live_sensor_occlusion_attenuates_flags_and_reports_diagnostics():
    sensor = _live_sensor(
        _fake_stage(),
        occlusion_enabled=True,
        occlusion_raycaster=FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),)),
    )
    frame = sensor.update(sim_time_s=0.0)

    detection = frame.detections[0]
    assert detection.occluded is True
    assert set(detection.diagnostics["occlusion"]) == {
        "occlusion_factor",
        "per_mic_blocked",
        "per_mic_attenuation_db",
    }
    state = frame.diagnostics["acoustics_state"]["occlusion"]
    assert state["model"] == "raycast_transmission_v1"
    assert state["unknown_material_loss_db"] == 20.0
    assert set(state["material_resolution"]) == {WALL_PRIM_PATH}
    assert state["unknown_material_fallbacks"] == [
        {
            "array_id": "rig_front",
            "source_id": "speaker_a",
            "mic_id": mic_id,
            "partition_id": WALL_PRIM_PATH,
            "attenuation_db": 20.0,
        }
        for mic_id in ("front", "right")
    ]
    occlusion_diag = frame.diagnostics["stage_snapshot"]["occlusion"]
    assert occlusion_diag == {"status": "computed", "record_count": 1}
    assert sensor.latest_debug_primitives == ()
    sensor.close()


def test_live_sensor_debug_draw_adds_transient_occlusion_primitives_only():
    sensor = _live_sensor(
        _fake_stage(),
        debug_draw=True,
        occlusion_enabled=True,
        occlusion_raycaster=FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),)),
    )
    frame = sensor.update(sim_time_s=0.0)

    ray = next(
        primitive
        for primitive in sensor.latest_debug_primitives
        if primitive.kind == "occlusion_ray"
    )
    hits = [
        primitive
        for primitive in sensor.latest_debug_primitives
        if primitive.kind == "occlusion_hit"
    ]
    assert len(ray.points_world) == 3
    assert ray.metadata["partitions"][0] == {
        "partition_id": WALL_PRIM_PATH,
        "prim_path": WALL_PRIM_PATH,
        "material_id": "configured_unknown_material:20-db",
        "broadband_db": 20.0,
        "band_db": None,
        "unknown_material_fallback": True,
        "applied": True,
    }
    assert len(hits) == 2
    serialized = debug_primitives_to_dicts(sensor.latest_debug_primitives)
    serialized_ray = next(
        primitive for primitive in serialized if primitive["kind"] == "occlusion_ray"
    )
    assert serialized_ray["metadata"] == ray.metadata
    assert WALL_PRIM_PATH not in str(frame.detections[0].diagnostics)
    sensor.close()


def test_live_analytic_sensor_tracks_blocked_to_clear_transition() -> None:
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),))
    sensor = _live_sensor(
        _fake_stage(),
        backend="analytic_acoustics",
        occlusion_enabled=True,
        occlusion_raycaster=raycaster,
    )

    blocked = sensor.update(sim_time_s=0.0)
    raycaster.walls = ()
    clear = sensor.update(sim_time_s=0.1)

    assert blocked.backend_id == "analytic_acoustics"
    assert blocked.detections[0].occluded is True
    assert blocked.detections[0].diagnostics["occlusion"][
        "occlusion_factor"
    ] == 1.0
    assert clear.detections[0].occluded is False
    assert clear.detections[0].diagnostics["occlusion"][
        "occlusion_factor"
    ] == 0.0
    sensor.close()


def test_live_sensor_occlusion_disabled_by_default():
    sensor = _live_sensor(_fake_stage())
    frame = sensor.update(sim_time_s=0.0)

    assert frame.detections[0].occluded is False
    assert "occlusion" not in frame.detections[0].diagnostics
    assert "occlusion" not in frame.diagnostics["stage_snapshot"]
    sensor.close()


def test_live_sensor_degrades_gracefully_when_raycaster_unavailable():
    sensor = _live_sensor(
        _fake_stage(),
        occlusion_enabled=True,
        occlusion_raycaster=UnavailableRaycaster(),
    )
    frame = sensor.update(sim_time_s=0.0)

    assert frame.detections[0].occluded is False
    occlusion_diag = frame.diagnostics["stage_snapshot"]["occlusion"]
    assert occlusion_diag["status"] == "unavailable"
    assert "PhysX" in occlusion_diag["error"]
    sensor.close()


def test_compute_scene_occlusion_accumulates_without_total_loss_clamp():
    walls = ((WALL_PRIM_PATH, 2.0, None), ("/World/Wall2", 3.0, None))
    records = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=walls),
        unknown_material_loss_db=40.0,
    )

    record = records[0]
    assert record.per_mic_blocked == {"front": True, "right": True}
    assert record.per_mic_attenuation_db == {"front": 80.0, "right": 80.0}
    assert record.per_mic_band_attenuation_db == {}


class _PartitionResolver:
    def __init__(self, partition_ids, losses):
        self.partition_ids = partition_ids
        self.losses = losses

    def partition_id_for(self, prim_path):
        return self.partition_ids.get(prim_path, prim_path)

    def loss_for(self, prim_path):
        return self.losses[prim_path]


def test_fragmented_acoustic_partition_applies_one_assembly_curve():
    first = "/World/Assembly/ColliderA"
    second = "/World/Assembly/ColliderB"
    loss = TransmissionLoss(broadband_db=35.0, material_id="assembly.double_leaf")
    resolver = _PartitionResolver(
        {first: "wall-assembly", second: "wall-assembly"},
        {first: loss, second: loss},
    )
    diagnostics = {}

    record = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((first, 3.0, None), (second, 2.0, None))),
        transmission_resolver=resolver,
        diagnostics_out=diagnostics,
    )[0]

    assert record.per_mic_attenuation_db == {"front": 35.0, "right": 35.0}
    assert set(diagnostics["material_resolution"]) == {"wall-assembly"}


def test_fragmented_partition_preserves_authored_assembly_band_curve():
    first = "/World/Assembly/ColliderA"
    second = "/World/Assembly/ColliderB"
    bands = (30.0, 35.0, 40.0, 45.0, 50.0, 55.0)
    loss = TransmissionLoss(
        broadband_db=sum(bands) / len(bands),
        band_db=bands,
        material_id="assembly.double_leaf",
    )
    resolver = _PartitionResolver(
        {first: "wall-assembly", second: "wall-assembly"},
        {first: loss, second: loss},
    )

    record = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((first, 3.0, None), (second, 2.0, None))),
        transmission_resolver=resolver,
    )[0]

    assert record.per_mic_band_attenuation_db == {
        "front": bands,
        "right": bands,
    }


def test_conflicting_curves_within_one_partition_fail_closed():
    first = "/World/Assembly/ColliderA"
    second = "/World/Assembly/ColliderB"
    resolver = _PartitionResolver(
        {first: "wall-assembly", second: "wall-assembly"},
        {
            first: TransmissionLoss(broadband_db=10.0),
            second: TransmissionLoss(broadband_db=20.0),
        },
    )

    with pytest.raises(ValueError, match="conflicting transmission"):
        compute_scene_occlusion(
            _scene(),
            FakeRaycaster(walls=((first, 3.0, None), (second, 2.0, None))),
            transmission_resolver=resolver,
        )


def test_default_resolver_uses_authored_partition_id_with_path_fallback():
    partitioned = FakeUsdPrim(
        WALL_PRIM_PATH,
        "Cube",
        {"ias:acoustic_partition_id": "wall-assembly"},
    )
    stage = FakeUsdStage((partitioned,))
    resolver = UsdTransmissionLossResolver(stage)

    assert resolver.partition_id_for(WALL_PRIM_PATH) == "wall-assembly"
    assert resolver.partition_id_for("/World/Missing") == "/World/Missing"


def test_default_resolver_deduplicates_fragmented_authored_partition():
    first = "/World/Assembly/ColliderA"
    second = "/World/Assembly/ColliderB"
    attrs = {
        "ias:acoustic_partition_id": "wall-assembly",
        "ias:transmission_loss_db": 72.0,
    }
    stage = FakeUsdStage(
        (
            FakeUsdPrim(first, "Cube", dict(attrs)),
            FakeUsdPrim(second, "Cube", dict(attrs)),
        )
    )

    record = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((first, 3.0, None), (second, 2.0, None))),
        transmission_resolver=UsdTransmissionLossResolver(stage),
    )[0]

    assert record.per_mic_attenuation_db == {"front": 72.0, "right": 72.0}


def test_hit_limit_fails_instead_of_returning_partial_attenuation():
    walls = ((WALL_PRIM_PATH, 3.0, None), ("/World/Wall2", 2.0, None))
    with pytest.raises(ValueError, match="max_hits_per_ray"):
        compute_scene_occlusion(
            _scene(),
            FakeRaycaster(walls=walls),
            max_hits_per_ray=1,
        )


@pytest.mark.parametrize("removed_name", ["max_attenuation_db", "attenuation_cap_db"])
def test_compute_scene_occlusion_removed_arguments_have_no_alias(removed_name):
    with pytest.raises(TypeError, match=removed_name):
        compute_scene_occlusion(
            _scene(),
            FakeRaycaster(),
            **{removed_name: 20.0},
        )


def test_live_sensor_removed_fallback_argument_has_no_alias():
    with pytest.raises(TypeError, match="occlusion_max_attenuation_db"):
        _live_sensor(
            _fake_stage(),
            occlusion_max_attenuation_db=20.0,
        )


def test_compute_scene_occlusion_resolves_material_bands_from_path():
    walls = (("/World/ConcreteWall", 2.0, None),)
    diagnostics = {}
    records = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=walls),
        transmission_resolver=UsdTransmissionLossResolver(None),
        diagnostics_out=diagnostics,
    )

    record = records[0]
    assert record.band_centers_hz == OCCLUSION_BAND_CENTERS_HZ
    assert (
        record.per_mic_band_attenuation_db["front"]
        == (DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"])
    )
    assert record.per_mic_attenuation_db["front"] == pytest.approx(
        sum(DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"])
        / len(DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"])
    )
    evidence = diagnostics["material_resolution"]["/World/ConcreteWall"]
    assert evidence["material_id"] == "nominal.concrete"
    assert evidence["unknown_material_fallback"] is False
    assert diagnostics["unknown_material_fallbacks"] == []


def _per_mic_record(
    *,
    source_id: str = "speaker_a",
    front_db: float = 20.0,
    right_db: float = 0.0,
    band_rows: dict[str, tuple[float, ...]] | None = None,
) -> SourceOcclusion:
    return SourceOcclusion(
        array_id="rig_front",
        source_id=source_id,
        per_mic_blocked={"front": front_db > 0.0, "right": right_db > 0.0},
        per_mic_attenuation_db={"front": front_db, "right": right_db},
        per_mic_band_attenuation_db=band_rows or {},
        band_centers_hz=OCCLUSION_BAND_CENTERS_HZ if band_rows else (),
    )


def test_occlusion_diagnostics_round_trip_new_fields():
    record = _per_mic_record(
        band_rows={
            "front": (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
            "right": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        },
    )
    frame = AnalyticAcoustics().simulate(
        _scene(occlusion=(record,)), "rig_front", _window()
    )

    restored = frame_from_trace_dict(frame_to_trace_dict(frame))
    diagnostics = restored.detections[0].diagnostics["occlusion"]
    assert diagnostics["per_mic_attenuation_db"] == {"front": 20.0, "right": 0.0}
    assert diagnostics["per_mic_band_attenuation_db"]["front"] == [
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
    ]
    assert diagnostics["band_centers_hz"] == list(OCCLUSION_BAND_CENTERS_HZ)
    assert set(diagnostics) == {
        "occlusion_factor",
        "per_mic_blocked",
        "per_mic_attenuation_db",
        "per_mic_band_attenuation_db",
        "band_centers_hz",
    }


class _RepeatingHitRaycaster:
    """Repeats one collider on continuation casts."""

    def __init__(self, hit_count: int = 3) -> None:
        self.remaining_hits = hit_count

    def raycast_closest(self, origin, direction, max_distance_m):
        if self.remaining_hits <= 0:
            return None
        self.remaining_hits -= 1
        return OcclusionHit(prim_path=WALL_PRIM_PATH, distance_m=0.05)


def test_compute_scene_occlusion_counts_one_thick_wall_once():
    records = compute_scene_occlusion(_scene(), _RepeatingHitRaycaster())

    record = records[0]
    assert record.per_mic_blocked["front"] is True
    assert record.per_mic_attenuation_db["front"] == 20.0
