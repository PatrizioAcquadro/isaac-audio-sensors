# R0 — Repository Restructuring Inventory

Status: approved restructuring specification

Baseline: `main` at `de2b680e1354e9db2327abbe8e2b0f419860afe7`

Target release line: clean `2.x`

Scope of R0: documentation and decisions only

## Purpose

This document is the temporary source of truth for restructuring
`isaac-audio-sensors`. It records the target repository boundary, the
disposition of the current top-level surfaces, the deletion gates, and the
order of implementation.

R0 does not move or delete source code, datasets, evidence, tests, or runtime
artifacts. This file itself is temporary: R4 will remove `docs/` after the
small amount of still-current product documentation has moved to
`knowledge/wiki/`.

## Product Boundary

`isaac-audio-sensors` is a reusable open-source audio sensor package for Isaac
Sim and Isaac Lab. The product owns:

- simulator-independent audio scene, source, microphone-array, and frame
  contracts;
- audio propagation, room-acoustics, Doppler, DOA, effects, and backend
  behavior;
- calibration profiles and their application;
- generic recording, session layout, manifests, loading, validation, and
  replay;
- Isaac Sim stage integration and runtime sensors;
- Isaac Lab sensor integration and batched data;
- the Kit/Omniverse extension and its user interface;
- small public examples, deterministic test fixtures, and release tooling.

The product does not own:

- SquadBot behaviors, policies, task orchestration, or task-specific
  evaluation;
- Alex- or SquadBot-specific paths, factories, showcase logic, or acceptance
  criteria;
- S0–S4 campaign orchestration, physical-acquisition protocols, grants,
  holdouts, corrective amendments, or one-shot evidence workflows;
- raw experiment datasets or run-specific outputs;
- historical phase documentation beyond concise release notes in
  `CHANGELOG.md`.

SquadBot is a downstream consumer. It may own an adapter to the public audio
sensor API, task logic, evaluators, and a few small derived fixtures. It must
not receive a wholesale copy of the raw S4 dataset or generic sensor code.

## Target Repository

The target `2.x` repository is intentionally small:

```text
isaac-audio-sensors/
├── AGENTS.md
├── README.md
├── CHANGELOG.md
├── LICENSE
├── NOTICE
├── pyproject.toml
├── Makefile
├── .gitignore
├── knowledge/
│   ├── AGENTS.md
│   ├── raw/
│   └── wiki/
│       ├── index.md
│       ├── status.md
│       ├── getting-started.md
│       ├── assets/
│       ├── topics/
│       ├── decisions/
│       └── experiments/
├── src/isaac_audio_sensors/
│   ├── __init__.py
│   ├── cli.py
│   ├── schemas/
│   ├── core/
│   ├── recording/
│   ├── isaac/
│   ├── lab/
│   └── kit/
├── exts/
│   └── isaac_audio_sensors.omni/
├── examples/
│   ├── configs/
│   ├── core/
│   ├── isaac_sim/
│   ├── isaac_lab/
│   ├── calibration/
│   └── traces/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── isaac/
│   ├── release/
│   └── fixtures/
├── tools/
│   ├── release/
│   └── smoke/
└── packs/
    └── acoustics/
```

There is no target root `docs/`, `dataset/`, `outputs/`, `configs/`,
`scripts/`, or `.github/` directory. Build products, caches, generated data,
local goals, and runtime output remain ignored and absent from releases.

`knowledge/raw/` is for small, immutable source material used to build the
wiki. It is not a destination for multi-gigabyte audio, video, or experiment
datasets.

## Root File Disposition

This table covers every file tracked at the repository root on the R0
baseline, plus the two target files that do not yet exist.

| Current or target file | Decision | Target responsibility |
| --- | --- | --- |
| `.gitignore` | Keep and simplify | Ignore build products, datasets, outputs, media, caches, and local tooling state. |
| `CHANGELOG.md` | Keep | The only retained historical summary, organized by release. |
| `CITATION.cff` | Delete | Add the paper citation to `README.md` only after the paper exists. |
| `CODE_OF_CONDUCT.md` | Delete | Not essential at the current project/community stage. |
| `CONTRIBUTING.md` | Absorb, then delete | Put the few essential contribution commands and expectations in `README.md`. |
| `LICENSE` | Keep | Open-source license. |
| `MANIFEST.in` | Absorb, then delete | Declare necessary package data in `pyproject.toml` and verify wheel/sdist contents. |
| `Makefile` | Keep and reduce | Expose a small set of local test, lint, build, release, and runtime-smoke commands. |
| `NOTICE` | Keep | Required notices and attributions for distribution. |
| `README.md` | Keep and rewrite | Product landing page, install, quick start, concise contribution/security notes, limitations, and later paper citation. |
| `SECURITY.md` | Absorb, then delete | Preserve only warnings against publishing secrets/private recordings and against safety-critical use without independent validation. |
| `pyproject.toml` | Keep and simplify | Package metadata, dependencies, entry points, tool settings, and package data. |
| `AGENTS.md` | Create in R1 | Repository-wide development and validation rules. |
| `TODO.md` | Keep local and ignored | Active implementation checklist only; never product documentation or release history. |

