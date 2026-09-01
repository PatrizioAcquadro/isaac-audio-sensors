"""Optional room-acoustics integration tests."""

from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics.environments import shoebox_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.exceptions import OptionalDependencyUnavailable
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    SourceOcclusion,
)
from tests.helpers import CaptureSink, FakeShoeBox, install_fake_pyroom


def _source(
    source_id: str,
    position: tuple[float, float, float],
    *,
    audio_asset_path: str | None = "generated://impulse",
    start_time_s: float = 0.0,
    duration_s: float | None = 1.0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=None,
        start_time_s=start_time_s,
        duration_s=duration_s,
        gain_db=0.0,
    )


def _room_scene_with_sources(*sources: AudioSourceSpec, array):
    return AudioSceneSnapshot(
        stage_id="room_backend_test",
        timestamp_ms=0,
        sources=sources,
        arrays=(array,),
        environment=shoebox_environment(
            environment_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            position_world=(-1.5, -1.0, -1.5),
        ),
    )


def _window(
    *,
    start_time_s: float = 0.0,
    end_time_s: float = 1.0,
    max_events: int | None = None,
) -> AudioTimeWindow:
    return AudioTimeWindow(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        timestamp_ms=0,
        sample_rate_hz=48_000,
        max_events=max_events,
    )


