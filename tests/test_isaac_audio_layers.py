"""Tests for optional Isaac/Lab layers and CLI behavior."""

from __future__ import annotations

import json

import pytest

from isaac_audio_sensors.cli import main as cli_main
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.exceptions import (
    IsaacIntegrationUnavailable,
    IsaacLabUnavailable,
)
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from isaac_audio_sensors.isaac.array_registry import discover_microphone_arrays
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.listener_registry import discover_listeners
from isaac_audio_sensors.isaac.source_registry import discover_sound_sources
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_array_attrs,
    create_listener_prim,
    create_sound_prim,
    require_isaac_usd,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    AudioArraySensorData,
)
from isaac_audio_sensors.lab.audio_array_sensor import require_isaac_lab


def _source(source_id: str, position: tuple[float, float, float]) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
    )


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object],
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
        self._prims = list(prims)

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)

    def DefinePrim(self, path: str, type_name: str) -> _FakePrim:
        prim = _FakePrim(path, type_name, {})
        self._prims.append(prim)
        return prim


def test_isaac_sim_unavailable_path_is_lazy_and_clear():
    try:
        require_isaac_usd()
    except IsaacIntegrationUnavailable as exc:
        assert "Isaac" in str(exc)
        return
    pytest.skip("Isaac/pxr modules are installed; unavailable path is not active.")


def test_isaac_lab_unavailable_path_is_clear():
    try:
        require_isaac_lab()
    except IsaacLabUnavailable as exc:
        assert "Isaac Lab" in str(exc)
        return
    pytest.skip("Isaac Lab is installed; unavailable path is not active.")


def test_isaac_lab_cfg_and_empty_data_shape():
    cfg = AudioArraySensorCfg(
        prim_path="{ENV_REGEX_NS}/Robot/audio_array",
        update_period=0.05,
        backend="tdoa_synthetic",
    )
    assert cfg.prim_path.startswith("{ENV_REGEX_NS}")
    assert AudioArraySensorData.empty().event_presence == ()


def test_isaac_lab_cfg_rejects_invalid_update_period():
    with pytest.raises(ValueError, match="update_period"):
        AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=-0.01,
        )


def test_isaac_source_listener_and_array_discovery_with_fake_stage():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Sources/SpeakerA/Sound",
                "Sound",
                {"filePath": "generated://impulse", "ias:source_id": "speaker_a"},
            ),
            _FakePrim(
                "/World/Rig/AudioArray",
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:sample_rate_hz": 48000,
                    "ias:layout_name": "quad_front",
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/front",
                "Xform",
                {"ias:microphone_id": "front"},
            ),
            _FakePrim(
                "/World/Rig/AudioArray/Listener",
                "Listener",
                {"ias:array_id": "rig_front"},
            ),
        )
    )

    assert discover_sound_sources(stage)[0].source_id == "speaker_a"
    assert discover_listeners(stage)[0].array_id == "rig_front"
    arrays = discover_microphone_arrays(stage)
    assert arrays[0].array_id == "rig_front"
    assert arrays[0].microphone_ids == ("front",)


def test_isaac_stage_authoring_helpers_work_with_duck_typed_stage():
    stage = _FakeStage(())

    sound = create_sound_prim(
        stage,
        prim_path="/World/Sources/SpeakerA/Sound",
        audio_asset_path="generated://impulse",
        spatial=True,
        start_time_s=1.0,
        gain_db=-3.0,
    )
    listener = create_listener_prim(
        stage,
        prim_path="/World/Rig/AudioArray/Listener",
        array_id="rig_front",
    )
    array_prim = stage.DefinePrim("/World/Rig/AudioArray", "Xform")
    attrs = attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
    )

    assert sound.attributes["filePath"] == "generated://impulse"
    assert sound.attributes["gain"] == -3.0
    assert listener.attributes["ias:array_id"] == "rig_front"
    assert attrs["ias:layout_name"] == "quad_front"


