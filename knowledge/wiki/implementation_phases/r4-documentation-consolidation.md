# Phase R4 — Documentation Consolidation

Status: complete; efficiency follow-up authorized 2026-09-11.

## Objective

Keep one canonical owner per subject and make the current implementation path cheap to read.

## Subphase R4.1 — Canonical Knowledge Model

#### Implementation

Replaced root docs with plans, topics, decisions, experiments and a current status index. The 2026-09-11 follow-up compacts every plan/status/log and separates R10 acceptance, native contract and decisive evidence.

#### Key Decisions

Plans contain outcome, remaining work and limits; decisions contain binding scope; experiments contain decisive methods/results; topics contain reusable contracts. Link instead of copying.

#### Problems / Limitations

The user explicitly authorized historical log compaction for this pass. Older full prose remains recoverable at `5cfe48d`; append-only maintenance resumes afterward. Raw material and AGENTS.md remain unchanged.

## Subphase R4.2 — Public and Extension Metadata

#### Implementation

Root README is a compact landing page; installed Kit keeps standalone readme/changelog without requiring the wiki.

#### Key Decisions

No documentation tooling dependency or package runtime change.

#### Problems / Limitations

Historical GUI captures do not establish current interface behavior.

## Subphase R4.3 — Boundary Enforcement

#### Implementation

Maintain index/page/link checks, removed-root-doc checks, Kit metadata and version synchronization.

#### Key Decisions

Retain accepted scope, decisive failures, evidence locations and current contract links during compaction; do not create a verbatim archive in another wiki page.

#### Problems / Limitations

Structural tests cannot prove editorial completeness; review requirements and negative findings explicitly.

## Artifacts

Current navigation: [[index|Wiki index]]. Original R0 remains in its authorized `knowledge/raw/docs/` location; no source ingestion or raw edit occurs.

## Files

`knowledge/wiki/`, `README.md`, `tests/release/test_documentation_boundary.py`.
