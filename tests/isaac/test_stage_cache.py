from __future__ import annotations

from types import SimpleNamespace

import pytest

from isaac_audio_sensors.core.acoustics import free_field_environment
from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
)
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_cache import StageAudioCache
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot
from tests.helpers import FakeUsdPrim, FakeUsdStage

MANUAL_ENVIRONMENT = free_field_environment(environment_id="cache_free_field")
MANUAL_RESOLUTION = IsaacEnvironmentResolutionCfg(mode="manual")


def _source_prim(path: str = "/World/Sources/SpeakerA") -> FakeUsdPrim:
    return FakeUsdPrim(
        path,
        "Sound",
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_a",
            "ias:class_label": "Speech",
            "ias:position_world": (5.0, 0.0, 0.0),
            "ias:start_time_s": 0.0,
            "ias:duration_s": 10.0,
        },
    )


def _array_prims() -> tuple[FakeUsdPrim, ...]:
    return (
        FakeUsdPrim(
            "/World/Rig/AudioArray",
            "Xform",
            {
                "ias:array_id": "rig_front",
                "ias:sample_rate_hz": 48000,
                "ias:position_world": (0.0, 0.0, 0.0),
                "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
            },
        ),
        FakeUsdPrim(
            "/World/Rig/AudioArray/front",
            "Xform",
            {
                "ias:microphone_id": "front",
                "ias:relative_position_m": (0.08, 0.0, 0.0),
            },
        ),
        FakeUsdPrim(
            "/World/Rig/AudioArray/right",
            "Xform",
            {
                "ias:microphone_id": "right",
                "ias:relative_position_m": (0.0, 0.08, 0.0),
            },
        ),
    )


def _counting_stage() -> tuple[FakeUsdStage, FakeUsdPrim]:
    source = _source_prim()
    return FakeUsdStage((source, *_array_prims())), source


def _live_sensor(
    stage: FakeUsdStage, *, discovered: bool = False
) -> IsaacAudioArraySensor:
    if discovered:
        return IsaacAudioArraySensor.from_discovered_stage(
            stage=stage,
            environment_resolution_cfg=MANUAL_RESOLUTION,
            environment=MANUAL_ENVIRONMENT,
            backend="analytic_acoustics",
            update_period_s=0.1,
        ).start()
    return IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig/AudioArray",
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        backend="analytic_acoustics",
        update_period_s=0.1,
    ).start()


@pytest.mark.parametrize("discovered", [False, True], ids=["explicit", "discovered"])
def test_steady_state_updates_reuse_discovery_cache(discovered):
    stage, source = _counting_stage()
    sensor = _live_sensor(stage, discovered=discovered)
    assert stage.traverse_count == 1

    first = sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    assert warm_count == 2

    source.attributes["ias:position_world"] = (0.0, 5.0, 0.0)
    for tick in range(1, 6):
        frame = sensor.update(sim_time_s=tick * 0.2)
    assert stage.traverse_count == warm_count

    assert first.detections[0].source_pose.position_m == (5.0, 0.0, 0.0)
    assert frame.detections[0].source_pose.position_m == (0.0, 5.0, 0.0)
    assert first.diagnostics["stage_snapshot"]["discovery_cache"]["hit"] is False
    cache_diag = frame.diagnostics["stage_snapshot"]["discovery_cache"]
    assert cache_diag["hit"] is True
    assert cache_diag["policy"] == "cache_until_invalidated"
    sensor.close()


def test_cached_snapshot_matches_full_discovery_snapshot():
    stage, source = _counting_stage()
    sensor = _live_sensor(stage)

    sensor.capture(timestamp_ms=100, usd_time_code=0.1)
    source.attributes["ias:position_world"] = (1.0, 4.0, 0.5)
    sensor.capture(timestamp_ms=200, usd_time_code=0.2)
    cached_scene = sensor.latest_scene
    assert sensor._latest_stage_diagnostics["discovery_cache"]["hit"] is True

    fresh_scene = build_stage_snapshot(
        stage,
        timestamp_ms=200,
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        array_prim_path="/World/Rig/AudioArray",
        usd_time_code=0.2,
    )
    assert cached_scene == fresh_scene
    assert cached_scene.sources[0].position_world == (1.0, 4.0, 0.5)
    sensor.close()


def test_removed_cached_prim_falls_back_to_full_rediscovery():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count

    stage.RemovePrim("/World/Sources/SpeakerA")
    frame = sensor.update(sim_time_s=0.2)

    assert stage.traverse_count == warm_count + 1
    assert frame.detections == ()
    cache_diag = frame.diagnostics["stage_snapshot"]["discovery_cache"]
    assert cache_diag["hit"] is False
    assert any(
        reason.startswith("missing_prim:")
        for reason in cache_diag["invalidation_reasons"]
    )
    sensor.close()


def test_rediscover_picks_up_new_prims_after_explicit_invalidation():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count

    new_source = stage.DefinePrim("/World/Sources/SpeakerB", "Sound")
    new_source.attributes.update(
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_b",
            "ias:position_world": (0.0, 3.0, 0.0),
            "ias:start_time_s": 0.0,
        }
    )

    stale = sensor.update(sim_time_s=0.2)
    assert len(stale.detections) == 1
    assert stage.traverse_count == warm_count

    sensor.rediscover()
    refreshed = sensor.update(sim_time_s=0.4)
    assert stage.traverse_count == warm_count + 1
    assert len(refreshed.detections) == 2
    sensor.close()


