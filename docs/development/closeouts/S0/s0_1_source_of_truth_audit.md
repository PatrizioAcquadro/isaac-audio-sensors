# S0.1 source-of-truth audit

| Field | Audited value |
| --- | --- |
| Audit date | 2026-07-16 |
| Entry revision | `e626ee2` (`e626ee23d7c828645b75df6345f4cb2b1d3eadd2`) |
| Package version | `1.7.0`, confirmed in `pyproject.toml` and `src/isaac_audio_sensors/__init__.py` |
| Frame schema version | `ias.audio_sensor_frame.v1`, confirmed in `src/isaac_audio_sensors/core/constants.py` and `docs/schemas/audio_sensor_frame.v1.schema.json` |
| Auditor tooling | Codex static inspection with `rg`, `sed`, `find`, `stat`, and Git diff/status. Primary implementation modules and covering tests were read; no tests, builds, or live gates were run by this audit. |

## Scope and method

This audit covers every current-state claim in Section 3 of
`docs/final_sensor_development_plan.md`. At the entry revision, Section 3 has
15 table rows, not 16. The separate package/schema sentence immediately above
the table is therefore treated as the sixteenth claim entry.

Statuses are normalized to the four S0.1 acceptance categories:

- **Verified**: implemented and supported by tracked code and tests. Optional
  dependency or machine-local qualifiers are retained in the finding.
- **Partial**: a concrete subset exists, with named missing behavior.
- **Target**: vocabulary or a planned boundary exists, but the claimed product
  capability does not.
- **External**: implementation and acceptance ownership are outside this
  repository.

Machine-local evidence under `outputs/isaac_audio_sensors/` is supporting
evidence, not tracked source. Exact current paths are used below. The output
tree was reorganized on 2026-07-03, so older Isaac Sim evidence is cited at
its actual archived path rather than at stale pre-cleanup root paths.

## Status summary

| Section 3 claim | Plan status | Confirmed status | Disagreement |
| --- | --- | --- | --- |
| Package and schema versions | Unlabelled sentence | **Verified** | None |
| Core contract | **Verified** | **Verified** | None |
| L0 geometry | **Verified** | **Verified** | None |
| L1 synthetic TDOA | **Verified** | **Verified** | None |
| L2 room acoustics | **Verified, optional** | **Verified** | None; dependency-gated |
| L3 realism | **Partial** | **Partial** | None |
| L4 calibration | **Target** | **Target** | None |
| 3D DOA and motion | **Partial** | **Partial** | None |
| Isaac Sim | **Verified** | **Verified** | None |
| Isaac Lab | **Verified** | **Verified** | None |
| Training performance | **Verified locally** | **Verified** | None; local-host result only |
| GUI | **Partial** | **Partial** | None |
| Dataset recording | **Partial** | **Partial** | None |
| Distribution | **Partial** | **Partial** | None |
| Alex demonstration | **Partial evidence** | **Partial** | None |
| SquadBot adapter | **External, verified consumer** | **External** | External details not re-read by policy |

## Claim audit

### 1. Package and schema versions

**Plan claim:** The package release is `1.7.0`; the independent frame schema
remains `ias.audio_sensor_frame.v1`.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `pyproject.toml` sets `[project].version = "1.7.0"`.
- `src/isaac_audio_sensors/__init__.py` exports `__version__ = "1.7.0"`.
- `src/isaac_audio_sensors/core/constants.py` sets
  `FRAME_SCHEMA_VERSION = "ias.audio_sensor_frame.v1"`.
- `src/isaac_audio_sensors/core/schema.py` uses that constant as the generated
  schema's `schema_version.const`.
- `src/isaac_audio_sensors/core/types.py` defaults `AudioSensorFrame` to that
  value and rejects other schema versions.
- `docs/schemas/audio_sensor_frame.v1.schema.json` contains the matching
  `"const": "ias.audio_sensor_frame.v1"` and the same required top-level
  fields produced by `audio_sensor_frame_json_schema()`.

**Covering tests:**

