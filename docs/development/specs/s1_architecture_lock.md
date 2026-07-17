# S1.1 architecture lock

## Status

**State:** Proposed — awaiting orchestrator/user approval recorded in the S1.1
closeout.

**Scope:** Stage 1 internal research release.

**Package release:** `1.8.0` after approval.

**Governing gate:** `S1.1` - Architecture lock.

Approval is prospective.  This ADR is the single Stage 1 record for the
packaging and architecture decisions below, but implementation must not begin
from it until approval is recorded in
`docs/development/closeouts/S1/s1_1_architecture_lock.md`.

## Context

Stage 1 must turn the maintained sensor source into immutable Linux artifacts
without changing the generic sensor boundary or weakening the frozen v1 frame
contract.  The current Kit entrypoint prepends a checkout-relative `../../src`
directory when it exists.  That is useful in a developer checkout, but it does
not prove which package source a distributed extension imports.  The current
distribution audit checks the wheel and source distribution, but it does not
build or audit a self-contained Kit archive or an acoustic pack.

The release is an internal research release.  It is not a GitHub release and
is not published to PyPI or the Kit Community Registry.  It does not make the
Stage 3 public-release, Windows, cross-platform, production-support, or public
supply-chain claims.  The existing public promises in `docs/v1_scope.md` and
compatibility rules in `docs/versioning.md` remain authoritative.

The selected S0.3/S1.1 host facts are frozen as evidence, not generalized into
a portability claim.  The evidence is already recorded at:

- `outputs/isaac_audio_sensors/S1/S1.1/isaac_python_version.txt`;
- `outputs/isaac_audio_sensors/S1/S1.1/isaac_numpy_probe.txt`; and
- `outputs/isaac_audio_sensors/S1/S1.1/environment.txt`.

All scripts, tests, APIs, archives, manifests, and closeouts assigned below to
S1.2-S1.8 are future enforcement work.  This ADR locks their required behavior
and ownership; it does not claim that those enforcement artifacts exist yet.
The existing `scripts/audit_distribution.py` is the one exception and is the
current wheel/source-distribution audit baseline.

## Decision 1: Stage 1 packaging form

Stage 1 produces the following internal artifacts:

1. one pure-Python wheel named
   `isaac_audio_sensors-<ver>-py3-none-any.whl` and the corresponding source
   distribution `isaac_audio_sensors-<ver>.tar.gz`, audited by the existing
   `scripts/audit_distribution.py`;
2. one self-contained Kit extension archive named
   `isaac_audio_sensors.omni-<ver>.zip`, built by the new
   `scripts/build_kit_extension.py` that lands in S1.4; and
3. exactly one Linux acoustic pack archive named
   `isaac_audio_sensors_acoustic_pack-l2l3-<ver>-linux_x86_64-cp312.tar.gz`,
   which lands in S1.5.

Every release artifact has a SHA-256 entry in `dist/SHA256SUMS`.  The artifact
set is immutable after acceptance: changing archive bytes requires rebuilding,
rehashing, and rerunning the affected gates.  Stage 1 does not publish these
artifacts to PyPI or the Kit Community Registry.

This split gives ordinary Python consumers a conventional wheel and sdist,
gives Kit a self-contained install unit, and isolates optional compiled
acoustics dependencies from the import-safe base.  S1.4 owns the future Kit
builder and its archive audit.  S1.5 owns production of the candidate
wheel/sdist, Kit zip, single acoustic pack, and `dist/SHA256SUMS`, including
the existing distribution audit.

## Decision 2: Supported reference runtime

Stage 1 supports one frozen reference host:

- Isaac Sim `6.0.1-rc.7+release.42383.32955d8d.gl`, installed at
  `/home/pacquadr/isaacsim`;
- Kit Python `3.12.13` with the `cp312` ABI and bundled NumPy `2.5.0`;
- Isaac Lab `3.0.0`;
- Ubuntu `24.04` with glibc `2.39` on `x86_64`; and
- an NVIDIA RTX 4090 host.

Windows and older Isaac Sim or Isaac Lab major versions are explicitly outside
Stage 1 scope.  The single-host lock makes the binary pack and clean-install
claim reproducible without implying broader compatibility.  S1.6 must enforce
the lock by recording runtime, ABI, NumPy, operating-system, architecture, and
GPU identity before exercising the exact artifacts.  A different runtime is
unsupported Stage 1 evidence, not an inferred pass or silent fallback.

