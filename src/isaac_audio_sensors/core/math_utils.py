"""Coordinate, quaternion, and vector helpers for the core API."""

from __future__ import annotations

import math
from collections.abc import Iterable

from isaac_audio_sensors.core.constants import EPSILON

Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


def as_vector3(value: Iterable[float], field_name: str) -> Vector3:
    """Coerce an iterable into a finite 3-vector."""

    try:
        x, y, z = value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain exactly three values.") from exc

    vector = (float(x), float(y), float(z))
    if not all(math.isfinite(component) for component in vector):
        raise ValueError(f"{field_name} must contain only finite values.")
    return vector


def as_quaternion_xyzw(value: Iterable[float], field_name: str) -> Quaternion:
    """Coerce an iterable into a finite quaternion in ``(x, y, z, w)`` order."""

    try:
        x, y, z, w = value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain exactly four values.") from exc

    quat = (float(x), float(y), float(z), float(w))
    if not all(math.isfinite(component) for component in quat):
        raise ValueError(f"{field_name} must contain only finite values.")
    if norm4(quat) <= EPSILON:
        raise ValueError(f"{field_name} must be non-zero.")
    return normalize_quaternion(quat)


def normalize_quaternion(quat: Quaternion) -> Quaternion:
    """Return a unit quaternion in ``(x, y, z, w)`` order."""

    length = norm4(quat)
    if length <= EPSILON:
        raise ValueError("quaternion must be non-zero.")
    return tuple(component / length for component in quat)  # type: ignore[return-value]


def quaternion_from_yaw_deg(yaw_deg: float) -> Quaternion:
    """Build a ``(x, y, z, w)`` quaternion for yaw about ``+Z``."""

    yaw_rad = math.radians(float(yaw_deg))
    half = yaw_rad / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


def quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    """Multiply two ``(x, y, z, w)`` quaternions."""

    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def quaternion_conjugate(quat: Quaternion) -> Quaternion:
    """Return the conjugate of a ``(x, y, z, w)`` quaternion."""

    x, y, z, w = quat
    return (-x, -y, -z, w)


def rotate_vector_by_quaternion(vector: Vector3, quat: Quaternion) -> Vector3:
    """Rotate a vector by a ``(x, y, z, w)`` quaternion."""

    qvec = (vector[0], vector[1], vector[2], 0.0)
    rotated = quaternion_multiply(
        quaternion_multiply(quat, qvec),
        quaternion_conjugate(quat),
    )
    return (rotated[0], rotated[1], rotated[2])


def basis_from_quaternion(quat: Quaternion) -> tuple[Vector3, Vector3, Vector3]:
    """Return forward, right, and up world vectors for a local audio-array frame."""

    normalized = normalize_quaternion(quat)
    return (
        rotate_vector_by_quaternion((1.0, 0.0, 0.0), normalized),
        rotate_vector_by_quaternion((0.0, 1.0, 0.0), normalized),
        rotate_vector_by_quaternion((0.0, 0.0, 1.0), normalized),
    )


def add(left: Vector3, right: Vector3) -> Vector3:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def subtract(left: Vector3, right: Vector3) -> Vector3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def scale(vector: Vector3, scalar: float) -> Vector3:
    return (vector[0] * scalar, vector[1] * scalar, vector[2] * scalar)


def dot(left: Vector3, right: Vector3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def norm(vector: Vector3) -> float:
    return math.sqrt(dot(vector, vector))


def norm4(quat: Quaternion) -> float:
    return math.sqrt(sum(component * component for component in quat))


def normalize(vector: Vector3, field_name: str = "vector") -> Vector3:
    length = norm(vector)
    if length <= EPSILON:
        raise ValueError(f"{field_name} must be non-zero.")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def normalize_bearing_deg(value: float) -> float:
    normalized = float(value) % 360.0
    if math.isclose(normalized, 360.0, rel_tol=0.0, abs_tol=1e-12):
        return 0.0
    if math.isclose(normalized, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return 0.0
    return normalized


def bearing_from_components(forward_m: float, right_m: float) -> float | None:
    """Return clockwise bearing from local forward/right components."""

    horizontal = math.hypot(forward_m, right_m)
    if horizontal <= EPSILON:
        return None
    return normalize_bearing_deg(math.degrees(math.atan2(right_m, forward_m)))


def angular_error_deg(left: float, right: float) -> float:
    """Return the smallest absolute angular difference in degrees."""

    delta = (left - right + 180.0) % 360.0 - 180.0
    return abs(delta)