## Top-Level Directory Disposition

This table covers every top-level directory with tracked files on the R0
baseline, plus ignored data/runtime directories that affect the cleanup.

| Current directory | Decision | Destination or rule |
| --- | --- | --- |
| `.github/` | Delete | The only current workflow is S4-coupled. Use local Make targets unless a concrete publication requirement later justifies automation. |
| `configs/` | Split, then delete | Move the generic demo configuration to `examples/configs/`; delete S-specific configurations. |
| `dataset/` | Archive externally if needed, then delete locally | Raw S4 evidence; never ship it and do not move it wholesale to SquadBot. Deletion requires the evidence gate below. |
| `docs/` | Absorb, then delete in R4 | Move only current essential content and useful GUI images to `knowledge/wiki/`; move public schemas into the package; delete phase history. |
| `examples/` | Keep and reduce | Retain only small runnable public examples, configs, traces, calibration samples, and deterministic fixtures. |
| `exts/` | Keep and thin | Keep Kit packaging, metadata, icons, and the extension entry point; implementation belongs in `src/.../kit/`. |
| `outputs/` | Archive selectively, then delete from the active tree | Keep externally only evidence required by a paper or release. Runtime outputs remain ignored. |
| `packs/` | Keep if supported | Retain the optional acoustics pack only while its build and runtime contract are actively tested. |
| `scripts/` | Split, then delete | Move public examples to `examples/`, release tooling to `tools/release/`, runtime checks to `tools/smoke/`, and delete phase/run-specific scripts. |
| `src/` | Keep and restructure | Retain only the generic package subsystems described below. |
| `tests/` | Keep and restructure | Replace phase/history organization with unit, contract, integration, Isaac, release, and fixture ownership. |

Ignored directories such as `dist/`, `build/`, `runs/`, `.local/`, caches,
and local agent state are not product surfaces. Cleanup may remove generated
copies when safe, but these paths must never become package inputs or sources
of truth.

## Package Component Disposition

| Current component | Decision | Target |
| --- | --- | --- |
| `core/` | Keep and narrow | Simulator-independent contracts, configuration, DSP, backends, plugins, calibration, and acoustics. No S-specific acceptance policy. |
| `core/dataset/` and generic dataset IO | Move | `recording/`, owning generic record, manifest, load, replay, shard, split, stats, and validation behavior. |
| `acquisition/` | Delete | It is S-specific physical acquisition/evidence code. Its reference generator is not a target public API and leaves with the S workflows. |
| `examples/` inside the package | Delete | Root `examples/` is the only example surface. |
| `isaac/` | Keep and narrow | Isaac Sim discovery, stage binding, pose resolution, occlusion, and runtime sensing. |
| `isaac/extension_ui/` | Move | `kit/`, separated into lifecycle, configuration, recording, and view-model responsibilities. |
| `lab/` | Keep and narrow | Isaac Lab sensor configuration, stage/entity binding, and batched data buffers. |
| Public JSON schemas | Move | Ship `audio_sensor_frame.v1`, `audio_dataset_manifest.v1`, and `audio_calibration_profile.v1` from `src/isaac_audio_sensors/schemas/`. |
| S-specific schemas | Delete | They are campaign/evidence contracts, not product contracts. |
| CLI | Keep and reduce | Retain public validate, simulate, recording, trace, capability, and schema operations; remove S-specific acquisition commands. |

## Data and Evidence Policy

The word "dataset" currently refers to three different surfaces. They have
different outcomes:

1. Root `dataset/` is ignored raw S4 audio/video/evidence. It is not required
   by the installed sensor and leaves the active checkout after verified
   archival or an explicit decision that it is no longer needed.
2. Generic dataset code is a product capability. It moves from
   `core/dataset/` to the clearer `recording/` subsystem.
3. The small deterministic reference session remains as a test fixture under
   `tests/fixtures/recording/`; it is not a research dataset.

Raw evidence that is necessary for a paper must live in a deliberate external
archive, research artifact, or separately published dataset. Source Git is
not that archive. SquadBot receives only the smallest derived fixture needed
to test its consumer boundary.

## Clean v2 API Policy

