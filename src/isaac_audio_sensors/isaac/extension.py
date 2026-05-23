"""High-level Isaac Sim-facing audio array sensor API."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import AudioSensorConfig, build_scene_snapshot
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.exceptions import IsaacIntegrationUnavailable
from isaac_audio_sensors.core.io.traces import AudioFrameJsonlWriter
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.stage_snapshot import build_stage_snapshot
from isaac_audio_sensors.isaac.viz.debug_draw import IsaacDebugDrawer
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
    build_debug_primitives,
)


@dataclass(slots=True)
class IsaacAudioArraySensor:
    """Lifecycle-capable audio array sensor for Isaac Sim-style stages."""

    array_id: str
    backend: str = "tdoa_synthetic"
    config: AudioSensorConfig | None = None
    stage_snapshot: AudioSceneSnapshot | None = None
    stage: Any | None = None
    array_prim_path: str | None = None
    robot_base_prim_path: str | None = None
    scene_binding_cfg: IsaacAudioSceneBindingCfg | None = None
    usd_time_code_scale: float | None = None
    usd_time_code_offset: float = 0.0
    update_period_s: float = 0.05
    max_events: int | None = None
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS
    ambiguity_policy: str = "none"
    writer: AudioFrameJsonlWriter | None = None
    debug_draw_enabled: bool = False
    debug_drawer: IsaacDebugDrawer | None = None
    latest_frame: AudioSensorFrame | None = field(default=None, init=False)
    latest_debug_primitives: tuple[DebugPrimitive, ...] = field(
        default_factory=tuple,
        init=False,
    )
    _running: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _frame_index: int = field(default=0, init=False)
    _last_update_time_s: float | None = field(default=None, init=False)
    _latest_scene: AudioSceneSnapshot | None = field(default=None, init=False)
    _latest_sensor: MicrophoneArraySpec | None = field(default=None, init=False)
    _latest_stage_diagnostics: dict[str, Any] | None = field(
        default=None,
        init=False,
    )
    _update_subscription: Any | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.update_period_s <= 0.0:
            raise ValueError("update_period_s must be positive.")
        if self.max_events is not None and self.max_events < 0:
            raise ValueError("max_events must be non-negative.")
        if self.usd_time_code_scale is not None and not math.isfinite(
            float(self.usd_time_code_scale)
        ):
            raise ValueError("usd_time_code_scale must be finite.")
        if not math.isfinite(float(self.usd_time_code_offset)):
            raise ValueError("usd_time_code_offset must be finite.")

    @classmethod
    def from_stage(
        cls,
        *,
        stage: Any,
        array_prim_path: str,
        backend: str = "tdoa_synthetic",
        timestamp_ms: int = 0,
        robot_base_prim_path: str | None = None,
        usd_time_code_scale: float | None = None,
        usd_time_code_offset: float = 0.0,
        update_period_s: float = 0.05,
        max_events: int | None = None,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        debug_draw: bool = False,
        writer_path: str | Path | None = None,
    ) -> IsaacAudioArraySensor:
        """Create a live sensor from a real or duck-typed Isaac stage."""

        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=timestamp_ms,
            array_prim_path=array_prim_path,
            robot_base_prim_path=robot_base_prim_path,
        )
        if len(snapshot.arrays) != 1:
            raise ValueError(
                f"Expected exactly one array at {array_prim_path!r}, "
                f"found {len(snapshot.arrays)}."
            )
        return cls(
            array_id=snapshot.arrays[0].array_id,
            backend=backend,
            stage_snapshot=snapshot,
            stage=stage,
            array_prim_path=array_prim_path,
            robot_base_prim_path=robot_base_prim_path,
            usd_time_code_scale=usd_time_code_scale,
            usd_time_code_offset=usd_time_code_offset,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
            debug_draw_enabled=debug_draw,
            writer=(
                None if writer_path is None else AudioFrameJsonlWriter(writer_path)
            ),
        )

    @classmethod
    def from_discovered_stage(
        cls,
        *,
        stage: Any,
        binding_cfg: IsaacAudioSceneBindingCfg | None = None,
        backend: str = "tdoa_synthetic",
        timestamp_ms: int = 0,
        usd_time_code: Any | None = None,
        usd_time_code_scale: float | None = None,
        usd_time_code_offset: float = 0.0,
        update_period_s: float = 0.05,
        max_events: int | None = None,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        debug_draw: bool = False,
        writer_path: str | Path | None = None,
    ) -> IsaacAudioArraySensor:
        """Create a live sensor by discovering arrays and sources on a stage."""

        binding = binding_cfg or IsaacAudioSceneBindingCfg()
        result = discover_stage_audio(
            stage,
            cfg=binding.to_discovery_cfg(),
            timestamp_ms=timestamp_ms,
            usd_time_code=usd_time_code,
            preferred_array=binding.preferred_array,
            preferred_source=binding.preferred_source,
        )
        if result.selected_array is None:
            raise ValueError("No microphone array was discovered for stage binding.")
        sources = (
            (result.selected_source.spec,)
            if binding.preferred_source is not None
            and result.selected_source is not None
            else tuple(source.spec for source in result.sources)
        )
        snapshot = AudioSceneSnapshot(
            stage_id=result.stage_id,
            timestamp_ms=timestamp_ms,
            sources=sources,
            arrays=tuple(array.spec for array in result.arrays),
            room=None,
        )
        return cls(
            array_id=result.selected_array.spec.array_id,
            backend=backend,
            stage_snapshot=snapshot,
            stage=stage,
            robot_base_prim_path=binding.robot_base_prim_path,
            scene_binding_cfg=binding,
            usd_time_code_scale=usd_time_code_scale,
            usd_time_code_offset=usd_time_code_offset,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
            debug_draw_enabled=debug_draw,
            writer=(
                None if writer_path is None else AudioFrameJsonlWriter(writer_path)
            ),
        )

    @classmethod
    def from_config(
        cls,
        *,
        config: AudioSensorConfig,
        array_id: str,
        backend: str | None = None,
        update_period_s: float = 0.05,
        max_events: int | None = None,
    ) -> IsaacAudioArraySensor:
        """Create an offline sensor facade from validated config."""

        if array_id not in config.arrays:
            raise KeyError(f"Unknown array id {array_id!r}.")
        return cls(
            array_id=array_id,
            backend=backend or config.default_backend,
            config=config,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=config.speed_of_sound_mps,
            ambiguity_policy=config.tdoa_ambiguity_policy,
        )

    def start(
        self,
        *,
        subscribe_to_update_stream: bool = False,
    ) -> IsaacAudioArraySensor:
        """Start the sensor and optionally subscribe to Isaac Kit update ticks."""

        self._raise_if_closed()
        self._running = True
        if subscribe_to_update_stream:
            self._update_subscription = self._subscribe_to_isaac_updates()
        return self

    def stop(self) -> None:
        """Stop update-loop capture without discarding the latest frame."""

        self._running = False
        self._update_subscription = None

    def reset(self) -> None:
        """Reset frame counters and buffered output."""

        self._raise_if_closed()
        self._frame_index = 0
        self._last_update_time_s = None
        self.latest_frame = None
        self.latest_debug_primitives = ()
        self._latest_scene = None
        self._latest_sensor = None

    def close(self) -> None:
        """Stop the sensor and close any package writer fallback."""

        self.stop()
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self.debug_drawer is not None:
            self.debug_drawer.close()
            self.debug_drawer = None
        self.latest_debug_primitives = ()
        self._closed = True

    def get_latest_frame(self) -> AudioSensorFrame | None:
        """Return the most recently emitted frame."""

        return self.latest_frame

    def configure_writer(self, path: str | Path) -> AudioFrameJsonlWriter:
        """Configure a JSONL writer for frames emitted by ``update``."""

        self._raise_if_closed()
        self.writer = AudioFrameJsonlWriter(path)
        return self.writer

    def update(
        self,
        *,
        sim_time_s: float | None = None,
        dt: float | None = None,
        timestamp_ms: int | None = None,
        usd_time_code: Any | None = None,
        force: bool = False,
    ) -> AudioSensorFrame:
        """Capture a repeatable live frame for one update-loop tick."""

        self._raise_if_closed()
        if not self._running and not force:
            raise RuntimeError("IsaacAudioArraySensor.update requires start() first.")
        update_time_s = self._resolve_update_time(sim_time_s=sim_time_s, dt=dt)
        if (
            not force
            and self.latest_frame is not None
            and self._last_update_time_s is not None
            and update_time_s - self._last_update_time_s < self.update_period_s
        ):
            return self.latest_frame

        timestamp = (
            int(timestamp_ms)
            if timestamp_ms is not None
            else int(round(update_time_s * 1000.0))
        )
        window_s = dt if dt is not None and dt > 0.0 else self.update_period_s
        frame = self.capture(
            timestamp_ms=timestamp,
            start_time_s=update_time_s,
            end_time_s=update_time_s + window_s,
            frame_index=self._frame_index,
            max_events=self.max_events,
            usd_time_code=self._resolve_usd_time_code(
                explicit_time_code=usd_time_code,
                sim_time_s=update_time_s,
                timestamp_ms=timestamp,
            ),
        )

        self.latest_frame = frame
        self._last_update_time_s = update_time_s
        self._frame_index += 1
        if self.writer is not None:
            self.writer.write(frame)
        if self.debug_draw_enabled:
            self.latest_debug_primitives = self._emit_debug_primitives(frame)
        return frame

    def capture(
        self,
        *,
        timestamp_ms: int,
        start_time_s: float = 0.0,
        end_time_s: float = 1.0,
        frame_index: int | None = 0,
        max_events: int | None = None,
        source_prim_path: str | None = None,
        usd_time_code: Any | None = None,
    ) -> AudioSensorFrame:
        """Capture one deterministic offline frame."""

        scene = self._scene_for_capture(
            timestamp_ms=timestamp_ms,
            source_prim_path=source_prim_path,
            usd_time_code=(
                usd_time_code
                if usd_time_code is not None or self.stage is None
                else self._resolve_usd_time_code(
                    explicit_time_code=None,
                    sim_time_s=None,
                    timestamp_ms=timestamp_ms,
                )
            ),
        )
        sensor = scene.array_by_id(self.array_id)
        time_window = AudioTimeWindow(
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            timestamp_ms=timestamp_ms,
            sample_rate_hz=sensor.sample_rate_hz,
            frame_index=frame_index,
            max_events=self.max_events if max_events is None else max_events,
        )
        kwargs = {}
        if self.backend in {"tdoa_synthetic", "room_acoustics"}:
            kwargs = {
                "speed_of_sound_mps": self.speed_of_sound_mps,
                "ambiguity_policy": self.ambiguity_policy,
            }
        backend = get_backend(self.backend, **kwargs)
        frame = backend.simulate(scene, sensor, time_window)
        if self.stage is not None:
            frame = replace(
                frame,
                provenance="isaac_live",
                diagnostics={
                    **frame.diagnostics,
                    "stage_snapshot": self._latest_stage_diagnostics or {},
                },
            )
        self._latest_scene = scene
        self._latest_sensor = sensor
        return frame

    def _scene_for_capture(
        self,
        *,
        timestamp_ms: int,
        source_prim_path: str | None,
        usd_time_code: Any | None,
    ) -> AudioSceneSnapshot:
        if self.stage is not None:
            if self.scene_binding_cfg is not None:
                binding = self.scene_binding_cfg
                diagnostics: dict[str, Any] = {}
                scene = build_stage_snapshot(
                    self.stage,
                    timestamp_ms=timestamp_ms,
                    robot_base_prim_path=binding.robot_base_prim_path,
                    source_prim_path=source_prim_path,
                    usd_time_code=usd_time_code,
                    discovery_cfg=binding.to_discovery_cfg(),
                    preferred_array=binding.preferred_array,
                    preferred_source=binding.preferred_source,
                    diagnostics_out=diagnostics,
                )
                self._latest_stage_diagnostics = diagnostics
            elif self.array_prim_path is None:
                raise RuntimeError("Live Isaac stage sensor has no array prim path.")
            else:
                diagnostics = {}
                scene = build_stage_snapshot(
                    self.stage,
                    timestamp_ms=timestamp_ms,
                    array_prim_path=self.array_prim_path,
                    robot_base_prim_path=self.robot_base_prim_path,
                    source_prim_path=source_prim_path,
                    usd_time_code=usd_time_code,
                    diagnostics_out=diagnostics,
                )
                self._latest_stage_diagnostics = diagnostics
        elif self.config is not None:
            scene = build_scene_snapshot(self.config, timestamp_ms=timestamp_ms)
            self._latest_stage_diagnostics = None
        elif self.stage_snapshot is not None:
            scene = AudioSceneSnapshot(
                stage_id=self.stage_snapshot.stage_id,
                timestamp_ms=timestamp_ms,
                sources=self.stage_snapshot.sources,
                arrays=self.stage_snapshot.arrays,
                room=self.stage_snapshot.room,
            )
            self._latest_stage_diagnostics = None
        else:
            raise RuntimeError("IsaacAudioArraySensor has no config or stage snapshot.")

        if source_prim_path is None:
            return scene
        sources = tuple(
            source for source in scene.sources if source.prim_path == source_prim_path
        )
        if not sources:
            raise ValueError(f"No source prim found at {source_prim_path!r}.")
        return AudioSceneSnapshot(
            stage_id=scene.stage_id,
            timestamp_ms=scene.timestamp_ms,
            sources=sources,
            arrays=scene.arrays,
            room=scene.room,
        )

    def _resolve_update_time(
        self,
        *,
        sim_time_s: float | None,
        dt: float | None,
    ) -> float:
        if sim_time_s is not None:
            return float(sim_time_s)
        if dt is not None:
            if dt <= 0.0:
                raise ValueError("dt must be positive when provided.")
            return (self._last_update_time_s or 0.0) + float(dt)
        timeline_time = _current_isaac_timeline_time_s()
        if timeline_time is not None:
            return timeline_time
        return (
            0.0
            if self._last_update_time_s is None
            else self._last_update_time_s + self.update_period_s
        )

    def _resolve_usd_time_code(
        self,
        *,
        explicit_time_code: Any | None,
        sim_time_s: float | None,
        timestamp_ms: int,
    ) -> Any | None:
        if explicit_time_code is not None:
            return explicit_time_code
        if self.usd_time_code_scale is not None:
            base_time_s = (
                float(sim_time_s)
                if sim_time_s is not None
                else float(timestamp_ms) / 1000.0
            )
            return base_time_s * float(self.usd_time_code_scale) + float(
                self.usd_time_code_offset
            )
        if sim_time_s is not None:
            return sim_time_s
        return float(timestamp_ms) / 1000.0

    def _emit_debug_primitives(
        self,
        frame: AudioSensorFrame,
    ) -> tuple[DebugPrimitive, ...]:
        if self._latest_scene is None or self._latest_sensor is None:
            return ()
        primitives = build_debug_primitives(
            frame=frame,
            scene=self._latest_scene,
            sensor=self._latest_sensor,
        )
        if self.debug_drawer is None:
            self.debug_drawer = IsaacDebugDrawer()
        try:
            return self.debug_drawer.draw(primitives)
        except IsaacIntegrationUnavailable:
            self.debug_drawer.last_primitives = primitives
            return primitives

    def _subscribe_to_isaac_updates(self) -> Any:
        try:
            import omni.kit.app  # type: ignore
        except ImportError as exc:
            raise IsaacIntegrationUnavailable(
                "Isaac update-stream subscription requires omni.kit.app inside "
                "an Isaac Sim Python environment."
            ) from exc
        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()

        def _on_update(_event: Any) -> None:
            if self._running:
                self.update(force=True)

        return stream.create_subscription_to_pop(
            _on_update,
            name="isaac_audio_sensors.update",
        )

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError("IsaacAudioArraySensor is closed.")


def _current_isaac_timeline_time_s() -> float | None:
    try:
        import omni.timeline  # type: ignore
    except ImportError:
        return None
    timeline = omni.timeline.get_timeline_interface()
    if hasattr(timeline, "get_current_time"):
        return float(timeline.get_current_time())
    if hasattr(timeline, "get_current_time_seconds"):
        return float(timeline.get_current_time_seconds())
    return None
