"""Optional native PRA image-source adapter for the intermediate specular domain."""

from __future__ import annotations

import ctypes as C
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.directivity import (
    microphone_world_orientation,
    pattern_coefficient,
)
from isaac_audio_sensors.core.math_utils import rotate_vector_by_quaternion


def native(values):
    return np.ascontiguousarray(
        np.asarray(values)[..., [0, 2, 1]] * [1, 1, -1], dtype=np.float32
    )


def polygons(obj):
    """Recover each authored face boundary from 08.1's triangulation."""
    points = obj.world_points
    for face in np.unique(obj.face_indices):
        indices = np.flatnonzero(obj.face_indices == face)
        edges = {
            (int(a), int(b))
            for tri in obj.triangles[indices]
            for a, b in zip(tri, np.roll(tri, -1), strict=True)
        }
        boundary = {(a, b) for a, b in edges if (b, a) not in edges}
        successors = dict(boundary)
        if not boundary or len(successors) != len(boundary):
            raise ValueError(f"Unsupported specular face boundary: {obj.path}")
        first = min(successors)
        ordered, current = [first], successors[first]
        while current != first and current not in ordered:
            ordered.append(current)
            current = successors[current]
        if current != first or len(ordered) != len(boundary):
            raise ValueError(f"Unsupported specular face boundary: {obj.path}")
        boundary_points = points[ordered]
        singular = np.linalg.svd(
            boundary_points - boundary_points.mean(axis=0), compute_uv=False
        )
        if len(singular) == 3 and singular[-1] > max(1e-6, singular[0] * 1e-6):
            for index in indices:
                yield (
                    points[obj.triangles[index]],
                    obj.materials[obj.material_indices[index]],
                )
        else:
            yield boundary_points, obj.materials[obj.material_indices[indices[0]]]


def polar(pattern, orientation, directions):
    coefficient = pattern_coefficient(pattern)
    if coefficient == 1:
        return np.ones(len(directions))
    axis = native(rotate_vector_by_quaternion((1.0, 0.0, 0.0), orientation))
    lengths = np.linalg.norm(directions, axis=-1)
    return coefficient + (1 - coefficient) * (directions @ axis) / np.maximum(
        lengths, 1e-12
    )


