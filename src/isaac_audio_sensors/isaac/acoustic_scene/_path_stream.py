"""Retarded transport of selected Steam polylines through held scene snapshots.

The timeline is explicit: geometry is constant between committed updates; source
and receiver positions follow supplied trajectories. This schedules native routes,
not a new path search or diffraction solver. Route selection is emission-owned.
It cannot discover a flight that is absent from every instantaneous native route
selection. This admission failure is documented in R10; do not enable this helper
as complete GeometryAcoustics pathing.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass

import numpy as np

from isaac_audio_sensors.core.backends._analytic.arrival import retarded_path

from ._paths import EmissionConvolution


class SegmentQuery:
    """Query a committed native scene that stays immutable for this object's life."""

    def __init__(self, lib, scene):
        try:
            lib.ias_visibility_abi.restype = C.c_int
            if lib.ias_visibility_abi() != 1:
                raise RuntimeError("Unsupported Steam visibility ABI.")
            lib.ias_scene_segments.argtypes = [
                C.c_void_p,
                C.c_int,
                C.c_void_p,
                C.c_void_p,
                C.c_void_p,
            ]
            lib.ias_scene_segments.restype = C.c_int
        except AttributeError as exc:
            raise RuntimeError(
                "Steam timed visibility extension is unavailable."
            ) from exc
        self.lib, self.scene = lib, scene

    def __call__(self, starts, ends):
        starts = np.ascontiguousarray(starts, dtype=np.float32)
        ends = np.ascontiguousarray(ends, dtype=np.float32)
        if starts.shape != ends.shape or starts.ndim != 2 or starts.shape[1] != 3:
            raise ValueError("Native segment arrays must have matching [N,3] shapes.")
        output = np.zeros(len(starts), np.uint8)
        if len(starts) and self.lib.ias_scene_segments(
            self.scene,
            len(starts),
            starts.ctypes.data,
            ends.ctypes.data,
            output.ctypes.data,
        ):
            raise RuntimeError("Native timed segment query failed.")
        return output.astype(bool)


class GeometryHistory:
    """Half-open geometry epochs; retain snapshots until their flights have drained."""

    def __init__(self):
        self.epochs = []

    def append(self, time, query, release=lambda: None):
        if not np.isfinite(time) or (self.epochs and time <= self.epochs[-1][0]):
            raise ValueError(
                "Geometry snapshots need strictly increasing finite times."
            )
        self.epochs.append((float(time), query, release))

    def close(self):
        for _, _, release in self.epochs:
            release()
        self.epochs.clear()

    def prune(self, before):
        while len(self.epochs) > 1 and self.epochs[1][0] <= before:
            self.epochs.pop(0)[2]()

    def visible(self, points, emission, speed=343.0):
        points = np.asarray(points, float)
        emission = np.asarray(emission, float)
        if points.ndim != 3 or points.shape[0] != len(emission) or points.shape[2] != 3:
            raise ValueError("Timed routes need [sample, vertex, xyz] geometry.")
        if not self.epochs or (
            len(emission) and emission.min() < self.epochs[0][0] - 1e-12
        ):
            raise ValueError("Geometry history does not cover the acoustic flight.")
        visible = np.ones(len(emission), bool)
        lengths = np.linalg.norm(np.diff(points, axis=1), axis=-1)
        times = (
            emission[:, None]
            + np.c_[np.zeros(len(points)), np.cumsum(lengths, axis=1)] / speed
        )
        stamps = [epoch[0] for epoch in self.epochs]
        first = max(0, int(np.searchsorted(stamps, times.min(), side="right")) - 1)
        last = int(np.searchsorted(stamps, times.max(), side="right"))
        for index in range(first, last):
            stamp, query, _ = self.epochs[index]
            stop = self.epochs[index + 1][0] if index + 1 < len(self.epochs) else np.inf
            for leg in range(lengths.shape[1]):
                start = np.maximum(times[:, leg], stamp)
                end = np.minimum(times[:, leg + 1], stop)
                mask = visible & (end > start) & (lengths[:, leg] > 1e-9)
                if not mask.any():
                    continue
                direction = (points[mask, leg + 1] - points[mask, leg]) / lengths[
                    mask, leg, None
                ]
                a = (
                    points[mask, leg]
                    + (start[mask] - times[mask, leg])[:, None] * speed * direction
                )
                b = (
                    points[mask, leg]
                    + (end[mask] - times[mask, leg])[:, None] * speed * direction
                )
                visible[mask] &= ~query(a, b)
        return visible


