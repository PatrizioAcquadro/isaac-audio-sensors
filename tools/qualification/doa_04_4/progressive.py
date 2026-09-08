"""Paired room-robustness diagnosis; all scene facts stay evaluator-owned."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
from scipy.signal import fftconvolve

from .cases import ARRAYS, ASSETS, FS, ROOT, match, summary, wave
from .evaluate import construct

PROTOCOL = Path(__file__).with_name("progressive_protocol.json")


def decay_t20(rir):
    energy = np.cumsum(np.square(rir)[::-1])[::-1]
    if not energy[0]:
        return None
    db = 10 * np.log10(np.maximum(energy / energy[0], 1e-30))
    fit = (db <= -5) & (db >= -25)
    if fit.sum() < 10:
        return None
    slope = np.polyfit(np.arange(len(rir))[fit] / FS, db[fit], 1)[0]
    return float(-60 / slope) if slope < 0 else None


def episode(array, content, repeat, seed_base, *, speech_assets=None):
    seed = (
        seed_base
        + (
            list(ARRAYS).index(array) * 3
            + ("speech", "noise", "disjoint").index(content)
        )
        * 100
        + repeat
    )
    room_rng, signal_rng, noise_rng = [
        np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(3)
    ]
    dims = np.array([6, 5, 4]) + room_rng.uniform(-0.3, 0.3, 3)
    center = dims / 2 + room_rng.uniform(-0.2, 0.2, 3)
    az = room_rng.uniform(-np.pi, np.pi)
    el = room_rng.uniform(-np.pi / 4, np.pi / 4) if array in ("raised", "tetra") else 0
    origin = np.array([np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), np.sin(el)])
    tangent = (
        np.array([-np.cos(az) * np.sin(el), -np.sin(az) * np.sin(el), np.cos(el)])
        if array in ("raised", "tetra") and repeat % 2
        else np.array([-np.sin(az), np.cos(az), 0])
    )
    indices = (
        signal_rng.choice(len(ASSETS["reference"]), 2, replace=False)
        if content == "speech"
        else [0, 1]
    )
    assets = [ASSETS["reference"][i] for i in indices] if content == "speech" else []
    if content == "speech" and speech_assets is not None:
        # Pair different speakers; utterances from a speaker remain in one block.
        speakers = sorted({a["speaker"] for a in speech_assets})
        chosen = signal_rng.choice(speakers, 2, replace=False)
        assets = [
            str(
                signal_rng.choice(
                    [a["name"] for a in speech_assets if a["speaker"] == s]
                )
            )
            for s in chosen
        ]
    sources = [
        wave(
            content,
            "reference",
            int(i),
            signal_rng,
            16000,
            asset_name=assets[source] if assets else None,
        )
        for source, i in enumerate(indices)
    ]
    noise = noise_rng.standard_normal((len(ARRAYS[array]), 4000))
    noise /= np.sqrt(np.mean(noise**2))
    return dict(
        seed=seed,
        dims=dims,
        center=center,
        origin=origin,
        tangent=tangent,
        sources=sources,
        noise=noise,
        assets=assets,
    )


def room_responses(ep, array, stage, truth):
    """Room and direct responses shared by steady and transition evaluations."""
    rt = stage["rt60"]
    distance = stage.get("distance_m", 1.5)
    absorption, order = pra.inverse_sabine(rt, ep["dims"]) if rt else (1.0, 0)

    def rirs(max_order):
        room = pra.ShoeBox(
            ep["dims"], fs=FS, materials=pra.Material(absorption), max_order=max_order
        )
        room.add_microphone_array((ARRAYS[array] + ep["center"]).T)
        for direction in truth:
            room.add_source(ep["center"] + distance * direction)
        room.compute_rir()
        return room.rir

    room_rir = rirs(order)
    return room_rir, rirs(0) if rt else room_rir


def render_stage(
    array,
    content,
    repeat,
    stage,
    seed_base,
    *,
    history_samples=4000,
    speech_assets=None,
):
    if not 4000 <= history_samples <= 12000:
        raise ValueError("History must contain 4000 to 12000 samples")
    key = dict(
        array=array,
        content=content,
        repeat=repeat,
        stage=stage,
        seed_base=seed_base,
        renderer="paired_room_v1",
    )
    if history_samples != 4000:
        key["history_samples"] = history_samples
    if speech_assets is not None and content == "speech":
        key["speech_assets"] = speech_assets
    path = (
        ROOT
        / "progressive_mixtures"
        / (
            hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]
            + ".npz"
        )
    )
    if path.exists():
        with np.load(path) as data:
            return data["mixtures"], data["truth"], json.loads(str(data["acoustics"]))
    ep = episode(array, content, repeat, seed_base, speech_assets=speech_assets)
    angle = np.radians(stage["separation"])
    truth = np.stack(
        [ep["origin"], np.cos(angle) * ep["origin"] + np.sin(angle) * ep["tangent"]]
    )
    rt = stage["rt60"]
    distance = stage.get("distance_m", 1.5)
    room_rir, direct_rir = room_responses(ep, array, stage, truth)
    stems = []
    ratios = []
    decays = []
    for source, mono in enumerate(ep["sources"]):
        stem = np.stack(
            [
                fftconvolve(mono, room_rir[m][source])[12000 - history_samples : 12000]
                for m in range(len(ARRAYS[array]))
            ]
        )
        stem *= (
            0.03
            / np.sqrt(np.mean(stem[0, -4000:] ** 2))
            * 10 ** (-stage["imbalance"] * source / 20)
        )
        stems.append(stem)
        reflected = room_rir[0][source].copy()
        direct = direct_rir[0][source]
        reflected[: len(direct)] -= direct
        ratios.append(
            float(10 * np.log10(np.sum(direct**2) / max(np.sum(reflected**2), 1e-30)))
        )
        decays.append(decay_t20(room_rir[0][source]) if rt else None)
    mixtures = []
    noise = ep["noise"]
    if history_samples > 4000:
        prior_rng = np.random.default_rng(np.random.SeedSequence([ep["seed"], 4]))
        noise = np.concatenate(
            (
                prior_rng.standard_normal((len(ARRAYS[array]), 8000))[
                    :, -(history_samples - 4000) :
                ],
                noise,
            ),
            axis=1,
        )
    for count in (0, 1, 2):
        mix = sum(stems[:count], np.zeros_like(stems[0]))
        level = (
            np.sqrt(np.mean(mix[:, -4000:] ** 2)) * 10 ** (-stage["snr"] / 20)
            if count
            else 0.0001
        )
        mixtures.append(mix + noise * level)
    acoustics = dict(
        seed=ep["seed"],
        assets=ep["assets"],
        room_dimensions_m=ep["dims"].tolist(),
        array_center_m=ep["center"].tolist(),
        target_rt60_s=rt,
        t20_extrapolated_s=decays,
        direct_reflected_energy_db=ratios if rt else [None, None],
        source_distance_m=distance,
    )
    path.parent.mkdir(exist_ok=True)
    np.savez_compressed(
        path,
        mixtures=np.asarray(mixtures),
        truth=truth,
        acoustics=json.dumps(acoustics),
    )
    return np.asarray(mixtures), truth, acoustics


def pair_summary(pairs):
    result = {}
    result["exact_pair_count"] = float(np.mean([r["count_correct"] for r in pairs]))
    result["both_localized_without_extras"] = float(
        np.mean([r["tp"] == 2 and r["fp"] == 0 for r in pairs])
    )
    result["pair_undercounts"] = sum(r["count_error"] < 0 for r in pairs)
    result["pair_overcounts"] = sum(r["count_error"] > 0 for r in pairs)
    if pairs and all("matched_truth_indices" in r for r in pairs):
        result["second_source_recall"] = float(
            np.mean([1 in r["matched_truth_indices"] for r in pairs])
        )
    return result


def grouped(rows, protocol):
    results = {}
    for name in sorted({r["candidate"] for r in rows}):
        results[name] = {}
        for array in ARRAYS:
            results[name][array] = {}
            for stage in protocol["stages"]:
                subset = [
                    r
                    for r in rows
                    if r["candidate"] == name
                    and r["array"] == array
                    and r["stage"] == stage["name"]
                ]
                if not subset:
                    continue
                st = summary(subset)
                pairs = [r for r in subset if r["count"] == 2]
                st.update(pair_summary(pairs))
                st["by_count"] = {
                    str(c): summary([r for r in subset if r["count"] == c])
                    for c in (0, 1, 2)
                }
                st["by_content"] = {
                    c: {
                        **summary([r for r in subset if r["content"] == c]),
                        **pair_summary([r for r in pairs if r["content"] == c]),
                    }
                    for c in protocol["contents"]
                }
                thresholds = protocol["quality_reference"]
                st["below_reference"] = [
                    k
                    for k in ("precision", "recall")
                    if st[k] is None or st[k] < thresholds["minimum_" + k]
                ]
                if st["exact_pair_count"] < thresholds["minimum_pair_count_accuracy"]:
                    st["below_reference"].append("pair_count")
                for metric in ("count_accuracy", "both_localized_without_extras"):
                    minimum = thresholds.get("minimum_" + metric)
                    if minimum is not None and st[metric] < minimum:
                        st["below_reference"].append(metric)
                if (
                    st["angular_p95"] is None
                    or st["angular_p95"] > thresholds["maximum_angular_p95_deg"]
                ):
                    st["below_reference"].append("angle")
                results[name][array][stage["name"]] = st
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--loading", type=float, action="append")
    parser.add_argument("--stage", action="append")
    parser.add_argument("--distance", type=float, action="append")
    parser.add_argument(
        "--refit-statistic", choices=("product", "mean"), default="product"
    )
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise FileExistsError(output)
    protocol = json.loads(args.protocol.read_text())
    if args.threshold is not None:
        protocol["threshold"] = args.threshold
    protocol["refit_statistic"] = args.refit_statistic
    if args.stage:
        unknown = set(args.stage) - {s["name"] for s in protocol["stages"]}
        if unknown:
            parser.error(f"Unknown stages: {sorted(unknown)}")
        protocol["stages"] = [s for s in protocol["stages"] if s["name"] in args.stage]
    if args.distance:
        if any(d <= 0 or d > 1.5 for d in args.distance):
            parser.error("Distances must be in (0, 1.5] m to stay inside every room")
        protocol["stages"] = [
            dict(s, name=f"{s['name']}_distance_{d:g}", distance_m=d)
            for d in args.distance
            for s in protocol["stages"]
        ]
    loadings = args.loading or [0.0001]
    protocol["compared_relative_loadings"] = loadings
    rows = []
    for array in ARRAYS:
        candidates = {}
        for loading in loadings:
            candidate = construct(protocol["candidate"], protocol["threshold"])
            candidate.relative_loading = loading
            candidate.refit_statistic = args.refit_statistic
            name = protocol["candidate"] if loading == 0.0001 else f"loading_{loading}"
            if args.refit_statistic != "product":
                name += f"_{args.refit_statistic}"
            candidates[name] = candidate
        for content in protocol["contents"]:
            for repeat in range(protocol["repetitions"]):
                for stage in protocol["stages"]:
                    mixtures, truth, acoustics = render_stage(
                        array, content, repeat, stage, protocol["seed_base"]
                    )
                    for count in protocol["counts"]:
                        samples = np.ascontiguousarray(mixtures[count])
                        samples.setflags(write=False)
                        for name, candidate in candidates.items():
                            start = time.perf_counter()
                            pred, diagnostics = candidate.localize(
                                samples, ARRAYS[array], FS
                            )
                            rows.append(
                                dict(
                                    candidate=name,
                                    array=array,
                                    content=content,
                                    repeat=repeat,
                                    stage=stage["name"],
                                    count=count,
                                    acoustics=acoustics,
                                    predicted=pred.tolist(),
                                    truth=truth[:count].tolist(),
                                    diagnostics=diagnostics,
                                    compute_ms=1000 * (time.perf_counter() - start),
                                    **match(pred, truth[:count]),
                                )
                            )
            print(array, content, len(rows), flush=True)
            output.write_text(
                json.dumps(dict(protocol=protocol, rows=rows), indent=2) + "\n"
            )
    result = dict(protocol=protocol, summary=grouped(rows, protocol), rows=rows)
    output.write_text(json.dumps(result, indent=2) + "\n")
    for candidate, arrays in result["summary"].items():
        for array, stages in arrays.items():
            for stage, st in stages.items():
                print(
                    candidate,
                    array,
                    stage,
                    st["precision"],
                    st["recall"],
                    st["exact_pair_count"],
                    st["below_reference"],
                    flush=True,
                )


if __name__ == "__main__":
    main()


def render_transitions(array, content, repeat, seed_base, stage, *, speech_assets=None):
    """Causal room tails for 0/1/2 changes and a one-source direction replacement."""
    ep = episode(array, content, repeat, seed_base, speech_assets=speech_assets)
    angle = np.radians(stage["separation"])
    truth = np.stack(
        [ep["origin"], np.cos(angle) * ep["origin"] + np.sin(angle) * ep["tangent"]]
    )
    responses, _ = room_responses(ep, array, stage, truth)
    # The final 1 -> 1 switch replaces the bearing without changing cardinality.
    active_sets = ((), (0,), (0, 1), (0,), (), (0, 1), (), (0,), (1,), ())
    phase_samples = 24000
    length = len(active_sets) * phase_samples
    rng = np.random.default_rng(np.random.SeedSequence([ep["seed"], 17]))
    samples = rng.standard_normal((len(ARRAYS[array]), length)) * 0.003
    for source, mono in enumerate(ep["sources"]):
        dry = np.tile(mono, int(np.ceil(length / len(mono))))[:length]
        reference = fftconvolve(dry, responses[0][source])[24000:48000]
        scale = (
            0.03
            * 10 ** (-stage["imbalance"] * source / 20)
            / np.sqrt(np.mean(reference**2))
        )
        dry *= (
            np.repeat([source in active for active in active_sets], phase_samples)
            * scale
        )
        samples += np.stack(
            [
                fftconvolve(dry, responses[m][source])[:length]
                for m in range(len(ARRAYS[array]))
            ]
        )
    return samples, [truth[list(active)] for active in active_sets], phase_samples
