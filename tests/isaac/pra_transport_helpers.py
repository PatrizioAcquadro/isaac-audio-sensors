"""Direct checked-ABI fixtures for native PRA transport qualification."""

import ctypes as C
from pathlib import Path

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
    def __init__(self, library, faces, absorption, scattering, order=3):
        self.lib = C.CDLL(str(Path(library).resolve()))
        specifications = {
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
            "ias_specular_error": (C.c_char_p, []),
            "ias_pra_transport_abi": (C.c_int, []),
            "ias_pra_event_size": (C.c_int, []),
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
        for name, (result, arguments) in specifications.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, arguments
        assert self.lib.ias_pra_transport_abi() == 1
        assert self.lib.ias_pra_event_size() == C.sizeof(Event)
        counts = np.array([len(face) for face in faces], np.int32)
        points = np.ascontiguousarray(np.concatenate(faces), np.float32)
        absorption = np.ascontiguousarray(absorption, np.float32)
        scattering = np.ascontiguousarray(scattering, np.float32)
        assert absorption.shape == scattering.shape and absorption.ndim == 2
        assert len(absorption) == len(faces)
        self.bands = absorption.shape[1]
        self.handle = self.lib.ias_specular_create(
            len(faces),
            counts.ctypes.data,
            points.ctypes.data,
            self.bands,
            absorption.ctypes.data,
            scattering.ctypes.data,
            order,
            343.0,
        )
        if not self.handle:
            raise RuntimeError(self.lib.ias_specular_error().decode())

    def close(self):
        if self.handle:
            self.lib.ias_specular_destroy(self.handle)
            self.handle = None

    def trace(
        self,
        source,
        microphones=(),
        *,
        rays=4096,
        horizon=0.15,
        radius=0.1,
        threshold=1e-7,
        seed=0,
        limit=2_000_000,
    ):
        source = np.ascontiguousarray(source, np.float32)
        microphones = np.ascontiguousarray(microphones, np.float32).reshape(-1, 3)
        count = self.lib.ias_pra_trace(
            self.handle,
            source.ctypes.data,
            len(microphones),
            microphones.ctypes.data,
            rays,
            horizon,
            radius,
            threshold,
            seed,
            limit,
        )
        if count < 0:
            raise RuntimeError(self.lib.ias_specular_error().decode())
        events = np.zeros(count, dtype=np.dtype(Event))
        energies = np.empty((count, self.bands), np.float32)
        if self.lib.ias_pra_trace_outputs(
            self.handle, count, events.ctypes.data, energies.ctypes.data
        ):
            raise RuntimeError(self.lib.ias_specular_error().decode())
        return events, energies


def box(dimensions=(6, 6, 3)):
    import pyroomacoustics as pra

    return [wall.corners.T.copy() for wall in pra.ShoeBox(dimensions).walls]


def partition(opened=False):
    faces = box()
    for lo, hi in ((0, 2.5), (3.5, 6)):
        faces.append(np.array([(3, lo, 0), (3, hi, 0), (3, hi, 3), (3, lo, 3)]))
    if not opened:
        faces.append(np.array([(3, 2.5, 0), (3, 3.5, 0), (3, 3.5, 3), (3, 2.5, 3)]))
    return faces