## Decision 3: Contract compatibility and runtime semantics

`ias.audio_sensor_frame.v1` remains frozen in fields and meaning.  Compatible
changes are limited to additive optional fields or diagnostics that older v1
readers may ignore, as specified by `docs/versioning.md`.  Removing, renaming,
or changing existing field semantics requires a new contract version.

S1.2 introduces two independent contracts:

- `ias.audio_dataset_manifest.v1`; and
- `ias.audio_calibration_profile.v1`.

Their schema versions are independent of the Python package version.  A
package release such as `1.8.0` therefore does not rename any `v1` contract,
and a future schema-version change does not follow automatically from a
package bump.

S1.2 also makes `training_features` and `waveform_fidelity` the complete
configuration-validated runtime-profile vocabulary for Stage 1.  Unknown
profiles fail closed before partial use.  Stage 1 freezes these contracts and
fail-closed semantics only; the batched fast-path optimization and its formal
performance gate belong to P1.

This preserves existing frame consumers while allowing dataset, calibration,
and configuration responsibilities to evolve independently.  S1.2 owns the
new schemas, serializers, validators, and valid/invalid fixtures.  S1.7 owns
the compatibility matrix, old frame/config fixture runs, public-name freeze,
and proof that additive readers and old readers retain their documented
behavior.

## Decision 4: Generic contract ownership

This repository owns only generic sensor exports:

- sensor frames;
- dataset manifests;
- calibration profiles;
- plugin protocols; and
- capability reports.

These exports may describe sensor observations, provenance, calibration,
plugin requirements, and available capabilities.  They must not contain
downstream ontology, robot intent, behavior, transport-specific, or graph
policy fields.  This follows the four-layer architecture in which transport,
ontology, world models, perception fusion, and robot behavior are external
adapters.

Keeping exports generic preserves reuse and prevents an installed sensor
artifact from acquiring a downstream repository as an import or installation
dependency.  S1.2 owns generic frame/manifest/profile contracts, S1.3 owns
generic plugin protocols and capability declarations, and S1.8 must inspect
the installed-artifact consumer results to prove that no downstream ontology
or behavior field entered a generic export.

## Decision 5: Separate-repository responsibilities

Protobuf transport, `AuditoryCue`, ontology, `MiniSceneGraph`, and robot
behavior remain owned by
`/home/pacquadr/Desktop/squadbot-av-phase1`.  Sensor work never modifies that
repository.  The only Stage 1 cross-repository activity is read-only
consumption of immutable installed sensor artifacts and adapter fixtures.

This boundary lets sensor defects be distinguished from adapter or behavior
defects and prevents sibling-source coupling.  S1.8 owns the installed-artifact
consumer gate and must record before/after Git status evidence proving that the
consumer repository was not modified.  It must also prove that imports resolve
from installed artifacts rather than either repository's sibling source path.
Unavailable consumer access or runtime support is a cross-repository blocker,
not permission to edit the consumer or declare a pass.

## Decision 6: Base and acoustic-pack boundary

The base consists of the wheel and self-contained Kit archive.  It is pure
Python, requires only NumPy, and is fully functional for L0 `geometry_only`
and L1 `tdoa_synthetic`.  Material-aware ray/transmission occlusion, the
existing L3-partial capability, is pure Python and stays in the base.  Keeping
it in the base does not promote it to the complete L3/L4 or
realistic-material-acoustics promise excluded by `docs/v1_scope.md`.

Only waveform-dependent L2/L3 features that require `pyroomacoustics`, SciPy,
or SoundFile move behind the acoustic pack.  The pack is an offline wheelhouse
containing:

- pinned `cp312` manylinux wheels;
- hash-locked `packs/acoustics/requirements.lock`;
- `pack_manifest.json` with compatibility, wheel, capability,
  `host_requirements`, and `pack_distributions` declarations; and
- an offline, hash-verifying `install_pack.py` that performs no network access.

The manifest splits dependencies into two explicitly named categories:

- `host_requirements` are owned by the host runtime.  They include, at
  minimum, Kit-owned `numpy==2.5.0`.  The activation gate validates each
  requirement's exact version and import origin: `module.__file__` must resolve
  to the host runtime, such as Kit's bundled site-packages.  The pack never
  installs, vendors, or shadows a host requirement, and the pack root must not
  contain any distribution listed in `host_requirements`.
