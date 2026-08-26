"""Far-field least-squares direction solvers for microphone arrays."""

from __future__ import annotations

import math

from isaac_audio_sensors.core.constants import EPSILON
from isaac_audio_sensors.core.microphone_array import layout_rank_xyz
from isaac_audio_sensors.core.types import MicrophoneArraySpec


def least_squares_direction(
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    speed_of_sound_mps: float,
) -> tuple[float, float, float | None, float] | None:
    """Solve the far-field direction in local coordinates.

    Returns ``(ux, uy, uz, residual)`` with a unit 3D direction when the
    layout has full 3D rank, or ``(ux, uy, None, residual)`` from the planar
    XY solve otherwise (unchanged legacy behavior for planar arrays).
    """

    if layout_rank_xyz(sensor) >= 3:
        return _least_squares_direction_3d(
            sensor,
            per_mic_delay_s,
            speed_of_sound_mps,
        )
    microphones = sensor.microphones
    ref = microphones[0]
    ref_pos = ref.relative_position_m
    ref_delay = per_mic_delay_s[ref.mic_id]
    sxx = sxy = syy = bx = by = 0.0
    rows: list[tuple[float, float, float]] = []
    for microphone in microphones[1:]:
        pos = microphone.relative_position_m
        ax = pos[0] - ref_pos[0]
        ay = pos[1] - ref_pos[1]
        b = -speed_of_sound_mps * (per_mic_delay_s[microphone.mic_id] - ref_delay)
        rows.append((ax, ay, b))
        sxx += ax * ax
        sxy += ax * ay
        syy += ay * ay
        bx += ax * b
        by += ay * b
    det = sxx * syy - sxy * sxy
    if abs(det) <= EPSILON:
        return None
    ux = (bx * syy - by * sxy) / det
    uy = (sxx * by - sxy * bx) / det
    length = math.hypot(ux, uy)
    if length <= EPSILON:
        return None
    ux /= length
    uy /= length
    residual = 0.0
    for ax, ay, b in rows:
        residual += (ax * ux + ay * uy - b) ** 2
    residual = math.sqrt(residual / max(len(rows), 1))
    return ux, uy, None, residual


def _least_squares_direction_3d(
    sensor: MicrophoneArraySpec,
    per_mic_delay_s: dict[str, float],
    speed_of_sound_mps: float,
) -> tuple[float, float, float | None, float] | None:
    microphones = sensor.microphones
    ref = microphones[0]
    ref_pos = ref.relative_position_m
    ref_delay = per_mic_delay_s[ref.mic_id]
    m_xx = m_xy = m_xz = m_yy = m_yz = m_zz = 0.0
    v_x = v_y = v_z = 0.0
    rows: list[tuple[float, float, float, float]] = []
    for microphone in microphones[1:]:
        pos = microphone.relative_position_m
        ax = pos[0] - ref_pos[0]
        ay = pos[1] - ref_pos[1]
        az = pos[2] - ref_pos[2]
        b = -speed_of_sound_mps * (per_mic_delay_s[microphone.mic_id] - ref_delay)
        rows.append((ax, ay, az, b))
        m_xx += ax * ax
        m_xy += ax * ay
        m_xz += ax * az
        m_yy += ay * ay
        m_yz += ay * az
        m_zz += az * az
        v_x += ax * b
        v_y += ay * b
        v_z += az * b
    det = (
        m_xx * (m_yy * m_zz - m_yz * m_yz)
        - m_xy * (m_xy * m_zz - m_yz * m_xz)
        + m_xz * (m_xy * m_yz - m_yy * m_xz)
    )
    if abs(det) <= EPSILON:
        return None
    ux = (
        v_x * (m_yy * m_zz - m_yz * m_yz)
        - m_xy * (v_y * m_zz - m_yz * v_z)
        + m_xz * (v_y * m_yz - m_yy * v_z)
    ) / det
    uy = (
        m_xx * (v_y * m_zz - v_z * m_yz)
        - v_x * (m_xy * m_zz - m_yz * m_xz)
        + m_xz * (m_xy * v_z - v_y * m_xz)
    ) / det
    uz = (
        m_xx * (m_yy * v_z - m_yz * v_y)
        - m_xy * (m_xy * v_z - v_y * m_xz)
        + v_x * (m_xy * m_yz - m_yy * m_xz)
    ) / det
    length = math.sqrt(ux * ux + uy * uy + uz * uz)
    if length <= EPSILON:
        return None
    ux /= length
    uy /= length
    uz /= length
    residual = 0.0
    for ax, ay, az, b in rows:
        residual += (ax * ux + ay * uy + az * uz - b) ** 2
    residual = math.sqrt(residual / max(len(rows), 1))
    return ux, uy, uz, residual


__all__ = ["least_squares_direction"]
