# S0 SquadBot-readiness acceptance specification

| Field | Locked value |
| --- | --- |
| Acceptance target | Stage 1 - SquadBot-Ready Sensor |
| Lock date | 2026-07-16 |
| Lock revision | `b9ba7a4` |
| Functional-validation amendment | 2026-07-20; preserves all `S1.1-S6.4` gates while replacing the former metrology-first S4 prerequisites with claim-driven functional evidence |
| Governing plan | `docs/final_sensor_development_plan.md`, Sections 2-10 |
| Required phases | `S1` through `S6` |

## Release definition

The Stage 1 release is an internal research release: immutable, checksummed
Linux wheel and Kit archives, version-matched supported Linux acoustic packs,
schemas, fixtures, and the S6 evidence and limitations index.  The complete S6
matrix must run against those installed artifacts, not a worktree.  The frozen
artifact identity and patch policy are the only inputs supplied to Stage 2.

This is **not** a PyPI, GitHub release, or Kit Community Registry release and
does not make a final cross-platform, production-usability, final training-
scale, absolute acoustic-calibration, universal hardware/room-transfer, or
metrology-grade-extrinsic claim. This definition follows Sections 5.1, 6.9,
and 9.1 of the plan.

## Authority, evidence, and result rules

This specification turns the execution rows in plan Sections 6.4-6.9 into
release gates.  It does not promote any **Partial**, **Target**, or
machine-local claim.  The current public v1 promises remain those in
`docs/v1_scope.md` and `docs/versioning.md`; compatible work preserves
`ias.audio_sensor_frame.v1` as required by plan Sections 4.3 and 10.

Each phase must create its design material below
`docs/development/specs/`, its subphase records below
`docs/development/closeouts/<phase>/`, its phase closeout at
`docs/development/closeouts/<phase>_closeout.md`, and machine-local evidence
below `outputs/isaac_audio_sensors/<phase>/<subphase>/`, following plan
Section 6.2.  The path names in the tables are required future artifacts.
Raw physical recordings may remain outside Git under the Section 6.2 rules,
but their tracked manifests, hashes, acquisition contracts, retrieval
instructions, and archived release-evidence location are mandatory.

A phase result is one of the following:

- **Pass:** all applicable criteria pass from the declared inputs and the
  required evidence is retained.
- **Fail / fix before proceed:** a sensor-owned defect or failed criterion is
  corrected and the affected plus regression gates are rerun.
- **Blocked:** an unavailable live, GPU, display, hardware, or cross-repository
  check produces a blocker record with the attempted command/action, exact
  error or missing prerequisite, partial artifacts, owner, and retry condition.
  It is not passing evidence.
- **Descope escalation:** only an explicitly optional claim may be removed by
  a reviewed release-scope decision.  Evidence may not be relabeled to make a
  required claim pass.  A required Stage 1 capability remains failed or
  blocked unless the governing plan and this lock are deliberately revised.

Every closeout must also contain the common facts required by plan Section 5:
entry revision, versions and predecessors; commands and configuration;
environment and hardware/runtime facts; pass/fail/blocked status; metrics with
sample counts, tolerances, and aggregation; artifact paths and checksums;
reproduction instructions; limitations; and the next phase input contract.
Machine-local evidence can support a closeout but cannot replace the archived
release evidence package declared by S6.

## Frozen S0 entry facts

These facts are entry evidence, not proof of later gates:

- The S0.2 pure gates were green at closing revision `5a388b5` and are the
  recorded predecessor baseline for the S0.3 entry at `161d429`: 383 tests
  passed with 67 documented optional-dependency skips; lint, import smoke,
  configuration validation, build/distribution audit, schema parity, trace
  parity, and internal-document sdist exclusion passed.  Evidence is under
  `outputs/isaac_audio_sensors/S0/S0.2/`.
- The selected live pair is Isaac Sim `6.0.1-rc.7` and Isaac Lab `3.0.0` on
  Ubuntu 24.04.4, driver `580.159.03`, and an NVIDIA GeForce RTX 4090.  The six
  required S0.3 gate processes passed, with evidence under
  `outputs/isaac_audio_sensors/S0/S0.3/`.
- The real Isaac Lab `InteractiveScene`/`RigidObject` sub-probe is **blocked**,
  not passed.  The passing Lab gates used a synthetic tensor scene while still
  exercising real SensorBase classes, Kit/USD execution, entity binding,
  selected reset/update, and device placement.  Later claims that require the
  real entity scene must resolve or retain this blocker honestly.
- The frozen S0.4 reference scenario observed 4,096 environments using the
  batched `tdoa_synthetic` path on `cuda:0`.  Across 150 timed samples, the
  pooled mean was `10.878135340171866 ms` and pooled p95 was
  `11.228774001210695 ms` (10.878 ms and 11.229 ms rounded).  These are
  informational single-host observations, not the final `20 ms` gate or a
  portable promise.  Evidence is under
  `outputs/isaac_audio_sensors/S0/S0.4/`.
- At its July 16 closeout, S0.5 recorded an available four-microphone ReSpeaker
  XVF3800 and Raspberry Pi 5 development bench, not a calibrated reference.
  Nominal 66 mm spacing was not measured geometry; raw channel exposure/order,
  clocks, extrinsics, mounts, room geometry, tools, reference output path,
  firmware/software, and final BOM then contained explicit unknowns. The later
  current records below supersede those unknowns where new evidence exists.

### S0.5 facts and current functional gates carried into S4

