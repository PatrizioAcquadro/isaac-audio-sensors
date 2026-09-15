"""Optional native probe routes and receiver-clock transport for prepared scenes."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from isaac_audio_sensors.core.backends._analytic.arrival import Trajectory, polar_gain
from isaac_audio_sensors.core.directivity import pattern_coefficient
from isaac_audio_sensors.core.math_utils import rotate_vector_by_quaternion
from isaac_audio_sensors.core.motion.orientation import rotate_vectors

from ._path_stream import GeometryHistory, RetardedRouteStream, SegmentQuery
from ._paths import ProbeRoutes, RouteFilter
from .steam import SteamScene


def native(points):
    return np.asarray(points)[..., [0, 2, 1]] * (1, 1, -1)


def world(points):
    return np.asarray(points)[..., [0, 2, 1]] * (1, -1, 1)


@dataclass(frozen=True, slots=True)
class SteamNLOSConfig:
    """Opt-in automatic floor probes; metre units and explicit bounded resources.

    The floor generator samples the prepared static scene at the specified height.
    Missing floor or uncovered endpoints fail visibly instead of producing silence.
    """

    probe_spacing_m: float = 1.0
    probe_height_m: float = 1.2
    max_probes: int = 4096
    update_hz: int = 100

    def __post_init__(self):
        for name in ("probe_spacing_m", "probe_height_m"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        for name in ("max_probes", "update_hz"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer.")


class NLOSScene:
    """Share static native preparation; retain live snapshots by simulation time."""

    def __init__(self, session, cfg):
        self.session, self.cfg = session, cfg
        self.static = SteamScene(session.provider.library_path)
        self.paths = None
        self.static_signature = None
        self.live_signature = None
        self.history = GeometryHistory()
        self.bakes = 0

    def refresh(self, time):
        objects = {p: o for p, o in self.session.objects.items() if not o.dynamic}
        signature = tuple(
            (p, o.revision, tuple(o.transform.flat), o.partition)
            for p, o in sorted(objects.items())
        )
        if signature != self.static_signature:
            self.static.sync(objects, valid=True)
            points = [
                (np.c_[o.points, np.ones(len(o.points))] @ o.transform)[:, :3]
                for o in objects.values()
            ]
            if not points:
                raise ValueError("Steam NLOS requires static floor geometry.")
            points = np.concatenate(points)
            bounds = np.array([points.min(axis=0), points.max(axis=0)])
            # A floor-only control still needs a nonzero vertical probe volume.
            bounds[1, 1] = max(
                bounds[1, 1], bounds[0, 1] + self.cfg.probe_height_m + 0.1
            )
            replacement = ProbeRoutes(
                self.static.lib,
                self.static.scene,
                bounds,
                self.cfg.probe_spacing_m,
                self.cfg.probe_height_m,
                self.cfg.max_probes,
            )
            if self.paths:
                self.paths.close()
            self.paths = replacement
            self.static_signature = signature
            self.bakes += 1
        provider = self.session.provider
        signature = (
            id(provider),
            provider.builds,
            provider.updates,
            tuple(provider.entries),
        )
        if signature != self.live_signature:
            snapshot = provider.snapshot()
            query = SegmentQuery(provider.lib, snapshot.scene)
            try:
                self.history.append(
                    time, lambda a, b: query(native(a), native(b)), snapshot.close
                )
            except Exception:
                snapshot.close()
                raise
            self.live_signature = signature

    def routes(self, source, receivers):
        channels, states = [], []
        for receiver in receivers:
            routes, state = self.paths.find(
                self.session.provider.scene, native(source), native(receiver)
            )
            channels.append(tuple(replace(r, points=world(r.points)) for r in routes))
            states.append(state)
        return tuple(channels), tuple(states)

    def close(self):
        self.history.close()
        if self.paths:
            self.paths.close()
        self.static.close()


class MicrophoneTrajectory:
    def __init__(self, array, offset):
        self.array, self.offset = array, offset

    @property
    def velocities(self):
        return self.array.velocities

    def at(self, times):
        return self.array.receiver_at(times, self.offset)


class NLOSStream:
    """Array-local emission/routing state; refresh cadence does not follow PCM reads."""

    def __init__(self, owner, array, config, start, speed):
        self.owner, self.config, self.speed = owner, config, speed
        self.rate = array.sample_rate_hz
        if owner.cfg.update_hz > self.rate:
            raise ValueError("NLOS update_hz cannot exceed the audio sample rate.")
        self.array = Trajectory()
        self.trajectories, self.streams, self.routes = {}, {}, {}
        self.states = {}
        self.next_tick = math.ceil(start * owner.cfg.update_hz / self.rate)
        self.start = start
        self.renderer = RouteFilter(
            owner.session.provider.lib,
            owner.session.provider.context,
            self.rate,
            config.frame_samples,
        )
        self.geometry_signature = None

    def observe(self, scene, array, time, window_motion=None):
        entities = [(array.array_id, array, self.array)]
        for source in scene.sources:
            trajectory = self.trajectories.setdefault(source.source_id, Trajectory())
            entities.append((source.source_id, source, trajectory))
            if source.source_id not in self.streams:
                stream = RetardedRouteStream(
                    self.rate,
                    len(array.microphones),
                    self.config.max_delay_s,
                    self.renderer.equalizer,
                )
                stream.cursor = stream.input_start = self.start
                self.streams[source.source_id] = stream
        for entity_id, entity, trajectory in entities:
            if window_motion is None:
                trajectory.observe(
                    time,
                    entity.position_world,
                    entity.velocity_world_mps,
                    entity.orientation_world_quat,
                )
            else:
                for segment in window_motion.segments:
                    motion = segment.entities[entity_id]
                    trajectory.observe(
                        segment.start_time_s,
                        motion.start_position_world_m,
                        motion.velocity_world_mps,
                        motion.start_orientation_world_xyzw
                        or entity.orientation_world_quat,
                    )
                    trajectory.observe(
                        segment.end_time_s,
                        motion.end_position_world_m,
                        motion.velocity_world_mps,
                        motion.end_orientation_world_xyzw
                        or entity.orientation_world_quat,
                    )

    def process(self, scene, array, start, emissions, count):
        end = start + count
        receivers = [
            MicrophoneTrajectory(self.array, m.relative_position_m)
            for m in array.microphones
        ]
        cursor = start
        while cursor < end:
            tick_sample = round(self.next_tick * self.rate / self.owner.cfg.update_hz)
            changed = self.geometry_signature != self.owner.live_signature
            if not self.routes or changed or tick_sample <= cursor:
                time = cursor / self.rate
                positions = [r.at(np.array([time]))[0] for r in receivers]
                for source in scene.sources:
                    source_id = source.source_id
                    self.routes[source_id], self.states[source_id] = self.owner.routes(
                        self.trajectories[source_id].at(np.array([time]))[0], positions
                    )
                self.geometry_signature = self.owner.live_signature
                self.next_tick = max(
                    self.next_tick,
                    math.floor(cursor * self.owner.cfg.update_hz / self.rate),
                )
                while (
                    round(self.next_tick * self.rate / self.owner.cfg.update_hz)
                    <= cursor
                ):
                    self.next_tick += 1
                tick_sample = round(
                    self.next_tick * self.rate / self.owner.cfg.update_hz
                )
            stop = min(end, tick_sample)
            for source_id, stream in self.streams.items():
                stream.append(
                    cursor,
                    emissions[source_id][cursor - start : stop - start],
                    self.routes[source_id],
                )
            cursor = stop
        output = np.zeros((len(receivers), count), np.float32)
        for source in scene.sources:
            trajectory = self.trajectories[source.source_id]

            def gain(
                mic, emission, reception, points, source=source, trajectory=trajectory
            ):
                value = polar_gain(
                    source.directivity,
                    trajectory.orientation_at(emission),
                    points[:, 1] - points[:, 0],
                )
                microphone = array.microphones[mic]
                local_axis = rotate_vector_by_quaternion(
                    (1.0, 0.0, 0.0),
                    microphone.relative_orientation_quat or (0.0, 0.0, 0.0, 1.0),
                )
                axis = rotate_vectors(local_axis, self.array.orientation_at(reception))
                direction = points[:, -2] - points[:, -1]
                cosine = np.sum(axis * direction, axis=-1) / np.linalg.norm(
                    direction, axis=-1
                )
                coefficient = pattern_coefficient(microphone.directivity)
                return value * (
                    coefficient + (1 - coefficient) * np.clip(cosine, -1, 1)
                )

            output += self.streams[source.source_id].read(
                count, trajectory, receivers, self.owner.history, self.speed, gain
            )
        before = (end - 1) / self.rate - self.config.max_delay_s
        for trajectory in [self.array, *self.trajectories.values()]:
            trajectory.prune(before)
        return output

    def close(self):
        for stream in self.streams.values():
            stream.reset()
        self.renderer.close()
