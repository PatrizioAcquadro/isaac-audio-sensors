"""Execute corrected R9.2 qualification and derive both readiness profiles."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

import numpy as np

from tools.qualification.geometry_acoustics_contract import CRITERIA

from .fixtures import (
    IAS_REFERENCE_TRANSMISSION_LOSS_DB,
    IAS_TRANSMISSION_FREQUENCIES_HZ,
    MICROPHONE_IDS,
    QUAD_FRONT_OFFSETS_M,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    FixtureSpec,
    common_fixtures,
)
from .metrics import (
    ASSEMBLY_EQUIVALENCE_DB,
    BLOCK_P95_MS,
    DOOR_OPEN_GAIN_DB,
    PARTITION_SUM_TOLERANCE_DB,
    TRANSMISSION_DYNAMIC_RANGE_DB,
    TRANSMISSION_TONE_TOLERANCE_DB,
    amplitude_drops_db,
    dynamic_update_passes,
    expected_tdoa_samples,
    free_field_amplitude_passes,
    interpolate_transmission_amplitude,
    phase_metrics,
    rms_db,
    summarize_timings,
)
from .models import CandidateAdapter, FixtureRun, PerformanceRun, RuntimeProbe
from .reporting import CriterionObservation, Evidence, QualificationReportBuilder

_NUMERICAL_FLOOR_DB = 20.0 * math.log10(float(np.finfo(np.float32).eps))
_INDIRECT_MARGIN_DB = 20.0
_DYNAMIC_CHANGE_DB = 3.0


@dataclass(frozen=True, slots=True)
class QualificationRun:
    report: dict[str, object]
    measurements: dict[str, object]
    arrays: dict[str, np.ndarray]
    provenance: dict[str, object]
    log_lines: tuple[str, ...]


def _text(*parts: str) -> str:
    return " ".join(parts)


def _reference(candidate_id: str, filename: str) -> str:
    return f"build/validation/r9/rev2/{candidate_id}/{filename}"


def _blocked_run(
    candidate_id: str,
    candidate_version: str,
    probe: RuntimeProbe,
) -> QualificationRun:
    builder = QualificationReportBuilder(
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        runtime=probe.runtime,
    )
    blocker = probe.external_blocker or "provider runtime is inaccessible"
    for criterion in CRITERIA:
        builder.record(
            CriterionObservation(
                criterion.criterion_id,
                None,
                "The criterion could not be exercised.",
                (
                    Evidence(
                        "runtime_probe",
                        "provider_native",
                        _reference(candidate_id, "run.log"),
                        blocker,
                    ),
                ),
                blocker,
            )
        )
    return QualificationRun(
        builder.build(),
        {"runtime_probe": _probe_payload(probe)},
        {"unavailable": np.empty(0, dtype=np.float32)},
        {"candidate_version": candidate_version},
        (f"BLOCKED: {blocker}",),
    )


def _probe_payload(probe: RuntimeProbe) -> dict[str, object]:
    return {
        "available": probe.available,
        "capabilities": dict(probe.capabilities),
        "details": dict(probe.details),
        "external_blocker": probe.external_blocker,
        "provider_version": probe.provider_version,
        "runtime": dict(probe.runtime),
    }


def _performance_payload(run: PerformanceRun) -> dict[str, object]:
    return {
        "diagnostics_enabled": run.diagnostics_enabled,
        "environment_count": run.environment_count,
        "measured_audio_blocks": run.measured_blocks,
        "measured_refreshes": len(run.update_ms),
        "peak_memory_mib": run.peak_memory_mib,
        "audio_timing": summarize_timings(run.block_ms),
        "refresh_timing": summarize_timings(run.update_ms) if run.update_ms else None,
        "audio_warmups": run.warmup_blocks,
        "refresh_warmups": run.update_warmups,
    }


def _fixture_payload(run: FixtureRun) -> dict[str, object]:
    payload: dict[str, object] = {
        "compatible": run.compatible,
        "component_shapes": {
            name: list(np.asarray(samples).shape)
            for name, samples in run.component_samples.items()
        },
        "diagnostic_count": len(run.diagnostics),
        "fixture_id": run.fixture_id,
        "incompatibility": run.incompatibility,
        "measurements": dict(run.measurements),
        "repetition": run.repetition,
    }
    if run.block is not None:
        payload["block"] = {
            "microphone_ids": list(run.block.microphone_ids),
            "sample_rate_hz": run.block.sample_rate_hz,
            "shape": list(run.block.samples.shape),
            "timing_ms": dict(run.block.timing_ms),
        }
    return payload


def _run_all_fixtures(
    adapter: CandidateAdapter,
) -> tuple[list[FixtureRun], dict[str, np.ndarray]]:
    runs: list[FixtureRun] = []
    arrays: dict[str, np.ndarray] = {}
    for fixture in common_fixtures():
        for repetition in range(REPEAT_COUNT):
            run = adapter.run_fixture(fixture, repetition=repetition)
            runs.append(run)
            if run.block is not None:
                arrays[f"{fixture.fixture_id}__r{repetition}__combined"] = (
                    run.block.samples
                )
            for component, samples in run.component_samples.items():
                arrays[f"{fixture.fixture_id}__r{repetition}__{component}"] = samples
    return runs, arrays


def _runs_by_fixture(runs: list[FixtureRun], fixture_id: str) -> list[FixtureRun]:
    return [run for run in runs if run.fixture_id == fixture_id]


def _fixture(fixture_id: str) -> FixtureSpec:
    return next(item for item in common_fixtures() if item.fixture_id == fixture_id)


def _microphone_positions(fixture: FixtureSpec) -> list[tuple[float, float, float]]:
    return [
        tuple(
            coordinate + delta
            for coordinate, delta in zip(fixture.array_xyz_m, offset, strict=True)
        )
        for offset in QUAD_FRONT_OFFSETS_M
    ]


def _phase_results(runs: list[FixtureRun], component: str) -> list[dict[str, object]]:
    results = []
    for fixture_id in ("phase_impulse_a", "phase_impulse_b"):
        fixture = _fixture(fixture_id)
        expected = expected_tdoa_samples(
            fixture.source_xyz_m,
            _microphone_positions(fixture),
            sample_rate_hz=SAMPLE_RATE_HZ,
        )
        for run in _runs_by_fixture(runs, fixture_id):
            if component == "combined":
                samples = run.block.samples if run.block is not None else None
            else:
                samples = run.component_samples.get(component)
            if samples is None:
                continue
            result = phase_metrics(samples, expected, MICROPHONE_IDS)
            results.append(
                {
                    "fixture_id": fixture_id,
                    "repetition": run.repetition,
                    **asdict(result),
                }
            )
    return results


def _mean_tone_loss(runs: list[FixtureRun], fixture_id: str) -> dict[str, float]:
    curves = [
        run.measurements["tone_loss_db"]
        for run in _runs_by_fixture(runs, fixture_id)
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


def _within(
    curve: Mapping[str, float], target: Mapping[str, float], tolerance: float
) -> bool:
    return curve.keys() == target.keys() and all(
        abs(float(curve[band]) - float(target[band])) <= tolerance for band in curve
    )


def _finite_level(samples: np.ndarray) -> float:
    return max(rms_db(samples), _NUMERICAL_FLOOR_DB)


def _indirect_result(
    runs: list[FixtureRun], fixture_id: str, control_db: float
) -> dict[str, object]:
    levels = [
        _finite_level(run.component_samples["reflections"][0])
        for run in _runs_by_fixture(runs, fixture_id)
        if "reflections" in run.component_samples
    ]
    valid = [level for level in levels if level > _NUMERICAL_FLOOR_DB]
    median_db = float(np.median(levels)) if levels else _NUMERICAL_FLOOR_DB
    margin_db = median_db - max(control_db, _NUMERICAL_FLOOR_DB)
    return {
        "levels_db": levels,
        "margin_db": margin_db,
        "median_db": median_db,
        "passed": len(valid) >= 4 and margin_db >= _INDIRECT_MARGIN_DB,
        "valid_repetitions": len(valid),
    }


def _dynamic_metrics(runs: list[FixtureRun]) -> dict[str, object]:
    geometry_results: dict[str, object] = {}
    for fixture_id in ("move_door", "move_large_object"):
        fixture_runs = _runs_by_fixture(runs, fixture_id)
        changes = []
        counters_ok = []
        for run in fixture_runs:
            delta = run.measurements.get("dynamic_level_delta_db", {})
            assert isinstance(delta, Mapping)
            finite_changes = [
                abs(float(delta[key]))
                for key in ("direct", "reflections")
                if key in delta and math.isfinite(float(delta[key]))
            ]
            changes.append(max(finite_changes, default=0.0))
            counter_delta = run.measurements.get("update_counter_delta", {})
            assert isinstance(counter_delta, Mapping)
            counters_ok.append(
                int(counter_delta.get("static_mesh_create", 0)) == 0
                and int(counter_delta.get("instance_transform_update", 0)) == 1
                and not bool(
                    run.measurements.get("static_geometry_recreated_during_update")
                )
            )
        geometry_results[fixture_id] = {
            "changes_db": changes,
            "counter_evidence_passed": bool(counters_ok) and all(counters_ok),
            "passed": len(changes) == REPEAT_COUNT
            and all(change >= _DYNAMIC_CHANGE_DB for change in changes)
            and all(counters_ok),
        }

    motion_results: dict[str, object] = {}
    for fixture_id in ("move_source", "move_array"):
        fixture = _fixture(fixture_id)
        fixture_runs = _runs_by_fixture(runs, fixture_id)
        passed = []
        phase_changes = []
        for run in fixture_runs:
            before = run.component_samples.get("before_bridged_direct")
            after = run.component_samples.get("bridged_direct")
            distance_delta = float(
                run.measurements.get("geometric_distance_delta_m", 0.0)
            )
            level_delta = 0.0
            if before is not None and after is not None:
                level_delta = _finite_level(after[0]) - _finite_level(before[0])
            if fixture_id == "move_source":
                after_source = (
                    fixture.source_xyz_m[0] + 0.5,
                    fixture.source_xyz_m[1] + 0.5,
                    fixture.source_xyz_m[2],
                )
                after_array = fixture.array_xyz_m
            else:
                after_source = fixture.source_xyz_m
                after_array = (
                    fixture.array_xyz_m[0],
                    fixture.array_xyz_m[1] + 0.5,
                    fixture.array_xyz_m[2],
                )
            before_expected = expected_tdoa_samples(
                fixture.source_xyz_m,
                _microphone_positions(fixture),
                sample_rate_hz=SAMPLE_RATE_HZ,
            )
            after_positions = [
                tuple(
                    coordinate + delta
                    for coordinate, delta in zip(after_array, offset, strict=True)
                )
                for offset in QUAD_FRONT_OFFSETS_M
            ]
            after_expected = expected_tdoa_samples(
                after_source,
                after_positions,
                sample_rate_hz=SAMPLE_RATE_HZ,
            )
            before_phase = (
                phase_metrics(before, before_expected, MICROPHONE_IDS)
                if before is not None
                else None
            )
            after_phase = (
                phase_metrics(after, after_expected, MICROPHONE_IDS)
                if after is not None
                else None
            )
            direction_ok = False
            if before_phase is not None and after_phase is not None:
                expected_delta = np.asarray(
                    after_phase.expected_lags_samples
                ) - np.asarray(before_phase.expected_lags_samples)
                measured_delta = np.asarray(
                    after_phase.measured_lags_samples
                ) - np.asarray(before_phase.measured_lags_samples)
                informative = np.abs(expected_delta) >= 0.75
                direction_ok = bool(
                    np.any(
                        informative
                        & (np.sign(expected_delta) == np.sign(measured_delta))
                    )
                )
            phase_changes.append(direction_ok)
            passed.append(
                distance_delta != 0.0
                and level_delta != 0.0
                and math.copysign(1.0, level_delta)
                == -math.copysign(1.0, distance_delta)
                and direction_ok
            )
        motion_results[fixture_id] = {
            "passed": len(passed) == REPEAT_COUNT and all(passed),
            "tdoa_direction_passed": phase_changes,
            "repetitions": passed,
        }
    overall = all(
        bool(result["passed"])
        for result in (*geometry_results.values(), *motion_results.values())
    )
    return {"geometry": geometry_results, "motion": motion_results, "passed": overall}


def qualify_steam_audio(
    adapter: CandidateAdapter,
    *,
    source_commit: str,
    build_configuration: dict[str, object],
) -> QualificationRun:
    probe = adapter.probe_runtime()
    if not probe.available:
        return _blocked_run(adapter.candidate_id, adapter.candidate_version, probe)
    runs, arrays = _run_all_fixtures(adapter)
    performance = [
        adapter.run_performance(environment_count=count, diagnostics=False)
        for count in (1, 4)
    ]

    bridged_phase = _phase_results(runs, "combined")
    native_phase = _phase_results(runs, "native_direct")
    phase_ok = len(bridged_phase) == 2 * REPEAT_COUNT and all(
        bool(result["passed"]) for result in bridged_phase
    )
    native_zero_lag = bool(native_phase) and all(
        max(abs(int(value)) for value in result["measured_lags_samples"]) == 0
        for result in native_phase
    )

    impulse_runs = [
        *_runs_by_fixture(runs, "phase_impulse_a"),
        *_runs_by_fixture(runs, "phase_impulse_b"),
    ]
    multitone_runs = _runs_by_fixture(runs, "passive_multitone")
    passive_ok = all(
        run.block is not None
        and run.block.samples.shape == (len(MICROPHONE_IDS), 960)
        and all(
            _finite_level(channel) > _NUMERICAL_FLOOR_DB
            for channel in run.block.samples
        )
        and len({channel.tobytes() for channel in run.block.samples})
        == len(MICROPHONE_IDS)
        for run in (*impulse_runs, *multitone_runs)
    )

    amplitude_results = []
    for repetition in range(REPEAT_COUNT):
        levels = [
            _runs_by_fixture(runs, fixture_id)[repetition].block.samples[0]
            for fixture_id in ("distance_1_5m", "distance_3m", "distance_6m")
        ]
        drops = amplitude_drops_db(levels)
        amplitude_results.append(
            {"drops_db": drops, "passed": free_field_amplitude_passes(levels)}
        )
    amplitude_ok = all(result["passed"] for result in amplitude_results)

    direct_run = _runs_by_fixture(runs, "direct_path")
    opaque_run = _runs_by_fixture(runs, "occlusion_opaque")
    curve_run = _runs_by_fixture(runs, "transmission_curve")
    direct_levels = [
        _finite_level(run.component_samples["bridged_direct"][0]) for run in direct_run
    ]
    opaque_losses = [float(run.measurements["direct_loss_db"]) for run in opaque_run]
    curve_losses = [float(run.measurements["direct_loss_db"]) for run in curve_run]
    direct_ok = (
        len(direct_levels) == REPEAT_COUNT
        and all(level > _NUMERICAL_FLOOR_DB for level in direct_levels)
        and all(loss >= 20.0 for loss in opaque_losses)
        and all(0.0 < loss < 100.0 for loss in curve_losses)
    )

    control_levels = [
        _finite_level(run.component_samples["reflections"][0])
        for run in _runs_by_fixture(runs, "reflection_control")
    ]
    control_db = float(np.median(control_levels))
    room_indirect = _indirect_result(runs, "reflective_room", control_db)
    corridor_indirect = _indirect_result(runs, "l_corridor_nlos", control_db)
    corridor_direct_losses = [
        float(run.measurements["direct_loss_db"])
        for run in _runs_by_fixture(runs, "l_corridor_nlos")
    ]
    indirect_ok = (
        bool(room_indirect["passed"])
        and bool(corridor_indirect["passed"])
        and all(loss >= 20.0 for loss in corridor_direct_losses)
    )

    closed_runs = _runs_by_fixture(runs, "connected_rooms_closed")
    open_runs = _runs_by_fixture(runs, "connected_rooms_open")
    door_gains_db = [
        _finite_level(open_run.block.samples[0])
        - _finite_level(closed_run.block.samples[0])
        for closed_run, open_run in zip(closed_runs, open_runs, strict=True)
    ]
    connected_ok = (
        len(door_gains_db) == REPEAT_COUNT
        and float(np.median(door_gains_db)) >= DOOR_OPEN_GAIN_DB
        and _fixture("connected_rooms_closed").source_xyz_m
        == _fixture("connected_rooms_open").source_xyz_m
    )

    mono_loss = _mean_tone_loss(runs, "assembly_mono")
    fragmented_loss = _mean_tone_loss(runs, "assembly_fragmented")
    two_partition_loss = _mean_tone_loss(runs, "assembly_two_partitions")
    summed_mono_loss = {band: 2.0 * value for band, value in mono_loss.items()}
    assembly_ok = mono_loss.keys() == fragmented_loss.keys() and all(
        abs(mono_loss[band] - fragmented_loss[band]) <= ASSEMBLY_EQUIVALENCE_DB
        for band in mono_loss
    )
    sequential_partition_ok = _within(
        two_partition_loss,
        summed_mono_loss,
        PARTITION_SUM_TOLERANCE_DB,
    )

    measured_curve = _mean_tone_loss(runs, "transmission_curve")
    expected_amplitudes = interpolate_transmission_amplitude(
        IAS_TRANSMISSION_FREQUENCIES_HZ,
        IAS_REFERENCE_TRANSMISSION_LOSS_DB,
        STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    )
    expected_curve = {
        str(int(frequency)): float(-20.0 * math.log10(amplitude))
        for frequency, amplitude in zip(
            STEAM_AUDIO_BAND_FREQUENCIES_HZ,
            expected_amplitudes,
            strict=True,
        )
    }
    loss_12db = _mean_tone_loss(runs, "transmission_12db")
    loss_60db = _mean_tone_loss(runs, "transmission_60db")
    dynamic_range_db = {band: loss_60db[band] - loss_12db[band] for band in loss_12db}
    ray_counts = {
        int(run.measurements["num_transmission_surfaces"])
        for run in runs
        if "num_transmission_surfaces" in run.measurements
    }
    transmission_ok = (
        _within(measured_curve, expected_curve, TRANSMISSION_TONE_TOLERANCE_DB)
        and all(
            value >= TRANSMISSION_DYNAMIC_RANGE_DB
            for value in dynamic_range_db.values()
        )
        and len(ray_counts) == 1
        and sequential_partition_ok
    )

    dynamics = _dynamic_metrics(runs)
    audio_performance_ok = all(
        len(run.block_ms) == 200
        and run.warmup_blocks == 20
        and summarize_timings(run.block_ms)["p95_ms"] <= BLOCK_P95_MS
        for run in performance
    )
    refresh_performance_ok = all(
        len(run.update_ms) == 50
        and run.update_warmups == 10
        and dynamic_update_passes(run.update_ms, run.environment_count)
        for run in performance
    )

    measurement_reference = _reference(adapter.candidate_id, "measurements.json")
    runtime_reference = _reference(adapter.candidate_id, "provenance.json")
    builder = QualificationReportBuilder(
        candidate_id=adapter.candidate_id,
        candidate_version=adapter.candidate_version,
        runtime=probe.runtime,
    )
    observations = (
        CriterionObservation(
            "passive_audible_content",
            passive_ok,
            _text(
                "Generated impulses and a file-backed three-band WAV produced",
                "distinct non-zero microphone blocks.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "provider_native",
                    measurement_reference,
                    "Impulse and WAV fixture outputs.",
                ),
            ),
        ),
        CriterionObservation(
            "phase_coherent_microphone_signals",
            phase_ok,
            _text(
                "All six microphone pairs were measured at two oblique source poses.",
                "Native direct output remained zero-lag; the geometric IAS bridge",
                "supplied time of flight.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "Separate native and bridge phase metrics.",
                ),
            ),
        ),
        CriterionObservation(
            "scene_geometry_and_dynamics",
            bool(dynamics["passed"]),
            _text(
                "Planar Embree assemblies, instance transforms, source motion,",
                "and array motion were measured without static-mesh recreation.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "Measured output changes and native lifecycle counters.",
                ),
            ),
        ),
        CriterionObservation(
            "direct_occlusion_transmission",
            direct_ok,
            _text(
                "Distance-only, opaque, and transmitting planar boundaries were",
                "compared at identical source-receiver distances.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "provider_native",
                    measurement_reference,
                    "Separated direct-path fixture measurements.",
                ),
            ),
        ),
        CriterionObservation(
            "indirect_nlos_propagation",
            indirect_ok,
            _text(
                "Real-time provider reflections were rendered for an enclosed room",
                "and an occluded corridor over five repetitions.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "provider_native",
                    measurement_reference,
                    "Reflection IR output, silent control, and numerical floor.",
                ),
            ),
        ),
        CriterionObservation(
            "relative_amplitude_coherence",
            amplitude_ok,
            _text(
                "The same signal was measured at 1.5, 3, and 6 metres with the",
                "authorized propagation-delay bridge enabled.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "Doubling-distance amplitude drops.",
                ),
            ),
        ),
        CriterionObservation(
            "isaac_runtime",
            True,
            _text(
                "The pinned shared library executed through ctypes in the intended",
                "Isaac Python interpreter.",
            ),
            (
                Evidence(
                    "runtime_probe",
                    "provider_native",
                    runtime_reference,
                    "Context, Embree, scene, simulator, source, and effect probe.",
                ),
            ),
        ),
        CriterionObservation(
            "packaging",
            bool(build_configuration.get("verified")),
            _text(
                "The pinned source build produced a Release shared library with",
                "Embree enabled.",
            ),
            (
                Evidence(
                    "packaging_probe",
                    "provider_native",
                    runtime_reference,
                    "Pinned source commit and CMake cache values.",
                ),
            ),
        ),
        CriterionObservation(
            "licensing",
            True,
            "Steam Audio 4.8.1 source is licensed under Apache-2.0.",
            (
                Evidence(
                    "official_license",
                    "documentation",
                    "https://github.com/ValveSoftware/steam-audio/blob/v4.8.1/LICENSE",
                    "Official Apache-2.0 license.",
                ),
            ),
        ),
        CriterionObservation(
            "audio_block_performance",
            audio_performance_ok,
            _text(
                "Persistent four-microphone direct, reflection, and bridge rendering",
                "was measured independently of acoustic refresh.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "20 warm-ups and 200 blocks for one/four environments.",
                ),
            ),
        ),
        CriterionObservation(
            "connected_space_propagation",
            connected_ok,
            _text(
                "Two enclosed rooms retained their shared wall while only the",
                "physical door surface was opened.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "provider_native",
                    measurement_reference,
                    "Closed/open door gain at unchanged source pose.",
                ),
            ),
        ),
        CriterionObservation(
            "acoustic_assembly_identity",
            assembly_ok,
            _text(
                "IAS grouping preserved one acoustic assembly across equivalent",
                "mono and fragmented surface meshes.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "Mono and fragmented loss curves.",
                ),
            ),
        ),
        CriterionObservation(
            "frequency_dependent_transmission",
            transmission_ok,
            _text(
                "Direct Effect waveform gains were measured at 400/2500/15000 Hz",
                "with one global transmission-surface count.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "mixed",
                    measurement_reference,
                    "Provider bands, sequential partitions, and 12/60 dB controls.",
                ),
            ),
        ),
        CriterionObservation(
            "acoustic_refresh_performance",
            refresh_performance_ok,
            _text(
                "Dynamic instance commit plus direct/reflection refresh was timed",
                "separately from audio rendering.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    "provider_native",
                    measurement_reference,
                    "10 warm-ups and 50 measured refreshes for one/four environments.",
                ),
            ),
        ),
        CriterionObservation(
            "path_diagnostics",
            None,
            "No path/ray diagnostics were claimed or timed.",
            (
                Evidence(
                    "runtime_probe",
                    "provider_native",
                    runtime_reference,
                    "The corrected harness did not enable a native diagnostic stream.",
                ),
            ),
            "native diagnostics were not exercised",
        ),
    )
    for observation in observations:
        builder.record(observation)

    performance_payload = [_performance_payload(run) for run in performance]
    measurements = {
        "amplitude": {"repetitions": amplitude_results, "passed": amplitude_ok},
        "assembly": {
            "fragmented_loss_db": fragmented_loss,
            "mono_loss_db": mono_loss,
            "passed": assembly_ok,
            "sequential_partition_passed": sequential_partition_ok,
            "summed_mono_loss_db": summed_mono_loss,
            "two_partition_loss_db": two_partition_loss,
        },
        "connected_spaces": {
            "door_open_gain_db": door_gains_db,
            "median_door_open_gain_db": float(np.median(door_gains_db)),
            "passed": connected_ok,
        },
        "direct_propagation": {
            "curve_direct_losses_db": curve_losses,
            "direct_levels_db": direct_levels,
            "opaque_losses_db": opaque_losses,
            "passed": direct_ok,
        },
        "dynamics": dynamics,
        "fixture_runs": [_fixture_payload(run) for run in runs],
        "indirect": {
            "control_levels_db": control_levels,
            "corridor": corridor_indirect,
            "corridor_direct_losses_db": corridor_direct_losses,
            "numerical_floor_db": _NUMERICAL_FLOOR_DB,
            "passed": indirect_ok,
            "reflective_room": room_indirect,
        },
        "performance": performance_payload,
        "phase": {
            "bridge": bridged_phase,
            "native": native_phase,
            "native_zero_lag": native_zero_lag,
            "passed": phase_ok,
        },
        "runtime_probe": _probe_payload(probe),
        "transmission": {
            "dynamic_range_db": dynamic_range_db,
            "expected_curve_db": expected_curve,
            "global_num_transmission_surfaces": sorted(ray_counts),
            "loss_12db": loss_12db,
            "loss_60db": loss_60db,
            "measured_curve_db": measured_curve,
            "passed": transmission_ok,
            "sequential_partition_passed": sequential_partition_ok,
        },
    }
    provenance = {
        "adapter": (
            "tools.qualification.geometry_acoustics.steam_audio.SteamAudioAdapter"
        ),
        "bridge_scope": [
            "geometric source-to-microphone propagation delay",
            "shared input timeline with one output per microphone",
            "assembly fragment grouping",
        ],
        "build_configuration": build_configuration,
        "candidate_version": adapter.candidate_version,
        "direct_effect_semantics": "three-band EQ coefficients applied to waveform",
        "scene_api_semantics": "surface transmission documented as energy fraction",
        "source_commit": source_commit,
        "source_tag": "v4.8.1",
        "transmission_mapping": "10^(-loss_db/20)",
        "transmission_semantics_discrepancy": {
            "direct_effect": "https://valvesoftware.github.io/steam-audio/doc/capi/direct-effect.html",
            "scene": "https://valvesoftware.github.io/steam-audio/doc/capi/scene.html",
        },
    }
    return QualificationRun(
        builder.build(),
        measurements,
        arrays,
        provenance,
        (
            f"Steam Audio source commit: {source_commit}",
            f"Fixture runs: {len(runs)}",
            f"Native direct output zero-lag: {native_zero_lag}",
            f"IAS bridge phase gate passed: {phase_ok}",
            f"Direct propagation gate passed: {direct_ok}",
            f"Indirect NLOS gate passed: {indirect_ok}",
            f"Full assembly gate passed: {assembly_ok}",
            f"Full transmission gate passed: {transmission_ok}",
            f"Audio-block performance gate passed: {audio_performance_ok}",
            f"Acoustic-refresh performance gate passed: {refresh_performance_ok}",
        ),
    )


def reevaluate_nvidia_rtx_acoustic(
    *,
    rev1_report: Mapping[str, object],
    rev1_measurements_reference: str,
    rev1_provenance_reference: str,
) -> QualificationRun:
    """Map already-recorded RTX evidence to rev2 without rerunning Isaac."""

    candidate = rev1_report["candidate"]
    runtime = rev1_report["runtime"]
    assert isinstance(candidate, Mapping)
    assert isinstance(runtime, Mapping)
    candidate_id = str(candidate["id"])
    candidate_version = str(candidate["version"])
    builder = QualificationReportBuilder(
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        runtime={str(key): str(value) for key, value in runtime.items()},
    )
    measurement = Evidence(
        "runtime_measurement",
        "provider_native",
        rev1_measurements_reference,
        "Reused rev1 event-driven GMO and timing measurements; no rev2 rerun.",
    )
    probe = Evidence(
        "runtime_probe",
        "provider_native",
        rev1_provenance_reference,
        "Reused exact extension and active-sensor semantic probe; no rev2 rerun.",
    )
    blocked_measurement = (measurement,)
    observations = (
        CriterionObservation(
            "passive_audible_content",
            False,
            _text(
                "The measured CHIRP/AM transmitter-receiver interface accepted no",
                "arbitrary passive PCM.",
            ),
            (probe,),
        ),
        CriterionObservation(
            "phase_coherent_microphone_signals",
            False,
            _text(
                "Measured GMO signal ways were active returns, not four raw passive",
                "microphone signals.",
            ),
            (probe,),
        ),
        CriterionObservation(
            "scene_geometry_and_dynamics",
            True,
            _text(
                "Motion BVH and dynamic GPU sensor output were exercised in the",
                "intended runtime.",
            ),
            (measurement,),
        ),
        CriterionObservation(
            "direct_occlusion_transmission",
            False,
            _text(
                "The exercised interface exposed no passive direct-effect microphone",
                "waveform to qualify.",
            ),
            (measurement,),
        ),
        CriterionObservation(
            "indirect_nlos_propagation",
            False,
            _text(
                "Active WPM returns cannot supply the required passive audible",
                "NLOS waveform.",
            ),
            (measurement,),
        ),
        CriterionObservation(
            "relative_amplitude_coherence",
            False,
            "Active return amplitudes do not form the required passive array signal.",
            (measurement,),
        ),
        CriterionObservation(
            "isaac_runtime",
            True,
            _text(
                "The exact acoustic extension produced GMO through an event-driven",
                "writer with Motion BVH enabled.",
            ),
            (probe,),
        ),
        CriterionObservation(
            "packaging",
            False,
            _text(
                "The installed proprietary extension is runtime-available but has no",
                "source-build redistribution path for this SDK.",
            ),
            (
                Evidence(
                    "packaging_probe",
                    "documentation",
                    rev1_provenance_reference,
                    "Reused installed-package provenance.",
                ),
            ),
        ),
        CriterionObservation(
            "licensing",
            False,
            "The bundled provider license did not establish SDK redistribution rights.",
            (
                Evidence(
                    "official_license",
                    "documentation",
                    rev1_provenance_reference,
                    "Reused installed license evidence.",
                ),
            ),
        ),
        CriterionObservation(
            "audio_block_performance",
            None,
            "No four-passive-microphone audio block was rendered.",
            blocked_measurement,
            "rev1 evidence did not exercise the rev2 audio workload",
        ),
        CriterionObservation(
            "connected_space_propagation",
            None,
            "No passive two-room door fixture was exercised.",
            blocked_measurement,
            "rev1 harness lacked this passive waveform",
        ),
        CriterionObservation(
            "acoustic_assembly_identity",
            None,
            "No passive mono/fragmented/sequential assembly campaign was exercised.",
            blocked_measurement,
            "rev1 harness lacked this passive waveform",
        ),
        CriterionObservation(
            "frequency_dependent_transmission",
            None,
            "No passive provider-band transmission curve was exercised.",
            blocked_measurement,
            "rev1 harness lacked this passive waveform",
        ),
        CriterionObservation(
            "acoustic_refresh_performance",
            None,
            "Rev1 timings do not match the separated 10-warm-up/50-refresh workload.",
            blocked_measurement,
            "rev1 timing evidence is not comparable",
        ),
        CriterionObservation(
            "path_diagnostics",
            None,
            "No bounded native path stream was measured.",
            (probe,),
            "native diagnostics were not exercised",
        ),
    )
    for observation in observations:
        builder.record(observation)
    return QualificationRun(
        builder.build(),
        {
            "evidence_reused": True,
            "rev1_measurements_reference": rev1_measurements_reference,
            "rev1_provenance_reference": rev1_provenance_reference,
        },
        {"reused_evidence_only": np.empty(0, dtype=np.float32)},
        {
            "candidate_version": candidate_version,
            "evidence_reused": True,
            "rerun": False,
            "source_contract_version": rev1_report.get("contract_version"),
        },
        (
            "RTX Acoustic was not rerun.",
            "Rev2 statuses were derived only from the preserved rev1 runtime evidence.",
        ),
    )


def qualify_nvidia_rtx_acoustic(
    adapter: CandidateAdapter,
    *,
    license_reference: str,
    package_reference: str,
    package_version: str,
    captured_arrays: Callable[[], dict[str, np.ndarray]],
) -> QualificationRun:
    """Retain the legacy entry point while preventing accidental rev2 claims."""

    del adapter, license_reference, package_reference, package_version, captured_arrays
    raise RuntimeError(
        "R9.1 rev2 reuses the preserved RTX evidence; run "
        "reuse_nvidia_rtx_acoustic.py instead of rerunning the provider."
    )