def test_usd_notice_handler_invalidates_only_on_resynced_paths():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    cache = sensor._stage_cache

    cache._on_objects_changed(
        SimpleNamespace(GetResyncedPaths=lambda: ()),
        None,
    )
    sensor.update(sim_time_s=0.2)
    assert stage.traverse_count == warm_count

    cache._on_objects_changed(
        SimpleNamespace(GetResyncedPaths=lambda: ("/World/NewWall",)),
        None,
    )
    sensor.update(sim_time_s=0.4)
    assert stage.traverse_count == warm_count + 1
    assert "usd_objects_changed_resync" in cache.invalidation_reasons
    sensor.close()


def test_capture_with_different_source_path_changes_cache_key():
    stage, _source = _counting_stage()
    speaker_b = stage.DefinePrim("/World/Sources/SpeakerB", "Sound")
    speaker_b.attributes.update(
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_b",
            "ias:position_world": (0.0, 3.0, 0.0),
            "ias:start_time_s": 0.0,
        }
    )
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count

    narrowed = sensor.capture(
        timestamp_ms=300,
        source_prim_path="/World/Sources/SpeakerB",
    )
    assert stage.traverse_count == warm_count + 1
    assert [det.source_id for det in narrowed.detections] == ["speaker_b"]
    sensor.close()


def test_rediscover_each_update_forces_full_discovery_every_capture():
    stage, _source = _counting_stage()
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        environment_resolution_cfg=MANUAL_RESOLUTION,
        environment=MANUAL_ENVIRONMENT,
        binding_cfg=IsaacAudioSceneBindingCfg(rediscover_each_update=True),
        backend="analytic_acoustics",
        update_period_s=0.1,
    ).start()
    construction_count = stage.traverse_count

    frames = [sensor.update(sim_time_s=tick * 0.2) for tick in range(3)]

    assert stage.traverse_count == construction_count + 3
    for frame in frames:
        cache_diag = frame.diagnostics["stage_snapshot"]["discovery_cache"]
        assert cache_diag["hit"] is False
        assert cache_diag["policy"] == "rediscover_each_update"
    assert sensor._stage_cache.full_discovery_count == 3
    sensor.close()


def test_info_only_discovery_attr_change_invalidates_cache():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    cache = sensor._stage_cache

    new_source = stage.DefinePrim("/World/Sources/SpeakerB", "Sound")
    new_source.attributes.update(
        {
            "filePath": "generated://impulse",
            "ias:source_id": "speaker_b",
            "ias:position_world": (0.0, 3.0, 0.0),
            "ias:start_time_s": 0.0,
        }
    )
    cache._on_objects_changed(
        SimpleNamespace(
            GetResyncedPaths=lambda: (),
            GetChangedInfoOnlyPaths=lambda: ("/World/Sources/SpeakerB.ias:source_id",),
        ),
        None,
    )

    refreshed = sensor.update(sim_time_s=0.2)
    assert stage.traverse_count == warm_count + 1
    assert len(refreshed.detections) == 2
    assert "usd_info_only_discovery_attr" in cache.invalidation_reasons
    sensor.close()


def test_native_loop_and_aural_mode_changes_refresh_source_semantics():
    stage, source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    cache = sensor._stage_cache

    source.attributes["loopCount"] = 2
    cache._on_objects_changed(
        SimpleNamespace(
            GetResyncedPaths=lambda: (),
            GetChangedInfoOnlyPaths=lambda: ("/World/Sources/SpeakerA.loopCount",),
        ),
        None,
    )
    sensor.update(sim_time_s=0.2)

    assert stage.traverse_count == warm_count + 1
    assert sensor.latest_scene is not None
    assert sensor.latest_scene.sources[0].loop_count == 2

    source.attributes["auralMode"] = "nonSpatial"
    cache._on_objects_changed(
        SimpleNamespace(
            GetResyncedPaths=lambda: (),
            GetChangedInfoOnlyPaths=lambda: ("/World/Sources/SpeakerA.auralMode",),
        ),
        None,
    )
    frame = sensor.update(sim_time_s=0.4)

    assert stage.traverse_count == warm_count + 2
    assert frame.detections == ()
    assert sensor.latest_scene is not None
    assert sensor.latest_scene.sources == ()
    rejection = frame.diagnostics["stage_snapshot"]["source_rejections"][source.path]
    assert rejection["reason"] == "non_spatial_source"
    sensor.close()


def test_info_only_pose_and_unrelated_changes_keep_cache():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    cache = sensor._stage_cache

    cache._on_objects_changed(
        SimpleNamespace(
            GetResyncedPaths=lambda: (),
            GetChangedInfoOnlyPaths=lambda: (
                "/World/Sources/SpeakerA.xformOp:translate",
                "/World/Sources/SpeakerA.visibility",
            ),
        ),
        None,
    )

    sensor.update(sim_time_s=0.2)
    assert stage.traverse_count == warm_count
    assert "usd_info_only_discovery_attr" not in cache.invalidation_reasons
    sensor.close()


def test_cache_close_revokes_listener_and_requires_traverse_method():
    stage, _source = _counting_stage()
    cache = StageAudioCache(stage)
    revoked: list[bool] = []
    cache._listener = SimpleNamespace(Revoke=lambda: revoked.append(True))
    cache.close()
    assert revoked == [True]
    assert cache._listener is None

    with pytest.raises(ValueError, match="Traverse"):
        StageAudioCache(object())
