from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "configs/s4_8_recovery_amendment_03_future_holdout.v2.json"
)
SCHEMA_PATH = (
    ROOT
    / "docs/schemas/s4_8_recovery_amendment_03_future_holdout.v2.schema.json"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_future_holdout_contract_validates_and_preserves_frozen_bindings() -> None:
    contract = _load(CONTRACT_PATH)
    schema = _load(SCHEMA_PATH)

    jsonschema.validate(contract, schema)

    inherited = contract["extends"]
    assert _sha256(ROOT / inherited["release_candidate_path"]) == inherited[
        "release_candidate_sha256"
    ]
    scope = contract["scope"]
    assert _sha256(ROOT / scope["base_design_path"]) == scope["base_design_sha256"]
    for name in ("reference_policy", "evaluator", "pipeline"):
        preserved = contract["preserved_contract"]
        assert _sha256(ROOT / preserved[f"{name}_path"]) == preserved[
            f"{name}_sha256"
        ]
    assert contract["authority"] == {
        "collects_data": False,
        "creates_grant": False,
        "consumes_grant": False,
        "opens_holdout": False,
        "executes_official_evaluation": False,
        "publishes_official_evidence": False,
        "authorizes_new_holdout": False,
        "starts_later_phase": False,
    }


def test_each_future_bc_pair_differs_only_by_playback_gain() -> None:
    contract = _load(CONTRACT_PATH)
    control = contract["pairing_control"]
    design = _load(ROOT / contract["scope"]["base_design_path"])
    design_by_id = {
        take["planned_take_id"]: take for take in design["take_order"]
    }
    pairs = control["pairs"]

    assert len(design_by_id) == contract["scope"]["planned_take_count"] == 37
    assert len(pairs) == contract["scope"]["bc_pair_count"] == 4
    assert control["only_allowed_scientific_difference"] == "playback_gain"

    corrected_c_ids: set[str] = set()
    for pair in pairs:
        conditions = pair["scientific_conditions"]
        b = pair["b"]
        c = pair["c"]
        realized_b = {**conditions, "playback_gain": b["playback_gain"]}
        realized_c = {**conditions, "playback_gain": c["playback_gain"]}
        differences = {
            field
            for field in realized_b
            if realized_b[field] != realized_c[field]
        }

        assert differences == {"playback_gain"}
        assert b["playback_gain"] == control["b_playback_gain"] == 0.75
        assert c["playback_gain"] == control["c_playback_gain"] == 0.35

        base_b = design_by_id[b["planned_take_id"]]
        base_c = design_by_id[c["planned_take_id"]]
        assert pair["pair_id"] == base_b["leakage_group_id"]
        assert pair["pair_id"] == base_c["leakage_group_id"]
        assert conditions["target_bearing_deg_f_project"] == base_b["bearing_deg"]
        assert conditions["target_bearing_deg_f_project"] == base_c["bearing_deg"]
        assert conditions["target_radius_m"] == base_b["radius_m"]
        assert conditions["target_radius_m"] == base_c["radius_m"]
        assert conditions["nuisance_condition_id"] == base_b["condition_id"]
        assert base_c["condition_id"] == "low_volume"
        reference = conditions["reference_signal"]
        assert _sha256(ROOT / reference["path"]) == reference["sha256"]
        corrected_c_ids.add(c["planned_take_id"])

    assert len(corrected_c_ids) == contract["scope"]["changed_take_count"]
    assert (
        len(design_by_id) - len(corrected_c_ids)
        == contract["scope"]["unchanged_take_count"]
    )
    assert corrected_c_ids == {
        "s48r02_preholdout_031_low_front_000",
        "s48r02_preholdout_032_low_right_090",
        "s48r02_preholdout_033_low_rear_180",
        "s48r02_preholdout_034_low_left_270",
    }


def test_schema_rejects_a_c_specific_nuisance_or_gain_override() -> None:
    contract = _load(CONTRACT_PATH)
    schema = _load(SCHEMA_PATH)

    nuisance_override = copy.deepcopy(contract)
    nuisance_override["pairing_control"]["pairs"][0]["c"][
        "nuisance_condition_id"
    ] = "clean"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(nuisance_override, schema)

    gain_override = copy.deepcopy(contract)
    gain_override["pairing_control"]["pairs"][0]["c"]["playback_gain"] = 0.34
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(gain_override, schema)
