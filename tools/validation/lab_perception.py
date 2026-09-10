"""Compare CUDA Lab perception with scalar perception on received-PCM archives."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from isaac_audio_sensors.lab._torch_perception import TorchPerception
from tools.validation.joint_motion import assess, run_stream, summarize
from tools.validation.motion_localization import LAYOUTS, direction, score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("Received-audio parity requires CUDA, without CPU fallback.")
    report = {"gpu": torch.cuda.get_device_name(0), "layouts": {}, "status": "running"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    passed = True
    for layout in LAYOUTS:
        paths = sorted(args.inputs_dir.glob(f"*_{layout}_*stationary*.npz"))
        if not paths:
            raise ValueError(f"No received stationary inputs for {layout}.")
        data = []
        reference = []
        for path in paths:
            with np.load(path, allow_pickle=False) as archive:
                data.append(dict(archive))
            reference.append(run_stream(data[-1]))
        lengths = {d["samples"].shape[-1] for d in data}
        if len(lengths) != 1 or not all(
            np.array_equal(d["positions"], data[0]["positions"]) for d in data
        ):
            raise ValueError(
                "Batched evaluation requires matching geometry and duration."
            )
        p = TorchPerception(
            num_envs=len(data),
            positions=data[0]["positions"],
            threshold_dbfs=-60,
            doa_enabled=True,
            max_observations=32,
            max_doa_candidates=2,
            device="cuda:0",
        )
        ids = torch.arange(len(data), device="cuda:0")
        values = torch.tensor(
            np.stack([d["samples"] for d in data]), dtype=torch.float32, device="cuda:0"
        )
        counts = torch.full((len(data),), 1600, device="cuda:0")
        results = [[] for _ in data]
        agreement, deviations, activity_agreement = [], [], []
        for tick, start in enumerate(range(0, values.shape[-1], 1600)):
            torch.cuda.synchronize()
            begin = time.perf_counter()
            p.ingest(ids, values[..., start : start + 1600], counts)
            output = p.observations(ids)
            torch.cuda.synchronize()
            elapsed = (time.perf_counter() - begin) * 1000
            for i, item in enumerate(data):
                valid = output.bearing_deg_mask[i]
                found = np.array(
                    [
                        direction(a, e)
                        for a, e in zip(
                            output.bearing_deg[i, valid].tolist(),
                            output.elevation_deg[i, valid].tolist(),
                            strict=True,
                        )
                    ]
                ).reshape(-1, 3)
                if bool(item.get("azimuth_only", False)) and len(found):
                    found[:, 2] = 0
                    found /= np.linalg.norm(found, axis=1)[:, None]
                comparison = score(found, reference[i][tick]["directions"])
                agreement.append(comparison["count"])
                deviations.extend(comparison["errors"])
                activity_agreement.append(
                    bool(p.active[i]) == reference[i][tick]["activity"]
                )
                diag = {"status": "events" if len(found) else "no_events"}
                if tick < 7:
                    diag = {"status": "unavailable"}
                row = assess(found, diag, item, tick)
                row.update(compute_ms=elapsed, completion_delay_ms=elapsed)
                results[i].append(row)
        summary = {
            "count_agreement": float(np.mean(agreement)),
            "activity_agreement": float(np.mean(activity_agreement)),
            "direction_difference_p95_deg": float(np.percentile(deviations, 95))
            if deviations
            else 0,
            "cases": [
                {
                    "input": path.name,
                    "scalar": summarize(ref[7:]),
                    "cuda": summarize(actual[7:]),
                }
                for path, ref, actual in zip(paths, reference, results, strict=True)
            ],
        }
        summary["passed"] = (
            summary["count_agreement"] >= 0.97
            and summary["activity_agreement"] == 1
            and summary["direction_difference_p95_deg"] <= 5
        )
        passed &= summary["passed"]
        report["layouts"][layout] = summary
        args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(
            layout,
            json.dumps({k: v for k, v in summary.items() if k != "cases"}),
            flush=True,
        )
    report["status"] = "passed" if passed else "failed"
    report["scope"] = (
        "paired integration preservation on supplied stationary recordings; "
        "not new acoustic qualification"
    )
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
