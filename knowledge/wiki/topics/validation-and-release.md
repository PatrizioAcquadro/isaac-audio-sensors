# Validation and Release

## Test lanes

| Command | What it checks |
| --- | --- |
| `make check` | Version synchronization, Ruff, diff whitespace, then unit/contract, integration, and release tests. Runs in the host development environment. |
| `make test` | Core behavior and public contracts. |
| `make test-integration` | CLI, recording, codecs, analytic acoustics, and host-side Kit workflows. |
| `make test-release` | Python and Kit artifact contracts, versioning, documentation links, and content policy. |
| `make test-isaac` | USD, native-provider, and CUDA parity and isolation tests through the configured Isaac launcher. |
| `make smoke-optional` | Execution with installed room-acoustics and audio codec dependencies. |

The GitHub host matrix covers Python 3.10–3.12. Its Python 3.12 room/FLAC job also exercises the optional SciPy-backed scoring, convolution, and transport regressions.

## Focused checks

Use `make validate-config` for the example TOML and `make validate-fixture` for the committed recording. `make export-schema` writes the three public schemas to `build/schemas/` by default. `make lint` runs Ruff.

`make clean` removes the entire build directory, including installed native libraries and validation evidence. Use a clean separate checkout for release builds when existing outputs need to be preserved.

## Live runtime gates

Run from the checkout root using the supported Isaac launcher. Set `ISAAC_LAB_ROOT` or `ISAAC_LAB_PYTHON` for a different installation. Exit an unrelated activated environment before launching.

| Command | What it exercises |
| --- | --- |
| `make smoke-isaac-sim` | Stage discovery, transforms, sensors, diagnostics, and frame output. |
| `make smoke-isaac-lab` | Real Lab bindings, fixed-shape observations, per-environment reset, and CUDA placement. |
| `make smoke-kit` | Extension Manager, configuration and attachment, instruments, OmniGraph, recording, screenshots, and shutdown. |

For a custom `--out` with generated audio, put the report **inside the working directory** or one of its subdirectories. The smoke writes its signal files beside the report and records their paths relative to the working directory. The Kit application output root is a separate setting, `ISAAC_AUDIO_SENSORS_OUTPUT_ROOT`. For packaged validation use the extracted extension as the import source.

## Version Authority

`pyproject.toml` is authoritative for the package version.

The version gate synchronizes the package `__version__`, Kit manifest, root README, canonical wiki status, root changelog, and extension-specific changelog.

The frame, dataset-manifest, and calibration-profile schema versions remain independent from the package version.

## Build and Audit

The `dev` extra installs the build frontend, Setuptools 77 or newer, and wheel, matching the default non-isolated source/wheel build and its PEP 639 license metadata.

`make release WHEELHOUSE=<path>` runs one preflight for version synchronization, clean Git source, and the locked wheelhouse before clearing `dist/`. It builds the source distribution, builds the universal wheel from that source distribution, creates the self-contained Kit ZIP, and requires those exact synchronized filenames as the complete flat outbox. It never publishes, tags, or pushes.

The source-distribution audit requires safe tar paths, exact source and generated-metadata inventories, matching root files, package metadata, licenses, console entry point, and README description. It rejects repository-only and project-specific content. The wheel audit derives the complete package and schema inventory from the maintained source tree, then installs the exact wheel without dependency downloads or checkout import paths and verifies the import, CLI, schemas, exact Core requirements, and `room` metadata.

The Kit build creates `PatrizioAcquadro-isaac-audio-sensors-linux-x86_64-v<version>.zip`. The explicit wheelhouse must match the hashes and exact eight-distribution inventory in `tools/release/kit_dependencies.lock`: Auditok, NARA-WPE, Click, `pyroomacoustics`, SciPy, SoundFile, CFFI, and pycparser. Acquisition verifies hashes while downloading; the preflight, builder, and post-build audit independently validate their input or artifact boundary.

Temporary staging contains the direct Python package, Kit configuration/resources/docs/entrypoint, licenses, and the locked Auditok/room/FLAC dependencies under `isaac_audio_sensors/_bundled`. The audit derives the complete first-party inventory from source, reconstructs the complete bundled inventory from the eight hash-locked wheels, and compares both file-for-file. It also verifies Auditok's module, metadata, and MIT license; required native libraries; no bundled NumPy or `typing_extensions`; and no retired release surface.

The shared policy rejects first-party tests, tools, scripts, local datasets, evidence, outputs, phase paths/content, downstream project identifiers, and absolute workstation paths. Bundled third-party content receives safe-path and dedicated dependency/license audits instead of project-semantic filtering.