def test_backend_selects_canonical_array_state_from_snapshot(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    first = create_microphone_array(
        array_id="first",
        prim_path="/World/Rig/First",
        layout_name="quad_front",
    )
    selected = replace(
        first,
        array_id="selected",
        prim_path="/World/Rig/Selected",
        position_world=(1.0, 0.5, 0.25),
    )
    scene = replace(
        _room_scene_with_sources(
            _source("speaker", (3.0, 0.0, 0.0)),
            array=first,
        ),
        arrays=(first, selected),
    )

    frame = AnalyticAcoustics().simulate(scene, "selected", _window(end_time_s=0.1))

    assert frame.array_id == "selected"
    assert frame.array_pose is not None
    assert frame.array_pose.position_m == selected.position_world


def test_backend_rejects_array_id_absent_from_snapshot(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )

    with pytest.raises(KeyError, match="AudioSceneSnapshot has no array 'missing'"):
        AnalyticAcoustics().simulate(scene, "missing", _window(end_time_s=0.1))


def test_room_acoustics_fake_pyroom_path_uses_waveforms(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )

    frame = AnalyticAcoustics(max_order=1).simulate(scene, array.array_id, _window())
    detection = frame.detections[0]

    assert frame.backend_id == "analytic_acoustics"
    assert frame.diagnostics["physical_waveform"] is True
    assert frame.diagnostics["pyroomacoustics_version"] == "fake-test"
    assert frame.diagnostics["scheduled_source_ids"] == ("speaker",)
    assert frame.diagnostics["environment_config"] == {
        "environment_id": "unit_room",
        "kind": "shoebox",
        "dimensions_m": (6.0, 5.0, 3.0),
        "absorption": {
            "floor": 0.35,
            "ceiling": 0.35,
            "wall_x_min": 0.35,
            "wall_x_max": 0.35,
            "wall_y_min": 0.35,
            "wall_y_max": 0.35,
        },
        "position_world": (-1.5, -1.0, -1.5),
        "orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
        "surface_count": 6,
    }
    assert frame.diagnostics["analytic_acoustics_options"] == {
        "max_order": 1,
        "air_absorption": False,
        "ray_tracing": False,
    }
    assert frame.diagnostics["per_source_rir_summary"]["speaker"]["rir_length_samples"]
    assert detection.diagnostics["physical_waveform"] is True
    assert detection.diagnostics["pyroomacoustics_version"] == "fake-test"
    assert (
        detection.diagnostics["environment_config"]
        == (frame.diagnostics["environment_config"])
    )
    assert detection.diagnostics["source_waveform_mode"] == "generated://impulse"
    assert set(detection.diagnostics["rir_length_samples"]) == {
        "front",
        "right",
        "rear",
        "left",
    }
    assert set(detection.diagnostics["gcc_phat_peaks"]) == set(
        detection.diagnostics["estimated_tdoa_matrix_s"]
    )
    assert detection.diagnostics["per_mic_rms"] == detection.per_mic_rms
    assert detection.diagnostics["estimated_tdoa_matrix_s"]["rear->front"] > 0.0
    assert (
        detection.diagnostics["direct_path_delay_s"]["rear"]
        > (detection.diagnostics["direct_path_delay_s"]["front"])
    )
    assert detection.doa.estimated_bearing_deg == pytest.approx(0.0, abs=15.0)
    assert all(value > 0.0 for value in frame.aggregate_per_mic_rms.values())
    assert FakeShoeBox.instances[-1].fs == 48_000
    assert FakeShoeBox.instances[-1].max_order == 1
    assert FakeShoeBox.instances[-1].kwargs["air_absorption"] is False
    assert FakeShoeBox.instances[-1].kwargs["ray_tracing"] is False


def test_room_acoustics_schedules_multiple_sources(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("ended", (4.0, 0.0, 0.0), start_time_s=-1.0, duration_s=1.0),
        _source("b_second", (0.0, 3.0, 0.0), start_time_s=0.1, duration_s=0.5),
        _source("a_first", (3.0, 0.0, 0.0), start_time_s=0.0, duration_s=0.5),
        _source("c_truncated", (-3.0, 0.0, 0.0), start_time_s=0.2, duration_s=0.5),
        _source("future", (0.0, -3.0, 0.0), start_time_s=1.0, duration_s=0.5),
        array=array,
    )
    backend = AnalyticAcoustics()
    window = _window(max_events=2)

    first = backend.simulate(scene, array.array_id, window)
    second = backend.simulate(scene, array.array_id, window)

    assert first == second
    assert tuple(detection.source_id for detection in first.detections) == (
        "a_first",
        "b_second",
    )
    by_source_id = {detection.source_id: detection for detection in first.detections}
    assert by_source_id["a_first"].doa.estimated_bearing_deg == pytest.approx(
        0.0,
        abs=20.0,
    )
    assert by_source_id["b_second"].doa.estimated_bearing_deg == pytest.approx(
        90.0,
        abs=20.0,
    )
    assert first.diagnostics["active_source_count"] == 2
    assert first.diagnostics["scheduled_source_ids"] == ("a_first", "b_second")
    assert set(first.diagnostics["per_source_rir_summary"]) == {
        "a_first",
        "b_second",
    }
    assert len(first.detections) == first.max_events == 2
    assert first.detections[0].detection_id == (
        "analytic_acoustics_room_backend_test_rig_0_a_first_00"
    )
    assert first.detections[1].detection_id == (
        "analytic_acoustics_room_backend_test_rig_0_b_second_01"
    )
    assert (
        first.detections[0].diagnostics["environment_microphone_positions_m"]
        == first.detections[1].diagnostics["environment_microphone_positions_m"]
    )


def test_room_acoustics_occlusion_replaces_only_the_affected_source_stem(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    first = _source("first", (3.0, 0.0, 0.0))
    second = _source("second", (0.0, 3.0, 0.0))
    scene = _room_scene_with_sources(first, second, array=array)
    window = _window(end_time_s=0.1)

    def render(selected_scene, max_order):
        sink = CaptureSink()
        AnalyticAcoustics(
            max_order=max_order,
            waveform_writer=sink,
        ).simulate(selected_scene, array.array_id, window)
        return sink.calls[0]["mixture"]

    first_scene = replace(scene, sources=(first,))
    second_scene = replace(scene, sources=(second,))
    direct_first = render(first_scene, 0)
    full_first = render(first_scene, 1)
    full_second = render(second_scene, 1)
    baseline = render(scene, 1)
    occlusion = SourceOcclusion(
        array_id=array.array_id,
        source_id=first.source_id,
        per_mic_blocked={mic.mic_id: True for mic in array.microphones},
        per_mic_attenuation_db={mic.mic_id: 20.0 for mic in array.microphones},
    )
    observed = render(replace(scene, occlusion=(occlusion,)), 1)
    sample_count = max(
        waveform.shape[1]
        for waveform in (direct_first, full_first, full_second, baseline, observed)
    )

    def pad(waveform):
        padded = np.zeros((waveform.shape[0], sample_count), dtype=waveform.dtype)
        padded[:, : waveform.shape[1]] = waveform
        return padded

    direct_first = pad(direct_first)
    full_first = pad(full_first)
    full_second = pad(full_second)
    baseline = pad(baseline)
    observed = pad(observed)
    np.testing.assert_allclose(
        baseline,
        full_first + full_second,
        rtol=0.0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        observed,
        0.1 * direct_first + (full_first - direct_first) + full_second,
        rtol=0.0,
        atol=1e-15,
    )
def test_room_acoustics_rejects_unknown_doa_estimator() -> None:
    with pytest.raises(ValueError, match="doa_estimator"):
        AnalyticAcoustics(doa_estimator="music")


def test_analytic_srp_emits_frames(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )
    backend = AnalyticAcoustics(doa_estimator="srp_phat")

    frame = backend.simulate(scene, array.array_id, _window())
    detection = frame.detections[0]

    assert frame.backend_id == "analytic_acoustics"
    assert frame.provenance == "room_acoustics"
    assert frame.diagnostics["doa_estimator"] == "srp_phat"
    assert detection.diagnostics["doa_estimator"] == "srp_phat"
    srp_diagnostics = detection.diagnostics["srp_phat"]
    assert srp_diagnostics["pair_count"] == 6
    assert srp_diagnostics["grid_point_count"] == 180
    assert srp_diagnostics["elevation_step_deg"] is None
    assert srp_diagnostics["peak_power"] > srp_diagnostics["mean_power"]
    assert detection.doa.estimated_bearing_deg == pytest.approx(0.0, abs=15.0)
    assert detection.doa.estimated_elevation_deg is None
    assert detection.diagnostics["estimated_tdoa_matrix_s"]["rear->front"] > 0.0
    assert frame == backend.simulate(scene, array.array_id, _window())


def test_room_acoustics_rejects_non_public_file_asset_paths(
    monkeypatch,
    tmp_path,
) -> None:
    install_fake_pyroom(monkeypatch)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    source = _source(
        "speaker",
        (3.0, 0.0, 0.0),
        audio_asset_path=str(tmp_path / "private.wav"),
    )
    scene = _room_scene_with_sources(source, array=array)

    with pytest.raises(ValueError, match="relative public package path"):
        AnalyticAcoustics().simulate(scene, array.array_id, _window())


def test_room_acoustics_rejects_malformed_pyroom_signals(monkeypatch) -> None:
    fake_pra = install_fake_pyroom(monkeypatch)
    fake_pra.ShoeBox = _MalformedSignalShoeBox
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(_source("speaker", (3.0, 0.0, 0.0)), array=array)

    with pytest.raises(ValueError, match="unexpected mic signal shape"):
        AnalyticAcoustics().simulate(scene, array.array_id, _window())


def test_room_acoustics_unavailable_error_is_clear(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyroomacoustics", None)
    array = create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig/AudioArray",
        layout_name="quad_front",
    )
    scene = _room_scene_with_sources(
        _source("speaker", (3.0, 0.0, 0.0)),
        array=array,
    )

    with pytest.raises(OptionalDependencyUnavailable, match="room"):
        AnalyticAcoustics().simulate(scene, array.array_id, _window())


class _MalformedSignalShoeBox(FakeShoeBox):
    def simulate(self, return_premix=False):
        self.mic_array.signals = np.zeros((1, 16))
        if return_premix:
            return np.zeros((1, 16))
        return None