- `tests/test_audio_sensor_frame_contract.py` compares the generated schema to
  the checked-in schema exactly and freezes the version constant.
- `tests/test_isaac_audio_core.py` checks package version, schema version, and
  JSON round-trip behavior.

**Tracked documentation:**

- `docs/api_freeze_0_1.md`
- `docs/schemas/audio_sensor_frame.v1.schema.json`
- `docs/versioning.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/S0/S0.2/gate_import_smoke.log` records a separate
  import smoke returning `1.7.0`.
- `outputs/isaac_audio_sensors/extension_trace.frames.jsonl` contains emitted
  frames with `schema_version` equal to `ias.audio_sensor_frame.v1`.

**Discrepancy:** None in Section 3. `docs/api_freeze_0_1.md` still describes
the active distribution as `1.1.0`; that ancillary release prose is stale but
does not change its v1 frame-contract rules or the verified Section 3 claim.

### 2. Core contract

**Plan claim:** Stable `AudioSensorFrame` v1, JSON Schema, JSON/JSONL
round-trip, units, poses, provenance, and deterministic event ordering.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/types.py` defines and validates `Pose3D`,
  `DoaEstimate`, `AudioDetection`, and `AudioSensorFrame`, including stable
  units, provenance, timestamps, `max_events`, and schema version.
- `src/isaac_audio_sensors/core/schema.py` exports the public JSON Schema.
- `src/isaac_audio_sensors/core/io/traces.py` implements frame-to-dictionary,
  dictionary-to-frame, JSON, and JSONL serialization.
- `src/isaac_audio_sensors/core/scene.py` sorts active sources by start time,
  source id, and prim path before deterministic truncation and id creation.

**Covering tests:**

- `tests/test_audio_sensor_frame_contract.py`
- `tests/test_isaac_audio_core.py`

**Tracked documentation:**

- `docs/api_freeze_0_1.md`
- `docs/schemas/audio_sensor_frame.v1.schema.json`
- `docs/v1_scope.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.latest_frame.json`
- `outputs/isaac_audio_sensors/extension_trace.frames.jsonl`

Both are concrete v1 frame artifacts; they do not replace the tracked contract
tests.

**Discrepancy:** None.

### 3. L0 geometry

**Plan claim:** `geometry_only` provides deterministic bearing, elevation
where observable, distance, sector, and RMS proxies.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/backends/geometry.py` computes array-frame
  bearing, geometric elevation, distance, confidence, sector, per-microphone
  RMS proxies, and aggregate RMS in deterministic source order.
- `src/isaac_audio_sensors/core/microphone_array.py` defines named layouts,
  transforms local microphone positions to world positions, and reports
  layout rank.
- `src/isaac_audio_sensors/core/math_utils.py` owns the coordinate and bearing
  math.
- `src/isaac_audio_sensors/core/doa/sector_mapping.py` owns the frozen
  eight-sector mapping.

**Covering tests:**

- `tests/test_isaac_audio_layers.py` covers canonical bearings, rotated arrays,
  source ordering, and deterministic non-waveform frames.
- `tests/test_l0_l1_hardening.py` covers degenerate geometry, exact elevation,
  sector boundaries, RMS/directivity, and repeatability.

**Tracked documentation:**

- `docs/backends.md`
- `docs/tdoa_doa.md`
- `docs/acoustic_fidelity.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/extension_trace.frames.jsonl` contains current
  `geometry_only` v1 frames with bearing, elevation, distance, sector, and RMS.
- `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.frames.jsonl` contains
  L0 clear and occluded frames from the live gate.

**Discrepancy:** None.

### 4. L1 synthetic TDOA

