# S0 baseline and acceptance lock closeout

| Field | Recorded value |
| --- | --- |
| Phase | `S0` - Baseline and acceptance lock |
| Phase status | **Passed** |
| Closeout date | 2026-07-16 |
| Entry revision | `e626ee2` (`e626ee23d7c828645b75df6345f4cb2b1d3eadd2`) |
| Closing revision | `43d3106` (`43d3106d6137b69f70822cafa0210667bf78c148`) |
| Package version | `1.7.0` |
| Frame schema version | `ias.audio_sensor_frame.v1` |
| Predecessor closeouts | None; S0 is the initial baseline phase |
| Host summary | Ubuntu 24.04.4 LTS; Linux `6.8.0-136-generic`; x86_64; Python 3.12.3 in the pure `.venv` and Kit Python 3.12.13 for the live runtime |
| Live runtime | Isaac Sim `6.0.1-rc.7`; Isaac Lab checkout `3.0.0`; NVIDIA driver `580.159.03`; NVIDIA GeForce RTX 4090 |
| Dependency record | [`outputs/isaac_audio_sensors/S0/S0.2/pip_freeze.txt`](../../../outputs/isaac_audio_sensors/S0/S0.2/pip_freeze.txt), supplemented by the live runtime facts in the S0.3 closeout |

Revision `e626ee2` is the baseline pin from which S0 work proceeded; its parent
is `8395d65`. This closeout summarizes the complete phase through `43d3106`.
It is based on the six tracked subphase closeouts, their named evidence, the
two locked acceptance specifications, and Sections 5, 6.2, and 6.3 of
[`docs/final_sensor_development_plan.md`](../../final_sensor_development_plan.md).
No test, build, live runtime, GPU, or hardware work was rerun for this phase
closeout.

## Subphase results

The commit column identifies the commit that added the subphase closeout. A
separate implementation or evidence revision is retained in the outcome where
one exists.

| Subphase | Status | Closeout commit | Closeout | Outcome |
| --- | --- | --- | --- | --- |
| `S0.1` | **Passed** | `f660c86` | [`S0/s0_1_source_of_truth_audit.md`](S0/s0_1_source_of_truth_audit.md) | Classified the package/schema statement and all 15 Section 3 rows as Verified, Partial, Target, or External, with no plan correction required. |
| `S0.2` | **Passed** | `161d429` | [`S0/s0_2_pure_baseline.md`](S0/s0_2_pure_baseline.md) | Closed all available pure gates after revision `5a388b5` corrected the public-artifact boundary for internal development and rig documents. |
| `S0.3` | **Passed** | `9c86e58` | [`S0/s0_3_live_baseline.md`](S0/s0_3_live_baseline.md) | Recorded six passing live gate processes on the selected Sim/Lab/GPU host while preserving one blocked and two unavailable sub-probes. |
| `S0.4` | **Passed** | `b9ba7a4` | [`S0/s0_4_performance_observation.md`](S0/s0_4_performance_observation.md) | Instrumented at `1d663c9` and froze three warmed 50-step observations plus their pooled timing and CUDA-memory baseline. |
| `S0.5` | **Passed** | `ec2e1fa` | [`S0/s0_5_reference_rig_inventory.md`](S0/s0_5_reference_rig_inventory.md) | Inventoried the proposed four-microphone bench and every unknown or unmeasured item without representing it as calibrated. |
| `S0.6` | **Passed** | `43d3106` | [`S0/s0_6_dual_acceptance_lock.md`](S0/s0_6_dual_acceptance_lock.md) | Locked separate Stage 1 SquadBot-readiness and Stage 3 final-public acceptance definitions with one-to-one plan-row coverage. |

## Gate summary

### Pure baseline

All eight available S0.2 gates passed in the recorded Python 3.12.3 virtual
environment: 383 tests passed with 67 documented optional-dependency skips;
lint, import smoke, configuration validation, build/distribution audit, schema
parity, example-trace parity, and direct internal-document sdist exclusion all
passed.

Two initial failures were resolved before closeout:

- The first test run failed because the public-name guard traversed the
  internal reference-rig document and rejected its project-specific text.
