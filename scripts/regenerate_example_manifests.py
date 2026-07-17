"""Regenerate deterministic valid dataset and calibration fixtures."""

from __future__ import annotations

from pathlib import Path

from isaac_audio_sensors.core.calibration_profile import (
    ApplicabilityLimits,
    AudioCalibrationProfile,
    ChannelCalibration,
    FrequencyResponse,
    FrequencyResponsePoint,
    MicrophoneGeometry,
    ScalarCalibrationValue,
    UsableFrequencyRange,
)
from isaac_audio_sensors.core.constants import (
    CALIBRATION_PROFILE_UNITS,
    COORDINATE_CONVENTION,
    DATASET_MANIFEST_UNITS,
)
from isaac_audio_sensors.core.dataset_manifest import (
    AssetRecord,
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
    EpisodeRecord,
    ManifestPose,
    ResetMarker,
    ShardRecord,
    SourceTruth,
    SplitRecord,
)
from isaac_audio_sensors.core.io.calibration import write_calibration_profile
from isaac_audio_sensors.core.io.manifests import write_dataset_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "examples" / "manifests"
CALIBRATION_DIR = REPO_ROOT / "examples" / "calibration"


def _sha(character: str) -> str:
    return character * 64


def _creation() -> CreationProvenance:
    return CreationProvenance(
        tool_name="ias_fixture_generator",
        tool_version="1.8.0",
        isaac_sim_version="6.0.1-rc.7",
        isaac_lab_version="3.0.0",
        kit_version="108.0",
        backend_id="room_acoustics",
        estimator_id="tdoa_least_squares",
    )


def _device() -> DeviceProvenance:
    return DeviceProvenance(
        device_id="rtx4090_reference",
        device_type="simulation_host",
        platform="linux_x86_64",
        compute_device="cuda:0",
    )


def _episode(
    episode_id: str,
    *,
    scene_id: str,
    environment_id: str,
    seed: int,
    start_frame: int,
    timestamps_ms: tuple[int, ...],
) -> EpisodeRecord:
    start_timestamp = timestamps_ms[0]
    array_pose = ManifestPose(
        entity_id="xvf3800_array",
        entity_kind="array",
        timestamp_ms=start_timestamp,
        position_m=(0.0, 0.0, 1.0),
        orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
        frame="world",
    )
    source_pose = ManifestPose(
        entity_id="speaker_1",
        entity_kind="source",
        timestamp_ms=start_timestamp,
        position_m=(2.0, 0.5, 1.0),
        orientation_xyzw=None,
        frame="world",
    )
    return EpisodeRecord(
        episode_id=episode_id,
        scene_id=scene_id,
        environment_id=environment_id,
        seed=seed,
        start_step=0,
        end_step=len(timestamps_ms) - 1,
        start_frame=start_frame,
        end_frame=start_frame + len(timestamps_ms) - 1,
        timestamps_ms=timestamps_ms,
        split_group=scene_id,
        reset_markers=(
            ResetMarker(
                step_index=0,
                frame_index=start_frame,
                timestamp_ms=start_timestamp,
            ),
        ),
        array_poses=(array_pose,),
        source_truth=(
            SourceTruth(
                source_id="speaker_1",
                timestamp_ms=start_timestamp,
                class_label="Speech",
                active=True,
                pose=source_pose,
            ),
        ),
        labels=("Speech",),
    )


