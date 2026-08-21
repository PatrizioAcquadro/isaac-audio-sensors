# Phase R5 — Semantic Component Refactor

## Objective

Align package ownership, dependency direction, and the public Python API before deeper subsystem refactors.

## Subphase R5.0 — Architectural Foundation

#### Implementation

R5.0 makes the package root metadata-only and places public contracts under their owning subsystem. `core` owns simulator-independent sensor behavior; `recording` owns dataset manifests and serialization; `schemas.generate` owns schema generation; `isaac` owns shared USD helpers; `lab` may reuse those Isaac helpers; and `kit` owns guided application workflows.

The allowed dependency direction is enforced statically, including imports inside functions. Optional Isaac, Lab, Torch, Omniverse, and Kit services remain absent from pure-package imports.

The cleanup removes duplicate package examples, compatibility aliases, production structures used only by tests, private Kit re-exports, and semantic GUI/headless comparison scaffolding. One headless end-to-end workflow and focused CLI outcomes remain.

#### Key Decisions

- Package version `2.0.0` starts immediately because root v1 imports are removed without shims.
- Serialized frame, manifest, and calibration contracts remain on their compatible `v1` schemas.
- `lab -> isaac` is allowed for shared import-safe USD stage utilities.
- Kit translates validation findings into `ExtensionActionError`; Isaac validation returns dependency-free reports.

#### Problems / Limitations

The former dependency cycles from `core` to `recording` and from `isaac` to `kit` are fixed. R5.0 does not redesign internal backend, recording, Isaac, Lab, or Kit implementations; those remain candidates for later R5 subphases.

## Subphase R5.1 — Core Contracts, Config, and Schema

#### Implementation

R5.1 reduces `core.__all__` to the eleven fundamental scene and sensor models. Importing `isaac_audio_sensors.core` loads only those pure contracts; config, calibration, backend, plugin, capability, fidelity, and pack APIs remain available from their owning modules.

`AudioSensorConfig` no longer stores Lab configuration or fixed-value `stage_units` and `up_axis` fields. Generic TOML loading still rejects non-meter and non-Z-up scenes, while Isaac Lab configuration remains owned by `AudioArraySensorCfg`.

`MicrophoneArraySpec.orientation_world_quat` is the sole array orientation authority. Internal consumers derive the normalized forward/right/up basis once where needed. The cleanup also consolidates backends on `PropagationBackend` and removes duplicate plugin-output, custom-array, basis-check, and occlusion-amplitude APIs.

The three Python schema generators are authoritative. `write_json_schema` provides one deterministic export path used by the CLI, and packaged JSON files must remain byte-identical generated artifacts. The compatible frame schema now permits legacy v1 traces that predate the additive `units.elevation` key. JSON Schema validation is development-only.

#### Key Decisions

- Serialized frame, manifest, calibration, trace, unit, coordinate, provenance, and plugin declaration semantics remain compatible v1 contracts.
- Trace and calibration serialization stay in `core.io` because they are active simulator-independent contracts.
- `types.py` remains one coherent vocabulary; R5.1 does not refactor backend/DSP, recording, Isaac, Lab, Kit, or CLI internals beyond required contract migrations.
- Focused config, types, microphone-array, math, and schema tests replace duplicate catch-all and historical-surface checks.

#### Problems / Limitations

The duplicated array basis could diverge from its quaternion, and core configuration previously contained unused Lab state; both issues are fixed. R5.1 does not change acoustic fidelity, recording layout, simulator behavior, or serialized schema versions.

## Subphase R5.2 — Backends, DSP, and Effects

#### Implementation

R5.2 makes `get_backend()` the sole public resolver. It delegates to `PluginRegistry.resolve()`, distinguishes unknown identifiers from missing optional dependencies, and checks declared device and runtime-profile support before construction. `registered_backend_ids()` derives the maintained inventory from `PluginDeclaration` values used by core configuration, Isaac validation, Lab, Kit, and capability reporting.

Effects configuration now separates immutable dataclasses, dict/TOML normalization, and semantic validation. Mapping shape, unknown keys, structural types, finite values, channel order, and used seeds fail closed; range and backend compatibility checks apply only when the corresponding stage is active.

Room acoustics is a compatible package split into backend orchestration, signal scheduling and preparation, pyroomacoustics rendering, and diagnostic construction. Public backend class imports and `RoomAcousticsBackend.is_available()` remain stable, while direct construction reports a precise missing-dependency error.

