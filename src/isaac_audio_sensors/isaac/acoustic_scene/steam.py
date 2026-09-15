"""Private Steam Audio 4.8.1 scene binding; no propagation or perception API."""

from __future__ import annotations

import ctypes as C
from pathlib import Path

import numpy as np

BANDS = (400.0, 2500.0, 15000.0)
Handle = C.c_void_p
F3 = C.c_float * 3


class Matrix(C.Structure):
    _fields_ = [("elements", (C.c_float * 4) * 4)]


class ContextSettings(C.Structure):
    _fields_ = [
        ("version", C.c_uint32),
        ("log", Handle),
        ("allocate", Handle),
        ("free", Handle),
        ("simd", C.c_int),
        ("flags", C.c_int),
    ]


class SceneSettings(C.Structure):
    _fields_ = [
        ("type", C.c_int),
        ("closest", Handle),
        ("any", Handle),
        ("batch_closest", Handle),
        ("batch_any", Handle),
        ("user", Handle),
        ("embree", Handle),
        ("radeon", Handle),
    ]


class Material(C.Structure):
    _fields_ = [("absorption", F3), ("scattering", C.c_float), ("transmission", F3)]


class MeshSettings(C.Structure):
    _fields_ = [
        ("vertices_count", C.c_int),
        ("triangles_count", C.c_int),
        ("materials_count", C.c_int),
        ("vertices", Handle),
        ("triangles", Handle),
        ("indices", Handle),
        ("materials", C.POINTER(Material)),
    ]


class InstanceSettings(C.Structure):
    _fields_ = [("scene", Handle), ("transform", Matrix)]


def converted_material(material, planar):
    absorption = material.absorption.at(BANDS)
    scattering = material.scattering.at((1000.0,))[0]
    transmission = (
        tuple(10 ** (-loss / 20) for loss in material.transmission_db.at(BANDS))
        if planar and material.transmission_db
        else (0.0,) * 3
    )
    return absorption, scattering, transmission


def _matrix(row_transform):
    # Gf uses row vectors; Steam matrices operate on column vectors.
    values = np.asarray(row_transform).T
    return Matrix(((C.c_float * 4) * 4)(*(tuple(map(float, row)) for row in values)))


