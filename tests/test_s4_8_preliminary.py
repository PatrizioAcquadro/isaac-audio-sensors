from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import wave
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from isaac_audio_sensors.acquisition import s4_8, s4_8_recovery_02
from isaac_audio_sensors.acquisition.s4_8_engineering_campaign import (
    S48EngineeringCampaignError,
    build_preliminary_manifest,
    build_reference_take_manifest,
    derive_preliminary_design,
    validate_preliminary_manifest,
)
from isaac_audio_sensors.acquisition.s4_8_preliminary import (
    AUTHORITY_NONE,
    CASE_IDS,
    DIAGNOSTIC_CLASSIFICATION,
    S48PreliminaryError,
    _candidate_seal_manifest_authenticated,
    build_diagnostic_package,
    build_readiness_report,
    build_reuse_decision,
    load_workflow_config,
    process_case,
    resolve_reprocessing_record_paths,
    run_diagnostic_evaluator,
)
from isaac_audio_sensors.acquisition.s4_8_presealing_gate import canonical_sha256
from isaac_audio_sensors.core import acceptance_criteria_corrective_03

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / (
    "outputs/isaac_audio_sensors/S4/S4.4/amendments/"
    "s4_4_data_expansion_amendment_03/manifests/sessions/"
    "prospective_holdout.json"
)


def _manifest() -> dict[str, object]:
    design = derive_preliminary_design(json.loads(TEMPLATE.read_text(encoding="utf-8")))
    return build_preliminary_manifest(
        code_head="4" * 40,
        source_archive_sha256="1" * 64,
        source_package_hashes={"controller.py": "2" * 64},
        environment={"python": "3.12.3"},
        reference_wav_sha256="3" * 64,
        gate_configuration_sha256="5" * 64,
        detector_configuration_sha256="6" * 64,
        controller={"identity": "preliminary", "version": "1", "sha256": "7" * 64},
        protocol={"identity": "four_take_preliminary", "sha256": "8" * 64},
        devices={
            "respeaker": {"profile_id": "respeaker_usb_6ch_pcm16_v1"},
            "playback": {"model": "MacBookPro18,1"},
            "zed": {"model": "ZED 2i"},
        },
        channel_map=[
            "Conference",
            "ASR",
            "raw microphone 0",
            "raw microphone 1",
            "raw microphone 2",
            "raw microphone 3",
        ],
        design=design,
        retry_policy={
            "maximum_attempts_per_planned_take": 2,
            "replacement_requires_retained_retry_required": True,
            "sequence_advances_only_after_pass": True,
            "configuration_change_restarts_campaign": True,
        },
        operational_locations={
            "campaign_root": "/tmp/s4_8_preliminary",
            "pi_capture_root": "S4.8/preliminary",
        },
        template_manifest_sha256=hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
    )


def _case_results() -> list[dict[str, object]]:
    return [
        {
            "case_id": case_id,
            "acquisition_gate": "PASS",
            "technical_validation_gate": "PASS",
            "detector_processing_gate": "PASS",
            "synchronization_gate": (
                "PASS" if case_id == "audio_video_impact_with_zed" else "NOT_APPLICABLE"
            ),
            "derived_take": {"case": case_id},
            "classification": DIAGNOSTIC_CLASSIFICATION,
            "authority": AUTHORITY_NONE,
        }
        for case_id in CASE_IDS
    ]


def _package(manifest: dict[str, object]) -> dict[str, object]:
    evaluation = {
        "preliminary_manifest_sha256": manifest["manifest_sha256"],
        "gate": "PASS",
    }
    return build_diagnostic_package(
        manifest=manifest,
        case_results=_case_results(),
        evaluation=evaluation,
    )


def test_active_workflow_is_exactly_four_preliminary_plus_one_37_holdout() -> None:
    config = load_workflow_config(ROOT)

    assert config["preliminary"]["planned_take_count"] == 4
    assert [case["case_id"] for case in config["preliminary"]["cases"]] == list(
        CASE_IDS
    )
    assert config["official_path"]["official_take_count"] == 37
    assert config["official_path"]["official_holdout_count"] == 1
    assert (
        config["official_path"]["final_protocol_status"]
        == "frozen_for_precollection"
    )
    assert config["official_path"]["official_acquisition_status"] == (
        "permitted_with_exact_per_take_authorization"
    )
    assert config["authority"] == AUTHORITY_NONE


