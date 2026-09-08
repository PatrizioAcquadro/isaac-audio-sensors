"""Run fixed settings on an unopened partition; report every gate violation."""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .candidates import (
    CovarianceCandidate,
    FrequencyOrderCandidate,
    OdasCandidate,
    PyroomCandidate,
)
from .cases import ARRAYS, FS, make_cases, match, render, summary

ROOT = Path(__file__).resolve().parents[3] / "build/qualification/doa/04_4"


def construct(name, threshold):
    if name == "frequency_order":
        return FrequencyOrderCandidate(threshold)
    if name == "odas":
        return OdasCandidate(threshold)
    if name == "covariance":
        return CovarianceCandidate(threshold)
    return PyroomCandidate(
        "SRP" if name == "srp" else "MUSIC", threshold, normalized=name == "normmusic"
    )


def quality_gates(rows, protocol):
    result = {}
    for name in protocol["candidates"]:
        result[name] = {}
        for array in ARRAYS:
            subset = [
                r
                for r in rows
                if r["candidate"] == name and r["case"]["array"] == array
            ]
            failures = []
            groups = {}
            for group in ("nominal", "operational"):
                limits = protocol[group]
                scored = [
                    r for r in subset if r["case"]["condition"] in limits["conditions"]
                ]
                st = summary(scored)
                groups[group] = st
                for metric in ("precision", "recall", "count_accuracy"):
                    if st[metric] is None or st[metric] < limits["minimum_" + metric]:
                        failures.append(group + "." + metric)
                if (
                    st["angular_p95"] is None
                    or st["angular_p95"] > limits["maximum_angular_p95_deg"]
                ):
                    failures.append(group + ".angular_p95")
                pairs = summary([r for r in scored if r["case"]["count"] == 2])
                if pairs["count_accuracy"] < limits["minimum_pair_count_accuracy"]:
                    failures.append(group + ".pair_count_accuracy")
                if group == "operational":
                    for condition in limits["conditions"]:
                        s = summary(
                            [r for r in scored if r["case"]["condition"] == condition]
                        )
                        if (
                            s["recall"] is None
                            or s["recall"] < limits["minimum_condition_recall"]
                        ):
                            failures.append("operational.recall." + condition)
            result[name][array] = {
                "quality_status": "fail" if failures else "pass",
                "failures": failures,
                "groups": groups,
                "by_condition": {
                    c: summary([r for r in subset if r["case"]["condition"] == c])
                    for c in sorted({r["case"]["condition"] for r in subset})
                },
                "by_count": {
                    str(k): summary([r for r in subset if r["case"]["count"] == k])
                    for k in (0, 1, 2)
                },
                "by_content": {
                    c: summary([r for r in subset if r["case"]["content"] == c])
                    for c in ("noise", "speech", "disjoint")
                },
            }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split", choices=("development", "evaluation", "confirmation"), required=True
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--protocol", type=Path, default=Path(__file__).with_name("final_protocol.json")
    )
    parser.add_argument("--repetitions", type=int, default=4)
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise FileExistsError(output)
    protocol = json.loads(args.protocol.read_text())
    candidates = {
        (name, role): construct(name, threshold)
        for name, roles in protocol["candidates"].items()
        for role, threshold in roles.items()
    }
    rows = []
    for i, case in enumerate(make_cases(args.split, args.repetitions)):
        samples, truth = render(case)
        values = np.ascontiguousarray(samples[:, 8000:12000])
        values.setflags(write=False)
        role = "planar" if case.array in ("triangle", "square") else "3d"
        for name in protocol["candidates"]:
            start = time.perf_counter()
            found, diag = candidates[name, role].localize(
                values, ARRAYS[case.array], FS
            )
            elapsed = (time.perf_counter() - start) * 1000
            rows.append(
                dict(
                    candidate=name,
                    case=asdict(case),
                    predicted=found.tolist(),
                    truth=truth.tolist(),
                    diagnostics=diag,
                    compute_ms=elapsed,
                    **match(found, truth),
                )
            )
        if i % 36 == 0:
            print(i, case.array, flush=True)
        output.write_text(
            json.dumps(
                {"protocol": protocol, "split": args.split, "rows": rows}, indent=2
            )
        )
    result = quality_gates(rows, protocol)
    output.write_text(
        json.dumps(
            {
                "protocol": protocol,
                "split": args.split,
                "quality": result,
                "rows": rows,
            },
            indent=2,
        )
    )
    for name, arrays in result.items():
        for array, result in arrays.items():
            print(name, array, result["quality_status"], result["failures"], flush=True)


if __name__ == "__main__":
    main()
