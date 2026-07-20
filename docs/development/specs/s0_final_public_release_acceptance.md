# S0 final public release acceptance specification

| Field | Locked value |
| --- | --- |
| Acceptance target | Stage 3 - Final Public Product |
| Lock date | 2026-07-16 |
| Lock revision | `b9ba7a4` |
| Functional-validation amendment | 2026-07-20; carries the S4 functional evidence model and claim boundaries through `P0-P5` without removing any execution unit |
| Governing plan | `docs/final_sensor_development_plan.md`, Sections 2-10 |
| Required phases | `P0` through `P5`, after the Stage 2 interlude |

## Release definition and entry dependency

The final public release consists of audited immutable Python and Linux/Windows
Kit artifacts, optional platform acoustic packs, and a public evidence index.
The exact audited artifacts must be published through PyPI, GitHub, and the Kit
Community Registry after P0-P5 pass.  The registry listing must describe a
community-provided extension rather than an NVIDIA-supported product.  This
definition follows plan Sections 5.1, 6.16, and 9.3.

Stage 3 cannot begin directly from S6.  It begins only after the Stage 2
interlude returns its V7-15 downstream closeouts or the downstream plans'
accepted blocker reports, plus any versioned sensor-patch evidence.  An
accepted Stage 2 hardware/access blocker is not passing real-robot evidence;
it is an input finding that P0 must classify.  This dependency is fixed by
plan Sections 5.3, 6.10, and 9.2.

The final product remains the generic sensor SDK described in plan Section 2.
It does not absorb learned classification, downstream protobuf/`AuditoryCue`,
ontology, graph, vision, fusion, robot behavior/control, locomotion, safety, or
ROS 2 as a core dependency.  Current public promises remain those in
`docs/v1_scope.md` and `docs/versioning.md`; **Partial** and **Target** work
becomes a release claim only after the applicable P gate passes.

## Evidence and anti-overstatement rules

The P0 final acceptance freeze owns all final metrics, supported
runtimes/platforms, claims, workload definitions, runner classifications, and
release gates that the plan leaves open.  A quantity such as dataset scale,
memory/throughput, UI cost, or an analytical tolerance is marked "to be frozen
in P0.4" below rather than assigned a number here.  P0.4 must freeze it before
the corresponding final evidence or holdout is inspected.  No threshold may
be chosen after seeing its final holdout evidence.

Each phase must create design material below `docs/development/specs/`,
subphase records below `docs/development/closeouts/<phase>/`, its phase
closeout at `docs/development/closeouts/<phase>_closeout.md`, and machine-local
evidence below `outputs/isaac_audio_sensors/<phase>/<subphase>/`, following
plan Section 6.2.  Paths in the tables are required future artifacts.  Raw
physical recordings may remain outside Git only under the manifest, hash,
acquisition, retrieval, and archival rules in Section 6.2.

Machine-local live, performance, calibration, media, or Windows evidence may
support a closeout but never substitutes for the archived release evidence
package in its declared release location.  The P5 claim/evidence index must
point to exact artifact hashes and archived evidence.

The Stage 1 S4 package supports functional and relative claims inside its
documented device/source/room/distance/angle/volume/mount/environment envelope.
It does not by itself support absolute SPL or microphone sensitivity, isolated
speaker/microphone response, certified room acoustics, precision calibrated
optical/acoustic extrinsics, or universal device/room transfer. Those
capabilities become public gates only if P0.4 advertises them prospectively and
P2 adds the necessary claim-driven equipment and validation.

A phase result is one of the following:

- **Pass:** every applicable criterion passes from the declared inputs with
  retained, reproducible evidence.
- **Fail / fix before proceed:** a sensor-owned defect or failed criterion is
  fixed and all affected regression and candidate gates are rerun.
- **Blocked:** a skipped or unavailable live, GPU, display, hardware, Windows,
  or cross-repository check creates a blocker record containing the attempted
  command/action, exact error or missing prerequisite, partial artifacts,
  owner, and retry condition.  A skip is never a pass.
- **Descope escalation:** an optional capability may be removed only through a
  reviewed P0.4-compatible release-scope decision that removes its claim and
  keeps the base behavior healthy.  A mandatory final-release gate remains
  failed or blocked; it is not silently waived.

