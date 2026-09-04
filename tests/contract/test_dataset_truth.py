from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pytest

from isaac_audio_sensors.core import AudioObservation, AudioPerceptionPipeline
from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    half_space_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.effects import (
    EffectsConfig,
    NoiseConfig,
    NoiseLevelSpecConfig,
    SelfNoiseConfig,
)
from isaac_audio_sensors.core.math_utils import quaternion_from_euler_deg
from isaac_audio_sensors.core.simulation import simulate_frame
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioTimeWindow,
    SourceOcclusion,
)
from isaac_audio_sensors.recording import AnnotationRecord, simulate_dataset_frame
from isaac_audio_sensors.recording.truth import (
    _annotations_from_dict,
    _annotations_to_dict,
    _truth_from_dict,
    _truth_to_dict,
    _validate_supervision,
)
from tests.helpers import CaptureSink, quad_array, source

WINDOW = AudioTimeWindow(start_time_s=0.0, end_time_s=0.1, frame_index=3)


def scene_with(*sources, array=None, environment=None, occlusion=None):
    return AudioSceneSnapshot(
        stage_id="truth",
        sources=sources,
        arrays=(array or quad_array(),),
        environment=environment or free_field_environment(environment_id="free"),
        occlusion=occlusion,
    )


def simulate(scene, *, backend=None, window=WINDOW, **kwargs):
    return simulate_dataset_frame(
        backend or AnalyticAcoustics(),
        scene,
        scene.arrays[0].array_id,
        window,
        perception=AudioPerceptionPipeline(),
        **kwargs,
    )


def test_empty_truth_and_external_observation_are_independent():
    external = AudioObservation(
        observation_id="external", origin="external_system", detector_id="other"
    )
    frame, block, truth = simulate(scene_with(), external_observations=(external,))
    assert truth.truth_events == ()
    assert frame.observations == (external,)
    assert not np.any(block.samples)
    assert all(value == 0.0 for value in truth.mixture_residual_rms.values())
    assert _truth_from_dict(None) is None
    assert _truth_from_dict(_truth_to_dict(truth)) == truth


@pytest.mark.parametrize("noise", [False, True])
def test_single_render_and_exact_observed_parity_with_received_evidence(noise):
    scene = scene_with(source("one", (1.0, 0.3, 0.2)), source("two", (0.5, 1.0, 0.0)))
    backend = AnalyticAcoustics(
        effects=EffectsConfig(
            noise=NoiseConfig(
                enabled=True,
                seed=123,
                self_noise=SelfNoiseConfig(
                    default=NoiseLevelSpecConfig(level_db=-30.0)
                ),
            )
            if noise
            else NoiseConfig()
        )
    )
    sink = CaptureSink()
    with patch.object(
        backend, "_render_signal", wraps=backend._render_signal
    ) as render:
        frame, block, truth = simulate(scene, backend=backend, waveform_sink=sink)
        assert render.call_count == 1
    plain_frame, plain_block = simulate_frame(
        backend,
        scene,
        "rig",
        WINDOW,
        perception=AudioPerceptionPipeline(),
        waveform_sink=CaptureSink(),
    )
    np.testing.assert_array_equal(block.samples, plain_block.samples)
    assert frame == plain_frame
    assert sink.calls[0]["block"] is block
    assert frame.observations == ()
    assert [event.source_id for event in truth.truth_events] == ["one", "two"]
    assert all(event.emitting for event in truth.truth_events)
    prepared, rendered, _ = backend._render_signal(scene, "rig", WINDOW)
    for index, event in enumerate(truth.truth_events):
        expected = np.sqrt(np.mean(rendered.premix[index, :, :4800] ** 2, axis=1))
        np.testing.assert_allclose(list(event.received_rms.values()), expected)
        assert event.emission_rms > 0
    residual = block.samples.astype(float) - rendered.premix[:, :, :4800].sum(axis=0)
    np.testing.assert_allclose(
        list(truth.mixture_residual_rms.values()), np.sqrt(np.mean(residual**2, axis=1))
    )
    assert set(truth.mixture_residual_rms) == set(prepared.mic_ids)
    payload = _truth_to_dict(truth)
    assert "observations" not in payload
    assert _truth_from_dict(json.loads(json.dumps(payload))) == truth


