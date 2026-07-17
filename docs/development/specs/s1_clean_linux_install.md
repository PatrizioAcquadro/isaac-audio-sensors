# S1.6 clean Linux install harness

## Scope

This harness implements the evidence runner for ADR Decision 10. It does not
execute during package import, install an acoustic pack, modify the maintained
sensor implementation, or claim that a live Isaac Sim run passed. The
orchestrator runs the scenarios on the frozen Isaac Sim 6.0.1 reference host.

The release wheel and self-contained Kit extension zip are selected only from
`dist/SHA256SUMS`. Both artifacts are rehashed before any host state is
neutralized. The wheel is rehashed a second time immediately before its venv
installation. A missing entry, duplicate expected filename, unsafe checksum
path, missing file, or digest mismatch fails closed.

## Scenario matrix

| Scenario | Fresh boundary | Command and required proof |
| --- | --- | --- |
| `headless` | Recreated `clean_env/extsUser/` containing only the exact Kit zip | Kit base app with `--no-window --ext-folder ... --enable isaac_audio_sensors.omni --exec ...`; the probe must pass, and `isaac_audio_sensors.__file__` plus the extension-manager path must resolve below the staged extension and `_vendor`. |
| `reinstall` | The complete `clean_env/` tree is removed and the exact zip is extracted again | The headless probe is repeated into `probe_reinstall.json`; the second extracted-tree inventory records update/reinstall identity. |
| `gui` | The complete `clean_env/` tree is removed and the exact zip is extracted again | The same Kit probe runs without `--no-window`; `gui_screenshot.png` must exist and exceed 10 KiB. |
| `wheel-venv` | A separate new `wheel_venv/` | The exact wheel is installed with `pip --no-cache-dir`; capabilities JSON, version `1.8.0`, `pip freeze`, disabled user site, in-venv package/NumPy origins, and explicit SciPy/SoundFile/pyroomacoustics absence are required. |

Every subprocess starts in the S1.6 output directory. The harness sets
`PYTHONNOUSERSITE=1`, removes `PYTHONPATH`, `PYTHONHOME`, and every `PIP_*`
variable, and records the exact variable names removed and values set. The Kit
probe additionally records `site.ENABLE_USER_SITE`, `sys.path`, the effective
sanitization facts, and present-origin or explicit-absence records for the ADR
module inventory. Scenario timeouts terminate the whole subprocess group and
are recorded as failures.

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
