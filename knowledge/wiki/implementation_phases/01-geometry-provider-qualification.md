# Implementation Plan 01 — Geometry Provider Qualification

Status: Planned after the completed R9.1 contract work.

## Objective

Complete the evidence-based qualification and selection of one existing geometry-aware passive-acoustics provider before maintaining a product integration. This plan executes the remaining provider work already bounded by [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]]; it does not redesign perception or add a runtime backend.

## Place in the Sequence

R9.1, R9.1.1, and R9.1.2 are complete. Provider qualification is therefore the first remaining activity. The chosen provider must later implement the signal boundary defined by [[implementation_phases/02-signal-and-perception-architecture|Plan 02]] rather than inheriting the current source-conditioned detection behavior.

## Subphase 01.1 — Measured Candidate Qualification

#### Implementation

Evaluate each serious provider against the existing fail-closed qualification contract in the intended Isaac runtime. Evidence must establish passive arbitrary-content propagation, separate phase-coherent microphone channels, relevant static and dynamic geometry, material and assembly behavior, connected-space propagation, approximate around-edge or around-corner behavior, operational packaging, licensing, and bounded performance.

Use temporary adapters only to expose native provider capabilities to shared semantic scenarios. Qualification must measure the provider itself rather than recreate missing propagation algorithms inside Isaac Audio Sensors.

#### Key Decisions

- Behavioral capability is established by runtime evidence, not product claims or qualitative listening.
- Raw microphone-array channels are mandatory; listener or device mixes are insufficient.
- The provider may lack optional path visualization while still qualifying, but every missing diagnostic remains explicit.
- Candidate adapters remain temporary until one provider is selected.

#### Problems / Limitations

Simulation evidence does not establish real-world calibration. A provider that approximates useful propagation may still require bounded domain randomization and real-audio comparison later in the sequence.

## Subphase 01.2 — Provider Comparison and Decision

#### Implementation

Compare only candidates that satisfy the blocking contract. Select one primary provider whose native feature set, maintenance burden, distribution path, and runtime behavior best support the practical-realism objective. If no candidate qualifies, record an explicit no-provider result instead of weakening the sensor contract.

The decision must preserve a single maintained geometry-provider path. Unselected experimental adapters do not become permanent public backends.

#### Key Decisions

- Selection follows complete evidence; it is not predetermined by ecosystem preference.
- Native provider functionality is preferred to repository-owned reimplementation.
- One maintainable provider is preferable to several partial backends.
- The selected provider supplies microphone signals; it does not own activity detection, DOA semantics, observations, or learning labels.

#### Problems / Limitations

A qualified provider may still be unsuitable for mass-parallel Isaac Lab execution. High-fidelity geometry propagation and scalable policy training remain separate operating regimes.

## Artifacts

Expected artifacts are candidate qualification reports, a comparison summary, and one documented provider decision or explicit no-provider outcome.

## Files

Implementation files are intentionally deferred to the qualification agent. The existing R9 contract remains the detailed authority for evidence fields and acceptance semantics.
