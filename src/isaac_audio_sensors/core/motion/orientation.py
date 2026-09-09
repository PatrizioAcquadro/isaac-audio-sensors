"""Shortest-arc quaternion interpolation and vector rotation (xyzw)."""

import numpy as np


def interpolate_orientation(first, second, weight):
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    first = first / np.linalg.norm(first, axis=-1, keepdims=True)
    second = second / np.linalg.norm(second, axis=-1, keepdims=True)
    dot = np.sum(first * second, axis=-1, keepdims=True)
    second = np.where(dot < 0, -second, second)
    angle = np.arccos(np.clip(np.abs(dot), 0, 1))
    weight = np.asarray(weight)[..., None]
    sine = np.sin(angle)
    denominator = np.maximum(sine, 1e-12)
    value = np.where(
        sine > 1e-8,
        np.sin((1 - weight) * angle) / denominator * first
        + np.sin(weight * angle) / denominator * second,
        (1 - weight) * first + weight * second,
    )
    return value / np.linalg.norm(value, axis=-1, keepdims=True)


def rotate_vectors(vectors, orientations):
    q = np.asarray(orientations, dtype=float)
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    vectors = np.asarray(vectors)
    cross = 2 * np.cross(q[..., :3], vectors)
    return vectors + q[..., 3:] * cross + np.cross(q[..., :3], cross)
