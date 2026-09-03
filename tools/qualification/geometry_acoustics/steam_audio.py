"""Temporary Steam Audio 4.8.1 adapter for R9.2 qualification."""

from __future__ import annotations

import ctypes
import os
import resource
import time
import wave
from pathlib import Path

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
from .metrics import (
    interpolate_transmission_energy,
    tone_losses_db,
    transmission_loss_db_to_energy,
)
from .models import FixtureRun, PerformanceRun, RuntimeProbe, SignalBlock

_API_VERSION = (4 << 16) | (8 << 8) | 1
_STATUS_SUCCESS = 0
_SIMD_AVX2 = 3
_CONTEXT_VALIDATION = 1
_SCENE_EMBREE = 1
_DIRECT_APPLY_DISTANCE = 1 << 0
_DIRECT_APPLY_OCCLUSION = 1 << 3
_DIRECT_APPLY_TRANSMISSION = 1 << 4
_DIRECT_SIMULATE_DISTANCE = 1 << 0
_DIRECT_SIMULATE_OCCLUSION = 1 << 3
_DIRECT_SIMULATE_TRANSMISSION = 1 << 4
_SIMULATE_DIRECT = 1 << 0
_TRANSMISSION_FREQUENCY_DEPENDENT = 1


class _Vector3(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float)]


class _Matrix4x4(ctypes.Structure):
    _fields_ = [("elements", (ctypes.c_float * 4) * 4)]


class _Triangle(ctypes.Structure):
    _fields_ = [("indices", ctypes.c_int32 * 3)]


class _Material(ctypes.Structure):
    _fields_ = [
        ("absorption", ctypes.c_float * 3),
        ("scattering", ctypes.c_float),
        ("transmission", ctypes.c_float * 3),
    ]


class _ContextSettings(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("log_callback", ctypes.c_void_p),
        ("allocate_callback", ctypes.c_void_p),
        ("free_callback", ctypes.c_void_p),
        ("simd_level", ctypes.c_int),
        ("flags", ctypes.c_int),
    ]


class _EmbreeDeviceSettings(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_ubyte)]


class _SceneSettings(ctypes.Structure):
    _fields_ = [
        ("scene_type", ctypes.c_int),
        ("closest_hit_callback", ctypes.c_void_p),
        ("any_hit_callback", ctypes.c_void_p),
        ("batched_closest_hit_callback", ctypes.c_void_p),
        ("batched_any_hit_callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
        ("embree_device", ctypes.c_void_p),
        ("radeon_rays_device", ctypes.c_void_p),
    ]


class _StaticMeshSettings(ctypes.Structure):
    _fields_ = [
        ("num_vertices", ctypes.c_int32),
        ("num_triangles", ctypes.c_int32),
        ("num_materials", ctypes.c_int32),
        ("vertices", ctypes.POINTER(_Vector3)),
        ("triangles", ctypes.POINTER(_Triangle)),
        ("material_indices", ctypes.POINTER(ctypes.c_int32)),
        ("materials", ctypes.POINTER(_Material)),
    ]


class _InstancedMeshSettings(ctypes.Structure):
    _fields_ = [("sub_scene", ctypes.c_void_p), ("transform", _Matrix4x4)]


class _AudioSettings(ctypes.Structure):
    _fields_ = [("sampling_rate", ctypes.c_int32), ("frame_size", ctypes.c_int32)]


class _DirectEffectSettings(ctypes.Structure):
    _fields_ = [("num_channels", ctypes.c_int32)]


class _DirectEffectParams(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("transmission_type", ctypes.c_int),
        ("distance_attenuation", ctypes.c_float),
        ("air_absorption", ctypes.c_float * 3),
        ("directivity", ctypes.c_float),
        ("occlusion", ctypes.c_float),
        ("transmission", ctypes.c_float * 3),
    ]


class _AudioBuffer(ctypes.Structure):
    _fields_ = [
        ("num_channels", ctypes.c_int32),
        ("num_samples", ctypes.c_int32),
        ("data", ctypes.POINTER(ctypes.POINTER(ctypes.c_float))),
    ]


class _DistanceAttenuationModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("min_distance", ctypes.c_float),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
        ("dirty", ctypes.c_int),
    ]


class _CoordinateSpace3(ctypes.Structure):
    _fields_ = [
        ("right", _Vector3),
        ("up", _Vector3),
        ("ahead", _Vector3),
        ("origin", _Vector3),
    ]


class _AirAbsorptionModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("coefficients", ctypes.c_float * 3),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
        ("dirty", ctypes.c_int),
    ]


