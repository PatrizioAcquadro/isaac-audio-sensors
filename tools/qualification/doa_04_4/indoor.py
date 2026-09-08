"""Mixture-only candidate comparison using the existing paired room evaluator."""

import argparse
import json
import sys
import time
from pathlib import Path

from .cases import ARRAYS, FS, ROOT, match
from .evaluate import construct
from .indoor_candidates import DirectPathRtf, WeightedHistogramSrp
from .progressive import grouped, render_stage

PROTOCOL = Path(__file__).with_name("indoor_protocol.json")


def load_protocol(path, block=None):
    protocol = json.loads(path.read_text())
    if "blocks" in protocol:
        if block not in protocol["blocks"]:
            raise ValueError("Choose a named independent protocol block")
        chosen = protocol.pop("blocks")[block]
        protocol.update(chosen, block=block)
    elif block is not None:
        raise ValueError("This protocol has no named blocks")
    return protocol


def candidate(setting):
    parameters = setting.get("parameters", {})
    if setting["method"] == "music":
        return construct("weighted_covariance_aic", **parameters)
    if setting["method"] == "wpe_group_sparse":
        from .sparse_covariance import WpeSparseCovariance

        return WpeSparseCovariance(**parameters)
    factories = {"dprtf": DirectPathRtf, "srp_histogram": WeightedHistogramSrp}
    return factories[setting["method"]](**parameters)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--candidate", action="append")
    parser.add_argument("--stage", action="append")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--dependency-path", type=Path)
    parser.add_argument("--block")
    args = parser.parse_args()
    if args.dependency_path:
        sys.path.insert(0, str(args.dependency_path.resolve()))
    path = ROOT / args.output
    if path.exists():
        raise FileExistsError(path)
    protocol = load_protocol(args.protocol, args.block)
    for option, field in ((args.candidate, "candidates"), (args.stage, "stages")):
        if option:
            unknown = set(option) - {s["name"] for s in protocol[field]}
            if unknown:
                parser.error(f"Unknown {field}: {sorted(unknown)}")
            protocol[field] = [s for s in protocol[field] if s["name"] in option]
    if args.repetitions is not None:
        if args.repetitions < 1:
            parser.error("Repetitions must be positive")
        protocol["repetitions"] = args.repetitions
    history = max(s["history_samples"] for s in protocol["candidates"])
    rows = []
    for array, positions in ARRAYS.items():
        estimators = {s["name"]: candidate(s) for s in protocol["candidates"]}
        for content in protocol["contents"]:
            for repeat in range(protocol["repetitions"]):
                for stage in protocol["stages"]:
                    mixtures, truth, acoustics = render_stage(
                        array,
                        content,
                        repeat,
                        stage,
                        protocol["seed_base"],
                        history_samples=history,
                        speech_assets=protocol.get("speech_assets"),
                    )
                    for count in protocol["counts"]:
                        for setting in protocol["candidates"]:
                            values = mixtures[count, :, -setting["history_samples"] :]
                            start = time.perf_counter()
                            found, diagnostic = estimators[setting["name"]].localize(
                                values, positions, FS
                            )
                            rows.append(
                                dict(
                                    candidate=setting["name"],
                                    array=array,
                                    content=content,
                                    repeat=repeat,
                                    stage=stage["name"],
                                    count=count,
                                    acoustics=acoustics,
                                    predicted=found.tolist(),
                                    truth=truth[:count].tolist(),
                                    diagnostics=diagnostic,
                                    compute_ms=1000 * (time.perf_counter() - start),
                                    **match(found, truth[:count]),
                                )
                            )
            path.write_text(json.dumps(dict(protocol=protocol, rows=rows)) + "\n")
            print(array, content, len(rows), flush=True)
    result = dict(protocol=protocol, rows=rows, summary=grouped(rows, protocol))
    path.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
