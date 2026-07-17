# S0.6 dual acceptance lock closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S0.6` - Dual acceptance lock |
| Closeout date | 2026-07-16 |
| Entry revision | `b9ba7a4` |
| Predecessor input | `docs/development/closeouts/S0/s0_2_pure_baseline.md` |
| Predecessor input | `docs/development/closeouts/S0/s0_3_live_baseline.md` |
| Predecessor input | `docs/development/closeouts/S0/s0_4_performance_observation.md` |
| Predecessor input | `docs/development/closeouts/S0/s0_5_reference_rig_inventory.md` |
| Governing plan | `docs/final_sensor_development_plan.md`, especially Sections 5 and 6 |

## Scope

This closeout records the Section 6.3 dual acceptance lock.  It uses only the
canonical development plan, the S0.1-S0.5 closeouts, and the current public
scope/versioning documents.  It does not run tests, builds, GPU/live checks, or
hardware work and does not promote any **Partial**, **Target**, machine-local,
nominal, planned, blocked, or unavailable result.

## Specifications locked

Two separate tracked release definitions now exist:

- [SquadBot-readiness acceptance](../../specs/s0_squadbot_readiness_acceptance.md)
  locks the Stage 1 internal research release from S1 through S6.  Its release
  artifact is the immutable checksummed Linux wheel and Kit archives, supported
  Linux acoustic packs, schemas/fixtures, and the S6 evidence and limitations
  index.  It is not a public registry release.
- [Final public release acceptance](../../specs/s0_final_public_release_acceptance.md)
  locks the Stage 3 final public product from P0 through P5, entered only after
  Stage 2 returns closeouts or accepted blocker reports.  Its exact audited
  artifacts are published through PyPI, GitHub, and the Kit Community Registry.

Each plan execution row has its own acceptance gate.  Every gate names required
predecessor/S0 inputs, a concrete future specification, closeout, or evidence
path under the Section 6.2 convention, measurable pass criteria, and explicit
failure handling.  Sensor-owned failures require correction and rerun;
unavailable live/GPU/display/hardware/Windows/cross-repository work produces a
blocker record; only optional claims can receive a reviewed descope decision.
No skip is a pass, and local evidence cannot replace the archived release
evidence package.

The SquadBot specification's
`Explicit exclusions from the Stage 1 critical path` section keeps all final
publication-only work off Stage 1.  It explicitly excludes Windows, PyPI,
GitHub and Community Registry publication, public supply-chain/docs/support
hardening, production usability/accessibility/migration/recovery and the
five-person study, final training scale, and optional advanced propagation.
It also preserves the Stage 2/downstream boundary for protobuf transport,
`AuditoryCue`, ontology, graph, vision, fusion, robot control, locomotion, and
safety.

## S0 facts carried into the lock

- S0.2 records all available pure gates green at closing revision `5a388b5`;
  S0.3 entered at `161d429` and records six passing live gate processes on
  Isaac Sim `6.0.1-rc.7`, Isaac Lab `3.0.0`, driver `580.159.03`, and an RTX
  4090.
- The real Isaac Lab `InteractiveScene`/`RigidObject` sub-probe remains
  **blocked**.  Neither specification converts the synthetic tensor-scene Lab
  evidence into real entity-scene physics evidence.
- S0.4 records the frozen 4,096-environment batched `tdoa_synthetic` scenario
  with pooled mean `10.878135340171866 ms` and p95
  `11.228774001210695 ms` across 150 samples.  The final public specification
  preserves its full measurement protocol and informational, single-host
  status; the formal p95 `<= 20 ms` gate remains in P1.
- S0.5 records an inventoried but uncalibrated ReSpeaker/Raspberry Pi bench.
  The Stage 1 specification carries all eight pending rig gates into S4 and
  requires an explicit blocker record for any unmet applicable hardware gate.
  Nominal or estimated geometry is never accepted as measurement.

## Open quantities preserved without invention

The plan leaves some quantities to later phase design.  The specifications do
not invent them:

- S0 contains observed CUDA memory for the S0.4 sensor benchmark but no writer
  memory limit, even though S2.2 refers to an S0 specification.  Its
  representative workload, sampling rule, and writer-memory limit are
  therefore **to be frozen in S2.2** before acceptance evidence is viewed.
- P0.4 owns the final supported runtime/platform/performance-host matrix,
  dataset scale, memory/throughput, UI cost, workloads, tolerances, and other
  final thresholds left open by the plan.  They must be frozen before their
  final evidence or holdouts are inspected.
- Effect-specific S3 and calibration S4 tolerances remain owned by their named
  preregistration/design gates and must be locked prospectively from analytical,
  S0, pilot, or fit evidence as the plan permits.

These are explicit later-phase inputs, not blockers to S0.6 and not implied
claims.

## Acceptance argument

The SquadBot specification covers every row in plan Sections 6.4-6.9:
`S1.1-S1.8`, `S2.1-S2.9`, `S3.1-S3.9`, `S4.1-S4.9`, `S5.1-S5.8`, and
`S6.1-S6.4`.  The final-public specification covers every row in Sections
6.11-6.16: `P0.1-P0.4`, `P1.1-P1.6`, `P2.1-P2.5`, `P3.1-P3.6`,
`P4.1-P4.5`, and `P5.1-P5.4`.

The one-row/one-gate mapping makes every later execution unit reviewable from
measurable inputs, outputs/evidence, pass criteria, and failure handling.  The
common evidence rules also require the phase exit criteria, environment,
metrics, checksums, reproduction, limitations, and next-phase contract.  The
separate release definitions prevent final publication gates from becoming
Stage 1 prerequisites while preventing early work from substituting for an
S1-S6 gate.

## S0 exit-gate assessment

The S0 exit gate is satisfied as an acceptance baseline, without overstating
what S0 proved:

- repository pure and selected live baselines are reproducible from S0.2 and
  S0.3 records, with narrower blocked/unavailable sub-probes retained;
- performance is observed and reproducible under the frozen S0.4 scenario,
  but remains informational and machine-local;
- the proposed rig is inventoried in S0.5 with explicit unknowns and eight
  pending gates, not represented as calibrated; and
- the internal SquadBot-ready and final public release definitions are frozen
  separately, with prospective thresholds and evidence rules that do not
  promote current **Partial** or **Target** capabilities.

## Verification record

This closeout and both specifications were checked by static review only.  The
verification checked one-to-one coverage against every S1-S6 and P0-P5 plan
row, matched all S0 revisions/runtime/hardware/performance/rig facts to their
closeouts, checked referenced existing source paths, checked Markdown
whitespace, and checked Git status/diff scope.  No test, build, live runtime,
GPU, hardware, commit, push, or destructive Git operation was performed.
