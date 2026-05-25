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

## V1 Scope Freeze

- [x] [V1 Public Scope](v1_scope.md) is the canonical public source of truth
  for v1 promises and non-promises.
- [x] V1 promises only the stable `AudioSensorFrame` v1 public contract,
  stable L0 `geometry_only`, stable L1 `tdoa_synthetic`, supported optional L2
  `room_acoustics`, supported Isaac Sim live sensor path, supported Isaac Lab
  sensor path, Omniverse extension as the reference UX, stable JSON/JSONL
  export, and Replicator as an optional extension capability.
- [x] V1 does not promise SquadBot as a v1 release gate, sim-real calibration,
  real hardware benchmarks, complete L3/L4 acoustic fidelity, realistic
  occlusions or material acoustics, mandatory ROS 2 or downstream adapters, or
  Alex or SquadBot validation before releasing the sensor package.
- [x] Explicit non-promises use the canonical labels: SquadBot as a v1 release
  gate; Sim-real calibration; Real hardware benchmarks; Complete L3/L4
  acoustic fidelity; Realistic occlusions or material acoustics; Mandatory
  ROS 2 or downstream adapters; Alex or SquadBot validation before releasing
  the sensor package.
- [x] Replicator is documented as extension-only and optional; core package
  import, `AudioSensorFrame`, JSON/JSONL export, the Isaac Sim base sensor, and
  the Isaac Lab sensor do not depend on `omni.replicator.core`.

## API Freeze

- [x] `docs/api_freeze_0_1.md` separates stable, provisional, experimental, and
  private surfaces.
- [x] `AudioSensorFrame` v1 is documented as the primary stable data contract.
- [x] `AudioSensorFrame.schema_version` is documented as independent from the
  Python package version.
- [x] Checked-in JSON Schema parity, JSON corpus coverage, and NDJSON corpus
  coverage are release gates.
- [x] Core data models, backend ids, trace/schema helpers, and CLI commands are
  listed with compatibility expectations.
- [x] Isaac Sim live stage lifecycle and explicit stage binding are documented.
- [x] Semantic discovery and live USD pose resolution are documented as
  provisional but supported.
- [x] Isaac Lab `SensorBase` class recovery, vector buffers, stage binding, and
  entity binding are documented with compatibility limits.
- [x] Diagnostic/provenance namespaces are documented as open-ended but
  supported evidence fields.
- [x] Acoustic fidelity ladder is documented with stable L0/L1, supported
  optional L2, provisional L3, and experimental/tooling L4 boundaries.
- [x] Coordinate policy, units, timestamps, provenance values, ambiguity
  representation, and stable diagnostics namespaces are documented in public
  contract terms.
- [x] Deprecation and API-change release checklist are documented.

## Documentation Consistency

- [x] README and docs describe a standalone open-source Isaac Sim/Lab audio
  sensor package.
- [x] Docs avoid claims of full acoustic realism, production beamforming,
  speech recognition, core-required Replicator integration, or universal
  Replicator/annotator compatibility.
- [x] Docs state that L3 advanced realism and L4 sim-real calibration are
  future-compatible metadata/tooling directions, not complete v1 runtime
  systems.
- [x] Limitations document the optional approximate `pyroomacoustics` path.
- [x] Limitations document that Replicator recording is an optional extension
  writer path, while annotator registration remains best-effort by Kit version
  and missing Kit Replicator APIs do not block core package JSON/JSONL output.
- [x] Limitations document that Lab entity binding covers common Isaac Lab
  tensor/entity patterns, not arbitrary custom task APIs.
- [x] Validation docs state that live Isaac checks require user-managed Isaac
  runtimes, GPU access, and non-sandboxed runtime visibility.
- [x] Validation docs state that SquadBot, Alex, ROS 2/downstream adapters, real
  hardware benchmarks, sim-real calibration, complete L3/L4, and realistic
  material/occlusion acoustics are not v1 package release gates.
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

- [x] Package version is `1.0.0rc1`, using exact PEP 440 spelling.
- [x] `1.0.0rc1` is documented as a release candidate, not final `1.0.0`.
- [x] `docs/versioning.md` explains that package version and frame schema
  version are separate.
- [x] `CHANGELOG.md` has a dated `1.0.0rc1` section covering the release
  candidate scope.
