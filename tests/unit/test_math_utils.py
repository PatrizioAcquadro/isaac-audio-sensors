"""Tests for core coordinate and quaternion math."""

from __future__ import annotations

import pytest

from isaac_audio_sensors.core.math_utils import (
    basis_from_quaternion,
    euler_deg_from_quaternion,
    quaternion_from_euler_deg,
    quaternion_from_yaw_deg,
)


def test_quaternion_basis_uses_x_forward_y_right_z_up():
    forward, right, up = basis_from_quaternion((0.0, 0.0, 0.0, 1.0))
    yaw_forward, yaw_right, _ = basis_from_quaternion(quaternion_from_yaw_deg(90.0))

    assert forward == pytest.approx((1.0, 0.0, 0.0))
    assert right == pytest.approx((0.0, 1.0, 0.0))
    assert up == pytest.approx((0.0, 0.0, 1.0))
    assert yaw_forward == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
    assert yaw_right == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


def test_euler_quaternion_helpers_round_trip():
    assert quaternion_from_euler_deg(yaw_deg=90.0) == pytest.approx(
        quaternion_from_yaw_deg(90.0),
        abs=1e-12,
    )
    assert euler_deg_from_quaternion(quaternion_from_yaw_deg(90.0)) == pytest.approx(
        (0.0, 0.0, 90.0),
        abs=1e-9,
    )

    quaternion = quaternion_from_euler_deg(
        roll_deg=10.0,
        pitch_deg=-20.0,
        yaw_deg=135.0,
    )
    assert euler_deg_from_quaternion(quaternion) == pytest.approx(
        (10.0, -20.0, 135.0),
        abs=1e-9,
    )
