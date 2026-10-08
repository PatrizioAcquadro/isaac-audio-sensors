# SquadBot Phase 7 — SDK Audio Runtime Readiness

Status: planned. Phase 7 identifies the downstream SquadBot roadmap; the SDK's
existing Phase 07 — Isaac Lab Observation Integration retains its own scope.

## Objective

Establish a usable audio configuration for closed-loop attention and learning
before downstream robot integration. Build on the existing SDK through focused
readiness assessment and optimization. SquadBot motivates this work; improvements
must remain reusable across consumers, robots and microphone arrays.

## 7.1 — SDK compatibility and operating envelope

Establish the supported SDK and Isaac Sim/Isaac Lab configuration and identify
any contract changes that consumers need to adopt. Document migration guidance;
updating SquadBot's dependency and adapters belongs to the downstream project.

Assess observation quality with moving sources and receivers, ambiguity,
reverberation and competing sounds. Use representative microphone geometry,
acoustic backends and perception settings within their documented bounds.
Existing integration and stable-source results do not establish useful dynamic
tracking. Begin with a bounded scenario and introduce harder acoustics only
where they materially affect the intended consumer.

## 7.2 — Latency and learning throughput

Measure audio generation, buffering, perception and observation delivery in the
supported runtime, accounting for representative rendering and simulation load.
Distinguish simulated time, observation age, wall-clock response and
multi-environment learning throughput. Preserve signal timing and direction
information while optimizing demonstrated SDK bottlenecks.

An interactive configuration need not use the most expensive acoustic path or
the settings used for every training episode. Choose useful operating profiles
from measured quality and cost. Do not presume that this work requires a
large-scale GPU rewrite; revisit training scale when the workload is concrete.

Reusable changes belong in the SDK. Robot-specific configuration, application
queues and scheduling, task behavior, partner-classifier latency and policy
training remain downstream responsibilities.

## Outcome and handoff

Provide a measured audio configuration, any necessary reusable SDK improvements,
and documented compatibility, quality and performance limits. The consumer then
adopts the selected revision/configuration and verifies its own observation path
before robot simulation integration.

Downstream scope and adoption work:
[SquadBot Phase 7](https://github.com/PatrizioAcquadro/squadbot-av/blob/main/knowledge/wiki/implementation_phases/phase-7-audio-runtime-readiness.md).

[[decisions/product-boundary-and-compatibility|SDK ownership and compatibility]] ·
[[index|Wiki index]]
