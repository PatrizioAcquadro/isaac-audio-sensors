# Technical Wiki

[Current status](status.md) summarizes what is available, the conditions in which it was validated, and the open issues. [Getting started](topics/getting-started.md) covers installation and the first runnable example.

| I want to… | Start here |
| --- | --- |
| Simulate an array from Python or the CLI | [First CLI workflow](topics/getting-started.md#first-cli-workflow) · [Acoustic modeling](topics/acoustic-modeling.md) |
| Record, replay, or prepare a dataset | [Public contracts and recording](topics/public-contracts-and-recording.md) |
| Attach a sensor in Isaac Sim or author a scene in Kit | [Sim and Kit](topics/isaac-sim-and-kit.md) · [Native Geometry setup](topics/geometry-acoustics.md) |
| Use audio observations in Isaac Lab | [Lab integration](topics/isaac-lab-integration.md) |
| Develop or validate a change | [System architecture](topics/system-architecture.md) · [Validation and release](topics/validation-and-release.md) |

## Topics

- [[status|Current Status]] — supported workflows, measured performance, open issues, and distribution.
- [[topics/getting-started|Getting Started]] — runtime choice, installation, CLI, and examples.
- [[topics/system-architecture|System Architecture]] — component responsibilities, data flow, and dependencies.
- [[topics/acoustic-modeling|Acoustic Modeling]] — arrays, analytic propagation, effects, and perception.
- [[topics/geometry-acoustics|Geometry Acoustics]] — USD preparation, materials, native providers, and configuration.
- [[topics/public-contracts-and-recording|Public Contracts and Recording]] — signals, frames, truth, datasets, and splits.
- [[topics/isaac-sim-and-kit|Isaac Sim and Kit]] — live sensors, authoring, instruments, and lifecycle.
- [[topics/isaac-lab-integration|Isaac Lab Integration]] — bindings, tensors, masks, and clocks.
- [[topics/validation-and-release|Validation and Release]] — host checks, GPU checks, builds, and artifact audits.
- [[topics/onr-video-production|ONR Video Production]] — delivered demonstrations, evidence, and remaining reviews.

## Experiments

- [[experiments/acoustic-provider-evaluation|Provider Evaluation]] — selection evidence and alternatives inspected.
- [[experiments/geometry-acoustics-trial-protocol|Geometry Trial Protocol]] — fixtures, controlled references, and preparation limits.
- [[experiments/geometry-acoustics-admission|Geometry Admission]] — native and RTX results, motion controls, and unresolved room equivalence.
- [[experiments/04-4-multisource-localization|Multisource Localization]] — stable-source reference and failed temporal candidates.
- [[experiments/lab-perception-runtime|Lab Perception Runtime]] — scalar/CUDA parity, numerical corrections, and batch cost.
- [[experiments/consumer-audio-operating-envelope|Operating Envelope]] — baseline natural-speech quality under motion and competition.
- [[experiments/consumer-audio-dynamic-quality|Dynamic Audio Quality]] — context selection, independent confirmations, and lag.
- [[experiments/consumer-audio-indoor-quality|Indoor Audio Quality]] — spatial coherence, single-voice gains, and weak-voice failures.
- [[experiments/consumer-audio-runtime-performance|Runtime Performance]] — combined quality and delivery under load, clocks, and scaling.
- [[experiments/physical-signal-comparison|Physical Signal Comparison]] — real/simulated signal parity and level mismatch.

## Key Decisions

- [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] — supported interfaces and v3 migration.
- [[decisions/robot-audition-fidelity|Robot-Audition Fidelity]] — supported domain, acceptance budgets, and provider limits.
- [[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]] — arrival timing, motion, and lifecycle assumptions.
- [[decisions/minimal-maintained-repository-surface|Maintained Repository Surface]] — criteria for retaining code and tools.

## Implementation Phases

- [[implementation_phases/01-geometry-provider-qualification|01 · Provider qualification]] — provider evaluation sequence.
- [[implementation_phases/02-signal-and-perception-architecture|02 · Signal and perception]] — separation of acquisition and observation.
- [[implementation_phases/03-audio-activity-detection|03 · Activity detection]] — fixed-threshold Auditok integration.
- [[implementation_phases/04-observed-direction-estimation|04 · Direction estimation]] — estimator roles and bounded multisource results.
- [[implementation_phases/05-ground-truth-and-learning-datasets|05 · Learning datasets]] — independent truth and learning splits.
- [[implementation_phases/06-simulated-and-real-signal-parity|06 · Signal parity]] — common processing for captured and simulated signals.
- [[implementation_phases/07-isaac-lab-observation-integration|07 · Lab observations]] — tensors, CUDA reference checks, and Kit presentation.
- [[implementation_phases/08-geometry-acoustics-integration|08 · Geometry acoustics]] — bounded native integration and runtime qualification.
- [[implementation_phases/09-practical-realism-and-randomization|09 · Practical realism]] — planned consumer-driven variation.
- [[implementation_phases/10-end-to-end-validation-and-product-closeout|10 · Product closeout]] — planned product-wide validation.
- [[implementation_phases/11-future-semantic-perception|11 · Semantic perception]] — deferred classification, tracking, and separation.
- [[implementation_phases/r2-fast-test-architecture|R2 · Test lanes]] — responsibility of each validation environment.
- [[implementation_phases/r3-product-boundary-cleanup|R3 · Product boundary]] — separation of SDK and campaigns.
- [[implementation_phases/r4-documentation-consolidation|R4 · Documentation]] — wiki ownership and structure.
- [[implementation_phases/r5-semantic-component-refactor|R5 · Runtime ownership]] — subsystem refactor.
- [[implementation_phases/r6-packaging-and-release|R6 · Packaging and release]] — clean-source distributions and publication.
- [[implementation_phases/r7-acoustic-environment-contract|R7 · Environments]] — topology and environment resolution.
- [[implementation_phases/r8-analytic-acoustics-backend|R8 · Analytic propagation]] — solvers, timing, and direct occlusion.
- [[implementation_phases/r9-geometry-acoustics-provider-selection|R9 · Provider selection]] — retained provider roles.
- [[implementation_phases/r10-geometry-acoustics-integration|R10 · Geometry implementation]] — native components and integration criteria.
- [[implementation_phases/squadbot-audio-runtime-readiness|Consumer audio readiness]] — SDK changes and handoff for bounded listening trials.

## Sources and history

The wiki currently has no source pages derived from raw research material. The [knowledge log](log.md) records milestones.
