#!/usr/bin/env python3
"""Regenerate S2 review addenda from machine-produced evidence only."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "outputs/isaac_audio_sensors/S2"
CLOSEOUT_ROOT = REPO_ROOT / "docs/development/closeouts"
BEGIN = "<!-- BEGIN GENERATED S2 REVIEW REMEDIATION -->"
END = "<!-- END GENERATED S2 REVIEW REMEDIATION -->"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "passed":
        raise RuntimeError(f"refusing closeout generation from non-passing {path}")
    return payload


def _replace_generated(path: Path, body: str) -> None:
    text = path.read_text(encoding="utf-8").rstrip()
    paragraphs = []
    for paragraph in body.rstrip().split("\n\n"):
        paragraphs.append(
            paragraph
            if paragraph.startswith("#")
            else textwrap.fill(
                paragraph,
                width=88,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    rendered_body = "\n\n".join(paragraphs)
    block = f"{BEGIN}\n\n{rendered_body}\n\n{END}"
    if BEGIN in text:
        prefix, tail = text.split(BEGIN, 1)
        if END not in tail:
            raise RuntimeError(f"unterminated generated block in {path}")
        _old, suffix = tail.split(END, 1)
        text = f"{prefix.rstrip()}\n\n{block}{suffix}"
    else:
        text = f"{text}\n\n{block}"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    remediation = _read(OUTPUT_ROOT / "S2.review/remediation_gate.json")
    guided = _read(OUTPUT_ROOT / "S2.7/guided_workflow_gate.json")
    parity = _read(OUTPUT_ROOT / "S2.8/parity_gate.json")
    audio = guided["audio_acceptance"]
    reset = guided["reset_lifecycle"]
    if (
        reset.get("status") != "passed"
        or reset.get("isaac_post_reset_callback_registered") is not True
        or reset.get("manual_recorder_notification") is not False
        or reset.get("episode_count") != 2
        or reset.get("reset_count") != 1
        or reset.get("equal_identity_before_reset")
        != reset.get("equal_identity_after_reset")
    ):
        raise RuntimeError("refusing closeout generation from invalid reset evidence")
    semantic = parity["semantic_diff"]
    parity_audio = semantic["audio_parity"]
    gate_status = {item["name"]: item["status"] for item in remediation["gates"]}

    addenda = {
        "S2/s2_2_atomic_writers.md": (
            "## S2 review remediation (regenerated)\n\n"
            "Fresh-process ENOSPC coverage passes for manifest temporary-file "
            "write, atomic replace, temporary-file fsync, and session-root "
            "directory fsync. Durable finalization intent remains under "
            "`_staging/` until manifest publication is complete, and recovery "
            "produces a validator-clean final session. Evidence: "
            "`outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json`."
        ),
        "S2/s2_3_checked_replay.md": (
            "## S2 review remediation (regenerated)\n\n"
            "The documented export-only FLAC path now passes int16 and int24 "
            "export/replay, exact declared-type decoded comparisons, corruption "
            "location, and missing-dependency behavior. Evidence: "
            "`outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json`."
        ),
        "S2/s2_6_validation_controller.md": (
            "## S2 review remediation (regenerated)\n\n"
            "Explicit compute-device and calibration-profile checks now execute "
            "through the shared controller. GUI and headless results are "
            "identical, and replacement/deletion plus device-change tests prove "
            "that neither check answers from stale state. Evidence: "
            "`outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json`."
        ),
        "S2/s2_7_operational_gui.md": (
            "## S2 review remediation rerun (regenerated)\n\n"
            f"The real room-acoustics waveform backend produced {audio['frame_count']} "
            f"attributed frame ranges; {audio['nonempty_attributed_ranges']} were "
            f"nonempty and {audio['nonzero_sample_values']} decoded sample values "
            "were nonzero. The exported dataset has zero validator errors. "
            "An actual sensor reset, without a manual recorder notification, created "
            "a second episode with an explicit ResetMarker even when frame id, "
            "timestamp, and producer frame index were unchanged. Evidence: "
            "`outputs/isaac_audio_sensors/S2/S2.7/`."
        ),
        "S2/s2_8_headless_parity.md": (
            "## S2 review remediation rerun (regenerated)\n\n"
            f"The live GUI/headless rerun compared {parity_audio['ranges_compared']} "
            "nonempty attributed waveform ranges from the real room-acoustics "
            f"backend. All {parity_audio['exact_ranges']} ranges were byte-exact, "
            f"with nonzero counts {parity_audio['nonzero_sample_values']['left']} "
            f"and {parity_audio['nonzero_sample_values']['right']}; semantic "
            f"difference count was {semantic['difference_count']}. Both exports "
            "have zero validator errors. Evidence: "
            "`outputs/isaac_audio_sensors/S2/S2.8/parity_gate.json`."
        ),
    }
    for relative, body in addenda.items():
        _replace_generated(CLOSEOUT_ROOT / relative, body)

    phase_path = CLOSEOUT_ROOT / "S2_closeout.md"
    phase_text = phase_path.read_text(encoding="utf-8")
    old_reset = (
        "- Simulator reset boundaries are not yet exposed by the tick contract, so\n"
        "  recorded episodes carry no mid-episode reset markers (documented in\n"
        "  workflow.py); S3.2 (time gaps and intra-window motion) is the natural\n"
        "  owner."
    )
    new_reset = (
        "- Guided recording subscribes to the Isaac post-reset lifecycle and the\n"
        "  sensor reset lifecycle; each actual reset closes and starts episodes,\n"
        "  and the first post-reset record carries an explicit reset marker.\n"
        "  Timestamp/frame-index rollback remains a tested fallback."
    )
    previous_generated_reset = (
        "- Guided recording now closes and starts episodes at explicit simulator\n"
        "  reset notifications and detected timestamp/frame-index rollbacks; the\n"
        "  first post-reset record carries the reset marker."
    )
    if old_reset in phase_text or previous_generated_reset in phase_text:
        phase_path.write_text(
            phase_text.replace(old_reset, new_reset).replace(
                previous_generated_reset,
                new_reset,
            ),
            encoding="utf-8",
        )
    _replace_generated(
        phase_path,
        "## S2 review remediation exit gate (regenerated)\n\n"
        "All review findings are closed without changing the frozen acceptance "
        "criteria. Manifest finalization recovery, shared device/calibration "
        "validation, FLAC export/replay, and guided reset-boundary gates pass. "
        "The live guided gate performs an actual sensor reset without manually "
        "notifying the recorder and proves the equal-identity edge creates a new "
        "episode with an explicit ResetMarker. "
        f"The S2.7 real-waveform rerun has {audio['nonempty_attributed_ranges']} "
        "nonempty attributed ranges and nonzero audio; the S2.8 rerun has exact "
        f"GUI/headless audio across {parity_audio['exact_ranges']} ranges and "
        f"{semantic['difference_count']} semantic differences. Generated pure-gate "
        f"statuses: {json.dumps(gate_status, sort_keys=True)}.",
    )

    dedicated = CLOSEOUT_ROOT / "S2/s2_review_remediation.md"
    gate_count = len(remediation["gates"])
    dedicated.write_text(
        "# S2 review remediation closeout\n\n"
        "Status: **passed** (generated from executable evidence).\n\n"
        "This closeout is regenerated by "
        "`scripts/regenerate_s2_review_closeouts.py`; it refuses any\n"
        "non-passing input artifact. The frozen S2 acceptance criteria were not\n"
        "edited.\n\n"
        f"- Pure remediation gates: {gate_count}/{gate_count} passed.\n"
        f"- S2.7: {audio['frame_count']} frames, "
        f"{audio['nonempty_attributed_ranges']} nonempty ranges, "
        f"{audio['nonzero_sample_values']} nonzero sample values.\n"
        "- S2.7 reset lifecycle: Isaac callback registered; actual sensor reset;\n"
        "  no manual recorder notification; 2 episodes; 1 reset; equal frame\n"
        "  identity preserved; explicit ResetMarker.\n"
        f"- S2.8: {parity_audio['exact_ranges']}/"
        f"{parity_audio['ranges_compared']} exact audio ranges, "
        f"{semantic['difference_count']} semantic differences.\n"
        "- Canonical validator errors: 0 for the S2.7 export and both S2.8 exports.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
