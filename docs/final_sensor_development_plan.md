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
5. calibrate a simulated array against a documented physical reference rig;
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

The current package release is `1.7.0`; the independent frame schema remains
`ias.audio_sensor_frame.v1`.

| Area | Status | Current evidence and boundary |
| --- | --- | --- |
| Core contract | **Verified** | Stable `AudioSensorFrame` v1, JSON Schema, JSON/JSONL round-trip, units, poses, provenance, and deterministic event ordering. See [API Freeze](api_freeze_0_1.md). |
| L0 geometry | **Verified** | `geometry_only` provides deterministic bearing, elevation where observable, distance, sector, and RMS proxies. |
| L1 synthetic TDOA | **Verified** | `tdoa_synthetic` provides delays, RMS, deterministic stress controls, confidence, and explicit ambiguity. |
| L2 room acoustics | **Verified, optional** | `room_acoustics` and `room_acoustics_srp` generate approximate room waveforms and GCC/SRP estimates when optional dependencies are installed. |
| L3 realism | **Partial** | Material-aware per-microphone ray/transmission occlusion exists. Diffraction, calibrated materials, hardware response, richer noise, and other advanced effects remain incomplete. |
| L4 calibration | **Target** | The fidelity vocabulary exists, but no stable calibration artifact or automatic sim-vs-real workflow is implemented. |
| 3D DOA and motion | **Partial** | Rank-aware 3D DOA, elevation, SRP-PHAT, and explicitly authored Doppler velocities exist. Automatic velocity derivation and intra-window motion do not. |
| Isaac Sim | **Verified** | Lazy stage discovery, live transforms, moving arrays/sources, occlusion, overlays, JSONL/WAV output, and lifecycle handling exist. |
| Isaac Lab | **Verified** | `SensorBase` integration, fixed-shape multi-environment tensors, GPU placement, stage/entity binding, reset, and selected-environment updates exist. |
| Training performance | **Verified locally** | The machine-local GPU artifact reports 4,096 environments at p95 `13.09 ms` for the batched L1 path against a `20 ms` budget. This is a reference-host observation, not a portable performance promise. |
| GUI | **Partial** | The extension supports authoring, discovery, live control, instruments, audio preview, debug geometry, recording, and export. The current section-heavy interface is not yet the final guided experience. |
| Dataset recording | **Partial** | JSON/JSONL, WAV, continuous sessions, and an optional Replicator writer exist. A dataset-level manifest, atomic shards, validation, and split tooling do not. |
| Distribution | **Partial** | The Python package has wheel/sdist auditing. The Kit entrypoint still finds `src/` from a checkout, so a registry archive is not yet self-contained. |
| Alex demonstration | **Partial evidence** | A live showcase mounts an array on Alex and demonstrates DOA-driven turning and occlusion. It is a demonstrator, not the full downstream phase acceptance chain. |
| SquadBot adapter | **External, verified consumer** | The sibling project converts released frame types into its protobuf, auditory cue, ontology candidate, and graph contracts. Those contracts remain outside this package. |

### 3.1 Highest-Priority Gaps

1. Produce a self-contained Kit package and clean-install evidence.
2. Freeze dataset, calibration, plugin, and runtime-profile contracts.
3. Keep the fast Isaac Lab path while adding scalable dataset capture.
4. Complete and validate the intended L3 physical effects.
5. Build an L4 calibration workflow around a measured reference rig.
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

### 4.5 Calibration Profile Contract

Add `ias.audio_calibration_profile.v1` containing:

- profile id/version, device and channel identity, reference-rig BOM, and
  measured microphone geometry;
- coordinate frames, units, sample rate, temperature, speed-of-sound policy,
  and environment description;
- per-channel gain, delay, polarity, frequency response, self-noise, and usable
  frequency range;
- source/speaker identity, pose measurement method, reference signal, and
  acquisition procedure;
- fitted model parameters, fit/holdout metrics, applicability limits, and
  uncertainty;
- raw-measurement manifest references, checksums, tool version, and timestamp;
- explicit indication of unmeasured or unsupported fields.

Calibration application must be deterministic, validate channel identity and
sample rate, and reject incompatible profiles rather than partially applying
them.

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

## 5. Evidence-Gated Milestones

Every milestone closeout must record:

- entry revision and dependency versions;
- exact commands and environment;
- pass/fail/blocked status for every gate;
- metrics with denominators and tolerances;
- artifact paths and checksums;
- known limitations and the next milestone's input contract.

### M0 - Baseline And Measurement Lock

**Objective:** turn the current repository state into a reproducible baseline
before changing contracts or claims.

**Work:**

- run the pure test, lint, build, import-smoke, schema, distribution, Isaac Sim,
  Isaac Lab GPU, extension UX, and optional L2 gates;
- record the exact Isaac Sim 6.x and Isaac Lab 3.x pair used for the release
  line;
- preserve the 4,096-environment benchmark scenario and raw timing samples;
- inventory the Raspberry Pi, audio interface, microphones, speaker, mounts,
  room, measurement tools, and available 4+ microphone upgrade options;
- create the benchmark and calibration protocol documents before choosing
  claim thresholds.

**Exit gate:** all software gates pass or have exact blocker records; the
reference benchmark and hardware inventory are versioned; no current
capability is represented as stronger than its evidence.

### M1 - Self-Contained Distribution

**Objective:** install and run the base sensor without a repository checkout.

**Work:**

- build the Kit extension from the same source used by the Python wheel;
- remove checkout-relative `sys.path` behavior from the distributed artifact;
- include L0/L1, the GUI, schemas, presets, examples, and required pure-Python
  code in the base archive;
- package compiled L2/L3 dependencies as separately versioned,
  platform-specific acoustic packs with clear capability discovery;
