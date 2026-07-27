from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from isaac_audio_sensors.acquisition import s4_8
from isaac_audio_sensors.core.acceptance_criteria_corrective_03 import (
    build_synthetic_payload,
)

ROOT = Path(__file__).resolve().parents[1]

IMMUTABLE_OPERATIONAL_HASHES = {
    "dataset/S4.8/access/authorization_record.v1.json": (
        "4ab7e70466217a8541d44f7071d62b3bc1be24580e9b3b56eb6f9d1d90643c1d"
    ),
    "dataset/S4.8/access/holdout_access_grant.corrective_03.v1.json": (
        "22c8636944ee5d62f7f89e6d8557319c73775244f7d49e0f3a5af4e8b3fbba34"
    ),
    "dataset/S4.8/access/opening_transition.v1/access_ledger.jsonl": (
        "20f0decb2286be4c295a3afe46319e44bb53341b4f3b2a0a1c027176694c96dc"
    ),
    "dataset/S4.8/access/opening_transition.v1/first_run_journal.jsonl": (
        "0eab13440bd997bf7a79f85d8581bd62ce41ca1254681b75d22de938bd7b39ea"
    ),
    "dataset/S4.8/access/opening_transition.v1/recovery_context.v1.json": (
        "b01f4d7b006404ddc81321f6de43306b850b178625d9c065c136f7712a2eea75"
    ),
    "dataset/S4.8/derived/heldout_evaluation_input.v1.json": (
        "d68fbecedc6c15367675d0ea7e8f11fcb04beabe5bfb32d56253c0cd8a1f9a0f"
    ),
    "dataset/S4.8/recovery_amendment_01/access/authorization_record.v1.json": (
        "16e415df2e1ab77d72587f922f3298f5eeaa40db13fba91331d7a4511b0ad06d"
    ),
    (
        "dataset/S4.8/recovery_amendment_01/access/"
        "holdout_access_grant.corrective_03.v1.json"
    ): "73c095e7ed0b713a4a32330435331da08d5ca6d74d7f7b446e02eb0748079216",
    (
        "dataset/S4.8/recovery_amendment_01/access/opening_transition.v1/"
        "access_ledger.jsonl"
    ): "85e451d71406a3dd89754b42f2d4f1e1bfa53f5555553d131f8eabfc4a09932b",
    (
        "dataset/S4.8/recovery_amendment_01/access/opening_transition.v1/"
        "first_run_journal.jsonl"
    ): "308ca53b166e0f4a8115ea544d0b969a341641b313ccfb7937e323d6f674fe32",
    (
        "dataset/S4.8/recovery_amendment_01/access/opening_transition.v1/"
        "post_consumption_progress.v2/"
        "007451.e68bb5aaa8411f64db154aa0850a86cfd2955b2c7c8acd4985c809f7a1c7b839.json"
    ): "dc59917aa70cc892d499302aa2d264b3cb7542f174ff4afeac7b35292bed745f",
    (
        "dataset/S4.8/recovery_amendment_01/access/opening_transition.v1/"
        "recovery_context.v1.json"
    ): "141421fdf727a0382576ec5313d370e4edd271fd9ade62f323780db6b7c6ad13",
    (
        "dataset/S4.8/recovery_amendment_01/derived/heldout_evaluation_input.v1.json"
    ): "b8b243afb08bad0a12dfbae2881b68650f50c6d40921a035f2e4b2ac11e5c30d",
    (
        "dataset/S4.8/recovery_amendment_01/review/independent_review.v1.json"
    ): "1cabcc2af83288446fffd378a287f5b7bd1ca9746ec9ba88b14c1ffda19e12cb",
}

