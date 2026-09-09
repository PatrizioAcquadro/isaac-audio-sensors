"""Paired numerical motion/indoor evaluation; no visualization or media delivery."""

from __future__ import annotations

import argparse
import importlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy.optimize import linear_sum_assignment
from scipy.signal import butter, sosfiltfilt

from isaac_audio_sensors.core.acoustics import (
    free_field_environment,
    shoebox_environment,
)
from isaac_audio_sensors.core.backends.analytic import AnalyticAcoustics
from isaac_audio_sensors.core.motion import (
    SegmentEntityMotion,
    WindowMotionPlan,
    WindowMotionSegment,
)
from isaac_audio_sensors.core.plugins.multisource import MaintainedEventLocalizer
from isaac_audio_sensors.core.types import (
    AudioSceneSnapshot,
    AudioSourceSpec,
    AudioTimeWindow,
    MicrophoneArraySpec,
    MicrophoneSpec,
)

FS = 16000
LAYOUTS = {
    "triangle": ((-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0)),
    "square": (
        (-0.033, -0.033, 0),
        (-0.033, 0.033, 0),
        (0.033, 0.033, 0),
        (0.033, -0.033, 0),
    ),
    "raised": (
        (-0.03, -0.03, 0),
        (-0.03, 0.03, 0),
        (0.03, 0.03, 0),
        (0.03, -0.03, 0),
        (0, 0, 0.04),
    ),
    "tetra": (
        (0.03, 0.03, 0.03),
        (0.03, -0.03, -0.03),
        (-0.03, 0.03, -0.03),
        (-0.03, -0.03, 0.03),
    ),
}


def angle_cost(first, second):
    return np.degrees(
        np.arccos(np.clip(np.asarray(first) @ np.asarray(second).T, -1, 1))
    )


class Candidate:
    """The public mixture-only localizer protocol is also the evaluation boundary."""

    def __init__(self, factory=None):
        if factory is None:
            self.estimator = MaintainedEventLocalizer()
        else:
            module, name = factory.split(":", 1)
            self.estimator = getattr(importlib.import_module(module), name)()

    def localize(self, samples, positions):
        events, diagnostic = self.estimator.localize(samples, positions, FS)
        vectors = np.array(
            [
                direction(
                    event.estimated_bearing_deg, event.estimated_elevation_deg or 0.0
                )
                for event in events
                if event.estimated_bearing_deg is not None
            ]
        ).reshape(-1, 3)
        return vectors, diagnostic


def score(found, truth):
    errors = []
    matches = []
    if len(found) and len(truth):
        cost = angle_cost(found, truth)
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


def yaw(angle):
    return (0.0, 0.0, float(np.sin(angle / 2)), float(np.cos(angle / 2)))


def dry_signal(content, source, duration, rng, assets):
    count = round(duration * FS)
    if content == "speech":
        path = assets[int(rng.integers(len(assets)))]
        signal, fs = sf.read(path)
        if fs != FS:
            raise ValueError("Speech assets must be native 16 kHz")
        start = int(rng.integers(max(1, len(signal) - count)))
        signal = np.resize(signal[start:], count)
    else:
        band = (
            [300, 5000]
            if content == "broadband"
            else ([300, 2100] if source == 0 else [2500, 5000])
        )
        signal = sosfiltfilt(
            butter(4, band, fs=FS, btype="bandpass", output="sos"),
            rng.normal(size=count),
        )
    return 0.1 * signal / max(float(np.sqrt(np.mean(signal**2))), 1e-12)


