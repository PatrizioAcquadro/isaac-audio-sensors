# S2.7 closeout - Operational guided GUI

Status: **passed** (2026-07-17). Entry revision `b467c87`; predecessors
S2.2-S2.6 closeouts.

## Scope delivered (three Codex runs, commits d6aef07, d1aaeda, 2a583d7)

- `extension_ui/workflow.py`: import-safe `GuidedWorkflow` — six ordered
  stages (`Setup -> Validate -> Run -> Inspect -> Record -> Export`),
  per-stage gating and blocked-finding records, safe presets ("XVF3800
  quad demo" from the demo config; "Minimal single source") applied through
  existing configuration paths, finding->field inline-issue indexing, and a
  data-driven recovery-action registry.
- Run: drives the existing sensor lifecycle; frame observation completes
  the stage; stop regresses with a finding. Inspect: instrument summaries
  plus an explicit human mark-inspected action (inspection is judgment, by
  design). Record: tick frames stream into `SessionRecorder` (producer
  constructs stored frames with empty `waveform_paths` per layout §4.5)
  with live progress (frames/drops/shards/bytes), token cancellation to a
  finalized-incomplete session with a retry recovery, and stop-and-finalize
  gated on the canonical validator. Export: portable relocation +
  revalidation of the copy, optional TVT split plan (single-group sessions
  skip with a note), manifest/marker-derived output inventory.
- `INVALID_STATE_MATRIX`: every planted invalid state across all six
  stages maps to an actionable field or recovery action; tests iterate the
  matrix generically.
- `scripts/live_guided_workflow_gate.py` + `make live-guided-workflow`.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.7/guided_workflow_gate.json`
(+ exported session + screenshot under the same root).

- Pure: 716 passed / 0 failed; ruff clean; GUI suites unmodified across
  all three runs; 34 guided-workflow tests.
- **Live end-to-end on real Isaac Sim 6.0.1 (RTX 4090): passed.** Full
  stage progression; 201 frames recorded, 0 drops; export validated with
  0 errors (`passed_with_warnings`); 3 planted invalid states exercised
  live (absent stage, invalid backend, cancel-and-retry) all passed;
  1 screenshot captured.
- Known characteristic: the real scene's frame diagnostics contain
  absolute asset paths, producing 3,015 per-frame portability *warnings* —
  warning-only by frozen contract (layout spec §4.5/§8; diagnostics are
  excluded from the portability promise). A future dedup/aggregation of
  repeated warnings is a UX nicety, not a defect.

A user can configure a valid scene, capture frames, and export a
validator-clean dataset entirely through the guided workflow without
source-code intervention.

## Input contract for S2.8

Every guided operation has a controller-level API (`guided_*`) independent
of `omni.ui`; S2.8 must provide config/CLI equivalents for the same
operations and prove semantic equivalence of GUI-driven and headless
outputs from one normalized configuration after documented path
normalization.
