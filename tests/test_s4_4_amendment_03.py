from __future__ import annotations

import copy
import json
import shutil
from argparse import Namespace
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

import scripts.run_s4_4_amendment_03_readiness as readiness_runner
import scripts.run_s4_4_amendment_03_take as take_runner
from isaac_audio_sensors.acquisition.s4_4_amendment import (
    S44AmendmentError,
    canonical_sha256,
    canonicalize_holdout_technical_qa,
    combined_partition_manifest,
    load_amendment_configuration,
    load_json,
    require_evidence_access,
    sanitize_holdout_technical_qa,
    sha256_file,
    validate_holdout_technical_qa,
)
from isaac_audio_sensors.acquisition.s4_4_amendment_03 import (
    PREFLIGHT_SCHEMA,
    READINESS_SCHEMA,
    REQUIRED_READINESS_CHECKS,
    active_precollection_package,
    build_aggregate_index,
    build_future_manifests,
    build_inherited_fit_a,
    build_precollection_seal,
    load_configuration,
    validate_configuration,
    validate_future_attempt_census,
    validate_inherited_fit_a,
    validate_precollection_seal,
    validate_predecessor_bytes,
    validate_session_preflight,
    validate_session_readiness,
)
from scripts.build_s4_4_amendment_03 import build
from scripts.build_s4_4_amendment_03_multiday import (
    V1_PACKAGE_SHA256,
    V2_PACKAGE_SHA256,
    V3_PACKAGE_SHA256,
    V4_PACKAGE_SHA256,
    build_cutoff_inventory,
)
from scripts.build_s4_4_amendment_03_multiday import (
    build as build_multiday,
)
from scripts.validate_s4_4_amendment import validate as validate_predecessor_amendment
from scripts.validate_s4_4_amendment_03 import _validate_cutoff_inventory, validate

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/s4_4_data_expansion_amendment_03.v1.json"
CONFIG_02_PATH = ROOT / "configs/s4_4_data_expansion_amendment_02.v1.json"
INDEX_02_PATH = (
    ROOT / "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_02/evidence_index.v1.json"
)


@pytest.fixture(scope="module")
def config() -> dict:
    value = load_configuration(CONFIG_PATH, ROOT)
    validate_configuration(value)
    return value


@pytest.fixture(scope="module")
def future(config: dict) -> dict:
    return build_future_manifests(config, ROOT)


@pytest.fixture(scope="module")
def inherited(config: dict) -> dict:
    return build_inherited_fit_a(config, ROOT)


def _preflight(config: dict, session_id: str, value: str) -> dict:
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "status": "passed",
        "amendment_id": config["amendment_id"],
        "session_id": session_id,
        "session_date_local": value,
        "recorded_at_local": f"{value}T12:00:00-04:00",
        "collected_at_utc": f"{value}T16:00:00+00:00",
        "checks": {key: "passed" for key in config["preflight_required_checks"]},
        "identity_contract_sha256": canonical_sha256(config["identities"]),
        "observations": {
            "live_connectivity_and_readiness": {
                "protocol_mandated_device_state_change": False
            },
            "mac": {
                "keyboard_plane": "level",
                "lid_angle_deg": 90,
                "work_focus_active_operator_confirmed": True,
                "notifications_suppressed_operator_confirmed": True,
            },
            "respeaker": {"identity_and_format_confirmed": True},
            "zed": {"identity_and_readiness_confirmed": True},
            "clocks": {"truthful_timestamps_confirmed": True},
            "room_environment": {
                "canonical_room_id": "WANG_2022_DESK_NEAR_ENTRANCE",
                "operator_will_remain_outside_retained_camera_frames": True,
            },
            "mount_and_coordinates": {
                "fixture_id": "S4_TEMP_DESKTOP_FIXTURE_REV0",
                "project_frame": "F_project",
                "marked_origin_and_axes_unchanged_operator_confirmed": True,
                "room_bounds_verified": True,
            },
            "privacy": {
                (
                    "no_person_private_screen_credential_or_private_label_in_recordings"
                ): True
            },
            "storage": {"output_root_gitignored": True},
            "access": {"prospective_holdout_scientifically_opened": False},
        },
    }
    return {**payload, "preflight_sha256": canonical_sha256(payload)}


