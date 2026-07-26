from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_7_holdout_acceptance.corrective_03.v4.json"
SCHEMA = (
    ROOT
    / "docs/schemas/s4_7_holdout_acceptance.corrective_03.v4.schema.json"
)
V1 = ROOT / "configs/s4_7_holdout_acceptance.v1.json"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_corrective_03_contract_validates_and_hash_binds_history() -> None:
    config = _load(CONFIG)
    jsonschema.validate(config, _load(SCHEMA))
    for path_key, hash_key in (
        ("config_path", "config_sha256"),
        ("schema_path", "schema_sha256"),
        ("spec_path", "spec_sha256"),
    ):
        path = ROOT / config["supersedes"][path_key]
        assert _sha256(path) == config["supersedes"][hash_key]
    package = ROOT / config["supersedes"]["package_path"] / "SHA256SUMS"
    assert _sha256(package) == config["supersedes"]["package_sha256_manifest"]
    inherited = config["inherited_contract"]
    assert _sha256(ROOT / inherited["criteria_config_path"]) == inherited[
        "criteria_config_sha256"
    ]
    assert _sha256(ROOT / inherited["criteria_spec_path"]) == inherited[
        "criteria_spec_sha256"
    ]


def test_corrective_03_preserves_every_frozen_threshold() -> None:
    criteria = _load(V1)["criteria"]
    config = _load(CONFIG)
    assert len([item for item in criteria if item["tier"] == "readiness"]) == 23
    assert len([item for item in criteria if item["tier"] == "stretch"]) == 6
    assert config["preserved_contract"] == {
        "planned_take_count": 47,
        "bearing_sim_real_condition_count": 32,
        "raw_microphone_channel_count": 4,
        "maximum_clip_run_readiness_threshold_samples": 8,
        "sustained_clipping_minimum_consecutive_samples": 4000,
        "thresholds_changed": False,
        "claimed_envelope_changed": False,
        "scientific_eligibility_changed": False,
        "holdout_identity_changed": False,
    }


def test_window_contract_is_exact_and_scientifically_separates_derivations() -> None:
    config = _load(CONFIG)
    windows = config["window_observation_contract"]
    assert windows["expected_count_by_duration_s"] == {"15": 119, "20": 159}
    assert windows["window_samples"] == 4000
    assert windows["hop_samples"] == 2000
    assert windows["exact_contiguous_window_index_set_required"] is True
    assert windows["no_valid_bearing_window"] == "take_failure"
    assert config["bearing_derivation"]["per_take_error"] == (
        "median(valid_window_circular_absolute_errors_deg)"
    )
    assert config["repeatability_derivation"][
        "per_take_representative_bearing"
    ] == "statistics.median(valid_window_srp_bearing_deg_f_project)"
    assert config["sector_derivation"]["per_take_sector"] == (
        "unique_strict_majority_of_valid_window_sector_names"
    )


def test_effective_semantics_are_machine_readable_not_prose() -> None:
    semantics = _load(CONFIG)["scientific_semantics_authentication"]
    assert semantics["arbitrary_effective_semantics_prose_permitted"] is False
    assert semantics["exact_register_equality_required"] is True
    assert semantics["bearing_resolution"]["resolution_id"] == (
        "exact_window_error_then_per_take_median"
    )
    assert semantics["sector_resolution"]["resolution_id"] == (
        "valid_window_sector_strict_majority"
    )
    assert semantics["repeatability_resolution"]["resolution_id"] == (
        "existing_window_bearing_median_then_frozen_circular_range"
    )


def test_phase_boundary_remains_closed() -> None:
    boundary = _load(CONFIG)["phase_boundary"]
    assert boundary["holdout_observations_accessed"] == 0
    assert boundary["holdout_access_grant_created"] is False
    assert boundary["holdout_access_grant_consumed"] is False
    assert boundary["s4_8_started"] is False
    assert boundary["later_phases_started"] == []
    assert boundary["grant_still_required_for_s4_8"] is True
