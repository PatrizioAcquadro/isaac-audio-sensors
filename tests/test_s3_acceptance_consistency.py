"""Prevent S3.6 evidence from silently dropping confidence degradation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
S3_6_GATE = (
    ROOT / "outputs/isaac_audio_sensors/S3/S3.6/waveform_directivity_gate.json"
)


def test_s3_6_gate_proves_expected_confidence_degradation() -> None:
    if not S3_6_GATE.is_file():
        pytest.skip("S3.6 evidence is absent in this checkout; no gate was fabricated")

    gate = json.loads(S3_6_GATE.read_text(encoding="utf-8"))
    thresholds = gate["thresholds"]
    confidence = gate["measured_maxima"]["estimator_medians"][
        "srp_bearing_confidence"
    ]

    assert gate["rows"]["estimator_degradation"] == "passed"
    assert gate["confidence_remediation_revision"] == "5bfa67e"
    assert gate["confidence_formula_id"] == (
        "contrast_times_clamped_peak_power_per_pair_v1"
    )
    assert thresholds["estimator_confidence_front_floor"] == 0.050
    assert thresholds["estimator_confidence_rear_ceiling"] == 0.005
    assert thresholds["estimator_confidence_front_rear_drop"] == 0.040
    assert thresholds["estimator_confidence_ladder_order"] == "non_increasing"
    assert confidence[0] >= thresholds["estimator_confidence_front_floor"]
    assert confidence[-1] <= thresholds["estimator_confidence_rear_ceiling"]
    assert confidence[0] - confidence[-1] >= thresholds[
        "estimator_confidence_front_rear_drop"
    ]
    assert all(
        left >= right
        for left, right in zip(confidence, confidence[1:], strict=False)
    )