- `pack_distributions` are dependencies that, once the pack is active, must
  resolve exclusively from the validated private pack root.  They include
  `pyroomacoustics`, SciPy, SoundFile, and all of their locked transitive
  dependencies.

The pack must never install into Isaac's global site-packages or any user site.
The offline installer is the only component permitted to populate the private,
versioned sensor-project root:

```text
${XDG_DATA_HOME:-~/.local/share}/isaac_audio_sensors/packs/<pack_id>/<pack_version>/
```

The installer invokes `pip install --target` with `--no-deps --no-index
--require-hashes` and `--find-links` pointing only to the pack's `wheels/`
directory.  It installs every locked wheel explicitly.  The lock file
enumerates every wheel individually so pip cannot transitively install NumPy
or any other undeclared dependency.

Installation is atomic.  The installer creates a temporary staging directory
beside the final location and installs into that staging tree.  It validates
all wheel hashes, the manifest, and a post-install import self-check inside the
staging tree before atomically renaming staging to the immutable final
`<pack_id>/<pack_version>/` directory.  Once created, a version directory is
immutable, and the installer refuses to overwrite it; installing a distinct
version or explicitly removing the existing version is required.  An
interrupted or failed installation leaves only its staging directory, which is
never selectable for activation.  Multiple final pack versions may coexist.
Deactivation is deselecting or explicitly removing a versioned directory, and
rollback is selecting the previous versioned directory.  A pack has no shared
mutable state outside its versioned root.

Before importing any pack code, the capability layer must explicitly select a
completed immutable pack root and validate its `pack_manifest.json`.  Staging
directories and any directory without a valid manifest are not candidates for
selection.  The manifest identifies, and the activation gate validates:

- the exact sensor package version for which the pack was built;
- the exact Kit Python version and ABI, including the locked `cp312` ABI;
- operating system and architecture;
- every dependency declared in `host_requirements`, including Kit-owned
  `numpy==2.5.0`, for its exact version, host-runtime import origin, and
  absence from the selected private pack root;
- every dependency declared in `pack_distributions` for its exact version and
  exclusive presence under the selected private pack root;
- every wheel's SHA-256;
- the declared capabilities.

Every mismatch is rejected before any pack import, with no partial
application.  A partial, hash-mismatched, or manifest-invalid directory is
reported unavailable with an actionable message; it must never be selected or
partially imported.  Before placing the selected pack root on `sys.path`, the
activation gate inspects already imported modules in `sys.modules`.  If any
`pack_distributions` module is already loaded from outside the selected pack
root, activation fails closed with an actionable provenance-conflict report.
Mixed dependency provenance, including a mixture of pack-root and global,
user-site, or other origins, is never allowed.

After validation and the `sys.modules` provenance-purity check, activation
places the selected pack root on `sys.path` without shadowing any
`host_requirements`.  Pack-managed distributions then resolve exclusively
from the selected root, while base and Kit paths are otherwise untouched.

In packaged mode, a capability is pack-provided only when all of its modules
resolve from the active, manifest-validated private pack root.  Acoustic
dependencies discovered in Isaac's global site-packages or a user site are a
distinct `external/unmanaged` origin and can never masquerade as the released
pack in packaged evidence.  Developer/wheel mode retains the documented
external extras, including `pip install .[room]`.  Every packaged evidence run
records the import origin from `module.__file__` for every acoustic dependency.

The pack pins this official PyPI wheel:

```text
pyroomacoustics-0.10.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
```

Its SHA-256 is
`c1b1077cfcafed9775d1b826dbbaf25fb4090aa95d21e9bc6dac795f88e8875c`.
It was verified against PyPI on 2026-07-16, and the reference host's glibc
`2.39` satisfies `manylinux_2_28`; the probe is recorded at
`outputs/isaac_audio_sensors/S1/S1.1/`
`pyroomacoustics_official_wheel_probe.txt`.  SciPy, SoundFile, and transitive
dependencies are likewise official PyPI wheels, hash-locked in
`packs/acoustics/requirements.lock`; their exact pins land in S1.5.  If the
official wheel becomes unavailable or incompatible, the only substitute path
is a separate reviewed ADR amendment approved before any substitute enters the
pack.

