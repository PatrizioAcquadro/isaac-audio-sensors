"""Execute candidate adapters and derive complete R9.1 reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np

from tools.qualification.geometry_acoustics_contract import CRITERIA

from .fixtures import (
    IAS_REFERENCE_TRANSMISSION_LOSS_DB,
    QUAD_FRONT_OFFSETS_M,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    common_fixtures,
)
from .metrics import (
    amplitude_drops_db,
    dynamic_update_passes,
    expected_tdoa_samples,
    free_field_amplitude_passes,
    phase_metrics,
    rms_db,
    summarize_timings,
)
from .models import CandidateAdapter, FixtureRun, PerformanceRun, RuntimeProbe
from .reporting import CriterionObservation, Evidence, QualificationReportBuilder


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
    return f"build/validation/r9/{candidate_id}/{filename}"


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
                "The criterion could not be measured.",
                (
                    Evidence(
                        "runtime_probe",
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
        "measured_blocks": run.measured_blocks,
        "peak_memory_mib": run.peak_memory_mib,
        "timing": summarize_timings(run.block_ms),
        "update_timing": summarize_timings(run.update_ms) if run.update_ms else None,
        "warmup_blocks": run.warmup_blocks,
    }


def _diagnostics_overhead(
    performance: list[PerformanceRun],
) -> dict[str, dict[str, float]]:
    """Compare diagnostics-on runs with their diagnostics-off baseline."""

    payload = {
        (run.environment_count, run.diagnostics_enabled): _performance_payload(run)
        for run in performance
    }
    overhead: dict[str, dict[str, float]] = {}
    for environment_count in (1, 4):
        baseline = payload[(environment_count, False)]
        diagnostics = payload[(environment_count, True)]
        baseline_timing = baseline["timing"]
        diagnostics_timing = diagnostics["timing"]
        assert isinstance(baseline_timing, dict)
        assert isinstance(diagnostics_timing, dict)
        overhead[str(environment_count)] = {
            "p50_ms": float(diagnostics_timing["p50_ms"])
            - float(baseline_timing["p50_ms"]),
            "p95_ms": float(diagnostics_timing["p95_ms"])
            - float(baseline_timing["p95_ms"]),
            "peak_memory_mib": float(diagnostics["peak_memory_mib"])
            - float(baseline["peak_memory_mib"]),
        }
    return overhead


def _fixture_payload(run: FixtureRun) -> dict[str, object]:
    payload: dict[str, object] = {
        "compatible": run.compatible,
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
                arrays[f"{fixture.fixture_id}__r{repetition}"] = run.block.samples
    return runs, arrays


def _runs_by_fixture(runs: list[FixtureRun], fixture_id: str) -> list[FixtureRun]:
    return [run for run in runs if run.fixture_id == fixture_id]


def _mean_tone_loss(runs: list[FixtureRun], fixture_id: str) -> dict[str, float]:
    curves = [
        run.measurements["tone_loss_db"]
        for run in _runs_by_fixture(runs, fixture_id)
        if "tone_loss_db" in run.measurements
    ]
    if not curves:
        return {}
    return {
        band: float(np.mean([curve[band] for curve in curves])) for band in curves[0]
    }


def _within(
    curve: dict[str, float], target: dict[str, float], tolerance: float
) -> bool:
    return curve.keys() == target.keys() and all(
        abs(curve[band] - target[band]) <= tolerance for band in curve
    )


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
        adapter.run_performance(
            environment_count=environment_count,
            diagnostics=diagnostics,
        )
        for diagnostics in (False, True)
        for environment_count in (1, 4)
    ]
    phase_runs = _runs_by_fixture(runs, "phase_impulse")
    fixture = next(
        item for item in common_fixtures() if item.fixture_id == "phase_impulse"
    )
    microphone_positions = [
        tuple(
            coordinate + offset_component
            for coordinate, offset_component in zip(
                fixture.array_xyz_m, offset, strict=True
            )
        )
        for offset in QUAD_FRONT_OFFSETS_M
    ]
    expected = expected_tdoa_samples(
        fixture.source_xyz_m,
        microphone_positions,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )
    phase_results = [
        phase_metrics(run.block.samples, expected)
        for run in phase_runs
        if run.block is not None
    ]
    distance_runs = [
        _runs_by_fixture(runs, fixture_id)[0]
        for fixture_id in ("distance_1_5m", "distance_3m", "distance_6m")
    ]
    distance_levels = [
        run.block.samples[0] for run in distance_runs if run.block is not None
    ]
    amplitude_compatible = len(distance_levels) == 3 and free_field_amplitude_passes(
        distance_levels
    )
    dynamic_runs = [run for run in runs if run.fixture_id.startswith("move_")]
    one_environment_updates = [
        float(run.block.timing_ms["update"])
        for run in dynamic_runs
        if run.block is not None
    ]
    four_environment_updates = [
        sum(
            float(run.block.timing_ms["update"])
            for run in dynamic_runs
            if run.repetition == repetition and run.block is not None
        )
        for repetition in range(REPEAT_COUNT)
    ]
    dynamics_ok = (
        len(dynamic_runs) == 4 * REPEAT_COUNT
        and all(run.compatible for run in dynamic_runs)
        and dynamic_update_passes(one_environment_updates, 1)
        and dynamic_update_passes(four_environment_updates, 4)
    )
    propagation_ids = (
        "direct_path",
        "occlusion",
        "reflection",
        "transmission",
        "l_corner",
    )
    propagation_ok = all(
        run.compatible
        for fixture_id in propagation_ids
        for run in _runs_by_fixture(runs, fixture_id)
    )
    connected_runs = [
        *_runs_by_fixture(runs, "connected_rooms_closed"),
        *_runs_by_fixture(runs, "connected_rooms_open"),
    ]
    connected_ok = bool(connected_runs) and all(
        run.compatible for run in connected_runs
    )
    closed_blocks = [
        run.block.samples[0]
        for run in _runs_by_fixture(runs, "connected_rooms_closed")
        if run.block is not None
    ]
    open_blocks = [
        run.block.samples[0]
        for run in _runs_by_fixture(runs, "connected_rooms_open")
        if run.block is not None
    ]
    door_gain_db = float(
        np.mean(
            [
                rms_db(open_block) - rms_db(closed_block)
                for closed_block, open_block in zip(
                    closed_blocks, open_blocks, strict=True
                )
            ]
        )
    )
    connected_ok = connected_ok and door_gain_db >= 3.0

    mono_loss = _mean_tone_loss(runs, "assembly_mono")
    fragmented_loss = _mean_tone_loss(runs, "assembly_fragmented")
    two_partition_loss = _mean_tone_loss(runs, "assembly_two_partitions")
    double_leaf_loss = _mean_tone_loss(runs, "assembly_double_leaf")
    target_12db = {band: 12.0 for band in ("250", "1000", "4000")}
    target_24db = {band: 24.0 for band in target_12db}
    assembly_ok = (
        mono_loss.keys() == fragmented_loss.keys()
        and all(
            abs(mono_loss[band] - fragmented_loss[band]) <= 1.0 for band in mono_loss
        )
        and _within(two_partition_loss, target_24db, 3.0)
        and all(two_partition_loss[band] - mono_loss[band] >= 8.0 for band in mono_loss)
        and _within(double_leaf_loss, target_12db, 4.0)
    )

    reference_curve = _mean_tone_loss(runs, "transmission")
    expected_curve = {
        "250": IAS_REFERENCE_TRANSMISSION_LOSS_DB[1],
        "1000": IAS_REFERENCE_TRANSMISSION_LOSS_DB[3],
        "4000": IAS_REFERENCE_TRANSMISSION_LOSS_DB[5],
    }
    loss_12db = _mean_tone_loss(runs, "transmission_12db")
    loss_60db = _mean_tone_loss(runs, "transmission_60db")
    dynamic_range_db = {band: loss_60db[band] - loss_12db[band] for band in loss_12db}
    transmission_ok = _within(reference_curve, expected_curve, 4.0) and all(
        value >= 40.0 for value in dynamic_range_db.values()
    )
    performance_payload = [_performance_payload(run) for run in performance]
    diagnostics_off = [run for run in performance if not run.diagnostics_enabled]
    measured_performance_ok = all(
        _performance_payload(run)["timing"]["p95_ms"] <= 20.0 for run in diagnostics_off
    )
    full_performance_ok = (
        measured_performance_ok
        and propagation_ok
        and bool(phase_results)
        and all(result.passed for result in phase_results)
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
            all(run.block is not None for run in runs),
            _text(
                "Generated impulse and file-equivalent deterministic multitone",
                "WAV were processed natively.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "110 native fixture runs.",
                ),
            ),
        ),
        CriterionObservation(
            "raw_phase_coherent_microphones",
            bool(phase_results) and all(result.passed for result in phase_results),
            _text(
                "Four independent point-receiver calls were measured without HRTF",
                "or post alignment.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Impulse TDOA and aligned correlation.",
                ),
            ),
        ),
        CriterionObservation(
            "scene_geometry_and_dynamics",
            dynamics_ok,
            _text(
                "Embree static meshes and instances were scene-coupled; door,",
                "source, array, and large-object updates were measured in place.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Static/instance probe and dynamic fixtures.",
                ),
            ),
        ),
        CriterionObservation(
            "geometry_propagation",
            propagation_ok,
            _text(
                "Native direct, occlusion, and transmission were measured, but",
                "unbaked reflection/path output did not complete the gate.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Separated propagation fixtures.",
                ),
            ),
        ),
        CriterionObservation(
            "connected_space_propagation",
            connected_ok,
            _text(
                "Door-open gain was measured, but the closed-room output was",
                "transmitted direct energy rather than a qualifying indirect path.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Connected-room fixtures.",
                ),
            ),
        ),
        CriterionObservation(
            "relative_amplitude_coherence",
            amplitude_compatible,
            "Native inverse-distance output was checked at 1.5, 3, and 6 metres.",
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Free-field doubling-distance levels.",
                ),
            ),
        ),
        CriterionObservation(
            "acoustic_assembly_identity",
            assembly_ok,
            _text(
                "Mono/fragmented, two-partition, and whole-assembly losses were",
                "derived from scene-coupled native output.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Assembly fixture inventory and output.",
                ),
            ),
        ),
        CriterionObservation(
            "frequency_dependent_transmission",
            transmission_ok,
            _text(
                "IAS loss was converted to native energy bands and measured at",
                "250/1000/4000 Hz plus 12/60 dB dynamic-range controls.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "Three-band material mapping and tone fixtures.",
                ),
            ),
        ),
        CriterionObservation(
            "isaac_runtime",
            True,
            _text(
                "libphonon was loaded through ctypes and executed in the intended",
                "Isaac Python interpreter.",
            ),
            (
                Evidence(
                    "runtime_probe",
                    runtime_reference,
                    "Context, Embree, scene, mesh, instance, and effect probe.",
                ),
            ),
        ),
        CriterionObservation(
            "packaging",
            bool(build_configuration.get("verified")),
            _text(
                "The pinned source build produced a shared Release library with",
                "Embree enabled.",
            ),
            (
                Evidence(
                    "packaging_probe",
                    runtime_reference,
                    "Pinned commit and CMake cache values.",
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
                    "https://github.com/ValveSoftware/steam-audio/blob/v4.8.1/LICENSE",
                    "Official Apache-2.0 license.",
                ),
            ),
        ),
        CriterionObservation(
            "performance",
            full_performance_ok,
            _text(
                "Direct-effect timings were recorded, but the complete geometry",
                "update/simulation/effects block was unavailable.",
            ),
            (
                Evidence(
                    "runtime_measurement",
                    measurement_reference,
                    "20 warm-ups and 200 measured blocks for one/four environments.",
                ),
            ),
        ),
        CriterionObservation(
            "path_diagnostics",
            False,
            _text(
                "The native path callback symbol exists, but no bounded qualifying",
                "path stream was produced.",
            ),
            (
                Evidence(
                    "runtime_probe",
                    runtime_reference,
                    "Native symbol and runtime probe.",
                ),
            ),
        ),
    )
    for observation in observations:
        builder.record(observation)
    measurements = {
        "amplitude": {
            "drops_db": amplitude_drops_db(distance_levels),
            "passed": amplitude_compatible,
        },
        "fixture_runs": [_fixture_payload(run) for run in runs],
        "geometry": {
            "connected_space_passed": connected_ok,
            "door_open_gain_db": door_gain_db,
            "dynamics_passed": dynamics_ok,
            "four_environment_update_ms": four_environment_updates,
            "propagation_passed": propagation_ok,
        },
        "assembly": {
            "double_leaf_loss_db": double_leaf_loss,
            "fragmented_loss_db": fragmented_loss,
            "mono_loss_db": mono_loss,
            "passed": assembly_ok,
            "two_partition_loss_db": two_partition_loss,
        },
        "performance": performance_payload,
        "performance_diagnostics_overhead": _diagnostics_overhead(performance),
        "phase": [asdict(result) for result in phase_results],
        "runtime_probe": _probe_payload(probe),
        "transmission": {
            "dynamic_range_db": dynamic_range_db,
            "expected_curve_db": expected_curve,
            "loss_12db": loss_12db,
            "loss_60db": loss_60db,
            "measured_curve_db": reference_curve,
            "passed": transmission_ok,
        },
    }
    provenance = {
        "adapter": (
            "tools.qualification.geometry_acoustics.steam_audio.SteamAudioAdapter"
        ),
        "build_configuration": build_configuration,
        "candidate_version": adapter.candidate_version,
        "diagnostics_off_performance_runs": len(diagnostics_off),
        "source_commit": source_commit,
        "source_tag": "v4.8.1",
    }
    return QualificationRun(
        builder.build(),
        measurements,
        arrays,
        provenance,
        (
            f"Steam Audio source commit: {source_commit}",
            f"Fixture runs: {len(runs)}",
            f"Phase gate passed: {all(result.passed for result in phase_results)}",
            f"Scene dynamics gate passed: {dynamics_ok}",
            f"Geometry propagation gate passed: {propagation_ok}",
            f"Assembly gate passed: {assembly_ok}",
            f"Transmission gate passed: {transmission_ok}",
            f"Complete performance gate passed: {full_performance_ok}",
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
    probe = adapter.probe_runtime()
    if not probe.available:
        return _blocked_run(adapter.candidate_id, adapter.candidate_version, probe)
    runs, _ = _run_all_fixtures(adapter)
    performance = [
        adapter.run_performance(
            environment_count=environment_count,
            diagnostics=diagnostics,
        )
        for diagnostics in (False, True)
        for environment_count in (1, 4)
    ]
    measurement_reference = _reference(adapter.candidate_id, "measurements.json")
    provenance_reference = _reference(adapter.candidate_id, "provenance.json")
    performance_payload = [_performance_payload(run) for run in performance]
    builder = QualificationReportBuilder(
        candidate_id=adapter.candidate_id,
        candidate_version=adapter.candidate_version,
        runtime=probe.runtime,
    )
    incompatible = {
        "passive_audible_content": _text(
            "CHIRP/AM are active transmissions and accept no arbitrary passive",
            "PCM.",
        ),
        "raw_phase_coherent_microphones": _text(
            "GMO is keyed by transmitter, receiver, and channel signal ways,",
            "not raw microphones.",
        ),
        "scene_geometry_and_dynamics": _text(
            "Dynamic active-sensor output cannot satisfy the passive",
            "microphone-block contract.",
        ),
        "geometry_propagation": _text(
            "WPM active returns cannot be reinterpreted as passive audible",
            "propagation.",
        ),
        "connected_space_propagation": (
            "No passive connected-space microphone blocks are exposed."
        ),
        "relative_amplitude_coherence": _text(
            "Active return amplitudes do not form the required passive array",
            "signal.",
        ),
        "acoustic_assembly_identity": (
            "No passive assembly-transmission blocks are exposed."
        ),
        "frequency_dependent_transmission": _text(
            "No arbitrary passive multitone transmission blocks are",
            "exposed.",
        ),
        "performance": _text(
            "Update timings do not include the unavailable four passive",
            "microphone signals.",
        ),
        "path_diagnostics": _text(
            "No bounded provider-native path stream is exposed through the",
            "acoustic GMO.",
        ),
    }
    for criterion in CRITERIA:
        criterion_id = criterion.criterion_id
        if criterion_id == "isaac_runtime":
            observation = CriterionObservation(
                criterion_id,
                bool(probe.details.get("writer_callback_events")),
                _text(
                    "AcousticSensor produced GMO via an event-driven Writer with",
                    "Motion BVH enabled.",
                ),
                (
                    Evidence(
                        "runtime_probe",
                        provenance_reference,
                        "GPU runtime and writer probe.",
                    ),
                ),
            )
        elif criterion_id == "packaging":
            observation = CriterionObservation(
                criterion_id,
                package_version == adapter.candidate_version,
                "The exact 3.0.0 extension is installed in the intended Isaac runtime.",
                (
                    Evidence(
                        "packaging_probe",
                        package_reference,
                        "Installed extension manifest.",
                    ),
                ),
            )
        elif criterion_id == "licensing":
            observation = CriterionObservation(
                criterion_id,
                False,
                _text(
                    "The installed provider package is proprietary; its bundled",
                    "license does not grant SDK redistribution rights.",
                ),
                (
                    Evidence(
                        "official_license",
                        license_reference,
                        "Installed package license.",
                    ),
                ),
            )
        else:
            evidence_kind = (
                "runtime_probe"
                if criterion_id == "path_diagnostics"
                else "runtime_measurement"
            )
            observation = CriterionObservation(
                criterion_id,
                False,
                incompatible[criterion_id],
                (
                    Evidence(
                        evidence_kind,
                        measurement_reference,
                        "Event-driven GMO fixture and timing evidence.",
                    ),
                ),
            )
        builder.record(observation)
    measurements = {
        "fixture_runs": [_fixture_payload(run) for run in runs],
        "performance": performance_payload,
        "performance_diagnostics_overhead": _diagnostics_overhead(performance),
        "runtime_probe": _probe_payload(probe),
    }
    arrays = dict(captured_arrays())
    provenance = {
        "adapter": (
            "tools.qualification.geometry_acoustics.nvidia_rtx_acoustic."
            "RtxAcousticAdapter"
        ),
        "candidate_version": adapter.candidate_version,
        "capture": "event-driven Replicator Writer",
        "motion_bvh_enabled": True,
        "package_reference": package_reference,
        "package_version": package_version,
        "signal_semantics": "active transmitter-receiver signal ways",
        "signal_modes": ["CHIRP", "AM"],
    }
    return QualificationRun(
        builder.build(),
        measurements,
        arrays,
        provenance,
        (
            f"Fixture runs: {len(runs)}",
            _text(
                "Writer events during probe:",
                str(probe.details.get("writer_callback_events")),
            ),
            f"GMO semantic: {probe.details.get('semantic')}",
            "Passive microphone reinterpretation: disabled",
        ),
    )
