from __future__ import annotations

import pytest

from isaac_audio_sensors.core.directivity import DirectivityPattern
from isaac_audio_sensors.core.types import MicrophoneSpec
from isaac_audio_sensors.kit.microphone_rig_profiles import (
    RIG_LAYOUT_CHOICES,
    MicrophoneRigProfile,
    default_microphone_rig_profiles,
    microphone_rig_profile_from_mapping,
    validate_microphone_rig_profile_library,
)
from isaac_audio_sensors.kit.sound_profiles import (
    SoundProfile,
    default_object_profile_mappings,
    default_sound_profiles,
)


def test_sound_profiles_validate_default_library_and_safe_assets():
    profiles = default_sound_profiles()
    profile_ids = tuple(profile.profile_id for profile in profiles)

    assert profile_ids == (
        "speech_generic",
        "oven_stove",
        "sink_water",
        "door_knock",
        "footsteps_movement",
    )
    assert len(set(profile_ids)) == len(profile_ids)
    assert {profile.audio_asset_path for profile in profiles} <= {
        "generated://impulse",
        "generated://pulse",
    }
    assert {profile.loop_count for profile in profiles} == {0}
    assert default_object_profile_mappings(profiles)["oven"] == "oven_stove"
    assert default_object_profile_mappings(profiles)["sink"] == "sink_water"

    with pytest.raises(ValueError, match="audio_asset_path"):
        SoundProfile(
            profile_id="unsafe",
            display_label="Unsafe",
            object_label_aliases=("unsafe",),
            source_id_template="{object_slug}_source",
            class_label="Unsafe",
            audio_asset_path="/tmp/private.wav",
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
        )

    with pytest.raises(ValueError, match="duration_s"):
        SoundProfile(
            profile_id="bad_duration",
            display_label="Bad Duration",
            object_label_aliases=("bad",),
            source_id_template="{object_slug}_source",
            class_label="Bad",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=0.0,
            gain_db=0.0,
        )

    with pytest.raises(ValueError, match="loop_count"):
        SoundProfile(
            profile_id="bad_loop",
            display_label="Bad Loop",
            object_label_aliases=("bad",),
            source_id_template="{object_slug}_source",
            class_label="Bad",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
            loop_count=-2,
        )

    with pytest.raises(ValueError, match="directivity"):
        SoundProfile(
            profile_id="bad_directivity",
            display_label="Bad Directivity",
            object_label_aliases=("bad",),
            source_id_template="{object_slug}_source",
            class_label="Bad",
            audio_asset_path="generated://impulse",
            start_time_s=0.0,
            duration_s=1.0,
            gain_db=0.0,
            directivity="unknown",
        )


def test_sound_profiles_store_the_canonical_directivity_enum() -> None:
    profile = SoundProfile(
        profile_id="directional",
        display_label="Directional",
        object_label_aliases=("speaker",),
        source_id_template="{object_slug}_source",
        class_label="Speech",
        audio_asset_path="generated://impulse",
        start_time_s=0.0,
        duration_s=1.0,
        gain_db=0.0,
        directivity="supercardioid",
    )

    assert profile.directivity is DirectivityPattern.SUPERCARDIOID
    assert profile.to_dict()["directivity"] == "supercardioid"


def test_default_rig_library_contains_named_presets_with_valid_geometry():
    profiles = default_microphone_rig_profiles()

    assert [profile.profile_id for profile in profiles] == [
        "quad_cross_120mm",
        "stereo_y_100mm",
    ]
    assert [len(profile.microphone_ids) for profile in profiles] == [4, 2]
    for profile in profiles:
        assert profile.layout_name in RIG_LAYOUT_CHOICES
        assert len(profile.microphone_relative_offsets_m) == len(profile.microphone_ids)
        assert len(profile.microphone_gains_db) == len(profile.microphone_ids)
        assert profile.sample_rate_hz == 48_000
        assert profile.mount_local_offset_m == (0.0, 0.0, 0.0)
        assert profile.recommended_mount_prim_path is None

    validated = validate_microphone_rig_profile_library(profiles)
    assert {profile.profile_id for profile in validated} == {
        profile.profile_id for profile in profiles
    }
    by_id = {profile.profile_id: profile for profile in profiles}
    assert by_id["quad_cross_120mm"].microphone_relative_offsets_m[0] == (
        0.06,
        0.0,
        0.0,
    )
    assert by_id["stereo_y_100mm"].microphone_relative_offsets_m == (
        (0.0, -0.05, 0.0),
        (0.0, 0.05, 0.0),
    )