- The first build audit failed because the same rig document was included in
  the sdist and contained forbidden public-package context.

Revision `5a388b5` resolved their shared boundary error by excluding
`docs/development/` and `docs/reference_rig_hardware_environment.md` from the
sdist and treating those tracked documents as internal context in the naming
guard. The distribution auditor and its universal forbidden-content checks
were not weakened; the rebuilt wheel and sdist passed.

### Live baseline

All six required S0.3 gate processes passed on the recorded Isaac Sim
`6.0.1-rc.7` / Isaac Lab `3.0.0` installation, driver `580.159.03`, and RTX
4090: Isaac Sim audio lifecycle, live occlusion, extension UX/screenshots,
Isaac Lab CPU integration, Isaac Lab GPU integration, and optional acoustic
backend availability. The room-acoustics backend was exercised live rather
than inferred from import alone.

The following narrower sub-probes remain non-passing evidence:

- **Blocked:** the real Isaac Lab `InteractiveScene`/`RigidObject` probe hit
  PhysX CUDA illegal-memory errors in GPU form and hung during Kit shutdown in
  CPU form. The passing Lab gates used a synthetic tensor scene while retaining
  real SensorBase classes, Kit/USD execution, entity binding, selected reset
  and update behavior, and device placement.
- **Unavailable:** `omni.renderer_capture` could not be imported, so no full
  swapchain/application screenshot was produced. The required instruments
  panel and both viewport captures were produced and passed.
- **Unavailable, non-required:** no supported Replicator annotator
  registration method was found. Replicator was available, its writer was
  registered, and both scenarios directly wrote and flushed seven frames;
  annotator attachment was explicitly not required by that direct-update path.

### Performance observation

S0.4 froze the 4,096-environment, four-microphone, two-source batched
`tdoa_synthetic` scenario on `cuda:0`. Three runs used 10 untimed warmups and
50 synchronized timed steps each. The pooled observation is:

| Samples | Mean | Median | p95 | Worst | Peak CUDA allocation |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 150 | 10.878 ms | 10.901 ms | 11.229 ms | 11.671 ms | approximately 12.85 MiB |

Each run recorded 13,474,304 bytes (12.85009765625 MiB) as maximum allocated
CUDA memory after the post-warmup peak-counter reset. These values are an
informational, single-host baseline only. The formal `20 ms` performance gate
belongs to P1 and is not claimed by S0.

### Reference-rig inventory

S0.5 met its inventory stop condition: the Raspberry Pi, ReSpeaker audio
interface and four-microphone array, geometry status, unknown channel order,
speaker direction, ZED 2i, missing mounts, room, unlocked clock policy, and
planned measurement tools are reconstructable from the canonical record.
Nominal 66 mm microphone spacing and approximate room dimensions are not
labeled measured.

All eight carried hardware gates remain open: six-channel firmware and channel
verification; Raspberry Pi capture/playback/disconnect/endurance; ZED SDK;
physical measurements and uncertainty; reference-output and measurement-tool
acquisition; clock and metadata policy; Alex access/mounting; and final
serial/version/profile/BOM freeze. The current Genelec 8030C plus Focusrite
Scarlett Solo direction remains planned, and the purchase BOM is not frozen.
S0.5 passed as an honest inventory, not as a calibrated-rig gate.

### Dual acceptance lock

S0.6 locked both release definitions:

- [`s0_squadbot_readiness_acceptance.md`](../specs/s0_squadbot_readiness_acceptance.md)
  defines the S1-S6 internal research release and keeps final-publication work
  off the Stage 1 critical path.
- [`s0_final_public_release_acceptance.md`](../specs/s0_final_public_release_acceptance.md)
  defines the P0-P5 final public product after the Stage 2 interlude.

Static review verified one gate for every S1-S6 and P0-P5 execution row. Each
gate carries measurable inputs, outputs/evidence, pass criteria, and failure
handling. Missing live, GPU, display, hardware, Windows, or cross-repository
work remains blocked evidence rather than a pass, and optional capabilities
can be removed only through a reviewed descope decision.

## S0 exit-gate assessment

The governing plan states:

