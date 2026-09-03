from __future__ import annotations

from dataclasses import fields, replace

import pytest

from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioObservation,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    ObservationOrigin,
)


def test_specs_accept_optional_world_velocity():
    source = _source(velocity_world_mps=(-10.0, 0.0, 0.0))
    static_source = _source(source_id="static", prim_path="/World/Static")
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
    )

    assert source.velocity_world_mps == (-10.0, 0.0, 0.0)
    assert static_source.velocity_world_mps is None
    assert array.velocity_world_mps is None

    with pytest.raises(ValueError, match="velocity_world_mps"):
        _source(source_id="short", velocity_world_mps=(1.0, 0.0))
    with pytest.raises(ValueError, match="velocity_world_mps"):
        _source(source_id="nan", velocity_world_mps=(float("nan"), 0.0, 0.0))


@pytest.mark.parametrize("loop_count", (-1, 0, 3))
def test_audio_source_accepts_kit_loop_count_semantics(loop_count):
    assert _source(loop_count=loop_count).loop_count == loop_count


@pytest.mark.parametrize("loop_count", (-2, 1.5, True, "1"))
def test_audio_source_rejects_invalid_loop_count(loop_count):
    with pytest.raises(ValueError, match="loop_count"):
        _source(loop_count=loop_count)


def test_audio_time_window_requires_positive_duration():
    window = AudioTimeWindow(
        start_time_s=1.0,
        end_time_s=1.5,
        frame_index=0,
    )
    assert window.start_time_s == 1.0

    with pytest.raises(ValueError, match="end must be after start"):
        AudioTimeWindow(
            start_time_s=1.0,
            end_time_s=1.0,
            frame_index=0,
        )


def test_capture_contract_has_one_authority_per_value():
    assert tuple(field.name for field in fields(AudioTimeWindow)) == (
        "start_time_s",
        "end_time_s",
        "frame_index",
    )
    timestamp_field = next(
        field for field in fields(AudioSensorFrame) if field.name == "timestamp_ms"
    )
    assert timestamp_field.init is False

    with pytest.raises(TypeError, match="timestamp_ms"):
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            frame_index=0,
            timestamp_ms=0,
        )
    with pytest.raises(TypeError, match="sample_rate_hz"):
        AudioTimeWindow(
            start_time_s=0.0,
            end_time_s=1.0,
            frame_index=0,
            sample_rate_hz=48_000,
        )
    with pytest.raises(TypeError, match="timestamp_ms"):
        AudioSceneSnapshot(stage_id="scene", sources=(), arrays=(), timestamp_ms=0)
    with pytest.raises(TypeError, match="timestamp_ms"):
        _observation(timestamp_ms=0)


@pytest.mark.parametrize(
    "values",
    (
        {"start_time_s": float("nan"), "end_time_s": 1.0, "frame_index": 0},
        {"start_time_s": 0.0, "end_time_s": float("inf"), "frame_index": 0},
        {"start_time_s": 0.0, "end_time_s": 1.0, "frame_index": True},
        {"start_time_s": 0.0, "end_time_s": 1.0, "frame_index": -1},
    ),
)
def test_audio_time_window_rejects_invalid_required_values(values):
    with pytest.raises(ValueError):
        AudioTimeWindow(**values)


def test_array_sample_rate_is_a_strict_positive_integer():
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="quad_front",
    )

    assert array.sample_rate_hz == 48_000
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(array, sample_rate_hz=True)
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(array, sample_rate_hz=0)


def test_doa_estimate_validates_optional_elevation_fields():
    doa = DoaEstimate(
        estimated_bearing_deg=90.0,
        bearing_confidence=0.5,
        estimated_elevation_deg=30.0,
        candidate_elevation_deg=(30.0,),
    )
    default = DoaEstimate(estimated_bearing_deg=None, bearing_confidence=0.0)

    assert doa.estimated_elevation_deg == pytest.approx(30.0)
    assert doa.candidate_elevation_deg == pytest.approx((30.0,))
    assert default.estimated_elevation_deg is None
    assert default.candidate_elevation_deg == ()

    with pytest.raises(ValueError, match="estimated_elevation_deg"):
        DoaEstimate(
            estimated_bearing_deg=0.0,
            bearing_confidence=0.0,
            estimated_elevation_deg=120.0,
        )
    with pytest.raises(ValueError, match="candidate_elevation_deg"):
        DoaEstimate(
            estimated_bearing_deg=0.0,
            bearing_confidence=0.0,
            candidate_elevation_deg=(-95.0,),
        )


def _source(
    *,
    source_id: str = "mover",
    prim_path: str = "/World/Mover",
    velocity_world_mps=None,
    loop_count: int = 0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=prim_path,
        class_label="Vehicle",
        audio_asset_path=None,
        position_world=(5.0, 0.0, 0.0),
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=None,
        gain_db=0.0,
        loop_count=loop_count,
        velocity_world_mps=velocity_world_mps,
    )


def _observation(**overrides) -> AudioObservation:
    values = {
        "observation_id": "obs",
        "origin": ObservationOrigin.SIGNAL_DERIVED,
        "detector_id": "fake",
    }
    values.update(overrides)
    return AudioObservation(**values)
