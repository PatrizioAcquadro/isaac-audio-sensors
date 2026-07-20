# Final Isaac Audio Sensor Development Plan

This document is the canonical forward-looking development plan for turning
`isaac-audio-sensors` into a broadly reusable, research-grade audio sensor for
Isaac Sim and Isaac Lab. It describes the intended final product, the evidence
needed to claim each capability, and the path required to support downstream
audio-visual robotics work without coupling the public package to one project.

[V1 Public Scope](v1_scope.md) remains the source of truth for what current v1
releases promise. [Roadmap](roadmap.md) records completed releases and shorter
future items. This plan does not retroactively expand either source: every item
marked **Target** remains future work until its exit gate has passed.

## 1. How To Read This Plan

The plan uses four status labels:

- **Verified**: implemented and backed by tests or recorded live evidence.
- **Partial**: useful behavior exists, but the final product claim is not yet
  justified.
- **Target**: approved future work with a defined evidence gate.
- **External**: owned by a downstream project, hardware provider, robot team,
  or infrastructure outside this repository.

Milestones are ordered by dependencies, not calendar dates. A milestone is
complete only when its exit criteria and evidence artifacts exist. A skipped
live, GPU, hardware, or cross-repository check is a blocker record, not passing
evidence.

## 2. Product Definition

### 2.1 Goal

The final product is an installable audio-sensor SDK that lets users:

1. author microphones, arrays, sound sources, and acoustic environments in
   Isaac Sim;
2. consume efficient, fixed-shape audio observations in Isaac Lab;
3. generate deterministic or physically motivated multichannel audio datasets;
4. inspect, validate, record, and export results through a guided GUI or an
   equivalent headless interface;
5. functionally characterize a simulated array against a documented physical
   rig, with calibrated quantities added only when the evidence and claim
   require them;
6. connect generic sensor output to project-specific perception, graph, and
   robot-control systems through adapters.

### 2.2 Intended Users

- Isaac Sim developers who need audio sources and robot-mounted arrays.
- Isaac Lab researchers who need scalable audio observations for training.
- Dataset creators who need synchronized audio, geometry, labels, and
  provenance.
- Acoustic-robotics researchers studying localization, robustness, or
  sim-to-real behavior.
- Downstream projects such as SquadBot that consume generic frames through
  their own ontology and behavior adapters.

### 2.3 Product Boundary

The public package owns:

- microphone-array geometry and configuration;
- scene/source capture from Isaac;
- propagation and sensor-model backends;
- DOA estimation and generic audio features;
- frame, dataset, and calibration contracts;
- Isaac Sim, Isaac Lab, GUI, CLI, recording, and validation paths;
- plugin interfaces for optional algorithms.

The public package does not own:

- a bundled learned sound-event classifier;
- a project-specific object ontology or world model;
- audio-cued search, robot navigation, locomotion, or manipulation;
- a safety-certified perception or control system;
- guaranteed physical transfer across unmeasured devices and rooms;
- ROS 2 as a core dependency. A ROS 2 adapter may be added later as an
  optional integration.

## 3. Current-State Audit

The current package release is `1.8.0`; the independent frame schema remains
`ias.audio_sensor_frame.v1`.

| Area | Status | Current evidence and boundary |
| --- | --- | --- |
| Core contract | **Verified** | Stable `AudioSensorFrame` v1, JSON Schema, JSON/JSONL round-trip, units, poses, provenance, and deterministic event ordering. See [API Freeze](api_freeze_0_1.md). |
| L0 geometry | **Verified** | `geometry_only` provides deterministic bearing, elevation where observable, distance, sector, and RMS proxies. |
| L1 synthetic TDOA | **Verified** | `tdoa_synthetic` provides delays, RMS, deterministic stress controls, confidence, and explicit ambiguity. |
| L2 room acoustics | **Verified, optional** | `room_acoustics` and `room_acoustics_srp` generate approximate room waveforms and GCC/SRP estimates when optional dependencies are installed. |
| L3 realism | **Partial** | Material-aware per-microphone ray/transmission occlusion exists. Diffraction, calibrated materials, hardware response, richer noise, and other advanced effects remain incomplete. |
| L4 functional sim-to-real | **Target** | The fidelity vocabulary exists, but no stable functional characterization artifact or automatic sim-vs-real workflow is implemented. Absolute, traceable calibration remains outside the current evidence. |
| 3D DOA and motion | **Partial** | Rank-aware 3D DOA, elevation, SRP-PHAT, and explicitly authored Doppler velocities exist. Automatic velocity derivation and intra-window motion do not. |
| Isaac Sim | **Verified** | Lazy stage discovery, live transforms, moving arrays/sources, occlusion, overlays, JSONL/WAV output, and lifecycle handling exist. |
| Isaac Lab | **Verified** | `SensorBase` integration, fixed-shape multi-environment tensors, GPU placement, stage/entity binding, reset, and selected-environment updates exist. |
| Training performance | **Verified locally** | The machine-local GPU artifact reports 4,096 environments at p95 `13.09 ms` for the batched L1 path against a `20 ms` budget. This is a reference-host observation, not a portable performance promise. |
| GUI | **Partial** | The extension supports authoring, discovery, live control, instruments, audio preview, debug geometry, recording, and export. The current section-heavy interface is not yet the final guided experience. |
| Dataset recording | **Partial** | JSON/JSONL, WAV, continuous sessions, and an optional Replicator writer exist. A dataset-level manifest, atomic shards, validation, and split tooling do not. |
| Distribution | **Verified for S1** | One rebuilt wheel, sdist, self-contained Kit zip, and Linux acoustic pack share a final checksum set. The canonical clean-install harness uses Kit's embedded isolated interpreter and rejects checkout, virtualenv, sibling-worktree, and editable-hook contamination. |
| Alex demonstration | **Partial evidence** | A live showcase mounts an array on Alex and demonstrates DOA-driven turning and occlusion. It is a demonstrator, not the full downstream phase acceptance chain. |
| SquadBot adapter | **External, verified consumer** | The sibling project converts released frame types into its protobuf, auditory cue, ontology candidate, and graph contracts. Those contracts remain outside this package. |

### 3.1 Highest-Priority Gaps

1. Keep the fast Isaac Lab path while adding scalable dataset capture.
2. Add bounded, atomic dataset recording, replay, validation, and splits.
3. Preserve the frozen S1 contracts and artifact provenance through later work.
4. Complete and validate the intended L3 physical effects.
5. Build an L4 functional sim-to-real workflow around the available documented
   rig, preserving evidence labels and adding precision only when a required
   claim or observed uncertainty justifies it.
6. Redesign the GUI around user tasks and progressive disclosure.
7. Prove released-artifact compatibility across downstream Phases 7-15.
8. Establish reproducible release, maintenance, and support evidence.

## 4. Final Architecture And Public Contracts

### 4.1 Layer Ownership

The existing four-layer boundary remains:

1. `isaac_audio_sensors.core`: import-safe models, math, contracts, backends,
   estimators, dataset/calibration IO, and CLI utilities.
2. `isaac_audio_sensors.isaac`: lazy Isaac Sim stage capture, physics queries,
   visualization, recording, and extension support.
3. `isaac_audio_sensors.lab`: Isaac Lab sensor configuration, bindings, and
   vectorized observation buffers.
4. External adapters: transport, ontology, world model, perception fusion, and
   robot behavior owned by downstream repositories.

Core imports must never require Isaac, Kit, torch, a GPU, ROS 2, protobuf, a
downstream project, or optional high-fidelity acoustic packages.

### 4.2 Runtime Profiles

Introduce one public configuration field:

```toml
[audio]
runtime_profile = "training_features"  # or "waveform_fidelity"
```

| Profile | Purpose | Required output | Default behavior |
| --- | --- | --- | --- |
| `training_features` | Large batched Isaac Lab training | masks, bearing/elevation/range, confidence, sector, RMS, ambiguity, occlusion, optional feature tensors | GPU-vectorized where available; no waveform generation in the default loop |
| `waveform_fidelity` | Dataset creation, evaluation, calibration, and demos | multichannel audio plus the generic frame/feature record | scalar or bounded batches; optional acoustic dependencies allowed |

Unknown profiles must fail configuration validation. Requesting a CUDA-only
path without CUDA must produce a clear error or an explicitly selected CPU
fallback; it must not silently move tensors to a different device.

### 4.3 `AudioSensorFrame` Compatibility

`ias.audio_sensor_frame.v1` remains the live event/frame contract. Existing
required fields and semantics do not change. Compatible additions must be
optional, use explicit units, and round-trip through older v1 readers that
ignore unknown fields.

Dataset organization and hardware calibration do not belong in required frame
fields. They receive separate schemas so a live frame stays small and stable.

### 4.4 Dataset Manifest Contract

