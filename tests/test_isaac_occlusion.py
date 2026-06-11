"""Occlusion: Isaac-layer raycasts computed, pure-core backends consume."""

from __future__ import annotations

from dataclasses import replace

import pytest

from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
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
    IsaacPhysxRaycaster,
    OcclusionHit,
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
    # is still evaluated normally.
    raycaster = FakeRaycaster(walls=((WALL_PRIM_PATH, 0.04, None),))
    scene = _scene(sources=(_source(position=(0.085, 0.0, 0.0)),))
    records = compute_scene_occlusion(scene, raycaster)

    assert records[0].per_mic_blocked == {"front": False, "right": True}
    assert len(raycaster.casts) == 1


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


def test_isaac_physx_raycaster_unavailable_path_is_lazy_and_clear():
    raycaster = IsaacPhysxRaycaster()
    try:
        raycaster.raycast_closest((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0)
    except IsaacIntegrationUnavailable as exc:
        assert "omni.physx" in str(exc)
        return
    pytest.skip("omni.physx is installed; unavailable path is not active.")
