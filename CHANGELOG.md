# Changelog

## 2.0.0 - Unreleased

R5.0 establishes the v2 semantic component boundary. This release intentionally removes the root v1 convenience imports and does not provide compatibility shims.

- Reduced the package root to `__version__`; public contracts now live under their owning subsystems.
- Moved dataset manifests and serializers to `recording`, schema generation to `schemas.generate`, USD bounds to `isaac.usd_bounds`, and the headless guided service to `kit.headless`.
- Enforced import direction with an AST architecture contract while keeping Isaac, Lab, Kit, Torch, and Omniverse optional and lazy.
- Removed duplicate package examples, manifest aliases, production test matrices, private Kit re-exports, and GUI/headless comparison scaffolding without changing serialized v1 schemas.

R5.1 narrows the simulator-independent core without changing serialized v1 contracts.

- Reduced `core.__all__` to the eleven fundamental sensor models; importing `isaac_audio_sensors.core` no longer loads NumPy, recording, concrete backends/effects, or optional simulator runtimes.
- Removed Lab state and fixed-value stage convention fields from `AudioSensorConfig`; meters and Z-up remain validated, while Isaac Lab uses `AudioArraySensorCfg`.
- Made the normalized array quaternion the sole pose authority, consolidated propagation on `PropagationBackend`, and removed duplicate array, plugin-output, basis, and occlusion helpers.
- Made the three Python schema generators authoritative, replaced specialized writers with `write_json_schema`, and moved JSON Schema validation to the `dev` extra.
- Preserved frame, calibration, manifest, trace, and provenance semantics; legacy v1 traces may omit the additive `units.elevation` field as originally intended.
- Consolidated schema coverage and replaced the catch-all core test file with focused config, types, microphone-array, and math tests.

R5.2 simplifies backends, DSP, and effects without changing valid-input results.

- Made `get_backend()` the sole public backend resolver and `registered_backend_ids()` the authoritative inventory, with dependency, device, runtime-profile, and structural contract checks derived from plugin declarations.
- Split immutable effects configuration, dict/TOML normalization, and active-stage semantic validation into focused modules while preserving the established DSP order and diagnostics.
- Split room-acoustics orchestration, signal preparation, pyroomacoustics rendering, and diagnostic construction into a compatible package without changing formulas, source order, seeds, phase cursors, units, coordinates, or frame meaning.
- Removed unused compatibility and test-only registry validation paths, legacy effects flags, private room helper tests, and redundant disabled-stage matrices while retaining direct backend imports and actionable optional-dependency errors.

R5.3 simplifies recording and dataset sessions without changing serialized v1 artifacts.

- Reduced `recording.__all__` to the maintained models, reports, errors, `SessionRecorder`, `SessionDataset`, replay, validation, FLAC, manifest IO, and split-plan services; internal writers, filesystem seams, state, marker, planner, and recovery wrappers are no longer public.
- Made `SessionDataset` the shared streaming authority for lifecycle, manifests, markers, record ordering, audio joins, validation, replay, and FLAC export.
- Composed `SessionRecorder` from internal writing, recovery, and manifest-building components; frame timestamps now drive automatic time-gap diagnostics, and `cancel()` replaces token-based incomplete finalization.
- Made manifest parsing strict and canonical, made manifest and split writes atomic, unified checksum verification, and replaced text-classified failures with structured layout errors.
- Removed duplicate helper-level, seam, callback, retry, snapshot, and retained-mode test matrices while retaining crash/recovery, replay, bounded-memory, corruption, split, statistics, time-gap, and real FLAC coverage.

R5.4 narrows `isaac` to the live USD/Isaac bridge without changing frame semantics.

- Renamed the live sensor module to `isaac.sensor`; removed offline/config construction, legacy registries, and compatibility paths without a shim.
- Moved microphone and sound profiles plus validation to `kit`, which owns extension configuration and workflow behavior.
- Made Kit own JSONL paths and waveform-sink construction; the sensor only consumes and closes an injected core `WaveformSink`.
- Centralized lazy update/timeline subscriptions, anchored-room refresh, and live occlusion state while preserving discovery, cache, motion, stage time, debug, frame publication, and Replicator behavior.
- Consolidated lifecycle tests around public behavior and strengthened the exact Isaac export and fresh-import isolation contracts.

Stage 1 dynamic acoustics required by SquadBot (phase S3 of the final sensor
development plan). `ias.audio_sensor_frame.v1` is unchanged; all new effects
and diagnostics are additive, every effect defaults off, and the compatibility
off-state is preserved.

