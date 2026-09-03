"""Steam Audio 4.8.1 native probes used only by R9.4."""

from __future__ import annotations

import ctypes
import math
import resource
import time
from dataclasses import dataclass, field

import numpy as np

from .fixtures import (
    BLOCK_SAMPLES,
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    SAMPLE_RATE_HZ,
    FixtureSpec,
    common_fixtures,
    generated_impulse,
)
from .models import DebugPathSample, bounded_diagnostics
from .r9_4 import (
    PathingFixtureSpec,
    PathingPerformanceRun,
    PathingRun,
    StreamingDelayScheduler,
    TimingRun,
)
from .steam_audio import (
    SteamAudioAdapter,
    _AirAbsorptionModel,
    _AudioBuffer,
    _AudioSettings,
    _BakedDataIdentifier,
    _check,
    _coordinate_space,
    _Directivity,
    _DistanceAttenuationModel,
    _PathEffectParams,
    _SimulationInputs,
    _SimulationOutputs,
    _SimulationSettings,
    _SimulationSharedInputs,
    _SourceSettings,
    _Sphere,
    _steam_vector,
    _Vector3,
)

_SIMULATE_PATHING = 1 << 2
_BAKED_DATA_PATHING = 1
_BAKED_VARIATION_DYNAMIC = 3
_PATHING_ORDER = 1
_PROBE_RADIUS_M = 1.25
_VIS_RADIUS_M = 0.1
_VIS_THRESHOLD = 0.5
_VIS_RANGE_M = 4.0
_PATH_RANGE_M = 20.0
_PATH_BAKE_SAMPLES = 4
_PATH_BAKE_THREADS = 1
_PATH_VIS_SAMPLES = 16
_SOUND_SPEED_M_S = 343.0


class _SpeakerLayout(ctypes.Structure):
    _fields_ = [
        ("layout_type", ctypes.c_int),
        ("num_speakers", ctypes.c_int32),
        ("speakers", ctypes.POINTER(_Vector3)),
    ]


class _PathEffectSettings(ctypes.Structure):
    _fields_ = [
        ("max_order", ctypes.c_int32),
        ("spatialize", ctypes.c_int),
        ("speaker_layout", _SpeakerLayout),
        ("hrtf", ctypes.c_void_p),
    ]


class _PathBakeParams(ctypes.Structure):
    _fields_ = [
        ("scene", ctypes.c_void_p),
        ("probe_batch", ctypes.c_void_p),
        ("identifier", _BakedDataIdentifier),
        ("num_samples", ctypes.c_int32),
        ("radius", ctypes.c_float),
        ("threshold", ctypes.c_float),
        ("vis_range", ctypes.c_float),
        ("path_range", ctypes.c_float),
        ("num_threads", ctypes.c_int32),
    ]


_PathVisualizationCallback = ctypes.CFUNCTYPE(
    None, _Vector3, _Vector3, ctypes.c_int, ctypes.c_void_p
)
_BakeProgressCallback = ctypes.CFUNCTYPE(None, ctypes.c_float, ctypes.c_void_p)


@dataclass(slots=True)
class _PathReceiver:
    simulator: ctypes.c_void_p
    source: ctypes.c_void_p
    path_effect: ctypes.c_void_p
    microphone_id: str
    microphone_xyz_m: tuple[float, float, float]
    outputs: _SimulationOutputs = field(default_factory=_SimulationOutputs)


@dataclass(slots=True)
class _PathSession:
    fixture: FixtureSpec
    scene: ctypes.c_void_p
    sub_scenes: list[ctypes.c_void_p]
    instances: list[tuple[str, ctypes.c_void_p]]
    receivers: list[_PathReceiver]
    source_xyz_m: tuple[float, float, float]
    array_xyz_m: tuple[float, float, float]
    probe_batch: ctypes.c_void_p
    baked_identifier: _BakedDataIdentifier
    bake_ms: float
    storage_bytes: int
    scheduler: StreamingDelayScheduler


def _ias_vector(vector: _Vector3) -> tuple[float, float, float]:
    return (-float(vector.z), float(vector.x), float(vector.y))


def _finite_rms_db(samples: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=np.float64)))))
    return -200.0 if rms == 0.0 else max(-200.0, 20.0 * math.log10(rms))


def _peak_index(samples: np.ndarray) -> int:
    return int(np.argmax(np.abs(np.asarray(samples))))


