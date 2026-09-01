from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics.environments import (
    environment_to_world_point,
    free_field_environment,
    half_space_environment,
    polygon_prism_environment,
    shoebox_environment,
    surface_set_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.effects.validation import UnsupportedEffectError
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AcousticSurfaceSpec,
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    SourceOcclusion,
)
from tests.helpers import CaptureSink, FakeMaterial, FakeMicrophoneArray, FakeShoeBox

SAMPLE_RATE_HZ = 48_000
WINDOW = AudioTimeWindow(
    start_time_s=0.0,
    end_time_s=0.1,
    timestamp_ms=0,
    sample_rate_hz=SAMPLE_RATE_HZ,
    frame_index=0,
)


def _array(
    position_world=(0.0, 0.0, 1.0),
    orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=position_world,
        orientation_world_quat=orientation_world_quat,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )


def _source(position_world=(2.0, 0.0, 1.0)) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position_world,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _scene(environment, *, array=None, source=None) -> AudioSceneSnapshot:
    array = _array() if array is None else array
    source = _source() if source is None else source
    return AudioSceneSnapshot(
        stage_id="analytic_test",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
        environment=environment,
    )


def test_free_field_uses_core_without_importing_pyroom(monkeypatch) -> None:
    import isaac_audio_sensors.core.backends.analytic as analytic_module

    def blocked_import(name: str):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(analytic_module.importlib, "import_module", blocked_import)
    scene = _scene(free_field_environment(environment_id="free"))
    sink = CaptureSink()
    backend = AnalyticAcoustics(waveform_writer=sink)

    first = backend.simulate(scene, "rig", WINDOW)
    second = backend.simulate(scene, "rig", WINDOW)

    assert first == second
    assert first.backend_id == "analytic_acoustics"
    assert first.provenance == "synthetic/core"
    assert first.diagnostics["analytic_solver"] == {
        "solver_id": "free_field_direct",
        "provider": "core",
        "environment_kind": "free_field",
    }
    assert "pyroomacoustics_version" not in first.diagnostics
    assert first.waveform_paths == (f"stub://{first.frame_id}.wav",)
    assert sink.calls[0]["mixture"].shape[0] == 4
    assert sink.calls[0]["window_sample_count"] == WINDOW.sample_rate_hz // 10
    assert first.detections[0].diagnostics["analytic_solver"] == (
        first.diagnostics["analytic_solver"]
    )
    assert all(value > 0.0 for value in first.aggregate_per_mic_rms.values())


def test_half_space_uses_rotated_local_plane_and_one_floor_reflection() -> None:
    root_half = 2.0**-0.5
    orientation = (root_half, 0.0, 0.0, root_half)
    environment = half_space_environment(
        environment_id="tilted_floor",
        absorption=0.0,
        position_world=(1.0, -2.0, 0.5),
        orientation_world_quat=orientation,
    )
    array = _array(
        environment_to_world_point(environment, (1.0, 2.0, 1.0)),
        orientation,
    )
    source = _source(environment_to_world_point(environment, (3.0, 2.0, 1.0)))
    scene = _scene(environment, array=array, source=source)

    direct = AnalyticAcoustics(max_order=0).simulate(scene, "rig", WINDOW)
    reflected = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)

    assert reflected.diagnostics["analytic_solver"]["solver_id"] == (
        "half_space_image_source"
    )
    assert reflected.aggregate_per_mic_rms["front"] > (
        direct.aggregate_per_mic_rms["front"]
    )
    direct_delay = direct.detections[0].diagnostics["direct_path_delay_s"]["front"]
    reflected_delay = reflected.detections[0].diagnostics[
        "direct_path_delay_s"
    ]["front"]
    assert reflected_delay == pytest.approx(direct_delay)


