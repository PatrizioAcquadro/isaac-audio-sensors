from __future__ import annotations

import math
from dataclasses import fields

import pytest

from isaac_audio_sensors.core.directivity import (
    DirectivityPattern,
    DirectivityValidationError,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.stage_audio import (
    attach_microphone_attrs,
    attach_sound_source_attrs,
    create_listener_prim,
    create_sound_prim,
)
from tests.helpers import FakeUsdPrim, FakeUsdStage


def test_sound_authoring_uses_current_schema_and_converts_sdk_units() -> None:
    stage = FakeUsdStage(time_codes_per_second=24.0)

    record = create_sound_prim(
        stage,
        prim_path="/World/Speaker",
        audio_asset_path="audio/speech.wav",
        spatial=False,
        loop=True,
        start_time_s=1.5,
        duration_s=2.0,
        gain_db=-6.0,
    )

    prim = stage.GetPrimAtPath("/World/Speaker")
    assert prim is not None
    assert record.prim_type == "OmniSound"
    assert prim.type_name == "OmniSound"
    assert prim.attributes == {
        "ias:audio_asset_path": "audio/speech.wav",
        "auralMode": "nonSpatial",
        "loopCount": -1,
        "startTime": 36.0,
        "gain": pytest.approx(10.0 ** (-6.0 / 20.0)),
        "filePath": "audio/speech.wav",
        "endTime": 84.0,
    }


def test_sound_authoring_migrates_legacy_alias_and_clears_obsolete_attrs() -> None:
    legacy = FakeUsdPrim(
        "/World/Speaker",
        "Sound",
        {
            "filePath": "old.wav",
            "spatial": True,
            "loop": True,
            "endTime": 99.0,
        },
    )
    stage = FakeUsdStage((legacy,))

    create_sound_prim(
        stage,
        prim_path=legacy.path,
        audio_asset_path="generated://pulse",
    )

    assert legacy.type_name == "OmniSound"
    assert legacy.attributes["ias:audio_asset_path"] == "generated://pulse"
    assert legacy.attributes["auralMode"] == "spatial"
    assert legacy.attributes["loopCount"] == 0
    assert "filePath" not in legacy.attributes
    assert "spatial" not in legacy.attributes
    assert "loop" not in legacy.attributes
    assert "endTime" not in legacy.attributes


def test_sound_authoring_preserves_finite_loop_count_and_rejects_ambiguity() -> None:
    stage = FakeUsdStage()

    record = create_sound_prim(
        stage,
        prim_path="/World/Speaker",
        audio_asset_path="audio/speech.wav",
        loop_count=3,
    )

    assert record.attributes["loopCount"] == 3
    with pytest.raises(ValueError, match="not both"):
        create_sound_prim(
            stage,
            prim_path="/World/Ambiguous",
            audio_asset_path="audio/speech.wav",
            loop=True,
            loop_count=2,
        )


def test_entity_directivity_authoring_is_validated_before_mutation() -> None:
    source = FakeUsdPrim("/World/Speaker", "OmniSound")

    with pytest.raises(DirectivityValidationError, match="ias:directivity"):
        attach_sound_source_attrs(
            source,
            source_id="speaker",
            class_label="Speech",
            directivity="unsupported",
        )
    assert source.attributes == {}

    with pytest.raises(DirectivityValidationError, match="orientation_world_quat"):
        attach_sound_source_attrs(
            source,
            source_id="speaker",
            class_label="Speech",
            directivity="cardioid",
        )
    assert source.attributes == {}

    source_attrs = attach_sound_source_attrs(
        source,
        source_id="speaker",
        class_label="Speech",
        position_world=(1.0, 0.0, 0.0),
        orientation_world_quat=(0.0, 0.0, 0.0, 1.0),
        directivity=DirectivityPattern.CARDIOID,
    )
    assert source_attrs["ias:directivity"] == "cardioid"

    microphone = FakeUsdPrim("/World/Array/front", "Microphone")
    with pytest.raises(DirectivityValidationError, match="directivity"):
        attach_microphone_attrs(
            microphone,
            mic_id="front",
            relative_position_m=(0.05, 0.0, 0.0),
            directivity="unsupported",
        )
    assert microphone.attributes == {}

    with pytest.raises(DirectivityValidationError, match="relative_orientation_quat"):
        attach_microphone_attrs(
            microphone,
            mic_id="front",
            relative_position_m=(0.05, 0.0, 0.0),
            directivity="supercardioid",
        )
    assert microphone.attributes == {}

    microphone_attrs = attach_microphone_attrs(
        microphone,
        mic_id="front",
        relative_position_m=(0.05, 0.0, 0.0),
        relative_orientation_quat=(0.0, 0.0, 0.0, 1.0),
        directivity=DirectivityPattern.SUPERCARDIOID,
    )
    assert microphone_attrs["ias:directivity"] == "supercardioid"


@pytest.mark.parametrize("directivity", ["unsupported", "cardioid"])
def test_source_discovery_propagates_directivity_errors_when_non_strict(
    directivity: str,
) -> None:
    source = FakeUsdPrim(
        "/World/Speaker",
        "OmniSound",
        {
            "ias:source_id": "speaker",
            "ias:audio_asset_path": "generated://impulse",
            "ias:position_world": (1.0, 0.0, 0.0),
            "ias:directivity": directivity,
        },
    )
    if directivity == "unsupported":
        source.attributes["ias:orientation_world_quat"] = (0.0, 0.0, 0.0, 1.0)

    with pytest.raises(DirectivityValidationError):
        discover_stage_audio(FakeUsdStage((source,)))


@pytest.mark.parametrize("directivity", ["unsupported", "figure_eight"])
def test_microphone_discovery_propagates_directivity_errors_when_non_strict(
    directivity: str,
) -> None:
    array = FakeUsdPrim(
        "/World/Array",
        "Xform",
        {
            "ias:array_id": "array",
            "ias:position_world": (0.0, 0.0, 0.0),
        },
    )
    microphone = FakeUsdPrim(
        "/World/Array/front",
        "Microphone",
        {
            "ias:microphone_id": "front",
            "ias:relative_position_m": (0.05, 0.0, 0.0),
            "ias:directivity": directivity,
        },
    )
    if directivity == "unsupported":
        microphone.attributes["ias:relative_orientation_quat"] = (
            0.0,
            0.0,
            0.0,
            1.0,
        )

    with pytest.raises(DirectivityValidationError):
        discover_stage_audio(FakeUsdStage((array, microphone)))


def test_listener_authoring_migrates_alias_and_disables_view_orientation() -> None:
    legacy = FakeUsdPrim("/World/Listener", "Listener")
    stage = FakeUsdStage((legacy,))

    record = create_listener_prim(
        stage,
        prim_path=legacy.path,
        array_id="robot_array",
    )

    assert record.prim_type == "OmniListener"
    assert legacy.type_name == "OmniListener"
    assert legacy.attributes == {
        "ias:array_id": "robot_array",
        "orientationFromView": False,
    }


def test_discovery_prefers_ias_metadata_but_can_prefer_native_usd() -> None:
    source = FakeUsdPrim(
        "/World/Speaker",
        "OmniSound",
        {
            "ias:source_id": "speaker",
            "ias:class_label": "Speech",
            "ias:audio_asset_path": "generated://speech",
            "ias:start_time_s": 2.0,
            "ias:duration_s": 4.0,
            "ias:gain_db": -3.0,
            "filePath": "audio/native.wav",
            "startTime": 24.0,
            "endTime": 72.0,
            "gain": 0.5,
            "loopCount": 2,
            "xformOp:translate": (1.0, 0.0, 0.0),
        },
    )
    stage = FakeUsdStage((source,), time_codes_per_second=24.0)

    default_result = discover_stage_audio(stage)
    default_source = default_result.sources[0]
    assert default_source.spec.audio_asset_path == "generated://speech"
    assert default_source.spec.start_time_s == 2.0
    assert default_source.spec.duration_s == 4.0
    assert default_source.spec.gain_db == -3.0
    assert default_source.diagnostics["audio_asset_path_provenance"] == (
        "ias:audio_asset_path"
    )

    usd_result = discover_stage_audio(
        stage,
        cfg=IsaacAudioDiscoveryCfg(metadata_precedence=("usd", "ias", "defaults")),
    )
    usd_source = usd_result.sources[0]
    assert usd_source.spec.audio_asset_path == "audio/native.wav"
    assert usd_source.spec.start_time_s == 1.0
    assert usd_source.spec.duration_s == 2.0
    assert usd_source.spec.gain_db == pytest.approx(20.0 * math.log10(0.5))
    assert usd_source.spec.loop_count == 2
    assert usd_source.diagnostics["active_window_provenance"] == {
        "start_time_s": "startTime",
        "duration_s": "endTime",
    }
    assert usd_source.diagnostics["gain_db_provenance"] == "gain"
    assert usd_source.diagnostics["loop_count_provenance"] == "loopCount"


def test_discovery_excludes_non_spatial_sound_with_clear_diagnostic() -> None:
    stage = FakeUsdStage(
        (
            FakeUsdPrim(
                "/World/UiSound",
                "OmniSound",
                {
                    "auralMode": "nonSpatial",
                    "filePath": "audio/ui.wav",
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    result = discover_stage_audio(
        stage,
        cfg=IsaacAudioDiscoveryCfg(strict_candidate_errors=True),
        diagnostics_out=diagnostics,
    )

    assert result.sources == ()
    rejection = diagnostics["source_rejections"]["/World/UiSound"]
    assert rejection["reason"] == "non_spatial_source"
    assert "physical microphone-array discovery" in rejection["error"]


def test_discovery_rejects_explicit_non_spatial_sound() -> None:
    stage = FakeUsdStage(
        (
            FakeUsdPrim(
                "/World/UiSound",
                "OmniSound",
                {
                    "auralMode": "nonSpatial",
                    "filePath": "audio/ui.wav",
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
        )
    )

    with pytest.raises(ValueError, match="nonSpatial"):
        discover_stage_audio(
            stage,
            explicit_source_prim_path="/World/UiSound",
        )


def test_discovery_reads_legacy_sound_alias_with_native_unit_conversion() -> None:
    stage = FakeUsdStage(
        (
            FakeUsdPrim(
                "/World/LegacySound",
                "Sound",
                {
                    "filePath": "audio/legacy.wav",
                    "startTime": 48.0,
                    "endTime": 120.0,
                    "gain": 2.0,
                    "xformOp:translate": (0.0, 1.0, 0.0),
                },
            ),
        ),
        time_codes_per_second=24.0,
    )

    source = discover_stage_audio(stage).sources[0].spec

    assert source.source_id == "LegacySound"
    assert source.audio_asset_path == "audio/legacy.wav"
    assert source.start_time_s == 2.0
    assert source.duration_s == 3.0
    assert source.gain_db == pytest.approx(20.0 * math.log10(2.0))


def test_ias_gain_precedence_bypasses_nonrepresentable_native_gain() -> None:
    stage = FakeUsdStage(
        (
            FakeUsdPrim(
                "/World/Speaker",
                "OmniSound",
                {
                    "ias:gain_db": -12.0,
                    "gain": 0.0,
                    "startTime": 0.0,
                    "filePath": "audio/native.wav",
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
        )
    )

    source = discover_stage_audio(stage).sources[0].spec

    assert source.gain_db == -12.0


@pytest.mark.parametrize(
    ("attributes", "message"),
    (
        ({"loopCount": -2}, "loopCount"),
        ({"startTime": -1.0, "gain": 1.0}, "source is disabled"),
        ({"startTime": 0.0, "gain": 0.0}, "gain must be positive"),
    ),
)
def test_discovery_rejects_disabled_or_nonrepresentable_native_source(
    attributes: dict[str, object],
    message: str,
) -> None:
    attributes.update(
        {
            "filePath": "audio/native.wav",
            "xformOp:translate": (0.0, 0.0, 0.0),
        }
    )
    stage = FakeUsdStage((FakeUsdPrim("/World/Speaker", "OmniSound", attributes),))
    diagnostics: dict[str, object] = {}

    result = discover_stage_audio(stage, diagnostics_out=diagnostics)

    assert result.sources == ()
    rejection = diagnostics["source_rejections"]["/World/Speaker"]
    assert message in rejection["error"]


def test_metadata_precedence_requires_each_supported_layer_once() -> None:
    with pytest.raises(ValueError, match="metadata_precedence"):
        IsaacAudioDiscoveryCfg(metadata_precedence=("ias", "ias", "defaults"))


def test_discovery_configs_preserve_defaults_and_conversion() -> None:
    discovery = IsaacAudioDiscoveryCfg()
    binding = IsaacAudioSceneBindingCfg()
    assert discovery.required_arrays is False
    assert binding.required_arrays is True
    assert binding.preferred_array is None
    assert binding.preferred_source is None
    assert binding.rediscover_each_update is False

    binding = IsaacAudioSceneBindingCfg(
        discovery_roots=("/World/",),
        robot_base_prim_path="/World/Robot/",
        array_roots=("/World/Robot/Arrays/",),
        source_roots=("/World/Sources/",),
        include_globs=("*Speaker*",),
        default_sample_rate_hz=44_100,
        metadata_precedence=("usd", "ias", "defaults"),
        preferred_array="front",
        preferred_source="speech",
        rediscover_each_update=True,
        strict_candidate_errors=True,
    )
    converted = binding.to_discovery_cfg()

    assert binding.discovery_roots == ("/World",)
    assert binding.robot_base_prim_path == "/World/Robot"
    assert binding.array_roots == ("/World/Robot/Arrays",)
    assert binding.source_roots == ("/World/Sources",)
    for item in fields(converted):
        assert getattr(converted, item.name) == getattr(binding, item.name)


def test_real_usd_listener_compatibility_requires_static_identity_child() -> None:
    pytest.importorskip("pxr")
    from pxr import Gf, Sdf, Usd, UsdGeom

    from isaac_audio_sensors.kit.kit_audio import _listener_is_compatible

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World/Array")

    def listener(name: str):
        prim = UsdGeom.Xform.Define(stage, f"/World/Array/{name}").GetPrim()
        prim.CreateAttribute(
            "orientationFromView",
            Sdf.ValueTypeNames.Bool,
        ).Set(False)
        prim.CreateAttribute("ias:array_id", Sdf.ValueTypeNames.String).Set("rig")
        return prim

    identity = listener("Identity")
    assert _listener_is_compatible(
        identity,
        array_prim_path="/World/Array",
        array_id="rig",
    )

    offset = listener("Offset")
    UsdGeom.Xformable(offset).AddTranslateOp().Set(Gf.Vec3d(0.1, 0.0, 0.0))
    assert not _listener_is_compatible(
        offset,
        array_prim_path="/World/Array",
        array_id="rig",
    )

    reset = listener("Reset")
    UsdGeom.Xformable(reset).SetResetXformStack(True)
    assert not _listener_is_compatible(
        reset,
        array_prim_path="/World/Array",
        array_id="rig",
    )

    animated = listener("Animated")
    translate = UsdGeom.Xformable(animated).AddTranslateOp()
    translate.Set(Gf.Vec3d(0.0, 0.0, 0.0), Usd.TimeCode.Default())
    translate.Set(Gf.Vec3d(0.1, 0.0, 0.0), Usd.TimeCode(1.0))
    assert not _listener_is_compatible(
        animated,
        array_prim_path="/World/Array",
        array_id="rig",
    )
