"""Dynamic-environment, moving-occluder, and consistency tests."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics import shoebox_environment
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.constants import OCCLUSION_BAND_CENTERS_HZ
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.io.waveforms import WaveformWriteResult
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    SourceOcclusion,
)
from isaac_audio_sensors.isaac.occlusion import OcclusionHit
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_cache import StageAudioCache

SAMPLE_RATE_HZ = 48_000
MIC_IDS = ("front", "right", "rear", "left")
SOURCE_PATH = "/World/Source"
ARRAY_PATH = "/World/Array"
ENVIRONMENT_PATH = "/World/Environment"
WALL_PATH = "/World/Wall"


class _CaptureSink:
    def __init__(self) -> None:
        self.mixtures: list[np.ndarray] = []

    def write_frame_mixture(self, **kwargs):
        self.mixtures.append(np.asarray(kwargs["mixture"], dtype=np.float64).copy())
        return WaveformWriteResult(paths=("memory://fixture.wav",))

    def close(self):
        return None


class _FakeMaterial:
    def __init__(self, absorption):
        self.absorption = absorption


class _FakeMicrophoneArray:
    def __init__(self, positions, fs):
        self.R = np.asarray(positions, dtype=float)
        self.fs = int(fs)


class _StatefulShoeBox:
    instances: list[_StatefulShoeBox] = []
    compute_rir_calls = 0

    def __init__(self, dimensions, *, fs, materials=None, **_kwargs):
        self.dimensions = tuple(float(value) for value in dimensions)
        self.fs = int(fs)
        self.materials = materials
        self.sources = []
        self.mic_array = None
        self.rir = []
        type(self).instances.append(self)

    def add_source(self, position, signal):
        self.sources.append((tuple(position), np.asarray(signal, dtype=float)))

    def add_microphone_array(self, mic_array):
        self.mic_array = mic_array

    def compute_rir(self):
        type(self).compute_rir_calls += 1
        assert self.mic_array is not None
        material = getattr(self.materials, "absorption", self.materials)
        material_bytes = json.dumps(material, sort_keys=True, default=list).encode()
        geometry = sum(sum(position) for position, _signal in self.sources) + float(
            np.sum(self.mic_array.R)
        )
        state = (
            sum(self.dimensions)
            + geometry
            + int(hashlib.sha256(material_bytes).hexdigest()[:4], 16)
        )
        gain = 0.5 + (state % 997) / 1994.0
        self.rir = [
            [np.asarray([gain], dtype=float) for _source in self.sources]
            for _mic in self.mic_array.R.T
        ]

    def simulate(self, return_premix=False):
        assert self.mic_array is not None
        sample_count = max(signal.size for _position, signal in self.sources)
        fixture_signal = _six_tone()[:sample_count]
        premix = np.zeros((len(self.sources), self.mic_array.R.shape[1], sample_count))
        for source_index, (_position, signal) in enumerate(self.sources):
            for mic_index in range(self.mic_array.R.shape[1]):
                premix[source_index, mic_index, : signal.size] = (
                    fixture_signal * self.rir[mic_index][source_index][0]
                )
        return premix if return_premix else None


@pytest.fixture
def fake_room(monkeypatch):
    fake = types.ModuleType("pyroomacoustics")
    fake.__version__ = "room-fixture"
    fake.Material = _FakeMaterial
    fake.MicrophoneArray = _FakeMicrophoneArray
    fake.ShoeBox = _StatefulShoeBox
    _StatefulShoeBox.instances = []
    _StatefulShoeBox.compute_rir_calls = 0
    monkeypatch.setitem(sys.modules, "pyroomacoustics", fake)
    return fake


def _six_tone():
    samples = np.arange(SAMPLE_RATE_HZ, dtype=float)
    return sum(
        0.1 * np.sin(2.0 * np.pi * frequency * samples / SAMPLE_RATE_HZ)
        for frequency in OCCLUSION_BAND_CENTERS_HZ
    )


def _array(position=(0.0, 0.0, 1.0)):
    return create_microphone_array(
        array_id="rig_front",
        prim_path=ARRAY_PATH,
        layout_name="quad_front",
        position_world=position,
    )


def _source(position=(4.0, 0.0, 1.0)):
    return AudioSourceSpec(
        source_id="tone",
        prim_path=SOURCE_PATH,
        class_label="Tone",
        audio_asset_path="generated://tone",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _environment(
    absorption="pra.rough_concrete",
    *,
    dimensions_m=(6.0, 6.0, 3.0),
    position_world=(-1.0, -3.0, 0.0),
):
    return shoebox_environment(
        environment_id="dynamic_environment",
        dimensions_m=dimensions_m,
        position_world=position_world,
        absorption=absorption,
    )


def _window():
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=1.0,
        timestamp_ms=0,
        sample_rate_hz=SAMPLE_RATE_HZ,
        frame_index=0,
    )


def _record(blocked, bands=None, flat_db=0.0, material=None):
    per_mic_blocked = {mic_id: mic_id in blocked for mic_id in MIC_IDS}
    broadband = {
        mic_id: (sum(bands) / len(bands) if bands is not None else flat_db)
        if mic_id in blocked
        else 0.0
        for mic_id in MIC_IDS
    }
    band_rows = (
        {mic_id: (bands if mic_id in blocked else (0.0,) * 6) for mic_id in MIC_IDS}
        if bands is not None
        else {}
    )
    return SourceOcclusion(
        array_id="rig_front",
        source_id="tone",
        per_mic_blocked=per_mic_blocked,
        occlusion_factor=len(blocked) / 4,
        attenuation_db=sum(broadband.values()) / 4,
        hit_prim_paths=(WALL_PATH,) if blocked else (),
        per_mic_attenuation_db=broadband,
        per_mic_band_attenuation_db=band_rows,
        band_centers_hz=OCCLUSION_BAND_CENTERS_HZ if bands is not None else (),
        per_mic_hit_prim_paths={
            mic_id: ((WALL_PATH,) if mic_id in blocked else ()) for mic_id in MIC_IDS
        },
        hit_materials=({WALL_PATH: material} if blocked and material else {}),
        occlusion_model="raycast_transmission_v1",
    )


def _render(fake_room, record=None, environment=None):
    array = _array()
    scene = AudioSceneSnapshot(
        stage_id="dynamic_room_fixture",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(array,),
        environment=environment or _environment(),
        occlusion=None if record is None else (record,),
    )
    sink = _CaptureSink()
    frame = RoomAcousticsBackend(max_order=1, waveform_writer=sink).simulate(
        scene, array.array_id, _window()
    )
    return frame, sink.mixtures[0]


def _center_losses(clear, observed):
    losses = {}
    for mic_index, mic_id in enumerate(MIC_IDS):
        clear_fft = np.fft.rfft(clear[mic_index])
        observed_fft = np.fft.rfft(observed[mic_index])
        losses[mic_id] = tuple(
            -20.0
            * math.log10(
                abs(observed_fft[int(frequency)]) / abs(clear_fft[int(frequency)])
            )
            for frequency in OCCLUSION_BAND_CENTERS_HZ
        )
    return losses


def test_clear_blocked_partial_and_material_swap_consistency(fake_room):
    clear_frame, clear = _render(fake_room, _record(set()))
    concrete = (33.0, 36.0, 40.0, 44.0, 50.0, 55.0)
    blocked_frame, blocked = _render(
        fake_room,
        _record(set(MIC_IDS), concrete, material="nominal.concrete"),
    )
    wood = (15.0, 19.0, 23.0, 26.0, 29.0, 32.0)
    partial_frame, partial = _render(
        fake_room,
        _record({"right"}, wood, material="nominal.wood"),
    )
    glass = (18.0, 22.0, 26.0, 30.0, 33.0, 36.0)
    glass_frame, glass_wave = _render(
        fake_room,
        _record(set(MIC_IDS), glass, material="nominal.glass"),
    )
    blocked_losses = _center_losses(clear, blocked)
    partial_losses = _center_losses(clear, partial)
    for mic_id in MIC_IDS:
        assert (
            max(
                abs(measured - expected)
                for measured, expected in zip(
                    blocked_losses[mic_id], concrete, strict=True
                )
            )
            <= 0.05
        )
    assert (
        max(
            abs(measured - expected)
            for measured, expected in zip(partial_losses["right"], wood, strict=True)
        )
        <= 0.05
    )
    for mic_id in ("front", "rear", "left"):
        assert max(abs(value) for value in partial_losses[mic_id]) <= 0.05
    assert clear_frame.detections[0].occluded is False
    assert blocked_frame.detections[0].occluded is True
    assert partial_frame.detections[0].occluded is False
    assert not np.array_equal(blocked, glass_wave)
    assert blocked_frame.aggregate_per_mic_rms != glass_frame.aggregate_per_mic_rms


def test_five_frame_moving_wall_sequence_is_fresh_and_deterministic(fake_room):
    blocked_maps = (set(), {"right"}, set(MIC_IDS), {"left"}, set())
    mixtures = []
    frames = []
    for blocked in blocked_maps:
        frame, mixture = _render(fake_room, _record(blocked, flat_db=12.0))
        frames.append(frame)
        mixtures.append(mixture)
    assert mixtures[0].tobytes() == mixtures[4].tobytes()
    assert (
        frame_to_trace_dict(frames[0])["detections"][0]["diagnostics"]["occlusion"]
        == frame_to_trace_dict(frames[4])["detections"][0]["diagnostics"]["occlusion"]
    )
    assert mixtures[1][1].tobytes() != mixtures[0][1].tobytes()
    assert mixtures[1][0].tobytes() == mixtures[0][0].tobytes()
    assert mixtures[3][3].tobytes() != mixtures[0][3].tobytes()
    assert all(
        mixtures[2][index].tobytes() != mixtures[0][index].tobytes()
        for index in range(4)
    )
    clear_rms = frames[0].aggregate_per_mic_rms
    for state, blocked in enumerate(blocked_maps):
        for mic_id in MIC_IDS:
            measured = 20.0 * math.log10(
                clear_rms[mic_id] / frames[state].aggregate_per_mic_rms[mic_id]
            )
            expected = 12.0 if mic_id in blocked else 0.0
            assert abs(measured - expected) <= 1e-6


def test_environment_hash_and_output_diverge_for_geometry_and_material_mutations(
    fake_room,
):
    base_frame, base_wave = _render(fake_room)
    translated_frame, translated_wave = _render(
        fake_room,
        environment=_environment(position_world=(-0.75, -3.0, 0.0)),
    )
    dimension_frame, dimension_wave = _render(
        fake_room,
        environment=_environment(dimensions_m=(7.0, 6.0, 3.0)),
    )
    material_frame, material_wave = _render(
        fake_room,
        environment=_environment(absorption="pra.carpet_cotton"),
    )
    hashes = {
        frame.diagnostics["acoustics_state"]["environment_state_hash"]
        for frame in (base_frame, translated_frame, dimension_frame, material_frame)
    }
    assert len(hashes) == 4
    assert not np.array_equal(base_wave, translated_wave)
    assert not np.array_equal(base_wave, dimension_wave)
    assert not np.array_equal(base_wave, material_wave)
    assert _StatefulShoeBox.compute_rir_calls == 4
    evidence = material_frame.diagnostics["acoustics_state"]["material_evidence"]
    assert evidence["environment"]["evidence"] == "measured"
    assert "citation" in evidence["environment"]


def test_source_and_array_motion_use_current_endpoints_without_stale_output(fake_room):
    base_frame, base_wave = _render(fake_room)
    array = _array(position=(0.0, 0.25, 1.0))
    array_scene = AudioSceneSnapshot(
        stage_id="dynamic_room_fixture",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(array,),
        environment=_environment(),
    )
    array_sink = _CaptureSink()
    array_frame = RoomAcousticsBackend(waveform_writer=array_sink).simulate(
        array_scene,
        array.array_id,
        _window(),
    )
    source_scene = replace(
        array_scene,
        sources=(_source(position=(3.5, 0.0, 1.0)),),
        arrays=(_array(),),
    )
    source_sink = _CaptureSink()
    source_frame = RoomAcousticsBackend(waveform_writer=source_sink).simulate(
        source_scene,
        source_scene.arrays[0].array_id,
        _window(),
    )
    assert array_frame.array_pose.position_m == (0.0, 0.25, 1.0)
    assert source_frame.detections[0].source_pose.position_m == (3.5, 0.0, 1.0)
    assert array_sink.mixtures[0].tobytes() != base_wave.tobytes()
    assert source_sink.mixtures[0].tobytes() != base_wave.tobytes()
    assert base_frame.detections[0].source_pose.position_m == (4.0, 0.0, 1.0)


class _Prim:
    def __init__(self, path, type_name, attributes):
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _Stage:
    identifier = "dynamic_room_stage"

    def __init__(self):
        self.traversals = 0
        self.prims = {
            SOURCE_PATH: _Prim(
                SOURCE_PATH,
                "Sound",
                {
                    "filePath": "generated://tone",
                    "ias:source_id": "tone",
                    "ias:position_world": (4.0, 0.0, 1.0),
                    "ias:start_time_s": 0.0,
                },
            ),
            ARRAY_PATH: _Prim(
                ARRAY_PATH,
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:layout_name": "quad_front",
                    "ias:sample_rate_hz": SAMPLE_RATE_HZ,
                    "ias:position_world": (0.0, 0.0, 1.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            ENVIRONMENT_PATH: _Prim(
                ENVIRONMENT_PATH,
                "Xform",
                {
                    "ias:environment_min_world": (-1.0, -3.0, 0.0),
                    "ias:environment_max_world": (5.0, 3.0, 3.0),
                    "ias:acoustic_material_id": "pra.rough_concrete",
                },
            ),
            WALL_PATH: _Prim(
                WALL_PATH,
                "Cube",
                {"ias:transmission_loss_db": 12.0},
            ),
        }

    def Traverse(self):
        self.traversals += 1
        return tuple(self.prims.values())

    def GetPrimAtPath(self, path):
        return self.prims.get(str(path))


def _notice(*paths, resynced=()):
    return SimpleNamespace(
        GetResyncedPaths=lambda: tuple(resynced),
        GetChangedInfoOnlyPaths=lambda: tuple(paths),
    )


def test_stage_cache_reason_taxonomy_order_and_actions():
    stage = _Stage()
    cache = StageAudioCache(stage, environment_anchor_prim_path=ENVIRONMENT_PATH)
    cache.snapshot(timestamp_ms=0, array_prim_path=ARRAY_PATH)
    baseline_traversals = stage.traversals
    cache._on_objects_changed(
        _notice(
            f"{ENVIRONMENT_PATH}.xformOp:translate",
            f"{ENVIRONMENT_PATH}.ias:acoustic_material_id",
        ),
        None,
    )
    assert cache.current_acoustic_refresh_reasons == (
        "environment_geometry_changed",
        "material_changed",
    )
    cache.snapshot(timestamp_ms=1, array_prim_path=ARRAY_PATH)
    assert stage.traversals == baseline_traversals + 1
    cache.consume_acoustic_refresh_reasons()
    cache._on_objects_changed(
        _notice(f"{WALL_PATH}.xformOp:translate"),
        None,
    )
    assert cache.pending_non_audio_pose_paths == (WALL_PATH,)
    assert cache._dirty is False
    cache.record_acoustic_refresh("occluder_moved")
    assert cache._dirty is False
    assert cache.current_acoustic_refresh_reasons == ("occluder_moved",)
    assert cache._cache_diagnostics(hit=True)["acoustic_refresh_reasons"] == (
        "environment_geometry_changed",
        "material_changed",
        "occluder_moved",
    )


class _MovingRaycaster:
    def __init__(self):
        self.blocked = False

    def raycast_closest(self, _origin, _direction, _distance):
        if not self.blocked:
            return None
        return OcclusionHit(prim_path=WALL_PATH, distance_m=2.0)


def test_live_sensor_preserves_static_environment_without_anchor():
    environment = _environment()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=_Stage(),
        array_prim_path=ARRAY_PATH,
        backend="geometry_only",
        environment=environment,
    ).start()

    sensor.update(sim_time_s=0.0, force=True)

    assert sensor.environment == environment
    assert sensor.latest_scene is not None
    assert sensor.latest_scene.environment == environment
    sensor.close()


def test_live_extension_tracks_occluder_move_and_anchor_refresh_without_stale_state():
    stage = _Stage()
    raycaster = _MovingRaycaster()
    environment = _environment()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path=ARRAY_PATH,
        backend="geometry_only",
        environment=environment,
        environment_anchor_prim_path=ENVIRONMENT_PATH,
        occlusion_enabled=True,
        occlusion_raycaster=raycaster,
        update_period_s=0.05,
    ).start()
    first = sensor.update(sim_time_s=0.0, force=True)
    full_before = sensor._stage_cache.full_discovery_count
    raycaster.blocked = True
    sensor._stage_cache._on_objects_changed(
        _notice(f"{WALL_PATH}.xformOp:translate"),
        None,
    )
    second = sensor.update(sim_time_s=0.1, force=True)
    state = second.diagnostics["acoustics_state"]
    assert state["occlusion_recompute_count"] == 1
    assert state["refresh_reasons"] == ["occluder_moved"]
    assert state["changed_occlusion_pairs"] == ["rig_front:tone"]
    assert sensor._stage_cache.full_discovery_count == full_before
    assert first.detections[0].occluded is False
    assert second.detections[0].occluded is True
    stage.prims[ENVIRONMENT_PATH].attributes["ias:environment_min_world"] = (
        -0.75,
        -3.0,
        0.0,
    )
    stage.prims[ENVIRONMENT_PATH].attributes["ias:acoustic_material_id"] = (
        "pra.carpet_cotton"
    )
    sensor._stage_cache._on_objects_changed(
        _notice(
            f"{ENVIRONMENT_PATH}.ias:environment_min_world",
            f"{ENVIRONMENT_PATH}.ias:acoustic_material_id",
        ),
        None,
    )
    third = sensor.update(sim_time_s=0.2, force=True)
    assert sensor.latest_scene is not None
    assert sensor.latest_scene.environment is not None
    assert sensor.latest_scene.environment.world_pose.position_m == (
        -0.75,
        -3.0,
        0.0,
    )
    assert all(
        surface.absorption == "pra.carpet_cotton"
        for surface in sensor.latest_scene.environment.surfaces
    )
    assert third.diagnostics["acoustics_state"]["refresh_reasons"] == [
        "environment_geometry_changed",
        "material_changed",
    ]
    sensor.close()


def test_anchor_deletion_fails_before_backend_frame_and_keeps_reason_pending():
    stage = _Stage()
    environment = _environment()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path=ARRAY_PATH,
        backend="geometry_only",
        environment=environment,
        environment_anchor_prim_path=ENVIRONMENT_PATH,
    ).start()
    sensor.update(sim_time_s=0.0, force=True)
    stage.prims.pop(ENVIRONMENT_PATH)
    sensor._stage_cache._on_objects_changed(
        _notice(resynced=(ENVIRONMENT_PATH,)),
        None,
    )
    with pytest.raises(
        ValueError,
        match="Environment anchor.*missing.*previous environment",
    ):
        sensor.update(sim_time_s=0.1, force=True)
    assert "environment_geometry_changed" in (
        sensor._stage_cache.current_acoustic_refresh_reasons
    )


def test_off_state_frame_has_no_acoustics_namespace_and_is_byte_deterministic():
    array = _array()
    scene = AudioSceneSnapshot(
        stage_id="off",
        timestamp_ms=0,
        sources=(_source(),),
        arrays=(array,),
    )
    first = GeometryBackend().simulate(scene, array.array_id, _window())
    second = GeometryBackend().simulate(scene, array.array_id, _window())
    assert "acoustics_state" not in first.diagnostics
    first_bytes = json.dumps(frame_to_trace_dict(first), sort_keys=True).encode()
    second_bytes = json.dumps(frame_to_trace_dict(second), sort_keys=True).encode()
    assert first_bytes == second_bytes
