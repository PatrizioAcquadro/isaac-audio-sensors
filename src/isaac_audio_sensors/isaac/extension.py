"""High-level Isaac Sim-facing audio array sensor API."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from isaac_audio_sensors.core.acoustics.materials import resolve_material
from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.config import AudioSensorConfig, build_scene_snapshot
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects.config import (
    EffectsConfig,
    UnsupportedEffectError,
    validate_motion_effects_config,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    IsaacIntegrationUnavailable,
)
from isaac_audio_sensors.core.io.traces import AudioFrameJsonlWriter
from isaac_audio_sensors.core.io.waveforms import (
    ContinuousWaveformWriter,
    FrameWaveformWriter,
    WaveformSink,
    waveform_safe_filename,
)
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    WindowMotionPlan,
    build_window_motion,
    validate_pose_observation,
)
from isaac_audio_sensors.core.room_anchor import room_spec_from_bounds
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
    RoomAcousticsSpec,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.occlusion import (
    DEFAULT_OCCLUSION_ATTENUATION_CAP_DB,
    DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
    OCCLUSION_MODEL_RAYCAST_TRANSMISSION,
    IsaacPhysxRaycaster,
    UsdTransmissionLossResolver,
    compute_scene_occlusion,
)
from isaac_audio_sensors.isaac.stage_cache import StageAudioCache
from isaac_audio_sensors.isaac.stage_snapshot import (
    build_stage_snapshot,
    enrich_snapshot_motion,
)
from isaac_audio_sensors.isaac.viz.debug_draw import IsaacDebugDrawer
from isaac_audio_sensors.isaac.viz.overlays import (
    DebugPrimitive,
    build_debug_primitives,
)
from isaac_audio_sensors.usd_bounds import (
    ABSORPTION_ATTR,
    DEFAULT_SEMANTIC_ABSORPTION,
    MATERIAL_ATTR,
    prim_attributes,
    resolve_room_absorption,
    world_aligned_bbox,
)


@dataclass(slots=True)
class IsaacAudioArraySensor:
    """Lifecycle-capable audio array sensor for Isaac Sim-style stages."""

    array_id: str
    backend: str = "tdoa_synthetic"
    config: AudioSensorConfig | None = None
    effects: EffectsConfig = field(default_factory=EffectsConfig)
    stage_snapshot: AudioSceneSnapshot | None = None
    stage: Any | None = None
    room: RoomAcousticsSpec | None = None
    array_prim_path: str | None = None
    source_prim_path: str | None = None
    robot_base_prim_path: str | None = None
    scene_binding_cfg: IsaacAudioSceneBindingCfg | None = None
    usd_time_code_scale: float | None = None
    usd_time_code_offset: float = 0.0
    update_period_s: float = 0.05
    max_events: int | None = None
    speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS
    ambiguity_policy: str = "none"
    writer: AudioFrameJsonlWriter | None = None
    waveform_dir: str | Path | None = None
    waveform_mode: str = "per_frame"
    debug_draw_enabled: bool = False
    debug_drawer: IsaacDebugDrawer | None = None
    occlusion_enabled: bool = False
    occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB
    occlusion_attenuation_cap_db: float = DEFAULT_OCCLUSION_ATTENUATION_CAP_DB
    occlusion_raycaster: Any | None = None
    occlusion_transmission_resolver: Any | None = None
    latest_frame: AudioSensorFrame | None = field(default=None, init=False)
    _waveform_sink: WaveformSink | None = field(default=None, init=False)
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
    _timeline_subscription: Any | None = field(default=None, init=False)
    _stage_cache: StageAudioCache | None = field(default=None, init=False)
    _pose_history: PoseHistory | None = field(default=None, init=False)
    _pose_history_stage: Any | None = field(default=None, init=False)
    _motion_entity_paths: dict[str, str] = field(default_factory=dict, init=False)
    _anchor_room_template: RoomAcousticsSpec | None = field(default=None, init=False)
    _previous_occlusion_pairs: dict[tuple[str, str], tuple[Any, ...]] = field(
        default_factory=dict,
        init=False,
    )
    _has_previous_occlusion_capture: bool = field(default=False, init=False)
    _pending_occlusion_pairs: dict[tuple[str, str], tuple[Any, ...]] | None = field(
        default=None,
        init=False,
    )
    _frame_acoustics_state: dict[str, Any] | None = field(default=None, init=False)
    _reset_listeners: list[Callable[[], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.room is not None and self.room.anchor_prim_path is not None:
            self._anchor_room_template = self.room
        validate_motion_effects_config(self.effects.motion)
        if self.effects.motion.segments_per_window > 1:
            if not self.effects.motion.derive_velocity_from_poses:
                raise UnsupportedEffectError(
                    "audio.effects.motion.segments_per_window>1 requires "
                    "derive_velocity_from_poses=true."
                )
            if self.backend not in {"room_acoustics", "room_acoustics_srp"}:
                raise UnsupportedEffectError(
                    "audio.effects.motion.segments_per_window>1 requires "
                    "room_acoustics or room_acoustics_srp."
                )
            if self.config is not None and self.config.runtime_profile != (
                "waveform_fidelity"
            ):
                raise UnsupportedEffectError(
                    "audio.effects.motion.segments_per_window>1 requires "
                    "runtime profile 'waveform_fidelity'."
                )
        if self.effects.motion.derive_velocity_from_poses:
            if self.stage is None:
                raise UnsupportedEffectError(
                    "audio.effects.motion.derive_velocity_from_poses=true requires "
                    "a live Isaac stage pose-time stream; configuration-only and "
                    "offline sensors are unsupported."
                )
            if self.stage_snapshot is not None and any(
                source.source_id == self.array_id
                for source in self.stage_snapshot.sources
            ):
                raise ConfigValidationError(
                    "audio.effects.motion.derive_velocity_from_poses=true cannot "
                    f"represent source/selected-array id collision {self.array_id!r}."
                )
            self._pose_history = PoseHistory(
                teleport_speed_threshold_mps=(
                    self.effects.motion.teleport_speed_threshold_mps
                ),
                stale_time_s=self.effects.motion.stale_time_s,
                smoothing_alpha=self.effects.motion.smoothing_alpha,
            )
            self._pose_history_stage = self.stage
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
        if self.waveform_mode not in {"per_frame", "session"}:
            raise ValueError("waveform_mode must be 'per_frame' or 'session'.")
        if (
            not math.isfinite(float(self.occlusion_max_attenuation_db))
            or float(self.occlusion_max_attenuation_db) < 0.0
        ):
            raise ValueError(
                "occlusion_max_attenuation_db must be finite and non-negative."
            )

    @classmethod
    def from_stage(
        cls,
        *,
        stage: Any,
        array_prim_path: str,
        source_prim_path: str | None = None,
        backend: str = "tdoa_synthetic",
        timestamp_ms: int = 0,
        robot_base_prim_path: str | None = None,
        usd_time_code_scale: float | None = None,
        usd_time_code_offset: float = 0.0,
        update_period_s: float = 0.05,
        max_events: int | None = None,
        speed_of_sound_mps: float = DEFAULT_SPEED_OF_SOUND_MPS,
        ambiguity_policy: str = "none",
        room: RoomAcousticsSpec | None = None,
        debug_draw: bool = False,
        occlusion_enabled: bool = False,
        occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
        occlusion_raycaster: Any | None = None,
        writer_path: str | Path | None = None,
        waveform_dir: str | Path | None = None,
        waveform_mode: str = "per_frame",
        effects: EffectsConfig | None = None,
    ) -> IsaacAudioArraySensor:
        """Create a live sensor from a real or duck-typed Isaac stage."""

        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=timestamp_ms,
            array_prim_path=array_prim_path,
            source_prim_path=source_prim_path,
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
            effects=EffectsConfig() if effects is None else effects,
            stage_snapshot=snapshot,
            stage=stage,
            room=room,
            array_prim_path=array_prim_path,
            source_prim_path=source_prim_path,
            robot_base_prim_path=robot_base_prim_path,
            usd_time_code_scale=usd_time_code_scale,
            usd_time_code_offset=usd_time_code_offset,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
            debug_draw_enabled=debug_draw,
            occlusion_enabled=occlusion_enabled,
            occlusion_max_attenuation_db=occlusion_max_attenuation_db,
            occlusion_raycaster=occlusion_raycaster,
            writer=(
                None if writer_path is None else AudioFrameJsonlWriter(writer_path)
            ),
            waveform_dir=waveform_dir,
            waveform_mode=waveform_mode,
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
        room: RoomAcousticsSpec | None = None,
        debug_draw: bool = False,
        occlusion_enabled: bool = False,
        occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
        occlusion_raycaster: Any | None = None,
        writer_path: str | Path | None = None,
        waveform_dir: str | Path | None = None,
        waveform_mode: str = "per_frame",
        effects: EffectsConfig | None = None,
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
            effects=EffectsConfig() if effects is None else effects,
            stage_snapshot=snapshot,
            stage=stage,
            room=room,
            robot_base_prim_path=binding.robot_base_prim_path,
            scene_binding_cfg=binding,
            usd_time_code_scale=usd_time_code_scale,
            usd_time_code_offset=usd_time_code_offset,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=speed_of_sound_mps,
            ambiguity_policy=ambiguity_policy,
            debug_draw_enabled=debug_draw,
            occlusion_enabled=occlusion_enabled,
            occlusion_max_attenuation_db=occlusion_max_attenuation_db,
            occlusion_raycaster=occlusion_raycaster,
            writer=(
                None if writer_path is None else AudioFrameJsonlWriter(writer_path)
            ),
            waveform_dir=waveform_dir,
            waveform_mode=waveform_mode,
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
        if config.effects.motion.derive_velocity_from_poses:
            raise UnsupportedEffectError(
                "audio.effects.motion.derive_velocity_from_poses=true requires a "
                "live Isaac stage pose-time stream; from_config is offline."
            )
        return cls(
            array_id=array_id,
            backend=backend or config.default_backend,
            config=config,
            effects=config.effects,
            update_period_s=update_period_s,
            max_events=max_events,
            speed_of_sound_mps=config.speed_of_sound_mps,
            ambiguity_policy=config.tdoa_ambiguity_policy,
            waveform_dir=(
                (config.waveform_dir or "outputs/audio_waveforms")
                if config.write_waveforms
                else None
            ),
        )

    def start(
        self,
        *,
        subscribe_to_update_stream: bool = False,
    ) -> IsaacAudioArraySensor:
        """Start the sensor and optionally subscribe to Isaac Kit update ticks."""

        self._raise_if_closed()
        self._running = True
        if self.effects.motion.segments_per_window > 1:
            self._prime_piecewise_motion()
        if subscribe_to_update_stream:
            self._update_subscription = self._subscribe_to_isaac_updates()
            if self._pose_history is not None:
                self._timeline_subscription = self._subscribe_to_timeline_events()
        return self

    def _prime_piecewise_motion(self) -> None:
        """Observe current live poses once without emitting a backend frame."""

        if self.stage is None or self._pose_history is None:
            raise UnsupportedEffectError(
                "piecewise motion requires a live stage pose-time stream"
            )
        prime_time_s = _current_isaac_timeline_time_s()
        if prime_time_s is None:
            prime_time_s = 0.0
        if not math.isfinite(prime_time_s):
            raise ValueError("piecewise motion prime time must be finite")
        timestamp_ms = int(round(prime_time_s * 1000.0))
        self._scene_for_capture(
            timestamp_ms=timestamp_ms,
            source_prim_path=self.source_prim_path,
            usd_time_code=self._resolve_usd_time_code(
                explicit_time_code=None,
                sim_time_s=prime_time_s,
                timestamp_ms=timestamp_ms,
            ),
            sim_time_s=prime_time_s,
        )
        self._last_update_time_s = prime_time_s

    def stop(self) -> None:
        """Stop update-loop capture without discarding the latest frame."""

        self._running = False
        self._update_subscription = None
        self._timeline_subscription = None

    def reset(self) -> None:
        """Reset frame counters and buffered output, starting a new session."""

        self._raise_if_closed()
        self._frame_index = 0
        self._last_update_time_s = None
        if self._waveform_sink is not None:
            self._waveform_sink.close()
            self._waveform_sink = None
        self.latest_frame = None
        self.latest_debug_primitives = ()
        self._latest_scene = None
        self._latest_sensor = None
        self._previous_occlusion_pairs.clear()
        self._has_previous_occlusion_capture = False
        self._pending_occlusion_pairs = None
        self._frame_acoustics_state = None
        if self._stage_cache is not None:
            self._stage_cache.reset_acoustic_state()
        if self._pose_history is not None:
            self._pose_history.reset()
            self._motion_entity_paths.clear()
        for listener in tuple(self._reset_listeners):
            listener()

    def _add_reset_listener(self, listener: Callable[[], None]) -> None:
        """Attach an internal observer to the completed sensor reset lifecycle."""

        if listener not in self._reset_listeners:
            self._reset_listeners.append(listener)

    def close(self) -> None:
        """Stop the sensor and close any package writer fallback."""

        self.stop()
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self._waveform_sink is not None:
            self._waveform_sink.close()
            self._waveform_sink = None
        if self.debug_drawer is not None:
            self.debug_drawer.close()
            self.debug_drawer = None
        if self._stage_cache is not None:
            self._stage_cache.close()
            self._stage_cache = None
        self._previous_occlusion_pairs.clear()
        self._has_previous_occlusion_capture = False
        self._pending_occlusion_pairs = None
        self._frame_acoustics_state = None
        if self._pose_history is not None:
            self._pose_history.reset()
            self._pose_history = None
            self._motion_entity_paths.clear()
            self._pose_history_stage = None
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
        if not math.isfinite(update_time_s):
            raise ValueError("simulation update time must be finite")
        if (
            self._last_update_time_s is not None
            and update_time_s < self._last_update_time_s
        ):
            raise ValueError("simulation update time is non-monotonic")
        if (
            force
            and self.effects.motion.segments_per_window > 1
            and self._last_update_time_s is not None
            and update_time_s - self._last_update_time_s < self.update_period_s
            and not math.isclose(
                update_time_s - self._last_update_time_s,
                self.update_period_s,
                rel_tol=1e-9,
            )
        ):
            raise ValueError(
                "forced update time duplicates or overlaps the prior capture window"
            )
        if (
            not force
            and self._last_update_time_s is not None
            and update_time_s - self._last_update_time_s < self.update_period_s
        ):
            if self.latest_frame is None:
                raise ValueError(
                    "capture time duplicates the piecewise-motion prime sample"
                )
            return self.latest_frame

        piecewise = self.effects.motion.segments_per_window > 1
        window_s = (
            self.update_period_s
            if piecewise
            else (dt if dt is not None and dt > 0.0 else self.update_period_s)
        )
        start_time_s = update_time_s - window_s if piecewise else update_time_s
        end_time_s = update_time_s if piecewise else update_time_s + window_s
        timestamp = (
            int(timestamp_ms)
            if timestamp_ms is not None
            else int(round(start_time_s * 1000.0))
        )
        frame = self.capture(
            timestamp_ms=timestamp,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            frame_index=self._frame_index,
            max_events=self.max_events,
            usd_time_code=self._resolve_usd_time_code(
                explicit_time_code=usd_time_code,
                sim_time_s=update_time_s,
                timestamp_ms=timestamp,
            ),
            sim_time_s=update_time_s,
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
        sim_time_s: float | None = None,
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
            sim_time_s=sim_time_s,
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
        window_motion: WindowMotionPlan | None = None
        if self.effects.motion.segments_per_window > 1:
            window_motion = self._build_window_motion(scene, sensor, time_window)
        kwargs: dict[str, Any] = {}
        if self.backend in {"tdoa_synthetic", "room_acoustics", "room_acoustics_srp"}:
            kwargs = {
                "speed_of_sound_mps": self.speed_of_sound_mps,
                "ambiguity_policy": self.ambiguity_policy,
            }
        if self.backend in {"room_acoustics", "room_acoustics_srp"}:
            sink = self._resolve_waveform_sink()
            if sink is not None:
                kwargs["waveform_writer"] = sink
        if not self.effects.all_disabled:
            kwargs["effects"] = self.effects
        if window_motion is not None:
            kwargs["window_motion"] = window_motion
        backend = get_backend(self.backend, **kwargs)
        frame = backend.simulate(scene, sensor, time_window)
        frame = self._merge_acoustics_state(frame)
        if self.stage is not None:
            stage_diagnostics = dict(self._latest_stage_diagnostics or {})
            motion_diagnostics = stage_diagnostics.pop("motion", None)
            diagnostics = {
                **frame.diagnostics,
                "stage_snapshot": stage_diagnostics,
            }
            if motion_diagnostics is not None:
                backend_motion = diagnostics.get("motion")
                diagnostics["motion"] = {
                    **(backend_motion if isinstance(backend_motion, dict) else {}),
                    **motion_diagnostics,
                }
            frame = replace(
                frame,
                provenance="isaac_live",
                diagnostics=diagnostics,
            )
        self._latest_scene = scene
        self._latest_sensor = sensor
        return frame

    def _build_window_motion(
        self,
        scene: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
        time_window: AudioTimeWindow,
    ) -> WindowMotionPlan:
        history = self._pose_history
        if history is None:
            raise UnsupportedEffectError(
                "piecewise motion requires an owned live PoseHistory"
            )
        stage_motion = (self._latest_stage_diagnostics or {}).get("motion")
        velocity_sources = (
            stage_motion.get("velocity_source")
            if isinstance(stage_motion, dict)
            else None
        )
        if not isinstance(velocity_sources, dict):
            raise ValueError("piecewise motion has no velocity-source diagnostics")
        entities: dict[str, EntityMotionInput] = {
            source.source_id: EntityMotionInput(
                position_world_m=source.position_world,
                velocity_world_mps=source.velocity_world_mps,
                velocity_source=str(velocity_sources[source.source_id]),
            )
            for source in scene.sources
        }
        entities[sensor.array_id] = EntityMotionInput(
            position_world_m=sensor.position_world,
            velocity_world_mps=sensor.velocity_world_mps,
            velocity_source=str(velocity_sources[sensor.array_id]),
        )
        window_sample_count = round(
            (time_window.end_time_s - time_window.start_time_s)
            * time_window.sample_rate_hz
        )
        if self.effects.motion.segments_per_window > window_sample_count:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window must be no greater "
                f"than window_sample_count={window_sample_count}."
            )
        return build_window_motion(
            history,
            entities=entities,
            start_time_s=time_window.start_time_s,
            sample_rate_hz=time_window.sample_rate_hz,
            window_sample_count=window_sample_count,
            segments_per_window=self.effects.motion.segments_per_window,
        )

    def rediscover(self) -> None:
        """Force full stage re-discovery (one Traverse) on the next capture."""

        if self._stage_cache is not None:
            self._stage_cache.rediscover()

    def _ensure_stage_cache(self) -> StageAudioCache:
        if (
            self._pose_history_stage is not None
            and self._pose_history_stage is not self.stage
        ):
            if self._pose_history is not None:
                self._pose_history.reset()
                self._motion_entity_paths.clear()
            self._previous_occlusion_pairs.clear()
            self._has_previous_occlusion_capture = False
            self._pending_occlusion_pairs = None
            self._frame_acoustics_state = None
            if self._stage_cache is not None:
                self._stage_cache.reset_acoustic_state()
            self._timeline_subscription = None
            self._pose_history_stage = self.stage
        if self._stage_cache is not None and self._stage_cache.stage is not self.stage:
            self._stage_cache.close()
            self._stage_cache = None
            self._previous_occlusion_pairs.clear()
            self._has_previous_occlusion_capture = False
            self._pending_occlusion_pairs = None
            self._frame_acoustics_state = None
        if self._stage_cache is None:
            rediscover_each_update = (
                self.scene_binding_cfg is not None
                and self.scene_binding_cfg.rediscover_each_update
            )
            self._stage_cache = StageAudioCache(
                self.stage,
                rediscover_each_update=rediscover_each_update,
                room_anchor_prim_path=(
                    None if self.room is None else self.room.anchor_prim_path
                ),
            )
        return self._stage_cache

    def _resolve_waveform_sink(self) -> WaveformSink | None:
        """Build the waveform sink on first use when waveform_dir is set."""

        if self.waveform_dir is None:
            return None
        if self._waveform_sink is None:
            if self.waveform_mode == "session":
                session_name = waveform_safe_filename(self.array_id)
                self._waveform_sink = ContinuousWaveformWriter(
                    Path(self.waveform_dir) / f"{session_name}_session.wav"
                )
            else:
                self._waveform_sink = FrameWaveformWriter(self.waveform_dir)
        return self._waveform_sink

    def _scene_for_capture(
        self,
        *,
        timestamp_ms: int,
        source_prim_path: str | None,
        usd_time_code: Any | None,
        sim_time_s: float | None,
    ) -> AudioSceneSnapshot:
        self._frame_acoustics_state = None
        self._pending_occlusion_pairs = None
        effective_source_prim_path = source_prim_path or self.source_prim_path
        if self.stage is not None:
            cache = self._ensure_stage_cache()
            if self.scene_binding_cfg is not None:
                binding = self.scene_binding_cfg
                diagnostics: dict[str, Any] = {}
                scene = cache.snapshot(
                    timestamp_ms=timestamp_ms,
                    robot_base_prim_path=binding.robot_base_prim_path,
                    source_prim_path=effective_source_prim_path,
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
                scene = cache.snapshot(
                    timestamp_ms=timestamp_ms,
                    array_prim_path=self.array_prim_path,
                    robot_base_prim_path=self.robot_base_prim_path,
                    source_prim_path=effective_source_prim_path,
                    usd_time_code=usd_time_code,
                    diagnostics_out=diagnostics,
                )
                self._latest_stage_diagnostics = diagnostics
            self._refresh_anchored_room_if_needed(
                cache,
                time_code=usd_time_code,
            )
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

        if self.room is not None:
            scene = replace(scene, room=self.room)

        if effective_source_prim_path is not None:
            sources = tuple(
                source
                for source in scene.sources
                if source.prim_path == effective_source_prim_path
            )
            if not sources:
                raise ValueError(
                    f"No source prim found at {effective_source_prim_path!r}."
                )
            scene = replace(scene, sources=sources)
        if self.effects.motion.derive_velocity_from_poses:
            if sim_time_s is None:
                raise ValueError(
                    "Enabled pose derivation requires a finite explicit sim_time_s "
                    "for direct live capture."
                )
            scene = self._enrich_live_motion(scene, time_s=sim_time_s)
        return self._apply_occlusion(scene)

    def _refresh_anchored_room_if_needed(
        self,
        cache: StageAudioCache,
        *,
        time_code: Any | None,
    ) -> None:
        """Rebuild an anchor-derived room after frozen acoustic invalidations."""

        template = self._anchor_room_template
        if template is None or template.anchor_prim_path is None:
            return
        reasons = cache.current_acoustic_refresh_reasons
        if not any(
            reason in {"room_geometry_changed", "material_changed"}
            for reason in reasons
        ):
            return
        anchor_path = template.anchor_prim_path
        get_prim = getattr(self.stage, "GetPrimAtPath", None)
        prim = get_prim(anchor_path) if callable(get_prim) else None
        if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
            raise ValueError(
                f"Room anchor {anchor_path!r} is missing after "
                "room_geometry_changed/material_changed; the previous room "
                "cannot be reused."
            )
        minimum, maximum = world_aligned_bbox(
            prim,
            prim_path=anchor_path,
            time_code=time_code,
        )
        absorption = self._resolve_anchor_absorption(
            prim,
            template=template,
            time_code=time_code,
        )
        self.room = room_spec_from_bounds(
            min_world=minimum,
            max_world=maximum,
            room_id=template.room_id,
            absorption=absorption,
            max_order=template.max_order,
            out_of_bounds=template.out_of_bounds,
            anchor_prim_path=anchor_path,
            air_absorption=template.air_absorption,
            ray_tracing=template.ray_tracing,
        )

    @staticmethod
    def _resolve_anchor_absorption(
        prim: Any,
        *,
        template: RoomAcousticsSpec,
        time_code: Any | None,
    ) -> float | dict[str, float] | str:
        attrs = prim_attributes(prim, time_code=time_code)
        explicit = attrs.get(ABSORPTION_ATTR)
        if explicit is not None:
            if isinstance(explicit, dict):
                return {str(key): float(value) for key, value in explicit.items()}
            return float(explicit)
        acoustic_id = attrs.get("ias:acoustic_material_id")
        if acoustic_id is not None:
            return resolve_material(
                str(acoustic_id),
                application=f"room anchor {template.anchor_prim_path!r}",
            ).material_id
        material_id = attrs.get(MATERIAL_ATTR)
        if material_id is not None and str(material_id).strip():
            try:
                return resolve_material(
                    str(material_id),
                    application=f"room anchor {template.anchor_prim_path!r}",
                ).material_id
            except ValueError:
                pass
        absorption, _provenance = resolve_room_absorption(
            prim,
            semantic_absorption=dict(DEFAULT_SEMANTIC_ABSORPTION),
            default=template.absorption,
            time_code=time_code,
        )
        return absorption

    def _enrich_live_motion(
        self,
        scene: AudioSceneSnapshot,
        *,
        time_s: float,
    ) -> AudioSceneSnapshot:
        history = self._pose_history
        if history is None:
            raise RuntimeError("Enabled pose derivation has no PoseHistory.")
        selected_array = scene.array_by_id(self.array_id)
        if any(source.source_id == self.array_id for source in scene.sources):
            raise ConfigValidationError(
                "audio.effects.motion.derive_velocity_from_poses=true cannot "
                f"represent source/selected-array id collision {self.array_id!r}."
            )
        observations = tuple(
            (
                source.source_id,
                source.position_world,
                source.orientation_world_quat,
            )
            for source in scene.sources
        ) + (
            (
                selected_array.array_id,
                selected_array.position_world,
                selected_array.orientation_world_quat,
            ),
        )
        for entity_id, position, orientation in observations:
            validate_pose_observation(entity_id, time_s, position, orientation)

        current_paths = {source.source_id: source.prim_path for source in scene.sources}
        current_paths[selected_array.array_id] = selected_array.prim_path
        for entity_id, previous_path in tuple(self._motion_entity_paths.items()):
            if current_paths.get(entity_id) != previous_path:
                history.remove_entity(entity_id)

        enriched, velocity_sources = enrich_snapshot_motion(
            scene,
            selected_array_id=self.array_id,
            time_s=time_s,
            pose_history=history,
            motion_config=self.effects.motion,
        )
        self._motion_entity_paths = current_paths
        if self._latest_stage_diagnostics is None:
            self._latest_stage_diagnostics = {}
        self._latest_stage_diagnostics["motion"] = {"velocity_source": velocity_sources}
        return enriched

    def _apply_occlusion(self, scene: AudioSceneSnapshot) -> AudioSceneSnapshot:
        """Attach Isaac-raycast occlusion records to a live snapshot."""

        if not self.occlusion_enabled or self.stage is None:
            return scene
        try:
            if self.occlusion_raycaster is None:
                self.occlusion_raycaster = IsaacPhysxRaycaster()
            if self.occlusion_transmission_resolver is None:
                self.occlusion_transmission_resolver = UsdTransmissionLossResolver(
                    self.stage,
                    default_db=self.occlusion_max_attenuation_db,
                )
            records = compute_scene_occlusion(
                scene,
                self.occlusion_raycaster,
                max_attenuation_db=self.occlusion_max_attenuation_db,
                transmission_resolver=self.occlusion_transmission_resolver,
                attenuation_cap_db=self.occlusion_attenuation_cap_db,
            )
        except IsaacIntegrationUnavailable as exc:
            self._note_occlusion_diagnostics(
                {"status": "unavailable", "error": str(exc)}
            )
            self._frame_acoustics_state = {"occlusion_recompute_count": 0}
            return scene
        current_pairs = {
            (record.array_id, record.source_id): _canonical_occlusion_pair(record)
            for record in records
        }
        had_previous = self._has_previous_occlusion_capture
        changed_pairs = [
            f"{array_id}:{source_id}"
            for array in scene.arrays
            for source in scene.sources
            for array_id, source_id in ((array.array_id, source.source_id),)
            if had_previous
            and self._previous_occlusion_pairs.get((array_id, source_id))
            != current_pairs.get((array_id, source_id))
        ]
        cache = self._stage_cache
        if cache is not None and cache.pending_non_audio_pose_paths and changed_pairs:
            cache.record_acoustic_refresh("occluder_moved")
        self._pending_occlusion_pairs = current_pairs
        resolver_evidence = getattr(
            self.occlusion_transmission_resolver,
            "material_evidence",
            {},
        )
        state: dict[str, Any] = {"occlusion_recompute_count": 1}
        if had_previous:
            state["changed_occlusion_pairs"] = changed_pairs
        if isinstance(resolver_evidence, dict) and resolver_evidence:
            state["material_evidence"] = {
                key: dict(resolver_evidence[key]) for key in sorted(resolver_evidence)
            }
        self._frame_acoustics_state = state
        self._note_occlusion_diagnostics(
            {
                "status": "computed",
                "record_count": len(records),
                "max_attenuation_db": float(self.occlusion_max_attenuation_db),
                "attenuation_cap_db": float(self.occlusion_attenuation_cap_db),
                "occlusion_model": OCCLUSION_MODEL_RAYCAST_TRANSMISSION,
            }
        )
        return replace(scene, occlusion=records)

    def _merge_acoustics_state(self, frame: AudioSensorFrame) -> AudioSensorFrame:
        """Merge room and live acoustic diagnostics after successful simulation."""

        diagnostics = dict(frame.diagnostics)
        backend_state = diagnostics.get("acoustics_state")
        state: dict[str, Any] = (
            dict(backend_state) if isinstance(backend_state, dict) else {}
        )
        live_state = self._frame_acoustics_state
        if live_state is not None:
            live_materials = live_state.get("material_evidence")
            room_materials = state.get("material_evidence")
            merged_materials: dict[str, Any] = {}
            if isinstance(room_materials, dict) and "room" in room_materials:
                merged_materials["room"] = room_materials["room"]
            for mapping in (room_materials, live_materials):
                if isinstance(mapping, dict):
                    for key in sorted(mapping):
                        if key != "room":
                            merged_materials[key] = mapping[key]
            if merged_materials:
                state["material_evidence"] = merged_materials
            for key, value in live_state.items():
                if key != "material_evidence":
                    state[key] = value
        cache = self._stage_cache
        reasons = () if cache is None else cache.consume_acoustic_refresh_reasons()
        if state or self.occlusion_enabled:
            state["refresh_reasons"] = list(reasons)
            diagnostics["acoustics_state"] = state
        if cache is not None:
            if self._pending_occlusion_pairs is not None:
                self._previous_occlusion_pairs = self._pending_occlusion_pairs
                self._has_previous_occlusion_capture = True
                cache.clear_pending_non_audio_pose_paths()
            stage_diagnostics = self._latest_stage_diagnostics
            if isinstance(stage_diagnostics, dict):
                cache_diagnostics = stage_diagnostics.get("discovery_cache")
                if isinstance(cache_diagnostics, dict):
                    cache_diagnostics["acoustic_refresh_reasons"] = tuple(
                        cache.acoustic_refresh_reasons
                    )
        self._pending_occlusion_pairs = None
        return replace(frame, diagnostics=diagnostics)

    def _note_occlusion_diagnostics(self, info: dict[str, Any]) -> None:
        if self._latest_stage_diagnostics is None:
            self._latest_stage_diagnostics = {}
        self._latest_stage_diagnostics["occlusion"] = info

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
        except IsaacIntegrationUnavailable as exc:
            self.debug_drawer.last_primitives = primitives
            self.debug_drawer.last_status = "serialized_fallback_debug_draw_unavailable"
            self.debug_drawer.last_error = str(exc)
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
                self.update(force=False)

        return stream.create_subscription_to_pop(
            _on_update,
            name="isaac_audio_sensors.update",
        )

    def _subscribe_to_timeline_events(self) -> Any | None:
        try:
            import omni.timeline  # type: ignore
        except ImportError:
            return None
        timeline = omni.timeline.get_timeline_interface()
        get_stream = getattr(timeline, "get_timeline_event_stream", None)
        if not callable(get_stream):
            return None
        stream = get_stream()

        def _on_timeline_event(event: Any) -> None:
            if not _is_timeline_reset_event(event, omni.timeline):
                return
            if self._pose_history is not None:
                self._pose_history.reset()
                self._motion_entity_paths.clear()
            self._previous_occlusion_pairs.clear()
            self._has_previous_occlusion_capture = False
            self._pending_occlusion_pairs = None
            self._frame_acoustics_state = None
            if self._stage_cache is not None:
                self._stage_cache.reset_acoustic_state()

        return stream.create_subscription_to_pop(
            _on_timeline_event,
            name="isaac_audio_sensors.timeline",
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


def _is_timeline_reset_event(event: Any, timeline_module: Any) -> bool:
    event_type = getattr(event, "type", event)
    enum = getattr(timeline_module, "TimelineEventType", None)
    reset_values = {
        getattr(enum, name)
        for name in ("STOP", "RESET")
        if enum is not None and hasattr(enum, name)
    }
    if event_type in reset_values:
        return True
    text = str(event_type).upper()
    return (
        text == "STOP"
        or text == "RESET"
        or text.endswith(".STOP")
        or text.endswith(".RESET")
    )


def _canonical_occlusion_pair(record: Any) -> tuple[Any, ...]:
    """Serialize all acoustic pair fields used by the moving-occluder seam."""

    return (
        record.array_id,
        record.source_id,
        tuple(record.per_mic_blocked.items()),
        record.occlusion_factor,
        record.attenuation_db,
        tuple(record.per_mic_attenuation_db.items()),
        tuple(record.band_centers_hz),
        tuple(
            (mic_id, tuple(values))
            for mic_id, values in record.per_mic_band_attenuation_db.items()
        ),
        tuple(record.hit_prim_paths),
        tuple(
            (mic_id, tuple(paths))
            for mic_id, paths in record.per_mic_hit_prim_paths.items()
        ),
        tuple(sorted(record.hit_materials.items())),
        record.occlusion_model,
    )