- Added pose-derived source and array velocity with tagged first-sample, reset, stale-time, teleport, smoothing, recovery, and authored-precedence policies.
- Added opt-in session time-gap preservation and segmented intra-window motion with bounded interpolation, piecewise Doppler/RIR rendering, and exact gap accounting.
- Added per-channel gain, fractional delay, polarity, and frequency-response effects with honest metadata-only L1 adapters and typed unsupported waveform cases.
- Added seeded spectral self-noise, ambient coherence, clock jitter, and drift with deterministic named streams, replay, isolation, and additive diagnostics.
- Added the post-mix electronics path for saturation/clipping, quantization, TPDF dither, and optional AGC with clipping and gain-trace diagnostics.
- Added L2 waveform source/microphone directivity in `per_pair_direct_path` mode, applying signed polar and frequency response to each complete convolved pair stem.
- Added noise-aware SRP bearing confidence; `room_srp` confidence values change behavior without a schema change and now degrade on noise-dominated input instead of saturating.
- Added measured-absorption provenance, nominal transmission separation, dynamic-room/material invalidation, and live direct-ray occlusion refresh without claiming diffraction.
- Added the supported/unsupported motion and multi-source stress matrix plus a published claim-to-evidence fidelity envelope with explicit geometry, dependency, performance, and realism limits.
- Consolidated current product documentation into the canonical technical wiki, removed the obsolete root `docs/` tree, retained the applied R0 specification as authorized raw material, and added a tested documentation boundary without changing Python, CLI, schema, or runtime behavior.

## 1.9.0 - Unreleased

Stage 1 recording, replay, diagnostics, and operational GUI (phase S2 of the
final sensor development plan), in progress.

- Added the frozen S2.1 session/shard dataset layout: the import-safe
  `isaac_audio_sensors.core.dataset` subpackage (`ias.dataset_frame_record.v1`
  records, `ias.shard_completion.v1` completion markers, deterministic bounded
  shard packing, episode-seed derivation, canonical configuration hashing,
  trace-projection gate, lifecycle classification, and full session-layout
  validation), the committed deterministic reference session fixture at
  `examples/datasets/reference_session_v1/`, and its regeneration tooling.
  `ias.audio_dataset_manifest.v1` and `ias.audio_sensor_frame.v1` are
  unchanged.

## 1.8.0 - Unreleased

Stage 1 stable installable foundation (phase S1 of the final sensor
development plan): additive `ias.audio_dataset_manifest.v1` and
`ias.audio_calibration_profile.v1` contracts, runtime profiles, plugin
protocols, canonical self-contained Kit extension build, and Linux
base/acoustic-pack artifacts. `ias.audio_sensor_frame.v1` is unchanged.

Official Isaac 6.0.1 / Isaac Lab 3.0.0-beta2 launcher migration:

- Added the independent `ias.audio_dataset_manifest.v1` and
  `ias.audio_calibration_profile.v1` dataclass, schema, deterministic JSON,
  validation, and valid/invalid fixture contracts.
- Added configuration-validated `training_features` and `waveform_fidelity`
  runtime profiles. `waveform_fidelity` is the compatibility default; unknown
  profiles and waveform export under `training_features` fail closed.
- Added import-safe `PropagationBackend`, `DoaEstimator`, and
  `AudioFeatureExtractor` protocols plus frozen capability declarations and a
  registry that rejects duplicate ids, missing dependencies at resolution,
  incompatible devices/profiles, output-contract lies, and false determinism.
  Existing L0/L1/L2 backends and the GCC/SRP estimators are registered without
  changing backend construction or simulation semantics; no core audio feature
  extractor or learned model is claimed.
- Added exact schema regeneration through the CLI and Makefile, deterministic
  valid-fixture regeneration, and distribution inventory coverage.
- Added the canonical Kit extension builder and archive audit. Kit archives now
  vendor the maintained wheel source byte-for-byte, record deterministic source
  provenance and a tree hash, and fail closed on missing, corrupt, or ambiguous
  packaged/developer mode metadata without borrowing an installed package.
- Added a version synchronization build gate deriving every current-release
  surface from `pyproject.toml` while leaving historical references unchanged.
- Added the deterministic, hash-locked Linux `cp312` acoustic-pack builder,
  offline atomic installer, and archive audit. Pack dependencies install only
  into private immutable version roots; Kit-owned NumPy is validated and never
  installed or shadowed.
- Added fail-closed pack activation with runtime, distribution, host-origin,
  and preloaded-module provenance checks, plus deterministic capability
  discovery and the `capabilities --json` CLI report. Removing a pack leaves
  L0/L1 healthy and reports the exact L2/L3 pack artifact to install.
- Added `build-pack`, `audit-pack`, and ordered `artifacts` Make targets with a
  combined top-level checksum inventory for all four release artifact forms.
- Added the S1.6 clean-install harness for hash-verified wheel and Kit archive
  staging, backed-up preflight decontamination/restoration, sanitized Kit and
  fresh-venv scenarios, installed-origin evidence, lifecycle/capture/export
  probes, and optional GUI screenshot proof.
- Froze the S1.7 compatibility matrix and public-name inventory. The published
  `1.7.0` frame/schema/config fixtures remain byte-identical and load with
  identical semantics; round trips add only documented optional defaults.
  `AudioSensorConfig.runtime_profile` now also defaults to
  `waveform_fidelity` for direct legacy-style construction.
