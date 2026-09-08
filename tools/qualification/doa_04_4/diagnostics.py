"""Idle-noise, causal transition, capacity and composed compute diagnostics."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector

from .cases import ARRAYS, FS, Case, match, render
from .evaluate import construct

ROOT = Path(__file__).resolve().parents[3] / "build/qualification/doa/04_4"


def diffuse_factor(positions, size=4000):
    distance = np.linalg.norm(positions[:, None] - positions[None, :], axis=-1)
    frequency = np.fft.rfftfreq(size, 1 / FS)
    covariance = np.sinc(2 * frequency[:, None, None] * distance[None] / 343)
    eigen, vectors = np.linalg.eigh(covariance)
    return vectors * np.sqrt(np.maximum(eigen, 0))[:, None, :]


def idle_windows(positions, seed):
    rng = np.random.default_rng(seed)
    factor = diffuse_factor(positions)
    yield "silence", np.zeros((len(positions), 4000))
    for i in range(100):
        rms = (0.0001, 0.003, 0.03)[i % 3]
        white = rng.standard_normal((len(positions), 4000))
        yield "uncorrelated", white / np.sqrt(np.mean(white**2)) * rms
        noise = rng.standard_normal((2001, len(positions), 2))
        spectrum = np.einsum("fij,fj->fi", factor, noise[:, :, 0] + 1j * noise[:, :, 1])
        values = np.fft.irfft(spectrum.T, n=4000)
        yield "diffuse", values / np.sqrt(np.mean(values**2)) * rms


def transition_signal(positions, seed, randomize=False, bandlimited=False):
    rng = np.random.default_rng(seed)
    count_per_phase = (0, 1, 2, 1, 0)
    phase_samples = 12800
    count = len(count_per_phase) * phase_samples
    azimuth = np.radians([20, 90])
    elevation = (
        np.radians([15, -25])
        if np.linalg.matrix_rank(positions - positions[0]) == 3
        else np.zeros(2)
    )
    directions = np.column_stack(
        (
            np.cos(azimuth) * np.cos(elevation),
            np.sin(azimuth) * np.cos(elevation),
            np.sin(elevation),
        )
    )
    if randomize:
        az = rng.uniform(-np.pi, np.pi)
        el = (
            rng.uniform(-np.pi / 4, np.pi / 4)
            if np.linalg.matrix_rank(positions - positions[0]) == 3
            else 0
        )
        origin = np.array(
            [np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), np.sin(el)]
        )
        tangent = np.array([-np.sin(az), np.cos(az), 0])
        directions = np.stack(
            (origin, origin * np.cos(np.radians(70)) + tangent * np.sin(np.radians(70)))
        )
    samples = np.zeros((len(positions), count))
    for source, direction in enumerate(directions):
        mono = rng.standard_normal(count + 256) * 0.03
        time_samples = np.arange(count, dtype=float) + 128
        propagated = np.stack(
            [
                np.interp(
                    time_samples + p @ direction / 343 * FS, np.arange(len(mono)), mono
                )
                for p in positions
            ]
        )
        if bandlimited:
            frequency = np.fft.rfftfreq(len(mono), 1 / FS)
            propagated = np.fft.irfft(
                np.fft.rfft(mono)[None]
                * np.exp(
                    2j
                    * np.pi
                    * frequency[None]
                    * (positions @ direction)[:, None]
                    / 343
                ),
                n=len(mono),
            )[:, 128 : 128 + count]
        mask = np.repeat([n > source for n in count_per_phase], phase_samples)
        samples += propagated * mask
    return samples, directions, phase_samples, count_per_phase


def observability_controls(candidate, positions, seed):
    """Report unresolved inputs separately from the qualified operating domain."""
    rng = np.random.default_rng(seed)
    frequency = np.fft.rfftfreq(8192, 1 / FS)
    results = {}
    for label, separation, coherent in (
        ("near_5deg", 5, False),
        ("coherent", 70, True),
    ):
        azimuth = np.radians([20, 20 + separation])
        truth = np.column_stack((np.cos(azimuth), np.sin(azimuth), np.zeros(2)))
        sources = rng.standard_normal((2, 8192)) * 0.03
        if coherent:
            sources[1] = sources[0]
        spectra = np.zeros((len(positions), len(frequency)), dtype=complex)
        for source, direction in zip(sources, truth, strict=True):
            delay = positions @ direction / 343
            spectra += np.fft.rfft(source)[None] * np.exp(
                2j * np.pi * delay[:, None] * frequency
            )
        samples = np.fft.irfft(spectra, n=8192)[:, 2000:6000]
        samples += rng.standard_normal(samples.shape) * 0.003
        found, diagnostic = candidate.localize(samples, positions, FS)
        results[label] = {
            "predicted": found.tolist(),
            "truth": truth.tolist(),
            "diagnostics": diagnostic,
            **match(found, truth),
        }
    return results


def measure(name, candidate, array, split="evaluation", bandlimited=False):
    offset = {
        "evaluation": 0,
        "development": -500000,
        "confirmation": 100000,
        "verification": 200000,
        "validation": 300000,
        "qualification": 400000,
    }[split]
    positions = ARRAYS[array]
    idle = {
        kind: {"windows": 0, "false_event_windows": 0}
        for kind in ("silence", "uncorrelated", "diffuse")
    }
    for kind, values in idle_windows(
        positions, 910000 + offset + list(ARRAYS).index(array)
    ):
        found, _ = candidate.localize(values, positions, FS)
        idle[kind]["windows"] += 1
        idle[kind]["false_event_windows"] += int(len(found) > 0)
    samples, directions, phase_samples, counts = transition_signal(
        positions,
        920000 + offset,
        randomize=split
        in ("development", "verification", "validation", "qualification"),
        bandlimited=bandlimited,
    )
    detector = AuditokActivityDetector(energy_threshold_dbfs=-40.5)
    ticks = []
    for end in range(800, samples.shape[1] + 1, 800):
        start = time.perf_counter()
        active = detector.detect(samples[:, end - 800 : end], FS).active
        found = np.empty((0, 3))
        status = "inactive" if not active else "insufficient_context"
        if active and end >= 4000:
            found, diagnostic = candidate.localize(
                samples[:, end - 4000 : end], positions, FS
            )
            status = diagnostic["status"]
        elapsed = (time.perf_counter() - start) * 1000
        phase = min((end - 1) // phase_samples, 4)
        truth = directions[: counts[phase]]
        scores = match(found, truth)
        correct = scores["count_correct"] and scores["fp"] == scores["fn"] == 0
        ticks.append(
            {
                "end_s": end / FS,
                "count": len(found),
                "correct": correct,
                "status": status,
                "compute_ms": elapsed,
            }
        )
    responses = []
    for phase in range(1, 5):
        onset = phase * phase_samples / FS
        region = [t for t in ticks if onset < t["end_s"] <= onset + phase_samples / FS]
        delay = None
        for previous, current in zip(region, region[1:], strict=False):
            if previous["correct"] and current["correct"]:
                delay = (current["end_s"] - onset) * 1000 + current["compute_ms"]
                break
        responses.append(
            {
                "from_count": counts[phase - 1],
                "to_count": counts[phase],
                "delay_ms": delay,
            }
        )
    case = Case(split, 930000 + offset, array, 2, "noise")
    values, truth = render(case)
    detector.reset()
    timings = []
    for _ in range(220):
        start = time.perf_counter()
        decision = detector.detect(values[:, 11200:12000], FS)
        if decision.active:
            candidate.localize(values[:, 8000:12000], positions, FS)
        timings.append((time.perf_counter() - start) * 1000)
    capacity_values, capacity_truth = render(
        Case(split, 940000 + offset, array, 3, "noise", separation=90)
    )
    found, _ = candidate.localize(capacity_values[:, 8000:12000], positions, FS)
    return {
        "candidate": name,
        "array": array,
        "idle": idle,
        "responses": responses,
        "ticks": ticks,
        "compute_warm_p95_ms": float(np.percentile(timings[20:], 95)),
        "compute_warm_max_ms": float(max(timings[20:])),
        "three_source_diagnostic": {
            "predicted_count": len(found),
            **match(found, capacity_truth),
        },
        "context_ms": 250,
        "update_interval_ms": 50,
        "transition_propagation": "bandlimited" if bandlimited else "linear",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate", action="append")
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument(
        "--protocol", type=Path, default=Path(__file__).with_name("final_protocol.json")
    )
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise FileExistsError(output)
    protocol = json.loads(args.protocol.read_text())
    if args.candidate:
        protocol["candidates"] = {
            name: protocol["candidates"][name] for name in args.candidate
        }
    rows = []
    for name, thresholds in protocol["candidates"].items():
        for array in ARRAYS:
            role = "planar" if array in ("triangle", "square") else "3d"
            candidate = construct(name, thresholds[role])
            if args.controls_only:
                result = {
                    "candidate": name,
                    "array": array,
                    "observability": observability_controls(
                        candidate, ARRAYS[array], 950000 + list(ARRAYS).index(array)
                    ),
                }
            else:
                result = measure(
                    name,
                    candidate,
                    array,
                    protocol["split"],
                    protocol.get("transition_bandlimited", False),
                )
            rows.append(result)
            print(name, array, "complete", flush=True)
            if hasattr(candidate, "close"):
                candidate.close()
            output.write_text(
                json.dumps({"protocol": protocol, "results": rows}, indent=2)
            )


if __name__ == "__main__":
    main()
