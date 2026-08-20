"""Pure Python core for Isaac audio sensor simulation."""

from __future__ import annotations

from isaac_audio_sensors.core.backends.base import AudioSimulationBackend, get_backend
from isaac_audio_sensors.core.backends.geometry import GeometryBackend
from isaac_audio_sensors.core.backends.room_acoustics import RoomAcousticsBackend
from isaac_audio_sensors.core.backends.tdoa import TdoaSyntheticBackend
from isaac_audio_sensors.core.calibration_profile import (
    AudioCalibrationProfile,
    check_profile_compatibility,
)
from isaac_audio_sensors.core.capabilities import (
    CapabilityReport,
    CapabilityStatus,
    discover_capabilities,
)
from isaac_audio_sensors.core.config import (
    AudioSensorConfig,
    build_scene_snapshot,
    load_audio_config,
    validate_audio_config,
)
from isaac_audio_sensors.core.fidelity import (
    ACOUSTIC_FIDELITY_LADDER,
    AcousticFidelityLevel,
    AcousticFidelityMetadata,
    fidelity_level_for_backend,
)
from isaac_audio_sensors.core.microphone_array import (
    create_microphone_array,
    microphone_world_positions,
)
from isaac_audio_sensors.core.packs import (
    PackActivationError,
    PackError,
    PackValidationError,
    activate_pack,
    discover_pack_installs,
    validate_pack_install,
)
from isaac_audio_sensors.core.plugins import (
    AudioFeatureExtractor,
    DoaEstimator,
    GccPhatLeastSquaresEstimator,
    PluginAvailability,
    PluginDeclaration,
    PluginRegistry,
    PropagationBackend,
    SrpPhatEstimator,
    get_default_registry,
    validate_declaration,
)
from isaac_audio_sensors.core.schema import (
    audio_calibration_profile_json_schema,
    audio_dataset_manifest_json_schema,
    audio_sensor_frame_json_schema,
    write_audio_calibration_profile_json_schema,
    write_audio_dataset_manifest_json_schema,
    write_audio_sensor_frame_json_schema,
)
from isaac_audio_sensors.core.types import (
    AudioDetection,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioSourceSpec,
    AudioTimeWindow,
    DoaEstimate,
    MicrophoneArraySpec,
    MicrophoneSpec,
    Pose3D,
    RoomAcousticsSpec,
    SourceOcclusion,
)
from isaac_audio_sensors.recording.manifest import AudioDatasetManifest

__all__ = [
    "AudioDetection",
    "AudioCalibrationProfile",
    "AudioDatasetManifest",
    "AudioSceneSnapshot",
    "AudioSensorConfig",
    "AudioSensorFrame",
    "AudioSimulationBackend",
    "AudioFeatureExtractor",
    "AudioSourceSpec",
    "AudioTimeWindow",
    "ACOUSTIC_FIDELITY_LADDER",
    "AcousticFidelityLevel",
    "AcousticFidelityMetadata",
    "CapabilityReport",
    "CapabilityStatus",
    "DoaEstimate",
    "DoaEstimator",
    "GccPhatLeastSquaresEstimator",
    "GeometryBackend",
    "MicrophoneArraySpec",
    "MicrophoneSpec",
    "Pose3D",
    "PluginAvailability",
    "PluginDeclaration",
    "PluginRegistry",
    "PackActivationError",
    "PackError",
    "PackValidationError",
    "PropagationBackend",
    "RoomAcousticsBackend",
    "RoomAcousticsSpec",
    "SourceOcclusion",
    "SrpPhatEstimator",
    "TdoaSyntheticBackend",
    "audio_sensor_frame_json_schema",
    "audio_calibration_profile_json_schema",
    "audio_dataset_manifest_json_schema",
    "activate_pack",
    "build_scene_snapshot",
    "check_profile_compatibility",
    "create_microphone_array",
    "discover_capabilities",
    "discover_pack_installs",
    "fidelity_level_for_backend",
    "get_backend",
    "get_default_registry",
    "load_audio_config",
    "microphone_world_positions",
    "validate_audio_config",
    "validate_pack_install",
    "validate_declaration",
    "write_audio_sensor_frame_json_schema",
    "write_audio_calibration_profile_json_schema",
    "write_audio_dataset_manifest_json_schema",
]
