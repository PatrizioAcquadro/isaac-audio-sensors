"""Reevaluate preserved RTX Acoustic evidence without rerunning the provider."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ..geometry_acoustics_contract import evaluate_report
from .evaluation import reevaluate_nvidia_rtx_acoustic
from .reporting import write_candidate_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev1-root", type=Path, default=Path("build/validation/r9"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("IAS_R9_OUTPUT_ROOT", "build/validation/r9/rev2")),
    )
    args = parser.parse_args(argv)
    candidate_id = "nvidia_rtx_acoustic"
    rev1_candidate = args.rev1_root / candidate_id
    report_path = rev1_candidate / "r9.1-report.json"
    result = reevaluate_nvidia_rtx_acoustic(
        rev1_report=json.loads(report_path.read_text(encoding="utf-8")),
        rev1_measurements_reference=(
            f"build/validation/r9/{candidate_id}/measurements.json"
        ),
        rev1_provenance_reference=(
            f"build/validation/r9/{candidate_id}/provenance.json"
        ),
    )
    output_dir = args.output_root / candidate_id
    write_candidate_bundle(
        output_dir,
        report=result.report,
        measurements=result.measurements,
        arrays=result.arrays,
        provenance=result.provenance,
        log_lines=result.log_lines,
    )
    evaluation = evaluate_report(result.report)
    print(json.dumps(evaluation.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
