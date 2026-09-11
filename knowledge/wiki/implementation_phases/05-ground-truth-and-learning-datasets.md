# Implementation Plan 05 — Ground Truth and Learning Datasets

Status: 05.1–05.3 complete.

## Objective

Keep aligned observations, optional truth and annotations separate, allowing supervision and evaluation without privileged policy inputs.

## Subphase 05.1 — Truth and Observation Boundary

#### Implementation

Added `FrameTruth`, `TruthEvent`, annotations and `simulate_dataset_frame()` from one shared render. Recording validates supervision before advancing output state. Truth describes emitted sources and received stems separately.

#### Key Decisions

Unavailable truth is `None`; an empty truth sequence is a known empty scene. Emission schedule/RMS, received contribution and mixture residual are distinct.

#### Problems / Limitations

Residual is not a noise/SNR estimate. Truth does not establish audibility, matching or a positive target.

## Subphase 05.2 — Robot-Learning Sample Boundary

#### Implementation

Added frame-indexed `LearningDataset` samples with observed inputs, separately named truth/annotations, recording metadata and explicit supervision availability. Supervision is opt-in; collation pads without truncation. Acquisition session identity survives exports; corpus splits keep sessions and selected scene/trajectory/asset groups together transitively, failing on missing identities or impossible splits.

#### Key Decisions

Policies receive observed fields; task-owned labels/rewards remain separate. Preserve variable event count, ambiguity and absent values.

#### Problems / Limitations

Labels require independent task definitions; dataset availability does not qualify a learner or generalization.

## Subphase 05.3 — Dataset Migration and Cleanup

#### Implementation

Migrated canonical manifests/records/loaders/replay and deterministic fixtures; removed episode-level duplicate source truth. Current manifest is v4, frame record v2; current embedded sensor frame v4 came later.

#### Key Decisions

One recorder/layout authority; maintain crash recovery, gap/reset semantics, sample alignment and leakage-group isolation.

#### Problems / Limitations

Historical schema versions are not parallel runtime formats. See the current contract for exact supported fields.

## Artifacts

Recording/replay, supervision alignment, split/leakage and loader tests passed. [[topics/public-contracts-and-recording|Public Contracts and Recording]] owns schemas, learning samples and validation semantics.

## Files

`src/isaac_audio_sensors/recording/`, `src/isaac_audio_sensors/schemas/`, `tests/fixtures/`.
