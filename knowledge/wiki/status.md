# Current Status

Updated: 2026-08-24. Package version: `2.0.0`.

## Product Boundary

`isaac-audio-sensors` is a reusable robot-audition SDK that owns pure audio contracts and backends, calibration, generic recording/replay, optional Isaac Sim and Isaac Lab integration, the Kit extension, examples, and release tooling.

Robot-specific assets and mounts, downstream adapters and policies, task orchestration, measurement campaigns, holdouts, acceptance criteria, and experiment evidence remain outside the distributed product.

## Verified Capabilities

- Stable frame, calibration, manifest, serialization, configuration, plugin, capability, CLI, and packaged JSON Schema contracts.
- Deterministic geometry and synthetic TDOA backends plus optional room acoustics, SRP-PHAT, motion, Doppler, channel response, noise, electronics, directivity, and material/occlusion behavior.
- Atomic generic recording, verified sharded sessions, codecs, validation, statistics, deterministic splits, and read-only replay.
- Generic `quad_cross_120mm` and `stereo_y_100mm` stage rig profiles; robot-specific profiles remain downstream configuration.
- Lazy Isaac Sim stage discovery, pose and cache handling, sensor lifecycle, visualization, OmniGraph, Replicator, and Kit workflows.
- Current NVIDIA `OmniSound` and `OmniListener` authoring with schema-native timing, gain, finite/infinite loop, spatial, and listener-orientation semantics; non-spatial sources are excluded with diagnostics even during strict scans unless explicitly selected, and deprecated `Sound` and `Listener` remain read-compatible.
- Separate Kit scene audition and qualitative device-mix capture from a compatible direct array-child listener, creating a session-layer child when needed, with verified WAV metadata, lifecycle cleanup, manual-listener override preservation, and no path into microphone-array frames, datasets, or Isaac Lab observations.
- Lazy Isaac Lab imports, direct current `SensorBase` inheritance after `AppLauncher`, explicit entity/reference binding, fixed-shape tensor observations, partial reset, and fail-closed device validation.
- Python source and universal wheel distributions plus a self-contained Kit Community Registry archive with audited room/FLAC dependencies.
- Enforced R5.0 semantic imports, metadata-only package root, subsystem-owned public APIs, and fresh-process optional-runtime isolation.
- R5.1 core root limited to eleven fundamental models, simulator-independent config, quaternion-authoritative array pose, one propagation protocol, and generator-authoritative schemas.
- R5.2 single-path backend resolution and declaration-derived inventory, separated effects parsing/validation, and modular room-acoustics orchestration with unchanged valid-input numerical results.
- R5.3 minimal recording API, strict canonical manifests, one streaming session authority, composed recorder internals, structured corruption findings, and consolidated black-box coverage with compatible v1 artifacts.
- R5.4 live-only Isaac sensor, Kit-owned profiles/validation/output workflow, shared lazy lifecycle helpers, domain-owned room/occlusion state, and exact import-safe Isaac exports.
- R5.5 five-name Lab API, vectorized entity training path, pure-snapshot reference path, six-tensor data contract, current Warp-mask lifecycle, and removal of stage/fallback/metadata compatibility paths.
- R5.6 composed Kit services, thin controller/view/entrypoint boundaries, stateful-only validation controller, complete best-effort shutdown, and focused service tests.
- R5.7 lazy CLI leaf handlers, subsystem-owned config simulation, frozen v2 command inventory, one trace-export path, consistent exit codes, and consolidated command tests.
- R5.8 exact curated v2 entrypoint inventory, minimal Kit/schema roots, one maintained root example set, installed-package execution coverage, and no duplicate example documentation.
- R6.1 concise root guidance and release history, temporary validation output under `build/validation/`, and a safe generated-workspace cleanup target.
- R6.2 explicit wheel-only package data, one universal Python build, minimal installed-artifact audit, and no sdist or compatibility build aliases.
- R6.3 minimal self-contained Kit archive, standard Linux/CPython/Kit target metadata, temporary-only staging, direct package layout, and Extension Manager lifecycle verification.
- R6.4 removal of the dependency-pack API and tooling, three-state capability provenance, and locked room/FLAC dependencies inside the single Kit zip without a second NumPy.
- R6.5 three-command local workflow, deterministic host check, clean-source release preflight, flat two-artifact outbox, and removal of redundant release orchestration.
- R6.6 one exact two-artifact audit derived from source and locked wheels, including isolated offline wheel installation and packaged dependency provenance.
- R6.7 complete host, RTX 4090, packaged Kit, artifact, and downstream-consumer closeout without publication.
- R6.8 exact source distribution, Python 3.10–3.12 CI, and verified tokenless TestPyPI/PyPI publication with isolated OIDC permissions.