def _readiness(
    config: dict,
    preflight: dict,
    seal_sha256: str,
    *,
    status: str = "passed",
    expected_next_attempt_id: str = "s44a03_fit_b_001_sil__attempt_01",
) -> dict:
    payload = {
        "schema": READINESS_SCHEMA,
        "status": status,
        "amendment_id": config["amendment_id"],
        "session_id": preflight["session_id"],
        "session_date_local": preflight["session_date_local"],
        "collected_at_utc": f"{preflight['session_date_local']}T16:01:00+00:00",
        "precollection_seal_sha256": seal_sha256,
        "session_preflight_path": "dataset/test/preflight.json",
        "session_preflight_sha256": preflight["preflight_sha256"],
        "expected_next_attempt_id": expected_next_attempt_id,
        "checks": {
            key: "passed" if status == "passed" else "failed"
            for key in REQUIRED_READINESS_CHECKS
        },
        "observations": {
            "protocol_mandated_device_state_change": False,
            "mac_readiness": {
                "payload": {
                    "schema": "ias.s4_4.mac_readiness.v1",
                    "collector_version": "test",
                    "read_only": True,
                    "scope": "s4_4_reduced_readiness",
                    "collected_at": (
                        f"{preflight['session_date_local']}T16:00:00+00:00"
                    ),
                    "timezone": "UTC",
                    "power": {
                        "status": "collected",
                        "source": "Battery Power",
                        "on_ac_power": False,
                        "charging": False,
                        "battery_percent": 73,
                    },
                    "legacy_identity_output_reference_fields_required": False,
                }
            },
        },
        "attempt_allocated": False,
        "recorder_started": False,
        "playback_started": False,
        "zed_capture_started": False,
        "media_created": False,
        "failure_retention_class": (
            None if status == "passed" else "session_readiness_failure_not_attempt"
        ),
    }
    return {**payload, "readiness_sha256": canonical_sha256(payload)}