IMMUTABLE_PACKAGE_MANIFEST_HASHES = {
    "outputs/isaac_audio_sensors/S4/S4.8": (
        "bb3e57bdac2cdf545f9adf39e867db3bf5b35831892c66b101e57913af9e59e2"
    ),
    "outputs/isaac_audio_sensors/S4/S4.8_recovery_amendment_01": (
        "3ebcaf1070f5d8d53f878ea666cb8c63a4b9f1350d84e70ae68405a9652e3cbb"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_real_take(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stratum_id: str,
    target_bearing: float | None,
    emitted_bearing: float,
) -> dict[str, Any]:
    identity = SimpleNamespace(
        planned_take_id=f"synthetic_{stratum_id}",
        stratum_id=stratum_id,
        duration_s=15,
        target_bearing_deg_f_project=target_bearing,
        payload_identity=lambda: {
            "planned_take_id": f"synthetic_{stratum_id}",
            "stratum_id": stratum_id,
            "duration_s": 15,
            "target_bearing_deg_f_project": target_bearing,
        },
    )
    monkeypatch.setattr(s4_8, "_verify_sealed_file", lambda *_args: None)
    monkeypatch.setattr(
        s4_8,
        "inspect_six_channel_wav",
        lambda *_args, **_kwargs: (
            {
                "per_channel_rms_pcm16": [1.0] * 6,
                "per_channel_maximum_clip_run_samples": [0] * 6,
            },
            [],
        ),
    )
    monkeypatch.setattr(
        s4_8,
        "_read_pcm16",
        lambda _path: (np.zeros((240000, 6), dtype=float), 16000),
    )

    def analyze_window(*_args, index: int, start: int, **_kwargs):
        return (
            {
                "window_id": f"window_{index:03d}",
                "window_index": index,
                "start_sample": start,
                "abstained": False,
                "srp_bearing_deg_f_project": emitted_bearing,
                "sub_floor_direction_emitted": False,
            },
            0.8,
            {},
            {},
            0.0,
            0.0,
        )

    monkeypatch.setattr(s4_8, "_analyze_window", analyze_window)
    monkeypatch.setattr(
        s4_8,
        "load_json",
        lambda _path: {"overall_technical_pass": True},
    )
    monkeypatch.setattr(s4_8, "sha256_file", lambda _path: "0" * 64)
    monkeypatch.setattr(
        s4_8,
        "_derive_av_association",
        lambda *_args: {
            "audio_event_time_ms": 100.0,
            "video_event_time_ms": 104.0,
            "av_absolute_residual_ms": 4.0,
        },
    )
    take, _inventory = s4_8._analyze_real_take(
        ROOT,
        ROOT / "synthetic/attempt_01",
        identity,
        profile={
            "gain_multipliers": [1.0] * 4,
            "positions": [
                [0.0, 0.0, 0.0],
                [0.1, 0.0, 0.0],
                [0.0, 0.1, 0.0],
                [0.1, 0.1, 0.0],
            ],
        },
        seal={},
    )
    return take


@pytest.mark.parametrize(
    ("stratum_id", "target_bearing", "expected_confidence", "expected_av"),
    [
        ("C_center_low_level", 0.0, 0.8, (None, None, None)),
        ("D_silence", None, None, (None, None, None)),
        ("E_impact_audio_video", None, None, (100.0, 104.0, 4.0)),
    ],
)
def test_non_applicable_strata_do_not_publish_incidental_srp_bearings(
    monkeypatch: pytest.MonkeyPatch,
    stratum_id: str,
    target_bearing: float | None,
    expected_confidence: float | None,
    expected_av: tuple[float | None, float | None, float | None],
) -> None:
    take = _synthetic_real_take(
        monkeypatch,
        stratum_id=stratum_id,
        target_bearing=target_bearing,
        emitted_bearing=44.0,
    )

    assert take["window_summary"] == {
        "source_window_count": 119,
        "abstained_window_count": 0,
        "sub_floor_direction_emission_count": 0,
    }
    assert take["estimated_bearing_deg_f_project"] is None
    assert take["bearing_absolute_error_deg"] is None
    assert take["bearing_windows"] == []
    assert take["candidate_covered"] is None
    assert take["candidate_bearings_deg_f_project"] == []
    assert take["sector_correct"] is None
    assert take["tdoa"] == []
    assert take["confidence"] == expected_confidence
    assert (
        take["audio_event_time_ms"],
        take["video_event_time_ms"],
        take["av_absolute_residual_ms"],
    ) == expected_av


@pytest.mark.parametrize(
    ("stratum_id", "expected_sector", "expected_tdoa_count"),
    [
        ("A_controlled_boundary_sweep", None, 6),
        ("B_center_nominal_level", True, 0),
    ],
)
def test_applicable_strata_preserve_representative_and_window_semantics(
    monkeypatch: pytest.MonkeyPatch,
    stratum_id: str,
    expected_sector: bool | None,
    expected_tdoa_count: int,
) -> None:
    take = _synthetic_real_take(
        monkeypatch,
        stratum_id=stratum_id,
        target_bearing=0.0,
        emitted_bearing=4.0,
    )

    assert take["estimated_bearing_deg_f_project"] == 4.0
    assert take["bearing_absolute_error_deg"] == 4.0
    assert take["candidate_covered"] is True
    assert take["candidate_bearings_deg_f_project"] == [4.0]
    assert take["sector_correct"] is expected_sector
    assert len(take["bearing_windows"]) == 119
    assert [item["window_index"] for item in take["bearing_windows"]] == list(
        range(119)
    )
    assert {item["srp_bearing_deg_f_project"] for item in take["bearing_windows"]} == {
        4.0
    }
    assert len(take["tdoa"]) == expected_tdoa_count


def test_tdoa_take_median_excludes_abstained_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = SimpleNamespace(
        planned_take_id="synthetic_tdoa_abstention",
        stratum_id="A_controlled_boundary_sweep",
        duration_s=15,
        target_bearing_deg_f_project=0.0,
        payload_identity=lambda: {
            "planned_take_id": "synthetic_tdoa_abstention",
            "stratum_id": "A_controlled_boundary_sweep",
            "duration_s": 15,
            "target_bearing_deg_f_project": 0.0,
        },
    )
    monkeypatch.setattr(s4_8, "_verify_sealed_file", lambda *_args: None)
    monkeypatch.setattr(
        s4_8,
        "inspect_six_channel_wav",
        lambda *_args, **_kwargs: (
            {
                "per_channel_rms_pcm16": [1.0] * 6,
                "per_channel_maximum_clip_run_samples": [0] * 6,
            },
            [],
        ),
    )
    monkeypatch.setattr(
        s4_8,
        "_read_pcm16",
        lambda _path: (np.zeros((240000, 6), dtype=float), 16000),
    )
    pair_ids = s4_8._pair_ids()

    def analyze_window(*_args, index: int, start: int, **_kwargs):
        abstained = index >= 10
        tdoa_s = 200e-6 if abstained else 10e-6
        return (
            {
                "window_id": f"window_{index:03d}",
                "window_index": index,
                "start_sample": start,
                "abstained": abstained,
                "srp_bearing_deg_f_project": None if abstained else 0.0,
                "sub_floor_direction_emitted": False,
            },
            0.0 if abstained else 0.1,
            dict.fromkeys(pair_ids, tdoa_s),
            dict.fromkeys(pair_ids, 1.0),
            0.0,
            0.0,
        )

    monkeypatch.setattr(s4_8, "_analyze_window", analyze_window)
    monkeypatch.setattr(
        s4_8,
        "load_json",
        lambda _path: {"overall_technical_pass": True},
    )
    monkeypatch.setattr(s4_8, "sha256_file", lambda _path: "0" * 64)

    take, _inventory = s4_8._analyze_real_take(
        ROOT,
        ROOT / "synthetic/attempt_01",
        identity,
        profile={
            "gain_multipliers": [1.0] * 4,
            "positions": [
                [0.0, 0.0, 0.0],
                [0.1, 0.0, 0.0],
                [0.0, 0.1, 0.0],
                [0.1, 0.1, 0.0],
            ],
        },
        seal={},
    )

    assert take["window_summary"]["abstained_window_count"] == 109
    assert {item["tdoa_us"] for item in take["tdoa"]} == {10.0}


def test_visual_association_selects_nearest_significant_local_peak() -> None:
    host_times_ms = [float(index * 20) for index in range(101)]
    motion = [0.01] * 101
    motion[20] = 0.8
    motion[51] = 0.2

    selected = s4_8._select_significant_visual_peak(
        host_times_ms,
        motion,
        audio_event_time_ms=1000.0,
        search_half_width_ms=1000.0,
        robust_sigma_multiplier=8.0,
    )

    assert selected == 51


def test_non_applicable_representative_still_fails_closed() -> None:
    payload = build_synthetic_payload(ROOT)
    silence = next(
        take
        for take in payload["takes"]
        if take["identity"]["stratum_id"] == "D_silence"
    )
    silence["estimated_bearing_deg_f_project"] = 44.0

    result = s4_8.evaluate_payload(payload, repo_root=ROOT)

    assert result["readiness_passed"] is False
    assert result["criteria"] == []
    assert result["failed_gating_criteria"] == ["evaluation_input_contract_rejected"]
    assert (
        "estimated_bearing_deg_f_project is not applicable and must be null"
        in result["evaluation_error"]
    )


def test_conforming_complete_synthetic_payload_reaches_all_frozen_criteria() -> None:
    payload = build_synthetic_payload(ROOT)
    payload["sim_vs_real"] = s4_8.build_simulation_comparisons(ROOT)

    result = s4_8.evaluate_payload(payload, repo_root=ROOT)

    assert result["readiness_passed"] is True
    assert len(result["criteria"]) == 29
    assert sum(item["gating"] for item in result["criteria"]) == 23
    assert sum(not item["gating"] for item in result["criteria"]) == 6


def _assert_package_manifest(package: Path, expected_manifest_hash: str) -> None:
    manifest = package / "SHA256SUMS"
    assert _sha256(manifest) == expected_manifest_hash
    records = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", maxsplit=1)
        records[name] = digest
    assert set(records) == {
        path.name for path in package.iterdir() if path.name != "SHA256SUMS"
    }
    for name, expected in records.items():
        assert _sha256(package / name) == expected


@pytest.mark.skipif(
    not all((ROOT / path).is_file() for path in IMMUTABLE_OPERATIONAL_HASHES)
    or not all(
        (ROOT / package / "SHA256SUMS").is_file()
        for package in IMMUTABLE_PACKAGE_MANIFEST_HASHES
    ),
    reason="machine-local immutable S4.8 evidence is unavailable",
)
def test_terminal_evidence_matches_pre_correction_hashes() -> None:
    for relative, expected in IMMUTABLE_OPERATIONAL_HASHES.items():
        assert _sha256(ROOT / relative) == expected
    for relative, expected in IMMUTABLE_PACKAGE_MANIFEST_HASHES.items():
        package = ROOT / relative
        _assert_package_manifest(package, expected)
        final = json.loads(
            (package / "final_validation.json").read_text(encoding="utf-8")
        )
        assert final["status"] == "failed"
        assert final["terminal"] is True
        assert final["automatic_retry_forbidden"] is True
