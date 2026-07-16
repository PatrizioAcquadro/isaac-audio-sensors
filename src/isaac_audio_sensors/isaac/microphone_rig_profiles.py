"""Import-safe microphone rig presets for the Omniverse extension.

Rig profiles describe reusable listener hardware layouts (microphone ids,
relative offsets, gains, sample rate, and a local mount pose). They are not
sound profiles: microphones do not emit audio.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from isaac_audio_sensors.core.math_utils import as_quaternion_xyzw, as_vector3
from isaac_audio_sensors.core.types import MicrophoneSpec

RIG_LAYOUT_CHOICES = ("quad_front", "quad_cross", "stereo_y", "two_mic_y", "mono")

_RIG_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class MicrophoneRigProfile:
    """Reusable microphone-rig preset applied to a USD array prim."""

    profile_id: str
    display_label: str
    layout_name: str
    microphone_ids: tuple[str, ...]
    microphone_relative_offsets_m: tuple[tuple[float, float, float], ...]
    microphone_gains_db: tuple[float, ...] = ()
    mount_local_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mount_local_orientation_quat: tuple[float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        1.0,
    )
    sample_rate_hz: int = 48_000
    recommended_mount_prim_path: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", self.profile_id.strip())
        object.__setattr__(self, "display_label", self.display_label.strip())
        object.__setattr__(self, "layout_name", self.layout_name.strip())
        object.__setattr__(
            self,
            "microphone_ids",
            tuple(str(mic_id).strip() for mic_id in self.microphone_ids),
        )
        object.__setattr__(
            self,
            "microphone_relative_offsets_m",
            tuple(
                as_vector3(offset, "microphone_relative_offsets_m")
                for offset in self.microphone_relative_offsets_m
            ),
        )
        gains = tuple(float(gain) for gain in self.microphone_gains_db)
        if not gains:
            gains = tuple(0.0 for _ in self.microphone_ids)
        object.__setattr__(self, "microphone_gains_db", gains)
        object.__setattr__(
            self,
            "mount_local_offset_m",
            as_vector3(self.mount_local_offset_m, "mount_local_offset_m"),
        )
        object.__setattr__(
            self,
            "mount_local_orientation_quat",
            as_quaternion_xyzw(
                self.mount_local_orientation_quat,
                "mount_local_orientation_quat",
            ),
        )
        object.__setattr__(self, "sample_rate_hz", int(self.sample_rate_hz))
        if self.recommended_mount_prim_path is not None:
            object.__setattr__(
                self,
                "recommended_mount_prim_path",
                self.recommended_mount_prim_path.strip() or None,
            )
        object.__setattr__(self, "description", self.description.strip())
        validate_microphone_rig_profile(self)

    def microphones(self) -> tuple[MicrophoneSpec, ...]:
        """Return core microphone specs with per-mic gains applied."""

        return tuple(
            MicrophoneSpec(
                mic_id=mic_id,
                relative_position_m=offset,
                gain_db=gain_db,
            )
            for mic_id, offset, gain_db in zip(
                self.microphone_ids,
                self.microphone_relative_offsets_m,
                self.microphone_gains_db,
                strict=True,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic config/export representation."""

        payload = asdict(self)
        payload["microphone_ids"] = list(self.microphone_ids)
        payload["microphone_relative_offsets_m"] = [
            list(offset) for offset in self.microphone_relative_offsets_m
        ]
        payload["microphone_gains_db"] = list(self.microphone_gains_db)
        payload["mount_local_offset_m"] = list(self.mount_local_offset_m)
        payload["mount_local_orientation_quat"] = list(
            self.mount_local_orientation_quat
        )
        return {key: payload[key] for key in sorted(payload)}


def validate_microphone_rig_profile(profile: MicrophoneRigProfile) -> None:
    """Validate one rig profile and raise ``ValueError`` with a clear reason."""

    _require_rig_text(profile.profile_id, "profile_id")
    if not _RIG_PROFILE_ID_RE.fullmatch(profile.profile_id):
        raise ValueError(
            "profile_id must be a stable lowercase slug using letters, digits, "
            "hyphen, or underscore."
        )
    _require_rig_text(profile.display_label, "display_label")
    if profile.layout_name not in RIG_LAYOUT_CHOICES:
        raise ValueError(
            f"layout_name must be one of {', '.join(RIG_LAYOUT_CHOICES)}."
        )
    if not profile.microphone_ids:
        raise ValueError("microphone_ids must include at least one microphone.")
    for mic_id in profile.microphone_ids:
        _require_rig_text(mic_id, "microphone_id")
    if len(set(profile.microphone_ids)) != len(profile.microphone_ids):
        raise ValueError("microphone_ids must be unique.")
    if len(profile.microphone_relative_offsets_m) != len(profile.microphone_ids):
        raise ValueError(
            "microphone_relative_offsets_m must match microphone_ids length."
        )
    if len(profile.microphone_gains_db) != len(profile.microphone_ids):
        raise ValueError("microphone_gains_db must match microphone_ids length.")
    for gain_db in profile.microphone_gains_db:
        if not math.isfinite(float(gain_db)):
            raise ValueError("microphone_gains_db must contain only finite values.")
    if int(profile.sample_rate_hz) <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    if profile.recommended_mount_prim_path is not None and not str(
        profile.recommended_mount_prim_path
    ).startswith("/"):
        raise ValueError(
            "recommended_mount_prim_path must be an absolute USD prim path."
        )


