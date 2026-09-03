"""Temporary Steam Audio 4.8.1 adapter for corrected R9.2 qualification."""

from __future__ import annotations

import ctypes
import math
import os
import resource
import time
import wave
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.effects.channel_response import fractional_delay

from .fixtures import (
    BLOCK_SAMPLES,
    IAS_TRANSMISSION_FREQUENCIES_HZ,
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    SAMPLE_RATE_HZ,
    STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    AcousticSurfaceSpec,
    FixtureSpec,
    common_fixtures,
    generated_impulse,
    surface_points,
)
from .metrics import (
    interpolate_transmission_amplitude,
    rms_db,
    tone_losses_db,
    transmission_loss_db_to_amplitude,
)
from .models import FixtureRun, PerformanceRun, RuntimeProbe, SignalBlock

_API_VERSION = (4 << 16) | (8 << 8) | 1
_STATUS_SUCCESS = 0
_SIMD_AVX2 = 3
_CONTEXT_VALIDATION = 1
_SCENE_EMBREE = 1
_REFLECTION_CONVOLUTION = 0
_DIRECT_APPLY_DISTANCE = 1 << 0
_DIRECT_APPLY_OCCLUSION = 1 << 3
_DIRECT_APPLY_TRANSMISSION = 1 << 4
_DIRECT_SIMULATE_DISTANCE = 1 << 0
_DIRECT_SIMULATE_OCCLUSION = 1 << 3
_DIRECT_SIMULATE_TRANSMISSION = 1 << 4
_SIMULATE_DIRECT = 1 << 0
_SIMULATE_REFLECTIONS = 1 << 1
_NUM_TRANSMISSION_SURFACES = 8
_REFLECTION_RAYS = 4096
_REFLECTION_BOUNCES = 8
_REFLECTION_DURATION_S = 0.1
_REFLECTION_ORDER = 0
_SOUND_SPEED_M_S = 343.0
_SERIALIZABLE_FLOOR_DB = -200.0


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


