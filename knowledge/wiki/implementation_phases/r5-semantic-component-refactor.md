# Phase R5 — Semantic Component Refactor

Status: complete historical v2 refactor; later phases own current contract changes.

## Objective

Give each runtime responsibility one owner, with lazy optional imports and a small public surface. Historical source-to-frame/six-tensor contracts below were superseded by Phases 02/07.

## Subphase R5.0 — Architectural Foundation

#### Implementation

Established subsystem-owned APIs and separated Core, recording, Isaac, Lab, Kit and CLI responsibilities.

#### Key Decisions

No speculative managers or compatibility facades.

#### Problems / Limitations

Current module/API inventories come from source and [[topics/system-architecture|System Architecture]], not old frozen lists.

## Subphase R5.1 — Core Contracts, Config, and Schema

#### Implementation

Reduced Core exports, made orientation quaternion-authoritative and schemas generator-owned; kept simulator concerns outside Core.

#### Key Decisions

Strict units/conventions and explicit optional dependencies.

#### Problems / Limitations

Later frame/dataset versions replace the historical v1 formats.

## Subphase R5.2 — Backends, DSP, and Effects

#### Implementation

Consolidated backend resolution/capabilities and split effects/room responsibilities; preserved numerical behavior while removing unused paths.

#### Key Decisions

One authoritative declaration per capability; no test-only production surfaces.

#### Problems / Limitations

Later R8/02 own analytic routing and signal-only propagation.

## Subphase R5.3 — Recording and Dataset

#### Implementation

Made `SessionDataset` the layout authority and `SessionRecorder` the orchestrator; consolidated bounded scans, durable writes, gaps, recovery and structured layout errors.

#### Key Decisions

False-complete prevention, replay identity and split isolation remain essential.

#### Problems / Limitations

Current recorder signatures/schema versions belong to [[topics/public-contracts-and-recording|Public Contracts]].

## Subphase R5.4 — Isaac Sim Bridge

#### Implementation

Kept one live sensor lifecycle and moved persistence/UI to owners; removed offline fallback and duplicate registries/subscriptions.

#### Key Decisions

Isaac imports remain lazy and stage/runtime behavior explicit.

#### Problems / Limitations

Host mocks do not qualify actual stage/PhysX behavior.

## Subphase R5.5 — Isaac Lab Observations

#### Implementation

Established lazy real SensorBase inheritance, separate entity/reference roles, device ownership and selected resets.

#### Key Decisions

No fallback classes, silent transfers or duplicated USD discovery.

#### Problems / Limitations

Original source-conditioned six tensors and empty/feature-only performance are historical; Phase 07 owns observed PCM/CUDA behavior.

## Subphase R5.6 — Kit UI

#### Implementation

Thin controller composes lifecycle, authoring, sensing, recording and configuration services; views render state and invoke actions.

#### Key Decisions

Best-effort shutdown releases each resource independently.

#### Problems / Limitations

Live Kit validation remains necessary after wiring changes.

## Subphase R5.7 — CLI

#### Implementation

Made CLI a lazy public-service adapter; retained one trace-export path and recording-owned dataset validation/splitting.

#### Key Decisions

Help/version avoid expensive runtime imports; no duplicate simulation implementation.

#### Problems / Limitations

Current commands live in [[topics/getting-started|Getting Started]].

## Subphase R5.8 — Examples and v2 API Freeze

#### Implementation

Consolidated maintained examples and documented public entrypoints; validated host, runtime, downstream and distribution behavior.

#### Key Decisions

Examples use maintained public APIs; removed private compatibility paths stay removed.

#### Problems / Limitations

A historical API freeze does not override intentional later contract migrations.

## Artifacts

Historical closeout passed focused numerical/contract, actual RTX Sim/Lab/Kit, downstream and archive gates. Detailed old inventories/test totals are recoverable from this path at `5cfe48d`.

## Files

`src/isaac_audio_sensors/`, `examples/`, `tests/`; current ownership is in the linked topics.