def render(
    root,
    layout,
    content,
    scenario,
    rt60,
    imbalance,
    seed,
    assets,
    *,
    duration,
    snr_db=20.0,
):
    """Return received PCM and scoring truth, never pass truth to estimators."""
    rng = np.random.default_rng(seed)
    positions = np.array(LAYOUTS[layout])
    three_d = layout in ("raised", "tetra")
    center = np.array([3.0, 2.5, 1.5])
    array = MicrophoneArraySpec(
        array_id="rig",
        prim_path="/Array",
        position_world=tuple(center),
        orientation_world_quat=yaw(0),
        sample_rate_hz=FS,
        microphones=tuple(
            MicrophoneSpec(mic_id=str(i), relative_position_m=tuple(p))
            for i, p in enumerate(positions)
        ),
    )
    az = float(rng.uniform(-12, 12))
    base = [
        center + 1.5 * direction(20 + az, 15 if three_d else 0),
        center + 1.5 * direction(90 + az, -25 if three_d else 0),
    ]
    count = (
        int(scenario[-1])
        if scenario.startswith("stationary")
        else (1 if scenario in ("pass", "translate", "rotate") else 2)
    )
    motion_kind = scenario.removeprefix("separated_")
    if scenario.startswith("separated_"):
        base[1] = center + 1.5 * direction(-80 + az, -25 if three_d else 0)
    starts = [0.0, 0.0]
    stops = [duration, duration]
    if scenario == "transitions":
        starts = [0.3, 1.4]
        stops = [3.4, 2.6]

    def pose(index, t):
        if motion_kind == "pass" or (
            motion_kind in ("mixed", "combined") and index == 0
        ):
            return center + np.array([1.8 - 1.0 * t, 1.25, 0.2 if three_d else 0])
        if scenario == "crossing":
            return center + np.array(
                [
                    (1.6 - 1.0 * t) * (1 if index == 0 else -1),
                    1.3 if index == 0 else 1.8,
                    0.2 * (-1 if index else 1) if three_d else 0,
                ]
            )
        return base[index]

    def receiver(t):
        return (
            center + np.array([0.25 * t, 0, 0])
            if motion_kind in ("translate", "combined")
            else center
        )

    def rotation(t):
        return 0.7 * t if motion_kind in ("rotate", "combined") else 0.0

    sources = []
    for i in range(count):
        dry = dry_signal(content, i, duration, rng, assets) * 10 ** (
            -imbalance * i / 20
        )
        if scenario == "transitions":
            stamps = np.arange(len(dry)) / FS
            dry *= (stamps >= starts[i]) & (stamps < stops[i])
        if scenario == "level_change" and i == 1:
            dry[round(2 * FS) :] *= 10 ** (-6 / 20)
        path = root / f"source{i}.wav"
        sf.write(path, dry, FS, subtype="FLOAT")
        sources.append(
            AudioSourceSpec(
                source_id=f"s{i}",
                prim_path=f"/Source{i}",
                class_label="Sound",
                audio_asset_path=str(path.relative_to(Path.cwd())),
                position_world=tuple(pose(i, 0)),
                orientation_world_quat=yaw(0),
                start_time_s=0.0,
                duration_s=duration,
                gain_db=0.0,
            )
        )
    if rt60:
        absorption = pra.inverse_sabine(rt60, [6, 5, 3])[0]
        environment = shoebox_environment(
            environment_id="room", dimensions_m=(6.0, 5.0, 3.0), absorption=absorption
        )
    else:
        environment = free_field_environment(environment_id="free")
    scene = AudioSceneSnapshot(
        stage_id="evaluation",
        arrays=(array,),
        sources=tuple(sources),
        environment=environment,
    )
    backend = AnalyticAcoustics(max_order=10 if rt60 else 0)
    truth = []
    start = 0.0
    end = duration
    current = replace(
        scene,
        arrays=(
            replace(
                array,
                position_world=tuple(receiver(start)),
                orientation_world_quat=yaw(rotation(start)),
            ),
        ),
        sources=tuple(
            replace(s, position_world=tuple(pose(i, start)))
            for i, s in enumerate(sources)
        ),
    )
    entities = {}
    for key, pfun, qfun in [("rig", receiver, rotation)] + [
        (f"s{i}", lambda t, i=i: pose(i, t), lambda t: 0.0) for i in range(count)
    ]:
        entities[key] = SegmentEntityMotion(
            start_position_world_m=tuple(pfun(start)),
            end_position_world_m=tuple(pfun(end)),
            midpoint_position_world_m=tuple(pfun((start + end) / 2)),
            velocity_world_mps=tuple((pfun(end) - pfun(start)) / duration),
            velocity_source="derived",
            start_orientation_world_xyzw=yaw(qfun(start)),
            end_orientation_world_xyzw=yaw(qfun(end)),
        )
    backend.window_motion = WindowMotionPlan(
        sample_rate_hz=FS,
        window_sample_count=round(duration * FS),
        segments=(
            WindowMotionSegment(
                index=0,
                start_sample=0,
                end_sample=round(duration * FS),
                start_time_s=start,
                end_time_s=end,
                entities=entities,
            ),
        ),
    )
    block = backend.propagate(
        current,
        "rig",
        AudioTimeWindow(start_time_s=start, end_time_s=end, frame_index=0),
    )
    for end in np.arange(1, round(duration / 0.1) + 1) * 0.1:
        target = []
        for i in range(count):
            te = end
            for _ in range(8):
                te = end - np.linalg.norm(pose(i, te) - receiver(end)) / 343
            if starts[i] <= te < stops[i]:
                v = pose(i, te) - receiver(end)
                v /= np.linalg.norm(v)
                q = rotation(end)
                target.append(
                    [
                        np.cos(q) * v[0] + np.sin(q) * v[1],
                        -np.sin(q) * v[0] + np.cos(q) * v[1],
                        v[2],
                    ]
                )
        truth.append(np.array(target).reshape(-1, 3))
    values = block.samples.astype(float)
    noise_scale = np.sqrt(np.mean(values**2)) * 10 ** (-snr_db / 20) if count else 0.003
    values += rng.normal(0, noise_scale, values.shape)
    return values, truth, positions