- Added the S1.8 installed-artifact consumer harness. It hash-verifies and
  installs the wheel in an isolated venv, runs the external adapter contract
  fixtures without installing or modifying the consumer checkout, double-runs
  a canonical trace-to-graph export, scans the installed generic boundary, and
  records unavailable consumer access or dependencies as blockers rather than
  passes.

- Makefile live gates now auto-detect the official installs at `~/isaacsim`
  and `~/IsaacLab`, while keeping `ISAAC_SIM_COMMAND` and `ISAAC_LAB_PYTHON`
  overrides for non-default or legacy runtimes.
- Runtime discovery now lists official Isaac Sim and Isaac Lab launchers first
  and keeps the old `isaac_suitcase` setup as legacy-last fallback.
- The Isaac Lab live smoke forwards official `AppLauncher` flags such as
  `--viz kit`; runs without extra flags keep the existing headless behavior.
- The Isaac Sim extension installer now selects the highest installed Kit
  `user.config.json` version for autoload instead of hardcoding Kit 5.1.
- Docs now use literal official launcher commands and plain `make live-*`
  examples instead of undefined `$ISAAC_*` placeholders.

## 1.7.0 - 2026-06-12

3D DOA, SRP-PHAT, and Doppler release. The frame schema version is unchanged
at `ias.audio_sensor_frame.v1`; all new frame, DOA, and unit fields are
additive optional per the v1 evolution policy, and pre-1.7.0 traces still
load with defaults.

3D DOA and elevation:

- `DoaEstimate` gains additive optional `estimated_elevation_deg` and
  `candidate_elevation_deg` (degrees up from the array's forward/right
  plane, `[-90, +90]`); detections gain `ground_truth_elevation_deg` and the
  `oracle_elevation_error_deg` diagnostic; `units` gains the additive
  `elevation` key.
- The multi-microphone least-squares solver works in full 3D when
  `layout_rank_xyz` reports rank 3; planar arrays keep the exact azimuth-only
  behavior (elevation stays `None` instead of guessing the cone-ambiguous
  sign). `array_geometry_rank_xyz` is recorded in diagnostics.
- New `tetrahedral` layout preset: a centered regular tetrahedron with edge
  length `spacing_m`, the built-in rank-3 layout. Elevation accuracy is
  gated against ground truth in 3D scenes at L1 (clean within 2 degrees) and
  at L2 with real pyroomacoustics.
- `geometry_only` (L0) emits exact geometric elevation.

SRP-PHAT estimation path:

- New public module `isaac_audio_sensors.core.doa.srp_phat`: PHAT-weighted
  steered-response power over a deterministic azimuth grid (2 degrees), plus
  an elevation grid (5 degrees) for rank-3 layouts.
- `RoomAcousticsBackend` accepts `doa_estimator`
  (`"tdoa_least_squares"` default or `"srp_phat"`), and the new
  `room_acoustics_srp` backend id pins SRP-PHAT over the same L2 room
  pipeline. It is selectable through `audio.default_backend`, `get_backend`,
  and the extension GUI, and is placed in the fidelity ladder as a second L2
  backend id. Estimator-id dispatch leaves room for MUSIC later.
- Diagnostics gain `doa_estimator` (frame and detection) and the `srp_phat`
  detection namespace (grid steps, grid point count, pair count, peak and
  mean power); GCC-PHAT TDOA diagnostics stay emitted in both modes.

Doppler:

- `AudioSourceSpec` and `MicrophoneArraySpec` gain additive optional
  `velocity_world_mps`; TOML sources accept the matching key. Velocity-less
  scenes stay byte-identical.
- L1 `tdoa_synthetic` emits metadata-only `doppler_factor` and
  `per_mic_doppler_factor` detection diagnostics when a velocity is set.
- L2 `room_acoustics` resamples each source's window signal by the
  observed/emitted frequency ratio at the array center before simulation, so
  mixtures, GCC/SRP estimates, and exported per-frame and session waveforms
  carry the shift; `doppler_factor` and `doppler_waveform_rendered`
  diagnostics record what was applied. Factors clamp to `[1/8, 8]`.

Deferred:

- Automatic velocity tracking from per-tick Isaac pose deltas (velocities
  are authored on the specs in 1.7.0), per-microphone Doppler rendering,
  rendering sim-time gaps between throttled ticks, and MUSIC.

## 1.6.0 - 2026-06-12

Scene-anchored rooms release: `room_acoustics` rooms now occupy an explicit
world-space box (`origin_m` + `dimensions_m`) instead of being refit around the
current sources and microphones every frame. The frame schema version is
unchanged at `ias.audio_sensor_frame.v1`; diagnostics gain additive room
placement details.

Breaking change:

- `RoomAcousticsBackend` no longer translates source and microphone positions
  into the shoebox with an automatic margin. Existing room-acoustics configs
  whose world positions are outside `[origin_m, origin_m + dimensions_m]` must
  now set `room.origin_m`, move prims inside the room, or choose
  `out_of_bounds="clamp"`. The default policy is `out_of_bounds="error"` so
  authoring mistakes fail with the offending source/mic and room bounds.

