"""Score actual loaded single-voice PCM and outputs, including misses and extras.

Run after audio_runtime_performance.py with Isaac's Python (USD/native producer).
Scalar replay is a CPU reference; the CUDA lane is the saved live observation.
Reference rendering/scoring is outside the measured loop and never enters inference.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tools.validation import lab_perception as evaluation
from tools.validation.audio_runtime_performance import (
    acoustic_rooms,
    bearing_at,
    distribution,
    window_work,
)

POSITIONS = np.array(
    [(-0.033, -0.033, 0), (-0.033, 0.033, 0), (0.033, 0.033, 0), (0.033, -0.033, 0)]
)


def received_reference(directory, report):
    """Same producer's order-zero LoS component, with unchanged motion cadence.

    This tests single-voice direct/specular rooms, not physical truth or NLOS.
    References use the first environment, as do the retained live PCM/outputs.
    """
    from pxr import Usd, UsdGeom

    from isaac_audio_sensors.core.acoustics import free_field_environment
    from isaac_audio_sensors.core.types import (
        AudioSceneSnapshot,
        AudioSourceSpec,
        AudioTimeWindow,
        MicrophoneArraySpec,
        MicrophoneSpec,
    )
    from isaac_audio_sensors.isaac.acoustic_scene import GeometryAcoustics

    args = SimpleNamespace(**report["args"])
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    cfg, sessions = acoustic_rooms(
        1,
        args.geometry_library,
        args.specular_library,
        0,
        args.acoustic_stage,
        stage=stage,
        envelope=getattr(args, "acoustic_envelope", False),
    )
    producer = GeometryAcoustics(acoustic_scene=sessions[0], geometry_config=cfg)
    array = MicrophoneArraySpec(
        array_id="array",
        prim_path="/Array",
        sample_rate_hz=16000,
        position_world=tuple(args.array_position),
        orientation_world_quat=(0, 0, 0, 1),
        microphones=tuple(
            MicrophoneSpec(mic_id=str(i), relative_position_m=tuple(p))
            for i, p in enumerate(POSITIONS)
        ),
    )
    source = AudioSourceSpec(
        source_id="speaker",
        gain_db=0.0,
        prim_path="/Source",
        class_label="audio",
        audio_asset_path=str(directory / "source.wav"),
        position_world=(0, 0, 0),
        orientation_world_quat=(0, 0, 0, 1),
        start_time_s=0.0,
        duration_s=None,
        loop_count=-1,
    )
    chunks = []
    radius = args.distance_m or 2.25
    try:
        for row in report["measurement"]["rows"]:
            t = row["audio_s"]
            angle = math.radians(
                35 * math.sin(t * args.source_speed_m_s / (radius * math.radians(35)))
            )
            yaw = math.radians(args.head_speed_deg_s * math.sin(t))
            if args.motion in ("static", "receiver"):
                angle = 0.0
            if args.motion in ("static", "source"):
                yaw = 0.0
            x, y, z = args.array_position
            snap = AudioSceneSnapshot(
                stage_id="scoring",
                arrays=(
                    replace(
                        array,
                        orientation_world_quat=(
                            0,
                            0,
                            math.sin(yaw / 2),
                            math.cos(yaw / 2),
                        ),
                    ),
                ),
                sources=(
                    replace(
                        source,
                        position_world=(
                            x + radius * math.cos(angle),
                            y + radius * math.sin(angle),
                            z,
                        ),
                    ),
                ),
                environment=free_field_environment(environment_id="scoring"),
            )
            tick = row["tick"]
            chunks.append(
                producer.propagate(
                    snap,
                    "array",
                    AudioTimeWindow(
                        start_time_s=math.floor(tick * 16000 / 60 + 1e-7) / 16000,
                        end_time_s=math.floor((tick + 1) * 16000 / 60 + 1e-7) / 16000,
                        frame_index=tick,
                    ),
                ).samples
            )
    finally:
        producer.close()
        sessions[0].close()
    direct = np.concatenate(chunks, axis=-1)
    samples = np.load(directory / "received-pcm.npz")["samples"]
    emitted = np.load(directory / "source-pcm.npz")["samples"]
    if direct.shape != samples.shape or emitted.shape != samples.shape:
        raise ValueError("Reference, source and live PCM shapes disagree")

    def power(pcm):
        return np.square(pcm.astype(float)).reshape(4, -1, 1600).mean(-1).max(0)

    times = np.arange(1, samples.shape[1] // 1600 + 1) / 10
    data = dict(
        samples=samples,
        positions=POSITIONS,
        sample_rate_hz=16000,
        received_power=power(emitted)[:, None],
        direct_power=power(direct)[:, None],
        noise_power=power(samples - emitted),
        scheduled_count=np.ones(len(times)),
        directions=np.array([evaluation.direction(bearing_at(t, args)) for t in times])[
            :, None
        ],
        azimuth_only=True,
    )
    np.savez(directory / "received-reference.npz", **data)
    return data


def score_live(data, report, outputs):
    rows = []
    updates = [r for r in report["measurement"]["rows"] if "sdk_ready_ms" in r]
    for step, timing in enumerate(updates):
        mask = outputs["bearing_deg_mask"][step, 0]
        found = [evaluation.direction(b) for b in outputs["bearing_deg"][step, 0, mask]]
        diag = {"status": "events" if found else "no_events"}
        if timing["audio_s"] < report["args"]["context_s"]:
            diag = {"status": "unavailable"}
        row = evaluation.assess(found, diag, data, step)
        row.update(
            time_s=timing["audio_s"],
            activity=timing["activity_detected"],
            diagnostic=diag,
            compute_ms=timing["sdk_ready_ms"],
            completion_delay_ms=timing["deadline_to_sdk_ms"],
            ambiguity_count=int(outputs["ambiguity_mask"][step, 0].sum()),
            observations_truncated=int(outputs["observations_truncated"][step, 0]),
        )
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    directory = args.run
    destination = directory / "quality.json"
    if destination.exists():
        raise FileExistsError(destination)
    report = json.loads((directory / "report.json").read_text())
    if (
        not report["args"]["geometry_library"]
        or report["status"] != "measured"
        or report["args"]["envs"] != 1
    ):
        raise ValueError(
            "A completed single-environment native Geometry run is required"
        )
    data = received_reference(directory, report)
    scalar = evaluation.run_stream(
        data,
        localization_context_s=report["args"]["context_s"],
        localization_dereverberation=report["args"]["wpe"],
        localization_spatial_coherence=report["args"]["spatial_coherence"],
    )
    live = score_live(data, report, np.load(directory / "observations.npz"))
    comparisons = [
        evaluation.score(a["directions"], b["directions"])
        for a, b in zip(live, scalar, strict=True)
    ]
    differences = [
        dict(
            update=i + 1,
            audio_s=a["time_s"],
            scalar_count=b["detected"],
            cuda_count=a["detected"],
            scalar_directions=b["directions"],
            cuda_directions=a["directions"],
        )
        for i, (a, b) in enumerate(zip(live, scalar, strict=True))
        if a["detected"] != b["detected"]
        or a["activity"] != b["activity"]
        or any(e > 0.1 for e in comparisons[i]["errors"])
    ]
    context = round(report["args"]["context_s"] * 16000)
    result = dict(
        scope="loaded CUDA outputs; same-PCM scalar reference; one voice, LoS",
        window_work_ms=window_work(report["measurement"]["rows"]),
        live=evaluation.case_report(data, live, context_samples=context),
        scalar=evaluation.case_report(data, scalar, context_samples=context),
        activity_agreement=float(
            np.mean(
                [
                    a["activity"] == b["activity"]
                    for a, b in zip(live, scalar, strict=True)
                ]
            )
        ),
        count_agreement=float(np.mean([c["count"] for c in comparisons])),
        direction_difference_deg=distribution(
            [e for c in comparisons for e in c["errors"]]
        ),
        discrepancies=differences,
        rows=dict(live=live, scalar=scalar),
    )
    gate = result["live"]["common_after_750ms"]
    result["single_voice_quality_pass"] = bool(
        gate["active_resolvable_updates"] > 0
        and gate["active_complete_set_rate"] >= 0.9
        and gate["active_long_error_runs"] == 0
        and all(
            s["response_delay_ms"] is not None and s["response_delay_ms"] <= 400
            for s in result["live"]["direction_onset_responses"]
        )
    )
    result["combined_pass"] = bool(
        result["single_voice_quality_pass"]
        and report["measurement"]["interactive_timing_pass"]
        and report["measurement"]["gpu_load"]["clean"]
    )
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("rows", "live", "scalar")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