def test_isaac_stage_snapshot_and_sensor_capture_from_duck_typed_stage():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Sources/SpeakerA",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker_a",
                    "ias:class_label": "Speech",
                    "ias:position_world": (5.0, 0.0, 0.0),
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 1.0,
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray",
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:sample_rate_hz": 48000,
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/front",
                "Xform",
                {
                    "ias:microphone_id": "front",
                    "ias:relative_position_m": (0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/right",
                "Xform",
                {
                    "ias:microphone_id": "right",
                    "ias:relative_position_m": (0.0, 0.08, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/rear",
                "Xform",
                {
                    "ias:microphone_id": "rear",
                    "ias:relative_position_m": (-0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/left",
                "Xform",
                {
                    "ias:microphone_id": "left",
                    "ias:relative_position_m": (0.0, -0.08, 0.0),
                },
            ),
        )
    )

    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=1234,
        array_prim_path="/World/Rig/AudioArray",
    )
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig/AudioArray",
        backend="tdoa_synthetic",
        timestamp_ms=1234,
    )
    frame = sensor.capture(timestamp_ms=1234, start_time_s=0.0, end_time_s=1.0)

    assert snapshot.sources[0].source_id == "speaker_a"
    assert snapshot.arrays[0].array_id == "rig_front"
    assert len(snapshot.arrays[0].microphones) == 4
    assert frame.detections[0].doa.estimated_bearing_deg == pytest.approx(0.0, abs=2.0)


def test_live_isaac_sensor_updates_moving_stage_windows_writer_and_debug(tmp_path):
    source_prim = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:position_world": (5.0, 0.0, 0.0),
            "ias:start_time_s": 0.0,
            "ias:duration_s": 0.2,
        },
    )
    array_prim = _FakePrim(
        "/World/Rig/AudioArray",
        "Xform",
        {
            "ias:array_id": "rig_front",
            "ias:sample_rate_hz": 48000,
            "ias:position_world": (0.0, 0.0, 0.0),
            "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
        },
    )
    stage = _FakeStage(
        (
            source_prim,
            array_prim,
            _FakePrim(
                "/World/Rig/AudioArray/front",
                "Xform",
                {
                    "ias:microphone_id": "front",
                    "ias:relative_position_m": (0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/right",
                "Xform",
                {
                    "ias:microphone_id": "right",
                    "ias:relative_position_m": (0.0, 0.08, 0.0),
                },
            ),
        )
    )
    trace_path = tmp_path / "frames.jsonl"
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig/AudioArray",
        backend="geometry_only",
        update_period_s=0.1,
        max_events=1,
        debug_draw=True,
        writer_path=trace_path,
    ).start()

    first = sensor.update(sim_time_s=0.0)
    source_prim.attributes["ias:position_world"] = (0.0, 5.0, 0.0)
    array_prim.attributes["ias:position_world"] = (1.0, 0.0, 0.0)
    second = sensor.update(sim_time_s=0.1)
    third = sensor.update(sim_time_s=0.3)

    assert first.provenance == "isaac_live"
    assert first.frame_index == 0
    assert first.detections[0].source_pose.position_m == (5.0, 0.0, 0.0)
    assert second.frame_index == 1
    assert second.array_pose.position_m == (1.0, 0.0, 0.0)
    assert second.detections[0].source_pose.position_m == (0.0, 5.0, 0.0)
    assert second.detections[0].doa.estimated_bearing_deg != (
        first.detections[0].doa.estimated_bearing_deg
    )
    assert third.detections == ()
    assert sensor.get_latest_frame() is third
    assert sensor.latest_debug_primitives

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["provenance"] == "isaac_live"
    sensor.close()
    with pytest.raises(RuntimeError, match="closed"):
        sensor.update(force=True)


def test_isaac_lab_update_period_reuses_buffer_until_elapsed():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = AudioSceneSnapshot(
        stage_id="lab_test",
        timestamp_ms=0,
        sources=(_source("speaker", (5.0, 0.0, 0.0)),),
        arrays=(array,),
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
        )
    )
    first = sensor.update(
        scene_snapshot=scene,
        sensor=array,
        sim_time_s=0.0,
        timestamp_ms=0,
    )
    second = sensor.update(
        scene_snapshot=scene,
        sensor=array,
        sim_time_s=0.01,
        timestamp_ms=10,
    )

    assert first is second
    assert first.bearing_deg == (0.0,)


def test_isaac_lab_bound_scene_snapshot_updates_without_repassing_scene():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = AudioSceneSnapshot(
        stage_id="lab_bound_test",
        timestamp_ms=0,
        sources=(_source("speaker", (0.0, 5.0, 0.0)),),
        arrays=(array,),
    )
    sensor = AudioArraySensor.from_scene_snapshot(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
        ),
        scene_snapshot=scene,
        sensor=array,
    )

    data = sensor.update(sim_time_s=0.0, timestamp_ms=0)

    assert data.event_presence == (True,)
    assert data.bearing_deg == (90.0,)


def test_cli_validate_and_simulate_smoke(capsys):
    assert (
        cli_main(["validate-config", "configs/isaac_audio_sensors_demo.toml"]) == 0
    )
    validate_out = capsys.readouterr().out
    assert "demo_audio_lab_single_source" in validate_out

    assert (
        cli_main(
            [
                "simulate",
                "configs/isaac_audio_sensors_demo.toml",
                "--backend",
                "geometry_only",
                "--array-id",
                "rig_front",
            ]
        )
        == 0
    )
    simulate_out = capsys.readouterr().out
    assert '"backend_id": "geometry_only"' in simulate_out


def test_geometry_backend_still_accepts_bound_scene_data():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = AudioSceneSnapshot(
        stage_id="geometry_layer_test",
        timestamp_ms=0,
        sources=(_source("speaker", (5.0, 0.0, 0.0)),),
        arrays=(array,),
    )
    frame = GeometryBackend().simulate(
        scene,
        array,
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            timestamp_ms=0,
            sample_rate_hz=array.sample_rate_hz,
        ),
    )

    assert frame.detections[0].doa.estimated_bearing_deg == 0.0
