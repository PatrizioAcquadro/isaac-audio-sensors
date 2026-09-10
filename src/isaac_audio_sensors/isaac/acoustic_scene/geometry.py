"""USD polygon extraction; triangulation preserves concave face boundaries."""

from __future__ import annotations

import numpy as np


def triangulate(points, counts, indices, holes=()):
    triangles, faces = [], []
    cursor = 0
    for face, count in enumerate(counts):
        polygon = list(map(int, indices[cursor : cursor + count]))
        cursor += count
        if face in holes:
            continue
        if (
            count < 3
            or len(polygon) != count
            or min(polygon) < 0
            or max(polygon) >= len(points)
        ):
            raise ValueError("Invalid polygon indices")
        xyz = points[polygon]
        normal = np.sum(np.cross(xyz, np.roll(xyz, -1, axis=0)), axis=0)
        if np.linalg.norm(normal) < 1e-12:
            raise ValueError("Degenerate polygon")
        xy = np.delete(xyz, np.argmax(abs(normal)), axis=1)

        def cross(a, b, c):
            u, v = b - a, c - a
            return u[0] * v[1] - u[1] * v[0]

        area = sum(
            xy[i, 0] * xy[(i + 1) % count, 1] - xy[(i + 1) % count, 0] * xy[i, 1]
            for i in range(count)
        )
        sign = 1 if area > 0 else -1
        remaining = list(range(count))
        while len(remaining) > 3:
            for i, mid in enumerate(remaining):
                a, b, c = remaining[i - 1], mid, remaining[(i + 1) % len(remaining)]
                if sign * cross(xy[a], xy[b], xy[c]) <= 1e-12:
                    continue
                if any(
                    all(
                        sign * cross(xy[u], xy[v], xy[p]) >= -1e-12
                        for u, v in ((a, b), (b, c), (c, a))
                    )
                    for p in remaining
                    if p not in (a, b, c)
                ):
                    continue
                triangles.append([polygon[a], polygon[b], polygon[c]])
                faces.append(face)
                remaining.pop(i)
                break
            else:
                raise ValueError(
                    "Cannot triangulate polygon without changing its boundary"
                )
        triangles.append([polygon[i] for i in remaining])
        faces.append(face)
    if cursor != len(indices):
        raise ValueError("Face counts do not match indices")
    return np.asarray(triangles, dtype=np.int32).reshape(-1, 3), np.asarray(
        faces, dtype=np.int32
    )


