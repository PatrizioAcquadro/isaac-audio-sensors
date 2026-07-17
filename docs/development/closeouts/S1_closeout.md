# S1 phase closeout — stable installable foundation

| Field | Recorded value |
| --- | --- |
| Phase | `S1` - Stable installable foundation |
| Closeout date | 2026-07-17 |
| Entry revision | `74a4ed6` (S0 closeout) |
| Closing revision | `9deeccb` (this closeout commit changes only sdist-excluded `docs/development/`) |
| Package version | `1.8.0` (bumped from 1.7.0 at S1.1 approval; pyproject is the single authority) |
| Governing spec | `docs/development/specs/s0_squadbot_readiness_acceptance.md` §S1 |
| Result | **Pass — S1 exit gate met** |

## Subphase record

| Subphase | Closeout | Result | Commit |
| --- | --- | --- | --- |
| S1.1 architecture lock (user-approved ADR, 3 review rounds) | `S1/s1_1_architecture_lock.md` | Pass | `8d64a13` (+ bump `8ef3d89`, prep `1534ce8`) |
| S1.2 Stage 1 public contracts | `S1/s1_2_public_contracts.md` | Pass | `a23a395` |
| S1.3 plugin contracts | `S1/s1_3_plugin_contracts.md` | Pass | `efadee5` |
| S1.4 canonical extension build | `S1/s1_4_canonical_extension_build.md` | Pass | `024c13e` |
| S1.5 Linux artifacts + capability discovery | `S1/s1_5_linux_artifacts.md` | Pass | `062d7b4` |
| S1.6 clean Linux install (live) | `S1/s1_6_clean_linux_install.md` | Pass | `5a730ee` |
| S1.7 compatibility freeze | `S1/s1_7_compatibility_freeze.md` | Pass | `ebc4b75` |
| S1.8 installed-artifact consumer gate | `S1/s1_8_installed_consumer_gate.md` | Pass | `9deeccb` |

## Immutable S1 artifact set (built at `9deeccb`)

Recorded at `outputs/isaac_audio_sensors/S1/SHA256SUMS_final.txt`:

| Artifact | sha256 |
| --- | --- |
| `isaac_audio_sensors-1.8.0-py3-none-any.whl` | `a9bc40e306e1087fa7a48a8fde3ed30c6cd66a3f4e3b88995a60c2b23866107a` |
| `isaac_audio_sensors-1.8.0.tar.gz` | `6d5221bd7b8274d19babfff7b840f7d34f84ffde90db10aee3fca41c112a9dcc` |
| `kit/isaac_audio_sensors.omni-1.8.0.zip` | `36a7aac790ef8bb2f96b4644f171328b1d9cba63e8f0c4fc84b64d9028140683` |
| `packs/isaac_audio_sensors_acoustic_pack-l2l3-1.8.0-linux_x86_64-cp312.tar.gz` | `64b076bf2208bbd19c3e861cdc4c25493d3780764232847a7787bc58fd8b6e5c` |

Reproduction: `make artifacts WHEELHOUSE=<dir with the five locked wheels>`
at `9deeccb` (deterministic builds; Kit zip and pack tarball are
byte-stable; wheel/sdist follow setuptools reproducibility).

## Exit-gate statement (§6.4 + spec §S1)

- **Immutable Linux artifacts install cleanly**: final-set re-verification
  at `9deeccb` — headless clean-install scenario passed (one Kit shutdown
  SIGABRT flake occurred after probe evidence completed and disappeared on
  rerun; recorded in `outputs/isaac_audio_sensors/S1/final_installed_gate_recheck.log`);
  full four-scenario evidence (headless, reinstall, GUI, wheel venv) in the
  S1.6 closeout.
- **Supported base and acoustic capabilities are discoverable**:
  `capabilities --json` verified in dev venv, bare wheel venv, and with a
  real activated pack (`pack:acoustics-l2l3@1.8.0` origin); pack absence
  leaves L0/L1 healthy with actionable messages.
- **Frame v1 remains compatible**: S1.7 hash-pinned corpus, byte-identical
  schema vs `74a4ed6`, enumerated-expansion round-trips, public-name
  freeze; one compatibility regression found (required `runtime_profile`
  kwarg) and repaired additively.
- **External adapter consumes installed artifacts with no sibling source
  path**: S1.8 — consumer suite 7/7 from the installed wheel, deterministic
  double-run graph export, clean generic-boundary scan, consumer repository
  byte-provably unmodified; re-verified against the final artifact set.

## Pure-gate state at close

`outputs/isaac_audio_sensors/S1/final_pure_battery.log`: 504 passed /
67 optional-dependency skips; ruff clean; version-sync OK 1.8.0. Test count
grew from 386 (S0 baseline) to 504.

## Known limitations carried forward

- L3/L4 remain honestly unavailable (advanced realism S3/P2; calibration
  S4). The pack unlocks waveform-dependent L2 only.
- `scipy 1.18.0` has an undeclared runtime dependency on
  `typing_extensions` (cp312); handled as a Kit-owned host requirement
  (`4.12.2`). Upstream quirk recorded in the S1.5 closeout.
- Kit shutdown can flake (Carbonite TaskGroup assertion) after evidence
  collection; scenario verdicts require the probe evidence, so the flake
  surfaces as a failed run to rerun, never as a silent pass.
- Pack activation is once-per-process; in-Kit pack activation is exercised
  in S5 flows.
- Isaac Lab InteractiveScene/RigidObject probe remains blocked from S0
  (PhysX CUDA); untouched by S1.

## Next phase input contract (S2)

S2.1 (session/shard layout) consumes: `ias.audio_dataset_manifest.v1`
(S1.2), the plugin/capability layer (S1.3/S1.5), the immutable artifact
set above, and the S1.7 freeze. The S2 evidence root is
`outputs/isaac_audio_sensors/S2/`.
