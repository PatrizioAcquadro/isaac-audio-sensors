"""High-level Isaac Sim-facing audio array sensor API."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import DEFAULT_SPEED_OF_SOUND_MPS
from isaac_audio_sensors.core.effects.config import EffectsConfig
from isaac_audio_sensors.core.effects.validation import (
    UnsupportedEffectError,
    validate_motion_effects_config,
)
from isaac_audio_sensors.core.exceptions import (
    ConfigValidationError,
    IsaacIntegrationUnavailable,
)
from isaac_audio_sensors.core.io.waveforms import WaveformSink
from isaac_audio_sensors.core.motion import (
    EntityMotionInput,
    PoseHistory,
    WindowMotionPlan,
    build_window_motion,
    validate_pose_observation,
)
from isaac_audio_sensors.core.types import (
    AcousticEnvironmentSpec,
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
)
from isaac_audio_sensors.isaac.discovery import (
    IsaacAudioSceneBindingCfg,
    discover_stage_audio,
)
from isaac_audio_sensors.isaac.environment_resolution import (
    IsaacEnvironmentResolutionCfg,
    resolve_stage_environment,
)
from isaac_audio_sensors.isaac.lifecycle import (
    current_timeline_time_s,
    subscribe_to_timeline_resets,
    subscribe_to_updates,
)
from isaac_audio_sensors.isaac.occlusion import (
    DEFAULT_OCCLUSION_ATTENUATION_CAP_DB,
    DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
    LiveOcclusionState,
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


@dataclass(slots=True)
class IsaacAudioArraySensor:
    """Lifecycle-capable audio array sensor for Isaac Sim-style stages."""

    array_id: str
    stage: Any
    environment: AcousticEnvironmentSpec
    backend: str = "tdoa_synthetic"
    effects: EffectsConfig = field(default_factory=EffectsConfig)
    environment_resolution_cfg: IsaacEnvironmentResolutionCfg = field(
        default_factory=lambda: IsaacEnvironmentResolutionCfg(mode="manual")
    )
    room_acoustics_max_order: int = 0
    room_acoustics_air_absorption: bool = False
    room_acoustics_ray_tracing: bool = False
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
    waveform_sink: WaveformSink | None = None
    debug_draw_enabled: bool = False
    debug_drawer: IsaacDebugDrawer | None = None
    occlusion_enabled: bool = False
    occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB
    occlusion_attenuation_cap_db: float = DEFAULT_OCCLUSION_ATTENUATION_CAP_DB
    occlusion_raycaster: Any | None = None
    occlusion_transmission_resolver: Any | None = None
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
    _timeline_subscription: Any | None = field(default=None, init=False)
    _stage_cache: StageAudioCache | None = field(default=None, init=False)
    _pose_history: PoseHistory | None = field(default=None, init=False)
    _pose_history_stage: Any | None = field(default=None, init=False)
    _motion_entity_paths: dict[str, str] = field(default_factory=dict, init=False)
    _occlusion_state: LiveOcclusionState = field(init=False)
    _reset_listeners: list[Callable[[], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.stage is None:
            raise ValueError("IsaacAudioArraySensor requires a live stage.")
        if not isinstance(self.environment, AcousticEnvironmentSpec):
            raise ValueError(
                "IsaacAudioArraySensor.environment must be an AcousticEnvironmentSpec."
            )
        if not isinstance(
            self.environment_resolution_cfg,
            IsaacEnvironmentResolutionCfg,
        ):
            raise ValueError(
                "environment_resolution_cfg must be an IsaacEnvironmentResolutionCfg."
            )
        if (
            isinstance(self.room_acoustics_max_order, bool)
            or not isinstance(self.room_acoustics_max_order, int)
            or self.room_acoustics_max_order < 0
        ):
            raise ValueError("room_acoustics_max_order must be a non-negative integer.")
        if not isinstance(self.room_acoustics_air_absorption, bool):
            raise ValueError("room_acoustics_air_absorption must be a boolean.")
        if not isinstance(self.room_acoustics_ray_tracing, bool):
            raise ValueError("room_acoustics_ray_tracing must be a boolean.")
        self._occlusion_state = LiveOcclusionState(
            enabled=self.occlusion_enabled,
            max_attenuation_db=self.occlusion_max_attenuation_db,
            attenuation_cap_db=self.occlusion_attenuation_cap_db,
            raycaster=self.occlusion_raycaster,
            transmission_resolver=self.occlusion_transmission_resolver,
        )
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
        if self.effects.motion.derive_velocity_from_poses:
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
        environment_resolution_cfg: IsaacEnvironmentResolutionCfg,
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
        environment: AcousticEnvironmentSpec | None = None,
        room_acoustics_max_order: int = 0,
        room_acoustics_air_absorption: bool = False,
        room_acoustics_ray_tracing: bool = False,
        debug_draw: bool = False,
        occlusion_enabled: bool = False,
        occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
        occlusion_raycaster: Any | None = None,
        waveform_sink: WaveformSink | None = None,
        effects: EffectsConfig | None = None,
    ) -> IsaacAudioArraySensor:
        """Create a live sensor from a real or duck-typed Isaac stage."""

        diagnostics: dict[str, Any] = {}
        snapshot = build_stage_snapshot(
            stage,
            timestamp_ms=timestamp_ms,
            environment_resolution_cfg=environment_resolution_cfg,
            environment=environment,
            array_prim_path=array_prim_path,
            source_prim_path=source_prim_path,
            robot_base_prim_path=robot_base_prim_path,
            diagnostics_out=diagnostics,
        )
        if len(snapshot.arrays) != 1:
            raise ValueError(
                f"Expected exactly one array at {array_prim_path!r}, "
                f"found {len(snapshot.arrays)}."
            )
        sensor = cls(
            array_id=snapshot.arrays[0].array_id,
            stage=stage,
            backend=backend,
            effects=EffectsConfig() if effects is None else effects,
            environment=snapshot.environment,
            environment_resolution_cfg=environment_resolution_cfg,
            room_acoustics_max_order=room_acoustics_max_order,
            room_acoustics_air_absorption=room_acoustics_air_absorption,
            room_acoustics_ray_tracing=room_acoustics_ray_tracing,
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
            waveform_sink=waveform_sink,
        )
        sensor._latest_stage_diagnostics = diagnostics
        return sensor

    @classmethod
    def from_discovered_stage(
        cls,
        *,
        stage: Any,
        environment_resolution_cfg: IsaacEnvironmentResolutionCfg,
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
        environment: AcousticEnvironmentSpec | None = None,
        room_acoustics_max_order: int = 0,
        room_acoustics_air_absorption: bool = False,
        room_acoustics_ray_tracing: bool = False,
        debug_draw: bool = False,
        occlusion_enabled: bool = False,
        occlusion_max_attenuation_db: float = DEFAULT_OCCLUSION_MAX_ATTENUATION_DB,
        occlusion_raycaster: Any | None = None,
        waveform_sink: WaveformSink | None = None,
        effects: EffectsConfig | None = None,
    ) -> IsaacAudioArraySensor:
        """Create a live sensor by discovering arrays and sources on a stage."""

        binding = binding_cfg or IsaacAudioSceneBindingCfg()
        prims = tuple(stage.Traverse())
        result = discover_stage_audio(
            stage,
            cfg=binding.to_discovery_cfg(),
            timestamp_ms=timestamp_ms,
            usd_time_code=usd_time_code,
            preferred_array=binding.preferred_array,
            preferred_source=binding.preferred_source,
            prims=prims,
        )
        if result.selected_array is None:
            raise ValueError("No microphone array was discovered for stage binding.")
        environment_diagnostics: dict[str, Any] = {}
        resolved_environment = resolve_stage_environment(
            stage,
            result.selected_array.spec,
            cfg=environment_resolution_cfg,
            manual_environment=environment,
            time_code=usd_time_code,
            prims=prims,
            diagnostics_out=environment_diagnostics,
        )
        sensor = cls(
            array_id=result.selected_array.spec.array_id,
            stage=stage,
            backend=backend,
            effects=EffectsConfig() if effects is None else effects,
            environment=resolved_environment,
            environment_resolution_cfg=environment_resolution_cfg,
            room_acoustics_max_order=room_acoustics_max_order,
            room_acoustics_air_absorption=room_acoustics_air_absorption,
            room_acoustics_ray_tracing=room_acoustics_ray_tracing,
            array_prim_path=result.selected_array.spec.prim_path,
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
            waveform_sink=waveform_sink,
        )
        sensor._latest_stage_diagnostics = dict(result.diagnostics)
        sensor._latest_stage_diagnostics["environment_resolution"] = (
            environment_diagnostics
        )
        return sensor

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
            self._update_subscription = subscribe_to_updates(
                self._on_update,
                name="isaac_audio_sensors.update",
            )
            if self._pose_history is not None:
                self._timeline_subscription = subscribe_to_timeline_resets(
                    self._reset_live_acoustic_state,
                    name="isaac_audio_sensors.timeline",
                )
        return self

    def _prime_piecewise_motion(self) -> None:
        """Observe current live poses once without emitting a backend frame."""

        if self.stage is None or self._pose_history is None:
            raise UnsupportedEffectError(
                "piecewise motion requires a live stage pose-time stream"
            )
        prime_time_s = current_timeline_time_s()
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
        self.latest_frame = None
        self.latest_debug_primitives = ()
        self._latest_scene = None
        self._latest_sensor = None
        self._occlusion_state.reset()
        if self._stage_cache is not None:
            self._stage_cache.reset_acoustic_state()
        if self._pose_history is not None:
            self._pose_history.reset()
            self._motion_entity_paths.clear()
        for listener in tuple(self._reset_listeners):
            listener()

    def close(self) -> None:
        """Stop the sensor and close owned live resources."""

        self.stop()
        if self.waveform_sink is not None:
            self.waveform_sink.close()
            self.waveform_sink = None
        if self.debug_drawer is not None:
            self.debug_drawer.close()
            self.debug_drawer = None
        if self._stage_cache is not None:
            self._stage_cache.close()
            self._stage_cache = None
        self._occlusion_state.reset()
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

    @property
    def latest_scene(self) -> AudioSceneSnapshot | None:
        """Return the scene used for the latest frame."""

        return self._latest_scene

    @property
    def latest_array_spec(self) -> MicrophoneArraySpec | None:
        """Return the array specification used for the latest frame."""

        return self._latest_sensor

    def add_reset_listener(self, listener: Callable[[], None]) -> None:
        """Notify ``listener`` after each completed reset."""

        if listener not in self._reset_listeners:
            self._reset_listeners.append(listener)

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
        """Capture one frame from the live stage."""

        scene = self._scene_for_capture(
            timestamp_ms=timestamp_ms,
            source_prim_path=source_prim_path,
            usd_time_code=(
                usd_time_code
                if usd_time_code is not None
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
        if (
            self.backend in {"room_acoustics", "room_acoustics_srp"}
            and self.waveform_sink is not None
        ):
            kwargs["waveform_writer"] = self.waveform_sink
        if self.backend in {"room_acoustics", "room_acoustics_srp"}:
            kwargs.update(
                max_order=self.room_acoustics_max_order,
                air_absorption=self.room_acoustics_air_absorption,
                ray_tracing=self.room_acoustics_ray_tracing,
            )
        if not self.effects.all_disabled:
            kwargs["effects"] = self.effects
        if window_motion is not None:
            kwargs["window_motion"] = window_motion
        backend = get_backend(self.backend, **kwargs)
        frame = backend.simulate(scene, self.array_id, time_window)
        frame = self._merge_acoustics_state(frame)
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
            self._occlusion_state.reset()
            if self._stage_cache is not None:
                self._stage_cache.reset_acoustic_state()
            self._timeline_subscription = None
            self._pose_history_stage = self.stage
        if self._stage_cache is not None and self._stage_cache.stage is not self.stage:
            self._stage_cache.close()
            self._stage_cache = None
            self._occlusion_state.reset()
        if self._stage_cache is None:
            rediscover_each_update = (
                self.scene_binding_cfg is not None
                and self.scene_binding_cfg.rediscover_each_update
            )
            self._stage_cache = StageAudioCache(
                self.stage,
                rediscover_each_update=rediscover_each_update,
                environment_anchor_prim_path=(
                    self.environment_resolution_cfg.anchor_prim_path
                    if self.environment_resolution_cfg.mode == "anchor"
                    else None
                ),
                environment_candidate_roots=(
                    self.environment_resolution_cfg.candidate_roots
                    if self.environment_resolution_cfg.mode == "auto"
                    else ()
                ),
            )
        return self._stage_cache

    def _scene_for_capture(
        self,
        *,
        timestamp_ms: int,
        source_prim_path: str | None,
        usd_time_code: Any | None,
        sim_time_s: float | None,
    ) -> AudioSceneSnapshot:
        self._occlusion_state.begin_capture()
        effective_source_prim_path = source_prim_path or self.source_prim_path
        cache = self._ensure_stage_cache()
        diagnostics: dict[str, Any] = {}
        if self.scene_binding_cfg is not None:
            binding = self.scene_binding_cfg
            scene = cache.snapshot(
                timestamp_ms=timestamp_ms,
                environment=self.environment,
                robot_base_prim_path=binding.robot_base_prim_path,
                source_prim_path=effective_source_prim_path,
                usd_time_code=usd_time_code,
                discovery_cfg=binding.to_discovery_cfg(),
                preferred_array=binding.preferred_array,
                preferred_source=binding.preferred_source,
                diagnostics_out=diagnostics,
            )
        elif self.array_prim_path is None:
            raise RuntimeError("Live Isaac stage sensor has no array prim path.")
        else:
            scene = cache.snapshot(
                timestamp_ms=timestamp_ms,
                environment=self.environment,
                array_prim_path=self.array_prim_path,
                robot_base_prim_path=self.robot_base_prim_path,
                source_prim_path=effective_source_prim_path,
                usd_time_code=usd_time_code,
                diagnostics_out=diagnostics,
            )
        environment_diagnostics: dict[str, Any] = {}
        self.environment = resolve_stage_environment(
            self.stage,
            scene.array_by_id(self.array_id),
            cfg=self.environment_resolution_cfg,
            manual_environment=(
                self.environment
                if self.environment_resolution_cfg.mode == "manual"
                else None
            ),
            time_code=usd_time_code,
            prims=cache.cached_prims,
            diagnostics_out=environment_diagnostics,
        )
        diagnostics["environment_resolution"] = environment_diagnostics
        self._latest_stage_diagnostics = diagnostics
        scene = replace(scene, environment=self.environment)

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
        return self._occlusion_state.apply(
            scene,
            stage=self.stage,
            cache=cache,
            stage_diagnostics=diagnostics,
        )

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

    def _merge_acoustics_state(self, frame: AudioSensorFrame) -> AudioSensorFrame:
        return self._occlusion_state.merge_frame(
            frame,
            cache=self._stage_cache,
            stage_diagnostics=self._latest_stage_diagnostics,
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
        timeline_time = current_timeline_time_s()
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

    def _on_update(self, _event: Any) -> None:
        if self._running:
            self.update(force=False)

    def _reset_live_acoustic_state(self) -> None:
        if self._pose_history is not None:
            self._pose_history.reset()
            self._motion_entity_paths.clear()
        self._occlusion_state.reset()
        if self._stage_cache is not None:
            self._stage_cache.reset_acoustic_state()

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError("IsaacAudioArraySensor is closed.")
