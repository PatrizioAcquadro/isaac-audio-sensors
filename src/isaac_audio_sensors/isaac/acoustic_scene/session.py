"""USD-authoritative preparation and selective scene refresh."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .geometry import extract
from .materials import DEFAULT_ASSOCIATIONS, AcousticMaterial, attribute, resolve

INCLUDE = "ias:acoustic_enabled"
DYNAMIC = "ias:acoustic_dynamic"
PARTITION = "ias:acoustic_partition_id"
REPRESENTATION = "ias:acoustic_geometry"
SETTINGS = "/IASAcousticScene"


@dataclass
class AcousticObject:
    path: str
    partition: str
    points: np.ndarray
    triangles: np.ndarray
    face_indices: np.ndarray
    transform: np.ndarray
    materials: tuple[AcousticMaterial, ...]
    material_indices: np.ndarray
    dynamic: bool
    planar: bool = False
    revision: int = 0
    dependencies: tuple[str, ...] = ()

    @property
    def world_points(self):
        return (
            np.column_stack((self.points, np.ones(len(self.points)))) @ self.transform
        )[:, :3]


class AcousticSceneSession:
    """Prepare a composed stage; edits are persisted in its current edit target."""

    def __init__(self, stage, roots=None):
        from pxr import Tf, Usd

        if not isinstance(stage, Usd.Stage):
            raise ValueError("Acoustic preparation requires a USD stage")
        self.stage = stage
        self.roots = tuple(roots or ("/",))
        if any(not p.startswith("/") for p in self.roots):
            raise ValueError("Acoustic roots must be absolute USD paths")
        self.objects: dict[str, AcousticObject] = {}
        self.excluded: dict[str, str] = {}
        self.issues: list[str] = []
        self.warnings: list[str] = []
        self.containment: dict[str, Any] = {}
        self.geometry_builds = 0
        self.transform_updates = 0
        self.provider = None
        self.closed = False
        self._prepared = False
        self._dirty: set[str] = set()
        self._structural = True
        self._prims = []
        self._last_time = None
        self._partition_cache = {}
        self._listener = Tf.Notice.Register(
            Usd.Notice.ObjectsChanged, self._changed, stage
        )

    def _changed(self, notice, sender):
        paths = tuple(notice.GetResyncedPaths())
        self._structural |= bool(paths)
        self._dirty.update(str(p) for p in paths)
        self._dirty.update(str(p) for p in notice.GetChangedInfoOnlyPaths())
        if self.provider:
            self.provider.verified = False

    def _in_roots(self, path):
        return any(
            root == "/" or path == root or path.startswith(root.rstrip("/") + "/")
            for root in self.roots
        )

    @staticmethod
    def _inherited(prim, name, time):
        while prim and not prim.IsPseudoRoot():
            value = attribute(prim, name, time)
            if value is not None:
                return value
            prim = prim.GetParent()
        return None

    def refresh(self, time=None):
        from pxr import Usd, UsdGeom, UsdShade

        if self.closed:
            raise RuntimeError("Acoustic scene session is closed")
        time = Usd.TimeCode.Default() if time is None else Usd.TimeCode(time)
        self.issues, self.warnings, self.excluded = [], [], {}
        settings = self.stage.GetPrimAtPath(SETTINGS)
        associations = dict(DEFAULT_ASSOCIATIONS)
        fallback_id, fallback_scattering = "pra.hard_surface", 0.05
        if settings:
            mapping = attribute(settings, "ias:material_associations", time)
            if mapping is not None:
                import json

                associations = json.loads(mapping)
                if not isinstance(associations, dict):
                    raise ValueError("Material associations must be an object")
            fallback_id = (
                attribute(settings, "ias:fallback_material", time) or fallback_id
            )
            value = attribute(settings, "ias:fallback_scattering", time)
            if value is not None:
                fallback_scattering = float(value)
                if not np.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Fallback scattering must be in [0, 1]")
        if self._structural:
            self._prims = list(
                Usd.PrimRange.Stage(self.stage, Usd.TraverseInstanceProxies())
            )
        xforms = UsdGeom.XformCache(time)
        unit = UsdGeom.GetStageMetersPerUnit(self.stage)
        conversion = np.eye(4)
        conversion[:3, :3] *= unit
        if UsdGeom.GetStageUpAxis(self.stage) == "Z":
            conversion[:3, :3] = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]) * unit
        replacements = {}
        for prim in self._prims:
            rel = prim.GetRelationship(REPRESENTATION)
            if rel and rel.GetTargets() and self._in_roots(str(prim.GetPath())):
                targets = tuple(map(str, rel.GetTargets()))
                if any(not self.stage.GetPrimAtPath(p) for p in targets):
                    self.issues.append(
                        f"{prim.GetPath()}: missing acoustic representation"
                    )
                replacements[str(prim.GetPath())] = targets
        active = {}
        for prim in self._prims:
            path = str(prim.GetPath())
            explicit_target = any(
                path == target or path.startswith(target + "/")
                for targets in replacements.values()
                for target in targets
            )
            if not self._in_roots(path) and not explicit_target:
                continue
            if not prim.IsLoaded():
                self.issues.append(f"{path}: unloaded payload")
            if not prim.IsA(UsdGeom.Gprim):
                continue
            reason = self._exclude(prim, replacements, time)
            if reason:
                self.excluded[path] = reason
                continue
            try:
                if any("Deformable" in str(s) for s in prim.GetAppliedSchemas()):
                    raise ValueError(
                        "Deformable geometry requires an acoustic representation"
                    )
                if any(
                    a.ValueMightBeTimeVarying()
                    for a in prim.GetAttributes()
                    if a.GetName()
                    in ("points", "faceVertexIndices", "faceVertexCounts")
                ):
                    raise ValueError("Deforming/time-varying topology is unsupported")
                old = self.objects.get(path)
                animated = self._last_time != time and any(
                    a.ValueMightBeTimeVarying()
                    for a in prim.GetAttributes()
                    if not a.GetName().startswith("xformOp")
                )
                changed = (
                    old is None
                    or animated
                    or any(
                        (
                            self._affects(path, p)
                            or (
                                old
                                and any(self._affects(d, p) for d in old.dependencies)
                            )
                        )
                        for p in self._dirty
                        if not p.rsplit(".", 1)[-1].startswith("xformOp")
                    )
                )
                transform = self._world_transform(prim, xforms) @ conversion
                if (
                    not np.isfinite(transform).all()
                    or abs(np.linalg.det(transform[:3, :3])) < 1e-15
                ):
                    raise ValueError("Invalid or singular world transform")
                dynamic = self._dynamic(prim, time)
                if changed:
                    geometry_changed = (
                        old is None
                        or animated
                        or any(
                            self._affects(path, p)
                            and (
                                "." not in p
                                or p.rsplit(".", 1)[-1]
                                in (
                                    "points",
                                    "faceVertexIndices",
                                    "faceVertexCounts",
                                    "holeIndices",
                                    "orientation",
                                    "size",
                                    "radius",
                                    "height",
                                    "axis",
                                    "subdivisionScheme",
                                )
                            )
                            for p in self._dirty
                        )
                    )
                    if geometry_changed:
                        points, triangles, faces = extract(prim, time)
                        self.geometry_builds += 1
                    else:
                        points, triangles, faces = (
                            old.points,
                            old.triangles,
                            old.face_indices,
                        )
                    if (
                        not len(triangles)
                        or points.ndim != 2
                        or points.shape[1] != 3
                        or not np.isfinite(points).all()
                    ):
                        raise ValueError("Empty or invalid acoustic geometry")
                    material, _ = UsdShade.MaterialBindingAPI(
                        prim
                    ).ComputeBoundMaterial()
                    bound = material.GetPrim() if material else None
                    kwargs = dict(
                        time=time,
                        associations=associations,
                        fallback_id=fallback_id,
                        fallback_scattering=fallback_scattering,
                    )
                    dependencies = [str(bound.GetPath())] if bound else []
                    materials = [resolve(prim, bound, **kwargs)]
                    material_indices = np.zeros(len(triangles), dtype=np.int32)
                    assigned = set()
                    for subset in UsdShade.MaterialBindingAPI(
                        prim
                    ).GetMaterialBindSubsets():
                        indices = set(subset.GetIndicesAttr().Get(time) or ())
                        if any(
                            i < 0
                            or i
                            >= len(
                                UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get(time)
                            )
                            for i in indices
                        ):
                            raise ValueError("Material subset refers to a missing face")
                        if assigned & indices:
                            raise ValueError("Overlapping material subsets")
                        assigned |= indices
                        material, _ = UsdShade.MaterialBindingAPI(
                            subset.GetPrim()
                        ).ComputeBoundMaterial()
                        if material:
                            dependencies.append(str(material.GetPath()))
                        materials.append(
                            resolve(
                                prim,
                                material.GetPrim() if material else bound,
                                **kwargs,
                            )
                        )
                        material_indices[np.isin(faces, list(indices))] = (
                            len(materials) - 1
                        )
                    partition = self._inherited(prim, PARTITION, time)
                    if partition is not None and not str(partition).strip():
                        raise ValueError("Acoustic partition ID must be nonempty")
                    partition = partition or self._object_owner(prim)
                    obj = AcousticObject(
                        path,
                        str(partition),
                        points,
                        triangles,
                        faces,
                        transform,
                        tuple(materials),
                        material_indices,
                        dynamic,
                        revision=0
                        if old is None
                        else old.revision + int(geometry_changed),
                        dependencies=tuple(dependencies),
                    )
                else:
                    obj = old
                    if not np.allclose(obj.transform, transform, rtol=0, atol=1e-10):
                        obj.transform = transform
                        obj.dynamic = (
                            True  # Unexpected rigid edits become selectively movable.
                        )
                        self.transform_updates += 1
                    obj.dynamic |= dynamic
                active[path] = obj
            except (ValueError, TypeError, RuntimeError) as exc:
                self.issues.append(f"{path}: {exc}")
        self.objects = active
        if not active:
            self.issues.append("No usable acoustic geometry in the selected roots")
        self._qualify_partitions()
        for error in self.stage.GetCompositionErrors():
            self.issues.append(f"USD composition: {error}")
        from isaac_audio_sensors.isaac.discovery import (
            IsaacAudioDiscoveryCfg,
            discover_stage_audio,
        )

        try:
            discovery = discover_stage_audio(
                self.stage,
                cfg=IsaacAudioDiscoveryCfg(
                    discovery_roots=tuple(
                        str(p.GetPath())
                        for p in self.stage.GetPseudoRoot().GetChildren()
                    )
                    if self.roots == ("/",)
                    else self.roots
                ),
                time_code=time,
                prims=tuple(self._prims),
            )
            self.resolve_containment(
                [array.spec for array in discovery.arrays], time=time
            )
        except ValueError as exc:
            self.containment = {"state": "unknown", "reason": str(exc)}
        self._prepared = True
        self._last_time = time
        self._dirty.clear()
        self._structural = False
        if self.provider:
            self.provider.sync(self.objects, valid=not self.issues)
        return self.summary()

    @staticmethod
    def _affects(path, changed):
        owner = changed.split(".")[0]
        return (
            owner in (SETTINGS, path)
            or path.startswith(owner + "/")
            or owner.startswith(path + "/")
        )

    def _exclude(self, prim, replacements, time):
        from pxr import UsdGeom

        path = str(prim.GetPath())
        enabled = self._inherited(prim, INCLUDE, time)
        if enabled is False:
            return "explicit exclusion"
        if enabled is True or any(
            path == target or path.startswith(target + "/")
            for targets in replacements.values()
            for target in targets
        ):
            return None
        if any(
            part.lower()
            in (
                "debug",
                "__debug",
                "iasdebug",
                "audiodebug",
                "iasaudiodebug",
                "visualizations",
            )
            for part in path.split("/")
        ):
            return "technical visualization"
        if UsdGeom.Imageable(prim).ComputePurpose() == "guide":
            return "technical guide"
        for owner, targets in replacements.items():
            if (path == owner or path.startswith(owner + "/")) and not any(
                path == t or path.startswith(t + "/") for t in targets
            ):
                return "replaced by explicit acoustic geometry"
        if "collision" in path.lower().split("/") or "collisions" in path.lower().split(
            "/"
        ):
            parent = prim.GetParent()
            while parent and parent.GetName().lower() not in (
                "collision",
                "collisions",
            ):
                parent = parent.GetParent()
            if parent:
                siblings = parent.GetParent().GetChildren()
                if any(
                    p.GetName().lower() in ("visual", "visuals", "geometry", "render")
                    for p in siblings
                ):
                    return "collision duplicate of visual representation"
        if UsdGeom.Imageable(prim).ComputeVisibility(time) == "invisible":
            return "invisible geometry (override inclusion to use an acoustic proxy)"
        return None

    @staticmethod
    def _object_owner(prim):
        current = prim
        while current and not current.IsPseudoRoot():
            if current.IsModel() and current.GetMetadata("kind") in (
                "component",
                "subcomponent",
            ):
                return str(current.GetPath())
            current = current.GetParent()
        return str(prim.GetPath())

    @staticmethod
    def _world_transform(prim, xforms):
        """Read live PhysX poses when simulation does not write transforms to USD."""
        from pxr import Gf

        world = xforms.GetLocalToWorldTransform(prim)
        try:
            import omni.physx
            import omni.timeline
        except ImportError:
            return np.asarray(world, dtype=float)
        if not omni.timeline.get_timeline_interface().is_playing():
            return np.asarray(world, dtype=float)
        body = prim
        while body and not body.IsPseudoRoot():
            if attribute(body, "physics:rigidBodyEnabled"):
                pose = omni.physx.get_physx_interface().get_rigidbody_transformation(
                    str(body.GetPath())
                )
                if not pose.get("ret_val"):
                    raise ValueError(
                        f"Live rigid-body pose unavailable: {body.GetPath()}"
                    )
                rotation = pose["rotation"]
                live = Gf.Matrix4d(1)
                live.SetRotate(Gf.Quatd(rotation[3], Gf.Vec3d(*rotation[:3])))
                live.SetTranslateOnly(Gf.Vec3d(*pose["position"]))
                authored = xforms.GetLocalToWorldTransform(body)
                # Retain the authored scale and the child's local transform.
                scale = Gf.Transform(authored).GetScale()
                scale_matrix = Gf.Matrix4d(1).SetScale(scale)
                return np.asarray(
                    world * authored.GetInverse() * scale_matrix * live, dtype=float
                )
            body = body.GetParent()
        return np.asarray(world, dtype=float)

    def _dynamic(self, prim, time):
        explicit = self._inherited(prim, DYNAMIC, time)
        if explicit is not None:
            if explicit not in ("auto", "static", "dynamic"):
                raise ValueError("Dynamic override must be auto, static or dynamic")
            if explicit != "auto":
                return explicit == "dynamic"
        while prim and not prim.IsPseudoRoot():
            if attribute(prim, "physics:rigidBodyEnabled", time):
                return True
            if any(
                a.ValueMightBeTimeVarying()
                for a in prim.GetAttributes()
                if a.GetName().startswith("xformOp")
            ):
                return True
            prim = prim.GetParent()
        return False

    def _qualify_partitions(self):
        groups = {}
        for obj in self.objects.values():
            groups.setdefault(obj.partition, []).append(obj)
        self._partition_cache = {
            k: v for k, v in self._partition_cache.items() if k in groups
        }
        for partition, objects in groups.items():
            signature = tuple(
                (o.path, o.revision, o.materials, tuple(o.transform.flat))
                for o in objects
            )
            cached = self._partition_cache.get(partition)
            if cached and cached[0] == signature:
                for obj in objects:
                    obj.planar = cached[1]
                self.issues.extend(cached[2])
                self.warnings.extend(cached[3])
                continue
            before_issues, before_warnings = len(self.issues), len(self.warnings)
            points = np.concatenate([o.world_points for o in objects])
            centered = points - points.mean(axis=0)
            singular = np.linalg.svd(centered, compute_uv=False)
            planar = (
                len(singular) == 3
                and singular[1] > 1e-8
                and singular[-1] <= max(1e-6, singular[0] * 1e-6)
            )

            def material_key(material):
                return tuple(
                    None
                    if curve is None
                    else (
                        curve.values,
                        curve.frequencies,
                        curve.evidence,
                        curve.citation,
                    )
                    for curve in (
                        material.absorption,
                        material.scattering,
                        material.transmission_db,
                    )
                )

            materials = {material_key(m) for o in objects for m in o.materials}
            transmissive = any(
                m.transmission_db is not None for o in objects for m in o.materials
            )
            if transmissive and len(materials) > 1:
                self.issues.append(
                    f"{partition}: conflicting whole-assembly material definitions"
                )
                planar = False
            for obj in objects:
                obj.planar = bool(planar)
            if transmissive and not planar:
                self.warnings.append(
                    f"{partition}: transmission unsupported; imported opaque"
                )
            self._partition_cache[partition] = (
                signature,
                bool(planar),
                tuple(self.issues[before_issues:]),
                tuple(self.warnings[before_warnings:]),
            )
        self.warnings.append("Distinct sequential-assembly transmission is unsupported")

    def resolve_containment(self, arrays, *, time=None):
        from isaac_audio_sensors.isaac.environment_resolution import (
            IsaacEnvironmentResolutionCfg,
            resolve_stage_environment,
        )

        result = {}
        for array in arrays:
            diagnostics = {}
            try:
                resolve_stage_environment(
                    self.stage,
                    array,
                    cfg=IsaacEnvironmentResolutionCfg(
                        mode="auto", candidate_roots=self.roots
                    ),
                    diagnostics_out=diagnostics,
                    time_code=time,
                    prims=tuple(self._prims),
                )
                result[array.array_id] = {"state": "contained", **diagnostics}
            except ValueError as exc:
                result[array.array_id] = {"state": "unknown", "reason": str(exc)}
        self.containment = result or {
            "state": "unknown",
            "reason": "No microphone arrays discovered",
        }
        return result

    def edit(self, paths, values):
        """Author the same USD changes used by Kit commands; None clears an override."""
        from pxr import Sdf

        if self.closed:
            raise RuntimeError("Acoustic scene session is closed")
        for path in paths:
            prim = self.stage.GetPrimAtPath(path)
            if not prim:
                raise ValueError(f"Missing prim {path}")
            if prim.IsInstanceProxy():
                raise ValueError(
                    "Edit the instance root or source material for instance proxies"
                )
        with Sdf.ChangeBlock():
            for path in paths:
                prim = self.stage.GetPrimAtPath(path)
                for name, value in values.items():
                    if value is None:
                        attr = prim.GetAttribute(name)
                        if attr:
                            attr.Clear()
                        continue
                    if isinstance(value, bool):
                        kind = Sdf.ValueTypeNames.Bool
                    elif isinstance(value, str):
                        kind = Sdf.ValueTypeNames.String
                    elif isinstance(value, (tuple, list)):
                        kind = Sdf.ValueTypeNames.DoubleArray
                    else:
                        kind = Sdf.ValueTypeNames.Double
                    prim.CreateAttribute(name, kind, custom=True).Set(value)
        return self.refresh()

    def configure(
        self, *, associations=None, fallback_material=None, fallback_scattering=None
    ):
        import json

        self.stage.DefinePrim(SETTINGS, "Scope")
        values = {}
        if associations is not None:
            for value in associations.values():
                from isaac_audio_sensors.core.acoustics.materials import (
                    resolve_material,
                )

                resolve_material(value)
            values["ias:material_associations"] = json.dumps(
                associations, sort_keys=True
            )
        if fallback_material is not None:
            values["ias:fallback_material"] = fallback_material
        if fallback_scattering is not None:
            values["ias:fallback_scattering"] = fallback_scattering
        return self.edit([SETTINGS], values)

    def verify_provider(self, library_path):
        from .steam import SteamScene

        if self.closed:
            raise RuntimeError("Acoustic scene session is closed")
        if self.provider:
            self.provider.close()
        self.provider = None
        self.provider = SteamScene(library_path)
        self.provider.sync(self.objects, valid=not self.issues)
        return self.summary()

    def reset(self):
        """Rebuild owned runtime state, retaining authored scene corrections."""
        library = self.provider.library_path if self.provider else None
        if self.provider:
            self.provider.close()
            self.provider = None
        self.objects.clear()
        self._partition_cache.clear()
        self._structural = True
        result = self.refresh()
        return self.verify_provider(library) if library else result

    def summary(self):
        fallback_count = sum(
            any(c.origin.startswith("fallback:") for c in (m.absorption, m.scattering))
            or m.transmission_db is None
            for o in self.objects.values()
            for m in o.materials
        )
        return {
            "state": "closed"
            if self.closed
            else "scene not prepared"
            if not self._prepared
            else "preparation with issues"
            if self.issues
            else "scene verified in provider"
            if self.provider and self.provider.verified
            else "scene prepared",
            "roots": self.roots,
            "objects": len(self.objects),
            "excluded": dict(self.excluded),
            "triangles": sum(len(o.triangles) for o in self.objects.values()),
            "partitions": len({o.partition for o in self.objects.values()}),
            "dynamic": sum(o.dynamic for o in self.objects.values()),
            "fallback_materials": fallback_count,
            "issues": tuple(self.issues),
            "warnings": tuple(self.warnings),
            "containment": self.containment,
            "geometry_builds": self.geometry_builds,
            "transform_updates": self.transform_updates,
        }

    def close(self):
        if self.closed:
            return
        self._listener.Revoke()
        if self.provider:
            self.provider.close()
        self.objects.clear()
        self.closed = True
