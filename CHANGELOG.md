# Changelog

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
- New [Audio Assets](docs/audio_assets.md) doc: asset path rules,
  auto-resampling, the `data/` convention for external corpora
  (ESC-50/FSD50K style), and the test-time fixture-generation pattern.

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
- `docs/api_freeze_0_1.md` gains an explicit "V1 Frame Schema Evolution
  Policy" section defining what compatible v1 releases may add to a frame.

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
