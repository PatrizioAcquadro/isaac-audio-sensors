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
from tests.helpers import (
    CaptureSink,
    FakeShoeBox,
    install_fake_pyroom,
    run_frame_pipeline,
)


def test_backend_selects_canonical_array_state_from_snapshot(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    first = _array("first")
    selected = replace(
        first,
        array_id="selected",
        prim_path="/World/Rig/Selected",
        position_world=(1.0, 0.5, 0.25),
    )
    scene = replace(_scene(_source("speaker"), array=first), arrays=(first, selected))

    frame, block = run_frame_pipeline(
        AnalyticAcoustics(), scene, "selected", _window(0.1)
    )

    assert frame.array_id == "selected"
    assert frame.array_pose is not None
    assert frame.array_pose.position_m == selected.position_world
    assert frame.producer_id == "analytic_acoustics"
    assert frame.observations == ()
    assert frame.channel_validity == {
        microphone.mic_id: True for microphone in selected.microphones
    }
    assert block.array_id == "selected"


def test_backend_rejects_array_id_absent_from_snapshot(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    with pytest.raises(KeyError, match="AudioSceneSnapshot has no array 'missing'"):
        AnalyticAcoustics().propagate(
            _scene(_source("speaker"), array=array), "missing", _window(0.1)
        )


def test_room_path_keeps_waveform_and_rms_but_emits_no_oracle_observations(
    monkeypatch,
) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    scene = _scene(_source("speaker"), array=array)
    sink = CaptureSink()

    frame, block = run_frame_pipeline(
        AnalyticAcoustics(max_order=1),
        scene,
        array.array_id,
        _window(),
        waveform_sink=sink,
    )

    assert frame.producer_id == "analytic_acoustics"
    assert frame.observations == ()
    assert frame.diagnostics["analytic_solver"]["provider"] == "pyroomacoustics"
    assert frame.diagnostics["analytic_solver"]["provider_version"] == "fake-test"
    assert sink.calls[0]["block"] is block
    assert all(value > 0.0 for value in frame.aggregate_per_mic_rms.values())
    mixture = sink.calls[0]["mixture"]
    for index, microphone in enumerate(array.microphones):
        assert frame.aggregate_per_mic_rms[microphone.mic_id] == pytest.approx(
            np.sqrt(np.mean(mixture[index] ** 2))
        )
    assert FakeShoeBox.instances[-1].max_order == 1


def test_observation_cap_never_changes_rendered_soundscape(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    scene = _scene(
        _source("weak", gain_db=-20.0),
        _source("strong", position=(0.0, 3.0, 0.0), gain_db=20.0),
        array=array,
    )
    frames = []
    mixtures = []
    for cap in (None, 1, 0):
        sink = CaptureSink()
        frame, _ = run_frame_pipeline(
            AnalyticAcoustics(),
            scene,
            array.array_id,
            _window(0.1),
            waveform_sink=sink,
            max_observations=cap,
        )
        frames.append(frame)
        mixtures.append(sink.calls[0]["mixture"])

    assert np.array_equal(mixtures[0], mixtures[1])
    assert np.array_equal(mixtures[0], mixtures[2])
    assert all(frame.observations == () for frame in frames)
    assert [frame.max_observations for frame in frames] == [None, 1, 0]


def test_room_occlusion_replaces_only_affected_source_stem(monkeypatch) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    first = _source("first")
    second = _source("second", position=(0.0, 3.0, 0.0))
    scene = _scene(first, second, array=array)

    def render(selected_scene, max_order):
        sink = CaptureSink()
        run_frame_pipeline(
            AnalyticAcoustics(max_order=max_order),
            selected_scene,
            array.array_id,
            _window(0.1),
            waveform_sink=sink,
        )
        return sink.calls[0]["mixture"]

    direct_first = render(replace(scene, sources=(first,)), 0)
    full_first = render(replace(scene, sources=(first,)), 1)
    full_second = render(replace(scene, sources=(second,)), 1)
    baseline = render(scene, 1)
    occlusion = SourceOcclusion(
        array_id=array.array_id,
        source_id=first.source_id,
        per_mic_blocked={mic.mic_id: True for mic in array.microphones},
        per_mic_attenuation_db={mic.mic_id: 20.0 for mic in array.microphones},
    )
    observed = render(replace(scene, occlusion=(occlusion,)), 1)
    sample_count = max(
        item.shape[1]
        for item in (direct_first, full_first, full_second, baseline, observed)
    )

    def pad(waveform):
        padded = np.zeros((waveform.shape[0], sample_count), dtype=waveform.dtype)
        padded[:, : waveform.shape[1]] = waveform
        return padded

    direct_first, full_first, full_second, baseline, observed = map(
        pad, (direct_first, full_first, full_second, baseline, observed)
    )
    np.testing.assert_allclose(
        baseline, full_first + full_second, rtol=1e-6, atol=1e-8
    )
    np.testing.assert_allclose(
        observed,
        0.1 * direct_first + (full_first - direct_first) + full_second,
        rtol=1e-6,
        atol=3e-8,
    )


def test_removed_backend_perception_arguments_are_rejected() -> None:
    with pytest.raises(TypeError, match="doa_estimator"):
        AnalyticAcoustics(doa_estimator="srp_phat")
    with pytest.raises(TypeError, match="max_detections"):
        AnalyticAcoustics(max_detections=1)


def test_room_rejects_non_public_file_asset_paths(monkeypatch, tmp_path) -> None:
    install_fake_pyroom(monkeypatch)
    array = _array()
    source = _source("speaker", audio_asset_path=str(tmp_path / "private.wav"))
    with pytest.raises(ValueError, match="relative public package path"):
        AnalyticAcoustics().propagate(
            _scene(source, array=array), array.array_id, _window()
        )


def test_room_rejects_malformed_pyroom_signals(monkeypatch) -> None:
    fake_pra = install_fake_pyroom(monkeypatch)
    fake_pra.ShoeBox = _MalformedSignalShoeBox
    array = _array()
    with pytest.raises(ValueError, match="unexpected mic signal shape"):
        AnalyticAcoustics().propagate(
            _scene(_source("speaker"), array=array), array.array_id, _window()
        )


def test_room_unavailable_error_is_clear(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pyroomacoustics", None)
    array = _array()
    with pytest.raises(OptionalDependencyUnavailable, match="room"):
        AnalyticAcoustics().propagate(
            _scene(_source("speaker"), array=array), array.array_id, _window()
        )


def _array(array_id: str = "rig"):
    return create_microphone_array(
        array_id=array_id,
        prim_path=f"/World/Rig/{array_id}",
        layout_name="quad_front",
    )


def _source(
    source_id: str,
    *,
    position: tuple[float, float, float] = (3.0, 0.0, 0.0),
    audio_asset_path: str | None = "generated://impulse",
    gain_db: float = 0.0,
) -> AudioSourceSpec:
    return AudioSourceSpec(
        source_id=source_id,
        prim_path=f"/World/Sources/{source_id}",
        class_label="Speech",
        audio_asset_path=audio_asset_path,
        position_world=position,
        orientation_world_quat=None,
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=gain_db,
    )


def _scene(*sources: AudioSourceSpec, array) -> AudioSceneSnapshot:
    return AudioSceneSnapshot(
        stage_id="room_backend_test",
        sources=sources,
        arrays=(array,),
        environment=shoebox_environment(
            environment_id="unit_room",
            dimensions_m=(6.0, 5.0, 3.0),
            absorption=0.35,
            position_world=(-1.5, -1.0, -1.5),
        ),
    )


def _window(end_time_s: float = 1.0) -> AudioTimeWindow:
    return AudioTimeWindow(start_time_s=0.0, end_time_s=end_time_s, frame_index=0)


class _MalformedSignalShoeBox(FakeShoeBox):
    def simulate(self, return_premix=False):
        self.mic_array.signals = np.zeros((1, 16))
        if return_premix:
            return np.zeros((1, 16))
        return None