The current v1 name freeze does not constrain the `2.x` restructuring.
Removing obsolete imports, moving namespaces, and reducing the CLI are
intentional breaking changes. Permanent compatibility shims are not required
for experimental, phase-specific, Alex-specific, or SquadBot-specific
surfaces.

The target public concepts are:

- audio frame, time window, scene, source, pose, detection, and microphone
  array models;
- configuration, schema, backend, acoustics, calibration, DOA, effects, and
  plugin interfaces;
- generic recording, manifest, loading, validation, and replay;
- Isaac Sim sensor and stage integration;
- Isaac Lab sensor and batched data;
- Kit extension behavior;
- a small user-facing CLI.

R5 freezes the exact v2 import and CLI inventory only after R3 removes the
non-product surfaces. Python package versions and serialized schema versions
are independent: an existing `v1` data schema may remain valid in package
`2.0.0` when its data contract remains useful.

## Deletion Gates

No destructive restructuring step may bypass these gates:

1. **Consumer gate:** audit imports, CLI calls, paths, schemas, and generated
   artifacts before moving or deleting a symbol. Active SquadBot behavior
   must be migrated to its owning repository or adapted to the v2 API.
2. **Evidence gate:** verify an external backup/archive and its scope before
   deleting raw datasets or paper-relevant outputs. R0 does not open, copy,
   move, or delete S4 evidence.
3. **Test gate:** establish the R2 characterization and contract suites before
   removing S-specific source and tests, so skips cannot masquerade as
   successful coverage.
4. **Distribution gate:** audit an installed wheel, sdist, Kit extension
   archive, and optional pack before declaring the migration complete. None
   may contain acquisition code, S-phase surfaces, SquadBot/Alex paths, raw
   data, tests, or maintainer-only scripts.

## Implementation Sequence

### R1 — Knowledge and repository rules

Create root and knowledge `AGENTS.md` files, create the wiki skeleton, and
migrate only current, essential information. Do not recreate S0–S3 history;
release history belongs in `CHANGELOG.md`.

### R2 — Fast tests before code movement

- Add characterization tests for the intended public frames, schemas,
  configuration, backends, recording contract, Isaac/Lab imports, and CLI.
- Organize tests into `unit`, `contract`, `integration`, `isaac`, `release`,
  and `fixtures` instead of phase-based filenames.
- Make `make test` run unit and contract tests with a target below ten seconds.
  Provide separate `test-integration`, `test-isaac`, `test-release`, and
  `test-all` targets.
- Remove historical Git-checkout and filename-regex phase classification.
- Add a distribution-content test that rejects `acquisition`, S-phase,
  SquadBot/Alex, local absolute path, dataset, output, and test surfaces in
  released artifacts.

### R3 — Enforce the repository boundary

- Remove `acquisition/`, S-specific acceptance criteria, configs, schemas,
  scripts, tests, docs, and tracked output only after their gates pass.
- Move generic configuration, schemas, release tools, smoke tools, and small
  fixtures to their target owners.
- Keep generic calibration, sensor backends, and recording behavior here.
- Move only active downstream adapters, task evaluators, and tiny fixtures to
  SquadBot; keep raw evidence in an external archive when required.
- Remove S, Alex, and SquadBot targets and paths from packaging and the
  Makefile.

### R4 — Replace `docs/` with the wiki

Move concise current product documentation and useful GUI assets to
`knowledge/wiki/`, absorb essential root guidance into `README.md`, and delete
the entire root `docs/` directory, including this applied R0 specification.

### R5 — Refactor by semantic component

Refactor one subsystem at a time in this order: public core contracts,
backends/DSP, recording, Isaac Sim, Isaac Lab, Kit UI, and CLI. Remove the
duplicate package examples and freeze the exact v2 public API only after the
tree is clean. Validate and commit each coherent component independently.

### R6 — Simplify packaging and release

Move package-data declarations into `pyproject.toml`, reduce local Make
targets, verify clean wheel/sdist/Kit/pack artifacts, and prepare the public
README and marketplace release. Do not restore automation unless a concrete
publication or maintenance need justifies it.

### R7 — Paper readiness

Define the reproducible benchmark, publish or archive the necessary scientific
artifacts separately, state claims and limitations, and add the paper citation
to the README once available.

## R0 Completion Criteria

R0 is complete when:

- every tracked root file and top-level directory has an explicit target;
- product and SquadBot ownership are unambiguous;
- raw data, generic recording code, and small fixtures are distinguished;
- the clean v2 compatibility policy is explicit;
- deletion gates and the R1–R7 order are recorded;
- no runtime code, dataset, evidence, or package artifact has changed;
- this documentation-only change passes `git diff --check` and is committed
  locally without a push.
