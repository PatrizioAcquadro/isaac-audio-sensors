# Implementation Plan 01 — Geometry Provider Qualification

Status: complete (2026-09-03); later timing claims corrected in R10.

## Objective

Sequence reference for [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]], which owns provider selection. This page adds no independent requirements.

## Subphase 01.1 — Implement R9.2

#### Implementation

Completed corrected rev2 candidate qualification.

#### Key Decisions

Separate core integration from full acoustic coverage.

#### Problems / Limitations

Passing core integration did not establish complete R10 physics.

## Subphase 01.2 — Implement R9.3

#### Implementation

Selected Steam 4.8.1 for its qualified passive-audio role.

#### Key Decisions

RTX Acoustic remains historical evidence, not a maintained provider.

#### Problems / Limitations

Subsequent reflection/NLOS failures narrow the original claims.

## Subphase 01.3 — Retire Selected-Provider R10 Risks

#### Implementation

R9.4 ran after 02.1 and before 02.2, without replaying history.

#### Key Decisions

Retained native pathing/validation; excluded the failed paired transmission proxy.

#### Problems / Limitations

Original NLOS timing interpretation is withdrawn; production correction belongs to R10.

## Artifacts

[[experiments/acoustic-provider-evaluation|Provider results]] and [[experiments/geometry-acoustics-admission|later admission corrections]].

## Files

R9 and R10 are the canonical implementation records; this sequence owns no runtime files.