The S0.5 closeout remains a historical record of the inventory and pending work
known on July 16. Current planning also consumes the later verified bring-up,
`docs/reference_rig_hardware_environment.md`, and the implemented-mount source
`docs/zed_respeaker_mount_model_handoff.md`. Revision A Option 1 is digitally
released in its external companion CAD project, uses a detachable
steel-ballasted table base, and has a CAD-derived nominal 90 mm sensor-center
separation, but is not yet fabricated. Current functional work uses the
documented `S4_TEMP_DESKTOP_FIXTURE_REV0` in WANG 2022: ZED below, ReSpeaker
above on two operator-fixed supports, with operator-reported approximate
`90-100 mm` center-to-center separation. The CAD transform is not assigned to
that temporary fixture. Neither configuration proves formal physical/field
acceptance or a measured optical/acoustic extrinsic.

S4 tracks these eight current functional gates:

1. retain the hashed official six-channel ReSpeaker firmware evidence and
   verify the channel identity/order used by each accepted acquisition;
2. retain the Raspberry Pi capture/recovery/long-run facts; ReSpeaker 3.5 mm
   analog playback is optional and non-blocking unless a chosen experiment uses
   that output path, in which case its limitation must be resolved or labeled;
3. retain the ZED SDK/device evidence and record the exact ZED settings used;
4. lock device/source/room/mount state, coordinate conventions, nominal CAD
   geometry, approximate as-used geometry, supported uncertainty, and explicit
   Unmeasured/Unsupported labels needed by the functional metrics;
5. pass the practical no-unintended-motion, stability, pose-repeatability,
   microphone/FOV-obstruction, and safe-cable checks for the actual assembly;
6. lock acquisition metadata, practical time association and uncertainty,
   compact controlled matrix, stopping rule, and data/failure thresholds;
7. freeze grouped development/fit and held-out evaluation conditions, hashes,
   supported fields, and decision-relevant acceptance criteria before opening
   held-out results; and
8. freeze the replayable functional profile/configuration, complete trial and
   failure inventory, limitations, hashes, and evidence package for S5/S6.

An unmet applicable gate is failed or blocked; it never silently passes.
However, an explicitly Unmeasured or Unsupported quantity is not a blocker
unless a target metric or advertised claim requires it. Professional reference
speakers, dedicated interfaces, calibrated microphones, stands, a tripod,
laser distance meter, digital caliper/level, AprilTags, turntable, certified SPL
meter/calibrator, and formal mount-qualification equipment are not Stage 1
prerequisites. Alex access and installed-camera verification belong to the S5.7
handoff and Stage 2 V14-15, not the S4 bench holdout.

## S1 - Stable installable foundation

Required phase evidence root: `outputs/isaac_audio_sensors/S1/`; required
phase closeout: `docs/development/closeouts/S1_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S1.1` Architecture lock | This S0.6 lock; plan Sections 4, 5, and 10; S0.2 distribution baseline; S0.3 runtime facts. | Approved ADR at `docs/development/specs/s1_architecture_lock.md`; decision evidence at `outputs/isaac_audio_sensors/S1/S1.1/`; closeout at `docs/development/closeouts/S1/s1_1_architecture_lock.md`. | ADR fixes packaging, supported runtime, compatibility, ownership, base/pack boundary, version synchronization, and repository responsibilities; proves wheel/extension sources cannot drift; identifies binary/platform boundaries; preserves the generic sensor boundary before implementation. | Missing or contradictory decisions fail S1.1 and are fixed before implementation.  An unresolved ownership or platform boundary is escalated; it is not assumed. |
| `S1.2` Stage 1 public contracts | Approved S1.1 ADR; frame-v1 rules; plan Sections 4.2-4.5; S0.1 status audit. | Dataset/calibration schemas under `docs/schemas/`; valid/invalid fixtures under the relevant `examples/` directory; contract logs at `outputs/isaac_audio_sensors/S1/S1.2/`; closeout `docs/development/closeouts/S1/s1_2_public_contracts.md`. | Generated and checked schemas match; valid fixtures round-trip; malformed ids, units, frames, timestamps, channel order, checksums, and incompatible profiles fail before partial use; unknown runtime profiles fail; existing configurations retain documented behavior. | Any schema, round-trip, compatibility, or fail-closed defect is fixed and all contract regressions rerun before S1.3. |
| `S1.3` Plugin contracts | S1.1; S1.2 contracts and runtime profiles; plan Section 4.6. | Protocol/registry specifications and fixtures, with results at `outputs/isaac_audio_sensors/S1/S1.3/`; closeout `docs/development/closeouts/S1/s1_3_plugin_contracts.md`. | `PropagationBackend`, `DoaEstimator`, and `AudioFeatureExtractor` declarations reject duplicate ids, missing dependencies, unsupported device/profile combinations, invalid shapes, and false determinism; existing backends register without semantic drift. | Contract or existing-backend drift is fixed before dependent work.  An optional plugin may be descoped only with its claim removed and the base left healthy. |
| `S1.4` Canonical extension build | S1.1 ADR; S0.1 **Partial** distribution finding; current shared package source. | Packaged-source provenance and checkout-reference scans at `outputs/isaac_audio_sensors/S1/S1.4/`; closeout `docs/development/closeouts/S1/s1_4_canonical_extension_build.md`. | Source-checkout development still works; the packaged extension is built from the maintained wheel source and a test fails if packaged startup references repository `src/` or requires manual package installation. | Any checkout-relative distributed import or source divergence fails the gate and is fixed before artifact production. |
| `S1.5` Linux artifacts | S1.2-S1.4; audited S0.2 wheel/sdist baseline; base/pack boundary in S1.1. | Candidate wheel, self-contained L0/L1 Kit archive, version-matched Linux L2/L3 packs, manifests, hashes, and audit logs at `outputs/isaac_audio_sensors/S1/S1.5/`; closeout `docs/development/closeouts/S1/s1_5_linux_artifacts.md`. | Archives contain no caches, outputs, private paths, sibling code, or undeclared dependencies; capability discovery is accurate; removing a pack leaves the base healthy and reports missing capabilities actionably. | Unsafe/undeclared content, mismatch, or unhealthy pack removal rejects the artifacts.  An optional pack may be descoped only by reviewed claim removal. |
| `S1.6` Clean Linux install | Exact S1.5 artifacts; S0.3 selected 6.x runtime facts; clean-environment procedure from S1.1. | Install inventories, import provenance, lifecycle/capture/export/update/reinstall logs, GUI/headless artifacts, and hashes at `outputs/isaac_audio_sensors/S1/S1.6/`; closeout `docs/development/closeouts/S1/s1_6_clean_linux_install.md`. | Exact wheel/archive artifacts install into a clean Isaac Sim 6.x environment; every scenario passes without checkout imports or a manual `pip` step; imports resolve only from installed artifacts. | Sensor/install defects are fixed and rebuilt.  Runtime/display unavailability produces a blocker with command and partial artifacts, never a pass. |
| `S1.7` Compatibility freeze | S1.2, S1.3, S1.6; old frame/config fixtures; `docs/v1_scope.md` and `docs/versioning.md`. | Compatibility matrix, regenerated examples/docs, public-name inventory, and results at `outputs/isaac_audio_sensors/S1/S1.7/`; closeout `docs/development/closeouts/S1/s1_7_compatibility_freeze.md`. | `ias.audio_sensor_frame.v1` remains valid and unchanged in meaning; old fixtures load; new consumers work; breaking additions are removed or separately versioned; public names are frozen. | Any silent semantic break fails and is fixed or receives an explicit new contract version before proceeding. |
| `S1.8` Installed-artifact consumer gate | Immutable S1.6 artifacts; S1.7 freeze; external adapter fixtures; generic/external ownership boundary. | Isolated-environment logs for nominal, empty, malformed, multi-source, ambiguity, and replay cases at `outputs/isaac_audio_sensors/S1/S1.8/`; closeout `docs/development/closeouts/S1/s1_8_installed_consumer_gate.md`. | Installed-artifact `AudioSensorFrame -> protobuf -> AuditoryCue -> graph` results are deterministic; generic exports have no downstream ontology or behavior fields; the consumer repository is not modified. | A reproducible sensor defect is fixed and rerun.  Consumer access/runtime absence is a cross-repository blocker, not a pass; ownership disputes are classified and escalated. |