Unused compatibility and test-only surfaces were removed from the registry, effects configuration, TDOA estimation, material validation, and room backend. Focused numerical tests retain routing, dependency and capability failures, scheduling, mixtures, SRP, RIR, motion, effects placement, and diagnostics.

#### Key Decisions

- The public computation remains `AudioSceneSnapshot + MicrophoneArraySpec + AudioTimeWindow -> AudioSensorFrame` for every propagation backend.
- Backend identifiers, serialized v1 schemas, units, coordinate conventions, provenance, diagnostics, formulas, DSP order, source order, seeds, and phase-cursor meaning remain unchanged.
- Direct imports of maintained backend classes and actively used Isaac material aliases remain supported.
- Invalid values in an inactive effects stage may be accepted when they cannot affect computation; structural errors are always rejected.
- Recording and other R5 subsystems are outside R5.2.

#### Problems / Limitations

Backend inventory and optional dependency metadata no longer have parallel lists in configuration or simulator consumers. Large effects and room-acoustics modules no longer combine unrelated responsibilities. The acoustic fidelity limits described in the modeling documentation are unchanged.

## Subphase R5.3 — Recording and Dataset

#### Implementation

R5.3 makes `SessionDataset` the single session-layout authority used by loading, validation, replay, FLAC export, and recording recovery. Internal modules now separate canonical frame records, deterministic shard planning, shard completion and streaming scans, durable writes, audio writing, recovery state, time gaps, and manifest construction.

`SessionRecorder` remains the public orchestrator. `append_frame(frame, audio_block, *, is_reset=False)` accepts only `AudioSensorFrame`, reads `frame.timestamp_ms`, and records time-gap diagnostics internally. `cancel()` publishes a finalized-incomplete session; resume and finalization recovery remain class methods. Atomic helpers, writer state, filesystem seams, promotion callbacks, planner details, and module-level recovery wrappers are private or removed.

Manifest parsing is strict canonical v1 parsing rather than coercion. Manifest and split-plan writes use durable atomic replacement. Shard checksum verification has one implementation, and `DatasetLayoutError` reports stable `code`, `location`, and `detail` fields consumed directly by validation.

Focused black-box tests retain aligned and unaligned output, crash/resume/recovery safety, incomplete-session opt-in, bounded streaming, replay identity and read-only behavior, time-gap/reset diagnostics, corruption codes, exact statistics, split leakage, and real FLAC behavior. Duplicate seam, callback, retry, snapshot, retained-mode, and helper-level matrices were removed.

#### Key Decisions

- `ias.audio_dataset_manifest.v1`, `ias.dataset_frame_record.v1`, `ias.shard_completion.v1`, marker meaning, session layout, units, and provenance remain compatible.
- The Python recording API reduction is intentionally breaking and has no compatibility shims.
- `verify_checksums` remains available through `SessionDataset` and replay without a second verifier.
- Atomic promotion, false-complete prevention, drop accounting, time-gap preservation, streaming bounded memory, statistics, split isolation, WAV, and optional FLAC remain maintained behavior.

#### Problems / Limitations

Normal callers no longer need checkpoint, carry-buffer, marker, filesystem, or promotion internals. FLAC still requires SoundFile from the optional `room` dependencies; absence fails explicitly.

## Subphase R5.4 — Isaac Sim Bridge

#### Implementation

R5.4 makes `isaac_audio_sensors.isaac` the live USD/Isaac bridge. The sensor lives in `isaac.sensor`, binds a selected array prim path, builds every capture from a live stage, and retains manual capture, update subscriptions, monotonic timing, motion, discovery/cache, stage snapshots, occlusion, debug output, latest-frame publication, and Replicator integration.

Kit now owns microphone/sound profiles, validation, JSONL paths, and waveform output configuration. The controller appends only new frames and constructs the optional core `WaveformSink`; the sensor consumes and closes that sink without knowing application paths or UI modes.

Lazy timeline/update subscriptions share `isaac.lifecycle`. Anchored-room refresh moved to stage-snapshot helpers, and live occlusion pair state, refresh reasons, material evidence, and diagnostics moved to `isaac.occlusion`. Lifecycle coverage is consolidated around manual capture, throttling, forced updates, non-monotonic time, update subscriptions, timeline resets, stop, and close.

#### Key Decisions

