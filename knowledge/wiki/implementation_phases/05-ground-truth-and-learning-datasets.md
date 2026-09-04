# Implementation Plan 05 — Ground Truth and Learning Datasets

Status: Subphase 05.1 in progress; dataset contracts and single-render production implemented. Subphases 05.2 and 05.3 remain planned.

## Objective

Store observations and simulation truth as aligned but independent dataset information. Prevent privileged scene state from leaking into robot-policy inputs while preserving supervision for training, evaluation, and diagnosis.

Plan 05 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: one clear observation, truth, annotation, and recording model replaces overlapping dataset paths.

## Subphase 05.1 — Truth and Observation Boundary

#### Implementation

`recording.FrameTruth`, `TruthEvent`, and `AnnotationRecord` define supervision beside the observed frame. Truth identifies the frame, array, exact window, and sample rate. `None` means unavailable truth; an empty `truth_events` sequence means a known empty scene. Annotations carry a caller-authored label and provenance with optional explicit source and observation references.

`recording.simulate_dataset_frame()` returns `(frame, block, truth)` from one private analytic render, sharing perception and waveform-sink composition with `simulate_frame()`. It emits one truth event per snapshot source, including inactive sources. Snapshot world pose, array-relative bearing/elevation and distance, authored class, prim, and asset reference stay outside observations. A coincident source has no direction; a vertical source has no azimuth.

Schedule overlap and full-window source emission RMS are distinct from received RMS. Received evidence uses per-source private stems after propagation, directivity, occlusion, gains, and linear microphone response, cropped to the public window. Mixture residual RMS compares the final float32 block with the summed linear stems; it includes mixture noise, electronics, and float32 conversion, not a pure-noise or SNR estimate. Existing occlusion maps are copied only when supplied by the snapshot. No audibility threshold, matching, or positive-target decision is made here.

Persistence and removal of the old manifest truth are the remaining 05.1 milestone. No public `GroundTruthAssembler`, stem output, or waveform duplication is introduced.

#### Key Decisions

- Ground truth is beside the frame, never inside `AudioObservation`.
- Observation and truth cardinality are independent.
- Private stems and scene state may support supervision but never policy observations.
- Unmatched observations and truth events are valid evaluation outcomes.

#### Problems / Limitations

Simulation truth describes only the implemented producer model. Geometry describes the supplied snapshot while RMS integrates the rendered window, including supported motion. The producer renders window-local emission; cross-window arrivals and reverberation are not added by truth extraction. Audibility thresholds and observation-to-truth matching remain evaluator-owned. Automatic production currently supports only `AnalyticAcoustics`.

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
