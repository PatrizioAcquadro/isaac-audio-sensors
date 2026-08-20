# isaac-audio-sensors Technical Wiki Rules

## Scope and Hierarchy

This file governs all work under `knowledge/`. Repository-wide instructions
and the current restructuring specification remain authoritative.

The allowed structure is:

```text
knowledge/
├── .obsidian/                 # local and ignored
├── AGENTS.md
├── raw/
│   ├── assets/
│   ├── data/
│   ├── docs/
│   ├── notes/
│   ├── papers/
│   ├── transcripts/
│   └── web/
└── wiki/
    ├── decisions/
    ├── experiments/
    ├── implementation_phases/
    ├── sources/
    ├── topics/
    ├── index.md
    ├── log.md
    └── status.md
```

Empty leaf directories may contain only a `.gitkeep` placeholder. Do not add
folders without an explicit request and a matching update to this hierarchy.

## Ownership and Safety

- `knowledge/raw/` is user-owned and immutable to agents after this initial
  scaffold. Agents may inventory and read its contents, but must not edit,
  rename, move, overwrite, reformat, or delete them without explicit user
  authorization.
- Raw storage is limited to small research sources, clipped web material,
  specifications, reports, notes, transcripts, ingestible data, and local
  visual assets. Multi-gigabyte audio/video datasets, campaign evidence, and
  run outputs do not belong here.
- `knowledge/wiki/` is primarily agent-maintained. Preserve user editorial
  changes and make only evidence-backed updates requested by the user or
  required by a material implementation change.
- `knowledge/.obsidian/` is local editor state. Keep it ignored and do not
  treat workspace settings as project knowledge.

## Evidence and Truth

Use evidence in this order:

1. Current code and deterministic tests for executable behavior.
2. Current configurations, schemas, and verified small artifacts for declared
   contracts and recorded results.
3. Git history for phase attribution and meaningful change boundaries.
4. Current documentation and ingested sources for explanation, checked
   against the stronger evidence above.

Do not infer implementation from filenames, comments, plans, or outdated
documents. Clearly distinguish verified behavior, recorded claims,
interpretation, inference, and unresolved uncertainty.

## Canonical Page Ownership

- `wiki/status.md` — current capabilities, evidence, limitations, boundaries,
  and next steps.
- `wiki/implementation_phases/` — current restructuring and future product
  phases. Do not reconstruct S0–S4 campaign history; release history belongs
  in `CHANGELOG.md`.
- `wiki/topics/` — reusable concepts, architectures, backends, schemas,
  interfaces, hardware, and cross-cutting components.
- `wiki/decisions/` — choices with material architectural, interface, data,
  dependency, evaluation, reproducibility, or maintenance consequences.
- `wiki/experiments/` — durable product experiments or evaluations explicitly
  requested by the user. Ordinary correctness tests belong with the relevant
  implementation page.
- `wiki/sources/` — provenance and synthesis for material actually ingested
  from `knowledge/raw/`.

Link to one canonical page instead of duplicating its explanation.

## Writing and Linking

- Write clear, precise, direct US English.
- Prefer coherent technical explanations over file-by-file summaries.
- Use stable lower-kebab-case filenames and readable Obsidian links, such as
  `[[topics/system-architecture|System Architecture]]`.
- `wiki/index.md` is the navigation root. It must list `status.md` prominently
  and every other wiki page except itself and `log.md`, grouped by owner with a
  one-line description.
- `wiki/log.md` is append-only and chronological. Use
  `## YYYY-MM-DD — operation: Title`, followed by a concise description.
  Allowed operations are `setup`, `ingest`, `update`, `query`, `experiment`,
  and `lint`.

## Ingest and Synchronization

For source ingestion:

1. Inventory the candidate under `knowledge/raw/` without changing it.
2. Read only the material needed for the requested ingest.
3. Create or update one canonical `wiki/sources/` provenance page.
4. Update the affected canonical wiki pages without duplicating provenance.
5. Update `wiki/index.md` and append an `ingest` entry to `wiki/log.md`.

Synchronize affected wiki pages when a code change materially changes public
behavior, architecture, interfaces, schemas, formats, data flow, algorithms,
recording, simulation, or evaluation. Do not update the wiki for formatting,
comments, temporary debugging, or behavior-preserving refactoring.

For read-only queries, start at `wiki/index.md`, verify consequential claims
against the repository, and update the wiki only when explicitly requested or
when preserving a meaningful verified correction is necessary.

## Lint Workflow

Before finishing wiki work:

1. Confirm the allowed tree and preserve `knowledge/raw/` byte-for-byte.
2. Resolve internal wikilinks and ensure every page is represented in the
   index.
3. Check headings, repository-relative references, and canonical ownership.
4. Search for duplicated explanations, stale claims, unsupported completion
   language, copied plans, and accidental source ingestion.
5. Verify important claims against current code, tests, configurations,
   artifacts, and Git history.
6. Run scoped Markdown whitespace checks and inspect Git status and diffs.
7. Append a concise `lint` entry to `wiki/log.md` only after the checks pass.
