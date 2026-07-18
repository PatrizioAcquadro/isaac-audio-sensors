"""Isaac Lab ``SensorBase`` audio array sensor with vectorized buffers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from isaac_audio_sensors.core.backends.base import get_backend
from isaac_audio_sensors.core.constants import EPSILON, SECTOR_ORDER
from isaac_audio_sensors.core.effects import EffectsConfig, UnsupportedEffectError
from isaac_audio_sensors.core.exceptions import IsaacLabUnavailable
from isaac_audio_sensors.core.io.waveforms import FrameWaveformWriter
from isaac_audio_sensors.core.microphone_array import microphone_layout
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSensorFrame,
    AudioTimeWindow,
    MicrophoneArraySpec,
)
from isaac_audio_sensors.lab._isaac_lab import (
    last_isaac_lab_import_error,
    load_isaac_lab_types,
)
from isaac_audio_sensors.lab.audio_array_sensor_cfg import AudioArraySensorCfg
from isaac_audio_sensors.lab.audio_array_sensor_data import AudioArraySensorData
from isaac_audio_sensors.lab.batched_backend import (
    batched_geometry_observations,
    batched_tdoa_observations,
    compact_active_events,
    precompute_lstsq_operator,
)
from isaac_audio_sensors.lab.entity_binding import (
    EntityPoseTensorBatch,
    EntityStaticBatchMeta,
    LabAudioEntityBindingCfg,
    build_lab_entity_provider,
    resolve_lab_entity_num_envs,
    resolve_lab_entity_scene,
)
from isaac_audio_sensors.lab.stage_binding import (
    LabAudioStageBindingCfg,
    build_lab_stage_provider,
    resolve_lab_num_envs,
    resolve_lab_stage,
)

SceneProvider = Callable[
    [Sequence[int]],
    Mapping[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]],
]

_LAB_TYPES = load_isaac_lab_types()
_SENSOR_BASE = _LAB_TYPES.SensorBase if _LAB_TYPES is not None else object


def isaac_lab_available() -> bool:
    """Return whether this module was imported with real Isaac Lab bases."""

    return _LAB_TYPES is not None


def require_isaac_lab() -> None:
    """Raise a clear error when real Isaac Lab bases are not active."""

    if _LAB_TYPES is not None:
        return
    if load_isaac_lab_types() is not None:
        raise IsaacLabUnavailable(
            "Isaac Lab SensorBase is now importable, but this module was imported "
            "while fallback classes were active. Call "
            "isaac_audio_sensors.lab.ensure_isaac_lab_sensor_classes() after "
            "AppLauncher initialization and use the classes returned from that "
            "call, or restart and import isaac_audio_sensors.lab only after "
            "AppLauncher."
        )
    import_error = last_isaac_lab_import_error()
    detail = "" if import_error is None else f" Last import error: {import_error}"
    raise IsaacLabUnavailable(
        "Isaac Lab SensorBase is unavailable for this imported module. "
        "Launch Isaac Lab/Kit first and import isaac_audio_sensors.lab after "
        f"the Lab runtime is initialized.{detail}"
    )


class AudioArraySensor(_SENSOR_BASE):  # type: ignore[misc, valid-type]
    """Audio array sensor using Isaac Lab semantics when Lab is available."""

    def __init__(
        self,
        cfg: AudioArraySensorCfg,
        sensor: MicrophoneArraySpec | None = None,
        scene_snapshot: AudioSceneSnapshot | None = None,
        *,
        num_envs: int | None = None,
        scene_provider: SceneProvider | None = None,
    ) -> None:
        if _LAB_TYPES is None and load_isaac_lab_types() is not None:
            raise IsaacLabUnavailable(
                "AudioArraySensor is a fallback class imported before Isaac Lab "
                "SensorBase was available. Call "
                "isaac_audio_sensors.lab.ensure_isaac_lab_sensor_classes() after "
                "AppLauncher initialization and use the returned classes, or "
                "restart and import isaac_audio_sensors.lab only after "
                "AppLauncher."
            )
        self._data = AudioArraySensorData.empty()
        self._compute_path_decision: tuple[int, str] | None = None
        self._last_compute_path: str = "scalar"
        self._lstsq_cache: tuple[int, Any, Any] | None = None
        self._scene_provider = scene_provider
        self._bound_scene_snapshots: dict[int, AudioSceneSnapshot] = {}
        self._bound_sensors: dict[int, MicrophoneArraySpec] = {}
        self._frame_indices: list[int] = []
        self._pending_timestamp_ms: dict[int, int] = {}
        self._last_legacy_sim_time_s: float | None = None
        self._waveform_sinks: dict[int, Any] = {}
        self._manual_num_envs = int(num_envs) if num_envs is not None else None
        self._manual_device = cfg.device or "cpu"
        self._is_visualizing = False

        if _LAB_TYPES is not None:
            super().__init__(cfg)
        else:
            self.cfg = cfg.copy() if hasattr(cfg, "copy") else cfg
            self._is_initialized = False
            self._device = self._manual_device
            self._backend = "python"
            self._sim_physics_dt = 0.0
            self._num_envs = int(num_envs or 0)

        if scene_snapshot is not None or sensor is not None:
            if scene_snapshot is None or sensor is None:
                raise ValueError("scene_snapshot and sensor must be provided together.")
            self.bind_env(env_id=0, scene_snapshot=scene_snapshot, sensor=sensor)
        elif scene_provider is not None and num_envs is not None:
            self._ensure_runtime_buffers(num_envs=num_envs)

    @classmethod
    def from_lab_scene(
        cls,
        *,
        cfg: AudioArraySensorCfg,
        scene: object,
        binding_cfg: LabAudioStageBindingCfg | LabAudioEntityBindingCfg | None = None,
    ) -> AudioArraySensor:
        """Construct from an Isaac Lab scene wrapper with audio bindings."""

        require_isaac_lab()
        sensor = cls(cfg=cfg)
        if binding_cfg is not None:
            if isinstance(binding_cfg, LabAudioEntityBindingCfg):
                return sensor.bind_lab_entities(scene=scene, binding_cfg=binding_cfg)
            return sensor.bind_lab_scene(scene=scene, binding_cfg=binding_cfg)
        entity_binding_cfg = getattr(scene, "audio_entity_binding_cfg", None)
        if entity_binding_cfg is not None:
            return sensor.bind_lab_entities(
                scene=scene,
                binding_cfg=entity_binding_cfg,
            )
        scene_binding_cfg = getattr(scene, "audio_stage_binding_cfg", None)
        if scene_binding_cfg is not None:
            return sensor.bind_lab_scene(scene=scene, binding_cfg=scene_binding_cfg)
        scene_snapshots = getattr(scene, "audio_scene_snapshots", None)
        array_specs = getattr(scene, "audio_array_specs", None)
        if scene_snapshots is not None or array_specs is not None:
            if scene_snapshots is None or array_specs is None:
                raise ValueError(
                    "scene must expose both audio_scene_snapshots and "
                    "audio_array_specs for env-indexed binding."
                )
            return sensor.bind_envs(
                scene_snapshots=tuple(scene_snapshots),
                sensors=tuple(array_specs),
            )

        scene_snapshot = getattr(scene, "audio_scene_snapshot", None)
        array_spec = getattr(scene, "audio_array_spec", None)
        if not isinstance(scene_snapshot, AudioSceneSnapshot):
            raise ValueError(
                "scene must expose audio_scene_snapshot: AudioSceneSnapshot."
            )
        if not isinstance(array_spec, MicrophoneArraySpec):
            raise ValueError("scene must expose audio_array_spec: MicrophoneArraySpec.")
        return sensor.bind_env(
            env_id=0,
            scene_snapshot=scene_snapshot,
            sensor=array_spec,
        )

    @classmethod
    def from_scene_snapshot(
        cls,
        *,
        cfg: AudioArraySensorCfg,
        scene_snapshot: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
    ) -> AudioArraySensor:
        """Construct a one-environment sensor for offline tests and examples."""

        return cls(cfg=cfg).bind_env(
            env_id=0,
            scene_snapshot=scene_snapshot,
            sensor=sensor,
        )

    @classmethod
    def from_lab_entities(
        cls,
        *,
        cfg: AudioArraySensorCfg,
        scene: object | None = None,
        binding_cfg: LabAudioEntityBindingCfg,
    ) -> AudioArraySensor:
        """Construct from Isaac Lab scene entity tensors."""

        return cls(cfg=cfg).bind_lab_entities(
            scene=scene,
            binding_cfg=binding_cfg,
        )

    @property
    def data(self) -> AudioArraySensorData:
        """Return lazily refreshed vectorized buffers."""

        self._ensure_runtime_buffers()
        self._update_outdated_buffers()
        return self._data

    def bind_env(
        self,
        *,
        env_id: int,
        scene_snapshot: AudioSceneSnapshot,
        sensor: MicrophoneArraySpec,
    ) -> AudioArraySensor:
        """Bind one scene snapshot and microphone array to an environment id."""

        if not isinstance(scene_snapshot, AudioSceneSnapshot):
            raise TypeError("scene_snapshot must be an AudioSceneSnapshot.")
        if not isinstance(sensor, MicrophoneArraySpec):
            raise TypeError("sensor must be a MicrophoneArraySpec.")
        env_id = int(env_id)
        if env_id < 0:
            raise ValueError("env_id must be non-negative.")
        self._bound_scene_snapshots[env_id] = scene_snapshot
        self._bound_sensors[env_id] = sensor
        self._ensure_runtime_buffers(
            num_envs=max(self._known_num_envs(), env_id + 1),
            num_mics=len(sensor.microphones),
        )
        self._mark_outdated((env_id,))
        return self

    def bind_envs(
        self,
        *,
        scene_snapshots: Sequence[AudioSceneSnapshot],
        sensors: Sequence[MicrophoneArraySpec] | MicrophoneArraySpec,
    ) -> AudioArraySensor:
        """Bind env-indexed snapshots/specs for cloned Isaac Lab environments."""

        snapshots = tuple(scene_snapshots)
        if isinstance(sensors, MicrophoneArraySpec):
            sensor_specs = tuple(sensors for _ in snapshots)
        else:
            sensor_specs = tuple(sensors)
        if len(snapshots) != len(sensor_specs):
            raise ValueError("scene_snapshots and sensors must have the same length.")
        if not snapshots:
            raise ValueError("At least one environment binding is required.")
        num_mics = _derive_num_mics_from_sensors(sensor_specs)
        self._bound_scene_snapshots = dict(enumerate(snapshots))
        self._bound_sensors = dict(enumerate(sensor_specs))
        self._ensure_runtime_buffers(num_envs=len(snapshots), num_mics=num_mics)
        self._mark_outdated(range(len(snapshots)))
        return self

    def bind_provider(
        self,
        *,
        provider: SceneProvider,
        num_envs: int,
        num_mics: int | None = None,
    ) -> AudioArraySensor:
        """Bind a callable that returns snapshots/specs for requested env ids."""

        if int(num_envs) <= 0:
            raise ValueError("num_envs must be positive.")
        self._scene_provider = provider
        self._ensure_runtime_buffers(num_envs=int(num_envs), num_mics=num_mics)
        self._mark_outdated(range(int(num_envs)))
        return self

    def bind_lab_stage(
        self,
        *,
        stage: object,
        binding_cfg: LabAudioStageBindingCfg,
        num_envs: int | None = None,
    ) -> AudioArraySensor:
        """Bind cloned env audio prims from a live USD/stage-like object."""

        provider = build_lab_stage_provider(
            stage=stage,
            binding_cfg=binding_cfg,
            num_envs=num_envs,
        )
        self._scene_provider = provider
        self._ensure_runtime_buffers(
            num_envs=provider.num_envs,
            num_mics=provider.num_mics,
        )
        self._mark_outdated(range(provider.num_envs))
        return self

    def bind_lab_scene(
        self,
        *,
        scene: object,
        binding_cfg: LabAudioStageBindingCfg,
    ) -> AudioArraySensor:
        """Bind audio prims from a common Isaac Lab scene-like object."""

        stage = resolve_lab_stage(scene)
        num_envs = resolve_lab_num_envs(binding_cfg=binding_cfg, owner=scene)
        return self.bind_lab_stage(
            stage=stage,
            binding_cfg=binding_cfg,
            num_envs=num_envs,
        )

    def bind_lab_env(
        self,
        *,
        env: object,
        binding_cfg: LabAudioStageBindingCfg,
    ) -> AudioArraySensor:
        """Bind audio prims from a common Isaac Lab env/task wrapper."""

        stage = resolve_lab_stage(env)
        num_envs = resolve_lab_num_envs(binding_cfg=binding_cfg, owner=env)
        return self.bind_lab_stage(
            stage=stage,
            binding_cfg=binding_cfg,
            num_envs=num_envs,
        )

    def bind_lab_entities(
        self,
        *,
        scene: object | None = None,
        binding_cfg: LabAudioEntityBindingCfg,
    ) -> AudioArraySensor:
        """Bind microphone arrays and sources from Lab entity state tensors."""

        resolved_scene = resolve_lab_entity_scene(
            scene=scene,
            env=binding_cfg.env,
            fallback_scene=binding_cfg.scene,
        )
        provider = build_lab_entity_provider(
            scene=resolved_scene,
            binding_cfg=binding_cfg,
        )
        num_envs = resolve_lab_entity_num_envs(
            binding_cfg=binding_cfg,
            owner=resolved_scene,
        )
        self._scene_provider = provider
        self._ensure_runtime_buffers(
            num_envs=num_envs,
            num_mics=provider.num_mics,
        )
        self._mark_outdated(range(num_envs))
        return self

    def bind_lab_scene_entities(
        self,
        *,
        scene: object | None = None,
        binding_cfg: LabAudioEntityBindingCfg,
    ) -> AudioArraySensor:
        """Alias for ``bind_lab_entities`` for explicit scene wording."""

        return self.bind_lab_entities(scene=scene, binding_cfg=binding_cfg)

    def bind_lab_env_entities(
        self,
        *,
        env: object,
        binding_cfg: LabAudioEntityBindingCfg,
    ) -> AudioArraySensor:
        """Bind entity tensors from an env/task wrapper exposing a scene."""

        scene = resolve_lab_entity_scene(
            scene=None,
            env=env,
            fallback_scene=binding_cfg.scene,
        )
        return self.bind_lab_entities(scene=scene, binding_cfg=binding_cfg)

    def update(
        self,
        dt: float | None = None,
        force_recompute: bool = False,
        *,
        env_ids: Sequence[int] | int | None = None,
        scene_snapshot: AudioSceneSnapshot | Sequence[AudioSceneSnapshot] | None = None,
        sensor: MicrophoneArraySpec | Sequence[MicrophoneArraySpec] | None = None,
        sim_time_s: float | None = None,
        timestamp_ms: int | None = None,
        force: bool | None = None,
    ) -> AudioArraySensorData | None:
        """Update timestamps and optionally recompute selected env buffers.

        The positional ``dt``/``force_recompute`` behavior follows Isaac Lab's
        ``SensorBase.update``. Keyword ``sim_time_s``/``timestamp_ms`` is kept
        as a compatibility path for offline examples.
        """

        legacy_call = (
            sim_time_s is not None
            or timestamp_ms is not None
            or scene_snapshot is not None
            or sensor is not None
        )
        if force is not None:
            force_recompute = force
        if scene_snapshot is not None or sensor is not None:
            self._bind_update_inputs(
                scene_snapshot=scene_snapshot,
                sensor=sensor,
                env_ids=env_ids,
            )
        self._ensure_runtime_buffers()
        ids = self._normalize_env_ids(env_ids)

        if sim_time_s is not None:
            if self._last_legacy_sim_time_s is None:
                dt_value = float(sim_time_s)
            else:
                dt_value = float(sim_time_s) - self._last_legacy_sim_time_s
            if dt_value < 0.0:
                raise ValueError("sim_time_s must be monotonically non-decreasing.")
            self._last_legacy_sim_time_s = float(sim_time_s)
        else:
            dt_value = 0.0 if dt is None else float(dt)
        if dt_value < 0.0:
            raise ValueError("dt must be non-negative.")

        if timestamp_ms is not None:
            for env_id in ids:
                self._pending_timestamp_ms[int(env_id)] = int(timestamp_ms)

        self._timestamp[ids] += dt_value
        elapsed = (
            self._timestamp[ids] - self._timestamp_last_update[ids] + 1e-6
            >= self.cfg.update_period
        )
        self._is_outdated[ids] |= elapsed
        if force_recompute:
            self._is_outdated[ids] = True

        if env_ids is not None:
            ready_ids = self._ids_to_list(ids[self._is_outdated[ids]])
            if ready_ids:
                self._update_selected_buffers(ready_ids)
            return self._data if legacy_call else None

        if force_recompute or legacy_call or self._is_visualizing:
            self._update_outdated_buffers()
        return self._data if legacy_call else None

    def reset(self, env_ids: Sequence[int] | int | None = None) -> None:
        """Reset all or selected environments using Isaac Lab env-id semantics."""

        if not self._has_runtime_buffers():
            self._ensure_runtime_buffers()
        ids = self._normalize_env_ids(env_ids)
        self._timestamp[ids] = 0.0
        self._timestamp_last_update[ids] = 0.0
        self._is_outdated[ids] = True
        self._data.reset_envs(self._ids_to_list(ids))
        for env_id in self._ids_to_list(ids):
            self._frame_indices[env_id] = 0
            self._pending_timestamp_ms.pop(env_id, None)

    def capture_frame(
        self,
        *,
        scene_snapshot: AudioSceneSnapshot | None = None,
        sensor: MicrophoneArraySpec | None = None,
        timestamp_ms: int,
        start_time_s: float,
        end_time_s: float,
        env_id: int = 0,
    ) -> AudioSensorFrame:
        """Capture one core frame through the configured backend."""

        scene_snapshot = scene_snapshot or self._resolve_scene_snapshot(env_id)
        sensor = sensor or self._resolve_sensor(env_id)
        if str(getattr(self.cfg, "compute_path", "auto")) == "batched" and (
            sensor.velocity_world_mps is not None
            or any(
                source.velocity_world_mps is not None
                for source in scene_snapshot.sources
            )
        ):
            raise UnsupportedEffectError(
                "authored velocity Doppler semantics require the Lab scalar frame path"
            )
        kwargs: dict[str, Any] = {}
        if self.cfg.backend in {"tdoa_synthetic", "room_acoustics"}:
            kwargs = {"ambiguity_policy": self.cfg.ambiguity_policy}
        if self.cfg.backend == "room_acoustics":
            sink = self._resolve_waveform_sink(env_id)
            if sink is not None:
                kwargs["waveform_writer"] = sink
        effects = getattr(self.cfg, "effects", EffectsConfig())
        if not effects.all_disabled:
            kwargs["effects"] = effects
        backend = get_backend(self.cfg.backend, **kwargs)
        return backend.simulate(
            scene_snapshot,
            sensor,
            AudioTimeWindow(
                start_time_s=start_time_s,
                end_time_s=end_time_s,
                timestamp_ms=timestamp_ms,
                sample_rate_hz=sensor.sample_rate_hz,
                frame_index=self._frame_indices[env_id],
                max_events=self.cfg.max_events,
            ),
        )

    def _initialize_impl(self) -> None:
        if _LAB_TYPES is not None:
            super()._initialize_impl()
            self._ensure_runtime_buffers(num_envs=self._num_envs, device=self.device)
        else:
            self._ensure_runtime_buffers()

    def _update_buffers_impl(self, env_ids: Sequence[int]) -> None:
        ids = self._ids_to_list(env_ids)
        if not ids:
            return
        self._ensure_runtime_buffers(num_envs=max(self._known_num_envs(), max(ids) + 1))
        requested_batched = str(getattr(self.cfg, "compute_path", "auto")) == "batched"
        if requested_batched:
            self._validate_batched_effects()
        if self._resolve_compute_path() == "batched":
            if not requested_batched:
                self._validate_batched_effects()
            self._update_buffers_batched(ids)
            return
        self._last_compute_path = "scalar"
        bindings = self._resolve_bindings(
            ids,
            sim_time_s_by_env={env_id: self._timestamp_value(env_id) for env_id in ids},
        )
        for env_id in ids:
            scene_snapshot, sensor = bindings[env_id]
            timestamp_s = self._timestamp_value(env_id)
            timestamp_ms = self._pending_timestamp_ms.pop(
                env_id,
                int(round(timestamp_s * 1000.0)),
            )
            window_s = max(float(self.cfg.update_period), 1e-3)
            frame = self.capture_frame(
                scene_snapshot=scene_snapshot,
                sensor=sensor,
                timestamp_ms=timestamp_ms,
                start_time_s=timestamp_s,
                end_time_s=timestamp_s + window_s,
                env_id=env_id,
            )
            frame = self._attach_provider_diagnostics(
                frame=frame,
                env_id=env_id,
            )
            microphone_ids = tuple(
                microphone.mic_id for microphone in sensor.microphones
            )
            self._data.write_frame(
                env_id=env_id,
                frame=frame,
                microphone_ids=microphone_ids,
                timestamp_s=timestamp_s,
            )
            self._frame_indices[env_id] += 1

    def _update_buffers_batched(self, ids: Sequence[int]) -> None:
        torch = _require_torch()
        batch = self._pose_batch_on_device(
            self._scene_provider.pose_tensor_batch(ids)
        )
        static = batch.static
        ids_t = torch.tensor(ids, dtype=torch.long, device=self._device)
        start_time_s = self._timestamp[ids_t]
        window_s = max(float(self.cfg.update_period), 1e-3)
        end_time_s = start_time_s + window_s
        active = (
            static.source_start_s.unsqueeze(0) < end_time_s.unsqueeze(1)
        ) & (static.source_end_s.unsqueeze(0) > start_time_s.unsqueeze(1))
        if self.cfg.backend == "geometry_only":
            observations = batched_geometry_observations(batch)
        else:
            solve_op, baseline = self._lstsq_operator(static)
            observations = batched_tdoa_observations(
                batch,
                solve_op=solve_op,
                baseline_matrix=baseline,
            )
        events = compact_active_events(
            observations,
            active_mask=active,
            max_events=int(self.cfg.max_events),
        )
        self._data.write_batch(
            env_ids=ids_t,
            last_update_time_s=start_time_s,
            microphone_ids=static.mic_ids,
            **events,
        )
        self._last_compute_path = "batched"
        for env_id in ids:
            self._frame_indices[int(env_id)] += 1
        if self._pending_timestamp_ms:
            for env_id in ids:
                self._pending_timestamp_ms.pop(int(env_id), None)

    def _validate_batched_effects(self) -> None:
        """Reject semantics the Stage 1 tensor kernel cannot represent."""

        effects = getattr(self.cfg, "effects", EffectsConfig())
        if effects.motion.derive_velocity_from_poses:
            raise UnsupportedEffectError(
                "derive_velocity_from_poses=true is unsupported by Isaac Lab "
                "batched compute in Stage 1"
            )
        if effects.motion.segments_per_window > 1:
            raise UnsupportedEffectError(
                "audio.effects.motion.segments_per_window>1 is unsupported by "
                "Isaac Lab batched compute"
            )
        for stage_name, stage in (
            ("channel_response", effects.channel_response),
            ("noise", effects.noise),
            ("electronics", effects.electronics),
            ("directivity", effects.directivity),
        ):
            if stage.enabled:
                raise UnsupportedEffectError(
                    f"audio.effects.{stage_name} is unsupported by Isaac Lab "
                    "batched compute"
                )
        snapshots = getattr(self, "_bound_scene_snapshots", {})
        for snapshot in snapshots.values():
            if snapshot.occlusion:
                raise UnsupportedEffectError(
                    "AudioSceneSnapshot.occlusion is unsupported by Isaac Lab "
                    "batched compute"
                )
            if snapshot.room is not None:
                raise UnsupportedEffectError(
                    "AudioSceneSnapshot.room is unsupported by Isaac Lab batched "
                    "compute"
                )
        provider_cfg = getattr(getattr(self, "_scene_provider", None), "cfg", None)
        if getattr(provider_cfg, "room", None) is not None:
            raise UnsupportedEffectError(
                "LabAudioEntityBindingCfg.room is unsupported by Isaac Lab batched "
                "compute"
            )
        if getattr(provider_cfg, "room_prim_path", None) is not None:
            raise UnsupportedEffectError(
                "LabAudioStageBindingCfg.room_prim_path is unsupported by Isaac Lab "
                "batched compute"
            )

    def _pose_batch_on_device(
        self,
        batch: EntityPoseTensorBatch,
    ) -> EntityPoseTensorBatch:
        if str(batch.array_positions.device) == str(self._device):
            return batch
        return EntityPoseTensorBatch(
            env_ids=batch.env_ids.to(self._device),
            array_positions=batch.array_positions.to(self._device),
            array_quats_xyzw=batch.array_quats_xyzw.to(self._device),
            source_positions=batch.source_positions.to(self._device),
            source_quats_xyzw=batch.source_quats_xyzw.to(self._device),
            static=self._scene_provider.static_batch_meta(device=self._device),
        )

    def _lstsq_operator(self, static: EntityStaticBatchMeta) -> tuple[Any, Any]:
        cached = self._lstsq_cache
        if cached is not None and cached[0] == id(static):
            return cached[1], cached[2]
        solve_op, baseline, det = precompute_lstsq_operator(
            static.mic_offsets_local
        )
        if abs(det) <= EPSILON:
            raise ValueError(
                "Microphone layout is degenerate for batched TDOA "
                "least-squares; use the scalar compute path."
            )
        self._lstsq_cache = (id(static), solve_op, baseline)
        return solve_op, baseline

    def _resolve_compute_path(self) -> str:
        requested = str(getattr(self.cfg, "compute_path", "auto"))
        if requested == "scalar":
            return "scalar"
        key = id(self._scene_provider)
        cached = self._compute_path_decision
        if cached is not None and cached[0] == key:
            return cached[1]
        failure = self._batched_prerequisite_failure()
        if failure is None:
            provider_cfg = getattr(self._scene_provider, "cfg", None)
            opted_out_of_diagnostics = (
                getattr(provider_cfg, "diagnostics", True) is False
            )
            decision = (
                "batched"
                if requested == "batched" or opted_out_of_diagnostics
                else "scalar"
            )
        elif requested == "batched":
            raise ValueError(f"compute_path='batched' is unavailable: {failure}")
        else:
            decision = "scalar"
        self._compute_path_decision = (key, decision)
        return decision

    def _batched_prerequisite_failure(self) -> str | None:
        provider = self._scene_provider
        if not callable(getattr(provider, "pose_tensor_batch", None)):
            return (
                "the scene provider does not expose pose tensors "
                "(entity binding is required)"
            )
        if self.cfg.backend not in {"geometry_only", "tdoa_synthetic"}:
            return f"backend {self.cfg.backend!r} has no batched implementation"
        if getattr(self.cfg, "write_waveforms", False):
            return "write_waveforms requires the scalar frame pipeline"
        if self.cfg.backend == "tdoa_synthetic":
            if self._known_num_mics() < 3:
                return (
                    "batched tdoa_synthetic requires at least 3 microphones "
                    "(2-mic ambiguity handling is scalar-only)"
                )
            static = provider.static_batch_meta(device=self._device)
            _solve_op, _baseline, det = precompute_lstsq_operator(
                static.mic_offsets_local
            )
            if abs(det) <= EPSILON:
                return "microphone layout is rank-deficient in local XY"
        return None

    def _set_debug_vis_impl(self, debug_vis: bool) -> None:
        self._is_visualizing = bool(debug_vis)

    def _debug_vis_callback(self, event: object) -> None:
        return None

    def _update_outdated_buffers(self) -> None:
        if not self._has_runtime_buffers():
            return
        outdated_env_ids = self._is_outdated.nonzero().squeeze(-1)
        ids = self._ids_to_list(outdated_env_ids)
        if ids:
            self._update_selected_buffers(ids)

    def _update_selected_buffers(self, env_ids: Sequence[int]) -> None:
        ids = tuple(int(env_id) for env_id in env_ids)
        if not ids:
            return
        self._update_buffers_impl(ids)
        self._timestamp_last_update[list(ids)] = self._timestamp[list(ids)]
        self._is_outdated[list(ids)] = False

    def _ensure_runtime_buffers(
        self,
        *,
        num_envs: int | None = None,
        num_mics: int | None = None,
        device: str | None = None,
    ) -> None:
        torch = _require_torch()
        resolved_num_envs = int(num_envs or self._known_num_envs() or 1)
        resolved_num_mics = int(num_mics or self._known_num_mics())
        current_device = self._device if hasattr(self, "_device") else None
        resolved_device = str(device or current_device or self._manual_device)
        if self.cfg.device is not None:
            resolved_device = str(self.cfg.device)

        shape_matches = (
            hasattr(self._data.event_presence, "shape")
            and tuple(self._data.event_presence.shape)
            == (resolved_num_envs, int(self.cfg.max_events))
            and tuple(self._data.per_mic_rms.shape)
            == (resolved_num_envs, int(self.cfg.max_events), resolved_num_mics)
            and str(self._data.event_presence.device) == resolved_device
        )
        if not shape_matches:
            self._data = AudioArraySensorData.allocate(
                num_envs=resolved_num_envs,
                max_events=int(self.cfg.max_events),
                num_mics=resolved_num_mics,
                device=resolved_device,
                sector_order=SECTOR_ORDER,
            )

        if (
            not hasattr(self, "_timestamp")
            or tuple(self._timestamp.shape) != (resolved_num_envs,)
            or str(self._timestamp.device) != resolved_device
        ):
            self._timestamp = torch.zeros(
                resolved_num_envs,
                dtype=torch.float32,
                device=resolved_device,
            )
            self._timestamp_last_update = torch.zeros_like(self._timestamp)
            self._is_outdated = torch.ones(
                resolved_num_envs,
                dtype=torch.bool,
                device=resolved_device,
            )

        if len(self._frame_indices) != resolved_num_envs:
            existing = list(self._frame_indices[:resolved_num_envs])
            existing.extend(0 for _ in range(resolved_num_envs - len(existing)))
            self._frame_indices = existing
        self._num_envs = resolved_num_envs
        self._device = resolved_device

    def _has_runtime_buffers(self) -> bool:
        return hasattr(self, "_timestamp") and hasattr(
            self._data.event_presence,
            "shape",
        )

    def _known_num_envs(self) -> int:
        candidates = [
            self._manual_num_envs or 0,
            len(self._bound_scene_snapshots),
            len(self._bound_sensors),
            int(getattr(self, "_num_envs", 0) or 0),
        ]
        return max(candidates)

    def _known_num_mics(self) -> int:
        if self.cfg.num_mics is not None:
            return int(self.cfg.num_mics)
        if self._bound_sensors:
            return _derive_num_mics_from_sensors(tuple(self._bound_sensors.values()))
        provider_num_mics = getattr(self._scene_provider, "num_mics", None)
        if provider_num_mics:
            return int(provider_num_mics)
        return len(microphone_layout(self.cfg.microphone_layout))

    def _mark_outdated(self, env_ids: Sequence[int] | range) -> None:
        if self._has_runtime_buffers():
            ids = [int(env_id) for env_id in env_ids]
            self._is_outdated[ids] = True

    def _normalize_env_ids(
        self,
        env_ids: Sequence[int] | int | None,
    ) -> Any:
        torch = _require_torch()
        if env_ids is None:
            return torch.arange(self._known_num_envs(), device=self._device)
        if isinstance(env_ids, int):
            ids = (env_ids,)
        else:
            ids = tuple(int(env_id) for env_id in env_ids)
        if any(env_id < 0 for env_id in ids):
            raise ValueError("env_ids must be non-negative.")
        if ids and max(ids) >= self._known_num_envs():
            self._ensure_runtime_buffers(num_envs=max(ids) + 1)
        return torch.tensor(ids, dtype=torch.long, device=self._device)

    def _ids_to_list(self, env_ids: Any) -> list[int]:
        if isinstance(env_ids, slice):
            return list(range(self._known_num_envs()))
        if hasattr(env_ids, "detach"):
            return [int(value) for value in env_ids.detach().cpu().tolist()]
        if isinstance(env_ids, int):
            return [env_ids]
        return [int(value) for value in env_ids]

    def _bind_update_inputs(
        self,
        *,
        scene_snapshot: AudioSceneSnapshot | Sequence[AudioSceneSnapshot] | None,
        sensor: MicrophoneArraySpec | Sequence[MicrophoneArraySpec] | None,
        env_ids: Sequence[int] | int | None,
    ) -> None:
        if scene_snapshot is None or sensor is None:
            raise ValueError("scene_snapshot and sensor must be provided together.")
        if isinstance(scene_snapshot, AudioSceneSnapshot):
            if not isinstance(sensor, MicrophoneArraySpec):
                raise TypeError("sensor must be a MicrophoneArraySpec.")
            env_id = 0 if env_ids is None else self._ids_to_list(env_ids)[0]
            self.bind_env(
                env_id=env_id,
                scene_snapshot=scene_snapshot,
                sensor=sensor,
            )
            return
        sensors = sensor if isinstance(sensor, MicrophoneArraySpec) else tuple(sensor)
        self.bind_envs(scene_snapshots=tuple(scene_snapshot), sensors=sensors)

    def _resolve_bindings(
        self,
        env_ids: Sequence[int],
        *,
        sim_time_s_by_env: Mapping[int, float] | None = None,
    ) -> dict[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]]:
        ids = tuple(int(env_id) for env_id in env_ids)
        if self._scene_provider is not None:
            set_context = getattr(self._scene_provider, "set_update_context", None)
            if callable(set_context):
                set_context(sim_time_s_by_env=sim_time_s_by_env)
            provided = dict(self._scene_provider(ids))
        else:
            provided = {}
        bindings: dict[int, tuple[AudioSceneSnapshot, MicrophoneArraySpec]] = {}
        for env_id in ids:
            binding = provided.get(env_id)
            if binding is None:
                binding = (
                    self._resolve_scene_snapshot(env_id),
                    self._resolve_sensor(env_id),
                )
            bindings[env_id] = binding
        return bindings

    def _attach_provider_diagnostics(
        self,
        *,
        frame: AudioSensorFrame,
        env_id: int,
    ) -> AudioSensorFrame:
        diagnostics_by_env = getattr(self._scene_provider, "last_diagnostics", None)
        if not isinstance(diagnostics_by_env, Mapping):
            return frame
        provider_diagnostics = diagnostics_by_env.get(int(env_id))
        if not provider_diagnostics:
            return frame
        diagnostics_key = getattr(
            self._scene_provider,
            "diagnostics_key",
            "stage_binding",
        )
        return replace(
            frame,
            diagnostics={
                **frame.diagnostics,
                str(diagnostics_key): dict(provider_diagnostics),
            },
        )

    def _resolve_scene_snapshot(self, env_id: int) -> AudioSceneSnapshot:
        try:
            return self._bound_scene_snapshots[int(env_id)]
        except KeyError as exc:
            raise ValueError(
                f"No AudioSceneSnapshot is bound for env {env_id}. Use bind_envs() "
                "or bind_provider() before reading data."
            ) from exc

    def _resolve_waveform_sink(self, env_id: int) -> FrameWaveformWriter | None:
        """Build the per-env waveform writer when waveform export is enabled.

        Per-env subdirectories keep deterministic frame file names from
        colliding across vectorized environments.
        """

        if not getattr(self.cfg, "write_waveforms", False):
            return None
        if env_id not in self._waveform_sinks:
            base_dir = self.cfg.waveform_dir or "outputs/audio_waveforms"
            self._waveform_sinks[env_id] = FrameWaveformWriter(
                f"{base_dir}/env_{env_id}"
            )
        return self._waveform_sinks[env_id]

    def _resolve_sensor(self, env_id: int) -> MicrophoneArraySpec:
        try:
            return self._bound_sensors[int(env_id)]
        except KeyError as exc:
            raise ValueError(
                f"No MicrophoneArraySpec is bound for env {env_id}. Use bind_envs() "
                "or bind_provider() before reading data."
            ) from exc

    def _timestamp_value(self, env_id: int) -> float:
        value = self._timestamp[int(env_id)]
        if hasattr(value, "item"):
            return float(value.item())
        return float(value)


def _derive_num_mics_from_sensors(sensors: Sequence[MicrophoneArraySpec]) -> int:
    counts = {len(sensor.microphones) for sensor in sensors}
    if len(counts) != 1:
        raise ValueError("All bound environments must use the same microphone count.")
    return counts.pop()


def _stage_from_scene(scene: object) -> object:
    return resolve_lab_stage(scene)


def _require_torch() -> Any:
    try:
        import torch  # type: ignore

        return torch
    except ImportError as exc:
        raise RuntimeError(
            "AudioArraySensor requires torch for vectorized Lab buffers."
        ) from exc
