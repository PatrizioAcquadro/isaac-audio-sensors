"""Scene, source, microphone-array, and time-window contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from isaac_audio_sensors.core.constants import (
    COORDINATE_CONVENTION,
    DEFAULT_SAMPLE_RATE_HZ,
)
from isaac_audio_sensors.core.directivity import (
    DirectivityPattern,
    DirectivityValidationError,
    resolve_directivity_pattern,
)
from isaac_audio_sensors.core.gain import db_to_amplitude_gain
from isaac_audio_sensors.core.math_utils import (
    Quaternion,
    Vector3,
    as_quaternion_xyzw,
    as_vector3,
)
from isaac_audio_sensors.core.types._validation import (
    require_coordinate_convention,
    require_finite,
    require_non_empty,
    require_unique_ids,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Pose3D:
    """World-frame pose used by the public audio sensor frame schema."""

    position_m: Vector3
    orientation_xyzw: Quaternion | None = None
    frame: str = "world"
    coordinate_convention: str = COORDINATE_CONVENTION

    def __post_init__(self) -> None:
        require_non_empty(self.frame, "Pose3D.frame")
        require_coordinate_convention(
            self.coordinate_convention,
            "Pose3D.coordinate_convention",
        )
        object.__setattr__(
            self,
            "position_m",
            as_vector3(self.position_m, "Pose3D.position_m"),
        )
        if self.orientation_xyzw is not None:
            object.__setattr__(
                self,
                "orientation_xyzw",
                as_quaternion_xyzw(
                    self.orientation_xyzw,
                    "Pose3D.orientation_xyzw",
                ),
            )

    @classmethod
    def from_array(cls, array: MicrophoneArraySpec) -> Pose3D:
        """Build an array pose from a microphone array spec."""

        return cls(
            position_m=array.position_world,
            orientation_xyzw=array.orientation_world_quat,
            coordinate_convention=array.coordinate_convention,
        )

    @classmethod
    def from_source(cls, source: AudioSourceSpec) -> Pose3D:
        """Build a source pose from a source spec."""

        return cls(
            position_m=source.position_world,
            orientation_xyzw=source.orientation_world_quat,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioSourceSpec:
    """Known sound source in a scene snapshot."""

    source_id: str
    prim_path: str
    class_label: str
    audio_asset_path: str | None
    position_world: Vector3
    orientation_world_quat: Quaternion | None
    start_time_s: float
    duration_s: float | None
    gain_db: float
    loop_count: int = 0
    directivity: DirectivityPattern = DirectivityPattern.OMNI
    velocity_world_mps: Vector3 | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.source_id, "AudioSourceSpec.source_id")
        require_non_empty(self.prim_path, "AudioSourceSpec.prim_path")
        require_non_empty(self.class_label, "AudioSourceSpec.class_label")
        directivity = resolve_directivity_pattern(
            self.directivity,
            "AudioSourceSpec.directivity",
        )
        object.__setattr__(self, "directivity", directivity)
        object.__setattr__(
            self,
            "position_world",
            as_vector3(self.position_world, "AudioSourceSpec.position_world"),
        )
        if self.velocity_world_mps is not None:
            object.__setattr__(
                self,
                "velocity_world_mps",
                as_vector3(
                    self.velocity_world_mps,
                    "AudioSourceSpec.velocity_world_mps",
                ),
            )
        if self.orientation_world_quat is not None:
            object.__setattr__(
                self,
                "orientation_world_quat",
                as_quaternion_xyzw(
                    self.orientation_world_quat,
                    "AudioSourceSpec.orientation_world_quat",
                ),
            )
        require_finite(self.start_time_s, "AudioSourceSpec.start_time_s")
        db_to_amplitude_gain(self.gain_db, "AudioSourceSpec.gain_db")
        object.__setattr__(self, "gain_db", float(self.gain_db))
        if (
            directivity is not DirectivityPattern.OMNI
            and self.orientation_world_quat is None
        ):
            raise DirectivityValidationError(
                "AudioSourceSpec.orientation_world_quat is required for "
                f"non-omni directivity {directivity.value!r}."
            )
        if type(self.loop_count) is not int or self.loop_count < -1:
            raise ValueError(
                "AudioSourceSpec.loop_count must be -1 or a non-negative integer."
            )
        if self.duration_s is not None:
            require_finite(self.duration_s, "AudioSourceSpec.duration_s")
            if self.duration_s <= 0.0:
                raise ValueError("AudioSourceSpec.duration_s must be positive.")

    def is_active_in(self, start_time_s: float, end_time_s: float) -> bool:
        """Return whether the source overlaps a half-open time window."""

        source_end = (
            math.inf if self.duration_s is None else self.start_time_s + self.duration_s
        )
        return self.start_time_s < end_time_s and source_end > start_time_s


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneSpec:
    """One microphone in an array-local frame."""

    mic_id: str
    relative_position_m: Vector3
    relative_orientation_quat: Quaternion | None = None
    gain_db: float = 0.0
    self_noise_db: float | None = None
    directivity: DirectivityPattern = DirectivityPattern.OMNI

    def __post_init__(self) -> None:
        require_non_empty(self.mic_id, "MicrophoneSpec.mic_id")
        object.__setattr__(
            self,
            "relative_position_m",
            as_vector3(
                self.relative_position_m,
                "MicrophoneSpec.relative_position_m",
            ),
        )
        if self.relative_orientation_quat is not None:
            object.__setattr__(
                self,
                "relative_orientation_quat",
                as_quaternion_xyzw(
                    self.relative_orientation_quat,
                    "MicrophoneSpec.relative_orientation_quat",
                ),
            )
        directivity = resolve_directivity_pattern(
            self.directivity,
            "MicrophoneSpec.directivity",
        )
        object.__setattr__(self, "directivity", directivity)
        db_to_amplitude_gain(self.gain_db, "MicrophoneSpec.gain_db")
        object.__setattr__(self, "gain_db", float(self.gain_db))
        if (
            directivity is not DirectivityPattern.OMNI
            and self.relative_orientation_quat is None
        ):
            raise DirectivityValidationError(
                "MicrophoneSpec.relative_orientation_quat is required for "
                f"non-omni directivity {directivity.value!r}."
            )
        if self.self_noise_db is not None:
            require_finite(self.self_noise_db, "MicrophoneSpec.self_noise_db")


@dataclass(frozen=True, slots=True, kw_only=True)
class MicrophoneArraySpec:
    """Microphone array pose and layout in the public core convention."""

    array_id: str
    prim_path: str
    position_world: Vector3
    orientation_world_quat: Quaternion
    microphones: tuple[MicrophoneSpec, ...]
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    coordinate_convention: str = COORDINATE_CONVENTION
    velocity_world_mps: Vector3 | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.array_id, "MicrophoneArraySpec.array_id")
        require_non_empty(self.prim_path, "MicrophoneArraySpec.prim_path")
        require_coordinate_convention(
            self.coordinate_convention,
            "MicrophoneArraySpec.coordinate_convention",
        )
        object.__setattr__(
            self,
            "position_world",
            as_vector3(self.position_world, "MicrophoneArraySpec.position_world"),
        )
        object.__setattr__(
            self,
            "orientation_world_quat",
            as_quaternion_xyzw(
                self.orientation_world_quat,
                "MicrophoneArraySpec.orientation_world_quat",
            ),
        )
        if self.velocity_world_mps is not None:
            object.__setattr__(
                self,
                "velocity_world_mps",
                as_vector3(
                    self.velocity_world_mps,
                    "MicrophoneArraySpec.velocity_world_mps",
                ),
            )
        microphones = tuple(self.microphones)
        if not microphones:
            raise ValueError("MicrophoneArraySpec.microphones must not be empty.")
        require_unique_ids(
            [microphone.mic_id for microphone in microphones],
            "microphone id",
        )
        object.__setattr__(self, "microphones", microphones)
        if type(self.sample_rate_hz) is not int or self.sample_rate_hz <= 0:
            raise ValueError(
                "MicrophoneArraySpec.sample_rate_hz must be a positive integer."
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioTimeWindow:
    """Half-open simulation window ``[start_time_s, end_time_s)``."""

    start_time_s: float
    end_time_s: float
    frame_index: int

    def __post_init__(self) -> None:
        require_finite(self.start_time_s, "AudioTimeWindow.start_time_s")
        require_finite(self.end_time_s, "AudioTimeWindow.end_time_s")
        if self.end_time_s <= self.start_time_s:
            raise ValueError("AudioTimeWindow end must be after start.")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError(
                "AudioTimeWindow.frame_index must be a non-negative integer."
            )