def test_schedule_emission_received_and_geometry_are_separate(tmp_path, monkeypatch):
    pytest.importorskip("soundfile")
    monkeypatch.chdir(tmp_path)
    import wave

    silent = tmp_path / "silent.wav"
    with wave.open(str(silent), "wb") as output:
        output.setparams((1, 2, 48000, 4800, "NONE", "not compressed"))
        output.writeframes(bytes(9600))
    with wave.open("constant.wav", "wb") as output:
        output.setparams((1, 2, 48000, 4800, "NONE", "not compressed"))
        output.writeframes(np.full(4800, 16384, dtype="<i2").tobytes())
    array = replace(
        quad_array(), orientation_world_quat=quaternion_from_euler_deg(yaw_deg=90)
    )
    scene = scene_with(
        source("inactive", (1, 0, 0), start_time_s=1),
        source("silent", (1, 0, 0), audio_asset_path="silent.wav"),
        source(
            "partial", (0, 2, 0), start_time_s=0.05, audio_asset_path="constant.wav"
        ),
        source("far", (100, 0, 0)),
        source("coincident", array.position_world),
        array=array,
    )
    _, _, truth = simulate(scene)
    inactive, silent_event, partial, far, coincident = truth.truth_events
    assert not inactive.schedule_overlap and not inactive.emitting
    assert silent_event.schedule_overlap and not silent_event.emitting
    assert all(value == 0 for value in silent_event.received_rms.values())
    assert partial.schedule_overlap and partial.emitting
    assert partial.bearing_deg == pytest.approx(0, abs=1e-10)
    assert partial.distance_m == pytest.approx(2)
    assert partial.emission_rms == pytest.approx(0.5 / np.sqrt(2))
    assert far.emitting and all(value == 0 for value in far.received_rms.values())
    assert coincident.distance_m == 0
    assert coincident.bearing_deg is None and coincident.elevation_deg is None


def test_occlusion_attenuates_received_evidence_without_changing_emission():
    array = replace(quad_array(), position_world=(0, 0, 1))
    src = source("blocked", (1, 0, 1))
    baseline = scene_with(src, array=array)
    mic_ids = [mic.mic_id for mic in array.microphones]
    occlusion = SourceOcclusion(
        array_id="rig",
        source_id="blocked",
        per_mic_blocked=dict.fromkeys(mic_ids, True),
        per_mic_attenuation_db=dict.fromkeys(mic_ids, 40.0),
    )
    _, _, clean = simulate(baseline)
    _, _, blocked = simulate(replace(baseline, occlusion=(occlusion,)))
    a, b = clean.truth_events[0], blocked.truth_events[0]
    assert a.occlusion is None
    assert b.occlusion == occlusion
    assert a.emission_rms == b.emission_rms
    np.testing.assert_allclose(
        list(b.received_rms.values()), np.array(list(a.received_rms.values())) * 0.01
    )
    reflected = replace(
        baseline,
        environment=half_space_environment(environment_id="floor"),
        occlusion=(occlusion,),
    )
    _, _, reflection = simulate(reflected, backend=AnalyticAcoustics(max_order=1))
    assert max(reflection.truth_events[0].received_rms.values()) > max(
        b.received_rms.values()
    )
    restored = _truth_from_dict(_truth_to_dict(reflection))
    assert restored == reflection
    occlusion.per_mic_attenuation_db[mic_ids[0]] = 90
    assert b.occlusion.per_mic_attenuation_db[mic_ids[0]] == 40


