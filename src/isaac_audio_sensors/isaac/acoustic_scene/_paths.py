"""Native selected-route capture, automatic probes and per-route pressure filters."""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass

import numpy as np

from isaac_audio_sensors.isaac.acoustic_scene._steam_audio import audio_buffer
from isaac_audio_sensors.isaac.acoustic_scene._steam_audio_types import (
    _AudioSettings,
    _PathEffectParams,
)
from isaac_audio_sensors.isaac.acoustic_scene.steam import Handle


@dataclass(frozen=True)
class Route:
    """One interpolation contribution; coordinates stay in Steam's metre frame."""

    probes: tuple[int, ...]
    points: np.ndarray
    length_m: float
    weight: float
    eq: tuple[float, float, float]
    interpolation_probes: tuple[int, int] | None = None


_CALLBACK = C.CFUNCTYPE(
    None,
    C.c_int,
    C.POINTER(C.c_int),
    C.POINTER(C.c_float),
    C.c_float,
    C.c_float,
    C.POINTER(C.c_float),
    Handle,
)

_CALLBACK_V2 = C.CFUNCTYPE(
    None,
    C.c_int,
    C.POINTER(C.c_int),
    C.POINTER(C.c_float),
    C.c_float,
    C.c_float,
    C.POINTER(C.c_float),
    C.c_int,
    C.c_int,
    Handle,
)


def _require_abi(lib):
    try:
        lib.ias_path_abi.argtypes = []
        lib.ias_path_abi.restype = C.c_int
        version = lib.ias_path_abi()
    except AttributeError as exc:
        raise RuntimeError("Steam selected-route extension is unavailable.") from exc
    if version not in (1, 2):
        raise RuntimeError("Unsupported Steam selected-route ABI.")
    return version


def capture(lib, simulate):
    """Copy selected contributions synchronously, unregister even on failure.

    Not reentrant: the caller must serialize captures on this thread. An empty
    result means no exported route; it does not certify complete probe coverage.
    """
    version = _require_abi(lib)
    lib.ias_path_capture.argtypes = [Handle, Handle]
    lib.ias_path_capture.restype = None
    routes = []

    def receive(count, ids, xyz, length, weight, eq, *rest):
        points = np.ctypeslib.as_array(xyz, shape=(count * 3,)).copy().reshape(-1, 3)
        pair = tuple(rest[:2]) if version == 2 else None
        routes.append(
            Route(tuple(ids[:count]), points, length, weight, tuple(eq[:3]), pair)
        )

    receive = (_CALLBACK_V2 if version == 2 else _CALLBACK)(receive)

    lib.ias_path_capture(C.cast(receive, Handle), None)
    try:
        simulate()
    finally:
        lib.ias_path_capture(None, None)
    for route in routes:
        if (
            len(route.points) < 3
            or not np.isfinite(route.points).all()
            or not np.isfinite((route.length_m, route.weight, *route.eq)).all()
            or route.length_m <= 0
            or route.weight < 0
            or min(route.eq) < 0
            or abs(
                np.linalg.norm(np.diff(route.points, axis=0), axis=1).sum()
                - route.length_m
            )
            > max(1e-5, 1e-5 * route.length_m)
        ):
            raise RuntimeError("Invalid selected Steam route.")
    return routes


class _SpeakerLayout(C.Structure):
    _fields_ = [("type", C.c_int), ("count", C.c_int32), ("speakers", Handle)]


class _PathSettings(C.Structure):
    _fields_ = [
        ("order", C.c_int32),
        ("spatialize", C.c_int),
        ("layout", _SpeakerLayout),
        ("hrtf", Handle),
    ]


