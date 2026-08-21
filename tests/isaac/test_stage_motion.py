"""Motion config, snapshot precedence, and stage enrichment tests."""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest

from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.config import validate_audio_config
from isaac_audio_sensors.core.effects import (
    EffectsConfig,
    MotionEffectsConfig,
    UnsupportedEffectError,
)
from isaac_audio_sensors.core.effects.validation import validate_effects_config
from isaac_audio_sensors.core.exceptions import ConfigValidationError
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.motion import PoseHistory
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_snapshot import (
    build_stage_snapshot,
    enrich_snapshot_motion,
)


def _raw_config() -> dict[str, object]:
    return {
        "scene": {"scene_id": "motion_config"},
        "audio": {
            "default_backend": "tdoa_synthetic",
            "sample_rate_hz": 48_000,
            "tdoa_ambiguity_policy": "none",
        },
        "sources": [
            {
                "source_id": "speaker",
                "prim_path": "/World/Speaker",
                "class_label": "Speech",
            }
        ],
        "arrays": {
            "rig": {
                "array_id": "rig",
                "prim_path": "/World/Rig",
                "microphones": [
                    {"mic_id": "left"},
                    {"mic_id": "right"},
                ],
            }
        },
    }


def _motion(enabled: bool = True, **kwargs) -> MotionEffectsConfig:
    return MotionEffectsConfig(derive_velocity_from_poses=enabled, **kwargs)


def _array(*, position=(0.0, 0.0, 0.0), velocity=None):
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
        position_world=position,
    )
    return replace(array, velocity_world_mps=velocity)


def _source(*, position=(1.0, 0.0, 0.0), velocity=None, source_id="speaker"):
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/{source_id}",
        class_label="Speech",
        audio_asset_path=None,
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=10.0,
        gain_db=0.0,
        velocity_world_mps=velocity,
    )


def _scene(source, array) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="motion_scene",
        timestamp_ms=0,
        sources=(source,),
        arrays=(array,),
    )


def test_motion_config_defaults_and_normalized_fields_are_frozen():
    config = validate_audio_config(_raw_config())
    assert config.effects.motion == MotionEffectsConfig(
        derive_velocity_from_poses=False,
        teleport_speed_threshold_mps=50.0,
        stale_time_s=0.5,
        smoothing_alpha=None,
    )
    assert config.effects.all_disabled

    raw = _raw_config()
    raw["audio"]["effects"] = {
        "motion": {
            "derive_velocity_from_poses": True,
            "teleport_speed_threshold_mps": 75,
            "stale_time_s": 1,
            "smoothing_alpha": 0.5,
        }
    }
    configured = validate_audio_config(raw).effects.motion
    assert configured == MotionEffectsConfig(
        derive_velocity_from_poses=True,
        teleport_speed_threshold_mps=75.0,
        stale_time_s=1.0,
        smoothing_alpha=0.5,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unknown", 1),
        ("enabled", True),
        ("derive_velocity_from_poses", 1),
        ("derive_velocity_from_poses", 0.0),
        ("teleport_speed_threshold_mps", True),
        ("teleport_speed_threshold_mps", "50.0"),
        ("teleport_speed_threshold_mps", float("nan")),
        ("stale_time_s", False),
        ("stale_time_s", float("inf")),
        ("smoothing_alpha", True),
        ("smoothing_alpha", float("-inf")),
    ],
)
def test_invalid_motion_config_matrix_fails_closed(field, value):
    raw = _raw_config()
    raw["audio"]["effects"] = {"motion": {field: value}}
    with pytest.raises(ConfigValidationError, match=f"audio.effects.motion.*{field}"):
        validate_audio_config(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("teleport_speed_threshold_mps", 0.0),
        ("stale_time_s", 60.0001),
        ("smoothing_alpha", 1.0001),
    ],
)
def test_active_motion_rejects_out_of_range_values(field, value):
    raw = _raw_config()
    raw["audio"]["effects"] = {
        "motion": {"derive_velocity_from_poses": True, field: value}
    }
    with pytest.raises(ConfigValidationError, match=f"audio.effects.motion.*{field}"):
        validate_audio_config(raw)


def test_direct_motion_record_validation_rejects_bool_as_number():
    effects = EffectsConfig(
        motion=MotionEffectsConfig(teleport_speed_threshold_mps=True)
    )
    with pytest.raises(ConfigValidationError, match="teleport_speed_threshold_mps"):
        validate_effects_config(
            effects,
            microphone_orders=(("left", "right"),),
            sample_rate_hz=48_000,
            backend_id="tdoa_synthetic",
            runtime_profile="waveform_fidelity",
        )


