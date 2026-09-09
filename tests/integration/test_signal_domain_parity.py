"""Maintained perception semantics survive producer changes and recorded faults."""

from dataclasses import replace

import numpy as np
import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.io.traces import frame_to_trace_dict
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.plugins import AuditokActivityDetector
from isaac_audio_sensors.core.plugins.standard_doa import MaintainedDoaEstimator
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioTimeWindow,
    MicrophoneSignalBlock,
)
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    SessionDataset,
    SessionRecorder,
    replay_session,
    validate_dataset,
)
from tests.helpers import source


@pytest.mark.parametrize(
    ("layout", "rate"),
    (("mono", 8000), ("stereo_y", 16000), ("quad_cross", 16000), ("quad_cross", 48000)),
)
@pytest.mark.parametrize("moving", [False, True])
def test_producer_parity_and_recorded_fault_replay(layout, rate, tmp_path, moving):
    if layout == "quad_cross":
        pytest.importorskip("pyroomacoustics")
    array = create_microphone_array(
        array_id="array", prim_path="/Array", layout_name=layout, sample_rate_hz=rate
    )
    ids = tuple(m.mic_id for m in array.microphones)
    count = len(ids)
    scene = AudioSceneSnapshot(
        stage_id="parity",
        arrays=(array,),
        sources=(source("reference", (2, 0, 0), audio_asset_path="generated://tone"),),
        environment=free_field_environment(environment_id="free"),
    )

    def pipeline():
        return AudioPerceptionPipeline(
            activity_detector=AuditokActivityDetector(energy_threshold_dbfs=-60),
            doa_estimator=None if count == 1 else MaintainedDoaEstimator(),
        )

    backend = AnalyticAcoustics()
    simulated_pipeline, physical_pipeline = pipeline(), pipeline()
    originals = []
    recorder = SessionRecorder(
        tmp_path / "session",
        {
            "backend_id": "external_pcm",
            "channel_order": list(ids),
            "dataset_id": "domain_parity",
            "dtype": "float32",
            "hop_sample_count": rate // 20,
            "window_sample_count": rate // 20,
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": rate,
            "session_seed": 0,
            "shard_episode_aligned": False,
            "shard_max_frames": 4,
            "split_grouping_key": "scene_id",
        },
        creation=CreationProvenance(
            tool_name="signal_parity",
            tool_version="1",
            backend_id="external_pcm",
            estimator_id="none" if count == 1 else "maintained_doa",
        ),
        device=DeviceProvenance(
            device_id="test", device_type="test", platform="host", compute_device="cpu"
        ),
        license="CC0-1.0",
        source="Generated contract test signals",
        coordinate_frames=("world",),
        time_base="monotonic",
    )
    recorder.begin_episode("scene", "environment", "scene")
    for index in range(16):
        offset = int(index >= 6)
        start = (index + offset) / 20
        current = scene
        if moving:
            current = replace(
                scene,
                sources=(
                    replace(
                        scene.sources[0],
                        position_world=(1.0 - 3.0 * start, 1.0, 0.0),
                        velocity_world_mps=(-3.0, 0.0, 0.0),
                    ),
                ),
            )
        block = backend.propagate(
            current,
            array.array_id,
            AudioTimeWindow(
                start_time_s=(index + offset) / 20,
                end_time_s=(index + offset + 1) / 20,
                frame_index=index,
            ),
        )
        clipped = np.clip(block.samples, -0.0001, 0.0001)
        block = replace(
            block,
            samples=clipped if index == 3 else block.samples,
            channel_clipping=(True,) * count if index == 3 else (None,) * count,
            channel_validity=(False,) * count if index == 7 else (True,) * count,
            discontinuity=index in (0, 10),
        )
        physical = replace(
            block,
            producer_id="external_pcm",
            provenance="physical_capture",
            clock_domain="device:take",
            diagnostics={"acquisition": {"measured_calibration": None}},
        )
        frame_id = f"frame_{index}"
        simulated = simulated_pipeline.process(block, array, frame_id=frame_id)
        observed = physical_pipeline.process(physical, array, frame_id=frame_id)
        assert simulated.observations == observed.observations
        assert simulated.aggregate_per_mic_rms == observed.aggregate_per_mic_rms
        assert simulated.diagnostics["perception"] == observed.diagnostics["perception"]
        reason = observed.diagnostics["perception"]["reset_reason"]
        if index in (6, 7, 8, 10):
            assert reason is not None
            fresh = pipeline().process(physical, array, frame_id=frame_id)
            assert fresh.observations == observed.observations
        appended = recorder.append_frame(
            observed, physical, is_reset=reason is not None
        )
        assert appended.accepted, appended.reason
        originals.append((physical, frame_to_trace_dict(observed)))
    recorder.end_episode()
    recorder.finalize()
    assert validate_dataset(tmp_path / "session").status == "passed"
    replay_pipeline = pipeline()
    dataset = SessionDataset.open(tmp_path / "session")
    for (original, expected), item in zip(
        originals, dataset.iter_records(), strict=True
    ):
        actual = frame_to_trace_dict(item.frame)
        assert actual["observations"] == expected["observations"]
        assert actual["diagnostics"] == expected["diagnostics"]
        audio = dataset.read_frame_audio(item)
        np.testing.assert_array_equal(audio, original.samples)
        metadata = item.frame.diagnostics["signal"]
        replayed = MicrophoneSignalBlock(
            samples=audio,
            microphone_ids=ids,
            microphone_positions_m=tuple(
                metadata["microphone_positions_m"][m] for m in ids
            ),
            array_id=item.frame.array_id,
            sample_rate_hz=rate,
            time_window=AudioTimeWindow(
                start_time_s=item.frame.start_time_s,
                end_time_s=item.frame.end_time_s,
                frame_index=item.frame.frame_index,
            ),
            clock_domain=metadata["clock_domain"],
            discontinuity=metadata["discontinuity"],
            channel_validity=tuple(item.frame.channel_validity[m] for m in ids),
            channel_clipping=tuple(metadata["channel_clipping"][m] for m in ids),
            producer_id=item.frame.producer_id,
            provenance=item.frame.provenance,
        )
        frame = replay_pipeline.process(replayed, array, frame_id=item.frame.frame_id)
        assert frame_to_trace_dict(frame)["observations"] == expected["observations"]
    resets = [e for e in replay_session(tmp_path / "session") if e.kind == "reset"]
    assert len(resets) == 5