Installing and activating the pack are explicit artifact actions.  Packaged
base startup requires no `pip` step of any kind.  Pack absence or removal must
leave L0/L1 and material-aware ray/transmission functionality healthy and must
produce actionable capability messages through the capability-discovery API
that lands in S1.5.  Missing pack capabilities must never become partial or
silent behavior.

The boundary keeps the common path import-safe and installable while making
the optional binary dependency set explicit and reproducible offline.  S1.5
owns the future lock file, manifest, installer, capability-discovery API,
archive-content checks, and pack-present/pack-absent tests.  Its required
future coverage also includes:

- base import followed by successful pack activation while NumPy remains
  Kit-owned, origin-validated as a `host_requirements` entry, and never
  shadowed;
- a conflicting pack-managed dependency preloaded from outside the pack root
  causing activation to fail closed; and
- an interrupted or partial installation, including staging left behind, a
  missing manifest, or a hash mismatch, never being selectable for activation.

S1.6 owns proof that the base starts without dependency installation and that
explicit, validated pack activation enables only the declared capabilities.

## Decision 7: Single authoritative package version

`pyproject.toml` `[project].version` is the one authoritative package-version
source.  Every other current-release surface is derived from that authority:

- `src/isaac_audio_sensors/__init__.py` `__version__`;
- `exts/isaac_audio_sensors.omni/config/extension.toml`;
- `scripts/audit_distribution.py` `PACKAGE_VERSION` and its expected artifact
  names;
- `Makefile` `EXPECTED_VERSION`;
- the current-release statements and pinned install example in `README.md`;
- the `CITATION.cff` `version` field;
- the current package- and extension-version statements in
  `docs/versioning.md`;
- the top release heading in `CHANGELOG.md` and
  `exts/isaac_audio_sensors.omni/docs/CHANGELOG.md`;
- built wheel, source-distribution, Kit-zip, and acoustic-pack names; and
- version-asserting tests.

The `scripts/check_version_sync.py` synchronization gate lands in S1.4.  It
must derive the expected value from `pyproject.toml`, verify every listed
current-release surface against it, and fail the build on any disagreement.
Historical version references, including older changelog entries, dated
closeouts, and past evidence, remain unchanged; the gate checks current-release
surfaces only.

S1 work uses package version `1.8.0`, a minor bump for additive contracts.  The
`1.8.0` bump commit updates the authority and all derived surfaces together
immediately after this ADR is approved; this ADR does not perform or claim that
bump.  Contract schema versions remain `v1` and never track the package
version.

## Decision 8: Canonical source and anti-drift proof

There is exactly one maintained Python package source:
`src/isaac_audio_sensors/`.  The wheel packages this tree directly.  At build
time, the Kit builder copies it byte for byte into
`<archive>/_vendor/isaac_audio_sensors/` and writes
`<archive>/_vendor/VENDORED.json`.  This packaged-mode metadata records
`mode=packaged`, the extension version, source Git revision, and SHA-256 tree
hash.  The source checkout carries a separate, tracked developer-mode
sentinel.  The builder excludes that developer sentinel from the archive.

The extension entrypoint loader is rewritten in S1.4 with two exclusive modes:

1. valid packaged-mode metadata: import only from `_vendor`, assert that the
   package and extension versions are equal, never fall back to checkout or
   installed-package paths, and fail loudly if the metadata or vendored tree
   is broken; or
2. a valid tracked developer-mode sentinel: try a plain package import first,
   then use the existing `../../src` fallback so source-checkout development
   remains supported.

The loader requires exactly one valid mode sentinel.  A missing mode sentinel,
or corrupt, ambiguous, or inconsistent packaged metadata, fails startup loudly
and must never fall back to an installed wheel or a checkout.  S1.4 lands
`scripts/build_kit_extension.py`, `scripts/audit_kit_archive.py`, the loader
rewrite, and `tests/test_kit_extension_package.py`.  The archive audit must
re-hash the vendored tree against `src/isaac_audio_sensors` at build time.  The
test must prove that packaged startup cannot reference repository `src/`.  Its
negative cases must also prove that a packaged extension with missing or
corrupt metadata refuses to start even when a conflicting
`isaac_audio_sensors` wheel is installed globally in the same interpreter.
Together, the one-source rule, byte-for-byte vendoring, version assertion,
explicit sentinels, provenance metadata, re-hash, and isolated-startup tests
are the anti-drift proof.

