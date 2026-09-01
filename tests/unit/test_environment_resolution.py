from __future__ import annotations

import pytest

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.microphone_array import create_microphone_array
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
    resolve_stage_environment,
)
from isaac_audio_sensors.isaac.stage_audio import attach_acoustic_environment_attrs
from tests.helpers import FakeUsdPrim, FakeUsdStage


def _array(position=(1.0, 1.0, 1.0)):
    return create_microphone_array(
        array_id="rig",
        prim_path="/World/Rig",
        layout_name="stereo_y",
        position_world=position,
    )


def _volume(
    path: str,
    *,
    identifier: str,
    minimum=(0.0, 0.0, 0.0),
    maximum=(4.0, 4.0, 3.0),
    priority: int = 0,
) -> FakeUsdPrim:
    return FakeUsdPrim(
        path,
        "Cube",
        {
            "ias:environment_kind": "shoebox",
            "ias:environment_id": identifier,
            "ias:environment_priority": priority,
            "ias:environment_min_world": minimum,
            "ias:environment_max_world": maximum,
        },
    )


def _floor(path: str, *, identifier: str, priority: int = 0) -> FakeUsdPrim:
    return FakeUsdPrim(
        path,
        "Plane",
        {
            "ias:environment_kind": "half_space",
            "ias:environment_id": identifier,
            "ias:environment_priority": priority,
            "ias:position_world": (0.0, 0.0, 0.0),
            "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
        },
    )


def test_resolution_config_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="mode"):
        IsaacEnvironmentResolutionCfg(mode="")
    with pytest.raises(ValueError, match="requires anchor_prim_path"):
        IsaacEnvironmentResolutionCfg(mode="anchor")
    with pytest.raises(ValueError, match="only when mode='anchor'"):
        IsaacEnvironmentResolutionCfg(mode="auto", anchor_prim_path="/World/Room")
    with pytest.raises(ValueError, match="containment_tolerance_m"):
        IsaacEnvironmentResolutionCfg(mode="auto", containment_tolerance_m=-1.0)


def test_manual_resolution_requires_explicit_environment() -> None:
    stage = FakeUsdStage()
    cfg = IsaacEnvironmentResolutionCfg(mode="manual")

    with pytest.raises(ValueError, match="explicit AcousticEnvironmentSpec"):
        resolve_stage_environment(stage, _array(), cfg=cfg)

    environment = free_field_environment(environment_id="manual_free")
    assert (
        resolve_stage_environment(
            stage,
            _array(),
            cfg=cfg,
            manual_environment=environment,
        )
        is environment
    )


def test_manual_shoebox_checks_every_microphone_with_tolerance() -> None:
    stage = FakeUsdStage()
    environment = shoebox_environment(
        environment_id="manual_box",
        dimensions_m=(2.0, 2.0, 2.0),
    )
    cfg = IsaacEnvironmentResolutionCfg(mode="manual")

    with pytest.raises(ValueError, match="complete microphone array"):
        resolve_stage_environment(
            stage,
            _array(position=(1.0, 1.96, 1.0)),
            cfg=cfg,
            manual_environment=environment,
        )


def test_explicit_unmarked_anchor_defaults_to_shoebox_and_path_id() -> None:
    anchor = FakeUsdPrim(
        "/World/RoomA",
        "Cube",
        {
            "ias:environment_min_world": (0.0, 0.0, 0.0),
            "ias:environment_max_world": (4.0, 4.0, 3.0),
        },
    )
    environment = resolve_stage_environment(
        FakeUsdStage((anchor,)),
        _array(),
        cfg=IsaacEnvironmentResolutionCfg(
            mode="anchor",
            anchor_prim_path="/World/RoomA",
        ),
    )

    assert environment.kind == "shoebox"
    assert environment.environment_id == "RoomA"
    assert environment.dimensions_m == (4.0, 4.0, 3.0)


