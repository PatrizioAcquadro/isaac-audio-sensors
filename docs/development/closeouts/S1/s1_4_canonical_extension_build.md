# S1.4 canonical extension build closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.4` - Canonical extension build |
| Closeout date | 2026-07-17 |
| Entry revision | `efadee5` |
| Predecessor input | `docs/development/closeouts/S1/s1_1_architecture_lock.md` (Decisions 7, 8); S0.1 **Partial** distribution finding |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.4 row |
| Design note | `docs/development/specs/s1_canonical_extension_build.md` |
| Result | **Pass** |

## Scope

Removes the distributed checkout-relative import behavior and makes the Kit
extension build from the single maintained package source:

- Loader rewrite (`exts/.../isaac_audio_sensors_omni/__init__.py`): explicit
  fail-closed mode sentinels per ADR Decision 8. Packaged mode
  (`_vendor/VENDORED.json`, mode=packaged + version + source_revision +
  tree_sha256) imports only from `_vendor`, asserts import provenance under
  the vendor tree and version equality, and raises `RuntimeError` on
  missing/corrupt/ambiguous metadata — never falling back to an installed
  wheel or checkout. Developer mode (tracked
  `DEVELOPMENT_MODE.json`, excluded from archives) preserves plain-import
  then `../../src` fallback. Exactly one valid sentinel is required.
  `graph_node.py` contained no path shim.
- `scripts/build_kit_extension.py`: deterministic archive build (sorted
  entries, fixed timestamps) with byte-for-byte vendoring of
  `src/isaac_audio_sensors/`, provenance metadata, zip + `dist/kit/SHA256SUMS`.
- `scripts/audit_kit_archive.py`: required/forbidden entries, private-path
  and project-token scans (reusing distribution-audit rules), version gate,
  and the vendored-tree drift gate (archive hash vs metadata vs current
  `src/` tree).
- `scripts/check_version_sync.py`: `pyproject.toml [project].version` is the
  authority; all ADR Decision 7 derived surfaces verified; historical
  references excluded. Wired ahead of `make build`.
- `tests/test_kit_extension_package.py`: packaged startup from an extracted
  archive in a clean subprocess (no pip step, provenance under `_vendor`,
  repo `src/` not on `sys.path`); fail-loud negatives (missing vendored
  tree, corrupt metadata, ambiguous dual sentinels, corrupt metadata with a
  conflicting globally installed fake wheel — never imported); developer
  mode still resolves from `src/`; version-sync positive/negative;
  tamper-detection via tree hash.
- Make targets `build-kit`, `audit-kit`, `check-version`.

## Gate results (evidence: `outputs/isaac_audio_sensors/S1/S1.4/`)

| Gate | Result | Evidence |
| --- | --- | --- |
| `make test` | 455 passed, 67 skipped | `gate_test.log` |
| `make lint` | clean | `gate_lint.log` |
| `make check-version` | OK 1.8.0 | `gate_check_version.log` |
| `make build-kit` | OK (zip at revision efadee5, tree_sha256 28f8918b…) | `gate_build_kit.log` |
| `make audit-kit` | OK (96 files) | `gate_audit_kit.log` |
| `make build` + distribution audit | OK (sdist 268, wheel 95) | `gate_build_audit.log` |
| Rebuild determinism | byte-identical zip sha256 23b3a057… across rebuilds | `kit_rebuild_determinism.log` |
| Kit CLI flags probe (S1.6 prep) | `--ext-folder` / `--enable` confirmed on Isaac Sim 6.0.1 | `kit_cli_flags_probe.txt` |
| Developer-mode live smoke | `make live-omniverse-extension-ux` on `/home/pacquadr/isaacsim/python.sh`: status passed | `dev_mode_live_ux.json` |

Acceptance mapping (S1.4 row): source-checkout development still works
(developer-mode live smoke on real Kit + subprocess test); the packaged
extension is built from the maintained wheel source (byte-vendoring + drift
gate); `tests/test_kit_extension_package.py` fails if packaged startup
references repository `src/` or requires a manual package installation
(explicit negative assertions).

## Operational note

`make build` recreates `dist/` from scratch; the S1.5 umbrella `artifacts`
target must therefore sequence `build` before `build-kit`/`build-pack`.

## Limitations and next input contract

- Packaged startup is proven in clean Python subprocesses; the full packaged
  Kit runtime scenario belongs to S1.6 (clean install) by design.
- Next subphase input (S1.5): S1.2-S1.4 outputs, audited wheel/sdist
  baseline, ADR base/pack boundary (Decision 6) and binary boundary
  (Decision 9), Kit Python cp312 facts.
