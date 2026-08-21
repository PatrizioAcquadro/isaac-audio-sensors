"""Import-safe object sound-profile presets for the Omniverse extension."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

SUPPORTED_GENERATED_AUDIO_ASSETS = ("generated://impulse", "generated://pulse")

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SLUG_COMPONENT_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SoundProfile:
    """Reusable metadata preset applied to a USD sound source prim."""

    profile_id: str
    display_label: str
    object_label_aliases: tuple[str, ...]
    class_label: str
    audio_asset_path: str
    start_time_s: float
    duration_s: float
    gain_db: float
    directivity: str = "omni"
    source_id: str | None = None
    source_id_template: str | None = "{object_slug}_source"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", self.profile_id.strip())
        object.__setattr__(self, "display_label", self.display_label.strip())
        object.__setattr__(self, "class_label", self.class_label.strip())
        object.__setattr__(self, "audio_asset_path", self.audio_asset_path.strip())
        object.__setattr__(self, "directivity", self.directivity.strip())
        object.__setattr__(
            self,
            "object_label_aliases",
            tuple(
                alias.strip() for alias in self.object_label_aliases if alias.strip()
            ),
        )
        if self.source_id is not None:
            object.__setattr__(self, "source_id", self.source_id.strip() or None)
        if self.source_id_template is not None:
            object.__setattr__(
                self,
                "source_id_template",
                self.source_id_template.strip() or None,
            )
        validate_sound_profile(self)

    def source_id_for(
        self,
        *,
        object_label: str,
        current_source_id: str,
        source_prim_path: str,
    ) -> str:
        """Return the concrete source id to author for this profile."""

        if self.source_id:
            return self.source_id
        template = self.source_id_template or "{current_source_id}"
        object_slug = object_label_slug(object_label) or "object"
        current_slug = object_label_slug(current_source_id) or object_slug
        source_name = object_label_slug(source_prim_path.rsplit("/", 1)[-1])
        source_id = template.format(
            profile_id=self.profile_id,
            object_label=object_label.strip() or object_slug,
            object_slug=object_slug,
            current_source_id=current_slug,
            source_name=source_name or current_slug,
        )
        return object_label_slug(source_id) or f"{self.profile_id}_source"

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic config/export representation."""

        payload = asdict(self)
        payload["object_label_aliases"] = list(self.object_label_aliases)
        return {key: payload[key] for key in sorted(payload)}


def validate_sound_profile(profile: SoundProfile) -> None:
    """Validate a profile and raise ``ValueError`` with a user-readable reason."""

    _require_profile_text(profile.profile_id, "profile_id")
    if not _PROFILE_ID_RE.fullmatch(profile.profile_id):
        raise ValueError(
            "profile_id must be a stable lowercase slug using letters, digits, "
            "hyphen, or underscore."
        )
    _require_profile_text(profile.display_label, "display_label")
    if not profile.object_label_aliases:
        raise ValueError("object_label_aliases must include at least one alias.")
    for alias in profile.object_label_aliases:
        _require_profile_text(alias, "object_label_alias")
    _require_profile_text(profile.class_label, "class_label")
    _require_profile_text(profile.audio_asset_path, "audio_asset_path")
    _require_profile_text(profile.directivity, "directivity")
    if profile.source_id is None and profile.source_id_template is None:
        raise ValueError("source_id or source_id_template must be configured.")
    if profile.audio_asset_path not in SUPPORTED_GENERATED_AUDIO_ASSETS:
        raise ValueError(
            "audio_asset_path must be one of "
            f"{', '.join(SUPPORTED_GENERATED_AUDIO_ASSETS)} for GUI profiles."
        )
    for field_name, value in (
        ("start_time_s", profile.start_time_s),
        ("duration_s", profile.duration_s),
        ("gain_db", profile.gain_db),
    ):
        if not math.isfinite(float(value)):
            raise ValueError(f"{field_name} must be finite.")
    if float(profile.duration_s) <= 0.0:
        raise ValueError("duration_s must be positive.")


