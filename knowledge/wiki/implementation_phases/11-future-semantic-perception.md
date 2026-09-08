# Implementation Plan 11 — Future Semantic Perception

Status: Classification, tracking, speech-specific processing, beamforming, and separation remain deferred. Simultaneous localization is now planned in 04.4 before 07.2.

## Objective

Extend the observed pipeline with classification, tracking, speech-focused detection, and optional multi-source processing only when concrete application requirements justify their contracts and runtime cost.

Plan 11 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision. Deferred capabilities create no placeholder fields, dependencies, modules, configuration, registry entries, or test-only production hooks before a concrete application authorizes them.

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

The simultaneous-localization evaluation, including unknown source count, multi-peak processing, and ODAS as an optional candidate, is now owned by [[implementation_phases/04-observed-direction-estimation|Subphase 04.4]]. Its first target is zero/one/two-source detection and localization before 07.2, not tracking or separated audio.

Evaluate speech VAD, beamforming, and source separation separately when a concrete task requires them. Preserve the final-mixture input boundary and do not make specialized native runtimes mandatory for generic activity and dominant-direction sensing.

For every capability eventually authorized, select the smallest supported implementation and remove rejected experiments, unused models or plugins, placeholders, and their supporting surfaces. Do not retain semantic or multi-source code only for tests or possible future use.

#### Key Decisions

- Speech-focused detection does not replace generic acoustic activity.
- ODAS localization evaluation belongs to 04.4. Its tracking and separation roles remain optional future work, not mandatory Core dependencies.
- Multi-source output is added only with honest observability, association, and evaluation semantics.
- Active ultrasound remains a separate product capability.
- Each retained future component requires a concrete application and measured value.

#### Problems / Limitations

Semantic and multi-source models add data, native dependencies, compute, and maintenance. They require separate value evidence; temporary research candidates remain bounded to evaluation and leave production after selection.

## Artifacts

No artifacts or production placeholders are required until a future application activates one of these capabilities. An activated capability must leave one selected implementation and its evidence, not permanent candidate clutter.

## Files

Implementation files and model dependencies are intentionally undefined until the corresponding capability is authorized.
