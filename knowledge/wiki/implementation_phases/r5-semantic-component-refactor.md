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

## Artifacts

- AST dependency contract and fresh-process import-boundary tests.
- Synchronized `2.0.0` package, Kit, acoustic-pack, documentation, and fixture metadata.
- Draft 2020-12 schema validity, generated/package parity, deterministic export, and preserved-payload contract tests.

## Files

- `src/isaac_audio_sensors/__init__.py`
- `src/isaac_audio_sensors/core/__init__.py`
- `src/isaac_audio_sensors/core/config.py`
- `src/isaac_audio_sensors/core/types.py`
- `src/isaac_audio_sensors/kit/headless.py`
- `src/isaac_audio_sensors/schemas/generate.py`
- `tests/contract/test_schemas.py`
- `tests/contract/test_public_surface.py`