- add Kit target metadata for the supported current runtime;
- gate Linux workstation and headless install first, then Windows GUI install
  for the cross-platform final release.

**Exit gate:** on a clean machine, the archive is discovered, installed,
enabled, and runs an L0/L1 example without a checkout or manual package
installation. Missing acoustic packs disable only their capabilities and show
an actionable message.

### M2 - Contract And Plugin Freeze

**Objective:** land the new extension points without breaking frame v1.

**Work:** implement and document the dataset manifest, calibration profile,
runtime profiles, plugin protocols, registry validation, and additive Isaac Lab
buffers.

**Exit gate:** checked-in JSON Schemas match generated schemas; valid fixtures
round-trip; malformed versions, units, timestamps, channel orders, checksums,
and plugin declarations fail clearly; older v1 frame fixtures remain valid.

### M3 - Efficient Training And Dataset Pipeline

**Objective:** support high-throughput observations and reliable large capture
without conflating their performance envelopes.

**Work:**

- preserve vectorized feature computation for `training_features`;
- build bounded-memory, atomic, resumable dataset shards for
  `waveform_fidelity`;
- add deterministic replay, validation, statistics, split construction, and
  optional Parquet indexing;
- record dropped/late frames and IO backpressure rather than hiding them;
- expand Replicator export as an adapter to the canonical manifest.

**Exit gate:**

- 4,096 environments, four microphones, two events, and 50 measured steps pass
  p95 `<= 20 ms` on the RTX 4090 reference host for the batched L1 path;
- a representative long capture completes with bounded memory, zero manifest
  violations, valid checksums, monotonic timestamps, and no split leakage;
- interruption leaves no shard marked complete, and resume produces the same
  canonical manifest as an uninterrupted seeded run.

### M4 - L3 Advanced Realism

**Objective:** model the effects needed for research datasets while keeping
each approximation explicit.

**Work, in dependency order:**

1. automatic source/array velocity from timestamped Isaac poses;
2. rendered sim-time gaps and intra-window motion policy;
3. microphone frequency response, gain/delay mismatch, polarity, and
   self-noise spectra;
4. clipping, quantization, and optional AGC with recorded state;
5. waveform-applied source/microphone directivity;
6. measured material parameters, dynamic room/source/array behavior, and
   multi-source stress cases;
7. replaceable advanced propagation for diffraction or richer wave effects.

**Exit gate:** every effect has an off-state that preserves the prior baseline,
a focused physical or analytical fixture, additive diagnostics, performance
measurements, and documented limitations. Ray/transmission occlusion is not
described as diffraction or a complete wave solver.

### M5 - L4 Reference-Rig Calibration

**Objective:** support a defensible, repeatable research-grade calibrated claim
for one documented rig and environment envelope.

**Work:**

- lock the BOM, exact measured geometry, channel identity, and acquisition
  procedure before fitting parameters;
- begin with the available two-microphone bench while preserving explicit
  front/back ambiguity and a documented 4+ microphone upgrade path;
- measure pose sweeps, per-channel level/delay, noise, frequency response,
  reverberation, occlusion, clock behavior, and end-to-end latency;
- separate fit and holdout measurements;
- compare uncalibrated simulation, calibrated simulation, and real recordings;
- freeze baseline-derived pass thresholds in a tracked benchmark specification
  before using them as release gates.

**Required reported metrics:** TDOA error, candidate-bearing coverage for the
two-microphone rig, unambiguous DOA error where geometry supports it, level
error in dB, reverberation error, latency distribution, failure rate, and
confidence calibration. Every metric reports sample count, pose/distance
coverage, median, p95, and worst case.

**Exit gate:** the holdout comparison passes the pre-registered thresholds,
calibration improves the declared metrics without corrupting unaffected
contracts, the full run is replayable from checked artifacts, and unmodeled
conditions are listed. No generic claim is inferred from one reference rig.

### M6 - Guided GUI And Headless Parity

**Objective:** make the common workflow understandable to a first-time Isaac
user while preserving expert control.

**Guided workflow:**

1. **Setup**: select or create array, source, room, and runtime profile.
2. **Validate**: show stage health, geometry rank, dependencies, paths, frames,
   devices, and actionable fixes.
3. **Run**: configure and control the sensor with safe defaults.
4. **Inspect**: view compass, elevation/range, meters, waveform, spectrogram,
   events, occlusion, and performance.
5. **Record**: configure a validated dataset session and monitor progress.
6. **Export**: write frame, config, manifest, calibration, and evidence
   artifacts with a summary of what was produced.

Advanced mode retains every expert field and supports lossless config
round-trip. Long operations report progress and are cancellable. Invalid input
is attached to its field, preserves the last valid state, and never leaves a
half-started sensor or dataset.

Every GUI operation must have a documented config/API/CLI equivalent suitable
for headless use.

**Exit gate:** at least four of five evaluators, unfamiliar with the package,
install the extension, configure a valid scene, capture frames, and export a
small valid dataset within ten minutes without source-code or terminal use.
All expert config fields round-trip, cancellation/retry tests pass, and the
headless equivalence suite produces semantically identical outputs.

### M7 - SquadBot And Alex Readiness

**Objective:** prove that released generic artifacts support the attached
audio-visual robotics plan while keeping ownership boundaries intact.

Cross-repository tests must install a built wheel or extension archive. They
must not depend on a sibling checkout, source-path injection, or generated
local evidence from this repository.

