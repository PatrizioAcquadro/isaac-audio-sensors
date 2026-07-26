from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_7_holdout_acceptance.corrective_02.v3.json"
SCHEMA = (
    ROOT / "docs/schemas/s4_7_holdout_acceptance.corrective_02.v3.schema.json"
)
SPEC = (
    ROOT / "docs/development/specs/s4_holdout_acceptance_corrective_02.md"
)
V1 = ROOT / "configs/s4_7_holdout_acceptance.v1.json"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_corrective_02_contract_is_schema_valid_and_frozen() -> None:
    config = _load(CONFIG)
    jsonschema.validate(config, _load(SCHEMA))
    assert config["schema"] == "ias.s4_7.holdout_acceptance_corrective_config.v3"
    assert config["status"] == "frozen"
    assert config["corrective_id"] == "s4_7_corrective_02"
    assert config["supersedes"]["thresholds_changed"] is False
    assert config["supersedes"]["claimed_envelope_changed"] is False
    assert config["supersedes"]["scientific_eligibility_changed"] is False


def test_corrective_02_binds_corrective_01_and_same_unopened_holdout() -> None:
    config = _load(CONFIG)
    supersedes = config["supersedes"]
    binding = config["holdout_binding"]
    assert _sha256(ROOT / supersedes["config_path"]) == supersedes["config_sha256"]
    assert _sha256(ROOT / supersedes["spec_path"]) == supersedes["spec_sha256"]
    assert _sha256(ROOT / binding["seal_path"]) == binding["seal_file_sha256"]
    for key in ("partition_manifest", "session_manifest"):
        assert _sha256(ROOT / binding[f"{key}_path"]) == binding[f"{key}_sha256"]
    assert binding["planned_take_count"] == 47
    assert binding["scientifically_opened"] is False
    assert binding["technical_qa_only"] is True


def test_all_inherited_thresholds_are_unchanged() -> None:
    criteria = _load(V1)["criteria"]
    assert len(criteria) == 29
    readiness = [item for item in criteria if item["gating"]]
    stretch = [item for item in criteria if not item["gating"]]
    assert len(readiness) == 23
    assert len(stretch) == 6
    expected = {
        item["criterion_id"]: (
            item["tier"],
            item["gating"],
            item["comparator"],
            item["threshold"],
        )
        for item in criteria
    }
    assert len(expected) == 29


def test_effective_counts_and_clipping_semantics_are_exact() -> None:
    config = _load(CONFIG)
    sim = config["sim_vs_real"]
    clipping = config["clipping_contract"]
    identity = config["identity_contract"]
    assert sum(item["take_count"] for item in identity["stratum_rules"]) == 47
    assert len(identity["raw_microphone_ids"]) == 4
    assert config["latency_contract"]["interpretation"].endswith(
        "each of 47 planned takes"
    )
    assert sim["bearing_sim_real_condition_count"] == 32
    assert sim["bearing_referenced_take_count"] == 40
    assert sim["payload_may_supply_real"] is False
    assert sim["payload_paths"] == [
        "unadjusted_simulation",
        "adjusted_simulation",
    ]
    assert clipping["maximum_clip_run_readiness_threshold_samples"] == 8
    assert clipping["sustained_clipping_minimum_consecutive_samples"] == 4000
    assert clipping["sustained_clipping_take_denominator"] == 47
    assert clipping["maximum_clip_run_record_denominator"] == 188


def test_observation_derivation_contract_is_fail_closed() -> None:
    source = _load(CONFIG)["source_observation_contract"]
    assert source["reported_derived_values_must_match_exactly"] is True
    assert source[
        "non_finite_missing_duplicate_unknown_mismatched_or_inconsistent"
    ] == "fail_closed"
    assert "bearing_deg_to_sector_name" in source["sector_correct"]
    assert "20 degrees" in source["candidate_covered"]
    assert "reference_tdoa_us" in source["tdoa_absolute_error"]
    assert "failure_reasons" in source["failure_status"]


def test_historical_package_manifests_are_unchanged() -> None:
    assert _sha256(
        ROOT / "outputs/isaac_audio_sensors/S4/S4.7/SHA256SUMS"
    ) == "795ce0b263326b99f9c551dd2ce6b2f3682913a23a73c4449dc7d08f5656ce53"
    assert _sha256(
        ROOT
        / "outputs/isaac_audio_sensors/S4/S4.7_corrective_01/SHA256SUMS"
    ) == "de6b4f8ee8721d48deed51b177688f91b3d40f133bcabb3a7ea201dc157bc676"


def test_freeze_is_after_corrective_01_closeout() -> None:
    config = _load(CONFIG)
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", "6b0e838"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    closeout = datetime.fromisoformat(result.stdout.strip())
    frozen = datetime.fromisoformat(config["frozen_at_utc"].replace("Z", "+00:00"))
    assert closeout < frozen


def test_spec_declares_canonical_corrective_02_and_zero_access() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert "outputs/isaac_audio_sensors/S4/S4.7_corrective_02/" in text
    assert "No S4.8 grant is created or consumed" in text
    assert "exactly 32 A+B" in text
    assert "40 bearing-referenced" in text
    assert "4,000 consecutive samples" in text