Each phase closeout must record the common Section 5 facts: entry revision,
versions and predecessors; exact commands and configuration; environment and
hardware/runtime; pass/fail/blocked status; metrics with sample counts,
tolerances, and aggregation; paths/checksums/reproduction; limitations; and
the next phase input contract.

## Frozen S0 performance reference

P1 inherits the S0.4 scenario definition, not merely its headline numbers:

- 4,096 environments on `cuda:0` use the deterministic synthetic entity
  tensor scene, a four-microphone `quad_front` array, and two source entities;
- `AudioArraySensor` uses `tdoa_synthetic`, with `compute_path="auto"`
  verified to resolve to `batched`; no waveform generation or real
  `InteractiveScene` physics is included;
- every update uses `dt=0.02` and `force_recompute=True`;
- 10 untimed warmup updates precede an initial `torch.cuda.synchronize()` and
  reset of CUDA peak-memory counters; and
- each of 50 timed steps measures one sensor update plus a following
  `torch.cuda.synchronize()`, so CUDA work completes within the sample.

S0.4 ran that scenario three times on the single Ubuntu/RTX 4090 reference host
with Isaac Sim `6.0.1-rc.7`, Isaac Lab `3.0.0`, driver `580.159.03`, and
PyTorch `2.10.0+cu128`.  Across 150 timed samples, pooled mean was
`10.878135340171866 ms`, pooled median `10.901460000241059 ms`, pooled p95
`11.228774001210695 ms`, and worst `11.670615000184625 ms` (10.878 ms,
10.901 ms, 11.229 ms, and 11.671 ms rounded).

Those figures are an informational baseline only.  They do not promise
portability to another GPU, driver, operating system, runtime, workload, scene,
or installation.  P0.4 must freeze the final supported host matrix and label
which hosts carry the performance claim.  P1/P4/P5 must run the locked protocol
on every claimed performance host; at minimum, plan P1.3 requires the RTX 4090
reference host.  The formal gate is at least three runs with every run's p95
`<= 20 ms`, while still reporting raw samples, mean, median, p95, worst,
memory, driver, and compute path.

The S0.3 real Isaac Lab `InteractiveScene`/`RigidObject` sub-probe remains
blocked.  The frozen performance scenario intentionally uses the synthetic
entity tensor scene and cannot be cited as real InteractiveScene physics
evidence.

## P0 - SquadBot findings consolidation

Required phase evidence root: `outputs/isaac_audio_sensors/P0/`; required
phase closeout: `docs/development/closeouts/P0_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P0.1` Evidence ingestion | Stage 2 V7-15 closeouts or accepted blocker reports; patch histories; exact S6/S4.9/S5.1 artifact identities; metrics and representative fixtures. | Traceable findings inventory with exact source artifact/version/fixture/reproduction links at `outputs/isaac_audio_sensors/P0/P0.1/findings_inventory.json`; preserved inputs/hashes in the same root; closeout `docs/development/closeouts/P0/p0_1_evidence_ingestion.md`. | Every report links to its originating artifact/version and reproduction evidence; unverifiable findings are explicitly unverified; accepted blockers retain their non-pass status. | Missing provenance is pursued or recorded unverified. Stage 2 output absent without an accepted blocker means Stage 3 entry is blocked. |
| `P0.2` Ownership classification | Complete P0.1 inventory; product boundary in plan Sections 2.3, 4.1, and 5.3. | One-owner classification ledger at `outputs/isaac_audio_sensors/P0/P0.2/ownership.json`; decision record and closeout `docs/development/closeouts/P0/p0_2_ownership_classification.md`. | Every finding is classified as sensor defect, downstream defect, limitation, or future feature with boundary citation and one owner; robot-specific behavior is not moved into the sensor. | Unclear ownership blocks disposition and is escalated; downstream work is not silently accepted into scope. |
| `P0.3` Regression consolidation | P0.2 sensor-defect set; latest S6-compatible artifact; representative real failures. | Minimal permanent fixtures in the relevant `examples/` fixture directory; focused and S6 regression logs at `outputs/isaac_audio_sensors/P0/P0.3/`; exact patch/artifact/reproduction provenance and hashes; closeout `docs/development/closeouts/P0/p0_3_regressions.md`. | Remaining reproducible sensor defects are fixed; focused and S6 suites pass; each reproducible integration failure has a minimal regression; unverified findings stay labeled; frame-v1 meaning is unchanged and any new contract is additive or separately versioned. | Reproducible sensor failures are fixed before P0.4. Irreproducible reports remain labeled; a semantic frame break is removed or versioned. |
| `P0.4` Final acceptance freeze | Passing P0.3; this S0 lock; all classified Stage 2 evidence; final holdouts still unseen for threshold selection. | Approved final acceptance specification `docs/development/specs/p0_final_acceptance_freeze.md`; supported runtime/platform/host matrix; functional-envelope claim matrix; dataset scale, memory/throughput, UI cost, workload, tolerance, and gate definitions; timestamp/hash at `outputs/isaac_audio_sensors/P0/P0.4/`; closeout `docs/development/closeouts/P0/p0_4_acceptance_freeze.md`. | Every P-phase output and final claim has a measurable gate, tested envelope, denominator, sample count, aggregation, exclusions, runner, and evidence location; all open quantities and claims are frozen before final holdout evidence; no threshold is outcome-selected. | Missing/open gate semantics block P1. Evidence viewed before threshold lock is identified and cannot serve as final holdout; affected holdout is resealed/recollected. |