> **S0 exit gate:** the repository and reference rig have reproducible baselines,
> all present failures are resolved or explicitly blocked, and both release
> definitions are frozen without overstating current evidence.

S0 satisfies each clause:

1. **Reproducible repository and rig baselines.** S0.2 records exact pure-gate
   commands, environment, dependency freeze, logs, and final results. S0.3
   records exact Sim/Lab launchers, runtime/build versions, driver/GPU facts,
   commands, JSON/log evidence, and screenshots. S0.4 freezes the scenario,
   warmup/timing protocol, three raw 50-sample runs, aggregator, pooled metrics,
   and memory facts. S0.5 identifies the proposed bench and explicitly names
   every missing, unknown, nominal, planned, or unmeasured input, allowing a
   reviewer to reconstruct the proposal or identify what prevents calibration.
2. **Failures resolved or explicitly blocked.** The two S0.2 failures were
   reproduced, traced to one distribution boundary error, fixed at `5a388b5`,
   and rerun to passing results. All six required live processes passed. The
   real InteractiveScene probe remains explicitly blocked; renderer capture
   and annotator registration remain explicitly unavailable and are not used
   as passing evidence. The rig's eight open hardware gates are recorded as
   future prerequisites, not silently passed S0 checks.
3. **Both definitions frozen without overstatement.** The two tracked
   specifications cover every later plan row one-to-one and keep Stage 1 and
   final-public gates separate. They preserve the InteractiveScene blocker,
   single-host performance boundary, informational S0.4 status, uncalibrated
   rig status, Partial/Target capability labels, external ownership boundary,
   and prospective threshold rules. Neither specification promotes current
   local or planned evidence into a broader release claim.

The S0 exit gate is therefore **passed** at revision `43d3106`.

## Known limitations carried forward

- The real Isaac Lab `InteractiveScene`/`RigidObject` probe remains blocked.
  Synthetic tensor-scene results do not establish real entity-scene physics.
- Live and performance evidence comes from one Ubuntu 24.04.4 / Isaac Sim
  `6.0.1-rc.7` / Isaac Lab `3.0.0` / driver `580.159.03` / RTX 4090 host. It is
  not a portable OS, runtime, driver, GPU, display, clean-install, or
  performance claim.
- Full-application renderer capture and Replicator annotator registration were
  unavailable as described above; their narrower required alternatives passed.
- The pure virtual environment intentionally skipped 67 tests for absent
  optional dependencies: 43 for `torch`, 15 for `soundfile`, 6 for
  `pyroomacoustics`, 2 for `scipy`, and 1 for `pxr`. S0.2 does not claim those
  dependency-specific paths passed in the pure environment; supported live
  paths were addressed separately by S0.3.
- All eight reference-rig hardware gates remain open. The bench is not
  calibrated, measured geometry/channel order/clocks/extrinsics are not
  locked, planned equipment is not acquired or characterized, and the final
  BOM is not frozen.
- S0.1 identified ancillary documentation for later scoped cleanup:
  `docs/api_freeze_0_1.md` retains active-release `1.1.0` prose;
  `docs/installation.md` and `docs/open_source_release_checklist.md` retain
  `1.0.0` examples or checklist prose; `docs/isaac_lab.md` retains the older
  indicative `~5.6 ms/step` sentence; and `docs/isaac_sim.md` plus
  `docs/showcase.md` name pre-cleanup evidence paths whose retained artifacts
  now live under the dated archive. These are future scoped cleanup items, not
  S0 failures and not corrections to the Section 3 audit.

## S1 input contract

S1 enters from revision `43d3106` and receives:

- the S0.1 source-of-truth classification and the frozen S0.2 pure,
  distribution, schema, and trace baseline;
- the S0.3 selected runtime/host facts and explicit blocked/unavailable
  sub-probe ledger;
- the S0.4 frozen performance scenario, raw/pooled measurements, and
  informational single-host boundary;
- the S0.5 proposed-rig inventory and eight-gate hardware ledger;
- package `1.7.0`, the preserved `ias.audio_sensor_frame.v1` meaning, and the
  two S0.6 acceptance specifications; and
- this phase closeout as the integrated S0 exit assessment and artifact index.

