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
HOP = 1600
PERIOD = HOP / FS


def load_input(path):
    """Reject partial windows or misaligned scoring references before replay."""
    with np.load(path, allow_pickle=False) as archive:
        data = dict(archive)
    samples, positions = data["samples"], data["positions"]
    if (
        samples.ndim != 2
        or samples.shape[1] < 8 * HOP
        or samples.shape[1] % HOP
        or positions.shape != (samples.shape[0], 3)
        or int(data.get("sample_rate_hz", FS)) != FS
    ):
        raise ValueError("Received PCM requires aligned 16 kHz, 100 ms windows.")
    steps = samples.shape[1] // HOP
    received = data["received_power"]
    if received.ndim != 2 or received.shape[0] != steps:
        raise ValueError("Received-power references must align with PCM windows.")
    expected = {
        "direct_power": received.shape,
        "directions": (*received.shape, 3),
        "noise_power": (steps,),
        "scheduled_count": (steps,),
    }
    if any(data[key].shape != shape for key, shape in expected.items()):
        raise ValueError("Scoring references must align with received PCM windows.")
    for key in ("samples", "positions", "received_power", *expected):
        if not np.isfinite(data[key]).all():
            raise ValueError(f"Received input {key} must be finite.")
    for key in ("received_power", "direct_power", "noise_power", "scheduled_count"):
        if (data[key] < 0).any():
            raise ValueError(f"Received input {key} must be nonnegative.")
    if not np.allclose(np.linalg.norm(data["directions"], axis=-1), 1):
        raise ValueError("Scoring directions must be unit vectors.")
    return data


def score(found, truth):
    from scipy.optimize import linear_sum_assignment

    errors = []
    matches = []
    if len(found) and len(truth):
        cost = np.degrees(
            np.arccos(np.clip(np.asarray(found) @ np.asarray(truth).T, -1, 1))
        )
        # One invalid edge must cost more than every angular error combined.
        # First maximize cardinality inside the gate, then minimize total angle
        # among those assignments. Retain invalid-pair errors for honest p95.
        penalty = 180 * min(cost.shape) + 1
        rows, cols = linear_sum_assignment(cost + (cost > 20) * penalty)
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
    result["received_source_indices"] = np.flatnonzero(reference["present"]).tolist()
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
    for step, end in enumerate(range(HOP, data["samples"].shape[1] + 1, HOP)):
        samples = np.array(data["samples"][:, end - HOP : end], dtype=np.float32)
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
            ambiguity_count=sum(e.ambiguity_class is not None for e in events),
            unresolved_observation_count=sum(
                e.estimated_bearing_deg is None for e in events
            ),
            observations_truncated=frame.diagnostics["perception"][
                "truncated_observation_count"
            ],
        )
        rows.append(result)
    return rows


def onset_responses(rows, *, localization):
    """Responses to received onset bins; never move an estimate back in time.

    Bin starts are the onset reference and output timestamps are bin ends.
    Delay has 100 ms resolution. A response must occur before that received
    segment ends; later activity or a different source cannot repair a miss.
    """
    pending = {}
    previous = set()
    responses = []
    for row in rows:
        present = (
            set(row["source_indices"])
            if localization
            else ({0} if row["received_count"] else set())
        )
        found = (
            set(row["matched_source_indices"])
            if localization and row["available"]
            else ({0} if not localization and row["activity"] else set())
        )
        for source in sorted(previous - present):
            if source in pending:
                responses.append(pending.pop(source))
        for source in sorted(present - previous):
            pending[source] = dict(
                source_index=source if localization else None,
                onset_bin_start_s=row["time_s"] - PERIOD,
                response_delay_ms=None,
            )
        for source in sorted(present & found):
            if source in pending:
                response = pending.pop(source)
                response["response_delay_ms"] = 1000 * (
                    row["time_s"] - response["onset_bin_start_s"]
                )
                responses.append(response)
        previous = present
    responses.extend(pending.values())
    return sorted(
        responses, key=lambda r: (r["onset_bin_start_s"], r["source_index"] or 0)
    )


def summarize(rows):
    resolved = [r for r in rows if r["exact"] is not None]
    active_resolved = [r for r in resolved if r["received_count"] > 0]
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
        active_resolvable_updates=len(active_resolved),
        active_complete_set_rate=float(np.mean([r["exact"] for r in active_resolved]))
        if active_resolved
        else None,
        active_count_rate=float(np.mean([r["count"] for r in active_resolved]))
        if active_resolved
        else None,
        precision=matches / detected if detected else None,
        recall=matches / expected if expected else None,
        angular_p95=float(np.percentile(errors, 95)) if errors else None,
        unavailable=sum(not r["available"] for r in rows),
        excess_over_received=sum(r["excess_over_received"] for r in rows),
        uncertain_count=sum(r["count_status"] == "uncertain" for r in rows),
        extras=sum(r["extras"] for r in resolved),
        misses=sum(r["misses"] for r in resolved),
        activity_updates=sum(r.get("activity", False) for r in rows),
        unresolved_received_updates=sum(not r["fully_resolvable"] for r in rows),
        ambiguity_observations=sum(r.get("ambiguity_count", 0) for r in rows),
        unresolved_observations=sum(
            r.get("unresolved_observation_count", 0) for r in rows
        ),
        observations_truncated=sum(r.get("observations_truncated", 0) for r in rows),
        compute_p95_ms=float(np.percentile([r["compute_ms"] for r in rows], 95)),
        max_completion_delay_ms=max(r["completion_delay_ms"] for r in rows),
    )