**Plan claim:** `tdoa_synthetic` provides delays, RMS, deterministic stress
controls, confidence, and explicit ambiguity.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/backends/tdoa.py` computes per-microphone
  direct-path delay and RMS, deterministic seeded delay/jitter/gain stress,
  observable-residual confidence, multi-microphone least-squares DOA, and
  explicit two-microphone ambiguity.
- `src/isaac_audio_sensors/core/doa/ambiguity.py` constructs and deduplicates
  the two-microphone candidates and applies only an explicit front-hemisphere
  prior.
- `src/isaac_audio_sensors/core/scene.py` supplies stable scheduling and ids.

**Covering tests:**

- `tests/test_isaac_audio_backends.py` covers clean/noisy cases, deterministic
  replay, elevation gating, and front/back ambiguity.
- `tests/test_l0_l1_hardening.py` covers stress controls, invalid apertures,
  confidence independence from oracle bearing, and deterministic output.

**Tracked documentation:**

- `docs/backends.md`
- `docs/tdoa_doa.md`
- `docs/acoustic_fidelity.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl`
  contains `tdoa_synthetic` v1 frames.
- `outputs/isaac_audio_sensors/archive/2026-07-03_pre_cleanup/isaac_sim_live_smoke.frames.jsonl`
  retains the prior live L0/L1 motion trace at its actual current path.

**Discrepancy:** None.

### 5. L2 room acoustics

**Plan claim:** `room_acoustics` and `room_acoustics_srp` generate approximate
room waveforms and GCC/SRP estimates when optional dependencies are installed.

**Confirmed status:** **Verified** (optional dependency-gated capability).

**Implementation evidence:**

- `src/isaac_audio_sensors/core/backends/room_acoustics.py` lazily imports
  `pyroomacoustics`, builds a shoebox room, simulates per-source premixes and
  microphone mixtures, records RIR/GCC diagnostics, exports waveforms through
  an optional sink, and dispatches least-squares or SRP-PHAT DOA.
- `src/isaac_audio_sensors/core/doa/gcc_phat.py` provides waveform-derived
  pairwise TDOA and RMS helpers.
- `src/isaac_audio_sensors/core/doa/srp_phat.py` provides deterministic
  waveform-domain azimuth/elevation steering and confidence.
- `src/isaac_audio_sensors/core/io/waveforms.py` implements per-frame and
  continuous WAV sinks.

**Covering tests:**

- `tests/test_isaac_audio_backends.py` covers the fake and optional real room
  paths, GCC diagnostics, multiple sources, and `room_acoustics_srp`.
- `tests/test_waveform_export.py` covers mixture content, scheduling,
  deterministic export, JSONL round-trip, and continuous sessions.

**Tracked documentation:**

- `docs/room_acoustics.md`
- `docs/backends.md`
- `docs/acoustic_fidelity.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.frames.jsonl`
  contains current `room_acoustics` frames.
- `outputs/isaac_audio_sensors/live_waveforms_gui/room_acoustics_anon_0x60fc26ce35c0_World1.usd_rig_front_0_0.wav`
  is an exact current multichannel room-output artifact.
- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/media/audio/alex_head_quad_session.wav`
  is a named four-channel `room_acoustics_srp` session artifact.

**Discrepancy:** None. The status is not a claim that the optional dependency
is installed everywhere or that the room is a calibrated acoustic twin.

### 6. L3 realism

**Plan claim:** Material-aware per-microphone ray/transmission occlusion
exists; diffraction, calibrated materials, hardware response, richer noise,
and other advanced effects remain incomplete.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `src/isaac_audio_sensors/isaac/occlusion.py` casts per-source/per-microphone
  rays, walks multiple distinct blocking prims, resolves explicit USD loss,
  material presets, or a default, and emits broadband and octave-band
  `SourceOcclusion` records with capped attenuation.
- `src/isaac_audio_sensors/core/scene.py` exposes the shared occlusion
  consumption and diagnostic helpers.
