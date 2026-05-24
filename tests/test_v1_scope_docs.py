"""Guardrails for the frozen v1 public scope documentation."""

from __future__ import annotations

from pathlib import Path

PROMISE_PHRASES = (
    "Stable `AudioSensorFrame` v1 public contract",
    "Stable L0 `geometry_only` backend",
    "Stable L1 `tdoa_synthetic` backend",
    "Supported optional L2 `room_acoustics` backend",
    "Supported Isaac Sim live sensor path",
    "Supported Isaac Lab sensor path",
    "Omniverse extension as the reference UX",
    "Stable JSON/JSONL export",
    "Replicator as an optional extension capability",
)
NON_PROMISE_PHRASES = (
    "SquadBot as a v1 release gate",
    "Sim-real calibration",
    "Real hardware benchmarks",
    "Complete L3/L4 acoustic fidelity",
    "Realistic occlusions or material acoustics",
    "Mandatory ROS 2 or downstream adapters",
    "Alex or SquadBot validation before releasing the sensor package",
)
SCOPE_LINKED_DOCS = (
    Path("README.md"),
    Path("docs/README.md"),
    Path("docs/api_freeze_0_1.md"),
    Path("docs/validation.md"),
    Path("docs/versioning.md"),
    Path("docs/roadmap.md"),
    Path("docs/open_source_release_checklist.md"),
)
FORBIDDEN_SCOPE_OVERCLAIMS = (
    "SquadBot validation is required",
    "Alex validation is required",
    "SquadBot release gate",
    "Alex release gate",
    "ROS 2 adapter is required",
    "ROS2 adapter is required",
    "downstream adapter is required",
    "real hardware benchmark is required",
    "sim-real calibration is required",
    "complete L3 runtime backend",
    "complete L4 runtime backend",
    "Replicator is required for core",
    "Replicator is a core dependency",
    "The package does not implement a Replicator annotator/writer registration",
)


def test_v1_scope_doc_lists_all_promises_and_non_promises() -> None:
    text = Path("docs/v1_scope.md").read_text(encoding="utf-8")

    for phrase in PROMISE_PHRASES + NON_PROMISE_PHRASES:
        assert phrase in text

    normalized = _normalized(text)
    assert "release gate" in normalized
    assert "must not be treated as package release gates" in normalized


def test_v1_scope_doc_is_linked_from_public_release_docs() -> None:
    for path in SCOPE_LINKED_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "v1_scope.md" in text or "docs/v1_scope.md" in text, path


def test_validation_and_release_checklist_define_gates_and_non_gates() -> None:
    combined = _normalized(
        "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in (
                "docs/validation.md",
                "docs/open_source_release_checklist.md",
            )
        )
    )
    raw_combined = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "docs/validation.md",
            "docs/open_source_release_checklist.md",
        )
    )

    for phrase in (
        "contract/schema/trace validation",
        "L0/L1 tests",
        "optional L2 behavior",
        "JSON/JSONL export",
        "Isaac Sim",
        "Isaac Lab",
        "extension UX",
        "packaging audit",
        "import smoke",
        "distribution audit",
        "Non-Gates For V1 Package Release",
    ):
        assert phrase in combined

    for phrase in NON_PROMISE_PHRASES:
        assert _normalized(phrase) in combined

    assert "Non-Gates For V1 Package Release" in raw_combined


def test_replicator_is_documented_as_optional_extension_only() -> None:
    combined = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/api_freeze_0_1.md",
            "docs/api_reference.md",
            "docs/architecture.md",
            "docs/isaac_sim.md",
            "docs/limitations.md",
            "docs/open_source_release_checklist.md",
            "docs/v1_scope.md",
            "docs/validation.md",
        )
    )

    for phrase in (
        "optional extension capability",
        "not a core dependency",
        "core package import",
        "JSON/JSONL export",
        "Isaac Lab sensor",
    ):
        assert phrase in combined


def test_public_docs_do_not_overclaim_v1_scope() -> None:
    docs = [Path("README.md"), *sorted(Path("docs").glob("*.md"))]
    for path in docs:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_SCOPE_OVERCLAIMS:
            assert phrase.lower() not in text, (path, phrase)


def _normalized(text: str) -> str:
    return " ".join(text.split())