| Downstream phase | Sensor-owned readiness evidence | External responsibility |
| --- | --- | --- |
| 7-8: bench and calibration | real recording import/replay, calibration profile, comparable sim/real metrics, stable timestamps/frames | physical assembly, transport messages, graph insertion, visual bench path |
| 9: Alex bring-up | array discovery and mounting on the canonical head/base frame, finite moving transforms, trace/config export | robot asset validation, camera and control-interface bring-up |
| 10: orientation | localized or explicitly ambiguous cues, latency and confidence, moving-array correctness | cue-to-orientation intent and safe yaw control |
| 11: visual confirmation | stable frame ids, source metadata, poses, and adapter inputs | visual detection/ground truth, ontology, graph link |
| 12-13: mobile and scaled scenes | motion, Doppler, occlusion, longer sessions, hallway/multi-area stress, deterministic scenario configs | locomotion, planning, stopping, visual search, scenario policy |
| 14-15: real torso/mobile validation | portable configs/calibration, real/sim trace comparability, stable generic outputs | hardware safety, robot transport, actuation, IHMC execution and approval |

**Exit gate:** released artifacts pass the complete generic-frame-to-protobuf-
to-auditory-cue-to-graph fixture chain; every event preserves schema version,
source/frame ids, timestamps, order, units, bearing ambiguity, and provenance;
no downstream ontology or behavior field appears in the generic frame schema.

Alex or IHMC availability is not a dependency of package publication. Missing
access produces a downstream blocker report while replayable interface
fixtures continue to gate compatibility.

### M8 - Publication, Maintenance, And Evidence

**Objective:** make releases reproducible, discoverable, supportable, and
honest about their evidence.

**Work:**

