"""Record two acquisitions, split them, and collate observed-only NumPy inputs."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from isaac_audio_sensors import __version__
from isaac_audio_sensors.core import AudioPerceptionPipeline
from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.core.plugins import AuditokActivityDetector
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
)
from isaac_audio_sensors.recording import (
    CreationProvenance,
    DeviceProvenance,
    LearningDataset,
    SessionRecorder,
    collate_learning_samples,
    simulate_dataset_frame,
)


def record(root: Path, pattern: str) -> Path:
    array = create_microphone_array(
        array_id="stereo", prim_path="/World/Array", layout_name="stereo_y"
    )
    scene_id = f"scene_{pattern}"
    scene = AudioSceneSnapshot(
        stage_id=scene_id,
        arrays=(array,),
        sources=(
            AudioSourceSpec(
                source_id="speaker",
                prim_path="/World/Speaker",
                class_label="Sound",
                audio_asset_path=f"generated://{pattern}",
                position_world=(1, 0.3, 0),
                orientation_world_quat=None,
                start_time_s=0,
                duration_s=0.3,
                gain_db=0,
            ),
        ),
        environment=free_field_environment(environment_id=scene_id),
    )
    backend = AnalyticAcoustics()
    perception = AudioPerceptionPipeline(
        activity_detector=AuditokActivityDetector(energy_threshold_dbfs=-60)
    )
    window_samples = round(0.1 * array.sample_rate_hz)
    recorder = SessionRecorder(
        root,
        {
            "dataset_id": pattern,
            "session_id": f"capture_{pattern}",
            "backend_id": backend.backend_id,
            "runtime_profile": "waveform_fidelity",
            "sample_rate_hz": array.sample_rate_hz,
            "channel_order": [mic.mic_id for mic in array.microphones],
            "dtype": "float32",
            "session_seed": 42,
            "window_sample_count": window_samples,
            "hop_sample_count": window_samples,
            "shard_max_frames": 3,
            "shard_episode_aligned": True,
            "split_grouping_key": "scene_id",
        },
        creation=CreationProvenance(
            tool_name="learning_example",
            tool_version=__version__,
            backend_id=backend.backend_id,
            estimator_id="none",
        ),
        device=DeviceProvenance(
            device_id="example",
            device_type="synthetic",
            platform="python",
            compute_device="cpu",
        ),
        license="CC0-1.0",
        source="Generated learning example",
        coordinate_frames=("world", array.array_id),
        time_base="simulation_time",
    )
    recorder.begin_episode(
        scene_id,
        scene_id,
        scene_id,
        trajectory_id=f"route_{pattern}",
        source_asset_ids=(f"generated_{pattern}",),
    )
    for index in range(3):
        frame, block, truth = simulate_dataset_frame(
            backend,
            scene,
            array.array_id,
            AudioTimeWindow(
                start_time_s=index * 0.1,
                end_time_s=(index + 1) * 0.1,
                frame_index=index,
            ),
            perception=perception,
        )
        result = recorder.append_frame(frame, block, truth=truth, is_reset=index == 0)
        if not result.accepted:
            raise RuntimeError(result.reason)
    recorder.end_episode()
    recorder.finalize()
    return root


def main() -> None:
    # Temporary recordings keep this example repeatable without retained outputs.
    with TemporaryDirectory(prefix="ias-learning-") as directory:
        roots = [record(Path(directory) / name, name) for name in ("impulse", "pulse")]
        dataset = LearningDataset.open(roots)
        assignments = dataset.build_split(ratios={"train": 0.5, "test": 0.5}, seed=42)
        batch = collate_learning_samples(
            list(dataset.iter_samples(split="train", with_supervision=True))
        )
        print(
            {
                "assignments": dict(assignments),
                "policy_waveform_shape": batch["policy_inputs"]["waveform"].shape,
                "supervised_frames": sum(truth is not None for truth in batch["truth"]),
            }
        )
        # Feed only batch["policy_inputs"] to the policy. Targets remain separate.


if __name__ == "__main__":
    main()
