"""Real multievent output through common simulation, recording and Kit consumers."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("soundfile")
pytest.importorskip("nara_wpe")

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.io.traces import (
    frame_from_trace_dict,
    frame_to_trace_dict,
)
from isaac_audio_sensors.core.perception import _build_standard_perception_pipeline
from isaac_audio_sensors.core.simulation import simulate_frame
from isaac_audio_sensors.core.types import AudioTimeWindow
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.kit.controller import ExtensionController
from isaac_audio_sensors.kit.instruments import append_observation_history
from isaac_audio_sensors.recording import (
    LearningDataset,
    SessionRecorder,
    validate_dataset,
)
from tests.integration.test_recording_writer import _configuration, _kwargs
from tools.smoke.multisource_reference import reference_scenes


@pytest.mark.parametrize("array_index", range(4))
def test_real_multisource_common_consumers(tmp_path, monkeypatch, array_index):
    monkeypatch.chdir(tmp_path)
    scene = reference_scenes(tmp_path / "signals")[array_index]
    array = scene.arrays[0]
    backend = get_backend("analytic_acoustics")
    pipeline = _build_standard_perception_pipeline(
        energy_threshold_dbfs=-60, doa_enabled=True
    )
    config = _configuration(aligned=True)
    config.update(
        backend_id="analytic_acoustics",
        sample_rate_hz=16000,
        channel_order=[m.mic_id for m in array.microphones],
        window_sample_count=800,
        hop_sample_count=800,
    )
    provenance = _kwargs()
    provenance["creation"] = replace(
        provenance["creation"], backend_id="analytic_acoustics"
    )
    recorder = SessionRecorder(tmp_path / "session", config, **provenance)
    recorder.begin_episode("scene", "environment", "scene")
    frames = []
    for i in range(18):
        frame, block = simulate_frame(
            backend,
            scene,
            array.array_id,
            AudioTimeWindow(
                start_time_s=i * 0.05, end_time_s=(i + 1) * 0.05, frame_index=i
            ),
            perception=pipeline,
        )
        frames.append(frame)
        assert recorder.append_frame(frame, block, is_reset=i == 0).accepted
        assert len(frame.observations) == (0 if i < 14 else 2)
        assert (
            frame_from_trace_dict(frame_to_trace_dict(frame)).observations
            == frame.observations
        )
    recorder.end_episode()
    recorder.finalize()
    assert validate_dataset(tmp_path / "session").status == "passed"
    loaded = list(LearningDataset.open([tmp_path / "session"]).iter_samples())
    assert [len(s.frame.observations) for s in loaded] == [0] * 14 + [2] * 4
    assert not loaded[-1].policy_inputs["detection_score_mask"].any()
    np.testing.assert_allclose(
        loaded[-1].policy_inputs["bearing_deg"], [20, 100], atol=5
    )
    assert loaded[-1].policy_inputs["elevation_deg_mask"].all() == (array_index >= 2)
    history = []
    append_observation_history(history, frames[-1])
    assert len(history) == 2
    assert history[0]["observation_id"] != history[1]["observation_id"]
    controller = ExtensionController()
    controller._sensor_session._record_latest_frame(frames[-1])
    assert controller.state.latest_observation_count == 2
    assert len(controller.state.observation_history) == 2
    monkeypatch.setattr(
        IsaacAudioArraySensor, "_scene_for_capture", lambda self, **kwargs: scene
    )
    sensor = IsaacAudioArraySensor(
        array_id=array.array_id,
        stage=object(),
        environment=scene.environment,
        array_prim_path=array.prim_path,
        energy_threshold_dbfs=-60,
        doa_enabled=True,
    )
    for i in range(18):
        captured = sensor.capture(
            start_time_s=i * 0.05, end_time_s=(i + 1) * 0.05, frame_index=i
        )
        assert len(captured.observations) == len(frames[i].observations)
    assert [o.doa for o in captured.observations] == [
        o.doa for o in frames[-1].observations
    ]
    sensor.close()
    # A changed stream discards the previous two-source context immediately.
    restarted = pipeline.process(
        replace(block, discontinuity=True), array, frame_id="reset"
    )
    assert restarted.observations == ()
    assert (
        restarted.diagnostics["perception"]["localization"]["reason"]
        == "insufficient_context"
    )
