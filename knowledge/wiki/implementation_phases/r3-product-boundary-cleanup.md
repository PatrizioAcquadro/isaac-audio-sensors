# Phase R3 — Product Boundary Cleanup

## Objective

Restrict the active repository and every distributed artifact to reusable robot-audition SDK capabilities while moving task policy, campaigns, downstream adapters, and scientific evidence to their owning projects or ignored evidence workspaces.

## Subphase R3.1 — Active Source Boundary

#### Implementation

Phase-coupled acquisition, acceptance, orchestration, configuration, schema, test, and output surfaces were removed after consumer and evidence gates were satisfied.

Generic frame, calibration, manifest, plugin, recording, replay, acoustic, Isaac Sim, Isaac Lab, Kit, CLI, schema, example, and release capabilities remain maintained.

The built-in stage rig profiles are generic `quad_cross_120mm` and `stereo_y_100mm`; robot-specific rig definitions remain downstream configuration.

The live Kit smoke creates a portable in-memory scene and has no external robot or showcase fixture dependency.

#### Key Decisions

Removed project-specific interfaces have no compatibility shims because they were not part of the reusable product contract.

Existing versioned sensor, dataset, calibration, and recording contracts remain supported independently of removed campaign workflows.

#### Problems / Limitations

Downstream projects must own their adapters, task policies, acceptance criteria, and replay fixtures.

Ignored publication evidence is protected local state and is not a package input or release payload.

## Subphase R3.2 — Distribution Boundary

#### Implementation

One recursive content policy audits wheels, source archives, Kit archives, optional packs, and nested wheels for forbidden paths, project identifiers, phase content, hard-coded test paths, and absolute workstation paths.

Schemas ship from `src/isaac_audio_sensors/schemas/`; no runtime or build step reads public contracts from documentation.

#### Key Decisions

Release archives may contain concise history only in a file named `CHANGELOG.md`.

Tests, tools, local datasets, outputs, evidence, acquisition code, and task-specific implementation do not ship.

#### Problems / Limitations

Archive cleanliness does not establish acoustic fidelity, physical validity, or downstream task correctness.

## Artifacts

The release content policy, archive auditors, generic rig profiles, portable Kit smoke, and ignored evidence manifest are the durable R3 artifacts.

## Files

- `tools/release/content_policy.py`
- `tools/release/`
- `src/isaac_audio_sensors/isaac/microphone_rig_profiles.py`