- `src/isaac_audio_sensors/core/backends/geometry.py` and
  `src/isaac_audio_sensors/core/backends/tdoa.py` apply per-microphone
  broadband attenuation.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py` applies broadband
  or band-filtered attenuation to each source premix before summing.
- The occlusion module explicitly states that diffraction, edge effects, and
  thickness-dependent transmission are not modeled; its preset table is
  illustrative rather than calibrated truth.

**Covering tests:**

- `tests/test_isaac_occlusion.py` covers ray exclusion, partial/full blocking,
  material attributes and presets, multi-hit accumulation, per-band filtering,
  diagnostics, exported WAV effects, and thick-wall deduplication.
- `tests/test_acoustic_fidelity.py` keeps L3 outside the runtime backend
  registry.

**Tracked documentation:**

- `docs/acoustic_fidelity.md`
- `docs/limitations.md`
- `docs/backends.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json` records
  `status: "passed"`, material-aware attenuation, and
  `raycast_transmission_v1` diagnostics.
- `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.viewport.png`

**Discrepancy:** None. The implementation confirms both the shipped subset and
the missing physical effects named by the plan.

### 7. L4 calibration

**Plan claim:** The fidelity vocabulary exists, but no stable calibration
artifact or automatic sim-vs-real workflow is implemented.

**Confirmed status:** **Target**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/fidelity.py` defines L4
  `sim_real_calibration` metadata as `experimental_tooling_v1`, with no backend
  ids and `runtime_selectable_v1=False`.
- No calibration implementation module, stable calibration artifact schema,
  or automatic sim-vs-real workflow exists under `src/isaac_audio_sensors/`,
  `scripts/`, or `tests/`; the filename and text searches found only future
  vocabulary and roadmap statements.

**Covering tests:**

- `tests/test_acoustic_fidelity.py` asserts that L4 is metadata-only, has no
  backend id, cannot be selected through `get_backend()`, and is documented as
  experimental/tooling.

**Tracked documentation:**

- `docs/acoustic_fidelity.md`
- `docs/limitations.md`
- `docs/reference_rig_hardware_environment.md`

**Machine-local evidence:** No L4 calibration artifact exists under
`outputs/isaac_audio_sensors/`. That negative inventory result is consistent
with **Target**; unrelated live sensor captures are not treated as calibration.

**Discrepancy:** None.

### 8. 3D DOA and motion

**Plan claim:** Rank-aware 3D DOA, elevation, SRP-PHAT, and explicitly authored
Doppler velocities exist; automatic velocity derivation and intra-window
motion do not.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/microphone_array.py` reports full 3D affine
  rank and includes a tetrahedral rank-3 layout.
- `src/isaac_audio_sensors/core/backends/tdoa.py` selects a 3D least-squares
  solve only for rank-3 arrays and keeps planar elevation unset.
- `src/isaac_audio_sensors/core/doa/srp_phat.py` adds an elevation grid only
  for rank-3 layouts.
- `src/isaac_audio_sensors/core/doppler.py` computes factors only from optional
  `velocity_world_mps` values already authored on source/array specs.
- `src/isaac_audio_sensors/core/backends/room_acoustics.py` resamples one
  source signal by one factor per window; it explicitly excludes
  intra-window motion.
- No Isaac pose-history velocity derivation path was found.

**Covering tests:**

- `tests/test_srp_phat.py` covers rank-3 bearing/elevation recovery, planar
  azimuth-only behavior, determinism, and invalid input.
- `tests/test_doppler.py` covers factor math, L1 metadata, L2 resampling, and
  velocity-free compatibility.
- `tests/test_isaac_audio_backends.py` covers tetrahedral L1 elevation and
  planar elevation gating.

**Tracked documentation:**

- `docs/tdoa_doa.md`
- `docs/room_acoustics.md`
- `docs/limitations.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/manifest.json`
  records an SRP-PHAT head-array run and scripted robot motion.
- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/evidence/showcase.frames.jsonl`
  contains the emitted moving-array/source sequence.

**Discrepancy:** None. Scripted robot yaw demonstrates changing poses, not
automatic velocity derivation or continuous intra-window propagation.

### 9. Isaac Sim

**Plan claim:** Lazy stage discovery, live transforms, moving arrays/sources,
occlusion, overlays, JSONL/WAV output, and lifecycle handling exist.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `src/isaac_audio_sensors/isaac/discovery.py` implements semantic array/source
  discovery with explicit paths, metadata, names, native sound signals, and
  configurable selection.
