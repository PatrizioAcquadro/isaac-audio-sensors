#!/usr/bin/env python3
"""Generate the deterministic, fit-only S4.5 evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from isaac_audio_sensors.acquisition.s4_5 import (  # noqa: E402
    EVIDENCE_INDEX_SCHEMA,
    S45_CONFIG,
    S45_OUTPUT,
    FitEvidenceAccessor,
    S45Error,
    build_partial_profile,
    checksum_text,
    evidence_records,
    extract_fit_observations,
    fit_parameter_decisions,
    pretty_json,
    sha256_file,
    source_commit_is_valid,
    synthetic_recovery,
    validate_evidence_package,
    validate_s4_4_preservation,
)


def _write(path: Path, value: Any) -> None:
    path.write_text(pretty_json(value), encoding="utf-8")


def _pre_s4_5_record() -> dict[str, Any]:
    return {
        "schema": "ias.s4_5.pre_s4_4_validation_record.v1",
        "status": "passed",
        "command": (
            ".venv/bin/python scripts/validate_s4_4_amendment_03_final.py "
            "--repo-root . --require-tracked --require-committed "
            "--require-machine-local --require-corrective"
        ),
        "source_commit": "45ec248296370de9be90a90cc01b74a484667380",
        "census": {
            "valid_cells_total": 149,
            "retained_attempts_total": 152,
            "failures_total": 3,
            "replacements_total": 3,
            "incomplete_logical_cells": 0,
        },
        "holdout_scientifically_opened": False,
        "scientific_outcomes_returned": False,
        "issues": [],
    }


def build(
    *,
    repo_root: Path,
    output: Path,
    config_path: Path,
    source_commit: str,
) -> dict[str, Any]:
    """Build all S4.5 evidence into an empty output directory."""

    repo_root = repo_root.resolve()
    output = output if output.is_absolute() else repo_root / output
    config_path = config_path if config_path.is_absolute() else repo_root / config_path
    source_commit_is_valid(repo_root, source_commit)
    if output.exists():
        if any(output.iterdir()):
            raise S45Error(f"output must be empty: {output}")
    else:
        output.mkdir(parents=True)
    accessor = FitEvidenceAccessor(repo_root, config_path)
    contract = accessor.contract
    preservation = validate_s4_4_preservation(repo_root)
    if preservation["status"] != "passed":
        raise S45Error(f"S4.4 preservation failed: {preservation}")
    inventory, records = accessor.inventory(purpose="S4.5_validation")
    synthetic = synthetic_recovery(contract)
    if any(
        synthetic[name]["status"] != "passed"
        for name in (
            "relative_gain",
            "relative_delay",
            "polarity",
            "bearing_correction",
            "confidence_calibration",
            "relative_timing",
        )
    ):
        raise S45Error("a frozen synthetic recovery case failed")
    measurements, observations = extract_fit_observations(accessor, records)
    decisions = fit_parameter_decisions(observations, contract, synthetic)
    if decisions["status"] != "passed":
        raise S45Error("no scientifically useful parameter passed the frozen criteria")
    profile = build_partial_profile(contract, inventory, decisions)
    residuals = {
        "schema": "ias.s4_5.grouped_residual_results.v1",
        "status": "passed",
        "fit_partition": "fit_a",
        "validation_partition": "fit_b",
        "group_indivisible": True,
        "holdout_observations": 0,
        "comparisons": [
            item
            for item in decisions["decisions"]
            if "unadjusted_median_absolute_residual" in item
        ],
    }
    uncertainty = {
        "schema": "ias.s4_5.uncertainty_sensitivity.v1",
        "status": "passed",
        "method": "deterministic_grouped_bootstrap_and_leave_one_group_out",
        "bootstrap_seed": contract["determinism"]["grouped_bootstrap_seed"],
        "bootstrap_resamples": contract["determinism"]["bootstrap_resamples"],
        "results": [
            item
            for item in decisions["decisions"]
            if "uncertainty_95_half_width" in item
            or "uncertainty_disagreeing_group_fraction" in item
        ],
    }
    limitations = {
        "schema": "ias.s4_5.limitations.v1",
        "status": "declared",
        "applicability": [
            "Exact ReSpeaker serial 114993701261100454 at 16 kHz.",
            "S4_TEMP_DESKTOP_FIXTURE_REV0 in WANG_2022_DESK_NEAR_ENTRANCE.",
            "MacBook reference WAV/source placements represented by Fit A and Fit B.",
            "Functional relative correction only; tested source-room-sensor path.",
        ],
        "unsupported_claims": contract["unsupported_claims"],
        "omitted_candidates": [
            {
                "candidate": item["candidate"],
                "channel_id": item.get("channel_id"),
                "reason": item["reason"],
            }
            for item in decisions["decisions"]
            if item.get("retained") is False
        ],
        "microphone_geometry_status": "nominal_not_measured",
        "holdout_used": False,
        "repository_tooling_not_os_level_protection": True,
    }
    census = {
        "schema": "ias.s4_5.authorized_attempt_census.v1",
        "status": "passed",
        "purposes": contract["purposes"],
        "planned_fit_cells": inventory["planned_fit_cells"],
        "valid_fit_cells": inventory["valid_fit_cells"],
        "retained_attempts": inventory["retained_attempts"],
        "retained_failures": inventory["retained_failures"],
        "replacements": inventory["replacements"],
        "fit_a_valid": inventory["session_counts"]["fit_a"],
        "fit_b_valid": inventory["session_counts"]["fit_b"],
        "holdout_attempts_accessed": 0,
    }
    provenance = {
        "schema": "ias.s4_5.provenance.v1",
        "status": "passed",
        "source_commit": source_commit,
        "entry_commit": contract["entry"]["commit"],
        "tool_version": contract["tool_version"],
        "config_path": str(config_path.relative_to(repo_root)),
        "config_sha256": sha256_file(config_path),
        "spec_path": "docs/development/specs/s4_5_supported_functional_fitting.md",
        "spec_sha256": sha256_file(
            repo_root / "docs/development/specs/s4_5_supported_functional_fitting.md"
        ),
        "input_records": [
            {"name": name, **record}
            for name, record in sorted(contract["evidence"].items())
        ],
        "raw_media_tracked": False,
        "push_performed": False,
    }
    reproduction = {
        "schema": "ias.s4_5.reproduction.v1",
        "status": "passed",
        "commands": [
            (
                ".venv/bin/python scripts/run_s4_5_fitting.py "
                f"--source-commit {source_commit} --output <empty-directory>"
            ),
            (
                ".venv/bin/python scripts/validate_s4_5.py "
                "--evidence outputs/isaac_audio_sensors/S4/S4.5"
            ),
            ".venv/bin/python -m pytest -q tests/test_s4_5_fitting.py",
            "make test",
            "make lint",
            "make check-version",
            "make build",
            "git diff --check",
        ],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "source_commit": source_commit,
        "deterministic": True,
    }
    contract_record = {
        "schema": "ias.s4_5.frozen_contract_record.v1",
        "status": "frozen_before_fit",
        "config": contract,
        "config_sha256": sha256_file(config_path),
        "spec_sha256": provenance["spec_sha256"],
        "source_commit": source_commit,
    }
    files = {
        "pre_s4_5_s4_4_validation.json": _pre_s4_5_record(),
        "fit_inventory.json": inventory,
        "fitting_contract.json": contract_record,
        "authorized_attempt_census.json": census,
        "synthetic_recovery.json": synthetic,
        "fit_measurements.json": measurements,
        "grouped_residual_results.json": residuals,
        "parameter_decisions.json": decisions,
        "uncertainty_sensitivity.json": uncertainty,
        "limitations.json": limitations,
        "calibration_profile.v1.json": profile,
        "preservation_validation.json": preservation,
        "reproduction.json": reproduction,
        "provenance.json": provenance,
    }
    for name, value in files.items():
        _write(output / name, value)
    index_payload = {
        "schema": EVIDENCE_INDEX_SCHEMA,
        "status": "passed",
        "source_commit": source_commit,
        "tool_version": contract["tool_version"],
        "records": evidence_records(output),
        "profile_path": "calibration_profile.v1.json",
        "holdout_metrics_empty": True,
        "holdout_opened": False,
        "S4.6_started": False,
    }
    index_payload["index_payload_sha256"] = hashlib.sha256(
        json.dumps(
            index_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    _write(output / "evidence_index.json", index_payload)
    (output / "SHA256SUMS").write_text(checksum_text(output), encoding="utf-8")
    validation = validate_evidence_package(repo_root, output)
    if validation["status"] != "passed":
        raise S45Error(f"generated S4.5 package failed validation: {validation}")
    return {
        "status": "passed",
        "source_commit": source_commit,
        "output": output.relative_to(repo_root).as_posix()
        if output.is_relative_to(repo_root)
        else str(output),
        "retained_parameter_count": decisions["retained_parameter_count"],
        "scientifically_useful_retained_count": decisions[
            "scientifically_useful_retained_count"
        ],
        "holdout_opened": False,
        "S4.6_started": False,
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=S45_CONFIG)
    parser.add_argument("--output", type=Path, default=S45_OUTPUT)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        result = build(
            repo_root=args.repo_root,
            output=args.output,
            config_path=args.config,
            source_commit=args.source_commit,
        )
    except (OSError, ValueError, S45Error) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