Add `ias.audio_dataset_manifest.v1` with these responsibilities:

- dataset id, schema version, creation tool/version, and license/source;
- Isaac Sim/Lab/Kit, backend, estimator, runtime profile, and device provenance;
- coordinate convention, time base, sample rate, channel order, units, and
  dtype;
- episode id, scene id, environment id, seed, step/frame range, reset markers,
  and timestamps;
- array/source poses and stable ids, source truth, labels, and optional visual
  synchronization references;
- relative paths to frame traces and lossless multichannel WAV or FLAC assets;
- calibration-profile reference, configuration digest, and per-asset checksum;
- deterministic train/validation/test split records and the grouping key used
  to prevent leakage;
- completion state so interrupted shards cannot be mistaken for valid data.

JSONL is the canonical metadata stream. WAV or FLAC is the canonical lossless
audio payload. Parquet may be generated as an optional performance index, but
it must be reproducible from the canonical manifest and must not be the only
copy of required metadata.

### 4.5 Functional Profile Contract

Add `ias.audio_calibration_profile.v1` containing:

- profile id/version, device and channel identity, rig inventory, and available
  microphone geometry with per-field evidence status;
- coordinate frames, units, sample rate, temperature, speed-of-sound policy,
  and environment description;
- supported relative channel gain/delay/polarity, combined spectral and noise
  behavior, bearing or timing corrections, and usable frequency range;
- source/speaker identity, pose measurement method, reference signal, and
  acquisition procedure;
- fitted model parameters, fit/holdout metrics, applicability limits, and
  uncertainty;
- raw-measurement manifest references, checksums, tool version, and timestamp;
- explicit per-field indication of Verified, Measured, CAD-derived, Nominal,
  Approximate, Unmeasured, or Unsupported status.

Profile application must be deterministic, validate device identity, channel
order, sample rate, frames, mount or geometry identity, and applicable
environment constraints, and reject incompatible profiles rather than
partially applying them. Unsupported absolute SPL, isolated component response,
certified room-acoustic, or precision-extrinsic fields remain absent or
explicitly unsupported rather than receiving invented values.

### 4.6 Plugin Interfaces

Define three import-safe public protocols:

- `PropagationBackend`: scene/window/array input to waveform and physical
  diagnostics.
- `DoaEstimator`: ordered multichannel samples plus geometry to DOA result and
  estimator diagnostics.
- `AudioFeatureExtractor`: ordered samples plus sample rate to a fixed,
  documented feature tensor and metadata.

Each plugin declares a stable id, supported runtime profiles, required optional
dependencies, determinism policy, device support, and configuration schema.
Registries must reject duplicate ids and incompatible capabilities. Learned
classifiers may consume these hooks, but no learned model is part of the base
release.

### 4.7 Isaac Lab Observation Additions

Retain the existing observation names and add fixed-shape tensors for:

- `elevation_deg`;
- `range_m`;
- `occlusion_mask`;
- optional `audio_features` with a shape declared by the selected extractor.

Padding uses the existing mask-driven policy: invalid continuous values use
`NaN` where absence must remain distinguishable, boolean masks are `False`,
and non-applicable feature slots are zeroed. All tensors must share the sensor
device and selected-environment reset/update behavior.

## 5. Three-Stage Delivery Model

All work is evidence-gated rather than date-gated. Every phase closeout records:

- entry revision, dependency versions, and predecessor closeouts;
- exact commands, configuration, environment, and hardware/runtime facts;
- pass, fail, or blocked status for every acceptance gate;
- metrics with sample counts, tolerances, and aggregation rules;
- artifact paths, checksums, and reproduction instructions;
- known limitations and the next phase's input contract.

A skipped live, GPU, display, hardware, Windows, or cross-repository check is a
blocker record, not passing evidence.

### 5.1 Delivery Stages

| Stage | Purpose | Completion artifact | Publication status |
| --- | --- | --- | --- |
| **Stage 1 - SquadBot-Ready Sensor** | Complete the generic sensor capabilities needed to support SquadBot Phases 7-15 before downstream execution begins. | Immutable, checksummed Linux wheel and Kit archives plus the S6 evidence index. | Internal research release; not a public registry release. |
| **Stage 2 - SquadBot Validation Interlude** | Consume the frozen sensor artifact through the existing downstream Phase 7-15 plans and return verified defects or limitations. | Downstream closeouts or accepted blocker reports, plus versioned sensor patch evidence when needed. | No new sensor feature program. |
| **Stage 3 - Final Public Product** | Incorporate downstream findings, finish training scale, optional advanced realism, production UX, Windows, release hardening, and publication. | Audited final release artifacts and public evidence index. | PyPI, GitHub, and Kit Community Registry. |

### 5.2 Stage 1 Phase Outcomes

| Phase | Outcome required before the next phase |
| --- | --- |
| `S0` | Current software, live runtime, performance, hardware, and acceptance baselines are explicit and reproducible. |
| `S1` | A stable, self-contained Linux sensor artifact preserves public contracts and passes the external adapter boundary. |
| `S2` | Recording, replay, validation, operational guided GUI, and headless equivalents are reliable enough for bench and robot work. |
| `S3` | Dynamic acoustics required by the downstream scenarios are isolated, tested, and bounded honestly. |
| `S4` | The available rig has a replayable functional profile and preregistered sim-vs-real evaluation inside a documented experimental envelope. |
| `S5` | Installed artifacts pass fixtures representing every sensor-owned requirement through downstream Phases 7-15. |
| `S6` | The complete SquadBot-readiness matrix passes and immutable research artifacts are frozen. |

### 5.3 Stage 2 Boundary

Stage 2 is executed from `squadbot-av-phase1` using that repository's existing
Phase 7-15 plans. This repository supplies released generic artifacts,
calibration/config packages, replay fixtures, and sensor defect fixes only. It
does not take ownership of protobuf transport, `AuditoryCue`, ontology, graph,
vision, fusion, robot control, locomotion, or safety.

The Stage 2 sequence is:

1. `V7-8`: physical bench and functional sim-vs-real validation;
2. `V9-11`: Alex simulation, orientation-input, and visual-link validation;
3. `V12-13`: mobile and scaled-scenario validation;
4. `V14-15`: real torso/mobile validation or the downstream plans' accepted
   blocker reports.

### 5.4 Stage 3 Phase Outcomes

| Phase | Outcome required before the next phase |
| --- | --- |
| `P0` | SquadBot findings are classified, sensor defects become regressions, and final public acceptance is frozen. |
| `P1` | Isaac Lab training and dataset production meet the final scale, determinism, and performance gates. |
| `P2` | Optional advanced propagation, public functional-characterization tooling, claim-driven calibration extensions, and acoustic-pack limits are validated. |
| `P3` | The production GUI passes usability, accessibility, migration, recovery, and headless-parity gates. |
| `P4` | Windows, current-runtime CI, supply-chain, documentation, support, and registry-readiness gates pass. |
| `P5` | Exact audited artifacts are published and post-release maintenance begins. |

## 6. Agent Execution Work Breakdown

### 6.1 Summary
The top-level implementation agent owns one complete `S` or `P` phase. It may
delegate dependency-independent subphases, but it remains responsible for
integration, repository-wide verification, evidence quality, and the phase
closeout. Stage 2 is not assigned from this roadmap; it follows the downstream
repository's own plans.

### 6.2 Execution Artifact Convention

Use these locations when implementation begins:

- phase design and benchmark specifications:
  `docs/development/specs/<phase>_<topic>.md`;
- subphase closeouts:
  `docs/development/closeouts/<phase>/<subphase>_<topic>.md`;
- phase closeout: `docs/development/closeouts/<phase>_closeout.md`;
- public schemas: `docs/schemas/`;
- small redistributable fixtures: the relevant `examples/` fixture directory;
- machine-local live, performance, calibration, and media evidence:
  `outputs/isaac_audio_sensors/<phase>/<subphase>/`.

Raw physical recordings remain outside git unless their license, consent, and
size permit redistribution. Track their manifests, hashes, acquisition
contracts, and retrieval instructions. A closeout may cite ignored local
evidence, but a release claim needs an archived evidence package in its declared
release location.

