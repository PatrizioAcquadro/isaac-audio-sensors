"""Persistent surface pressure candidate; admission is separate from construction.

Native PRA owns ray flights, band transport and visibility. Surface modes own
random pressure, independently of the source identifier and receiver grouping.
"""

import hashlib
import math
from dataclasses import dataclass, replace

import numpy as np

from ._pra import Transport
from ._specular import native, polar, polygons
from .geometry import triangulate


@dataclass(frozen=True, slots=True)
class PRADiffuseConfig:
    seed: int = 0
    rays: int = 16384
    surface_spacing_m: float = 0.25
    tail_spacing_m: float = 1.0
    time_bin_s: float = 0.004
    direction_modes: int = 64
    specular_concentration: float = 64.0
    max_events: int = 8_000_000
    max_nodes: int = 100_000

    def __post_init__(self):
        for name in ("rays", "direction_modes", "max_events", "max_nodes"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise ValueError("seed must be an unsigned 64-bit integer.")
        for name in (
            "surface_spacing_m",
            "tail_spacing_m",
            "time_bin_s",
            "specular_concentration",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive.")


def directions(count):
    z = 1 - 2 * (np.arange(count) + 0.5) / count
    phi = np.arange(count) * np.pi * (3 - np.sqrt(5))
    rho = np.sqrt(1 - z * z)
    return np.c_[rho * np.cos(phi), rho * np.sin(phi), z]


def signs(keys, seed, band):
    value = np.full(len(keys), np.uint64(seed) ^ np.uint64(band + 1), np.uint64)
    for column in np.asarray(keys, np.int64).T:
        value ^= column.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
        value ^= value >> 30
        value *= np.uint64(0xBF58476D1CE4E5B9)
        value ^= value >> 27
        value *= np.uint64(0x94D049BB133111EB)
        value ^= value >> 31
    return 2 * (value & 1).astype(float) - 1


def surface_nodes(points, spacing, max_nodes):
    """Triangle centroids form persistent local elements, including concave faces."""
    triangles, _ = triangulate(points, [len(points)], range(len(points)))
    result, areas = [], []
    for a, b, c in points[triangles]:
        count = max(
            1,
            math.ceil(
                max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))
                / spacing
            ),
        )
        if len(result) + count**2 > max_nodes:
            raise ValueError("PRA persistent surface node budget exceeded.")
        area = np.linalg.norm(np.cross(b - a, c - a)) / (2 * count**2)
        for i in range(count):
            for j in range(count - i):
                result.append(
                    a + (i + 1 / 3) / count * (b - a) + (j + 1 / 3) / count * (c - a)
                )
                areas.append(area)
                if i + j < count - 1:
                    result.append(
                        a
                        + (i + 2 / 3) / count * (b - a)
                        + (j + 2 / 3) / count * (c - a)
                    )
                    areas.append(area)
    return np.asarray(result), np.asarray(areas)


