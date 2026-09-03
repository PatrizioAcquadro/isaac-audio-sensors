from __future__ import annotations

import json

import numpy as np
import pytest

from tools.qualification.geometry_acoustics.evaluation_r9_4 import (
    qualify_steam_audio_r9_4,
)
from tools.qualification.geometry_acoustics.fixtures import (
    BLOCK_SAMPLES,
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    SAMPLE_RATE_HZ,
    generated_impulse,
)
from tools.qualification.geometry_acoustics.metrics import (
    expected_tdoa_samples,
    phase_metrics,
)
from tools.qualification.geometry_acoustics.models import RuntimeProbe
from tools.qualification.geometry_acoustics.r9_4 import (
    GATE_IDS,
    REPORT_VERSION,
    RiskObservation,
    RiskRetirementRun,
    StreamingDelayScheduler,
    assembly_fixtures,
    build_report,
    evaluate_report,
    paired_proxy_surfaces,
    pathing_fixtures,
    write_bundle,
    write_fixture_assets,
)


def _observations(*, failed: str | None = None) -> tuple[RiskObservation, ...]:
    evidence = (
        {
            "kind": "runtime_measurement",
            "origin": "provider_native",
            "reference": "measurements.json",
            "summary": "Measured evidence.",
        },
    )
    return tuple(
        RiskObservation(
            gate_id,
            "fail" if gate_id == failed else "pass",
            "Measured result.",
            evidence,
        )
        for gate_id in GATE_IDS
    )


def test_paired_proxy_maps_one_assembly_curve_to_every_closed_face() -> None:
    surfaces = paired_proxy_surfaces(
        "partition",
        center_xyz_m=(1.0, 0.0, 1.5),
        size_xyz_m=(0.2, 4.0, 3.0),
        face_fragments=4,
    )
    assert len(surfaces) == 12
    assert {surface.assembly_id for surface in surfaces} == {"partition"}
    assert {surface.transmission_loss_db for surface in surfaces} == {(12.0,) * 6}
    assert all(
        sum(size == 0.0 for size in surface.size_xyz_m) == 1 for surface in surfaces
    )


def test_r9_4_fixture_matrix_is_deterministic_and_bounded(tmp_path) -> None:
    assemblies = assembly_fixtures()
    pathing = pathing_fixtures()
    assert [fixture.fixture_id for fixture in assemblies] == [
        "proxy_one",
        "proxy_two",
        "proxy_three",
        "proxy_oblique",
        "proxy_thin",
        "proxy_thick",
        "proxy_fragmented",
    ]
    assert [item.fixture.fixture_id for item in pathing] == [
        "l_corridor_pathing",
        "connected_rooms_pathing",
    ]
    assert pathing[0].dynamic_translation_xyz_m is not None
    assert pathing[1].dynamic_translation_xyz_m is None
    assert len(set(pathing[0].probes_xyz_m)) == len(pathing[0].probes_xyz_m)

    first = tmp_path / "first"
    second = tmp_path / "second"
    write_fixture_assets(first)
    write_fixture_assets(second)
    first_files = sorted(
        path.relative_to(first) for path in first.rglob("*") if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second) for path in second.rglob("*") if path.is_file()
    )
    assert first_files == second_files
    assert all(
        (first / path).read_bytes() == (second / path).read_bytes()
        for path in first_files
    )
    manifest = json.loads((first / "fixture_manifest.json").read_text())
    assert manifest["report_version"] == REPORT_VERSION


def test_streaming_delay_matches_one_continuous_static_run() -> None:
    sample_count = BLOCK_SAMPLES * 3
    phase = np.arange(sample_count, dtype=np.float32)
    samples = np.stack((phase, phase * 0.5))
    delay_s = (2.5 / SAMPLE_RATE_HZ, 7.25 / SAMPLE_RATE_HZ)
    whole = StreamingDelayScheduler(
        channel_count=2, sample_rate_hz=SAMPLE_RATE_HZ
    ).process(samples, delay_s)
    split_scheduler = StreamingDelayScheduler(
        channel_count=2, sample_rate_hz=SAMPLE_RATE_HZ
    )
    split = np.concatenate(
        [
            split_scheduler.process(samples[:, start : start + BLOCK_SAMPLES], delay_s)
            for start in range(0, sample_count, BLOCK_SAMPLES)
        ],
        axis=1,
    )
    np.testing.assert_array_equal(split, whole)
    np.testing.assert_array_equal(
        StreamingDelayScheduler(channel_count=2, sample_rate_hz=SAMPLE_RATE_HZ).process(
            samples, (0.0, 0.0)
        ),
        samples,
    )


