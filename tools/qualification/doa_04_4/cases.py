"""Evaluator-only sources, geometry, propagation and one-to-one matching."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy import signal
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[3] / "build/qualification/doa/04_4"
FS = 16000
ARRAYS = {
    "triangle": np.array([[-0.033, -0.033, 0], [-0.033, 0.033, 0], [0.033, 0.033, 0]]),
    "square": np.array(
        [[-0.033, -0.033, 0], [-0.033, 0.033, 0], [0.033, 0.033, 0], [0.033, -0.033, 0]]
    ),
    "raised": np.array(
        [
            [-0.03, -0.03, 0],
            [-0.03, 0.03, 0],
            [0.03, 0.03, 0],
            [0.03, -0.03, 0],
            [0, 0, 0.04],
        ]
    ),
    "tetra": 0.03 * np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]]),
}
ASSETS = {
    "development": ("cmu_arctic_us_aew_a0001.wav", "cmu_arctic_us_axb_a0004.wav"),
    "evaluation": ("cmu_arctic_us_aew_a0002.wav", "cmu_arctic_us_axb_a0005.wav"),
    "confirmation": ("cmu_arctic_us_aew_a0003.wav", "cmu_arctic_us_axb_a0006.wav"),
    "verification": ("6930-75918-0000.flac", "1320-122617-0003.flac"),
    "validation": ("5639-40744-0032.flac", "260-123440-0018.flac"),
}


@dataclass(frozen=True)
class Case:
    split: str
    seed: int
    array: str
    count: int
    content: str
    separation: float = 70
    imbalance: float = 0
    snr: float = 20
    rt60: float = 0
    condition: str = "nominal"
    orientation: str = "azimuth"


def make_cases(split, repetitions=2):
    base = {
        "development": 1000,
        "evaluation": 100000,
        "confirmation": 200000,
        "verification": 300000,
        "validation": 400000,
    }[split]
    conditions = [
        ("nominal", 70, 0, 20, 0),
        ("moderate", 45, 6, 10, 0.3),
        ("close", 25, 0, 20, 0),
        ("unequal", 70, 10, 20, 0),
        ("noise", 70, 0, 5, 0),
        ("reverberant", 70, 0, 20, 0.5),
    ]
    cases = []
    for array in ARRAYS:
        for content in ("noise", "speech", "disjoint"):
            for repeat in range(repetitions):
                for name, sep, level, snr, rt in conditions:
                    for count in (0, 1, 2):
                        # Keep zero/single controls in every acoustic stratum.
                        cases.append(
                            Case(
                                split,
                                base + len(cases),
                                array,
                                count,
                                content,
                                sep,
                                level,
                                snr,
                                rt,
                                name,
                                "elevation" if repeat % 2 else "azimuth",
                            )
                        )
    return cases


def wave(kind, split, index, rng, length):
    if kind == "speech":
        data, rate = sf.read(ROOT / "assets" / ASSETS[split][index % 2])
        if rate != FS:
            data = signal.resample_poly(data, FS, rate)
        # Use the most energetic contiguous episode, selected only by asset waveform.
        windows = np.lib.stride_tricks.sliding_window_view(data, length)[::800]
        data = windows[np.argmax(np.mean(windows**2, axis=1))].copy()
    else:
        data = rng.standard_normal(length)
    band = (
        ([300, 1800] if index % 2 == 0 else [2200, 6000])
        if kind == "disjoint"
        else [300, 6000]
    )
    data = signal.sosfilt(
        signal.butter(4, band, btype="bandpass", fs=FS, output="sos"), data
    )
    return data / (np.sqrt(np.mean(data**2)) + 1e-15)


def render(case):
    encoded = ("received_window_v2" + json.dumps(asdict(case), sort_keys=True)).encode()
    cache = ROOT / "mixtures" / f"{hashlib.sha256(encoded).hexdigest()[:20]}.npz"
    if cache.exists():
        with np.load(cache) as z:
            return z["samples"], z["truth"]
    rng = np.random.default_rng(case.seed)
    positions = ARRAYS[case.array]
    three_d = np.linalg.matrix_rank(positions - positions[0]) == 3
    length = 16000
    bearing = rng.uniform(-180, 180)
    elevation = rng.uniform(-45, 45) if three_d else 0
    a, e = np.radians([bearing, elevation])
    origin = np.array([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])
    tangent = (
        np.array([-np.cos(a) * np.sin(e), -np.sin(a) * np.sin(e), np.cos(e)])
        if three_d and case.orientation == "elevation"
        else np.array([-np.sin(a), np.cos(a), 0])
    )
    theta = np.radians(np.arange(case.count) * case.separation)
    truth = np.cos(theta[:, None]) * origin + np.sin(theta[:, None]) * tangent
    sources = [
        wave(case.content, case.split, i, rng, length) for i in range(case.count)
    ]
    stems = []
    if case.rt60 and case.count:
        dims = np.array([6, 5, 4]) + rng.uniform(-0.3, 0.3, 3)
        absorption, order = pra.inverse_sabine(case.rt60, dims)
        center = dims / 2
        room = pra.ShoeBox(
            dims, fs=FS, materials=pra.Material(absorption), max_order=order
        )
        room.add_microphone_array((positions + center).T)
        for direction, source in zip(truth, sources, strict=True):
            room.add_source(center + 1.5 * direction, signal=source)
        room.compute_rir()
        for i, source in enumerate(sources):
            stems.append(
                np.stack(
                    [
                        signal.fftconvolve(source, room.rir[m][i])[:length]
                        for m in range(len(positions))
                    ]
                )
            )
    else:
        for direction, source in zip(truth, sources, strict=True):
            padded = np.pad(source, (256, 256))
            freq = np.fft.rfftfreq(len(padded), 1 / FS)
            spec = np.fft.rfft(padded)
            stems.append(
                np.stack(
                    [
                        np.fft.irfft(
                            spec * np.exp(2j * np.pi * freq * (p @ direction) / 343),
                            n=len(padded),
                        )[256 : 256 + length]
                        for p in positions
                    ]
                )
            )
    mixture = np.zeros((len(positions), length))
    for i, stem in enumerate(stems):
        ref = np.sqrt(np.mean(stem[0, 8000:12000] ** 2))
        mixture += stem / max(ref, 1e-15) * 0.03 * 10 ** (-case.imbalance * i / 20)
    noise_rms = (
        np.sqrt(np.mean(mixture[:, 8000:12000] ** 2)) * 10 ** (-case.snr / 20)
        if stems
        else 0.0001
    )
    mixture += rng.standard_normal(mixture.shape) * noise_rms
    if np.max(np.abs(mixture)) >= 1:
        raise RuntimeError("Unexpected clipping")
    cache.parent.mkdir(exist_ok=True)
    np.savez_compressed(cache, samples=mixture, truth=truth)
    return mixture, truth


def match(pred, truth, gate=30):
    pred = np.asarray(pred).reshape(-1, 3)
    truth = np.asarray(truth).reshape(-1, 3)
    if not len(pred) or not len(truth):
        errors = []
    else:
        angles = np.degrees(np.arccos(np.clip(pred @ truth.T, -1, 1)))
        # Prioritize maximum admissible matching cardinality, then angular error.
        cost = np.where(angles <= gate, angles, 10000.0)
        a, b = linear_sum_assignment(cost)
        errors = [
            float(angles[i, j])
            for i, j in zip(a, b, strict=True)
            if angles[i, j] <= gate
        ]
    tp = len(errors)
    return dict(
        tp=tp,
        fp=len(pred) - tp,
        fn=len(truth) - tp,
        errors=errors,
        count_correct=len(pred) == len(truth),
        count_error=len(pred) - len(truth),
        abstained=bool(len(truth) and not len(pred)),
    )


def summary(rows):
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    errors = [e for r in rows for e in r["errors"]]
    return dict(
        cases=len(rows),
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / (tp + fn) if tp + fn else None,
        fp=fp,
        fn=fn,
        count_accuracy=float(np.mean([r["count_correct"] for r in rows])),
        angular_p95=float(np.percentile(errors, 95)) if errors else None,
        abstentions=sum(r["abstained"] for r in rows),
        compute_p95_ms=float(np.percentile([r["compute_ms"] for r in rows], 95)),
    )
