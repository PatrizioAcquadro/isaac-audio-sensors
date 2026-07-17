# S2.8 closeout - Headless and config parity

Status: **passed** (2026-07-17). Entry revision `b6de09a`; predecessor
closeout `docs/development/closeouts/S2/s2_7_operational_gui.md`.

## Scope delivered

- `isaac/headless_workflow.py`: `HeadlessGuidedSession` driving the
  identical `ExtensionController` guided API (Setup through Export) with
  no UI object; every Stage 1 guided operation is reachable headlessly.
- CLI `guided run-headless <config> --session-dir --export-dir
  [--frames|--seconds] [--json]`; outside Isaac it reports a located Setup
  error (the run stage genuinely requires a USD stage — no synthetic
  production stage path was invented); inside Isaac it runs fully.
- Lossless configuration round-trip: `export -> import -> export` is
  byte-identical for defaults, both presets, and a fully-populated state.
  Fixes required and landed: canonical ordering of sound and
  microphone-rig profile libraries (a real pre-existing byte-identity
  bug) and serialization of the guided recording/split settings.
- `scripts/compare_gui_headless_sessions.py`: semantic session diff with
  every normalized field documented with its reason (wall-clock
  provenance, host device, dataset id, config hash/paths, session-root
  substrings, absolute-path diagnostics, derived hashes/sizes, stored
  tails); exact comparison of schema, profile, convention, episodes,
  shard tiling, frames, timestamps, detections, attributed sample ranges,
  channel order, sample rate, dtype, split policy, and decoded attributed
  audio.
- `scripts/live_headless_parity_gate.py` + `make live-headless-parity`.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.8/parity_gate.json`.

- Pure: 727 passed / 0 failed; ruff clean; GUI + guided suites unmodified;
  11 parity tests; self-comparison of the real S2.7 export equal across
  201 frames.
- **Live on Isaac Sim 6.0.1: passed** — one normalized configuration run
  through the GUI-path guided workflow and through `HeadlessGuidedSession`;
  semantic diff: equal, 0 differences.

## Execution notes

One Codex run (gpt-5.6-sol, high), in scope (controller.py touched only
for the authorized round-trip serialization fixes, itemized above).

## Input contract for S2.9

Headless capture from configuration is the endurance-run vehicle. S2.9
ratifies the frozen representative capture definition (layout spec
Appendix A + the frozen S2.2 memory rule), executes >= 30 minutes of
continuous headless capture, and closes the phase on the canonical
validator plus telemetry.