- publish wheels and source distributions through PyPI and GitHub releases;
- publish the Kit extension through the
  [Kit Community Registry](https://docs.omniverse.nvidia.com/kit/docs/kit-registry-reference/latest/community/extensions.html);
- use the required public repository topic, valid `extension.toml`, release
  archives, target metadata, and platform naming current at release time;
- add clean-install, archive, SBOM, license, security, compatibility, GUI,
  benchmark, and calibration evidence;
- define support windows, deprecation policy, migration notes, issue templates,
  and a release evidence index;
- recheck the
  [Kit extension configuration reference](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/)
  immediately before release because registry and compatibility rules can
  change.

The Community Registry is a community distribution channel. Listing there
must not be represented as NVIDIA support, certification, or endorsement.

**Exit gate:** a clean Linux install passes all claimed base and acoustic-pack
capabilities; the final cross-platform release also passes the Windows
install/GUI matrix; published artifacts match locally audited checksums; docs,
metadata, schemas, versions, and support statements agree.

## 6. Agent Execution Work Breakdown

The milestone descriptions above define outcomes. This section divides those
outcomes into reviewable implementation units small enough to assign to an
agent. The agent should execute one numbered subphase at a time unless the
parallelization rules below explicitly allow otherwise.

### 6.1 Subphase Execution Contract

For every subphase, the implementing agent must:

1. read this plan, the named predecessor closeout, and the relevant current
   implementation before editing;
2. restate the subphase boundary and its tests in the working plan;
3. add or update the failing acceptance test before, or with, production code;
4. implement only the named deliverable and necessary compatibility changes;
5. run focused tests first, then all available milestone/repository gates;
6. stop before the next subphase.

A subphase is not complete merely because code exists. Its tests, documentation,
artifact validation, and closeout must also pass. If a required runtime, GPU,
display, operating system, device, or external repository is unavailable, the
agent records `blocked` evidence and stops that subphase; it does not weaken the
gate or substitute a mock as live proof.

### 6.2 Execution Artifact Convention

When implementation begins, use these locations consistently:

- tracked design and benchmark specifications:
  `docs/development/specs/<subphase>_<topic>.md`;
- tracked closeouts:
  `docs/development/closeouts/<subphase>_<topic>.md`;
- public schemas: `docs/schemas/`;
- small, redistributable contract fixtures: the relevant `examples/` fixture
  directory;
- machine-local live, performance, calibration, and media evidence:
  `outputs/isaac_audio_sensors/<subphase>/`.

Raw physical recordings remain outside git unless their license, consent, and
size are explicitly suitable. Track their manifest, hashes, acquisition
contract, and retrieval instructions instead. A closeout may cite ignored
evidence, but public claims require the evidence package to be archived in the
declared release location.

### 6.3 M0 Subphases - Baseline And Measurement Lock

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M0.1` | **Source-of-truth audit.** Map every current claim in Section 3 to code, tests, tracked docs, or a named machine-local artifact. Record discrepancies without changing behavior. | Each row is classified Verified/Partial/Target/External with an evidence link. Stop and correct this plan if code and docs disagree. | None |
| `M0.2` | **Pure release baseline.** Run and record tests, lint, schema generation/parity, import smoke, build, and archive audit from a clean environment. | All available pure gates pass. Existing failures receive reproducible commands and must be resolved before feature work. | `M0.1` |
| `M0.3` | **Live runtime baseline.** Run Isaac Sim lifecycle, Isaac Lab GPU, extension UX, screenshots, and optional L2 checks on the selected 6.x/3.x pair. | Each live gate has exact runtime/GPU facts and artifacts. Unavailable capability is `blocked`, never silently skipped. | `M0.2` |
| `M0.4` | **Performance baseline.** Freeze the 4,096-env/four-mic/two-event L1 benchmark config and collect raw timings for at least three 50-step runs after warm-up. | Report mean, median, p95, worst step, GPU, driver, memory, and compute path. The worst run must meet the current `20 ms` p95 target before later optimization claims use this baseline. | `M0.3` |
| `M0.5` | **Reference-rig inventory.** Record the Raspberry Pi, audio interface, microphone count/geometry, channel order, speaker, camera, mounts, room, clocks, and measurement tools; mark unknown values explicitly. | A reviewer can reconstruct the proposed bench or identify every missing item. No estimated geometry is labeled measured. | `M0.1` |
| `M0.6` | **Acceptance-spec lock.** Write tracked performance, dataset, calibration, GUI-usability, and release evidence specifications using M0 facts. | Each later milestone has a measurable input/output contract and no threshold depends on unseen holdout data. | `M0.2`-`M0.5` |

### 6.4 M1 Subphases - Self-Contained Distribution

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M1.1` | **Packaging ADR.** Lock the single-source build design, extension id, archive contents, base/optional-pack boundary, supported Kit target, and version synchronization policy. | ADR demonstrates that wheel and extension cannot drift and identifies every compiled dependency/platform boundary. No packaging code starts before approval. | `M0.6` |
| `M1.2` | **Extension build pipeline.** Assemble the Kit package from the canonical Python source/wheel into a staging directory without copying maintained source by hand. | A content manifest proves which package files were included and rejects stale/missing modules. Repeated builds from one revision have identical logical contents. | `M1.1` |
| `M1.3` | **Runtime entrypoint cleanup.** Remove distributed checkout-relative import behavior and resolve package modules only from the extension artifact. Preserve editable-checkout development separately. | A test fails if the packaged entrypoint references repository `src/`; source-checkout and packaged startup both pass. | `M1.2` |
| `M1.4` | **Base archive.** Package L0/L1, GUI, schemas, presets, examples, and pure runtime dependencies; add archive safety and metadata audits. | Archive contains no caches, outputs, private paths, sibling-project code, or undeclared dependencies. Extracted base imports without network access. | `M1.3` |
| `M1.5` | **Linux clean-install gate.** Install the base archive into a clean Isaac Sim 6.x environment and run GUI plus headless L0/L1 workflows. | Discovery, enable, sample scene, frame capture, JSONL export, disable/re-enable, and uninstall/reinstall pass without checkout or manual package installation. | `M1.4` |
| `M1.6` | **Optional acoustic packs.** Build version-matched platform artifacts for L2/L3 compiled dependencies and expose capability discovery in API/CLI/GUI. | Installing the pack enables its backends; removing it leaves the base healthy and produces an actionable unavailable-capability result. Version/platform mismatch is rejected. | `M1.4` |
| `M1.7` | **Windows clean-install gate.** Reproduce the base and supported acoustic-pack workflows on the current Windows Isaac runtime. | The same install, GUI, capture, export, update, and removal contract passes; platform differences are documented rather than hidden. | `M1.5`, `M1.6` |
| `M1.8` | **Registry-readiness dry run.** Validate `extension.toml`, target metadata, icons/docs, archive names, GitHub release layout, and current Community Registry discovery rules. | Dry-run/install-from-release artifacts pass and a checklist identifies only external publication actions. Recheck official rules during M8. | `M1.5`; `M1.7` for the final cross-platform artifact |

### 6.5 M2 Subphases - Contract And Plugin Freeze

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M2.1` | **Contract ADR and namespaces.** Lock schema ids, compatibility policy, directory/module ownership, time/coordinate conventions, and migration policy. | The design keeps frame v1 stable and proves why dataset/calibration data are separate contracts. | `M0.6` |
| `M2.2` | **Dataset manifest model.** Implement types, JSON Schema, serialization, validation, and nominal/invalid fixtures for `ias.audio_dataset_manifest.v1`. | Generated and checked schema match; fixtures preserve ids, units, frames, channel order, timestamps, checksums, and completion state. | `M2.1` |
| `M2.3` | **Calibration profile model.** Implement `ias.audio_calibration_profile.v1`, compatibility validation, serialization, and fixtures. | Wrong device/channel/sample-rate/coordinate profiles fail before any partial application; unknown optional fields round-trip under the version policy. | `M2.1` |
| `M2.4` | **Runtime-profile configuration.** Add `training_features` and `waveform_fidelity` to config/API/CLI with strict validation and documented defaults. | Existing configs retain prior behavior through an explicit compatibility default; unknown profiles and impossible profile/backend combinations fail clearly. | `M2.1` |
| `M2.5` | **Plugin protocols and registries.** Add `PropagationBackend`, `DoaEstimator`, and `AudioFeatureExtractor` capability declarations and registry rules. | Duplicate ids, missing dependencies, device/profile mismatch, invalid output shapes, and nondeterminism claims are tested. Existing backends register without semantic change. | `M2.1`, `M2.4` |
| `M2.6` | **Isaac Lab additive buffers.** Add elevation, range, occlusion, and optional feature tensors with masks, allocation, reset, selected update, and observation export. | CPU/import-safe and live GPU tests confirm shapes, dtypes, device placement, padding, selected-row isolation, and backward-compatible keys. | `M2.4`, `M2.5` |
| `M2.7` | **Compatibility freeze.** Regenerate public examples/docs and run old frame/config fixtures plus new schema/plugin consumers. | Pre-change v1 fixtures remain valid; all breaking changes are removed or moved behind a new version; closeout freezes public names. | `M2.2`-`M2.6` |

### 6.6 M3 Subphases - Efficient Training And Dataset Pipeline

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M3.1` | **Fast-profile parity.** Route L0/L1 batched observation generation through `training_features` without waveform allocation. | Scalar/batched outputs match within declared tolerances; profiler proves no per-environment frame or waveform objects on the steady-state fast path. | `M2.4`, `M2.6` |
| `M3.2` | **Dataset session and shard layout.** Define deterministic ids, relative paths, shard boundaries, asset naming, metadata/audio joins, and completion markers. | A tiny reference dataset is byte/logically reproducible for one seed and portable after moving its root directory. | `M2.2`, `M2.4` |
| `M3.3` | **Atomic bounded-memory writers.** Implement streaming JSONL and WAV/FLAC writes, staging, fsync/finalization policy, checksums, cancellation, and resume. | Disk interruption, process termination, disk-full, partial line, and retry tests never expose an incomplete shard as complete; memory stays within the M0 spec. | `M3.2` |
| `M3.4` | **Loader and deterministic replay.** Load episodes/shards incrementally and replay frames in original order with preserved types, units, and boundaries. | Tiny and multi-shard fixtures round-trip; corrupt assets, missing frames, checksum mismatch, and unknown versions fail with location context. | `M3.3` |
| `M3.5` | **Validator and statistics.** Report counts, duration, missingness, channel/sample-rate consistency, timestamp quality, ranges, labels, modalities, and asset integrity. | Zero violations on valid fixtures; each planted corruption produces the intended finding; large validation is streaming/bounded. | `M3.4` |
| `M3.6` | **Deterministic split builder.** Build train/validation/test manifests using scene/object/task/episode grouping selected by config. | Same seed produces the same hashes; no group crosses splits; impossible ratios or missing grouping metadata fail. | `M3.5` |
| `M3.7` | **Replicator adapter.** Map Replicator capture into the canonical session/writer contracts without creating a second source of truth. | Replicator and direct recording of the same seeded frames are semantically equivalent after path normalization; absence of Replicator does not affect core capture. | `M3.3`-`M3.5` |
| `M3.8` | **Performance and endurance closeout.** Run the 4,096-env benchmark and representative long dataset sessions with IO/resource telemetry. | L1 p95 target, bounded memory, zero valid-dataset violations, deterministic resume, and no unreported dropped frames pass. | `M3.1`, `M3.5`-`M3.7` |

### 6.7 M4 Subphases - L3 Advanced Realism

Implement each physical effect as a separate review unit. Do not batch multiple
effects into one opaque backend change.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M4.1` | **Pose-derived velocity.** Derive source/array linear velocity from timestamped Isaac poses with reset, first-sample, teleport, stale-time, and smoothing policy. | Constant-velocity analytical fixtures match tolerance; teleport/reset never emits an extreme Doppler spike; authored velocity precedence is explicit. | `M2.7` |
| `M4.2` | **Time gaps and intra-window motion.** Preserve sim-time gaps in session audio and define piecewise motion within capture windows. | Known pause/throttle trajectories produce the expected silence/sample count and bounded interpolation error; non-monotonic time fails. | `M4.1`, `M3.3` |
| `M4.3` | **Channel response and mismatch.** Apply calibrated frequency response, gain, delay, and polarity per microphone. | Impulse, tone, and broadband fixtures recover expected transfer functions; off-state remains compatible; channel mismatch is observable in diagnostics. | `M2.3`, `M2.5` |
| `M4.4` | **Noise model.** Add configurable spectral self-noise, ambient noise sources, clock jitter/drift, and seeded stochastic policy. | PSD/RMS and delay statistics meet analytical tolerances over sufficient samples; fixed seeds replay; independent streams do not accidentally correlate. | `M4.3` |
| `M4.5` | **Electronics path.** Add quantization, saturation/clipping, optional AGC, and recorded AGC state in the waveform path. | Boundary amplitudes, recovery timing, clipping counts, and quantization noise pass; disabled electronics preserve the prior waveform within tolerance. | `M4.3`, `M4.4` |
| `M4.6` | **Waveform directivity.** Apply source and microphone polar/frequency response in L2/L3 rather than metadata only. | Cardinal-angle and frequency sweeps match configured patterns; zero/invalid patterns fail; DOA tests cover expected confidence degradation. | `M4.3` |
| `M4.7` | **Materials and dynamic rooms.** Consume measured material parameters where available and define cache invalidation for moving geometry/room changes. | Controlled clear/blocked/material fixtures keep waveform, RMS, diagnostics, and export mutually consistent; cache never returns stale acoustics. | `M4.2`, `M4.6` |
| `M4.8` | **Advanced propagation plugin.** Integrate diffraction or richer wave propagation only through `PropagationBackend`, with explicit supported geometry and performance limits. | Backend passes common contract fixtures, declares dependency/device limits, and is compared against analytical or trusted reference cases. It does not change L0-L2 ids. | `M2.5`; may develop alongside `M4.1`-`M4.7` |
| `M4.9` | **Multi-source robustness and closeout.** Stress overlap, near/far imbalance, motion, occlusion, reverb, and unavailable effects across backends. | No source/detection identity corruption, NaNs, hidden ambiguity, stale cache, or unbounded resource growth; performance and failure envelopes are published. | `M4.1`-`M4.8` |

### 6.8 M5 Subphases - L4 Reference-Rig Calibration

Fit and holdout data must remain separated. Once holdout evaluation begins,
failed results cannot be fixed by tuning against holdout measurements; a new
calibration version and new sealed holdout are required.

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M5.1` | **BOM and frame lock.** Measure and version device/channel identity, microphone coordinates, array/source frames, speaker, room, clocks, temperature method, and uncertainty. | Independent review can reproduce coordinate transforms and channel order. Unknown/estimated measurements are not accepted as calibrated values. | `M0.5`, `M2.3` |
| `M5.2` | **Acquisition tool and runbook.** Capture synchronized multichannel recordings plus poses, reference signals, timestamps, environment facts, and operator notes. | Dry runs detect missing channels, clipping, clock loss, stale pose, insufficient duration, and invalid metadata before accepting a take. | `M5.1`, `M3.3` |
| `M5.3` | **Pilot sweep and quality gate.** Run a small pose/level/delay/noise/reverb sweep to validate the rig and acquisition protocol. | Repeat takes remain inside predeclared repeatability tolerances; otherwise fix the rig/protocol before collecting the main dataset. | `M5.2` |
| `M5.4` | **Fit/holdout dataset freeze.** Collect the full sweep, assign groups before fitting, seal holdout assets/hashes, and record coverage. | No pose/source/room group leaks between fit and holdout; holdout contents are not inspected by fitting code. | `M5.3`, `M3.6` |
| `M5.5` | **Calibration fitting.** Estimate geometry corrections, channel delay/gain/polarity, response/noise parameters, and uncertainty from fit data only. | Synthetic recovery tests and fit residuals pass; regularization/constraints are documented; parameters serialize into the profile schema. | `M5.4`, `M4.3`-`M4.6` |
| `M5.6` | **Profile application.** Apply profiles to simulation and comparison tooling with strict identity/sample-rate/frame checks. | Uncalibrated mode is unchanged; compatible profile application is deterministic; swapped/stale/incompatible profiles fail closed. | `M5.5` |
| `M5.7` | **Metric threshold freeze.** Using M0 targets, pilot evidence, and fit-data behavior only, preregister TDOA, bearing coverage/error, level, reverb, latency, failure, and confidence criteria. | Threshold document includes denominators, aggregation, exclusions, tolerances, and pass logic before holdout results are opened. | `M5.5`, `M5.6` |
| `M5.8` | **Sealed holdout evaluation.** Compare real, uncalibrated sim, and calibrated sim without refitting. | All preregistered metrics and failure counts are reported. Any failed gate remains failed; no selective scenario removal is allowed. | `M5.7` |
| `M5.9` | **Calibration closeout.** Package the profile, manifest, metrics, uncertainty, limitations, hashes, and reproduction commands. | A clean consumer can replay the comparison and obtain the declared results. Claims are restricted to the measured rig/environment envelope. | `M5.8` |

### 6.9 M6 Subphases - Guided GUI And Headless Parity

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M6.1` | **UX specification and state machine.** Define novice/expert personas, six-step workflow, navigation, persistent state, cancellation, error recovery, and wireframes before UI code. | Every current control is mapped to Guided, Advanced, removed, or headless-only; no capability is lost accidentally. | `M2.1`, `M2.4` |
| `M6.2` | **Shared validation/capability model.** Move stage/config/dependency/device checks into import-safe controller services used by GUI and CLI. | Pure tests prove identical validation results without `omni.ui`; capability state updates after install/remove/stage changes. | `M2.5`, `M6.1` |
| `M6.3` | **Setup workflow.** Implement selection, presets, array/source/room authoring, runtime profile, and saved setup summary. | A minimal valid scene can be created from an empty stage; invalid/degenerate geometry is caught before Run. | `M6.2` |
| `M6.4` | **Validate workflow.** Present stage health, geometry rank, frames, time, dependencies, device, paths, calibration compatibility, and actionable repairs. | Every planted invalid state maps to the correct field/action and no warning is represented as a pass. | `M6.3`, `M2.3` |
| `M6.5` | **Run and Inspect workflows.** Add lifecycle state, live instruments, performance, waveform/spectrogram, events, occlusion, and stale-frame indicators. | Start/stop/restart/update and simulator-stage replacement recover; UI update cost stays inside the M0 GUI budget; no stale frame appears current. | `M6.4`, `M3.1` |
| `M6.6` | **Record and Export workflows.** Add dataset session validation, progress, backpressure, cancellation/resume, output inventory, and evidence export. | UI-created datasets pass the canonical validator; cancellation is atomic; export lists hashes and errors; disk failure is recoverable. | `M3.3`-`M3.5`, `M6.5` |
| `M6.7` | **Advanced mode and migration.** Rehome all expert fields, preserve full config round-trip, and migrate old extension configs additively where possible. | Old fixtures import to semantically equivalent state; Guided edits remain visible in Advanced; unknown/removed fields get explicit migration findings. | `M6.3`-`M6.6`, `M2.7` |
| `M6.8` | **Headless parity.** Add or align config/API/CLI operations for each Guided action and a semantic comparison harness. | Guided and headless runs from the same config produce equivalent stage metadata, frames, manifests, and calibration selection after path normalization. | `M6.7` |
| `M6.9` | **Live QA and usability gate.** Run Kit UI automation/screenshots, accessibility/error review, cancellation/restart scenarios, and the five-person first-use study. | At least four of five users complete the ten-minute task; all blocking usability findings are fixed and rerun; live evidence records exact Kit/runtime facts. | `M6.8`, `M1.5`; Windows rerun after `M1.7` |

### 6.10 M7 Subphases - SquadBot And Alex Readiness

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M7.1` | **Released-artifact consumer harness.** Create an isolated environment that installs the built wheel/archive and runs the external adapter fixtures without sibling source paths. | Import provenance points only to installed artifacts; frame-to-protobuf-to-cue-to-graph nominal, empty, multi-source, ambiguity, and replay cases pass. | `M1.5`, `M2.7` |
| `M7.2` | **Phases 7-8 bench fixture.** Export/replay reference-rig recordings, calibration profiles, and comparable sim/real traces through the external adapter. | Timestamps, frames, source ids, ambiguity, provenance, and metric joins survive the boundary; physical transport/graph code remains external. | `M5.9`, `M7.1` |
| `M7.3` | **Phase 9 Alex mounting fixture.** Package a generic example that discovers/mounts the array on the canonical robot link and records moving finite transforms. | Clean Isaac run proves mount identity, child microphones, coordinate convention, trace/config export, and no robot-specific frame-schema field. | `M4.1`, `M7.1` |
| `M7.4` | **Phase 10 orientation input fixture.** Supply localized and explicitly ambiguous moving-array cue sequences with latency/confidence evidence. | External orientation adapter receives stable ordered cues; ambiguous/nonlocalized inputs never invent direction; sensor owns no actuation. | `M7.3`, `M4.9` |
| `M7.5` | **Phase 11 visual-confirmation boundary.** Verify that sensor frame/source/pose metadata joins deterministically to external visual and graph fixtures. | Link inputs preserve ids/timestamps/provenance; visual classes and link state stay outside the generic frame. | `M7.4` |
| `M7.6` | **Phases 12-13 scaled stress.** Run long moving, Doppler, occlusion, hallway/multi-area, outside-FOV, and overlap scenarios through capture and adapter replay. | No stale transforms, identity corruption, unbounded memory, silent frame loss, or contract drift; failures remain separately measurable. | `M4.9`, `M3.8`, `M7.5` |
| `M7.7` | **Phases 14-15 handoff package.** Provide portable config/calibration, replay fixtures, expected generic outputs, metric definitions, and blocker template for real torso/mobile work. | Package contains no unsafe command assumptions or actuation code; it can validate interfaces when robot access is absent. | `M7.2`, `M7.6` |
| `M7.8` | **Cross-repository contract closeout.** Run the full installed-artifact matrix and freeze compatibility evidence for the release candidate. | All supported fixtures pass from released artifacts; generic exports contain no downstream ontology/behavior leakage; external blockers are explicit. | `M7.1`-`M7.7` |

### 6.11 M8 Subphases - Publication And Maintenance

| ID | Execution unit and deliverable | Verification and stop condition | Depends on |
| --- | --- | --- | --- |
| `M8.1` | **Release CI matrix.** Encode pure, schema, build, archive, Linux clean install, live Sim/Lab/GUI, performance, optional-pack, and cross-repository gates with explicit hardware runners. | Required jobs cannot pass through blanket skips; artifact retention and blocker reporting are configured; repeated runs are stable. | Begin after `M1.5`; finalize after `M7.8` |
| `M8.2` | **Supply-chain and archive hardening.** Generate SBOM, dependency/license inventory, checksums/signatures where supported, vulnerability review, and reproducible archive manifests. | Audits cover base and every acoustic pack; undeclared binary/dependency/private content fails the build. | `M1.6`, `M2.7` |
| `M8.3` | **Documentation and support package.** Finalize installation, quickstart, Guided/Advanced GUI, API/contracts, calibration limits, examples, troubleshooting, security, support window, and deprecation/migration policy. | Fresh-user doc walkthrough succeeds; versions/claims/commands/links agree; known limitations match evidence. | `M6.9`, `M5.9` |
| `M8.4` | **Release candidate rehearsal.** Build immutable candidate artifacts and run the complete matrix from those exact archives, not the worktree. | Every required gate passes or the candidate is rejected; evidence index maps claims to artifacts and hashes. | `M3.8`, `M4.9`, `M5.9`, `M6.9`, `M7.8`, `M8.1`-`M8.3` |
| `M8.5` | **Linux public base publication.** Publish signed/hashed Python and Linux Kit artifacts with accurate base/optional capability statements. | Clean external install matches candidate checksums and smoke results; rollback/yank procedure is documented before announcement. | `M8.4` |
| `M8.6` | **Windows final-platform validation.** Rebuild/reuse the candidate policy for Windows and rerun install, GUI, examples, update, and optional-pack gates. | Windows artifacts meet the same declared contracts; unsupported advanced-pack differences are explicit. | `M1.7`, `M8.4` |
| `M8.7` | **Community Registry publication.** Recheck current official rules, publish correctly named platform archives/release metadata, and verify discovery from a clean registry client. | Listing installs the exact audited artifacts and is described as community-provided, not NVIDIA-supported. | `M8.5`, `M8.6` |
| `M8.8` | **Post-release verification and maintenance start.** Rerun install/update telemetry-free smoke, archive evidence, triage release issues, and create the next compatibility review date/event. | No critical packaging/schema regression remains open; hotfixes follow the same candidate gates; evidence and changelog are finalized. | `M8.7` |

### 6.12 Critical Path And Parallel Work

The default critical path is:

```text
M0 -> M1.1-M1.5 -> M2 -> M3 -> M4 -> M5 -> M7.8 -> M8.4-M8.8
```

Safe parallel work is limited to these lanes:

- `M1.6` acoustic-pack work can proceed beside the late M2 contract work after
  `M1.4`, but it must adopt the frozen plugin contract before closeout.
- `M1.7` Windows validation can proceed after Linux base and acoustic artifacts
  are stable.
- `M4.8` advanced propagation can proceed beside `M4.1`-`M4.7` after the plugin
  protocol freezes; `M4.9` waits for all effects.
- `M6.1` UX design may begin after runtime-profile intent is locked. GUI
  implementation waits for the shared M2/M3 contracts it exposes.
- `M7.3`-`M7.5` simulator fixtures may proceed while physical calibration is
  running; `M7.2`, `M7.7`, and the final closeout wait for M5 evidence.
- `M8.1`-`M8.3` can grow continuously, but release rehearsal uses completed
  milestone artifacts only.

Do not parallelize changes to the same public schema, the calibration fit and
sealed holdout evaluation, or GUI state migration and config compatibility.
Those boundaries need one authoritative implementation and review sequence.

### 6.13 Reusable Agent Assignment Template

Use this template when assigning a subphase to an implementation agent:

```text
Implement subphase <ID> from docs/final_sensor_development_plan.md only.

Read the subphase, its dependencies, the predecessor closeout, current code,
tests, and public compatibility docs before editing. Restate the exact input,
output, non-goals, tests, and evidence in your working plan. Preserve unrelated
user changes. Add or update acceptance tests, implement the smallest complete
deliverable, run focused and available repository/live gates, and write the
tracked closeout required by Section 6.2.

Do not begin a later subphase. Do not weaken or skip a gate to report success.
If required external evidence is unavailable, record the exact blocker and
complete only the valid offline evidence allowed by this subphase.
```

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

Use explicit `sim`, `gpu`, `hardware`, and `cross_repo` markers for checks that
cannot run in the pure test environment. Each skip must include a concrete
reason and the host-visible command that supplies the missing evidence.

### 7.2 Required Scenarios

| Level | Minimum cases | Pass criteria |
| --- | --- | --- |
| Contract/unit | nominal, boundary, invalid, regression | schemas and validators preserve units, frames, shapes, ids, versions, and error semantics |
| Determinism/property | repeated seed, shuffled input, transform round-trip, JSONL replay | stable ordering/hashes where promised; floating/GPU differences stay within documented tolerance |
| Acoustic | silence/inactive source, noise, overlap, ambiguity, motion, Doppler, occlusion, reverberation, invalid geometry | no invented direction, no hidden ambiguity, finite bounded outputs, explicit failure/diagnostics |
| Dataset | tiny round-trip, long stream, interruption, resume, corrupt asset, duplicate/non-monotonic timestamp, split leakage | zero violations for valid data; all corruptions detected; bounded memory; deterministic manifest |
| Isaac Sim | stage open/close, rediscovery, moving mount, multiple sources, debug, recording, optional pack missing | lifecycle recovery, current poses, no stale frame, valid exports, readable errors |
| Isaac Lab GPU | allocation, selected reset/update, device mismatch, 4,096-env benchmark, headless capture | all buffers on declared device, unaffected rows unchanged, performance gate met |
| GUI | first-use path, advanced round-trip, invalid input, cancellation, restart, dependency blocker | user-study target met; no lost valid state; output matches headless path |
| Hardware | fit/holdout sweeps, channel swap, stale profile, environmental variation | incompatible profiles rejected; declared calibration metrics and uncertainty reproduced |
| Cross-repository | released artifact, empty frame, multi-source, ambiguous two-mic, trace replay, malformed event | deterministic adapter output; generic schema unchanged; failures explicit |

### 7.3 Canonical Verification Commands

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

Future milestones should add stable make targets for dataset validation,
performance benchmarking, Kit packaging/clean install, calibration replay, and
the released-artifact cross-repository test. The closeout document for each
milestone must name the actual targets once implemented; ad hoc shell history
is not sufficient release evidence.

## 8. Failure And Recovery Requirements

The final product must handle these failures deliberately:

- no stage, deleted/replaced prim, simulator restart, or stale discovery cache;
- invalid/missing microphone geometry, degenerate array, frame mismatch, NaN,
  impossible sample rate, negative timestamp, or unknown schema/profile;
- unavailable GPU, wrong tensor device, missing optional acoustic pack, or
  unsupported platform/runtime;
- corrupt/partial audio, checksum mismatch, partial manifest line, disk-full,
  interrupted shard, slow writer, or non-monotonic time;
- calibration channel/sample-rate/device mismatch or measurements outside the
  declared validity envelope;
- GUI cancellation, invalid field text, failed start, failed export, or stale
  selection;
- missing robot/hardware access in an otherwise valid offline compatibility
  run.

Failures must leave resources closable, preserve the last known valid config,
avoid publishing incomplete artifacts, and return actionable messages. A
fallback must be explicitly selected and recorded; it must not silently change
provenance, device, fidelity, bearing, or calibration semantics.

## 9. Release Stages And Final Definition

### 9.1 Public Base Release

The package may publish an initial Community Registry release after M0-M3 and
the core M6 guided path pass on Linux. That release must describe L0/L1 as the
self-contained base, identify optional acoustic packs, and avoid calibrated
physical-realism claims.

### 9.2 Research-Grade Final Release

The final target described by this document is reached only when:

- the base Kit extension is self-contained and clean-installable;
- current Isaac Sim 6.x and Isaac Lab 3.x gates pass;
- Linux/headless and Windows GUI installation evidence exists;
- frame v1 remains compatible and the dataset/calibration schemas are frozen;
- both runtime profiles and the 4,096-environment performance gate pass;
- L3 effects have isolated validation and honest model boundaries;
- the reference rig passes the pre-registered L4 holdout criteria;
- the guided GUI and advanced/headless parity gates pass;
- a released artifact passes the downstream adapter fixture chain;
- build, archive, SBOM, license, security, docs, and release-evidence checks
  pass;
- support, deprecation, migration, and known-limitation policies are published.

Real Alex torso or IHMC mobile execution can add valuable downstream evidence,
but it does not delay this package definition when the generic interfaces and
replay fixtures are already proven.

## 10. Locked Decisions

- Distribution: Kit Community Registry plus PyPI and GitHub releases.
- Compatibility: current Isaac Sim 6.x and Isaac Lab 3.x; no older-major
  support promise.
- Platforms: Linux/headless first, Windows required for the final
  cross-platform claim.
- Packaging: self-contained L0/L1 base plus optional platform acoustic packs.
- Product boundary: sensor SDK and plugin hooks, not a bundled learned
  classifier or robot behavior stack.
- Runtime strategy: fast batched feature observations plus separate
  waveform-fidelity capture.
- Dataset: JSONL manifest and lossless multichannel WAV/FLAC; Parquet is an
  optional derived index.
- Calibration: reusable tooling validated on one measured reference rig; the
  exact BOM is locked at M0.
- GUI: guided workflow with progressive Advanced controls and headless parity.
- Downstream architecture: generic producer here, project adapter in the
  consumer repository.
- ROS 2: optional later integration.
- Scheduling: dependency and evidence gates, not dates.
