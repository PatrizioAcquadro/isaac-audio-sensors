# Implementation Plan 05 — Ground Truth and Learning Datasets

Status: Planned after observed activity and DOA contracts are defined.

## Objective

Store sensor observations and simulation truth as aligned but independent dataset information. Prevent privileged scene state from leaking into robot-policy inputs while preserving the supervision needed for training, evaluation, and diagnosis.

Plan 05 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: one clear observation, truth, annotation, and recording ownership model replaces overlapping dataset paths.

## Subphase 05.1 — Dataset-Only Truth Boundary

#### Implementation

Do not add a public runtime `GroundTruthAssembler` service. Produce truth through the smallest dataset-owned extraction and serialization path that keeps one time-aligned truth record for each recorded sensor frame. The exact implementation may be a private function or compact typed record; it does not become another runtime subsystem without a demonstrated consumer.

The truth record contains zero or more true source events with source identity, true class when authored, pose, bearing, elevation, distance, emission state, received audibility evidence, occlusion or provider path state when meaningful, and source-asset provenance.

Former `scheduled_known_source` information becomes scheduled emission and source truth in this dataset-owned record; it never creates a runtime observation by itself. Former `manual_annotation` information becomes a separate annotation record with annotator, method, timing, and label provenance as appropriate. Neither former mode remains serialized as `detection_mode`, and neither is accepted as an `AudioObservation.origin` value.

#### Key Decisions

- Ground truth is recorded beside a frame, never inside `AudioObservation`.
- A separate record is still necessary because frames with zero observations or zero truth events are valid.
- Truth extraction may use private stems and scene state because it is supervision, not sensor output.
- Scheduled source state belongs to simulation truth rather than observed detection.
- Manual annotations belong to dataset annotation provenance rather than detection origin.

#### Problems / Limitations

Simulation truth is exact only relative to the simulator model. It does not become measured physical truth and must retain provider and scenario provenance.

## Subphase 05.2 — Independent Observation and Truth Cardinality

#### Implementation

Store `observations[]` and `truth_events[]` independently. Do not force one observation per true source or place a true source identifier inside an observed event. Evaluation owns any matching between estimated directions and true events.

Distinguish a source that is emitting from one whose received contribution is meaningfully audible at the array. This prevents impossible positive targets when an active source is below noise or effectively blocked.

#### Key Decisions

- Observation-to-truth association is an evaluation result, not sensor data.
- Emission truth and received audibility truth are distinct.
- A dominant observed direction may coexist with several true sources.
- Unmatched observations and unmatched truth events are expected evaluation outcomes.

#### Problems / Limitations

Audibility thresholds depend on the intended task and calibration. Dataset generation must preserve the underlying received evidence rather than hide it behind one universal label.

## Subphase 05.3 — Robot-Learning Sample Boundary

#### Implementation

Define a learning sample around one sensor time step with three separable groups: observed waveform or features, `AudioSensorFrame`, and optional truth/annotation records. Dataset loaders must make privileged inputs explicit rather than silently joining them into policy observations.

Preserve atomic alignment between audio samples, frame metadata, observations, reset markers, and truth records. Splits must prevent scene, trajectory, source-asset, or session leakage appropriate to the evaluation claim.

#### Key Decisions

- Policy inputs and supervision are separate loader outputs.
- Ground truth is optional for deployment and mandatory only for supervised dataset uses that need it.
- Raw audio and derived observations can coexist without duplicating waveform arrays inside frame JSON.
- Dataset integrity and semantic non-leakage are both required.

#### Problems / Limitations

Variable-length observations and truth events require masks or collation rules for batched training. Those rules belong to the learning adapter rather than the serialized acoustic observation itself.

## Subphase 05.4 — Dataset Surface Consolidation and Cleanup

#### Implementation

After migrating recording, replay, validation, and learning consumers, remove mixed observation/truth fields, duplicate serializers, unused dataset wrappers, compatibility readers, and their unused supporting surfaces. Do not add a public `GroundTruthAssembler`, duplicate waveform storage, or test-only dataset fields.

#### Key Decisions

- Keep one canonical observation, truth, annotation, and recording model.
- Preserve required historical evidence without retaining obsolete active APIs.

#### Problems / Limitations

Check packaged schemas, replay, and in-scope consumers before removal.

## Artifacts

Expected artifacts are an aligned dataset truth record, explicit policy-input and supervision boundaries, evaluation-owned observation matching, and one minimal maintained dataset surface.

## Files

Exact schemas, recorder changes, and loader surfaces are deferred to implementation. Current session ownership is described by [[topics/public-contracts-and-recording|Public Contracts and Recording]].
