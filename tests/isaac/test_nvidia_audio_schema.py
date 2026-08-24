from __future__ import annotations

import math

import pytest

from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.stage_audio import (
    create_listener_prim,
    create_sound_prim,
)


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object] | None = None,
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes or {}


class _FakeStage:
    def __init__(
        self,
        prims: tuple[_FakePrim, ...] = (),
        *,
        time_codes_per_second: float = 1.0,
    ) -> None:
        self._prims = list(prims)
        self._time_codes_per_second = time_codes_per_second

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)

    def DefinePrim(self, path: str, type_name: str) -> _FakePrim:
        existing = self.GetPrimAtPath(path)
        if existing is not None:
            existing.type_name = type_name
            return existing
        prim = _FakePrim(path, type_name)
        self._prims.append(prim)
        return prim

    def GetPrimAtPath(self, path: object) -> _FakePrim | None:
        resolved = str(path)
        return next((prim for prim in self._prims if prim.path == resolved), None)

    def GetTimeCodesPerSecond(self) -> float:
        return self._time_codes_per_second


def test_sound_authoring_uses_current_schema_and_converts_sdk_units() -> None:
    stage = _FakeStage(time_codes_per_second=24.0)

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
    legacy = _FakePrim(
        "/World/Speaker",
        "Sound",
        {
            "filePath": "old.wav",
            "spatial": True,
            "loop": True,
            "endTime": 99.0,
        },
    )
    stage = _FakeStage((legacy,))

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
    stage = _FakeStage()

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


def test_listener_authoring_migrates_alias_and_disables_view_orientation() -> None:
    legacy = _FakePrim("/World/Listener", "Listener")
    stage = _FakeStage((legacy,))

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
    source = _FakePrim(
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
    stage = _FakeStage((source,), time_codes_per_second=24.0)

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
        cfg=IsaacAudioDiscoveryCfg(
            metadata_precedence=("usd", "ias", "defaults")
        ),
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
    stage = _FakeStage(
        (
            _FakePrim(
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
    stage = _FakeStage(
        (
            _FakePrim(
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


def test_discovery_rejects_invalid_native_loop_count() -> None:
    stage = _FakeStage(
        (
            _FakePrim(
                "/World/Speaker",
                "OmniSound",
                {
                    "filePath": "audio/native.wav",
                    "loopCount": -2,
                    "xformOp:translate": (0.0, 0.0, 0.0),
                },
            ),
        )
    )
    diagnostics: dict[str, object] = {}

    result = discover_stage_audio(stage, diagnostics_out=diagnostics)

    assert result.sources == ()
    rejection = diagnostics["source_rejections"]["/World/Speaker"]
    assert "loopCount" in rejection["error"]


def test_discovery_reads_legacy_sound_alias_with_native_unit_conversion() -> None:
    stage = _FakeStage(
        (
            _FakePrim(
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
    stage = _FakeStage(
        (
            _FakePrim(
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
    stage = _FakeStage((_FakePrim("/World/Speaker", "OmniSound", attributes),))
    diagnostics: dict[str, object] = {}

    result = discover_stage_audio(stage, diagnostics_out=diagnostics)

    assert result.sources == ()
    rejection = diagnostics["source_rejections"]["/World/Speaker"]
    assert message in rejection["error"]


def test_metadata_precedence_requires_each_supported_layer_once() -> None:
    with pytest.raises(ValueError, match="metadata_precedence"):
        IsaacAudioDiscoveryCfg(metadata_precedence=("ias", "ias", "defaults"))


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