The next gate is **S1.1 Architecture lock**. Its approved ADR must lock
packaging, supported runtime, compatibility, contract ownership, the base and
acoustic-pack boundary, version synchronization, binary/platform boundaries,
and separate-repository responsibilities before implementation begins. S1.1
must use the S0.6 lock, plan Sections 4, 5, and 10, the S0.2 distribution
baseline, and the S0.3 runtime facts; it must not assume away any carried
limitation.

## Artifact and reproduction index

### Machine-local evidence roots

- [`outputs/isaac_audio_sensors/S0/S0.2/`](../../../outputs/isaac_audio_sensors/S0/S0.2/)
  - pure-gate environment, dependency, passing/failing logs, and archive audit.
- [`outputs/isaac_audio_sensors/S0/S0.3/`](../../../outputs/isaac_audio_sensors/S0/S0.3/)
  - live-gate runtime facts, JSON, logs, screenshots, and prior-evidence snapshot.
- [`outputs/isaac_audio_sensors/S0/S0.4/`](../../../outputs/isaac_audio_sensors/S0/S0.4/)
  - three raw performance runs, logs, and pooled aggregate.

These are machine-local S0 evidence, not archived release packages or portable
claims.

### Subphase closeouts and reproduction authority

| Subphase | Closeout | Reproduction or verification pointer |
| --- | --- | --- |
| `S0.1` | [`s0_1_source_of_truth_audit.md`](S0/s0_1_source_of_truth_audit.md) | Static audit; use its [`Verification record`](S0/s0_1_source_of_truth_audit.md#verification-record). |
| `S0.2` | [`s0_2_pure_baseline.md`](S0/s0_2_pure_baseline.md) | [`Reproduction`](S0/s0_2_pure_baseline.md#reproduction) gives the exact Make and sdist-exclusion commands. |
| `S0.3` | [`s0_3_live_baseline.md`](S0/s0_3_live_baseline.md) | [`Reproduction`](S0/s0_3_live_baseline.md#reproduction) gives the exact live and optional-backend commands. |
| `S0.4` | [`s0_4_performance_observation.md`](S0/s0_4_performance_observation.md) | [`Reproduction`](S0/s0_4_performance_observation.md#reproduction) gives the three-run and aggregation commands. |
| `S0.5` | [`s0_5_reference_rig_inventory.md`](S0/s0_5_reference_rig_inventory.md) | Inventory-only closeout; use its [`Pending gates`](S0/s0_5_reference_rig_inventory.md#pending-gates) and [`Acceptance check`](S0/s0_5_reference_rig_inventory.md#acceptance-check), with [`docs/reference_rig_hardware_environment.md`](../../reference_rig_hardware_environment.md) as the canonical source. |
| `S0.6` | [`s0_6_dual_acceptance_lock.md`](S0/s0_6_dual_acceptance_lock.md) | Static lock; use its [`Verification record`](S0/s0_6_dual_acceptance_lock.md#verification-record). |

S0.1, S0.5, and S0.6 do not contain literal `Reproduction` headings because
they are respectively a static audit, an inventory mapping, and a static
acceptance lock. The pointers above identify their actual verification or
canonical authority rather than implying an unrecorded execution command.

### Locked acceptance specifications

- [`docs/development/specs/s0_squadbot_readiness_acceptance.md`](../specs/s0_squadbot_readiness_acceptance.md)
- [`docs/development/specs/s0_final_public_release_acceptance.md`](../specs/s0_final_public_release_acceptance.md)

## Verification record

This phase closeout was prepared by static inspection only. All six subphase
closeouts and both acceptance specifications were read in full. The Section 5,
6.2, and 6.3 requirements and the exact S0 exit-gate text were checked against
the governing plan. The nine phase commits from `e626ee2` through `43d3106`,
their full hashes, parentage, order, subjects, and closeout-file provenance were
checked with Git. Every linked source path and the three evidence roots above
were checked for existence. Gate statuses, initial failures and resolution,
runtime/hardware versions, sample counts, pooled statistics, CUDA allocation,
rig-gate count, acceptance coverage, and carried limitations were cross-checked
against their subphase sources. No tests, builds, live/GPU/hardware work,
commit, push, or destructive Git operation was performed.