def test_half_space_material_and_containment_are_fail_closed() -> None:
    fully_absorbing = half_space_environment(
        environment_id="floor",
        absorption=1.0,
    )
    scene = _scene(fully_absorbing)
    direct = AnalyticAcoustics(max_order=0).simulate(scene, "rig", WINDOW)
    reflected = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)
    assert reflected.aggregate_per_mic_rms == pytest.approx(
        direct.aggregate_per_mic_rms
    )

    below = _scene(
        fully_absorbing,
        source=_source((2.0, 0.0, -0.01)),
    )
    with pytest.raises(ValueError, match="below half_space"):
        AnalyticAcoustics(max_order=1).simulate(below, "rig", WINDOW)

    named_material = half_space_environment(
        environment_id="material_floor",
        absorption="pra.rough_concrete",
    )
    material_frame = AnalyticAcoustics(max_order=1).simulate(
        _scene(named_material),
        "rig",
        WINDOW,
    )
    assert material_frame.diagnostics["acoustics_state"]["material_evidence"]


@pytest.mark.parametrize(
    ("environment", "kwargs", "message"),
    (
        (
            free_field_environment(environment_id="free"),
            {"max_order": 1},
            "requires max_order=0",
        ),
        (
            half_space_environment(environment_id="half"),
            {"max_order": 2},
            "supports max_order 0 or 1",
        ),
        (
            free_field_environment(environment_id="free"),
            {"air_absorption": True},
            "only for PyRoom",
        ),
        (
            half_space_environment(environment_id="half"),
            {"ray_tracing": True},
            "only for PyRoom",
        ),
    ),
)
def test_core_solver_options_fail_closed(environment, kwargs, message) -> None:
    with pytest.raises(UnsupportedEffectError, match=message):
        AnalyticAcoustics(**kwargs).simulate(_scene(environment), "rig", WINDOW)


def test_surface_set_and_source_occlusion_are_rejected() -> None:
    surface = AcousticSurfaceSpec(
        surface_id="panel",
        role="wall",
        vertices_local_m=((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
        absorption=0.2,
    )
    environment = surface_set_environment(
        environment_id="panels",
        surfaces=(surface,),
    )
    with pytest.raises(UnsupportedEffectError, match="GeometryAcoustics"):
        AnalyticAcoustics().simulate(_scene(environment), "rig", WINDOW)

    occluded = replace(
        _scene(free_field_environment(environment_id="free")),
        occlusion=(
            SourceOcclusion(
                array_id="rig",
                source_id="speaker",
                occlusion_factor=1.0,
                attenuation_db=20.0,
            ),
        ),
    )
    with pytest.raises(UnsupportedEffectError, match="R8.1"):
        AnalyticAcoustics().simulate(occluded, "rig", WINDOW)


def test_closed_room_import_error_is_actionable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyroomacoustics", None)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
    )

    with pytest.raises(OptionalDependencyUnavailable, match="optional 'room' extra"):
        AnalyticAcoustics().simulate(_scene(environment), "rig", WINDOW)


def test_shoebox_routes_to_pyroom_with_per_surface_materials(monkeypatch) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = shoebox_environment(
        environment_id="room",
        dimensions_m=(6.0, 5.0, 3.0),
        absorption=0.2,
    )
    environment = replace(
        environment,
        surfaces=tuple(
            replace(surface, absorption=0.1 + index * 0.1)
            for index, surface in enumerate(environment.surfaces)
        ),
    )

    frame = AnalyticAcoustics(max_order=1).simulate(
        _scene(
            environment,
            array=_array((1.0, 1.0, 1.0)),
            source=_source((3.0, 1.0, 1.0)),
        ),
        "rig",
        WINDOW,
    )

    assert frame.provenance == "room_acoustics"
    assert frame.diagnostics["analytic_solver"] == {
        "solver_id": "pyroom_shoebox",
        "provider": "pyroomacoustics",
        "environment_kind": "shoebox",
    }
    assert frame.diagnostics["pyroomacoustics_version"] == "fake-analytic"
    assert set(frame.diagnostics["environment_config"]["absorption"]) == {
        surface.surface_id for surface in environment.surfaces
    }
    assert set(module.ShoeBox.instances[-1].kwargs["materials"]) == {
        "west",
        "east",
        "south",
        "north",
        "floor",
        "ceiling",
    }


def test_concave_polygon_routes_through_from_corners_and_checks_containment(
    monkeypatch,
) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = polygon_prism_environment(
        environment_id="concave",
        floor_vertices_local_m=(
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 4.0, 0.0),
            (2.0, 2.0, 0.0),
            (0.0, 4.0, 0.0),
        ),
        height_m=3.0,
        absorption="pra.rough_concrete",
    )
    array = _array((1.0, 1.0, 1.0))
    scene = _scene(environment, array=array, source=_source((3.0, 1.0, 1.0)))

    frame = AnalyticAcoustics(max_order=1).simulate(scene, "rig", WINDOW)

    assert frame.diagnostics["analytic_solver"]["solver_id"] == (
        "pyroom_polygon_prism"
    )
    assert frame.detections[0].doa.estimated_bearing_deg == pytest.approx(
        0.0,
        abs=20.0,
    )
    room = module.Room.instances[-1]
    assert room.extruded_height == 3.0
    assert len(room.kwargs["materials"]) == 5
    assert set(room.extrude_materials) == {"floor", "ceiling"}

    outside = _scene(
        environment,
        array=array,
        source=_source((2.0, 3.5, 1.0)),
    )
    with pytest.raises(ValueError, match="outside polygon-prism"):
        AnalyticAcoustics().simulate(outside, "rig", WINDOW)


