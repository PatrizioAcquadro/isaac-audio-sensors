# Product Boundary and Compatibility

## Decision

`isaac-audio-sensors` is a reusable robot-audition SDK, not a robot task, acquisition campaign, downstream policy, or scientific evidence repository.

The maintained product owns simulator-independent audio contracts and backends, calibration contracts, generic recording/replay, Isaac Sim integration, Isaac Lab observations, the Kit extension, small examples/fixtures, and release tooling.

Robot-specific mounts, assets, adapters, policies, task orchestration, acceptance criteria, datasets, holdouts, and experiment evidence remain with their owning downstream project.

## Current Compatibility Line

The current package is `1.10.0` on the v1 compatibility line, while the repository restructuring prepares a clean future `2.x` API boundary.

R4 changes documentation ownership only; R5 will decide and freeze the exact v2 import and CLI inventory after obsolete source boundaries have been removed.

Existing `ias.audio_sensor_frame.v1`, `ias.audio_dataset_manifest.v1`, and `ias.audio_calibration_profile.v1` data contracts may remain valid in a future major package version when their serialized meanings remain useful.

## Stable Promises

The v1 line promises the documented sensor frame, dataset-manifest, and calibration-profile contracts; deterministic L0/L1 behavior; optional supported L2 behavior; generic plugin contracts; package JSON/JSONL; generic recording/replay; supported lazy Isaac Sim and Isaac Lab paths; and the Kit extension as the reference UX.

Compatible releases preserve required fields, meanings, units, provenance values, coordinate convention, ambiguity representation, stable backend identifiers, sector behavior, and named diagnostic namespaces.

Bug fixes, stricter invalid-input rejection, additive optional fields/diagnostics, and new optional capabilities are compatible when existing readers and configurations retain their documented meaning.

## Non-Promises

The package does not promise a downstream robot or project as a release gate, real hardware benchmarks, automatic calibration, complete L3/L4 realism, production perception, mandatory ROS 2 integration, or sim-to-real transfer.

Simulation validation cannot be promoted to a physical claim without measurements, calibration evidence, controlled data, and an explicit validation protocol.

Optional Replicator, room-acoustics, Isaac, Kit, GPU, and pack capabilities do not become core import dependencies.

## Breaking Changes

Removing or renaming stable public fields, changing their semantics, changing units/provenance/coordinates/ambiguity/sector meaning, or silently changing a v1 serialized shape is breaking and requires a new schema or major compatibility decision.

Experimental or private names may change with clear release notes, but downstream project-specific surfaces are not preserved through permanent shims.

## Consequences

The core stays portable and testable, optional runtimes remain lazy, downstream ownership is explicit, and release archives can be audited against one generic product boundary.

Consumers must maintain their own adapters and validation, and physical or task-level readiness must be reported separately from package correctness.
