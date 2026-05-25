"""Generate a local live-evidence report from canonical smoke artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_EVIDENCE_DIR = Path("outputs/isaac_audio_sensors")
DEFAULT_MARKDOWN_OUT = DEFAULT_EVIDENCE_DIR / "live_validation_evidence.md"
DEFAULT_PDF_OUT = DEFAULT_EVIDENCE_DIR / "live_validation_evidence.pdf"

SIM_JSON = "isaac_sim_live_smoke.json"
SIM_FRAMES = "isaac_sim_live_smoke.frames.jsonl"
SIM_CONFIG = "isaac_sim_live_smoke.config.json"
LAB_GPU_JSON = "isaac_lab_live_smoke_gpu.json"
UX_JSON = "omniverse_extension_live_ux.json"
UX_FRAMES = "omniverse_extension_live_ux.frames.jsonl"
UX_CONFIG = "omniverse_extension_live_ux.config.json"
REPLICATOR_MANIFEST = (
    "omniverse_extension_live_ux.replicator/"
    "audio_sensor_replicator_manifest.json"
)


@dataclass(frozen=True, slots=True)
class ReportResult:
    """Paths written by the report generator."""

    markdown_path: Path
    pdf_path: Path | None
    pdf_status: str


def build_report(evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR) -> str:
    """Build a Markdown report from current evidence artifacts."""

    root = Path(evidence_dir)
    sim = _read_json(root / SIM_JSON)
    lab = _read_json(root / LAB_GPU_JSON)
    ux = _read_json(root / UX_JSON)
    sim_config = _read_json(root / SIM_CONFIG)
    ux_config = _read_json(root / UX_CONFIG)
    replicator = _read_json(root / REPLICATOR_MANIFEST)
    sim_frames = _read_jsonl(root / SIM_FRAMES)
    ux_frames = _read_jsonl(root / UX_FRAMES)

    lines: list[str] = [
        "# Live Validation Evidence Report",
        "",
        "This report is generated from local JSON/JSONL artifacts. It is a",
        "machine-local evidence record, not a portability promise and not a",
        "claim of official NVIDIA product status.",
        "",
        "## Source Artifacts",
        "",
        "| Artifact | Status | Modified UTC |",
        "| --- | --- | --- |",
    ]
    for relative_path in (
        SIM_JSON,
        SIM_FRAMES,
        SIM_CONFIG,
        LAB_GPU_JSON,
        UX_JSON,
        UX_FRAMES,
        UX_CONFIG,
        REPLICATOR_MANIFEST,
    ):
        artifact_path = root / relative_path
        lines.append(
            _row(
                f"`{artifact_path}`",
                _artifact_status(artifact_path),
                _artifact_mtime(artifact_path),
            )
        )

    lines.extend(
        [
            "",
            "## Runtime Facts",
            "",
            "| Evidence | Fact | Value |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(_runtime_rows("Isaac Sim smoke", sim))
    lines.extend(_lab_runtime_rows(lab))
    lines.extend(_runtime_rows("Omniverse extension UX", ux))

    lines.extend(
        [
            "",
            "## Passed Checks",
            "",
            "| Area | Evidence-backed result |",
            "| --- | --- |",
        ]
    )
    lines.extend(_passed_rows(sim, lab, ux, sim_frames, ux_frames, replicator))

    lines.extend(
        [
            "",
            "## Optional Or Environment-Dependent Items",
            "",
            "| Item | Current evidence |",
            "| --- | --- |",
        ]
    )
    lines.extend(_optional_rows(sim, ux, replicator))

    lines.extend(
        [
            "",
            "## Blockers And Limits",
            "",
            "| Item | Evidence-backed status |",
            "| --- | --- |",
        ]
    )
    lines.extend(_blocker_rows(sim, lab, ux, replicator))

    lines.extend(
        [
            "",
            "## Config And Trace Details",
            "",
            "| Artifact | Extracted facts |",
            "| --- | --- |",
            (
                f"| `{root / SIM_CONFIG}` | "
                f"stage mode `{_get(sim_config, 'stage.mode')}`, "
                f"array `{_get(sim_config, 'stage.array_prim_path')}`, "
                f"source `{_get(sim_config, 'stage.source_prim_path')}`, "
                "required backends "
                f"`{_json(_get(sim_config, 'sensor.required_backends'))}`, "
                "optional backends "
                f"`{_json(_get(sim_config, 'sensor.optional_backends'))}` |"
            ),
            (
                f"| `{root / UX_CONFIG}` | "
                f"schema `{_get(ux_config, 'schema_version')}`, "
                f"backend `{_get(ux_config, 'backend')}`, "
                f"array `{_get(ux_config, 'array.prim_path')}`, "
                f"source `{_get(ux_config, 'source.prim_path')}`, "
                f"overlay primitives `{_get(ux_config, 'overlay.primitive_count')}` |"
            ),
            (
                f"| `{root / SIM_FRAMES}` | "
                f"{len(sim_frames)} frames, schema versions "
                "`"
                f"{_json(_unique(item.get('schema_version') for item in sim_frames))}"
                "`, backends `"
                f"{_json(_unique(item.get('backend_id') for item in sim_frames))}` |"
            ),
            (
                f"| `{root / UX_FRAMES}` | "
                f"{len(ux_frames)} frames, schema versions "
                "`"
                f"{_json(_unique(item.get('schema_version') for item in ux_frames))}"
                "`, backends `"
                f"{_json(_unique(item.get('backend_id') for item in ux_frames))}` |"
            ),
            "",
            "## Declared Non-Promises",
            "",
            "- No sim-real calibration is claimed.",
            "- No real hardware benchmark is claimed.",
            "- No complete L3/L4 acoustic-fidelity runtime is claimed.",
            "- No realistic occlusion or material-acoustics model is claimed.",
            "- No SquadBot, Alex, ROS 2, or downstream release validation is claimed.",
            (
                "- The Omniverse extension is a reference UX, not an official "
                "NVIDIA extension."
            ),
        ]
    )

    return "\n".join(lines) + "\n"


def write_report(
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
    *,
    markdown_out: str | Path = DEFAULT_MARKDOWN_OUT,
    pdf_out: str | Path | None = DEFAULT_PDF_OUT,
) -> ReportResult:
    """Write Markdown and, when ReportLab is installed, a local PDF artifact."""

    markdown = build_report(evidence_dir)
    markdown_path = Path(markdown_out)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")

    pdf_path: Path | None = None
    pdf_status = "not requested"
    if pdf_out is not None:
        pdf_path = Path(pdf_out)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_status = _write_pdf(markdown, pdf_path)
        if not pdf_path.exists():
            pdf_path = None
    return ReportResult(
        markdown_path=markdown_path,
        pdf_path=pdf_path,
        pdf_status=pdf_status,
    )


def _runtime_rows(label: str, data: dict[str, Any]) -> list[str]:
    return [
        _row(label, "status", f"`{_get(data, 'status')}`"),
        (
            _row(
                label,
                "Isaac Sim app version field",
                (
                    f"`kit_app_version={_get(data, 'kit_app_version')}`, "
                    f"`isaacsim_version={_get(data, 'isaacsim_version')}`"
                ),
            )
        ),
        _row(
            label,
            "Kit build",
            f"`{_get(data, 'kit_build_version') or _get(data, 'kit_version')}`",
        ),
        _row(label, "Python executable", f"`{_get(data, 'python_executable')}`"),
        _row(label, "Python version", f"`{_get(data, 'python_version')}`"),
        _row(
            label,
            "Torch/CUDA",
            f"`torch={_get(data, 'torch_version')}`, "
            f"`gpu_visible={_get(data, 'gpu_visible')}`",
        ),
        (
            _row(
                label,
                "NVIDIA device/driver",
                (
                    f"`devices={_json(_get(data, 'cuda_device_names'))}`, "
                    f"`nvidia-smi={_get(data, 'nvidia_smi.stdout')}`"
                ),
            )
        ),
    ]


def _lab_runtime_rows(data: dict[str, Any]) -> list[str]:
    return [
        _row("Isaac Lab GPU", "status", f"`{_get(data, 'status')}`"),
        _row(
            "Isaac Lab GPU",
            "Isaac Lab version",
            f"`{_get(data, 'runtime.isaaclab_version')}`",
        ),
        _row(
            "Isaac Lab GPU",
            "Isaac Sim version",
            f"`{_get(data, 'runtime.isaac_sim_version')}`",
        ),
        _row(
            "Isaac Lab GPU",
            "Kit build",
            f"`{_get(data, 'runtime.kit_build_version')}`",
        ),
        _row(
            "Isaac Lab GPU",
            "Python executable",
            f"`{_get(data, 'python_executable')}`",
        ),
        _row("Isaac Lab GPU", "CUDA device", f"`{_get(data, 'device')}`"),
        _row(
            "Isaac Lab GPU",
            "NVIDIA device/driver",
            (
                f"`{_get(data, 'cuda.torch_cuda_device_name')}`, "
                f"`{_get(data, 'cuda.nvidia_smi_stdout')}`"
            ),
        ),
        _row(
            "Isaac Lab GPU",
            "Torch/CUDA",
            (
                f"`torch={_get(data, 'cuda.torch_version')}`, "
                f"`cuda_available={_get(data, 'cuda.torch_cuda_available')}`"
            ),
        ),
    ]


def _passed_rows(
    sim: dict[str, Any],
    lab: dict[str, Any],
    ux: dict[str, Any],
    sim_frames: list[dict[str, Any]],
    ux_frames: list[dict[str, Any]],
    replicator: dict[str, Any],
) -> list[str]:
    entity_tensor_device = _get(
        lab,
        "entity_binding.entity_scene_evidence.tensor_scene_device",
    )
    return [
        _row(
            "Isaac Sim smoke",
            (
                f"status `{_get(sim, 'status')}`; `SimulationApp` bootstrap "
                f"`{_get(sim, 'simulation_app_bootstrap')}`; "
                f"`pxr_imported={_get(sim, 'pxr_imported')}`; "
                f"`omni_imported={_get(sim, 'omni_imported')}`"
            ),
        ),
        _row(
            "Isaac Sim USD binding",
            (
                f"selected array `{_get(sim, 'selected_array.prim_path')}` / "
                f"`{_get(sim, 'selected_array_id')}` and source "
                f"`{_get(sim, 'selected_source.prim_path')}` / "
                f"`{_get(sim, 'selected_source.source_id')}`"
            ),
        ),
        _row(
            "Isaac Sim backends",
            (
                f"backend statuses `{_json(_get(sim, 'backend_statuses'))}`; "
                "frame counts "
                f"`{_json(_get(sim, 'jsonl_backend_frame_counts'))}`"
            ),
        ),
        _row(
            "Isaac Sim JSONL",
            (
                f"evidence reports `{_get(sim, 'jsonl_frame_count')}` frames; "
                f"parsed `{len(sim_frames)}` frames from `{SIM_FRAMES}`"
            ),
        ),
        _row(
            "Isaac Sim debug evidence",
            (
                f"`{_get(sim, 'debug_primitive_count')}` primitives with kinds "
                f"`{_json(_get(sim, 'debug_primitive_kinds'))}` and diagnostics "
                f"namespaces `{_json(_get(sim, 'diagnostics_namespaces'))}`"
            ),
        ),
        _row(
            "Isaac Lab classes",
            (
                f"`classes_real={_get(lab, 'class_resolution.classes_real')}`, "
                "`cfg_is_sensorbasecfg_subclass="
                f"{_get(lab, 'cfg_is_sensorbasecfg_subclass')}`, "
                "`sensor_is_sensorbase_subclass="
                f"{_get(lab, 'sensor_is_sensorbase_subclass')}`, "
                "`fallback_classes_used_in_lab="
                f"{_get(lab, 'fallback_classes_used_in_lab')}`"
            ),
        ),
        _row(
            "Isaac Lab CUDA buffers",
            (
                f"`device={_get(lab, 'device')}`, shapes "
                f"`{_shape_summary(lab)}`, devices "
                f"`{_json(_get(lab, 'buffer_device_map'))}`"
            ),
        ),
        _row("Isaac Lab selected env checks", _selected_check_summary(lab)),
        _row(
            "Isaac Lab stage binding",
            (
                f"`stage_kind={_get(lab, 'stage_kind')}`, "
                "`semantic_discovery="
                f"{_get(lab, 'stage_auto_binding.semantic_discovery')}`, "
                "`stage_ran_inside_kit_lab="
                f"{_get(lab, 'stage_auto_binding.stage_ran_inside_kit_lab')}`, "
                "env 1 bearing changed "
                f"`{_get(lab, 'stage_auto_binding.first_env_1_bearing_deg')}` "
                f"to `{_get(lab, 'stage_auto_binding.moved_env_1_bearing_deg')}`"
            ),
        ),
        _row(
            "Isaac Lab entity binding",
            (
                "`bearing_changed="
                f"{_get(lab, 'entity_binding.bearing_changed')}`, "
                "env 1 bearing changed "
                f"`{_get(lab, 'entity_binding.first_env_1_bearing_deg')}` "
                f"to `{_get(lab, 'entity_binding.moved_env_1_bearing_deg')}`, "
                f"tensor scene device `{entity_tensor_device}`"
            ),
        ),
        _row(
            "Isaac Lab observation surface",
            (
                f"RL keys `{_json(_get(lab, 'observation_surface.rl_keys'))}`; "
                "example status "
                f"`{_get(lab, 'rl_observation_example.status')}` on "
                f"`{_get(lab, 'rl_observation_example.device')}`"
            ),
        ),
        _row(
            "Extension UX smoke",
            (
                f"status `{_get(ux, 'status')}`; extension manager "
                f"`{_get(ux, 'kit_extension_manager.status')}`; enabled id "
                "`"
                f"{_get(ux, 'kit_extension_manager.verification.enabled_extension_id')}"
                "`"
            ),
        ),
        _row(
            "Extension workflow",
            (
                f"`{_workflow_pass_count(ux)}` workflow steps passed; "
                f"stage mode `{_get(ux, 'stage_mode')}`; selection API "
                f"`{_json(_get(ux, 'selection_api'))}`"
            ),
        ),
        _row(
            "Extension frame export",
            (
                f"evidence reports `{_get(ux, 'jsonl_frame_count')}` JSONL "
                f"frames with backends `{_json(_get(ux, 'jsonl_backend_ids'))}`; "
                f"parsed `{len(ux_frames)}` frames from `{UX_FRAMES}`"
            ),
        ),
        _row(
            "Extension overlays",
            (
                f"`{_get(ux, 'overlay_primitive_count')}` primitives with "
                f"kinds `{_json(_get(ux, 'overlay_primitive_kinds'))}`"
            ),
        ),
        _row(
            "Replicator writer",
            (
                f"runtime `{_get(replicator, 'runtime_module')}`, writer "
                f"registered `{_get(replicator, 'writer_registered')}`, "
                f"write count `{_get(replicator, 'write_count')}`, flush count "
                f"`{_get(replicator, 'flush_count')}`, stopped "
                f"`{_get(replicator, 'stopped')}`"
            ),
        ),
    ]


def _optional_rows(
    sim: dict[str, Any],
    ux: dict[str, Any],
    replicator: dict[str, Any],
) -> list[str]:
    return [
        _row(
            "L2 `room_acoustics`",
            (
                f"`{_get(sim, 'room_acoustics_status')}`; reason "
                f"`{_get(sim, 'room_acoustics_skip_reason')}`"
            ),
        ),
        _row(
            "Omniverse Replicator",
            (
                "optional extension path; runtime available "
                f"`{_get(replicator, 'runtime_available')}`, writer registered "
                f"`{_get(replicator, 'writer_registered')}`"
            ),
        ),
        _row(
            "Replicator annotator registration",
            (
                f"`{_get(replicator, 'annotator_status')}`; writer path remains "
                "the passed evidence path"
            ),
        ),
        _row(
            "Viewport screenshot",
            (
                f"`{_get(ux, 'screenshot.status')}`; reason "
                f"`{_get(ux, 'screenshot.reason')}`"
            ),
        ),
        _row(
            "Live Isaac gates",
            (
                "environment-dependent; require a user-managed Isaac runtime, "
                "GPU visibility, and accepted EULA"
            ),
        ),
    ]


def _blocker_rows(
    sim: dict[str, Any],
    lab: dict[str, Any],
    ux: dict[str, Any],
    replicator: dict[str, Any],
) -> list[str]:
    blocker = _get(lab, "entity_binding.entity_scene_evidence.blocker_summary")
    probe_status = _get(
        lab,
        "entity_binding.entity_scene_evidence.real_lab_rigid_object_probe_status",
    )
    return [
        _row(
            "Isaac Sim optional room backend",
            (
                f"`{_get(sim, 'room_acoustics_status')}` because "
                f"`{_get(sim, 'room_acoustics_skip_reason')}`"
            ),
        ),
        _row(
            "Full real Isaac Lab `InteractiveScene`/`RigidObject` probe",
            f"`{probe_status}`: {blocker}",
        ),
        _row(
            "Replicator annotator API",
            f"`{_get(replicator, 'annotator_status')}`",
        ),
        _row(
            "Headless screenshot capture",
            f"`{_get(ux, 'screenshot.status')}`: {_get(ux, 'screenshot.reason')}",
        ),
    ]


def _row(*columns: object) -> str:
    return "| " + " | ".join(str(column) for column in columns) + " |"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    with path.open(encoding="utf-8") as file_obj:
        return json.load(file_obj)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file_obj:
        for line in file_obj:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "`missing`"
    if path.suffix == ".json":
        try:
            data = _read_json(path)
        except json.JSONDecodeError as exc:
            return f"`invalid json: {exc}`"
        status = data.get("status")
        if status is None and "runtime_available" in data:
            status = f"runtime_available={data['runtime_available']}"
        return f"`{status}`" if status is not None else "`present`"
    if path.suffix == ".jsonl":
        try:
            return f"`present: {len(_read_jsonl(path))} records`"
        except json.JSONDecodeError as exc:
            return f"`invalid jsonl: {exc}`"
    return "`present`"


def _artifact_mtime(path: Path) -> str:
    if not path.exists():
        return "`missing`"
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return f"`{timestamp.isoformat(timespec='seconds').replace('+00:00', 'Z')}`"


def _get(data: Any, dotted_path: str, default: Any = "unavailable") -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _unique(values) -> list[Any]:
    return sorted({value for value in values if value is not None}, key=str)


def _shape_summary(data: dict[str, Any]) -> str:
    shapes = {
        "event_presence": _get(data, "event_presence_shape"),
        "bearing_deg": _get(data, "bearing_deg_shape"),
        "confidence": _get(data, "confidence_shape"),
        "sector_onehot": _get(data, "sector_onehot_shape"),
        "per_mic_rms": _get(data, "per_mic_rms_shape"),
        "ambiguity_mask": _get(data, "ambiguity_mask_shape"),
    }
    return _json(shapes)


def _selected_check_summary(data: dict[str, Any]) -> str:
    checks = _get(data, "selected_env_checks", default={})
    if not isinstance(checks, dict):
        return "`unavailable`"
    summary: list[str] = []
    for area, area_checks in checks.items():
        if not isinstance(area_checks, dict):
            continue
        passed = [
            name
            for name, check_data in area_checks.items()
            if isinstance(check_data, dict) and check_data.get("passed") is True
        ]
        summary.append(f"{area}: {', '.join(sorted(passed))}")
    return "; ".join(summary) if summary else "`unavailable`"


def _workflow_pass_count(data: dict[str, Any]) -> str:
    steps = _get(data, "workflow_steps", default=[])
    if not isinstance(steps, list):
        return "0/0"
    passed = sum(1 for step in steps if step.get("status") == "passed")
    return f"{passed}/{len(steps)}"


def _write_pdf(markdown: str, pdf_path: Path) -> str:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:
        return f"missing PDF dependency: {exc.name}"

    pdf = canvas.Canvas(str(pdf_path), pagesize=letter)
    page_width, page_height = letter
    margin = 0.55 * inch
    y = page_height - margin

    def new_page() -> None:
        nonlocal y
        pdf.showPage()
        y = page_height - margin

    for raw_line in markdown.splitlines():
        if not raw_line:
            y -= 8
            if y < margin:
                new_page()
            continue
        font = "Helvetica"
        size = 8
        line = raw_line
        if raw_line.startswith("# "):
            font = "Helvetica-Bold"
            size = 15
            line = raw_line[2:]
        elif raw_line.startswith("## "):
            font = "Helvetica-Bold"
            size = 12
            line = raw_line[3:]
        wrapped = textwrap.wrap(
            line,
            width=108 if size <= 8 else 82,
            replace_whitespace=False,
            drop_whitespace=True,
        ) or [""]
        for segment in wrapped:
            pdf.setFont(font, size)
            pdf.drawString(margin, y, segment[:180])
            y -= size + 3
            if y < margin:
                new_page()
    pdf.save()
    return "generated with reportlab"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN_OUT))
    parser.add_argument("--pdf-out", default=str(DEFAULT_PDF_OUT))
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Only write the Markdown report source.",
    )
    args = parser.parse_args(argv)

    result = write_report(
        args.evidence_dir,
        markdown_out=args.markdown_out,
        pdf_out=None if args.no_pdf else args.pdf_out,
    )
    print(f"[live-evidence-report] wrote {result.markdown_path}")
    print(f"[live-evidence-report] pdf status: {result.pdf_status}")
    if result.pdf_path is not None:
        print(f"[live-evidence-report] wrote {result.pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