Room placement and discovery:

- `RoomAcousticsSpec` adds `origin_m`, `out_of_bounds`, and
  `anchor_prim_path`.
- New helpers derive room specs from world-aligned bounds and resolve room
  absorption from explicit `ias:absorption` attributes, `ias:material` labels,
  or USD semantic labels.
- Isaac Lab stage bindings can set `room_prim_path` to derive one room per
  env from a stage prim's world bounding box, with diagnostics recording
  dimensions, origin, absorption provenance, and the anchor prim.
- Entity bindings can pass an explicit `RoomAcousticsSpec` for room-acoustics
  runs that have no stage anchor.

GUI and visualization:

- The Omniverse extension gains a `Room` section with anchor-prim and
  out-of-bounds controls.
- Debug overlays and persistent USD debug geometry include a yellow
  `room_outline` wireframe box when the scene has a room.
- Live Isaac Lab GPU evidence now records a room-anchoring phase; the
  pre-merge run passed on RTX 4090 with the batched path under budget.

## 1.5.0 - 2026-06-11

GUI instruments release: the Omniverse extension window becomes maintainable
(monolith split into a package) and visual (compass, meters, timeline,
waveform/spectrogram), the viewport becomes the primary interaction surface,
debug geometry becomes persistent USD, and the latest frame wires into Action
Graphs through a runtime OmniGraph node. The frame schema version is
unchanged at `ias.audio_sensor_frame.v1`; the extension config schema stays
`ias.omni_extension_binding.v1` with additive lifecycle keys only.

Refactor (zero behavior change):

- `isaac/extension_ui.py` (4,592 lines) became the `isaac/extension_ui/`
  package with the same import path: `state`, `controller`, `window`,
  `sections` (one builder function per window section), plus
  `constants`/`paths`/`stage_context`/`formatting`/`ui_models` helpers. All
  public and test-consumed names re-export from the package `__init__`.

Instruments (new `Instruments` section, read-only, refreshed per update):

- Polar bearing compass rasterized through `ui.ByteImageProvider`
  (forward = up, clockwise bearings per the v1 convention) with
  occlusion-colored needle, candidate-bearing needles, and sector wedge.
- Per-mic RMS meters (`ui.ProgressBar`, -60 dB floor) and a newest-first
  detection timeline backed by a bounded (50-event) history in UI state.
- The pipe-separated `latest` label keeps frame/backend/source facts;
  bearing, sector, and RMS moved into the instruments.

Audio output (new `Audio Output` section, consumes the 1.2.0 WAV export):

- `WAV Export` toggle plus dir/mode fields flow into the sensor's
  `waveform_dir`/`waveform_mode`; the latest `waveform_paths` render as a
  min/max envelope strip and a numpy-STFT spectrogram (no scipy needed).
- New `core.io.wave_read` decodes FLOAT32/PCM16 WAVs with a stdlib RIFF
  parser so previews work without the optional `room` extra.
- Play/Stop audition via `omni.audioplayer` with a system-player fallback;
  `Open WAV Folder` as the dependable escape hatch.
- Selecting `room_acoustics` now synthesizes a default 6x6x3 m shoebox
  (stage discovery authors no rooms), fixing live room sensors that
  previously failed at simulate time with "requires scene.room".

Viewport-first interaction:

- `Follow Selection` routes clicked prims by discovery class (array/source/
  object) via `omni.usd` SELECTION_CHANGED stage events with a polling
  fallback on the update tick.
- `Live Sync Pose` mirrors manipulator-driven array/source transforms into
  the numeric fields each tick; fields stay the precision path when off.

Persistent USD debug geometry (roadmap item shipped):

- `viz.usd_debug.UsdDebugGeometryAuthor` authors overlay primitives as
  session-layer Spheres/BasisCurves under `/World/IasAudioDebug`
  (configurable), updated in place and pruned per frame; survives pause and
  Stop, removed by `Clear Debug Geometry`.

OmniGraph:

- Runtime-registered Python node `isaac_audio_sensors.omni.
  IsaacAudioSensorFrame` (no `.ogn` codegen; `omni.graph.core` is an
  optional dependency) exposing `frameId`, `timestampMs`, `detectionCount`,
  `bearingDeg`, `sector`, `micIds`, `micRms`, `occluded`, and `frameJson`,
  fed by the new import-safe `isaac.frame_registry` the controller publishes
  on every recorded frame. Registration status is reported verbatim in the
  GUI and gate evidence; `frame_registry.get_latest_frame()` is the Script
  Node alternative.

Verification:

- `make live-omniverse-extension-ux-screenshots` now also requires the
  instruments evidence (compass values, meter fractions, captured
  compass+meter panel PNG), validates persistent USD debug prims on the live
  stage, exercises a real room-acoustics WAV export/preview/audition round
  trip, and records the OmniGraph registration outcome.
- The extension documentation gained Instruments, Audio Output, Work From the Viewport, Use Audio In Action Graphs, and persistent debug geometry guidance; the maintained behavior is now described in [Isaac Sim and Kit](knowledge/wiki/topics/isaac-sim-and-kit.md).