def test_rig_profile_to_dict_round_trips_through_mapping_loader():
    for profile in default_microphone_rig_profiles():
        payload = profile.to_dict()
        assert payload["microphone_ids"] == list(profile.microphone_ids)
        assert payload["mount_local_offset_m"] == list(profile.mount_local_offset_m)
        restored = microphone_rig_profile_from_mapping(payload)
        assert restored == profile


def test_rig_profile_microphones_carry_per_mic_gains():
    profile = MicrophoneRigProfile(
        profile_id="custom_stereo",
        display_label="Custom Stereo",
        layout_name="stereo_y",
        microphone_ids=("left", "right"),
        microphone_relative_offsets_m=((0.0, -0.05, 0.0), (0.0, 0.05, 0.0)),
        microphone_gains_db=(-1.0, 2.5),
    )

    microphones = profile.microphones()
    assert all(isinstance(mic, MicrophoneSpec) for mic in microphones)
    assert [mic.mic_id for mic in microphones] == ["left", "right"]
    assert [mic.gain_db for mic in microphones] == [-1.0, 2.5]
    assert microphones[0].relative_position_m == (0.0, -0.05, 0.0)


def test_rig_profile_defaults_gains_to_zero_when_omitted():
    profile = MicrophoneRigProfile(
        profile_id="quad_default_gain",
        display_label="Quad Default Gain",
        layout_name="quad_cross",
        microphone_ids=("front", "right", "rear", "left"),
        microphone_relative_offsets_m=(
            (0.08, 0.0, 0.0),
            (0.0, 0.08, 0.0),
            (-0.08, 0.0, 0.0),
            (0.0, -0.08, 0.0),
        ),
    )

    assert profile.microphone_gains_db == (0.0, 0.0, 0.0, 0.0)


def test_rig_profile_validation_rejects_bad_inputs():
    base = dict(
        profile_id="ok_rig",
        display_label="OK Rig",
        layout_name="stereo_y",
        microphone_ids=("left", "right"),
        microphone_relative_offsets_m=((0.0, -0.05, 0.0), (0.0, 0.05, 0.0)),
    )

    with pytest.raises(ValueError, match="lowercase slug"):
        MicrophoneRigProfile(**{**base, "profile_id": "Bad Rig"})
    with pytest.raises(ValueError, match="layout_name"):
        MicrophoneRigProfile(**{**base, "layout_name": "circle_8"})
    with pytest.raises(ValueError, match="unique"):
        MicrophoneRigProfile(**{**base, "microphone_ids": ("left", "left")})
    with pytest.raises(ValueError, match="match microphone_ids length"):
        MicrophoneRigProfile(
            **{**base, "microphone_relative_offsets_m": ((0.0, -0.05, 0.0),)}
        )
    with pytest.raises(ValueError, match="match microphone_ids length"):
        MicrophoneRigProfile(**{**base, "microphone_gains_db": (1.0,)})
    with pytest.raises(ValueError, match="sample_rate_hz"):
        MicrophoneRigProfile(**{**base, "sample_rate_hz": 0})
    with pytest.raises(ValueError, match="absolute USD prim path"):
        MicrophoneRigProfile(**{**base, "recommended_mount_prim_path": "relative/path"})


def test_rig_profile_library_rejects_duplicates_and_empty():
    profile = default_microphone_rig_profiles()[0]
    with pytest.raises(ValueError, match="Duplicate rig profile id"):
        validate_microphone_rig_profile_library((profile, profile))
    with pytest.raises(ValueError, match="must not be empty"):
        validate_microphone_rig_profile_library(())