class SpecularScene:
    def __init__(
        self, session, library_path, sample_rate, order, speed, max_candidates
    ):
        try:
            import pyroomacoustics as pra
        except ImportError as exc:
            raise RuntimeError(
                "Geometry requires optional Pyroomacoustics 0.10.1 and scipy."
            ) from exc

        if pra.__version__ != "0.10.1":
            raise RuntimeError(
                "Geometry specular rendering requires qualified Pyroomacoustics 0.10.1."
            )
        self.pra, self.session = pra, session
        self.rate, self.order, self.speed = sample_rate, order, speed
        self.max_candidates = max_candidates
        self.bands = pra.acoustics.OctaveBandsFactory(fs=sample_rate)
        self.handle = None
        self.signature = None
        try:
            self.lib = C.CDLL(str(Path(library_path).resolve(strict=True)))
        except (OSError, FileNotFoundError) as exc:
            raise RuntimeError(
                "Geometry requires the optional native specular library; "
                "build with tools/native/build_specular.py."
            ) from exc
        specs = {
            "ias_specular_abi": (C.c_int, []),
            "ias_specular_error": (C.c_char_p, []),
            "ias_specular_create": (
                C.c_void_p,
                [
                    C.c_int,
                    C.c_void_p,
                    C.c_void_p,
                    C.c_int,
                    C.c_void_p,
                    C.c_void_p,
                    C.c_int,
                    C.c_float,
                ],
            ),
            "ias_specular_destroy": (None, [C.c_void_p]),
            "ias_specular_solve": (
                C.c_int,
                [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p],
            ),
            "ias_specular_outputs": (None, [C.c_void_p] * 6),
        }
        for name, (result, arguments) in specs.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, arguments
        if self.lib.ias_specular_abi() != 1:
            raise RuntimeError("Unsupported specular library ABI.")
        self.refresh()

    def close(self):
        if self.handle:
            self.lib.ias_specular_destroy(self.handle)
            self.handle = None
        self.signature = None

    def refresh(self):
        signature = tuple(
            (o.path, o.revision, o.materials, tuple(o.transform.flat))
            for o in self.session.objects.values()
        )
        if signature == self.signature:
            return
        rows = [row for obj in self.session.objects.values() for row in polygons(obj)]
        if (
            sum((2 * len(rows)) ** depth for depth in range(1, self.order + 1))
            > self.max_candidates
        ):
            raise ValueError(
                "Prepared geometry exceeds the specular image-candidate budget; "
                "use an explicit acoustic representation or lower reflection_order."
            )
        handle = None
        if rows:
            counts = np.asarray([len(p) for p, _ in rows], np.int32)
            points = np.ascontiguousarray(
                np.concatenate([p for p, _ in rows]), dtype=np.float32
            )
            absorption = np.ascontiguousarray(
                [m.absorption.at(tuple(self.bands.centers)) for _, m in rows],
                dtype=np.float32,
            )
            scattering = np.ascontiguousarray(
                [m.scattering.at(tuple(self.bands.centers)) for _, m in rows],
                dtype=np.float32,
            )
            handle = self.lib.ias_specular_create(
                len(rows),
                counts.ctypes.data,
                points.ctypes.data,
                len(self.bands.centers),
                absorption.ctypes.data,
                scattering.ctypes.data,
                self.order,
                self.speed,
            )
            if not handle:
                raise RuntimeError(self.lib.ias_specular_error().decode())
        self.close()
        self.handle, self.signature = handle, signature

    def paths(self, source_position, positions):
        self.refresh()
        if not self.handle:
            return None
        source, points = native(source_position), native(positions)
        count = self.lib.ias_specular_solve(
            self.handle, source.ctypes.data, len(points), points.ctypes.data
        )
        if count < 0:
            raise RuntimeError(self.lib.ias_specular_error().decode())
        if count == 0:
            return None
        images = np.empty((count, 3), np.float32)
        damping = np.empty((count, len(self.bands.centers)), np.float32)
        directions = np.empty((count, len(points), 3), np.float32)
        orders = np.empty(count, np.int32)
        visible = np.empty((len(points), count), np.uint8)
        self.lib.ias_specular_outputs(
            self.handle,
            *(v.ctypes.data for v in (images, damping, directions, orders, visible)),
        )
        return images, damping, directions, orders, visible.astype(bool)

    def impulses(self, source, array, positions, max_delay_s):
        from pyroomacoustics.simulation.ism import multi_convolve

        paths = self.paths(source.position_world, positions)
        result = []
        for m, (microphone, position) in enumerate(
            zip(array.microphones, native(positions), strict=True)
        ):
            if paths is None:
                result.append(np.zeros(1, np.float32))
                continue
            images, damping, directions, orders, visible = paths
            mask = visible[m] & (orders > 0)
            if not mask.any():
                result.append(np.zeros(1, np.float32))
                continue
            incoming = images[mask] - position
            distances = np.linalg.norm(incoming, axis=1)
            if np.any(distances / self.speed > max_delay_s):
                raise ValueError("Specular arrival exceeds max_delay_s.")
            orientation = microphone_world_orientation(
                array.orientation_world_quat, microphone.relative_orientation_quat
            )
            gain = polar(
                source.directivity, source.orientation_world_quat, directions[mask, m]
            ) * polar(microphone.directivity, orientation, incoming)
            amplitudes = (
                damping[mask]
                * (gain / np.maximum(distances, 1e-6) / (4 * np.pi))[:, None]
            )
            samples = distances / self.speed * self.rate
            integer = np.floor(samples).astype(np.int32)
            fractional = np.ascontiguousarray(samples - integer, dtype=np.float32)
            kernels = np.zeros((len(samples), 81), np.float32)
            self.pra.libroom.fractional_delay(kernels, fractional, 20, 1)
            if np.allclose(amplitudes, amplitudes[:, :1], rtol=1e-6, atol=0):
                kernels *= amplitudes[:, :1]
            else:
                filters = self.bands.synthesis(amplitudes, min_phase=True)
                kernels = np.ascontiguousarray(
                    multi_convolve(kernels, filters), dtype=np.float32
                )
            rir = np.zeros(int(integer.max()) + kernels.shape[1], np.float32)
            self.pra.libroom.delay_sum(kernels, integer, rir, 1)
            result.append(rir[40:])  # Remove only the native fractional-filter latency.
        return result
