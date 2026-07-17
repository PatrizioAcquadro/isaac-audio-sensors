# S1.3 plugin contracts closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.3` - Plugin contracts |
| Closeout date | 2026-07-17 |
| Entry revision | `a23a395` |
| Predecessor input | `docs/development/closeouts/S1/s1_1_architecture_lock.md`, `s1_2_public_contracts.md` |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.3 row |
| Design note | `docs/development/specs/s1_plugin_contracts.md` |
| Result | **Pass** |

## Scope

Implements plan Section 4.6: `src/isaac_audio_sensors/core/plugins/`
(`protocols.py`, `declarations.py`, `registry.py`) with import-safe
`PropagationBackend`, `DoaEstimator`, and `AudioFeatureExtractor` protocols,
frozen fail-closed `PluginDeclaration` capability records (id, kind, fidelity
level, required dependencies, devices, runtime profiles, determinism, output
contract), and a validating `PluginRegistry` with a populated default
registry. `get_backend` is now a thin wrapper over the registry through
`instantiate_registered`, which preserves the historical behavior exactly
(unknown-id error text unchanged; optional room dependencies still checked at
`simulate`, not construction). Built-ins registered: `geometry_only`,
`tdoa_synthetic`, `room_acoustics`, `room_acoustics_srp` (propagation);
`tdoa_least_squares`, `srp_phat` (DOA, thin adapters over the existing
functions with zero computation change). No core `AudioFeatureExtractor`
ships — an explicit non-claim; the protocol and registry validation are
exercised by a test-local fake.

## Execution record

One bounded Codex CLI run (`codex` 0.144.4, `gpt-5.6-sol`, reasoning `high`,
`--ignore-user-config`, `workspace-write`), orchestrated and diff-reviewed by
Claude, including a specific review of the `get_backend` rewire semantics.

## Gate results (evidence: `outputs/isaac_audio_sensors/S1/S1.3/`)

| Gate | Result | Evidence |
| --- | --- | --- |
| `make test` | 445 passed, 67 skipped | `gate_test.log` |
| `make lint` | clean | `gate_lint.log` |
| Focused backend/plugin suite | 56 passed, 25 skipped (optional-dep skips) | `gate_focused_backends.log` |
| Schema/fixture no-op parity | clean | `gate_noop_parity.log` |
| `make build` + distribution audit | OK (sdist 263, wheel 95, 1.8.0) | `gate_build_audit.log` |
| Registry inventory + import safety | 4 propagation / 2 DOA / 0 extractor; `pyroomacoustics` not imported at import time | `registry_inventory.log` |

Acceptance mapping (S1.3 row): duplicate ids, unknown kinds/ids, missing
dependencies at resolve, unsupported device/profile combinations, invalid
output shapes, false determinism declarations, and invalid declaration
fields all reject with actionable errors (`tests/test_backend_plugins.py`
rejection matrix). Existing backends register without semantic drift:
seeded no-drift tests compare `frame_to_trace_dict` output from direct
construction vs registry-backed `get_backend` for geometry and TDOA paths —
identical; existing backend suites pass unmodified.

## Limitations and next input contract

- Room-backend no-drift execution is availability-gated in the pure
  environment (no `pyroomacoustics`); construction-path equivalence is
  proven, waveform-path equivalence is exercised wherever the optional
  dependency exists (S1.6 clean-install and pack scenarios re-exercise it).
- `resolve()` is the capability-checked path for new consumers; existing
  code keeps `get_backend` semantics.
- Next subphase input (S1.4): approved ADR (Decisions 7, 8), S0.1 Partial
  distribution finding, shared package source.