def test_environment_authoring_helper_writes_typed_markers() -> None:
    prim = FakeUsdPrim("/World/Room", "Cube")

    attrs = attach_acoustic_environment_attrs(
        prim,
        environment_id="room",
        kind="shoebox",
        priority=3,
    )

    assert attrs == {
        "ias:environment_id": "room",
        "ias:environment_kind": "shoebox",
        "ias:environment_priority": 3,
    }
    assert prim.attributes == attrs


def test_auto_prefers_priority_then_smallest_containing_volume() -> None:
    large = _volume(
        "/World/Large",
        identifier="large",
        maximum=(6.0, 6.0, 4.0),
        priority=1,
    )
    small = _volume(
        "/World/Small",
        identifier="small",
        maximum=(3.0, 3.0, 2.0),
        priority=1,
    )
    lower_priority = _volume(
        "/World/HighVolumeLowPriority",
        identifier="lower",
        maximum=(2.5, 2.5, 2.0),
        priority=0,
    )
    diagnostics = {}

    environment = resolve_stage_environment(
        FakeUsdStage((large, small, lower_priority)),
        _array(),
        cfg=IsaacEnvironmentResolutionCfg(mode="auto"),
        diagnostics_out=diagnostics,
    )

    assert environment.environment_id == "small"
    assert diagnostics["selected_prim_path"] == "/World/Small"
    assert diagnostics["containing_volume_count"] == 3


def test_auto_rejects_equal_best_volumes_without_path_tiebreak() -> None:
    stage = FakeUsdStage(
        (
            _volume("/World/A", identifier="a"),
            _volume("/World/B", identifier="b"),
        )
    )

    with pytest.raises(ValueError, match="ambiguous.*explicit anchor"):
        resolve_stage_environment(
            stage,
            _array(),
            cfg=IsaacEnvironmentResolutionCfg(mode="auto"),
        )


def test_auto_uses_volume_before_floor_then_falls_back_to_unique_floor() -> None:
    floor = _floor("/World/Floor", identifier="floor", priority=10)
    volume = _volume("/World/Room", identifier="room", priority=0)
    cfg = IsaacEnvironmentResolutionCfg(mode="auto")

    selected_volume = resolve_stage_environment(
        FakeUsdStage((floor, volume)),
        _array(),
        cfg=cfg,
    )
    selected_floor = resolve_stage_environment(
        FakeUsdStage((floor,)),
        _array(),
        cfg=cfg,
    )

    assert selected_volume.environment_id == "room"
    assert selected_floor.kind == "half_space"


def test_auto_ignores_unmarked_geometry_and_rejects_malformed_markers() -> None:
    unmarked = FakeUsdPrim(
        "/World/Geometry",
        "Cube",
        {
            "ias:environment_min_world": (0.0, 0.0, 0.0),
            "ias:environment_max_world": (4.0, 4.0, 3.0),
        },
    )
    cfg = IsaacEnvironmentResolutionCfg(mode="auto")
    with pytest.raises(ValueError, match="found no marked"):
        resolve_stage_environment(FakeUsdStage((unmarked,)), _array(), cfg=cfg)

    malformed = FakeUsdPrim(
        "/World/Malformed",
        "Cube",
        {
            "ias:environment_kind": "shoebox",
            "ias:environment_min_world": (0.0, 0.0, 0.0),
            "ias:environment_max_world": (4.0, 4.0, 3.0),
        },
    )
    with pytest.raises(ValueError, match="requires.*ias:environment_id"):
        resolve_stage_environment(FakeUsdStage((malformed,)), _array(), cfg=cfg)


def test_auto_half_space_requires_complete_array_above_floor() -> None:
    floor = _floor("/World/Floor", identifier="floor")

    with pytest.raises(ValueError, match="found no marked"):
        resolve_stage_environment(
            FakeUsdStage((floor,)),
            _array(position=(1.0, 1.0, -0.01)),
            cfg=IsaacEnvironmentResolutionCfg(mode="auto"),
        )
