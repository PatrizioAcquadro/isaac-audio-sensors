# Implementation Plan 11 — Future Semantic Perception

Status: deferred; bounded simultaneous localization is already maintained by 04.4/07.

## Objective

Add specialized perception only for a separately authorized application. No placeholder fields, dependencies or hooks. R10 reference AV confirmation does not authorize a learned recognizer or semantic graph.

## Subphase 11.1 — Sound Classification

#### Implementation

Qualify labels, model/taxonomy, score semantics and leakage-controlled data before an explicit observation-schema extension.

#### Key Decisions

Authored class is supervision, not prediction; no robot-specific Core ontology.

#### Problems / Limitations

Asset/recording/scene leakage can make synthetic classification artificially easy.

## Subphase 11.2 — Temporal Tracking

#### Implementation

Introduce estimator-owned identity only after observed quality/latency are characterized; define reset and discontinuity behavior.

#### Key Decisions

Track IDs never inherit truth source IDs; association is evaluation output.

#### Problems / Limitations

Crossings, silence, reverberation and robot motion require separate switch/continuity evidence.

## Subphase 11.3 — Specialized and Multi-Source Plugins

#### Implementation

Speech VAD, beamforming and separation need distinct task evidence. Simultaneous localization/count inference belongs to [[implementation_phases/04-observed-direction-estimation|04.4]].

#### Key Decisions

Use final mixtures and isolate specialized optional dependencies.

#### Problems / Limitations

More event slots or repeated DOA do not establish separation/tracking. No policy training or semantic planner is implied.

## Artifacts

No deferred runtime surface exists solely to prepare these capabilities.

## Files

Select files only after a concrete capability is authorized.