P0 passes only when findings are traceable/classified, sensor failures are
permanent regressions, and final public acceptance is frozen prospectively.

## P1 - Scalable Isaac Lab training and dataset production

Required phase evidence root: `outputs/isaac_audio_sensors/P1/`; required
phase closeout: `docs/development/closeouts/P1_closeout.md`.
All performance, training, dataset, and scale claims are tied to recorded
workload conditions and supported scenarios. Functional S4 evidence cannot be
used to claim universal acoustic fidelity or untested hardware/room transfer.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P1.1` Additive Lab observations | P0.4 matrix/gates; S1.3 plugin contracts; plan Section 4.7 padding/device rules. | CPU/import-safe and live-GPU logs, shape/dtype/key manifests, and reset/selected-row traces at `outputs/isaac_audio_sensors/P1/P1.1/`; closeout `docs/development/closeouts/P1/p1_1_lab_observations.md`. | Elevation, range, occlusion, masks, and optional features have fixed declared shapes; tests verify dtype, padding, device, reset, selected-row isolation, export, and backward-compatible existing keys. | Pure defects are fixed.  GPU/live absence is a blocker, not a CPU-only pass; the blocked InteractiveScene probe is not overclaimed. |
| `P1.2` Fast-profile parity | Passing P1.1; `training_features` contract; scalar and batched fixtures. | Numerical parity report, allocation profile, and compute-path proof at `outputs/isaac_audio_sensors/P1/P1.2/`; closeout `docs/development/closeouts/P1/p1_2_fast_profile.md`. | L0/L1 scalar and batched outputs match P0.4-frozen tolerances; steady-state batched computation uses `training_features`, generates no waveform, and avoids all allocation types forbidden by P0.4. | Numerical/allocation regression is fixed before performance measurement.  Device fallback must be explicit and cannot satisfy a CUDA claim. |
| `P1.3` Reference performance gate | Passing P1.2; frozen S0.4 protocol above; P0.4 claimed-host matrix; RTX 4090 reference host. | At least three raw 50-sample runs per claimed performance host, aggregate, environment/driver facts, mean/median/p95/worst/memory/compute path, and logs at `outputs/isaac_audio_sensors/P1/P1.3/`; closeout `docs/development/closeouts/P1/p1_3_performance.md`. | Exact 4,096-env/four-mic/two-event protocol is used; every run has p95 `<= 20 ms`; all required statistics/provenance are reported.  S0.4 figures are compared as informational context only, without a portability claim. | Any over-budget run fails the host gate and is fixed/rerun without threshold change.  Missing GPU/host is a blocker.  A host can leave the claim only through P0-compatible descope escalation before candidate claims freeze. |
| `P1.4` Replicator parity | S2.4 canonical validator/session contract; P0.4 semantics; seeded frames. | Direct and Replicator datasets plus normalized semantic diff at `outputs/isaac_audio_sensors/P1/P1.4/`; closeout `docs/development/closeouts/P1/p1_4_replicator_parity.md`. | Direct and optional Replicator capture are semantically equivalent after path normalization and use one canonical session/writer truth; Replicator remains optional. | Semantic divergence is fixed.  Missing Replicator is an explicit optional-capability blocker/non-claim, not a base-release failure or false pass. |
| `P1.5` Large-corpus tools | S2.5 canonical JSONL/lossless-audio and split contracts; P0.4-frozen corpus, memory, and throughput specifications. | Parquet regeneration, streaming query, shard catalog, split/validation, and telemetry evidence at `outputs/isaac_audio_sensors/P1/P1.5/`; closeout `docs/development/closeouts/P1/p1_5_large_corpus.md`. | JSONL plus lossless audio stays canonical; optional indexes regenerate exactly as declared; operations on the P0.4-frozen corpus remain within its memory/throughput gates and preserve split integrity. | Exceeding a frozen bound, irreproducible index, or canonical-truth fork is fixed.  Optional Parquet may be descoped only with its claim removed. |
| `P1.6` Scale and endurance closeout | Passing P1.3-P1.5; P0.4 scale/endurance workload. | GPU, large capture, interruption/resume, validator, split-leakage, replay, resource, checksum, and dropped-frame reports at `outputs/isaac_audio_sensors/P1/P1.6/`; closeout `docs/development/closeouts/P1/p1_6_scale_endurance.md`. | Performance passes; manifests/checksums validate; memory meets the frozen bound; no split leakage or unreported dropped frame occurs; seeded resume is deterministic. | Any failure is fixed and affected endurance scenarios rerun.  Unavailable GPU/storage/runtime is a blocker, never reduced scale. |

P1 passes only when final training and dataset-production scale, determinism,
and performance gates all pass on the P0.4-supported claim matrix.

## P2 - Final realism and extensibility

Required phase evidence root: `outputs/isaac_audio_sensors/P2/`; required
phase closeout: `docs/development/closeouts/P2_closeout.md`. Advanced
propagation is optional and cannot inflate base or reference-rig claims. The
functional acquisition/fitting/validation workflow remains the default; a
metrology-grade requirement is introduced only for a prospectively advertised
capability that actually needs it.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P2.1` Advanced propagation plugin | P0.4 final claim/gate freeze; S1.3 `PropagationBackend`; common analytical/trusted cases. | Backend capability/config specification and contract/reference/performance results at `outputs/isaac_audio_sensors/P2/P2.1/`; closeout `docs/development/closeouts/P2/p2_1_advanced_propagation.md`. | Diffraction/richer model is introduced only through the plugin; explicit geometry, dependency, device, and performance limits are enforced; common contracts and P0.4-frozen analytical/trusted criteria pass without changing L0-L3 ids or base availability. | Plugin defects are fixed.  The optional backend may be descoped with all claims/packs removed; base behavior must remain passing. |
| `P2.2` Expanded materials and rooms | S3.9 envelope; P0.4 claim limits; new measured material/room inputs. | Isolated fixtures, uncertainty, cache invalidation, multi-backend comparisons, and unsupported-region results at `outputs/isaac_audio_sensors/P2/P2.2/`; closeout `docs/development/closeouts/P2/p2_2_materials_rooms.md`. | Every new claim has a passing isolated fixture, uncertainty, cache test, and honest unsupported-region behavior under P0.4-frozen criteria. | Failed or unmeasured claims are fixed or removed.  Synthetic presets are not promoted to measured truth. |
| `P2.3` Public functional characterization toolkit | S4.9 package/regression; P0.4 compatibility/claim gates; reusable acquisition/supported-fitting/validation/evidence requirements. | Public API/controller spec, evidence-status and claim-envelope workflow, new-compatible-device evidence, incompatible profiles, and reference-rig replay at `outputs/isaac_audio_sensors/P2/P2.3/`; closeout `docs/development/closeouts/P2/p2_3_calibration_toolkit.md`. | A compatible new device follows the documented functional workflow without project code; nominal/approximate/measured/unsupported fields remain distinct; incompatible profiles fail before application; reference-rig results remain reproducible. | API/workflow or regression failure is fixed. Missing device/hardware evidence limits the claim rather than becoming a universal-tool claim. |
| `P2.4` Platform acoustic packs | P2.1-P2.2; P0.4 Linux/Windows matrix; base/pack version contract. | Versioned Linux/Windows L2/L3/advanced packs and install/remove/update/mismatch/unsupported/missing-dependency logs at `outputs/isaac_audio_sensors/P2/P2.4/`; closeout `docs/development/closeouts/P2/p2_4_platform_packs.md`. | Capability discovery and mismatch rejection are accurate; each scenario passes independently of the base extension; supported packs match their declared platforms. | Broken pack is fixed or optional pack/claim is descoped.  Missing Windows runner is a blocker, not a pass. |
| `P2.5` Fidelity closeout | Passing/declared P2.1-P2.4 capabilities; S3/S4 envelopes; P0.4 claims. | Public backend/effect claim map, approximations, functional characterization envelope, accuracy/resource results, unavailable-capability behavior, and any claim-driven metrology extension at `outputs/isaac_audio_sensors/P2/P2.5/`; closeout `docs/development/closeouts/P2/p2_5_fidelity.md`. | Every advertised backend/effect maps to tests and archived evidence; advanced results do not inflate base/reference-rig claims. Absolute SPL, isolated component response, certified room acoustics, precision calibrated extrinsics, or universal calibrated transfer requires explicit equipment/validation; otherwise the functional envelope is published honestly. | Unsupported/overstated claims are removed or evidence supplied. Unclassified unavailable capability blocks closeout. |