class SteamScene:
    """Own the context, Embree device, native geometry, and bounded updates."""

    def __init__(self, library_path):
        path = Path(library_path).resolve(strict=True)
        # 4.8.1 has no runtime version query and accepts newer minor ABIs.
        # Exact version cannot be inferred from ABI success.
        import hashlib

        if hashlib.sha256(path.read_bytes()).hexdigest() not in (
            QUALIFIED_LIBRARY_SHA256,
            NLOS_LIBRARY_SHA256,
        ):
            raise ValueError(
                "Steam binary is not the qualified 4.8.1 Release/Embree build; "
                "requalification is required"
            )
        self.library_path = str(path)
        self.lib = C.CDLL(str(path))
        self.context, self.device, self.scene = Handle(), Handle(), Handle()
        self.entries = {}
        self.verified = False
        self.closed = False
        self.builds = 0
        self.updates = 0
        self._bind()
        try:
            settings = ContextSettings(version=0x040801, simd=0)
            self._check(
                self.lib.iplContextCreate(C.byref(settings), C.byref(self.context))
            )
            reserved = C.c_byte()
            self._check(
                self.lib.iplEmbreeDeviceCreate(
                    self.context, C.byref(reserved), C.byref(self.device)
                )
            )
            self.scene = self._scene()
        except Exception:
            self.close()
            raise

    def _bind(self):
        P = C.POINTER
        specs = {
            "iplContextCreate": (C.c_int, [P(ContextSettings), P(Handle)]),
            "iplContextRelease": (None, [P(Handle)]),
            "iplEmbreeDeviceCreate": (C.c_int, [Handle, Handle, P(Handle)]),
            "iplEmbreeDeviceRelease": (None, [P(Handle)]),
            "iplSceneCreate": (C.c_int, [Handle, P(SceneSettings), P(Handle)]),
            "iplSceneRelease": (None, [P(Handle)]),
            "iplSceneCommit": (None, [Handle]),
            "iplSceneSaveOBJ": (None, [Handle, C.c_char_p]),
            "iplStaticMeshCreate": (C.c_int, [Handle, P(MeshSettings), P(Handle)]),
            "iplStaticMeshAdd": (None, [Handle, Handle]),
            "iplStaticMeshRelease": (None, [P(Handle)]),
            "iplInstancedMeshCreate": (
                C.c_int,
                [Handle, P(InstanceSettings), P(Handle)],
            ),
            "iplInstancedMeshAdd": (None, [Handle, Handle]),
            "iplInstancedMeshRemove": (None, [Handle, Handle]),
            "iplInstancedMeshRelease": (None, [P(Handle)]),
            "iplInstancedMeshUpdateTransform": (None, [Handle, Handle, Matrix]),
        }
        for name, (restype, argtypes) in specs.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, argtypes

    @staticmethod
    def _check(result):
        if result != 0:
            raise RuntimeError(f"Steam Audio operation failed (code {result})")

    def _scene(self):
        scene = Handle()
        settings = SceneSettings(type=1, embree=self.device)
        self._check(
            self.lib.iplSceneCreate(self.context, C.byref(settings), C.byref(scene))
        )
        return scene

    def _create(self, obj):
        sub, mesh, instance = self._scene(), Handle(), Handle()
        try:
            points = np.ascontiguousarray(obj.points, dtype=np.float32)
            triangles = np.ascontiguousarray(obj.triangles, dtype=np.int32)
            if np.linalg.det(obj.transform[:3, :3]) < 0:
                triangles = np.ascontiguousarray(triangles[:, ::-1])
            indices = np.ascontiguousarray(obj.material_indices, dtype=np.int32)
            materials = (Material * len(obj.materials))()
            for i, material in enumerate(obj.materials):
                absorption, scattering, transmission = converted_material(
                    material, obj.planar
                )
                materials[i] = Material(F3(*absorption), scattering, F3(*transmission))
            settings = MeshSettings(
                len(points),
                len(triangles),
                len(materials),
                points.ctypes.data,
                triangles.ctypes.data,
                indices.ctypes.data,
                materials,
            )
            self._check(
                self.lib.iplStaticMeshCreate(sub, C.byref(settings), C.byref(mesh))
            )
            self.lib.iplStaticMeshAdd(mesh, sub)
            self.lib.iplSceneCommit(sub)
            instance_settings = InstanceSettings(sub, _matrix(obj.transform))
            self._check(
                self.lib.iplInstancedMeshCreate(
                    self.scene, C.byref(instance_settings), C.byref(instance)
                )
            )
            self.lib.iplInstancedMeshAdd(instance, self.scene)
            self.builds += 1
            return (
                sub,
                mesh,
                instance,
                obj.revision,
                obj.planar,
                obj.transform.copy(),
                obj.materials,
                obj.material_indices.copy(),
            )
        except Exception:
            if instance:
                self.lib.iplInstancedMeshRelease(C.byref(instance))
            if mesh:
                self.lib.iplStaticMeshRelease(C.byref(mesh))
            self.lib.iplSceneRelease(C.byref(sub))
            raise

    def _remove(self, path):
        sub, mesh, instance, *_ = self.entries.pop(path)
        self.lib.iplInstancedMeshRemove(instance, self.scene)
        self.lib.iplInstancedMeshRelease(C.byref(instance))
        self.lib.iplStaticMeshRelease(C.byref(mesh))
        self.lib.iplSceneRelease(C.byref(sub))

    @staticmethod
    def _assemblies(objects):
        """Fragments of one construction share one native mesh/material definition."""
        from types import SimpleNamespace

        groups = {}
        for obj in objects.values():
            groups.setdefault(obj.partition, []).append(obj)
        result = {}
        for key, members in groups.items():
            if len(members) == 1:
                result[key] = members[0]
                continue
            reference = members[0].transform
            inverse = np.linalg.inv(reference)
            points, triangles, indices, materials, revisions = [], [], [], [], []
            offset = 0
            for obj in members:
                relative = obj.transform @ inverse
                transformed = (
                    np.column_stack((obj.points, np.ones(len(obj.points)))) @ relative
                )[:, :3]
                points.append(transformed)
                triangles.append(obj.triangles + offset)
                indices.append(obj.material_indices + len(materials))
                materials.extend(obj.materials)
                revisions.append(
                    (obj.path, obj.revision, tuple(np.round(relative, 9).flat))
                )
                offset += len(obj.points)
            result[key] = SimpleNamespace(
                points=np.concatenate(points),
                triangles=np.concatenate(triangles),
                material_indices=np.concatenate(indices),
                materials=tuple(materials),
                transform=reference,
                planar=all(o.planar for o in members),
                revision=tuple(revisions),
            )
        return result

    def sync(self, objects, *, valid):
        if self.closed:
            raise RuntimeError("Steam scene is closed")
        self.verified = False
        objects = self._assemblies(objects)
        for path in set(self.entries) - set(objects):
            self._remove(path)
        for path, obj in objects.items():
            entry = self.entries.get(path)
            if entry and (
                entry[3] != obj.revision
                or entry[4] != obj.planar
                or entry[6] != obj.materials
                or not np.array_equal(entry[7], obj.material_indices)
                or np.sign(np.linalg.det(entry[5][:3, :3]))
                != np.sign(np.linalg.det(obj.transform[:3, :3]))
            ):
                self._remove(path)
                entry = None
            if entry is None:
                self.entries[path] = self._create(obj)
            elif not np.array_equal(entry[5], obj.transform):
                self.lib.iplInstancedMeshUpdateTransform(
                    entry[2], self.scene, _matrix(obj.transform)
                )
                self.entries[path] = (*entry[:5], obj.transform.copy(), *entry[6:])
                self.updates += 1
        self.lib.iplSceneCommit(self.scene)
        self.verified = valid and bool(objects)

    def export_geometry(self, path):
        """Export provider geometry for preparation review (not acoustic paths)."""
        if self.closed:
            raise RuntimeError("Steam scene is closed")
        self.lib.iplSceneSaveOBJ(self.scene, str(Path(path).resolve()).encode())

    def snapshot(self):
        """Retain shared meshes with independent, immutable instance transforms."""
        if self.closed:
            raise RuntimeError("Steam scene is closed")
        return SceneSnapshot(self)

    def close(self):
        if self.closed:
            return
        for path in list(self.entries):
            self._remove(path)
        for handle, release in (
            (self.scene, "iplSceneRelease"),
            (self.device, "iplEmbreeDeviceRelease"),
            (self.context, "iplContextRelease"),
        ):
            if handle:
                getattr(self.lib, release)(C.byref(handle))
        self.verified = False
        self.closed = True