- `from isaac_audio_sensors.isaac import IsaacAudioArraySensor` remains stable; the removed `isaac.extension` path has no shim before the v2 API freeze.
- Offline `from_config()`, snapshot fallback construction, legacy source/array/listener registries, and the JSONL writer wrapper are removed.
- Importing `isaac_audio_sensors.isaac` must not load Omniverse, USD, Isaac Lab, Torch, Kit, or recording modules.
- Kit UI and instruments remain in place for a later Kit-focused phase.

#### Problems / Limitations

The ambiguous sensor module name, duplicate discovery registries, duplicated Kit update subscription, and sensor-owned application persistence are fixed. R5.4 does not change serialized frames, backend acoustics, Isaac Lab behavior, Kit UI structure, or the optional-runtime requirements of live simulation and waveform export.

## Subphase R5.5 — Isaac Lab Observations

#### Implementation

R5.5 makes `isaac_audio_sensors.lab` a lazy, import-safe package whose public surface contains only `AudioArraySensor`, `AudioArraySensorCfg`, `AudioArraySensorData`, `EntityBindingCfg`, and `SourceEntityCfg`. Resolving those classes after `AppLauncher` yields direct subclasses of the current Isaac Lab `SensorBaseCfg` and `SensorBase`; fallback classes, reload helpers, legacy namespaces, aliases, and generic provider APIs are removed.

The sensor has two binding modes. `bind_entities(scene, cfg)` is the vectorized training path and reads `scene[name]` root/body state tensors, mount geometry, source schedules, directivity, quaternion order, and optional environment origins. It accepts only `float32` tensors already on the sensor device and supports `geometry_only` or `tdoa_synthetic` with effects disabled. `bind_reference(snapshots, array_specs)` runs the maintained scalar core backends over pure dataclasses for semantic comparison and debugging.

The observation is exactly six fixed-shape tensors: presence and ambiguity masks, bearing, confidence, eight-sector one-hot encoding, and per-microphone RMS. Padding is deterministic, device ownership comes only from `SimulationContext`, and partial reset clears only selected rows. Entity updates use tensor selection, compaction, and scatter operations without environment loops or host round trips; the scalar conversion is isolated in the reference backend.

USD discovery, stage pose resolution, and room anchoring remain in `isaac`. The former Lab stage adapter and its fake-stage, fallback, metadata, alias, and helper-level tests are removed; compatible v1 traces may still contain legacy diagnostic namespaces.

#### Key Decisions

- The breaking cleanup has no compatibility shims.
- Entity mode is the batched RL path; reference mode is the pure-snapshot semantic authority.
- `debug_vis=True` fails until a real visualization exists.
- Scalar and batched paths preserve source scheduling, event order, truncation, bearings, confidence, sector, RMS, ambiguity, and padding semantics for maintained entity backends.
- Core backends, recording, Kit, CLI, and serialized v1 contracts are unchanged.

#### Problems / Limitations

Duplicate stage/entity ownership, silent device transfers, fallback inheritance, test-only metadata, and multiple binding routes are removed. The live-only RTX 4090 gate cannot be replaced by CPU execution; it passed entity/reference parity, partial reset, CUDA shape/dtype/device checks, and 50 steps over 4096 environments at 1.879 ms/step mean against the 20 ms budget.

## Artifacts

- AST dependency contract and fresh-process import-boundary tests.
- Synchronized `2.0.0` package, Kit, acoustic-pack, documentation, and fixture metadata.
- Draft 2020-12 schema validity, generated/package parity, deterministic export, and preserved-payload contract tests.

## Files

- `src/isaac_audio_sensors/__init__.py`
- `src/isaac_audio_sensors/core/__init__.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/core/types.py`
- `src/isaac_audio_sensors/core/backends/room_acoustics/`
- `src/isaac_audio_sensors/core/effects/`
- `src/isaac_audio_sensors/core/plugins/registry.py`
- `src/isaac_audio_sensors/recording/`
- `src/isaac_audio_sensors/isaac/sensor.py`
- `src/isaac_audio_sensors/isaac/lifecycle.py`
- `src/isaac_audio_sensors/isaac/occlusion.py`
- `src/isaac_audio_sensors/lab/`
- `src/isaac_audio_sensors/kit/validation/`
- `src/isaac_audio_sensors/kit/headless.py`
- `src/isaac_audio_sensors/schemas/generate.py`
- `tests/contract/test_schemas.py`
- `tests/contract/test_public_surface.py`
