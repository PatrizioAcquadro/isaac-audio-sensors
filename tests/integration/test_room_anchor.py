"""Environment-frame placement and fail-closed room-backend tests."""

from __future__ import annotations

import pytest

from isaac_audio_sensors.core.acoustics import (
    environment_to_world_point,
    shoebox_environment,
    shoebox_environment_from_bounds,
    world_to_environment_point,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.math_utils import quaternion_from_euler_deg
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from tests.helpers import FakeShoeBox, install_fake_pyroom

ENVIRONMENT_MIN_WORLD = (2.0, 1.0, 0.0)
ENVIRONMENT_MAX_WORLD = (8.0, 5.0, 3.0)
ARRAY_POSITION = (4.0, 3.0, 1.5)
SOURCE_POSITION = (6.0, 2.0, 1.0)


def _array(position=ARRAY_POSITION, orientation=(0.0, 0.0, 0.0, 1.0)):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
        position_world=position,
        orientation_world_quat=orientation,
    )


def _source(position=SOURCE_POSITION) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id="speaker",
        prim_path="/World/Sources/speaker",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


def _environment() -> AcousticEnvironmentSpec:
    return shoebox_environment_from_bounds(
        min_world=ENVIRONMENT_MIN_WORLD,
        max_world=ENVIRONMENT_MAX_WORLD,
        environment_id="bounded_environment",
        absorption=0.35,
    )


def _scene(
    environment: AcousticEnvironmentSpec | None,
    *,
    source: AudioSourceSpec | None = None,
    array=None,
) -> AudioSceneSnapshot:
    selected_array = _array() if array is None else array
    return AudioSceneSnapshot(
        stage_id="environment_backend_test",
        sources=((_source() if source is None else source),),
        arrays=(selected_array,),
        environment=environment,
    )


def _window() -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=0.0,
        end_time_s=0.2,
        frame_index=0,
    )


def test_world_aligned_environment_preserves_stage_distances(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    environment = _environment()
    array = _array()

    frame = AnalyticAcoustics(max_order=1).simulate(
        _scene(environment, array=array),
        array.array_id,
        _window(),
    )

    shoebox = FakeShoeBox.instances[-1]
    assert tuple(shoebox.dimensions) == (6.0, 4.0, 3.0)
    assert frame.observations == ()
    mic_local = shoebox.mic_array.R.T
    for mic_index, world in enumerate(microphone_world_positions(array).values()):
        for axis in range(3):
            local_position = mic_local[mic_index][axis]
            assert local_position == pytest.approx(
                world[axis] - ENVIRONMENT_MIN_WORLD[axis]
            )
            assert environment.dimensions_m[axis] - local_position == pytest.approx(
                ENVIRONMENT_MAX_WORLD[axis] - world[axis]
            )
    source_local = shoebox.sources[0][0]
    for axis in range(3):
        assert source_local[axis] == pytest.approx(
            SOURCE_POSITION[axis] - ENVIRONMENT_MIN_WORLD[axis]
        )
    assert frame.diagnostics["environment_config"]["position_world"] == (
        ENVIRONMENT_MIN_WORLD
    )


def test_rotated_and_inclined_shoebox_uses_environment_local_coordinates(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    orientation = quaternion_from_euler_deg(
        roll_deg=20.0,
        pitch_deg=-15.0,
        yaw_deg=55.0,
    )
    environment = shoebox_environment(
        environment_id="posed",
        dimensions_m=(7.0, 5.0, 3.0),
        position_world=(3.0, -2.0, 1.0),
        orientation_world_quat=orientation,
    )
    array_local = (2.0, 2.0, 1.2)
    source_local = (5.0, 2.0, 1.2)
    array = _array(
        position=environment_to_world_point(environment, array_local),
        orientation=orientation,
    )
    source = _source(environment_to_world_point(environment, source_local))

    frame = AnalyticAcoustics().simulate(
        _scene(environment, source=source, array=array),
        array.array_id,
        _window(),
    )

    assert frame.observations == ()
    shoebox = FakeShoeBox.instances[-1]
    assert shoebox.sources[0][0] == pytest.approx(source_local)
    expected_mics = {
        mic_id: world_to_environment_point(environment, position)
        for mic_id, position in microphone_world_positions(array).items()
    }
    for actual, expected in zip(
        shoebox.mic_array.R.T,
        expected_mics.values(),
        strict=True,
    ):
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    ("scene", "offending_id"),
    (
        (_scene(_environment(), source=_source((9.0, 2.0, 1.0))), "source:speaker"),
        (_scene(_environment(), array=_array(position=(9.0, 3.0, 1.5))), "mic:"),
    ),
)
def test_out_of_bounds_positions_always_error(
    monkeypatch,
    scene,
    offending_id,
) -> None:
    install_fake_pyroom(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        AnalyticAcoustics().simulate(scene, "rig", _window())

    message = str(excinfo.value)
    assert offending_id in message
    assert "outside shoebox environment" in message
    assert "bounded_environment" in message


def test_room_backend_requires_environment(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)

    with pytest.raises(ValueError, match="AudioSceneSnapshot.environment"):
        AnalyticAcoustics().simulate(_scene(None), "rig", _window())
