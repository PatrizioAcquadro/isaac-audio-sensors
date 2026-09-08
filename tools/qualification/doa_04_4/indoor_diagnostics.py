"""Idle and causal response measurements for one frozen indoor candidate."""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector

from .cases import ARRAYS, FS, ROOT, match
from .diagnostics import idle_windows
from .indoor import candidate, load_protocol
from .progressive import render_transitions


def responses(ticks, truths, phase_samples):
    results = []
    for phase in range(1, len(truths)):
        onset = phase * phase_samples / FS
        region = [t for t in ticks if onset < t["end_s"] <= onset + phase_samples / FS]
        delay = None
        for previous, current in zip(region, region[1:], strict=False):
            if previous["correct"] and current["correct"]:
                delay = (current["end_s"] - onset) * 1000 + current["compute_ms"]
                break
        results.append(
            dict(
                from_count=len(truths[phase - 1]),
                to_count=len(truths[phase]),
                direction_change=len(truths[phase - 1]) == len(truths[phase]) == 1,
                delay_ms=delay,
            )
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dependency-path", type=Path)
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument("--block")
    args = parser.parse_args()
    if args.dependency_path:
        sys.path.insert(0, str(args.dependency_path.resolve()))
    path = ROOT / args.output
    if path.exists():
        raise FileExistsError(path)
    protocol = load_protocol(args.protocol, args.block)
    setting = next(s for s in protocol["candidates"] if s["method"] != "music")
    history = setting["history_samples"]
    interval = 1600  # 100 ms; measurements include compute, never future samples.
    idle, rows = [], []
    for array, positions in ARRAYS.items():
        estimator = candidate(setting)
        for kind, values in idle_windows(
            positions,
            protocol["seed_base"] + 10000 + list(ARRAYS).index(array),
            size=history,
        ):
            start = time.perf_counter()
            found, diagnostic = estimator.localize(values, positions, FS)
            idle.append(
                dict(
                    array=array,
                    kind=kind,
                    rms=float(np.sqrt(np.mean(values**2))),
                    events=len(found),
                    compute_ms=1000 * (time.perf_counter() - start),
                )
            )
        for content in protocol["contents"]:
            for repeat in range(args.repetitions):
                samples, truths, phase_samples = render_transitions(
                    array,
                    content,
                    repeat,
                    protocol["seed_base"],
                    dict(rt60=0.3, imbalance=6, separation=70, snr=20),
                    speech_assets=protocol.get("speech_assets"),
                )
                detector = AuditokActivityDetector(energy_threshold_dbfs=-40.5)
                ticks = []
                for end in range(interval, samples.shape[1] + 1, interval):
                    start = time.perf_counter()
                    active = detector.detect(
                        samples[:, end - interval : end], FS
                    ).active
                    found = np.empty((0, 3))
                    if active and end >= history:
                        found, diagnostic = estimator.localize(
                            samples[:, end - history : end], positions, FS
                        )
                    truth = truths[(end - 1) // phase_samples]
                    metrics = match(found, truth)
                    ticks.append(
                        dict(
                            end_s=end / FS,
                            predicted=found.tolist(),
                            correct=metrics["tp"] == len(truth) and metrics["fp"] == 0,
                            compute_ms=1000 * (time.perf_counter() - start),
                        )
                    )
                rows.append(
                    dict(
                        array=array,
                        content=content,
                        repeat=repeat,
                        responses=responses(ticks, truths, phase_samples),
                        ticks=ticks,
                    )
                )
            path.write_text(
                json.dumps(
                    dict(
                        protocol=protocol,
                        idle=idle,
                        transitions=rows,
                        update_ms=100,
                        history_ms=history / 16,
                    )
                )
            )
            print(array, content, "complete", flush=True)


if __name__ == "__main__":
    main()
