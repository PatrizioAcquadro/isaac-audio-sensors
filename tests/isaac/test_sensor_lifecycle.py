from __future__ import annotations

import math
import sys
from types import ModuleType, SimpleNamespace

import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from tests.helpers import motion_stage

UPDATE_PERIOD_S = 0.05
MANUAL_ENVIRONMENT = free_field_environment(environment_id="lifecycle_free_field")
MANUAL_RESOLUTION = IsaacEnvironmentResolutionCfg(mode="manual")


def _segmented_sensor(monkeypatch):
    captures = []

    def _capture(_sensor, **kwargs):
        captures.append(kwargs)
        return object()

    monkeypatch.setattr(IsaacAudioArraySensor, "capture", _capture)
    sensor = IsaacAudioArraySensor(
        array_id="array",
        stage=object(),
        environment=MANUAL_ENVIRONMENT,
        update_period_s=UPDATE_PERIOD_S,
    )
    sensor.effects = EffectsConfig(
        motion=MotionEffectsConfig(
            derive_velocity_from_poses=True,
            segments_per_window=8,
        )
    )
    return sensor, captures


def test_forced_exact_lattice_with_ulp_jitter_passes_many_steps(monkeypatch):
    sensor, captures = _segmented_sensor(monkeypatch)
    times = []
    for slot in range(256):
        update_time_s = (slot + 1) * UPDATE_PERIOD_S
        if slot % 3 == 0:
            update_time_s = math.nextafter(update_time_s, -math.inf)
        elif slot % 3 == 1:
            update_time_s = math.nextafter(update_time_s, math.inf)
        times.append(update_time_s)

    spacings = [right - left for left, right in zip(times, times[1:], strict=False)]
    assert any(spacing < UPDATE_PERIOD_S for spacing in spacings)

    for update_time_s in times:
        sensor.update(sim_time_s=update_time_s, force=True)

    assert [capture["end_time_s"] for capture in captures] == times
    assert sensor.get_latest_frame() is not None


@pytest.mark.parametrize(
    "next_time_s",
    [UPDATE_PERIOD_S, UPDATE_PERIOD_S * 1.5],
    ids=["duplicate", "overlap"],
)
def test_forced_duplicate_or_overlap_preserves_latest_frame(monkeypatch, next_time_s):
    sensor, captures = _segmented_sensor(monkeypatch)
    first = sensor.update(sim_time_s=UPDATE_PERIOD_S, force=True)

    with pytest.raises(ValueError, match="duplicates or overlaps"):
        sensor.update(sim_time_s=next_time_s, force=True)

    assert sensor.latest_frame is first
    assert len(captures) == 1


def test_manual_capture_and_update_throttling():
    stage, _, _ = motion_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        source_prim_path="/World/Speaker",
        backend="analytic_acoustics",
        update_period_s=UPDATE_PERIOD_S,
    )
    manual = sensor.capture()
    assert manual.provenance == "isaac_live"

    sensor.start()
    first = sensor.update(sim_time_s=0.0)
    assert sensor.update(sim_time_s=0.01) is first
    second = sensor.update(sim_time_s=0.06)
    assert second.frame_index == 1
    assert sensor.get_latest_frame() is second
    assert sensor.latest_scene is not None
    assert sensor.latest_array_spec is not None

    reset_events = []

    def listener():
        reset_events.append("reset")

    sensor.add_reset_listener(listener)
    sensor.add_reset_listener(listener)
    sensor.reset()
    assert reset_events == ["reset"]
    assert sensor.latest_scene is None
    assert sensor.latest_array_spec is None
    sensor.close()


def test_live_sensor_recognizes_analytic_core_backend() -> None:
    stage, _, _ = motion_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        source_prim_path="/World/Speaker",
        backend="analytic_acoustics",
    )

    frame = sensor.capture()

    assert frame.producer_id == "analytic_acoustics"
    assert frame.observations == ()
    assert frame.provenance == "isaac_live"
    assert frame.diagnostics["analytic_solver"] == {
        "solver_id": "free_field_direct",
        "provider": "core",
        "environment_kind": "free_field",
    }


def test_non_monotonic_time_preserves_latest_frame():
    stage, _, _ = motion_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        source_prim_path="/World/Speaker",
        backend="analytic_acoustics",
    ).start()
    first = sensor.update(sim_time_s=1.0)
    with pytest.raises(ValueError, match="non-monotonic"):
        sensor.update(sim_time_s=0.9)
    assert sensor.get_latest_frame() is first
    sensor.close()


class _EventStream:
    def __init__(self):
        self.callback = None

    def create_subscription_to_pop(self, callback, name=None):
        del name
        self.callback = callback
        return SimpleNamespace(callback=callback)

    def trigger(self, event_type=None):
        assert self.callback is not None
        self.callback(SimpleNamespace(type=event_type))


def _install_lifecycle_streams(monkeypatch):
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
    return update_stream, timeline_stream, timeline_module


@pytest.mark.parametrize("event_name", ["STOP", "RESET"])
def test_update_subscription_timeline_reset_and_close(monkeypatch, event_name):
    update_stream, timeline_stream, timeline_module = _install_lifecycle_streams(
        monkeypatch
    )
    stage, source_prim, _ = motion_stage()
    sensor = IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig",
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        source_prim_path="/World/Speaker",
        backend="analytic_acoustics",
        effects=EffectsConfig(
            motion=MotionEffectsConfig(derive_velocity_from_poses=True)
        ),
    ).start(subscribe_to_update_stream=True)

    update_stream.trigger()
    first = sensor.get_latest_frame()
    assert first is not None
    source_prim.attributes["ias:position_world"] = (1.1, 0.0, 0.0)
    sensor.update(sim_time_s=0.05)
    timeline_stream.trigger(getattr(timeline_module.TimelineEventType, event_name))
    source_prim.attributes["ias:position_world"] = (1.2, 0.0, 0.0)
    after_reset = sensor.update(sim_time_s=0.10)
    assert after_reset.diagnostics["motion"]["velocity_source"] == {
        "speaker": "none:first_sample",
        "rig": "none:first_sample",
    }

    sensor.stop()
    stopped = sensor.get_latest_frame()
    update_stream.trigger()
    assert sensor.get_latest_frame() is stopped
    sensor.close()
    with pytest.raises(RuntimeError, match="closed"):
        sensor.update(force=True)