Deferred:

- Editable room-spec fields in the GUI (the default shoebox is constant).
- Spectrogram color-map options and audition scrubbing.
- OmniGraph exec-pin semantics and per-detection array outputs.

## 1.4.0 - 2026-06-11

Occlusion realism and cache-semantics release: discovery caching becomes
semantically explicit, and occlusion upgrades from a uniform per-source
attenuation to a material-aware, frequency-dependent ray/transmission model
that is per-microphone and multi-hit. It is not a wave-acoustic propagation
solver: diffraction, edge effects, and thickness-dependent transmission stay
deferred. The frame schema version is unchanged at
`ias.audio_sensor_frame.v1`; pre-existing v1 traces remain valid and all new
`SourceOcclusion` fields and diagnostics are additive.

Cache semantics:

- `IsaacAudioSceneBindingCfg.rediscover_each_update` is now consumed. The
  default flips from the never-read `True` to `False`, which documents the
  actual shipped 1.3.0 behavior (cache until invalidated) without changing
  runtime behavior; setting `True` now really forces full discovery (one
  `stage.Traverse()`) on every capture. The active policy is reported as
  `diagnostics["stage_snapshot"]["discovery_cache"]["policy"]`.
- The USD notice handler now also inspects `GetChangedInfoOnlyPaths()`:
  info-only changes to discovery-relevant properties (the `ias:` marker
  attributes plus the `filePath`/`inputs:file`/`inputs:audio`/`startTime`/
  `duration`/`gain` aliases discovery reads) invalidate the cache, so newly
  audio-tagged existing prims are discovered without a manual
  `rediscover()`. Pose-only (`xformOp:*`) and unrelated property changes
  keep the cached path; `rediscover()` remains the guaranteed fallback for
  duck-typed stages without notices.

Occlusion physics (documented value changes where multi-hit, partial
blockage, or materials are in play; fully-blocked and clear default
single-wall numbers are unchanged from 1.3.0):

- Ray traversal walks past every blocking surface, deduplicated per prim
  (one thick collider counts as one partition), accumulating per-microphone
  transmission loss capped at `occlusion_attenuation_cap_db` (default
  60 dB).
- Per-hit loss resolves through the new `UsdTransmissionLossResolver`:
  explicit `ias:transmission_loss_db` / `ias:transmission_loss_db_bands`
  attributes on the hit prim, then an illustrative octave-band preset table
  (`OCCLUSION_BAND_CENTERS_HZ`, 125 Hz - 4 kHz: concrete, brick, metal,
  drywall, plaster, glass, wood, fabric, curtain) matched against
  bound-material or prim-path tokens, then the flat
  `occlusion_max_attenuation_db` default. Resolvers are injectable via
  `occlusion_transmission_resolver`.
- `SourceOcclusion` gains additive optional fields:
  `per_mic_attenuation_db`, `per_mic_band_attenuation_db`,
  `band_centers_hz`, `per_mic_hit_prim_paths`, `hit_materials`, and
  `occlusion_model` (`"raycast_transmission_v1"`); the per-source
  `attenuation_db` is now the mean of the per-microphone values (equal to
  the legacy `occlusion_factor * max` for single-hit defaults).
- L0/L1 consume `per_mic_attenuation_db` so blocked microphones lose level
  independently while delays and DOA stay geometric; backends fall back to
  the uniform `attenuation_db` for records without per-mic data.
- L2 applies per-source/per-microphone attenuation to the simulation premix
  before summing (identical to input scaling for uniform records by
  linearity), with zero-phase per-band rFFT filtering when band data is
  present, so the mixture, per-source premix RMS, aggregate RMS, GCC-PHAT
  diagnostics, and exported WAVs stay mutually consistent. A spectral test
  proves a material wall attenuates a high overtone far more than the low
  fundamental in the exported waveform.
- The detection `occlusion` diagnostics namespace additively gains the
  per-mic attenuation and band maps, per-mic hit paths, resolved hit
  materials, and the occlusion model label.
- The `make live-isaac-occlusion` gate adds a material-wall phase (an
  authored 12 dB `ias:transmission_loss_db` measured within 0.5 dB through
  real PhysX raycasts) and a `rediscover_each_update=True` policy phase
  (one full discovery per update, asserted by counter).

Deferred:

- Diffraction and edge effects.
- Thickness-dependent transmission (per-prim loss only).
- An Isaac Lab `occluded` observation buffer.

## 1.3.0 - 2026-06-10

Isaac-native occlusion and live-path caching release. The Isaac layer now
raycasts each active source against each microphone through the PhysX scene
query interface and emits per-source occlusion into the scene snapshot;
pure-core backends only consume it. Steady-state live sensor ticks no longer
re-traverse the USD stage. The frame schema version is unchanged at
`ias.audio_sensor_frame.v1`; pre-existing v1 traces remain valid.

Occlusion (additive, first shipped L3 capability):

