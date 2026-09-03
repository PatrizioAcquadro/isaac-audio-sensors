from __future__ import annotations

import inspect
import json
import zipfile

import numpy as np
import pytest

from tools.qualification.geometry_acoustics.evaluation import (
    reevaluate_nvidia_rtx_acoustic,
)
from tools.qualification.geometry_acoustics.fixtures import (
    BLOCK_SAMPLES,
    MICROPHONE_IDS,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    common_fixtures,
    generated_impulse,
    generated_multitone,
    surface_points,
    write_fixture_assets,
)
from tools.qualification.geometry_acoustics.gmo import (
    classify_acoustic_gmo,
    expand_signal_way_ids,
)
from tools.qualification.geometry_acoustics.metrics import (
    dynamic_update_passes,
    interpolate_transmission_amplitude,
    performance_passes,
    phase_metrics,
    tone_levels_db,
    tone_losses_db,
    transmission_loss_db_to_amplitude,
)
from tools.qualification.geometry_acoustics.models import (
    DebugPathSample,
    SignalBlock,
    bounded_diagnostics,
)
from tools.qualification.geometry_acoustics.reporting import (
    CriterionObservation,
    Evidence,
    QualificationReportBuilder,
    build_coverage_summary,
    derive_status,
    deterministic_json,
    write_deterministic_npz,
)
from tools.qualification.geometry_acoustics.steam_audio import SteamAudioAdapter
from tools.qualification.geometry_acoustics_contract import CRITERIA, evaluate_report


def test_fixture_inventory_uses_planar_boundaries_and_real_openings() -> None:
    fixtures = common_fixtures()
    assert len(fixtures) == 23
    assert len({fixture.fixture_id for fixture in fixtures}) == len(fixtures)
    assert SAMPLE_RATE_HZ == 48_000
    assert BLOCK_SAMPLES == 960
    assert REPEAT_COUNT == 5
    assert all(
        sum(size == 0.0 for size in surface.size_xyz_m) == 1
        for fixture in fixtures
        for surface in fixture.surfaces
    )

    closed = next(
        item for item in fixtures if item.fixture_id == "connected_rooms_closed"
    )
    opened = next(
        item for item in fixtures if item.fixture_id == "connected_rooms_open"
    )
    assert closed.source_xyz_m == opened.source_xyz_m
    assert closed.array_xyz_m == opened.array_xyz_m
    assert {surface.assembly_id for surface in closed.surfaces} - {
        surface.assembly_id for surface in opened.surfaces
    } == {"door"}
    assert sum(surface.assembly_id == "shared_wall" for surface in opened.surfaces) == 3


def test_fragmented_fixture_preserves_one_acoustic_assembly() -> None:
    fragmented = next(
        fixture
        for fixture in common_fixtures()
        if fixture.fixture_id == "assembly_fragmented"
    )
    assert {surface.assembly_id for surface in fragmented.surfaces} == {"partition"}
    assert sum(surface.size_xyz_m[1] for surface in fragmented.surfaces) == 4.0
    assert all(len(surface_points(surface)) == 4 for surface in fragmented.surfaces)