## Decision 9: Binary and platform boundary

The base artifacts contain only pure Python.  The wheel tag is
`py3-none-any`, and the self-contained Kit archive contains no compiled
extension.  Compiled code exists only inside the acoustic pack, whose boundary
is `cp312`, manylinux/Linux, and `linux_x86_64`.  All binary dependencies are
the official, hash-locked PyPI wheels required by Decision 6 and remain
confined to that Python, operating-system, and architecture boundary.

Any dependency or feature requiring another Python ABI, wheel tag, operating
system, or architecture is outside Stage 1 scope.  It must be reported as
unsupported rather than downloaded, compiled at startup, or silently selected.
S1.5 owns archive scans and manifest/capability checks that prove base archives
contain no binaries and pack contents match the declared ABI and platform.

## Decision 10: S1.6 clean-install definition

On the reference host, a "clean Isaac Sim 6.x environment" means all of the
following:

1. the exact hashed Kit zip is extracted into a fresh temporary extension
   folder below
   `outputs/isaac_audio_sensors/S1/S1.6/clean_env/extsUser/` and enabled only
   with Kit CLI `--ext-folder` and `--enable` flags; the real `extsUser` and
   `user.config.json` are never mutated;
2. a recorded preflight decontamination inventory proves there is no
   pip-installed `isaac_audio_sensors` in Isaac Python, no leftover extension
   symlink or copy, and no autoload entry; S0 tooling side effects are backed up
   and neutralized with before/after evidence;
3. Kit runs from a neutral current working directory with
   `PYTHONNOUSERSITE=1`; `PYTHONPATH`, `PYTHONHOME`, and all `PIP_*`
   environment variables are sanitized, with their effective state recorded;
4. every probed interpreter records that `site.ENABLE_USER_SITE` is disabled;
5. every scenario records `module.__file__` origins for
   `isaac_audio_sensors`, `numpy`, `scipy`, `soundfile`, and
   `pyroomacoustics`, with each module recorded as present at its resolved
   origin or explicitly absent; and
6. a separate fresh temporary virtual environment proves the wheel side from
   the exact hashed wheel under the same environment and provenance rules.

The deliberate wheel or extension artifact installation is part of the gate;
no package/dependency installation step is permitted during packaged base
startup.  A full operating-system-level Isaac Sim reinstall is explicitly not
required.  The preflight inventory and before/after records are the honesty
record that makes the narrower clean-environment claim reviewable.

This definition avoids destructive changes to the reference installation
while excluding checkout paths and common S0 contamination.  S1.6 owns the
future preflight inventory, temporary directories, CLI invocations, import
provenance and user-site verification, lifecycle results, wheel-venv results,
artifact hashes, and before/after restoration evidence.

## Consequences

- Stage 1 has one reproducible artifact topology and one supported Linux host;
  other platforms and older majors cannot be inferred from its evidence.
- Base users retain healthy L0/L1 and pure-Python material-aware occlusion
  without accepting optional compiled acoustics dependencies.
- High-fidelity waveform users perform a deliberate, offline, hash-verified,
  atomic installation into a private immutable versioned root and accept the
  pack's narrow `cp312` Linux/x86_64 boundary.  Coexisting immutable roots make
  rollback a selection change without mutating Isaac or user site-packages;
  incomplete staging trees are never activation candidates.
- Pack dependencies have two explicit categories: exact-version,
  origin-validated `host_requirements` remain host-owned and unshadowed, while
  `pack_distributions` resolve exclusively from the validated private root.
  Activation is manifest-validated and fails closed on mismatches, preloaded
  provenance conflicts, or any mixed dependency provenance.
- The wheel and Kit extension cannot evolve as separately maintained package
  copies.  Explicit packaged/developer sentinels prevent a broken packaged
  extension from borrowing a checkout or globally installed wheel.
- One authoritative version in `pyproject.toml` drives every current-release
  surface; historical records remain immutable while current drift fails the
  build.
- Frame v1 and the new v1 schemas evolve independently of SemVer package
  releases, preserving old consumers while allowing additive contracts.
- The sensor remains reusable and generic.  The downstream repository owns
  protobuf, ontology, graph, and robot behavior and is consumed read-only.
