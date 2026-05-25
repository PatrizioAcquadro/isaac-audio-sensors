# Versioning

`isaac-audio-sensors` follows semantic versioning for the Python package and a
separate schema-version policy for frame traces.

## Current Version

- distribution: `isaac-audio-sensors`
- import package: `isaac_audio_sensors`
- package version: `1.0.0rc1`
- frame schema version: `ias.audio_sensor_frame.v1`
- pure Python support: Python 3.10 or newer

`1.0.0rc1` is a release candidate, not final `1.0.0`. It is the first v1
package candidate that makes the frozen frame contract, stable L0/L1,
supported optional L2, Isaac Sim path, Isaac Lab path, Omniverse reference UX,
JSON/JSONL export, and optional extension-only Replicator support coherent as a
third-party Python package.

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

The generated schema in `docs/schemas/audio_sensor_frame.v1.schema.json` is the
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
make live-isaac-sim-audio ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

Do not publish to PyPI or create a git tag until the release checklist,
changelog, archive audit, install smoke, and live-runtime evidence or blockers
are reviewed.