def extract(prim, time):
    from pxr import UsdGeom

    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        if mesh.GetSubdivisionSchemeAttr().Get() not in (None, "none"):
            # Control cages are not silently treated as evaluated surfaces.
            raise ValueError(
                "Subdivision surface requires a polygonal acoustic representation"
            )
        points = np.asarray(mesh.GetPointsAttr().Get(time), dtype=float)
        triangles, faces = triangulate(
            points,
            mesh.GetFaceVertexCountsAttr().Get(time),
            mesh.GetFaceVertexIndicesAttr().Get(time),
            mesh.GetHoleIndicesAttr().Get(time) or (),
        )
        if mesh.GetOrientationAttr().Get() == "leftHanded":
            triangles = triangles[:, ::-1].copy()
        return points, triangles, faces
    if prim.IsA(UsdGeom.Cube):
        half = UsdGeom.Cube(prim).GetSizeAttr().Get(time) / 2
        points = (
            np.array(
                [
                    [-1, -1, -1],
                    [1, -1, -1],
                    [1, 1, -1],
                    [-1, 1, -1],
                    [-1, -1, 1],
                    [1, -1, 1],
                    [1, 1, 1],
                    [-1, 1, 1],
                ],
                dtype=float,
            )
            * half
        )
        polygons = [
            0,
            3,
            2,
            1,
            4,
            5,
            6,
            7,
            0,
            1,
            5,
            4,
            1,
            2,
            6,
            5,
            2,
            3,
            7,
            6,
            3,
            0,
            4,
            7,
        ]
        tri, faces = triangulate(points, [4] * 6, polygons)
        return points, tri, faces
    if prim.IsA(UsdGeom.Sphere):
        radius = UsdGeom.Sphere(prim).GetRadiusAttr().Get(time)
        # Bounded polygonal approximation (32 longitudes, 16 latitude intervals).
        points = [[0, 0, radius], [0, 0, -radius]]
        for j in range(1, 16):
            phi = np.pi * j / 16
            points.extend(
                [
                    [
                        radius * np.sin(phi) * np.cos(a),
                        radius * np.sin(phi) * np.sin(a),
                        radius * np.cos(phi),
                    ]
                    for a in np.arange(32) * 2 * np.pi / 32
                ]
            )
        tri = []
        for i in range(32):
            k = (i + 1) % 32
            tri.extend([[0, 2 + i, 2 + k], [1, 2 + 14 * 32 + k, 2 + 14 * 32 + i]])
            for j in range(14):
                a, b = 2 + j * 32 + i, 2 + j * 32 + k
                tri.extend([[a, a + 32, b], [b, a + 32, b + 32]])
        triangles = np.array(tri, dtype=np.int32)
        return np.array(points), triangles, np.zeros(len(triangles), dtype=np.int32)
    if prim.IsA(UsdGeom.Capsule):
        schema = UsdGeom.Capsule(prim)
        radius, height = (
            schema.GetRadiusAttr().Get(time),
            schema.GetHeightAttr().Get(time),
        )
        rings = []
        for j in range(1, 9):
            angle = np.pi * j / 16
            rings.append((radius * np.sin(angle), height / 2 + radius * np.cos(angle)))
        for j in range(8, 16):
            angle = np.pi * j / 16
            rings.append((radius * np.sin(angle), -height / 2 + radius * np.cos(angle)))
        points = [[0, 0, height / 2 + radius], [0, 0, -height / 2 - radius]]
        for r, z in rings:
            points.extend(
                [
                    [r * np.cos(a), r * np.sin(a), z]
                    for a in np.arange(32) * 2 * np.pi / 32
                ]
            )
        triangles = []
        for i in range(32):
            k = (i + 1) % 32
            triangles.extend([[0, 2 + i, 2 + k], [1, 2 + 15 * 32 + k, 2 + 15 * 32 + i]])
            for j in range(15):
                a, b = 2 + j * 32 + i, 2 + j * 32 + k
                triangles.extend([[a, a + 32, b], [b, a + 32, b + 32]])
        points = np.array(points)
        axis = schema.GetAxisAttr().Get()
        if axis == "X":
            points = points[:, [2, 0, 1]]
        elif axis == "Y":
            points = points[:, [1, 2, 0]]
        triangles = np.array(triangles, dtype=np.int32)
        return points, triangles, np.zeros(len(triangles), dtype=np.int32)
    if prim.IsA(UsdGeom.Cylinder) or prim.IsA(UsdGeom.Cone):
        schema = (
            UsdGeom.Cylinder(prim) if prim.IsA(UsdGeom.Cylinder) else UsdGeom.Cone(prim)
        )
        radius, height = (
            schema.GetRadiusAttr().Get(time),
            schema.GetHeightAttr().Get(time),
        )
        angles = np.arange(32) * 2 * np.pi / 32
        ring = np.column_stack(
            (radius * np.cos(angles), radius * np.sin(angles), np.full(32, -height / 2))
        )
        if prim.IsA(UsdGeom.Cone):
            points = np.vstack((ring, [0, 0, height / 2], [0, 0, -height / 2]))
            tri = [[i, (i + 1) % 32, 32] for i in range(32)] + [
                [33, (i + 1) % 32, i] for i in range(32)
            ]
        else:
            top = ring.copy()
            top[:, 2] = height / 2
            points = np.vstack((ring, top, [0, 0, -height / 2], [0, 0, height / 2]))
            tri = []
            for i in range(32):
                k = (i + 1) % 32
                tri.extend(
                    [
                        [i, k, i + 32],
                        [k, k + 32, i + 32],
                        [64, k, i],
                        [65, i + 32, k + 32],
                    ]
                )
        axis = schema.GetAxisAttr().Get()
        if axis == "X":
            points = points[:, [2, 0, 1]]
        elif axis == "Y":
            points = points[:, [1, 2, 0]]
        triangles = np.array(tri, dtype=np.int32)
        return points, triangles, np.zeros(len(triangles), dtype=np.int32)
    raise ValueError(
        f"Unsupported geometry {prim.GetTypeName()}; supply an acoustic mesh"
    )