S1 passes only when all eight row gates and the Section 6.4 exit gate pass:
immutable Linux artifacts install cleanly, capabilities are discoverable, frame
v1 is compatible, and the external adapter consumes installed artifacts with
no sibling source path.

## S2 - Recording, replay, diagnostics, and operational GUI

Required phase evidence root: `outputs/isaac_audio_sensors/S2/`; required
phase closeout: `docs/development/closeouts/S2_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S2.1` Session and shard layout | S1.2 dataset manifest; Section 4.4 contract; S0 recording status. | Layout specification `docs/development/specs/s2_session_shard_layout.md`; reference dataset in the relevant `examples/` fixture directory; hashes/results at `outputs/isaac_audio_sensors/S2/S2.1/`; closeout `docs/development/closeouts/S2/s2_1_session_shard_layout.md`. | Episode/frame ids, relative paths, names, shard boundaries, joins, seeds, provenance, and completion markers are deterministic; the fixture is byte-identical where promised, logically deterministic otherwise, and portable after root relocation. | Nondeterminism, absolute-path dependence, or ambiguous completion fails and is corrected before writers. |
| `S2.2` Atomic bounded-memory writers | S2.1; S0.4 observed resource facts only; runtime-profile boundary. | Writer specification, interruption/disk-full/partial-line/slow/retry fixtures, telemetry, and staged/final artifacts at `outputs/isaac_audio_sensors/S2/S2.2/`; closeout `docs/development/closeouts/S2/s2_2_atomic_writers.md`. | Streaming JSONL and lossless multichannel WAV/FLAC implement staging, checksums, cancellation, resume, and finalization; no incomplete shard is exposed as complete.  Because S0 froze no writer-memory threshold, the representative workload, sample rule, and memory limit are **to be frozen in S2.2** before acceptance evidence is viewed, then passed. | Data-loss, false completion, or over-limit memory is fixed before S2.3.  Disk/runtime unavailability is recorded as a blocker; the memory limit is not selected after results. |
| `S2.3` Checked loader and replay | Passing S2.2 artifacts and corrupt variants; dataset/frame schemas. | Tiny/multi-shard replay traces and failure reports at `outputs/isaac_audio_sensors/S2/S2.3/`; closeout `docs/development/closeouts/S2/s2_3_checked_replay.md`. | Incremental replay preserves order, types, units, frames, timestamps, and episode boundaries; missing/corrupt/checksum-mismatched assets, non-monotonic time, and unknown versions fail with location context. | Any silent coercion, reordering, or missed corruption is fixed before validation. |
| `S2.4` Validator and statistics | S2.3 loader; valid and planted-corruption datasets. | Machine-readable validator reports and telemetry at `outputs/isaac_audio_sensors/S2/S2.4/`; closeout `docs/development/closeouts/S2/s2_4_validator_statistics.md`. | Valid fixtures have zero violations; each planted corruption yields the intended finding; counts, duration, missingness, consistency, timestamps, ranges, labels, modalities, and integrity are reported; large validation is streaming and bounded to the S2.2-frozen limit. | Missed or false findings and unbounded behavior are fixed; unsupported input fails explicitly. |
| `S2.5` Deterministic grouped splits | S2.4-clean manifests and configured grouping metadata. | Split manifests/hashes and leakage reports at `outputs/isaac_audio_sensors/S2/S2.5/`; closeout `docs/development/closeouts/S2/s2_5_grouped_splits.md`. | Repeated seeds reproduce hashes; no scene/source/room/task/episode grouping key crosses splits; impossible ratios or missing grouping metadata fail. | Leakage or nondeterminism fails and is fixed before calibration data use. |
| `S2.6` Shared validation controller | S1.2-S1.3 contracts/capabilities; existing GUI/headless validation. | Import-safe service tests and GUI/headless comparison reports at `outputs/isaac_audio_sensors/S2/S2.6/`; closeout `docs/development/closeouts/S2/s2_6_validation_controller.md`. | Stage, configuration, dependency, device, path, geometry, time, and calibration checks give identical results without `omni.ui`; state refreshes after stage, dependency, or config changes. | Divergence or stale capability state fails and is fixed before the guided GUI. |
| `S2.7` Operational guided GUI | S2.2-S2.6; S0.3 operational extension evidence and its unavailable sub-probes. | Workflow logs/screenshots, invalid-state matrix, cancellation outputs, and validator-clean dataset at `outputs/isaac_audio_sensors/S2/S2.7/`; closeout `docs/development/closeouts/S2/s2_7_operational_gui.md`. | `Setup -> Validate -> Run -> Inspect -> Record -> Export` lets a user create a valid scene, capture frames, and export a clean small dataset without source intervention; every planted invalid state has an actionable field/recovery action. | UI defects are fixed and rerun.  Display/capture unavailability yields a blocker record; machine-local screenshots alone do not close release evidence. |
| `S2.8` Headless and config parity | Passing S2.7 workflow; shared controller; one normalized configuration. | Config/API/CLI outputs and semantic diff at `outputs/isaac_audio_sensors/S2/S2.8/`; closeout `docs/development/closeouts/S2/s2_8_headless_parity.md`. | Every Stage 1 GUI operation has a config/API/CLI equivalent and lossless config round-trip; guided and headless outputs are semantically equivalent after documented path normalization. | Missing operations or semantic mismatch fails and is fixed before reliability closeout. |
| `S2.9` Reliability closeout | S2.4 and S2.8; representative capture definition frozen by S2 before execution. | Cancellation/restart, simulator replacement, dependency removal, disk failure, resume, and 30-minute headless capture logs with telemetry at `outputs/isaac_audio_sensors/S2/S2.9/`; closeout `docs/development/closeouts/S2/s2_9_reliability.md`. | No stale frame, incomplete published shard, unreported drop, unbounded memory growth, or unrecoverable valid config occurs; output passes the canonical validator. | Any criterion failure is fixed and the endurance scenario rerun.  Runtime/display/resource absence is a blocker, not a shortened pass. |

