# S2.6 closeout - Shared validation controller

Status: **passed** (2026-07-17). Entry revision `3f7632c`; predecessor
closeouts S2.1-S2.5 (dataset chain) — S2.6 itself depends on S1.2/S1.3.

## Scope delivered

- New import-safe package `src/isaac_audio_sensors/isaac/validation/`
  (`results.py`, `checks.py`, `controller.py`): stage, configuration,
  dependency, device, path, geometry, time, and calibration-adjacent checks
  extracted from the 3,461-line GUI `ExtensionController` with stable
  `check_id`s and byte-identical user-facing messages;
  `ValidationReport.raise_first()` preserves the GUI's
  `ExtensionActionError` raise semantics and check order. Zero
  `omni`/`pxr`/`carb`/`torch` imports (proven by an import-sandbox
  subprocess test).
- GUI controller methods are delegation shims; scattered inline predicates
  (stage-present, selection, attach-target, abs-path, presets, profiles,
  rig profiles) route through the shared package.
- Capability state (Run B): frozen `CapabilityState` snapshots over
  `discover_capabilities` with generation tracking, lazy refresh-on-access,
  explicit `invalidate(reason)`, never-refreshed access raising, and
  `validate_backend_available` that never answers from a stale snapshot.
  GUI wiring at existing event paths only: startup, USD stage open/close
  (existing subscription), source/array attach/detach, `configure_sensor`,
  and config-summary apply.

## Gate results

Evidence: `outputs/isaac_audio_sensors/S2/S2.6/{controller_gate.json,
live_ux_regression.json}`.

- Pure: 682 passed / 0 failed / 67 optional-dependency skips; ruff clean;
  GUI suites pass UNMODIFIED; 25 validation-controller tests including
  GUI-vs-headless identical-results across the full check matrix and the
  dependency-flip/stale-state guards.
- Live: `make live-omniverse-extension-ux` on real Isaac Sim 6.0.1 passed
  (status `passed` in the evidence JSON) — no GUI behavior change after
  extraction and capability wiring.

## Execution notes

Two Codex runs (gpt-5.6-sol, high), both exactly in scope — the
highest-drift-risk subphase of the phase completed with zero drift;
operational lifecycle guards (missing waveform, unconfigured sensor, no
latest frame, inactive Replicator) were intentionally left inline as they
are runtime-lifecycle, not configuration validation, per the Run A report.

## Input contract for S2.7

The guided GUI builds its Validate stage on `ValidationController` reports
(findings carry `field` hints for inline error mapping) and its dependency
gating on `CapabilityState`; headless S2.8 consumes the identical services.

<!-- BEGIN GENERATED S2 REVIEW REMEDIATION -->

## S2 review remediation (regenerated)

Explicit compute-device and calibration-profile checks now execute through the shared
controller. GUI and headless results are identical, and replacement/deletion plus
device-change tests prove that neither check answers from stale state. Evidence:
`outputs/isaac_audio_sensors/S2/S2.review/remediation_gate.json`.

<!-- END GENERATED S2 REVIEW REMEDIATION -->