## P3 - Production GUI

Required phase evidence root: `outputs/isaac_audio_sensors/P3/`; required
phase closeout: `docs/development/closeouts/P3_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P3.1` Final UX specification | P0.4 UI budgets/gates; S2.9 operational evidence; Stage 2 findings. | Persona/navigation/state/cancel/recovery specification and control inventory at `docs/development/specs/p3_final_ux.md`; evidence at `outputs/isaac_audio_sensors/P3/P3.1/`; closeout `docs/development/closeouts/P3/p3_1_ux_spec.md`. | Every existing control maps to Guided, Advanced, removed, or headless-only; progressive disclosure, persistent state, cancellation, recovery, and wireframes are defined; no valid capability is accidentally lost. | Unmapped/lost capability blocks implementation and is resolved in the spec. |
| `P3.2` Guided workflows and wizards | P3.1; P2.3 functional-characterization/profile controllers; shared S2 controllers. | Setup/stage/profile/dataset/record/export workflow logs; recorded source, room, device, mount/pose, settings, uncertainty, and supported/unsupported fields; state traces and validator reports at `outputs/isaac_audio_sensors/P3/P3.2/`; closeout `docs/development/closeouts/P3/p3_2_guided_workflows.md`. | First-time paths prevent invalid starts, preserve valid state, expose prerequisites, emit validator-clean artifacts, and never present nominal or approximate values as measured calibration. | Workflow, field-status, or artifact defects are fixed. Display/runtime absence is a blocker. |
| `P3.3` Diagnostics and accessibility | P3.2; P0.4 UI-cost budget and accessibility/recovery protocol. | Instruments/backpressure/waveform/spectrogram/event evidence, keyboard/readability/accessibility review, planted-failure recoveries, and UI telemetry at `outputs/isaac_audio_sensors/P3/P3.3/`; closeout `docs/development/closeouts/P3/p3_3_diagnostics_accessibility.md`. | Stale/error state is never presented as current/success; UI cost meets the P0.4 budget; every planted failure has understandable recovery; the frozen accessibility review passes. | Accessibility, stale-state, recovery, or cost failure is fixed and rerun; unavailable review/display is blocked. |
| `P3.4` Advanced mode and migration | P3.2; prior extension config fixtures; full expert-field inventory. | Old-config migration reports, config round-trips, Guided/Advanced synchronization diffs, and explicit findings at `outputs/isaac_audio_sensors/P3/P3.4/`; closeout `docs/development/closeouts/P3/p3_4_migration.md`. | Every expert field is preserved; old fixtures import to equivalent state; edits stay synchronized; unknown/removed fields yield explicit migration findings. | Data loss or silent field removal fails and is fixed; intentional incompatibility requires an explicit migration finding/policy. |
| `P3.5` Final headless parity | P3.3-P3.4; all Guided workflows; normalized configs. | Config/API/CLI/GUI semantic comparisons at `outputs/isaac_audio_sensors/P3/P3.5/`; closeout `docs/development/closeouts/P3/p3_5_headless_parity.md`. | Equivalent inputs match stage metadata, frames, manifests, calibration, and exports after documented normalization. | Missing operation or semantic mismatch is fixed before the user study. |
| `P3.6` Usability gate | Passing P3.5; P0.4-frozen study protocol; five unfamiliar evaluators; Kit UI automation/screenshots and recovery cases. | Per-participant timing/outcome records, consent-safe aggregate, automation/screenshots, accessibility and cancellation/restart results at `outputs/isaac_audio_sensors/P3/P3.6/`; closeout `docs/development/closeouts/P3/p3_6_usability.md`. | At least four of five unfamiliar evaluators install, configure, capture, and export a valid dataset within ten minutes without source code or terminal use; blocking findings are fixed and the study rerun. | A miss or blocking finding fails and is fixed/rerun under the locked protocol.  Missing evaluators, display, or runtime is a blocker, not a smaller study pass. |

