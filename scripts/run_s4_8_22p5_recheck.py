#!/usr/bin/env python3
"""Run one additive engineering-only S4.8 22.5-degree recheck."""

from __future__ import annotations

try:
    from scripts import run_s4_8_bias_disambiguation as workflow
except ModuleNotFoundError:
    import run_s4_8_bias_disambiguation as workflow

workflow.DEFAULT_CAMPAIGN_ROOT = (
    workflow.LOCAL_ROOT / "s4_8_bias_disambiguation_22p5_recheck_v2"
)
workflow.TAKE_BEARINGS_DEG = (22.5,)
workflow.PROTOCOL_ID_PREFIX = "s4_8_additive_22p5_recheck_v2"
workflow.PI_REMOTE_CAMPAIGN_NAME = "bias_disambiguation_22p5_recheck_v2"
workflow.SOURCE_PATHS = (
    *workflow.SOURCE_PATHS,
    "scripts/run_s4_8_22p5_recheck.py",
)


if __name__ == "__main__":
    raise SystemExit(workflow.main())