def test_preliminary_manifest_has_four_unofficial_representative_cases() -> None:
    manifest = _manifest()
    validate_preliminary_manifest(
        manifest,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
    )

    assert manifest["planned_take_count"] == 4
    assert manifest["classification"] == DIAGNOSTIC_CLASSIFICATION
    assert [take["preliminary_case_id"] for take in manifest["design"]] == list(
        CASE_IDS
    )
    assert [take["stratum_id"] for take in manifest["design"]] == [
        "B_center_nominal_level",
        "C_center_low_level",
        "D_silence",
        "E_impact_audio_video",
    ]
    assert all(
        take["engineering_take_id"].startswith("s48prelim_")
        for take in manifest["design"]
    )


def test_preliminary_manifest_rejects_official_eligibility_or_fifth_take() -> None:
    manifest = _manifest()
    altered = copy.deepcopy(manifest)
    altered["classification"]["official_evidence_eligible"] = True
    with pytest.raises(S48EngineeringCampaignError):
        validate_preliminary_manifest(
            altered,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
        )
    altered = copy.deepcopy(manifest)
    altered["design"].append(copy.deepcopy(altered["design"][-1]))
    altered["planned_take_count"] = 5
    with pytest.raises(S48EngineeringCampaignError):
        validate_preliminary_manifest(
            altered,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
        )


def test_reuse_policy_is_scope_sensitive_and_not_blanket_reacquisition() -> None:
    downstream = build_reuse_decision(
        correction_id="fix-metric-packaging",
        change_class="downstream_code",
        affected_case_ids=["nominal_reference"],
        raw_sha256_by_case={"nominal_reference": "a" * 64},
        decision="reuse",
        technical_justification="Raw acquisition bytes and conditions are unchanged.",
        physical_confirmation="not_applicable",
        physical_confirmation_evidence=None,
        replacement_complete=False,
    )
    assert downstream["decision"] == "reuse"
    assert downstream["automatic_four_take_reacquisition"] is False

    with pytest.raises(S48PreliminaryError, match="require affected-take"):
        build_reuse_decision(
            correction_id="change-gain",
            change_class="playback_gain",
            affected_case_ids=["nominal_reference"],
            raw_sha256_by_case={"nominal_reference": "a" * 64},
            decision="reuse",
            technical_justification="Gain changed.",
            physical_confirmation="not_applicable",
            physical_confirmation_evidence=None,
            replacement_complete=False,
        )

    detector = build_reuse_decision(
        correction_id="detector-fix",
        change_class="detector_or_processing",
        affected_case_ids=["nominal_reference", "low_level_reference"],
        raw_sha256_by_case={
            "nominal_reference": "a" * 64,
            "low_level_reference": "b" * 64,
        },
        decision="reuse",
        technical_justification="Raw signal validity is unaffected.",
        physical_confirmation="not_required_by_evidence",
        physical_confirmation_evidence=(
            "Regression proves the correction consumes identical PCM inputs."
        ),
        replacement_complete=False,
    )
    assert detector["physical_confirmation"] == "not_required_by_evidence"


def test_reprocessing_paths_support_authenticated_whole_campaign_relocation(
    tmp_path: Path,
) -> None:
    take_id = "s48prelim_002_low_level_reference"
    declared_root = Path("/old/runtime/s4_8_preliminary")
    runtime_root = tmp_path / "s4_8_preliminary"
    attempt_suffix = (
        Path("attempts") / take_id / f"{take_id}__attempt_03"
    )
    historical_names = (
        "raw_capture",
        "retry_report",
        "gate_report",
        "controller_result",
        "process_journal",
        "take_precollection_manifest",
        "attempt_ledger",
        "campaign_manifest",
    )
    record = {
        "preliminary_take_id": take_id,
        "attempt_number": 3,
        "attempt_path": str(declared_root / attempt_suffix),
        "historical_result": {
            name: {
                "path": str(
                    declared_root
                    / (
                        f"historical/{name}"
                        if name not in {"attempt_ledger", "campaign_manifest"}
                        else (
                            "attempt_ledger.jsonl"
                            if name == "attempt_ledger"
                            else "freeze/campaign_manifest.json"
                        )
                    )
                )
            }
            for name in historical_names
        },
        "corrected_offline_result": {
            "report": {
                "path": str(
                    declared_root
                    / "diagnostics/correction/gate_report.reprocessed.json"
                )
            }
        },
    }
    original = copy.deepcopy(record)

    paths = resolve_reprocessing_record_paths(
        record,
        runtime_campaign_root=runtime_root,
    )

    assert paths["attempt_path"] == runtime_root / attempt_suffix
    assert paths["historical_result"]["attempt_ledger"] == (
        runtime_root / "attempt_ledger.jsonl"
    )
    assert paths["corrected_report"] == (
        runtime_root / "diagnostics/correction/gate_report.reprocessed.json"
    )
    assert record == original