## P4 - Cross-platform release hardening

Required phase evidence root: `outputs/isaac_audio_sensors/P4/`; required
phase closeout: `docs/development/closeouts/P4_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P4.1` Current-runtime CI | P1.6, P2.5, P3.6; P0.4 advertised-capability and supported-runner matrix. | CI specification `docs/development/specs/p4_current_runtime_ci.md`; repeated pure/schema/build/Linux/Windows/Sim/Lab/GPU/GUI/perf/pack/advertised-functional-or-calibration/dataset/cross-repo logs and retention manifest at `outputs/isaac_audio_sensors/P4/P4.1/`; closeout `docs/development/closeouts/P4/p4_1_ci.md`. | Only advertised capabilities are claim gates; each required job has an explicit supported runner, cannot blanket-skip, is stable across repetitions, and retains artifacts/blockers. | Failed jobs are fixed/rerun. Missing required hardware/GPU/display/Windows/cross-repo runner is a classified blocker, never a pass. |
| `P4.2` Windows clean install | P2.4 Windows packs; passing P4.1 definition; current P0.4-supported Windows Isaac runtime. | Base/pack install inventory, lifecycle/GUI/example/capture/export/update/removal logs, screenshots, import provenance, and hashes at `outputs/isaac_audio_sensors/P4/P4.2/`; closeout `docs/development/closeouts/P4/p4_2_windows_install.md`. | Windows satisfies the same declared contracts; platform limitations are explicit and tested; installed content matches the candidate-style artifacts. | Any contract/install defect is fixed.  Windows/runtime/display unavailability is a release blocker, not a non-Windows pass. |
| `P4.3` Supply-chain hardening | P4.1 artifact set; base and every pack; P0.4 policy. | SBOM, dependency/license inventory, checksums/signatures where supported, vulnerability review, and reproducible archive manifests at `outputs/isaac_audio_sensors/P4/P4.3/`; closeout `docs/development/closeouts/P4/p4_3_supply_chain.md`. | Audits cover base and every pack; undeclared binary/dependency/private content/unsafe archive path fails the build; all P0.4-frozen review criteria pass. | Audit finding rejects the build until fixed or a documented P0.4-compatible disposition removes the affected claim/artifact. |
| `P4.4` Documentation and support | Passing P4.2-P4.3; final advertised claim/version/envelope/limitation set. | Final install/quickstart/GUI/API/dataset/functional-characterization/calibration/example/troubleshooting/security/support/deprecation/migration docs and fresh-user walkthrough evidence at `outputs/isaac_audio_sensors/P4/P4.4/`; closeout `docs/development/closeouts/P4/p4_4_docs_support.md`. | Fresh-user walkthrough succeeds; claims, supported configurations, versions, commands, links, failure modes, limitations, support window, and policies agree with archived evidence. | Broken walkthrough or inconsistency is fixed. Missing support/security policy blocks publication. |
| `P4.5` Registry-readiness dry run | P4.4 candidate-style docs/artifacts; current Kit target/Community Registry rules rechecked immediately before release. | Rule snapshot/reference, naming/metadata/discovery checks, clean install-from-release dry run, and exact hashes at `outputs/isaac_audio_sensors/P4/P4.5/`; closeout `docs/development/closeouts/P4/p4_5_registry_readiness.md`. | Exact candidate-style artifacts install cleanly; current naming, metadata, documentation, archive, and discovery requirements pass; only explicit publication actions remain. | Rule/install mismatch is fixed.  Registry/client/network unavailability is a blocker; stale remembered rules cannot pass. |

