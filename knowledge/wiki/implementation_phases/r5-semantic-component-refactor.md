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

## Artifacts

- AST dependency contract and fresh-process import-boundary tests.
- Synchronized `2.0.0` package, Kit, acoustic-pack, documentation, and fixture metadata.

## Files

- `src/isaac_audio_sensors/__init__.py`
- `src/isaac_audio_sensors/kit/headless.py`
- `src/isaac_audio_sensors/schemas/generate.py`
- `tests/contract/test_public_surface.py`