def test_config_source_selected_array_collision_fails_before_snapshot():
    raw = _raw_config()
    raw["sources"][0]["source_id"] = "rig"
    raw["audio"]["effects"] = {"motion": {"derive_velocity_from_poses": True}}
    with pytest.raises(ConfigValidationError, match="collisions.*rig"):
        validate_audio_config(raw)


def test_disabled_motion_enrichment_is_literal_identity_and_no_history_update():
    scene = _scene(_source(), _array())
    history = PoseHistory()
    enriched, diagnostics = enrich_snapshot_motion(
        scene,
        selected_array_id="rig",
        time_s=float("nan"),
        pose_history=history,
        motion_config=_motion(False),
    )
    assert enriched is scene
    assert diagnostics == {}
    assert history._entities == {}


def test_authored_precedence_preserves_bits_while_history_stays_current():
    source_velocity = (-0.0, 7.25, -3.5)
    array_velocity = (1.25, -0.0, 4.5)
    initial = _scene(
        _source(position=(1.0, 2.0, 3.0), velocity=source_velocity),
        _array(position=(-1.0, 1.0, 0.0), velocity=array_velocity),
    )
    history = PoseHistory(smoothing_alpha=0.5)
    first, first_diagnostics = enrich_snapshot_motion(
        initial,
        selected_array_id="rig",
        time_s=1.0,
        pose_history=history,
        motion_config=_motion(smoothing_alpha=0.5),
    )
    assert first is initial
    assert first_diagnostics == {"speaker": "authored", "rig": "authored"}
    assert struct.pack(">ddd", *first.sources[0].velocity_world_mps) == struct.pack(
        ">ddd", *source_velocity
    )
    assert struct.pack(">ddd", *first.arrays[0].velocity_world_mps) == struct.pack(
        ">ddd", *array_velocity
    )

    moved = _scene(
        _source(position=(1.2, 2.0, 3.0), velocity=None),
        _array(position=(-1.0, 1.1, 0.0), velocity=None),
    )
    second, second_diagnostics = enrich_snapshot_motion(
        moved,
        selected_array_id="rig",
        time_s=1.1,
        pose_history=history,
        motion_config=_motion(smoothing_alpha=0.5),
    )
    assert second_diagnostics == {"speaker": "derived", "rig": "derived"}
    assert second.sources[0].velocity_world_mps == pytest.approx((1.0, 0.0, 0.0))
    assert second.arrays[0].velocity_world_mps == pytest.approx((0.0, 0.5, 0.0))


def test_snapshot_collision_fails_before_any_history_mutation():
    scene = _scene(_source(source_id="rig"), _array())
    history = PoseHistory()
    with pytest.raises(ConfigValidationError, match="collision.*rig"):
        enrich_snapshot_motion(
            scene,
            selected_array_id="rig",
            time_s=0.0,
            pose_history=history,
            motion_config=_motion(),
        )
    assert history._entities == {}


class _FakePrim:
    def __init__(self, path: str, type_name: str, attributes: dict[str, object]):
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    def __init__(self, prims: tuple[_FakePrim, ...]):
        self._prims = list(prims)

    def Traverse(self):
        return tuple(self._prims)

    def GetPrimAtPath(self, path: str):
        return next((prim for prim in self._prims if prim.path == path), None)

    def RemovePrim(self, path: str):
        self._prims = [
            prim
            for prim in self._prims
            if prim.path != path and not prim.path.startswith(f"{path}/")
        ]

    def add(self, prim: _FakePrim):
        self._prims.append(prim)


def _fake_stage():
    source = _FakePrim(
        "/World/Speaker",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker",
            "ias:class_label": "Speech",
            "ias:position_world": (1.0, 0.0, 0.0),
            "ias:duration_s": 10.0,
        },
    )
    array = _FakePrim(
        "/World/Rig",
        "Xform",
        {
            "ias:array_id": "rig",
            "ias:position_world": (0.0, 0.0, 0.0),
            "ias:layout_name": "quad_front",
        },
    )
    return _FakeStage((source, array)), source, array