- New `isaac.occlusion` module: `IsaacPhysxRaycaster` lazily acquires the
  PhysX scene-query interface, and `compute_scene_occlusion` casts one ray
  per source/microphone pair with endpoint epsilons and bounded re-casts
  past hits on the source or array prims themselves.
- New core `SourceOcclusion` record and optional, additive
  `AudioSceneSnapshot.occlusion` field plus `occlusion_for(...)` lookup; the
  occlusion factor is the fraction of blocked rays and the attenuation is
  baked in by the producer (`occlusion_max_attenuation_db`, default 20 dB).
- `AudioDetection` gains the optional `occluded: bool = False` field. It is
  always serialized by current writers, parsed with a `False` default, and
  listed in the new `OPTIONAL_DETECTION_FIELDS` so the JSON schema does not
  require it; detections also carry an `occlusion` diagnostics namespace.
- All backends consume occlusion uniformly per source: L0/L1 apply
  `attenuation_db` through `extra_gain_db` (delays and DOA unchanged), L2
  scales the source input signal so mixture, premix RMS, and exported
  waveforms agree.
- `IsaacAudioArraySensor` gains `occlusion_enabled` (off by default),
  `occlusion_max_attenuation_db`, and an injectable `occlusion_raycaster`;
  outside Isaac the feature degrades gracefully with an `occlusion` status
  in the stage diagnostics. The Kit extension GUI gains an Occlusion toggle.
- Overlay bearing rays are colored by occlusion state (green/amber/red).
- New `make live-isaac-occlusion` gate: a collider wall between source and
  array must attenuate per-mic RMS by the configured 20 dB via real PhysX
  raycasts, set the occluded flag, keep the discovery cache warm, and
  capture a viewport screenshot of the red occluded bearing ray.

Live-path caching:

- New `isaac.stage_cache.StageAudioCache`: the first capture runs full
  semantic discovery (one `stage.Traverse()`); steady-state ticks rebuild
  specs only for the cached audio prim paths at the new time code. Cached
  snapshots are asserted equal to fresh full-discovery snapshots.
- Invalidation via `Usd.Notice.ObjectsChanged` resyncs on real USD stages
  (info-only changes never invalidate; poses are re-read every tick), cheap
  per-tick path validation with transparent full-rediscovery fallback, and
  an explicit `sensor.rediscover()`.
- `IsaacStagePoseResolver` and `discover_stage_audio` accept a pre-traversed
  `prims` tuple; `frame.diagnostics["stage_snapshot"]` gains a
  `discovery_cache` summary.

Isaac Sim 5.x visualization fixes:

- The debug-draw shim also resolves `isaacsim.util.debug_draw` (the 5.x
  module name), so overlays render live again instead of falling back to
  serialized primitives.
- Point sizes and line widths are converted from meters to the pixel units
  the debug-draw interface expects; they were sub-pixel before.

Deferred:

- Frequency-dependent or material-based occlusion transmission.
- Diffraction and edge effects.
- Per-microphone (instead of per-source) occlusion attenuation.
- An Isaac Lab `occluded` observation buffer.

## 1.2.0 - 2026-06-10

Audio output release: the room backend now renders true microphone mixtures
and exports them as multichannel WAVs. The frame schema version is unchanged
at `ias.audio_sensor_frame.v1`; the previously empty `waveform_paths` field
is now populated when waveform export is enabled, and all diagnostic value
changes below are documented physics improvements.

Mixtures and sample-accurate scheduling (documented value changes at L2):

- All active sources share one `pyroomacoustics` room per frame
  (`simulate(return_premix=True)`) instead of one room per source.
  Per-source diagnostics (`estimated_tdoa_matrix_s`, `gcc_phat_peaks`,
  `per_mic_rms`, `rir_length_samples`, `rir_peak_delay_s`) now derive from
  the per-source simulation premix, so their values shift relative to 1.1.
- `aggregate_per_mic_rms` at L2 is now the RMS of the true mixture instead
  of an incoherent per-source power sum; coherent interference between
  sources is now physical.
- Source scheduling is sample-accurate: a source starting mid-window gets
  leading zero-padding, a source that started before the window resumes from
  its elapsed offset (file assets play through across frames instead of
  restarting), and content truncates at min(source end, window end).
- Generated sources emit a deterministic, phase-continuous two-tone signal
  over their whole active interval (seeded fundamental plus a golden-ratio
  overtone that keeps GCC-PHAT correlation aperiodic), with fixed per-mode
  scaling instead of per-window peak normalization.
  `RoomAcousticsBackend(source_waveform_duration_s=...)` is retained for API
  compatibility but no longer limits emission.
- File-backed `audio_asset_path` assets with mismatched sample rates are now
  resampled with `scipy.signal.resample_poly` instead of raising.

Waveform export (additive):

