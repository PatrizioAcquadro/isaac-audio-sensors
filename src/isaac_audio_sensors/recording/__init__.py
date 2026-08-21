"""Public recording and dataset contracts."""

from isaac_audio_sensors.recording._records import DatasetLayoutError
from isaac_audio_sensors.recording.flac import export_session_flac
from isaac_audio_sensors.recording.loader import LoadedFrame, SessionDataset
from isaac_audio_sensors.recording.manifest import (
    AudioDatasetManifest,
    CreationProvenance,
    DeviceProvenance,
)
from isaac_audio_sensors.recording.recorder import (
    AppendFrameResult,
    SessionRecorder,
    SessionRecorderError,
)
from isaac_audio_sensors.recording.replay import ReplayEvent, replay_session
from isaac_audio_sensors.recording.serialization import (
    manifest_from_dict,
    manifest_to_dict,
    read_dataset_manifest,
    write_dataset_manifest,
)
from isaac_audio_sensors.recording.splits import (
    DatasetSplitError,
    SplitPlan,
    apply_split_plan,
    build_split_plan,
    read_split_plan,
    write_split_plan,
)
from isaac_audio_sensors.recording.statistics import Statistics
from isaac_audio_sensors.recording.validate import (
    Finding,
    ValidationReport,
    validate_dataset,
)

__all__ = [
    "AppendFrameResult",
    "AudioDatasetManifest",
    "CreationProvenance",
    "DatasetLayoutError",
    "DatasetSplitError",
    "DeviceProvenance",
    "Finding",
    "LoadedFrame",
    "ReplayEvent",
    "SessionDataset",
    "SessionRecorder",
    "SessionRecorderError",
    "SplitPlan",
    "Statistics",
    "ValidationReport",
    "apply_split_plan",
    "build_split_plan",
    "export_session_flac",
    "manifest_from_dict",
    "manifest_to_dict",
    "read_dataset_manifest",
    "read_split_plan",
    "replay_session",
    "validate_dataset",
    "write_dataset_manifest",
    "write_split_plan",
]
