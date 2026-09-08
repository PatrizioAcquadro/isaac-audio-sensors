"""Combine static quality with idle and response gates before role admission."""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3] / "build/qualification/doa/04_4"


def diagnostic_failures(result, protocol):
    failures = []
    for kind, minimum in (("silence", 1), ("uncorrelated", 100), ("diffuse", 100)):
        if result["idle"][kind]["windows"] < minimum:
            failures.append("insufficient_idle_" + kind)
    if result["idle"]["silence"]["false_event_windows"]:
        failures.append("silence")
    diffuse = result["idle"]["diffuse"]
    # The 1% diffuse-noise gate was fixed in the canonical experiment before evaluation.
    if diffuse["false_event_windows"] > 0.01 * diffuse["windows"]:
        failures.append("diffuse_noise")
    if result["compute_warm_p95_ms"] >= protocol["compute"]["maximum_warm_p95_ms"]:
        failures.append("compute_p95")
    if result["compute_warm_max_ms"] >= protocol["compute"]["maximum_warm_ms"]:
        failures.append("compute_max")
    delays = [item["delay_ms"] for item in result["responses"]]
    if len(delays) != 4 or any(delay is None for delay in delays):
        failures.append("unresolved_transition")
    else:
        if (
            np.percentile(delays, 95)
            > protocol["response"]["maximum_change_delay_p95_ms"]
        ):
            failures.append("response_p95")
        if max(delays) > protocol["response"]["maximum_change_delay_ms"]:
            failures.append("response_max")
    return failures


def assess(evaluation, diagnostics, regression=None):
    protocol = evaluation["protocol"]
    if protocol["split"] == "development":
        raise ValueError("Development cannot establish independent admission")
    if diagnostics["protocol"] != protocol or evaluation["split"] != protocol["split"]:
        raise ValueError("Evaluation and diagnostics must use the same fixed protocol")
    conditions = set().union(
        *(protocol[k]["conditions"] for k in ("nominal", "operational", "stress"))
    )
    expected = protocol["repetitions"] * 3 * 3 * len(conditions)
    results = {}
    for name, quality in evaluation["quality"].items():
        geometries = {}
        for array, static in quality.items():
            failures = list(static["failures"])
            if regression is not None:
                previous = regression["quality"].get(name, {}).get(array)
                if previous is None:
                    failures.append("regression_evidence_missing")
                else:
                    failures.extend(
                        "known_cases." + reason for reason in previous["failures"]
                    )
            rows = [
                r
                for r in evaluation["rows"]
                if r["candidate"] == name and r["case"]["array"] == array
            ]
            cases = {json.dumps(r["case"], sort_keys=True) for r in rows}
            if len(rows) != expected or len(cases) != expected:
                failures.append("incomplete_or_duplicate_cases")
            measured = [
                r
                for r in diagnostics["results"]
                if r["candidate"] == name and r["array"] == array
            ]
            if len(measured) != 1:
                failures.append("missing_or_duplicate_diagnostics")
            else:
                failures.extend(diagnostic_failures(measured[0], protocol))
            geometries[array] = {
                "status": "NO-GO" if failures else "GO",
                "failures": failures,
            }
        results[name] = {
            "geometries": geometries,
            "roles": {
                role: "GO"
                if all(geometries.get(a, {}).get("status") == "GO" for a in arrays)
                else "NO-GO"
                for role, arrays in protocol["roles"].items()
            },
        }
    return {
        "scope": (
            "Simulated candidate evidence including known-case regression"
            if regression is not None
            else "Single-run result only; not a general promotion decision"
        ),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--regression")
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise FileExistsError(output)
    result = assess(
        json.loads((ROOT / args.evaluation).read_text()),
        json.loads((ROOT / args.diagnostics).read_text()),
        json.loads((ROOT / args.regression).read_text()) if args.regression else None,
    )
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
