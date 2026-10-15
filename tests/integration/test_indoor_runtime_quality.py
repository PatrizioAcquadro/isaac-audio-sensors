"""Loaded quality must count absent estimates, extras and current directions."""

import numpy as np

from tools.validation.indoor_runtime_quality import score_live


def test_live_quality_includes_misses_extras_and_original_audio_time():
    data = dict(
        received_power=np.array([[1.0], [1.0], [0.0]]),
        direct_power=np.array([[1.0], [1.0], [0.0]]),
        directions=np.tile([[[1.0, 0.0, 0.0]]], (3, 1, 1)),
        noise_power=np.zeros(3),
        scheduled_count=np.ones(3),
    )
    report = dict(
        args=dict(context_s=0.2),
        measurement=dict(
            rows=[
                dict(
                    audio_s=t,
                    sdk_ready_ms=30.0,
                    deadline_to_sdk_ms=40.0,
                    activity_detected=a,
                )
                for t, a in [(0.8, True), (0.9, True), (1.0, False)]
            ]
        ),
    )
    outputs = dict(
        bearing_deg_mask=np.array([[[False, False]], [[True, True]], [[False, False]]]),
        bearing_deg=np.array([[[0.0, 0.0]], [[0.0, 90.0]], [[0.0, 0.0]]]),
        ambiguity_mask=np.zeros((3, 1, 2), dtype=bool),
        observations_truncated=np.zeros((3, 1), dtype=int),
    )
    rows = score_live(data, report, outputs)
    assert rows[0]["misses"] == 1 and rows[0]["exact"] is False
    assert rows[1]["extras"] == 1 and rows[1]["exact"] is False
    assert rows[2]["exact"] is True
    assert [r["time_s"] for r in rows] == [0.8, 0.9, 1.0]