def default_sound_profiles() -> tuple[SoundProfile, ...]:
    """Return the deterministic built-in object profile library."""

    return (
        SoundProfile(
            profile_id="speech_generic",
            display_label="Speech / Generic",
            object_label_aliases=("speech", "speaker", "voice", "person", "source"),
            source_id_template="{current_source_id}",
            class_label="Speech",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
            directivity="omni",
        ),
        SoundProfile(
            profile_id="oven_stove",
            display_label="Appliance / Oven / Stove",
            object_label_aliases=(
                "oven",
                "stove",
                "cooktop",
                "range",
                "microwave",
                "microwaveoven",
                "fridge",
                "refrigerator",
            ),
            source_id_template="{object_slug}_source",
            class_label="Appliance",
            audio_asset_path="generated://pulse",
            start_time_s=0.0,
            duration_s=1.5,
            gain_db=-3.0,
            directivity="omni",
        ),
        SoundProfile(
            profile_id="sink_water",
            display_label="Sink / Water",
            object_label_aliases=("sink", "faucet", "water", "basin"),
            source_id_template="{object_slug}_source",
            class_label="Water",
            audio_asset_path="generated://pulse",
            start_time_s=0.0,
            duration_s=1.2,
            gain_db=-2.0,
            directivity="omni",
        ),
        SoundProfile(
            profile_id="door_knock",
            display_label="Door / Knock",
            object_label_aliases=("door", "knock", "cabinetdoor", "alarm"),
            source_id_template="{object_slug}_source",
            class_label="Door",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=0.6,
            gain_db=-1.0,
            directivity="omni",
        ),
        SoundProfile(
            profile_id="footsteps_movement",
            display_label="Footsteps / Movement",
            object_label_aliases=(
                "footstep",
                "footsteps",
                "movement",
                "movingobject",
                "walker",
                "robot",
            ),
            source_id_template="{object_slug}_source",
            class_label="Footsteps",
            audio_asset_path="generated://pulse",
            start_time_s=0.0,
            duration_s=0.8,
            gain_db=-4.0,
            directivity="omni",
        ),
    )


def default_object_profile_mappings(
    profiles: Iterable[SoundProfile] | None = None,
) -> dict[str, str]:
    """Return alias-to-profile mappings used by auto-match."""

    mapping: dict[str, str] = {}
    for profile in profiles or default_sound_profiles():
        for alias in profile.object_label_aliases:
            normalized = normalize_object_label(alias)
            if normalized:
                mapping[normalized] = profile.profile_id
    return dict(sorted(mapping.items()))


def sound_profile_from_mapping(value: Mapping[str, Any]) -> SoundProfile:
    """Load one profile from config JSON."""

    if not isinstance(value, Mapping):
        raise ValueError("sound profile entries must be objects.")
    return SoundProfile(
        profile_id=str(value.get("profile_id", "")),
        display_label=str(value.get("display_label", "")),
        object_label_aliases=tuple(
            str(alias) for alias in value.get("object_label_aliases", ())
        ),
        source_id=(
            None
            if value.get("source_id") is None
            else str(value.get("source_id", "")).strip() or None
        ),
        source_id_template=(
            None
            if value.get("source_id_template") is None
            else str(value.get("source_id_template", "")).strip() or None
        ),
        class_label=str(value.get("class_label", "")),
        audio_asset_path=str(value.get("audio_asset_path", "")),
        start_time_s=float(value.get("start_time_s", 0.0)),
        duration_s=float(value.get("duration_s", 0.0)),
        gain_db=float(value.get("gain_db", 0.0)),
        directivity=str(value.get("directivity", "")),
    )


def validate_sound_profile_library(
    profiles: Iterable[SoundProfile],
) -> tuple[SoundProfile, ...]:
    """Validate library uniqueness and return profiles sorted by id."""

    by_id: dict[str, SoundProfile] = {}
    for profile in profiles:
        validate_sound_profile(profile)
        if profile.profile_id in by_id:
            raise ValueError(f"Duplicate sound profile id {profile.profile_id!r}.")
        by_id[profile.profile_id] = profile
    if not by_id:
        raise ValueError("Sound profile library must not be empty.")
    return tuple(by_id[key] for key in sorted(by_id))


def match_sound_profile_id(
    *,
    labels: Iterable[str],
    profiles: Iterable[SoundProfile],
    object_profile_mappings: Mapping[str, str],
) -> str | None:
    """Return the first matching profile id from object labels and aliases."""

    profile_by_id = {profile.profile_id: profile for profile in profiles}
    normalized_labels = tuple(
        label for label in (normalize_object_label(item) for item in labels) if label
    )
    label_tokens = tuple(
        token for normalized in normalized_labels for token in _label_tokens(normalized)
    )
    for candidate in (*normalized_labels, *label_tokens):
        profile_id = object_profile_mappings.get(candidate)
        if profile_id in profile_by_id:
            return profile_id
    for profile in profiles:
        aliases = tuple(
            normalize_object_label(alias) for alias in profile.object_label_aliases
        )
        if any(
            alias
            and (
                alias in normalized_labels
                or alias in label_tokens
                or any(alias in label for label in normalized_labels)
            )
            for alias in aliases
        ):
            return profile.profile_id
    return None


def normalize_object_label(label: str) -> str:
    """Normalize object labels for alias matching and config keys."""

    return "_".join(_SLUG_COMPONENT_RE.findall(str(label).lower()))


def object_label_slug(label: str) -> str:
    """Return a filesystem/metadata-safe object slug."""

    return normalize_object_label(label).strip("_")


def _label_tokens(normalized_label: str) -> tuple[str, ...]:
    return tuple(token for token in normalized_label.split("_") if token)


def _require_profile_text(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field_name} must be non-empty.")
