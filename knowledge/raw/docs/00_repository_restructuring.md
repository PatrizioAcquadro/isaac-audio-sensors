# R0 — Repository Restructuring Inventory

Target release line: clean `2.x`

This document is the temporary source of truth for restructuring `isaac-audio-sensors`.
It records the target repository boundary, the disposition of the current top-level surfaces, the deletion gates, and the order of implementation.

## Product Boundary

`isaac-audio-sensors` is an open-source robot-audition SDK for Isaac Sim and Isaac Lab.
It connects acoustic simulation, robot-mounted microphone arrays, standardized sensor observations, recording, datasets, and robot-learning policies.

The product owns:
- simulator-independent audio scene, source, microphone-array, and frame contracts;
- pluggable acoustic-propagation and sensor-model backends, including lightweight built-in backends and adapters to NVIDIA Kit Audio, RTX Acoustic, and other acoustic engines;
- observed multichannel sensor outputs and derived audio features, with privileged source, geometry, and isolated-signal ground truth kept separate for supervision and evaluation;
- calibration profiles and their application;
- generic recording, session layout, manifests, loading, validation, and replay;
- Isaac Sim stage integration and runtime sensors;
- Isaac Lab SensorBase integration with fixed-shape batched waveform, TDOA, spatial-audio feature, detection, and confidence observations;
- the Kit/Omniverse extension and its user interface;
- small public examples, deterministic test fixtures, and release tooling.
- The package complements NVIDIA Kit Audio and RTX Acoustic by providing the robot-mounted sensor, data-contract, recording, and Isaac Lab observation layer that connects acoustic simulation to robot learning.

The distributed product and tracked source tree do not own:
- SquadBot behaviors, policies, task orchestration, or task-specific   evaluation;
- Alex- or SquadBot-specific paths, factories, showcase logic, or acceptance criteria;
- S0–S4 campaign orchestration, physical-acquisition protocols, grants, holdouts, corrective amendments, or one-shot evidence workflows;
- raw experiment datasets or run-specific outputs as tracked or distributed content;
- historical phase documentation beyond concise release notes in `CHANGELOG.md`.

SquadBot is a downstream consumer.
It may own an adapter to the public audio sensor API, task logic, evaluators, and a few small derived fixtures.
These product boundaries do not exclude repository-owned publication evidence from the ignored local `evidence/` workspace defined below.

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
├── evidence/ (local and ignored; repository-owned publication evidence, USED ONLY WHEN NEEDED)
├── knowledge/
│   ├── .obsidian/ (local and ignored)
│   ├── AGENTS.md
│   ├── raw/
│   │   ├── assets/
│   │   ├── data/
│   │   ├── docs/
│   │   ├── notes/
│   │   ├── papers/
│   │   ├── transcripts/
│   │   └── web/
│   └── wiki/
│       ├── decisions/
│       ├── experiments/
│       ├── implementation_phases/
│       ├── sources/
│       ├── topics/
│       ├── index.md
│       ├── log.md
│       └── status.md
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

There is no target root `docs/`, `dataset/`, `outputs/`, `configs/`, `scripts/`, or `.github/` directory.
Build products, caches, generated data, local goals, and runtime output remain ignored and absent from releases.

Root `evidence/` is the deliberate local home for paper-relevant evidence owned by `isaac-audio-sensors`.
It remains inside the repository working directory, is ignored by Git, and is excluded from packages and releases.
Use one clearly named subdirectory per study or paper. Evidence owned by SquadBot or another downstream project belongs under the corresponding ignored evidence directory in that project's repository.

`knowledge/raw/` is for small, immutable source material used to build the wiki.
It is not a destination for multi-gigabyte audio, video, or experiment datasets.

## Root File Disposition

This table covers every file tracked at the repository root on the R0 baseline, plus the two target files that do not yet exist.

| Current or target file | Decision | Target responsibility |
| --- | --- | --- |
| `.gitignore` | Keep and simplify | Ignore local publication evidence, build products, datasets, outputs, media, caches, and local tooling state. |
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

This table covers every top-level directory with tracked files on the R0 baseline, plus ignored data/runtime directories that affect the cleanup.

| Current directory | Decision | Destination or rule |
| --- | --- | --- |
| `.github/` | Delete | The only current workflow is S4-coupled. Use local Make targets unless a concrete publication requirement later justifies automation. |
| `configs/` | Split, then delete | Move the generic demo configuration to `examples/configs/`; delete S-specific configurations. |
| `dataset/` | Classify, relocate, then delete | Move paper-relevant evidence owned by this repository to `evidence/<study-or-paper>/`. Move SquadBot or other downstream evidence to the corresponding repository. Delete data only after the evidence gate below passes. |
| `docs/` | Absorb, then delete in R4 | Move only current essential content to `knowledge/wiki/`; move public schemas into the package. |
| `examples/` | Keep and reduce | Retain only small runnable public examples, configs, traces, calibration samples, and deterministic fixtures. Move useful GUI images here |
| `exts/` | Keep and thin | Keep Kit packaging, metadata, icons, and the extension entry point; implementation belongs in `src/.../kit/`. |
| `outputs/` | Classify, relocate, then delete | Move paper- or release-relevant evidence to `evidence/<study-or-paper>/` in the owning repository. Discard ordinary reproducible runtime outputs only after confirming that they are not evidence. |
| `packs/` | Keep if supported | Retain the optional acoustics pack only while its build and runtime contract are actively tested. |
| `scripts/` | Split, then delete | Move public examples to `examples/`, release tooling to `tools/release/`, runtime checks to `tools/smoke/`, and delete phase/run-specific scripts. |
| `src/` | Keep and restructure | Retain only the generic package subsystems described below. |
| `tests/` | Keep and restructure | Replace phase/history organization with unit, contract, integration, Isaac, release, and fixture ownership. |