@dataclass
class RouteEpoch:
    start: float
    end: float
    routes: tuple


def routed_emission(times, receiver, source_trajectory, route, speed, rate):
    """Solve te + (source(te)->fixed native nodes->receiver(tr))/c = tr."""
    nodes = route.points[1:-1].astype(float)
    internal = np.linalg.norm(np.diff(nodes, axis=0), axis=1).sum()
    last = np.linalg.norm(receiver - nodes[-1], axis=1)
    first_receiver = np.broadcast_to(nodes[0], receiver.shape)
    emission, first, _ = retarded_path(
        times - (internal + last) / speed,
        first_receiver,
        source_trajectory,
        speed,
        rate,
    )
    points = np.concatenate(
        (
            source_trajectory.at(emission)[:, None, :],
            np.broadcast_to(nodes, (len(times), *nodes.shape)),
            receiver[:, None, :],
        ),
        axis=1,
    )
    return emission, first + internal + last, points


class RetardedRouteStream:
    """One source and receiver array, with native EQ after retarded transport.

    Epoch changes affect emission routing, never an earlier packet's flight time.
    Native EQ tails are retained on the receiver clock. GeometryHistory handles
    interception only on portions traversed in each geometry epoch. Callers must
    supply the same simulation epochs independently of PCM read partitioning.
    """

    def __init__(self, rate, microphones, max_delay_s, equalizer):
        if (
            type(rate) is not int
            or rate <= 0
            or type(microphones) is not int
            or microphones <= 0
            or not np.isfinite(max_delay_s)
            or max_delay_s <= 0
        ):
            raise ValueError(
                "Positive rate, channel count and finite delay horizon required."
            )
        self.rate, self.microphones, self.max_delay = rate, microphones, max_delay_s
        self.equalizer = equalizer
        self.epochs = []
        self.cursor = 0
        self.input_start = 0
        self.emission = np.empty(0, np.float32)
        self.filters = {}
        self.epoch_signature = None
        self.tail = EmissionConvolution(microphones, int(0.25 * rate) + 128)

    def append(self, start_sample, emission, routes):
        if start_sample != self.input_start + len(self.emission):
            raise ValueError("Emission must append on a continuous sample clock.")
        if len(routes) != self.microphones:
            raise ValueError("Route microphone count changed.")
        values = np.asarray(emission, np.float32)
        if values.ndim != 1 or not np.isfinite(values).all() or not len(values):
            raise ValueError("Append a finite, nonempty mono emission.")
        self.emission = np.r_[self.emission, values]
        signature = tuple(
            tuple(
                (tuple(route.points[1:-1].flat), route.weight, route.eq)
                for route in channel
            )
            for channel in routes
        )
        if self.epochs and signature == self.epoch_signature:
            self.epochs[-1].end = (start_sample + len(values)) / self.rate
            return
        self.epoch_signature = signature
        self.epochs.append(
            RouteEpoch(
                start_sample / self.rate,
                (start_sample + len(values)) / self.rate,
                tuple(tuple(ch) for ch in routes),
            )
        )

    def reset(self):
        self.epochs.clear()
        self.cursor = self.input_start = 0
        self.emission = np.empty(0, np.float32)
        self.filters.clear()
        self.epoch_signature = None
        self.tail.reset()

    def read(
        self,
        count,
        source_trajectory,
        receivers,
        geometry,
        speed=343.0,
        directional_gain=None,
    ):
        if len(receivers) != self.microphones:
            raise ValueError("Receiver trajectory count changed.")
        if not np.isfinite(speed) or speed <= 0:
            raise ValueError("Sound speed must be finite and positive.")
        if self.cursor + count > self.input_start + len(self.emission):
            raise ValueError("Cannot read beyond available emission/scene time.")
        if type(count) is not int or count < 0:
            raise ValueError("Read count must be a nonnegative integer.")
        if count == 0:
            return np.zeros((self.microphones, 0), np.float32)
        for trajectory in [source_trajectory, *receivers]:
            if any(np.linalg.norm(v) >= speed for v in trajectory.velocities):
                raise ValueError(
                    "Retarded routes require subsonic source/receiver motion."
                )
        times = (self.cursor + np.arange(count)) / self.rate
        positions = [receiver.at(times) for receiver in receivers]
        knots = np.asarray(source_trajectory.times)
        # Each carrier is delayed first, then filtered using the native route EQ.
        carriers = {}
        for epoch in self.epochs:
            # The norm on a linear trajectory segment reaches its maximum at an
            # endpoint. This conservative bound retires old flights before solving
            # per-sample arrival times, without assuming a fixed route delay.
            source_points = source_trajectory.at(
                np.r_[
                    epoch.start,
                    epoch.end,
                    knots[(knots > epoch.start) & (knots < epoch.end)],
                ]
            )
            for mic, routes in enumerate(epoch.routes):
                position = positions[mic]
                for route in routes:
                    nodes = route.points[1:-1]
                    maximum = (
                        np.linalg.norm(source_points - nodes[0], axis=-1).max()
                        + np.linalg.norm(np.diff(nodes, axis=0), axis=-1).sum()
                        + np.linalg.norm(position - nodes[-1], axis=-1).max()
                    )
                    if epoch.end + maximum / speed < times[0]:
                        continue
                    emission, length, points = routed_emission(
                        times, position, source_trajectory, route, speed, self.rate
                    )
                    mask = (
                        (emission >= epoch.start)
                        & (emission < epoch.end)
                        & (emission >= 0)
                    )
                    if not mask.any():
                        continue
                    if np.any((length[mask] / speed) > self.max_delay):
                        raise ValueError(
                            "Retarded route exceeds the configured delay horizon."
                        )
                    mask[mask] &= geometry.visible(points[mask], emission[mask], speed)
                    if not mask.any():
                        continue
                    gain = (
                        np.ones(mask.sum())
                        if directional_gain is None
                        else directional_gain(
                            mic, emission[mask], times[mask], points[mask]
                        )
                    )
                    carrier = carriers.setdefault(
                        (mic, route.eq), np.zeros(count, float)
                    )
                    values = np.interp(
                        emission[mask] * self.rate - self.input_start,
                        np.arange(len(self.emission)),
                        self.emission,
                        left=0.0,
                        right=0.0,
                    )
                    carrier[mask] += (
                        values * route.weight * gain / (4 * np.pi * length[mask])
                    )
        # Store only native-filter tails; transport itself is sampled causally above.
        output = self.tail.process(np.zeros(count), [np.zeros(1)] * self.microphones)
        from scipy.signal import fftconvolve

        for (mic, eq), values in carriers.items():
            if eq not in self.filters:
                self.filters[eq] = self.equalizer(eq)
            filtered = fftconvolve(values, self.filters[eq]).astype(np.float32)
            output[mic] += filtered[:count]
            remaining = filtered[count:]
            if len(remaining) > self.tail.pending.shape[1]:
                raise ValueError("Native EQ exceeds the configured filter horizon.")
            self.tail.pending[mic, : len(remaining)] += remaining
        self.cursor += count
        before = (self.cursor - 1) / self.rate - self.max_delay
        self.epochs = [e for e in self.epochs if e.end > before]
        keep = max(self.input_start, int(np.floor(before * self.rate)) - 1)
        drop = max(0, keep - self.input_start)
        self.emission = self.emission[drop:]
        self.input_start += drop
        active_eq = {
            route.eq
            for epoch in self.epochs
            for channel in epoch.routes
            for route in channel
        }
        self.filters = {eq: ir for eq, ir in self.filters.items() if eq in active_eq}
        return output