## Release Checklist

Run `make check` and `make release WHEELHOUSE=<path>`. Add the runtime gates appropriate to changed behavior, regenerate schemas when contracts change, update `CHANGELOG.md`, and inspect all three artifacts before publication. Preserve installed native providers and local evidence; a whole-build cleanup is unnecessary.

Builds must originate from one clean committed tree; do not publish, tag, or push based on uncommitted artifacts or skipped required lanes.

Publishing a matching non-prerelease GitHub release builds and audits all three artifacts, runs `twine check` once, and transfers only the immutable sdist and wheel artifact to a protected PyPI upload job with `id-token: write`. One post-publication matrix verifies base installations on Python 3.10–3.12 and the Python 3.12 `room`/FLAC path.

After publication, verify the remote tag and immutable GitHub asset against the release commit and digest. Verify the PyPI JSON and Integrity APIs expose only the expected sdist and wheel with provenance, then repeat base and optional-extra installation checks from the public index. Community Registry closeout additionally requires discovery, installation, enable/disable, and launch from the registry; a valid GitHub release is only the crawler input, not proof of registry publication.

Before closeout, extract the ZIP into an `isaac_audio_sensors.omni` directory so Extension Manager resolves its identifier. Run the packaged Kit smoke with offline pip settings, no checkout package path, and a precreated `ISAAC_AUDIO_SENSORS_OUTPUT_ROOT`. Use the working-directory layout in the live runtime instructions above. Verify Extension Manager enable/disable, first-party and bundled origins, Kit-owned NumPy and `typing_extensions`, fixed-threshold Auditok detection, room waveform, FLAC, and shutdown.

## Interpretation

Passing software gates establishes the implemented contract within their environments; it does not establish physical acoustic fidelity, hardware calibration, downstream policy quality, or sim-to-real behavior.

Current verified results and exact limitations belong in [[status|Current Status]], while release chronology belongs in the root `CHANGELOG.md`.


## R10.1 native scene gate

`tests/isaac/test_acoustic_scene.py` uses real USD. Native cases additionally
require the local qualified Steam binary and skip explicitly if it is absent.
The live GPU/panel gate is:

```bash
PYTHONPATH=src:tools/smoke:exts/isaac_audio_sensors.omni CUDA_VISIBLE_DEVICES=0 \
  "$HOME/IsaacLab/isaaclab.sh" -p tools/smoke/live_acoustic_scene.py \
  --library /absolute/path/to/qualified/libphonon.so \
  --out build/validation/r10/scene
```

The Isaac/Kit runtime also needs Auditok 0.5.2 and NARA WPE 0.0.11. If absent,
install their existing wheels with `pip install --no-deps --target <runtime-deps>`
and append that directory to `PYTHONPATH`. Keep Isaac's native packages and CUDA
PyTorch authoritative; do not add the entire host virtual environment to its path.
The gate compares native exported coordinates, exercises PhysX poses without
USD writes, tests shared Kit edits and Undo/Redo, and captures the actual panel.
It does not qualify propagation PCM or perceptual accuracy.

## Geometry operating gate

The optional native libraries are external dependencies of both Python and Kit
artifacts. Building a Kit ZIP does not bundle or qualify them. Keep the pinned
recipes and ABI checks in [[topics/geometry-acoustics|Geometry Acoustics]].

Pass `--geometry-library <qualified-libias_pathing.so>` and
`--specular-library <qualified-libias_specular.so>` to the maintained Sim and Kit
smokes. The Kit gate additionally exercises prepared scene → configured sensor →
observed instruments, combined NLOS/diffuse, closed/open/closed screen motion,
source-stop/tail, widget recreation, configuration failure and stage replacement.
Use `--require-screenshot` for the actual UI gate. The same options apply when
running from the extracted archive; package/dependency origin checks must pass.

For bounded Lab cost, use the same library arguments with `--geometry-screen`
(base) or `--geometry-combined`, `--perf-envs 1` or `2`,
`--perf-steps 30 --perf-sources 1 --perf-reference-check --perf-reference-steps 2`.
GPU access is required. Acquisition/perception timing is separate from lazy native
warm-up, preparation and reset; host RSS and CUDA allocator peaks have distinct
scopes. [[experiments/geometry-acoustics-admission#08.3 operating runtime and cost (2026-09-19)|The operating results]]
own measured costs and limitations. There is no real-time threshold or inference
to complex rooms, large batches or physical transfer.
