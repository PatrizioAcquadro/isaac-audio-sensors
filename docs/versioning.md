# Versioning

`isaac-audio-sensors` follows semantic versioning for the Python package and a
separate schema-version policy for frame traces.

## Current Version

- distribution: `isaac-audio-sensors`
- import package: `isaac_audio_sensors`
- package version: `1.10.0`
- Kit extension manifest version: `1.10.0`
- frame schema version: `ias.audio_sensor_frame.v1`
- pure Python support: Python 3.10 or newer

`1.7.0` is a compatible v1 minor release: 3D DOA with additive optional
elevation fields gated on rank-3 microphone layouts (new `tetrahedral`
preset), the SRP-PHAT estimation path as the additive `room_acoustics_srp`
L2 backend id, and Doppler from the new optional `velocity_world_mps` spec
fields (metadata at L1, resampled source waveforms at L2). The frame schema
version is unchanged; new DOA/detection/unit fields are additive optional
and absent-tolerant, so pre-1.7.0 traces still load. Under the compatibility contract,
`1.7.0` traces load with identical semantics; current serialization adds only
the four documented canonical defaults for absent optional fields:
`occluded=false`, `ground_truth_elevation_deg=null`,
`doa.estimated_elevation_deg=null`, and
`doa.candidate_elevation_deg=[]`. No other key appears, disappears, or changes.

`1.6.0` is a v1 minor release with a documented `room_acoustics` behavior
break: rooms are fixed in world space (`origin_m` + `dimensions_m`) instead
of being automatically refit around the frame's sources and microphones.
Existing L2 configs whose positions fall outside the room must set
`room.origin_m`, move prims inside the room, or opt into
`out_of_bounds="clamp"`. The frame schema version is unchanged; new room
diagnostics are additive.

`1.5.0` is a compatible v1 minor release: the Omniverse extension GUI gains
visual instruments (bearing compass, per-mic RMS meters, detection timeline),
a waveform/spectrogram preview with audition of exported WAVs,
viewport-first interaction (selection follow and manipulator-driven pose
sync), persistent USD debug geometry, and a runtime OmniGraph node exposing
the latest frame. The backing `kit` module became a package with
the same import path, and the extension config schema stays
`ias.omni_extension_binding.v1` with additive lifecycle keys only; the frame
schema version is unchanged.

`1.4.0` is a compatible v1 minor release: occlusion upgrades to a
material-aware, frequency-dependent ray/transmission model (multi-hit,
per-microphone, octave-band material presets and explicit USD transmission
attributes) consumed per microphone at L0/L1 and as premix-stage band
filtering at L2, the documented `rediscover_each_update` binding flag is now
consumed (default `False`, matching the shipped cached behavior), and
discovery-relevant info-only USD property changes invalidate the live cache.
All `SourceOcclusion` extensions and diagnostics are additive; the frame
schema version is unchanged.

`1.3.0` is a compatible v1 minor release: the Isaac layer adds opt-in PhysX
raycast occlusion (the first shipped L3 capability) consumed by all backends
as per-source attenuation plus an optional `occluded` detection field that is
serialized by current writers but not schema-required, and steady-state live
sensor ticks reuse cached stage discovery instead of re-traversing the USD
stage. The frame schema version is unchanged.

`1.2.0` was a compatible v1 minor release: the `room_acoustics` backend now
simulates all scheduled sources in one shared room per frame (true microphone
mixtures with sample-accurate start offsets), exports per-frame or
session-continuous multichannel WAVs through the new `core.io.waveforms`
module (populating the previously empty `waveform_paths` frame field), and
resamples mismatched file assets instead of raising. All L2 diagnostic value
changes are documented physics improvements plus additive optional APIs; the
frame schema version is unchanged.

`1.1.0` is a compatible v1 minor release: it makes the L0/L1/L2 synthetic
physics coherent (1/distance pressure attenuation, source gain at every
level, power-sum aggregate RMS, observable-only confidence), adds seeded
Gaussian stress noise, first-order source directivity, microphone self-noise
floors, and an optional L1 air-absorption toggle. All changes are documented
physics bug fixes plus additive optional APIs and diagnostics; the frame
schema version is unchanged.

