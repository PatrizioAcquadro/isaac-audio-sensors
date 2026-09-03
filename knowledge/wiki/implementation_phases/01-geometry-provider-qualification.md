# Implementation Plan 01 — Geometry Provider Qualification

Status: 01.1 corrected and 01.2–01.3 completed on 2026-09-03. Subphase 01.3
ran after Plan 02.1 and before Plan 02.2.

## Objective

Record the execution order of the R9 provider work. This page is a sequence
reference only;
[[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] is the
sole authority for requirements, decisions, limitations, evidence, acceptance
semantics, and application of the
[[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]]
decision.

## Subphase 01.1 — Implement R9.2

#### Implementation

[[implementation_phases/r9-geometry-acoustics-provider-selection#Subphase R9.2 — Candidate Qualification|R9.2 Candidate Qualification]] is complete with corrected rev2 reports and separate core-integration and full-R10 outcomes. This reference does not duplicate those results or select a provider.

#### Key Decisions

- This plan defines only that R9.2 precedes R9.3; R9.2 remains authoritative for its execution.

#### Problems / Limitations

This reference adds no requirements beyond R9.2.

## Subphase 01.2 — Implement R9.3

#### Implementation

[[implementation_phases/r9-geometry-acoustics-provider-selection#Subphase R9.3 — Candidate Decision|R9.3 Candidate Decision]]
is complete. Steam Audio `4.8.1` is selected for future passive geometry
integration; NVIDIA RTX Acoustic remains historical qualification evidence and
has no maintained candidate tooling.

#### Key Decisions

- This plan defines only that R9.3 follows R9.2; R9.3 remains authoritative for
  the provider decision and its limitations.

#### Problems / Limitations

This reference adds no requirements beyond R9.3.

## Subphase 01.3 — Retire Selected-Provider R10 Risks

#### Implementation

After the already completed Plan 02.1,
[[implementation_phases/r9-geometry-acoustics-provider-selection#Subphase R9.4 — Selected-Provider R10 Risk Retirement|R9.4 Selected-Provider R10 Risk Retirement]]
completed before Plan 02.2 without rollback or history rewrite. The result
preserves Steam Audio `4.8.1`, admits baked pathing, private arrival scheduling,
and bounded diagnostics to R10, and excludes the failed closed/paired
transmission proxy.

#### Key Decisions

- This reference records the intentional R9.4-after-02.1 execution order; R9
  remains authoritative for the qualification requirements and outcomes.
- Plan 02 resumes at 02.2 after the bounded provider qualification.

#### Problems / Limitations

R9.4 is a completed post-selection risk check, not a second provider
competition or the start of R10 product integration. Its failed proxy gate
narrows R10 without revoking the R9.3 selection.

## Artifacts

This reference produces no independent artifacts. R9 owns the qualification
reports, provider decision, and selected-provider risk-retirement evidence.

## Files

- `knowledge/wiki/implementation_phases/r9-geometry-acoustics-provider-selection.md`