# Exact selected R9 Release/Embree artifact; changing it requires native gates.
QUALIFIED_LIBRARY_SHA256 = (
    "eaf2a6420d8c8e7822795a79dab455df70512e367a70d2d0d53ffc32dd0fd445"
)

# Native probe/filter/visibility controls; domain admission is documented separately.
NLOS_LIBRARY_SHA256 = "74f3d78b381afd84ff98e20b000705cf3128a831735c888ca60a13ebf77604ba"


class SceneSnapshot:
    """Own only scene/instance handles; Steam retains the shared static meshes."""

    def __init__(self, provider):
        self.lib = provider.lib
        self.scene = provider._scene()
        self.instances = []
        try:
            for sub, _, _, _, _, transform, *_ in provider.entries.values():
                instance = Handle()
                provider._check(
                    self.lib.iplInstancedMeshCreate(
                        self.scene,
                        C.byref(InstanceSettings(sub, _matrix(transform))),
                        C.byref(instance),
                    )
                )
                self.instances.append(instance)
                self.lib.iplInstancedMeshAdd(instance, self.scene)
            self.lib.iplSceneCommit(self.scene)
        except Exception:
            self.close()
            raise

    def close(self):
        for instance in self.instances:
            self.lib.iplInstancedMeshRelease(C.byref(instance))
        self.instances.clear()
        if self.scene:
            self.lib.iplSceneRelease(C.byref(self.scene))