## Documentation State

The canonical documentation is this wiki; the root README is the concise public landing page and the root `CHANGELOG.md` owns product and release chronology.

The root `docs/` directory is not part of the maintained repository boundary; the applied R0 specification is retained only as authorized raw material under `knowledge/raw/docs/`.

Essential contribution and security guidance now lives directly in the root README. Separate citation, conduct, contribution, and security policy files are no longer maintained; paper citation metadata remains deferred until a paper exists.

The GitHub repository is the public source tree. Python releases contain one audited source distribution and one universal wheel built from it.

The Kit extension keeps a narrow standalone README and extension-specific changelog because an installed archive cannot depend on repository-relative documentation.

## Validation

The R3 runtime baseline passed 116 Isaac tests on the RTX 4090 and the complete generic live Kit workflow.

The R4 deterministic gate passed 414 host tests in 9.58 seconds, 366 integration tests in 10.36 seconds, and 40 release tests in 0.36 seconds, including six documentation-boundary tests.

The R5.0 host gate passes 417 unit/contract tests, 343 integration tests, and 40 release tests after removing redundant test-only coverage.

The R5.1 gate passes 416 unit/contract tests, 343 integration tests, 40 release tests, and 115 Isaac tests on the RTX 4090. The known SquadBot audio contract, replay, live-bridge, and adapter selection passes 34 downstream tests without consumer changes.

The R5.2 gate passes 409 unit/contract tests in 6.26 seconds, 342 integration tests in 8.24 seconds, 40 release tests, and 112 Isaac tests on the RTX 4090. Geometry, TDOA, fake-room GCC, and fake-room SRP frames remain byte-identical to the pre-refactor baselines; the maintained real-room example renders with pyroomacoustics 0.10.1. The same 34 SquadBot tests pass without consumer changes.

The R5.3 gate passes 413 unit/contract tests, 223 host integration tests, 40 release tests, and 112 Isaac tests on the RTX 4090. The optional FLAC lane passes 5 tests with SoundFile in the Isaac Lab interpreter; the host-only environment skips that one optional roundtrip. The same 34 SquadBot tests pass without consumer changes, and wheel/source plus Kit archives pass their audits.

The R5.4 gate passes 406 unit/contract tests, 227 host integration tests, 40 release tests, and 113 Isaac tests on the RTX 4090. The host lane has one expected SoundFile skip; live Isaac Sim and Kit smokes pass on the same GPU. The same 34 SquadBot contract, adapter, replay, live-bridge, and ontology tests pass without consumer changes.

The R5.5 gate passes 405 unit/contract tests, 222 integration tests with one expected host SoundFile skip, 40 release tests, and 118 Isaac tests on the RTX 4090. The live Lab smoke passes entity/reference parity for both maintained entity backends, partial reset, CUDA shape/dtype/device checks, and 50 steps over 4096 environments at 1.879 ms/step mean against the 20 ms budget. The same 34 functional SquadBot consumer tests pass without consumer changes; its checkout-provenance assertion is rerun only from the final clean repository state.

The R5.6 gate passes 405 unit/contract tests, 229 integration tests with two expected host SoundFile skips, 40 release tests, and 88 Isaac-only tests on the RTX 4090 after pure Kit tests moved to integration. The 15 SoundFile tests pass in the Isaac Lab runtime, the single live Kit workflow passes on the same GPU, and the same 34 SquadBot consumer tests pass. Wheel/source and Kit archives pass their audits.

The R5.7 gate passes 406 unit/contract tests, 229 integration tests with two expected host SoundFile skips, 40 release tests, and 88 Isaac tests on the RTX 4090. The 15 SoundFile tests pass in the Isaac Lab runtime, the live Kit workflow passes on the same GPU, and the same 34 SquadBot consumer tests pass without consumer changes. Wheel/source and Kit archives pass their audits.