### 6.3 S0 - Baseline And Acceptance Lock

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S0.1` | **Source-of-truth audit.** Map every current claim in Section 3 to code, tests, tracked documents, or named machine-local evidence. | Every claim is Verified, Partial, Target, or External with evidence. Correct this plan before continuing if implementation and documentation disagree. | None |
| `S0.2` | **Pure baseline.** Run tests, lint, schema parity, import smoke, build, and archive/distribution audits from a documented environment. | All available pure gates pass. Existing failures have reproducible commands and are resolved before feature work. | `S0.1` |
| `S0.3` | **Live baseline.** Run Isaac Sim lifecycle, Isaac Lab GPU, extension GUI, screenshots, and supported optional-backend checks on the selected 6.x/3.x pair. | Every live gate records exact runtime, driver, GPU, and artifacts. Unavailable capability is `blocked`. | `S0.2` |
| `S0.4` | **Performance observation.** Freeze the existing reference scenarios and collect raw timing/memory samples, including three warmed 50-step runs for the 4,096-environment L1 benchmark when the host supports it. | Report mean, median, p95, worst step, device, memory, and compute path. Results are an informational baseline; the final `20 ms` gate belongs to `P1`. | `S0.3` |
| `S0.5` | **Reference-rig inventory.** Record the Raspberry Pi, audio interface, microphone count/geometry, channel order, speaker, camera, mounts, room, clocks, and measurement tools; mark unknown values explicitly. | A reviewer can reconstruct the proposed bench or identify every missing item. Estimated geometry is never labeled measured. | `S0.1` |
| `S0.6` | **Dual acceptance lock.** Write separate tracked specifications for the SquadBot-readiness release and the final public release using S0 facts. | Every later phase has measurable inputs, outputs, evidence, and failure handling. Final publication-only gates are not placed on the Stage 1 critical path. | `S0.2`-`S0.5` |

**S0 exit gate:** the repository and reference rig have reproducible baselines,
all present failures are resolved or explicitly blocked, and both release
definitions are frozen without overstating current evidence.

### 6.4 S1 - Stable Installable Foundation

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S1.1` | **Architecture lock.** Record packaging, supported runtime, compatibility, contract ownership, base/acoustic-pack boundary, version synchronization, and separate-repository responsibilities in one ADR. | The ADR proves wheel and extension sources cannot drift, identifies binary/platform boundaries, preserves generic sensor ownership, and is approved before implementation. | `S0.6` |
| `S1.2` | **Stage 1 public contracts.** Implement types, JSON Schemas, serialization, validation, and fixtures for `ias.audio_dataset_manifest.v1` and `ias.audio_calibration_profile.v1`; add `training_features` and `waveform_fidelity` runtime profiles. | Generated and checked schemas match; valid fixtures round-trip; malformed ids, units, frames, timestamps, channel order, checksums, quaternions, and incompatible profiles fail before partial use. Valid non-unit manifest quaternions normalize to unit length. | `S1.1` |
| `S1.3` | **Plugin contracts.** Implement `PropagationBackend`, `DoaEstimator`, and `AudioFeatureExtractor` protocols, capability declarations, and registry validation. | Duplicate ids, missing dependencies, unsupported device/profile combinations, invalid shapes, and false or unverifiable determinism declarations fail. Propagation declarations run twice on a canonical room-valid fixture. | `S1.1`, `S1.2` |
| `S1.4` | **Canonical extension build.** Build the Kit extension from the same maintained package source as the wheel and remove distributed checkout-relative import behavior. | Source-checkout development remains supported; packaged startup fails a test if it references repository `src/` or requires a manual package installation. | `S1.1` |
| `S1.5` | **Linux artifacts.** Produce a self-contained L0/L1 base archive and version-matched Linux L2/L3 acoustic packs with audited contents and capability discovery. | Every wheel's complete top-level import ownership, including native modules, and installed-file hashes are recorded and reverified. External preloads, tampering, incomplete inventories, and host/pack ownership overlap fail closed. | `S1.2`-`S1.4` |
| `S1.6` | **Clean Linux install.** Run headless, reinstall, GUI, and wheel-venv scenarios in one invocation against one final four-artifact checksum set. | Kit scenarios launch through embedded `python3 -I -S`; executable, prefix, and every import path are Kit-owned or output-local, with repository, virtualenv, sibling checkout, and editable-hook contamination rejected. Partial runs cannot replace the canonical verdict. | `S1.5` |
| `S1.7` | **Compatibility freeze.** Run old frame/config fixtures and new contract/plugin consumers; regenerate public examples and compatibility documentation. | `ias.audio_sensor_frame.v1` remains valid and unchanged in meaning. Breaking additions are removed or assigned a new version; the closeout freezes public names. | `S1.2`, `S1.3`, `S1.6` |
| `S1.8` | **Installed-artifact consumer gate.** In an isolated environment, run the external adapter's nominal, empty, malformed, multi-source, ambiguity, and replay fixtures against the built artifact. | The named malformed-schema case must pass with explicit rejection, zero protobuf/cue/candidate outputs, and byte-identical graph state; the harness makes no other consumer change. | `S1.6`, `S1.7` |

**S1 exit gate:** immutable Linux artifacts install cleanly, supported base and
acoustic capabilities are discoverable, frame v1 remains compatible, and the
external adapter consumes installed artifacts without sibling source paths.

### 6.5 S2 - Recording, Replay, Diagnostics, And Operational GUI

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S2.1` | **Session and shard layout.** Define deterministic episode/frame ids, relative paths, asset naming, shard boundaries, audio/metadata joins, seeds, provenance, and completion markers. | A small reference dataset is byte-identical where promised, logically deterministic otherwise, and portable after moving its root directory. | `S1.2` |
| `S2.2` | **Atomic bounded-memory writers.** Implement streaming JSONL and lossless multichannel WAV/FLAC output with staging, checksums, cancellation, resume, and finalization policy. | Process interruption, disk-full, partial line, slow writer, and retry tests never expose an incomplete shard as complete; memory remains within the S0 specification. | `S2.1` |
| `S2.3` | **Checked loader and replay.** Load sessions incrementally and replay frames in original order with preserved types, units, frames, timestamps, and episode boundaries. | Tiny and multi-shard fixtures round-trip. Missing assets, corruption, checksum mismatch, non-monotonic time, and unknown versions fail with location context. | `S2.2` |
| `S2.4` | **Validator and statistics.** Report counts, duration, missingness, channel/sample-rate consistency, timestamps, ranges, labels, modalities, and asset integrity. | Valid fixtures have zero violations; every planted corruption produces the intended finding; large validation is streaming and bounded. | `S2.3` |
| `S2.5` | **Deterministic grouped splits.** Build fit/holdout and train/validation/test manifests using configured scene, source, room, task, or episode grouping. | Repeated seeds produce the same hashes; no selected group crosses splits; impossible ratios or missing grouping metadata fail. | `S2.4` |
| `S2.6` | **Shared validation controller.** Move stage, configuration, dependency, device, path, geometry, time, and calibration checks into import-safe services shared by GUI and headless interfaces. | Pure tests prove identical results without `omni.ui`; capability state refreshes after stage, dependency, or configuration changes. | `S1.2`, `S1.3` |
| `S2.7` | **Operational guided GUI.** Deliver `Setup -> Validate -> Run -> Inspect -> Record -> Export` with safe presets, inline errors, lifecycle state, core instruments, recording progress, cancellation, and output inventory. | A user can configure a valid scene, capture frames, and export a validator-clean small dataset without source-code intervention. All planted invalid states map to actionable fields or recovery actions. | `S2.2`-`S2.6` |
| `S2.8` | **Headless and config parity.** Provide config/API/CLI equivalents and lossless configuration round-trip for every Stage 1 GUI operation. | Guided and headless runs from the same configuration produce semantically equivalent stage metadata, frames, manifests, and calibration selection after path normalization. | `S2.7` |
| `S2.9` | **Reliability closeout.** Run cancellation/restart, simulator replacement, dependency removal, disk failure, resume, and at least one 30-minute representative headless capture. | No stale frame, incomplete published shard, unreported drop, unbounded memory growth, or unrecoverable valid configuration occurs. Output passes the canonical validator. | `S2.4`, `S2.8` |

**S2 exit gate:** the same validated configuration can be operated through GUI
or headless interfaces, recordings are atomic and replayable, and long-running
SquadBot evidence capture has explicit resource and failure behavior.

### 6.6 S3 - Dynamic Acoustics Required By SquadBot

Implement each physical effect as an isolated review unit with a compatibility
off-state and additive diagnostics.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S3.1` | **Pose-derived velocity.** Derive source and array velocity from timestamped poses with first-sample, reset, teleport, stale-time, and smoothing policies. | Analytical constant-velocity fixtures match tolerance; reset/teleport never creates an extreme Doppler spike; authored velocity precedence is explicit. | `S1.7` |
| `S3.2` | **Time gaps and intra-window motion.** Preserve simulation-time gaps in session audio and define piecewise motion inside capture windows. | Known pause/throttle trajectories produce expected sample counts/silence and bounded interpolation error; non-monotonic time fails. | `S3.1`, `S2.2` |
| `S3.3` | **Channel response and mismatch.** Apply per-microphone frequency response, gain, delay, and polarity. | Impulse, tone, and broadband fixtures recover expected transfer functions; disabled modeling preserves the prior waveform within tolerance. | `S1.2`, `S1.3` |
| `S3.4` | **Seeded noise.** Add configurable spectral self-noise, ambient sources, clock jitter/drift, and deterministic stochastic-stream policy. | PSD, RMS, and delay statistics meet declared analytical tolerances; fixed seeds replay; independent streams do not accidentally correlate. | `S3.3` |
| `S3.5` | **Electronics path.** Add quantization, saturation/clipping, optional AGC, and exported AGC/clipping diagnostics. | Boundary amplitudes, recovery timing, clipping counts, and quantization noise pass; disabled electronics retain the prior baseline. | `S3.3`, `S3.4` |
| `S3.6` | **Waveform directivity.** Apply source and microphone polar/frequency response to L2/L3 waveforms rather than metadata only. | Cardinal-angle and frequency sweeps match configured patterns; invalid patterns fail; estimator tests show the expected confidence degradation. | `S3.3` |
| `S3.7` | **Materials, dynamic rooms, and occlusion.** Consume measured material parameters where available and define invalidation for moving geometry, sources, arrays, and room changes. | Clear, blocked, partial, and material fixtures keep waveform, RMS, occlusion, diagnostics, and export mutually consistent; caches never return stale acoustics. | `S3.2`, `S3.6` |
| `S3.8` | **Motion and multi-source stress.** Exercise Doppler, overlap, near/far imbalance, reverberation, occlusion, moving mounts, and source identity across supported backends. | No NaN, source identity corruption, hidden ambiguity, stale state, or unbounded resource growth occurs; unsupported combinations fail explicitly. | `S3.1`-`S3.7` |
| `S3.9` | **Fidelity envelope.** Publish effect-specific validation, performance, supported geometry, dependency requirements, and limitations. | Every Stage 1 realism claim maps to a passing fixture and off-state. Ray/transmission occlusion is not described as diffraction or a complete wave solver. | `S3.8` |