def case_report(data, rows):
    sensitivity = {}
    for threshold in (-3, 3):
        rescored = []
        for step, row in enumerate(rows):
            rescored.append(
                {
                    **row,
                    **assess(
                        row["directions"], row["diagnostic"], data, step, threshold
                    ),
                }
            )
        sensitivity[str(threshold)] = summarize(rescored[7:])
    return {
        **summarize(rows[7:]),
        "including_warmup": summarize(rows),
        "received_reference_sensitivity_db": sensitivity,
        "activity_onset_responses": onset_responses(rows, localization=False),
        "direction_onset_responses": onset_responses(rows, localization=True),
    }


def rescore_report(report, inputs_dir):
    """Recompute reference metrics from saved directions, without new inference."""
    for summary in report["layouts"].values():
        agreement, deviations = [], []
        for case in summary["cases"]:
            data = load_input(inputs_dir / case["input"])
            for lane, rows in case["rows"].items():
                for step, row in enumerate(rows):
                    row.update(assess(row["directions"], row["diagnostic"], data, step))
                case[lane] = case_report(data, rows)
            for actual, reference in zip(
                case["rows"]["cuda"], case["rows"]["scalar"], strict=True
            ):
                comparison = score(actual["directions"], reference["directions"])
                agreement.append(comparison["count"])
                deviations.extend(comparison["errors"])
        summary["count_agreement"] = float(np.mean(agreement))
        summary["direction_difference_p95_deg"] = (
            float(np.percentile(deviations, 95)) if deviations else 0
        )
    report["matching_policy"] = "maximum valid cardinality, then minimum total angle"
    report["rescored_saved_directions"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layouts", nargs="+", choices=LAYOUTS, default=LAYOUTS)
    parser.add_argument("--input-glob", default="*_{layout}_*stationary*.npz")
    parser.add_argument("--threshold-dbfs", type=float, default=-60)
    parser.add_argument("--include-rows", action="store_true")
    parser.add_argument("--rescore-report", type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.threshold_dbfs):
        parser.error("--threshold-dbfs must be finite.")
    if args.rescore_report:
        report = rescore_report(
            json.loads(args.rescore_report.read_text()), args.inputs_dir
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        return

    import torch

    from isaac_audio_sensors.lab._torch_perception import TorchPerception

    if not torch.cuda.is_available():
        raise RuntimeError("Received-audio parity requires CUDA, without CPU fallback.")
    report = {
        "gpu": torch.cuda.get_device_name(0),
        "layouts": {},
        "status": "running",
        "threshold_dbfs": args.threshold_dbfs,
        "input_glob": args.input_glob,
        "response_clock": "100 ms received-onset bin start to observation bin end",
        "timing_scope": "offline replay; compute is not end-to-end SDK latency",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    passed = True
    for layout in args.layouts:
        paths = sorted(args.inputs_dir.glob(args.input_glob.format(layout=layout)))
        if not paths:
            raise ValueError(f"No matching received inputs for {layout}.")
        data = []
        reference = []
        for path in paths:
            data.append(load_input(path))
            reference.append(run_stream(data[-1], threshold_dbfs=args.threshold_dbfs))
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
            threshold_dbfs=args.threshold_dbfs,
            doa_enabled=True,
            max_observations=32,
            max_doa_candidates=2,
            device="cuda:0",
        )
        ids = torch.arange(len(data), device="cuda:0")
        values = torch.tensor(
            np.stack([d["samples"] for d in data]), dtype=torch.float32, device="cuda:0"
        )
        counts = torch.full((len(data),), HOP, device="cuda:0")
        results = [[] for _ in data]
        agreement, deviations, activity_agreement = [], [], []
        for tick, start in enumerate(range(0, values.shape[-1], HOP)):
            torch.cuda.synchronize()
            begin = time.perf_counter()
            p.ingest(ids, values[..., start : start + HOP], counts)
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
                row.update(
                    time_s=(tick + 1) * PERIOD,
                    activity=bool(p.active[i]),
                    diagnostic=diag,
                    compute_ms=elapsed,
                    completion_delay_ms=elapsed,
                    ambiguity_count=int(output.ambiguity_mask[i].sum()),
                    unresolved_observation_count=int(
                        (output.observation_mask[i] & ~valid).sum()
                    ),
                    observations_truncated=int(output.observations_truncated[i]),
                )
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
                    "scalar": case_report(item, ref),
                    "cuda": case_report(item, actual),
                    **(
                        {"rows": {"scalar": ref, "cuda": actual}}
                        if args.include_rows
                        else {}
                    ),
                }
                for path, item, ref, actual in zip(
                    paths, data, reference, results, strict=True
                )
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
        "paired integration preservation on supplied received recordings; "
        "not new acoustic qualification"
    )
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
