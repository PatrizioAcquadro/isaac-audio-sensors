"""Steady-state live-path caching: no per-tick stage Traverse."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from isaac_audio_sensors.isaac.discovery import IsaacAudioSceneBindingCfg
from isaac_audio_sensors.isaac.sensor import IsaacAudioArraySensor
from isaac_audio_sensors.isaac.stage_cache import (
    StageAudioCache,
    _discovery_relevant_property,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot


class _FakePrim:
    def __init__(
        self,
        path: str,
        type_name: str,
        attributes: dict[str, object],
    ) -> None:
        self.path = path
        self.type_name = type_name
        self.attributes = attributes


class _FakeStage:
    def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
        self._prims = list(prims)

    def Traverse(self) -> tuple[_FakePrim, ...]:
        return tuple(self._prims)

    def DefinePrim(self, path: str, type_name: str) -> _FakePrim:
        prim = _FakePrim(path, type_name, {})
        self._prims.append(prim)
        return prim

    def GetPrimAtPath(self, path: str) -> _FakePrim | None:
        for prim in self._prims:
            if prim.path == path:
                return prim
        return None

    def RemovePrim(self, path: object) -> bool:
        path_string = str(path)
        before = len(self._prims)
        self._prims = [
            prim
            for prim in self._prims
            if prim.path != path_string and not prim.path.startswith(f"{path_string}/")
        ]
        return len(self._prims) != before


class _CountingFakeStage(_FakeStage):
    """Fake stage that counts full traversals for steady-state assertions."""

    def __init__(self, prims: tuple[_FakePrim, ...]) -> None:
        super().__init__(prims)
        self.traverse_count = 0

    def Traverse(self) -> tuple[_FakePrim, ...]:
        self.traverse_count += 1
        return super().Traverse()


def _source_prim(path: str = "/World/Sources/SpeakerA") -> _FakePrim:
    return _FakePrim(
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


def _array_prims() -> tuple[_FakePrim, ...]:
    return (
        _FakePrim(
            "/World/Rig/AudioArray",
            "Xform",
            {
                "ias:array_id": "rig_front",
                "ias:sample_rate_hz": 48000,
                "ias:position_world": (0.0, 0.0, 0.0),
                "ias:orientation_world_quat": (0.0, 0.0, 0.0, 1.0),
            },
        ),
        _FakePrim(
            "/World/Rig/AudioArray/front",
            "Xform",
            {
                "ias:microphone_id": "front",
                "ias:relative_position_m": (0.08, 0.0, 0.0),
            },
        ),
        _FakePrim(
            "/World/Rig/AudioArray/right",
            "Xform",
            {
                "ias:microphone_id": "right",
                "ias:relative_position_m": (0.0, 0.08, 0.0),
            },
        ),
    )


def _counting_stage() -> tuple[_CountingFakeStage, _FakePrim]:
    source = _source_prim()
    return _CountingFakeStage((source, *_array_prims())), source


def _live_sensor(stage: _FakeStage) -> IsaacAudioArraySensor:
    return IsaacAudioArraySensor.from_stage(
        stage=stage,
        array_prim_path="/World/Rig/AudioArray",
        backend="geometry_only",
        update_period_s=0.1,
    ).start()


def test_steady_state_updates_perform_no_full_traverse():
    stage, source = _counting_stage()
    sensor = _live_sensor(stage)
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
    assert frame.diagnostics["stage_snapshot"]["discovery_cache"]["hit"] is True
    sensor.close()


def test_cached_snapshot_matches_full_discovery_snapshot():
    stage, source = _counting_stage()
    sensor = _live_sensor(stage)

    sensor.capture(timestamp_ms=100, usd_time_code=0.1)
    source.attributes["ias:position_world"] = (1.0, 4.0, 0.5)
    sensor.capture(timestamp_ms=200, usd_time_code=0.2)
    cached_scene = sensor._latest_scene
    assert sensor._latest_stage_diagnostics["discovery_cache"]["hit"] is True

    fresh_scene = build_stage_snapshot(
        stage,
        timestamp_ms=200,
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


def test_discovered_stage_sensor_caches_semantic_discovery():
    stage, source = _counting_stage()
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        backend="geometry_only",
        update_period_s=0.1,
    ).start()
    construction_count = stage.traverse_count
    assert construction_count == 1

    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count
    assert warm_count == construction_count + 1

    source.attributes["ias:position_world"] = (0.0, 6.0, 0.0)
    frame = sensor.update(sim_time_s=0.4)
    assert stage.traverse_count == warm_count
    assert frame.detections[0].source_pose.position_m == (0.0, 6.0, 0.0)
    sensor.close()


def test_rediscover_each_update_forces_full_discovery_every_capture():
    stage, _source = _counting_stage()
    sensor = IsaacAudioArraySensor.from_discovered_stage(
        stage=stage,
        binding_cfg=IsaacAudioSceneBindingCfg(rediscover_each_update=True),
        backend="geometry_only",
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


def test_default_policy_keeps_cache_and_reports_policy():
    stage, _source = _counting_stage()
    sensor = _live_sensor(stage)
    sensor.update(sim_time_s=0.0)
    warm_count = stage.traverse_count

    frame = sensor.update(sim_time_s=0.2)

    assert stage.traverse_count == warm_count
    cache_diag = frame.diagnostics["stage_snapshot"]["discovery_cache"]
    assert cache_diag["hit"] is True
    assert cache_diag["policy"] == "cache_until_invalidated"
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
            GetChangedInfoOnlyPaths=lambda: (
                "/World/Sources/SpeakerB.ias:source_id",
            ),
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
            GetChangedInfoOnlyPaths=lambda: (
                "/World/Sources/SpeakerA.loopCount",
            ),
        ),
        None,
    )
    sensor.update(sim_time_s=0.2)

    assert stage.traverse_count == warm_count + 1
    assert sensor._latest_scene.sources[0].loop_count == 2

    source.attributes["auralMode"] = "nonSpatial"
    cache._on_objects_changed(
        SimpleNamespace(
            GetResyncedPaths=lambda: (),
            GetChangedInfoOnlyPaths=lambda: (
                "/World/Sources/SpeakerA.auralMode",
            ),
        ),
        None,
    )
    with pytest.raises(ValueError, match="nonSpatial"):
        sensor.update(sim_time_s=0.4)

    assert stage.traverse_count == warm_count + 2
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


def test_discovery_relevant_property_predicate():
    assert _discovery_relevant_property("/World/X.ias:source_id") is True
    assert _discovery_relevant_property("/World/X.ias:gain_db") is True
    assert _discovery_relevant_property("/World/X.filePath") is True
    assert _discovery_relevant_property("/World/X.startTime") is True
    assert _discovery_relevant_property("/World/X.endTime") is True
    assert _discovery_relevant_property("/World/X.loopCount") is True
    assert _discovery_relevant_property("/World/X.auralMode") is True
    assert _discovery_relevant_property("/World/X.xformOp:translate") is False
    assert _discovery_relevant_property("/World/X.visibility") is False
    assert _discovery_relevant_property("/World/X") is False
    assert _discovery_relevant_property(SimpleNamespace(name="ias:array_id")) is True
    assert (
        _discovery_relevant_property(SimpleNamespace(name="xformOp:orient")) is False
    )


def test_stage_cache_policy_unit_counts_full_discoveries():
    stage, _source = _counting_stage()
    cache = StageAudioCache(stage, rediscover_each_update=True)

    cache.snapshot(timestamp_ms=0, array_prim_path="/World/Rig/AudioArray")
    cache.snapshot(timestamp_ms=100, array_prim_path="/World/Rig/AudioArray")

    assert cache.full_discovery_count == 2
    assert cache.cached_tick_count == 0
    assert "rediscover_each_update_policy" in cache.invalidation_reasons


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
