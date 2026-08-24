"""Cached stage discovery so steady-state live ticks re-resolve only poses.

The first snapshot (and any snapshot after invalidation) runs the full
``discover_stage_audio`` path, including one ``stage.Traverse()``. Steady-state
snapshots reuse the cached prim tuple and the cached discovery decisions, and
only re-resolve poses and prim attributes at the new time code. Structural
stage edits invalidate the cache through ``Usd.Notice.ObjectsChanged`` resyncs
on real USD stages, and discovery-relevant info-only property changes (the
``ias:`` marker attributes plus the audio alias attributes discovery reads)
invalidate it as well, so newly audio-tagged existing prims are picked up
without a manual ``rediscover()``. Pose-only property changes never
invalidate. Cheap per-tick path validation and an explicit ``rediscover()``
cover duck-typed test stages, and ``rediscover_each_update=True`` forces full
discovery on every snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from isaac_audio_sensors.core.types import AudioSceneSnapshot
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioDiscoveryCfg,
    _array_spec_from_prim,
    _base_diagnostics,
    _pose_diagnostics,
    _resolve_time_code,
    _source_spec_from_prim,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.pose_resolver import IsaacStagePoseResolver
from isaac_audio_sensors.isaac.stage_snapshot import (
    effective_discovery_cfg,
    snapshot_from_discovery,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _CachedDiscovery:
    """Decisions and prim handles retained from one full discovery."""

    key: tuple[Any, ...]
    stage_id: str
    cfg: IsaacAudioDiscoveryCfg
    prims: tuple[Any, ...]
    array_entries: tuple[tuple[str, tuple[str, ...]], ...]
    source_entries: tuple[tuple[str, tuple[str, ...]], ...]
    selected_array_path: str | None
    selected_source_path: str | None
    preferred_source: str | None


# Non-"ias:" attribute names discovery reads as audio metadata aliases
# (see discovery.py); info-only changes to them can alter the candidate set.
_DISCOVERY_ALIAS_PROPERTY_NAMES = frozenset(
    {
        "filePath",
        "inputs:file",
        "inputs:audio",
        "startTime",
        "endTime",
        "duration",
        "gain",
        "loopCount",
        "auralMode",
    }
)

_ACOUSTIC_REFRESH_REASONS = (
    "room_geometry_changed",
    "material_changed",
    "occluder_moved",
)
_ROOM_GEOMETRY_PROPERTIES = frozenset(
    {
        "ias:room_min_world",
        "ias:room_max_world",
        "ias:room_size_m",
        "size",
        "extent",
    }
)
_MATERIAL_PROPERTIES = frozenset(
    {
        "ias:acoustic_material_id",
        "ias:material",
        "ias:absorption",
        "ias:transmission_loss_db",
        "ias:transmission_loss_db_bands",
        "material:binding",
    }
)


class StageAudioCache:
    """Per-sensor cache of discovered audio prim paths on one stage."""

    def __init__(
        self,
        stage: Any,
        *,
        rediscover_each_update: bool = False,
        room_anchor_prim_path: str | None = None,
    ) -> None:
        if stage is None or not hasattr(stage, "Traverse"):
            raise ValueError("stage must provide a Traverse method.")
        self.stage = stage
        self.rediscover_each_update = bool(rediscover_each_update)
        self.full_discovery_count = 0
        self.cached_tick_count = 0
        self.invalidation_reasons: list[str] = []
        self.acoustic_refresh_reasons: list[str] = []
        self.room_anchor_prim_path = (
            None
            if room_anchor_prim_path is None
            else str(room_anchor_prim_path).rstrip("/")
        )
        self._cached: _CachedDiscovery | None = None
        self._dirty = False
        self._listener: Any | None = None
        self._current_acoustic_refresh_reasons: list[str] = []
        self._pending_non_audio_pose_paths: list[str] = []

    def invalidate(self, reason: str) -> None:
        """Mark the cache dirty; the next snapshot runs full discovery."""

        resolved = str(reason)
        self._dirty = True
        self.invalidation_reasons.append(resolved)
        if resolved in _ACOUSTIC_REFRESH_REASONS:
            self._append_acoustic_refresh(resolved)

    def record_acoustic_refresh(self, reason: str) -> None:
        """Record a recompute-only acoustic reason without dirtying discovery."""

        resolved = str(reason)
        if resolved != "occluder_moved":
            raise ValueError(
                "record_acoustic_refresh only accepts recompute-only 'occluder_moved'."
            )
        self._append_acoustic_refresh(resolved)

    @property
    def current_acoustic_refresh_reasons(self) -> tuple[str, ...]:
        """Reasons awaiting successful publication by the current capture."""

        return tuple(self._current_acoustic_refresh_reasons)

    @property
    def pending_non_audio_pose_paths(self) -> tuple[str, ...]:
        """Pose-only non-audio paths awaiting comparison with a fresh raycast."""

        return tuple(self._pending_non_audio_pose_paths)

    def consume_acoustic_refresh_reasons(self) -> tuple[str, ...]:
        """Consume the deterministic current-frame reason subset."""

        reasons = tuple(self._current_acoustic_refresh_reasons)
        self._current_acoustic_refresh_reasons.clear()
        return reasons

    def clear_pending_non_audio_pose_paths(self) -> None:
        """Clear pose notices after a successful fresh raycast comparison."""

        self._pending_non_audio_pose_paths.clear()

    def reset_acoustic_state(self) -> None:
        """Clear transient acoustic comparison state for a sensor reset."""

        self._current_acoustic_refresh_reasons.clear()
        self._pending_non_audio_pose_paths.clear()

    def _append_acoustic_refresh(self, reason: str) -> None:
        if reason in self._current_acoustic_refresh_reasons:
            return
        self._current_acoustic_refresh_reasons.append(reason)
        self.acoustic_refresh_reasons.append(reason)

    def rediscover(self) -> None:
        """Force full re-discovery (and one Traverse) on the next snapshot."""

        self.invalidate("explicit_rediscover")

    def close(self) -> None:
        """Revoke the USD change listener and drop cached prim handles."""

        if self._listener is not None:
            revoke = getattr(self._listener, "Revoke", None)
            if callable(revoke):
                revoke()
            self._listener = None
        self._cached = None
        self._dirty = False
        self.invalidation_reasons.clear()
        self.acoustic_refresh_reasons.clear()
        self._current_acoustic_refresh_reasons.clear()
        self._pending_non_audio_pose_paths.clear()

    def snapshot(
        self,
        *,
        timestamp_ms: int,
        stage_id: str | None = None,
        array_prim_path: str | None = None,
        robot_base_prim_path: str | None = None,
        source_prim_path: str | None = None,
        usd_time_code: Any | None = None,
        time_code: Any | None = None,
        default_class_label: str = "Sound",
        discovery_cfg: IsaacAudioDiscoveryCfg | None = None,
        preferred_array: str | None = None,
        preferred_source: str | None = None,
        diagnostics_out: dict[str, Any] | None = None,
    ) -> AudioSceneSnapshot:
        """Build a live snapshot, traversing the stage only when required."""

        if self.rediscover_each_update:
            self.invalidate("rediscover_each_update_policy")
        cfg = effective_discovery_cfg(
            discovery_cfg=discovery_cfg,
            array_prim_path=array_prim_path,
            robot_base_prim_path=robot_base_prim_path,
            source_prim_path=source_prim_path,
            default_class_label=default_class_label,
        )
        resolved_time_code = _resolve_time_code(
            usd_time_code=usd_time_code,
            time_code=time_code,
        )
        key = (
            cfg,
            stage_id,
            array_prim_path,
            source_prim_path,
            preferred_array,
            preferred_source,
        )
        cached = self._cached
        if (
            cached is not None
            and not self._dirty
            and cached.key == key
            and self._cached_paths_resolve(cached)
        ):
            try:
                return self._cached_snapshot(
                    cached,
                    timestamp_ms=timestamp_ms,
                    array_prim_path=array_prim_path,
                    source_prim_path=source_prim_path,
                    preferred_array=preferred_array,
                    time_code=resolved_time_code,
                    diagnostics_out=diagnostics_out,
                )
            except Exception as exc:  # noqa: BLE001 - full rediscovery fallback.
                self.invalidate(f"cached_tick_failed:{type(exc).__name__}")
        return self._full_snapshot(
            key=key,
            cfg=cfg,
            timestamp_ms=timestamp_ms,
            stage_id=stage_id,
            array_prim_path=array_prim_path,
            source_prim_path=source_prim_path,
            time_code=resolved_time_code,
            preferred_array=preferred_array,
            preferred_source=preferred_source,
            diagnostics_out=diagnostics_out,
        )

    def _full_snapshot(
        self,
        *,
        key: tuple[Any, ...],
        cfg: IsaacAudioDiscoveryCfg,
        timestamp_ms: int,
        stage_id: str | None,
        array_prim_path: str | None,
        source_prim_path: str | None,
        time_code: Any | None,
        preferred_array: str | None,
        preferred_source: str | None,
        diagnostics_out: dict[str, Any] | None,
    ) -> AudioSceneSnapshot:
        prims = tuple(self.stage.Traverse())
        self.full_discovery_count += 1
        diagnostics: dict[str, Any] = {}
        result = discover_stage_audio(
            self.stage,
            cfg=cfg,
            timestamp_ms=timestamp_ms,
            stage_id=stage_id,
            time_code=time_code,
            explicit_array_prim_path=array_prim_path,
            explicit_source_prim_path=source_prim_path,
            preferred_array=preferred_array,
            preferred_source=preferred_source,
            diagnostics_out=diagnostics,
            prims=prims,
        )
        self._cached = _CachedDiscovery(
            key=key,
            stage_id=result.stage_id,
            cfg=cfg,
            prims=prims,
            array_entries=tuple(
                (array.spec.prim_path, array.reasons) for array in result.arrays
            ),
            source_entries=tuple(
                (source.spec.prim_path, source.reasons) for source in result.sources
            ),
            selected_array_path=(
                None
                if result.selected_array is None
                else result.selected_array.spec.prim_path
            ),
            selected_source_path=(
                None
                if result.selected_source is None
                else result.selected_source.spec.prim_path
            ),
            preferred_source=preferred_source,
        )
        self._dirty = False
        self._register_usd_listener()
        diagnostics["discovery_cache"] = self._cache_diagnostics(hit=False)
        if diagnostics_out is not None:
            diagnostics_out.clear()
            diagnostics_out.update(diagnostics)
        return snapshot_from_discovery(
            result,
            timestamp_ms=timestamp_ms,
            preferred_source=preferred_source,
        )

    def _cached_snapshot(
        self,
        cached: _CachedDiscovery,
        *,
        timestamp_ms: int,
        array_prim_path: str | None,
        source_prim_path: str | None,
        preferred_array: str | None,
        time_code: Any | None,
        diagnostics_out: dict[str, Any] | None,
    ) -> AudioSceneSnapshot:
        resolver = IsaacStagePoseResolver(
            self.stage,
            time_code=time_code,
            prims=cached.prims,
        )
        diagnostics = _base_diagnostics(
            stage_id=cached.stage_id,
            timestamp_ms=timestamp_ms,
            cfg=cached.cfg,
            explicit_array_prim_path=array_prim_path,
            explicit_source_prim_path=source_prim_path,
            preferred_array=preferred_array,
            preferred_source=cached.preferred_source,
            time_code=time_code,
        )
        if cached.cfg.robot_base_prim_path is not None:
            diagnostics["robot_base_transform"] = _pose_diagnostics(
                resolver.resolve_world_pose(
                    resolver.prim(cached.cfg.robot_base_prim_path),
                    field_name=cached.cfg.robot_base_prim_path,
                )
            )
        array_specs = []
        for path, reasons in cached.array_entries:
            spec, _ = _array_spec_from_prim(
                resolver.prim(path),
                resolver=resolver,
                cfg=cached.cfg,
                reasons=reasons,
                diagnostics=diagnostics,
            )
            array_specs.append((path, spec))
        source_specs = []
        for path, reasons in cached.source_entries:
            spec, _ = _source_spec_from_prim(
                resolver.prim(path),
                resolver=resolver,
                cfg=cached.cfg,
                reasons=reasons,
                diagnostics=diagnostics,
            )
            source_specs.append((path, spec))
        selected_source_spec = next(
            (
                spec
                for path, spec in source_specs
                if path == cached.selected_source_path
            ),
            None,
        )
        self._cached_selection_diagnostics(
            cached,
            diagnostics,
            array_specs=array_specs,
            source_specs=source_specs,
        )
        diagnostics["discovery_cache"] = self._cache_diagnostics(hit=True)
        self.cached_tick_count += 1
        if diagnostics_out is not None:
            diagnostics_out.clear()
            diagnostics_out.update(diagnostics)
        sources = (
            (selected_source_spec,)
            if cached.preferred_source is not None and selected_source_spec is not None
            else tuple(spec for _, spec in source_specs)
        )
        return AudioSceneSnapshot(
            stage_id=cached.stage_id,
            timestamp_ms=timestamp_ms,
            sources=sources,
            arrays=tuple(spec for _, spec in array_specs),
            room=None,
        )

    def _cached_selection_diagnostics(
        self,
        cached: _CachedDiscovery,
        diagnostics: dict[str, Any],
        *,
        array_specs: list[tuple[str, Any]],
        source_specs: list[tuple[str, Any]],
    ) -> None:
        reasons_by_path = dict(cached.array_entries + cached.source_entries)
        diagnostics["array_count"] = len(array_specs)
        diagnostics["source_count"] = len(source_specs)
        selected_array = next(
            (spec for path, spec in array_specs if path == cached.selected_array_path),
            None,
        )
        selected_source = next(
            (
                spec
                for path, spec in source_specs
                if path == cached.selected_source_path
            ),
            None,
        )
        diagnostics["selected_array"] = (
            None
            if selected_array is None
            else {
                "array_id": selected_array.array_id,
                "prim_path": selected_array.prim_path,
                "reasons": reasons_by_path[selected_array.prim_path],
            }
        )
        diagnostics["selected_source"] = (
            None
            if selected_source is None
            else {
                "source_id": selected_source.source_id,
                "prim_path": selected_source.prim_path,
                "reasons": reasons_by_path[selected_source.prim_path],
            }
        )

    def _cached_paths_resolve(self, cached: _CachedDiscovery) -> bool:
        get_prim = getattr(self.stage, "GetPrimAtPath", None)
        if not callable(get_prim):
            return True
        paths = [path for path, _ in cached.array_entries]
        paths.extend(path for path, _ in cached.source_entries)
        if cached.cfg.robot_base_prim_path is not None:
            paths.append(cached.cfg.robot_base_prim_path)
        for path in paths:
            prim = get_prim(path)
            if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
                self.invalidate(f"missing_prim:{path}")
                return False
        return True

    def _cache_diagnostics(self, *, hit: bool) -> dict[str, Any]:
        return {
            "hit": hit,
            "policy": (
                "rediscover_each_update"
                if self.rediscover_each_update
                else "cache_until_invalidated"
            ),
            "full_discovery_count": self.full_discovery_count,
            "cached_tick_count": self.cached_tick_count,
            "invalidation_reasons": tuple(self.invalidation_reasons),
            "acoustic_refresh_reasons": tuple(self.acoustic_refresh_reasons),
        }

    def _register_usd_listener(self) -> None:
        if self._listener is not None:
            return
        try:
            from pxr import Tf, Usd  # type: ignore
        except ImportError:
            return
        if not isinstance(self.stage, Usd.Stage):
            return
        try:
            self._listener = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self._on_objects_changed,
                self.stage,
            )
        except Exception:  # noqa: BLE001 - listener is best-effort.
            self._listener = None

    def _on_objects_changed(self, notice: Any, _sender: Any) -> None:
        try:
            resynced = tuple(notice.GetResyncedPaths())
        except Exception:  # noqa: BLE001 - treat unknown notices as structural.
            resynced = ("unknown",)
        try:
            info_only = tuple(notice.GetChangedInfoOnlyPaths())
        except Exception:  # noqa: BLE001 - notice variants without the API.
            info_only = ()
        room_geometry_changed = any(
            self._resync_changes_room(path) for path in resynced
        ) or any(self._property_changes_room(path) for path in info_only)
        material_changed = any(
            self._property_changes_material(path) for path in info_only
        )
        if room_geometry_changed:
            self.invalidate("room_geometry_changed")
        if material_changed:
            self.invalidate("material_changed")
        for path in info_only:
            if not _is_pose_property(path) or self._property_changes_room(path):
                continue
            prim_path = _property_prim_path(path)
            if self._is_audio_path(prim_path):
                continue
            if prim_path not in self._pending_non_audio_pose_paths:
                self._pending_non_audio_pose_paths.append(prim_path)
        if resynced:
            self.invalidate("usd_objects_changed_resync")
            return
        acoustic_names = _ROOM_GEOMETRY_PROPERTIES | _MATERIAL_PROPERTIES
        if any(
            _discovery_relevant_property(path)
            and _property_name(path) not in acoustic_names
            for path in info_only
        ):
            self.invalidate("usd_info_only_discovery_attr")

    def _resync_changes_room(self, path: Any) -> bool:
        anchor = self.room_anchor_prim_path
        if anchor is None:
            return False
        changed = str(path).rstrip("/")
        return _paths_overlap(changed, anchor)

    def _property_changes_room(self, path: Any) -> bool:
        anchor = self.room_anchor_prim_path
        if anchor is None:
            return False
        prim_path = _property_prim_path(path)
        name = _property_name(path)
        if name.startswith("xformOp:"):
            return _path_is_same_or_ancestor(prim_path, anchor)
        return name in _ROOM_GEOMETRY_PROPERTIES and _paths_overlap(
            prim_path,
            anchor,
        )

    def _is_audio_path(self, path: str) -> bool:
        cached = self._cached
        if cached is None:
            return False
        audio_paths = tuple(
            entry_path
            for entry_path, _reasons in cached.array_entries + cached.source_entries
        )
        return any(_path_is_same_or_descendant(path, item) for item in audio_paths)

    def _property_changes_material(self, path: Any) -> bool:
        if _property_name(path) not in _MATERIAL_PROPERTIES:
            return False
        prim_path = _property_prim_path(path)
        anchor = self.room_anchor_prim_path
        if anchor is not None and _paths_overlap(prim_path, anchor):
            return True
        return not self._is_audio_path(prim_path)


def _discovery_relevant_property(path: Any) -> bool:
    """Whether an info-only changed path can alter the discovery candidates.

    Pose updates (``xformOp:*``) and other unrelated properties must keep the
    cached path, while ``ias:`` marker attributes and the audio alias
    attributes discovery reads must invalidate it.
    """

    name = _property_name(path)
    if not name:
        return False
    return name.startswith("ias:") or name in _DISCOVERY_ALIAS_PROPERTY_NAMES


def _property_name(path: Any) -> str:
    name = getattr(path, "name", None)
    if isinstance(name, str) and name:
        return name
    get_name = getattr(path, "GetName", None)
    if callable(get_name):
        name = str(get_name())
        if name:
            return name
    _prim, _dot, name = str(path).rpartition(".")
    return name


def _property_prim_path(path: Any) -> str:
    get_prim_path = getattr(path, "GetPrimPath", None)
    if callable(get_prim_path):
        return str(get_prim_path()).rstrip("/")
    prim_path, _dot, _name = str(path).rpartition(".")
    return (prim_path or str(path)).rstrip("/")


def _is_pose_property(path: Any) -> bool:
    return _property_name(path).startswith("xformOp:")


def _path_is_same_or_descendant(path: str, ancestor: str) -> bool:
    resolved_path = path.rstrip("/")
    resolved_ancestor = ancestor.rstrip("/")
    return resolved_path == resolved_ancestor or resolved_path.startswith(
        f"{resolved_ancestor}/"
    )


def _path_is_same_or_ancestor(path: str, descendant: str) -> bool:
    return _path_is_same_or_descendant(descendant, path)


def _paths_overlap(left: str, right: str) -> bool:
    return _path_is_same_or_descendant(left, right) or _path_is_same_or_descendant(
        right,
        left,
    )
