"""Tests for optional Isaac/Lab layers and CLI behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from isaac_audio_sensors.cli import main as cli_main
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.constants import SECTOR_ORDER
from isaac_audio_sensors.core.exceptions import (
    IsaacIntegrationUnavailable,
    IsaacLabUnavailable,
)
from isaac_audio_sensors.core.math_utils import quaternion_from_yaw_deg
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
)
from isaac_audio_sensors.isaac.array_registry import discover_microphone_arrays
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.extension import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.listener_registry import discover_listeners
from isaac_audio_sensors.isaac.source_registry import discover_sound_sources
from isaac_audio_sensors.isaac.stage_audio import (
    attach_array_object_binding_attrs,
    attach_microphone_array_attrs,
    attach_microphone_attrs,
    attach_sound_source_attrs,
    attach_source_object_binding_attrs,
    clear_array_object_binding_attrs,
    clear_source_object_binding_attrs,
    create_listener_prim,
    create_sound_prim,
    move_prim_to_path,
    require_isaac_usd,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot
from isaac_audio_sensors.lab import (
    AudioArraySensor,
    AudioArraySensorCfg,
    AudioArraySensorData,
    LabAudioStageBindingCfg,
    get_audio_array_sensor_classes,
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

    def GetPrimAtPath(self, path: str) -> _FakePrim | None:
        for prim in self._prims:
            if prim.path == path:
                return prim
        return None

    def RemovePrim(self, path: object) -> bool:
        path_string = str(path)
        before = len(self._prims)
        self._prims = [
            prim
            for prim in self._prims
            if prim.path != path_string and not prim.path.startswith(f"{path_string}/")
        ]
        return len(self._prims) != before


class _FakeTimeSampledValue:
    def __init__(self, samples: dict[object, object]) -> None:
        self.samples = samples

    def Get(self, time_code: object | None = None) -> object:
        if time_code in self.samples:
            return self.samples[time_code]
        if time_code is not None:
            try:
                numeric_time = float(time_code)
            except (TypeError, ValueError):
                numeric_time = None
            if numeric_time in self.samples:
                return self.samples[numeric_time]
            for sample_time, value in self.samples.items():
                if (
                    isinstance(sample_time, (int, float))
                    and numeric_time is not None
                    and abs(float(sample_time) - numeric_time) <= 1e-5
                ):
                    return value
        return self.samples.get("default")


def _set_fake_attr(stage: _FakeStage, path: str, name: str, value: object) -> None:
    for prim in stage._prims:
        if prim.path == path:
            prim.attributes[name] = value
            return
    raise AssertionError(f"missing fake prim {path}")


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


def test_isaac_lab_class_loader_is_import_safe_without_lab():
    classes = get_audio_array_sensor_classes(require_real=False)

    assert classes.sensor is AudioArraySensor
    assert classes.cfg is AudioArraySensorCfg
    assert isinstance(classes.real, bool)


def test_public_imports_do_not_require_optional_runtime_modules():
    code = textwrap.dedent("""
        import importlib
        import importlib.abc
        import json
        import sys

        blocked = (
            "pxr",
            "omni",
            "isaacsim",
            "isaaclab",
            "pyroomacoustics",
            "scipy",
            "soundfile",
            "google.protobuf",
            "rclpy",
            "torch",
        )

        class OptionalRuntimeBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                for module_name in blocked:
                    if (
                        fullname == module_name
                        or fullname.startswith(module_name + ".")
                    ):
                        raise ImportError(f"blocked optional module {fullname}")
                return None

        sys.meta_path.insert(0, OptionalRuntimeBlocker())

        imported = []
        for module_name in (
            "isaac_audio_sensors",
            "isaac_audio_sensors.core",
            "isaac_audio_sensors.isaac",
            "isaac_audio_sensors.lab",
        ):
            importlib.import_module(module_name)
            imported.append(module_name)

        from isaac_audio_sensors.core.backends.room_acoustics import (
            RoomAcousticsBackend,
        )

        print(json.dumps({
            "imported": imported,
            "room_acoustics_available": RoomAcousticsBackend.is_available(),
        }, sort_keys=True))
        """)
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    evidence = json.loads(completed.stdout)

    assert evidence == {
        "imported": [
            "isaac_audio_sensors",
            "isaac_audio_sensors.core",
            "isaac_audio_sensors.isaac",
            "isaac_audio_sensors.lab",
        ],
        "room_acoustics_available": False,
    }


def test_isaac_lab_class_loader_recovers_after_prelauncher_fallback_import():
    code = textwrap.dedent("""
        import dataclasses
        import json
        import sys
        import types

        from isaac_audio_sensors.lab import (
            AudioArraySensor as fallback_sensor,
            AudioArraySensorCfg as fallback_cfg,
            ensure_isaac_lab_sensor_classes,
        )

        class SensorBaseCfg:
            pass

        class SensorBase:
            def __init__(self, cfg):
                self.cfg = cfg
                self._device = getattr(cfg, "device", None) or "cpu"
                self._num_envs = 0
                self._is_initialized = False
                self._backend = "fake"
                self._sim_physics_dt = 0.0

            @property
            def device(self):
                return self._device

        def configclass(cls):
            return dataclasses.dataclass(kw_only=True)(cls)

        isaaclab = types.ModuleType("isaaclab")
        sensors = types.ModuleType("isaaclab.sensors")
        sensors.SensorBase = SensorBase
        sensors.SensorBaseCfg = SensorBaseCfg
        utils = types.ModuleType("isaaclab.utils")
        utils.configclass = configclass
        sys.modules["isaaclab"] = isaaclab
        sys.modules["isaaclab.sensors"] = sensors
        sys.modules["isaaclab.utils"] = utils

        try:
            fallback_cfg(prim_path="/World/envs/env_0/Robot/audio_array")
            fallback_error = None
        except Exception as exc:
            fallback_error = f"{type(exc).__name__}: {exc}"

        classes = ensure_isaac_lab_sensor_classes()
        cfg = classes.cfg(prim_path="/World/envs/env_0/Robot/audio_array")
        sensor = classes.sensor(cfg=cfg, num_envs=1)
        print(json.dumps({
            "fallback_error_has_recovery": (
                fallback_error is not None
                and "ensure_isaac_lab_sensor_classes" in fallback_error
            ),
            "fallback_sensor_real": issubclass(fallback_sensor, SensorBase),
            "fallback_cfg_real": issubclass(fallback_cfg, SensorBaseCfg),
            "resolved_sensor_real": issubclass(classes.sensor, SensorBase),
            "resolved_cfg_real": issubclass(classes.cfg, SensorBaseCfg),
            "classes_real": classes.real,
            "sensor_cfg_path": sensor.cfg.prim_path,
        }, sort_keys=True))
        """)
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}"

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    evidence = json.loads(completed.stdout)

    assert evidence == {
        "classes_real": True,
        "fallback_error_has_recovery": True,
        "fallback_cfg_real": False,
        "fallback_sensor_real": False,
        "resolved_cfg_real": True,
        "resolved_sensor_real": True,
        "sensor_cfg_path": "/World/envs/env_0/Robot/audio_array",
    }


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
    source_attrs = attach_sound_source_attrs(
        stage._prims[0],
        source_id="speaker_a",
        class_label="Speech",
        position_world=(2.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        audio_asset_path="generated://impulse",
        start_time_s=1.0,
        duration_s=0.5,
        gain_db=-3.0,
        directivity="omni",
    )
    array_prim = stage.DefinePrim("/World/Rig/AudioArray", "Xform")
    attrs = attach_microphone_array_attrs(
        array_prim,
        array_id="rig_front",
        sample_rate_hz=48_000,
        coordinate_convention="x_forward_y_right_z_up_clockwise_bearing",
        layout_name="quad_front",
        position_world=(0.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        microphone_relative_offsets_m=((0.08, 0.0, 0.0), (0.0, 0.08, 0.0)),
        microphone_ids=("front", "right"),
    )
    mic_prim = stage.DefinePrim("/World/Rig/AudioArray/front", "Microphone")
    mic_attrs = attach_microphone_attrs(
        mic_prim,
        mic_id="front",
        relative_position_m=(0.08, 0.0, 0.0),
        relative_orientation_quat=(0.0, 0.0, 0.0, 1.0),
        gain_db=-1.0,
        self_noise_db=24.0,
    )

    assert sound.attributes["filePath"] == "generated://impulse"
    assert sound.attributes["gain"] == -3.0
    assert source_attrs["ias:audio_asset_path"] == "generated://impulse"
    assert stage._prims[0].attributes["ias:duration_s"] == 0.5
    assert stage._prims[0].attributes["xformOp:translate"] == (2.0, 0.0, 0.0)
    assert listener.attributes["ias:array_id"] == "rig_front"
    assert attrs["ias:layout_name"] == "quad_front"
    assert attrs["ias:microphone_ids"] == ("front", "right")
    assert array_prim.attributes["xformOp:translate"] == (0.0, 0.0, 0.0)
    assert mic_attrs["ias:relative_orientation_quat"] == (0.0, 0.0, 0.0, 1.0)
    assert mic_attrs["ias:self_noise_db"] == 24.0
    assert mic_prim.attributes["xformOp:translate"] == (0.08, 0.0, 0.0)


def test_isaac_stage_audio_object_binding_helpers_work_with_duck_typed_stage():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Sources/SpeakerA",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker_a",
                    "ias:class_label": "Speech",
                    "xformOp:translate": (2.0, 0.0, 0.0),
                },
            ),
        )
    )

    moved = move_prim_to_path(
        stage,
        source_path="/World/Sources/SpeakerA",
        dest_path="/World/Oven/SpeakerA",
        prim_type="Sound",
    )
    binding_attrs = attach_source_object_binding_attrs(
        moved,
        object_prim_path="/World/Oven",
        local_offset_m=(0.0, 0.5, 0.25),
    )

    assert stage.GetPrimAtPath("/World/Sources/SpeakerA") is None
    assert stage.GetPrimAtPath("/World/Oven/SpeakerA") is moved
    assert moved.attributes["ias:source_id"] == "speaker_a"
    assert moved.attributes["ias:attached_object_prim_path"] == "/World/Oven"
    assert binding_attrs["ias:source_local_offset_m"] == (0.0, 0.5, 0.25)
    assert moved.attributes["xformOp:translate"] == (0.0, 0.5, 0.25)

    clear_source_object_binding_attrs(moved)

    assert "ias:attached_object_prim_path" not in moved.attributes
    assert "ias:source_local_offset_m" not in moved.attributes


def test_isaac_stage_audio_array_binding_helpers_work_with_duck_typed_stage():
    yaw_quat = quaternion_from_yaw_deg(90.0)
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Rig/AudioArray",
                "Xform",
                {
                    "ias:array_id": "rig_front",
                    "ias:position_world": (1.0, 0.0, 0.0),
                    "xformOp:translate": (1.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/front",
                "Microphone",
                {
                    "ias:microphone_id": "front",
                    "ias:gain_db": -1.5,
                    "xformOp:translate": (0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Rig/AudioArray/left",
                "Microphone",
                {
                    "ias:microphone_id": "left",
                    "ias:gain_db": 0.5,
                    "xformOp:translate": (0.0, -0.08, 0.0),
                },
            ),
        )
    )

    moved = move_prim_to_path(
        stage,
        source_path="/World/Rig/AudioArray",
        dest_path="/World/Robot/head_link/AudioArray",
        prim_type="Xform",
        include_children=True,
    )
    binding_attrs = attach_array_object_binding_attrs(
        moved,
        object_prim_path="/World/Robot/head_link",
        local_offset_m=(0.0, 0.0, 0.12),
        local_orientation_quat=yaw_quat,
    )

    assert stage.GetPrimAtPath("/World/Rig/AudioArray") is None
    assert stage.GetPrimAtPath("/World/Rig/AudioArray/front") is None
    assert stage.GetPrimAtPath("/World/Robot/head_link/AudioArray") is moved
    moved_front = stage.GetPrimAtPath("/World/Robot/head_link/AudioArray/front")
    moved_left = stage.GetPrimAtPath("/World/Robot/head_link/AudioArray/left")
    assert moved_front is not None
    assert moved_left is not None
    assert moved_front.attributes["ias:gain_db"] == -1.5
    assert moved_front.attributes["xformOp:translate"] == (0.08, 0.0, 0.0)
    assert moved_left.attributes["ias:gain_db"] == 0.5
    assert moved.attributes["ias:array_id"] == "rig_front"
    assert moved.attributes["ias:attached_object_prim_path"] == (
        "/World/Robot/head_link"
    )
    assert binding_attrs["ias:array_local_offset_m"] == (0.0, 0.0, 0.12)
    assert moved.attributes["ias:array_local_orientation_quat"] == yaw_quat
    assert moved.attributes["xformOp:translate"] == (0.0, 0.0, 0.12)
    assert moved.attributes["xformOp:orient"] == yaw_quat

    clear_array_object_binding_attrs(moved)

    assert "ias:attached_object_prim_path" not in moved.attributes
    assert "ias:array_local_offset_m" not in moved.attributes
    assert "ias:array_local_orientation_quat" not in moved.attributes


def test_isaac_stage_audio_move_prim_default_still_leaves_children_behind():
    stage = _FakeStage(
        (
            _FakePrim("/World/Rig/AudioArray", "Xform", {"ias:array_id": "rig"}),
            _FakePrim(
                "/World/Rig/AudioArray/front",
                "Microphone",
                {"ias:microphone_id": "front"},
            ),
        )
    )

    moved = move_prim_to_path(
        stage,
        source_path="/World/Rig/AudioArray",
        dest_path="/World/Elsewhere/AudioArray",
        prim_type="Xform",
    )

    assert moved.path == "/World/Elsewhere/AudioArray"
    assert stage.GetPrimAtPath("/World/Elsewhere/AudioArray/front") is None


def test_isaac_stage_audio_move_prim_uses_sdf_path_for_strict_isaac_stage(
    monkeypatch,
):
    pxr = ModuleType("pxr")
    sdf = ModuleType("pxr.Sdf")

    class SdfPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return self.value

    sdf.Path = SdfPath
    pxr.Sdf = sdf
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    monkeypatch.setitem(sys.modules, "pxr.Sdf", sdf)

    class StrictStage(_FakeStage):
        def GetPrimAtPath(self, path: object) -> _FakePrim | None:
            if isinstance(path, str):
                raise TypeError("expected Sdf.Path")
            return super().GetPrimAtPath(str(path))

    stage = StrictStage(
        (
            _FakePrim(
                "/World/Sources/SpeakerA",
                "Sound",
                {"ias:source_id": "speaker_a"},
            ),
        )
    )

    moved = move_prim_to_path(
        stage,
        source_path="/World/Sources/SpeakerA",
        dest_path="/World/Oven/SpeakerA",
        prim_type="Sound",
    )

    assert moved.path == "/World/Oven/SpeakerA"
    assert moved.attributes["ias:source_id"] == "speaker_a"
    assert not any(prim.path == "/World/Sources/SpeakerA" for prim in stage.Traverse())


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


def test_live_isaac_sensor_update_prefers_moved_source_xform_over_stale_metadata():
    source_prim = _FakePrim(
        "/World/Sources/SpeakerA",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:position_world": (5.0, 0.0, 0.0),
            "ias:duration_s": 1.0,
            "xformOp:translate": (5.0, 0.0, 0.0),
        },
    )
    stage = _FakeStage(
        (
            source_prim,
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
        )
    )
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig/AudioArray",
        backend="geometry_only",
        update_period_s=0.01,
        max_events=1,
    ).start()

    first = sensor.update(sim_time_s=0.0)
    source_prim.attributes["xformOp:translate"] = (0.0, 5.0, 0.0)
    second = sensor.update(sim_time_s=0.1)

    assert first.detections[0].source_pose.position_m == pytest.approx((5.0, 0.0, 0.0))
    assert second.detections[0].source_pose.position_m == pytest.approx((0.0, 5.0, 0.0))
    assert second.detections[0].doa.estimated_bearing_deg == pytest.approx(90.0)
    assert second.detections[0].doa.bearing_sector == "right"


def test_isaac_stage_snapshot_resolves_nested_robot_array_source_and_mics():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (1.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/RobotBase",
                "Xform",
                {"xformOp:translate": (2.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/RobotBase/AudioArray",
                "Xform",
                {
                    "xformOp:orient": quaternion_from_yaw_deg(90.0),
                    "ias:array_id": "robot_array",
                    "ias:sample_rate_hz": 48000,
                },
            ),
            _FakePrim(
                "/World/RobotBase/AudioArray/front",
                "Microphone",
                {
                    "xformOp:translate": (0.08, 0.0, 0.0),
                    "ias:microphone_id": "front",
                },
            ),
            _FakePrim(
                "/World/RobotBase/AudioArray/right",
                "Microphone",
                {
                    "xformOp:translate": (0.0, 0.08, 0.0),
                    "ias:microphone_id": "right",
                },
            ),
            _FakePrim(
                "/World/MovingObject",
                "Xform",
                {"xformOp:translate": (1.0, 4.0, 0.0)},
            ),
            _FakePrim(
                "/World/MovingObject/Speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "nested_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=100,
        array_prim_path="/World/RobotBase/AudioArray",
        robot_base_prim_path="/World/RobotBase",
        diagnostics_out=diagnostics,
    )
    array = snapshot.arrays[0]
    source = snapshot.sources[0]

    assert array.position_world == pytest.approx((3.0, 0.0, 0.0))
    assert array.forward_vec_world == pytest.approx((0.0, 1.0, 0.0))
    assert array.right_vec_world == pytest.approx((-1.0, 0.0, 0.0))
    assert source.position_world == pytest.approx((2.0, 4.0, 0.0))
    assert array.microphones[0].relative_position_m == pytest.approx((0.08, 0.0, 0.0))
    assert array.microphones[1].relative_position_m == pytest.approx((0.0, 0.08, 0.0))
    assert diagnostics["provenance"] == "isaac_sim_live_usd_stage_snapshot"
    assert diagnostics["robot_base_transform"]["position_world"] == pytest.approx(
        (3.0, 0.0, 0.0)
    )
    assert (
        diagnostics["array_transforms"]["/World/RobotBase/AudioArray"]["provenance"]
        == "xformOp:stack"
    )
    assert (
        diagnostics["source_transforms"]["/World/MovingObject/Speaker"]["provenance"]
        == "xformOp:stack"
    )


def test_isaac_stage_snapshot_time_code_updates_source_and_microphones():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/AudioArray",
                "Xform",
                {
                    "xformOp:translate": (0.0, 0.0, 0.0),
                    "ias:array_id": "time_array",
                },
            ),
            _FakePrim(
                "/World/AudioArray/front",
                "Microphone",
                {
                    "ias:microphone_id": "front",
                    "xformOp:translate": _FakeTimeSampledValue(
                        {"default": (0.08, 0.0, 0.0), 2.0: (0.2, 0.0, 0.0)}
                    ),
                },
            ),
            _FakePrim(
                "/World/AudioArray/right",
                "Microphone",
                {
                    "ias:microphone_id": "right",
                    "xformOp:translate": (0.0, 0.08, 0.0),
                },
            ),
            _FakePrim(
                "/World/Speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "time_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                    "xformOp:translate": _FakeTimeSampledValue(
                        {"default": (5.0, 0.0, 0.0), 2.0: (0.0, 5.0, 0.0)}
                    ),
                },
            ),
        )
    )

    default_snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        array_prim_path="/World/AudioArray",
    )
    time_sampled_snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=200,
        array_prim_path="/World/AudioArray",
        usd_time_code=2.0,
    )

    assert default_snapshot.sources[0].position_world == pytest.approx((5.0, 0.0, 0.0))
    assert time_sampled_snapshot.sources[0].position_world == pytest.approx(
        (0.0, 5.0, 0.0)
    )
    assert default_snapshot.arrays[0].microphones[0].relative_position_m == (
        pytest.approx((0.08, 0.0, 0.0))
    )
    assert time_sampled_snapshot.arrays[0].microphones[0].relative_position_m == (
        pytest.approx((0.2, 0.0, 0.0))
    )


def test_isaac_sensor_update_rereads_sim_time_parent_array_and_source_transforms():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Robot",
                "Xform",
                {
                    "xformOp:translate": _FakeTimeSampledValue(
                        {
                            "default": (0.0, 0.0, 0.0),
                            0.0: (0.0, 0.0, 0.0),
                            0.1: (1.0, 0.0, 0.0),
                            0.2: (1.0, 0.0, 0.0),
                        }
                    )
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray",
                "Xform",
                {
                    "ias:array_id": "live_array",
                    "xformOp:translate": (0.0, 0.0, 0.0),
                    "xformOp:orient": _FakeTimeSampledValue(
                        {
                            "default": quaternion_from_yaw_deg(0.0),
                            0.0: quaternion_from_yaw_deg(0.0),
                            0.1: quaternion_from_yaw_deg(0.0),
                            0.2: quaternion_from_yaw_deg(90.0),
                        }
                    ),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/front",
                "Microphone",
                {
                    "ias:microphone_id": "front",
                    "xformOp:translate": _FakeTimeSampledValue(
                        {
                            "default": (0.08, 0.0, 0.0),
                            0.0: (0.08, 0.0, 0.0),
                            0.1: (0.08, 0.0, 0.0),
                            0.2: (0.2, 0.0, 0.0),
                        }
                    ),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/right",
                "Microphone",
                {
                    "ias:microphone_id": "right",
                    "xformOp:translate": (0.0, 0.08, 0.0),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/rear",
                "Microphone",
                {
                    "ias:microphone_id": "rear",
                    "xformOp:translate": (-0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/left",
                "Microphone",
                {
                    "ias:microphone_id": "left",
                    "xformOp:translate": (0.0, -0.08, 0.0),
                },
            ),
            _FakePrim(
                "/World/Speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "moving_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                    "xformOp:translate": _FakeTimeSampledValue(
                        {
                            "default": (5.0, 0.0, 0.0),
                            0.0: (5.0, 0.0, 0.0),
                            0.1: (0.0, 5.0, 0.0),
                            0.2: (0.0, 5.0, 0.0),
                        }
                    ),
                },
            ),
        )
    )
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Robot/AudioArray",
        robot_base_prim_path="/World/Robot",
        backend="tdoa_synthetic",
        update_period_s=0.01,
        max_events=1,
    ).start()

    first = sensor.update(sim_time_s=0.0)
    moved_parent_source = sensor.update(sim_time_s=0.1)
    rotated_array_mic = sensor.update(sim_time_s=0.2)

    assert first.detections[0].doa.estimated_bearing_deg == pytest.approx(0.0)
    assert moved_parent_source.array_pose.position_m == pytest.approx((1.0, 0.0, 0.0))
    assert moved_parent_source.detections[0].source_pose.position_m == pytest.approx(
        (0.0, 5.0, 0.0)
    )
    assert moved_parent_source.detections[0].doa.estimated_bearing_deg != (
        first.detections[0].doa.estimated_bearing_deg
    )
    assert rotated_array_mic.detections[0].doa.estimated_bearing_deg != (
        moved_parent_source.detections[0].doa.estimated_bearing_deg
    )
    assert sensor._latest_sensor.microphones[0].relative_position_m == pytest.approx(
        (0.2, 0.0, 0.0)
    )
    assert rotated_array_mic.provenance == "isaac_live"
    stage_diagnostics = rotated_array_mic.diagnostics["stage_snapshot"]
    assert stage_diagnostics["time_code"] == pytest.approx(0.2)
    assert stage_diagnostics["robot_base_transform"]["position_world"] == pytest.approx(
        (1.0, 0.0, 0.0)
    )


def test_isaac_stage_snapshot_source_filter_fallback_attrs_and_errors():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/AudioArray",
                "Xform",
                {
                    "ias:array_id": "fallback_array",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                    "ias:layout_name": "quad_front",
                },
            ),
            _FakePrim(
                "/World/SpeakerA",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker_a",
                    "ias:class_label": "Speech",
                    "ias:position_world": (5.0, 0.0, 0.0),
                    "ias:duration_s": 1.0,
                },
            ),
            _FakePrim(
                "/World/SpeakerB",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker_b",
                    "ias:class_label": "Speech",
                    "ias:position_world": (0.0, 5.0, 0.0),
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        array_prim_path="/World/AudioArray",
        source_prim_path="/World/SpeakerB",
        diagnostics_out=diagnostics,
    )

    assert tuple(source.source_id for source in snapshot.sources) == ("speaker_b",)
    assert (
        diagnostics["array_transforms"]["/World/AudioArray"]["provenance"]
        == "ias:position_world"
    )
    with pytest.raises(ValueError, match="No audio source prim found"):
        build_stage_snapshot(
            stage,
            timestamp_ms=0,
            array_prim_path="/World/AudioArray",
            source_prim_path="/World/Missing",
        )
    with pytest.raises(ValueError, match="No microphone array prim found"):
        build_stage_snapshot(
            stage,
            timestamp_ms=0,
            array_prim_path="/World/MissingArray",
        )

    missing_transform_stage = _FakeStage(
        (
            _FakePrim(
                "/World/AudioArray",
                "Xform",
                {
                    "ias:array_id": "array",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:layout_name": "quad_front",
                },
            ),
            _FakePrim(
                "/World/Speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:source_id": "speaker",
                    "ias:class_label": "Speech",
                },
            ),
        )
    )
    with pytest.raises(ValueError, match="missing a computable transform"):
        build_stage_snapshot(
            missing_transform_stage,
            timestamp_ms=0,
            array_prim_path="/World/AudioArray",
        )


def test_isaac_semantic_discovery_arrays_sources_filters_and_robot_root():
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (0.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/Robot",
                "Xform",
                {"xformOp:translate": (1.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/Robot/AudioArray",
                "Xform",
                {
                    "ias:array_id": "front_array",
                    "ias:sample_rate_hz": 44_100,
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/front",
                "Microphone",
                {
                    "ias:microphone_id": "front",
                    "ias:relative_position_m": (0.08, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Robot/AudioArray/right",
                "Microphone",
                {
                    "ias:microphone_id": "right",
                    "ias:relative_position_m": (0.0, 0.08, 0.0),
                },
            ),
            _FakePrim(
                "/World/OutsideArray",
                "Xform",
                {
                    "ias:array_id": "outside",
                    "ias:layout_name": "quad_front",
                    "xformOp:translate": (10.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Sources/SpeakerB",
                "Xform",
                {
                    "inputs:file": "generated://speech",
                    "ias:source_id": "speaker_b",
                    "ias:position_world": (5.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Sources/SkipSpeaker",
                "Sound",
                {
                    "filePath": "generated://skip",
                    "ias:source_id": "skip",
                    "ias:position_world": (0.0, 5.0, 0.0),
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        discovery_cfg=IsaacAudioDiscoveryCfg(
            discovery_roots=("/World",),
            robot_base_prim_path="/World/Robot",
            restrict_arrays_to_robot=True,
            exclude_globs=("*Skip*",),
            required_arrays=True,
            required_sources=True,
            default_source_duration_s=0.5,
            source_class_label_overrides={"speaker_b": "Speech"},
        ),
        preferred_array="front_array",
        diagnostics_out=diagnostics,
    )

    assert tuple(array.array_id for array in snapshot.arrays) == ("front_array",)
    assert snapshot.arrays[0].position_world == pytest.approx((1.0, 0.0, 0.0))
    assert len(snapshot.arrays[0].microphones) == 2
    assert tuple(source.source_id for source in snapshot.sources) == ("speaker_b",)
    assert snapshot.sources[0].audio_asset_path == "generated://speech"
    assert snapshot.sources[0].class_label == "Speech"
    assert snapshot.sources[0].duration_s == pytest.approx(0.5)
    array_diag = diagnostics["array_candidates"]["/World/Robot/AudioArray"]
    assert "child_ias:microphone_id" in array_diag["reasons"]
    assert diagnostics["robot_base_transform"]["position_world"] == pytest.approx(
        (1.0, 0.0, 0.0)
    )
    assert "/World/OutsideArray" in diagnostics["array_rejections"]
    assert "/World/Sources/SkipSpeaker" in diagnostics["source_rejections"]


def test_isaac_semantic_discovery_layout_name_pattern_selection_and_errors():
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/AArray",
                "Xform",
                {
                    "ias:layout_name": "quad_front",
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/BMicArray",
                "Xform",
                {"xformOp:translate": (1.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/CExplicitAudioArray",
                "Xform",
                {
                    "ias:microphone_relative_offsets_m": (
                        (0.05, 0.0, 0.0),
                        (0.0, 0.05, 0.0),
                    ),
                    "ias:microphone_ids": ("front", "right"),
                    "xformOp:translate": (2.0, 0.0, 0.0),
                },
            ),
            _FakePrim(
                "/World/Speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:position_world": (5.0, 0.0, 0.0),
                    "ias:duration_s": 1.0,
                },
            ),
            _FakePrim(
                "/World/ZAlarmSound",
                "Sound",
                {
                    "filePath": "generated://alarm",
                    "ias:source_id": "alarm",
                    "ias:class_label": "Alarm",
                    "ias:position_world": (0.0, 5.0, 0.0),
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )

    result = discover_stage_audio(
        stage,
        cfg=IsaacAudioDiscoveryCfg(required_arrays=True, required_sources=True),
        preferred_array="/World/BMicArray",
    )

    assert tuple(array.spec.prim_path for array in result.arrays) == (
        "/World/AArray",
        "/World/BMicArray",
        "/World/CExplicitAudioArray",
    )
    assert result.selected_array is not None
    assert result.selected_array.spec.prim_path == "/World/BMicArray"
    assert len(result.selected_array.spec.microphones) == 4
    assert result.arrays[2].spec.microphones[0].mic_id == "front"
    assert result.arrays[2].spec.microphones[0].relative_position_m == pytest.approx(
        (0.05, 0.0, 0.0)
    )
    assert "name_pattern:*MicArray*" in result.selected_array.reasons
    assert result.sources[0].reasons[0] == "type:Sound"

    preferred_source_snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        discovery_cfg=IsaacAudioDiscoveryCfg(
            required_arrays=True,
            required_sources=True,
        ),
        preferred_source="alarm",
    )
    assert tuple(source.source_id for source in preferred_source_snapshot.sources) == (
        "alarm",
    )

    with pytest.raises(ValueError, match="No microphone array prims were discovered"):
        discover_stage_audio(
            stage,
            cfg=IsaacAudioDiscoveryCfg(
                discovery_roots=("/World/Missing",),
                required_arrays=True,
            ),
        )
    with pytest.raises(ValueError, match="No discovered microphone array matches"):
        discover_stage_audio(
            stage,
            cfg=IsaacAudioDiscoveryCfg(required_arrays=True),
            preferred_array="missing_array",
        )


def test_isaac_discovered_stage_sensor_rereads_moving_semantic_entities():
    source = _FakePrim(
        "/World/Sources/Speaker",
        "Xform",
        {
            "inputs:file": "generated://speech",
            "ias:source_id": "speaker",
            "ias:class_label": "Speech",
            "ias:position_world": (5.0, 0.0, 0.0),
            "ias:duration_s": 1.0,
        },
    )
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Robot",
                "Xform",
                {"ias:position_world": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/Robot/AudioArray",
                "Xform",
                {
                    "ias:array_id": "front_array",
                    "ias:layout_name": "quad_front",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            source,
        )
    )
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        binding_cfg=IsaacAudioSceneBindingCfg(
            discovery_roots=("/World",),
            robot_base_prim_path="/World/Robot",
            restrict_arrays_to_robot=True,
            preferred_array="front_array",
        ),
        backend="geometry_only",
        update_period_s=0.01,
        max_events=1,
    ).start()

    first = sensor.update(sim_time_s=0.0)
    source.attributes["ias:position_world"] = (0.0, 5.0, 0.0)
    second = sensor.update(sim_time_s=0.1)

    assert first.detections[0].doa.estimated_bearing_deg == pytest.approx(0.0)
    assert second.detections[0].doa.estimated_bearing_deg == pytest.approx(90.0)
    stage_diag = second.diagnostics["stage_snapshot"]
    assert stage_diag["selected_array"]["array_id"] == "front_array"
    assert stage_diag["discovery_provenance"] == "isaac_semantic_discovery"
    assert (
        "inputs:file"
        in stage_diag["source_candidates"]["/World/Sources/Speaker"]["reasons"]
    )


def test_isaac_stage_snapshot_uses_usdgeom_xform_cache_when_available(monkeypatch):
    class FakeQuat:
        def __init__(self, quat):
            self.quat = quat

        def GetImaginary(self):
            return self.quat[:3]

        def GetReal(self):
            return self.quat[3]

    class FakeMatrix:
        def __init__(self, prim):
            self.prim = prim

        def ExtractTranslation(self):
            return self.prim.attributes["usd_world_position"]

        def ExtractRotationQuat(self):
            return FakeQuat(self.prim.attributes["usd_world_orientation"])

    class FakeXformCache:
        def __init__(self, time_code):
            self.time_code = time_code

        def GetLocalToWorldTransform(self, prim):
            prim.attributes["received_time_code"] = self.time_code
            return FakeMatrix(prim)

    class FakeTimeCode:
        @staticmethod
        def Default():
            return "DEFAULT_TIME_CODE"

        def __init__(self, value):
            self.value = float(value)

    pxr_module = ModuleType("pxr")
    usd_geom_module = ModuleType("pxr.UsdGeom")
    usd_geom_module.XformCache = FakeXformCache
    usd_module = ModuleType("pxr.Usd")
    usd_module.TimeCode = FakeTimeCode
    pxr_module.UsdGeom = usd_geom_module
    pxr_module.Usd = usd_module
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", usd_geom_module)
    monkeypatch.setitem(sys.modules, "pxr.Usd", usd_module)

    stage = _FakeStage(
        (
            _FakePrim(
                "/World/AudioArray",
                "Xform",
                {
                    "xformOp:translate": (999.0, 999.0, 999.0),
                    "usd_world_position": (0.0, 0.0, 0.0),
                    "usd_world_orientation": (0.0, 0.0, 0.0, 1.0),
                    "ias:array_id": "usd_array",
                    "ias:layout_name": "quad_front",
                },
            ),
            _FakePrim(
                "/World/Speaker",
                "Sound",
                {
                    "xformOp:translate": (999.0, 999.0, 999.0),
                    "usd_world_position": (0.0, 5.0, 0.0),
                    "usd_world_orientation": (0.0, 0.0, 0.0, 1.0),
                    "filePath": "generated://impulse",
                    "ias:source_id": "usd_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        array_prim_path="/World/AudioArray",
        usd_time_code=3.0,
        diagnostics_out=diagnostics,
    )

    assert snapshot.sources[0].position_world == pytest.approx((0.0, 5.0, 0.0))
    assert (
        diagnostics["array_transforms"]["/World/AudioArray"]["provenance"]
        == "usd:XformCache"
    )
    assert isinstance(stage._prims[0].attributes["received_time_code"], FakeTimeCode)
    assert stage._prims[0].attributes["received_time_code"].value == pytest.approx(3.0)


def test_isaac_stage_snapshot_real_pxr_transform_stack_when_available():
    pytest.importorskip("pxr")
    from pxr import Gf, Sdf, Usd, UsdGeom  # type: ignore

    stage = Usd.Stage.CreateInMemory("isaac_audio_transform_test.usda")
    world = stage.DefinePrim("/World", "Xform")
    UsdGeom.Xformable(world).AddTranslateOp().Set(Gf.Vec3d(1.0, 0.0, 0.0))
    array = stage.DefinePrim("/World/AudioArray", "Xform")
    UsdGeom.Xformable(array).AddTranslateOp().Set(Gf.Vec3d(2.0, 0.0, 0.0))
    array.CreateAttribute("ias:array_id", Sdf.ValueTypeNames.String, custom=True).Set(
        "pxr_array"
    )
    array.CreateAttribute(
        "ias:layout_name",
        Sdf.ValueTypeNames.String,
        custom=True,
    ).Set("quad_front")
    source = stage.DefinePrim("/World/Speaker", "Xform")
    UsdGeom.Xformable(source).AddTranslateOp().Set(Gf.Vec3d(0.0, 5.0, 0.0))
    source.CreateAttribute("filePath", Sdf.ValueTypeNames.String, custom=True).Set(
        "generated://impulse"
    )
    source.CreateAttribute("ias:source_id", Sdf.ValueTypeNames.String, custom=True).Set(
        "pxr_speaker"
    )
    source.CreateAttribute(
        "ias:class_label",
        Sdf.ValueTypeNames.String,
        custom=True,
    ).Set("Speech")
    duration_attr = source.CreateAttribute(
        "ias:duration_s",
        Sdf.ValueTypeNames.Double,
        custom=True,
    )
    duration_attr.Set(1.0)

    diagnostics: dict[str, object] = {}
    snapshot = build_stage_snapshot(
        stage,
        timestamp_ms=0,
        array_prim_path="/World/AudioArray",
        diagnostics_out=diagnostics,
    )
    discovered = build_stage_snapshot(
        stage,
        timestamp_ms=1,
        discovery_cfg=IsaacAudioDiscoveryCfg(
            required_arrays=True,
            required_sources=True,
        ),
        preferred_array="pxr_array",
    )

    assert snapshot.arrays[0].position_world == pytest.approx((3.0, 0.0, 0.0))
    assert snapshot.sources[0].position_world == pytest.approx((1.0, 5.0, 0.0))
    assert discovered.arrays[0].array_id == "pxr_array"
    assert discovered.sources[0].source_id == "pxr_speaker"
    assert diagnostics["array_transforms"]["/World/AudioArray"][
        "provenance"
    ].startswith("usd:")


def test_isaac_lab_update_period_reuses_buffer_until_elapsed():
    torch = pytest.importorskip("torch")
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
    assert tuple(first.event_presence.shape) == (1, 8)
    assert first.event_presence.dtype is torch.bool
    assert bool(first.event_presence[0, 0])
    assert first.bearing_deg[0, 0].item() == pytest.approx(0.0)
    assert torch.isnan(first.bearing_deg[0, 1])


def test_isaac_lab_bound_scene_snapshot_updates_without_repassing_scene():
    torch = pytest.importorskip("torch")
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

    assert tuple(data.event_presence.shape) == (1, 8)
    assert bool(data.event_presence[0, 0])
    assert data.bearing_deg[0, 0].item() == pytest.approx(90.0)
    assert torch.equal(
        data.sector_onehot[0, 0],
        torch.nn.functional.one_hot(
            torch.tensor(SECTOR_ORDER.index("right")),
            num_classes=len(SECTOR_ORDER),
        ).to(dtype=data.sector_onehot.dtype),
    )


def test_isaac_lab_vectorized_multi_env_padding_sector_rms_and_metadata():
    torch = pytest.importorskip("torch")
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scenes = (
        AudioSceneSnapshot(
            stage_id="env_0",
            timestamp_ms=0,
            sources=(_source("speaker_front", (5.0, 0.0, 0.0)),),
            arrays=(array,),
        ),
        AudioSceneSnapshot(
            stage_id="env_1",
            timestamp_ms=0,
            sources=(_source("speaker_right", (0.0, 5.0, 0.0)),),
            arrays=(array,),
        ),
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=2,
            device="cpu",
        )
    ).bind_envs(scene_snapshots=scenes, sensors=array)

    sensor.update(dt=0.05, force_recompute=True)
    data = sensor.data

    assert tuple(data.event_presence.shape) == (2, 2)
    assert tuple(data.bearing_deg.shape) == (2, 2)
    assert tuple(data.sector_onehot.shape) == (2, 2, len(SECTOR_ORDER))
    assert tuple(data.per_mic_rms.shape) == (2, 2, 4)
    assert bool(data.event_presence[0, 0])
    assert bool(data.event_presence[1, 0])
    assert not bool(data.event_presence[0, 1])
    assert data.bearing_deg[0, 0].item() == pytest.approx(0.0)
    assert data.bearing_deg[1, 0].item() == pytest.approx(90.0)
    assert torch.isnan(data.bearing_deg[0, 1])
    assert data.confidence[0, 1].item() == 0.0
    assert data.per_mic_rms[0, 1].sum().item() == 0.0
    assert data.sector_onehot[0, 0, SECTOR_ORDER.index("straight")].item() == 1.0
    assert data.sector_onehot[1, 0, SECTOR_ORDER.index("right")].item() == 1.0
    assert data.source_ids == (("speaker_front", None), ("speaker_right", None))
    assert data.class_labels == (("Speech", None), ("Speech", None))
    assert data.latest_frames[0].array_id == "rig"
    assert data.event_presence.device.type == "cpu"


def test_isaac_lab_selected_env_update_and_reset():
    pytest.importorskip("torch")
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scenes = (
        AudioSceneSnapshot(
            stage_id="env_0",
            timestamp_ms=0,
            sources=(_source("speaker_front", (5.0, 0.0, 0.0)),),
            arrays=(array,),
        ),
        AudioSceneSnapshot(
            stage_id="env_1",
            timestamp_ms=0,
            sources=(_source("speaker_right", (0.0, 5.0, 0.0)),),
            arrays=(array,),
        ),
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
        )
    ).bind_envs(scene_snapshots=scenes, sensors=array)
    sensor.update(dt=0.05, force_recompute=True)
    original = sensor.data.bearing_deg.clone()

    moved_env_1 = AudioSceneSnapshot(
        stage_id="env_1_clone",
        timestamp_ms=50,
        sources=(_source("speaker_left", (0.0, -5.0, 0.0)),),
        arrays=(array,),
    )
    sensor.bind_env(env_id=1, scene_snapshot=moved_env_1, sensor=array)
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])

    assert sensor.data.bearing_deg[0, 0].item() == original[0, 0].item()
    assert sensor.data.bearing_deg[1, 0].item() == pytest.approx(270.0)

    sensor.reset(env_ids=[1])
    assert bool(sensor._data.event_presence[0, 0])
    assert not bool(sensor._data.event_presence[1, 0])
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    assert bool(sensor.data.event_presence[1, 0])


def test_isaac_lab_stage_binding_reads_cloned_envs_and_moving_transforms():
    pytest.importorskip("torch")
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {
                    "ias:array_id": "rig_0",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            _FakePrim(
                "/World/envs/env_0/Sources/speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:position_world": (5.0, 0.0, 0.0),
                    "ias:source_id": "speaker_0",
                    "ias:class_label": "Speech",
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 1.0,
                },
            ),
            _FakePrim(
                "/World/envs/env_1/Robot/audio_array",
                "Xform",
                {
                    "ias:array_id": "rig_1",
                    "ias:position_world": (0.0, 0.0, 0.0),
                    "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
                },
            ),
            _FakePrim(
                "/World/envs/env_1/Sources/speaker",
                "Sound",
                {
                    "filePath": "generated://impulse",
                    "ias:position_world": (0.0, 5.0, 0.0),
                    "ias:source_id": "speaker_1",
                    "ias:class_label": "Speech",
                    "ias:start_time_s": 0.0,
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=2,
            env_namespace_pattern="/World/envs/env_{env_id}",
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
            microphone_layout="quad_front",
        ),
    )

    sensor.update(dt=0.05, force_recompute=True)
    first = sensor.data.bearing_deg.clone()

    stage._prims[3].attributes["ias:position_world"] = (0.0, -5.0, 0.0)
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    data = sensor.data

    assert tuple(data.event_presence.shape) == (2, 1)
    assert data.bearing_deg[0, 0].item() == first[0, 0].item()
    assert data.bearing_deg[1, 0].item() == pytest.approx(270.0)
    assert data.source_ids == (("speaker_0",), ("speaker_1",))


def test_isaac_lab_stage_binding_resolves_nested_transform_stack_and_orientation():
    pytest.importorskip("torch")
    stage = _FakeStage(
        (
            _FakePrim("/World", "Xform", {"xformOp:translate": (1.0, 0.0, 0.0)}),
            _FakePrim(
                "/World/envs/env_0",
                "Xform",
                {"xformOp:translate": (10.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Robot",
                "Xform",
                {"xformOp:translate": (0.0, 2.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {
                    "xformOp:orient": quaternion_from_yaw_deg(90.0),
                    "ias:array_id": "rig_nested",
                    "ias:layout_name": "quad_front",
                },
            ),
            _FakePrim(
                "/World/envs/env_0/Robot/link",
                "Xform",
                {"xformOp:translate": (0.0, 1.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Robot/link/Sources/speaker",
                "Sound",
                {
                    "xformOp:translate": (0.0, 4.0, 0.0),
                    "filePath": "generated://impulse",
                    "ias:source_id": "nested_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            array_prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            source_prim_paths=("Robot/link/Sources/speaker",),
            microphone_layout=None,
        ),
    )

    sensor.update(dt=0.05, force_recompute=True)
    frame = sensor.data.latest_frames[0]
    detection = frame.detections[0]

    assert frame.array_pose.position_m == pytest.approx((11.0, 2.0, 0.0))
    assert detection.source_pose.position_m == pytest.approx((11.0, 7.0, 0.0))
    assert detection.doa.estimated_bearing_deg == pytest.approx(0.0)
    stage_diag = frame.diagnostics["stage_binding"]
    assert stage_diag["array_transform"]["provenance"] == "xformOp:stack"
    assert (
        stage_diag["source_transforms"]["/World/envs/env_0/Robot/link/Sources/speaker"][
            "provenance"
        ]
        == "xformOp:stack"
    )


def test_isaac_lab_stage_binding_maps_sensor_time_to_time_code():
    pytest.importorskip("torch")
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Sources/speaker",
                "Sound",
                {
                    "xformOp:translate": _FakeTimeSampledValue(
                        {
                            "default": (5.0, 0.0, 0.0),
                            2.0: (0.0, 5.0, 0.0),
                        }
                    ),
                    "ias:source_id": "time_sampled_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.0,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
            usd_time_code_scale=10.0,
        ),
    )

    data = sensor.update(sim_time_s=0.2, timestamp_ms=200)
    frame = data.latest_frames[0]

    assert data.bearing_deg[0, 0].item() == pytest.approx(90.0)
    assert frame.diagnostics["stage_binding"]["time_code"] == pytest.approx(2.0)
    assert frame.detections[0].source_pose.position_m == pytest.approx((0.0, 5.0, 0.0))

    explicit_time_sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.0,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
            time_code=2.0,
        ),
    )
    explicit_data = explicit_time_sensor.update(sim_time_s=0.0, timestamp_ms=0)

    assert explicit_data.bearing_deg[0, 0].item() == pytest.approx(90.0)


def test_isaac_lab_scene_binding_discovers_sources_child_mics_and_env_paths():
    pytest.importorskip("torch")
    prims: list[_FakePrim] = []
    for env_id, source_position in ((0, (5.0, 0.0, 0.0)), (1, (0.0, 5.0, 0.0))):
        env_ns = f"/World/envs/env_{env_id}"
        prims.extend(
            [
                _FakePrim(
                    f"{env_ns}/Robot/audio_array",
                    "Xform",
                    {
                        "xformOp:translate": (0.0, 0.0, 0.0),
                        "ias:array_id": f"child_rig_{env_id}",
                        "ias:sample_rate_hz": 44_100,
                    },
                ),
                _FakePrim(
                    f"{env_ns}/Robot/audio_array/front",
                    "Microphone",
                    {
                        "ias:microphone_id": "front",
                        "ias:relative_position_m": (0.08, 0.0, 0.0),
                    },
                ),
                _FakePrim(
                    f"{env_ns}/Robot/audio_array/right",
                    "Microphone",
                    {
                        "ias:microphone_id": "right",
                        "ias:relative_position_m": (0.0, 0.08, 0.0),
                    },
                ),
                _FakePrim(
                    f"{env_ns}/Sources/speaker",
                    "Sound",
                    {
                        "xformOp:translate": source_position,
                        "ias:source_id": f"discovered_speaker_{env_id}",
                        "ias:class_label": "Speech",
                        "ias:duration_s": 1.0,
                    },
                ),
            ]
        )
    scene = SimpleNamespace(stage=_FakeStage(tuple(prims)), num_envs=2)
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_scene(
        scene=scene,
        binding_cfg=LabAudioStageBindingCfg(
            array_prim_path="{ENV_NS}/Robot/audio_array",
            discover_sources=True,
            source_discovery_root_path="Sources",
            microphone_layout=None,
        ),
    )

    sensor.update(dt=0.05, force_recompute=True)
    data = sensor.data

    assert tuple(data.per_mic_rms.shape) == (2, 1, 2)
    assert data.microphone_ids == ("front", "right")
    assert data.source_ids == (("discovered_speaker_0",), ("discovered_speaker_1",))
    assert data.latest_frames[0].sample_rate_hz == 44_100
    assert data.bearing_deg[0, 0].item() == pytest.approx(0.0)
    assert data.bearing_deg[1, 0].item() == pytest.approx(90.0)


def test_isaac_lab_stage_binding_discovers_arrays_and_sources_per_clone():
    pytest.importorskip("torch")
    prims: list[_FakePrim] = []
    for env_id, source_position in ((0, (5.0, 0.0, 0.0)), (1, (0.0, 5.0, 0.0))):
        env_ns = f"/World/envs/env_{env_id}"
        prims.extend(
            [
                _FakePrim(
                    f"{env_ns}/Robot",
                    "Xform",
                    {"xformOp:translate": (float(env_id), 0.0, 0.0)},
                ),
                _FakePrim(
                    f"{env_ns}/Robot/HeadMicArray",
                    "Xform",
                    {
                        "ias:array_id": f"head_array_{env_id}",
                        "ias:layout_name": "quad_front",
                        "xformOp:translate": (0.0, 0.0, 0.0),
                    },
                ),
                _FakePrim(
                    f"{env_ns}/Sources/Speaker",
                    "Xform",
                    {
                        "inputs:file": "generated://speech",
                        "ias:source_id": f"speaker_{env_id}",
                        "ias:class_label": "Speech",
                        "ias:duration_s": 1.0,
                        "xformOp:translate": source_position,
                    },
                ),
            ]
        )
    stage = _FakeStage(tuple(prims))
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/HeadMicArray",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=2,
            discover_arrays=True,
            array_discovery_root_path="Robot",
            discover_sources=True,
            source_discovery_root_path="Sources",
            preferred_array="HeadMicArray",
            microphone_layout=None,
        ),
    )

    sensor.update(dt=0.05, force_recompute=True)
    original = sensor.data.bearing_deg.clone()
    _set_fake_attr(
        stage,
        "/World/envs/env_1/Sources/Speaker",
        "xformOp:translate",
        (5.0, 0.0, 0.0),
    )
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    data = sensor.data

    assert data.source_ids == (("speaker_0",), ("speaker_1",))
    assert data.latest_frames[0].array_id == "head_array_0"
    assert data.latest_frames[1].array_id == "head_array_1"
    assert data.bearing_deg[0, 0].item() == original[0, 0].item()
    assert data.bearing_deg[1, 0].item() == pytest.approx(0.0)
    diag = data.latest_frames[1].diagnostics["stage_binding"]
    assert diag["array_discovery"]["mode"] == "semantic_discovery"
    assert diag["array_discovery"]["selected"].endswith("/Robot/HeadMicArray")
    assert (
        "source_metadata_attr"
        in diag["source_discovery"]["/World/envs/env_1/Sources/Speaker"]
    )


def test_isaac_lab_stage_binding_moving_local_parent_array_selected_envs():
    pytest.importorskip("torch")
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Sources",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_0/Sources/speaker",
                "Sound",
                {
                    "xformOp:translate": (5.0, 0.0, 0.0),
                    "ias:source_id": "speaker_0",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
            _FakePrim(
                "/World/envs/env_1/Robot/audio_array",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_1/Sources",
                "Xform",
                {"xformOp:translate": (0.0, 0.0, 0.0)},
            ),
            _FakePrim(
                "/World/envs/env_1/Sources/speaker",
                "Sound",
                {
                    "xformOp:translate": (0.0, 5.0, 0.0),
                    "ias:source_id": "speaker_1",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=2,
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
            microphone_layout="quad_front",
        ),
    )
    sensor.update(dt=0.05, force_recompute=True)
    original = sensor.data.bearing_deg.clone()

    _set_fake_attr(
        stage,
        "/World/envs/env_1/Sources/speaker",
        "xformOp:translate",
        (5.0, 0.0, 0.0),
    )
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    after_source_move = sensor.data.bearing_deg.clone()
    assert after_source_move[0, 0].item() == original[0, 0].item()
    assert after_source_move[1, 0].item() == pytest.approx(0.0)

    _set_fake_attr(
        stage,
        "/World/envs/env_1/Sources",
        "xformOp:translate",
        (0.0, -5.0, 0.0),
    )
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    after_parent_move = sensor.data.bearing_deg.clone()
    assert after_parent_move[0, 0].item() == original[0, 0].item()
    assert after_parent_move[1, 0].item() == pytest.approx(315.0)

    _set_fake_attr(
        stage,
        "/World/envs/env_1/Robot/audio_array",
        "xformOp:orient",
        quaternion_from_yaw_deg(90.0),
    )
    sensor.update(dt=0.05, force_recompute=True, env_ids=[1])
    after_array_rotation = sensor.data.bearing_deg.clone()
    assert after_array_rotation[0, 0].item() == original[0, 0].item()
    assert after_array_rotation[1, 0].item() == pytest.approx(225.0)


def test_isaac_lab_stage_binding_uses_usdgeom_when_available(monkeypatch):
    pytest.importorskip("torch")

    class FakeQuat:
        def __init__(self, quat):
            self.quat = quat

        def GetImaginary(self):
            return self.quat[:3]

        def GetReal(self):
            return self.quat[3]

    class FakeMatrix:
        def __init__(self, prim):
            self.prim = prim

        def ExtractTranslation(self):
            return self.prim.attributes["usd_world_position"]

        def ExtractRotationQuat(self):
            return FakeQuat(self.prim.attributes["usd_world_orientation"])

    class FakeXformable:
        def __init__(self, prim):
            self.prim = prim

        def ComputeLocalToWorldTransform(self, time_code):
            self.prim.attributes["received_time_code"] = time_code
            return FakeMatrix(self.prim)

    class FakeTimeCode:
        @staticmethod
        def Default():
            return "DEFAULT_TIME_CODE"

    pxr_module = ModuleType("pxr")
    usd_geom_module = ModuleType("pxr.UsdGeom")
    usd_geom_module.Xformable = FakeXformable
    usd_module = ModuleType("pxr.Usd")
    usd_module.TimeCode = FakeTimeCode
    pxr_module.UsdGeom = usd_geom_module
    pxr_module.Usd = usd_module
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", usd_geom_module)
    monkeypatch.setitem(sys.modules, "pxr.Usd", usd_module)

    stage = _FakeStage(
        (
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {
                    "usd_world_position": (0.0, 0.0, 0.0),
                    "usd_world_orientation": (0.0, 0.0, 0.0, 1.0),
                    "ias:array_id": "usd_array",
                },
            ),
            _FakePrim(
                "/World/envs/env_0/Sources/speaker",
                "Sound",
                {
                    "usd_world_position": (0.0, 5.0, 0.0),
                    "usd_world_orientation": (0.0, 0.0, 0.0, 1.0),
                    "ias:source_id": "usd_speaker",
                    "ias:class_label": "Speech",
                    "ias:duration_s": 1.0,
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/speaker",),
        ),
    )

    sensor.update(dt=0.05, force_recompute=True)
    frame = sensor.data.latest_frames[0]

    assert frame.detections[0].doa.estimated_bearing_deg == pytest.approx(90.0)
    assert (
        frame.diagnostics["stage_binding"]["array_transform"]["provenance"]
        == "usd:ComputeLocalToWorldTransform"
    )
    assert stage._prims[0].attributes["received_time_code"] == "DEFAULT_TIME_CODE"


def test_isaac_lab_stage_binding_reports_missing_prims_and_metadata():
    pytest.importorskip("torch")
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/envs/env_0/Robot/audio_array",
                "Xform",
                {
                    "ias:array_id": "rig_0",
                    "ias:position_world": (0.0, 0.0, 0.0),
                },
            ),
        )
    )
    sensor = AudioArraySensor(
        cfg=AudioArraySensorCfg(
            prim_path="{ENV_REGEX_NS}/Robot/audio_array",
            update_period=0.05,
            backend="geometry_only",
            max_events=1,
            device="cpu",
        )
    ).bind_lab_stage(
        stage=stage,
        binding_cfg=LabAudioStageBindingCfg(
            num_envs=1,
            env_namespace_pattern="/World/envs/env_{env_id}",
            array_prim_path="Robot/audio_array",
            source_prim_paths=("Sources/missing",),
            microphone_layout="quad_front",
        ),
    )

    with pytest.raises(ValueError, match="No audio source prim found"):
        sensor.update(dt=0.05, force_recompute=True)


def test_isaac_lab_frame_to_tensor_truncates_and_sets_ambiguity_mask():
    torch = pytest.importorskip("torch")
    frame = AudioSensorFrame(
        frame_id="manual",
        timestamp_ms=0,
        backend_id="manual",
        array_id="rig",
        max_events=3,
        detections=(
            AudioDetection(
                detection_id="d0",
                source_id="s0",
                class_label="Speech",
                detection_mode="manual_annotation",
                timestamp_ms=0,
                ground_truth_bearing_deg=0.0,
                source_distance_m=1.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=0.0,
                    bearing_confidence=0.9,
                ),
                per_mic_rms={"front": 0.1, "right": 0.2},
            ),
            AudioDetection(
                detection_id="d1",
                source_id="s1",
                class_label="Alarm",
                detection_mode="manual_annotation",
                timestamp_ms=0,
                ground_truth_bearing_deg=45.0,
                source_distance_m=1.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=45.0,
                    bearing_confidence=0.4,
                    ambiguity_class="front_back",
                ),
                per_mic_rms={"front": 0.3, "right": 0.4},
            ),
            AudioDetection(
                detection_id="d2",
                source_id="s2",
                class_label="Ignored",
                detection_mode="manual_annotation",
                timestamp_ms=0,
                ground_truth_bearing_deg=90.0,
                source_distance_m=1.0,
                doa=DoaEstimate(
                    estimated_bearing_deg=90.0,
                    bearing_confidence=1.0,
                ),
                per_mic_rms={"front": 1.0, "right": 1.0},
            ),
        ),
    )

    data = AudioArraySensorData.from_frame(
        frame,
        max_events=2,
        microphone_ids=("front", "right"),
        device="cpu",
    )

    assert data.event_presence.tolist() == [[True, True]]
    assert data.bearing_deg.tolist() == [[0.0, 45.0]]
    assert data.confidence.tolist() == [[pytest.approx(0.9), pytest.approx(0.4)]]
    assert data.ambiguity_mask.tolist() == [[False, True]]
    assert torch.equal(
        data.per_mic_rms[0],
        torch.tensor([[0.1, 0.2], [0.3, 0.4]], dtype=torch.float32),
    )
    assert data.source_ids == (("s0", "s1"),)
    assert data.class_labels == (("Speech", "Alarm"),)


def test_cli_validate_and_simulate_smoke(capsys):
    assert cli_main(["validate-config", "configs/isaac_audio_sensors_demo.toml"]) == 0
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