def validate_microphone_rig_profile_library(
    profiles: Iterable[MicrophoneRigProfile],
) -> tuple[MicrophoneRigProfile, ...]:
    """Validate rig library uniqueness and return profiles sorted by id."""

    by_id: dict[str, MicrophoneRigProfile] = {}
    for profile in profiles:
        validate_microphone_rig_profile(profile)
        if profile.profile_id in by_id:
            raise ValueError(f"Duplicate rig profile id {profile.profile_id!r}.")
        by_id[profile.profile_id] = profile
    if not by_id:
        raise ValueError("Microphone rig profile library must not be empty.")
    return tuple(by_id[key] for key in sorted(by_id))


def microphone_rig_profile_from_mapping(
    value: Mapping[str, Any],
) -> MicrophoneRigProfile:
    """Load one rig profile from config JSON."""

    if not isinstance(value, Mapping):
        raise ValueError("microphone rig profile entries must be objects.")
    raw_path = value.get("recommended_mount_prim_path")
    return MicrophoneRigProfile(
        profile_id=str(value.get("profile_id", "")),
        display_label=str(value.get("display_label", "")),
        layout_name=str(value.get("layout_name", "")),
        microphone_ids=tuple(
            str(mic_id) for mic_id in value.get("microphone_ids", ())
        ),
        microphone_relative_offsets_m=tuple(
            tuple(float(component) for component in offset)
            for offset in value.get("microphone_relative_offsets_m", ())
        ),
        microphone_gains_db=tuple(
            float(gain) for gain in value.get("microphone_gains_db", ())
        ),
        mount_local_offset_m=tuple(
            float(component)
            for component in value.get("mount_local_offset_m", (0.0, 0.0, 0.0))
        ),
        mount_local_orientation_quat=tuple(
            float(component)
            for component in value.get(
                "mount_local_orientation_quat",
                (0.0, 0.0, 0.0, 1.0),
            )
        ),
        sample_rate_hz=int(value.get("sample_rate_hz", 48_000)),
        recommended_mount_prim_path=(
            None if raw_path is None else str(raw_path).strip() or None
        ),
        description=str(value.get("description", "")),
    )


def default_microphone_rig_profiles() -> tuple[MicrophoneRigProfile, ...]:
    """Return the deterministic built-in microphone rig library."""

    return (
        MicrophoneRigProfile(
            profile_id="alex_head_quad",
            display_label="Alex Head / Quad",
            layout_name="quad_cross",
            microphone_ids=("front", "right", "rear", "left"),
            microphone_relative_offsets_m=(
                (0.06, 0.0, 0.0),
                (0.0, 0.06, 0.0),
                (-0.06, 0.0, 0.0),
                (0.0, -0.06, 0.0),
            ),
            microphone_gains_db=(0.0, 0.0, 0.0, 0.0),
            mount_local_offset_m=(0.0, 0.0, 0.12),
            sample_rate_hz=48_000,
            recommended_mount_prim_path=(
                "/World/Alex/PELVIS_LINK/TORSO_LINK/NECK_Z_LINK/HEAD_LINK"
            ),
            description="Four-mic cross rig mounted above the Alex V2 head link.",
        ),
        MicrophoneRigProfile(
            profile_id="alex_chest_stereo",
            display_label="Alex Chest / Stereo",
            layout_name="stereo_y",
            microphone_ids=("left", "right"),
            microphone_relative_offsets_m=(
                (0.0, -0.09, 0.0),
                (0.0, 0.09, 0.0),
            ),
            microphone_gains_db=(0.0, 0.0),
            mount_local_offset_m=(0.05, 0.0, 0.05),
            sample_rate_hz=48_000,
            recommended_mount_prim_path="/World/Alex/PELVIS_LINK/TORSO_LINK",
            description="Wide stereo pair mounted forward of the Alex V2 torso link.",
        ),
        MicrophoneRigProfile(
            profile_id="unitree_head_stereo",
            display_label="Unitree Head / Stereo",
            layout_name="stereo_y",
            microphone_ids=("left", "right"),
            microphone_relative_offsets_m=(
                (0.0, -0.04, 0.0),
                (0.0, 0.04, 0.0),
            ),
            microphone_gains_db=(0.0, 0.0),
            mount_local_offset_m=(0.25, 0.0, 0.05),
            sample_rate_hz=48_000,
            recommended_mount_prim_path="/World/Unitree/head_link",
            description="Compact stereo pair mounted toward a Unitree head link.",
        ),
        MicrophoneRigProfile(
            profile_id="unitree_base_quad",
            display_label="Unitree Base / Quad",
            layout_name="quad_cross",
            microphone_ids=("front", "right", "rear", "left"),
            microphone_relative_offsets_m=(
                (0.10, 0.0, 0.0),
                (0.0, 0.10, 0.0),
                (-0.10, 0.0, 0.0),
                (0.0, -0.10, 0.0),
            ),
            microphone_gains_db=(0.0, 0.0, 0.0, 0.0),
            mount_local_offset_m=(0.0, 0.0, 0.08),
            sample_rate_hz=48_000,
            recommended_mount_prim_path="/World/Unitree/base_link",
            description="Four-mic cross rig mounted above a Unitree body/base link.",
        ),
    )


def _require_rig_text(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field_name} must be non-empty.")