def _minimal_manifest() -> AudioDatasetManifest:
    episode = _episode(
        "episode_000",
        scene_id="scene_a",
        environment_id="env_0",
        seed=7,
        start_frame=0,
        timestamps_ms=(0, 20),
    )
    shard = ShardRecord(
        shard_id="shard_000",
        episode_ids=(episode.episode_id,),
        assets=(
            AssetRecord(
                asset_id="frames_000",
                path="shards/000/frames.ndjson",
                kind="frame_trace_jsonl",
                sha256=_sha("a"),
            ),
            AssetRecord(
                asset_id="audio_000",
                path="shards/000/audio.flac",
                kind="audio_flac",
                sha256=_sha("b"),
            ),
        ),
        completion_state="complete",
    )
    return AudioDatasetManifest(
        dataset_id="minimal_fixture",
        creation_timestamp_ms=0,
        creation=_creation(),
        license="CC0-1.0",
        source="Deterministic synthetic fixture",
        runtime_profile="waveform_fidelity",
        device=_device(),
        coordinate_convention=COORDINATE_CONVENTION,
        coordinate_frames=("world", "xvf3800_array"),
        time_base="simulation_time",
        sample_rate_hz=48_000,
        channel_order=("ch0", "ch1", "ch2", "ch3"),
        units=dict(DATASET_MANIFEST_UNITS),
        dtype="float32",
        episodes=(episode,),
        shards=(shard,),
        calibration_profile=None,
        configuration_sha256=_sha("c"),
        split_grouping_key="scene_id",
        splits=(SplitRecord(name="train", group_ids=("scene_a",)),),
        completion_state="complete",
    )


def _multi_manifest() -> AudioDatasetManifest:
    first = _episode(
        "episode_000",
        scene_id="scene_train",
        environment_id="env_0",
        seed=11,
        start_frame=0,
        timestamps_ms=(0, 20, 40),
    )
    second = _episode(
        "episode_001",
        scene_id="scene_validation",
        environment_id="env_1",
        seed=12,
        start_frame=3,
        timestamps_ms=(0, 20, 40),
    )
    shards = tuple(
        ShardRecord(
            shard_id=f"shard_{index:03d}",
            episode_ids=(episode.episode_id,),
            assets=(
                AssetRecord(
                    asset_id=f"frames_{index:03d}",
                    path=f"shards/{index:03d}/frames.ndjson",
                    kind="frame_trace_jsonl",
                    sha256=_sha("d" if index == 0 else "e"),
                ),
                AssetRecord(
                    asset_id=f"audio_{index:03d}",
                    path=f"shards/{index:03d}/audio.wav",
                    kind="audio_wav",
                    sha256=_sha("f" if index == 0 else "0"),
                ),
            ),
            completion_state="complete",
        )
        for index, episode in enumerate((first, second))
    )
    return AudioDatasetManifest(
        dataset_id="multi_episode_fixture",
        creation_timestamp_ms=1_000,
        creation=_creation(),
        license="CC-BY-4.0",
        source="Deterministic synthetic multi-shard fixture",
        runtime_profile="waveform_fidelity",
        device=_device(),
        coordinate_convention=COORDINATE_CONVENTION,
        coordinate_frames=("world", "xvf3800_array"),
        time_base="simulation_time",
        sample_rate_hz=48_000,
        channel_order=("ch0", "ch1", "ch2", "ch3"),
        units=dict(DATASET_MANIFEST_UNITS),
        dtype="float32",
        episodes=(first, second),
        shards=shards,
        calibration_profile=None,
        configuration_sha256=_sha("1"),
        split_grouping_key="scene_id",
        splits=(
            SplitRecord(name="train", group_ids=("scene_train",)),
            SplitRecord(name="validation", group_ids=("scene_validation",)),
        ),
        completion_state="complete",
    )


