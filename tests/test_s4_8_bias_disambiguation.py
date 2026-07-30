from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "s4_8_bias_disambiguation",
    ROOT / "scripts/run_s4_8_bias_disambiguation.py",
)
assert SPEC is not None and SPEC.loader is not None
bias = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bias)

RECHECK_SPEC = importlib.util.spec_from_file_location(
    "s4_8_22p5_recheck",
    ROOT / "scripts/run_s4_8_22p5_recheck.py",
)
assert RECHECK_SPEC is not None and RECHECK_SPEC.loader is not None
recheck = importlib.util.module_from_spec(RECHECK_SPEC)
RECHECK_SPEC.loader.exec_module(recheck)


def test_design_is_exactly_two_zero_then_two_45_degree_takes() -> None:
    takes = bias._take_definitions()

    assert [take["source_bearing_deg"] for take in takes] == [0.0, 0.0, 45.0, 45.0]
    assert [take["take_number"] for take in takes] == [1, 2, 3, 4]
    assert all(take["duration_s"] == 20 for take in takes)
    assert all(take["source_radius_m"] == 0.8 for take in takes)
    assert all(take["playback_gain"] == 0.75 for take in takes)
    assert all(take["rig_fixed"] is True for take in takes)
    assert all(take["mac_heading_fixed"] is True for take in takes)
    assert all(take["new_explicit_authorization_required"] is True for take in takes)
    assert [
        take["mac_removal_and_exact_reposition_before_take"] for take in takes
    ] == [False, True, True, True]


def test_22p5_recheck_is_one_take_in_a_new_additive_campaign() -> None:
    takes = recheck.workflow._take_definitions()

    assert recheck.workflow.DEFAULT_CAMPAIGN_ROOT.name == (
        "s4_8_bias_disambiguation_22p5_recheck_v2"
    )
    assert recheck.workflow.PROTOCOL_ID_PREFIX == (
        "s4_8_additive_22p5_recheck_v2"
    )
    assert [take["source_bearing_deg"] for take in takes] == [22.5]
    assert [take["take_number"] for take in takes] == [1]


def test_campaign_root_is_fixed_and_additive(tmp_path: Path) -> None:
    assert bias._campaign_root(bias.DEFAULT_CAMPAIGN_ROOT) == (
        bias.DEFAULT_CAMPAIGN_ROOT
    )
    with pytest.raises(bias.BiasDisambiguationError, match="fixed additive"):
        bias._campaign_root(tmp_path / "other")


def test_campaign_validation_allows_only_take_one_authorization() -> None:
    payload = {
        "schema": bias.SCHEMA,
        "campaign_id": bias.DEFAULT_CAMPAIGN_ROOT.name,
        "classification": bias.CLASSIFICATION,
        "authority": bias.AUTHORITY_NONE,
        "take_count": 4,
        "takes": bias._take_definitions(),
        "authorization_policy": {
            "automatic_continuation_forbidden": True,
            "explicit_authorization_required_before_each_take": True,
            "authorized_take_numbers": [1],
        },
    }
    manifest = {
        **payload,
        "manifest_sha256": bias.canonical_sha256(payload),
    }
    bias._validate_campaign(manifest)
    manifest["authorization_policy"]["authorized_take_numbers"] = [1, 2]
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    manifest["manifest_sha256"] = bias.canonical_sha256(payload)
    with pytest.raises(bias.BiasDisambiguationError, match="identity or scope"):
        bias._validate_campaign(manifest)


def test_additive_authorization_binds_exact_take_and_ledger_tip() -> None:
    manifest = {
        "manifest_sha256": "campaign-sha",
        "code_head": "base-head",
        "takes": bias._take_definitions(),
    }
    prior_records = [{"record_sha256": "take-1-record-sha"}]
    payload = {
        "schema": bias.AUTHORIZATION_SCHEMA,
        "recorded_at_utc": "2026-07-29T00:00:00+00:00",
        "campaign_manifest_sha256": "campaign-sha",
        "base_code_head": "base-head",
        "controller_head": "controller-head",
        "controller_source_sha256": "controller-source-sha",
        "take_number": 2,
        "take_id": "s48eng_bias_000_take_02",
        "target_bearing_deg_f_project": 0.0,
        "previous_record_sha256": "take-1-record-sha",
        "scope": "single_engineering_take_only",
        "automatic_continuation_authorized": False,
        "retry_authorized": False,
        "classification": bias.CLASSIFICATION,
        "authority": bias.AUTHORITY_NONE,
    }
    authorization = {
        **payload,
        "authorization_sha256": bias.canonical_sha256(payload),
    }

    bias._validate_authorization(authorization, manifest, prior_records, 2)

    authorization["take_number"] = 3
    changed_payload = {
        key: value
        for key, value in authorization.items()
        if key != "authorization_sha256"
    }
    authorization["authorization_sha256"] = bias.canonical_sha256(
        changed_payload
    )
    with pytest.raises(bias.BiasDisambiguationError, match="authorization"):
        bias._validate_authorization(authorization, manifest, prior_records, 2)


def test_additive_authorization_forbids_automatic_continuation() -> None:
    manifest = {
        "manifest_sha256": "campaign-sha",
        "code_head": "base-head",
        "takes": bias._take_definitions(),
    }
    prior_records = [{"record_sha256": "take-1-record-sha"}]
    payload = {
        "schema": bias.AUTHORIZATION_SCHEMA,
        "recorded_at_utc": "2026-07-29T00:00:00+00:00",
        "campaign_manifest_sha256": "campaign-sha",
        "base_code_head": "base-head",
        "controller_head": "controller-head",
        "controller_source_sha256": "controller-source-sha",
        "take_number": 2,
        "take_id": "s48eng_bias_000_take_02",
        "target_bearing_deg_f_project": 0.0,
        "previous_record_sha256": "take-1-record-sha",
        "scope": "single_engineering_take_only",
        "automatic_continuation_authorized": True,
        "retry_authorized": False,
        "classification": bias.CLASSIFICATION,
        "authority": bias.AUTHORITY_NONE,
    }
    authorization = {
        **payload,
        "authorization_sha256": bias.canonical_sha256(payload),
    }

    with pytest.raises(bias.BiasDisambiguationError, match="authorization"):
        bias._validate_authorization(authorization, manifest, prior_records, 2)


def test_identity_is_explicitly_engineering_stratum_a() -> None:
    identity = bias.EngineeringIdentity(
        planned_take_id="s48eng_bias_000_take_01",
        stratum_id="A_controlled_boundary_sweep",
        duration_s=20,
        target_bearing_deg_f_project=0.0,
        repetition=1,
    )

    assert identity.payload_identity()["target_bearing_deg_f_project"] == 0.0
    assert identity.payload_identity()["stratum_id"] == (
        "A_controlled_boundary_sweep"
    )
