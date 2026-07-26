from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from isaac_audio_sensors.acquisition.s4_7_prerequisite_corrective_03 import (
    expected_scientific_semantics_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/s4_8_heldout_evaluation.v1.json"
SCHEMA = ROOT / "docs/schemas/s4_8_heldout_evaluation.v1.schema.json"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_s4_8_contract_schema_and_frozen_bindings() -> None:
    config = _load(CONFIG)
    jsonschema.validate(config, _load(SCHEMA))
    bindings = (
        ("prerequisite", "path", "sha256"),
        ("prerequisite", "package_manifest_path", "package_manifest_sha256"),
        ("holdout", "seal_path", "seal_file_sha256"),
        ("holdout", "partition_manifest_path", "partition_manifest_sha256"),
        ("holdout", "session_manifest_path", "session_manifest_sha256"),
        ("profile_application", "config_path", "config_sha256"),
        ("profile_application", "active_pointer_path", "active_pointer_sha256"),
        ("criteria", "v1_config_path", "v1_config_sha256"),
        ("criteria", "corrective_config_path", "corrective_config_sha256"),
        ("criteria", "corrective_schema_path", "corrective_schema_sha256"),
    )
    for section, path_key, digest_key in bindings:
        record = config[section]
        assert isinstance(record, dict)
        path = ROOT / str(record[path_key])
        assert path.is_file()
        assert _sha256(path) == record[digest_key]


def test_s4_8_contract_preserves_scientific_semantics_and_counts() -> None:
    config = _load(CONFIG)
    prerequisite = config["prerequisite"]
    criteria = config["criteria"]
    holdout = config["holdout"]
    assert isinstance(prerequisite, dict)
    assert isinstance(criteria, dict)
    assert isinstance(holdout, dict)
    assert (
        prerequisite["scientific_semantics_sha256"]
        == expected_scientific_semantics_sha256(ROOT)
    )
    assert criteria["readiness_count"] == 23
    assert criteria["stretch_count"] == 6
    assert criteria["robustness_status"] == "not_evaluable"
    assert criteria["robustness_denominator"] == 0
    assert holdout["planned_take_count"] == 47
    assert holdout["leakage_group_count"] == 15


def test_s4_8_contract_uses_ignored_single_use_access_paths() -> None:
    config = _load(CONFIG)
    grant = config["grant"]
    assert isinstance(grant, dict)
    assert grant["single_use"] is True
    assert grant["serial_no_retry"] is True
    assert grant["purpose"] == "S4.8_evaluation"
    assert grant["consume_function"].endswith(".consume_s4_8_grant")
    assert str(grant["path"]).startswith("dataset/")
    assert str(grant["ledger_path"]).startswith("dataset/")


def test_s4_8_phase_boundary_excludes_later_phases() -> None:
    config = _load(CONFIG)
    boundary = config["phase_boundary"]
    assert isinstance(boundary, dict)
    assert boundary == {
        "s4_9_started": False,
        "s5_started": False,
        "s6_started": False,
        "s4_complete_after_s4_8": False,
        "push_tag_release_authorized": False,
    }
