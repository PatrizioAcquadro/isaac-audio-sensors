# S2 phase closeout - Recording, replay, diagnostics, and operational GUI

Status: **PASSED** (2026-07-18). Entry revision `eecbab2` (post-S1 `main`,
v1.8.0 line); exit revision `fbe6ce7`, v1.9.0 line. Predecessor closeout
`docs/development/closeouts/S1_closeout.md` (S1 exit gate met at
`465b3eb`).

## Exit gate statement

**The S2 exit gate is met:** the same validated configuration operates
through the guided GUI and headless interfaces with proven semantic
equivalence (S2.8 live parity: 0 differences); recordings are atomic and
replayable (S2.2/S2.3: no injected fault ever exposes an unverified shard
as complete; replay preserves order, types, units, timestamps, and episode
boundaries with located errors on every corruption class); and
long-running SquadBot evidence capture has explicit resource and failure
behavior (S2.9: 30-minute endurance capture with 14.9 MiB peak RSS delta
against the frozen 128 MiB limit, zero unreported drops, a deliberately
in-flight shard proven unpublished, and a five-scenario reliability gate).

## Subphase closeouts (all passed)

| Subphase | Closeout | Key evidence |
| --- | --- | --- |
| S2.1 layout | `S2/s2_1_session_shard_layout.md` | spec frozen after 3 user review rounds (20 findings); byte-identical fixture; relocation-valid |
| S2.2 writers | `S2/s2_2_atomic_writers.md` | memory spec frozen pre-telemetry; first full run FAILED the gate (666-860 MiB) -> streaming fix -> rerun 1.9-8.5 MiB |
| S2.3 replay | `S2/s2_3_checked_replay.md` | 14-corruption located-error matrix; O(1) iteration |
| S2.4 validator | `S2/s2_4_validator_statistics.md` | canonical validator; 38 finding codes; 28k-frame deep validation at 6 MiB |
| S2.5 splits | `S2/s2_5_grouped_splits.md` | seed-identical plan hashes; leakage-free; plan-level fit/holdout |
| S2.6 controller | `S2/s2_6_validation_controller.md` | zero-drift extraction; GUI/headless identical; live regression passed |
| S2.7 GUI | `S2/s2_7_operational_gui.md` | live end-to-end: 6 stages, 201 frames, export 0 errors, invalid-state matrix |
| S2.8 parity | `S2/s2_8_headless_parity.md` | lossless config round-trip (fixed a real ordering bug); live GUI-vs-headless equal |
| S2.9 reliability | `S2/s2_9_reliability.md` | 5/5 reliability scenarios; endurance acceptance on attempt 6 with all prior evidence preserved |

## Final phase verification

- Pure battery: **738 passed, 0 failed**, 67 optional-dependency skips;
  ruff clean; version-sync OK at 1.9.0; `make build` distribution audit OK
  (sdist 326 files / wheel 113 files) after excluding the user's rig
  pre-CAD document (token audit) and the repo-only reference fixture
  (frozen audit bans media payloads) from the sdist.
- Live gates on Isaac Sim 6.0.1 / RTX 4090, all passed: extension UX
  regression (S2.6), guided workflow end-to-end (S2.7), GUI/headless
  parity (S2.8), 30-minute endurance capture (S2.9).
- Baseline S1 test count 504 -> 738 (+234 tests across the phase).

## Execution record

Claude orchestrated; 14 Codex CLI implementation runs (gpt-5.6-sol,
reasoning high, workspace-write, per-run write scopes) across S2.1-S2.9
plus 4 micro-fix runs; every diff reviewed line-by-line against a pinned
baseline; all gates executed independently by the orchestrator; one Codex
run blocked correctly on an impossible requirement (resolved by a
pre-implementation spec amendment); zero scope-drift incidents. Commits
`d8cee69..fbe6ce7` on `main`.

Genuine defects found by the phase's own gates and fixed with regression
coverage: session-length writer memory growth (S2.2 frozen gate),
config-summary profile-library ordering nondeterminism (S2.8 round-trip
gate), and unbounded warning/finding retention in streaming validation
(S2.9 endurance gate).

## Known limitations and next-phase input contract

- Real-scene frame diagnostics carry absolute-path strings, producing
  large (bounded, exactly-counted) warning totals; warning-only by the
  frozen layout contract. A producer-side diagnostics path policy is a
  candidate S3+ refinement.
- Simulator reset boundaries are not yet exposed by the tick contract, so
  recorded episodes carry no mid-episode reset markers (documented in
  workflow.py); S3.2 (time gaps and intra-window motion) is the natural
  owner.
- The reference fixture and rig documents are repo-only, excluded from the
  sdist under the frozen S1 audit; revisiting distribution policy belongs
  to an S6/P4 ADR.
- S3 entry: dynamic acoustics consume the S2.2 writer timing contract
  (S3.2 depends on it) and the canonical validator; the endurance harness
  and reliability scenarios are reusable gates for S3.9/S5.6.
