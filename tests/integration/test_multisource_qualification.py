"""Check evaluation semantics independently of candidate performance."""

import numpy as np
import pytest

pytest.importorskip("pyroomacoustics")
pytest.importorskip("soundfile")

from tools.qualification.doa_04_4.cases import ASSETS, make_cases, match


def unit(bearing):
    angle = np.radians(bearing)
    return [np.cos(angle), np.sin(angle), 0.0]


def test_matching_counts_misses_and_spurious_events():
    truth = [unit(-40), unit(40)]
    assert match([unit(-40)], truth)["fn"] == 1
    assert match([], truth)["abstained"]
    result = match([unit(40), unit(-40), unit(170)], truth)
    assert (result["tp"], result["fp"], result["fn"]) == (2, 1, 0)
    assert not result["count_correct"]


def test_matching_is_circular_and_rejects_wrong_directions():
    assert match([unit(179)], [unit(-179)])["errors"] == pytest.approx([2])
    result = match([unit(150)], [unit(0)])
    assert result["count_correct"]
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)
    assert result["errors"] == []


def test_matching_prioritizes_admissible_cardinality_before_error():
    result = match([unit(0), unit(25)], [unit(5), unit(-25)])
    assert result["tp"] == 2
    assert sorted(result["errors"]) == pytest.approx([20, 25])


def test_partitions_are_disjoint_and_cover_pair_orientations():
    seen_assets = set()
    seen_seeds = set()
    for split, assets in ASSETS.items():
        assert seen_assets.isdisjoint(assets)
        seen_assets.update(assets)
        cases = make_cases(split, 4)
        seeds = {case.seed for case in cases}
        assert len(seeds) == len(cases) == 864
        assert seen_seeds.isdisjoint(seeds)
        seen_seeds.update(seeds)
        for array in ("raised", "tetra"):
            for condition in {case.condition for case in cases}:
                assert {
                    case.orientation
                    for case in cases
                    if case.array == array
                    and case.condition == condition
                    and case.count == 2
                } == {"azimuth", "elevation"}


def test_frequency_order_resolves_disjoint_bands_without_supplied_count():
    from scipy.signal import butter, sosfilt

    from tools.qualification.doa_04_4.candidates import FrequencyOrderCandidate
    from tools.qualification.doa_04_4.cases import ARRAYS, FS

    positions = ARRAYS["square"]
    rng = np.random.default_rng(82)
    spectra = np.zeros((len(positions), 4097), dtype=complex)
    frequencies = np.fft.rfftfreq(8192, 1 / FS)
    truth = [unit(-35), unit(60)]
    for direction, band in zip(truth, ([300, 1800], [2200, 6000]), strict=True):
        source = sosfilt(
            butter(4, band, btype="bandpass", fs=FS, output="sos"),
            rng.standard_normal(8192),
        )
        source *= 0.03 / np.sqrt(np.mean(source**2))
        delay = positions @ direction / 343
        spectra += np.fft.rfft(source)[None] * np.exp(
            2j * np.pi * delay[:, None] * frequencies
        )
    samples = np.fft.irfft(spectra, n=8192)[:, 2000:6000]
    samples.setflags(write=False)
    localizer = FrequencyOrderCandidate(0.11)
    found, _ = localizer.localize(samples, positions, FS)
    result = match(found, truth)
    assert result["count_correct"] and result["tp"] == 2
    # A changed call cannot leave an audio history in this window-local candidate.
    localizer.localize(np.zeros_like(samples), positions, FS)
    repeated, _ = localizer.localize(samples, positions, FS)
    np.testing.assert_array_equal(found, repeated)
    order = [2, 0, 3, 1]
    permuted, _ = localizer.localize(samples[order], positions[order], FS)
    assert match(permuted, truth)["tp"] == 2


def test_confirmation_keeps_original_acceptance_criteria():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "tools/qualification/doa_04_4"
    initial = json.loads((root / "final_protocol.json").read_text())
    confirmation = json.loads((root / "confirmation_protocol.json").read_text())
    verification = json.loads((root / "verification_protocol.json").read_text())
    validation = json.loads((root / "validation_protocol.json").read_text())
    qualification = json.loads((root / "qualification_protocol.json").read_text())
    assessment = json.loads((root / "assessment_protocol.json").read_text())
    for field in ("nominal", "operational", "stress", "compute", "response", "roles"):
        assert initial[field] == confirmation[field]
        assert initial[field] == verification[field]
        assert initial[field] == validation[field]
        assert initial[field] == qualification[field]
        assert initial[field] == assessment[field]


@pytest.mark.parametrize("array", ("triangle", "square", "raised", "tetra"))
def test_covariance_music_rejects_noiseless_sidelobes_and_preserves_pairs(array):
    from tools.qualification.doa_04_4.candidates import FrequencyOrderCandidate
    from tools.qualification.doa_04_4.cases import ARRAYS
    from tools.qualification.doa_04_4.diagnostics import transition_signal

    positions = ARRAYS[array]
    samples, truth, _, _ = transition_signal(positions, 103)
    localizer = FrequencyOrderCandidate(
        0.03, relative_loading=0.0001, refit_threshold=0.11
    )
    for end, count in ((24000, 1), (36000, 2), (48000, 1)):
        window = samples[:, end - 4000 : end]
        window.setflags(write=False)
        found, _ = localizer.localize(window, positions, 16000)
        result = match(found, truth[:count])
        assert result["count_correct"] and result["tp"] == count
    found, diagnostic = localizer.localize(np.zeros_like(window), positions, 16000)
    assert len(found) == 0 and diagnostic["status"] == "no_events"
    with pytest.raises(ValueError, match="non-collinear"):
        localizer.localize(window[:2], positions[:2], 16000)