**S3 exit gate:** all physical effects needed by the planned bench, moving
robot, hallway, occlusion, and multi-source scenarios have measurable behavior
and honest limits. Optional diffraction or richer propagation remains in `P2`.

### 6.7 S4 - Functional Sim-to-Real Characterization and Validation

The entry setup is the six-channel-firmware ReSpeaker XVF3800 on the Raspberry
Pi 5, the ZED 2i and fixed workstation, the MacBook controlled source, and the
documented `S4_TEMP_DESKTOP_FIXTURE_REV0` in WANG 2022. The temporary fixture
places the ZED below the ReSpeaker at an operator-reported approximate
`90-100 mm` center-to-center separation. The Revision A Option 1 mount and
detachable steel-ballasted table base remain the digitally released, not-yet-
fabricated future design documented in
[Reference Rig Hardware And Environment](reference_rig_hardware_environment.md)
and [ZED/ReSpeaker Mount Model Handoff](zed_respeaker_mount_model_handoff.md).
The mount handoff is authoritative for that design and digital release status;
the historical [pre-CAD input lock](zed_respeaker_mount_pre_cad.md) does not
override it. S4 records the actual temporary mount identity and approximate
as-used geometry without assigning the CAD nominal transform to it. Physical
and field acceptance and measured optical/acoustic extrinsics remain separate
and are not claimed by S4.

S4 is functional testing and engineering validation, not an acoustic metrology
campaign. It preserves physical units and measurable objectives, but reports
relative, approximate, nominal, or functional quantities whenever the evidence
does not support an absolute calibrated quantity. The initial matrix uses
existing resources and expands only to resolve an observed failure, excessive
variance, unresolved decision, or uncovered required claim. Professional
speakers, dedicated interfaces, calibrated microphones, stands, a tripod,
laser distance meter, digital caliper or level, AprilTags, a turntable, SPL
meter/calibrator, and formal mount-qualification equipment are not S4
prerequisites. Later precision is claim-driven.

Every trial and result uses these evidence levels:

1. **Within-configuration repeatability:** same Mac, WAV, volume, source pose,
   distance, room, ReSpeaker, mount state, and acquisition settings.
2. **Controlled variation:** planned WAV, volume, distance, angle, and source
   position changes within a stated range.
3. **Robustness and portability:** phone, voice, ordinary objects, claps or
   impacts, occlusion, background noise, overlap, other rooms, and other
   environmental conditions. These are robustness trials, not primary
   calibration references.

Another team need not reproduce identical numbers on different hardware or in
a different room. It must be able to reproduce the method, recorded variables,
metrics, evidence structure, failure handling, and interpretation rules. Each
quantity is labeled **Verified**, **Measured**, **CAD-derived**, **Nominal**,
**Approximate**, **Unmeasured**, or **Unsupported**. Within the documented
experimental envelope, supported functional and relative measurements are
valid engineering evidence; they are not absolute, traceable,
component-isolated, metrology-grade, or universally transferable claims.

The available setup can support, with good confidence inside the documented
experimental envelope:

- relative RMS and level trends; combined source-room-sensor spectral behavior;
  echoes and relative decay/reverberation behavior;
- channel presence, order, imbalance, relative delay, TDOA, and major polarity
  anomalies;
- bearing, candidate bearing, sector accuracy, ambiguity, confidence, and
  abstention;
- capture-to-frame and frame-to-adapter latency and coarse audio-video
  association;
- functional or approximate as-used ZED/ReSpeaker geometry, supported fitted
  corrections, and functional sim-versus-real comparisons; and
- robustness to documented changes in device, source, room, distance, angle,
  occlusion, noise, overlap, volume, mounting, and environmental conditions.

