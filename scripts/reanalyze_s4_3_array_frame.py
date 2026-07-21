#!/usr/bin/env python3
"""Write one immutable S4.3 array-frame amendment replay beside retained raw data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from isaac_audio_sensors.acquisition.s4_2 import sha256_file, write_checksums
from isaac_audio_sensors.acquisition.s4_3 import (
    S43Error,
    analyze_trial_wav,
    canonical_sha256,
    load_json,
    load_pilot_configuration,
    validate_preregistration,
)
from isaac_audio_sensors.core.dataset.atomic import write_json_atomic

ROOT = Path(__file__).resolve().parents[1]


def reanalyze(args: argparse.Namespace) -> dict[str, object]:
    configuration = load_pilot_configuration(args.config, repo_root=ROOT)
    preregistration = load_json(args.preregistration)
    freeze = validate_preregistration(configuration, preregistration, repo_root=ROOT)
    if not freeze.passed:
        raise S43Error(f"amendment freeze failed: {freeze.to_dict()}")
    correction = configuration.get("analysis_frame_correction")
    if not isinstance(correction, dict):
        raise S43Error("active configuration has no analysis-frame correction")
    expected_filename = correction.get("reanalyzed_filename")
    if (
        expected_filename != args.output_name
        or Path(args.output_name).name != args.output_name
    ):
        raise S43Error("output name differs from the frozen amendment")
    attempt_root = (ROOT / args.attempt_root).resolve()
    try:
        attempt_root.relative_to((ROOT / "dataset/S4.3/attempts").resolve())
    except ValueError as exc:
        raise S43Error("attempt root is outside dataset/S4.3/attempts") from exc
    original_path = attempt_root / "analysis.json"
    wav_path = attempt_root / "raw/respeaker_audio.wav"
    if not original_path.is_file() or not wav_path.is_file():
        raise S43Error("retained original analysis or raw WAV is absent")
    original = load_json(original_path)
    if original.get("configuration_sha256") == canonical_sha256(configuration):
        raise S43Error("original analysis already uses the amended configuration")
    trial_id = original.get("trial_id")
    matches = [
        item for item in configuration["matrix"] if item.get("trial_id") == trial_id
    ]
    if len(matches) != 1:
        raise S43Error("retained trial is absent or duplicated in amended matrix")
    output_path = attempt_root / args.output_name
    provenance_path = attempt_root / f"{Path(args.output_name).stem}_provenance.json"
    checksum_path = attempt_root / "SHA256SUMS.amendment_01"
    if output_path.exists() or provenance_path.exists() or checksum_path.exists():
        raise S43Error("refusing to overwrite immutable amendment evidence")
    reference = ROOT / configuration["reference"]["local_path"]
    report = analyze_trial_wav(
        wav_path,
        matches[0],
        configuration,
        reference_path=(
            reference if "mac_reference" in str(matches[0]["stimulus"]) else None
        ),
    )
    if report.get("status") != "passed":
        raise S43Error(f"amended replay failed: {report.get('issues')}")
    write_json_atomic(output_path, report)
    provenance = {
        "schema": "ias.s4_3.amended_reanalysis_provenance.v1",
        "status": "passed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempt_id": attempt_root.name,
        "trial_id": trial_id,
        "raw_wav_sha256": sha256_file(wav_path),
        "original_analysis_path": "analysis.json",
        "original_analysis_sha256": sha256_file(original_path),
        "amended_analysis_path": args.output_name,
        "amended_analysis_sha256": sha256_file(output_path),
        "amended_scientific_replay_sha256": report["scientific_replay_sha256"],
        "configuration_path": args.config.as_posix(),
        "configuration_file_sha256": sha256_file(args.config),
        "configuration_canonical_sha256": canonical_sha256(configuration),
        "preregistration_path": args.preregistration.as_posix(),
        "preregistration_sha256": sha256_file(args.preregistration),
        "correction_id": correction["id"],
        "original_unfavorable_analysis_retained": True,
        "raw_modified": False,
        "thresholds_modified": False,
        "s4_4_started": False,
    }
    write_json_atomic(provenance_path, provenance)
    records = [
        {
            "path": output_path.relative_to(attempt_root).as_posix(),
            "sha256": sha256_file(output_path),
        },
        {
            "path": provenance_path.relative_to(attempt_root).as_posix(),
            "sha256": sha256_file(provenance_path),
        },
    ]
    write_checksums(checksum_path, attempt_root, records)
    return {
        "status": "passed",
        "attempt_root": args.attempt_root.as_posix(),
        "analysis": output_path.relative_to(ROOT).as_posix(),
        "analysis_sha256": sha256_file(output_path),
        "scientific_replay_sha256": report["scientific_replay_sha256"],
        "summary": report["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    try:
        result = reanalyze(args)
    except (OSError, S43Error, ValueError) as exc:
        print(f"S4.3 amended reanalysis failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
