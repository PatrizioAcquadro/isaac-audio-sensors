# S1.6 clean Linux install closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S1.6` - Clean Linux install |
| Closeout date | 2026-07-17 |
| Entry revision | `062d7b4` |
| Predecessor input | S1.5 frozen artifacts (`outputs/isaac_audio_sensors/S1/S1.5/SHA256SUMS.txt`); ADR Decision 10 |
| Governing gate | `docs/development/specs/s0_squadbot_readiness_acceptance.md`, S1.6 row |
| Design note | `docs/development/specs/s1_clean_linux_install.md` |
| Runtime | Isaac Sim 6.0.1-rc.7 at `/home/pacquadr/isaacsim`, Kit Python 3.12.13, app `isaacsim.exp.base.kit`, RTX 4090 host |
| Result | **Pass** |

## Scope

Executes the ADR Decision 10 clean-install definition against the exact
hashed 1.8.0 artifacts using the new harness
(`scripts/live_clean_install_gate.py` + in-Kit
`scripts/live_clean_install_probe.py`, Make targets `live-clean-install`,
`live-clean-install-gui`; pure logic tests in
`tests/test_clean_install_harness.py`).

## Scenario results (consolidated single run; evidence: `outputs/isaac_audio_sensors/S1/S1.6/`)

| Scenario | Result | Key evidence |
| --- | --- | --- |
| Preflight decontamination | neutralized + restored | `preflight_inventory.json` (before/after/after-restore): S0 `extsUser` symlink moved to backup and restored; autoload entry stripped from `Isaac-Sim Full/6.0/user.config.json` and restored; Isaac python import probe: absent |
| Headless install/capture/export | passed | `probe_headless.json`: `isaac_audio_sensors.__file__` under `clean_env/extsUser/isaac_audio_sensors.omni-1.8.0/_vendor/`, version 1.8.0; stage + author + configure + frame capture + `latest_frame.json` + `config_summary.json` + capability report; extension disable/re-enable retained `_vendor` provenance |
| Reinstall/update (wipe + re-extract + rerun) | passed | `probe_reinstall.json` |
| GUI | passed | `gui_screenshot.png` (162 KB) |
| Wheel temp venv | passed | `wheel_venv_provenance.log`: package + numpy resolved inside the venv, `site.ENABLE_USER_SITE` false, scipy/soundfile/pyroomacoustics explicitly absent; `--version` 1.8.0; `wheel_venv_pip_freeze.txt` |
| Aggregate verdict | `clean_install_gate.json` status **passed** (all four scenarios in one invocation) | |

Environment rules enforced and recorded per scenario: `PYTHONNOUSERSITE=1`;
`PYTHONPATH`/`PYTHONHOME`/`PIP_*` sanitized; neutral cwd; artifact hashes
re-verified against `dist/SHA256SUMS` before staging/install; zero pip steps
for packaged base startup; extension enabled only via Kit CLI
`--ext-folder`/`--enable`.

## Harness defects found and fixed during live execution

Three integration defects were exposed by the real runs and fixed by the
orchestrator (each is exactly the class of defect this gate exists to catch):

1. `python.sh` wrapper noise after the probe's JSON line broke log parsing
   (misreported contamination) — parser now reads the first JSON line.
2. The Kit zip stores extension content at the archive root; staging now
   creates the `isaac_audio_sensors.omni-1.8.0` id-version folder itself and
   requires `config/extension.toml` + `_vendor/VENDORED.json` inside it.
3. The wheel-venv "not from the repository checkout" guard flagged the venv
   itself (it lives under `outputs/` inside the repo); the guard now
   excludes the venv root while still rejecting checkout `src/` origins.

Full pure battery re-run after the fixes: 489 passed, 67 skipped; lint clean.

## Acceptance mapping (S1.6 row)

Exact wheel/archive artifacts installed into a clean Isaac Sim 6.x
environment (hash-verified staging; preflight decontamination evidence);
every scenario passed without checkout imports (provenance recorded in every
scenario) or a manual pip step (packaged startup performed none; wheel-venv
install is the deliberate artifact installation the gate performs); imports
resolve only from installed artifacts (`_vendor` / venv site-packages).

## Limitations and next input contract

- The gate validates the base artifact in Kit; pack activation inside Kit is
  exercised in S1.8/S5 flows (S1.5 proved real pack activation against the
  host-contract venv).
- Restoration returned the developer symlink and autoload entry; the
  machine is in its pre-gate state.
- Next subphase input (S1.7): S1.2/S1.3 contracts, these installed-artifact
  results, `docs/v1_scope.md`, `docs/versioning.md`.

## Post-review remediation (2026-07-17)

The canonical gate now runs headless, reinstall, GUI, and wheel-venv in one
invocation. Kit is launched through embedded `kit/python/bin/python3 -I -S`;
only verified Kit-owned paths and the staged output-local extension are
admitted. Executable and prefixes must remain under the Isaac root, and the
gate rejects repository, virtualenv, discovered sibling-checkout, and
editable-hook contamination. Planted contamination regressions passed
14/14.

Final canonical result: all four scenarios passed against artifact-set id
`4f58b62c3cd84c321a400ce42231a7854d33f47ad4dc64ac711624e44326a9f4`
(headless 7.778 s, reinstall 7.495 s, GUI 7.571 s, wheel-venv 3.662 s).
`SHA256SUMS_final.txt` matched `dist/SHA256SUMS`; user state restoration and
output-local cleanup both passed. Canonical evidence:
`outputs/isaac_audio_sensors/S1/S1.6/clean_install_gate.json`.