- `src/isaac_audio_sensors/isaac/pose_resolver.py` lazily uses USD world
  transforms with import-safe fallbacks.
- `src/isaac_audio_sensors/isaac/stage_snapshot.py` builds live scene snapshots.
- `src/isaac_audio_sensors/isaac/stage_cache.py` caches discovered prims while
  re-reading their live state and invalidates on relevant USD changes.
- `src/isaac_audio_sensors/isaac/extension.py` implements start/stop/reset/close,
  update throttling, live snapshot capture, JSONL writing, per-frame/session
  WAV sinks, occlusion, and structured/debug-draw overlays.
- `src/isaac_audio_sensors/isaac/stage_audio.py` authors ordinary USD audio
  metadata and transforms.

**Covering tests:**

- `tests/test_isaac_stage_cache.py` covers cached live ticks, transform updates,
  invalidation, rediscovery, and listener cleanup.
- `tests/test_usd_debug_geometry.py` covers overlay geometry authoring and
  cleanup.
- `tests/test_isaac_sim_extension_install.py` covers extension installation
  planning and safe persistent configuration behavior.

**Tracked documentation:**

- `docs/isaac_sim.md`
- `docs/architecture.md`
- `docs/isaac_sim_gui_guide.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/archive/2026-07-03_pre_cleanup/isaac_sim_live_smoke.json`
- `outputs/isaac_audio_sensors/archive/2026-07-03_pre_cleanup/isaac_sim_live_smoke.frames.jsonl`
- `outputs/isaac_audio_sensors/isaac_occlusion_live_gate.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`

**Discrepancy:** None in the Section 3 capability claim. Some tracked docs
still name the old root `isaac_sim_live_smoke.*` paths; the retained files now
live under the dated archive path above, as explained by
`outputs/isaac_audio_sensors/README.md`.

### 10. Isaac Lab

**Plan claim:** `SensorBase` integration, fixed-shape multi-environment
tensors, GPU placement, stage/entity binding, reset, and selected-environment
updates exist.

**Confirmed status:** **Verified**.

**Implementation evidence:**

- `src/isaac_audio_sensors/lab/_isaac_lab.py` lazily resolves modern or legacy
  Isaac Lab base classes without poisoning a pre-Kit import.
- `src/isaac_audio_sensors/lab/audio_array_sensor.py` subclasses the resolved
  `SensorBase`, implements explicit/stage/entity providers, timestamped lazy
  updates, selected `env_ids`, reset, scalar dispatch, and batched dispatch.
- `src/isaac_audio_sensors/lab/audio_array_sensor_data.py` allocates fixed-shape
  torch tensors on the configured sensor device and updates/reset selected
  rows.
- `src/isaac_audio_sensors/lab/entity_binding.py` and
  `src/isaac_audio_sensors/lab/stage_binding.py` implement entity-tensor and
  cloned-stage binding.
- `src/isaac_audio_sensors/lab/batched_backend.py` keeps L0/L1 tensor math on
  device.

**Covering tests:**

- `tests/test_isaac_lab_entity_binding.py` covers root/body tensor resolution,
  selected-env reads, env-origin policy, error reporting, and CUDA placement
  when available.
- `tests/test_lab_batched_backend.py` covers scalar/batched parity, selected
  updates, reset, truncation, device paths, and dispatch prerequisites.

**Tracked documentation:**

- `docs/isaac_lab.md`
- `docs/architecture.md`
- `docs/limitations.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json` records real
  `SensorBase`/`SensorBaseCfg` class resolution, `cuda:0` buffers, selected-env
  behavior, stage binding, and entity-tensor binding.

**Discrepancy:** None. The artifact also honestly records that an additional
full `InteractiveScene`/`RigidObject` probe was blocked on that host; the
supported tensor-scene entity path and the Section 3 claim remain evidenced.

### 11. Training performance

**Plan claim:** A machine-local GPU artifact reports 4,096 environments at p95
`13.09 ms` for batched L1 against a `20 ms` budget.