- Acoustic binary inputs are official, hash-locked PyPI wheels.  Replacing the
  pinned official `pyroomacoustics` wheel requires a separately approved ADR
  amendment.
- S1.6 evidence disables user-site imports, sanitizes Python and pip
  environment variables, and records required module origins or absence in
  every scenario.
- Approval of this ADR authorizes the locked implementation sequence but does
  not itself prove any S1.2-S1.8 enforcement gate.

## Enforcement map

Except for the current `scripts/audit_distribution.py` and the recorded S1.1
runtime evidence, every artifact named here is prospective and lands in its
listed subphase.

1. **Stage 1 packaging form** → the future
   `scripts/build_kit_extension.py`, the current wheel/sdist audit, and future
   artifact-name, archive-count, and `dist/SHA256SUMS` checks → S1.4 owns the
   builder and S1.5 owns the artifacts.
2. **Supported reference runtime** → clean-install preflight and recorded
   runtime, ABI, operating-system, architecture, and GPU identity against the
   exact artifacts → S1.6.
3. **Contract compatibility and profiles** → future schema, serialization,
   configuration validation, valid/invalid fixtures, old frame/config fixture
   matrix, and public-name freeze → S1.2 and S1.7.
4. **Generic contract ownership** → future manifest/profile and
   plugin/capability contract checks plus installed-export inspection for
   forbidden downstream fields → S1.2, S1.3, and S1.8.
5. **Separate-repository responsibility** → installed-artifact adapter cases,
   sibling-path exclusion, and before/after consumer-repository Git status
   evidence → S1.8.
6. **Base/acoustic-pack boundary** → the future `host_requirements` /
   `pack_distributions` manifest split; private-versioned-root installer audit
   requiring `--no-deps --no-index --require-hashes`; pre-import manifest/hash
   validation and `sys.modules` provenance-purity checks; staging, atomic
   rename, and immutable-version tests; capability origin classification and
   `module.__file__` evidence; pack-present, pack-absent, and no-`pip` base
   startup checks; plus required scenarios for base import then activation
   with Kit-owned unshadowed NumPy, fail-closed activation with an externally
   preloaded pack-managed dependency, and rejection of interrupted or partial
   installations with staging left behind, a missing manifest, or a hash
   mismatch → S1.5 and S1.6.
7. **Single authoritative package version** → the future
   `scripts/check_version_sync.py` build gate deriving all current-release
   surfaces and artifact names from `pyproject.toml`, while excluding
   historical records → S1.4.
8. **Canonical source and anti-drift proof** → the future builder,
   `scripts/audit_kit_archive.py`, loader rewrite, explicit mode-sentinel and
   version/hash checks, and positive and conflicting-global-wheel negative
   cases in `tests/test_kit_extension_package.py` → S1.4.
9. **Binary/platform boundary** → future base binary scan and acoustic-pack
   ABI/platform/manifest audit, including the pinned official PyPI wheels and
   hashes → S1.5.
10. **Clean-install definition** → future decontamination inventory,
    neutral-cwd Kit CLI run, sanitized environment, disabled-user-site proof,
    required import-origin-or-absence records, and fresh wheel virtual
    environment → S1.6.

S1.7 additionally freezes the resulting compatible public surface.  S1.8 is
the final proof that the installed generic artifact crosses the external
adapter boundary without source-path or repository-ownership leakage.

## References

- `docs/development/specs/s0_squadbot_readiness_acceptance.md`, especially the
  authority rules and S1 gate table.
- `docs/final_sensor_development_plan.md`, Sections 4, 5, 6.4, and 10.
- `docs/development/closeouts/S0/s0_6_dual_acceptance_lock.md`.
- `docs/architecture.md`.
- `docs/versioning.md`.
- `docs/v1_scope.md`.
- `exts/isaac_audio_sensors.omni/isaac_audio_sensors_omni/__init__.py`.
- `scripts/audit_distribution.py`.
- `outputs/isaac_audio_sensors/S1/S1.1/isaac_python_version.txt`.
- `outputs/isaac_audio_sensors/S1/S1.1/isaac_numpy_probe.txt`.
- `outputs/isaac_audio_sensors/S1/S1.1/environment.txt`.
- `outputs/isaac_audio_sensors/S1/S1.1/`
  `pyroomacoustics_official_wheel_probe.txt`.