Without additional evidence, S4 does not support absolute SPL, absolute
microphone sensitivity, isolated speaker or microphone frequency response,
certified room-acoustic quantities, traceable acoustic calibration, precision
optical/acoustic extrinsics, or universal hardware/room transfer.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S4.1` | **Rig, mount, geometry, and frame lock.** Lock actual devices, serials, firmware, verified six-channel order, coordinate conventions, room, clocks, acquisition topology, sources, current support/mount identity, and actual assembled condition. Record the CAD-derived nominal 90 mm ZED-to-ReSpeaker sensor-center separation and nominal mechanical transform separately from temporary or future approximate as-used geometry and any later measured/fitted extrinsic. Use supported CAD values, metric tape, printed angular reference, manual measurements, and iPhone level checks where sufficient. | The record supports bearing evaluation, sector-level audio-visual association, repeatable placement, and later Alex preparation. Before each test, verify only that the rig does not move unintentionally, remains stable, can reproduce the target pose sufficiently, leaves microphone openings and camera field of view sufficiently unobstructed, and has safe cable routing that does not disturb it. Unmeasured or unsupported values are labeled and do not block functional testing unless required by a target metric. Formal torque, adhesive, lifecycle, proof-pull, precision-deflection, or mount-metrology tests are not automatic S4 blockers, and no physical/field acceptance is claimed without its evidence. | `S0.5`, `S1.2` |
| `S4.2` | **Acquisition tool and runbook.** Capture synchronized or practically time-associated multichannel audio, ZED observations, timestamps, source metadata, pose annotations, settings, environment facts, alignment uncertainty, and operator notes. Record the exact WAV, Mac identity and volume, source position/orientation/distance, room, relevant audio settings, mount revision, and actual assembled state. Use chirps, claps, or visible impacts for practical audio-video alignment. | Dry runs reject missing or swapped channels, incomplete takes, sustained clipping, nonmonotonic timestamps, stale poses, missing required metadata, and corrupt outputs. Expensive synchronization equipment is not required when per-take alignment supports the stated metrics; timing limitations are reported. Another operator with comparable equipment can reproduce the procedure. | `S4.1`, `S2.2` |
| `S4.3` | **Pilot repeatability and functional characterization.** Start with a compact, controlled matrix covering bearing/DOA, candidate-bearing behavior, sector accuracy, TDOA, channel health/order, relative RMS/level, combined source-room-sensor spectral behavior, relative channel delay, major polarity anomalies, capture-to-frame and frame-to-adapter latency, noise, echo/relative decay, occlusion, overlap, silence, confidence, ambiguity, abstention, failures, and coarse audio-video association. Use the Mac and identical WAV/volume for direct repetitions; introduce meaningful controlled variations and separate robustness sources only as needed. | Multiple repetitions use marked or recorded poses, distances, and angles. Report every planned trial and failure without deleting unfavorable runs. Expand only for an observed failure, high variance, unresolved decision, or uncovered claim; stop when repeatability and metrics are stable, claim coverage is adequate, and added trials have diminishing information gain. Relative level, spectrum, reverb, gain, delay, polarity, and latency remain functional measurements without a calibrated reference. | `S4.2` |
| `S4.4` | **Development/fit and held-out evaluation freeze.** Build a proportional matrix and group it by leakage-relevant session, room, source device, WAV/source type, position, angle, distance, and mounting condition before final tuning. Select and hash held-out conditions that will not adjust the system. | No leakage-relevant group crosses development/fit and held-out evaluation; manifests, provenance, hashes, and access integrity are preserved. Recollection or resealing is required only for actual leakage or invalid evidence, not merely because the matrix is non-exhaustive. | `S4.3`, `S2.5` |
| `S4.5` | **Supported functional fitting.** From development/fit data only, fit functionally identifiable bearing or supported geometry corrections, relative channel delay/gain, major polarity anomalies, confidence behavior, relative timing corrections, and other supported parameters. Leave unsupported fields absent or explicitly nominal, approximate, unmeasured, or unsupported. | Synthetic recovery and residual validation pass for every fitted parameter; uncertainty and practical limitations match the evidence. Do not invent absolute SPL, absolute microphone sensitivity, isolated speaker/microphone response, certified room acoustics, or precision optical/acoustic extrinsics. The valid partial profile serializes into `ias.audio_calibration_profile.v1`; not every theoretical field needs a value. | `S4.4`, `S3.3`-`S3.6` |
| `S4.6` | **Profile and configuration application.** Apply supported profiles deterministically with strict device identity, channel order, sample rate, frame, mount/geometry identity, and applicable environment checks. Preserve explicit off/unadjusted behavior and distinguish nominal CAD geometry from measured or fitted corrections. | Disabling the functional profile leaves unadjusted behavior unchanged. Unsupported or partial fields are never applied silently; swapped, stale, incompatible, or malformed profiles fail closed. | `S4.5` |
| `S4.7` | **Functional acceptance preregistration.** Before opening held-out results, freeze bearing error, sector accuracy, candidate-bearing coverage, TDOA, repeatability, relative latency, failure rate, clipping, channel health, confidence, ambiguity, abstention, coarse audio-video association, and sim-versus-real criteria for supported metrics. | The specification states denominators, aggregation, exclusions, sample counts, median, p95, worst case, failure logic, tested environmental envelope, controlled-versus-robustness treatment, and missing/unsupported treatment. Thresholds are decision-relevant for SquadBot and Alex; absolute SPL, metrological frequency response, certified reverberation, traceable calibration, and unsupported precision-extrinsic thresholds are not required. | `S4.5`, `S4.6` |
| `S4.8` | **Held-out functional sim-to-real evaluation.** Compare real data, unadjusted simulation, and functionally adjusted simulation on supported metrics only, with controlled-source and robustness results separated. | Report and archive every sample, repetition, scenario, and failure, including median, p95, and worst case; state whether each adjustment improves, preserves, or worsens each relevant metric. Every preregistered criterion must pass for S4.8 readiness in the claimed envelope; any failed criterion keeps S4.8 and S4 failed for that envelope. No refitting, result-driven threshold change, or selective scenario removal is allowed. If a narrower envelope is proposed after a failure, preregister new criteria and evaluate them on a new, previously unseen holdout; retain the original failed evidence. | `S4.7` |
| `S4.9` | **Replayable functional evidence package.** Package the functional profile/configuration, recordings, manifests, metrics, complete trial inventory, failure records, mount/geometry and environment records, limitations, hashes, reproduction commands, supported/unsupported field declarations, and explicit package status, including references to nominal CAD geometry and measured or fitted corrections. | A clean consumer can replay the evidence and recover the declared results. Every failure remains archived. The package distinguishes relative/functional measurements, nominal mechanical geometry, approximate as-used geometry, measured or fitted corrections, any absolute calibrated quantities, and unsupported quantities. S4.9 is passing readiness evidence only when S4.8 passed every preregistered criterion for the claimed envelope; a failed evidence package remains useful for diagnosis but cannot satisfy the S4 exit gate or feed S5 as passing readiness evidence. | `S4.8` |

**S4 exit gate:** S4.8 and S4.9 pass for the claimed envelope, and the available
rig has a versioned, repeatable functional-characterization workflow and
preregistered sim-vs-real evidence suitable for SquadBot bench work and Alex
preparation. All planned failures are retained. A failed package cannot close
S4; narrowing an envelope after failure requires new preregistered criteria and
a new, previously unseen holdout.

### 6.8 S5 - SquadBot Phases 7-15 Readiness Matrix

All S5 fixtures consume installed artifacts and test generic sensor outputs.
Downstream ontology, graph decisions, vision, fusion, intent generation,
actuation, locomotion, and safety remain outside this repository.
Generic mounting, moving transforms, localized and ambiguous cues, silence,
stale data, visual joins, motion, hallway/multi-area conditions, occlusion,
overlap, long sessions, identity, timestamps, and bounded resource use remain
required. S5 introduces no expensive equipment unless an observed failure or a
required claim demonstrates the need.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S5.1` | **Phases 7-8 bench readiness.** Consume a passing S4.8/S4.9 functional package and export/replay rig recordings, supported profiles/configurations, and comparable sim/real traces through the external adapter. Fixtures exercise only fields S4 supports; unsupported absolute calibration fields remain absent or explicitly unsupported. | The input package passed every preregistered criterion for its claimed envelope. Timestamps, frames, source ids, ambiguity, provenance, supported-field status, and metric joins survive the boundary; physical transport and graph policy remain external. Failed S4 packages may be retained as diagnostic fixtures but cannot satisfy S5.1 readiness. | `S4.9`, `S1.8` |
| `S5.2` | **Phase 9 mounting readiness.** Provide a generic example that discovers or mounts an array on a selected robot link and records finite moving transforms. | A clean Isaac run proves mount identity, child microphones, coordinate convention, and trace/config export without robot-specific frame fields. | `S3.1`, `S1.8` |
| `S5.3` | **Phase 10 orientation-input readiness.** Supply localized, explicitly ambiguous, silent, stale, and moving-array cue sequences with latency/confidence evidence. | The external orientation adapter receives stable ordered inputs; ambiguous/nonlocalized cases never invent direction; no actuation enters the sensor. | `S5.2`, `S3.8` |
| `S5.4` | **Phase 11 visual-join readiness.** Prove that source/frame ids, poses, timestamps, labels, and provenance join deterministically to external visual/graph fixtures. | Join inputs are stable across replay; visual classes, confirmation state, and graph links remain external. | `S5.3` |
| `S5.5` | **Phase 12 moving-robot readiness.** Run capture while the mounted array rotates and translates through valid, timeout, stop, and stale-transform scenarios. | Sensor continuity, timestamps, identity, latency, and resource use remain bounded; robot approach and stopping behavior are not implemented here. | `S3.8`, `S5.4` |
| `S5.6` | **Phase 13 scaled readiness.** Run hallway/multi-area, outside-FOV, overlap, occlusion, reverberation, and long-session scenarios. | No stale transform, identity corruption, silent frame loss, unbounded memory, or contract drift occurs; each failure mode remains separately measurable. | `S2.9`, `S5.5` |
| `S5.7` | **Phases 14-15 practical Alex handoff readiness.** Package portable functional configurations, replay fixtures, expected generic outputs, measured compute/network latency, and blocker templates. Include a lightweight procedure to record the ReSpeaker pose relative to Alex's actual installed camera, with the camera model verified from unit-specific or live authoritative evidence. Distinguish the bench ZED 2i/ReSpeaker assembly from the Alex installation; never reuse the bench nominal transform automatically. | The package contains no unsafe command assumption, transport requirement, or actuation code and can validate interfaces when robot access is unavailable. A simple non-permanent Alex installation is acceptable when stable, safe, documented, and repeatable enough; unsupported automatic bench-to-Alex transfer fails closed. | `S5.1`, `S5.6` |
| `S5.8` | **Installed-artifact matrix closeout.** Run nominal, empty, malformed, ambiguity, overlap, motion, supported-profile/configuration, compatibility, and replay cases through `AudioSensorFrame -> protobuf -> AuditoryCue -> MiniSceneGraph`. | Every supported case passes from immutable installed artifacts; schema version, ids, timestamps, order, units, ambiguity, provenance, and fail-closed behavior are preserved; malformed or incompatible inputs produce no partial use; generic exports contain no downstream leakage. | `S5.1`-`S5.7` |

**S5 exit gate:** a passing S4.8/S4.9 package underlies S5.1, and installed
generic artifacts demonstrate every sensor-owned capability required by the
downstream Phase 7-15 plans before those phases begin. A failed S4 package
cannot satisfy S5 readiness.