def test_motion_preserves_snapshot_geometry_and_canonical_annotations():
    src = replace(
        source("moving", (1, 0, 0), audio_asset_path="generated://tone"),
        velocity_world_mps=(30, 0, 0),
    )
    frame, _, truth = simulate(scene_with(src))
    event = truth.truth_events[0]
    assert event.position_world_m == src.position_world
    assert event.distance_m == 1
    assert event.emitting
    annotations = (
        AnnotationRecord(
            annotation_id="label",
            label="speech",
            provenance="manual_annotation:reviewer",
            source_id="moving",
        ),
    )
    assert _validate_supervision(frame, truth, annotations) == annotations
    assert _annotations_from_dict(_annotations_to_dict(annotations)) == annotations
    with pytest.raises(ValueError, match="match the frame"):
        _validate_supervision(frame, replace(truth, frame_id="wrong"), annotations)
    with pytest.raises(ValueError, match="unique"):
        _validate_supervision(frame, truth, annotations * 2)
    with pytest.raises(ValueError, match="absent observation"):
        _validate_supervision(
            frame, truth, (replace(annotations[0], observation_id="missing"),)
        )
    with pytest.raises(ValueError, match="unique"):
        replace(truth, truth_events=truth.truth_events * 2)
    for value in (True, float("nan"), -1):
        with pytest.raises(ValueError):
            replace(event, emission_rms=value)
    with pytest.raises(ValueError):
        replace(event, schedule_overlap="true")
    with pytest.raises(TypeError):
        event.received_rms["front"] = 100
    payload = _truth_to_dict(truth)
    payload["truth_events"][0]["audible"] = True
    with pytest.raises(ValueError, match="exactly"):
        _truth_from_dict(payload)


def test_truth_quaternion_serialization_is_idempotent():
    _, _, truth = simulate(scene_with(source("oriented", (1, 0, 0))))
    event = replace(
        truth.truth_events[0],
        orientation_world_xyzw=(
            0.0938595867742349,
            0.02834747652200631,
            0.8357651039198697,
            0.43276706790505337,
        ),
    )
    truth = replace(truth, truth_events=(event,))
    payload = json.dumps(_truth_to_dict(truth), sort_keys=True)
    for _ in range(3):
        truth = _truth_from_dict(json.loads(payload))
        assert json.dumps(_truth_to_dict(truth), sort_keys=True) == payload


def test_nonlinear_mixture_does_not_redefine_per_source_received_evidence():
    from isaac_audio_sensors.core.effects import ElectronicsConfig

    scene = scene_with(source("loud", (0.2, 0, 0), audio_asset_path="generated://tone"))
    _, clean, clean_truth = simulate(scene)
    backend = AnalyticAcoustics(
        effects=EffectsConfig(
            electronics=ElectronicsConfig(enabled=True, full_scale=0.01, bit_depth=8)
        )
    )
    frame, clipped, truth = simulate(scene, backend=backend)
    assert truth.truth_events == clean_truth.truth_events
    assert not np.array_equal(clean.samples, clipped.samples)
    assert max(truth.mixture_residual_rms.values()) > 0.01
    plain_frame, plain_block = simulate_frame(
        backend, scene, "rig", WINDOW, perception=AudioPerceptionPipeline()
    )
    assert frame == plain_frame
    np.testing.assert_array_equal(clipped.samples, plain_block.samples)


@pytest.mark.parametrize("topology", ["shoebox", "polygon_prism"])
def test_closed_room_truth_uses_same_rendered_window(topology):
    pytest.importorskip("pyroomacoustics")
    from isaac_audio_sensors.core.acoustics import (
        polygon_prism_environment,
        shoebox_environment,
    )

    environment = (
        shoebox_environment(environment_id="room", dimensions_m=(4, 4, 3))
        if topology == "shoebox"
        else polygon_prism_environment(
            environment_id="room",
            floor_vertices_local_m=((0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)),
            height_m=3,
        )
    )
    scene = scene_with(
        source("speaker", (2, 1, 1)),
        array=replace(quad_array(), position_world=(1, 1, 1)),
        environment=environment,
    )
    backend = AnalyticAcoustics(max_order=1)
    frame, block, truth = simulate(scene, backend=backend)
    np.testing.assert_allclose(
        list(truth.truth_events[0].received_rms.values()),
        np.sqrt(np.mean(block.samples.astype(float) ** 2, axis=1)),
        rtol=1e-6,
    )
    assert frame.observations == ()
    assert max(truth.mixture_residual_rms.values()) < 1e-7