def test_fixture_assets_are_deterministic_and_self_contained(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_assets = write_fixture_assets(first)
    second_assets = write_fixture_assets(second)
    assert first_assets.keys() == second_assets.keys()
    assert (first / "fixtures" / "phase_impulse_a.usda").read_bytes() == (
        second / "fixtures" / "phase_impulse_a.usda"
    ).read_bytes()
    manifest = json.loads((first / "fixture_manifest.json").read_text())
    assert manifest["fixture_revision"] == 2
    assert manifest["microphone_ids"] == list(MICROPHONE_IDS)
    assert generated_impulse().shape == (BLOCK_SAMPLES,)
    assert generated_multitone().shape == (BLOCK_SAMPLES,)


def test_signal_block_requires_microphone_sample_layout() -> None:
    block = SignalBlock(
        np.zeros((4, BLOCK_SAMPLES), dtype=np.float32),
        MICROPHONE_IDS,
        SAMPLE_RATE_HZ,
        {"complete_block": 1.0},
    )
    assert block.samples.shape == (4, BLOCK_SAMPLES)
    assert not block.samples.flags.writeable
    with pytest.raises(ValueError, match="microphone"):
        SignalBlock(
            np.zeros((3, BLOCK_SAMPLES), dtype=np.float32),
            MICROPHONE_IDS,
            SAMPLE_RATE_HZ,
            {},
        )


def test_transmission_mapping_uses_direct_effect_amplitude_gain() -> None:
    amplitude = transmission_loss_db_to_amplitude([0.0, 10.0, 20.0, 60.0])
    np.testing.assert_allclose(amplitude, [1.0, 10**-0.5, 0.1, 0.001])
    interpolated = interpolate_transmission_amplitude(
        [125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0],
        [12.0] * 6,
        STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    )
    np.testing.assert_allclose(interpolated, [10**-0.6] * 3)
    with pytest.raises(ValueError, match="non-negative"):
        transmission_loss_db_to_amplitude([-1.0])


def test_phase_uses_all_six_pairs_and_expected_fractional_alignment() -> None:
    reference = generated_impulse()
    absolute_lags = (0.0, 2.0, -1.0, 3.0)
    channels = np.stack(
        [
            reference,
            np.roll(reference, 2),
            np.roll(reference, -1),
            np.roll(reference, 3),
        ]
    )
    result = phase_metrics(channels, absolute_lags, MICROPHONE_IDS)
    assert result.passed
    assert len(result.microphone_pairs) == 6
    assert result.measured_lags_samples == (2, -1, 3, -3, 1, 4)


def test_authorized_bridge_uses_geometry_not_measured_alignment() -> None:
    impulse = generated_impulse()
    source = (3.0, 0.6, 1.2)
    microphones = ((0.08, 0.0, 1.2), (0.0, -0.08, 1.2))
    delayed = np.stack(
        [
            SteamAudioAdapter._delay_direct_path(impulse, source, mic)
            for mic in microphones
        ]
    )
    distances = [
        np.linalg.norm(np.asarray(source) - np.asarray(mic)) for mic in microphones
    ]
    expected = tuple(distance * SAMPLE_RATE_HZ / 343.0 for distance in distances)
    result = phase_metrics(delayed, expected, ("a", "b"))
    assert result.passed
    np.testing.assert_array_equal(
        delayed,
        np.stack(
            [
                SteamAudioAdapter._delay_direct_path(impulse, source, mic)
                for mic in microphones
            ]
        ),
    )


def test_tone_metrics_recover_steam_band_losses() -> None:
    reference = generated_multitone()
    levels = tone_levels_db(reference, sample_rate_hz=SAMPLE_RATE_HZ)
    assert levels.keys() == {"400", "2500", "15000"}
    observed = reference * np.float32(10.0 ** (-12.0 / 20.0))
    losses = tone_losses_db(reference, observed)
    np.testing.assert_allclose(list(losses.values()), [12.0, 12.0, 12.0])


def test_performance_and_refresh_thresholds_use_p95() -> None:
    assert performance_passes([19.0] * 200)
    assert not performance_passes([21.0] * 200)
    assert dynamic_update_passes([99.0] * 50, 1)
    assert dynamic_update_passes([249.0] * 50, 4)
    assert not dynamic_update_passes([101.0] * 50, 1)


def test_fixture_status_is_not_hardcoded_by_fixture_id() -> None:
    source = inspect.getsource(SteamAudioAdapter.run_fixture)
    assert "unsupported_indirect" not in source
    assert "fixture.fixture_id in" not in source
    assert "compatible=True" in source


def test_gmo_is_active_signal_ways_and_detects_noncontiguous_duplicates() -> None:
    result = classify_acoustic_gmo([0, 0, 1, 0], [1, 1, 2, 1], [0, 0, 0, 0])
    assert result.semantic == "active_transmitter_receiver_signal_ways"
    assert not result.is_passive_microphone_pcm
    assert result.signal_ways[0].sample_count == 3
    assert result.duplicate_keys == ((0, 1, 0),)


def test_gmo_signal_way_metadata_prefix_expands_to_waveform_samples() -> None:
    tx, rx, channel = expand_signal_way_ids(
        [0, 0, 0, 0, 99],
        [0, 1, 2, 3, 99],
        [4, 4, 4, 4, 99],
        signal_way_count=4,
        samples_per_way=320,
    )
    assert tx.shape == rx.shape == channel.shape == (1280,)
    assert [int(rx[index * 320]) for index in range(4)] == [0, 1, 2, 3]
    result = classify_acoustic_gmo(tx, rx, channel)
    assert [way.sample_count for way in result.signal_ways] == [320] * 4


def test_native_diagnostics_are_bounded_per_source_mic_frame() -> None:
    items = tuple(
        DebugPathSample("source", "front", 0, ((float(index), 0.0, 0.0),))
        for index in range(300)
    ) + tuple(
        DebugPathSample("source", "right", 0, ((float(index), 0.0, 0.0),))
        for index in range(10)
    )
    bounded = bounded_diagnostics(items)
    assert len(bounded) == 266
    assert sum(item.microphone_id == "front" for item in bounded) == 256


def _evidence(criterion_id: str) -> Evidence:
    if criterion_id == "licensing":
        return Evidence("official_license", "documentation", "LICENSE", "Evidence.")
    if criterion_id == "packaging":
        return Evidence("packaging_probe", "provider_native", "build.log", "Evidence.")
    if criterion_id in {"passive_audible_content", "isaac_runtime", "path_diagnostics"}:
        return Evidence("runtime_probe", "provider_native", "run.log", "Evidence.")
    return Evidence("runtime_measurement", "mixed", "measurements.json", "Evidence.")


def _built_report(candidate_id: str, failed: str | None = None) -> dict[str, object]:
    builder = QualificationReportBuilder(
        candidate_id=candidate_id,
        candidate_version="1.0.0",
        runtime={
            "hardware": "test host",
            "isaac_sim_version": "6.0.1-rc.7",
            "kit_version": "110.1.2",
            "platform": "linux-x86_64",
        },
    )
    for criterion in CRITERIA:
        builder.record(
            CriterionObservation(
                criterion.criterion_id,
                criterion.criterion_id != failed,
                "Measured result.",
                (_evidence(criterion.criterion_id),),
            )
        )
    return builder.build()


def test_report_status_distinguishes_executed_fail_from_unexercised_block() -> None:
    evidence = (Evidence("runtime_probe", "provider_native", "run.log", "Probe."),)
    incompatible = CriterionObservation("isaac_runtime", False, "No API.", evidence)
    blocked = CriterionObservation(
        "isaac_runtime", None, "Not exercised.", evidence, "harness unavailable"
    )
    assert derive_status(incompatible) == "fail"
    assert derive_status(blocked) == "blocked"
    with pytest.raises(ValueError, match="unknown"):
        derive_status(CriterionObservation("isaac_runtime", None, "Unknown.", evidence))


def test_summary_preserves_two_outcomes_without_ranking_or_selection() -> None:
    steam = _built_report("steam_audio", failed="acoustic_assembly_identity")
    rtx = _built_report("nvidia_rtx_acoustic", failed="passive_audible_content")
    summary = build_coverage_summary([rtx, steam])
    assert summary["reports_valid"] is True
    assert [row["candidate"]["id"] for row in summary["candidates"]] == [
        "steam_audio",
        "nvidia_rtx_acoustic",
    ]
    assert summary["candidates"][0]["core_integration_outcome"] == "qualified"
    assert summary["candidates"][0]["full_r10_outcome"] == "rejected"
    assert "selection" not in summary
    assert "ranking" not in summary


def test_rtx_rev2_is_derived_from_reused_evidence_without_rerun() -> None:
    rev1 = {
        "candidate": {"id": "nvidia_rtx_acoustic", "version": "3.0.0"},
        "contract_version": "r9.1",
        "runtime": {
            "hardware": "RTX 4090",
            "isaac_sim_version": "6.0.0",
            "kit_version": "110.1.2",
            "platform": "linux-x86_64",
        },
    }
    result = reevaluate_nvidia_rtx_acoustic(
        rev1_report=rev1,
        rev1_measurements_reference="build/validation/r9/nvidia/measurements.json",
        rev1_provenance_reference="build/validation/r9/nvidia/provenance.json",
    )
    evaluation = evaluate_report(result.report)
    assert result.provenance["rerun"] is False
    assert evaluation.core_integration_outcome == "rejected"
    assert "audio_block_performance" in evaluation.core_blocked_gates
    assert any(
        evidence["origin"] == "provider_native"
        for criterion in result.report["criteria"]
        for evidence in criterion["evidence"]
    )


def test_json_and_npz_serialization_are_byte_deterministic(tmp_path) -> None:
    assert deterministic_json({"b": 2, "a": 1}) == '{\n  "a": 1,\n  "b": 2\n}\n'
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    arrays = {"z": np.arange(3), "a": np.eye(2, dtype=np.float32)}
    write_deterministic_npz(first, arrays)
    write_deterministic_npz(second, arrays)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["a.npy", "z.npy"]
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