class SurfaceField:
    def __init__(self, specular, config, horizon):
        from scipy.spatial import cKDTree

        self.tree_type = cKDTree
        self.scene, self.config, self.horizon = specular, config, horizon
        self.transport = Transport(specular)
        self.axes = directions(config.direction_modes)
        self.angular_tree = cKDTree(self.axes)
        self.surfaces = {}
        self.signature = None
        self.cache = None
        self.diagnostics = {}

    def refresh(self):
        self.scene.refresh()
        if self.scene.signature == self.signature:
            return
        surfaces, active = [], {}
        for obj in self.scene.session.objects.values():
            local = replace(obj, transform=np.eye(4))
            for index, (points, material) in enumerate(polygons(local)):
                key = obj.path, index
                shape = points.tobytes()
                previous = self.surfaces.get(key)
                if previous is None or previous["shape"] != shape:
                    # Spacing is measured in metres at creation; subsequent rigid
                    # motion changes positions, never the element identity.
                    scale = np.linalg.svd(obj.transform[:3, :3], compute_uv=False)[0]
                    nodes, _ = surface_nodes(
                        points,
                        self.config.tail_spacing_m / scale,
                        self.config.max_nodes - sum(len(s["local"]) for s in surfaces),
                    )
                    first_nodes, first_areas = surface_nodes(
                        points,
                        self.config.surface_spacing_m / scale,
                        self.config.max_nodes
                        - len(nodes)
                        - sum(
                            len(s["local"]) + len(s["first_local"]) for s in surfaces
                        ),
                    )
                    token = (
                        int.from_bytes(
                            hashlib.blake2b(
                                f"{obj.path}:{index}".encode(), digest_size=8
                            ).digest(),
                            "little",
                        )
                        >> 1
                    )
                    reference = np.eye(4)
                else:
                    nodes, token, reference, first_nodes, first_areas = (
                        previous[n]
                        for n in (
                            "local",
                            "token",
                            "reference",
                            "first_local",
                            "first_areas",
                        )
                    )
                world = (np.c_[nodes, np.ones(len(nodes))] @ obj.transform)[:, :3]
                polygon = (np.c_[points, np.ones(len(points))] @ obj.transform)[:, :3]
                normal = np.cross(polygon[1] - polygon[0], polygon[2] - polygon[0])
                normal /= np.linalg.norm(normal)
                area_scale = np.linalg.norm(
                    np.cross(
                        (points[1] - points[0]) @ obj.transform[:3, :3],
                        (points[2] - points[0]) @ obj.transform[:3, :3],
                    )
                ) / np.linalg.norm(
                    np.cross(points[1] - points[0], points[2] - points[0])
                )
                row = dict(
                    shape=shape,
                    local=nodes,
                    world=world,
                    normal=normal,
                    tree=self.tree_type(world),
                    material=material,
                    token=token,
                    reference=reference,
                    transform=obj.transform.copy(),
                    first_local=first_nodes,
                    first_areas=first_areas,
                    first_world=(
                        np.c_[first_nodes, np.ones(len(first_nodes))] @ obj.transform
                    )[:, :3],
                    first_world_areas=first_areas * area_scale,
                )
                active[key] = row
                surfaces.append(row)
        if (
            sum(len(s["world"]) + len(s["first_world"]) for s in surfaces)
            > self.config.max_nodes
        ):
            raise ValueError("PRA persistent surface node budget exceeded.")
        self.surfaces, self.ordered = active, surfaces
        self.signature = self.scene.signature
        self.cache = None

    def project(self, source):
        self.refresh()
        origin = native(source.position_world).astype(float)
        signature = (
            tuple(origin),
            source.directivity,
            None
            if source.orientation_world_quat is None
            else tuple(source.orientation_world_quat),
        )
        if self.cache is not None and signature == self.cache[0]:
            return self.cache[1]
        if not self.scene.handle:
            return []
        events, energy = self.transport.trace(
            origin,
            rays=self.config.rays,
            horizon=self.horizon,
            seed=self.config.seed,
            limit=self.config.max_events,
        )
        energy = energy.astype(float)
        energy *= (
            polar(
                source.directivity, source.orientation_world_quat, events["departure"]
            )[:, None]
            ** 2
        )
        parent = events["parent"]
        previous = np.broadcast_to(origin, events["position"].shape).copy()
        previous[parent >= 0] = events["position"][parent[parent >= 0]]
        previous_surface = np.full(len(events), -1, np.int32)
        previous_surface[parent >= 0] = events["surface"][parent[parent >= 0]]
        # First-order path-length change under object displacement. Its role is
        # mode persistence, not replacement of the native geometric delay.
        displacement = np.zeros((len(events), 3))
        for i, surface in enumerate(self.ordered):
            mask = events["surface"] // 2 == i
            transform = np.linalg.inv(surface["transform"]) @ surface["reference"]
            before = (np.c_[events["position"][mask], np.ones(mask.sum())] @ transform)[
                :, :3
            ]
            displacement[mask] = events["position"][mask] - before
        # Accumulate only prior interactions: moving the final surface is handled
        # by its actual receiver distance below.
        cumulative = np.zeros(len(events))
        for bounce in range(1, int(events["bounce"].max(initial=0)) + 1):
            mask = events["bounce"] == bounce
            p = parent[mask]
            cumulative[mask] = cumulative[p] + np.sum(
                displacement[p] * (events["incoming"][p] - events["incoming"][mask]),
                axis=1,
            )
        cumulative += np.sum(displacement * events["incoming"], axis=1)
        fields = self._first_scatter(source, origin)
        totals = np.zeros((2, len(self.scene.bands.centers)))
        totals[0] = sum(
            (f["energy"].sum(axis=0) for f in fields), start=np.zeros(totals.shape[1])
        )
        rejected = np.zeros_like(totals)
        for i, surface in enumerate(self.ordered):
            mask = events["surface"] // 2 == i
            if not mask.any():
                continue
            e, power, prev = events[mask], energy[mask], previous[mask]
            scatter = np.asarray(
                surface["material"].scattering.at(tuple(self.scene.bands.centers))
            )
            specular = (e["diffuse_bounces"] > 0) | (e["bounce"] + 1 > self.scene.order)
            for family, amount in (
                (0, power * scatter * (e["bounce"] > 0)[:, None]),
                (1, power * (1 - scatter) * specular[:, None]),
            ):
                if not np.any(amount):
                    continue
                totals[family] += amount.sum(axis=0)
                valid = amount.sum(axis=1) > 0
                field, lost = self._project_surface(
                    surface,
                    e[valid],
                    amount[valid],
                    prev[valid],
                    previous_surface[mask][valid],
                    origin,
                    cumulative[mask][valid],
                    family,
                )
                rejected[family] += lost
                fields.extend(field)
        self.diagnostics = dict(
            events=len(events),
            nodes=sum(len(s["world"]) for s in self.ordered),
            first_scatter_nodes=sum(len(s["first_world"]) for s in self.ordered),
            modes=sum(len(f["keys"]) for f in fields),
            surface_spacing_m=self.config.surface_spacing_m,
            tail_spacing_m=self.config.tail_spacing_m,
            emitted_surface_energy=totals.tolist(),
            unprojected_surface_energy=rejected.tolist(),
        )
        self.cache = signature, fields
        return fields

    def _first_scatter(self, source, origin):
        fields = []
        for i, surface in enumerate(self.ordered):
            points = surface["first_world"]
            power = self.transport.illuminate(
                origin,
                np.full(len(points), 2 * i, np.int32),
                points,
                surface["first_world_areas"],
            ).astype(float)
            power *= (
                polar(
                    source.directivity, source.orientation_world_quat, points - origin
                )[:, None]
                ** 2
            )
            side = np.where((origin - points) @ surface["normal"] > 0, 1, -1)
            keep = power.sum(axis=1) > 0
            if not keep.any():
                continue
            keys = np.c_[
                np.flatnonzero(keep), side[keep], np.zeros((keep.sum(), 3), np.int64)
            ]
            fields.append(
                dict(
                    surface={**surface, "world": points},
                    keys=keys,
                    energy=power[keep],
                    lengths=np.linalg.norm(points[keep] - origin, axis=1),
                    family=2,
                    axes=self.axes,
                )
            )
        return fields

    def _project_surface(
        self,
        surface,
        events,
        energy,
        previous,
        previous_surface,
        origin,
        correction,
        family,
    ):
        count = min(4, len(surface["world"]))
        distance, neighbors = surface["tree"].query(events["position"], k=count)
        distance, neighbors = distance.reshape(-1, count), neighbors.reshape(-1, count)
        weights = 1 / np.maximum(distance, 1e-8) ** 2
        points = surface["world"][neighbors]
        weights *= self.transport.visible(previous[:, None], points)
        weights *= self.transport.visible(events["position"][:, None], points)
        weights *= self.transport.departure_visible(
            previous_surface[:, None], events["incoming"][:, None], points
        )
        # Project only onto the illuminated side. Native connection visibility
        # prevents interpolation across a partition or a closed door.
        side = np.where(
            np.sum(events["incoming"] * surface["normal"], axis=1) < 0, 1, -1
        )
        denom = weights.sum(axis=1, keepdims=True)
        lost = energy[denom[:, 0] == 0].sum(axis=0)
        weights /= np.maximum(denom, 1e-300)
        departure_distance, departure = self.angular_tree.query(
            events["departure"], k=min(3, len(self.axes))
        )
        departure = departure.reshape(len(events), -1)
        angle_weight = (
            1 / np.maximum(departure_distance.reshape(departure.shape), 1e-8) ** 2
        )
        angle_weight /= angle_weight.sum(axis=1, keepdims=True)
        outgoing = (
            events["incoming"]
            - 2
            * np.sum(events["incoming"] * surface["normal"], axis=1)[:, None]
            * surface["normal"]
        )
        # Native directions are represented in the object's persistent local frame.
        rotation = surface["transform"][:3, :3]
        u, _, vh = np.linalg.svd(rotation)
        local_axes = self.axes @ (u @ vh)
        outgoing_mode = (
            self.tree_type(local_axes).query(outgoing)[1]
            if family
            else np.zeros(len(events), int)
        )
        lengths = events["distance"][:, None] + np.sum(
            (points - events["position"][:, None]) * events["incoming"][:, None],
            axis=-1,
        )
        keys, values, travel = [], [], []
        for a in range(departure.shape[1]):
            gauge = self.axes[departure[:, a]] @ origin - correction
            delay = (lengths + gauge[:, None]) / (
                self.scene.speed * self.config.time_bin_s
            )
            slot = np.floor(delay).astype(np.int64)
            fraction = delay - slot
            for offset in (0, 1):
                weight = (
                    weights
                    * angle_weight[:, a, None]
                    * (fraction if offset else 1 - fraction)
                )
                keys.append(
                    np.stack(
                        (
                            neighbors,
                            np.broadcast_to(side[:, None], neighbors.shape),
                            slot + offset,
                            np.broadcast_to(departure[:, a, None], neighbors.shape),
                            np.broadcast_to(outgoing_mode[:, None], neighbors.shape),
                        ),
                        axis=-1,
                    ).reshape(-1, 5)
                )
                values.append(
                    (weight[..., None] * energy[:, None]).reshape(-1, energy.shape[1])
                )
                travel.append(
                    (
                        (slot + offset) * self.scene.speed * self.config.time_bin_s
                        - gauge[:, None]
                    ).ravel()
                )
        keys, values, travel = (
            np.concatenate(keys),
            np.concatenate(values),
            np.concatenate(travel),
        )
        unique, inverse = np.unique(keys, axis=0, return_inverse=True)
        total = np.column_stack(
            [np.bincount(inverse, weights=values[:, b]) for b in range(energy.shape[1])]
        )
        scalar = values.sum(axis=1)
        mean = np.bincount(inverse, weights=scalar * travel) / np.maximum(
            total.sum(axis=1), 1e-300
        )
        keep = (total.sum(axis=1) > 0) & (mean > 0)
        lost += total[mean <= 0].sum(axis=0)
        return [
            dict(
                surface=surface,
                keys=unique[keep],
                energy=total[keep],
                lengths=mean[keep],
                family=family,
                axes=local_axes,
            )
        ], lost

    def components(self, source, positions):
        """Return shared modal pressure coefficients before realization/filtering."""
        microphones = native(positions)
        for field in self.project(source):
            surface, keys = field["surface"], field["keys"]
            nodes = surface["world"]
            delta = microphones[:, None] - nodes[None]
            node_distance = np.linalg.norm(delta, axis=-1)
            if np.any(node_distance < 1e-5):
                raise ValueError("Microphone lies on a diffuse surface element.")
            node_direction = delta / node_distance[..., None]
            node_cosine = node_direction @ surface["normal"]
            node_visibility = self.transport.visible(nodes[None], microphones[:, None])
            if field["family"] == 1:
                axes = field["axes"]
                reflected = (
                    axes - 2 * (axes @ surface["normal"])[:, None] * surface["normal"]
                )
                k = self.config.specular_concentration
                node_density = (
                    k
                    / (2 * np.pi * (-np.expm1(-2 * k)))
                    * (
                        np.exp(k * (node_direction @ axes.T - 1))
                        + np.exp(k * (node_direction @ reflected.T - 1))
                    )
                )
            # Evaluate bounded chunks to avoid arrays proportional to all ray hits.
            for start in range(0, len(keys), 65536):
                sl = slice(start, start + 65536)
                key = keys[sl]
                points = surface["world"][key[:, 0]]
                distance = node_distance[:, key[:, 0]]
                direction = node_direction[:, key[:, 0]]
                cosine = node_cosine[:, key[:, 0]] * key[None, :, 1]
                visibility = (cosine > 0) & node_visibility[:, key[:, 0]]
                if field["family"] != 1:
                    density = np.maximum(cosine, 0) / np.pi
                else:
                    # Two mirrored vMF lobes integrate to one on the permitted
                    # hemisphere, including grazing directions. No gain fitting.
                    density = node_density[:, key[:, 0], key[:, 4]]
                gain = 2 * np.pi * density * visibility / distance**2 / (4 * np.pi) ** 2
                amplitude = np.sqrt(gain[..., None] * field["energy"][None, sl])
                departure = (
                    points - native(source.position_world)
                    if field["family"] == 2
                    else self.axes[key[:, 3]]
                )
                amplitude *= np.sign(
                    polar(
                        source.directivity,
                        source.orientation_world_quat,
                        departure,
                    )
                )[None, :, None]
                length = field["lengths"][None, sl] + distance
                ids = np.c_[
                    np.full(len(key), surface["token"], np.int64),
                    np.full(len(key), field["family"]),
                    key,
                ]
                yield ids, length, amplitude, -direction

    def impulses(self, source, array, positions):
        """Synthesize independent octave modes with analytical filter power weights."""
        from scipy.signal import fftconvolve

        from isaac_audio_sensors.core.directivity import microphone_world_orientation

        rate = self.scene.rate
        if not hasattr(self, "filters"):
            from pyroomacoustics.acoustics import magnitude_response_to_minimum_phase

            bank = self.scene.pra.acoustics.OctaveBandsFactory(fs=rate, keep_dc=True)
            magnitude = np.abs(np.fft.rfft(bank.filters, axis=0))
            # Independent band realizations require a partition of power.
            # PRA's ordinary synthesis windows instead partition amplitude.
            magnitude /= np.sqrt(np.sum(magnitude**2, axis=1, keepdims=True))
            self.filters = magnitude_response_to_minimum_phase(
                magnitude.T, bank.n_fft, axis=-1, eps=1e-7
            )
            self.filter_power = np.sum(self.filters**2, axis=1)
            # Energy of each fractional kernel convolved with each synthesis band.
            # This is numerical filter normalization, never a fitted room gain.
            fractions = np.linspace(0, 1, 257, dtype=np.float32)
            kernels = np.zeros((len(fractions), 81), np.float32)
            self.scene.pra.libroom.fractional_delay(kernels, fractions, 20, 1)
            combined = fftconvolve(kernels[:, None], self.filters[None], axes=-1)
            self.fraction_power = np.sum(combined**2, axis=-1)
        size = math.ceil(self.horizon * rate) + 81
        bands = np.zeros((len(array.microphones), len(self.filters), size), np.float32)
        expected = np.zeros((len(array.microphones), len(self.filters)))
        omitted = np.zeros_like(expected)
        orientations = [
            microphone_world_orientation(
                array.orientation_world_quat, mic.relative_orientation_quat
            )
            for mic in array.microphones
        ]
        for keys, lengths, amplitude, incoming in self.components(source, positions):
            physical = (lengths > 0) & (lengths <= self.horizon * self.scene.speed)
            for m, mic in enumerate(array.microphones):
                gain = polar(mic.directivity, orientations[m], incoming[m])
                power = amplitude[m] ** 2 * gain[:, None] ** 2
                omitted[m] += power[~physical[m]].sum(axis=0)
                keep = physical[m] & (power.sum(axis=1) > 0)
                if not keep.any():
                    continue
                d = lengths[m, keep] / self.scene.speed
                samples = d * rate
                fraction = samples - np.floor(samples)
                indices = np.minimum((fraction * 256).astype(int), 255)
                weight = fraction * 256 - indices
                kernel_power = (1 - weight[:, None]) * self.fraction_power[
                    indices
                ] + weight[:, None] * self.fraction_power[indices + 1]
                normalization = np.sqrt(self.filter_power / kernel_power)
                expected[m] += np.sum(power[keep], axis=0) * self.filter_power
                for b in range(len(self.filters)):
                    values = (
                        amplitude[m, keep, b]
                        * gain[keep]
                        * normalization[:, b]
                        * signs(keys[keep], self.config.seed, b)
                    )
                    self.scene.pra.libroom.rir_builder(
                        bands[m, b],
                        np.asarray(d + 40 / rate, np.float32),
                        np.asarray(values, np.float32),
                        rate,
                        81,
                        20,
                        1,
                    )
        result = []
        for microphone in bands:
            response = np.sum(fftconvolve(microphone, self.filters, axes=-1), axis=0)
            result.append(response[40:].astype(np.float32))
        self.diagnostics.update(
            filter_power=self.filter_power.tolist(),
            expected_rir_energy=expected.sum(axis=1).tolist(),
            excluded_arrival_energy=omitted.tolist(),
        )
        return result
