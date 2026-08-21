# Phase R6 — Packaging and Release

## Objective

Reduce local packaging and release workflows to the approved GitHub source, Python wheel, and NVIDIA Kit archive model without mixing temporary validation data or maintainer-only state into the product.

## Subphase R6.0 — Release Model

#### Implementation

The release model is locked to the public GitHub repository, one universal Python wheel, and one platform-compatible Kit extension zip. R6.0 records the decision; later subphases implement it.

#### Key Decisions

There is no target source archive, separate acoustics pack, checksum artifact, automated publication, tag, or push. Current source and pack commands remain operational until their assigned later R6 subphases remove them.

#### Problems / Limitations

None. The model is decision-complete but not fully implemented by R6.1.

## Subphase R6.1 — Root and Local Workspace Cleanup

#### Implementation

Essential contribution, private security-reporting, data-handling, and safety limitations now live in `README.md`. Separate citation, conduct, contribution, and security policy files were removed, and `CHANGELOG.md` retains one concise entry per release.

Automatic smoke, diagnostic, and default Kit output now belongs under temporary `build/validation/isaac_audio_sensors/`. The old root output and run surfaces are no longer ignored or supported. `make clean` removes only regenerable build, distribution, cache, coverage, Python metadata, and validation files.

The removed citation surface also left version synchronization and the temporary source manifest. The archive content policy still rejects an `outputs` member because that gate prevents the retired surface from re-entering a distribution.

#### Key Decisions

`ISAAC_AUDIO_SENSORS_OUTPUT_ROOT` and explicit absolute Kit paths remain supported. The compatibility-only legacy output-prefix stripper and its dedicated assertion were removed.

`evidence/`, `AGENTS.md`, `TODO.md`, `.venv/`, and local assistant state are outside `make clean`. The authorized specification under `knowledge/raw/` remains byte-identical. No Python API, CLI, schema, sensor, recording, backend, or release-model behavior changed.

#### Problems / Limitations

Host tests, version synchronization, Ruff, and current wheel/source and Kit archive audits pass. The RTX 4090 confirms that generated diagnostics use only `build/validation/`.

The R6.1 run exposed two semantic blockers outside its cleanup diff. A subsequent reconciliation preserves static room configuration during live capture and aligns the Kit smoke with the composed controller and current renderer-capture namespace. On the RTX 4090, Isaac Sim now passes three frames for each maintained backend and Kit passes all 37 workflow steps, UI/config/instrument checks, audio output, and screenshots.

## Artifacts

R6.1 retains no generated artifact. Build, distribution, cache, and live-validation products are temporary and removed by `make clean` after verification.

## Files

- `README.md`
- `Makefile`
- `src/isaac_audio_sensors/kit/paths.py`
