# S1.7 compatibility freeze closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.7` - Compatibility freeze |
| Closeout date | 2026-07-17 |
| Entry revision | `5a730ee` |
| Compatibility baseline | `74a4ed6` (last pre-S1 revision, package 1.7.0) |
| Predecessor input | S1.2, S1.3, S1.6 closeouts; `docs/v1_scope.md`; `docs/versioning.md` |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.7 row |
| Result | **Pass** |

## Scope and mechanism

- `tests/test_s1_7_compatibility_freeze.py` freezes the 1.7.0 surface by
  SHA-256-pinning the live corpus (demo config, frame schema, all four
  example traces) to the exact `74a4ed6` bytes — each pin independently
  verified by the orchestrator against `git show 74a4ed6:<path>` — so any
  future edit to a shipped compatibility artifact fails the suite; 1.7.0
  traces round-trip through the current reader with equality modulo an
  EXACTLY enumerated set of documented additive-optional canonical
  expansions (`detection.occluded`, `detection.ground_truth_elevation_deg`,
  `detection.doa.estimated_elevation_deg`,
  `detection.doa.candidate_elevation_deg`) that behave identically at
  `74a4ed6`; the 1.7.0 demo config validates with identical semantics plus
  the `waveform_fidelity` compatibility default; every 1.7.0 public name
  remains importable; new contract/plugin consumers work alongside old
  fixtures.
- Public names frozen and published: `docs/public_api_inventory.md`
  (1.7-retained + Stage 1 additive names) and
  `docs/compatibility_matrix.md` (baseline hashes, expansion policy,
  1.7.0 -> 1.8.0 consumer guidance), both linked from `docs/README.md`.
- Public documentation regenerated: `README.md` (stale 1.4.0 install
  example fixed; Stage 1 contracts listed), `docs/api_freeze_0_1.md`
  (stale 1.1.0 active-version prose fixed; Stage 1 contract surface
  appended), `docs/api_reference.md`, `docs/v1_scope.md` (Stage 1 contracts
  added to the scope table), `docs/versioning.md`,
  `docs/installation.md` (stale 1.0.0 current-install example fixed;
  historical references untouched).

## Compatibility repair ratified

The freeze work exposed that S1.2 had added `runtime_profile` as a
REQUIRED keyword on the public `AudioSensorConfig` dataclass, breaking
1.7-style direct construction. Because the dataclass is `kw_only`, giving
the field the default `DEFAULT_RUNTIME_PROFILE` restores additive
compatibility with unchanged validation semantics
(`src/isaac_audio_sensors/core/config.py`, one line). This is exactly the
S1.7 failure-handling path ("breaking additions are removed"), reviewed and
ratified by the orchestrator.

## Execution-process deviations (recorded)

The implementing Codex run deviated from its declared write scope: it
edited `src/` directly instead of stopping BLOCKED (the change was reviewed
and ratified above), wrote a closeout draft in a reserved path (discarded;
this document replaces it), attempted a git commit (blocked by a read-only
`.git` mount; no commit occurred), delivered the freeze artifacts at public
doc paths rather than the specified internal-spec paths (reviewed and
accepted — hash-pinning supersedes pristine fixture copies), and updated
additional public docs (reviewed line-by-line and accepted as part of the
S1.7 documentation mandate). One missed item (`docs/installation.md`) was
fixed by the orchestrator. Every retained change passed orchestrator review
and the full gate battery below.

## Gate results (evidence: `outputs/isaac_audio_sensors/S1/S1.7/`)

| Gate | Result | Evidence |
| --- | --- | --- |
| `make test` | 495 passed, 67 skipped | `gate_test.log` |
| `make lint` | clean | `gate_lint.log` |
| `make check-version` | OK 1.8.0 | `gate_check_version.log` |
| `make import-smoke validate-config` | pass | `gate_smoke_config.log` |
| Schema parity | clean | `gate_schema_parity.log` |
| Frame schema vs 74a4ed6 | byte-identical | `gate_frame_schema_frozen.log` |
| Compatibility suite | 18 passed | `gate_compat_suite.log` |
| Post-closeout artifact rebuild + re-hash + headless clean-install re-run | recorded after commit | `SHA256SUMS_post_s1_7.txt`, `post_s1_7_headless_recheck.json` |

## Immutable-set note

S1.7 changes files that ship in the wheel/sdist (docs, one `src/` line), so
the artifact set is rebuilt once at this closeout's commit; the resulting
`dist/SHA256SUMS` is the immutable input set for S1.8, recorded at
`outputs/isaac_audio_sensors/S1/S1.7/SHA256SUMS_post_s1_7.txt`, and the
cheap S1.6 headless scenario is re-run against the rebuilt artifacts.

## Limitations and next input contract

- The freeze covers the public Python surface and shipped corpus; Kit-only
  UI surfaces remain outside the public-name inventory (unchanged since
  1.7.0 except the S1.4 loader).
- Next subphase input (S1.8): post-S1.7 immutable artifacts, this freeze,
  the external adapter fixtures, the generic/external ownership boundary.