def test_reprocessing_relocation_rejects_artifact_outside_campaign(
    tmp_path: Path,
) -> None:
    take_id = "s48prelim_002_low_level_reference"
    declared_root = Path("/old/runtime/s4_8_preliminary")
    record = {
        "preliminary_take_id": take_id,
        "attempt_number": 3,
        "attempt_path": str(
            declared_root
            / "attempts"
            / take_id
            / f"{take_id}__attempt_03"
        ),
        "historical_result": {
            name: {"path": str(declared_root / name)}
            for name in (
                "raw_capture",
                "retry_report",
                "gate_report",
                "controller_result",
                "process_journal",
                "take_precollection_manifest",
                "attempt_ledger",
                "campaign_manifest",
            )
        },
        "corrected_offline_result": {
            "report": {"path": "/outside/corrected-report.json"}
        },
    }

    with pytest.raises(S48PreliminaryError, match="escapes declared campaign"):
        resolve_reprocessing_record_paths(
            record,
            runtime_campaign_root=tmp_path / "s4_8_preliminary",
        )


def test_readiness_requires_all_gates_and_resolved_physical_confirmation() -> None:
    manifest = _manifest()
    package = _package(manifest)
    decision = build_reuse_decision(
        correction_id="detector-fix",
        change_class="detector_or_processing",
        affected_case_ids=["nominal_reference"],
        raw_sha256_by_case={"nominal_reference": "a" * 64},
        decision="reuse",
        technical_justification="PCM remains valid and representative.",
        physical_confirmation="not_required_by_evidence",
        physical_confirmation_evidence="Exact-input replay and targeted regression.",
        replacement_complete=False,
    )

    report = build_readiness_report(
        manifest=manifest,
        package=package,
        reuse_decisions=[decision],
    )

    assert report["status"] == "passed"
    assert report["final_protocol_freeze_permitted"] is True
    assert report["final_protocol_frozen"] is False
    assert report["official_acquisition_permitted"] is False
    assert report["grant_creation_authorized"] is False
    assert report["holdout_opening_authorized"] is False

    tampered = copy.deepcopy(package)
    tampered["gates"]["detector_processing"]["status"] = "FAIL"
    blocked = build_readiness_report(
        manifest=manifest,
        package=tampered,
        reuse_decisions=[decision],
    )
    assert blocked["status"] == "failed"
    assert blocked["final_protocol_freeze_permitted"] is False


def test_silence_raw_take_runs_current_detector_and_metric_path(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    take = next(
        item for item in manifest["design"] if item["preliminary_case_id"] == "silence"
    )
    attempt = tmp_path / "silence_attempt"
    attempt.mkdir()
    capture = attempt / "respeaker_audio.wav"
    samples = np.zeros((15 * 16_000, 6), dtype="<i2")
    samples[:, 2:6] = np.rint(
        np.random.default_rng(480).normal(0.0, 8.0, size=(15 * 16_000, 4))
    ).astype("<i2")
    with wave.open(str(capture), "wb") as stream:
        stream.setnchannels(6)
        stream.setsampwidth(2)
        stream.setframerate(16_000)
        stream.writeframes(samples.tobytes())
    capture_sha256 = hashlib.sha256(capture.read_bytes()).hexdigest()
    classification = copy.deepcopy(DIAGNOSTIC_CLASSIFICATION)
    gate_report = {"decision": "PASS"}
    (attempt / "gate_report.json").write_text(
        json.dumps(gate_report),
        encoding="utf-8",
    )
    (attempt / "controller_result.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "preliminary_case_id": "silence",
                "classification": classification,
                "counts_as_official_take": False,
                "official_evidence_eligible": False,
            }
        ),
        encoding="utf-8",
    )
    seal_payload = {
        "engineering_only": True,
        "capture_sha256": capture_sha256,
        "campaign_manifest_sha256": manifest["manifest_sha256"],
        "engineering_take_definition_sha256": take[
            "engineering_take_definition_sha256"
        ],
        "report_sha256": canonical_sha256(gate_report),
        "authority": {
            "official_state_machine": False,
            "publishes_official_evidence": False,
        },
    }
    (attempt / "candidate_seal.json").write_text(
        json.dumps(
            {
                **seal_payload,
                "seal_sha256": canonical_sha256(seal_payload),
            }
        ),
        encoding="utf-8",
    )

    result = process_case(
        ROOT,
        manifest=manifest,
        case_root=attempt,
        case_id="silence",
    )

    assert result["technical_validation_gate"] == "PASS"
    assert result["detector_processing_gate"] == "PASS"
    assert result["derived_take"]["identity"]["stratum_id"] == "D_silence"
    assert result["classification"] == DIAGNOSTIC_CLASSIFICATION