class RouteFilter:
    """Native per-route deviation EQ, with one physical delay and one weight."""

    def __init__(self, lib, context, rate=16000, frame_samples=128):
        _require_abi(lib)
        if (
            type(rate) is not int
            or rate <= 0
            or type(frame_samples) is not int
            or frame_samples <= 0
            or frame_samples & (frame_samples - 1)
        ):
            raise ValueError("Positive rate and power-of-two native frame required.")
        self.lib, self.rate, self.frame = lib, rate, frame_samples
        self.native_rate = max(48000, rate)
        self.handle = Handle()
        p = C.POINTER
        lib.iplPathEffectCreate.argtypes = [
            Handle,
            p(_AudioSettings),
            p(_PathSettings),
            p(Handle),
        ]
        lib.iplPathEffectCreate.restype = C.c_int
        lib.iplPathEffectReset.argtypes = [Handle]
        lib.iplPathEffectReset.restype = None
        lib.iplPathEffectRelease.argtypes = [p(Handle)]
        lib.iplPathEffectRelease.restype = None
        from isaac_audio_sensors.isaac.acoustic_scene._steam_audio_types import (
            _AudioBuffer,
        )

        lib.iplPathEffectApply.argtypes = [
            Handle,
            p(_PathEffectParams),
            p(_AudioBuffer),
            p(_AudioBuffer),
        ]
        lib.iplPathEffectApply.restype = C.c_int
        result = lib.iplPathEffectCreate(
            context,
            C.byref(_AudioSettings(self.native_rate, self.frame)),
            C.byref(_PathSettings()),
            C.byref(self.handle),
        )
        if result:
            raise RuntimeError(f"Native path filter creation failed ({result}).")

    def close(self):
        if self.handle:
            self.lib.iplPathEffectRelease(C.byref(self.handle))

    def equalizer(self, eq):
        """Settled causal native EQ at the receiver sample rate, without transport."""
        import math

        from scipy.signal import resample_poly

        if not self.handle:
            raise RuntimeError("Native path filter is closed.")
        sh = (C.c_float * 1)(1.0)
        params = _PathEffectParams()
        params.eq_coeffs[:] = eq
        params.sh_coeffs = sh
        self.lib.iplPathEffectReset(self.handle)
        emission = np.zeros(self.frame, np.float32)

        def render():
            result = np.zeros(self.frame, np.float32)
            inp, keep = audio_buffer(emission)
            out, out_keep = audio_buffer(result)
            self.lib.iplPathEffectApply(
                self.handle, C.byref(params), C.byref(inp), C.byref(out)
            )
            return result

        render()
        render()  # Settle native parameter ramps before measuring the filter.
        emission[0] = 1
        response = [render()]
        emission[0] = 0
        for _ in range(math.ceil(0.2 * self.native_rate / self.frame)):
            response.append(render())
        response = np.concatenate(response)
        if np.max(abs(response[-self.frame :])) > max(
            1e-9, 1e-6 * np.max(abs(response))
        ):
            raise RuntimeError("Native path filter exceeds its settling horizon.")
        if self.native_rate != self.rate:
            divisor = math.gcd(self.rate, self.native_rate)
            response = (
                resample_poly(
                    response, self.rate // divisor, self.native_rate // divisor
                )
                * self.native_rate
                / self.rate
            )
        return response

    def impulse(self, route, *, gain=1.0, speed=343.0, max_delay_s=1.0):
        """gain contains source/microphone directivity, without distance or weight.

        Pressure convention matches Geometry: 1/(4*pi*r). Native probe deviation
        EQ is an approximation to bending loss, not a calibrated diffraction law.
        """
        import math

        import pyroomacoustics as pra
        from scipy.signal import fftconvolve

        if not self.handle:
            raise RuntimeError("Native path filter is closed.")
        if not np.isfinite((gain, speed, max_delay_s)).all() or speed <= 0:
            raise ValueError("Finite gain and positive speed/horizon required.")
        delay = route.length_m / speed
        if not math.isfinite(delay) or not 0 < delay <= max_delay_s:
            raise ValueError("Selected route exceeds its physical delay horizon.")
        response = self.equalizer(route.eq)
        sample = delay * self.rate
        integer = math.floor(sample)
        kernel = np.zeros((1, 81), np.float32)
        pra.libroom.fractional_delay(
            kernel, np.array([sample - integer], np.float32), 20, 1
        )
        response = np.pad(fftconvolve(response, kernel[0]), (integer, 0))[40:]
        return response * (route.weight * gain / (4 * math.pi * route.length_m))


class EmissionConvolution:
    """Overlap-add native responses without retiming already emitted samples.

    Responses describe the geometry at emission. Updating them affects only new
    input; existing arrivals drain. This is exact for stationary paths. Motion
    between updates and later interception by a moving obstacle are NOT solved.
    """

    def __init__(self, microphones, horizon_samples):
        if microphones <= 0 or horizon_samples <= 0:
            raise ValueError("Positive channel count and arrival horizon required.")
        self.pending = np.zeros((microphones, horizon_samples), np.float32)

    def reset(self):
        self.pending.fill(0)

    def process(self, emission, responses):
        from scipy.signal import fftconvolve

        values = np.asarray(emission, np.float32)
        if values.ndim != 1 or not np.isfinite(values).all():
            raise ValueError("Emission must be a finite mono signal.")
        if len(responses) != len(self.pending):
            raise ValueError("Response microphone count changed.")
        length = max(map(len, responses))
        if length > self.pending.shape[1]:
            raise ValueError("Response exceeds the arrival horizon.")
        if not len(values):
            return np.zeros((len(responses), 0), np.float32)
        impulse = np.array([np.pad(r, (0, length - len(r))) for r in responses])
        future = fftconvolve(values[None], impulse, axes=-1).astype(np.float32)
        size = max(future.shape[1], self.pending.shape[1] + len(values))
        future = np.pad(future, ((0, 0), (0, size - future.shape[1])))
        future[:, : self.pending.shape[1]] += self.pending
        output = future[:, : len(values)].copy()
        self.pending[:] = future[:, len(values) : len(values) + self.pending.shape[1]]
        return output


