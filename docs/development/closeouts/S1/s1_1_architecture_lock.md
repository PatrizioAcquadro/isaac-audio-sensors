# S1.1 architecture lock closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.1` - Architecture lock |
| Closeout date | 2026-07-16 |
| Entry revision | `74a4ed6` (plus baseline repair `1534ce8`) |
| Predecessor input | `docs/development/closeouts/S0/s0_6_dual_acceptance_lock.md` |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.1 row |
| Governing plan | `docs/final_sensor_development_plan.md`, Sections 4, 5, 6.4, 10 |
| Result | **Pass** |

## Scope

This closeout records the production, review, revision, and approval of the
S1.1 architecture-lock ADR at
`docs/development/specs/s1_architecture_lock.md`. It performs no S1.2-S1.8
implementation and promotes no prospective enforcement artifact to an
existing one.

## Execution record

- The ADR was authored and twice revised by bounded Codex CLI runs
  (`codex` 0.144.4, model `gpt-5.6-sol`, reasoning effort `high`,
  `--ignore-user-config`, `workspace-write` sandbox, single-file write scope,
  exit 0 on every run), orchestrated and diff-reviewed by Claude.
- Revision 2 applied seven user review requirements: a private versioned
  acoustic-pack installation root; a pre-import `pack_manifest.json`
  validation gate; origin-aware packaged-mode capability discovery; a
  hardened S1.6 clean-environment definition (`PYTHONNOUSERSITE=1`, sanitized
  `PYTHONPATH`/`PYTHONHOME`/`PIP_*`, `site.ENABLE_USER_SITE` verification,
  recorded import origins); an explicit fail-closed packaged/developer mode
  sentinel; a single authoritative version source (`pyproject.toml
  [project].version`) with a complete derived-surface policy; and the pin of
  the official `pyroomacoustics-0.10.1-cp312-cp312-manylinux_2_27_x86_64.
  manylinux_2_28_x86_64.whl` (SHA-256
  `c1b1077cfcafed9775d1b826dbbaf25fb4090aa95d21e9bc6dac795f88e8875c`) with
  removal of any local-build exception.
- Revision 3 applied five further user requirements to Decision 6: the
  `host_requirements` / `pack_distributions` manifest split with Kit-owned
  `numpy==2.5.0` origin validation; installer flags
  `--no-deps --no-index --require-hashes` against the bundled wheelhouse
  only; a pre-activation `sys.modules` provenance-purity rejection; staged,
  hash-verified, atomically renamed, immutable version directories with
  overwrite refusal; and three named required S1.5 test scenarios.

## Verification

- Review checklist (all pass-criteria and revision mappings):
  `outputs/isaac_audio_sensors/S1/S1.1/adr_review_checklist.md`.
- Runtime facts probed and recorded:
  `outputs/isaac_audio_sensors/S1/S1.1/environment.txt`,
  `isaac_python_version.txt` (Kit Python 3.12.13, cp312),
  `isaac_numpy_probe.txt` (NumPy 2.5.0),
  `pyroomacoustics_official_wheel_probe.txt` (PyPI probe, 2026-07-16).
- Gates run against the worktree containing the final ADR: `make test`
  (386 passed, 67 skipped), `make lint` (clean), `make build` plus
  distribution audit (OK; ADR and `docs/evidence/` verified absent from the
  sdist), `git diff --check` (clean).
- Negative architecture checks: residual-concept scan for the replaced
  policies (five-site version list, marker-presence mode detection,
  reference-host local wheel builds) returned zero hits.

## Approval

The user reviewed the ADR through two revision rounds and recorded approval
of revision 3 on 2026-07-16 in the orchestration session. Per the ADR status
clause, this recorded approval authorizes S1.2-S1.8 implementation, beginning
with the `1.8.0` version bump commit that Decision 7 places immediately after
approval.

## Baseline repair recorded in passing

Concurrent user-added machine-local evidence under `docs/evidence/` tripped
the public-file token scan and would have shipped in the sdist. Commit
`1534ce8` excludes `docs/evidence/` from the sdist and the hygiene scan,
mirroring the existing `docs/development/` exclusion. No user content was
modified.

## Limitations and next input contract

- Every enforcement artifact named by the ADR remains prospective; the ADR
  and this closeout do not claim any S1.2-S1.8 gate.
- Next subphase input (S1.2): the approved ADR, the frame-v1 rules, plan
  Sections 4.2-4.5, and the S0.1 status audit.
