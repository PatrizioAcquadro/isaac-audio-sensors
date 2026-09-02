# Implementation Plan 05 — Ground Truth and Learning Datasets

Status: Planned after observed activity and DOA contracts are defined.

## Objective

Store observations and simulation truth as aligned but independent dataset information. Prevent privileged scene state from leaking into robot-policy inputs while preserving supervision for training, evaluation, and diagnosis.

Plan 05 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: one clear observation, truth, annotation, and recording model replaces overlapping dataset paths.

## Subphase 05.1 — Truth and Observation Boundary

#### Implementation

Produce one dataset-owned truth record aligned with each sensor frame without adding a public runtime `GroundTruthAssembler`. It may contain zero or more true source events with identity, authored class, pose, direction, distance, emission, received audibility evidence, meaningful occlusion or path state, and asset provenance.

Store `observations[]` and `truth_events[]` independently. Evaluation, not the sensor, matches them. Distinguish emission from received audibility so blocked or below-noise sources do not become impossible positive targets.

Former `scheduled_known_source` information becomes source truth; `manual_annotation` becomes annotation provenance. Neither remains a `detection_mode` or `AudioObservation.origin`.

#### Key Decisions

- Ground truth is beside the frame, never inside `AudioObservation`.
- Observation and truth cardinality are independent.
- Private stems and scene state may support supervision but never policy observations.
- Unmatched observations and truth events are valid evaluation outcomes.

#### Problems / Limitations

Simulation truth is exact only for its model. Audibility thresholds remain task-dependent and must preserve underlying received evidence.

## Subphase 05.2 — Robot-Learning Sample Boundary

#### Implementation

Define one learning sample from separable observed waveform or features, `AudioSensorFrame`, and optional truth or annotation records. Loaders expose privileged inputs explicitly rather than silently joining them into policy observations.

Preserve atomic alignment across audio, frame metadata, observations, reset markers, and truth. Splits prevent appropriate scene, trajectory, asset, and session leakage. Variable-length records use masks or collation in the learning adapter, not the serialized observation.

#### Key Decisions

- Policy inputs and supervision are separate outputs.
- Ground truth is optional at deployment.
- Frames reference rather than duplicate waveform arrays.
- Dataset integrity and semantic non-leakage are both required.

#### Problems / Limitations

Batching rules depend on the learning consumer and do not belong in the generic observation contract.

## Subphase 05.3 — Dataset Migration and Cleanup

#### Implementation

Migrate recording, replay, validation, schema, and learning consumers. Remove mixed observation/truth fields, duplicate serializers, unused wrappers, compatibility readers, and their unused supporting surfaces. Do not add a public `GroundTruthAssembler`, duplicate waveform storage, or test-only dataset fields.

#### Key Decisions

- Keep one canonical observation, truth, annotation, and recording model.
- Preserve required historical evidence without retaining obsolete active APIs.

#### Problems / Limitations

Check packaged schemas, replay, and in-scope consumers before removal.

## Artifacts

Expected artifacts are an aligned truth record, explicit policy-input and supervision boundaries, evaluation-owned matching, and one minimal maintained dataset surface.

## Files

Exact schemas, recorder changes, and loader surfaces are deferred to implementation. Current session ownership is described by [[topics/public-contracts-and-recording|Public Contracts and Recording]].