def test_native_ssl_releases_plans_after_repeated_windows():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if not (root / "build/qualification/doa/04_4/native_ssl.so").exists():
        pytest.skip("isolated ODAS evaluation binding is not built")
    script = """
import numpy as np
from tools.qualification.doa_04_4.candidates import OdasCandidate
from tools.qualification.doa_04_4.cases import ARRAYS
rng = np.random.default_rng(814)
for _ in range(2):
    candidate = OdasCandidate(.05)
    for array in ('triangle', 'square'):
        for _ in range(8):
            values = rng.normal(0, .03, (len(ARRAYS[array]), 4000))
            candidate.localize(values, ARRAYS[array], 16000)
    candidate.close()
    candidate.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bandlimited_transition_propagation_preserves_channel_response():
    from tools.qualification.doa_04_4.cases import ARRAYS
    from tools.qualification.doa_04_4.diagnostics import transition_signal

    samples, _, _, _ = transition_signal(
        ARRAYS["raised"], 1120000, randomize=True, bandlimited=True
    )
    rms = np.sqrt(np.mean(samples[:, 14000:25000] ** 2, axis=1))
    assert rms.max() / rms.min() < 1.01


@pytest.mark.parametrize(
    "candidate,threshold", (("covariance_contrast", 0.014), ("covariance_aic", 0.011))
)
def test_covariance_contrast_keeps_a_ten_db_weaker_overlapping_source(
    candidate, threshold
):
    from tools.qualification.doa_04_4.cases import ARRAYS, FS
    from tools.qualification.doa_04_4.evaluate import construct

    positions = ARRAYS["square"]
    rng = np.random.default_rng(143)
    frequencies = np.fft.rfftfreq(8192, 1 / FS)
    spectrum = np.zeros((len(positions), len(frequencies)), dtype=complex)
    truth = [unit(-35), unit(60)]
    for index, direction in enumerate(truth):
        source = rng.standard_normal(8192) * 0.03 * 10 ** (-index / 2)
        delay = positions @ direction / 343
        spectrum += np.fft.rfft(source)[None] * np.exp(
            2j * np.pi * frequencies[None] * delay[:, None]
        )
    samples = np.fft.irfft(spectrum, n=8192)[:, 2000:6000]
    samples += rng.normal(0, 0.001, samples.shape)
    localizer = construct(candidate, threshold)
    found, _ = localizer.localize(samples, positions, FS)
    result = match(found, truth)
    assert result["count_correct"] and result["tp"] == 2


def test_noise_only_frequencies_do_not_dilute_narrowband_events():
    from tools.qualification.doa_04_4.cases import ARRAYS, FS
    from tools.qualification.doa_04_4.evaluate import construct

    positions = ARRAYS["square"]
    rng = np.random.default_rng(429)
    truth = np.array([unit(np.degrees(-0.6)), unit(np.degrees(1.1))])
    frequency = np.fft.rfftfreq(8192, 1 / FS)
    mixture = np.zeros((4, len(frequency)), dtype=complex)
    for band, direction in zip(((500, 800), (1500, 1800)), truth, strict=True):
        source = np.fft.rfft(rng.normal(size=8192))
        source[(frequency < band[0]) | (frequency > band[1])] = 0
        source *= 0.03 / np.std(np.fft.irfft(source, n=8192))
        mixture += source[None] * np.exp(
            2j * np.pi * frequency[None] * (positions @ direction)[:, None] / 343
        )
    samples = np.fft.irfft(mixture, n=8192)[:, 2000:6000]
    samples += rng.normal(0, 0.024, samples.shape)
    localizer = construct("weighted_covariance_aic", 0.01)
    found, _ = localizer.localize(samples, positions, FS)
    result = match(found, truth)
    assert result["count_correct"] and result["tp"] == 2


def test_missing_transition_response_cannot_pass_admission():
    import json
    from pathlib import Path

    from tools.qualification.doa_04_4.admission import diagnostic_failures

    root = Path(__file__).resolve().parents[2] / "tools/qualification/doa_04_4"
    protocol = json.loads((root / "assessment_protocol.json").read_text())
    result = {
        "idle": {
            kind: {"windows": 100, "false_event_windows": 0}
            for kind in ("silence", "uncorrelated", "diffuse")
        },
        "compute_warm_p95_ms": 1,
        "compute_warm_max_ms": 2,
        "responses": [{"delay_ms": delay} for delay in (150, 150, None, 200)],
    }
    assert "unresolved_transition" in diagnostic_failures(result, protocol)
    result["responses"][2]["delay_ms"] = 300
    assert diagnostic_failures(result, protocol) == []