S2 passes only when the same validated configuration works through GUI and
headless paths, recording is atomic and replayable, and the long-run capture
has explicit resource and failure behavior, as required by Section 6.5.

## S3 - Dynamic acoustics required by SquadBot

Required phase evidence root: `outputs/isaac_audio_sensors/S3/`; required
phase closeout: `docs/development/closeouts/S3_closeout.md`.  Every effect must
be isolated, have additive diagnostics, and preserve a compatibility off-state.
Any tolerance left open by the plan is frozen in the owning S3 subphase design
from analytical, prior, or pilot evidence before final acceptance evidence.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S3.1` Pose-derived velocity | S1.7 compatibility freeze; timestamped pose fixtures. | Policy/specification, analytical fixtures, and error traces at `outputs/isaac_audio_sensors/S3/S3.1/`; closeout `docs/development/closeouts/S3/s3_1_pose_velocity.md`. | Constant-velocity cases meet the predeclared tolerance; first sample, reset, teleport, stale time, and smoothing policies are explicit; reset/teleport causes no extreme Doppler spike; authored-velocity precedence is explicit. | Failed policy/fixture is fixed before motion work; no silent fallback to zero or authored velocity. |
| `S3.2` Time gaps and intra-window motion | S3.1; S2.2 writer timing contract. | Pause/throttle/non-monotonic trajectories and sample/interpolation reports at `outputs/isaac_audio_sensors/S3/S3.2/`; closeout `docs/development/closeouts/S3/s3_2_time_motion.md`. | Known trajectories produce expected sample counts/silence and meet the predeclared interpolation bound; non-monotonic time fails. | Timing loss, excess interpolation error, or accepted non-monotonic time is fixed before proceeding. |
| `S3.3` Channel response and mismatch | S1.2 calibration types; S1.3 plugin contracts; impulse/tone/broadband fixtures. | Transfer-function and off-state comparisons at `outputs/isaac_audio_sensors/S3/S3.3/`; closeout `docs/development/closeouts/S3/s3_3_channel_response.md`. | Gain, delay, polarity, and frequency response recover configured transfer functions within predeclared tolerances; disabled modeling preserves prior waveform within tolerance. | Model or compatibility regression is fixed before dependent effects. |
| `S3.4` Seeded noise | S3.3; deterministic stream policy frozen before trials. | PSD/RMS/delay statistics, seed replays, and correlation matrix at `outputs/isaac_audio_sensors/S3/S3.4/`; closeout `docs/development/closeouts/S3/s3_4_seeded_noise.md`. | Predeclared analytical tolerances pass; fixed seeds replay; independent spectral self-noise, ambient, jitter, and drift streams are not accidentally correlated. | Statistical or determinism failure is fixed and resampled under the unchanged protocol. |
| `S3.5` Electronics path | S3.3-S3.4; boundary-amplitude and recovery fixtures. | Quantization/clipping/AGC diagnostics and off-state comparisons at `outputs/isaac_audio_sensors/S3/S3.5/`; closeout `docs/development/closeouts/S3/s3_5_electronics.md`. | Boundary amplitudes, recovery timing, clipping counts, and quantization noise meet predeclared criteria; disabled electronics preserves baseline. | Failed boundaries, missing diagnostics, or off-state drift is fixed before stress closeout. |
| `S3.6` Waveform directivity | S3.3; configured source/mic patterns; L2/L3 waveforms. | Cardinal-angle/frequency sweeps and estimator-confidence report at `outputs/isaac_audio_sensors/S3/S3.6/`; closeout `docs/development/closeouts/S3/s3_6_waveform_directivity.md`. | Sweeps match configured patterns within predeclared tolerance; invalid patterns fail; estimator tests show expected confidence degradation. | Incorrect response, accepted invalid pattern, or missing degradation is fixed; unsupported patterns fail explicitly. |
| `S3.7` Materials, dynamic rooms, occlusion | S3.2, S3.6; measured parameters where available; S0 **Partial** L3 boundary. | Clear/blocked/partial/material fixtures and cache-invalidation traces at `outputs/isaac_audio_sensors/S3/S3.7/`; closeout `docs/development/closeouts/S3/s3_7_dynamic_rooms.md`. | Waveform, RMS, occlusion, diagnostics, and export agree for every fixture; moving geometry/sources/arrays/rooms invalidate correctly; caches never return stale acoustics. | Any stale cache or cross-output inconsistency is fixed.  Missing measured materials remain an explicit limitation, not synthetic truth. |
| `S3.8` Motion and multi-source stress | Passing S3.1-S3.7; supported backend matrix. | Doppler/overlap/imbalance/reverb/occlusion/mount/identity stress results and resource telemetry at `outputs/isaac_audio_sensors/S3/S3.8/`; closeout `docs/development/closeouts/S3/s3_8_stress.md`. | No NaN, identity corruption, hidden ambiguity, stale state, or unbounded resource growth; unsupported combinations fail explicitly. | Any supported-case failure is fixed.  Unsupported cases are recorded and excluded from claims, never silently downgraded. |
| `S3.9` Fidelity envelope | S3.8 evidence; Section 3 L3 status and Section 6.6 exit boundary. | Published Stage 1 fidelity specification `docs/development/specs/s3_fidelity_envelope.md`, claim/evidence map, and performance/limits package at `outputs/isaac_audio_sensors/S3/S3.9/`; closeout `docs/development/closeouts/S3/s3_9_fidelity_envelope.md`. | Every realism claim maps to a passing fixture and off-state; supported geometry, dependencies, performance, and limits are stated; ray/transmission occlusion is not called diffraction or a complete wave solver. | Unsupported/overstated claims are removed or evidence is added.  Optional diffraction/richer propagation is deferred to P2. |

S3 passes only when downstream-required bench, moving-robot, hallway,
occlusion, and multi-source effects have measurable behavior and honest limits.

## S4 - Functional sim-to-real characterization and validation

Required phase evidence root: `outputs/isaac_audio_sensors/S4/`; required
phase closeout: `docs/development/closeouts/S4_closeout.md`. The current
functional-gate ledger above is mandatory. Every quantity is declared
Verified, Measured, CAD-derived, Nominal, Approximate, Unmeasured, or
Unsupported. Trials are separated into within-configuration repeatability,
controlled variation, and robustness/portability. Useful functional evidence
is valid inside its documented envelope; it is not absolute, traceable,
component-isolated, metrology-grade, or universally transferable evidence.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S4.1` Rig, mount, geometry, and frame lock | S0.5 facts and current eight-gate ledger; S1.2 profile schema; hardware/environment record; mount model handoff. | Versioned rig/device/channel/frame/source/room/topology record, actual assembly state, practical mount-check record, evidence-status ledger, CAD nominal transform/90 mm reference, approximate as-used geometry, uncertainty/limitations, and hashes at `outputs/isaac_audio_sensors/S4/S4.1/`; closeout `docs/development/closeouts/S4/s4_1_bom_frame_lock.md`. | Independent review reproduces channel order, coordinate conventions, placement method, and functionally required transforms. The rig is stable, does not move unintentionally, is repeatable enough for target metrics, leaves microphone openings/FOV sufficiently clear, and has safe non-disturbing cables. CAD nominal geometry is never called measured extrinsic; unmeasured values block only claims that require them. | Unsafe/unstable/obstructed setup or missing required identity/frame facts is fixed or blocked. Formal companion-CAD physical-qualification gates remain separate and are not falsely passed or automatic S4 blockers. |
| `S4.2` Acquisition tool and runbook | Passing S4.1; S2.2 writer; available ReSpeaker/ZED/Mac paths. | Tool/runbook, dry-run WAV/ZED/manifests, exact WAV/Mac/volume/source pose-distance-orientation/room/settings, mount state, operator notes, alignment method/uncertainty, and fault-injection results at `outputs/isaac_audio_sensors/S4/S4.2/`; closeout `docs/development/closeouts/S4/s4_2_acquisition.md`. | Synchronized or practically time-associated multichannel audio and ZED observations are reproducible with comparable equipment. Dry runs reject missing/swapped channels, incomplete takes, sustained clipping, nonmonotonic timestamps, stale poses, missing required metadata, and corrupt outputs. Chirps, claps, or visible impacts suffice when timing uncertainty supports the metric. | Missed fault or corrupt accepted take is fixed. Hardware/software absence is blocked only when required by the procedure; expensive synchronization equipment is not presumed necessary. |
| `S4.3` Pilot repeatability and functional characterization | S4.2; compact pilot matrix, expansion triggers, stopping rule, and quality/repeatability criteria frozen before takes. | Complete trial inventory and controlled/robustness report for bearing/DOA, candidate bearing, sector accuracy, TDOA, channel health/order/imbalance, relative RMS/level, combined source-room-sensor spectrum, relative delay, polarity anomalies, capture-to-frame/frame-to-adapter latency, noise, echo/relative decay, occlusion, overlap, silence, confidence, ambiguity, abstention, failures, and coarse audio-video association at `outputs/isaac_audio_sensors/S4/S4.3/`; closeout `docs/development/closeouts/S4/s4_3_pilot_repeatability.md`. | Multiple identical Mac/WAV/volume/pose repetitions support within-configuration repeatability; planned variations support only the tested range; phone/voice/object/impact/room variations remain robustness evidence. All planned trials and failures are reported. Expand only for observed failure, high variance, unresolved decision, or uncovered claim; stop on stable metrics, adequate claim coverage, and diminishing information gain. | Failed quality/repeatability corrects setup/protocol or narrows the claim and reruns affected cases. Unfavorable trials are never deleted; no combinatorial expansion is required without an information need. |
| `S4.4` Development/fit and held-out evaluation freeze | Passing S4.3; S2.5 grouped split tooling; proportional matrix. | Coverage report, group manifests by session/room/source device/WAV or source type/position/angle/distance/mounting condition, sealed holdout hashes, provenance, and access controls at `outputs/isaac_audio_sensors/S4/S4.4/`; closeout `docs/development/closeouts/S4/s4_4_holdout_freeze.md`. | Leakage-relevant groups do not cross splits; held-out trials are selected before final tuning and cannot adjust thresholds/parameters. | Actual leakage or invalid evidence triggers affected recollection/resealing. A non-exhaustive but claim-sufficient matrix is not itself a failure. |
| `S4.5` Supported functional fitting | Sealed S4.4 fit data only; S3.3-S3.6 models; profile schema. | Fit code/results for supported bearing/geometry, relative delay/gain/polarity, confidence, relative timing, or other identifiable parameters; synthetic recovery, residuals, constraints, uncertainty, limitations, and partial profile at `outputs/isaac_audio_sensors/S4/S4.5/`; closeout `docs/development/closeouts/S4/s4_5_calibration_fit.md`. | Synthetic recovery and residual criteria pass for every fitted parameter; partial profile validates. Absolute SPL/sensitivity, isolated speaker or microphone response, certified room acoustics, and unsupported precision extrinsics remain absent or explicitly unsupported. | Failed supported fits are fixed using fit data only or omitted with a limitation. Holdout access invalidates the gate; theoretical fields are never filled without evidence. |
| `S4.6` Profile and configuration application | S4.5 profile; compatible/incompatible device, channel-order, sample-rate, frame, mount/geometry, environment, malformed, and stale fixtures. | Determinism, off-state, field-status, and fail-closed reports at `outputs/isaac_audio_sensors/S4/S4.6/`; closeout `docs/development/closeouts/S4/s4_6_profile_application.md`. | Disabled profile leaves unadjusted behavior unchanged; compatible supported fields apply deterministically; nominal CAD geometry remains distinct from fitted/measured corrections; unsupported/partial fields never apply silently; swapped, stale, incompatible, or malformed profiles fail closed. | Partial/silent application, identity bypass, or off-state drift is fixed before criteria freeze. |
| `S4.7` Functional acceptance preregistration | S0 facts, S4.3 pilot, S4.5 fit, S4.6 application; held-out data unopened. | Preregistered `docs/development/specs/s4_holdout_acceptance.md` plus timestamp/hash at `outputs/isaac_audio_sensors/S4/S4.7/`; closeout `docs/development/closeouts/S4/s4_7_threshold_preregistration.md`. | Bearing error, sector/candidate coverage, TDOA, repeatability, relative latency, failure/clipping/channel-health, confidence/ambiguity/abstention, coarse AV association, and supported sim-real criteria state denominators, aggregation, exclusions, sample counts, median, p95, worst, failure logic, environment envelope, controlled/robustness treatment, and missing/unsupported treatment before holdout opening. No absolute SPL, metrological response/reverb, traceability, or unsupported precision-extrinsic threshold is required. | Missing metric semantics blocks holdout opening. No threshold may be selected from held-out results. |
| `S4.8` Held-out functional sim-to-real evaluation | Unopened S4.4 holdout; locked S4.7 criteria; real, unadjusted-sim, and functionally adjusted-sim paths. | Immutable controlled-source and robustness results with all samples/repetitions/scenarios, median, p95, worst, failures, adjustment effect by metric, and hashes at `outputs/isaac_audio_sensors/S4/S4.8/`; closeout `docs/development/closeouts/S4/s4_8_holdout_evaluation.md`. | Every preregistered supported result/sample and failure is archived and reported without refitting, outcome-driven threshold changes, or selective removal. Each adjustment is classified as improving, preserving, or worsening each relevant metric; every preregistered criterion must pass for S4.8 readiness in the claimed envelope. | Any failed criterion keeps S4.8 and S4 failed for that envelope. A narrower envelope proposed after failure requires new preregistered criteria and a new, previously unseen holdout; the original failure remains archived. Hardware loss is blocked; no post-hoc threshold or scenario change is allowed. |
| `S4.9` Replayable functional evidence package | Completed S4.8, whether passing or failed for archival purposes; exact profile/configuration, recordings, trial inventory, manifests, geometry/environment records, and tools. | Replayable functional package with explicit pass/fail status, metrics, all failure records, hashes, limitations, reproduction commands, field-status declarations, nominal CAD references, approximate as-used geometry, measured/fitted corrections, and archived evidence at `outputs/isaac_audio_sensors/S4/S4.9/`; closeout `docs/development/closeouts/S4/s4_9_calibration_package.md`. | A clean consumer reproduces declared results. The package distinguishes functional/relative, nominal mechanical, approximate as-used, measured/fitted, any absolute calibrated, and unsupported quantities. It is passing readiness evidence only when S4.8 passed every preregistered criterion for the claimed envelope. | Replay/archive failure is fixed. Failed S4.8 evidence is still packaged and reported with failed status, but cannot satisfy the S4 exit gate or feed S5 as passing evidence. |