### 6.9 S6 - SquadBot-Ready Release Gate

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `S6.1` | **Readiness CI matrix.** Encode pure, schema, build, archive, Linux clean install, Isaac Sim/Lab/GPU, operational GUI, archived S4 functional-evidence replay, endurance, and cross-repository gates with explicit runner requirements. | Software CI replays archived S4 evidence and does not require a physical Mac, ReSpeaker, or ZED on every runner. Required hardware jobs name explicit runners or classified blockers; blanket skips cannot pass, and archived evidence remains reusable for regression and compatibility testing. | `S1.8`, `S2.9`, `S3.9`, `S4.9`, `S5.8` |
| `S6.2` | **Immutable candidate.** Build checksummed wheel, base Kit archive, Linux acoustic packs, schemas, the S4 functional package, S5 fixtures, and evidence manifest from one clean revision. | The complete S6 matrix runs against those exact artifacts rather than the worktree; artifact contents and hashes are reproducible and import provenance is installed-only. | `S6.1` |
| `S6.3` | **Evidence and limitations index.** Map each Stage 1 claim to tests, live artifacts, functional sim-to-real results, environment facts, tested envelope, and known limits. | No unsupported claim, unresolved critical defect, unclassified skip, or missing reproduction command remains. The index does not imply absolute acoustic calibration, universal hardware/room transfer, metrology-grade extrinsics, or public publication. | `S6.2` |
| `S6.4` | **SquadBot development freeze.** Declare the immutable artifact set and patch policy used during Stage 2. | Downstream installation instructions reference only the frozen artifacts; no public registry publication or final cross-platform claim is implied. | `S6.3` |

**S6 exit gate:** a research-quality Linux sensor artifact, S4 functional
evidence package, and S5 fixture set are honestly ready to support SquadBot and
Alex development. Windows, advanced propagation, final training scale,
production usability validation, public publication, absolute acoustic
calibration, universal device/room transfer, and metrology-grade extrinsics
remain explicitly unclaimed or deferred.

### 6.10 Stage 2 - SquadBot Validation Interlude

Stage 2 is owned and executed by `squadbot-av-phase1`. This roadmap records the
sensor input and feedback contract; it does not authorize the sensor agent to
modify that repository.

| Checkpoint | Downstream execution | Frozen sensor input | Feedback accepted by this repository |
| --- | --- | --- | --- |
| `V7-8` | Physical bench, message/graph path, functional sim-to-real validation, and review evidence. | S6 artifacts, S4.9 functional package, S5.1 fixtures. | Reproducible sensor defects, profile/configuration incompatibilities, measured limitations, and evidence gaps. |
| `V9-11` | Alex bring-up, orientation behavior, visual confirmation, and graph linking in simulation. | Same S6 artifact or a versioned patch, S5.2-S5.4 fixtures. | Moving-transform, latency, ambiguity, metadata, or lifecycle defects in generic outputs. |
| `V12-13` | Mobile simulation and hallway/multi-area scaling. | Same artifact line, S5.5-S5.6 scenarios. | Sensor continuity, Doppler, occlusion, identity, performance, or long-run defects. |
| `V14-15` | Real torso/mobile Alex validation using Alex's actual installed camera when available, or accepted downstream blocker reports. | Portable S5.7 package and the latest verified S6-compatible artifact. | Installed timing, compute/network behavior, self-noise, motion, occlusion, robustness, functionally sufficient installed geometry, real-device compatibility facts, and generic sensor defects; robot safety, transport, control, and access blockers remain external. |

The authoritative local evidence currently documents only a head location and
routed GMSL cable intended for a possible ZED X Mini, with no delivered camera
or mount verified at the time of that record. V14-15 must therefore confirm the
actual Alex camera model from the unit-specific model, approved robot records,
or live hardware inventory before planning the installed geometry; it must not
assume that the documented intended model is installed. The bench ZED 2i is not
mounted on Alex when Alex already has an appropriate camera.

For the final robot configuration, remeasure only the ReSpeaker-to-installed-
camera relationship and facts that materially change from the bench. Retain
still-applicable bench evidence. A simple non-permanent ReSpeaker installation
is acceptable when stable and safe for the planned test; straps, cosmetic cable
management, or specialized mounting hardware are required only when actual
safety or stability evidence shows a need. Real installed-system timing,
compute, network, self-noise, motion, occlusion, and robustness matter more than
bench-grade absolute SPL. More precise equipment is introduced only for a
specific final claim or observed blocker. Robot safety, command boundaries,
stale-data handling, ambiguity, abstention, complete failure reporting, and the
generic-sensor/downstream-behavior boundary remain mandatory.

#### Controlled Sensor Patch Policy

During Stage 2:

1. classify each finding as sensor defect, downstream defect, documented
   limitation, or future public feature;
2. patch only reproducible sensor-owned correctness, compatibility, reliability,
   or performance defects;
3. preserve `ias.audio_sensor_frame.v1` and the frozen generic/downstream
   ownership boundary;
4. add a regression fixture and focused test for every sensor patch;
5. rebuild immutable artifacts and rerun the complete S6 matrix;
6. version the replacement artifact and update downstream installation evidence;
7. defer new optional features and publication polish to Stage 3.

Stage 2 closes after `V14-15` completes under its downstream plan, including an
accepted blocker report when robot access or safe execution is unavailable.

### 6.11 P0 - SquadBot Findings Consolidation

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P0.1` | **Evidence ingestion.** Collect real Stage 2 closeouts, blocker reports, patch histories, metrics, and representative fixtures into a traceable findings inventory. | Every reported issue links to its exact originating artifact, version, S4 package/S5 fixture where applicable, and reproduction evidence; unverifiable findings remain explicitly unverified. | Stage 2 closeout |
| `P0.2` | **Ownership classification.** Classify every finding as sensor defect, downstream defect, limitation, or future feature. | Each classification cites the public boundary and has one owner; robot-specific behavior is not moved into the sensor. | `P0.1` |
| `P0.3` | **Regression consolidation.** Fix remaining sensor defects and convert reproducible real integration failures into minimal permanent fixtures while retaining exact artifact and reproduction provenance. | Focused and S6 regression suites pass; frame v1 meaning is unchanged; any new contract is additive or separately versioned; unverified findings are not silently converted into truth. | `P0.2` |
| `P0.4` | **Final acceptance freeze.** Reconcile Stage 2 evidence with the S0 public specification and lock final metrics, supported runtimes/platforms, functional-envelope claims, and release gates before inspecting final holdout evidence. | Every P-phase output and final claim has a measurable gate and tested envelope; no threshold or claim is chosen after seeing its final holdout evidence. | `P0.3` |

### 6.12 P1 - Scalable Isaac Lab Training And Dataset Production

Performance, training, dataset, and scale claims remain tied to recorded
workload conditions and supported scenarios. S4 functional evidence cannot be
used to imply universal acoustic fidelity, device transfer, or room transfer.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P1.1` | **Additive Lab observations.** Add elevation, range, occlusion, masks, and optional feature tensors with fixed shapes, device-aware allocation, reset, selected update, and observation export. | CPU/import-safe and live GPU tests verify shapes, dtypes, padding, device placement, reset, selected-row isolation, and backward-compatible existing keys. | `P0.4`, `S1.3` |
| `P1.2` | **Fast-profile parity.** Route L0/L1 batched computation through `training_features` without waveform or per-environment frame allocation. | Scalar and batched outputs match declared tolerances; profiling proves the steady-state fast path avoids forbidden allocations. | `P1.1` |
| `P1.3` | **Reference performance gate.** Optimize and measure 4,096 environments, four microphones, two events, and 50 post-warm-up steps on the RTX 4090 reference host. | At least three runs report raw samples, mean, median, p95, worst, memory, driver, and compute path; every run meets p95 `<= 20 ms`. | `P1.2` |
| `P1.4` | **Replicator parity.** Map Replicator capture into the canonical session/writer contracts without creating a second dataset truth. | Direct and Replicator capture of seeded frames are semantically equivalent after path normalization; Replicator remains optional. | `S2.4` |
| `P1.5` | **Large-corpus tools.** Add optional Parquet indexing, streaming queries, shard catalogs, and scalable split/validation operations. | JSONL plus lossless audio remains canonical; indexes can be regenerated; large operations stay inside the P0 memory/throughput specification. | `S2.5` |
| `P1.6` | **Scale and endurance closeout.** Run GPU performance, large capture, interruption/resume, validation, split-leakage, and replay scenarios with resource telemetry. | Performance gate passes; manifests/checksums are valid; memory is bounded; no leakage or unreported dropped frame occurs; seeded resume is deterministic. | `P1.3`-`P1.5` |