@pytest.fixture
def historical_cutoff_root(tmp_path: Path, config: dict) -> Path:
    """Materialize only the frozen take-34 state, independent of live dataset."""

    root = tmp_path / "historical-cutoff"
    tracked = Path(config["retention"]["tracked_evidence_root"])
    for relative in (
        "inheritance/inherited_fit_a.v1.json",
        "manifests/sessions/fit_b.json",
        "manifests/sessions/prospective_holdout.json",
    ):
        source = ROOT / tracked / relative
        destination = root / tracked / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    manifest = load_json(root / tracked / "manifests/sessions/fit_b.json")
    attempt_root = root / config["retention"]["attempt_root"]
    for take in manifest["takes"][:34]:
        planned_id = take["planned_take_id"]
        attempt_id = f"{planned_id}__attempt_01"
        directory = attempt_root / planned_id / attempt_id
        directory.mkdir(parents=True)
        payload = {
            "planned_take_id": planned_id,
            "attempt_id": attempt_id,
            "attempt_number": 1,
            "outcome": "valid",
            "retained": True,
            "partition": take["partition"],
            "session_id": take["session_id"],
            "take_definition_sha256": take["take_definition_sha256"],
            "precollection_seal_sha256": V1_PACKAGE_SHA256[
                "precollection_seal.v1.json"
            ],
            "scientific_outcome_used_for_replacement": False,
        }
        (directory / "manifest.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
    session = root / config["retention"]["session_root"] / "fit_b"
    session.mkdir(parents=True)
    (session / "preflight.json").write_text("{}\n", encoding="utf-8")
    return root


def test_configuration_changes_only_prospective_date_and_device_state_rules(
    config: dict,
) -> None:
    assert config["amendment_id"] == "s4_4_data_expansion_amendment_03"
    calendar = config["prospective_rule_changes"]["calendar_day_separation"]
    assert calendar["distinct_calendar_dates_required"] is False
    assert calendar["same_local_calendar_date_permitted"] is True
    assert calendar["truthful_dates_and_timestamps_required"] is True
    device = config["prospective_rule_changes"]["device_state"]
    assert all(
        device[key] is False
        for key in (
            "restart_required",
            "reboot_required",
            "power_cycle_required",
            "usb_disconnect_reconnect_required",
            "ssh_reconnect_required",
        )
    )
    assert "device_restart_or_reconnection" not in config["preflight_required_checks"]
    assert "live_connectivity_and_readiness" in config["preflight_required_checks"]
    power = config["prospective_rule_changes"]["mac_power_state"]
    assert power == {
        "ac_power_required": False,
        "battery_operation_permitted": True,
        "truthful_power_source_required": True,
        "truthful_charging_state_required": True,
        "truthful_battery_percentage_required": True,
    }


def test_amendment_01_and_02_immutable_tree_hashes_pass(config: dict) -> None:
    result = validate_predecessor_bytes(config, ROOT, require_machine_local=True)
    assert result["amendment_01"]["tracked_tree_sha256"] == (
        "ac10c42268d927952433c4205f98c9d5e73c36b022749045cff8a026acba2552"
    )
    assert result["amendment_02"]["tracked_tree_sha256"] == (
        "1a79193a645083d50729ae0dfa4b794e2197e1a2005e1e7c632492ae5d60160a"
    )
    assert result["amendment_02"]["machine_local_tree_sha256"] == (
        "05ad188516a4cb66d25cd370db50f8547aeef46d631677b5b05bdd19554940be"
    )


def test_future_counts_identities_and_exact_science(config: dict, future: dict) -> None:
    assert {key: len(value["takes"]) for key, value in future.items()} == {
        "fit_b": 51,
        "prospective_holdout": 47,
    }
    assert all(
        take["planned_take_id"].startswith("s44a03_")
        for manifest in future.values()
        for take in manifest["takes"]
    )
    assert all(
        "s4_4_data_expansion_amendment_03"
        in take["expected_artifact_paths"]["attempt_01_root"]
        for manifest in future.values()
        for take in manifest["takes"]
    )
    base_config = load_amendment_configuration(CONFIG_02_PATH, ROOT)
    from isaac_audio_sensors.acquisition.s4_4_amendment import build_manifests

    base = build_manifests(base_config)
    identity_fields = {
        "planned_take_id",
        "predecessor_planned_take_id",
        "successor_planned_take_id",
        "expected_artifact_paths",
        "take_definition_sha256",
        "group_id",
    }
    for session_id in future:
        new_science = [
            {key: value for key, value in take.items() if key not in identity_fields}
            for take in future[session_id]["takes"]
        ]
        old_science = [
            {key: value for key, value in take.items() if key not in identity_fields}
            for take in base[session_id]["takes"]
        ]
        assert new_science == old_science


def test_fit_b_reverse_order_low_to_high_and_holdout_counterbalance(
    future: dict,
) -> None:
    fit_b = future["fit_b"]["takes"]
    controlled = [take for take in fit_b if take["category"] == "controlled"]
    assert [
        (controlled[index]["target_radius_m"], controlled[index]["sweep_direction"])
        for index in (0, 16)
    ] == [(1.0, "clockwise"), (0.6, "counterclockwise")]
    gains = [
        take["playback_gain"] for take in fit_b if take["category"] == "confidence"
    ]
    assert gains == [0.25] * 4 + [0.5] * 4 + [1.0] * 4
    holdout = future["prospective_holdout"]["takes"]
    holdout_controlled = [take for take in holdout if take["category"] == "controlled"]
    assert [holdout_controlled[index]["sweep_direction"] for index in (0, 8, 16)] == [
        "clockwise",
        "counterclockwise",
        "clockwise",
    ]


def test_inherited_fit_a_exact_census_failure_replacement_and_inventory(
    config: dict, inherited: dict
) -> None:
    validate_inherited_fit_a(inherited, config)
    assert inherited["census"]["attempts"] == 52
    assert inherited["census"]["valid_takes"] == 51
    assert inherited["census"]["failures"] == 1
    assert inherited["census"]["replacements"] == 1
    assert inherited["replacement_allowance_reset"] is False
    assert inherited["additional_attempts_allowed_for_inherited_cells"] == 0
    cells = {cell["planned_take_id"]: cell for cell in inherited["logical_cells"]}
    special = cells["s44a02_fit_a_048_av"]
    assert [attempt["outcome"] for attempt in special["attempts"]] == [
        "invalid",
        "valid",
    ]
    assert [attempt["replacement"] for attempt in special["attempts"]] == [
        False,
        True,
    ]
    assert all(
        attempt["additional_attempts_allowed"] == 0 for attempt in special["attempts"]
    )
    for record in inherited["file_inventory"]:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["byte_size"]
        assert sha256_file(path) == record["sha256"]


def test_aggregate_logical_counts_and_no_group_leakage(
    config: dict, inherited: dict, future: dict
) -> None:
    aggregate = build_aggregate_index(
        config, inherited, future["fit_b"], future["prospective_holdout"]
    )
    assert aggregate["logical_counts"] == {
        "inherited_fit_a": 51,
        "new_fit_b": 51,
        "new_prospective_holdout": 47,
        "total": 149,
    }
    assert aggregate["fit_holdout_group_leakage"] is False
    partitions: dict[str, set[str]] = {}
    for manifest in future.values():
        for take in manifest["takes"]:
            partitions.setdefault(take["group_id"], set()).add(take["partition"])
    assert all(len(values) == 1 for values in partitions.values())


def test_same_date_sessions_and_multiday_session_segments_are_accepted(
    config: dict,
) -> None:
    fit_b = _preflight(config, "fit_b", "2026-07-22")
    holdout = _preflight(config, "prospective_holdout", "2026-07-22")
    fit_b_next_date = _preflight(config, "fit_b", "2026-07-23")
    validate_session_preflight(fit_b, config, other_records=[])
    validate_session_preflight(holdout, config, other_records=[fit_b])
    validate_session_preflight(fit_b_next_date, config, other_records=[fit_b, holdout])
    duplicate_segment = _preflight(config, "fit_b", "2026-07-22")
    with pytest.raises(S44AmendmentError, match="local-date segment"):
        validate_session_preflight(
            duplicate_segment, config, other_records=[fit_b, holdout]
        )


def test_partial_multiday_package_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "precollection_seal.v2.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(S44AmendmentError, match="incomplete"):
        active_precollection_package(tmp_path)


def test_truthful_exact_dates_and_timezone_aware_timestamps_required(
    config: dict,
) -> None:
    invalid_date = _preflight(config, "fit_b", "2026-07-22")
    invalid_date["session_date_local"] = "07/22/2026"
    invalid_date["preflight_sha256"] = canonical_sha256(
        {key: value for key, value in invalid_date.items() if key != "preflight_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="exact ISO"):
        validate_session_preflight(invalid_date, config, other_records=[])
    mismatch = _preflight(config, "fit_b", "2026-07-22")
    mismatch["recorded_at_local"] = "2026-07-23T00:01:00-04:00"
    mismatch["preflight_sha256"] = canonical_sha256(
        {key: value for key, value in mismatch.items() if key != "preflight_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="disagree"):
        validate_session_preflight(mismatch, config, other_records=[])
    naive = _preflight(config, "fit_b", "2026-07-22")
    naive["recorded_at_local"] = "2026-07-22T12:00:00"
    naive["preflight_sha256"] = canonical_sha256(
        {key: value for key, value in naive.items() if key != "preflight_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="timezone-aware"):
        validate_session_preflight(naive, config, other_records=[])


def test_restart_reconnection_field_is_rejected_and_no_claim_is_fabricated(
    config: dict,
) -> None:
    preflight = _preflight(config, "fit_b", "2026-07-22")
    preflight["checks"]["device_restart_or_reconnection"] = "passed"
    preflight["preflight_sha256"] = canonical_sha256(
        {key: value for key, value in preflight.items() if key != "preflight_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="check set"):
        validate_session_preflight(preflight, config, other_records=[])
    truthful = _preflight(config, "fit_b", "2026-07-22")
    live = truthful["observations"]["live_connectivity_and_readiness"]
    assert live == {"protocol_mandated_device_state_change": False}
    assert all("restart" not in key and "reconnect" not in key for key in live)


def test_battery_power_is_accepted_but_truthful_power_metadata_is_mandatory(
    config: dict,
) -> None:
    power = {
        "status": "collected",
        "source": "Battery Power",
        "on_ac_power": False,
        "charging": False,
        "battery_percent": 73,
    }
    reduced = {
        "schema": "ias.s4_4.mac_readiness.v1",
        "read_only": True,
        "power": power,
        "legacy_identity_output_reference_fields_required": False,
    }
    legacy = {
        "read_only": True,
        "power": power,
        "frozen_checks": {
            "ac_power": False,
            "model_identifier_matches": False,
            "output_device_matches": False,
            "reference_hash_matches": False,
        },
    }
    assert readiness_runner._mac_readiness_passed(reduced)
    assert readiness_runner._mac_readiness_passed(legacy)
    projection = readiness_runner.canonical_mac_readiness(legacy)
    assert set(projection) == {
        "schema",
        "read_only",
        "power",
        "legacy_identity_output_reference_fields_required",
    }
    assert projection["legacy_identity_output_reference_fields_required"] is False

    for field in ("source", "on_ac_power", "charging", "battery_percent"):
        changed = copy.deepcopy(reduced)
        changed["power"].pop(field)
        assert not readiness_runner._mac_readiness_passed(changed)
    malformed = copy.deepcopy(reduced)
    malformed["power"]["battery_percent"] = "73"
    assert not readiness_runner._mac_readiness_passed(malformed)
    inconsistent = copy.deepcopy(reduced)
    inconsistent["power"]["on_ac_power"] = True
    assert not readiness_runner._mac_readiness_passed(inconsistent)


def test_every_live_readiness_check_is_mandatory_and_media_boundary_is_closed(
    config: dict,
) -> None:
    today = date.today().isoformat()
    preflight = _preflight(config, "fit_b", today)
    readiness = _readiness(config, preflight, "1" * 64)
    validate_session_readiness(
        readiness,
        config,
        precollection_seal_sha256="1" * 64,
        session_preflight=preflight,
    )
    assert set(readiness["checks"]) == REQUIRED_READINESS_CHECKS
    for field in (
        "attempt_allocated",
        "recorder_started",
        "playback_started",
        "zed_capture_started",
        "media_created",
    ):
        changed = copy.deepcopy(readiness)
        changed[field] = True
        changed["readiness_sha256"] = canonical_sha256(
            {key: value for key, value in changed.items() if key != "readiness_sha256"}
        )
        with pytest.raises(S44AmendmentError, match="boundary"):
            validate_session_readiness(
                changed,
                config,
                precollection_seal_sha256="1" * 64,
                session_preflight=preflight,
            )
    missing = copy.deepcopy(readiness)
    missing["checks"].pop("privacy")
    missing["readiness_sha256"] = canonical_sha256(
        {key: value for key, value in missing.items() if key != "readiness_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="check set"):
        validate_session_readiness(
            missing,
            config,
            precollection_seal_sha256="1" * 64,
            session_preflight=preflight,
        )
    oversized = copy.deepcopy(readiness)
    oversized["observations"]["mac_readiness"]["payload"]["output_device"] = "legacy"
    oversized["readiness_sha256"] = canonical_sha256(
        {key: value for key, value in oversized.items() if key != "readiness_sha256"}
    )
    with pytest.raises(S44AmendmentError, match="reduced Mac"):
        validate_session_readiness(
            oversized,
            config,
            precollection_seal_sha256="1" * 64,
            session_preflight=preflight,
        )


def _prepare_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict,
    future: dict,
    *,
    status: str,
) -> tuple[Namespace, Path]:
    monkeypatch.setattr(take_runner, "ROOT", tmp_path)
    monkeypatch.setattr(take_runner, "load_configuration", lambda *_args: config)
    monkeypatch.setattr(
        take_runner, "require_capture_ready_package", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        take_runner, "validate_precollection_seal", lambda *_a, **_k: None
    )
    monkeypatch.setattr(take_runner, "validate_inherited_fit_a", lambda *_a, **_k: None)
    evidence_root = tmp_path / config["retention"]["tracked_evidence_root"]
    (evidence_root / "inheritance").mkdir(parents=True)
    (evidence_root / "manifests/sessions").mkdir(parents=True)
    (evidence_root / "inheritance/inherited_fit_a.v1.json").write_text("{}\n")
    seal_path = evidence_root / "precollection_seal.v1.json"
    seal_path.write_text("{}\n")
    manifest = future["fit_b"]
    (evidence_root / "manifests/sessions/fit_b.json").write_text(json.dumps(manifest))
    today = date.today().isoformat()
    preflight = _preflight(config, "fit_b", today)
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight))
    take = manifest["takes"][0]
    expected_attempt_id = f"{take['planned_take_id']}__attempt_01"
    readiness = _readiness(
        config,
        preflight,
        sha256_file(seal_path),
        status=status,
        expected_next_attempt_id=expected_attempt_id,
    )
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(json.dumps(readiness))
    args = Namespace(
        config=CONFIG_PATH,
        session_id="fit_b",
        planned_take_id=take["planned_take_id"],
        attempt_number=1,
        preflight=preflight_path,
        readiness=readiness_path,
        recorded_position=None,
        recorded_bearing=None,
        recorded_distance=None,
        placement_basis="operator_recorded_measurement",
        reposition_confirmed=False,
        pre_recording_failure=None,
    )
    return args, tmp_path / config["retention"]["attempt_root"]


def test_readiness_failure_creates_no_attempt_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict,
    future: dict,
) -> None:
    args, attempt_root = _prepare_fixture(
        tmp_path, monkeypatch, config, future, status="failed"
    )
    with pytest.raises(S44AmendmentError, match="identity/status"):
        take_runner.prepare(args)
    assert not attempt_root.exists()


def test_attempt_creation_requires_passed_hash_bound_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict,
    future: dict,
) -> None:
    args, attempt_root = _prepare_fixture(
        tmp_path, monkeypatch, config, future, status="passed"
    )
    result = take_runner.prepare(args)
    assert result["status"] == "awaiting_physical_operator_action"
    attempt_dir = (
        attempt_root
        / result["attempt_id"].split("__attempt_")[0]
        / result["attempt_id"]
    )
    assert attempt_dir.is_dir()
    contract = load_json(attempt_dir / "attempt_contract.json")
    assert (
        contract["session_readiness_sha256"]
        == load_json(args.readiness)["readiness_sha256"]
    )
    assert load_json(args.readiness)["expected_next_attempt_id"] == result["attempt_id"]


def test_readiness_is_bound_to_exact_next_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: dict,
    future: dict,
) -> None:
    args, attempt_root = _prepare_fixture(
        tmp_path, monkeypatch, config, future, status="passed"
    )
    readiness = load_json(args.readiness)
    readiness["expected_next_attempt_id"] = "s44a03_fit_b_002_ctl__attempt_01"
    readiness["readiness_sha256"] = canonical_sha256(
        {key: value for key, value in readiness.items() if key != "readiness_sha256"}
    )
    args.readiness.write_text(json.dumps(readiness), encoding="utf-8")
    with pytest.raises(S44AmendmentError, match="next-attempt binding"):
        take_runner.prepare(args)
    assert not attempt_root.exists()


def test_readiness_probes_next_unused_attempt_path_within_same_session(
    tmp_path: Path, future: dict
) -> None:
    manifest = future["fit_b"]
    attempt_root = tmp_path / "attempts"
    for take in manifest["takes"][:34]:
        planned_id = take["planned_take_id"]
        attempt_dir = attempt_root / planned_id / f"{planned_id}__attempt_01"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "manifest.json").write_text(
            json.dumps({"outcome": "valid"}), encoding="utf-8"
        )
    assert (
        readiness_runner._next_unallocated_attempt_id(manifest, attempt_root)
        == "s44a03_fit_b_035_conf__attempt_01"
    )
    assert not (attempt_root / "s44a03_fit_b_035_conf").exists()


def test_capture_is_prohibited_until_amendment_03_is_committed_and_sealed() -> None:
    seal = build_precollection_seal(bindings={"contract": "1" * 64}, checkpoint=None)
    validate_precollection_seal(seal, repo_root=ROOT, require_committed=False)
    with pytest.raises(S44AmendmentError, match="capture denied"):
        validate_precollection_seal(seal, repo_root=ROOT, require_committed=True)


def test_inherited_replacement_allowance_cannot_be_reset(
    inherited: dict, future: dict
) -> None:
    changed = copy.deepcopy(inherited)
    changed["replacement_allowance_reset"] = True
    changed["inherited_fit_a_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in changed.items()
            if key != "inherited_fit_a_sha256"
        }
    )
    with pytest.raises(S44AmendmentError, match="contract"):
        validate_inherited_fit_a(
            changed,
            {
                "immutable_predecessors": {
                    "amendment_02": {
                        "fit_a_in_progress_census_sha256": changed["census"][
                            "census_sha256"
                        ]
                    }
                }
            },
        )
    census = validate_future_attempt_census(inherited, future, [])
    assert census["attempts_total"] == 52
    assert census["valid_cells_total"] == 51
    assert census["failures_total"] == 1
    assert census["replacements_total"] == 1
    assert census["inherited_replacement_allowance_reset"] is False


def _qa_input(planned_id: str, **extra: object) -> dict:
    return {
        "planned_take_id": planned_id,
        "attempt_id": planned_id + "__attempt_01",
        "identity_pass": True,
        "assigned_metadata_pass": True,
        "duration_pass": True,
        "channel_order_pass": True,
        "channel_health_pass": True,
        "clipping_pass": True,
        "timestamps_pass": True,
        "reference_presence_pass": True,
        "integrity_pass": True,
        "privacy_pass": True,
        "full_svo2_replay_pass": True,
        **extra,
    }


def test_holdout_technical_qa_suppression_and_s4_5_fit_only_access_remain(
    inherited: dict, future: dict
) -> None:
    holdout_id = future["prospective_holdout"]["takes"][0]["planned_take_id"]
    qa = sanitize_holdout_technical_qa(
        _qa_input(holdout_id, bearing_error_deg=4.0, confidence=0.9),
        known_holdout_take_ids={holdout_id},
    )
    validate_holdout_technical_qa(qa)
    assert qa["scientific_outputs_exposed"] is False
    assert "bearing_error_deg" not in qa and "confidence" not in qa
    assert qa["schema"] == "ias.s4_4.amendment_technical_qa.v2"
    assert qa["six_channel_count_pass"] is True
    assert qa["no_detected_silent_channel_issue"] is True
    assert "channel_order_pass" not in qa
    legacy = {
        "schema": "ias.s4_4.amendment_technical_qa.v1",
        "partition": "prospective_holdout",
        **_qa_input(holdout_id),
        "overall_technical_pass": True,
        "scientific_outputs_exposed": False,
        "suppressed_field_count": 0,
    }
    projected = canonicalize_holdout_technical_qa(legacy)
    assert projected["source_schema"] == legacy["schema"]
    assert projected["assigned_metadata_declaration_carried_forward"] is True
    assert projected["producer_timestamps_present"] is True
    assert projected["playback_record_present_or_not_required"] is True
    assert projected["privacy_declaration_carried_forward"] is True
    fit_ids = {cell["planned_take_id"] for cell in inherited["logical_cells"]} | {
        take["planned_take_id"] for take in future["fit_b"]["takes"]
    }
    holdout_ids = set(
        combined_partition_manifest(
            {"prospective_holdout": future["prospective_holdout"]},
            "prospective_holdout",
        )["planned_take_ids"]
    )
    assert (
        require_evidence_access(
            planned_take_id=next(iter(fit_ids)),
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )["mode"]
        == "fit_only"
    )
    with pytest.raises(S44AmendmentError, match="denied"):
        require_evidence_access(
            planned_take_id=holdout_id,
            purpose="S4.5_fit",
            fit_ids=fit_ids,
            holdout_ids=holdout_ids,
        )


def test_amendment_02_validator_continues_to_pass() -> None:
    result = validate_predecessor_amendment(
        INDEX_02_PATH,
        repo_root=ROOT,
        config_path=CONFIG_02_PATH,
        require_tracked=True,
        require_committed=True,
        require_machine_local=False,
    )
    assert result["status"] == "passed", result["issues"]


def test_builder_is_byte_identical_and_validator_passes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_summary = build(output=first, config_path=CONFIG_PATH)
    second_summary = build(output=second, config_path=CONFIG_PATH)
    assert first_summary == second_summary
    assert first_summary["collection_allowed"] is False
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    result = validate(
        first / "evidence_index.v1.json",
        repo_root=ROOT,
        config_path=CONFIG_PATH,
        require_tracked=False,
        require_committed=False,
        require_machine_local=True,
        require_final=False,
    )
    assert result["status"] == "passed", result["issues"]
    assert result["prospective_holdout_scientifically_opened"] is False


def test_multiday_continuation_is_same_amendment_byte_identical_and_valid(
    tmp_path: Path,
    historical_cutoff_root: Path,
) -> None:
    first = tmp_path / "multiday-first"
    second = tmp_path / "multiday-second"
    first_summary = build_multiday(
        output=first,
        config_path=CONFIG_PATH,
        cutoff_root=historical_cutoff_root,
    )
    second_summary = build_multiday(
        output=second,
        config_path=CONFIG_PATH,
        cutoff_root=historical_cutoff_root,
    )
    assert first_summary == second_summary
    assert first_summary["new_amendment_created"] is False
    assert first_summary["collection_allowed"] is False
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert {
        relative: sha256_file(first / relative) for relative in V1_PACKAGE_SHA256
    } == V1_PACKAGE_SHA256
    assert {
        relative: sha256_file(first / relative) for relative in V2_PACKAGE_SHA256
    } == V2_PACKAGE_SHA256
    assert {
        relative: sha256_file(first / relative) for relative in V3_PACKAGE_SHA256
    } == V3_PACKAGE_SHA256
    assert {
        relative: sha256_file(first / relative) for relative in V4_PACKAGE_SHA256
    } == V4_PACKAGE_SHA256
    result = validate(
        first / "evidence_index.v5.json",
        repo_root=ROOT,
        config_path=CONFIG_PATH,
        require_tracked=False,
        require_committed=False,
        require_machine_local=True,
        require_final=False,
        cutoff_root=historical_cutoff_root,
    )
    assert result["status"] == "passed", result["issues"]
    assert result["attempt_census"]["valid_cells_total"] == 149
    continuation = load_json(first / "freeze/multiday_session_continuation.v5.json")
    assert continuation["cutoff"]["aggregate_census"]["valid_cells_total"] == 85
    assert continuation["cutoff"]["aggregate_census"]["attempts_total"] == 86
    assert result["prospective_holdout_scientifically_opened"] is False


def test_cutoff_includes_every_date_segment_record_in_same_fit_b_session(
    config: dict,
) -> None:
    cutoff = build_cutoff_inventory(config, ROOT)
    session_root = ROOT / config["retention"]["session_root"] / "fit_b"
    expected_paths = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(session_root.rglob("*.json"))
        if path.is_file()
    ]
    assert [record["path"] for record in cutoff["session_records"]] == expected_paths
    assert cutoff["cutoff_basis"] == "fit_b_retained_attempt_count"
    assert cutoff["date_segments_remain_within_same_fit_b_session"] is True
    _validate_cutoff_inventory(cutoff, config, ROOT)


def test_tampered_future_manifest_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    build(output=output, config_path=CONFIG_PATH)
    manifest_path = output / "manifests/sessions/fit_b.json"
    manifest = load_json(manifest_path)
    manifest["takes"][0]["duration_s"] += 1.0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate(
        output / "evidence_index.v1.json",
        repo_root=ROOT,
        config_path=CONFIG_PATH,
        require_tracked=False,
        require_committed=False,
        require_machine_local=True,
        require_final=False,
    )
    assert result["status"] == "failed"
    assert {issue["code"] for issue in result["issues"]} >= {
        "artifact_size_mismatch",
        "artifact_hash_mismatch",
        "amendment_03_contract_invalid",
    }


def test_category_counts_are_exact(future: dict, inherited: dict) -> None:
    inherited_counts = Counter(cell["category"] for cell in inherited["logical_cells"])
    assert inherited_counts == {
        "controlled": 32,
        "confidence": 12,
        "silence": 3,
        "audio_video": 4,
    }
    assert (
        Counter(take["category"] for take in future["fit_b"]["takes"])
        == inherited_counts
    )
    assert Counter(
        take["category"] for take in future["prospective_holdout"]["takes"]
    ) == {
        "controlled": 24,
        "confidence": 16,
        "silence": 3,
        "audio_video": 4,
    }
