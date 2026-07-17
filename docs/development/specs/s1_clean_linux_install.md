# S1.6 clean Linux install harness

## Scope

This harness implements the evidence runner for ADR Decision 10. It does not
execute during package import, install an acoustic pack, modify the maintained
sensor implementation, or claim that a live Isaac Sim run passed. The
orchestrator runs the scenarios on the frozen Isaac Sim 6.0.1 reference host.

The wheel, sdist, self-contained Kit zip, and acoustic pack are selected only
from `dist/SHA256SUMS`; the mapping must contain exactly those four artifacts
and be byte-identical to the canonical `S1/SHA256SUMS_final.txt`. All four are
rehashed before host state is neutralized. Their canonical mapping produces a
common artifact-set identifier recorded by every scenario. The wheel is
rehashed again immediately before its venv installation.

## Scenario matrix

| Scenario | Fresh boundary | Command and required proof |
| --- | --- | --- |
| `headless` | Recreated `clean_env/extsUser/` containing only the exact Kit zip | Kit's embedded `kit/python/bin/python3 -I -S` bootstraps `SimulationApp` with only verified Kit-owned paths and the staged extension; the probe and packaged origins must pass. |
| `reinstall` | The complete `clean_env/` tree is removed and the exact zip is extracted again | The headless probe is repeated into `probe_reinstall.json`; the second extracted-tree inventory records update/reinstall identity. |
| `gui` | The complete `clean_env/` tree is removed and the exact zip is extracted again | The same Kit probe runs without `--no-window`; `gui_screenshot.png` must exist and exceed 10 KiB. |
| `wheel-venv` | A separate new `wheel_venv/` | The exact wheel is installed with `pip --no-cache-dir`; capabilities JSON, version `1.8.0`, `pip freeze`, disabled user site, in-venv package/NumPy origins, and explicit SciPy/SoundFile/pyroomacoustics absence are required. |

The canonical verdict requires all four scenarios, in one invocation, against
one artifact-set id. A partial diagnostic run writes a scenario-named partial
record and never overwrites `clean_install_gate.json`.

Every subprocess starts in the S1.6 output directory. The harness sets
`PYTHONNOUSERSITE=1`, removes `PYTHONPATH`, `PYTHONHOME`, and every `PIP_*`
variable, and records the exact variable names removed and values set. The Kit
probe additionally records `sys.executable`, `sys.prefix`,
`site.ENABLE_USER_SITE`, `sys.path`, editable import hooks, the effective
sanitization facts, and present-origin or explicit-absence records for the ADR
module inventory. Executable and prefix must be under the Isaac root. Every
path must be under that root or the output-local clean tree; repository,
virtualenv, discovered sibling Git checkout, and editable-hook contamination
fails closed. Scenario timeouts terminate the whole subprocess group.

## Preflight and restore state machine

```text
artifact hashes verified
        |
        v
inventory before state
        |
        +-- move matching real extsUser entries to evidence backup
        +-- copy and JSON-scrub matching user.config.json files
        +-- require Isaac python import failure
        |
        v
inventory clean after state -> stage/run scenarios
        |
        v
finally: restore moved entries and copy original configs back
        |
        +-- restore success -> verdict may pass
        +-- restore failure -> verdict fails with exact errors
```

The preflight operation does not install the release extension into the real
Isaac `extsUser` or create a persistent autoload setting. Known prior
developer-tooling contamination is temporarily moved or scrubbed only after a
backup is created. Original configuration bytes are restored from the backup
in `finally`, including after a scenario or preflight import failure. A new
entry appearing at an original extension path is never overwritten during
restore. `--skip-restore` is an explicit operator override and is recorded;
normal Make targets never use it, and a skipped restore cannot produce a
passing overall verdict.

## Evidence inventory

| File | Contents |
| --- | --- |
| `clean_install_gate.json` | Overall timestamps and verdict, requested scenario records, exact artifact hashes, staging inventory hashes, commands, sanitized-environment deltas, timeouts, logs, and restore summary. |
| `preflight_inventory.json` | Before/after/after-restore extension and user-config inventories, backup paths, exact removed JSON paths, and the Isaac-Python absence probe. |
| `preflight_backup/` | Moved extension entries and byte-preserving copies of each modified `user.config.json`. |
| `probe_headless.json`, `probe_reinstall.json`, `probe_gui.json` | Kit interpreter/environment facts, module origins or absence, extension-manager state, guarded public-API exercise results, capability report, and disable/re-enable lifecycle proof. |
| `latest_frame.json`, `config_summary.json` | Probe exports produced through the extension controller public API. |
| `gui_screenshot.png` | Required non-trivial viewport/application image for the GUI scenario. |
| `wheel_venv_pip_freeze.txt` | Installed distribution inventory from the isolated wheel scenario. |
| `*.log` | Combined stdout/stderr for every preflight and scenario subprocess. |

By default the temporary extension tree and venv are removed after validation;
`--keep-clean-env` retains them for diagnosis. Their deterministic tree hash,
commands, import origins, and logs remain in the gate evidence either way.
