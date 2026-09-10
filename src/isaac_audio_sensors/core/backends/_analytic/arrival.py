"""Receiver-clock sampling of subsonic source trajectories."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from isaac_audio_sensors.core.backends._analytic.signals import (
    _scheduled_window_signal,
    convolve_emission,
)
from isaac_audio_sensors.core.directivity import pattern_coefficient
from isaac_audio_sensors.core.math_utils import rotate_vector_by_quaternion
from isaac_audio_sensors.core.motion.orientation import (
    interpolate_orientation,
    rotate_vectors,
)
from isaac_audio_sensors.core.types import AudioTimeWindow


@dataclass
class Trajectory:
    """Bounded timestamped positions, with explicit endpoint extrapolation."""

    times: list[float] = field(default_factory=list)
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    velocities: list[tuple[float, float, float]] = field(default_factory=list)

    orientations: list = field(default_factory=list)

    def observe(self, time, position, velocity, orientation=None):
        index = int(np.searchsorted(self.times, time))
        row = tuple(position)
        orientation = (
            tuple(orientation) if orientation is not None else (0.0, 0.0, 0.0, 1.0)
        )
        speed = tuple(velocity) if velocity is not None else (0.0, 0.0, 0.0)
        if velocity is None and index > 0 and time > self.times[index - 1]:
            speed = tuple(
                (np.asarray(row) - self.positions[index - 1])
                / (time - self.times[index - 1])
            )
        if index < len(self.times) and abs(self.times[index] - time) < 1e-9:
            self.positions[index] = row
            self.velocities[index] = speed
            self.orientations[index] = orientation
        else:
            self.times.insert(index, time)
            self.positions.insert(index, row)
            self.velocities.insert(index, speed)
            self.orientations.insert(index, orientation)

    def at(self, times):
        times = np.asarray(times, dtype=float)
        p = np.asarray(self.positions)
        values = np.stack(
            [np.interp(times, self.times, p[:, i]) for i in range(3)], axis=-1
        )
        before = times < self.times[0]
        after = times > self.times[-1]
        values[before] += (times[before] - self.times[0])[..., None] * self.velocities[
            0
        ]
        values[after] += (times[after] - self.times[-1])[..., None] * self.velocities[
            -1
        ]
        return values

    def orientation_at(self, times):
        """SLERP between poses; hold first, extrapolate last angular velocity."""
        times = np.asarray(times)
        if len(self.times) == 1:
            return np.broadcast_to(self.orientations[0], (*times.shape, 4))
        right = np.clip(np.searchsorted(self.times, times), 1, len(self.times) - 1)
        left = right - 1
        stamps = np.asarray(self.times)
        weight = np.maximum(0, (times - stamps[left]) / (stamps[right] - stamps[left]))
        poses = np.asarray(self.orientations)
        return interpolate_orientation(poses[left], poses[right], weight)

    def receiver_at(self, times, offset):
        return self.at(times) + rotate_vectors(offset, self.orientation_at(times))

    def prune(self, before):
        count = max(0, int(np.searchsorted(self.times, before)) - 1)
        del self.times[:count]
        del self.positions[:count]
        del self.velocities[:count]
        del self.orientations[:count]


def emission_samples(source, times, sample_rate):
    """Read the source clock, including real silence outside its schedule."""

    indices = np.asarray(times) * sample_rate
    first = max(0, int(np.floor(indices.min())))
    last = max(first + 1, int(np.ceil(indices.max())) + 1)
    window = AudioTimeWindow(
        start_time_s=first / sample_rate, end_time_s=last / sample_rate, frame_index=0
    )
    signal = _scheduled_window_signal(
        source, time_window=window, sample_rate_hz=sample_rate
    ).signal
    signal = np.pad(signal, (0, max(0, last - first - len(signal))))
    return np.interp(
        indices - first, np.arange(len(signal)), signal, left=0.0, right=0.0
    )


def retarded_path(
    times, receiver, trajectory, speed_of_sound, sample_rate, transform=None
):
    """Solve t_e + |receiver(t_r)-source(t_e)|/c = t_r."""

    def position(t):
        value = trajectory.at(t)
        return value if transform is None else transform(value)

    # For affine motion and image transforms the same arrival equation is quadratic.
    velocity = np.asarray(trajectory.velocities[0])
    linear = np.all(np.asarray(trajectory.velocities) == velocity) and np.allclose(
        np.asarray(trajectory.positions) - trajectory.positions[0],
        (np.asarray(trajectory.times) - trajectory.times[0])[:, None] * velocity,
        rtol=1e-12,
        atol=1e-12,
    )
    if linear:
        origin = position(np.array([trajectory.times[0]]))[0]
        velocity = position(np.array([trajectory.times[0] + 1]))[0] - origin
        offset = receiver - (origin + (times - trajectory.times[0])[:, None] * velocity)
        projection = offset @ velocity
        denominator = speed_of_sound**2 - velocity @ velocity
        if denominator <= 0:
            raise ValueError("Retarded propagation requires subsonic trajectories.")
        radius_squared = np.sum(offset * offset, axis=-1)
        root = np.sqrt(projection**2 + denominator * radius_squared)
        # Rationalize the negative-projection branch to avoid cancellation.
        delay = np.where(
            projection >= 0,
            (projection + root) / denominator,
            radius_squared / np.maximum(root - projection, 1e-30),
        )
        direction = offset + delay[:, None] * velocity
        distance = np.linalg.norm(direction, axis=-1)
        if np.any(distance <= 1e-9):
            raise ValueError(
                "analytic_acoustics requires distinct source and microphone positions."
            )
        return times - delay, distance, direction

    emission = np.asarray(times).copy()
    for _ in range(48):
        source_position = position(emission)
        distance = np.linalg.norm(receiver - source_position, axis=-1)
        updated = times - distance / speed_of_sound
        if np.max(np.abs(updated - emission)) < 1e-5 / sample_rate:
            emission = updated
            break
        emission = updated
    else:
        # Fixed-point iteration slows near c; the subsonic arrival equation is monotone.
        upper = np.asarray(times).copy()
        span = np.maximum(1.0 / sample_rate, 2 * distance / speed_of_sound)
        lower = upper - span
        for _ in range(64):
            residual = (
                lower
                + np.linalg.norm(receiver - position(lower), axis=-1) / speed_of_sound
                - times
            )
            if np.all(residual <= 0):
                break
            span *= 2
            lower = upper - span
        else:
            raise ValueError(
                "Retarded propagation requires a convergent subsonic trajectory."
            )
        for _ in range(64):
            emission = (lower + upper) / 2
            residual = (
                emission
                + np.linalg.norm(receiver - position(emission), axis=-1)
                / speed_of_sound
                - times
            )
            lower = np.where(residual <= 0, emission, lower)
            upper = np.where(residual > 0, emission, upper)
            if np.max(upper - lower) < 1e-5 / sample_rate:
                break
    direction = receiver - position(emission)
    distance = np.linalg.norm(direction, axis=-1)
    if np.any(distance <= 1e-9):
        raise ValueError(
            "analytic_acoustics requires distinct source and microphone positions."
        )
    return emission, distance, direction


def polar_gain(pattern, orientation, directions):
    coefficient = pattern_coefficient(pattern)
    if coefficient == 1.0:
        return np.ones(len(directions))
    if orientation is None:
        raise ValueError("Non-omni directivity requires an orientation.")
    axis = rotate_vectors((1.0, 0.0, 0.0), orientation)
    cosine = np.sum(directions * axis, axis=-1) / np.linalg.norm(directions, axis=-1)
    return coefficient + (1 - coefficient) * np.clip(cosine, -1, 1)


@dataclass
class ArrivalStream:
    """Motion history belongs to one producer stream, never to the recorder."""

    trajectories: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    rooms: dict = field(default_factory=dict)
    last_start: float | None = None
    last_end: float | None = None
    tail_duration_s: float = 0.0
    signature: object = None

    def prepare(self, scene, array, window, plan, speed_of_sound):
        from dataclasses import replace

        signature = (scene.environment, array.sample_rate_hz, array.microphones)
        restarted = (
            (self.signature is not None and self.signature != signature)
            or (
                self.last_start is not None
                and window.start_time_s < self.last_start - 1e-9
            )
            or (
                self.last_end is not None
                and window.start_time_s > self.last_end + 0.5 / array.sample_rate_hz
            )
        )
        if restarted:
            self.trajectories.clear()
            self.sources.clear()
            self.rooms.clear()
        self.last_end = window.end_time_s
        self.signature = signature
        self.last_start = window.start_time_s
        present = {s.source_id for s in scene.sources}
        for key, source in list(self.sources.items()):
            if key not in present and (
                source.duration_s is None
                or source.start_time_s + source.duration_s > window.start_time_s
            ):
                duration = window.start_time_s - source.start_time_s
                if duration <= 0:
                    del self.sources[key]
                else:
                    self.sources[key] = replace(source, duration_s=duration)
        self.sources.update({s.source_id: s for s in scene.sources})
        entities = [(("source", s.source_id), s) for s in scene.sources]
        entities.append((("array", array.array_id), array))
        for key, entity in entities:
            trajectory = self.trajectories.setdefault(key, Trajectory())
            entity_id = key[1]
            if plan is not None:
                for segment in plan.segments:
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
            else:
                trajectory.observe(
                    window.start_time_s,
                    entity.position_world,
                    entity.velocity_world_mps,
                    entity.orientation_world_quat,
                )
        farthest = max(
            (
                np.linalg.norm(np.asarray(s.position_world) - array.position_world)
                for s in self.sources.values()
            ),
            default=0.0,
        )
        speeds = [
            np.linalg.norm(v)
            for tr in self.trajectories.values()
            for v in tr.velocities
        ]
        for trajectory in self.trajectories.values():
            if len(trajectory.times) > 1:
                speeds.extend(
                    np.linalg.norm(np.diff(trajectory.positions, axis=0), axis=1)
                    / np.diff(trajectory.times)
                )
        maximum_speed = max(speeds, default=0.0)
        if maximum_speed >= speed_of_sound:
            raise ValueError(
                "Retarded propagation supports only subsonic trajectories."
            )
        horizon = max(
            1.0, self.tail_duration_s + 2 * farthest / (speed_of_sound - maximum_speed)
        )
        for trajectory in self.trajectories.values():
            trajectory.prune(window.start_time_s - horizon)
        # A removed emitter keeps its last motion until its arrivals have drained.
        for key, source in list(self.sources.items()):
            if (
                key not in present
                and source.duration_s is not None
                and (
                    source.start_time_s + source.duration_s
                    < window.start_time_s - horizon
                )
            ):
                del self.sources[key]
                self.trajectories.pop(("source", key), None)
        return replace(scene, sources=tuple(self.sources.values())), bool(restarted)


def moving_pair(trajectories, source_id, array_id):
    return any(
        any(np.linalg.norm(v) > 0 for v in trajectory.velocities)
        or len(set(trajectory.positions)) > 1
        or any(
            abs(np.dot(trajectory.orientations[0], q)) < 1 - 1e-12
            for q in trajectory.orientations[1:]
        )
        for trajectory in (
            trajectories[("source", source_id)],
            trajectories[("array", array_id)],
        )
    )


def image_transforms(room, provider_source):
    """Reuse provider image identities; reflect the actual emission trajectory."""

    images = provider_source.images.T
    if np.shape(getattr(provider_source, "orders_xyz", None)) == (3, len(images)):
        matrices = (
            np.eye(3)[None, :, :] * ((-1.0) ** provider_source.orders_xyz.T)[:, :, None]
        )
    else:
        matrices = np.zeros((len(images), 3, 3))
        for index in np.argsort(provider_source.orders):
            wall_index = int(provider_source.walls[index])
            if wall_index < 0:
                matrices[index] = np.eye(3)
            else:
                wall = room.walls[wall_index]
                normal = np.asarray(wall.normal, dtype=float)
                normal /= np.linalg.norm(normal)
                # PyRoom 0.10 leaves deprecated `generators` at -1. Recover the
                # parent from its image coordinates and generating wall.
                image = images[index]
                corner = np.asarray(wall.corners[:, 0])
                parent_position = image - 2 * np.dot(image - corner, normal) * normal
                candidates = np.flatnonzero(
                    provider_source.orders == provider_source.orders[index] - 1
                )
                distances = np.linalg.norm(images[candidates] - parent_position, axis=1)
                if not len(distances) or distances.min() > 1e-4 * max(
                    1.0, np.linalg.norm(image)
                ):
                    raise ValueError(
                        "Moving polygon paths require visible parent images "
                        "from PyRoom."
                    )
                parent = candidates[np.argmin(distances)]
                matrices[index] = (np.eye(3) - 2 * np.outer(normal, normal)) @ matrices[
                    parent
                ]
    offsets = images - np.einsum("nij,j->ni", matrices, provider_source.position)
    return matrices, offsets


def moving_room_premix(room, sources, sensor, environment, window, trajectories, c):
    """Retarded image-source paths; visibility/materials use the current room solve."""

    import pyroomacoustics as pra

    fs = sensor.sample_rate_hz
    n = max(1, round((window.end_time_s - window.start_time_s) * fs))
    guard = room.octave_bands.n_fft
    times = (round(window.start_time_s * fs) + np.arange(-guard, n + guard)) / fs
    # Match the provider's documented fractional-delay-filter latency.
    times -= pra.constants.get("frac_delay_length") // 2 / fs
    rotation = np.column_stack(
        [
            rotate_vector_by_quaternion(
                tuple(v), environment.world_pose.orientation_xyzw
            )
            for v in np.eye(3)
        ]
    )
    origin = np.asarray(environment.world_pose.position_m)
    output = np.zeros((len(sources), len(sensor.microphones), n))
    for si, source in enumerate(sources):
        provider_source = room.sources[si]
        moving = moving_pair(trajectories, source.source_id, sensor.array_id)
        if moving:
            matrices, offsets = image_transforms(room, provider_source)
        trajectory = trajectories[("source", source.source_id)]
        for mi, microphone in enumerate(sensor.microphones):
            array_trajectory = trajectories[("array", sensor.array_id)]
            receiver = array_trajectory.receiver_at(
                times, microphone.relative_position_m
            )
            emission, _, direct_direction = retarded_path(
                times, receiver, trajectory, c, fs
            )
            direct_gain = pair_gain(
                source,
                microphone,
                trajectory,
                array_trajectory,
                emission,
                times,
                direct_direction,
            )
            if not moving:
                output[si, mi] = (
                    convolve_emission(source, room.rir[mi][si], window, fs)
                    * direct_gain[guard : guard + n]
                )
                continue
            for image_index in np.flatnonzero(room.visibility[si][mi]):
                matrix, offset = matrices[image_index], offsets[image_index]

                def transform(points, matrix=matrix, offset=offset):
                    local = (points - origin) @ rotation
                    return (local @ matrix.T + offset) @ rotation.T + origin

                emission, distance, _ = retarded_path(
                    times, receiver, trajectory, c, fs, transform
                )
                signal = emission_samples(source, emission, fs) / distance
                amplitudes = provider_source.damping[:, image_index]
                if getattr(room, "air_absorption", None) is not None:
                    coefficients = np.asarray(room.air_absorption)
                    amplitudes = amplitudes[:, None] * np.exp(
                        -0.5 * coefficients[:, None] * distance
                    )
                if np.ndim(amplitudes) == 1 and len(amplitudes) == 1:
                    filtered = signal * amplitudes[0]
                else:
                    bands = room.octave_bands.analysis(signal)
                    filtered = np.sum(bands * np.asarray(amplitudes).T, axis=-1)
                path_gain = pair_gain(
                    source,
                    microphone,
                    trajectory,
                    array_trajectory,
                    emission,
                    times,
                    receiver - trajectory.at(emission),
                )
                output[si, mi] += (filtered * path_gain)[guard : guard + n]
            if room.simulator_state["rt_needed"]:
                from pyroomacoustics.simulation.ism import compute_ism_rir

                stationary = compute_ism_rir(
                    provider_source,
                    room.mic_array.R[:, mi],
                    None,
                    provider_source.directions[mi],
                    room.visibility[si][mi],
                    pra.constants.get("frac_delay_length"),
                    c,
                    fs,
                    room.octave_bands,
                    min_phase=room.min_phase,
                    air_abs_coeffs=room.air_absorption,
                )
                full = room.rir[mi][si]
                size = max(len(full), len(stationary))
                residual = np.pad(full, (0, size - len(full))) - np.pad(
                    stationary, (0, size - len(stationary))
                )
                output[si, mi] += (
                    convolve_emission(source, residual, window, fs)
                    * direct_gain[guard : guard + n]
                )
    return output


def pair_gain(
    source,
    microphone,
    source_trajectory,
    array_trajectory,
    emission,
    reception,
    directions,
):
    """Direct-path polar gains on their respective acoustic clocks."""
    source_gain = np.ones(len(emission))
    if pattern_coefficient(source.directivity) != 1.0:
        source_gain = polar_gain(
            source.directivity, source_trajectory.orientation_at(emission), directions
        )
    coefficient = pattern_coefficient(microphone.directivity)
    if coefficient == 1.0:
        return source_gain
    local_axis = rotate_vectors(
        (1.0, 0.0, 0.0), microphone.relative_orientation_quat or (0.0, 0.0, 0.0, 1.0)
    )
    axis = rotate_vectors(local_axis, array_trajectory.orientation_at(reception))
    cosine = np.sum(-directions * axis, axis=-1) / np.linalg.norm(directions, axis=-1)
    return source_gain * (coefficient + (1 - coefficient) * np.clip(cosine, -1, 1))