class _ReflectionEffectSettings(ctypes.Structure):
    _fields_ = [
        ("effect_type", ctypes.c_int),
        ("ir_size", ctypes.c_int32),
        ("num_channels", ctypes.c_int32),
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


@dataclass(slots=True)
class _ReceiverState:
    simulator: ctypes.c_void_p
    source: ctypes.c_void_p
    direct_effect: ctypes.c_void_p
    reflection_effect: ctypes.c_void_p
    microphone_xyz_m: tuple[float, float, float]
    outputs: _SimulationOutputs = field(default_factory=_SimulationOutputs)


@dataclass(slots=True)
class _FixtureSession:
    fixture: FixtureSpec
    scene: ctypes.c_void_p
    sub_scenes: list[ctypes.c_void_p]
    instances: list[tuple[str, ctypes.c_void_p]]
    receivers: list[_ReceiverState]
    source_xyz_m: tuple[float, float, float]
    array_xyz_m: tuple[float, float, float]


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


def _finite_rms_db(samples: np.ndarray) -> float:
    return max(rms_db(samples), _SERIALIZABLE_FLOOR_DB)


class SteamAudioAdapter:
    """Exercise ``libphonon.so`` through a thin, temporary IAS bridge."""

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
            else Path.cwd() / "build/validation/r9/rev2/common/signals"
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
        self._geometry_probe: dict[str, object] = {}
        self._counters: defaultdict[str, int] = defaultdict(int)

    def _find_library(self) -> Path:
        candidates = (
            self._source_root / "core/build/r9-release/src/core/libphonon.so",
            self._source_root / "core/build/linux-x64-release/libphonon.so",
            self._source_root / "core/bin/linux-x64/libphonon.so",
            self._source_root / "bin/linux-x64/libphonon.so",
        )
        return next((path for path in candidates if path.is_file()), candidates[0])

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
        library.iplReflectionEffectCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_AudioSettings),
            ctypes.POINTER(_ReflectionEffectSettings),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.iplReflectionEffectCreate.restype = ctypes.c_int
        library.iplReflectionEffectApply.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ReflectionEffectParams),
            ctypes.POINTER(_AudioBuffer),
            ctypes.POINTER(_AudioBuffer),
            ctypes.c_void_p,
        ]
        library.iplReflectionEffectApply.restype = ctypes.c_int
        library.iplReflectionEffectRelease.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.iplReflectionEffectReset.argtypes = [ctypes.c_void_p]
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
        library.iplSimulatorRunReflections.argtypes = [ctypes.c_void_p]
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
        _check(
            self._library.iplEmbreeDeviceCreate(
                self._context,
                ctypes.byref(_EmbreeDeviceSettings()),
                ctypes.byref(self._embree_device),
            ),
            "iplEmbreeDeviceCreate",
        )
        self._geometry_probe = self._probe_scene_and_instance()

    def _create_embree_scene(self) -> ctypes.c_void_p:
        assert self._library is not None
        scene = ctypes.c_void_p()
        settings = _SceneSettings(
            _SCENE_EMBREE, None, None, None, None, None, self._embree_device.value, None
        )
        _check(
            self._library.iplSceneCreate(
                self._context, ctypes.byref(settings), ctypes.byref(scene)
            ),
            "iplSceneCreate",
        )
        self._counters["scene_create"] += 1
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
    def _native_material(surface: AcousticSurfaceSpec) -> _Material:
        transmission = interpolate_transmission_amplitude(
            IAS_TRANSMISSION_FREQUENCIES_HZ,
            surface.transmission_loss_db,
            STEAM_AUDIO_BAND_FREQUENCIES_HZ,
        )
        return _Material(
            (ctypes.c_float * 3)(*surface.absorption),
            surface.scattering,
            (ctypes.c_float * 3)(*map(float, transmission)),
        )

    def _add_assembly_instance(
        self,
        parent_scene: ctypes.c_void_p,
        assembly_id: str,
        surfaces: tuple[AcousticSurfaceSpec, ...],
    ) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
        assert self._library is not None
        sub_scene = self._create_embree_scene()
        static_mesh = ctypes.c_void_p()
        instance = ctypes.c_void_p()
        vertex_values = [
            _steam_vector(point)
            for surface in surfaces
            for point in surface_points(surface)
        ]
        triangle_values = []
        for index in range(len(surfaces)):
            offset = index * 4
            triangle_values.extend(
                (
                    _Triangle((offset, offset + 1, offset + 2)),
                    _Triangle((offset, offset + 2, offset + 3)),
                )
            )
        vertices = (_Vector3 * len(vertex_values))(*vertex_values)
        triangles = (_Triangle * len(triangle_values))(*triangle_values)
        material_indices = (ctypes.c_int32 * len(triangle_values))(
            *(index for index in range(len(surfaces)) for _ in range(2))
        )
        materials = (_Material * len(surfaces))(
            *(self._native_material(surface) for surface in surfaces)
        )
        mesh_settings = _StaticMeshSettings(
            len(vertex_values),
            len(triangle_values),
            len(surfaces),
            vertices,
            triangles,
            material_indices,
            materials,
        )
        try:
            _check(
                self._library.iplStaticMeshCreate(
                    sub_scene, ctypes.byref(mesh_settings), ctypes.byref(static_mesh)
                ),
                "iplStaticMeshCreate",
            )
            self._counters["static_mesh_create"] += 1
            self._library.iplStaticMeshAdd(static_mesh, sub_scene)
            self._library.iplSceneCommit(sub_scene)
            self._counters["scene_commit"] += 1
            instance_settings = _InstancedMeshSettings(
                sub_scene.value, _identity_matrix()
            )
            _check(
                self._library.iplInstancedMeshCreate(
                    parent_scene,
                    ctypes.byref(instance_settings),
                    ctypes.byref(instance),
                ),
                "iplInstancedMeshCreate",
            )
            self._counters["instance_create"] += 1
            self._library.iplInstancedMeshAdd(instance, parent_scene)
        finally:
            if static_mesh.value:
                self._library.iplStaticMeshRelease(ctypes.byref(static_mesh))
        return sub_scene, instance

    def _create_fixture_scene(
        self, fixture: FixtureSpec
    ) -> tuple[
        ctypes.c_void_p,
        list[ctypes.c_void_p],
        list[tuple[str, ctypes.c_void_p]],
    ]:
        assert self._library is not None
        scene = self._create_embree_scene()
        sub_scenes: list[ctypes.c_void_p] = []
        instances: list[tuple[str, ctypes.c_void_p]] = []
        grouped: dict[str, list[AcousticSurfaceSpec]] = {}
        for surface in fixture.surfaces:
            grouped.setdefault(surface.assembly_id, []).append(surface)
        try:
            for assembly_id, surfaces in grouped.items():
                sub_scene, instance = self._add_assembly_instance(
                    scene, assembly_id, tuple(surfaces)
                )
                sub_scenes.append(sub_scene)
                instances.append((assembly_id, instance))
            self._library.iplSceneCommit(scene)
            self._counters["scene_commit"] += 1
        except Exception:
            self._release_fixture_scene(scene, sub_scenes, instances)
            raise
        return scene, sub_scenes, instances

    def _release_fixture_scene(
        self,
        scene: ctypes.c_void_p,
        sub_scenes: list[ctypes.c_void_p],
        instances: list[tuple[str, ctypes.c_void_p]],
    ) -> None:
        assert self._library is not None
        for _, instance in reversed(instances):
            self._library.iplInstancedMeshRemove(instance, scene)
            self._library.iplInstancedMeshRelease(ctypes.byref(instance))
        for sub_scene in reversed(sub_scenes):
            self._library.iplSceneRelease(ctypes.byref(sub_scene))
        if scene.value:
            self._library.iplSceneRelease(ctypes.byref(scene))

    @staticmethod
    def _simulation_inputs(
        source_xyz_m: tuple[float, float, float], *, reflections: bool
    ) -> _SimulationInputs:
        flags = _SIMULATE_DIRECT | (_SIMULATE_REFLECTIONS if reflections else 0)
        return _SimulationInputs(
            flags,
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
            1.0,
            0.25,
            0,
            _BakedDataIdentifier(0, 0, _Sphere(_Vector3(), 0.0)),
            None,
            0.0,
            0.0,
            0.0,
            0,
            0,
            0,
            _NUM_TRANSMISSION_SURFACES,
            None,
        )

    def _create_receiver(
        self,
        scene: ctypes.c_void_p,
        microphone_xyz_m: tuple[float, float, float],
        *,
        reflections: bool,
    ) -> _ReceiverState:
        assert self._library is not None
        flags = _SIMULATE_DIRECT | (_SIMULATE_REFLECTIONS if reflections else 0)
        simulator = ctypes.c_void_p()
        source = ctypes.c_void_p()
        direct_effect = ctypes.c_void_p()
        reflection_effect = ctypes.c_void_p()
        settings = _SimulationSettings(
            flags,
            _SCENE_EMBREE,
            _REFLECTION_CONVOLUTION,
            32,
            _REFLECTION_RAYS,
            32,
            _REFLECTION_DURATION_S,
            _REFLECTION_ORDER,
            1,
            1,
            16,
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
        self._counters["simulator_create"] += 1
        try:
            self._library.iplSimulatorSetScene(simulator, scene)
            _check(
                self._library.iplSourceCreate(
                    simulator,
                    ctypes.byref(_SourceSettings(flags)),
                    ctypes.byref(source),
                ),
                "iplSourceCreate",
            )
            self._counters["source_create"] += 1
            self._library.iplSourceAdd(source, simulator)
            self._library.iplSimulatorCommit(simulator)
            audio_settings = _AudioSettings(SAMPLE_RATE_HZ, BLOCK_SAMPLES)
            _check(
                self._library.iplDirectEffectCreate(
                    self._context,
                    ctypes.byref(audio_settings),
                    ctypes.byref(_DirectEffectSettings(1)),
                    ctypes.byref(direct_effect),
                ),
                "iplDirectEffectCreate",
            )
            if reflections:
                reflection_settings = _ReflectionEffectSettings(
                    _REFLECTION_CONVOLUTION,
                    math.ceil(_REFLECTION_DURATION_S * SAMPLE_RATE_HZ),
                    1,
                )
                _check(
                    self._library.iplReflectionEffectCreate(
                        self._context,
                        ctypes.byref(audio_settings),
                        ctypes.byref(reflection_settings),
                        ctypes.byref(reflection_effect),
                    ),
                    "iplReflectionEffectCreate",
                )
        except Exception:
            if reflection_effect.value:
                self._library.iplReflectionEffectRelease(
                    ctypes.byref(reflection_effect)
                )
            if direct_effect.value:
                self._library.iplDirectEffectRelease(ctypes.byref(direct_effect))
            if source.value:
                self._library.iplSourceRelease(ctypes.byref(source))
            self._library.iplSimulatorRelease(ctypes.byref(simulator))
            raise
        return _ReceiverState(
            simulator,
            source,
            direct_effect,
            reflection_effect,
            microphone_xyz_m,
        )

    def _create_session(self, fixture: FixtureSpec) -> _FixtureSession:
        scene, sub_scenes, instances = self._create_fixture_scene(fixture)
        receivers: list[_ReceiverState] = []
        try:
            for offset in QUAD_FRONT_OFFSETS_M:
                microphone_xyz = tuple(
                    coordinate + delta
                    for coordinate, delta in zip(
                        fixture.array_xyz_m, offset, strict=True
                    )
                )
                receivers.append(
                    self._create_receiver(
                        scene, microphone_xyz, reflections=fixture.reflections
                    )
                )
        except Exception:
            temporary = _FixtureSession(
                fixture,
                scene,
                sub_scenes,
                instances,
                receivers,
                fixture.source_xyz_m,
                fixture.array_xyz_m,
            )
            self._close_session(temporary)
            raise
        return _FixtureSession(
            fixture,
            scene,
            sub_scenes,
            instances,
            receivers,
            fixture.source_xyz_m,
            fixture.array_xyz_m,
        )

    def _refresh_session(self, session: _FixtureSession) -> float:
        assert self._library is not None
        flags = _SIMULATE_DIRECT | (
            _SIMULATE_REFLECTIONS if session.fixture.reflections else 0
        )
        start = time.perf_counter_ns()
        for receiver, offset in zip(
            session.receivers, QUAD_FRONT_OFFSETS_M, strict=True
        ):
            microphone_xyz = tuple(
                coordinate + delta
                for coordinate, delta in zip(session.array_xyz_m, offset, strict=True)
            )
            receiver.microphone_xyz_m = microphone_xyz
            shared = _SimulationSharedInputs(
                _coordinate_space(microphone_xyz),
                _REFLECTION_RAYS,
                _REFLECTION_BOUNCES,
                _REFLECTION_DURATION_S,
                _REFLECTION_ORDER,
                1.0,
                None,
                None,
            )
            inputs = self._simulation_inputs(
                session.source_xyz_m, reflections=session.fixture.reflections
            )
            self._library.iplSimulatorSetSharedInputs(
                receiver.simulator, flags, ctypes.byref(shared)
            )
            self._library.iplSourceSetInputs(
                receiver.source, flags, ctypes.byref(inputs)
            )
            self._library.iplSimulatorRunDirect(receiver.simulator)
            self._counters["direct_run"] += 1
            if session.fixture.reflections:
                self._library.iplSimulatorRunReflections(receiver.simulator)
                self._counters["reflection_run"] += 1
            outputs = _SimulationOutputs()
            outputs.reflections.effect_type = _REFLECTION_CONVOLUTION
            self._library.iplSourceGetOutputs(
                receiver.source, flags, ctypes.byref(outputs)
            )
            receiver.outputs = outputs
        return (time.perf_counter_ns() - start) / 1e6

    @staticmethod
    def _mono_buffer(samples: np.ndarray) -> tuple[_AudioBuffer, object]:
        values = np.ascontiguousarray(samples, dtype=np.float32)
        float_pointer = ctypes.POINTER(ctypes.c_float)
        channels = (float_pointer * 1)(values.ctypes.data_as(float_pointer))
        return _AudioBuffer(1, values.size, channels), (values, channels)

    def _process_direct(
        self,
        effect: ctypes.c_void_p,
        samples: np.ndarray,
        params: _DirectEffectParams,
        *,
        reset: bool,
    ) -> np.ndarray:
        assert self._library is not None
        input_buffer, input_keepalive = self._mono_buffer(samples)
        output = np.zeros(BLOCK_SAMPLES, dtype=np.float32)
        output_buffer, output_keepalive = self._mono_buffer(output)
        if reset:
            self._library.iplDirectEffectReset(effect)
        self._library.iplDirectEffectApply(
            effect,
            ctypes.byref(params),
            ctypes.byref(input_buffer),
            ctypes.byref(output_buffer),
        )
        self._counters["direct_effect_apply"] += 1
        return np.asarray(output_keepalive[0], dtype=np.float32).copy()

    def _process_reflections(
        self,
        effect: ctypes.c_void_p,
        samples: np.ndarray,
        params: _ReflectionEffectParams,
        *,
        reset: bool,
    ) -> np.ndarray:
        assert self._library is not None
        input_buffer, input_keepalive = self._mono_buffer(samples)
        output = np.zeros(BLOCK_SAMPLES, dtype=np.float32)
        output_buffer, output_keepalive = self._mono_buffer(output)
        if reset:
            self._library.iplReflectionEffectReset(effect)
        self._library.iplReflectionEffectApply(
            effect,
            ctypes.byref(params),
            ctypes.byref(input_buffer),
            ctypes.byref(output_buffer),
            None,
        )
        self._counters["reflection_effect_apply"] += 1
        return np.asarray(output_keepalive[0], dtype=np.float32).copy()

    @staticmethod
    def _delay_direct_path(
        samples: np.ndarray,
        source_xyz_m: tuple[float, float, float],
        microphone_xyz_m: tuple[float, float, float],
    ) -> np.ndarray:
        distance_m = float(
            np.linalg.norm(
                np.asarray(source_xyz_m, dtype=np.float64)
                - np.asarray(microphone_xyz_m, dtype=np.float64)
            )
        )
        return np.asarray(
            fractional_delay(
                samples,
                delay_s=distance_m / _SOUND_SPEED_M_S,
                sample_rate_hz=SAMPLE_RATE_HZ,
            ),
            dtype=np.float32,
        )

    def _render_session(
        self,
        session: _FixtureSession,
        signal: np.ndarray,
        *,
        reset: bool,
        include_reference: bool,
    ) -> tuple[dict[str, np.ndarray], float]:
        start = time.perf_counter_ns()
        native_direct: list[np.ndarray] = []
        bridged_direct: list[np.ndarray] = []
        reflected: list[np.ndarray] = []
        references: list[np.ndarray] = []
        for receiver in session.receivers:
            params = receiver.outputs.direct
            params.flags = (
                _DIRECT_APPLY_DISTANCE
                | _DIRECT_APPLY_OCCLUSION
                | _DIRECT_APPLY_TRANSMISSION
            )
            params.transmission_type = 1
            native = self._process_direct(
                receiver.direct_effect, signal, params, reset=reset
            )
            native_direct.append(native)
            bridged_direct.append(
                self._delay_direct_path(
                    native, session.source_xyz_m, receiver.microphone_xyz_m
                )
            )
            if session.fixture.reflections:
                reflected.append(
                    self._process_reflections(
                        receiver.reflection_effect,
                        signal,
                        receiver.outputs.reflections,
                        reset=reset,
                    )
                )
            else:
                reflected.append(np.zeros_like(signal, dtype=np.float32))
            if include_reference:
                reference_params = _DirectEffectParams(
                    _DIRECT_APPLY_DISTANCE,
                    0,
                    params.distance_attenuation,
                    (ctypes.c_float * 3)(1.0, 1.0, 1.0),
                    1.0,
                    1.0,
                    (ctypes.c_float * 3)(1.0, 1.0, 1.0),
                )
                reference_native = self._process_direct(
                    receiver.direct_effect, signal, reference_params, reset=True
                )
                references.append(
                    self._delay_direct_path(
                        reference_native,
                        session.source_xyz_m,
                        receiver.microphone_xyz_m,
                    )
                )
        native_array = np.stack(native_direct)
        direct_array = np.stack(bridged_direct)
        reflection_array = np.stack(reflected)
        components = {
            "native_direct": native_array,
            "bridged_direct": direct_array,
            "reflections": reflection_array,
            "combined": direct_array + reflection_array,
        }
        if references:
            components["distance_baseline"] = np.stack(references)
        return components, (time.perf_counter_ns() - start) / 1e6

    def _move_assembly(
        self,
        session: _FixtureSession,
        assembly_id: str,
        translation_xyz_m: tuple[float, float, float],
    ) -> float:
        assert self._library is not None
        instance = next(
            (item for name, item in session.instances if name == assembly_id), None
        )
        if instance is None:
            raise ValueError(f"fixture has no dynamic assembly {assembly_id!r}")
        start = time.perf_counter_ns()
        self._library.iplInstancedMeshUpdateTransform(
            instance, session.scene, _translation_matrix(translation_xyz_m)
        )
        self._counters["instance_transform_update"] += 1
        self._library.iplSceneCommit(session.scene)
        self._counters["scene_commit"] += 1
        for receiver in session.receivers:
            self._library.iplSimulatorCommit(receiver.simulator)
        return (time.perf_counter_ns() - start) / 1e6

    def _counter_snapshot(self) -> dict[str, int]:
        return dict(sorted(self._counters.items()))

    @staticmethod
    def _counter_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {
            key: after.get(key, 0) - before.get(key, 0)
            for key in sorted(set(before) | set(after))
            if after.get(key, 0) != before.get(key, 0)
        }

    def _close_session(self, session: _FixtureSession) -> None:
        assert self._library is not None
        for receiver in reversed(session.receivers):
            if receiver.reflection_effect.value:
                self._library.iplReflectionEffectRelease(
                    ctypes.byref(receiver.reflection_effect)
                )
            if receiver.direct_effect.value:
                self._library.iplDirectEffectRelease(
                    ctypes.byref(receiver.direct_effect)
                )
            if receiver.source.value:
                self._library.iplSourceRemove(receiver.source, receiver.simulator)
                self._library.iplSourceRelease(ctypes.byref(receiver.source))
            if receiver.simulator.value:
                self._library.iplSimulatorRelease(ctypes.byref(receiver.simulator))
        self._release_fixture_scene(
            session.scene, session.sub_scenes, session.instances
        )

    def _probe_scene_and_instance(self) -> dict[str, object]:
        fixture = FixtureSpec(
            "runtime_probe",
            "probe",
            (1.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (
                AcousticSurfaceSpec(
                    "probe_surface",
                    (0.5, 0.0, 1.0),
                    (0.0, 2.0, 2.0),
                    (12.0,) * 6,
                ),
            ),
        )
        scene, sub_scenes, instances = self._create_fixture_scene(fixture)
        try:
            start = time.perf_counter_ns()
            assert self._library is not None
            self._library.iplInstancedMeshUpdateTransform(
                instances[0][1], scene, _translation_matrix((0.0, 0.25, 0.0))
            )
            self._counters["instance_transform_update"] += 1
            self._library.iplSceneCommit(scene)
            self._counters["scene_commit"] += 1
            return {
                "embree_scene": True,
                "instanced_mesh": True,
                "planar_static_mesh": True,
                "instance_update_ms": (time.perf_counter_ns() - start) / 1e6,
                "transmission_amplitude": transmission_loss_db_to_amplitude(
                    [12.0] * 3
                ).tolist(),
            }
        finally:
            self._release_fixture_scene(scene, sub_scenes, instances)

    def probe_runtime(self) -> RuntimeProbe:
        required_symbols = (
            "iplContextCreate",
            "iplSceneCreate",
            "iplStaticMeshCreate",
            "iplInstancedMeshCreate",
            "iplSimulatorRunDirect",
            "iplSimulatorRunReflections",
            "iplDirectEffectApply",
            "iplReflectionEffectApply",
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
                "realtime_reflections": symbols["iplReflectionEffectApply"],
            },
            details={
                "api_version": _API_VERSION,
                "geometry_probe": self._geometry_probe,
                "global_num_transmission_surfaces": _NUM_TRANSMISSION_SURFACES,
                "library_path": str(self._library_path),
                "reflection_configuration": {
                    "bounces": _REFLECTION_BOUNCES,
                    "duration_s": _REFLECTION_DURATION_S,
                    "order": _REFLECTION_ORDER,
                    "rays": _REFLECTION_RAYS,
                },
                "source_root": str(self._source_root),
                "symbols": symbols,
            },
        )

    def run_fixture(
        self, fixture: FixtureSpec, *, repetition: int, diagnostics: bool = False
    ) -> FixtureRun:
        self._initialize()
        if repetition < 0:
            raise ValueError("repetition must be non-negative.")
        session = self._create_session(fixture)
        signal = self._load_signal(fixture.signal)
        try:
            simulation_ms = self._refresh_session(session)
            baseline_components, effects_ms = self._render_session(
                session, signal, reset=True, include_reference=True
            )
            components = dict(baseline_components)
            update_ms = 0.0
            update_counters: dict[str, int] = {}
            if fixture.dynamic_target:
                before_update = self._counter_snapshot()
                if fixture.dynamic_target == "source":
                    session.source_xyz_m = (
                        fixture.source_xyz_m[0] + 0.5,
                        fixture.source_xyz_m[1] + 0.5,
                        fixture.source_xyz_m[2],
                    )
                elif fixture.dynamic_target == "array":
                    session.array_xyz_m = (
                        fixture.array_xyz_m[0],
                        fixture.array_xyz_m[1] + 0.5,
                        fixture.array_xyz_m[2],
                    )
                else:
                    update_ms += self._move_assembly(
                        session, fixture.dynamic_target, (0.0, 6.0, 0.0)
                    )
                simulation_ms += self._refresh_session(session)
                updated_components, updated_effects_ms = self._render_session(
                    session, signal, reset=True, include_reference=True
                )
                effects_ms += updated_effects_ms
                update_counters = self._counter_delta(
                    before_update, self._counter_snapshot()
                )
                components = {
                    **{f"before_{key}": value for key, value in components.items()},
                    **updated_components,
                }

            output = components["combined"]
            direct = components["bridged_direct"]
            reflections = components["reflections"]
            reference = components["distance_baseline"]
            measurements: dict[str, object] = {
                "assembly_instance_count": len(session.instances),
                "assembly_surface_counts": {
                    assembly_id: sum(
                        surface.assembly_id == assembly_id
                        for surface in fixture.surfaces
                    )
                    for assembly_id, _ in session.instances
                },
                "counter_snapshot": self._counter_snapshot(),
                "diagnostics_enabled": False,
                "diagnostics_requested": diagnostics,
                "direct_loss_db": _finite_rms_db(reference[0])
                - _finite_rms_db(direct[0]),
                "distance_attenuation": [
                    float(receiver.outputs.direct.distance_attenuation)
                    for receiver in session.receivers
                ],
                "native_receiver_count": len(session.receivers),
                "num_transmission_surfaces": _NUM_TRANSMISSION_SURFACES,
                "occlusion": [
                    float(receiver.outputs.direct.occlusion)
                    for receiver in session.receivers
                ],
                "post_alignment_samples": 0,
                "reflection_rms_db": [
                    _finite_rms_db(channel) for channel in reflections
                ],
                "scene_geometry_applied_to_audio": bool(fixture.surfaces),
                "static_geometry_recreated_during_update": bool(
                    update_counters.get("static_mesh_create", 0)
                ),
                "transmission_amplitude": [
                    [float(value) for value in receiver.outputs.direct.transmission]
                    for receiver in session.receivers
                ],
                "update_counter_delta": update_counters,
            }
            if fixture.signal == "multitone":
                measurements["tone_loss_db"] = tone_losses_db(reference[0], direct[0])
            if fixture.dynamic_target:
                before_direct = components["before_bridged_direct"]
                before_reflections = components["before_reflections"]
                before_combined = components["before_combined"]
                measurements["dynamic_level_delta_db"] = {
                    "combined": _finite_rms_db(output[0])
                    - _finite_rms_db(before_combined[0]),
                    "direct": _finite_rms_db(direct[0])
                    - _finite_rms_db(before_direct[0]),
                    "reflections": _finite_rms_db(reflections[0])
                    - _finite_rms_db(before_reflections[0]),
                }
                before_distance = float(
                    np.linalg.norm(
                        np.asarray(fixture.source_xyz_m)
                        - np.asarray(fixture.array_xyz_m)
                    )
                )
                after_distance = float(
                    np.linalg.norm(
                        np.asarray(session.source_xyz_m)
                        - np.asarray(session.array_xyz_m)
                    )
                )
                measurements["geometric_distance_delta_m"] = (
                    after_distance - before_distance
                )
            block = SignalBlock(
                output,
                MICROPHONE_IDS,
                SAMPLE_RATE_HZ,
                {
                    "complete_block": effects_ms,
                    "effects": effects_ms,
                    "simulation_refresh": simulation_ms,
                    "update": update_ms,
                },
            )
            return FixtureRun(
                fixture.fixture_id,
                repetition,
                block,
                measurements,
                {
                    key: np.asarray(value, dtype=np.float32)
                    for key, value in components.items()
                },
                compatible=True,
            )
        finally:
            self._close_session(session)

    def run_performance(
        self, *, environment_count: int, diagnostics: bool
    ) -> PerformanceRun:
        if environment_count not in (1, 4):
            raise ValueError("environment_count must be one or four.")
        if diagnostics:
            raise ValueError(
                "Steam path/ray diagnostics are not enabled by this harness."
            )
        self._initialize()
        fixture = next(
            item for item in common_fixtures() if item.fixture_id == "move_large_object"
        )
        signal = self._load_signal("impulse")
        sessions = [self._create_session(fixture) for _ in range(environment_count)]
        try:
            for session in sessions:
                self._refresh_session(session)
            for _ in range(20):
                for session in sessions:
                    self._render_session(
                        session, signal, reset=False, include_reference=False
                    )
            block_ms: list[float] = []
            for _ in range(200):
                start = time.perf_counter_ns()
                for session in sessions:
                    self._render_session(
                        session, signal, reset=False, include_reference=False
                    )
                block_ms.append((time.perf_counter_ns() - start) / 1e6)

            for index in range(10):
                translation = (0.0, 6.0 if index % 2 == 0 else 0.0, 0.0)
                for session in sessions:
                    self._move_assembly(session, "large_object", translation)
                    self._refresh_session(session)
            update_ms: list[float] = []
            for index in range(50):
                translation = (0.0, 6.0 if index % 2 == 0 else 0.0, 0.0)
                start = time.perf_counter_ns()
                for session in sessions:
                    self._move_assembly(session, "large_object", translation)
                    self._refresh_session(session)
                update_ms.append((time.perf_counter_ns() - start) / 1e6)
            peak_memory_mib = (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            )
            return PerformanceRun(
                environment_count,
                False,
                20,
                200,
                tuple(block_ms),
                peak_memory_mib,
                tuple(update_ms),
                10,
            )
        finally:
            for session in reversed(sessions):
                self._close_session(session)

    def close(self) -> None:
        if self._library is None:
            return
        if self._embree_device.value:
            self._library.iplEmbreeDeviceRelease(ctypes.byref(self._embree_device))
        if self._context.value:
            self._library.iplContextRelease(ctypes.byref(self._context))
        self._library = None