### 6.13 P2 - Final Realism And Extensibility

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P2.1` | **Advanced propagation plugin.** Add diffraction or a richer wave model only through `PropagationBackend` with explicit geometry, dependency, device, and performance limits. | The backend passes common contracts and analytical or trusted-reference cases without changing L0-L3 identifiers or base availability. | `P0.4`, `S1.3` |
| `P2.2` | **Expanded materials and rooms.** Extend measured material coverage, dynamic-room scenarios, and multi-backend comparison beyond the Stage 1 SquadBot envelope. | New material/room claims have isolated fixtures, uncertainty, cache-invalidation tests, and honest unsupported-region behavior. | `S3.9` |
| `P2.3` | **Public functional characterization toolkit.** Generalize acquisition, supported fitting, validation, compatibility, evidence generation, field-status declarations, and claim-envelope reporting into reusable APIs and wizard controllers while retaining the reference-rig regression. | A new compatible device can follow the documented functional workflow without project-specific code; incompatible profiles fail before application; reference results remain reproducible. Metrology-grade requirements are added only if an advertised capability requires them. | `S4.9` |
| `P2.4` | **Platform acoustic packs.** Finalize versioned Linux and Windows L2/L3/advanced packs with capability discovery and mismatch rejection. | Install/remove/update, version mismatch, unsupported platform, and missing dependency scenarios pass independently of the base extension. | `P2.1`, `P2.2` |
| `P2.5` | **Fidelity closeout.** Publish backend-specific effects, approximations, functional characterization envelope, accuracy, resource use, and unavailable-capability behavior. If absolute SPL, isolated component response, certified room acoustics, precision calibrated extrinsics, or universal calibrated transfer becomes advertised, add the necessary equipment and validation as an explicit claim-driven requirement; otherwise publish the functional envelope honestly. | Every advertised backend/effect maps to tests and evidence; advanced models do not inflate base or reference-rig claims. | `P2.1`-`P2.4` |

### 6.14 P3 - Production GUI

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P3.1` | **Final UX specification.** Use S2 and Stage 2 evidence to refine personas, navigation, progressive disclosure, persistent state, cancellation, recovery, and wireframes. | Every existing control maps to Guided, Advanced, removed, or headless-only; no valid capability is lost accidentally. | `P0.4`, `S2.9` |
| `P3.2` | **Guided workflows and wizards.** Complete presets plus setup, stage validation, functional characterization/profile, dataset, recording, and export wizards on the shared controllers. Guide users to record their source, room, device, mount/pose, settings, uncertainty, and supported/unsupported quantities. | First-time paths prevent invalid starts, preserve valid state, expose prerequisites, emit validator-clean artifacts, and never present nominal or approximate values as measured calibration. | `P2.3`, `P3.1` |
| `P3.3` | **Diagnostics and accessibility.** Complete instruments, performance/backpressure indicators, waveform/spectrogram/event inspection, accessible errors, keyboard/readability review, and recoverable actions. | Stale/error state is never shown as current/success; UI cost meets the P0 budget; planted failures have understandable recovery. | `P3.2` |
| `P3.4` | **Advanced mode and migration.** Preserve every expert field, support lossless config round-trip, and migrate prior extension configurations additively where possible. | Old fixtures import to equivalent state; Guided and Advanced edits stay synchronized; unknown/removed fields produce explicit migration findings. | `P3.2` |
| `P3.5` | **Final headless parity.** Rerun semantic comparison across config/API/CLI and all Guided workflows. | Equivalent inputs produce matching stage metadata, frames, manifests, calibration, and exports after documented normalization. | `P3.3`, `P3.4` |
| `P3.6` | **Usability gate.** Run Kit UI automation/screenshots, cancellation/restart scenarios, accessibility review, and the five-person first-use study. | At least four of five unfamiliar evaluators install, configure, capture, and export a valid dataset within ten minutes without source code or terminal use; blocking findings are fixed and rerun. | `P3.5` |