class _Directivity(ctypes.Structure):
    _fields_ = [
        ("dipole_weight", ctypes.c_float),
        ("dipole_power", ctypes.c_float),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
    ]


class _Sphere(ctypes.Structure):
    _fields_ = [("center", _Vector3), ("radius", ctypes.c_float)]


class _BakedDataIdentifier(ctypes.Structure):
    _fields_ = [
        ("data_type", ctypes.c_int),
        ("variation", ctypes.c_int),
        ("endpoint_influence", _Sphere),
    ]


class _DeviationModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
    ]


class _SimulationSettings(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("scene_type", ctypes.c_int),
        ("reflection_type", ctypes.c_int),
        ("max_num_occlusion_samples", ctypes.c_int32),
        ("max_num_rays", ctypes.c_int32),
        ("num_diffuse_samples", ctypes.c_int32),
        ("max_duration", ctypes.c_float),
        ("max_order", ctypes.c_int32),
        ("max_num_sources", ctypes.c_int32),
        ("num_threads", ctypes.c_int32),
        ("ray_batch_size", ctypes.c_int32),
        ("num_vis_samples", ctypes.c_int32),
        ("sampling_rate", ctypes.c_int32),
        ("frame_size", ctypes.c_int32),
        ("opencl_device", ctypes.c_void_p),
        ("radeon_rays_device", ctypes.c_void_p),
        ("tan_device", ctypes.c_void_p),
    ]


class _SourceSettings(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_int)]


class _SimulationInputs(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("direct_flags", ctypes.c_int),
        ("source", _CoordinateSpace3),
        ("distance_attenuation_model", _DistanceAttenuationModel),
        ("air_absorption_model", _AirAbsorptionModel),
        ("directivity", _Directivity),
        ("occlusion_type", ctypes.c_int),
        ("occlusion_radius", ctypes.c_float),
        ("num_occlusion_samples", ctypes.c_int32),
        ("reverb_scale", ctypes.c_float * 3),
        ("hybrid_reverb_transition_time", ctypes.c_float),
        ("hybrid_reverb_overlap_percent", ctypes.c_float),
        ("baked", ctypes.c_int),
        ("baked_data_identifier", _BakedDataIdentifier),
        ("pathing_probes", ctypes.c_void_p),
        ("vis_radius", ctypes.c_float),
        ("vis_threshold", ctypes.c_float),
        ("vis_range", ctypes.c_float),
        ("pathing_order", ctypes.c_int32),
        ("enable_validation", ctypes.c_int),
        ("find_alternate_paths", ctypes.c_int),
        ("num_transmission_rays", ctypes.c_int32),
        ("deviation_model", ctypes.POINTER(_DeviationModel)),
    ]


class _SimulationSharedInputs(ctypes.Structure):
    _fields_ = [
        ("listener", _CoordinateSpace3),
        ("num_rays", ctypes.c_int32),
        ("num_bounces", ctypes.c_int32),
        ("duration", ctypes.c_float),
        ("order", ctypes.c_int32),
        ("irradiance_min_distance", ctypes.c_float),
        ("pathing_vis_callback", ctypes.c_void_p),
        ("pathing_user_data", ctypes.c_void_p),
    ]


class _ReflectionEffectParams(ctypes.Structure):
    _fields_ = [
        ("effect_type", ctypes.c_int),
        ("ir", ctypes.c_void_p),
        ("reverb_times", ctypes.c_float * 3),
        ("eq", ctypes.c_float * 3),
        ("delay", ctypes.c_int32),
        ("num_channels", ctypes.c_int32),
        ("ir_size", ctypes.c_int32),
        ("tan_device", ctypes.c_void_p),
        ("tan_slot", ctypes.c_int32),
    ]


class _PathEffectParams(ctypes.Structure):
    _fields_ = [
        ("eq_coeffs", ctypes.c_float * 3),
        ("sh_coeffs", ctypes.POINTER(ctypes.c_float)),
        ("order", ctypes.c_int32),
        ("binaural", ctypes.c_int),
        ("hrtf", ctypes.c_void_p),
        ("listener", _CoordinateSpace3),
        ("normalize_eq", ctypes.c_int),
    ]


class _SimulationOutputs(ctypes.Structure):
    _fields_ = [
        ("direct", _DirectEffectParams),
        ("reflections", _ReflectionEffectParams),
        ("pathing", _PathEffectParams),
    ]


def _check(status: int, operation: str) -> None:
    if status != _STATUS_SUCCESS:
        raise RuntimeError(f"{operation} failed with IPLerror {status}.")


