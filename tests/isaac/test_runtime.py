from __future__ import annotations

import torch
from pxr import Usd

from isaac_audio_sensors.lab.batched_backend import (
    batched_basis_from_quat_xyzw,
    batched_bearing_deg,
)
from isaac_audio_sensors.lab.class_loader import get_audio_array_sensor_classes


def test_isaac_lab_runtime_and_usd_are_available():
    import isaaclab

    classes = get_audio_array_sensor_classes(require_real=True)
    stage = Usd.Stage.CreateInMemory()

    assert isaaclab is not None
    assert classes.real
    assert stage.DefinePrim("/World/AudioArray", "Xform").IsValid()


def test_batched_audio_math_runs_on_rtx_4090():
    assert torch.cuda.is_available()
    assert "RTX 4090" in torch.cuda.get_device_name(0)

    device = torch.device("cuda:0")
    quaternions = torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=device)
    basis = batched_basis_from_quat_xyzw(quaternions)
    bearing, valid = batched_bearing_deg(
        torch.tensor([0.0, 1.0], device=device),
        torch.tensor([1.0, 0.0], device=device),
    )

    torch.testing.assert_close(basis, torch.eye(3, device=device).unsqueeze(0))
    torch.testing.assert_close(bearing, torch.tensor([90.0, 0.0], device=device))
    assert valid.tolist() == [True, True]