Ignored directories such as `dist/`, `build/`, `runs/`, `.local/`, caches, and local agent state are not product surfaces.
Cleanup may remove generated copies when safe, but these paths must never become package inputs or sources of truth.
The ignored `evidence/` directory is the explicit exception: it is a local research surface and may be the source of truth for publication claims, but it must never become a package input or release payload.

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

The word "dataset" currently refers to three different surfaces. They have different outcomes:

1. Root `dataset/` is ignored raw S4 audio/video/evidence.
   It is not required by the installed sensor. Before removing that legacy location, classify each retained dataset by owning project and relocate it to `evidence/<study-or-paper>/` inside that project's repository.
2. Generic dataset code is a product capability.
   It moves from `core/dataset/` to the clearer `recording/` subsystem.
3. The small deterministic reference session remains as a test fixture under `tests/fixtures/recording/`; it is not a research dataset.

Raw evidence that is necessary for an `isaac-audio-sensors` paper must live under root `evidence/<study-or-paper>/` in this working tree.
The entire `evidence/` directory remains untracked by Git and absent from distributions, but it is part of the declared local repository structure and must not be treated as disposable output.
SquadBot and other downstream projects keep their own raw evidence in the same kind of ignored, repository-local location; this repository receives only the smallest derived fixture needed to test a consumer boundary.

## Clean v2 API Policy

The current v1 name freeze does not constrain the `2.x` restructuring.
Removing obsolete imports, moving namespaces, and reducing the CLI are intentional breaking changes. 
Permanent compatibility shims are not required for experimental, phase-specific, Alex-specific, or SquadBot-specific surfaces.

The target public concepts are:

- audio frame, time window, scene, source, pose, detection, and microphone array models;
- configuration, schema, backend, acoustics, calibration, DOA, effects, and plugin interfaces;
- generic recording, manifest, loading, validation, and replay;
- Isaac Sim sensor and stage integration;
- Isaac Lab sensor and batched data;
- Kit extension behavior;
- a small user-facing CLI.

R5 freezes the exact v2 import and CLI inventory only after R3 removes the non-product surfaces. 
Python package versions and serialized schema versions are independent: an existing `v1` data schema may remain valid in package `2.0.0` when its data contract remains useful.

## Deletion Gates

No destructive restructuring step may bypass these gates:

1. **Consumer gate:** audit imports, CLI calls, paths, schemas, and generated artifacts before moving or deleting a symbol. 
   Active SquadBot behavior must be migrated to its owning repository.
2. **Evidence gate:** classify the owning project and verify the complete relocation of raw datasets or paper-relevant outputs to `evidence/` in that project's repository before deleting the old copy.
3. **Test gate:** establish the R2 characterization and contract suites before removing S-specific source and tests, so skips cannot masquerade as successful coverage.
4. **Distribution gate:** audit an installed wheel, sdist, Kit extension archive, and optional pack before declaring the migration complete. 
   None may contain acquisition code, S-phase surfaces, SquadBot/Alex paths, raw data, tests, or maintainer-only scripts.

## Implementation Sequence

### R1 — Knowledge and repository rules

Create the root and knowledge `AGENTS.md` files and the empty, versioned `knowledge/raw/` and `knowledge/wiki/` skeleton. Keep local Obsidian state ignored. 
Do not populate the wiki or recreate S0–S4 history during R1; migration of concise, current product information belongs in R4, and release history belongs in `CHANGELOG.md`.

### R2 — Fast tests before code movement

- Add characterization tests for the intended public frames, schemas, configuration, backends, recording contract, Isaac/Lab imports, and CLI.
- Organize tests into `unit`, `contract`, `integration`, `isaac`, `release`, and `fixtures` instead of phase-based filenames.
- Make `make test` run unit and contract tests with a target below ten seconds. Provide separate test targets.
- Remove historical Git-checkout and filename-regex phase classification.
- Add a distribution-content test that rejects `acquisition`, S-phase, SquadBot/Alex, local absolute path, dataset, output, and test surfaces in released artifacts.

### R3 — Enforce the repository boundary

- Remove `acquisition/`, S-specific acceptance criteria, configs, schemas, scripts, tests, docs, and tracked output only after their gates pass.
- Move generic configuration, schemas, release tools, smoke tools, and small fixtures to their target owners.
- Keep generic calibration, sensor backends, and recording behavior here.
- Move only active downstream adapters, task evaluators, and tiny fixtures to SquadBot; relocate raw evidence to the ignored `evidence/` directory in the repository that owns the study or paper.
- Remove S, Alex, and SquadBot targets and paths from packaging and the Makefile.

### R4 — Replace `docs/` with the wiki

Move concise current product documentation and useful GUI assets to `knowledge/wiki/`, absorb essential root guidance into `README.md`, and delete the entire root `docs/` directory, including this applied R0 specification.

### R5 — Refactor by semantic component

Refactor one subsystem at a time in this order: 
- public core contracts,
- backends/DSP,
- recording, 
- Isaac Sim, 
- Isaac Lab, 
- Kit UI,
- CLI. 

Remove the duplicate package examples and freeze the exact v2 public API only after the tree is clean. 

### R6 — Simplify packaging and release

Move package-data declarations into `pyproject.toml`, reduce local Make targets, verify clean wheel/sdist/Kit/pack artifacts, and prepare the public README and marketplace release. 
Do not restore automation unless a concrete publication or maintenance need justifies it.

### R7 — Paper readiness

Define the reproducible benchmark, organize the necessary scientific artifacts under the repository-local ignored `evidence/` directory, state claims and limitations, prepare selected artifacts for separate publication only when needed, and add the paper citation to the README once available.
