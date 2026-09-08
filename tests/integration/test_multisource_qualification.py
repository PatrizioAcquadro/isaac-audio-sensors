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
    for field in ("nominal", "operational", "stress", "compute", "response", "roles"):
        assert initial[field] == confirmation[field]
        assert initial[field] == verification[field]


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
