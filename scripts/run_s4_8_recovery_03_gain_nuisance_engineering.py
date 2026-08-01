#!/usr/bin/env python3
"""Acquire and replay the isolated S4.8 gain × nuisance experiment."""

from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from isaac_audio_sensors.acquisition import s4_8  # noqa: E402
from isaac_audio_sensors.acquisition import (  # noqa: E402
    s4_8_recovery_02_evaluator as historical_evaluator,
)
from isaac_audio_sensors.acquisition import (  # noqa: E402
    s4_8_recovery_03 as recovery03,
)
from isaac_audio_sensors.acquisition.s4_3 import (  # noqa: E402
    load_pilot_configuration,
)
from isaac_audio_sensors.acquisition.s4_8_engineering_acquisition import (  # noqa: E402
    S48EngineeringAcquisitionError,
    build_engineering_precollection_manifest,
    run_supported_engineering_acquisition,
)
from isaac_audio_sensors.acquisition.s4_8_physical_backend import (  # noqa: E402
    RemotePhysicalEngineeringBackend,
    S48PhysicalBackendError,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import (  # noqa: E402
    canonical_sha256,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate_v2 import (  # noqa: E402
    S48PresealingGateError,
    load_presealing_config_v2,
)

try:
    from scripts import run_s4_8_repeatability_diagnostic as repeatability
except ModuleNotFoundError:
    import run_s4_8_repeatability_diagnostic as repeatability

CONFIG_PATH = Path(
    "configs/s4_8_recovery_amendment_03_gain_nuisance_engineering.v1.json"
)
ENGINEERING_CONFIG_PATH = Path("configs/s4_8_engineering_campaign.v1.json")
PILOT_CONFIG_PATH = Path("configs/s4_3_pilot.v1.json")
CONTROLLER_SOURCE_PATH = Path(
    "scripts/run_s4_8_recovery_03_gain_nuisance_engineering.py"
)
REFERENCE_PATH = Path(
    "outputs/isaac_audio_sensors/S4/S4.2/reference/s4_2_reference_v1.0.0.wav"
)

CONTRACT_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_engineering_contract.v1"
CAMPAIGN_MANIFEST_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_campaign_manifest.v1"
AUTHORIZATION_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_attempt_authorization.v1"
LEDGER_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_attempt.v1"
DERIVED_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_derived_input.v1"
REPORT_SCHEMA = "ias.s4_8.recovery_03.gain_nuisance_replay_report.v1"
TOOL_VERSION = "ias_s4_8_recovery_03_gain_nuisance_engineering/1.0.0"

AUTHORITY_NONE = {
    "collects_data": False,
    "creates_grant": False,
    "consumes_grant": False,
    "opens_holdout": False,
    "executes_official_evaluation": False,
    "publishes_official_evidence": False,
    "authorizes_new_holdout": False,
    "starts_later_phase": False,
}
CLASSIFICATION = {
    "engineering_only": True,
    "official_evidence": False,
    "gain_nuisance_counterfactual_only": True,
}
SOURCE_PATHS = (
    CONFIG_PATH,
    CONTROLLER_SOURCE_PATH,
    Path("scripts/run_s4_8_repeatability_diagnostic.py"),
    Path("scripts/s4_8_mac_playback.swift"),
    Path("src/isaac_audio_sensors/acquisition/s4_8.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_engineering_acquisition.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_physical_backend.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_presealing_gate.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_presealing_gate_v2.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02_evaluator.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_03.py"),
    Path("configs/s4_3_pilot.v1.json"),
    Path("configs/s4_8_engineering_campaign.v1.json"),
    Path("configs/s4_8_presealing_gate.v2.json"),
    Path("configs/s4_8_recovery_amendment_03.v1.json"),
    Path("configs/s4_8_recovery_amendment_03_future_holdout.v2.json"),
    Path("configs/s4_8_reference_tdoa_boundary_policy.v1.json"),
    Path("outputs/isaac_audio_sensors/S4/S4.5_active_profile.v1.json"),
    Path(
        "outputs/isaac_audio_sensors/S4/S4.5_corrective_01/calibration_profile.v2.json"
    ),
)
PRESERVED_PATHS = (
    Path(".local/s4_8/s4_8_recovery_amendment_03_rc1_engineering_replay/SHA256SUMS"),
    Path(
        ".local/s4_8/s4_8_recovery_amendment_03_rc1_engineering_replay/"
        "derived_evaluation_input.v1.json"
    ),
    Path("configs/s4_8_recovery_amendment_03.v1.json"),
    Path("configs/s4_8_recovery_amendment_03_future_holdout.v2.json"),
    Path("configs/s4_8_reference_tdoa_boundary_policy.v1.json"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_02_evaluator.py"),
    Path("src/isaac_audio_sensors/acquisition/s4_8_recovery_03.py"),
    Path(
        "outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_02_37_take/SHA256SUMS"
    ),
)


class GainNuisanceEngineeringError(RuntimeError):
    """Fail-closed gain × nuisance engineering workflow error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GainNuisanceEngineeringError(f"{path} is not a JSON object")
    return value


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(value), indent=2, sort_keys=True))
            stream.write("\n")
    except FileExistsError as exc:
        raise GainNuisanceEngineeringError(f"refusing to overwrite {path}") from exc


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                dict(value),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        stream.write("\n")


def _safe_repo_path(repo_root: Path, value: str) -> Path:
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "." in candidate.parts
    ):
        raise GainNuisanceEngineeringError(f"unsafe repository path: {value!r}")
    return repo_root.resolve() / Path(*candidate.parts)


def _require_hash(repo_root: Path, binding: Mapping[str, Any]) -> Path:
    path = _safe_repo_path(repo_root, str(binding.get("path", "")))
    if (
        not path.is_file()
        or not isinstance(binding.get("sha256"), str)
        or _sha256(path) != binding["sha256"]
    ):
        raise GainNuisanceEngineeringError(
            f"hash binding mismatch: {binding.get('path')}"
        )
    return path


def _expected_perturbations(
    repo_root: Path,
    contract: Mapping[str, Any],
) -> dict[float, dict[str, Any]]:
    binding = contract["bindings"]["future_pairing_contract"]
    future = _load_json(_require_hash(repo_root, binding))
    pairs = future.get("pairing_control", {}).get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 4:
        raise GainNuisanceEngineeringError("future B/C pairing contract is incomplete")
    return {
        float(pair["scientific_conditions"]["target_bearing_deg_f_project"]): {
            "realized_condition_id": pair["scientific_conditions"][
                "nuisance_condition_id"
            ],
            "noise": pair["scientific_conditions"]["noise"],
            "occlusion": pair["scientific_conditions"]["occlusion"],
            "b_id": pair["b"]["planned_take_id"],
            "c_id": pair["c"]["planned_take_id"],
        }
        for pair in pairs
    }


def _take_definitions(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    campaign = contract["campaign"]
    definitions: list[dict[str, Any]] = []
    for source in campaign["takes"]:
        payload = {
            **copy.deepcopy(source),
            "take_number": source["sequence_index"],
            "duration_s": campaign["duration_s"],
            "source_frame": campaign["source_frame"],
            "source_radius_m": campaign["source_radius_m"],
            "reference_wav_sha256": contract["bindings"]["reference_signal"]["sha256"],
            "independent_recording": True,
            "rig_fixed": True,
            "mac_heading_fixed": True,
            "complete_removal_and_fresh_reposition_required": True,
            "explicit_authorization_required": True,
        }
        definitions.append(
            {
                **payload,
                "engineering_take_definition_sha256": canonical_sha256(payload),
            }
        )
    return definitions


def _validate_contract_structure(
    repo_root: Path,
    contract: Mapping[str, Any],
) -> None:
    if (
        contract.get("schema") != CONTRACT_SCHEMA
        or contract.get("status") != "engineering_only_not_acquired"
        or contract.get("classification") != CLASSIFICATION
        or contract.get("authority") != AUTHORITY_NONE
    ):
        raise GainNuisanceEngineeringError(
            "engineering contract identity or authority mismatch"
        )
    bindings = contract.get("bindings")
    if not isinstance(bindings, Mapping):
        raise GainNuisanceEngineeringError("engineering bindings are missing")
    for name, binding in bindings.items():
        if name != "base_engineering_replay":
            if not isinstance(binding, Mapping):
                raise GainNuisanceEngineeringError(f"invalid binding object: {name}")
            _require_hash(repo_root, binding)

    campaign = contract.get("campaign")
    replay = contract.get("replay")
    if (
        not isinstance(campaign, Mapping)
        or not isinstance(replay, Mapping)
        or campaign.get("take_count") != 8
        or campaign.get("duration_s") != 20
        or campaign.get("source_frame") != "F_project"
        or campaign.get("source_radius_m") != 0.8
        or campaign.get("explicit_authorization_required_before_every_attempt")
        is not True
        or campaign.get("automatic_continuation") is not False
        or campaign.get("automatic_retry") is not False
        or replay.get("common_old_sequence_indices") != [*range(1, 27), 35, 36, 37]
        or replay.get("old_raw_observation_read_count") != 0
        or replay.get("evaluator_invocation_count_per_variant") != 1
        or replay.get("official_evidence") is not False
        or replay.get("overwrite_permitted") is not False
    ):
        raise GainNuisanceEngineeringError("campaign or replay contract is invalid")
    takes = campaign.get("takes")
    if not isinstance(takes, list) or len(takes) != 8:
        raise GainNuisanceEngineeringError("eight take definitions are required")
    perturbations = _expected_perturbations(repo_root, contract)
    expected_bearings = [0.0, 90.0, 180.0, 270.0] * 2
    clean = {
        "realized_condition_id": "clean",
        "noise": {
            "enabled": False,
            "phrase": None,
            "repetitions": 0,
            "instruction": None,
        },
        "occlusion": {"enabled": False, "instruction": None},
    }
    seen_ids: set[str] = set()
    replacement_ids: set[str] = set()
    for index, take in enumerate(takes, start=1):
        bearing = expected_bearings[index - 1]
        perturbation = perturbations[bearing]
        expected = (
            {
                **clean,
                "gain": 0.75,
                "variant": "clean",
                "replacement": perturbation["b_id"],
            }
            if index <= 4
            else {
                "realized_condition_id": perturbation["realized_condition_id"],
                "noise": perturbation["noise"],
                "occlusion": perturbation["occlusion"],
                "gain": 0.35,
                "variant": "perturbed",
                "replacement": perturbation["c_id"],
            }
        )
        if (
            not isinstance(take, Mapping)
            or take.get("sequence_index") != index
            or take.get("target_bearing_deg_f_project") != bearing
            or take.get("playback_gain") != expected["gain"]
            or take.get("realized_condition_id") != expected["realized_condition_id"]
            or take.get("noise") != expected["noise"]
            or take.get("occlusion") != expected["occlusion"]
            or take.get("replay_variant") != expected["variant"]
            or take.get("replacement_planned_take_id") != expected["replacement"]
            or not isinstance(take.get("engineering_take_id"), str)
        ):
            raise GainNuisanceEngineeringError(
                f"take {index} does not match the frozen experiment"
            )
        seen_ids.add(str(take["engineering_take_id"]))
        replacement_ids.add(str(take["replacement_planned_take_id"]))
    if len(seen_ids) != 8 or len(replacement_ids) != 8:
        raise GainNuisanceEngineeringError(
            "engineering or replacement take identities are duplicated"
        )

    variants = replay.get("variants")
    if not isinstance(variants, Mapping) or set(variants) != {
        "clean",
        "perturbed",
    }:
        raise GainNuisanceEngineeringError("replay variants are invalid")
    by_variant = {
        name: {
            take["replacement_planned_take_id"]
            for take in takes
            if take["replay_variant"] == name
        }
        for name in variants
    }
    for name, value in variants.items():
        retained = value.get("retained_old_planned_take_ids")
        if (
            value.get("new_take_count") != 4
            or not isinstance(retained, list)
            or len(retained) != 4
            or len(set(retained)) != 4
            or set(retained) & by_variant[name]
        ):
            raise GainNuisanceEngineeringError(f"{name} replay mapping is invalid")
    design = _load_json(_require_hash(repo_root, contract["bindings"]["base_design"]))
    design_ids = [take["planned_take_id"] for take in design.get("take_order", [])]
    common = {design_ids[index - 1] for index in replay["common_old_sequence_indices"]}
    if (
        len(design_ids) != 37
        or len(common) != 29
        or set(variants["clean"]["retained_old_planned_take_ids"])
        != by_variant["perturbed"]
        or set(variants["perturbed"]["retained_old_planned_take_ids"])
        != by_variant["clean"]
        or common & replacement_ids
        or len(common | replacement_ids) != 37
    ):
        raise GainNuisanceEngineeringError("29 + 4 + 4 replay partition is invalid")


def _validate_base_replay(
    repo_root: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    base = contract["bindings"]["base_engineering_replay"]
    manifest = _safe_repo_path(repo_root, str(base["manifest_path"]))
    derived_path = _safe_repo_path(repo_root, str(base["derived_path"]))
    if (
        not manifest.is_file()
        or _sha256(manifest) != base["manifest_sha256"]
        or not derived_path.is_file()
        or _sha256(derived_path) != base["derived_sha256"]
    ):
        raise GainNuisanceEngineeringError(
            "authenticated RC1 engineering replay is unavailable"
        )
    replay_root = _safe_repo_path(repo_root, str(base["root"]))
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        path = replay_root / name
        if (
            not separator
            or len(digest) != 64
            or not path.is_file()
            or _sha256(path) != digest
        ):
            raise GainNuisanceEngineeringError("RC1 replay package manifest mismatch")
    derived = _load_json(derived_path)
    payload = derived.get("payload")
    design = _load_json(_require_hash(repo_root, contract["bindings"]["base_design"]))
    expected_ids = [take["planned_take_id"] for take in design.get("take_order", [])]
    actual_ids = (
        [
            take.get("identity", {}).get("planned_take_id")
            for take in payload.get("takes", [])
        ]
        if isinstance(payload, Mapping)
        else []
    )
    if (
        derived.get("mode") != recovery03.ENGINEERING_REPLAY_PROFILE
        or derived.get("status") != "non_official_engineering_replay"
        or derived.get("source_commit") != base["source_commit"]
        or derived.get("raw_take_read_count") != 37
        or not isinstance(payload, Mapping)
        or set(payload) != {"schema", "contract", "takes", "sim_vs_real"}
        or len(expected_ids) != 37
        or actual_ids != expected_ids
    ):
        raise GainNuisanceEngineeringError("RC1 derived payload identity mismatch")
    return derived


def load_contract(
    repo_root: Path = ROOT,
    *,
    require_base_replay: bool = True,
) -> dict[str, Any]:
    """Load and validate only the isolated engineering contract."""

    root = repo_root.resolve()
    contract = _load_json(root / CONFIG_PATH)
    _validate_contract_structure(root, contract)
    if require_base_replay:
        _validate_base_replay(root, contract)
    return contract


def validate_contract(repo_root: Path = ROOT) -> dict[str, Any]:
    """Authenticate tracked bindings and the derived RC1 base without replay."""

    root = repo_root.resolve()
    contract = load_contract(root, require_base_replay=True)
    return {
        "schema": "ias.s4_8.recovery_03.gain_nuisance_validation.v1",
        "status": "passed",
        "experiment_id": contract["experiment_id"],
        "take_count": 8,
        "replay_variants": ["clean", "perturbed"],
        "base_replay_source_commit": contract["bindings"]["base_engineering_replay"][
            "source_commit"
        ],
        "old_raw_observation_read_count": 0,
        "scientific_evaluator_invocation_count": 0,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _campaign_root(repo_root: Path, contract: Mapping[str, Any]) -> Path:
    return _safe_repo_path(repo_root, str(contract["campaign"]["root"]))


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_bound_source_state(
    repo_root: Path,
    manifest: Mapping[str, Any] | None = None,
) -> str:
    paths = [path.as_posix() for path in SOURCE_PATHS]
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *paths],
        cwd=repo_root,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *paths],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    head = _git_head(repo_root)
    if changed.returncode != 0 or untracked.stdout.strip():
        raise GainNuisanceEngineeringError(
            "engineering controller or dependencies are not committed"
        )
    if manifest is not None:
        if manifest.get("code_head") != head:
            raise GainNuisanceEngineeringError(
                "repository HEAD differs from the campaign freeze"
            )
        for path, digest in manifest["source_files_sha256"].items():
            if _sha256(_safe_repo_path(repo_root, path)) != digest:
                raise GainNuisanceEngineeringError(
                    f"campaign source changed after freeze: {path}"
                )
    return head


def _validate_campaign_manifest(
    repo_root: Path,
    contract: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    campaign_root = _campaign_root(repo_root, contract)
    if (
        manifest.get("schema") != CAMPAIGN_MANIFEST_SCHEMA
        or manifest.get("experiment_id") != contract["experiment_id"]
        or manifest.get("campaign_root")
        != campaign_root.relative_to(repo_root).as_posix()
        or manifest.get("contract_sha256") != _sha256(repo_root / CONFIG_PATH)
        or manifest.get("takes") != _take_definitions(contract)
        or manifest.get("classification") != CLASSIFICATION
        or manifest.get("authority") != AUTHORITY_NONE
        or manifest.get("manifest_sha256") != canonical_sha256(payload)
        or set(manifest.get("source_files_sha256", {}))
        != {path.as_posix() for path in SOURCE_PATHS}
    ):
        raise GainNuisanceEngineeringError(
            "campaign manifest identity or scope mismatch"
        )
    freeze = campaign_root / "freeze"
    if (
        not (freeze / "source.tar").is_file()
        or _sha256(freeze / "source.tar") != manifest["source_archive_sha256"]
        or not (freeze / "preflight_report.json").is_file()
        or _sha256(freeze / "preflight_report.json")
        != manifest["preflight_report_sha256"]
    ):
        raise GainNuisanceEngineeringError("campaign freeze artifacts are incomplete")


def _load_campaign(
    repo_root: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    root = _campaign_root(repo_root, contract)
    manifest = _load_json(root / "freeze/campaign_manifest.json")
    _validate_campaign_manifest(repo_root, contract, manifest)
    return manifest


def _ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise GainNuisanceEngineeringError(
                "attempt ledger contains a non-object record"
            )
        records.append(value)
    return records


def _validate_artifact_hashes(
    repo_root: Path,
    record: Mapping[str, Any],
) -> None:
    attempt_root = _safe_repo_path(repo_root, str(record["attempt_root"]))
    artifacts = record.get("artifact_sha256")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise GainNuisanceEngineeringError("attempt ledger artifact hashes are missing")
    for name, digest in artifacts.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(digest, str)
            or not (attempt_root / name).is_file()
            or _sha256(attempt_root / name) != digest
        ):
            raise GainNuisanceEngineeringError(
                f"attempt artifact hash mismatch: {name}"
            )


def _validate_ledger(
    repo_root: Path,
    contract: Mapping[str, Any],
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    authenticate_artifacts: bool = True,
) -> tuple[dict[str, Any] | None, int]:
    takes = manifest["takes"]
    take_index = 0
    attempt_number = 1
    previous = str(manifest["manifest_sha256"])
    for sequence, record in enumerate(records):
        if take_index >= len(takes):
            raise GainNuisanceEngineeringError(
                "attempt ledger continues after campaign completion"
            )
        take = takes[take_index]
        payload = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        expected_root = (
            _campaign_root(repo_root, contract)
            / "takes"
            / (f"{take['engineering_take_id']}__attempt_{attempt_number:02d}")
        )
        if (
            record.get("schema") != LEDGER_SCHEMA
            or record.get("sequence") != sequence
            or record.get("campaign_manifest_sha256") != manifest["manifest_sha256"]
            or record.get("previous_record_sha256") != previous
            or record.get("engineering_take_id") != take["engineering_take_id"]
            or record.get("engineering_take_definition_sha256")
            != take["engineering_take_definition_sha256"]
            or record.get("take_number") != take["take_number"]
            or record.get("attempt_number") != attempt_number
            or record.get("decision") not in {"PASS", "RETRY_REQUIRED"}
            or record.get("attempt_root")
            != expected_root.relative_to(repo_root).as_posix()
            or record.get("record_sha256") != canonical_sha256(payload)
        ):
            raise GainNuisanceEngineeringError(
                "attempt ledger identity or chain mismatch"
            )
        if authenticate_artifacts:
            _validate_artifact_hashes(repo_root, record)
        if record["decision"] == "PASS":
            if "candidate_seal.json" not in record["artifact_sha256"]:
                raise GainNuisanceEngineeringError(
                    "passing attempt lacks a candidate seal"
                )
            take_index += 1
            attempt_number = 1
        else:
            if "candidate_seal.json" in record["artifact_sha256"]:
                raise GainNuisanceEngineeringError(
                    "retry attempt unexpectedly has a candidate seal"
                )
            attempt_number += 1
        previous = str(record["record_sha256"])
    next_take = None if take_index == len(takes) else dict(takes[take_index])
    return next_take, attempt_number


def _authorization_path(
    campaign_root: Path,
    *,
    take_number: int,
    attempt_number: int,
) -> Path:
    return (
        campaign_root
        / "authorizations"
        / f"take_{take_number:02d}_attempt_{attempt_number:02d}.json"
    )


def _physical_setup(take: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_bearing_deg_f_project": take["target_bearing_deg_f_project"],
        "target_radius_m": take["source_radius_m"],
        "source_xy_m_f_project": take["source_xy_m_f_project"],
        "playback_gain": take["playback_gain"],
        "realized_condition_id": take["realized_condition_id"],
        "noise": copy.deepcopy(take["noise"]),
        "occlusion": copy.deepcopy(take["occlusion"]),
        "duration_s": take["duration_s"],
    }


def _validate_authorization(
    authorization: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    attempt_number: int,
    previous_record_sha256: str,
) -> None:
    payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_sha256"
    }
    if (
        authorization.get("schema") != AUTHORIZATION_SCHEMA
        or authorization.get("campaign_manifest_sha256") != manifest["manifest_sha256"]
        or authorization.get("base_code_head") != manifest["code_head"]
        or authorization.get("engineering_take_id") != take["engineering_take_id"]
        or authorization.get("engineering_take_definition_sha256")
        != take["engineering_take_definition_sha256"]
        or authorization.get("take_number") != take["take_number"]
        or authorization.get("attempt_number") != attempt_number
        or authorization.get("previous_record_sha256") != previous_record_sha256
        or authorization.get("physical_setup") != _physical_setup(take)
        or authorization.get("automatic_continuation") is not False
        or authorization.get("automatic_retry") is not False
        or authorization.get("retry_authorized") is not (attempt_number > 1)
        or authorization.get("classification") != CLASSIFICATION
        or authorization.get("authority") != AUTHORITY_NONE
        or authorization.get("authorization_sha256") != canonical_sha256(payload)
    ):
        raise GainNuisanceEngineeringError("attempt authorization identity mismatch")


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    contract = load_contract(root)
    campaign_root = _campaign_root(root, contract)
    if campaign_root.exists():
        raise GainNuisanceEngineeringError(
            f"refusing to reuse campaign root: {campaign_root}"
        )
    head = _require_bound_source_state(root)
    preflight = _load_json(args.preflight_report.resolve())
    repeatability._validate_preflight(preflight)
    config = _load_json(root / ENGINEERING_CONFIG_PATH)
    gate = load_presealing_config_v2(root)
    pilot = load_pilot_configuration(root / PILOT_CONFIG_PATH, repo_root=root)
    freeze = campaign_root / "freeze"
    freeze.mkdir(parents=True)
    preflight_copy = freeze / "preflight_report.json"
    shutil.copyfile(args.preflight_report.resolve(), preflight_copy)
    archive = freeze / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
        cwd=root,
        check=True,
    )
    payload = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "experiment_id": contract["experiment_id"],
        "campaign_root": campaign_root.relative_to(root).as_posix(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_head": head,
        "contract_sha256": _sha256(root / CONFIG_PATH),
        "source_archive_sha256": _sha256(archive),
        "source_files_sha256": {
            path.as_posix(): _sha256(root / path) for path in SOURCE_PATHS
        },
        "preflight_report_sha256": _sha256(preflight_copy),
        "reference_wav_sha256": _sha256(root / REFERENCE_PATH),
        "continuous_asset_sha256": preflight["continuous_asset"]["asset_sha256"],
        "gate_configuration_sha256": canonical_sha256(gate),
        "detector_configuration_sha256": canonical_sha256(gate["detector"]),
        "analysis_configuration_sha256": canonical_sha256(pilot),
        "device_profile_id": config["respeaker"]["profile_id"],
        "channel_map": config["channel_map"],
        "takes": _take_definitions(contract),
        "authorization_policy": {
            "explicit_authorization_required_before_every_attempt": True,
            "automatic_continuation": False,
            "automatic_retry": False,
        },
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    manifest = {**payload, "manifest_sha256": canonical_sha256(payload)}
    _write_new_json(freeze / "campaign_manifest.json", manifest)
    return {
        "status": "prepared",
        "campaign_root": campaign_root.relative_to(root).as_posix(),
        "manifest_sha256": manifest["manifest_sha256"],
        "next_take_number": 1,
        "next_attempt_number": 1,
        "physical_setup": _physical_setup(manifest["takes"][0]),
        "acquisition_started": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def authorize_take(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    contract = load_contract(root)
    campaign_root = _campaign_root(root, contract)
    manifest = _load_campaign(root, contract)
    _require_bound_source_state(root, manifest)
    records = _ledger(campaign_root / "attempt_ledger.jsonl")
    next_take, attempt_number = _validate_ledger(
        root,
        contract,
        manifest,
        records,
    )
    if next_take is None:
        raise GainNuisanceEngineeringError("campaign is already complete")
    if args.take_number != next_take["take_number"]:
        raise GainNuisanceEngineeringError(
            "authorization is permitted only for the next frozen take"
        )
    path = _authorization_path(
        campaign_root,
        take_number=args.take_number,
        attempt_number=attempt_number,
    )
    if path.exists():
        raise GainNuisanceEngineeringError(f"refusing to overwrite {path}")
    previous = (
        manifest["manifest_sha256"] if not records else records[-1]["record_sha256"]
    )
    payload = {
        "schema": AUTHORIZATION_SCHEMA,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "base_code_head": manifest["code_head"],
        "controller_source_sha256": _sha256(root / CONTROLLER_SOURCE_PATH),
        "engineering_take_id": next_take["engineering_take_id"],
        "engineering_take_definition_sha256": next_take[
            "engineering_take_definition_sha256"
        ],
        "take_number": next_take["take_number"],
        "attempt_number": attempt_number,
        "previous_record_sha256": previous,
        "physical_setup": _physical_setup(next_take),
        "automatic_continuation": False,
        "automatic_retry": False,
        "retry_authorized": attempt_number > 1,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }
    authorization = {
        **payload,
        "authorization_sha256": canonical_sha256(payload),
    }
    _write_new_json(path, authorization)
    return {
        "status": "authorized",
        "take_number": next_take["take_number"],
        "attempt_number": attempt_number,
        "engineering_take_id": next_take["engineering_take_id"],
        "authorization": path.relative_to(root).as_posix(),
        "authorization_sha256": authorization["authorization_sha256"],
        "physical_setup": _physical_setup(next_take),
        "automatic_continuation": False,
        "automatic_retry": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _build_backend(
    *,
    repo_root: Path,
    config: Mapping[str, Any],
    manifest: Mapping[str, Any],
    take: Mapping[str, Any],
    attempt_number: int,
) -> RemotePhysicalEngineeringBackend:
    return RemotePhysicalEngineeringBackend(
        pi_ssh_prefix=config["respeaker"]["ssh_prefix"],
        pi_scp_prefix=config["respeaker"]["scp_prefix"],
        pi_scp_target=config["respeaker"]["scp_target"],
        pi_helper_path=config["respeaker"]["helper_path"],
        pi_remote_attempt=(
            "S4.8/recovery_03_gain_nuisance_engineering/"
            f"{manifest['manifest_sha256'][:16]}/"
            f"{take['engineering_take_id']}/attempt_{attempt_number:02d}"
        ),
        pi_device=config["respeaker"]["device"],
        capture_duration_s=float(take["duration_s"]),
        mac_ssh_prefix=config["playback"]["ssh_prefix"],
        mac_playback_helper_path=config["playback"]["playback_helper_mac_path"],
        mac_continuous_asset_path=config["reference"]["continuous_asset_mac_path"],
        mac_continuous_asset_sha256=str(manifest["continuous_asset_sha256"]),
        playback_gain=float(take["playback_gain"]),
        zed_helper_path=repo_root / "scripts/run_s4_2_zed_capture.py",
        zed_replay_path=repo_root / "scripts/validate_s4_2_zed_svo.py",
        expected_zed_serial=config["zed"]["serial"],
        expected_zed_sdk=config["zed"]["sdk_version_reference"],
        expected_zed_camera_firmware=config["zed"]["camera_firmware_reference"],
        expected_zed_sensor_firmware=config["zed"]["sensor_firmware_reference"],
    )


def run_take(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    contract = load_contract(root)
    campaign_root = _campaign_root(root, contract)
    manifest = _load_campaign(root, contract)
    _require_bound_source_state(root, manifest)
    config = _load_json(root / ENGINEERING_CONFIG_PATH)
    ledger_path = campaign_root / "attempt_ledger.jsonl"
    records = _ledger(ledger_path)
    next_take, attempt_number = _validate_ledger(
        root,
        contract,
        manifest,
        records,
    )
    if next_take is None or args.take_number != next_take["take_number"]:
        raise GainNuisanceEngineeringError(
            "requested take is not the next frozen action"
        )
    authorization_path = _authorization_path(
        campaign_root,
        take_number=args.take_number,
        attempt_number=attempt_number,
    )
    if not authorization_path.is_file():
        raise GainNuisanceEngineeringError(
            "requested attempt lacks explicit authorization"
        )
    authorization = _load_json(authorization_path)
    previous = (
        manifest["manifest_sha256"] if not records else records[-1]["record_sha256"]
    )
    _validate_authorization(
        authorization,
        manifest=manifest,
        take=next_take,
        attempt_number=attempt_number,
        previous_record_sha256=previous,
    )
    if authorization["controller_source_sha256"] != _sha256(
        root / CONTROLLER_SOURCE_PATH
    ):
        raise GainNuisanceEngineeringError(
            "authorization does not bind the active controller"
        )

    attempt_name = f"{next_take['engineering_take_id']}__attempt_{attempt_number:02d}"
    attempt_root = campaign_root / "takes" / attempt_name
    if attempt_root.exists():
        raise GainNuisanceEngineeringError(
            f"attempt root already exists: {attempt_root}"
        )
    attempt_root.mkdir(parents=True)
    precollection = build_engineering_precollection_manifest(
        code_head=str(manifest["code_head"]),
        environment_identity=(
            f"campaign:{manifest['manifest_sha256']}:"
            f"preflight:{manifest['preflight_report_sha256']}:"
            f"take:{next_take['engineering_take_definition_sha256']}:"
            f"attempt:{attempt_number}"
        ),
        reference_wav_sha256=str(manifest["reference_wav_sha256"]),
        gate_configuration_sha256=str(manifest["gate_configuration_sha256"]),
        detector_configuration_sha256=str(manifest["detector_configuration_sha256"]),
        device_profile_id=str(manifest["device_profile_id"]),
        channel_map=manifest["channel_map"],
        protocol_id=(
            f"{contract['experiment_id']}:"
            f"{manifest['manifest_sha256']}:"
            f"{next_take['engineering_take_definition_sha256']}:"
            f"attempt:{attempt_number}"
        ),
        capture_controller_identity=str(config["controller"]["identity"]),
        capture_controller_version=str(config["controller"]["version"]),
    )
    _write_new_json(attempt_root / "take_definition.json", next_take)
    _write_new_json(
        attempt_root / "take_authorization.json",
        authorization,
    )
    _write_new_json(
        attempt_root / "take_precollection_manifest.json",
        precollection,
    )
    backend = _build_backend(
        repo_root=root,
        config=config,
        manifest=manifest,
        take=next_take,
        attempt_number=attempt_number,
    )
    try:
        result = run_supported_engineering_acquisition(
            backend=backend,
            repo_root=root,
            capture_path=attempt_root / "respeaker_audio.wav",
            reference_path=root / REFERENCE_PATH,
            manifest=precollection,
            expected_manifest_sha256=str(precollection["manifest_sha256"]),
            journal_path=attempt_root / "process_journal.jsonl",
            retry_report_path=attempt_root / "retry_report.json",
            candidate_seal_path=attempt_root / "candidate_seal.json",
            clearance_registry_path=attempt_root / "clearance_consumed.json",
            dry_run=False,
        )
    except BaseException as exc:
        try:
            cleanup = backend.abort()
        except Exception as cleanup_exc:
            cleanup = {
                "error_type": type(cleanup_exc).__name__,
                "error": str(cleanup_exc),
            }
        _write_new_json(
            attempt_root / "controller_failure.json",
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "cleanup": cleanup,
                "retained": True,
                "classification": dict(CLASSIFICATION),
                "authority": dict(AUTHORITY_NONE),
            },
        )
        raise
    _write_new_json(attempt_root / "gate_report.json", result["report"])
    if result["clearance"] is not None:
        _write_new_json(
            attempt_root / "candidate_clearance.json",
            result["clearance"],
        )
    _write_new_json(
        attempt_root / "controller_result.json",
        {
            **result,
            "take": next_take,
            "attempt_number": attempt_number,
            "classification": dict(CLASSIFICATION),
            "authority": dict(AUTHORITY_NONE),
        },
    )
    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(attempt_root.iterdir())
        if path.is_file()
    }
    payload = {
        "schema": LEDGER_SCHEMA,
        "sequence": len(records),
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "previous_record_sha256": previous,
        "engineering_take_id": next_take["engineering_take_id"],
        "engineering_take_definition_sha256": next_take[
            "engineering_take_definition_sha256"
        ],
        "take_number": next_take["take_number"],
        "attempt_number": attempt_number,
        "decision": result["decision"],
        "authorization_sha256": authorization["authorization_sha256"],
        "attempt_root": attempt_root.relative_to(root).as_posix(),
        "artifact_sha256": artifact_hashes,
    }
    record = {**payload, "record_sha256": canonical_sha256(payload)}
    _append_json_line(ledger_path, record)
    return {
        "status": "complete",
        "decision": result["decision"],
        "take_number": next_take["take_number"],
        "attempt_number": attempt_number,
        "engineering_take_id": next_take["engineering_take_id"],
        "attempt_root": attempt_root.relative_to(root).as_posix(),
        "record_sha256": record["record_sha256"],
        "automatic_continuation": False,
        "automatic_retry": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def _completed_attempts(
    repo_root: Path,
    contract: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records = _ledger(_campaign_root(repo_root, contract) / "attempt_ledger.jsonl")
    next_take, _attempt = _validate_ledger(
        repo_root,
        contract,
        manifest,
        records,
    )
    if next_take is not None:
        raise GainNuisanceEngineeringError(
            "all eight engineering takes must PASS before replay"
        )
    passed = {
        str(record["engineering_take_id"]): dict(record)
        for record in records
        if record["decision"] == "PASS"
    }
    if len(passed) != 8:
        raise GainNuisanceEngineeringError("engineering campaign PASS census mismatch")
    for record in passed.values():
        attempt_root = _safe_repo_path(repo_root, str(record["attempt_root"]))
        controller = _load_json(attempt_root / "controller_result.json")
        seal = _load_json(attempt_root / "candidate_seal.json")
        if (
            controller.get("decision") != "PASS"
            or controller.get("candidate_seal") != seal
            or record["artifact_sha256"].get("respeaker_audio.wav")
            != _sha256(attempt_root / "respeaker_audio.wav")
        ):
            raise GainNuisanceEngineeringError(
                "passing engineering attempt authentication failed"
            )
    return passed


def _analyze_new_takes(
    repo_root: Path,
    contract: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    campaign_root = _campaign_root(repo_root, contract)
    passed = _completed_attempts(repo_root, contract, manifest)
    registry = historical_evaluator.build_identity_registry(repo_root)
    profile = s4_8._profile_runtime(repo_root)
    derived_by_engineering_id: dict[str, dict[str, Any]] = {}
    provenance: list[dict[str, Any]] = []
    for take in manifest["takes"]:
        engineering_id = str(take["engineering_take_id"])
        record = passed[engineering_id]
        attempt_root = _safe_repo_path(repo_root, str(record["attempt_root"]))
        target_id = str(take["replacement_planned_take_id"])
        identity = registry.get(target_id)
        if identity is None:
            raise GainNuisanceEngineeringError(
                f"replacement evaluator slot is unknown: {target_id}"
            )
        analysis_take = {
            "take_id": attempt_root.name,
            "take_number": take["take_number"],
        }
        analysis = repeatability._current_pipeline_analysis(
            campaign_root=campaign_root,
            take=analysis_take,
            identity=identity,
            profile=profile,
        )
        capture_sha256 = _sha256(attempt_root / "respeaker_audio.wav")
        if (
            analysis.get("capture_sha256") != capture_sha256
            or record["artifact_sha256"].get("respeaker_audio.wav") != capture_sha256
            or analysis.get("derived", {}).get("identity")
            != identity.payload_identity()
        ):
            raise GainNuisanceEngineeringError(
                f"new take analysis authentication failed: {engineering_id}"
            )
        derived_by_engineering_id[engineering_id] = copy.deepcopy(analysis["derived"])
        provenance.append(
            {
                "engineering_take_id": engineering_id,
                "replacement_planned_take_id": target_id,
                "replay_variant": take["replay_variant"],
                "realized_condition_id": take["realized_condition_id"],
                "target_bearing_deg_f_project": take["target_bearing_deg_f_project"],
                "playback_gain": take["playback_gain"],
                "capture_sha256": capture_sha256,
                "attempt_number": record["attempt_number"],
                "candidate_seal_sha256": record["artifact_sha256"][
                    "candidate_seal.json"
                ],
            }
        )
    return derived_by_engineering_id, provenance


def compose_variant_payload(
    base_payload: Mapping[str, Any],
    derived_by_engineering_id: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
    variant: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replace exactly four frozen evaluator slots in one 37-take copy."""

    if variant not in {"clean", "perturbed"}:
        raise GainNuisanceEngineeringError(f"unknown replay variant: {variant}")
    payload = copy.deepcopy(dict(base_payload))
    takes = payload.get("takes")
    if not isinstance(takes, list) or len(takes) != 37:
        raise GainNuisanceEngineeringError("base replay must contain 37 takes")
    indices: dict[str, int] = {}
    for index, take in enumerate(takes):
        take_id = take.get("identity", {}).get("planned_take_id")
        if not isinstance(take_id, str) or take_id in indices:
            raise GainNuisanceEngineeringError(
                "base replay take identities are invalid"
            )
        indices[take_id] = index
    replacements = [
        take
        for take in contract["campaign"]["takes"]
        if take["replay_variant"] == variant
    ]
    if len(replacements) != 4:
        raise GainNuisanceEngineeringError(f"{variant} must replace exactly four takes")
    provenance = []
    for mapping in replacements:
        engineering_id = str(mapping["engineering_take_id"])
        target_id = str(mapping["replacement_planned_take_id"])
        derived = derived_by_engineering_id.get(engineering_id)
        if (
            target_id not in indices
            or not isinstance(derived, Mapping)
            or derived.get("identity", {}).get("planned_take_id") != target_id
        ):
            raise GainNuisanceEngineeringError(
                f"{variant} replacement is unavailable: {engineering_id}"
            )
        takes[indices[target_id]] = copy.deepcopy(dict(derived))
        provenance.append(
            {
                "engineering_take_id": engineering_id,
                "replacement_planned_take_id": target_id,
                "realized_condition_id": mapping["realized_condition_id"],
                "playback_gain": mapping["playback_gain"],
            }
        )
    actual_ids = [take.get("identity", {}).get("planned_take_id") for take in takes]
    if len(actual_ids) != 37 or len(set(actual_ids)) != 37:
        raise GainNuisanceEngineeringError(
            f"{variant} replay census or order is invalid"
        )
    retained = set(
        contract["replay"]["variants"][variant]["retained_old_planned_take_ids"]
    )
    replaced = {item["replacement_planned_take_id"] for item in provenance}
    if retained & replaced or len(retained) != 4:
        raise GainNuisanceEngineeringError(
            f"{variant} retained/replacement mapping overlaps"
        )
    return payload, provenance


def evaluate_variants(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    repo_root: Path,
    evaluator: Callable[..., Any],
) -> dict[str, dict[str, Any]]:
    """Invoke the supplied evaluator exactly once for each variant."""

    if set(payloads) != {"clean", "perturbed"}:
        raise GainNuisanceEngineeringError("both replay variants are required")
    results: dict[str, dict[str, Any]] = {}
    for variant in ("clean", "perturbed"):
        value = evaluator(payloads[variant], repo_root=repo_root)
        report = value.report() if hasattr(value, "report") else value
        if not isinstance(report, Mapping):
            raise GainNuisanceEngineeringError(
                f"{variant} evaluator returned no report"
            )
        evaluation = {**dict(report), "evaluation_invocation_count": 1}
        profile = recovery03.classify_package_profile(
            {
                "evaluation_state": "evaluation_completed",
                "evaluation": evaluation,
                "run_failure": None,
            }
        )
        if (
            profile != recovery03.FULL_EVALUATED_PROFILE
            or evaluation.get("evaluation_error") is not None
            or evaluation.get("holdout_observations_accessed_by_evaluator") != 0
        ):
            raise GainNuisanceEngineeringError(
                f"{variant} did not produce a complete evaluation"
            )
        results[variant] = evaluation
    return results


def _preserved_snapshot(repo_root: Path) -> dict[str, str]:
    return {path.as_posix(): _sha256(repo_root / path) for path in PRESERVED_PATHS}


def _replay_destination(
    repo_root: Path,
    contract: Mapping[str, Any],
) -> Path:
    destination = _safe_repo_path(repo_root, str(contract["replay"]["output_root"]))
    if destination.exists():
        raise GainNuisanceEngineeringError("engineering replay output already exists")
    return destination


def _write_variant_package(
    destination: Path,
    *,
    derived: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    report: Mapping[str, Any],
) -> str:
    destination.mkdir()
    files = {
        "derived_evaluation_input.v1.json": derived,
        "criteria_results.v1.json": evaluation,
        "engineering_replay_report.v1.json": report,
    }
    for name, value in files.items():
        _write_new_json(destination / name, value)
    manifest = "".join(
        f"{_sha256(destination / name)}  {name}\n" for name in sorted(files)
    )
    manifest_path = destination / "SHA256SUMS"
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(manifest)
    return _sha256(manifest_path)


def _atomic_publish_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a directory only when the target is absent."""

    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise GainNuisanceEngineeringError(
            "atomic no-replace publication is unavailable"
        ) from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(target),
        1,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise GainNuisanceEngineeringError("engineering replay output already exists")
    if error in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}:
        raise GainNuisanceEngineeringError(
            "atomic no-replace publication is unavailable"
        )
    raise OSError(error, os.strerror(error), os.fspath(target))


def engineering_replay(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    contract = load_contract(root)
    manifest = _load_campaign(root, contract)
    _require_bound_source_state(root, manifest)
    destination = _replay_destination(root, contract)
    before = _preserved_snapshot(root)
    base = _validate_base_replay(root, contract)
    new_takes, provenance = _analyze_new_takes(root, contract, manifest)
    payloads: dict[str, dict[str, Any]] = {}
    canonicalized: dict[str, int] = {}
    for variant in ("clean", "perturbed"):
        payload, replacements = compose_variant_payload(
            base["payload"],
            new_takes,
            contract,
            variant,
        )
        canonicalized[variant] = recovery03.apply_reference_policy(
            payload,
            repo_root=root,
            reference_origin=recovery03.REFERENCE_ORIGIN,
        )
        payloads[variant] = payload
        if len(replacements) != 4:
            raise GainNuisanceEngineeringError(
                f"{variant} replacement provenance is incomplete"
            )
    evaluations = evaluate_variants(
        payloads,
        repo_root=root,
        evaluator=historical_evaluator.evaluate_payload,
    )
    after = _preserved_snapshot(root)
    if after != before:
        raise GainNuisanceEngineeringError(
            "official, historical, or RC1 evidence changed during replay"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".gain_nuisance_replays_",
        dir=destination.parent,
    ) as temporary:
        staging = Path(temporary)
        manifests: dict[str, str] = {}
        for variant in ("clean", "perturbed"):
            variant_provenance = [
                item for item in provenance if item["replay_variant"] == variant
            ]
            derived = {
                "schema": DERIVED_SCHEMA,
                "mode": (
                    f"recovery_03_gain_nuisance_engineering_{variant}_non_official.v1"
                ),
                "status": "non_official_engineering_replay",
                "variant": variant,
                "tool_version": TOOL_VERSION,
                "source_commit": _git_head(root),
                "base_replay_source_commit": base["source_commit"],
                "old_raw_observation_read_count": 0,
                "new_engineering_raw_observation_read_count": 4,
                "common_old_take_count": 29,
                "retained_old_variant_take_count": 4,
                "new_take_count": 4,
                "payload": payloads[variant],
                "evaluation_state": "evaluation_completed",
                "evaluation": evaluations[variant],
                "evaluation_sha256": canonical_sha256(evaluations[variant]),
                "run_failure": None,
                "reference_policy_id": recovery03.POLICY_ID,
                "canonicalized_reference_count": canonicalized[variant],
                "replacement_provenance": variant_provenance,
                "classification": dict(CLASSIFICATION),
                "authority": dict(AUTHORITY_NONE),
            }
            report = {
                "schema": REPORT_SCHEMA,
                "status": evaluations[variant]["status"],
                "variant": variant,
                "official_evidence": False,
                "common_old_take_count": 29,
                "retained_old_variant_take_count": 4,
                "new_take_count": 4,
                "total_take_count": 37,
                "old_raw_observation_read_count": 0,
                "new_engineering_raw_observation_read_count": 4,
                "scientific_evaluator_invocation_count": 1,
                "official_evaluation_executed": False,
                "grant_created": False,
                "grant_consumed": False,
                "holdout_opened": False,
                "historical_preservation_passed": True,
                "historical_snapshot_sha256": canonical_sha256(after),
                "reference_policy_id": recovery03.POLICY_ID,
                "canonicalized_reference_count": canonicalized[variant],
                "replacement_provenance": variant_provenance,
                "classification": dict(CLASSIFICATION),
                "authority": dict(AUTHORITY_NONE),
            }
            manifests[variant] = _write_variant_package(
                staging / variant,
                derived=derived,
                evaluation=evaluations[variant],
                report=report,
            )
        _atomic_publish_directory_noreplace(staging, destination)
    return {
        "schema": "ias.s4_8.recovery_03.gain_nuisance_replay_closeout.v1",
        "status": "complete",
        "output": destination.relative_to(root).as_posix(),
        "variants": {
            variant: {
                "scientific_status": evaluations[variant]["status"],
                "manifest_sha256": manifests[variant],
                "take_count": 37,
                "evaluator_invocation_count": 1,
            }
            for variant in ("clean", "perturbed")
        },
        "total_scientific_evaluator_invocation_count": 2,
        "old_raw_observation_read_count": 0,
        "official_evaluation_executed": False,
        "classification": dict(CLASSIFICATION),
        "authority": dict(AUTHORITY_NONE),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare, acquire, or replay the isolated S4.8 gain × nuisance "
            "engineering experiment."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate_parser = subparsers.add_parser("validate-contract")
    validate_parser.set_defaults(
        function=lambda args: validate_contract(args.repo_root)
    )
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument(
        "--preflight-report",
        type=Path,
        required=True,
    )
    prepare_parser.set_defaults(function=prepare)
    authorize_parser = subparsers.add_parser("authorize-take")
    authorize_parser.add_argument(
        "--take-number",
        type=int,
        choices=range(1, 9),
        required=True,
    )
    authorize_parser.set_defaults(function=authorize_take)
    take_parser = subparsers.add_parser("run-take")
    take_parser.add_argument(
        "--take-number",
        type=int,
        choices=range(1, 9),
        required=True,
    )
    take_parser.set_defaults(function=run_take)
    replay_parser = subparsers.add_parser("engineering-replay")
    replay_parser.set_defaults(function=engineering_replay)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.function(args)
    except (
        GainNuisanceEngineeringError,
        OSError,
        S48EngineeringAcquisitionError,
        S48PhysicalBackendError,
        S48PresealingGateError,
        subprocess.CalledProcessError,
        ValueError,
    ) as exc:
        print(
            f"S4.8 gain × nuisance engineering workflow failed: {exc}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    terminal = result.get("decision", result.get("status"))
    successful = {"PASS", "complete", "passed", "prepared", "authorized"}
    return 0 if terminal in successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