The R5.8 gate passes 418 unit/contract tests, 229 integration tests with two expected host SoundFile skips, 40 release tests, and 88 Isaac tests on the RTX 4090. The 15 SoundFile tests and the retained room-acoustics example pass in the Isaac Lab runtime. Live Isaac Sim, Isaac Lab, and Kit smokes pass on the same GPU; the Lab smoke validates 4096 environments at 1.846 ms/step mean against the 20 ms budget. The same 34 SquadBot consumer tests pass with one expected skip and no consumer changes. Wheel/source and Kit archives pass their audits.

The R6.1 host gate passes 418 unit/contract tests, 229 integration tests with the same two expected SoundFile skips, 40 release tests, 11 focused Kit-path tests, version synchronization, and Ruff. Clean-source wheel/source and Kit builds pass their audits from commit `c96a152`.

The subsequent live-blocker reconciliation passes 418 unit/contract tests, 231 integration tests with the same two expected SoundFile skips, 40 release tests, and 88 Isaac tests on the RTX 4090. The Isaac Sim smoke passes three frames for geometry, TDOA, and room acoustics. The Kit smoke passes all 37 workflow steps, UI inventory, editable and invalid-input models, config roundtrip, instruments, audio output, and both screenshots. All generated evidence remains under `build/validation/`.

The R6.2 gate passes 418 unit/contract tests, 231 integration tests with the same two expected SoundFile skips, and 43 release tests. Version synchronization and Ruff pass. The real `py3-none-any` wheel contains only the maintained Python package, three JSON Schema files, metadata, and required licenses; a fresh no-dependency installation passes package import, CLI version, schema-resource parsing, and `room` extra metadata checks.

The R6.3 gate passes 418 unit/contract tests, 230 integration tests with the same two expected SoundFile skips, and 36 release tests after removing the retired installer and duplicate Kit checks. Version synchronization, Ruff, archive audit, and whitespace checks pass. The checkout and isolated packaged extension each pass all 37 live workflow steps on the RTX 4090 with Kit 110.1.2, including Extension Manager enable/disable and clean shutdown; the packaged run imports the core package only from the extracted archive.

The R6.4 gate passes 412 unit/contract tests, 230 integration tests with the same two expected SoundFile skips, 39 release tests, and 88 Isaac tests on the RTX 4090. The Python wheel contains no `_bundled` tree or removed pack module. The Kit zip contains the five locked dependency distributions and licenses, with NumPy and `typing_extensions` still supplied by Kit. The isolated extension passes bundled capability, room waveform, FLAC export/read/replay, enable/disable, and shutdown gates. The same 34 SquadBot consumer tests pass without consumer changes.

The R6.5 deterministic gate passes 412 unit/contract tests, 230 integration tests with two expected SoundFile skips, and 38 release tests. Version synchronization, Ruff, whitespace, wheelhouse hashes, clean-source provenance, the installed wheel audit, and the Kit audit pass. `dist/` contains only the current universal wheel and Community Registry ZIP.

The R6.6–R6.7 gate passes 412 unit/contract tests, 230 integration tests with two expected host SoundFile skips, 37 release tests, and 88 Isaac tests on the RTX 4090. Live Isaac Sim passes three frames each for geometry, TDOA, and room acoustics. Live Isaac Lab passes parity, partial reset, and 50 steps over 4096 environments at 1.934 ms/step mean against the 20 ms budget. The Isaac Lab interpreter passes room and FLAC execution with the locked versions. The isolated final ZIP passes Extension Manager enable/disable, exact package and dependency origins, Kit-owned NumPy and `typing_extensions`, room waveform, FLAC, and shutdown. The same 34 SquadBot consumer tests pass without consumer changes. `dist/` contains only the exact synchronized wheel and Kit ZIP.

The final R6.8 freeze at commit `583d66e` passes 412 unit/contract tests, 230 integration tests with the same two expected SoundFile skips, 45 release tests, and `twine check`. The clean-source build leaves exactly the audited sdist, universal wheel, and Kit ZIP; isolated wheel installation and sdist build/installation pass. The RTX 4090 passes 88 Isaac tests, all three live Isaac Sim backends, room/FLAC with pyroomacoustics 0.10.1, SciPy 1.18.0, and SoundFile 0.14.0, and the 4096-environment Lab smoke at 2.4035 ms/step mean against the 20 ms budget. The final extracted ZIP passes all 37 workflow steps with packaged first-party and bundled dependency origins, Kit-owned NumPy and `typing_extensions`, room waveform, FLAC, Extension Manager enable/disable, and shutdown. The unchanged SquadBot consumer subset passes 34 tests.

