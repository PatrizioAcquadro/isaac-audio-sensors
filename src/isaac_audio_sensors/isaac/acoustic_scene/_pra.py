"""Checked private PRA energy-transport and visibility interface."""

import ctypes as C

import numpy as np


class Event(C.Structure):
    _fields_ = [
        ("ray", C.c_uint64),
        ("parent", C.c_int64),
        *(
            (name, C.c_int)
            for name in (
                "kind",
                "surface",
                "receiver",
                "bounce",
                "diffuse_bounces",
                "scattered",
            )
        ),
        ("distance", C.c_float),
        *((name, C.c_float * 3) for name in ("position", "incoming", "departure")),
        ("local", C.c_float * 2),
    ]


class Transport:
    """Borrow a specular scene's handle; all coordinates use the native frame."""

    def __init__(self, scene):
        self.scene = scene
        self.lib = scene.lib
        specifications = {
            "ias_pra_transport_abi": (C.c_int, []),
            "ias_pra_event_size": (C.c_int, []),
            "ias_pra_visibility_abi": (C.c_int, []),
            "ias_pra_projection_abi": (C.c_int, []),
            "ias_pra_departure_visible": (
                C.c_int,
                [C.c_void_p, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p],
            ),
            "ias_pra_illumination_abi": (C.c_int, []),
            "ias_pra_illuminate": (
                C.c_int,
                [
                    C.c_void_p,
                    C.c_void_p,
                    C.c_int,
                    C.c_void_p,
                    C.c_void_p,
                    C.c_void_p,
                    C.c_void_p,
                ],
            ),
            "ias_pra_segments_visible": (
                C.c_int,
                [C.c_void_p, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p],
            ),
            "ias_pra_trace": (
                C.c_int64,
                [
                    C.c_void_p,
                    C.c_void_p,
                    C.c_int,
                    C.c_void_p,
                    C.c_int,
                    C.c_float,
                    C.c_float,
                    C.c_float,
                    C.c_uint64,
                    C.c_int64,
                ],
            ),
            "ias_pra_trace_outputs": (
                C.c_int,
                [C.c_void_p, C.c_int64, C.c_void_p, C.c_void_p],
            ),
        }
        try:
            for name, (result, arguments) in specifications.items():
                function = getattr(self.lib, name)
                function.restype, function.argtypes = result, arguments
        except AttributeError as exc:
            raise RuntimeError(
                "PRA diffuse extension unavailable; rebuild the bridge."
            ) from exc
        if (
            self.lib.ias_pra_transport_abi() != 1
            or self.lib.ias_pra_visibility_abi() != 1
            or self.lib.ias_pra_projection_abi() != 1
            or self.lib.ias_pra_illumination_abi() != 1
            or self.lib.ias_pra_event_size() != C.sizeof(Event)
        ):
            raise RuntimeError("Unsupported PRA diffuse transport ABI.")

    def trace(self, source, *, rays, horizon, seed, limit, threshold=1e-7):
        source = np.ascontiguousarray(source, np.float32)
        if source.shape != (3,) or not np.isfinite(source).all():
            raise ValueError("PRA source must be a finite xyz point.")
        count = self.lib.ias_pra_trace(
            self.scene.handle,
            source.ctypes.data,
            0,
            None,
            rays,
            horizon,
            0.1,
            threshold,
            seed,
            limit,
        )
        if count < 0:
            raise RuntimeError(self.lib.ias_specular_error().decode())
        events = np.empty(count, dtype=np.dtype(Event))
        energy = np.empty((count, len(self.scene.bands.centers)), np.float32)
        if self.lib.ias_pra_trace_outputs(
            self.scene.handle, count, events.ctypes.data, energy.ctypes.data
        ):
            raise RuntimeError(self.lib.ias_specular_error().decode())
        return events, energy

    def visible(self, starts, ends):
        starts, ends = np.broadcast_arrays(starts, ends)
        if starts.ndim < 1 or starts.shape[-1] != 3:
            raise ValueError("Visibility endpoints must be xyz points.")
        shape = starts.shape[:-1]
        starts, ends = (
            np.ascontiguousarray(p, np.float32).reshape(-1, 3) for p in (starts, ends)
        )
        result = np.empty(len(starts), np.uint8)
        if self.lib.ias_pra_segments_visible(
            self.scene.handle,
            len(starts),
            starts.ctypes.data,
            ends.ctypes.data,
            result.ctypes.data,
        ):
            raise RuntimeError(self.lib.ias_specular_error().decode())
        return result.astype(bool).reshape(shape)

    def departure_visible(self, surfaces, directions, points):
        """Keep projected flights on their native previous reflector's exit side."""
        directions, points = np.broadcast_arrays(directions, points)
        if points.ndim < 1 or points.shape[-1] != 3:
            raise ValueError("Departure connections must be xyz points.")
        shape = points.shape[:-1]
        surfaces = np.ascontiguousarray(np.broadcast_to(surfaces, shape), np.int32)
        directions, points = (
            np.ascontiguousarray(v, np.float32).reshape(-1, 3)
            for v in (directions, points)
        )
        result = np.empty(len(points), np.uint8)
        if self.lib.ias_pra_departure_visible(
            self.scene.handle,
            len(points),
            surfaces.ctypes.data,
            directions.ctypes.data,
            points.ctypes.data,
            result.ctypes.data,
        ):
            raise RuntimeError(self.lib.ias_specular_error().decode())
        return result.astype(bool).reshape(shape)

    def illuminate(self, source, surfaces, points, areas):
        source, points, areas = (
            np.ascontiguousarray(v, np.float32) for v in (source, points, areas)
        )
        surfaces = np.ascontiguousarray(surfaces, np.int32)
        if (
            source.shape != (3,)
            or points.shape != (len(surfaces), 3)
            or surfaces.ndim != 1
            or areas.shape != surfaces.shape
        ):
            raise ValueError("Invalid PRA surface quadrature arrays.")
        energy = np.empty((len(points), len(self.scene.bands.centers)), np.float32)
        if self.lib.ias_pra_illuminate(
            self.scene.handle,
            source.ctypes.data,
            len(points),
            surfaces.ctypes.data,
            points.ctypes.data,
            areas.ctypes.data,
            energy.ctypes.data,
        ):
            raise RuntimeError(self.lib.ias_specular_error().decode())
        return energy