`1.0.0` is the first final v1 package release. It makes the frozen frame
contract, stable L0/L1, supported optional L2, Isaac Sim path, Isaac Lab path,
Omniverse reference UX, JSON/JSONL export, and optional extension-only
Replicator support coherent as a third-party Python package.

The `AudioSensorFrame` v1 API is frozen for compatible v1 releases except for
bug fixes and additive compatible diagnostics or fields. The `1.0.0rc1`
feedback window was reviewed, and final `1.0.0` was promoted early on
2026-05-24 with explicit maintainer approval. SquadBot, Alex, ROS 2, and
downstream adapters are not final v1 package release gates, and phases 9, 10,
and 11 remain planned post-v1 work rather than prerequisites for this tag.

The Kit extension manifest uses SemVer spelling. The Kit extension manifest
and Python package version both use `1.10.0`.

The package's v1 promise boundary is frozen in [V1 Public Scope](v1_scope.md).
Versioning changes must not expand v1 into downstream release gates, sim-real
calibration, real hardware benchmarks, complete L3/L4 fidelity, realistic
material/occlusion acoustics, or mandatory ROS 2/project adapters without an
explicit future scope change.

## Package Compatibility

Compatible v1 releases keep the stable API in `docs/api_freeze_0_1.md`
compatible. Compatible changes include:

- bug fixes;
- documentation fixes;
- stricter rejection of invalid inputs;
- additive optional fields;
- additive diagnostics;
- new provisional helpers that do not require existing users to change code.

The acoustic fidelity ladder follows the same policy. L0 `geometry_only` and
L1 `tdoa_synthetic` are stable v1 runtime levels, L2 `room_acoustics` is
supported optional v1, and L3/L4 may evolve additively as provisional or
experimental/tooling metadata until complete runtime implementations exist.

Minor releases may add or promote public APIs. Major releases may introduce
incompatible public API changes.

Experimental modules can change with documentation and changelog notes.
Internal names starting with `_` are not part of the public compatibility
contract.

## Frame Schema Compatibility

The frame schema version is not the package version. `AudioSensorFrame` v1 uses
`schema_version = "ias.audio_sensor_frame.v1"` and is the stable trace contract
for compatible v1 package releases.

Compatible releases must not remove, rename, or change the semantics of
documented v1 fields, provenance values, unit meanings, coordinate policy,
timestamp semantics, ambiguity representation, or stable diagnostics
namespaces. They may add optional fields or diagnostics that readers can
ignore. If a future change needs an incompatible trace shape, create a new
schema version instead of silently changing `ias.audio_sensor_frame.v1`.

For `AudioSensorFrame` v1, the following are breaking changes:

- renaming or removing public frame, detection, DOA, pose, units, diagnostics
  namespace, or trace fields;
- changing `schema_version` away from `ias.audio_sensor_frame.v1`;
- changing unit meanings, timestamp meanings, provenance values, coordinate
  convention, ambiguity representation, diagnostics namespace meanings, stable
  backend ids, or bearing-sector semantics.

The corrected sector behavior is frozen as the v1 contract: normalized
clockwise bearings use 45-degree half-open bins, and the wraparound `straight`
sector includes `337.5 <= bearing < 360.0` plus `0.0 <= bearing < 22.5`. That
correction is a documented bug fix, not a schema redesign.

The generated schema in `src/isaac_audio_sensors/schemas/audio_sensor_frame.v1.schema.json` is the
checked-in public artifact. `make export-schema` regenerates it from code and
tests compare the generated schema with the checked-in file.

## Release Checklist

Before cutting a release or tag, run:

```bash
make test
make lint
make export-schema
git diff --check
make build
make audit-dist
make import-smoke
```

Also attempt live runtime validation on an installed Isaac Sim/Lab environment
when refreshing live evidence:

```bash
make live-isaac-sim-audio
make smoke-isaac-lab
```

These live gates auto-detect the official `~/isaacsim` and `~/IsaacLab`
installs when present; use `ISAAC_SIM_COMMAND` or `ISAAC_LAB_PYTHON` only for
non-default runtimes.

Do not publish to PyPI or create a git tag until the release checklist,
changelog, archive audit, install smoke, and live-runtime evidence or blockers
are reviewed.