def test_streaming_delay_interpolates_moving_targets_at_block_boundaries() -> None:
    source = np.sin(
        2.0
        * np.pi
        * 997.0
        * np.arange(BLOCK_SAMPLES * 3, dtype=np.float64)
        / SAMPLE_RATE_HZ
    ).astype(np.float32)[None, :]
    scheduler = StreamingDelayScheduler(channel_count=1, sample_rate_hz=SAMPLE_RATE_HZ)
    delays = (100.0, 125.0, 90.0)
    rendered = np.concatenate(
        [
            scheduler.process(
                source[:, index * BLOCK_SAMPLES : (index + 1) * BLOCK_SAMPLES],
                (delay / SAMPLE_RATE_HZ,),
            )
            for index, delay in enumerate(delays)
        ],
        axis=1,
    )
    steps = np.abs(np.diff(rendered[0]))
    for boundary in (BLOCK_SAMPLES, BLOCK_SAMPLES * 2):
        neighbors = np.concatenate(
            (steps[boundary - 65 : boundary - 1], steps[boundary : boundary + 64])
        )
        assert steps[boundary - 1] <= np.max(neighbors) + 1e-6


def test_streaming_delay_preserves_fractional_microphone_phase() -> None:
    source_xyz_m = (1.5, 0.0, 1.2)
    array_xyz_m = (-1.5, 0.0, 1.2)
    microphones = tuple(
        tuple(
            coordinate + offset
            for coordinate, offset in zip(array_xyz_m, offsets, strict=True)
        )
        for offsets in QUAD_FRONT_OFFSETS_M
    )
    absolute_delays = tuple(
        float(np.linalg.norm(np.asarray(source_xyz_m) - np.asarray(microphone))) / 343.0
        for microphone in microphones
    )
    rendered = StreamingDelayScheduler(
        channel_count=len(MICROPHONE_IDS), sample_rate_hz=SAMPLE_RATE_HZ
    ).process(
        np.tile(generated_impulse(), (len(MICROPHONE_IDS), 1)),
        absolute_delays,
    )
    expected = expected_tdoa_samples(
        source_xyz_m, microphones, sample_rate_hz=SAMPLE_RATE_HZ
    )
    result = phase_metrics(rendered, expected, MICROPHONE_IDS)
    assert result.passed
    assert max(result.lag_errors_samples) <= 1.0
    assert min(result.aligned_correlations) >= 0.99


def test_r9_4_report_keeps_selection_and_admissions_separate() -> None:
    report = build_report(
        runtime={"python": "test"},
        observations=_observations(failed="acoustic_proxy_transmission"),
    )
    evaluation = evaluate_report(report)
    assert evaluation["provider_selection"] == "unchanged"
    assert evaluation["execution_status"] == "complete"
    assert evaluation["failed_gates"] == ["acoustic_proxy_transmission"]
    assert not evaluation["admitted_capabilities"]["acoustic_proxy_transmission"]
    assert evaluation["admitted_capabilities"]["baked_pathing"]
    with pytest.raises(ValueError, match="canonical order"):
        build_report(
            runtime={"python": "test"},
            observations=tuple(reversed(_observations())),
        )


def test_r9_4_provider_baseline_fails_closed_before_measurement() -> None:
    class ProbeOnlyAdapter:
        def probe_runtime(self) -> RuntimeProbe:
            return RuntimeProbe(True, "4.8.1", {"python": "test"}, {})

    run = qualify_steam_audio_r9_4(
        ProbeOnlyAdapter(),
        source_commit="wrong",
        source_tag="v4.8.1",
        release_check={
            "latest_stable_tag": "v4.8.2",
            "latest_stable_commit": "new",
        },
        build_configuration={"verified": True},
    )
    assert run.report["gates"][0]["status"] == "fail"
    assert all(item["status"] == "blocked" for item in run.report["gates"][1:])
    assert run.evaluation["provider_selection"] == "unchanged"
    assert run.evaluation["execution_status"] == "blocked"


def test_r9_4_bundle_serialization_is_byte_deterministic(tmp_path) -> None:
    report = build_report(runtime={"python": "test"}, observations=_observations())
    run = RiskRetirementRun(
        report,
        evaluate_report(report),
        {"value": 1.0},
        {"signal": np.arange(8, dtype=np.float32)},
        {"source": "test"},
        ("qualification complete",),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_bundle(first, run)
    write_bundle(second, run)
    expected = {
        "evaluation.json",
        "measurements.json",
        "provenance.json",
        f"{REPORT_VERSION}-report.json",
        "run.log",
        "signals.npz",
    }
    assert {path.name for path in first.iterdir()} == expected
    assert all(
        (first / name).read_bytes() == (second / name).read_bytes() for name in expected
    )