def test_malformed_prism_fails_before_pyroom_room_construction(monkeypatch) -> None:
    module = _install_closed_room_fake(monkeypatch)
    environment = polygon_prism_environment(
        environment_id="invalid_prism",
        floor_vertices_local_m=(
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ),
        height_m=2.5,
    )
    malformed_wall = replace(
        environment.surfaces[2],
        vertices_local_m=(
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.0, 2.5),
            (1.0, 0.0, 2.5),
        ),
    )
    environment = replace(
        environment,
        surfaces=(*environment.surfaces[:2], malformed_wall, *environment.surfaces[3:]),
    )

    with pytest.raises(ValueError, match="does not map uniquely"):
        AnalyticAcoustics().simulate(
            _scene(
                environment,
                array=_array((1.0, 1.0, 1.0)),
                source=_source((3.0, 1.0, 1.0)),
            ),
            "rig",
            WINDOW,
        )

    assert module.Room.instances == []


class _FakePolygonRoom(FakeShoeBox):
    def __init__(self, corners, **kwargs):
        xs, ys = np.asarray(corners, dtype=float)
        super().__init__(
            (float(np.ptp(xs)), float(np.ptp(ys)), 1.0),
            **kwargs,
        )
        self.corners = np.asarray(corners, dtype=float)
        self.extruded_height = 0.0
        self.extrude_materials = None

    def extrude(self, height, *, materials):
        self.extruded_height = float(height)
        self.extrude_materials = materials

    def is_inside(self, position) -> bool:
        x, y, z = (float(value) for value in position)
        if z < 0.0 or z > self.extruded_height:
            return False
        vertices = tuple(zip(self.corners[0], self.corners[1], strict=True))
        inside = False
        previous = vertices[-1]
        for current in vertices:
            if (current[1] > y) != (previous[1] > y):
                crossing = (previous[0] - current[0]) * (y - current[1]) / (
                    previous[1] - current[1]
                ) + current[0]
                if x < crossing:
                    inside = not inside
            previous = current
        return inside


class _FakeRoomApi:
    instances: list[_FakePolygonRoom] = []

    @classmethod
    def from_corners(cls, corners, **kwargs):
        room = _FakePolygonRoom(corners, **kwargs)
        cls.instances.append(room)
        return room


def _install_closed_room_fake(monkeypatch):
    import types

    module = types.ModuleType("pyroomacoustics")
    module.__version__ = "fake-analytic"
    module.Material = FakeMaterial
    module.MicrophoneArray = FakeMicrophoneArray
    module.ShoeBox = FakeShoeBox
    module.Room = _FakeRoomApi
    FakeShoeBox.instances = []
    _FakeRoomApi.instances = []
    monkeypatch.setitem(sys.modules, "pyroomacoustics", module)
    return module
