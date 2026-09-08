"""Development-only causal-history WPE comparison before unchanged localization."""

import argparse
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
from scipy.signal import istft, stft

from .cases import ARRAYS, FS, ROOT, match
from .evaluate import construct
from .progressive import PROTOCOL, grouped, render_stage


def preprocess(
    samples, taps, implementation, *, nfft=512, hop=128, delay=3, output_samples=4000
):
    """Fit only supplied past audio; emit the current trailing window."""
    _, _, spectrum = stft(
        samples, fs=FS, nperseg=nfft, noverlap=nfft - hop, boundary="zeros", padded=True
    )
    if taps:
        spectrum = implementation(
            spectrum.transpose(1, 0, 2), taps=taps, delay=delay, iterations=3
        ).transpose(1, 0, 2)
    _, result = istft(spectrum, fs=FS, nperseg=nfft, noverlap=nfft - hop, boundary=True)
    current = np.ascontiguousarray(result[:, : samples.shape[-1]][:, -output_samples:])
    if not np.isfinite(current).all():
        raise ValueError("Non-finite dereverberation output")
    return current


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--dependency-path", type=Path, default=ROOT / "wpe_deps")
    args = parser.parse_args()
    path = ROOT / args.output
    if path.exists():
        raise FileExistsError(path)
    sys.path.insert(0, str(args.dependency_path.resolve()))
    from nara_wpe.wpe import wpe_v7

    protocol = json.loads(PROTOCOL.read_text())
    protocol["stages"] = [
        s for s in protocol["stages"] if s["name"] in ("direct", "room_030", "combined")
    ]
    settings = [(4000, 0), (8000, 5), (8000, 10), (12000, 5), (12000, 10)]
    protocol["wpe"] = dict(
        version=version("nara-wpe"),
        implementation="numpy_wpe_v7",
        settings=[dict(history_samples=h, taps=t) for h, t in settings],
        delay=3,
        iterations=3,
        scored_samples=4000,
        future_samples=0,
        nfft=512,
        hop=128,
        statistics_mode="full",
    )
    rows = []
    for array in ARRAYS:
        candidates = {
            setting: construct("weighted_covariance_aic", 0.010) for setting in settings
        }
        for content in protocol["contents"]:
            for repeat in range(protocol["repetitions"]):
                for stage in protocol["stages"]:
                    mixtures, truth, acoustics = render_stage(
                        array,
                        content,
                        repeat,
                        stage,
                        protocol["seed_base"],
                        history_samples=12000,
                    )
                    for count in protocol["counts"]:
                        for (history, taps), candidate in candidates.items():
                            samples = mixtures[count, :, -history:]
                            start = time.perf_counter()
                            processed = preprocess(samples, taps, wpe_v7)
                            if not taps:
                                np.testing.assert_allclose(
                                    processed, samples[:, -4000:], atol=1e-12
                                )
                            predicted, diagnostics = candidate.localize(
                                processed, ARRAYS[array], FS
                            )
                            rows.append(
                                dict(
                                    candidate=f"wpe_{history}_{taps}",
                                    array=array,
                                    content=content,
                                    repeat=repeat,
                                    stage=stage["name"],
                                    count=count,
                                    acoustics=acoustics,
                                    predicted=predicted.tolist(),
                                    truth=truth[:count].tolist(),
                                    diagnostics=diagnostics,
                                    compute_ms=1000 * (time.perf_counter() - start),
                                    **match(predicted, truth[:count]),
                                )
                            )
            path.write_text(json.dumps(dict(protocol=protocol, rows=rows)) + "\n")
            print(array, content, len(rows), flush=True)
    result = dict(protocol=protocol, rows=rows, summary=grouped(rows, protocol))
    path.write_text(json.dumps(result, indent=2) + "\n")
    for name, arrays in result["summary"].items():
        for array, stages in arrays.items():
            print(
                name,
                array,
                [
                    (
                        s,
                        round(v["precision"], 3),
                        round(v["recall"], 3),
                        round(v["both_localized_without_extras"], 3),
                        round(v["compute_p95_ms"], 1),
                    )
                    for s, v in stages.items()
                ],
                flush=True,
            )


if __name__ == "__main__":
    main()
