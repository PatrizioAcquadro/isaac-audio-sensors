"""Guards for the published S3.9 fidelity envelope and evidence map."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields
from pathlib import Path

from isaac_audio_sensors.core.effects import EffectsConfig
from isaac_audio_sensors.core.fidelity import ACOUSTIC_FIDELITY_LADDER

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE = ROOT / "docs/development/specs/s3_fidelity_envelope.md"
CLAIM_MAP = ROOT / "outputs/isaac_audio_sensors/S3/S3.9/claim_evidence_map.json"
GATE = ROOT / "outputs/isaac_audio_sensors/S3/S3.9/fidelity_envelope_gate.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_audio_effects_config_surface_is_published() -> None:
    envelope = ENVELOPE.read_text(encoding="utf-8")
    top_level_surfaces = {
        f"[audio.effects.{field.name}]" for field in fields(EffectsConfig)
    }
    nested_surfaces = {
        "[audio.effects.channel_response.microphones.<mic_id>]",
        "[audio.effects.noise.self_noise.default]",
        "[audio.effects.noise.self_noise.microphones.<mic_id>]",
        "[audio.effects.noise.ambient]",
        "[audio.effects.electronics.agc]",
        "[audio.effects.directivity.source_patterns.default]",
        "[audio.effects.directivity.source_patterns.overrides.<source_id>]",
        "[audio.effects.directivity.mic_patterns.default]",
        "[audio.effects.directivity.mic_patterns.overrides.<mic_id>]",
    }
    for surface in top_level_surfaces | nested_surfaces:
        assert f"`{surface}`" in envelope, surface


def test_every_does_not_model_string_is_reconciled_verbatim() -> None:
    envelope = ENVELOPE.read_text(encoding="utf-8")
    for level in ACOUSTIC_FIDELITY_LADDER:
        for limitation in level.does_not_model:
            assert f"`{limitation}`" in envelope, (level.level, limitation)


def test_mandatory_occlusion_and_public_boundary_text_is_guarded() -> None:
    envelope = ENVELOPE.read_text(encoding="utf-8")
    assert (
        "Ray/transmission occlusion is NOT diffraction and is NOT a complete wave "
        "solver."
    ) in envelope
    assert "does not expand `docs/v1_scope.md`" in envelope
    assert "P1 owns the scaled effects-on 20 ms gate" in envelope


def test_claim_map_and_gate_are_complete_and_all_rows_passed() -> None:
    envelope = ENVELOPE.read_text(encoding="utf-8")
    claim_map = json.loads(CLAIM_MAP.read_text(encoding="utf-8"))
    gate = json.loads(GATE.read_text(encoding="utf-8"))

    published_claim_ids = set(re.findall(r"`(S3C-[0-9]{2})`", envelope))
    mapped_claim_ids = {row["claim_id"] for row in claim_map["rows"]}
    assert published_claim_ids == mapped_claim_ids
    assert claim_map["row_count"] == len(mapped_claim_ids)
    assert claim_map["status"] == "passed"
    assert claim_map["failed_rows"] == []
    assert claim_map["global_failures"] == []

    for row in claim_map["rows"]:
        assert row["status"] == "passed", row
        assert row["validating_test_ids"]
        assert row["off_state_test_ids"]
        assert row["evidence"]
        assert row["off_state_evidence"]
        assert row["failures"] == []
        for evidence in (*row["evidence"], *row["off_state_evidence"]):
            path = ROOT / evidence["artifact_path"]
            assert path.is_file(), path
            assert evidence["status"] == "passed"
            assert evidence["hash_matches"] is True
            assert evidence["sha256"] == evidence["expected_sha256"]
            assert _sha256(path) == evidence["sha256"]

    assert gate["status"] == "passed"
    assert gate["failed_rows"] == []
    assert gate["claim_row_count"] == claim_map["row_count"]
    assert all(status == "passed" for status in gate["rows"].values())
    assert all(gate["checks"].values())
    assert gate["envelope_sha256"] == _sha256(ENVELOPE)
    assert gate["claim_map_sha256"] == _sha256(CLAIM_MAP)