def evaluation_cases(args, seed_base):
    from itertools import product

    scenarios = args.scenarios or (
        ["stationary0", "stationary1", "stationary2"]
        if args.suite == "stationary"
        else [
            "pass",
            "translate",
            "rotate",
            "mixed",
            "combined",
            "crossing",
            "transitions",
        ]
    )
    for layout, content, episode, rt60, imbalance in product(
        args.layouts, args.contents, range(args.episodes), args.rt60, args.imbalance
    ):
        if args.suite == "moving" and (rt60, imbalance) not in (
            (args.rt60[0], args.imbalance[0]),
            (args.rt60[-1], args.imbalance[-1]),
        ):
            continue
        for index, scenario in enumerate(scenarios):
            if args.suite == "moving" and args.scenarios is None:
                family = (index + list(LAYOUTS).index(layout)) % len(args.contents)
                if content != args.contents[family]:
                    continue
            yield dict(
                layout=layout,
                content=content,
                episode=episode,
                rt60=rt60,
                imbalance=imbalance,
                scenario=scenario,
                snr_db=args.snr_db,
                seed=seed_base
                + episode * 100
                + list(LAYOUTS).index(layout) * 10000
                + ("broadband", "speech", "disjoint").index(content) * 1000,
            )


def evaluate_case(case, args, assets, root):
    duration = 0.9 if args.suite == "stationary" else 4.0
    cache = None
    if args.cache_dir is not None:
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        name = "_".join(
            str(case[k])
            for k in ("layout", "content", "scenario", "rt60", "imbalance", "seed")
        )
        if args.snr_db != 20:
            name += f"_snr{args.snr_db}"
        cache = args.cache_dir / f"{name}.npz"
    if cache is not None and cache.exists():
        with np.load(cache, allow_pickle=False) as data:
            values, positions = data["samples"], data["positions"]
            truth = np.split(data["truth"], np.cumsum(data["counts"])[:-1])
    else:
        values, truth, positions = render(
            root,
            case["layout"],
            case["content"],
            case["scenario"],
            case["rt60"],
            case["imbalance"],
            case["seed"],
            assets,
            duration=duration,
            snr_db=args.snr_db,
        )
        if cache is not None:
            np.savez_compressed(
                cache,
                samples=values,
                positions=positions,
                truth=np.concatenate(truth),
                counts=[len(t) for t in truth],
            )
    if values.shape != (
        len(LAYOUTS[case["layout"]]),
        round(duration * FS),
    ) or not np.array_equal(positions, LAYOUTS[case["layout"]]):
        raise ValueError("Cached geometry/duration mismatch; use a new cache directory")
    values.setflags(write=False)
    positions.setflags(write=False)
    candidates = {"maintained": Candidate()}
    if args.candidate:
        candidates["candidate"] = Candidate(args.candidate)
    results = {name: [] for name in candidates}
    ends = (
        [values.shape[1]]
        if args.suite == "stationary"
        else range(12800, values.shape[1] + 1, 1600)
    )
    for end in ends:
        expected = truth[end // 1600 - 1]
        for name, estimator in candidates.items():
            then = time.perf_counter()
            found, diagnostic = estimator.localize(
                values[:, end - 12000 : end], positions
            )
            elapsed = time.perf_counter() - then
            result = score(found, expected)
            result["available"] = diagnostic.get("status") != "unavailable"
            if not result["available"]:
                result["exact"] = False
            result.update(time_s=end / FS, compute_ms=elapsed * 1000)
            results[name].append(result)
    return dict(case, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", choices=["stationary", "moving"], default="stationary"
    )
    parser.add_argument(
        "--partition", choices=["development", "confirmation"], default="development"
    )
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--seed-base", type=int)
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=Path("evidence/qualification/multisource/assets"),
    )
    parser.add_argument(
        "--candidate", help="Optional module:factory implementing EventLocalizer"
    )
    parser.add_argument(
        "--layouts", nargs="+", choices=list(LAYOUTS), default=list(LAYOUTS)
    )
    parser.add_argument(
        "--contents",
        nargs="+",
        choices=["broadband", "speech", "disjoint"],
        default=["broadband", "speech", "disjoint"],
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
        ],
    )
    parser.add_argument("--rt60", type=float, nargs="+", default=[0.2, 0.3])
    parser.add_argument("--imbalance", type=float, nargs="+", default=[0, 6])
    parser.add_argument("--snr-db", type=float, default=20.0)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("--episodes must be positive")
    if args.candidate and ":" not in args.candidate:
        parser.error("--candidate must be module:factory")
    assets = sorted(args.assets_dir.glob("*.flac"))
    assets = assets[::2] if args.partition == "development" else assets[1::2]
    if "speech" in args.contents and not assets:
        parser.error("Speech evaluation requires existing native 16 kHz FLAC assets")
    seed_base = (
        args.seed_base
        if args.seed_base is not None
        else (731000 if args.partition == "development" else 963000)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Path("build/validation").mkdir(parents=True, exist_ok=True)
    report = dict(
        partition=args.partition,
        suite=args.suite,
        seed_base=seed_base,
        candidate=args.candidate,
        rows=[],
    )
    with tempfile.TemporaryDirectory(
        dir="build/validation", prefix="motion_audio_"
    ) as temp:
        for case in evaluation_cases(args, seed_base):
            report["rows"].append(
                evaluate_case(case, args, assets, Path(temp).resolve())
            )
            args.output.write_text(json.dumps(report, indent=2))
            print(
                case["layout"],
                case["content"],
                case["episode"],
                case["scenario"],
                case["rt60"],
                case["imbalance"],
                len(report["rows"]),
                flush=True,
            )


if __name__ == "__main__":
    main()