**Confirmed status:** **Verified** (machine-local only).

**Implementation evidence:**

- `src/isaac_audio_sensors/lab/batched_backend.py` implements vectorized L0/L1
  bearing, sector, amplitude, TDOA, and least-squares tensor operations.
- `src/isaac_audio_sensors/lab/audio_array_sensor.py` dispatches eligible
  entity bindings to the batched path and writes selected rows in one batch.

**Covering tests:**

- `tests/test_lab_batched_backend.py` checks scalar/batched numerical parity,
  selected environments, reset, truncation, device behavior, and dispatch.

**Tracked documentation:**

- `docs/isaac_lab.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`, `perf` block:
  `backend="tdoa_synthetic"`, `compute_path="batched"`, `device="cuda:0"`,
  `num_envs=4096`, `steps=50`, mean `12.734441657084972 ms`, p95
  `13.08835600502789 ms`, budget `20.0 ms`, and `status="passed"`.

**Discrepancy:** None in Section 3. The p95 rounds to the claimed `13.09 ms`.
An earlier indicative `~5.6 ms/step` sentence remains in `docs/isaac_lab.md`;
the current named artifact and Section 3 value are the auditable result and do
not create a portable performance promise.

### 12. GUI

**Plan claim:** The extension supports authoring, discovery, live control,
instruments, audio preview, debug geometry, recording, and export, while the
section-heavy interface is not the final guided experience.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `src/isaac_audio_sensors/isaac/extension_ui/` contains 13 Python modules.
  `window.py` and `sections.py` build nine visible sections for stage,
  array/source authoring, sensor/room controls, instruments, audio output,
  Replicator, and export.
- `controller.py` owns discovery, authoring, sensor lifecycle, overlay/debug
  geometry, recording, configuration, and export actions.
- `instruments.py` renders compass, RMS meters, and timeline views.
- `audition.py`, `spectro.py`, and the audio-output section implement WAV
  preview, waveform/spectrogram rendering, and best-effort audition.
- `exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py` supplies
  the Kit extension lifecycle and `graph_node.py` supplies optional OmniGraph
  integration.

**Covering tests:**

- `tests/test_omniverse_extension_ux.py` covers the entrypoint, author/discover/
  run/export workflow, window sections, live updates, recording, and Kit
  integration fallbacks.
- `tests/test_audio_output_panel.py`
- `tests/test_extension_instruments.py`
- `tests/test_omnigraph_node.py`

**Tracked documentation:**

- `docs/isaac_sim_gui_guide.md`
- `docs/isaac_sim.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.viewport.png`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.instruments.png`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.config.json`
- `outputs/isaac_audio_sensors/prof_gui_artifacts_2026-06-15/`

**Discrepancy:** None. The broad operational feature set is implemented, and
the nine-section scrolling window supports the plan's **Partial** usability
classification rather than a final guided-workflow claim.

### 13. Dataset recording

**Plan claim:** JSON/JSONL, WAV, continuous sessions, and an optional
Replicator writer exist; a dataset-level manifest, atomic shards, validation,
and split tooling do not.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `src/isaac_audio_sensors/core/io/traces.py` implements frame JSON and
  append-only JSONL writers/readers.
- `src/isaac_audio_sensors/core/io/waveforms.py` implements deterministic
  per-frame and continuous multichannel WAV writing.
- `src/isaac_audio_sensors/isaac/extension.py` connects JSONL and WAV writers
  to live updates.
- `src/isaac_audio_sensors/isaac/replicator.py` implements the optional lazy
  Replicator writer, per-frame JSON, a JSONL stream, and a recorder-status
  manifest.
- The Replicator manifest is recorder lifecycle/status metadata, not the
  dataset-level episode/shard/hash/split manifest targeted by Section 4.4.
  No atomic shard, dataset validator, or grouped split implementation was
  found in `src/`, `scripts/`, or `tests/`.

**Covering tests:**

- `tests/test_waveform_export.py` covers JSONL/WAV round-trip, deterministic
  per-frame writes, and continuous-session overlap/tail behavior.
