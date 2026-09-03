"""Evaluate the bounded R9.4 Steam Audio risk-retirement probes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict

import numpy as np

from .fixtures import (
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    generated_impulse,
)
from .metrics import (
    ASSEMBLY_EQUIVALENCE_DB,
    BLOCK_P95_MS,
    MIN_ALIGNED_CORRELATION,
    PARTITION_SUM_TOLERANCE_DB,
    TDOA_TOLERANCE_SAMPLES,
    TRANSMISSION_TONE_TOLERANCE_DB,
    UPDATE_P95_MS,
    expected_tdoa_samples,
    phase_metrics,
    rms_db,
    summarize_timings,
)
from .models import RuntimeProbe
from .r9_4 import (
    GATE_IDS,
    SELECTED_PROVIDER_VERSION,
    SELECTED_SOURCE_COMMIT,
    PathingPerformanceRun,
    PathingRun,
    RiskObservation,
    RiskRetirementRun,
    TimingRun,
    assembly_fixtures,
    blocked_observations,
    build_report,
    evaluate_report,
    evidence,
    json_safe,
    pathing_fixtures,
)

_PATH_SIGNAL_MARGIN_DB = 20.0
_DYNAMIC_LEVEL_CHANGE_DB = 3.0


def _mean_curve(runs: list[object]) -> dict[str, float]:
    curves = [
        run.measurements["tone_loss_db"]
        for run in runs
        if "tone_loss_db" in run.measurements
    ]
    if not curves:
        return {}
    first = curves[0]
    assert isinstance(first, Mapping)
    return {
        str(band): float(
            np.mean(
                [float(curve[band]) for curve in curves if isinstance(curve, Mapping)]
            )
        )
        for band in first
    }


def _curve_within(
    observed: Mapping[str, float],
    expected: Mapping[str, float],
    tolerance_db: float,
) -> bool:
    return observed.keys() == expected.keys() and all(
        abs(float(observed[band]) - float(expected[band])) <= tolerance_db
        for band in observed
    )


def _finite_rms_db(samples: np.ndarray) -> float:
    level = rms_db(samples)
    return -200.0 if not math.isfinite(level) else max(-200.0, level)


def _microphone_positions(
    array_xyz_m: tuple[float, float, float],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(
            coordinate + delta
            for coordinate, delta in zip(array_xyz_m, offset, strict=True)
        )
        for offset in QUAD_FRONT_OFFSETS_M
    )


def _assembly_results(
    adapter: object,
) -> tuple[dict[str, object], dict[str, np.ndarray], bool]:
    grouped: dict[str, list[object]] = {}
    arrays: dict[str, np.ndarray] = {}
    for fixture in assembly_fixtures():
        runs = []
        for repetition in range(REPEAT_COUNT):
            run = adapter.run_fixture(fixture, repetition=repetition)
            runs.append(run)
            if repetition == 0 and run.block is not None:
                arrays[f"assembly__{fixture.fixture_id}"] = run.block.samples
        grouped[fixture.fixture_id] = runs
    curves = {fixture_id: _mean_curve(runs) for fixture_id, runs in grouped.items()}
    one = curves["proxy_one"]
    authored = {band: 12.0 for band in one}
    one_ok = _curve_within(one, authored, TRANSMISSION_TONE_TOLERANCE_DB)
    sequential = {
        fixture_id: {
            "expected_from_one_db": {band: float(one[band]) * count for band in one},
            "measured_db": curves[fixture_id],
        }
        for fixture_id, count in (("proxy_two", 2), ("proxy_three", 3))
    }
    sequential_ok = all(
        _curve_within(
            value["measured_db"],
            value["expected_from_one_db"],
            PARTITION_SUM_TOLERANCE_DB,
        )
        for value in sequential.values()
    )
    equivalent_ids = (
        "proxy_oblique",
        "proxy_thin",
        "proxy_thick",
        "proxy_fragmented",
    )
    equivalence = {
        fixture_id: {
            band: float(curves[fixture_id][band]) - float(one[band]) for band in one
        }
        for fixture_id in equivalent_ids
    }
    equivalence_ok = all(
        all(abs(delta) <= ASSEMBLY_EQUIVALENCE_DB for delta in differences.values())
        for differences in equivalence.values()
    )
    passed = one_ok and sequential_ok and equivalence_ok
    return (
        {
            "authored_one_assembly_db": authored,
            "curves_db": curves,
            "equivalence_delta_db": equivalence,
            "equivalence_passed": equivalence_ok,
            "passed": passed,
            "sequential": sequential,
            "sequential_passed": sequential_ok,
            "single_assembly_passed": one_ok,
        },
        arrays,
        passed,
    )


def _path_phase(run: PathingRun, spec: object) -> dict[str, object]:
    expected = expected_tdoa_samples(
        spec.fixture.source_xyz_m,
        _microphone_positions(spec.fixture.array_xyz_m),
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    result = phase_metrics(run.enabled_samples, expected, MICROPHONE_IDS)
    return {
        "fixture_id": run.fixture_id,
        "repetition": run.repetition,
        **asdict(result),
    }


def _pathing_results(
    adapter: object,
) -> tuple[
    dict[str, object],
    dict[str, np.ndarray],
    bool,
    bool,
    bool,
]:
    runs: list[tuple[object, PathingRun]] = []
    arrays: dict[str, np.ndarray] = {}
    for spec in pathing_fixtures():
        for repetition in range(REPEAT_COUNT):
            run = adapter.run_pathing_fixture(spec, repetition=repetition)
            runs.append((spec, run))
            prefix = f"pathing__{run.fixture_id}__r{repetition}"
            arrays[f"{prefix}__enabled"] = run.enabled_samples
            if run.validated_samples is not None:
                arrays[f"{prefix}__validated"] = run.validated_samples
            if run.alternate_samples is not None:
                arrays[f"{prefix}__alternate"] = run.alternate_samples

    signal_repetitions = []
    phase_results = []
    for spec, run in runs:
        enabled_levels = [_finite_rms_db(channel) for channel in run.enabled_samples]
        disabled_levels = [_finite_rms_db(channel) for channel in run.disabled_samples]
        margins = [
            enabled - disabled
            for enabled, disabled in zip(enabled_levels, disabled_levels, strict=True)
        ]
        signal_repetitions.append(
            {
                "fixture_id": run.fixture_id,
                "margins_db": margins,
                "passed": all(margin >= _PATH_SIGNAL_MARGIN_DB for margin in margins),
                "repetition": run.repetition,
            }
        )
        phase_results.append(_path_phase(run, spec))
    per_fixture_signal_pass = all(
        sum(
            bool(item["passed"])
            for item in signal_repetitions
            if item["fixture_id"] == spec.fixture.fixture_id
        )
        >= 4
        for spec in pathing_fixtures()
    )
    phase_ok = all(bool(result["passed"]) for result in phase_results)
    signal_passed = per_fixture_signal_pass and phase_ok

    dynamic_runs = [run for _, run in runs if run.fixture_id == "l_corridor_pathing"]
    dynamic_repetitions = []
    for run in dynamic_runs:
        assert run.validated_samples is not None
        assert run.alternate_samples is not None
        enabled_level = _finite_rms_db(run.enabled_samples)
        validated_level = _finite_rms_db(run.validated_samples)
        alternate_level = _finite_rms_db(run.alternate_samples)
        validated_metrics = run.measurements.get("validated")
        assert isinstance(validated_metrics, Mapping)
        occluded_segments = int(validated_metrics.get("occluded_segment_count", 0))
        dynamic_repetitions.append(
            {
                "alternate_level_db": alternate_level,
                "alternate_margin_over_validated_db": alternate_level - validated_level,
                "baseline_to_validated_delta_db": validated_level - enabled_level,
                "occluded_segment_count": occluded_segments,
                "passed": (
                    occluded_segments > 0
                    and abs(alternate_level - validated_level)
                    >= _DYNAMIC_LEVEL_CHANGE_DB
                    and alternate_level > -200.0 + _PATH_SIGNAL_MARGIN_DB
                ),
                "repetition": run.repetition,
                "validated_level_db": validated_level,
            }
        )
    dynamic_passed = (
        len(dynamic_repetitions) == REPEAT_COUNT
        and sum(bool(item["passed"]) for item in dynamic_repetitions) >= 4
    )

    diagnostic_counts = []
    for _, run in runs:
        per_key: dict[tuple[str, str, int], int] = {}
        for item in run.diagnostics:
            key = (item.source_id, item.microphone_id, item.frame_index)
            per_key[key] = per_key.get(key, 0) + 1
        diagnostic_counts.append(
            {
                "fixture_id": run.fixture_id,
                "max_segments_per_key": max(per_key.values(), default=0),
                "microphone_ids": sorted(
                    {item.microphone_id for item in run.diagnostics}
                ),
                "repetition": run.repetition,
                "segment_count": len(run.diagnostics),
            }
        )
    dynamic_diagnostics = [
        item for item in diagnostic_counts if item["fixture_id"] == "l_corridor_pathing"
    ]
    diagnostics_passed = len(dynamic_diagnostics) == REPEAT_COUNT and all(
        item["microphone_ids"] == sorted(MICROPHONE_IDS)
        and 0 < int(item["max_segments_per_key"]) <= 256
        for item in dynamic_diagnostics
    )
    measurements = {
        "diagnostic_counts": diagnostic_counts,
        "diagnostics_passed": diagnostics_passed,
        "dynamic": {
            "passed": dynamic_passed,
            "repetitions": dynamic_repetitions,
        },
        "fixtures": [
            {
                "fixture_id": run.fixture_id,
                "measurements": run.measurements,
                "repetition": run.repetition,
            }
            for _, run in runs
        ],
        "phase": {
            "minimum_aligned_correlation": MIN_ALIGNED_CORRELATION,
            "passed": phase_ok,
            "results": phase_results,
            "tdoa_tolerance_samples": TDOA_TOLERANCE_SAMPLES,
        },
        "signal": {
            "margin_db": _PATH_SIGNAL_MARGIN_DB,
            "passed": signal_passed,
            "repetitions": signal_repetitions,
        },
    }
    return measurements, arrays, signal_passed, dynamic_passed, diagnostics_passed


def _timing_results(timing: TimingRun) -> tuple[dict[str, object], bool]:
    measurements = dict(timing.measurements)
    direct = measurements["direct"]
    pathing = measurements["pathing"]
    streaming = measurements["streaming"]
    assert isinstance(direct, Mapping)
    assert isinstance(pathing, Mapping)
    assert isinstance(streaming, Mapping)
    impulse_index = int(np.argmax(generated_impulse()))
    direct_errors = [
        abs(int(observed) - (impulse_index + float(delay_s) * SAMPLE_RATE_HZ))
        for observed, delay_s in zip(
            direct["scheduled_peak_indices"], direct["delay_s"], strict=True
        )
    ]
    path_errors = [
        abs(int(scheduled) - (int(native) + float(delay_s) * SAMPLE_RATE_HZ))
        for scheduled, native, delay_s in zip(
            pathing["scheduled_peak_indices"],
            pathing["native_peak_indices"],
            pathing["scheduled"]["delay_s"],
            strict=True,
        )
    ]
    boundary_ok = all(
        float(boundary) <= float(local) + 1e-6
        for boundary, local in zip(
            streaming["boundary_steps"], streaming["local_max_steps"], strict=True
        )
    )
    reflection_unchanged = bool(measurements["reflections"]["unchanged"])
    passed = (
        max(direct_errors, default=math.inf) <= TDOA_TOLERANCE_SAMPLES
        and max(path_errors, default=math.inf) <= TDOA_TOLERANCE_SAMPLES
        and float(streaming["static_split_max_abs_error"]) <= 1e-6
        and boundary_ok
        and reflection_unchanged
    )
    measurements["acceptance"] = {
        "boundary_continuity_passed": boundary_ok,
        "direct_peak_errors_samples": direct_errors,
        "passed": passed,
        "pathing_peak_errors_samples": path_errors,
        "reflection_unchanged": reflection_unchanged,
        "static_split_passed": float(streaming["static_split_max_abs_error"]) <= 1e-6,
    }
    return measurements, passed


def _performance_payload(run: PathingPerformanceRun) -> dict[str, object]:
    return {
        "audio_timing": summarize_timings(run.block_ms),
        "audio_warmups": 20,
        "diagnostics_enabled": run.diagnostics_enabled,
        "environment_count": run.environment_count,
        "measured_audio_blocks": len(run.block_ms),
        "measured_updates": len(run.update_ms),
        "path_update_timing": summarize_timings(run.update_ms),
        "path_update_warmups": 10,
        "peak_memory_mib": run.peak_memory_mib,
    }


def _performance_results(
    runs: list[PathingPerformanceRun],
) -> tuple[dict[str, object], bool]:
    primary = [run for run in runs if not run.diagnostics_enabled]
    diagnostics = [run for run in runs if run.diagnostics_enabled]
    passed = len(primary) == 2 and all(
        summarize_timings(run.block_ms)["p95_ms"] <= BLOCK_P95_MS
        and summarize_timings(run.update_ms)["p95_ms"]
        <= UPDATE_P95_MS[run.environment_count]
        for run in primary
    )
    return (
        {
            "audio_block_p95_limit_ms": BLOCK_P95_MS,
            "diagnostics": [_performance_payload(run) for run in diagnostics],
            "passed": passed,
            "primary": [_performance_payload(run) for run in primary],
            "update_p95_limits_ms": UPDATE_P95_MS,
        },
        passed,
    )


def _blocked_run(probe: RuntimeProbe) -> RiskRetirementRun:
    report = build_report(
        runtime=probe.runtime, observations=blocked_observations(probe)
    )
    evaluation = evaluate_report(report)
    blocker = probe.external_blocker or "selected provider runtime is inaccessible"
    return RiskRetirementRun(
        report,
        evaluation,
        {"runtime_probe": asdict(probe)},
        {"unavailable": np.empty(0, dtype=np.float32)},
        {"provider_version": SELECTED_PROVIDER_VERSION},
        (f"BLOCKED: {blocker}",),
    )


def qualify_steam_audio_r9_4(
    adapter: object,
    *,
    source_commit: str,
    source_tag: str,
    release_check: Mapping[str, object],
    build_configuration: Mapping[str, object],
) -> RiskRetirementRun:
    """Execute all R9.4 gates and retain measured failures as useful evidence."""

    probe = adapter.probe_runtime()
    if not probe.available:
        return _blocked_run(probe)
    expected_tag = f"v{SELECTED_PROVIDER_VERSION}"
    baseline_ok = (
        source_commit == SELECTED_SOURCE_COMMIT
        and source_tag == expected_tag
        and release_check.get("latest_stable_tag") == expected_tag
        and release_check.get("latest_stable_commit") == SELECTED_SOURCE_COMMIT
        and bool(build_configuration.get("verified"))
    )
    if not baseline_ok:
        baseline_observation = RiskObservation(
            GATE_IDS[0],
            "fail",
            "The selected source, stable tag, or Embree build did not match R9.3.",
            evidence(
                "runtime_probe",
                "provider_native",
                "provenance.json",
                "Exact source, release-tag, and build checks.",
            ),
        )
        blocker = "provider baseline must pass before behavioral R9.4 gates"
        blocked = tuple(
            RiskObservation(
                gate_id,
                "blocked",
                "The gate was not exercised because the provider baseline failed.",
                evidence(
                    "runtime_probe",
                    "provider_native",
                    "provenance.json",
                    blocker,
                ),
            )
            for gate_id in GATE_IDS[1:]
        )
        report = build_report(
            runtime=probe.runtime, observations=(baseline_observation, *blocked)
        )
        return RiskRetirementRun(
            report,
            evaluate_report(report),
            {"runtime_probe": asdict(probe)},
            {"baseline_failed": np.empty(0, dtype=np.float32)},
            {
                "build_configuration": build_configuration,
                "release_check": release_check,
                "source_commit": source_commit,
                "source_tag": source_tag,
            },
            ("Provider baseline failed; behavioral gates were not run.",),
        )

    assembly, assembly_arrays, assembly_passed = _assembly_results(adapter)
    pathing, pathing_arrays, signal_passed, dynamic_passed, diagnostics_passed = (
        _pathing_results(adapter)
    )
    timing_run = adapter.run_timing_qualification(pathing_fixtures()[1])
    timing, timing_passed = _timing_results(timing_run)
    performance_runs = [
        adapter.run_pathing_performance(
            pathing_fixtures()[0], environment_count=count, diagnostics=False
        )
        for count in (1, 4)
    ]
    performance_runs.append(
        adapter.run_pathing_performance(
            pathing_fixtures()[0], environment_count=1, diagnostics=True
        )
    )
    performance, performance_passed = _performance_results(performance_runs)
    observations = (
        RiskObservation(
            "provider_baseline",
            "pass",
            "The stable tag, source commit, Release build, and Embree "
            "configuration match R9.3.",
            evidence(
                "packaging_probe",
                "provider_native",
                "provenance.json",
                "Live stable-tag, source identity, and CMake cache evidence.",
            ),
        ),
        RiskObservation(
            "acoustic_proxy_transmission",
            "pass" if assembly_passed else "fail",
            "Closed paired provider proxies were measured for one to three "
            "assemblies and representation variants.",
            evidence(
                "runtime_measurement",
                "provider_native",
                "measurements.json",
                "Per-band loss, sequential accumulation, and equivalence measurements.",
            ),
        ),
        RiskObservation(
            "baked_pathing_signal",
            "pass" if signal_passed else "fail",
            "Baked UTD pathing was rendered as one independently scheduled "
            "omnidirectional signal per microphone.",
            evidence(
                "runtime_measurement",
                "mixed",
                "measurements.json",
                "Enabled/disabled levels and all-pair phase measurements.",
            ),
        ),
        RiskObservation(
            "dynamic_path_validation",
            "pass" if dynamic_passed else "fail",
            "A moved blocker exercised native path validation and "
            "alternate-path search.",
            evidence(
                "runtime_measurement",
                "provider_native",
                "measurements.json",
                "Occluded segments and validated/alternate output levels.",
            ),
        ),
        RiskObservation(
            "arrival_time_scheduling",
            "pass" if timing_passed else "fail",
            "The private streaming scheduler was checked for single application, "
            "block continuity, and provider-owned reflection timing.",
            evidence(
                "runtime_measurement",
                "mixed",
                "measurements.json",
                "Native and scheduled impulse peaks plus streaming continuity.",
            ),
        ),
        RiskObservation(
            "operating_cost",
            "pass" if performance_passed else "fail",
            "Path audio and dynamic path updates were measured separately for "
            "one and four environments.",
            evidence(
                "runtime_measurement",
                "mixed",
                "measurements.json",
                "Diagnostics-off p95 gates and separate diagnostic overhead.",
            ),
        ),
        RiskObservation(
            "path_diagnostics",
            "pass" if diagnostics_passed else "fail",
            "The supported provider callback was captured and bounded outside "
            "sensor frames.",
            evidence(
                "runtime_measurement",
                "provider_native",
                "measurements.json",
                "Per-source, microphone, and frame path segments.",
            ),
        ),
    )
    report = build_report(runtime=probe.runtime, observations=observations)
    evaluation = evaluate_report(report)
    arrays = {**assembly_arrays, **pathing_arrays, **timing_run.arrays}
    measurements = json_safe(
        {
            "assembly": assembly,
            "pathing": pathing,
            "performance": performance,
            "runtime_probe": asdict(probe),
            "timing": timing,
        }
    )
    provenance = json_safe(
        {
            "adapter": "SteamAudioR94Adapter",
            "build_configuration": build_configuration,
            "delay_ownership": {
                "direct": "ias_streaming_scheduler_when_native_zero_lag",
                "pathing": "ias_streaming_scheduler_when_native_zero_lag",
                "reflections": "provider_native_ir",
            },
            "pathing": {
                "deviation_model": "provider_default_utd",
                "output": (
                    "first_order_ambisonics_omnidirectional_component_per_microphone"
                ),
            },
            "post_render_gain_compensation": False,
            "release_check": release_check,
            "source_commit": source_commit,
            "source_tag": source_tag,
        }
    )
    log_lines = (
        f"Steam Audio source: {source_tag} @ {source_commit}",
        f"Provider baseline gate passed: {baseline_ok}",
        f"Acoustic proxy transmission gate passed: {assembly_passed}",
        f"Baked pathing signal gate passed: {signal_passed}",
        f"Dynamic path validation gate passed: {dynamic_passed}",
        f"Arrival-time scheduling gate passed: {timing_passed}",
        f"Operating-cost gate passed: {performance_passed}",
        f"Path diagnostics gate passed: {diagnostics_passed}",
        f"R10 admissions: {evaluation['admitted_capabilities']}",
    )
    return RiskRetirementRun(
        report,
        evaluation,
        measurements,
        arrays,
        provenance,
        log_lines,
    )


__all__ = ["qualify_steam_audio_r9_4"]