def test_reference_candidate_seal_authenticates_v2_take_manifest(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    take = next(
        item
        for item in manifest["design"]
        if item["preliminary_case_id"] == "nominal_reference"
    )
    take_manifest = build_reference_take_manifest(
        campaign_manifest=manifest,
        take=take,
        expected_campaign_manifest_sha256=str(manifest["manifest_sha256"]),
    )
    (tmp_path / "take_precollection_manifest.json").write_text(
        json.dumps(take_manifest),
        encoding="utf-8",
    )

    assert _candidate_seal_manifest_authenticated(
        attempt=tmp_path,
        candidate_seal={"manifest_sha256": take_manifest["manifest_sha256"]},
        campaign_manifest=manifest,
        take=take,
        campaign_anchor=str(manifest["manifest_sha256"]),
    )

    altered = copy.deepcopy(take_manifest)
    altered["protocol_id"] = f"{altered['protocol_id']}:altered"
    (tmp_path / "take_precollection_manifest.json").write_text(
        json.dumps(altered),
        encoding="utf-8",
    )
    assert not _candidate_seal_manifest_authenticated(
        attempt=tmp_path,
        candidate_seal={"manifest_sha256": take_manifest["manifest_sha256"]},
        campaign_manifest=manifest,
        take=take,
        campaign_anchor=str(manifest["manifest_sha256"]),
    )


def test_diagnostic_evaluator_runs_exact_contract_with_four_replacements() -> None:
    manifest = _manifest()
    payload = acceptance_criteria_corrective_03.build_synthetic_payload(ROOT)
    takes = {take["identity"]["planned_take_id"]: take for take in payload["takes"]}
    case_results = [
        {
            "case_id": take["preliminary_case_id"],
            "source_evaluator_take_id": take["template_planned_take_id"],
            "derived_take": takes[take["template_planned_take_id"]],
        }
        for take in manifest["design"]
    ]

    result = run_diagnostic_evaluator(
        ROOT,
        manifest=manifest,
        case_results=case_results,
    )

    assert result["gate"] == "PASS"
    assert result["raw_preliminary_take_count"] == 4
    assert result["synthetic_completion_take_count"] == 43
    assert result["official_take_count"] == 0
    assert result["official_s4_8_pass_claimed"] is False
    assert result["evaluation"]["readiness_passed"] is True


def test_diagnostic_completion_uses_the_real_runtime_domain() -> None:
    manifest = _manifest()
    payload = acceptance_criteria_corrective_03.build_synthetic_payload(ROOT)
    takes = {take["identity"]["planned_take_id"]: take for take in payload["takes"]}
    observed_runtime_ms = {
        "nominal_reference": 253.906784,
        "low_level_reference": 253.894235,
        "silence": 253.898150,
        "audio_video_impact_with_zed": 253.903464,
    }
    case_results = []
    for take in manifest["design"]:
        derived = copy.deepcopy(takes[take["template_planned_take_id"]])
        derived["latency"]["capture_to_frame_offline_ms"] = observed_runtime_ms[
            take["preliminary_case_id"]
        ]
        case_results.append(
            {
                "case_id": take["preliminary_case_id"],
                "source_evaluator_take_id": take["template_planned_take_id"],
                "derived_take": derived,
            }
        )

    result = run_diagnostic_evaluator(
        ROOT,
        manifest=manifest,
        case_results=case_results,
    )
    criterion = next(
        item
        for item in result["evaluation"]["criteria"]
        if item["criterion_id"] == "capture_to_frame_offline_spread"
    )

    assert criterion["observed"] == pytest.approx(
        max(observed_runtime_ms.values()) - min(observed_runtime_ms.values())
    )
    assert criterion["passed"] is True
    assert result["synthetic_completion"]["runtime_domain_alignment"] == {
        "capture_to_frame_offline_ms": pytest.approx(253.900807),
        "frame_to_adapter_round_trip_ms": pytest.approx(1.0),
    }


def test_av_sequence_alignment_reproduces_preliminary_origin_error() -> None:
    audio_start_ms = 1785371185249.431
    audio_samples = [104493, 116039, 124897, 177454, 184795, 256761, 268182]
    audio_times_ms = [audio_start_ms + sample / 16.0 for sample in audio_samples]
    visual_frame_indices = [
        46,
        91,
        149,
        152,
        168,
        170,
        172,
        174,
        264,
        286,
        288,
        291,
        417,
        421,
        430,
        444,
        448,
        451,
        454,
        565,
    ]
    visual_times_ms = [
        1785371189005.559,
        1785371190505.5781,
        1785371192439.071,
        1785371192539.095,
        1785371193072.4512,
        1785371193139.2368,
        1785371193205.75,
        1785371193272.476,
        1785371196272.6072,
        1785371197006.003,
        1785371197072.5752,
        1785371197172.6028,
        1785371201372.917,
        1785371201506.393,
        1785371201806.545,
        1785371202273.0352,
        1785371202406.469,
        1785371202506.636,
        1785371202606.344,
        1785371206306.591,
    ]
    legacy_audio = [
        audio_start_ms + sample / 16.0
        for sample in (104493, 184795, 268182)
    ]
    legacy_video = [
        1785371192439.071,
        1785371197006.003,
        1785371201806.545,
    ]
    assert max(
        abs(audio_ms - video_ms)
        for audio_ms, video_ms in zip(legacy_audio, legacy_video, strict=True)
    ) == pytest.approx(658.82763671875)

    aligned = s4_8._align_av_event_sequences(
        audio_times_ms,
        visual_times_ms,
        event_count=3,
        expected_interval_ms=5000.0,
        maximum_origin_offset_ms=1000.0,
    )

    assert [audio_samples[index] for index in aligned["audio_indices"]] == [
        124897,
        184795,
        256761,
    ]
    assert [
        visual_frame_indices[index] for index in aligned["video_indices"]
    ] == [174, 286, 421]
    assert aligned["timestamp_origin_offset_ms"] == pytest.approx(209.399658203125)
    assert aligned["worst_absolute_residual_ms"] == pytest.approx(7.5830078125)


def test_amendment_02_keeps_evaluation_blocked_after_protocol_freeze(
) -> None:
    result = s4_8_recovery_02.recovery_preopen_validate(
        ROOT,
        require_access_paths_absent=False,
    )

    assert result["preliminary_take_count"] == 4
    assert result["planned_take_count"] == 37
    assert result["final_protocol_frozen"] is True
    assert result["official_readiness"] == "no_go"
    assert (
        "new_unseen_holdout_not_collected_or_bound" in result["blockers"]
    ) is not result["holdout_collection_complete"]
    assert (
        "evaluator_not_bound_to_37_take_protocol" in result["blockers"]
    ) is not result["evaluator_binding_authenticated"]
    assert (
        "independent_review_not_present" in result["blockers"]
    ) is not result["independent_review_authenticated"]
    assert "explicit_authorization_not_granted" in result["blockers"]
    assert result["grant_creation_authorized"] is False
    assert result["evaluation_execution_authorized"] is False


def test_workflow_schema_rejects_authority_and_count_changes() -> None:
    config = json.loads(
        (ROOT / "configs/s4_8_preliminary_workflow.v1.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/s4_8_preliminary_workflow.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    altered = copy.deepcopy(config)
    altered["preliminary"]["planned_take_count"] = 47
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(altered, schema)
    altered = copy.deepcopy(config)
    altered["authority"]["creates_grant"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(altered, schema)


def test_v9_campaign_files_remain_identical_to_preserved_commit() -> None:
    for relative in (
        "configs/s4_8_engineering_campaign.v1.json",
        "docs/development/specs/s4_8_engineering_campaign.md",
    ):
        historical = subprocess.run(
            ["git", "show", f"fd662c06f63c3f14cb1761a8172d44800ae7afb4:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        assert (ROOT / relative).read_bytes() == historical