def _identity_matrix() -> _Matrix4x4:
    matrix = _Matrix4x4()
    for row in range(4):
        matrix.elements[row][row] = 1.0
    return matrix


def _steam_vector(xyz_m: tuple[float, float, float]) -> _Vector3:
    """Map IAS world axes to Steam's right/up/-ahead convention."""

    x, y, z = xyz_m
    return _Vector3(y, z, -x)


def _coordinate_space(xyz_m: tuple[float, float, float]) -> _CoordinateSpace3:
    return _CoordinateSpace3(
        _Vector3(1.0, 0.0, 0.0),
        _Vector3(0.0, 1.0, 0.0),
        _Vector3(0.0, 0.0, -1.0),
        _steam_vector(xyz_m),
    )


def _translation_matrix(xyz_m: tuple[float, float, float]) -> _Matrix4x4:
    matrix = _identity_matrix()
    translation = _steam_vector(xyz_m)
    matrix.elements[0][3] = translation.x
    matrix.elements[1][3] = translation.y
    matrix.elements[2][3] = translation.z
    return matrix


class SteamAudioAdapter:
    """Load and exercise ``libphonon.so`` directly through ``ctypes``."""

    candidate_id = "steam_audio"
    candidate_version = "4.8.1"

    def __init__(
        self,
        *,
        library_path: Path | None = None,
        source_root: Path | None = None,
        signal_root: Path | None = None,
        runtime: dict[str, str] | None = None,
    ) -> None:
        root_override = os.environ.get("IAS_STEAM_AUDIO_ROOT")
        self._source_root = source_root or (
            Path(root_override)
            if root_override
            else Path.cwd() / "build/qualification/r9/steam-audio"
        )
        library_override = os.environ.get("IAS_STEAM_AUDIO_LIBRARY")
        self._library_path = library_path or (
            Path(library_override) if library_override else self._find_library()
        )
        signal_override = os.environ.get("IAS_R9_SIGNAL_ROOT")
        self._signal_root = signal_root or (
            Path(signal_override)
            if signal_override
            else Path.cwd() / "build/validation/r9/common/signals"
        )
        self._runtime = runtime or {
            "hardware": "CPU/Embree qualification host",
            "isaac_sim_version": "unknown",
            "kit_version": "unknown",
            "platform": "linux-x86_64",
        }
        self._library: ctypes.CDLL | None = None
        self._context = ctypes.c_void_p()
        self._embree_device = ctypes.c_void_p()
        self._effects: list[ctypes.c_void_p] = []
        self._geometry_probe: dict[str, object] = {}

    def _find_library(self) -> Path:
        candidates = (
            self._source_root / "core/build/r9-release/src/core/libphonon.so",
            self._source_root / "core/build/linux-x64-release/libphonon.so",
            self._source_root / "core/bin/linux-x64/libphonon.so",
            self._source_root / "bin/linux-x64/libphonon.so",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

    def _bind(self) -> None:
        assert self._library is not None
        library = self._library
        library.iplContextCreate.argtypes = [
            ctypes.POINTER(_ContextSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplContextCreate.restype = ctypes.c_int
        library.iplContextRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplEmbreeDeviceCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_EmbreeDeviceSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplEmbreeDeviceCreate.restype = ctypes.c_int
        library.iplEmbreeDeviceRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplSceneCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SceneSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplSceneCreate.restype = ctypes.c_int
        library.iplSceneRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplSceneCommit.argtypes = [ctypes.c_void_p]
        library.iplStaticMeshCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_StaticMeshSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplStaticMeshCreate.restype = ctypes.c_int
        library.iplStaticMeshAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplStaticMeshRemove.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplStaticMeshRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplInstancedMeshCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_InstancedMeshSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplInstancedMeshCreate.restype = ctypes.c_int
        library.iplInstancedMeshAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplInstancedMeshRemove.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplInstancedMeshUpdateTransform.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            _Matrix4x4,
        ]
        library.iplInstancedMeshRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplDirectEffectCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_AudioSettings),
            ctypes.POINTER(_DirectEffectSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplDirectEffectCreate.restype = ctypes.c_int
        library.iplDirectEffectApply.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DirectEffectParams),
            ctypes.POINTER(_AudioBuffer),
            ctypes.POINTER(_AudioBuffer),
        ]
        library.iplDirectEffectApply.restype = ctypes.c_int
        library.iplDirectEffectRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplDirectEffectReset.argtypes = [ctypes.c_void_p]
        library.iplDistanceAttenuationCalculate.argtypes = [
            ctypes.c_void_p,
            _Vector3,
            _Vector3,
            ctypes.POINTER(_DistanceAttenuationModel),
        ]
        library.iplDistanceAttenuationCalculate.restype = ctypes.c_float
        library.iplSimulatorCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SimulationSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplSimulatorCreate.restype = ctypes.c_int
        library.iplSimulatorRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplSimulatorSetScene.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplSimulatorSetSharedInputs.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(_SimulationSharedInputs),
        ]
        library.iplSimulatorCommit.argtypes = [ctypes.c_void_p]
        library.iplSimulatorRunDirect.argtypes = [ctypes.c_void_p]
        library.iplSourceCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SourceSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplSourceCreate.restype = ctypes.c_int
        library.iplSourceRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplSourceAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplSourceRemove.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        library.iplSourceSetInputs.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(_SimulationInputs),
        ]
        library.iplSourceGetOutputs.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(_SimulationOutputs),
        ]

    def _initialize(self) -> None:
        if self._library is not None:
            return
        self._library = ctypes.CDLL(str(self._library_path))
        self._bind()
        settings = _ContextSettings(
            _API_VERSION, None, None, None, _SIMD_AVX2, _CONTEXT_VALIDATION
        )
        _check(
            self._library.iplContextCreate(
                ctypes.byref(settings), ctypes.byref(self._context)
            ),
            "iplContextCreate",
        )
        embree_settings = _EmbreeDeviceSettings()
        _check(
            self._library.iplEmbreeDeviceCreate(
                self._context,
                ctypes.byref(embree_settings),
                ctypes.byref(self._embree_device),
            ),
            "iplEmbreeDeviceCreate",
        )
        self._geometry_probe = self._probe_scene_and_instance()
        audio_settings = _AudioSettings(SAMPLE_RATE_HZ, BLOCK_SAMPLES)
        effect_settings = _DirectEffectSettings(1)
        for _ in MICROPHONE_IDS:
            effect = ctypes.c_void_p()
            _check(
                self._library.iplDirectEffectCreate(
                    self._context,
                    ctypes.byref(audio_settings),
                    ctypes.byref(effect_settings),
                    ctypes.byref(effect),
                ),
                "iplDirectEffectCreate",
            )
            self._effects.append(effect)

    def _create_embree_scene(self) -> ctypes.c_void_p:
        assert self._library is not None
        scene = ctypes.c_void_p()
        settings = _SceneSettings(
            _SCENE_EMBREE,
            None,
            None,
            None,
            None,
            None,
            self._embree_device.value,
            None,
        )
        _check(
            self._library.iplSceneCreate(
                self._context, ctypes.byref(settings), ctypes.byref(scene)
            ),
            "iplSceneCreate",
        )
        return scene

    def _load_signal(self, signal_id: str) -> np.ndarray:
        if signal_id == "impulse":
            return generated_impulse()
        path = self._signal_root / f"{signal_id}.wav"
        with wave.open(str(path), "rb") as source:
            if (
                source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getframerate() != SAMPLE_RATE_HZ
                or source.getnframes() != BLOCK_SAMPLES
            ):
                raise ValueError(f"unsupported R9.2 WAV format: {path}")
            samples = np.frombuffer(source.readframes(BLOCK_SAMPLES), dtype="<i2")
        return np.asarray(samples, dtype=np.float32) / 32767.0

    @staticmethod
    def _box_vertices(size_xyz_m: tuple[float, float, float]) -> tuple[_Vector3, ...]:
        half_x, half_y, half_z = (value / 2.0 for value in size_xyz_m)
        return tuple(
            _steam_vector((x, y, z))
            for x, y, z in (
                (-half_x, -half_y, -half_z),
                (half_x, -half_y, -half_z),
                (half_x, half_y, -half_z),
                (-half_x, half_y, -half_z),
                (-half_x, -half_y, half_z),
                (half_x, -half_y, half_z),
                (half_x, half_y, half_z),
                (-half_x, half_y, half_z),
            )
        )

    def _add_barrier_instance(
        self, parent_scene: ctypes.c_void_p, barrier: object
    ) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
        assert self._library is not None
        library = self._library
        sub_scene = self._create_embree_scene()
        static_mesh = ctypes.c_void_p()
        instance = ctypes.c_void_p()
        vertices = (_Vector3 * 8)(*self._box_vertices(barrier.size_xyz_m))
        triangle_indices = (
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (1, 2, 6),
            (1, 6, 5),
            (2, 3, 7),
            (2, 7, 6),
            (3, 0, 4),
            (3, 4, 7),
        )
        triangles = (_Triangle * 12)(
            *(_Triangle(indices) for indices in triangle_indices)
        )
        material_indices = (ctypes.c_int32 * 12)(*([0] * 12))
        transmission = interpolate_transmission_energy(
            (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0),
            barrier.transmission_loss_db,
            (400.0, 2500.0, 15000.0),
        )
        materials = (_Material * 1)(
            _Material(
                (ctypes.c_float * 3)(0.1, 0.1, 0.1),
                0.05,
                (ctypes.c_float * 3)(*map(float, transmission)),
            )
        )
        settings = _StaticMeshSettings(
            8, 12, 1, vertices, triangles, material_indices, materials
        )
        try:
            _check(
                library.iplStaticMeshCreate(
                    sub_scene, ctypes.byref(settings), ctypes.byref(static_mesh)
                ),
                "iplStaticMeshCreate",
            )
            library.iplStaticMeshAdd(static_mesh, sub_scene)
            library.iplSceneCommit(sub_scene)
            instance_settings = _InstancedMeshSettings(
                sub_scene.value, _translation_matrix(barrier.center_xyz_m)
            )
            _check(
                library.iplInstancedMeshCreate(
                    parent_scene,
                    ctypes.byref(instance_settings),
                    ctypes.byref(instance),
                ),
                "iplInstancedMeshCreate",
            )
            library.iplInstancedMeshAdd(instance, parent_scene)
        finally:
            if static_mesh.value:
                library.iplStaticMeshRelease(ctypes.byref(static_mesh))
        return sub_scene, instance

    def _create_fixture_scene(
        self, fixture: FixtureSpec
    ) -> tuple[ctypes.c_void_p, list[ctypes.c_void_p], list[ctypes.c_void_p]]:
        assert self._library is not None
        scene = self._create_embree_scene()
        sub_scenes: list[ctypes.c_void_p] = []
        instances: list[ctypes.c_void_p] = []
        barriers = () if fixture.door_open else fixture.barriers
        try:
            for barrier in barriers:
                sub_scene, instance = self._add_barrier_instance(scene, barrier)
                sub_scenes.append(sub_scene)
                instances.append(instance)
            self._library.iplSceneCommit(scene)
        except Exception:
            self._release_fixture_scene(scene, sub_scenes, instances)
            raise
        return scene, sub_scenes, instances

    def _release_fixture_scene(
        self,
        scene: ctypes.c_void_p,
        sub_scenes: list[ctypes.c_void_p],
        instances: list[ctypes.c_void_p],
    ) -> None:
        assert self._library is not None
        for instance in reversed(instances):
            self._library.iplInstancedMeshRemove(instance, scene)
            self._library.iplInstancedMeshRelease(ctypes.byref(instance))
        for sub_scene in reversed(sub_scenes):
            self._library.iplSceneRelease(ctypes.byref(sub_scene))
        if scene.value:
            self._library.iplSceneRelease(ctypes.byref(scene))

    def _create_simulator(
        self, scene: ctypes.c_void_p
    ) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
        assert self._library is not None
        simulator = ctypes.c_void_p()
        source = ctypes.c_void_p()
        settings = _SimulationSettings(
            _SIMULATE_DIRECT,
            _SCENE_EMBREE,
            0,
            32,
            1,
            1,
            0.02,
            0,
            1,
            1,
            1,
            1,
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
            source_settings = _SourceSettings(_SIMULATE_DIRECT)
            _check(
                self._library.iplSourceCreate(
                    simulator, ctypes.byref(source_settings), ctypes.byref(source)
                ),
                "iplSourceCreate",
            )
            self._library.iplSourceAdd(source, simulator)
            self._library.iplSimulatorCommit(simulator)
        except Exception:
            if source.value:
                self._library.iplSourceRelease(ctypes.byref(source))
            self._library.iplSimulatorRelease(ctypes.byref(simulator))
            raise
        return simulator, source

    @staticmethod
    def _simulation_inputs(
        source_xyz_m: tuple[float, float, float],
    ) -> _SimulationInputs:
        return _SimulationInputs(
            _SIMULATE_DIRECT,
            _DIRECT_SIMULATE_DISTANCE
            | _DIRECT_SIMULATE_OCCLUSION
            | _DIRECT_SIMULATE_TRANSMISSION,
            _coordinate_space(source_xyz_m),
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
            _BakedDataIdentifier(0, 0, _Sphere(_Vector3(), 0.0)),
            None,
            0.0,
            0.0,
            0.0,
            0,
            0,
            0,
            16,
            None,
        )

    def _simulate_direct_params(
        self,
        simulator: ctypes.c_void_p,
        source: ctypes.c_void_p,
        source_xyz_m: tuple[float, float, float],
        array_xyz_m: tuple[float, float, float],
    ) -> tuple[list[_DirectEffectParams], float]:
        assert self._library is not None
        params: list[_DirectEffectParams] = []
        start = time.perf_counter_ns()
        for offset in QUAD_FRONT_OFFSETS_M:
            microphone_xyz = tuple(
                position + delta
                for position, delta in zip(array_xyz_m, offset, strict=True)
            )
            shared = _SimulationSharedInputs(
                _coordinate_space(microphone_xyz), 1, 1, 0.02, 0, 1.0, None, None
            )
            inputs = self._simulation_inputs(source_xyz_m)
            self._library.iplSimulatorSetSharedInputs(
                simulator, _SIMULATE_DIRECT, ctypes.byref(shared)
            )
            self._library.iplSourceSetInputs(
                source, _SIMULATE_DIRECT, ctypes.byref(inputs)
            )
            self._library.iplSimulatorRunDirect(simulator)
            outputs = _SimulationOutputs()
            self._library.iplSourceGetOutputs(
                source, _SIMULATE_DIRECT, ctypes.byref(outputs)
            )
            params.append(outputs.direct)
        return params, (time.perf_counter_ns() - start) / 1e6

    def _probe_scene_and_instance(self) -> dict[str, object]:
        assert self._library is not None
        library = self._library
        parent_scene = self._create_embree_scene()
        sub_scene = self._create_embree_scene()
        static_mesh = ctypes.c_void_p()
        instance = ctypes.c_void_p()
        vertices = (_Vector3 * 4)(
            _Vector3(0.0, -1.0, -1.0),
            _Vector3(0.0, 1.0, -1.0),
            _Vector3(0.0, 1.0, 1.0),
            _Vector3(0.0, -1.0, 1.0),
        )
        triangles = (_Triangle * 2)(
            _Triangle((0, 1, 2)),
            _Triangle((0, 2, 3)),
        )
        material_indices = (ctypes.c_int32 * 2)(0, 0)
        transmission = transmission_loss_db_to_energy([12.0] * 3)
        materials = (_Material * 1)(
            _Material(
                (ctypes.c_float * 3)(0.1, 0.1, 0.1),
                0.05,
                (ctypes.c_float * 3)(*map(float, transmission)),
            )
        )
        mesh_settings = _StaticMeshSettings(
            4, 2, 1, vertices, triangles, material_indices, materials
        )
        try:
            _check(
                library.iplStaticMeshCreate(
                    sub_scene, ctypes.byref(mesh_settings), ctypes.byref(static_mesh)
                ),
                "iplStaticMeshCreate",
            )
            library.iplStaticMeshAdd(static_mesh, sub_scene)
            library.iplSceneCommit(sub_scene)
            instance_settings = _InstancedMeshSettings(
                sub_scene.value, _identity_matrix()
            )
            _check(
                library.iplInstancedMeshCreate(
                    parent_scene,
                    ctypes.byref(instance_settings),
                    ctypes.byref(instance),
                ),
                "iplInstancedMeshCreate",
            )
            library.iplInstancedMeshAdd(instance, parent_scene)
            library.iplSceneCommit(parent_scene)
            moved = _identity_matrix()
            moved.elements[0][3] = 0.25
            start = time.perf_counter_ns()
            library.iplInstancedMeshUpdateTransform(instance, parent_scene, moved)
            library.iplSceneCommit(parent_scene)
            update_ms = (time.perf_counter_ns() - start) / 1e6
            return {
                "embree_scene": True,
                "instanced_mesh": True,
                "static_mesh": True,
                "instance_update_ms": update_ms,
                "transmission_energy": transmission.tolist(),
            }
        finally:
            if instance.value:
                library.iplInstancedMeshRemove(instance, parent_scene)
                library.iplInstancedMeshRelease(ctypes.byref(instance))
            if static_mesh.value:
                library.iplStaticMeshRemove(static_mesh, sub_scene)
                library.iplStaticMeshRelease(ctypes.byref(static_mesh))
            library.iplSceneRelease(ctypes.byref(sub_scene))
            library.iplSceneRelease(ctypes.byref(parent_scene))

    def probe_runtime(self) -> RuntimeProbe:
        required_symbols = (
            "iplContextCreate",
            "iplSceneCreate",
            "iplStaticMeshCreate",
            "iplInstancedMeshCreate",
            "iplSimulatorRunDirect",
            "iplSimulatorRunReflections",
            "iplSimulatorRunPathing",
            "iplDirectEffectApply",
            "iplReflectionEffectApply",
            "iplPathEffectApply",
        )
        try:
            self._initialize()
        except (OSError, RuntimeError) as error:
            return RuntimeProbe(
                available=False,
                provider_version=self.candidate_version,
                runtime=self._runtime,
                capabilities={},
                details={"library_path": str(self._library_path)},
                external_blocker=str(error),
            )
        assert self._library is not None
        symbols = {name: hasattr(self._library, name) for name in required_symbols}
        return RuntimeProbe(
            available=True,
            provider_version=self.candidate_version,
            runtime=self._runtime,
            capabilities={
                "direct_effect": symbols["iplDirectEffectApply"],
                "embree_scene": bool(self._geometry_probe.get("embree_scene")),
                "instanced_mesh": bool(self._geometry_probe.get("instanced_mesh")),
                "path_effect": symbols["iplPathEffectApply"],
                "reflection_effect": symbols["iplReflectionEffectApply"],
            },
            details={
                "api_version": _API_VERSION,
                "geometry_probe": self._geometry_probe,
                "library_path": str(self._library_path),
                "source_root": str(self._source_root),
                "symbols": symbols,
            },
        )

    def _process_mono(
        self,
        effect: ctypes.c_void_p,
        samples: np.ndarray,
        params: _DirectEffectParams,
    ) -> np.ndarray:
        assert self._library is not None
        input_samples = np.ascontiguousarray(samples, dtype=np.float32)
        output_samples = np.zeros_like(input_samples)
        float_pointer = ctypes.POINTER(ctypes.c_float)
        input_channels = (float_pointer * 1)(
            input_samples.ctypes.data_as(float_pointer)
        )
        output_channels = (float_pointer * 1)(
            output_samples.ctypes.data_as(float_pointer)
        )
        input_buffer = _AudioBuffer(1, input_samples.size, input_channels)
        output_buffer = _AudioBuffer(1, output_samples.size, output_channels)
        self._library.iplDirectEffectApply(
            effect,
            ctypes.byref(params),
            ctypes.byref(input_buffer),
            ctypes.byref(output_buffer),
        )
        return output_samples

    def run_fixture(
        self, fixture: FixtureSpec, *, repetition: int, diagnostics: bool = False
    ) -> FixtureRun:
        self._initialize()
        if repetition < 0:
            raise ValueError("repetition must be non-negative.")
        assert self._library is not None
        signal = self._load_signal(fixture.signal)
        scene, sub_scenes, instances = self._create_fixture_scene(fixture)
        simulator = ctypes.c_void_p()
        source = ctypes.c_void_p()
        try:
            simulator, source = self._create_simulator(scene)
            direct_params, simulation_ms = self._simulate_direct_params(
                simulator, source, fixture.source_xyz_m, fixture.array_xyz_m
            )
            baseline_params = direct_params
            update_ms = 0.0
            if fixture.dynamic_target:
                source_xyz = fixture.source_xyz_m
                array_xyz = fixture.array_xyz_m
                update_start = time.perf_counter_ns()
                if fixture.dynamic_target == "source":
                    source_xyz = (
                        fixture.source_xyz_m[0] + 0.5,
                        fixture.source_xyz_m[1],
                        fixture.source_xyz_m[2],
                    )
                elif fixture.dynamic_target == "array":
                    array_xyz = (
                        fixture.array_xyz_m[0],
                        fixture.array_xyz_m[1] + 0.5,
                        fixture.array_xyz_m[2],
                    )
                elif instances:
                    barrier = fixture.barriers[0]
                    moved_xyz = (
                        barrier.center_xyz_m[0],
                        barrier.center_xyz_m[1] + 6.0,
                        barrier.center_xyz_m[2],
                    )
                    self._library.iplInstancedMeshUpdateTransform(
                        instances[0], scene, _translation_matrix(moved_xyz)
                    )
                    self._library.iplSceneCommit(scene)
                    self._library.iplSimulatorCommit(simulator)
                update_ms = (time.perf_counter_ns() - update_start) / 1e6
                direct_params, second_simulation_ms = self._simulate_direct_params(
                    simulator, source, source_xyz, array_xyz
                )
                simulation_ms += second_simulation_ms

            outputs: list[np.ndarray] = []
            references: list[np.ndarray] = []
            effect_start = time.perf_counter_ns()
            for effect, params in zip(self._effects, direct_params, strict=True):
                params.flags = (
                    _DIRECT_APPLY_DISTANCE
                    | _DIRECT_APPLY_OCCLUSION
                    | _DIRECT_APPLY_TRANSMISSION
                )
                params.transmission_type = _TRANSMISSION_FREQUENCY_DEPENDENT
                self._library.iplDirectEffectReset(effect)
                self._process_mono(effect, np.zeros_like(signal), params)
                outputs.append(self._process_mono(effect, signal, params))

                reference_params = _DirectEffectParams(
                    _DIRECT_APPLY_DISTANCE,
                    0,
                    params.distance_attenuation,
                    (ctypes.c_float * 3)(1.0, 1.0, 1.0),
                    1.0,
                    1.0,
                    (ctypes.c_float * 3)(1.0, 1.0, 1.0),
                )
                self._library.iplDirectEffectReset(effect)
                self._process_mono(effect, np.zeros_like(signal), reference_params)
                references.append(self._process_mono(effect, signal, reference_params))
            effects_ms = (time.perf_counter_ns() - effect_start) / 1e6
            changed = any(
                abs(before.distance_attenuation - after.distance_attenuation) > 1e-6
                or abs(before.occlusion - after.occlusion) > 1e-6
                or any(
                    abs(before.transmission[index] - after.transmission[index]) > 1e-6
                    for index in range(3)
                )
                for before, after in zip(baseline_params, direct_params, strict=True)
            )
            unsupported_indirect = fixture.fixture_id in {
                "reflection",
                "l_corner",
                "connected_rooms_closed",
                "connected_rooms_open",
            }
            compatible = not unsupported_indirect and (
                not fixture.dynamic_target or changed
            )
            block = SignalBlock(
                np.stack(outputs),
                MICROPHONE_IDS,
                SAMPLE_RATE_HZ,
                {
                    "complete_block": update_ms + simulation_ms + effects_ms,
                    "effects": effects_ms,
                    "simulation": simulation_ms,
                    "update": update_ms,
                },
            )
            measurements: dict[str, object] = {
                "diagnostics_requested": diagnostics,
                "distance_attenuation": [
                    float(params.distance_attenuation) for params in direct_params
                ],
                "dynamic_output_changed": changed,
                "native_receiver_calls": len(MICROPHONE_IDS),
                "occlusion": [float(params.occlusion) for params in direct_params],
                "post_alignment_samples": 0,
                "scene_geometry_applied_to_audio": bool(fixture.barriers),
                "static_geometry_recreated_during_update": False,
                "transmission_energy": [
                    [float(value) for value in params.transmission]
                    for params in direct_params
                ],
            }
            if fixture.signal == "multitone":
                measurements["tone_loss_db"] = tone_losses_db(references[0], outputs[0])
            return FixtureRun(
                fixture.fixture_id,
                repetition,
                block,
                measurements,
                compatible=compatible,
                incompatibility=(
                    "The direct simulator has no qualifying unbaked indirect/path "
                    "microphone output for this fixture."
                    if unsupported_indirect
                    else (
                        "The native dynamic update did not change direct output."
                        if fixture.dynamic_target and not changed
                        else None
                    )
                ),
            )
        finally:
            if source.value:
                self._library.iplSourceRemove(source, simulator)
                self._library.iplSourceRelease(ctypes.byref(source))
            if simulator.value:
                self._library.iplSimulatorRelease(ctypes.byref(simulator))
            self._release_fixture_scene(scene, sub_scenes, instances)

    def run_performance(
        self, *, environment_count: int, diagnostics: bool
    ) -> PerformanceRun:
        if environment_count not in (1, 4):
            raise ValueError("environment_count must be one or four.")
        fixture = next(
            item for item in common_fixtures() if item.fixture_id == "direct_path"
        )
        for index in range(20):
            for _ in range(environment_count):
                self.run_fixture(fixture, repetition=index, diagnostics=diagnostics)
        block_ms: list[float] = []
        for index in range(200):
            start = time.perf_counter_ns()
            for _ in range(environment_count):
                self.run_fixture(fixture, repetition=index, diagnostics=diagnostics)
            block_ms.append((time.perf_counter_ns() - start) / 1e6)
        peak_memory_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        return PerformanceRun(
            environment_count,
            diagnostics,
            20,
            200,
            tuple(block_ms),
            peak_memory_mib,
            (float(self._geometry_probe.get("instance_update_ms", 0.0)),),
        )

    def close(self) -> None:
        if self._library is None:
            return
        for effect in reversed(self._effects):
            self._library.iplDirectEffectRelease(ctypes.byref(effect))
        self._effects.clear()
        if self._embree_device.value:
            self._library.iplEmbreeDeviceRelease(ctypes.byref(self._embree_device))
        if self._context.value:
            self._library.iplContextRelease(ctypes.byref(self._context))
        self._library = None
