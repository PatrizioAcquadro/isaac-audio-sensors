from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_7_holdout_acceptance.corrective_01.v2.json"
SCHEMA = ROOT / "docs/schemas/s4_7_holdout_acceptance.corrective_01.v2.schema.json"
SPEC = ROOT / "docs/development/specs/s4_holdout_acceptance_corrective_01.md"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_corrective_contract_is_schema_valid_and_frozen() -> None:
    config = _load(CONFIG)
    jsonschema.validate(config, _load(SCHEMA))
    assert config["status"] == "frozen"
    assert config["corrective_id"] == "s4_7_corrective_01"
    assert config["supersedes"]["thresholds_changed"] is False
    assert config["supersedes"]["claimed_envelope_changed"] is False
    assert config["supersedes"]["scientific_eligibility_changed"] is False


def test_corrective_binds_historical_v1_and_same_unopened_holdout() -> None:
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


def test_freeze_is_truthfully_after_baseline_commit() -> None:
    config = _load(CONFIG)
    baseline = config["baseline"]
    result = subprocess.run(
        ["git", "show", "-s", "--format=%cI", baseline["commit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    committed = datetime.fromisoformat(result.stdout.strip())
    frozen = datetime.fromisoformat(config["frozen_at_utc"].replace("Z", "+00:00"))
    assert committed < frozen
    recorded = datetime.fromisoformat(
        baseline["committed_at_utc"].replace("Z", "+00:00")
    )
    assert recorded == committed


def test_identity_contract_is_exactly_four_raw_mics_and_six_pairs() -> None:
    identity = _load(CONFIG)["identity_contract"]
    assert identity["raw_microphone_ids"] == [
        "raw_microphone_0",
        "raw_microphone_1",
        "raw_microphone_2",
        "raw_microphone_3",
    ]
    assert len(identity["microphone_pair_ids"]) == 6
    assert len(set(identity["microphone_pair_ids"])) == 6
    assert sum(item["take_count"] for item in identity["stratum_rules"]) == 47


def test_window_latency_and_clip_aggregation_are_unambiguous() -> None:
    config = _load(CONFIG)
    assert config["window_contract"]["expected_count_by_duration_s"] == {
        "15": 119,
        "20": 159,
    }
    assert "47 planned takes" in config["latency_contract"]["interpretation"]
    assert (
        config["physical_domains"]["clip_run_samples"]["aggregation"]
        == "maximum_over_all_four_raw_microphone_take_records"
    )


def test_sim_real_registry_is_exact_and_uses_32_for_bearing() -> None:
    sim = _load(CONFIG)["sim_vs_real"]
    registry = sim["comparison_registry"]
    assert len(registry) == 7
    assert len({item["comparison_id"] for item in registry}) == 7
    bearing = next(item for item in registry if item["metric"] == "bearing_doa_error")
    confidence = next(item for item in registry if item["metric"] == "confidence")
    assert bearing["expected_count"] == 32
    assert bearing["applicable_strata"] == [
        "A_controlled_boundary_sweep",
        "B_center_nominal_level",
    ]
    assert confidence["expected_count"] == 16
    assert sim["bearing_referenced_take_count"] == 40
    assert sim["payload_may_supply_direction_or_band"] is False


def test_spec_names_canonical_corrective_paths_and_zero_access() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert "outputs/isaac_audio_sensors/S4/S4.7_corrective_01/" in text
    assert "No S4.8 grant is created or consumed" in text
    assert "four analysis" in text
    assert "`raw_microphone_0..3`" in text
    assert "32 A+B takes" in text
