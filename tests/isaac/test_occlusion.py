"""Occlusion: Isaac-layer raycasts computed, pure-core backends consume."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSpec,
    RoomAcousticsSpec,
    SourceOcclusion,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.occlusion import (
    DEFAULT_MATERIAL_TRANSMISSION_DB,
    OcclusionHit,
    UsdTransmissionLossResolver,
    compute_scene_occlusion,
)
from isaac_audio_sensors.isaac.viz.overlays import (
    CLEAR_BEARING_RAY_COLOR,
    OCCLUDED_BEARING_RAY_COLOR,
    PARTIAL_OCCLUSION_BEARING_RAY_COLOR,
    bearing_ray_color,
    build_debug_primitives,
)

ARRAY_PRIM_PATH = "/World/Rig/AudioArray"
SOURCE_PRIM_PATH = "/World/Sources/SpeakerA"
WALL_PRIM_PATH = "/World/Wall"


class FakeRaycaster:
    """Deterministic raycaster blocking rays at configured X planes.

    Each wall is ``(prim_path, x_plane, y_range)``; ``y_range`` limits the
    wall to rays whose crossing point lies inside ``(y_min, y_max)``.
    """

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
        forward_vec_world=(1.0, 0.0, 0.0),
        right_vec_world=(0.0, 1.0, 0.0),
        up_vec_world=(0.0, 0.0, 1.0),
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


def _scene(**overrides) -> AudioSceneSnapshot:
    base = AudioSceneSnapshot(
        stage_id="occlusion_test",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(_array(),),
    )
    return replace(base, **overrides) if overrides else base


def _occlusion_record(
    *,
    factor: float = 1.0,
    attenuation_db: float = 20.0,
) -> SourceOcclusion:
    return SourceOcclusion(
        array_id="rig_front",
        source_id="speaker_a",
        per_mic_blocked={"front": factor > 0.0, "right": factor >= 1.0},
        occlusion_factor=factor,
        attenuation_db=attenuation_db,
        hit_prim_paths=(WALL_PRIM_PATH,),
    )


def _window(end_time_s: float = 1.0) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=end_time_s,
        timestamp_ms=0,
        sample_rate_hz=48_000,
    )


def test_compute_scene_occlusion_clear_path_yields_zero_factor():
    raycaster = FakeRaycaster()
    records = compute_scene_occlusion(_scene(), raycaster)

    assert len(records) == 1
    record = records[0]
    assert record.array_id == "rig_front"
    assert record.source_id == "speaker_a"
    assert record.per_mic_blocked == {"front": False, "right": False}
    assert record.occlusion_factor == 0.0
    assert record.attenuation_db == 0.0
    assert record.hit_prim_paths == ()
    assert len(raycaster.casts) == 2


def test_compute_scene_occlusion_wall_blocks_all_mics():
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),))
    records = compute_scene_occlusion(_scene(), raycaster)

    record = records[0]
    assert record.per_mic_blocked == {"front": True, "right": True}
    assert record.occlusion_factor == 1.0
    assert record.attenuation_db == 20.0
    assert record.hit_prim_paths == (WALL_PRIM_PATH,)


def test_compute_scene_occlusion_partial_wall_yields_fractional_factor():
    # Wall segment only covers the crossing point of the ray toward the
    # offset "right" microphone, not the on-axis "front" microphone.
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, (0.02, 1.0)),))
    records = compute_scene_occlusion(
        _scene(),
        raycaster,
        max_attenuation_db=30.0,
    )

    record = records[0]
    assert record.per_mic_blocked == {"front": False, "right": True}
    assert record.occlusion_factor == pytest.approx(0.5)
    assert record.attenuation_db == pytest.approx(15.0)


def test_compute_scene_occlusion_skips_source_and_array_hits_with_recast():
    self_hits = (
        (f"{SOURCE_PRIM_PATH}/collider", 3.95, None),
        (f"{ARRAY_PRIM_PATH}/mount", 0.05, None),
    )
    clear = FakeRaycaster(walls=self_hits)
    records = compute_scene_occlusion(_scene(), clear)
    assert records[0].occlusion_factor == 0.0
    assert len(clear.casts) > 2

    walled = FakeRaycaster(walls=(*self_hits, (WALL_PRIM_PATH, 2.0, None)))
    records = compute_scene_occlusion(_scene(), walled)
    assert records[0].occlusion_factor == 1.0
    assert records[0].hit_prim_paths == (WALL_PRIM_PATH,)


def test_compute_scene_occlusion_degenerate_short_ray_is_clear():
    # The source sits within two endpoint epsilons of the front microphone:
    # that ray is degenerate and never cast, while the right-microphone ray
    # is still evaluated normally (one blocking hit plus the continuation
    # cast that finds no further surface).
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 0.04, None),))
    scene = _scene(sources=(_source(position=(0.085, 0.0, 0.0)),))
    records = compute_scene_occlusion(scene, raycaster)

    assert records[0].per_mic_blocked == {"front": False, "right": True}
    assert len(raycaster.casts) == 2


def test_source_occlusion_and_snapshot_validation():
    with pytest.raises(ValueError, match="occlusion_factor"):
        SourceOcclusion(array_id="a", source_id="s", occlusion_factor=1.5)
    with pytest.raises(ValueError, match="attenuation_db"):
        SourceOcclusion(array_id="a", source_id="s", attenuation_db=-1.0)
    with pytest.raises(ValueError, match="occlusion record id"):
        _scene(occlusion=(_occlusion_record(), _occlusion_record()))

    scene = _scene(occlusion=(_occlusion_record(),))
    assert scene.occlusion_for("rig_front", "speaker_a") is not None
    assert scene.occlusion_for("rig_front", "unknown") is None
    assert _scene().occlusion_for("rig_front", "speaker_a") is None


def test_geometry_backend_applies_occlusion_attenuation_and_flag():
    backend = GeometryBackend()
    clear_frame = backend.simulate(_scene(), _array(), _window())
    occluded_frame = backend.simulate(
        _scene(occlusion=(_occlusion_record(),)),
        _array(),
        _window(),
    )

    clear = clear_frame.detections[0]
    occluded = occluded_frame.detections[0]
    assert clear.occluded is False
    assert "occlusion" not in clear.diagnostics
    assert occluded.occluded is True
    assert occluded.diagnostics["occlusion"]["attenuation_db"] == 20.0
    assert occluded.diagnostics["occlusion"]["per_mic_blocked"]["front"] is True
    for mic_id, rms in occluded.per_mic_rms.items():
        assert rms == pytest.approx(0.1 * clear.per_mic_rms[mic_id])
    for mic_id, rms in occluded_frame.aggregate_per_mic_rms.items():
        assert rms == pytest.approx(0.1 * clear_frame.aggregate_per_mic_rms[mic_id])


def test_geometry_backend_partial_occlusion_attenuates_without_flag():
    backend = GeometryBackend()
    record = _occlusion_record(factor=0.25, attenuation_db=5.0)
    frame = backend.simulate(
        _scene(occlusion=(record,)),
        _array(),
        _window(),
    )

    detection = frame.detections[0]
    assert detection.occluded is False
    assert detection.diagnostics["occlusion"]["occlusion_factor"] == 0.25
    clear = GeometryBackend().simulate(_scene(), _array(), _window())
    expected_scale = 10.0 ** (-5.0 / 20.0)
    for mic_id, rms in detection.per_mic_rms.items():
        assert rms == pytest.approx(
            expected_scale * clear.detections[0].per_mic_rms[mic_id]
        )


def test_tdoa_backend_attenuates_rms_but_keeps_delays():
    backend = TdoaSyntheticBackend()
    clear_frame = backend.simulate(_scene(), _array(), _window())
    occluded_frame = backend.simulate(
        _scene(occlusion=(_occlusion_record(),)),
        _array(),
        _window(),
    )

    clear = clear_frame.detections[0]
    occluded = occluded_frame.detections[0]
    assert occluded.occluded is True
    assert occluded.per_mic_delay_s == clear.per_mic_delay_s
    assert occluded.doa.estimated_bearing_deg == clear.doa.estimated_bearing_deg
    for mic_id, rms in occluded.per_mic_rms.items():
        assert rms == pytest.approx(0.1 * clear.per_mic_rms[mic_id])


def test_room_backend_scales_source_signal_and_flags_detection():
    pytest.importorskip("pyroomacoustics")
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsBackend,
    )

    room = RoomAcousticsSpec(
        room_id="occlusion_room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.35,
        max_order=1,
        # Explicit placement around the origin-mounted array and the source
        # at x=4 (rooms no longer auto-refit to the scene).
        origin_m=(-1.0, -2.5, -1.5),
    )
    backend = RoomAcousticsBackend()
    window = _window(end_time_s=0.1)
    clear_frame = backend.simulate(_scene(room=room), _array(), window)
    occluded_frame = backend.simulate(
        _scene(room=room, occlusion=(_occlusion_record(),)),
        _array(),
        window,
    )

    occluded = occluded_frame.detections[0]
    assert occluded.occluded is True
    assert occluded.diagnostics["occlusion"]["occlusion_factor"] == 1.0
    for mic_id, rms in occluded_frame.aggregate_per_mic_rms.items():
        assert rms == pytest.approx(
            0.1 * clear_frame.aggregate_per_mic_rms[mic_id],
            rel=1e-6,
        )
    for mic_id, rms in occluded.per_mic_rms.items():
        assert rms == pytest.approx(
            0.1 * clear_frame.detections[0].per_mic_rms[mic_id],
            rel=1e-6,
        )


def test_detection_occluded_flag_round_trips_and_defaults_false():
    frame = AudioSensorFrame(
        frame_id="occlusion_trace",
        timestamp_ms=0,
        backend_id="geometry_only",
        array_id="rig_front",
        detections=(
            AudioDetection(
                detection_id="det_0",
                source_id="speaker_a",
                class_label="Speech",
                detection_mode="scheduled_known_source",
                timestamp_ms=0,
                ground_truth_bearing_deg=0.0,
                source_distance_m=4.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=0.0,
                    candidate_bearing_deg=(0.0,),
                    bearing_confidence=1.0,
                ),
                occluded=True,
            ),
        ),
    )
    payload = frame_to_trace_dict(frame)
    assert payload["detections"][0]["occluded"] is True
    assert frame_from_trace_dict(payload).detections[0].occluded is True

    del payload["detections"][0]["occluded"]
    assert frame_from_trace_dict(payload).detections[0].occluded is False


def test_bearing_ray_color_tracks_occlusion_state():
    def detection(*, occluded: bool, factor: float | None) -> AudioDetection:
        diagnostics = (
            {} if factor is None else {"occlusion": {"occlusion_factor": factor}}
        )
        return AudioDetection(
            detection_id="det_color",
            source_id="speaker_a",
            class_label="Speech",
            detection_mode="scheduled_known_source",
            timestamp_ms=0,
            ground_truth_bearing_deg=0.0,
            source_distance_m=4.0,
            doa=DoaEstimate(
                estimated_bearing_deg=0.0,
                candidate_bearing_deg=(0.0,),
                bearing_confidence=1.0,
            ),
            occluded=occluded,
            diagnostics=diagnostics,
        )

    assert bearing_ray_color(detection(occluded=False, factor=None)) == (
        CLEAR_BEARING_RAY_COLOR
    )
    assert bearing_ray_color(detection(occluded=False, factor=0.25)) == (
        PARTIAL_OCCLUSION_BEARING_RAY_COLOR
    )
    assert bearing_ray_color(detection(occluded=True, factor=1.0)) == (
        OCCLUDED_BEARING_RAY_COLOR
    )


def test_debug_primitives_color_bearing_rays_by_occlusion():
    backend = GeometryBackend()
    frame = backend.simulate(
        _scene(occlusion=(_occlusion_record(),)),
        _array(),
        _window(),
    )
    primitives = build_debug_primitives(
        frame=frame,
        scene=_scene(),
        sensor=_array(),
    )
    rays = [primitive for primitive in primitives if primitive.kind == "bearing_ray"]
    assert rays
    assert rays[0].color_rgba == OCCLUDED_BEARING_RAY_COLOR
    assert rays[0].metadata["occluded"] is True
    assert rays[0].metadata["occlusion_factor"] == 1.0


class _FakePrim:
    def __init__(self, path, type_name, attributes):
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    def __init__(self, prims):
        self._prims = list(prims)

    def Traverse(self):
        return tuple(self._prims)

    def GetPrimAtPath(self, path):
        for prim in self._prims:
            if prim.path == path:
                return prim
        return None


def _fake_stage() -> _FakeStage:
    return _FakeStage(
        (
            _FakePrim(
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
            _FakePrim(
                ARRAY_PRIM_PATH,
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            _FakePrim(
                f"{ARRAY_PRIM_PATH}/front",
                "Xform",
                {
                    "ias:microphone_id": "front",
                    "ias:relative_position_m": (0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                f"{ARRAY_PRIM_PATH}/right",
                "Xform",
                {
                    "ias:microphone_id": "right",
                    "ias:relative_position_m": (0.0, 0.08, 0.0),
                },
            ),
        )
    )


def _live_sensor(stage, **kwargs) -> IsaacAudioArraySensor:
    return IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path=ARRAY_PRIM_PATH,
        backend="geometry_only",
        update_period_s=0.1,
        **kwargs,
    ).start()


def test_live_sensor_occlusion_attenuates_flags_and_reports_diagnostics():
    baseline_sensor = _live_sensor(_fake_stage())
    baseline = baseline_sensor.update(sim_time_s=0.0)

    sensor = _live_sensor(
        _fake_stage(),
        occlusion_enabled=True,
        occlusion_raycaster=FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),)),
    )
    frame = sensor.update(sim_time_s=0.0)

    detection = frame.detections[0]
    assert detection.occluded is True
    assert detection.diagnostics["occlusion"]["hit_prim_paths"] == [WALL_PRIM_PATH]
    for mic_id, rms in detection.per_mic_rms.items():
        assert rms == pytest.approx(0.1 * baseline.detections[0].per_mic_rms[mic_id])
    occlusion_diag = frame.diagnostics["stage_snapshot"]["occlusion"]
    assert occlusion_diag["status"] == "computed"
    assert occlusion_diag["record_count"] == 1
    sensor.close()
    baseline_sensor.close()


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


def test_compute_scene_occlusion_accumulates_multi_hit_transmission():
    walls = ((WALL_PRIM_PATH, 2.0, None), ("/World/Wall2", 3.0, None))
    records = compute_scene_occlusion(_scene(), FakeRaycaster(walls=walls))

    record = records[0]
    assert record.per_mic_blocked == {"front": True, "right": True}
    assert record.per_mic_attenuation_db == {"front": 40.0, "right": 40.0}
    assert record.attenuation_db == 40.0
    assert record.occlusion_model == "raycast_transmission_v1"
    assert record.per_mic_hit_prim_paths["front"] == (
        "/World/Wall2",
        WALL_PRIM_PATH,
    )
    assert set(record.hit_prim_paths) == {WALL_PRIM_PATH, "/World/Wall2"}
    assert record.per_mic_band_attenuation_db == {}


def test_compute_scene_occlusion_caps_accumulated_loss():
    walls = ((WALL_PRIM_PATH, 2.0, None), ("/World/Wall2", 3.0, None))
    records = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=walls),
        attenuation_cap_db=25.0,
    )

    assert records[0].per_mic_attenuation_db["front"] == 25.0
    assert records[0].attenuation_db == 25.0


def test_compute_scene_occlusion_single_hit_matches_legacy_values():
    records = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=((WALL_PRIM_PATH, 2.0, None),)),
    )

    record = records[0]
    assert record.occlusion_factor == 1.0
    assert record.attenuation_db == 20.0
    assert record.per_mic_attenuation_db == {"front": 20.0, "right": 20.0}


class _FakeMaterialPrim:
    def __init__(self, attributes: dict[str, object]) -> None:
        self.attributes = attributes


class _FakeMaterialStage:
    def __init__(self, prims: dict[str, _FakeMaterialPrim]) -> None:
        self._prims = prims

    def GetPrimAtPath(self, path: str) -> _FakeMaterialPrim | None:
        return self._prims.get(path)


def test_transmission_resolver_precedence_attr_then_preset_then_default():
    stage = _FakeMaterialStage(
        {
            "/World/TaggedWall": _FakeMaterialPrim(
                {"ias:transmission_loss_db": 12.0}
            ),
            "/World/ConcreteWall": _FakeMaterialPrim({}),
        }
    )
    resolver = UsdTransmissionLossResolver(stage, default_db=20.0)

    tagged = resolver.loss_for("/World/TaggedWall")
    assert tagged.broadband_db == 12.0
    assert tagged.band_db is None
    assert tagged.material == "usd_attribute"

    preset = resolver.loss_for("/World/ConcreteWall")
    assert preset.material == "concrete"
    assert preset.band_db == DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"]

    default = resolver.loss_for("/World/UnknownWall")
    assert default.broadband_db == 20.0
    assert default.band_db is None
    assert default.material is None


def test_transmission_resolver_reads_band_attribute():
    bands = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
    stage = _FakeMaterialStage(
        {
            "/World/BandWall": _FakeMaterialPrim(
                {"ias:transmission_loss_db_bands": bands}
            ),
        }
    )
    resolver = UsdTransmissionLossResolver(stage)

    loss = resolver.loss_for("/World/BandWall")
    assert loss.band_db == bands
    assert loss.broadband_db == pytest.approx(sum(bands) / len(bands))


def test_compute_scene_occlusion_resolves_material_bands_from_path():
    walls = (("/World/ConcreteWall", 2.0, None),)
    records = compute_scene_occlusion(
        _scene(),
        FakeRaycaster(walls=walls),
        transmission_resolver=UsdTransmissionLossResolver(None),
    )

    record = records[0]
    assert record.band_centers_hz == OCCLUSION_BAND_CENTERS_HZ
    assert record.per_mic_band_attenuation_db["front"] == (
        DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"]
    )
    assert record.hit_materials == {"/World/ConcreteWall": "concrete"}
    assert record.attenuation_db == pytest.approx(
        sum(DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"])
        / len(DEFAULT_MATERIAL_TRANSMISSION_DB["concrete"])
    )


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
        occlusion_factor=0.5,
        attenuation_db=(front_db + right_db) / 2.0,
        per_mic_attenuation_db={"front": front_db, "right": right_db},
        per_mic_band_attenuation_db=band_rows or {},
        band_centers_hz=OCCLUSION_BAND_CENTERS_HZ if band_rows else (),
        occlusion_model="raycast_transmission_v1",
    )


def test_geometry_backend_applies_per_mic_attenuation_independently():
    baseline = GeometryBackend().simulate(_scene(), _array(), _window())
    occluded = GeometryBackend().simulate(
        _scene(occlusion=(_per_mic_record(),)),
        _array(),
        _window(),
    )

    base_rms = baseline.detections[0].per_mic_rms
    occluded_rms = occluded.detections[0].per_mic_rms
    assert occluded_rms["front"] == pytest.approx(0.1 * base_rms["front"])
    assert occluded_rms["right"] == pytest.approx(base_rms["right"])
    diagnostics = occluded.detections[0].diagnostics["occlusion"]
    assert diagnostics["per_mic_attenuation_db"] == {"front": 20.0, "right": 0.0}
    assert diagnostics["occlusion_model"] == "raycast_transmission_v1"


def test_tdoa_backend_applies_per_mic_attenuation_and_keeps_delays():
    backend = TdoaSyntheticBackend(ambiguity_policy="front_hemisphere")
    baseline = backend.simulate(_scene(), _array(), _window())
    occluded = backend.simulate(
        _scene(occlusion=(_per_mic_record(),)),
        _array(),
        _window(),
    )

    base = baseline.detections[0]
    occ = occluded.detections[0]
    assert occ.per_mic_rms["front"] == pytest.approx(0.1 * base.per_mic_rms["front"])
    assert occ.per_mic_rms["right"] == pytest.approx(base.per_mic_rms["right"])
    assert occ.per_mic_delay_s == base.per_mic_delay_s
    assert occ.doa.estimated_bearing_deg == base.doa.estimated_bearing_deg


def _tone_room_scene(occlusion=None) -> AudioSceneSnapshot:
    tone_source = AudioSourceSpec(
        source_id="tone_high",
        prim_path="/World/Sources/ToneHigh",
        class_label="Speech",
        audio_asset_path=None,
        position_world=(3.0, 0.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )
    return _scene(
        sources=(tone_source,),
        room=RoomAcousticsSpec(
            room_id="occlusion_band_room",
            dimensions_m=(8.0, 6.0, 3.0),
            absorption=0.35,
            max_order=1,
            origin_m=(-2.0, -3.0, -1.5),
        ),
        occlusion=occlusion,
    )


def _band_record(rows: tuple[float, ...]) -> SourceOcclusion:
    return SourceOcclusion(
        array_id="rig_front",
        source_id="tone_high",
        per_mic_blocked={"front": True, "right": True},
        occlusion_factor=1.0,
        attenuation_db=sum(rows) / len(rows),
        per_mic_attenuation_db={"front": sum(rows) / len(rows)} | {
            "right": sum(rows) / len(rows)
        },
        per_mic_band_attenuation_db={"front": rows, "right": rows},
        band_centers_hz=OCCLUSION_BAND_CENTERS_HZ,
        occlusion_model="raycast_transmission_v1",
    )


class _CaptureSink:
    def __init__(self) -> None:
        self.mixtures: list[np.ndarray] = []

    def write_frame_mixture(
        self,
        *,
        frame_id,
        mixture,
        sample_rate_hz,
        mic_ids,
        window_sample_count,
    ):
        self.mixtures.append(np.array(mixture))
        return WaveformWriteResult(
            paths=(f"stub://{frame_id}.wav",),
            diagnostics={"mode": "stub"},
        )

    def close(self) -> None:
        return None


def _tone_levels_db(channel: np.ndarray) -> tuple[float, float]:
    seed = int(hashlib.sha256(b"tone_high").hexdigest()[:8], 16)
    fundamental_hz = 550.0 + float(seed % 700)
    overtone_hz = fundamental_hz * 1.618033988749895
    spectrum = np.abs(np.fft.rfft(channel[:48_000]))

    def _peak_db(frequency_hz: float) -> float:
        center = int(round(frequency_hz))
        return 20.0 * np.log10(
            max(float(np.max(spectrum[center - 2 : center + 3])), 1e-12)
        )

    return _peak_db(fundamental_hz), _peak_db(overtone_hz)


def test_room_backend_band_attenuation_shapes_mixture_spectrum(monkeypatch):
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsBackend,
    )
    from tests.helpers import install_fake_pyroom as _install_fake_pyroom

    _install_fake_pyroom(monkeypatch)
    rows = (0.0, 0.0, 0.0, 40.0, 40.0, 40.0)

    clear_sink = _CaptureSink()
    RoomAcousticsBackend(waveform_writer=clear_sink).simulate(
        _tone_room_scene(), _array(), _window()
    )
    occluded_sink = _CaptureSink()
    occluded_frame = RoomAcousticsBackend(waveform_writer=occluded_sink).simulate(
        _tone_room_scene(occlusion=(_band_record(rows),)),
        _array(),
        _window(),
    )

    clear_fund, clear_over = _tone_levels_db(clear_sink.mixtures[0][0])
    occ_fund, occ_over = _tone_levels_db(occluded_sink.mixtures[0][0])
    overtone_drop = clear_over - occ_over
    fundamental_drop = clear_fund - occ_fund
    # The material wall attenuates the high overtone much more than the
    # low fundamental.
    assert overtone_drop - fundamental_drop >= 15.0
    assert overtone_drop >= 30.0

    diagnostics = occluded_frame.detections[0].diagnostics["occlusion"]
    assert diagnostics["band_centers_hz"] == list(OCCLUSION_BAND_CENTERS_HZ)
    assert diagnostics["per_mic_band_attenuation_db"]["front"] == list(rows)
    # Aggregate RMS derives from the same attenuated mixture.
    for mic_id, rms in occluded_frame.aggregate_per_mic_rms.items():
        channel = occluded_sink.mixtures[0][
            0 if mic_id == "front" else 1
        ]
        assert rms == pytest.approx(
            float(np.sqrt(np.mean(channel**2))),
            rel=1e-9,
        )


def test_room_backend_band_attenuation_shows_in_exported_wav(
    monkeypatch, tmp_path
):
    soundfile = pytest.importorskip("soundfile")
    from isaac_audio_sensors.core.backends.room_acoustics import (
        RoomAcousticsBackend,
    )
    from isaac_audio_sensors.core.io.waveforms import FrameWaveformWriter
    from tests.helpers import install_fake_pyroom as _install_fake_pyroom

    _install_fake_pyroom(monkeypatch)
    rows = (0.0, 0.0, 0.0, 40.0, 40.0, 40.0)

    clear_frame = RoomAcousticsBackend(
        waveform_writer=FrameWaveformWriter(tmp_path / "clear")
    ).simulate(_tone_room_scene(), _array(), _window())
    occluded_frame = RoomAcousticsBackend(
        waveform_writer=FrameWaveformWriter(tmp_path / "occluded")
    ).simulate(
        _tone_room_scene(occlusion=(_band_record(rows),)),
        _array(),
        _window(),
    )

    clear_data, _ = soundfile.read(clear_frame.waveform_paths[0], always_2d=True)
    occ_data, _ = soundfile.read(occluded_frame.waveform_paths[0], always_2d=True)
    clear_fund, clear_over = _tone_levels_db(clear_data[:, 0])
    occ_fund, occ_over = _tone_levels_db(occ_data[:, 0])
    assert (clear_over - occ_over) - (clear_fund - occ_fund) >= 15.0


def test_occlusion_diagnostics_round_trip_new_fields():
    record = _per_mic_record(
        band_rows={
            "front": (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
            "right": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        },
    )
    frame = GeometryBackend().simulate(
        _scene(occlusion=(record,)), _array(), _window()
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
    assert diagnostics["occlusion_model"] == "raycast_transmission_v1"


def test_source_occlusion_validates_band_rows():
    with pytest.raises(ValueError, match="band_centers_hz length"):
        SourceOcclusion(
            array_id="a",
            source_id="s",
            per_mic_band_attenuation_db={"front": (1.0, 2.0)},
            band_centers_hz=OCCLUSION_BAND_CENTERS_HZ,
        )
    with pytest.raises(ValueError, match="non-negative"):
        SourceOcclusion(
            array_id="a",
            source_id="s",
            per_mic_attenuation_db={"front": -1.0},
        )


class _RepeatingHitRaycaster:
    """Simulates a thick collider re-hit on every continuation cast."""

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
    assert record.per_mic_hit_prim_paths["front"] == (WALL_PRIM_PATH,)