class ProbeRoutes:
    """Native automatic probes and search; coordinates are Steam metre/Y-up."""

    def __init__(self, lib, scene, bounds, spacing, height, max_probes):
        import threading

        if _require_abi(lib) != 2:
            raise RuntimeError("Automatic NLOS requires selected-route ABI 2.")
        self.lib, self.handle = lib, Handle()
        self.lock = threading.Lock()
        try:
            lib.ias_probes_abi.restype = C.c_int
            if lib.ias_probes_abi() != 1:
                raise RuntimeError("Unsupported Steam automatic-probe ABI.")
            lib.ias_probes_create.argtypes = [
                Handle,
                Handle,
                C.c_float,
                C.c_float,
                C.c_int,
                C.POINTER(Handle),
            ]
            lib.ias_probes_create.restype = C.c_int
            lib.ias_probes_release.argtypes = [Handle]
            lib.ias_probes_release.restype = None
            lib.ias_probes_find.argtypes = [Handle, Handle, Handle, Handle]
            lib.ias_probes_find.restype = C.c_int
        except AttributeError as exc:
            raise RuntimeError(
                "Steam automatic-probe extension is unavailable."
            ) from exc
        bounds = np.ascontiguousarray(bounds, np.float32)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
            raise ValueError("Probe bounds must be finite [min,max] metre coordinates.")
        self.count = lib.ias_probes_create(
            scene, bounds.ctypes.data, spacing, height, max_probes, C.byref(self.handle)
        )
        if self.count <= 0:
            reason = {
                -1: "invalid bounds or generation parameters",
                -2: "no floor probes; prepare a bounded floor acoustic representation",
                -3: "probe capacity exceeded; bound the acoustic roots or spacing",
                -4: "native bake failed",
            }.get(self.count, "unknown native failure")
            raise RuntimeError(f"Steam NLOS preparation failed: {reason}.")

    def close(self):
        if self.handle:
            self.lib.ias_probes_release(self.handle)
            self.handle = Handle()

    def find(self, scene, source, listener):
        if not self.handle:
            raise RuntimeError("Steam NLOS probes are closed.")
        source, listener = (
            np.ascontiguousarray(p, np.float32) for p in (source, listener)
        )
        if any(p.shape != (3,) or not np.isfinite(p).all() for p in (source, listener)):
            raise ValueError("NLOS endpoints must be finite xyz coordinates.")
        status = None

        def simulate():
            nonlocal status
            status = self.lib.ias_probes_find(
                self.handle, scene, source.ctypes.data, listener.ctypes.data
            )

        with self.lock:
            routes = capture(self.lib, simulate)
        if status < 0:
            reason = {
                -1: "invalid native input",
                -2: "source outside probe coverage",
                -3: "receiver outside probe coverage",
                -4: "no visible endpoint probes; coverage is unavailable",
                -5: "native search failed",
            }.get(status, "unknown native failure")
            raise RuntimeError(f"Steam NLOS unavailable: {reason}.")
        return canonical_routes(routes), (
            "los" if status == 1 else "selected" if routes else "no_selected_route"
        )


def canonical_routes(routes):
    """Sum interpolation contributions, never add duplicate native records twice.

    Geometric keys survive probe renumbering. Distinct EQ contributions remain
    separate linear filters, even when they follow the same geometric route.
    """
    from dataclasses import replace

    seen, groups = set(), {}
    for route in routes:
        geometry = tuple(tuple(p) for p in np.round(route.points[1:-1], 6))
        key = geometry, route.eq
        record = route.interpolation_probes or route.probes, key
        if record in seen:
            raise RuntimeError("Steam exported a duplicate probe contribution.")
        seen.add(record)
        if key in groups:
            previous = groups[key]
            groups[key] = replace(previous, weight=previous.weight + route.weight)
        else:
            groups[key] = route
    return tuple(groups[key] for key in sorted(groups))
