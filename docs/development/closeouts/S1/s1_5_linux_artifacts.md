# S1.5 Linux artifacts closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.5` - Linux artifacts |
| Closeout date | 2026-07-17 |
| Entry revision | `024c13e` |
| Predecessor input | S1.2-S1.4 closeouts; ADR Decisions 1, 6, 9 |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.5 row |
| Design note | `docs/development/specs/s1_linux_artifacts.md` |
| Result | **Pass** |

## Scope

Produces the complete Stage 1 Linux artifact set and the capability layer:

- Acoustic pack toolchain: tracked declaration `packs/acoustics/pack.toml`
  and hash-locked `packs/acoustics/requirements.lock` (exactly five official
  PyPI wheels: pyroomacoustics 0.10.1 — the ADR-pinned hash —, scipy 1.18.0,
  soundfile 0.14.0, cffi 2.1.0, pycparser 3.0; cp312 / Linux x86_64);
  `scripts/build_acoustic_pack.py` (wheelhouse verification, manifest
  generation, deterministic tarball), `scripts/install_pack.py` (offline,
  `--no-deps --no-index --require-hashes`, staging + in-staging self-check +
  atomic rename to the immutable private versioned root, overwrite refusal),
  `scripts/audit_acoustic_pack.py` (member set, hashes, tags, private-path
  and token scans, manifest completeness, no-numpy-wheel rule).
- Activation layer `core/packs.py`: discovery (final dirs only; staging and
  partial dirs never selectable), fail-closed manifest validation (sensor
  version, python/abi/os/arch, pack distribution presence/versions,
  host-requirement exact version + host origin + absence from the root),
  `sys.modules` provenance-purity gate, once-per-process activation with
  pack-root path precedence and no host_requirements shadowing.
- Capability API `core/capabilities.py` + CLI `capabilities --json`: origins
  `base` / `pack:<id>@<ver>` / `external-unmanaged` / `absent`, actionable
  messages naming the exact pack artifact.
- Umbrella `make artifacts` (check-version -> build -> build-kit ->
  audit-kit -> build-pack -> audit-pack -> combined `dist/SHA256SUMS`).

## Finding resolved during S1.5

Running the REAL installer exposed that scipy 1.18.0 imports
`typing_extensions` at runtime on cp312 without declaring it (dev-only
extra upstream). Kit ships `typing_extensions` 4.12.2 via
`omni.kit.pip_archive` pip_prebundle, and Kit code may import it early, so
adding it to `pack_distributions` would trip the provenance-purity gate.
Resolution (within ADR Decision 6's open host-requirements category):
declared `typing_extensions==4.12.2` as a second host requirement —
validated by exact version (importlib.metadata first) and host origin,
never installed or shadowed; the five-wheel lock and the pyroomacoustics
pin are unchanged. The staging-absence guard now covers every declared
host requirement.

## Gate results (evidence: `outputs/isaac_audio_sensors/S1/S1.5/`)

| Gate | Result | Evidence |
| --- | --- | --- |
| `make test` | 479 passed, 67 skipped | `gate_test.log`, `gate_test_final.log` |
| `make lint` | clean | `gate_lint.log` |
| `make artifacts` (full chain + audits) | all OK | `gate_artifacts.log` |
| Frozen artifact hashes (wheel, sdist, Kit zip, pack) | recorded | `SHA256SUMS.txt` |
| Capability report, dev venv (no pack) | base healthy; L2 unavailable with exact pack-artifact guidance | `capabilities_dev_venv.json` |
| Capability report, bare temp venv (wheel only) | base healthy from installed wheel | `capabilities_bare_venv.json` |
| REAL pack install + activation (host-contract venv: numpy 2.5.0, typing_extensions 4.12.2) | staged/atomic install OK; overwrite refused; activation validated; pyroomacoustics from pack root; numpy host-owned; `RoomAcousticsBackend.is_available()` True; L2 origin `pack:acoustics-l2l3@1.8.0` | `real_pack_install_activation.txt` |

Acceptance mapping (S1.5 row): archives contain no caches, outputs, private
paths, sibling code, or undeclared dependencies (kit + pack + distribution
audits; the one undeclared upstream dependency found was resolved and
recorded); capability discovery is accurate (three environments verified);
removing/absent pack leaves the base healthy and reports missing
capabilities actionably (bare-venv and dev-venv reports; hermetic
pack-removal tests). The ADR's three required scenarios are covered in
`tests/test_capability_discovery.py` / `tests/test_acoustic_pack.py` and
were additionally proven against the real pack.

## Limitations and next input contract

- The frozen `SHA256SUMS.txt` set is the immutable input to S1.6; any
  artifact change requires rebuild + rehash + re-run of affected gates.
- Pack activation is once-per-process by design; "deactivation" is
  selection/removal before activation, not hot unload.
- L3/L4 remain honestly unavailable even with the pack (advanced realism is
  S3/P2 scope).
- Next subphase input (S1.6): exact SHA256SUMS artifacts, ADR Decision 10
  clean-install definition, S0.3 runtime facts.

## Post-review remediation (2026-07-17)

Wheel inspection now combines metadata with import-bearing contents,
including native `_cffi_backend`, and verifies every wheel `RECORD` hash and
size. Manifests carry sorted import ownership plus installed-file SHA-256
values. The auditor, offline installer, discovery, and activation paths all
reject incomplete inventories and tampering; activation also rejects
externally preloaded owned modules and rolls back path, modules, and active
state on failure.

The final real offline install and activation passed with installed-file
integrity verified and 8/8 declared imports originating under the private
pack root. Evidence:
`outputs/isaac_audio_sensors/S1/S1.5/post_review_pack_install.log` and
`post_review_pack_activation.log`. Final hashes are in `SHA256SUMS.txt`.

## Final provenance correction (2026-07-17)

The final pack was built from clean committed revision
`c7ead4dd017e3900f44d374ce30eb92d1a196df3`; its manifest records that full
revision and the auditor verifies the embedded installer and lock file against
the recorded commit. The resulting pack sha256 is
`349aad4c727359d9738c81ea12497e23dfe38ab897ba055fb43c095a51daf5c2`.
Offline installation, installed-file integrity, and activation passed with all
8 declared imports originating under the private pack root. Canonical evidence:
`outputs/isaac_audio_sensors/S1/S1.5/final_provenance_pack_activation.json`.