- [ ] When maintainers decide to cut final `1.0.0`, add a new dated changelog
  section instead of editing the frame schema version.

## Required Validation

Run and record these required local release-candidate gates:

```bash
make test
make lint
make export-schema
git diff --check
make build
make audit-dist
make import-smoke
```

These required local gates cover contract/schema/trace validation, L0/L1 tests,
optional L2 behavior, JSON/JSONL export, package build, packaging audit, import
smoke, lint, and distribution audit. `make validate-config` is a useful local
usage smoke and may be run in addition, but it is not a downstream project gate.

Run and record live sensor gates on a local Isaac runtime when refreshing live
runtime evidence before publishing or tagging a release candidate:

```bash
make live-isaac-sim-audio ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"
```

Run the extension UX smoke when Kit is available and the reference UX evidence
is being refreshed:

```bash
make live-omniverse-extension-ux ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"
```

Replicator validation is an optional extension-capability gate. A missing
Replicator runtime or incompatible Kit writer/annotator API must be recorded as
extension evidence, but it must not block the core v1 package unless the release
specifically claims Replicator is enabled for that environment.

If a live command cannot run because of sandboxing, EULA, GPU visibility, or
runtime availability, record the exact command, exact error, and the closest
validation that did run.

Latest local Isaac Lab GPU evidence was refreshed on 2026-05-24 local time with
`make live-isaac-lab-audio-gpu ISAAC_LAB_PYTHON="$ISAAC_LAB_PYTHON"`.
The artifact `outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`
reported `status: "passed"` on Isaac Lab `0.54.2`, Isaac Sim `5.1.0`, Kit
`107.3.3+production.229672.69cbf6ad.gl`, Torch `2.7.0+cu128`, CUDA device
`cuda:0`, and `NVIDIA GeForce RTX 4090`. It proved real
`SensorBaseCfg`/`SensorBase` subclassing, no fallback classes in Lab, CUDA
placement for all RL-facing and bookkeeping tensors, selected update/reset
checks for explicit, stage, and entity paths, stable RL observation keys, and
real `pxr.Usd.Stage` binding. The full real `InteractiveScene`/`RigidObject`
entity probe remains documented as a local runtime blocker; the required target
uses the live CUDA tensor-scene entity path.

Latest local Omniverse extension UX evidence was refreshed on 2026-05-24 local
time with
`make live-omniverse-extension-ux ISAAC_SIM_COMMAND="$ISAAC_SIM_PYTHON"`.
The artifact `outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`
reported `status: "passed"` on the host-visible Isaac runtime with Isaac Sim
5.1.0 / Kit `107.3.3+production.229672.69cbf6ad.gl`, CUDA-visible
`NVIDIA GeForce RTX 4090`, extension-manager status `enabled`, enabled
extension id `isaac_audio_sensors.omni-1.0.0-rc.1`, real `omni.usd` stage and
selection updates, array/source authoring and discovery, `tdoa_synthetic`
start/update/stop, one valid `AudioSensorFrame` v1 JSONL record, 7 overlay
primitives, latest-frame/config JSON exports, Replicator writer
registration/write/flush/stop, and readable error checks.

## Non-Gates For V1 Package Release

- [x] SquadBot validation is not required before releasing the sensor package.
- [x] Alex validation is not required before releasing the sensor package.
- [x] ROS 2 and downstream adapters are optional project layers, not mandatory
  v1 package gates.
- [x] Real hardware benchmarks and sim-real calibration are outside v1 scope.
- [x] Complete L3/L4 fidelity, realistic materials, and realistic occlusion are
  outside v1 scope.

## Final Pre-Publish Checks

- [ ] Public hygiene grep returns no project-specific or private path leaks
  outside the allowed scope/non-promise docs.
- [ ] Acoustic fidelity ladder tests and docs links pass before release.
- [ ] `python -m isaac_audio_sensors --version` reports `1.0.0rc1` from the
  built wheel in a clean environment.
- [ ] `git ls-files` shows no tracked caches, generated outputs, local goals,
  virtual environments, build artifacts, or private environment files.
- [ ] Built archive audit passes after a fresh `make build`.
- [ ] README, docs, changelog, versioning, and roadmap agree on the current
  release status.
- [ ] Live Isaac Sim and Isaac Lab GPU evidence is fresh, or blockers are
  explicitly documented.
