"""Causal paired evaluation with private received evidence and full pipeline timing."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import tempfile
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
from tools.validation.motion_localization import (
    FS,
    LAYOUTS,
    direction,
    render,
    score,
    yaw,
)


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


def run_stream(
    data, factory=None, *, orientation=False, pipeline=True, threshold_dbfs=-60
):
    estimator = (
        MaintainedEventLocalizer()
        if factory is None
        else getattr(
            importlib.import_module(factory.split(":")[0]), factory.split(":")[1]
        )()
    )
    positions = np.array(data["positions"], dtype=float, copy=True)
    positions.setflags(write=False)
    array = MicrophoneArraySpec(
        array_id="rig",
        prim_path="/Array",
        position_world=(0, 0, 0),
        orientation_world_quat=yaw(0),
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
        q = yaw(float(data["receiver_yaw"][step])) if orientation else None
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
        if pipeline:
            frame = perception.process(
                block, array, frame_id=f"frame_{step}", receiver_orientation_xyzw=q
            )
            events = [o.doa for o in frame.observations if o.doa is not None]
            diag = frame.diagnostics["perception"]["localization"]
            activity = frame.diagnostics["perception"]["activity_detected"]
        elif callable(getattr(estimator, "localize_block", None)):
            events, diag = estimator.localize_block(
                samples,
                positions,
                FS,
                start_time_s=step / 10,
                receiver_orientation_xyzw=q,
            )
            activity = None
        else:
            history = data["samples"][:, max(0, end - 12000) : end].copy()
            history.setflags(write=False)
            events, diag = estimator.localize(history, positions, FS)
            activity = None
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
            sensitivity={
                str(th): assess(found, diag, data, step, th) for th in (-3, 3)
            },
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


def transitions(rows):
    """Consecutive received-source sets, including unresolved/missed responses."""
    result = []
    indices = [0] + [
        i
        for i in range(1, len(rows))
        if rows[i]["source_indices"] != rows[i - 1]["source_indices"]
    ]
    for start, stop in zip(indices, indices[1:] + [len(rows)], strict=True):
        response = next(
            (
                i
                for i in range(start + 1, stop)
                if rows[i - 1]["exact"] is True and rows[i]["exact"] is True
            ),
            None,
        )
        result.append(
            dict(
                start_s=rows[start]["time_s"] - 0.1,
                end_s=rows[stop - 1]["time_s"],
                source_indices=rows[start]["source_indices"],
                enough_updates=stop - start >= 2,
                response_ms=None
                if response is None
                else (rows[response]["time_s"] - (rows[start]["time_s"] - 0.1)) * 1000
                + rows[response]["completion_delay_ms"],
            )
        )
    return result


def render_occlusion(
    root,
    layout,
    content,
    scenario,
    rt60,
    imbalance,
    seed,
    assets,
    *,
    duration=4.0,
    snr_db=20.0,
):
    """Window-local direct loss with fixed noise, through the production renderer.

    Both complete renders share emission samples, poses and noise. Select clear,
    blocked, then clear receive windows; no crossfade or extra propagation delay.
    This evaluates the current window-local attenuation model, not moving edges
    or geometric indirect paths. Source contributions remain scoring-only.
    """
    base = "stationary2" if scenario == "occlusion_pair" else "control_20"
    args = (root, layout, content, base, rt60, imbalance, seed, assets)
    clear = render(
        *args,
        duration=duration,
        snr_db=snr_db,
        received_evidence=True,
        natural_speech=True,
    )
    losses = np.zeros((clear["received_power"].shape[1], len(LAYOUTS[layout])))
    losses[0, : 2 if scenario == "occlusion_partial" else losses.shape[1]] = 20
    blocked = render(
        *args,
        duration=duration,
        snr_db=snr_db,
        received_evidence=True,
        natural_speech=True,
        per_mic_loss_db=losses,
        noise_rms=np.sqrt(clear["noise_power"][0]),
    )
    mixed = {k: v.copy() for k, v in clear.items()}
    start, end = 10, 30
    sample_slice = slice(start * 1600, end * 1600)
    mixed["samples"][:, sample_slice] = blocked["samples"][:, sample_slice]
    for name in ("received_power", "direct_power"):
        mixed[name][start:end] = blocked[name][start:end]
    return mixed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate", action="append", default=[], help="name=module:factory"
    )
    parser.add_argument(
        "--layouts", nargs="+", choices=list(LAYOUTS), default=list(LAYOUTS)
    )
    parser.add_argument(
        "--contents",
        nargs="+",
        choices=["speech", "broadband", "disjoint"],
        default=["speech", "broadband", "disjoint"],
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=[
            "stationary0",
            "stationary1",
            "stationary2",
            "pass",
            "translate",
            "rotate",
            "mixed",
            "combined",
            "separated_mixed",
            "separated_combined",
            "crossing",
            "transitions",
            "level_change",
            "control_front",
            "control_20",
            "control_45",
            "occlusion_one",
            "occlusion_partial",
            "occlusion_pair",
            "replacement",
        ],
        default=["separated_mixed", "separated_combined"],
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--seed-base", type=int, default=1175000)
    parser.add_argument("--rt60", type=float, default=0.3)
    parser.add_argument("--imbalance", type=float, default=6)
    parser.add_argument("--snr-db", type=float, default=20)
    parser.add_argument("--orientation", action="store_true")
    parser.add_argument("--localizer-only", action="store_true")
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=Path("evidence/qualification/multisource/assets"),
    )
    parser.add_argument(
        "--partition", choices=["development", "confirmation"], default="development"
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = sorted(args.assets_dir.glob("*.flac"))
    assets = assets[::2] if args.partition == "development" else assets[1::2]
    if (
        args.episodes < 1
        or not np.isfinite([args.rt60, args.imbalance, args.snr_db]).all()
        or args.rt60 < 0
    ):
        parser.error(
            "Require positive episodes, nonnegative RT60 and finite acoustic parameters"
        )
    methods = {"maintained": None}
    for candidate in args.candidate:
        if "=" not in candidate or ":" not in candidate.split("=", 1)[1]:
            parser.error("Candidate must be name=module:factory")
        name, factory = candidate.split("=", 1)
        if not name or name in methods:
            parser.error("Candidate names must be unique and cannot replace maintained")
        methods[name] = factory
    if "speech" in args.contents and len(assets) < 2:
        parser.error("At least two distinct native 16 kHz speech assets are required")
    # A cache must not silently reuse another partition or asset pool.
    digest = hashlib.sha256()
    for path in assets:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    asset_key = digest.hexdigest()[:12]
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(
        protocol="received_energy_natural_v2",
        settings={
            k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
        },
        rows=[],
    )
    with tempfile.TemporaryDirectory(dir=args.cache_dir, prefix="render_") as temp:
        for layout in args.layouts:
            for content in args.contents:
                for episode in range(args.episodes):
                    seed = (
                        args.seed_base
                        + episode * 100
                        + list(LAYOUTS).index(layout) * 10000
                        + ["broadband", "speech", "disjoint"].index(content) * 1000
                    )
                    for scenario in args.scenarios:
                        key = (
                            f"v2_{args.partition}_{asset_key}_{layout}_{content}_{scenario}_{seed}_"
                            f"{args.rt60}_{args.imbalance}_{args.snr_db}"
                        )
                        cache = args.cache_dir / f"{key}.npz"
                        if cache.exists():
                            with np.load(cache, allow_pickle=False) as archive:
                                data = dict(archive)
                        else:
                            renderer = (
                                render_occlusion
                                if scenario.startswith("occlusion_")
                                else render
                            )
                            render_options = (
                                {}
                                if scenario.startswith("occlusion_")
                                else {"received_evidence": True, "natural_speech": True}
                            )
                            data = renderer(
                                Path(temp).resolve(),
                                layout,
                                content,
                                scenario,
                                args.rt60,
                                args.imbalance,
                                seed,
                                assets,
                                duration=6.0 if scenario == "transitions" else 4.0,
                                snr_db=args.snr_db,
                                **render_options,
                            )
                            np.savez_compressed(cache, **data)
                        for value in data.values():
                            value.setflags(write=False)
                        row = dict(
                            speech_assets=data["speech_assets"].tolist(),
                            layout=layout,
                            content=content,
                            episode=episode,
                            scenario=scenario,
                            results={},
                            summary={},
                        )
                        for name, factory in methods.items():
                            results = run_stream(
                                data,
                                factory,
                                orientation=args.orientation,
                                pipeline=not args.localizer_only,
                            )
                            row["results"][name] = results
                            row["summary"][name] = dict(
                                **summarize(results), transitions=transitions(results)
                            )
                            print(
                                key,
                                name,
                                {
                                    k: v
                                    for k, v in row["summary"][name].items()
                                    if k != "transitions"
                                },
                                flush=True,
                            )
                        report["rows"].append(row)
                        args.output.write_text(
                            json.dumps(report, indent=2, allow_nan=False)
                        )


if __name__ == "__main__":
    main()