- `tests/test_omniverse_extension_ux.py` covers Replicator registration,
  lifecycle, writes, manifest/status, and package-native fallback recording.
- `tests/test_live_evidence_report.py` covers parsing recorded live evidence.

**Tracked documentation:**

- `docs/audio_assets.md`
- `docs/room_acoustics.md`
- `docs/isaac_sim.md`
- `docs/limitations.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/extension_trace.frames.jsonl`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.replicator/audio_sensor_frames.jsonl`
- `outputs/isaac_audio_sensors/omniverse_extension_live_ux.replicator/audio_sensor_replicator_manifest.json`
- `outputs/isaac_audio_sensors/live_waveforms_gui/room_acoustics_anon_0x60fc26ce35c0_World1.usd_rig_front_0_0.wav`

**Discrepancy:** None. Existing per-run Replicator metadata does not satisfy the
missing dataset-contract features named in the plan.

### 14. Distribution

**Plan claim:** The Python package has wheel/sdist auditing; the Kit entrypoint
still finds `src/` from a checkout, so a registry archive is not yet
self-contained.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `pyproject.toml` defines the setuptools `src` package, extras, and console
  entrypoint.
- `MANIFEST.in` selects tracked source-distribution content and prunes local or
  generated material.
- `scripts/audit_distribution.py` inspects wheel/sdist names, required files,
  unsafe members, forbidden paths/media/content, scope locks, and metadata.
- `exts/isaac_audio_sensors.omni/config/extension.toml` defines the Kit module
  and optional dependencies.
- `exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py` calls
  `_ensure_checkout_src_on_path()`, derives `../../src`, and prepends it to
  `sys.path` when present. The extension archive does not vendor or declare a
  self-contained Python-package payload.

**Covering tests:**

- `tests/test_distribution_audit.py` covers accepted wheel/sdist layouts,
  required entries, version checks, forbidden content, traversal members,
  links, and duplicate normalized paths.
- `tests/test_omniverse_extension_ux.py` covers checkout-based and
  extension-path-only entrypoint import behavior.

**Tracked documentation:**

- `docs/open_source_release_checklist.md`
- `docs/installation.md`
- `docs/isaac_sim_gui_guide.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/S0/S0.2/gate_import_smoke.log` is an existing
  checkout import record, not a clean registry-archive proof.
- No machine-local self-contained Kit registry archive under
  `outputs/isaac_audio_sensors/` was identified.

**Discrepancy:** None. Older release examples and checklist lines in
`docs/installation.md` and `docs/open_source_release_checklist.md` still name
`1.0.0`; those ancillary docs reinforce the need for distribution cleanup but
do not contradict the plan's **Partial** classification.

### 15. Alex demonstration

**Plan claim:** A live showcase mounts an array on Alex and demonstrates
DOA-driven turning and occlusion; it is a demonstrator, not the full downstream
phase acceptance chain.

**Confirmed status:** **Partial**.

**Implementation evidence:**

- `scripts/live_alex_audio_showcase.py` resolves/imports Alex V2 assets,
  authors a four-microphone head array, runs `room_acoustics_srp`, enables the
  sensor occlusion pipeline with a scripted raycaster, and drives a bounded yaw
  servo from the estimated bearing.
- `scripts/build_alex_showcase_package.py` packages the trace, evidence,
  multichannel audio, images, video, provenance, metrics, and reproduction
  commands.
- `src/isaac_audio_sensors/isaac/microphone_rig_profiles.py` defines validated
  `alex_head_quad` and `alex_chest_stereo` rig profiles.
- The showcase is a focused sensor demonstrator and contains no SquadBot
  adapter, protobuf, ontology, graph, or downstream phase harness.

**Covering tests:**

- `tests/test_alex_showcase_assets.py` covers deterministic Alex V2 asset
  resolution, provenance, strict evidence, importer settings, and failure
  cases.
- `tests/test_microphone_rig_profiles.py` covers the Alex rig geometry,
  recommended mount paths, mapping round-trip, gains, and validation.

**Tracked documentation:**

- `docs/showcase.md`
- `docs/isaac_sim_gui_guide.md`

**Machine-local evidence:**

- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/`
- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/manifest.json`
- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/evidence/showcase_evidence.json`
- `outputs/isaac_audio_sensors/showcase/alex_audio_detection_2026-07-11/evidence/showcase.frames.jsonl`