The TestPyPI rehearsal and production workflow passed from the same commit. GitHub release `v2.0.0` is immutable, its tag targets `583d66e`, and its only asset is the validated Linux Kit ZIP with SHA-256 `cfaeea69ac79a711fc608329dad2a947cc66c4ff1c6a1f958fca4617c1c5ff8a`. PyPI exposes exactly the universal wheel and sdist with provenance attestations; clean Python 3.10, 3.11, 3.12, and `room`/FLAC installations passed. The public repository has the `omniverse-kit-extension` topic. NVIDIA Community Registry discovery and installation remain pending the periodic crawler.

The post-release NVIDIA audio-schema migration at commit `152569f` passes 412 unit/contract tests, 239 integration tests with two expected host SoundFile skips, 45 release tests, and 97 Isaac tests on the RTX 4090. Live Isaac Sim passes geometry, TDOA, and room-acoustics backends while validating `OmniAudioSchema.OmniSound`, `OmniAudioSchema.OmniListener`, current native attributes, robot-mounted listener orientation, and no authored `filePath` for `generated://`. The live Kit workflow passes with deprecated `Sound` seeds migrated to `OmniSound` and the same generated-asset boundary.

The post-release native Kit Audio integration passes 426 unit/contract tests, 251 integration tests with two expected host SoundFile skips, 45 release tests, and 103 Isaac tests. Strict discovery now omits implicit non-spatial sources with diagnostics while retaining explicit-selection failure, and listener reuse requires a static identity direct array child with array orientation. On the RTX 4090, live Isaac Sim passes three frames each for geometry, TDOA, and room acoustics; live Isaac Lab passes entity/reference parity, partial reset, and 50 steps over 4096 environments at 1.908 ms/step mean against the 20 ms budget. The live Kit gate on Kit build 110.1.2 creates the temporary listener below the four-microphone array in the session layer, captures a readable non-silent 2-channel 48 kHz device-mix WAV, restores the previous active listener, removes the temporary prim, destroys the streamer, and confirms that the sensor remains four-channel.

Ruff, version synchronization, the executable README quickstart, internal wikilinks, index coverage, removed-root-doc references, Kit metadata, and whitespace checks passed.

R4 changes documentation, packaging metadata, version checks, and release-boundary tests without changing Python, CLI, schema, or runtime behavior; its clean-source artifact builds were verified after the implementation commit and reported in the phase handoff.

See [[implementation_phases/r2-fast-test-architecture|R2 Fast Test Architecture]], [[implementation_phases/r3-product-boundary-cleanup|R3 Product Boundary Cleanup]], [[implementation_phases/r4-documentation-consolidation|R4 Documentation Consolidation]], and [[implementation_phases/r5-semantic-component-refactor|R5 Semantic Component Refactor]].

## Maintained Commands

- `make clean` — remove only regenerable local build, validation, cache, and Python metadata files.
- `make check` — run the complete deterministic host gate.
- `make release WHEELHOUSE=<path>` — rebuild and audit the sdist, wheel, and Kit ZIP from one clean commit.

Focused test, lint, Isaac, live-smoke, schema, and diagnostic targets remain available for subsystem work.

## Limits

- Isaac tests require a compatible user-managed runtime and visible GPU; required GPU checks do not use CPU fallback.
- Standard Python room acoustics requires the optional `room` extra; Kit includes the locked dependencies in its archive. The model remains an approximate shoebox simulation.
- Raycast occlusion and nominal transmission do not model diffraction or establish measured material behavior.
- Simulation correctness does not establish hardware calibration, physical acoustic fidelity, downstream policy quality, or sim-to-real validity.
- Kit mix capture is device- and speaker-layout-dependent qualitative output, not simultaneous microphone-array channels; concurrent third-party Kit capture streamers are unsupported.
- Retained scientific evidence is local, ignored, protected, and excluded from distributions.

## Next Work

Verify `isaac_audio_sensors.omni` 2.0.0 discovery, installation, and launch from the NVIDIA Community Registry after its crawler runs. R7 follows after that publication closeout.
