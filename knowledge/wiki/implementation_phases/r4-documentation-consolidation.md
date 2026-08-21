# Phase R4 — Documentation Consolidation

## Objective

Replace the root `docs/` collection with a canonical technical wiki that explains the maintained product by subject, keeps the root README concise, and leaves product and release chronology in `CHANGELOG.md`.

## Subphase R4.1 — Canonical Knowledge Model

#### Implementation

Current information from the former documentation is re-authored into canonical topic, decision, phase, and status pages after verification against code, tests, configuration, schemas, package metadata, and Git history.

Each subject has one owner page and other pages link to it instead of copying the same explanation.

The former combined R2-R3 record is separated into one page per top-level phase.

#### Key Decisions

The wiki contains current concepts, contracts, workflows, limitations, and phase outcomes; it does not reproduce old release narratives or machine-specific smoke reports.

The R0 restructuring specification is retained byte-for-byte under `knowledge/raw/docs/` as explicitly authorized raw material and receives no source page because it is the conceptual setup document for the knowledge system.

#### Problems / Limitations

The wiki is repository-hosted technical knowledge rather than an independently deployed documentation site.

The removed GUI screenshots represented extension version `1.0.0` and were not current evidence for the maintained interface.

## Subphase R4.2 — Public and Extension Metadata

#### Implementation

The root README provides the product landing page, install and quickstart path, validation entry points, limitations, and links into the canonical wiki.

The Kit extension retains a small standalone README and an extension-specific changelog because installed extension archives cannot depend on repository-relative wiki or root changelog files.

The extension manifest keeps its package `readme` and `changelog` metadata but no longer advertises the local files as the complete documentation set.

#### Key Decisions

Python, CLI, schema, and runtime contracts do not change in R4.

Documentation tooling is not a package extra because the wiki is plain Markdown and no MkDocs build remains.

#### Problems / Limitations

The standalone extension metadata is intentionally narrower than the canonical wiki.

## Subphase R4.3 — Boundary Enforcement

#### Implementation

Release tests require the root `docs/` directory to remain absent, the R0 specification to remain in its authorized raw location, every wiki page to be indexed, every internal wikilink to resolve, active Markdown references to avoid removed root-doc paths, and Kit metadata paths to resolve inside the extension.

Version synchronization reads current package information from executable metadata, the root README, canonical wiki status, the root changelog, and the extension-specific changelog instead of the deleted versioning document.

#### Key Decisions

The documentation boundary is tested as a maintained repository contract.

#### Problems / Limitations

Automated structural checks cannot replace editorial review for clarity, duplication, or unsupported claims.

## Artifacts

The R4 artifacts are the canonical wiki, compact root README, standalone Kit metadata, authorized raw R0 specification, and documentation-boundary release test.

Deterministic R4 validation results are recorded in [[status|Current Status]]; clean-source archive builds and audits run after the implementation commit and are reported in the phase handoff.

## Files

- `knowledge/wiki/`
- `README.md`
- `tests/release/test_documentation_boundary.py`
