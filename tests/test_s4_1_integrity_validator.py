from __future__ import annotations

from pathlib import Path

from scripts.validate_s4_1_integrity import parse_manifest, safe_repo_path


def test_safe_repo_path_rejects_absolute_and_parent_traversal() -> None:
    assert safe_repo_path("outputs/isaac_audio_sensors/S4/S4.1/gate.json")
    assert not safe_repo_path("/tmp/gate.json")
    assert not safe_repo_path("outputs/../private.json")
    assert not safe_repo_path("")


def test_manifest_parser_is_fail_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(
        "a" * 64 + "  evidence/frame.png\ninvalid\n",
        encoding="utf-8",
    )
    findings: list[str] = []

    rows = parse_manifest(manifest, findings)

    assert rows == {"evidence/frame.png": "a" * 64}
    assert findings == ["invalid hash manifest line 2: 'invalid'"]
