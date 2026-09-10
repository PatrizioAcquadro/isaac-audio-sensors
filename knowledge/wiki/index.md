# Technical Wiki

[[status|Current Status]] is the canonical summary of verified capabilities, boundaries, limitations, and next work.

## Implementation Phases

### Ordered Post-R9.1 Implementation Plans

- [[implementation_phases/01-geometry-provider-qualification|01 Geometry Provider Qualification]] — completed sequence reference for R9.2 qualification, R9.3 selection, and post-02.1 R9.4 risk retirement.
- [[implementation_phases/02-signal-and-perception-architecture|02 Signal and Perception Architecture]] — completed signal/perception separation, consumer migration and frame-v4 confidence availability.
- [[implementation_phases/03-audio-activity-detection|03 Audio Activity Detection]] — completed Auditok contract, qualification, explicit-threshold scalar integration, and duplicate-surface cleanup.
- [[implementation_phases/04-observed-direction-estimation|04 Observed Direction Estimation]] — completed 04.1–04.3 and bounded indoor reference; temporal research suspended with failures and limits preserved.
- [[implementation_phases/05-ground-truth-and-learning-datasets|05 Ground Truth and Learning Datasets]] — completed 05.1–05.3: separate truth, NumPy learning samples and corpus splits, manifest v4, and dataset consumer cleanup.
- [[implementation_phases/06-simulated-and-real-signal-parity|06 Simulated and Real Signal Parity]] — completed shared semantics, physical acquisition, 25-take nominal comparison, maintained-role parity, and obsolete campaign cleanup; raw remains enabled.
- [[implementation_phases/07-isaac-lab-observation-integration|07 Isaac Lab Observation Integration]] — completed 07.1; 07.2 causal clocks and active CUDA perception delivered within bounds, with realtime performance closure open; 07.3 GUI/consumer consolidation remains planned.
- [[implementation_phases/08-geometry-acoustics-integration|08 Geometry Acoustics Integration]] — R10.1–R10.3 sequence, including geometry-backed occlusion and provider diagnostics for the fuller Video 4 scope.
- [[implementation_phases/09-practical-realism-and-randomization|09 Practical Realism and Randomization]] — useful effects, evidence-backed variation and coherent GUI controls after geometry integration; received levels, noise and weak-signal activity remain priorities.
- [[implementation_phases/10-end-to-end-validation-and-product-closeout|10 End-to-End Validation and Product Closeout]] — validate behavior and finish with a consumer-proven minimal, maintainable repository surface.
- [[implementation_phases/11-future-semantic-perception|11 Future Semantic Perception]] — classification, tracking, speech and separation remain deferred; simultaneous localization moves to 04.4.

### Completed and Existing Phase Records

- [[implementation_phases/r2-fast-test-architecture|R2 Fast Test Architecture]] — semantic test ownership and maintained validation commands.
- [[implementation_phases/r3-product-boundary-cleanup|R3 Product Boundary Cleanup]] — generic SDK, downstream, evidence, and release-content boundaries.
- [[implementation_phases/r4-documentation-consolidation|R4 Documentation Consolidation]] — canonical wiki, root documentation removal, and documentation-boundary enforcement.
- [[implementation_phases/r5-semantic-component-refactor|R5 Semantic Component Refactor]] — v2 API ownership, dependency direction, and bounded semantic cleanup.
- [[implementation_phases/r6-packaging-and-release|R6 Packaging and Release]] — published Python source/wheel distributions, trusted publication, and self-contained Kit archive.
- [[implementation_phases/r7-acoustic-environment-contract|R7 Acoustic Environment Contract]] — unified analytic environment meaning, configuration entry paths, and fail-closed Isaac resolution.
- [[implementation_phases/r8-analytic-acoustics-backend|R8 Analytic Acoustics Backend]] — analytic propagation and completed bounded solid-collider/unavailable-occlusion corrections.
- [[implementation_phases/r9-geometry-acoustics-provider-selection|R9 Geometry Acoustics Provider Selection]] — Steam selection plus qualified pathing, timing, diagnostics, operating cost, and a rejected paired transmission proxy.
- [[implementation_phases/r10-geometry-acoustics-integration|R10 Geometry Acoustics Integration]] — planned provider-backed signals and analytic transfer constrained to R9-qualified capabilities, followed by one maintained Steam adapter.

## Topics

- [[topics/onr-video-production|ONR Video Production]] — maintained videos 1–3 and Video 4 occlusion readiness: bounded direct attenuation after immediate fixes, fuller geometry scope after 08.3.

- [[topics/getting-started|Getting Started]] — installation, CLI, examples, Isaac runtime launch, and contribution workflow.
- [[topics/system-architecture|System Architecture]] — package layers, data flow, lazy dependencies, and downstream ownership.
- [[topics/public-contracts-and-recording|Public Contracts and Recording]] — frames, schemas, configuration, plugins, trace IO, sessions, replay, and compatibility.
- [[topics/acoustic-modeling|Acoustic Modeling]] — arrays, backends, fidelity, room acoustics, motion, effects, occlusion, DOA, and interpretation limits.
- [[topics/isaac-sim-and-kit|Isaac Sim and Kit]] — stage discovery, live sensing, extension workflows, OmniGraph, Replicator, and troubleshooting.
- [[topics/isaac-lab-integration|Isaac Lab Integration]] — sensor configuration, observation tensors, entity/reference binding, reset/update, and GPU validation.
- [[topics/validation-and-release|Validation and Release]] — deterministic lanes, live gates, builds, audits, publication verification, and claim boundaries.

## Key Decisions

- [[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]] — continuous arrival rendering, maintained-library choice, lifecycle, and motion approximations.

- [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] — final cleanup and maintainability rule shared by all implementation plans.
- [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] — current v2 promises, exclusions, and compatibility rules.

## Experiments

- [[experiments/04-4-multisource-localization|04.4 Multisource Localization]] — bounded indoor reference and rejected temporal candidates; research suspended, 07.2 admitted without general temporal qualification.

## Sources

No external raw sources have been ingested into canonical project knowledge.