### 6.15 P4 - Cross-Platform Release Hardening

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P4.1` | **Current-runtime CI.** Finalize pure, schema, build, Linux/Windows install, Sim/Lab/GPU, GUI, performance, acoustic-pack, advertised functional-characterization/calibration, dataset, and cross-repository jobs with explicit runners. | Only advertised capabilities are tested as release claims; required jobs cannot pass by blanket skip, hardware-dependent claims name supported runner environments, repeated runs are stable, and artifacts/blocker records are retained. | `P1.6`, `P2.5`, `P3.6` |
| `P4.2` | **Windows clean install.** Install base and supported packs into the current Windows Isaac runtime and run lifecycle, GUI, examples, capture/export, update, and removal. | Windows satisfies the same declared contracts; platform-specific limitations are explicit and tested. | `P2.4`, `P4.1` |
| `P4.3` | **Supply-chain hardening.** Generate SBOM, dependency/license inventory, checksums/signatures where supported, vulnerability review, and reproducible archive manifests. | Audits cover base and every pack; undeclared binary, dependency, private content, or unsafe archive path fails the build. | `P4.1` |
| `P4.4` | **Documentation and support.** Finalize installation, quickstart, GUI, API/contracts, datasets, functional characterization/calibration limits, examples, troubleshooting, security, support window, and deprecation/migration policy. | Fresh-user walkthrough succeeds; advertised claims, supported configurations, versions, commands, links, failure modes, and known limitations agree with evidence. | `P4.2`, `P4.3` |
| `P4.5` | **Registry-readiness dry run.** Recheck current Kit metadata/target rules and Community Registry discovery, naming, documentation, and archive requirements. | Install-from-release dry run passes from exact candidate-style artifacts; only explicit publication actions remain. | `P4.4` |

### 6.16 P5 - Publication And Maintenance

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `P5.1` | **Final candidate rehearsal.** Build immutable candidate artifacts and run the complete P4 matrix from those exact archives rather than the worktree. | Every advertised capability and platform passes inside its declared envelope; the evidence index maps claims, limitations, supported configurations, reproduction procedures, and provenance to artifact hashes; any failed gate rejects the candidate. | `P4.5` |
| `P5.2` | **Python and Kit artifact publication.** Publish audited Python artifacts through PyPI/GitHub and audited Linux/Windows Kit archives with accurate base/optional capability and functional-envelope statements. | Clean external installs match candidate checksums and smoke results; published material does not overstate absolute acoustic fidelity; rollback/yank procedures exist before announcement. | `P5.1` |
| `P5.3` | **Community Registry publication.** Publish correctly named platform artifacts and metadata and verify discovery/install from a clean registry client. | The listing installs the exact audited artifacts, advertises only the supported functional envelope, links limitations and evidence provenance, and clearly states community support rather than NVIDIA product support. | `P5.2` |
| `P5.4` | **Post-release maintenance start.** Rerun install/update smoke, archive evidence, triage release issues, finalize changelog, and schedule the next runtime compatibility review. | No critical packaging or contract regression remains open; hotfixes reuse the candidate gates; support and evidence indexes are active. | `P5.3` |

### 6.17 Former-To-New Coverage

The former `M` identifiers are retired and must not be used for new assignments.
This table exists only to prove that restructuring did not drop a requirement.

| Former area | New owner | Coverage |
| --- | --- | --- |
| `M0` baseline and measurement | `S0` | Pure/live/performance baselines, hardware inventory, and acceptance specifications. |
| `M1` distribution | `S1`, `P2`, `P4`, `P5` | Stage 1 Linux artifacts first; platform packs, Windows, registry, and publication later. |
| `M2` contracts and plugins | `S1`, `P1` | Dataset/calibration/runtime/plugin contracts before SquadBot; expanded Lab tensors during final scale work. |
| `M3` training and datasets | `S2`, `P1` | Reliable recording/replay/splits before SquadBot; 4,096-env optimization, Replicator, and large-corpus tools later. |
| `M4` L3 realism | `S3`, `P2` | Downstream-required motion/electronics/material effects first; optional advanced propagation and broader validation later. |
| `M5` L4 calibration | `S4`, `P2` | Functional reference-rig characterization before SquadBot; reusable public tooling and claim-driven higher-precision validation later. |
| `M6` GUI | `S2`, `P3` | Operational guided workflow before SquadBot; production UX, migration, accessibility, and user study later. |
| `M7` SquadBot/Alex readiness | `S5`, Stage 2 | All generic fixtures before Phase 7; actual downstream execution remains external. |
| `M8` release and maintenance | `S6`, `P4`, `P5` | Internal research freeze before SquadBot; full hardening and publication after downstream validation. |

## 7. Test And Acceptance Matrix

### 7.1 Planned Test Artifacts

Add focused modules as their contracts land:

- `tests/test_dataset_manifest.py`
- `tests/test_calibration_profile.py`
- `tests/test_backend_plugins.py`
- `tests/test_runtime_profiles.py`
- `tests/test_dataset_pipeline.py`
- `tests/test_gui_guided_workflow.py`
- `tests/test_kit_extension_package.py`
- `tests/test_cross_repo_consumer.py`

Use explicit `sim`, `gpu`, `hardware`, `windows`, and `cross_repo` markers for
checks that cannot run in the pure test environment. Every skip records a
specific reason and the host-visible command or external action that supplies
the missing evidence.

### 7.2 Required Scenarios

| Level | Minimum cases | Pass criteria |
| --- | --- | --- |
| Contract/unit | nominal, boundary, invalid, and regression | schemas and validators preserve units, frames, shapes, ids, versions, compatibility, and error semantics |
| Determinism/property | repeated seed, shuffled input, transform round-trip, JSONL replay | stable ordering and hashes where promised; floating/GPU differences remain inside documented tolerances |
| Acoustic | silence, inactive source, noise, overlap, ambiguity, motion, Doppler, occlusion, reverberation, invalid geometry | no invented direction, hidden ambiguity, NaN, identity corruption, or silent fallback |
| Dataset | tiny round-trip, long stream, interruption, resume, corrupt asset, duplicate/non-monotonic time, split leakage | valid data has zero violations; corruptions are detected; memory is bounded; manifests are deterministic |
| Isaac Sim | stage open/close, rediscovery, moving mount, multiple sources, recording, optional pack missing | lifecycle recovers, poses stay current, frames are not stale, exports validate, and errors are actionable |
| Isaac Lab GPU | allocation, selected reset/update, device mismatch, Stage 1 observation smoke, final 4,096-env gate | buffers use the declared device, unaffected rows remain unchanged, and the phase-specific performance gate passes |
| GUI | Stage 1 operational path, final first-use study, Advanced round-trip, invalid input, cancellation, restart | outputs match headless semantics, valid state is preserved, and the P3 usability target passes |
| Hardware | channel swap, practical mount checks, pilot repeatability, grouped fit/holdout sweeps, stale profile, controlled and robustness variation | incompatible profiles fail closed; every trial/failure is inventoried; supported relative/functional metrics, evidence labels, and uncertainty reproduce inside the tested envelope |
| Cross-repository | installed artifact, empty/malformed frame, multi-source, two-mic ambiguity, motion, trace replay | adapter output is deterministic, generic schema remains unchanged, and failures are explicit |
| Distribution | Linux research artifact, Windows final artifact, missing pack, update/removal, registry install | installed contents match audited hashes and capability statements |

### 7.3 Stage Gates

| Gate | Required evidence |
| --- | --- |
| **S6 SquadBot-ready** | Pure/live tests, Linux clean install, installed-artifact consumer chain, operational GUI/headless parity, dataset reliability, S3 fidelity envelope, replayable S4 functional holdout package, S5 fixture matrix. |
| **Stage 2 checkpoint** | Downstream closeout or accepted blocker report using the exact S6-compatible artifact; any sensor patch includes regression and rerun evidence. |
| **P5 final public** | P1 performance/scale, P2 fidelity, P3 usability, Linux/Windows install, supply-chain/security/docs, candidate rehearsal, public install verification. |

### 7.4 Canonical Verification Commands

Existing gates remain:

```bash
make test
make lint
make build
make import-smoke
make live-isaac-sim-audio
make live-isaac-lab-audio-gpu
make live-omniverse-extension-ux
make live-evidence-report
```

As phases land, add stable make targets for schema validation, dataset
validation, clean Kit install, calibration replay, installed-artifact
cross-repository checks, Stage 1 readiness, final performance, Windows
validation, and release rehearsal. Closeouts must cite maintained targets;
ad hoc shell history is not sufficient release evidence.

## 8. Failure And Recovery Requirements

The Stage 1 and final products must deliberately handle:

- no stage, deleted/replaced prim, simulator restart, or stale discovery cache;
- invalid/missing microphone geometry, degenerate array, frame mismatch, NaN,
  impossible sample rate, negative timestamp, or unknown schema/profile;
- unavailable GPU, wrong tensor device, missing acoustic pack, or unsupported
  platform/runtime;
- corrupt/partial audio, checksum mismatch, partial manifest line, disk-full,
  interrupted shard, slow writer, or non-monotonic time;
- calibration channel, sample-rate, device, frame, or environment mismatch;
- GUI cancellation, invalid field text, failed start/export, stale selection,
  or dependency removal;
- missing physical rig, Alex, or IHMC access in an otherwise valid offline
  compatibility run;
- Stage 2 defect reports that cannot be reproduced from the claimed artifact.

Failures must leave resources closable, preserve the last valid configuration,
avoid publishing incomplete artifacts, and return actionable messages. A
fallback must be explicitly selected and recorded; it must not silently change
provenance, device, fidelity, bearing, ambiguity, or calibration semantics.

## 9. Release Gates And Final Definition

### 9.1 SquadBot-Ready Research Release

Stage 1 closes only when:

- the Linux base and supported acoustic packs install without a checkout;
- current Isaac Sim 6.x and Isaac Lab 3.x live gates pass or have explicit
  non-claim blockers;
- frame v1 remains compatible and Stage 1 contracts are frozen;
- recording, replay, validation, operational GUI, and headless parity pass;
- downstream-required dynamic acoustics have focused validation;
- the documented functional rig passes its preregistered supported holdout
  criteria and reports every failed trial or criterion honestly;
- installed artifacts pass every S5 downstream-readiness fixture;
- S6 artifacts, checksums, evidence index, limitations, and patch policy exist.

This release is an internal research artifact. It is not listed in the
Community Registry and makes no Windows, final training-scale, production
usability, absolute acoustic-calibration, universal device/room-transfer, or
metrology-grade extrinsic claim.

### 9.2 Validation Interlude And Patch Line

The frozen Stage 1 artifact is the default input for all downstream Phase 7-15
work. A replacement is allowed only for a reproduced sensor defect. Every
replacement preserves public contracts, adds regression coverage, receives a
new versioned identity/checksum, and reruns S6.

Downstream robot/hardware access can close with the blocker evidence allowed by
its own phase plan. Such a blocker does not become passing real-robot evidence,
but it does not prevent Stage 3 when the generic sensor fixture matrix remains
valid.

### 9.3 Final Public Release

The final target is reached only when:

- Stage 2 sensor findings are resolved or documented;
- both runtime profiles and the 4,096-environment p95 `<= 20 ms` gate pass;
- scalable dataset, Replicator, and optional indexing tools pass;
- advanced backends and acoustic packs have honest platform/fidelity limits;
- the reference functional-characterization workflow remains reproducible
  through public tooling, with any later absolute calibration capability gated
  by the equipment and evidence its advertised claim requires;
- production GUI, Advanced migration, accessibility, recovery, and headless
  parity pass the five-user gate;
- Linux/headless and Windows GUI clean-install evidence exists;
- build, archive, SBOM, license, security, documentation, support, deprecation,
  and release-evidence checks pass;
- exact audited artifacts are published through PyPI, GitHub, and the
  [Kit Community Registry](https://docs.omniverse.nvidia.com/kit/docs/kit-registry-reference/latest/community/extensions.html);
- the listing is described as community-provided rather than an
  NVIDIA-supported product.

Recheck the current
[Kit extension configuration and target rules](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/)
and registry process immediately before P4/P5 release work.

## 10. Locked Decisions

- Delivery order: SquadBot-ready sensor, downstream Phase 7-15 validation, then
  final public product.
- First gate: research-quality Linux baseline, not a minimal prototype or a
  near-public beta.
- Numbering: `S` phases for SquadBot readiness, `V` checkpoints for external
  validation, and `P` phases for final productization; former `M` identifiers
  are retired.
- Repository ownership: sensor implementation remains here; downstream
  execution and robot-specific changes remain in `squadbot-av-phase1`.
- Distribution: immutable internal Stage 1 artifacts, then PyPI, GitHub, and
  Kit Community Registry publication at P5.
- Compatibility: current Isaac Sim 6.x and Isaac Lab 3.x; no older-major
  support promise.
- Platforms: Linux/headless first; Windows is mandatory for the final
  cross-platform claim.
- Packaging: self-contained L0/L1 base plus optional versioned acoustic packs.
- Contracts: preserve `ias.audio_sensor_frame.v1`; dataset, calibration,
  runtime-profile, and plugin contracts land before SquadBot execution.
- Product boundary: sensor SDK and plugin hooks, not learned classification,
  ontology, graph policy, vision, robot behavior, locomotion, or safety.
- Runtime strategy: fast batched feature observations and separate
  waveform-fidelity capture.
- Dataset: JSONL manifest plus lossless multichannel WAV/FLAC; Parquet is an
  optional derived index.
- Functional sim-to-real: reusable tooling validated first on the documented
  ReSpeaker/ZED development rig using within-configuration repeatability,
  controlled variation, and robustness evidence; array-specific ambiguity,
  evidence status, uncertainty, and unsupported quantities remain explicit.
- GUI: operational guided workflow before SquadBot, production usability and
  accessibility before public release, with headless parity throughout.
- Advanced propagation: optional Stage 3 plugin, not a SquadBot-readiness gate.
- ROS 2: optional later integration, not a core gate.
- Scheduling: dependency and evidence gates rather than calendar dates.
