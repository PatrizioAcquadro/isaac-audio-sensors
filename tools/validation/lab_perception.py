"""Compare CUDA Lab perception with scalar perception on received-PCM archives."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from isaac_audio_sensors.core.perception import AudioPerceptionPipeline
from isaac_audio_sensors.core.plugins.auditok import AuditokActivityDetector
from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer
from isaac_audio_sensors.core.types import (
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSignalBlock,
    MicrophoneSpec,
)

FS = 16000
LAYOUTS = ("triangle", "square", "raised", "tetra")


def score(found, truth):
    from scipy.optimize import linear_sum_assignment

    errors = []
    matches = []
    if len(found) and len(truth):
        cost = np.degrees(
            np.arccos(np.clip(np.asarray(found) @ np.asarray(truth).T, -1, 1))
        )
        rows, cols = linear_sum_assignment(cost)
        errors = cost[rows, cols].tolist()
        matches = [int(c) for r, c in zip(rows, cols, strict=True) if cost[r, c] <= 20]
    return dict(
        exact=len(matches) == len(found) == len(truth),
        count=len(found) == len(truth),
        misses=len(truth) - len(matches),
        extras=len(found) - len(matches),
        errors=errors,
        matched=matches,
        expected=len(truth),
        detected=len(found),
        directions=np.asarray(found).reshape(-1, 3).tolist(),
        truth=np.asarray(truth).reshape(-1, 3).tolist(),
    )


def direction(azimuth, elevation=0.0):
    az, el = np.radians([azimuth, elevation])
    return np.array([np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), np.sin(el)])


def received_reference(data, step, threshold_db=0.0):
    """Audibility proxy, not a perceptual oracle: 100 ms received energy vs noise.

    Presence includes reverberant tails. A source direction is scored only while
    its direct component exceeds the noise floor; the remainder is unresolved
    received activity. Sensitivity at +/-3 dB accompanies every result.
    """
    floor = max(float(data["noise_power"][step]), 1e-12) * 10 ** (threshold_db / 10)
    present = data["received_power"][step] > floor
    direct = present & (data["direct_power"][step] > floor)
    return dict(
        present=present, direct=direct, directions=data["directions"][step][direct]
    )


def assess(found, diagnostic, data, step, threshold_db=0.0):
    reference = received_reference(data, step, threshold_db)
    result = score(found, reference["directions"])
    result["source_indices"] = np.flatnonzero(reference["direct"]).tolist()
    result["matched_source_indices"] = [
        result["source_indices"][i] for i in result["matched"]
    ]
    result["received_count"] = int(reference["present"].sum())
    result["unresolved_received_count"] = int(
        (reference["present"] & ~reference["direct"]).sum()
    )
    result["scheduled_count"] = int(data["scheduled_count"][step])
    result["excess_over_received"] = max(0, len(found) - result["received_count"])
    result["available"] = diagnostic.get("status") != "unavailable"
    result["count_status"] = diagnostic.get("count_status", "unspecified")
    result["fully_resolvable"] = result["unresolved_received_count"] == 0
    if not result["available"] or result["count_status"] == "uncertain":
        result["exact"] = result["count"] = False
    # Directional count is not the number of audible contributors in diffuse tails.
    if not result["fully_resolvable"]:
        result["exact"] = result["count"] = None
    return result


def run_stream(data, *, threshold_dbfs=-60):
    estimator = MaintainedEventLocalizer()
    positions = np.array(data["positions"], dtype=float, copy=True)
    positions.setflags(write=False)
    array = MicrophoneArraySpec(
        array_id="rig",
        prim_path="/Array",
        position_world=(0, 0, 0),
        orientation_world_quat=(0, 0, 0, 1),
        sample_rate_hz=FS,
        microphones=tuple(
            MicrophoneSpec(mic_id=str(i), relative_position_m=tuple(p))
            for i, p in enumerate(positions)
        ),
    )
    perception = AudioPerceptionPipeline(
        activity_detector=AuditokActivityDetector(energy_threshold_dbfs=threshold_dbfs),
        event_localizer=estimator,
    )
    rows = []
    backlog = 0.0
    for step, end in enumerate(range(1600, data["samples"].shape[1] + 1, 1600)):
        samples = np.array(data["samples"][:, end - 1600 : end], dtype=np.float32)
        samples.setflags(write=False)
        block = MicrophoneSignalBlock(
            samples=samples,
            microphone_ids=tuple(str(i) for i in range(len(positions))),
            microphone_positions_m=tuple(map(tuple, positions)),
            array_id="rig",
            sample_rate_hz=FS,
            time_window=AudioTimeWindow(
                start_time_s=step / 10, end_time_s=(step + 1) / 10, frame_index=step
            ),
            clock_domain="evaluation",
            discontinuity=False,
            channel_validity=(True,) * len(positions),
            channel_clipping=(False,) * len(positions),
            producer_id="received_pcm",
            provenance="room_acoustics",
        )
        start = time.perf_counter()
        frame = perception.process(block, array, frame_id=f"frame_{step}")
        events = [o.doa for o in frame.observations if o.doa is not None]
        diag = frame.diagnostics["perception"]["localization"]
        activity = frame.diagnostics["perception"]["activity_detected"]
        elapsed = time.perf_counter() - start
        backlog = max(0.0, backlog - 0.1) + elapsed
        found = np.array(
            [
                direction(e.estimated_bearing_deg, e.estimated_elevation_deg or 0)
                for e in events
                if e.estimated_bearing_deg is not None
            ]
        ).reshape(-1, 3)
        if bool(data.get("azimuth_only", False)) and len(found):
            found[:, 2] = 0
            found /= np.maximum(np.linalg.norm(found, axis=1)[:, None], 1e-12)
        result = assess(found, diag, data, step)
        result.update(
            time_s=(step + 1) / 10,
            compute_ms=elapsed * 1000,
            completion_delay_ms=backlog * 1000,
            activity=activity,
            diagnostic=diag,
        )
        rows.append(result)
    return rows


def summarize(rows):
    resolved = [r for r in rows if r["exact"] is not None]
    errors = [e for r in resolved for e in r["errors"]]
    matches = sum(r["expected"] - r["misses"] for r in resolved)
    detected = sum(r["detected"] for r in resolved)
    expected = sum(r["expected"] for r in resolved)
    longest_error = current_error = 0
    fragments = 0
    previous_matched = set()
    for row in rows:
        current_error = current_error + 1 if row["exact"] is False else 0
        longest_error = max(longest_error, current_error)
        current_matched = set(row.get("matched_source_indices", ()))
        current_sources = set(row["source_indices"])
        fragments += len((previous_matched & current_sources) - current_matched)
        previous_matched = current_matched
    return dict(
        updates=len(rows),
        longest_joint_error_s=longest_error * 0.1,
        localization_interruptions=fragments,
        resolvable_updates=len(resolved),
        exact=float(np.mean([r["exact"] for r in resolved])) if resolved else None,
        count=float(np.mean([r["count"] for r in resolved])) if resolved else None,
        precision=matches / detected if detected else None,
        recall=matches / expected if expected else None,
        angular_p95=float(np.percentile(errors, 95)) if errors else None,
        unavailable=sum(not r["available"] for r in rows),
        excess_over_received=sum(r["excess_over_received"] for r in rows),
        uncertain_count=sum(r["count_status"] == "uncertain" for r in rows),
        extras=sum(r["extras"] for r in resolved),
        misses=sum(r["misses"] for r in resolved),
        compute_p95_ms=float(np.percentile([r["compute_ms"] for r in rows], 95)),
        max_completion_delay_ms=max(r["completion_delay_ms"] for r in rows),
    )


def main():
    import torch

    from isaac_audio_sensors.lab._torch_perception import TorchPerception

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
