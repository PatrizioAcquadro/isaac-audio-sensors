# Technical Wiki

Start with [[status|Current Status]]. Read other pages only for the task at hand.
For Phase 08 implementation: [[implementation_phases/08-geometry-acoustics-integration|sequence]]
→ [[implementation_phases/r10-geometry-acoustics-integration|work/exit gates]] →
[[decisions/robot-audition-fidelity|approved domain, budgets and diagnostic criteria]]. Native details
and past experiments are linked from those pages, not required background for every task.

## Implementation Phases

- [[implementation_phases/01-geometry-provider-qualification|01 Provider Qualification]] — completed R9 sequencing.
- [[implementation_phases/02-signal-and-perception-architecture|02 Signal/Perception]] — completed observed-only separation.
- [[implementation_phases/03-audio-activity-detection|03 Activity]] — fixed-threshold Auditok and explicit limits.
- [[implementation_phases/04-observed-direction-estimation|04 Direction]] — nominal roles and bounded multisource; temporal gaps remain.
- [[implementation_phases/05-ground-truth-and-learning-datasets|05 Datasets]] — independent truth, learning inputs and splits.
- [[implementation_phases/06-simulated-and-real-signal-parity|06 Signal Parity]] — common semantics, physical integration and comparison.
- [[implementation_phases/07-isaac-lab-observation-integration|07 Lab/GUI]] — observed tensors, CUDA reference preservation and consumer closeout.
- [[implementation_phases/08-geometry-acoustics-integration|08 Geometry Sequence]] — eight remaining execution steps.
- [[implementation_phases/09-practical-realism-and-randomization|09 Realism]] — planned consumer-justified variation.
- [[implementation_phases/10-end-to-end-validation-and-product-closeout|10 Product Closeout]] — planned complete supported-system validation.
- [[implementation_phases/11-future-semantic-perception|11 Specialized Perception]] — deferred classification/tracking/separation.
- [[implementation_phases/r2-fast-test-architecture|R2 Test Lanes]] — semantic validation ownership.
- [[implementation_phases/r3-product-boundary-cleanup|R3 Product Boundary]] — campaign/source/distribution separation.
- [[implementation_phases/r4-documentation-consolidation|R4 Knowledge Organization]] — canonical ownership and efficient reading.
- [[implementation_phases/r5-semantic-component-refactor|R5 Runtime Ownership]] — historical subsystem refactor.
- [[implementation_phases/r6-packaging-and-release|R6 Release]] — clean-source delivery and historical publication.
- [[implementation_phases/r7-acoustic-environment-contract|R7 Environments]] — explicit topology and fail-closed resolution.
- [[implementation_phases/r8-analytic-acoustics-backend|R8 Analytic]] — routing, continuous timing and bounded direct occlusion.
- [[implementation_phases/r9-geometry-acoustics-provider-selection|R9 Selection]] — retained provider roles and corrected admission claims.
- [[implementation_phases/r10-geometry-acoustics-integration|R10 Implementation]] — current Geometry work and completion gates.

## Topics

Reusable current contracts and workflows; phase pages retain only introductions/outcomes.

- [[topics/getting-started|Getting Started]] — install, CLI, examples and contributions.
- [[topics/system-architecture|System Architecture]] — dependency and responsibility boundaries.
- [[topics/public-contracts-and-recording|Public Contracts and Recording]] — PCM, frames, truth, schemas, datasets and splits.
- [[topics/acoustic-modeling|Acoustic Modeling]] — arrays, analytic propagation, effects and perception semantics.
- [[topics/geometry-acoustics|Geometry Acoustics]] — prepared USD/materials, native ownership, build and configuration.
- [[topics/isaac-sim-and-kit|Isaac Sim and Kit]] — live sensor, authoring, instrumentation and lifecycle.
- [[topics/isaac-lab-integration|Isaac Lab Integration]] — current tensor/binding/clock contract.
- [[topics/validation-and-release|Validation and Release]] — maintained commands, runtime gates and artifact audits.
- [[topics/onr-video-production|ONR Video Production]] — delivered 1–3, remaining 4–9 and individual scene/media gates.

## Key Decisions

- [[decisions/robot-audition-fidelity|Robot-Audition Fidelity]] — approved scope, binding budgets/invariants, diagnostic cube exception, consumer semantics and provider stop rule.
- [[decisions/continuous-acoustic-clock|Continuous Acoustic Clock]] — arrival model, libraries and motion/lifecycle approximations.
- [[decisions/minimal-maintained-repository-surface|Minimal Maintained Surface]] — consumer-proven implementation/cleanup principle.
- [[decisions/product-boundary-and-compatibility|Product Boundary and Compatibility]] — supported interfaces and exclusions.

## Experiments

Read for a specific result/reference; these pages do not add requirements.

- [[experiments/geometry-acoustics-admission|Geometry Admission]] — result tables, corrected failures, diagnostic cube/AV evidence and replay index; admission limits remain explicit.
- [[experiments/geometry-acoustics-trial-protocol|Geometry Trial Protocol]] — exact fixtures/matrix, references/scoring and lean allocation, followed by completed preparation and its limits.
- [[experiments/acoustic-provider-evaluation|Provider Evaluation]] — executed versus inspected alternatives and selection limits.
- [[experiments/04-4-multisource-localization|Multisource Localization]] — accepted stable-source reference and rejected temporal candidates.
- [[experiments/lab-perception-runtime|Lab Runtime]] — scalar/CUDA preservation, precision rejection and practical batch costs.
- [[experiments/physical-signal-comparison|Physical Comparison]] — 25-take parity, level/activity gaps and rejected gains.

## Sources and history

No raw external sources have been ingested into canonical source pages.
[[log|Knowledge Log]] records compact milestones; detailed prior prose is recoverable
from Git at `5cfe48d`. Raw/evidence artifacts remain unchanged.