The manifest records a real URDF import and Isaac viewport capture,
`room_acoustics_srp`, a head-mounted array, phase residuals of `0.0` and
`-2.0` degrees, and an observed occluded detection.

**Discrepancy:** None. This evidence proves the demonstrator, not the later
installed-artifact/downstream acceptance matrix.

### 16. SquadBot adapter

**Plan claim:** The sibling project converts released frame types into its
protobuf, auditory cue, ontology candidate, and graph contracts; those
contracts remain outside this package.

**Confirmed status:** **External**.

**Implementation evidence:** No SquadBot adapter is implemented under
`src/isaac_audio_sensors/`, which is consistent with the package boundary.
The named external ownership path is
`/home/pacquadr/Desktop/squadbot-av-phase1/adapters/`. Its contents were not
read or copied, as required by this audit's scope.

**Covering tests:** No in-repository test can independently verify the sibling
adapter's protobuf/cue/ontology/graph conversions without crossing the external
boundary. Tracked package tests instead freeze the generic producer contract:

- `tests/test_audio_sensor_frame_contract.py`
- `tests/test_distribution_audit.py`

**Tracked documentation:**

- `docs/v1_scope.md` excludes SquadBot and downstream adapters from package v1
  release ownership.
- `docs/architecture.md` keeps transport, ontology, graph, and task adapters
  outside the pure core.
- `docs/limitations.md` preserves the same boundary.

**Machine-local evidence:** No `outputs/isaac_audio_sensors/` artifact is used
to claim the external conversion chain. The only named implementation evidence
is the external path above.

**Discrepancy:** No repository-boundary disagreement. The qualifier
"verified consumer" was not independently revalidated because reading the
sibling repository was explicitly prohibited; **External** is the confirmed
S0.1 status.

## Plan corrections

No plan corrections required.

All 15 Section 3 table rows agree with the inspected implementation boundary,
and the package/schema sentence agrees with `pyproject.toml`, the core
constant, the generated-schema source, the checked-in schema, and their
contract tests. Accordingly, `docs/final_sensor_development_plan.md` was not
modified.

Ancillary documentation issues discovered during the audit are recorded here
for later scoped cleanup, not treated as Section 3 plan corrections:

- `docs/api_freeze_0_1.md` still has active-release prose for `1.1.0`.
- `docs/installation.md` and `docs/open_source_release_checklist.md` retain
  final-release examples or checklist prose for `1.0.0`.
- `docs/isaac_lab.md` retains an older indicative `~5.6 ms/step` statement;
  the current artifact reports mean `12.7344 ms` and p95 `13.0884 ms`.
- `docs/isaac_sim.md` and `docs/showcase.md` name pre-cleanup root Isaac Sim
  evidence paths; the retained files are now under
  `outputs/isaac_audio_sensors/archive/2026-07-03_pre_cleanup/`.

## Verification record

The audit was verified without executing tests or builds:

1. Re-read this document and checked that the summary and detailed entries
   contain all 15 Section 3 rows plus the package/schema claim, in Section 3
   order.
2. Confirmed every cited repository and machine-local path exists, except for
   explicitly stated negative evidence and the intentionally unread external
   SquadBot path contents.
3. Reconfirmed package `1.7.0`, frame schema
   `ias.audio_sensor_frame.v1`, and the checked-in schema's matching `const`.
4. Checked Git diff/status and diff statistics to ensure repository writes are
   limited to `docs/development/closeouts/S0/`; no plan correction was needed.

No S0.1 claim was blocked. The external SquadBot conversion details remain
intentionally unadjudicated inside this repository and are classified
**External**, not **Verified**.
