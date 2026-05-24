# Versioning

`isaac-audio-sensors` follows semantic versioning for the Python package and a
separate schema-version policy for frame traces.

## Current Version

- distribution: `isaac-audio-sensors`
- import package: `isaac_audio_sensors`
- package version: `0.1.0`
- frame schema version: `ias.audio_sensor_frame.v1`
- pure Python support: Python 3.10 or newer

The current release-candidate work keeps the package version at `0.1.0`.
Changing to a pre-release marker would add churn without fixing an inconsistency:
the repository is still preparing the initial 0.1.0 release surface, and the
compatibility contract is documented through the Unreleased changelog entries
and the 0.1 API freeze.

The package's v1 promise boundary is frozen in [V1 Public Scope](v1_scope.md).
Versioning changes must not expand v1 into downstream release gates, sim-real
calibration, real hardware benchmarks, complete L3/L4 fidelity, realistic
material/occlusion acoustics, or mandatory ROS 2/project adapters without an
explicit future scope change.

## Package Compatibility

Patch releases in `0.1.x` keep the stable API in
`docs/api_freeze_0_1.md` compatible. Compatible changes include:

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
for 0.1.x.

Patch releases must not remove, rename, or change the semantics of documented
v1 fields, provenance values, unit meanings, coordinate policy, timestamp
semantics, ambiguity representation, or stable diagnostics namespaces. They may
add optional fields or diagnostics that readers can ignore. If a future change
needs an incompatible trace shape, create a new schema version instead of
silently changing `ias.audio_sensor_frame.v1`.

The generated schema in
`docs/schemas/audio_sensor_frame.v1.schema.json` is the checked-in public
artifact. `make export-schema` regenerates it from code and tests compare the
generated schema with the checked-in file.

## Release Checklist

Before cutting a release or tag, run:

```bash
make test
make lint
make build
make import-smoke
make validate-config
make export-schema
make audit-dist
git diff --check
```

Also attempt live runtime validation on an installed Isaac Sim/Lab environment:

```bash
make live-isaac-sim-audio ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

Do not publish to PyPI or create a git tag until the release checklist,
changelog, archive audit, and live-runtime evidence are reviewed.