S4 passes only when S4.8 and S4.9 pass for the claimed envelope, with a
versioned, repeatable functional workflow and honest held-out sim-to-real
evidence. All failures remain archived. A failed package cannot close S4; a
narrowed envelope requires new preregistered criteria and a new, previously
unseen holdout. S4 makes no absolute calibration, universal transfer, or
metrology-grade claim.

## S5 - SquadBot Phases 7-15 readiness matrix

Required phase evidence root: `outputs/isaac_audio_sensors/S5/`; required
phase closeout: `docs/development/closeouts/S5_closeout.md`.  Every fixture
uses installed artifacts and tests generic sensor outputs; external behavior
is observed only to prove the boundary.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S5.1` Phases 7-8 bench readiness | Passing S4.8/S4.9 functional package; S1.8 adapter gate; installed artifacts. | Exported/replayed rig recordings, supported profiles/configurations, sim/real traces, join/field-status report, and hashes at `outputs/isaac_audio_sensors/S5/S5.1/`; closeout `docs/development/closeouts/S5/s5_1_bench_readiness.md`. | The S4 package passed every preregistered criterion for its claimed envelope. Fixtures exercise only S4-supported fields; unsupported absolute fields remain absent/unsupported. Timestamps, frames, source ids, ambiguity, provenance, and metric joins survive the adapter boundary; transport and graph policy remain external. | A failed S4 package remains available for diagnosis but cannot satisfy S5.1. Sensor defects are fixed; hardware/adapter unavailability is a blocker; downstream policy is not implemented here. |
| `S5.2` Phase 9 mounting readiness | S3.1; S1.8; clean Isaac installed environment. | Generic mount/discovery example, moving-transform trace/config, live log, and hashes at `outputs/isaac_audio_sensors/S5/S5.2/`; closeout `docs/development/closeouts/S5/s5_2_mounting_readiness.md`. | Clean Isaac run proves mount identity, child microphones, coordinate convention, finite moving transforms, and exports without robot-specific frame fields. | Sensor/live defects are fixed; Isaac or robot asset access is a blocker, never invented static evidence. |
| `S5.3` Phase 10 orientation-input readiness | S5.2; S3.8 stress evidence. | Localized, ambiguous, silent, stale, and moving-array cue sequences with latency/confidence results at `outputs/isaac_audio_sensors/S5/S5.3/`; closeout `docs/development/closeouts/S5/s5_3_orientation_inputs.md`. | External orientation adapter receives stable ordered inputs; ambiguous/nonlocalized cases invent no direction; sensor contains no actuation. | Incorrect generic output is fixed; external adapter absence is blocked; actuation leakage rejects the gate. |
| `S5.4` Phase 11 visual-join readiness | S5.3; external visual/graph fixtures. | Repeated replay join manifests/diffs at `outputs/isaac_audio_sensors/S5/S5.4/`; closeout `docs/development/closeouts/S5/s5_4_visual_join.md`. | Source/frame ids, poses, timestamps, labels, and provenance join deterministically; visual classes, confirmation, and graph links remain external. | Unstable producer fields are fixed; external fixture access is blocked; visual/graph ownership is not absorbed. |
| `S5.5` Phase 12 moving-robot readiness | S3.8; S5.4; mounted-array scenario. | Rotate/translate valid, timeout, stop, and stale-transform traces with latency/resource telemetry at `outputs/isaac_audio_sensors/S5/S5.5/`; closeout `docs/development/closeouts/S5/s5_5_moving_robot.md`. | Continuity, timestamps, identity, latency, and resource use remain within bounds frozen in the S5.5 design before evidence; no robot approach/stopping behavior is implemented. | Sensor failure is fixed; unavailable sim/robot access is blocked; behavior/control stays external. |
| `S5.6` Phase 13 scaled readiness | S2.9; S5.5; hallway/multi-area scenario definition. | Outside-FOV, overlap, occlusion, reverb, and long-session traces plus per-failure/resource report at `outputs/isaac_audio_sensors/S5/S5.6/`; closeout `docs/development/closeouts/S5/s5_6_scaled_readiness.md`. | No stale transform, identity corruption, silent frame loss, unbounded memory, or contract drift; each failure mode remains separately measurable. | Any supported-case failure is fixed and endurance rerun; environment absence is a blocker. |
| `S5.7` Phases 14-15 practical Alex handoff readiness | S5.1 and S5.6; portable Stage 1 artifacts; current Alex evidence. | Functional config/profile package, replay fixtures, expected generic outputs, measured compute/network latency procedure/results, lightweight ReSpeaker-to-actual-installed-camera pose procedure, bench-versus-Alex distinction, and blocker templates at `outputs/isaac_audio_sensors/S5/S5.7/`; closeout `docs/development/closeouts/S5/s5_7_handoff.md`. | Package contains no unsafe command assumption, transport requirement, or actuation code. It verifies the actual Alex camera model from unit-specific/live authoritative evidence when available, never reuses the bench nominal transform automatically, and accepts a simple non-permanent ReSpeaker installation when stable, safe, documented, and repeatable enough. | Packaging/leakage or automatic bench-to-Alex transfer is fixed. Real robot/camera access remains a downstream blocker represented by templates, not a pass. No expensive equipment is introduced without an observed failure or claim need. |
| `S5.8` Installed-artifact matrix closeout | Passing S5.1-S5.7; immutable installed candidate; external chain fixtures. | Nominal, empty, malformed, ambiguity, overlap, motion, supported-profile/configuration, compatibility, and replay matrix plus installed provenance at `outputs/isaac_audio_sensors/S5/S5.8/`; closeout `docs/development/closeouts/S5/s5_8_installed_matrix.md`. | Every supported case passes through `AudioSensorFrame -> protobuf -> AuditoryCue -> MiniSceneGraph`; schema version, ids, timestamps, order, units, ambiguity, provenance, and fail-closed behavior are preserved; malformed/incompatible input is never partially used; generic exports have no downstream leakage. | Sensor defects are fixed and the full affected matrix rerun. Cross-repository unavailability is blocked and prevents this gate from passing. |

S5 passes only when a passing S4.8/S4.9 package underlies S5.1 and installed
generic artifacts demonstrate every sensor-owned capability required by
downstream Phases 7-15. A failed S4 package cannot satisfy S5 readiness.

## S6 - SquadBot-ready release gate

Required phase evidence root: `outputs/isaac_audio_sensors/S6/`; required
phase closeout: `docs/development/closeouts/S6_closeout.md`.

| Gate | Required inputs | Measurable outputs and evidence | Pass criteria | Failure handling |
| --- | --- | --- | --- | --- |
| `S6.1` Readiness CI matrix | S1.8, S2.9, S3.9, S4.9, and S5.8 closeouts; explicit runner inventory. | CI/job specification `docs/development/specs/s6_readiness_matrix.md`, repeated job logs, archived S4 replay results, blocker records, and retention manifest at `outputs/isaac_audio_sensors/S6/S6.1/`; closeout `docs/development/closeouts/S6/s6_1_readiness_ci.md`. | Pure, schema, build, archive, Linux clean-install, Sim/Lab/GPU, operational GUI, functional-evidence replay, endurance, and cross-repository jobs have explicit runners. Software CI reuses archived S4 evidence and need not have a Mac/ReSpeaker/ZED on every runner; hardware jobs have explicit runners or classified blockers; no blanket skip passes. | Failed jobs are fixed and rerun. Unavailable required runners create classified blockers; archived evidence is not silently replaced by skips. |
| `S6.2` Immutable candidate | Passing S6.1 definition; one clean revision; exact S1-S5 inputs. | Checksummed wheel, base Kit archive, Linux packs, schemas, S4 functional package, S5 fixtures, artifact/evidence manifest, build provenance, and complete matrix results at `outputs/isaac_audio_sensors/S6/S6.2/`; closeout `docs/development/closeouts/S6/s6_2_immutable_candidate.md`. | Complete S6 matrix runs against exact artifacts, not the worktree; contents/hashes are reproducible; import provenance is installed-only. | Any matrix failure, nonreproducible hash, or worktree import rejects and rebuilds the candidate. |
| `S6.3` Evidence and limitations index | Passing exact S6.2 candidate and all archived phase evidence. | Claim-to-evidence and limitation index at `outputs/isaac_audio_sensors/S6/S6.3/evidence_index.md`, archived package manifest/checksums, tested envelopes, and closeout `docs/development/closeouts/S6/s6_3_evidence_index.md`. | Every Stage 1 claim maps to tests, live artifacts, functional sim-to-real results, environment facts, limits, and reproduction commands; archived evidence is reusable for software regression/compatibility; no claim implies absolute calibration, universal device/room transfer, metrology extrinsics, or publication. | Missing/overstated evidence rejects the claim or candidate. A blocker stays classified and cannot be rewritten as a pass. |
| `S6.4` SquadBot development freeze | Passing S6.3 index; exact immutable set; Section 6.10 patch policy. | Frozen artifact list, hashes, installation instructions, and Stage 2 patch policy at `outputs/isaac_audio_sensors/S6/S6.4/`; closeout `docs/development/closeouts/S6/s6_4_squadbot_freeze.md`. | Downstream instructions reference only frozen artifacts; replacements are limited to reproduced sensor defects with regression, new identity/hash, and full S6 rerun; no public-registry or cross-platform claim is implied. | Any mutable/unidentified input or broader patch policy blocks the freeze.  Publication requests are deferred to P5. |

Stage 1 passes only when all S1-S6 row gates and phase exit gates pass and the
Section 9.1 evidence set is complete.  An allowed non-claim blocker remains a
blocker in the index; it never proves the unavailable capability.

## Explicit exclusions from the Stage 1 critical path

The following work is excluded from this release and cannot be introduced as a
Stage 1 pass condition:

- Stage 2 downstream execution and ownership: protobuf transport,
  `AuditoryCue`, project ontology, graph/world-model policy, vision, fusion,
  robot control, locomotion, and safety.  S1/S5 may exercise the external chain
  only as a consumer-boundary gate; they do not implement or accept those
  components.  Physical bench/Alex/mobile/torso execution in V7-15 remains in
  `squadbot-av-phase1` under plan Sections 5.3 and 6.10.
- Windows implementation, clean install, or Windows platform claims.
- PyPI, GitHub, and Kit Community Registry publication or public listing.
- Public-release supply-chain/signing, registry-readiness, documentation and
  support hardening, security/support/deprecation policy, and public install
  verification.
- Production GUI usability, accessibility, migration, recovery validation,
  and the five-person first-use study.  Stage 1 requires only the S2
  operational guided workflow and headless parity.
- Final 4,096-environment performance acceptance and large-corpus scale,
  optional advanced diffraction/richer propagation, public generalized
  calibration tooling, final platform acoustic packs, and other P1-P3 work.
- Professional reference speakers, dedicated audio interfaces, calibrated
  reference microphones, speaker/microphone stands, a tripod for the steel-base
  rig, laser distance meters, digital calipers or levels, AprilTags, turntables,
  certified SPL meters/calibrators, cosmetic cable management, and formal
  mount-qualification equipment unless a later advertised claim or observed
  blocker makes a specific item necessary.
- Learned classification, ROS 2 as a core dependency, guaranteed physical
  transfer, absolute SPL/component-isolated response, certified room acoustics,
  precision calibrated extrinsics, or any universal calibration/safety claim
  under the product boundary in plan Sections 2.3 and 10.

These are publication-, Stage 2-, or Stage 3-only gates.  Their absence does
not fail Stage 1, and satisfying them early cannot substitute for any S1-S6
gate.

## Coverage lock

The gate identifiers above map one-for-one to every execution row in plan
Sections 6.4-6.9: `S1.1-S1.8`, `S2.1-S2.9`, `S3.1-S3.9`, `S4.1-S4.9`,
`S5.1-S5.8`, and `S6.1-S6.4`.  Phase pass additionally requires the matching
exit paragraph and the common evidence/failure rules in this specification.
