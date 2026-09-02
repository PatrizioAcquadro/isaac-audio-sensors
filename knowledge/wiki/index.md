# Technical Wiki

[[status|Current Status]] is the canonical summary of verified capabilities, boundaries, limitations, and next work.

## Implementation Phases

### Ordered Post-R9.1 Implementation Plans

- [[implementation_phases/01-geometry-provider-qualification|01 Geometry Provider Qualification]] — measure serious candidates and select one maintained passive geometry-acoustics provider.
- [[implementation_phases/02-signal-and-perception-architecture|02 Signal and Perception Architecture]] — separate signal production from observed perception while retaining the minimal frame boundary.
- [[implementation_phases/03-audio-activity-detection|03 Audio Activity Detection]] — qualify Auditok and produce generic signal-derived activity without scene leakage.
- [[implementation_phases/04-observed-direction-estimation|04 Observed Direction Estimation]] — qualify mixture-only PyRoom SRP-PHAT and preserve honest ambiguity, latency, and confidence.
- [[implementation_phases/05-ground-truth-and-learning-datasets|05 Ground Truth and Learning Datasets]] — align observations, audio, and simulator truth without policy-input leakage.
- [[implementation_phases/06-simulated-and-real-signal-parity|06 Simulated and Real Signal Parity]] — make simulation and physical capture interchangeable signal producers for one perception pipeline.
- [[implementation_phases/07-isaac-lab-observation-integration|07 Isaac Lab Observation Integration]] — map observed dominant-event semantics into fixed, reset-safe policy tensors.
- [[implementation_phases/08-geometry-acoustics-integration|08 Geometry Acoustics Integration]] — integrate the selected provider as a high-fidelity signal producer behind the common boundary.
- [[implementation_phases/09-practical-realism-and-randomization|09 Practical Realism and Randomization]] — prioritize evidence-backed signal variation that improves application transfer.
- [[implementation_phases/10-end-to-end-validation-and-product-closeout|10 End-to-End Validation and Product Closeout]] — validate semantics, perception quality, runtime limits, datasets, and distributions.
- [[implementation_phases/11-future-semantic-perception|11 Future Semantic Perception]] — defer classification, tracking, speech focus, ODAS, and multi-source work until the base path is stable.

### Completed and Existing Phase Records

- [[implementation_phases/r2-fast-test-architecture|R2 Fast Test Architecture]] — semantic test ownership and maintained validation commands.
- [[implementation_phases/r3-product-boundary-cleanup|R3 Product Boundary Cleanup]] — generic SDK, downstream, evidence, and release-content boundaries.
- [[implementation_phases/r4-documentation-consolidation|R4 Documentation Consolidation]] — canonical wiki, root documentation removal, and documentation-boundary enforcement.
- [[implementation_phases/r5-semantic-component-refactor|R5 Semantic Component Refactor]] — v2 API ownership, dependency direction, and bounded semantic cleanup.
- [[implementation_phases/r6-packaging-and-release|R6 Packaging and Release]] — published Python source/wheel distributions, trusted publication, and self-contained Kit archive.
- [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]] — unified analytic environment meaning, configuration entry paths, and fail-closed Isaac resolution.
- [[implementation_phases/r8-analytic-acoustics-backend|R8 Analytic Acoustics Backend]] — completed topology routing, direct-stem occlusion, mass-parallel Isaac Lab execution, single-backend consolidation, and partition-transmission closeout.
- [[implementation_phases/r9-geometry-acoustics-provider-selection|R9 Geometry Acoustics Provider Selection]] — semantic fixture qualification and selection of one existing passive microphone-array engine.
- [[implementation_phases/r10-geometry-acoustics-integration|R10 Geometry Acoustics Integration]] — USD acoustic assemblies, provider-backed multichannel propagation, optional path review, and bounded analytic parameter transfer.

## Topics

- [[topics/getting-started|Getting Started]] — installation, CLI, examples, Isaac runtime launch, and contribution workflow.
- [[topics/system-architecture|System Architecture]] — package layers, data flow, lazy dependencies, and downstream ownership.
- [[topics/public-contracts-and-recording|Public Contracts and Recording]] — frames, schemas, configuration, plugins, trace IO, sessions, replay, and compatibility.
- [[topics/acoustic-modeling|Acoustic Modeling]] — arrays, backends, fidelity, room acoustics, motion, effects, occlusion, DOA, and interpretation limits.
- [[topics/isaac-sim-and-kit|Isaac Sim and Kit]] — stage discovery, live sensing, extension workflows, OmniGraph, Replicator, and troubleshooting.
- [[topics/isaac-lab-integration|Isaac Lab Integration]] — sensor configuration, observation tensors, entity/reference binding, reset/update, and GPU validation.
- [[topics/validation-and-release|Validation and Release]] — deterministic lanes, live gates, builds, audits, publication verification, and claim boundaries.

## Key Decisions

- [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] — current v2 promises, exclusions, and compatibility rules.

## Experiments

No canonical product experiments are currently recorded.

## Sources

No external raw sources have been ingested into canonical project knowledge.