- New `core.io.waveforms` module: `write_multichannel_wav`,
  `FrameWaveformWriter` (one deterministic `{frame_id}.wav` per frame),
  `ContinuousWaveformWriter` (one growing session WAV with window-exact
  chunks, overlap-added reverb tails, and `[start_sample, end_sample)` frame
  slices), and the `WaveformSink` protocol. WAVs use the `FLOAT` subtype
  with channels in microphone order.
- `RoomAcousticsBackend(waveform_writer=...)` writes each frame's mixture
  and populates `AudioSensorFrame.waveform_paths` plus a `waveform` frame
  diagnostics namespace; frames with no active sources write window-length
  silence so session streams stay gapless.
- `IsaacAudioArraySensor` gains `waveform_dir` and `waveform_mode`
  (`"per_frame"` or `"session"`); `reset()` starts a new session and
  `close()` flushes the final reverb tail. The Isaac Lab sensor activates
  the previously reserved `write_waveforms` with a new `waveform_dir`
  (per-frame mode, one `env_{id}` subdirectory per environment). TOML
  configs gain `audio.waveform_dir`.
- New detection diagnostics `scheduled_start_offset_samples` and
  `scheduled_content_sample_count`; new frame diagnostic
  `window_sample_count`.
- The live Isaac Sim smoke now requires WAV round-trip evidence for the
  room backend: non-empty `waveform_paths`, an existing file, and a
  `soundfile` read matching the frame's rate, mic count, and window length.
- Added audio asset path, auto-resampling, external-corpus, and test-fixture guidance; the maintained behavior is now described in [Public Contracts and Recording](knowledge/wiki/topics/public-contracts-and-recording.md) and [Acoustic Modeling](knowledge/wiki/topics/acoustic-modeling.md).

Deferred:

- Doppler from per-tick source motion is explicitly deferred to Block 8
  together with source velocity tracking; the continuous session stream is
  the concatenation of captured windows and does not render sim-time gaps
  between throttled ticks as silence.

## 1.1.0 - 2026-06-10

Physics coherence release for the v1 line. Every shared quantity now means
the same thing at L0, L1, and L2, and no observable output leaks ground
truth. The frame schema version is unchanged at `ias.audio_sensor_frame.v1`;
all value changes are documented physics bug fixes plus additive optional
APIs and diagnostics.

Documented physics corrections (bug fixes preserving the v1 frame shape):

- L0/L1 synthetic RMS now follows the pressure law `1/distance` instead of
  `1/distance^2`. The reference convention is documented: `gain_db` is the
  source level re 1 m, so RMS at 1 m equals `10 ** (gain_db / 20)`.
- `AudioSourceSpec.gain_db` is now applied at L0 and L1, matching the
  existing L2 behavior.
- `aggregate_per_mic_rms` is now an incoherent power sum `sqrt(sum(rms^2))`
  across sources in all three backends instead of a linear sum.
- Bearing confidence no longer uses the ground-truth bearing: it derives only
  from the least-squares residual, array geometry, and stress settings. The
  ground-truth comparison moved to the additive detection diagnostic
  `oracle_bearing_error_deg`, and confidence is invariant to ground-truth
  changes by test. `estimate_doa_from_delays` keeps its
  `ground_truth_bearing_deg` parameter for compatibility but ignores it.
- The L1 stress controls replace the alternating-sign bias with real Gaussian
  draws: delay noise and clock jitter are deterministic per
  `(seed, frame_id, mic_id)`, and gain mismatch is a static per-mic draw per
  `(seed, mic_id)`. Zero-noise outputs are bit-identical to before.

Additive APIs, diagnostics, and tooling:

- `TdoaSyntheticBackend(seed=...)` selects the deterministic noise stream;
  the default (`seed=None`) remains fully deterministic.
- `TdoaSyntheticBackend(air_absorption_db_per_m=...)` adds optional broadband
  air-absorption attenuation to L1 RMS (default 0.0 is a no-op).
- `MicrophoneSpec.self_noise_db` is now modeled at L0/L1 as a per-mic noise
  floor in `aggregate_per_mic_rms`; `AudioSourceSpec.directivity` is now
  modeled at L0/L1 with a first-order omni/cardioid factor. Unknown
  directivity values and cardioid sources without orientation behave as omni
  and are reported via the `directivity_applied` diagnostic. Both remain
  metadata-only at L2.
- New detection diagnostics: `source_gain_db`, `directivity`,
  `directivity_applied`, `oracle_bearing_error_deg`, `noise_seed`,
  `air_absorption_db_per_m`.
- The live Kit update-stream subscription now respects `update_period_s`
  instead of forcing a capture every tick.
- GCC-PHAT pairwise estimation caches per-channel rFFTs and mirrors the
  symmetric half of the pair matrix; outputs are unchanged.
- New `make regenerate-traces` target and
  `scripts/regenerate_example_traces.py` regenerate the backend-generated
  JSON example traces, which are refreshed for the corrected physics.
- Added the v1 frame schema evolution policy defining compatible additive frame changes; the maintained rule is now described in [Product Boundary and Compatibility](knowledge/wiki/decisions/product-boundary-and-compatibility.md).

## 1.0.0 - 2026-05-24

