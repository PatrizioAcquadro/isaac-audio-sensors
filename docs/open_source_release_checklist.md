# Open Source Release Checklist

This checklist is for preparing a public `isaac-audio-sensors` release
candidate. It is intentionally separate from publishing. Do not tag, push, or
publish to PyPI from this checklist unless a maintainer explicitly requests it.

## Repository Boundary

- [x] Standalone package repository exists outside downstream project repos.
- [x] Distribution name is `isaac-audio-sensors`.
- [x] Import package is `isaac_audio_sensors`.
- [x] Apache-2.0 license, notice, citation, contributing, conduct, and security
  files are present.
- [x] Project-specific adapters, private recordings, generated media, local
  goals, environment folders, and cache/build outputs are ignored and excluded
  from distributions.
- [x] Public metadata points to the package source repository, docs/showcase,
  changelog, and issue tracker.

## API Freeze

- [x] `docs/api_freeze_0_1.md` separates stable, provisional, experimental, and
  private surfaces.
- [x] `AudioSensorFrame` v1 is documented as the primary stable data contract.
- [x] Core data models, backend ids, trace/schema helpers, and CLI commands are
  listed with compatibility expectations.
- [x] Isaac Sim live stage lifecycle and explicit stage binding are documented.
- [x] Semantic discovery and live USD pose resolution are documented as
  provisional but supported.
- [x] Isaac Lab `SensorBase` class recovery, vector buffers, stage binding, and
  entity binding are documented with compatibility limits.
- [x] Diagnostic/provenance namespaces are documented as open-ended but
  supported evidence fields.
- [x] Deprecation and API-change release checklist are documented.

## Documentation Consistency

- [x] README and docs describe a standalone open-source Isaac Sim/Lab audio
  sensor package.
- [x] Docs avoid claims of full acoustic realism, production beamforming,
  speech recognition, or full Replicator integration.
- [x] Limitations document the optional approximate `pyroomacoustics` path.
- [x] Limitations document that Replicator annotator/writer registration is not
  implemented.
- [x] Limitations document that Lab entity binding covers common Isaac Lab
  tensor/entity patterns, not arbitrary custom task APIs.
- [x] Validation docs state that live Isaac checks require user-managed Isaac
  runtimes, GPU access, and non-sandboxed runtime visibility.
- [x] Roadmap separates completed release-candidate work from future work.

## Packaging And Distribution

- [x] `pyproject.toml` has package metadata, extras, classifiers, URLs, and the
  `isaac-audio-sensors` console script.
- [x] `MANIFEST.in` intentionally includes docs, examples, schemas, extension
  metadata, scripts, tests, and CI config for the source distribution.
- [x] `MANIFEST.in` prunes generated outputs, local goals, caches, virtual
  environments, build directories, egg-info, and media artifacts.
- [x] `make build` runs `scripts/audit_distribution.py` after building the
  source distribution and wheel.
- [x] `make audit-dist` can inspect existing built archives and fails on
  forbidden paths or public-package leak tokens.
- [ ] Inspect final archive contents before tagging or publishing.

## Versioning And Changelog

- [x] Version remains `0.1.0` while the repository is preparing the initial
  release candidate.
- [x] `docs/versioning.md` explains that package version and frame schema
  version are separate.
- [x] `CHANGELOG.md` has an Unreleased section for the current release
  candidate hardening.
- [ ] When maintainers decide to cut the release, move Unreleased entries under
  a dated version heading before tagging.

## Required Validation

Run and record:

```bash
make test
make lint
make build
make import-smoke
make validate-config
make export-schema
make audit-dist
git diff --check
```

Run live checks on a local Isaac runtime when available:

```bash
make live-isaac-sim-audio ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

If a live command cannot run because of sandboxing, EULA, GPU visibility, or
runtime availability, record the exact command, exact error, and the closest
validation that did run.

## Final Pre-Publish Checks

- [ ] Public hygiene grep returns no project-specific or private path leaks.
- [ ] `git ls-files` shows no tracked caches, generated outputs, local goals,
  virtual environments, build artifacts, or private environment files.
- [ ] Built archive audit passes after a fresh `make build`.
- [ ] README, docs, changelog, versioning, and roadmap agree on the current
  release status.
- [ ] Live Isaac Sim and Isaac Lab GPU evidence is fresh, or blockers are
  explicitly documented.
