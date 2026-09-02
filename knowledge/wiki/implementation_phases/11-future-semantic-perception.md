# Implementation Plan 11 — Future Semantic Perception

Status: Explicitly deferred until generic activity and observed DOA are stable across simulation and hardware.

## Objective

Extend the observed pipeline with classification, tracking, speech-focused detection, and optional multi-source processing only when concrete application requirements justify their contracts and runtime cost.

## Subphase 11.1 — Sound Classification

#### Implementation

Qualify a classifier only after the generic activity dataset provides non-leaking inputs and labels. Add class output, score semantics, taxonomy, and model provenance to observations through an explicit schema change rather than reserving unused fields in advance.

#### Key Decisions

- Authored source class is supervision, not predicted class.
- Classifier vocabulary belongs to a declared model or downstream application contract.
- Generic Core does not hard-code a robot-specific ontology.

#### Problems / Limitations

Simulated source assets can make classification unrealistically easy. Asset, recording, and scene split leakage require specific control.

## Subphase 11.2 — Temporal Tracking

#### Implementation

Introduce track identity and motion continuity only after observations are stable and latency is characterized. Tracking consumes observed activity and direction over time; it does not inherit simulation source identifiers.

#### Key Decisions

- `track_id` is estimator-owned and distinct from truth `source_id`.
- Track-to-truth association remains evaluation output.
- Resets and discontinuities terminate or explicitly reinitialize tracks.

#### Problems / Limitations

Crossing sources, silence, reverberation, and robot motion can create track switches. Tracking quality must remain separate from instantaneous DOA quality.

## Subphase 11.3 — Specialized and Multi-Source Plugins

#### Implementation

Evaluate speech VAD, ODAS, multi-peak localization, beamforming, and source separation as optional plugins when a real use case requires them. Preserve the same final-mixture input boundary and do not make specialized native runtimes mandatory for generic activity and dominant-direction sensing.

#### Key Decisions

- Speech-focused detection does not replace generic acoustic activity.
- ODAS is a candidate for optional localization, tracking, and separation rather than a mandatory Core dependency.
- Multi-source output is added only with honest observability, association, and evaluation semantics.
- Active ultrasound remains a separate product capability.

#### Problems / Limitations

Semantic and multi-source models add training data, native dependencies, compute, and maintenance. They require separate value evidence rather than inheriting approval from the base perception work.

## Artifacts

No artifacts are required until a future application activates one of these capabilities.

## Files

Implementation files and model dependencies are intentionally undefined until the corresponding capability is authorized.