def test_fake_stage_snapshot_seam_uses_explicit_simulation_time_not_time_code():
    stage, source_prim, array_prim = _fake_stage()
    history = PoseHistory()
    diagnostics = {}
    first = build_stage_snapshot(
        stage,
        timestamp_ms=1_000,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        usd_time_code=123.0,
        motion_config=_motion(),
        pose_history=history,
        simulation_time_s=1.0,
        diagnostics_out=diagnostics,
    )
    assert first.sources[0].velocity_world_mps is None
    assert diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }

    source_prim.attributes["ias:position_world"] = (1.2, 0.0, 0.0)
    array_prim.attributes["ias:position_world"] = (0.0, 0.1, 0.0)
    second = build_stage_snapshot(
        stage,
        timestamp_ms=9_999,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        usd_time_code=-50.0,
        motion_config=_motion(),
        pose_history=history,
        simulation_time_s=1.1,
        diagnostics_out=diagnostics,
    )
    assert second.sources[0].velocity_world_mps == pytest.approx((2.0, 0.0, 0.0))
    assert second.arrays[0].velocity_world_mps == pytest.approx((0.0, 1.0, 0.0))
    assert diagnostics["motion"]["velocity_source"] == {
        "speaker": "derived",
        "rig": "derived",
    }


def test_enabled_stage_snapshot_requires_finite_explicit_simulation_time():
    stage, _, _ = _fake_stage()
    history = PoseHistory()
    with pytest.raises(ValueError, match="simulation_time_s"):
        build_stage_snapshot(
            stage,
            timestamp_ms=0,
            array_prim_path="/World/Rig",
            source_prim_path="/World/Speaker",
            motion_config=_motion(),
            pose_history=history,
        )
    with pytest.raises(ValueError, match="time_s.*finite"):
        build_stage_snapshot(
            stage,
            timestamp_ms=0,
            array_prim_path="/World/Rig",
            source_prim_path="/World/Speaker",
            motion_config=_motion(),
            pose_history=history,
            simulation_time_s=math.nan,
        )
    assert history._entities == {}


def test_offline_sensor_rejects_pose_derivation_before_capture():
    raw = _raw_config()
    raw["audio"]["effects"] = {"motion": {"derive_velocity_from_poses": True}}
    config = validate_audio_config(raw)
    with pytest.raises(UnsupportedEffectError, match="from_config is offline"):
        IsaacAudioArraySensor.from_config(config=config, array_id="rig")


def test_empty_source_scene_enriches_selected_array_and_backend_emits_no_detection():
    array = _array()
    scene = AudioSceneSnapshot(
        stage_id="empty_motion_scene",
        timestamp_ms=0,
        sources=(),
        arrays=(array,),
    )
    enriched, diagnostics = enrich_snapshot_motion(
        scene,
        selected_array_id="rig",
        time_s=0.0,
        pose_history=PoseHistory(),
        motion_config=_motion(),
    )
    assert diagnostics == {"rig": "none:first_sample"}
    assert enriched.sources == ()
    frame = TdoaSyntheticBackend(effects=EffectsConfig(motion=_motion())).simulate(
        enriched,
        enriched.array_by_id("rig"),
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=0.05,
            timestamp_ms=0,
            sample_rate_hz=48_000,
        ),
    )
    assert frame.detections == ()


def test_live_extension_enriches_frame_diagnostics_and_rediscovery_keeps_history():
    stage, source_prim, _ = _fake_stage()
    effects = EffectsConfig(motion=_motion())
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        backend="tdoa_synthetic",
        update_period_s=0.05,
        effects=effects,
    ).start()
    first = sensor.update(sim_time_s=1.0)
    assert first.diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }
    assert "motion" not in first.diagnostics["stage_snapshot"]
    assert first.detections[0].diagnostics["doppler_factor"] == 1.0

    source_prim.attributes["ias:position_world"] = (1.1, 0.0, 0.0)
    second = sensor.update(sim_time_s=1.05)
    assert second.diagnostics["motion"]["velocity_source"] == {
        "speaker": "derived",
        "rig": "derived",
    }
    sensor.rediscover()
    source_prim.attributes["ias:position_world"] = (1.2, 0.0, 0.0)
    after_rediscovery = sensor.update(sim_time_s=1.10)
    assert after_rediscovery.diagnostics["motion"]["velocity_source"] == {
        "speaker": "derived",
        "rig": "derived",
    }

    sensor.reset()
    source_prim.attributes["ias:position_world"] = (1.3, 0.0, 0.0)
    after_reset = sensor.update(sim_time_s=2.0)
    assert after_reset.diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }
    sensor.close()


def test_live_direct_capture_requires_explicit_motion_time():
    stage, _, _ = _fake_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        effects=EffectsConfig(motion=_motion()),
    )
    with pytest.raises(ValueError, match="explicit sim_time_s"):
        sensor.capture(timestamp_ms=0)
    assert sensor._pose_history._entities == {}
    sensor.close()


