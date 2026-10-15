"""Protect performance qualification from hidden cold costs and scheduling drift."""

import os
from copy import deepcopy

import pytest

from tools.validation.audio_runtime_performance import (
    GpuMonitor,
    distribution,
    onsets,
    summarize,
    window_work,
)


def rows():
    result = []
    for tick in range(600):
        row = dict(
            simulation_ms=3, acquire_wall_ms=5, overdue_ticks=2, unprocessed_samples=0
        )
        if (tick + 1) % 6 == 0:
            row.update(
                sdk_ready_ms=130 if tick == 5 else 30,
                pcm_to_sdk_gpu_ms=25,
                acquire_wall_ms=5,
                consumer_cpu_ms=0.2,
                deadline_to_sdk_ms=35,
                window_age_wall_ms=135,
                phase="startup" if tick < 60 else "steady",
                events=1,
                simulation_ms=3,
                overdue_ticks=2,
                unprocessed_samples=0,
            )
        result.append(row)
    return result


def test_cold_cost_and_distribution_tails_are_retained():
    result = summarize(rows(), 1, 10.03)
    assert result["interactive_timing_pass"]
    assert result["steady"]["sdk_ready_ms"]["p95"] == 30
    assert result["startup_updates"][0]["sdk_ready_ms"] == 130
    assert result["updates"] == 100
    assert result["aggregate_simulated_s_per_wall_s"] == pytest.approx(10 / 10.03)
    assert distribution([1, 2, 3, 100])["maximum"] == 100
    assert distribution([]) == {"n": 0}


def test_whole_window_includes_previous_five_acquisitions_and_simulation():
    result = window_work(rows())
    assert result["sdk"]["p95"] == 55
    assert result["simulation_sdk_consumer"]["p95"] == pytest.approx(73.2)


@pytest.mark.parametrize(
    "change",
    [
        {"sdk_ready_ms": 60},
        {"deadline_to_sdk_ms": 120},
        {"skipped_windows": 1},
        {"discontinuities": 1},
        {"overdue_ticks": 100},
    ],
)
def test_bad_latency_or_backlog_does_not_qualify(change):
    values = deepcopy(rows())
    for row in values:
        if row.get("phase") == "steady":
            row.update(change)
    assert not summarize(values, 1, 10)["interactive_timing_pass"]


def test_slow_training_does_not_qualify_as_realtime():
    assert not summarize(rows(), 16, 20)["interactive_timing_pass"]
    assert not summarize(rows(), 1, 10, paced=False)["interactive_timing_pass"]


def test_missing_onset_cannot_match_a_later_speech_segment():
    import numpy as np

    pcm = np.zeros((4, 32000))
    pcm[:, 1600:3200] = 0.01
    pcm[:, 16000:17600] = 0.01
    acquisition = [
        dict(window_end_wall=10 + (i + 1) / 60, acquired_wall=10 + (i + 1) / 60 + 0.005)
        for i in range(120)
    ]
    acquisition[65].update(
        sdk_ready_ms=30, audio_s=1.1, source_correct=True, ready_wall=11.13
    )
    result = onsets(pcm, acquisition, 10)
    assert result[0]["wall_response_upper_ms"] is None
    assert result[1]["audio_response_ms"] == pytest.approx(100)
    assert result[1]["wall_response_lower_ms"] < result[1]["wall_response_upper_ms"]


@pytest.mark.parametrize("kind,sm", [("C", 0), ("G", 5)])
def test_external_activity_and_missing_monitoring_prevent_qualification(kind, sm):
    monitor = GpuMonitor()
    assert not monitor.assessment(0, 2)["clean"]
    own = dict(pid=os.getpid(), kind="C+G", sm=80, framebuffer_mb=1000)
    monitor.samples = [dict(wall=1, processes=[own])]
    assert monitor.assessment(0, 2)["clean"]
    monitor.samples[0]["processes"].append(
        dict(pid=os.getpid() + 1, kind=kind, sm=sm, framebuffer_mb=100)
    )
    assert not monitor.assessment(0, 2)["clean"]