def _nominal_profile() -> AudioCalibrationProfile:
    channel_order = ("ch0", "ch1", "ch2", "ch3")
    positions = (
        (0.035, 0.0, 0.0),
        (0.0, 0.035, 0.0),
        (-0.035, 0.0, 0.0),
        (0.0, -0.035, 0.0),
    )
    nominal_zero = ScalarCalibrationValue(
        status="nominal_not_measured",
        value=0.0,
        uncertainty=None,
    )
    nominal_polarity = ScalarCalibrationValue(
        status="nominal_not_measured",
        value=1.0,
        uncertainty=None,
    )
    nominal_response = FrequencyResponse(
        status="nominal_not_measured",
        points=(
            FrequencyResponsePoint(frequency_hz=100.0, magnitude_db=0.0),
            FrequencyResponsePoint(frequency_hz=1_000.0, magnitude_db=0.0),
            FrequencyResponsePoint(frequency_hz=10_000.0, magnitude_db=0.0),
        ),
    )
    unmeasured_noise = ScalarCalibrationValue(
        status="unmeasured",
        value=None,
    )
    nominal_range = UsableFrequencyRange(
        status="nominal_not_measured",
        minimum_hz=100.0,
        maximum_hz=10_000.0,
    )
    return AudioCalibrationProfile(
        profile_id="respeaker_xvf3800_nominal",
        profile_version="v1",
        device_id="respeaker_xvf3800_fixture",
        device_model="ReSpeaker XVF3800 USB 4-Mic Array",
        array_id="xvf3800_array",
        channel_order=channel_order,
        reference_rig_bom_path="reference_rig/bom.json",
        microphone_geometry=tuple(
            MicrophoneGeometry(
                channel_id=channel_id,
                status="nominal_not_measured",
                position_m=position,
                uncertainty_m=None,
                frame="xvf3800_array",
            )
            for channel_id, position in zip(channel_order, positions, strict=True)
        ),
        array_frame="xvf3800_array",
        source_frame="speaker_reference",
        coordinate_convention=COORDINATE_CONVENTION,
        units=dict(CALIBRATION_PROFILE_UNITS),
        sample_rate_hz=48_000,
        temperature_c=ScalarCalibrationValue(
            status="nominal_not_measured",
            value=20.0,
        ),
        speed_of_sound_policy="temperature_derived",
        speed_of_sound_mps=ScalarCalibrationValue(
            status="nominal_not_measured",
            value=343.0,
        ),
        environment_description=(
            "Nominal room-temperature fixture; no physical acquisition was run."
        ),
        channels=tuple(
            ChannelCalibration(
                channel_id=channel_id,
                gain_db=nominal_zero,
                delay_s=nominal_zero,
                polarity=nominal_polarity,
                frequency_response=nominal_response,
                self_noise_db_spl=unmeasured_noise,
                usable_frequency_range=nominal_range,
            )
            for channel_id in channel_order
        ),
        source_id="nominal_reference_source",
        speaker_id="nominal_reference_speaker",
        pose_measurement_method="not measured; nominal geometry only",
        reference_signal="not acquired; nominal flat response points",
        acquisition_procedure="not run; fixture exercises the public contract",
        fitted_model_parameters=(),
        fit_metrics=(),
        holdout_metrics=(),
        applicability_limits=ApplicabilityLimits(
            temperature_min_c=None,
            temperature_max_c=None,
            frequency_min_hz=None,
            frequency_max_hz=None,
            environment_tags=("nominal_fixture",),
        ),
        uncertainty_notes="No measurement uncertainty is claimed for nominal values.",
        raw_measurements=(),
        tool_version="ias_fixture_generator/1.8.0",
        created_at="2026-01-01T00:00:00Z",
        unmeasured_fields=(
            "raw_measurements",
            "fit_metrics",
            "holdout_metrics",
            "channels.*.self_noise_db_spl",
            "microphone_geometry.*.uncertainty_m",
        ),
        evidence_status="nominal_not_measured",
    )


def main() -> int:
    paths = (
        write_dataset_manifest(
            _minimal_manifest(),
            MANIFEST_DIR / "minimal_manifest.v1.json",
        ),
        write_dataset_manifest(
            _multi_manifest(),
            MANIFEST_DIR / "multi_episode_manifest.v1.json",
        ),
        write_calibration_profile(
            _nominal_profile(),
            CALIBRATION_DIR / "respeaker_xvf3800_nominal.v1.json",
        ),
    )
    for path in paths:
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