def test_stage_replacement_clears_history_before_new_stage_sample():
    first_stage, first_source, _ = _fake_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=first_stage,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        backend="geometry_only",
        effects=EffectsConfig(motion=_motion()),
    ).start()
    sensor.update(sim_time_s=0.0)
    first_source.attributes["ias:position_world"] = (1.1, 0.0, 0.0)
    assert (
        sensor.update(sim_time_s=0.05).diagnostics["motion"]["velocity_source"][
            "speaker"
        ]
        == "derived"
    )

    second_stage, _, _ = _fake_stage()
    sensor.stage = second_stage
    replaced = sensor.update(sim_time_s=0.10)
    assert replaced.diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }
    sensor.close()


def test_entity_removal_and_same_id_new_prim_purges_only_removed_history():
    stage, _, _ = _fake_stage()
    second_source = _FakePrim(
        "/World/Second",
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "second",
            "ias:position_world": (2.0, 0.0, 0.0),
            "ias:duration_s": 10.0,
        },
    )
    stage.add(second_source)
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        backend="geometry_only",
        effects=EffectsConfig(motion=_motion()),
    ).start()
    sensor.update(sim_time_s=0.0)
    second_source.attributes["ias:position_world"] = (2.1, 0.0, 0.0)
    derived = sensor.update(sim_time_s=0.05)
    assert derived.diagnostics["motion"]["velocity_source"]["second"] == "derived"

    stage.RemovePrim("/World/Second")
    sensor.rediscover()
    survivor = sensor.update(sim_time_s=0.10)
    assert "second" not in survivor.diagnostics["motion"]["velocity_source"]
    assert survivor.diagnostics["motion"]["velocity_source"]["speaker"] == "derived"

    stage.add(
        _FakePrim(
            "/World/ReusedSecond",
            "Sound",
            {
                "filePath": "generated://impulse",
                "ias:source_id": "second",
                "ias:position_world": (6.0, 0.0, 0.0),
                "ias:duration_s": 10.0,
            },
        )
    )
    sensor.rediscover()
    reused = sensor.update(sim_time_s=0.16)
    assert reused.diagnostics["motion"]["velocity_source"]["second"] == (
        "none:first_sample"
    )
    assert reused.diagnostics["motion"]["velocity_source"]["speaker"] == "derived"
    sensor.close()


class _EventStream:
    def __init__(self):
        self.callback = None

    def create_subscription_to_pop(self, callback, name=None):
        del name
        self.callback = callback
        return SimpleNamespace(callback=callback)

    def trigger(self, event_type):
        self.callback(SimpleNamespace(type=event_type))


@pytest.mark.parametrize("event_name", ["STOP", "RESET"])
def test_fake_timeline_stop_and_reset_events_clear_history(monkeypatch, event_name):
    update_stream = _EventStream()
    timeline_stream = _EventStream()
    omni = ModuleType("omni")
    kit = ModuleType("omni.kit")
    app_module = ModuleType("omni.kit.app")
    app_module.get_app = lambda: SimpleNamespace(
        get_update_event_stream=lambda: update_stream
    )
    timeline_module = ModuleType("omni.timeline")
    timeline_module.TimelineEventType = SimpleNamespace(STOP=10, RESET=20)
    timeline_module.get_timeline_interface = lambda: SimpleNamespace(
        get_timeline_event_stream=lambda: timeline_stream,
        get_current_time=lambda: 0.0,
    )
    omni.kit = kit
    omni.timeline = timeline_module
    kit.app = app_module
    monkeypatch.setitem(sys.modules, "omni", omni)
    monkeypatch.setitem(sys.modules, "omni.kit", kit)
    monkeypatch.setitem(sys.modules, "omni.kit.app", app_module)
    monkeypatch.setitem(sys.modules, "omni.timeline", timeline_module)

    stage, source_prim, _ = _fake_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        source_prim_path="/World/Speaker",
        backend="geometry_only",
        effects=EffectsConfig(motion=_motion()),
    ).start(subscribe_to_update_stream=True)
    sensor.update(sim_time_s=0.0)
    source_prim.attributes["ias:position_world"] = (1.1, 0.0, 0.0)
    sensor.update(sim_time_s=0.05)
    timeline_stream.trigger(getattr(timeline_module.TimelineEventType, event_name))
    source_prim.attributes["ias:position_world"] = (1.2, 0.0, 0.0)
    after_event = sensor.update(sim_time_s=0.10)
    assert after_event.diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }
    assert sensor._update_subscription is not None
    assert sensor._timeline_subscription is not None
    sensor.stop()
    assert sensor._update_subscription is None
    assert sensor._timeline_subscription is None
    sensor.close()
