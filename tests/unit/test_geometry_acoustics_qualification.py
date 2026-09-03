from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from tools.qualification.geometry_acoustics.fixtures import (
    BLOCK_SAMPLES,
    MICROPHONE_IDS,
    REPEAT_COUNT,
    SAMPLE_RATE_HZ,
    STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    common_fixtures,
    generated_impulse,
    generated_multitone,
    write_fixture_assets,
)
from tools.qualification.geometry_acoustics.gmo import (
    classify_acoustic_gmo,
    expand_signal_way_ids,
)
from tools.qualification.geometry_acoustics.metrics import (
    amplitude_drops_db,
    dynamic_update_passes,
    free_field_amplitude_passes,
    interpolate_transmission_energy,
    performance_passes,
    phase_metrics,
    tone_levels_db,
    tone_losses_db,
    transmission_loss_db_to_energy,
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
from tools.qualification.geometry_acoustics_contract import CRITERIA, evaluate_report


def test_common_fixture_inventory_and_parameters_are_frozen() -> None:
    fixtures = common_fixtures()
    assert len(fixtures) == 22
    assert len({fixture.fixture_id for fixture in fixtures}) == len(fixtures)
    assert SAMPLE_RATE_HZ == 48_000
    assert BLOCK_SAMPLES == 960
    assert REPEAT_COUNT == 5
    fragmented = next(
        fixture for fixture in fixtures if fixture.fixture_id == "assembly_fragmented"
    )
    assert {barrier.assembly_id for barrier in fragmented.barriers} == {"partition"}
    assert sum(barrier.size_xyz_m[1] for barrier in fragmented.barriers) == 4.0


def test_fixture_assets_are_deterministic_and_self_contained(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_assets = write_fixture_assets(first)
    second_assets = write_fixture_assets(second)
    assert first_assets.keys() == second_assets.keys()
    assert (first / "fixtures" / "phase_impulse.usda").read_bytes() == (
        second / "fixtures" / "phase_impulse.usda"
    ).read_bytes()
    manifest = json.loads((first / "fixture_manifest.json").read_text())
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


def test_material_conversion_uses_energy_fraction_and_frequency_interpolation() -> None:
    energy = transmission_loss_db_to_energy([0.0, 10.0, 20.0, 60.0])
    np.testing.assert_allclose(energy, [1.0, 0.1, 0.01, 1e-6])
    interpolated = interpolate_transmission_energy(
        [125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0],
        [12.0] * 6,
        STEAM_AUDIO_BAND_FREQUENCIES_HZ,
    )
    np.testing.assert_allclose(interpolated, [10**-1.2] * 3)
    with pytest.raises(ValueError, match="non-negative"):
        transmission_loss_db_to_energy([-1.0])


def test_phase_and_amplitude_thresholds() -> None:
    reference = generated_impulse()
    expected_lags = (0.0, 2.0, -1.0, 3.0)
    channels = np.stack(
        [
            reference,
            np.roll(reference, 2),
            np.roll(reference, -1),
            np.roll(reference, 3),
        ]
    )
    result = phase_metrics(channels, expected_lags)
    assert result.passed
    assert result.measured_lags_samples == (0, 2, -1, 3)
    levels = [np.ones(128), np.ones(128) / 2.0, np.ones(128) / 4.0]
    np.testing.assert_allclose(amplitude_drops_db(levels), [-6.0206, -6.0206])
    assert free_field_amplitude_passes(levels)


def test_tone_metrics_recover_three_band_losses() -> None:
    reference = generated_multitone()
    levels = tone_levels_db(reference, sample_rate_hz=SAMPLE_RATE_HZ)
    assert levels.keys() == {"250", "1000", "4000"}
    observed = reference * np.float32(10.0 ** (-12.0 / 20.0))
    losses = tone_losses_db(reference, observed)
    np.testing.assert_allclose(list(losses.values()), [12.0, 12.0, 12.0])


def test_performance_and_dynamic_thresholds_use_p95() -> None:
    assert performance_passes([19.0] * 200)
    assert not performance_passes([21.0] * 200)
    assert dynamic_update_passes([99.0] * 5, 1)
    assert dynamic_update_passes([249.0] * 5, 4)
    assert not dynamic_update_passes([101.0] * 5, 1)


def test_gmo_is_active_signal_ways_and_detects_noncontiguous_duplicates() -> None:
    result = classify_acoustic_gmo(
        [0, 0, 1, 0],
        [1, 1, 2, 1],
        [0, 0, 0, 0],
    )
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


def _evidence_kind(criterion_id: str) -> str:
    if criterion_id == "licensing":
        return "official_license"
    if criterion_id == "packaging":
        return "packaging_probe"
    if criterion_id in {
        "raw_phase_coherent_microphones",
        "geometry_propagation",
        "connected_space_propagation",
        "relative_amplitude_coherence",
        "acoustic_assembly_identity",
        "frequency_dependent_transmission",
        "performance",
    }:
        return "runtime_measurement"
    return "runtime_probe"


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
                (
                    Evidence(
                        _evidence_kind(criterion.criterion_id),
                        "build/validation/r9/measurement.json",
                        "Evidence.",
                    ),
                ),
            )
        )
    return builder.build()


def test_report_status_distinguishes_incompatibility_from_external_blocker() -> None:
    evidence = (Evidence("runtime_probe", "run.log", "Probe."),)
    incompatible = CriterionObservation("isaac_runtime", False, "No API.", evidence)
    blocked = CriterionObservation(
        "isaac_runtime", None, "Runtime inaccessible.", evidence, "sandbox denied GPU"
    )
    assert derive_status(incompatible) == "fail"
    assert derive_status(blocked) == "blocked"
    with pytest.raises(ValueError, match="unknown"):
        derive_status(CriterionObservation("isaac_runtime", None, "Unknown.", evidence))


def test_builder_and_coverage_summary_are_derived_without_selection() -> None:
    steam = _built_report("steam_audio", failed="raw_phase_coherent_microphones")
    rtx = _built_report("nvidia_rtx_acoustic", failed="passive_audible_content")
    assert evaluate_report(steam).outcome == "rejected"
    summary = build_coverage_summary([rtx, steam])
    assert summary["complete"] is True
    assert [row["candidate"]["id"] for row in summary["candidates"]] == [
        "steam_audio",
        "nvidia_rtx_acoustic",
    ]
    assert "selection" not in summary
    assert "ranking" not in summary


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