## P5 - Publication and maintenance

Required phase evidence root: `outputs/isaac_audio_sensors/P5/`; required
phase closeout: `docs/development/closeouts/P5_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `P5.1` Final candidate rehearsal | Passing P4.5; one clean revision; exact final artifacts; complete P4 matrix. | Immutable wheel/sdist, Linux/Windows Kit archives/packs, schemas/fixtures, hashes, complete matrix results, and claim/limitation/evidence index at `outputs/isaac_audio_sensors/P5/P5.1/`; closeout `docs/development/closeouts/P5/p5_1_candidate_rehearsal.md`. | Complete P4 matrix runs against exact archives rather than worktree; every advertised capability/platform passes inside its declared envelope; the index maps claims, supported configurations, reproduction procedures, limitations, and provenance to hashes; any failed gate rejects candidate. | Any failure or worktree provenance rejects/rebuilds candidate and reruns affected plus complete candidate gates. |
| `P5.2` Python and Kit publication | Passing exact P5.1 candidate; tested rollback/yank procedures; publication authority. | PyPI/GitHub publication receipts, audited Linux/Windows Kit archive locations, external clean-install/checksum/smoke evidence, published functional-envelope statements, and rollback record at `outputs/isaac_audio_sensors/P5/P5.2/`; closeout `docs/development/closeouts/P5/p5_2_artifact_publication.md`. | Published Python/Kit files match candidate checksums and capability statements; no absolute acoustic fidelity or universal transfer is overstated; clean external installs match smoke results; rollback/yank procedures exist before announcement. | Checksum/install/claim mismatch halts announcement and triggers rollback/yank plus corrected candidate. Service/network/auth failure is blocked, not published. |
| `P5.3` Community Registry publication | Passing P5.2; exact audited platform artifacts/metadata; current registry rules. | Listing identity, publication receipt, clean-client discovery/install logs, installed hashes, supported-envelope/limitation/provenance links, and listing capture at `outputs/isaac_audio_sensors/P5/P5.3/`; closeout `docs/development/closeouts/P5/p5_3_registry_publication.md`. | Clean client discovers and installs exact audited artifacts; listing names platforms and the supported functional envelope accurately, publishes limitations/reproduction/evidence provenance, and states community, not NVIDIA, support. | Discovery/install/hash/statement error triggers correction or rollback. Registry unavailability is a blocker, not a completed release. |
| `P5.4` Post-release maintenance start | Passing P5.3 public release; support/deprecation policy; exact published identities. | Install/update smoke, archived public evidence index, issue triage, final changelog, hotfix-gate procedure, and next runtime-review schedule at `outputs/isaac_audio_sensors/P5/P5.4/`; closeout `docs/development/closeouts/P5/p5_4_maintenance.md`. | No critical packaging/contract regression is open; hotfixes reuse candidate gates; active support and evidence indexes exist; next compatibility review is scheduled. | Critical regression invokes rollback/hotfix gates and prevents closeout; missing maintenance ownership/schedule is fixed before declaring completion. |

## Final release decision

The final public product passes only when every applicable `P0.1-P5.4` row,
every P-phase outcome in plan Section 5.4, and the Section 9.3 final definition
pass from the exact published artifacts.  Required skipped live, GPU, hardware,
Windows, display, or cross-repository checks remain blockers.  Optional
capabilities that were prospectively descoped must be absent from artifacts,
documentation, and registry claims.

## Coverage lock

The gates above map one-for-one to every execution row in plan Sections
6.11-6.16: `P0.1-P0.4`, `P1.1-P1.6`, `P2.1-P2.5`, `P3.1-P3.6`,
`P4.1-P4.5`, and `P5.1-P5.4`.  Phase pass also requires the common evidence,
anti-overstatement, and failure rules in this specification.
