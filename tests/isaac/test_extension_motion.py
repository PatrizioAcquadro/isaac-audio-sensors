"""Regression tests for segmented forced updates on a float time lattice."""

from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.core.effects import EffectsConfig, MotionEffectsConfig
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor

UPDATE_PERIOD_S = 0.05


def _segmented_sensor(monkeypatch):
    captures = []

    def _capture(_sensor, **kwargs):
        captures.append(kwargs)
        return object()

    monkeypatch.setattr(IsaacAudioArraySensor, "capture", _capture)
    sensor = IsaacAudioArraySensor(
        array_id="array",
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

    assert sensor._frame_index == len(times)
    assert sensor._last_update_time_s == times[-1]
    assert [capture["end_time_s"] for capture in captures] == times


def test_forced_genuine_overlap_still_raises(monkeypatch):
    sensor, captures = _segmented_sensor(monkeypatch)
    first = sensor.update(sim_time_s=UPDATE_PERIOD_S, force=True)

    with pytest.raises(ValueError, match="duplicates or overlaps"):
        sensor.update(sim_time_s=UPDATE_PERIOD_S * 1.5, force=True)

    assert sensor.latest_frame is first
    assert sensor._frame_index == 1
    assert len(captures) == 1


def test_forced_duplicate_time_still_raises(monkeypatch):
    sensor, captures = _segmented_sensor(monkeypatch)
    first = sensor.update(sim_time_s=UPDATE_PERIOD_S, force=True)

    with pytest.raises(ValueError, match="duplicates or overlaps"):
        sensor.update(sim_time_s=UPDATE_PERIOD_S, force=True)

    assert sensor.latest_frame is first
    assert sensor._frame_index == 1
    assert len(captures) == 1