class SteamAudioR94Adapter(SteamAudioAdapter):
    """Extend the retained selected-provider adapter with bounded R9.4 probes."""

    def _bind(self) -> None:
        super()._bind()
        assert self._library is not None
        library = self._library
        library.iplProbeBatchCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplProbeBatchCreate.restype = ctypes.c_int
        library.iplProbeBatchRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplProbeBatchAddProbe.argtypes = [ctypes.c_void_p, _Sphere]
        library.iplProbeBatchCommit.argtypes = [ctypes.c_void_p]
        library.iplProbeBatchGetDataSize.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_BakedDataIdentifier),
        ]
        library.iplProbeBatchGetDataSize.restype = ctypes.c_size_t
        library.iplPathBakerBake.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PathBakeParams),
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.iplSimulatorAddProbeBatch.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.iplSimulatorRemoveProbeBatch.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.iplSimulatorRunPathing.argtypes = [ctypes.c_void_p]
        library.iplPathEffectCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_AudioSettings),
            ctypes.POINTER(_PathEffectSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplPathEffectCreate.restype = ctypes.c_int
        library.iplPathEffectApply.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PathEffectParams),
            ctypes.POINTER(_AudioBuffer),
            ctypes.POINTER(_AudioBuffer),
        ]
        library.iplPathEffectApply.restype = ctypes.c_int
        library.iplPathEffectReset.argtypes = [ctypes.c_void_p]
        library.iplPathEffectRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]

    @staticmethod
    def _audio_buffer(samples: np.ndarray) -> tuple[_AudioBuffer, object]:
        values = np.ascontiguousarray(samples, dtype=np.float32)
        if values.ndim == 1:
            values = values[np.newaxis, :]
        if values.ndim != 2:
            raise ValueError("audio buffer must be mono or channel-major.")
        pointer = ctypes.POINTER(ctypes.c_float)
        channels = (pointer * values.shape[0])(
            *(values[index].ctypes.data_as(pointer) for index in range(values.shape[0]))
        )
        return _AudioBuffer(values.shape[0], values.shape[1], channels), (
            values,
            channels,
        )

    def _create_probe_batch(
        self,
        scene: ctypes.c_void_p,
        probes_xyz_m: tuple[tuple[float, float, float], ...],
    ) -> tuple[ctypes.c_void_p, _BakedDataIdentifier, float, int]:
        assert self._library is not None
        probe_batch = ctypes.c_void_p()
        _check(
            self._library.iplProbeBatchCreate(self._context, ctypes.byref(probe_batch)),
            "iplProbeBatchCreate",
        )
        try:
            for position in probes_xyz_m:
                self._library.iplProbeBatchAddProbe(
                    probe_batch, _Sphere(_steam_vector(position), _PROBE_RADIUS_M)
                )
            self._library.iplProbeBatchCommit(probe_batch)
            identifier = _BakedDataIdentifier(
                _BAKED_DATA_PATHING,
                _BAKED_VARIATION_DYNAMIC,
                _Sphere(_Vector3(), 0.0),
            )
            params = _PathBakeParams(
                scene,
                probe_batch,
                identifier,
                _PATH_BAKE_SAMPLES,
                _VIS_RADIUS_M,
                _VIS_THRESHOLD,
                _VIS_RANGE_M,
                _PATH_RANGE_M,
                _PATH_BAKE_THREADS,
            )
            start = time.perf_counter_ns()
            progress_callback = _BakeProgressCallback(lambda _progress, _data: None)
            self._library.iplPathBakerBake(
                self._context,
                ctypes.byref(params),
                ctypes.cast(progress_callback, ctypes.c_void_p),
                None,
            )
            bake_ms = (time.perf_counter_ns() - start) / 1e6
            storage_bytes = int(
                self._library.iplProbeBatchGetDataSize(
                    probe_batch, ctypes.byref(identifier)
                )
            )
            return probe_batch, identifier, bake_ms, storage_bytes
        except Exception:
            self._library.iplProbeBatchRelease(ctypes.byref(probe_batch))
            raise

    def _create_path_receiver(
        self,
        scene: ctypes.c_void_p,
        probe_batch: ctypes.c_void_p,
        microphone_id: str,
        microphone_xyz_m: tuple[float, float, float],
    ) -> _PathReceiver:
        assert self._library is not None
        simulator = ctypes.c_void_p()
        source = ctypes.c_void_p()
        path_effect = ctypes.c_void_p()
        settings = _SimulationSettings(
            _SIMULATE_PATHING,
            1,
            0,
            1,
            1,
            1,
            0.1,
            _PATHING_ORDER,
            1,
            1,
            16,
            _PATH_VIS_SAMPLES,
            SAMPLE_RATE_HZ,
            BLOCK_SAMPLES,
            None,
            None,
            None,
        )
        _check(
            self._library.iplSimulatorCreate(
                self._context, ctypes.byref(settings), ctypes.byref(simulator)
            ),
            "iplSimulatorCreate",
        )
        try:
            self._library.iplSimulatorSetScene(simulator, scene)
            self._library.iplSimulatorAddProbeBatch(simulator, probe_batch)
            _check(
                self._library.iplSourceCreate(
                    simulator,
                    ctypes.byref(_SourceSettings(_SIMULATE_PATHING)),
                    ctypes.byref(source),
                ),
                "iplSourceCreate",
            )
            self._library.iplSourceAdd(source, simulator)
            self._library.iplSimulatorCommit(simulator)
            _check(
                self._library.iplPathEffectCreate(
                    self._context,
                    ctypes.byref(_AudioSettings(SAMPLE_RATE_HZ, BLOCK_SAMPLES)),
                    ctypes.byref(
                        _PathEffectSettings(
                            _PATHING_ORDER,
                            0,
                            _SpeakerLayout(0, 0, None),
                            None,
                        )
                    ),
                    ctypes.byref(path_effect),
                ),
                "iplPathEffectCreate",
            )
        except Exception:
            if path_effect.value:
                self._library.iplPathEffectRelease(ctypes.byref(path_effect))
            if source.value:
                self._library.iplSourceRelease(ctypes.byref(source))
            if simulator.value:
                self._library.iplSimulatorRelease(ctypes.byref(simulator))
            raise
        return _PathReceiver(
            simulator,
            source,
            path_effect,
            microphone_id,
            microphone_xyz_m,
        )

    def _create_path_session(self, spec: PathingFixtureSpec) -> _PathSession:
        self._initialize()
        scene, sub_scenes, instances = self._create_fixture_scene(spec.fixture)
        probe_batch = ctypes.c_void_p()
        receivers: list[_PathReceiver] = []
        try:
            probe_batch, identifier, bake_ms, storage_bytes = self._create_probe_batch(
                scene, spec.probes_xyz_m
            )
            for microphone_id, offset in zip(
                MICROPHONE_IDS, QUAD_FRONT_OFFSETS_M, strict=True
            ):
                microphone_xyz_m = tuple(
                    coordinate + delta
                    for coordinate, delta in zip(
                        spec.fixture.array_xyz_m, offset, strict=True
                    )
                )
                receivers.append(
                    self._create_path_receiver(
                        scene,
                        probe_batch,
                        microphone_id,
                        microphone_xyz_m,
                    )
                )
            return _PathSession(
                spec.fixture,
                scene,
                sub_scenes,
                instances,
                receivers,
                spec.fixture.source_xyz_m,
                spec.fixture.array_xyz_m,
                probe_batch,
                identifier,
                bake_ms,
                storage_bytes,
                StreamingDelayScheduler(
                    channel_count=len(MICROPHONE_IDS),
                    sample_rate_hz=SAMPLE_RATE_HZ,
                ),
            )
        except Exception:
            temporary = _PathSession(
                spec.fixture,
                scene,
                sub_scenes,
                instances,
                receivers,
                spec.fixture.source_xyz_m,
                spec.fixture.array_xyz_m,
                probe_batch,
                _BakedDataIdentifier(),
                0.0,
                0,
                StreamingDelayScheduler(
                    channel_count=len(MICROPHONE_IDS),
                    sample_rate_hz=SAMPLE_RATE_HZ,
                ),
            )
            self._close_path_session(temporary)
            raise

    def _path_inputs(
        self,
        session: _PathSession,
        *,
        validation: bool,
        alternate_paths: bool,
    ) -> _SimulationInputs:
        return _SimulationInputs(
            _SIMULATE_PATHING,
            0,
            _coordinate_space(session.source_xyz_m),
            _DistanceAttenuationModel(0, 1.0, None, None, 0),
            _AirAbsorptionModel(0, (ctypes.c_float * 3)(0.0, 0.0, 0.0), None, None, 0),
            _Directivity(0.0, 1.0, None, None),
            0,
            0.1,
            1,
            (ctypes.c_float * 3)(1.0, 1.0, 1.0),
            0.0,
            0.0,
            0,
            session.baked_identifier,
            session.probe_batch,
            _VIS_RADIUS_M,
            _VIS_THRESHOLD,
            _VIS_RANGE_M,
            _PATHING_ORDER,
            int(validation),
            int(alternate_paths),
            1,
            None,
        )

    def _render_path_session(
        self,
        session: _PathSession,
        signal: np.ndarray,
        *,
        reset: bool,
        validation: bool,
        alternate_paths: bool,
        diagnostics: bool,
        frame_index: int,
        schedule: bool,
        run_simulation: bool = True,
    ) -> tuple[np.ndarray, tuple[DebugPathSample, ...], dict[str, object]]:
        assert self._library is not None
        channels: list[np.ndarray] = []
        diagnostic_items: list[DebugPathSample] = []
        native_peak_indices: list[int] = []
        eq_coefficients: list[list[float]] = []
        sh_coefficients: list[list[float]] = []
        for receiver in session.receivers:
            receiver_diagnostics: list[DebugPathSample] = []

            def visualize(
                start: _Vector3,
                end: _Vector3,
                occluded: int,
                _user_data: ctypes.c_void_p,
                *,
                receiver_state: _PathReceiver = receiver,
                diagnostic_target: list[DebugPathSample] = receiver_diagnostics,
            ) -> None:
                diagnostic_target.append(
                    DebugPathSample(
                        "source",
                        receiver_state.microphone_id,
                        frame_index,
                        (_ias_vector(start), _ias_vector(end)),
                        {"occluded": bool(occluded)},
                    )
                )

            callback = _PathVisualizationCallback(visualize) if diagnostics else None
            if run_simulation:
                shared = _SimulationSharedInputs(
                    _coordinate_space(receiver.microphone_xyz_m),
                    1,
                    1,
                    0.1,
                    _PATHING_ORDER,
                    1.0,
                    ctypes.cast(callback, ctypes.c_void_p) if callback else None,
                    None,
                )
                inputs = self._path_inputs(
                    session,
                    validation=validation,
                    alternate_paths=alternate_paths,
                )
                self._library.iplSimulatorSetSharedInputs(
                    receiver.simulator, _SIMULATE_PATHING, ctypes.byref(shared)
                )
                self._library.iplSourceSetInputs(
                    receiver.source, _SIMULATE_PATHING, ctypes.byref(inputs)
                )
                self._library.iplSimulatorRunPathing(receiver.simulator)
                self._library.iplSourceGetOutputs(
                    receiver.source,
                    _SIMULATE_PATHING,
                    ctypes.byref(receiver.outputs),
                )
            params = receiver.outputs.pathing
            params.order = _PATHING_ORDER
            params.binaural = 0
            params.hrtf = None
            params.listener = _coordinate_space(receiver.microphone_xyz_m)
            params.normalize_eq = 0
            eq_coefficients.append([float(value) for value in params.eq_coeffs])
            sh_values = [float(params.sh_coeffs[index]) for index in range(4)]
            sh_coefficients.append(sh_values)
            input_buffer, input_keepalive = self._audio_buffer(signal)
            output_buffer, output_keepalive = self._audio_buffer(
                np.zeros((4, BLOCK_SAMPLES), dtype=np.float32)
            )
            if reset:
                self._library.iplPathEffectReset(receiver.path_effect)
            self._library.iplPathEffectApply(
                receiver.path_effect,
                ctypes.byref(params),
                ctypes.byref(input_buffer),
                ctypes.byref(output_buffer),
            )
            del input_keepalive
            rendered = np.asarray(output_keepalive[0][0], dtype=np.float32).copy()
            native_peak_indices.append(_peak_index(rendered))
            channels.append(rendered)
            diagnostic_items.extend(receiver_diagnostics)
        native = np.stack(channels)
        if schedule:
            delays_s = tuple(
                float(
                    np.linalg.norm(
                        np.asarray(session.source_xyz_m, dtype=np.float64)
                        - np.asarray(receiver.microphone_xyz_m, dtype=np.float64)
                    )
                )
                / _SOUND_SPEED_M_S
                for receiver in session.receivers
            )
            rendered = session.scheduler.process(native, delays_s)
        else:
            delays_s = (0.0,) * len(session.receivers)
            rendered = native
        diagnostics_out = bounded_diagnostics(diagnostic_items)
        return (
            rendered,
            diagnostics_out,
            {
                "delay_s": list(delays_s),
                "diagnostic_count": len(diagnostics_out),
                "eq_coefficients": eq_coefficients,
                "native_peak_indices": native_peak_indices,
                "occluded_segment_count": sum(
                    bool(item.metadata.get("occluded")) for item in diagnostics_out
                ),
                "sh_coefficients": sh_coefficients,
            },
        )

    def run_pathing_fixture(
        self,
        spec: PathingFixtureSpec,
        *,
        repetition: int,
    ) -> PathingRun:
        session = self._create_path_session(spec)
        signal = generated_impulse()
        try:
            session.scheduler.reset()
            enabled, diagnostics, enabled_metrics = self._render_path_session(
                session,
                signal,
                reset=True,
                validation=False,
                alternate_paths=False,
                diagnostics=True,
                frame_index=repetition,
                schedule=True,
            )
            validated = None
            alternate = None
            validated_metrics: dict[str, object] | None = None
            alternate_metrics: dict[str, object] | None = None
            update_ms = 0.0
            if spec.dynamic_translation_xyz_m is not None:
                update_ms = self._move_assembly(
                    session,
                    "path_blocker",
                    spec.dynamic_translation_xyz_m,
                )
                session.scheduler.reset()
                validated, validated_diagnostics, validated_metrics = (
                    self._render_path_session(
                        session,
                        signal,
                        reset=True,
                        validation=True,
                        alternate_paths=False,
                        diagnostics=True,
                        frame_index=repetition,
                        schedule=True,
                    )
                )
                session.scheduler.reset()
                alternate, alternate_diagnostics, alternate_metrics = (
                    self._render_path_session(
                        session,
                        signal,
                        reset=True,
                        validation=True,
                        alternate_paths=True,
                        diagnostics=True,
                        frame_index=repetition,
                        schedule=True,
                    )
                )
                diagnostics = bounded_diagnostics(
                    (*diagnostics, *validated_diagnostics, *alternate_diagnostics)
                )
            disabled = np.zeros_like(enabled)
            measurements = {
                "alternate": alternate_metrics,
                "bake_ms": session.bake_ms,
                "enabled": enabled_metrics,
                "probe_count": len(spec.probes_xyz_m),
                "storage_bytes": session.storage_bytes,
                "update_ms": update_ms,
                "validated": validated_metrics,
            }
            return PathingRun(
                spec.fixture.fixture_id,
                repetition,
                disabled,
                enabled,
                validated,
                alternate,
                diagnostics,
                measurements,
            )
        finally:
            self._close_path_session(session)

    def run_timing_qualification(
        self,
        pathing_spec: PathingFixtureSpec,
    ) -> TimingRun:
        direct_fixture = FixtureSpec(
            "r9.4_timing_direct",
            "r9.4_timing",
            (3.0, 0.6, 1.2),
            (0.0, 0.0, 1.2),
        )
        direct_session = self._create_session(direct_fixture)
        reflection_fixture = next(
            fixture
            for fixture in common_fixtures()
            if fixture.fixture_id == "reflective_room"
        )
        reflection_session = self._create_session(reflection_fixture)
        path_session = self._create_path_session(pathing_spec)
        impulse = generated_impulse()
        try:
            self._refresh_session(direct_session)
            direct_components, _ = self._render_session(
                direct_session,
                impulse,
                reset=True,
                include_reference=False,
            )
            native_direct = direct_components["native_direct"]
            direct_scheduler = StreamingDelayScheduler(
                channel_count=len(MICROPHONE_IDS), sample_rate_hz=SAMPLE_RATE_HZ
            )
            direct_delays_s = tuple(
                float(
                    np.linalg.norm(
                        np.asarray(direct_session.source_xyz_m)
                        - np.asarray(receiver.microphone_xyz_m)
                    )
                )
                / _SOUND_SPEED_M_S
                for receiver in direct_session.receivers
            )
            scheduled_direct = direct_scheduler.process(native_direct, direct_delays_s)

            self._refresh_session(reflection_session)
            reflection_components, _ = self._render_session(
                reflection_session,
                impulse,
                reset=True,
                include_reference=False,
            )
            native_reflections = reflection_components["reflections"]
            final_reflections = native_reflections.copy()

            path_session.scheduler.reset()
            native_path, _, native_path_metrics = self._render_path_session(
                path_session,
                impulse,
                reset=True,
                validation=False,
                alternate_paths=False,
                diagnostics=False,
                frame_index=0,
                schedule=False,
            )
            path_session.scheduler.reset()
            scheduled_path, _, scheduled_path_metrics = self._render_path_session(
                path_session,
                impulse,
                reset=True,
                validation=False,
                alternate_paths=False,
                diagnostics=False,
                frame_index=0,
                schedule=True,
            )

            continuous = np.sin(
                2.0
                * math.pi
                * 997.0
                * np.arange(BLOCK_SAMPLES * 3, dtype=np.float64)
                / SAMPLE_RATE_HZ
            ).astype(np.float32)
            source = np.tile(continuous, (len(MICROPHONE_IDS), 1))
            static_scheduler = StreamingDelayScheduler(
                channel_count=len(MICROPHONE_IDS), sample_rate_hz=SAMPLE_RATE_HZ
            )
            static_blocks = np.concatenate(
                [
                    static_scheduler.process(
                        source[:, start : start + BLOCK_SAMPLES], direct_delays_s
                    )
                    for start in range(0, source.shape[1], BLOCK_SAMPLES)
                ],
                axis=1,
            )
            whole_scheduler = StreamingDelayScheduler(
                channel_count=len(MICROPHONE_IDS), sample_rate_hz=SAMPLE_RATE_HZ
            )
            static_whole = whole_scheduler.process(source, direct_delays_s)

            moving_scheduler = StreamingDelayScheduler(
                channel_count=len(MICROPHONE_IDS), sample_rate_hz=SAMPLE_RATE_HZ
            )
            moving_blocks = []
            moving_targets = []
            for block_index, start in enumerate(
                range(0, source.shape[1], BLOCK_SAMPLES)
            ):
                moved_source = np.asarray(direct_session.source_xyz_m) + np.asarray(
                    (0.15 * block_index, 0.05 * block_index, 0.0)
                )
                target = tuple(
                    float(
                        np.linalg.norm(
                            moved_source - np.asarray(receiver.microphone_xyz_m)
                        )
                    )
                    / _SOUND_SPEED_M_S
                    for receiver in direct_session.receivers
                )
                moving_targets.append(target)
                moving_blocks.append(
                    moving_scheduler.process(
                        source[:, start : start + BLOCK_SAMPLES], target
                    )
                )
            moving = np.concatenate(moving_blocks, axis=1)
            boundaries = (BLOCK_SAMPLES, BLOCK_SAMPLES * 2)
            adjacent_steps = np.max(np.abs(moving[:, 1:] - moving[:, :-1]), axis=0)
            boundary_steps = [float(adjacent_steps[index - 1]) for index in boundaries]
            local_steps = [
                float(
                    np.max(
                        np.concatenate(
                            (
                                adjacent_steps[max(0, index - 65) : index - 1],
                                adjacent_steps[
                                    index : min(adjacent_steps.size, index + 64)
                                ],
                            )
                        )
                    )
                )
                for index in boundaries
            ]
            measurements = {
                "direct": {
                    "delay_s": list(direct_delays_s),
                    "native_peak_indices": [
                        _peak_index(channel) for channel in native_direct
                    ],
                    "scheduled_peak_indices": [
                        _peak_index(channel) for channel in scheduled_direct
                    ],
                },
                "pathing": {
                    "native": native_path_metrics,
                    "scheduled": scheduled_path_metrics,
                    "native_peak_indices": [
                        _peak_index(channel) for channel in native_path
                    ],
                    "scheduled_peak_indices": [
                        _peak_index(channel) for channel in scheduled_path
                    ],
                },
                "reflections": {
                    "native_peak_indices": [
                        _peak_index(channel) for channel in native_reflections
                    ],
                    "unchanged": bool(
                        np.array_equal(native_reflections, final_reflections)
                    ),
                },
                "streaming": {
                    "boundary_steps": boundary_steps,
                    "local_max_steps": local_steps,
                    "moving_delay_targets_s": moving_targets,
                    "static_split_max_abs_error": float(
                        np.max(np.abs(static_blocks - static_whole))
                    ),
                },
            }
            return TimingRun(
                {
                    "native_direct": native_direct,
                    "scheduled_direct": scheduled_direct,
                    "native_pathing": native_path,
                    "scheduled_pathing": scheduled_path,
                    "native_reflections": native_reflections,
                    "final_reflections": final_reflections,
                    "streaming_moving": moving,
                    "streaming_static_split": static_blocks,
                    "streaming_static_whole": static_whole,
                },
                measurements,
            )
        finally:
            self._close_session(direct_session)
            self._close_session(reflection_session)
            self._close_path_session(path_session)

    def run_pathing_performance(
        self,
        spec: PathingFixtureSpec,
        *,
        environment_count: int,
        diagnostics: bool,
    ) -> PathingPerformanceRun:
        if environment_count not in (1, 4):
            raise ValueError("environment_count must be one or four.")
        sessions = [self._create_path_session(spec) for _ in range(environment_count)]
        signal = generated_impulse()
        try:
            for session in sessions:
                self._render_path_session(
                    session,
                    signal,
                    reset=True,
                    validation=False,
                    alternate_paths=False,
                    diagnostics=False,
                    frame_index=0,
                    schedule=True,
                )
            for _ in range(20):
                for session in sessions:
                    self._render_path_session(
                        session,
                        signal,
                        reset=False,
                        validation=False,
                        alternate_paths=False,
                        diagnostics=False,
                        frame_index=0,
                        schedule=True,
                        run_simulation=False,
                    )
            block_ms = []
            for index in range(200):
                start = time.perf_counter_ns()
                for session in sessions:
                    self._render_path_session(
                        session,
                        signal,
                        reset=False,
                        validation=False,
                        alternate_paths=False,
                        diagnostics=False,
                        frame_index=index,
                        schedule=True,
                        run_simulation=False,
                    )
                block_ms.append((time.perf_counter_ns() - start) / 1e6)

            for index in range(10):
                translation = (
                    spec.dynamic_translation_xyz_m
                    if index % 2 == 0
                    else (0.0, 0.0, 0.0)
                )
                assert translation is not None
                for session in sessions:
                    self._move_assembly(session, "path_blocker", translation)
                    self._render_path_session(
                        session,
                        signal,
                        reset=False,
                        validation=True,
                        alternate_paths=True,
                        diagnostics=False,
                        frame_index=index,
                        schedule=True,
                    )
            update_ms = []
            for index in range(50):
                translation = (
                    spec.dynamic_translation_xyz_m
                    if index % 2 == 0
                    else (0.0, 0.0, 0.0)
                )
                assert translation is not None
                start = time.perf_counter_ns()
                for session in sessions:
                    self._move_assembly(session, "path_blocker", translation)
                    self._render_path_session(
                        session,
                        signal,
                        reset=False,
                        validation=True,
                        alternate_paths=True,
                        diagnostics=diagnostics,
                        frame_index=index,
                        schedule=True,
                    )
                update_ms.append((time.perf_counter_ns() - start) / 1e6)
            return PathingPerformanceRun(
                environment_count,
                diagnostics,
                tuple(block_ms),
                tuple(update_ms),
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
            )
        finally:
            for session in reversed(sessions):
                self._close_path_session(session)

    def _close_path_session(self, session: _PathSession) -> None:
        if self._library is None:
            return
        for receiver in reversed(session.receivers):
            if receiver.path_effect.value:
                self._library.iplPathEffectRelease(ctypes.byref(receiver.path_effect))
            if receiver.source.value:
                self._library.iplSourceRemove(receiver.source, receiver.simulator)
                self._library.iplSourceRelease(ctypes.byref(receiver.source))
            if receiver.simulator.value:
                if session.probe_batch.value:
                    self._library.iplSimulatorRemoveProbeBatch(
                        receiver.simulator, session.probe_batch
                    )
                self._library.iplSimulatorRelease(ctypes.byref(receiver.simulator))
        if session.probe_batch.value:
            self._library.iplProbeBatchRelease(ctypes.byref(session.probe_batch))
        self._release_fixture_scene(
            session.scene, session.sub_scenes, session.instances
        )


__all__ = ["SteamAudioR94Adapter"]