This is the final v1 package release promoted from `1.0.0rc1`.

- Freezes the `AudioSensorFrame` v1 API/data contract for the v1 line except
  for compatible additive changes and bug fixes.
- Keeps the frame schema version separate from the package version at
  `ias.audio_sensor_frame.v1`.
- Reviewed the `1.0.0rc1` feedback window and promoted early with explicit
  maintainer approval on 2026-05-24.
- Confirmed the changes after `v1.0.0rc1` were non-breaking docs and evidence
  updates before the final version bump; no frame fields, schema semantics,
  stable backend ids, units, timestamps, provenance values, bearing sectors,
  public APIs, or core dependency boundaries were broken.
- Promotes the same v1 scope validated by the RC: stable L0 `geometry_only`,
  stable L1 `tdoa_synthetic`, supported optional L2 `room_acoustics`, Isaac
  Sim, Isaac Lab, Omniverse reference UX, stable JSON/JSONL export, and
  optional extension-only Replicator support.
- Documents that SquadBot, Alex, ROS 2, and downstream project adapters are not
  final v1 package release gates.
- Leaves phases 9, 10, and 11 as post-v1 planned work, not prerequisites for
  this release.

## 1.0.0rc1 - 2026-05-24

This is a release candidate for the v1 package line, not the final `1.0.0`
release.

- `AudioSensorFrame` v1 API is frozen except for bug fixes and additive
  compatible diagnostics or fields.
- The RC feedback window is open from 2026-05-24 through 2026-06-07 before
  final `1.0.0` consideration.
- This RC is not final `1.0.0`; final release still depends on RC feedback and
  review of real downstream usage.
- SquadBot is not included in the `v1.0.0rc1` release gate.
- Phases 9, 10, and 11 are planned after the RC and are not prerequisites for
  this tag.
- Strengthened `AudioSensorFrame` as the public v1 frame contract with
  `schema_version`, `frame_name`, `Pose3D` array/source poses, explicit units,
  provenance, time-window fields, and deterministic `max_events` semantics.
- Added JSON Schema export, tracked schema and trace examples, trace
  round-trip helpers, and JSONL frame writer support.
- Added checked-in schema parity tests, deterministic JSON and NDJSON trace
  corpus coverage, coordinate/unit/provenance/timestamp contract tests, and
  stable diagnostics namespace documentation for `AudioSensorFrame` v1.
- Added a public acoustic fidelity ladder with stable L0/L1 backends,
  supported optional L2 room acoustics, and future-compatible L3/L4 metadata
  boundaries.
- Hardened L2 `room_acoustics` as a supported optional v1 backend with
  pyroomacoustics RIR/waveform generation, waveform-derived GCC-PHAT TDOA,
  deterministic multi-source scheduling, and stable room/RIR/waveform
  diagnostics.
- Added lifecycle-capable `IsaacAudioArraySensor` updates for repeated stage
  snapshots, moving source/array metadata, active sound windows, latest-frame
  access, structured debug primitives, and package writer integration.
- Expanded the Omniverse extension wrapper with configure/start/stop/update
  and latest-frame export entry points.
- Added reference Omniverse extension UX coverage for selected-prim binding,
  array/source metadata authoring, live overlay state, config import/export,
  and optional Replicator writer recording.
- Fixed floating-point sector-boundary classification so L0/L1 bearing sectors
  stay consistent at exact 45-degree boundary cases.
- Renamed the bundled config and Isaac Sim example away from legacy project
  phase naming.
- Documented the public API freeze with stable, provisional, experimental, and
  internal/private surfaces after the Isaac-native Sim/Lab upgrades.
- Added public release-candidate docs for versioning, archive auditing,
  completed roadmap items, live Isaac validation expectations, and API-change
  deprecation policy.
- Added a distribution audit script and `make audit-dist`; `make build` now
  checks the built source distribution and wheel for required public files,
  forbidden generated/private paths, and public-package leak tokens.
- Added a canonical v1 public scope page plus guardrails for v1 promises,
  non-promises, downstream non-gates, and optional extension-only Replicator
  wording.
- Set the package version to `1.0.0rc1` while keeping the frame contract
  version separate at `ias.audio_sensor_frame.v1`.
- Closed the release-candidate scope around the stable frame contract, stable
  L0 `geometry_only`, stable L1 `tdoa_synthetic`, supported optional L2
  `room_acoustics`, Isaac Sim, Isaac Lab, Omniverse reference UX, stable
  JSON/JSONL export, and optional extension-only Replicator support.

## 0.1.0 - 2026-05-21

- Added the standalone `isaac-audio-sensors` package with pure core models,
  geometry-only simulation, synthetic TDOA simulation, optional room-acoustics
  simulation, CLI trace export, lazy Isaac Sim helpers, lazy Isaac Lab wrappers,
  generic examples, public documentation, and validation tests.
- Documented the initial 0.1.x public API freeze and semantic versioning policy.
- Excluded project-specific adapters, generated media, private recordings, and
  local environment artifacts from the public package boundary.
