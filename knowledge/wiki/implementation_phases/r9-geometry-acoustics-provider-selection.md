# Phase R9 — Geometry Acoustics Provider Selection

Status: R9.1 and R9.1.1 completed on 2026-09-01; R9.1.2 and R9.2 completed on 2026-09-02; R9.3 is planned.

The remaining R9.2/R9.3 execution order is referenced by [[implementation_phases/01-geometry-provider-qualification|Implementation Plan 01]]. That plan adds no technical requirements: this page is the sole authority for provider qualification, comparison, selection, evidence, limitations, and acceptance semantics.

## Objective

Select the existing acoustic engine that can satisfy the passive-audio requirements before building a maintained Isaac integration. This phase owns provider qualification and the final provider decision; R10 owns product integration.

R9 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: temporary candidate work may exist during qualification, but the completed decision retains no unselected provider integration or other surface without a current qualification or product role.

## Subphase R9.1 — Required Provider Contract

#### Implementation

R9.1 is implemented as the repository-internal
`tools/qualification/geometry_acoustics_contract.py` validator. It accepts one
JSON report with exact `r9.1` contract version, candidate identity and version,
the evaluated Isaac Sim/Kit runtime, and one result for every canonical
criterion. It does not register a backend, change package configuration, or
claim that a provider exists.

Each result uses `pass`, `fail`, or `blocked`, a non-empty explanation, and one
or more typed evidence references. Behavioral passes require a runtime probe or
measurement; phase coherence, propagation, relative amplitude, assembly,
transmission, and performance require measurements. Packaging requires a
packaging probe and licensing requires the official license. Documentation can
support a result but cannot by itself pass a behavioral gate.

The blocking contract requires the provider to support:

- passive audible sources with arbitrary file-backed or generated content;
- separate phase-coherent raw output for every physical microphone;
- relevant scene geometry, materials, static objects, and dynamic objects;
- direct occlusion, reflections, transmission, indirect pathing, and approximate around-edge or around-corner propagation;
- connected rooms, corridors, doors, and openings without clamping remote sources into the array's room;
- physically coherent relative amplitudes without requiring universal dB SPL calibration;
- acoustic-partition or assembly semantics that do not multiply loss merely because one physical barrier uses several meshes or colliders;
- authored frequency-dependent assembly transmission without undocumented total-loss clipping;
- a viable Isaac runtime, packaging, licensing, and performance path.

Bounded provider-native path or ray diagnostics are recorded as the one
non-blocking criterion. Their absence remains an explicit limitation but does
not reject an otherwise qualified provider or add path data to public sensor
state.

The validator derives the outcome: any failed gate is `rejected`; otherwise any
blocked gate is `incomplete`; otherwise the candidate is `qualified`. A report
cannot declare or override its outcome. Human-listener, binaural,
device-speaker-mix, metadata-only, or active-ultrasound-only output does not
satisfy the microphone-array contract.

#### Key Decisions

- Raw multichannel microphone output and passive audible content are non-negotiable gates.
- Approximate pathing/diffraction is required; a complete wave solver is not.
- The maintained product should select one primary passive provider.
- Native provider capabilities take precedence over repository-owned reimplementations when they satisfy the sensor contract and maintenance boundary.
- `qualified` means only that the R9.1 gates have evidence; R9.3 still owns provider selection.

#### Problems / Limitations

No provider is selected by R9.1. The validator checks report completeness,
evidence classes, and outcome semantics; it cannot establish that referenced
evidence is true. R9.2 must produce the runtime measurements. Provider
marketing or a plausible rendered signal remains insufficient. A provider that
cannot represent one acoustic assembly across fragmented geometry, or that
silently changes authored transmission values, does not satisfy the material
contract.

## Subphase R9.1.1 — Core Capture Contract Cleanup

#### Implementation

R9.1.1 is a breaking repository-wide migration of the Core capture contract,
completed before provider qualification. `AudioTimeWindow` now contains only
required `start_time_s`, `end_time_s`, and `frame_index` fields.
`MicrophoneArraySpec.sample_rate_hz` is the sole runtime sample-rate authority;
the selected array determines render length and the projected frame sample
rate. Scene snapshots, time windows, and detections no longer carry
`timestamp_ms`. `AudioSensorFrame.timestamp_ms` remains serialized but is
derived exclusively from `int(round(start_time_s * 1000.0))`.

The former source limit was removed. Every source overlapping the time window
is rendered and localized in deterministic `(start_time_s, source_id)` order,
independent of any output bound. `max_detections` is applied only after
localization by descending array RMS, computed as
`sqrt(mean(per_mic_rms^2))`, with deterministic source-id and detection-id
tie-breaking. A zero limit therefore produces a complete waveform and
aggregate RMS with no detections. The Isaac Lab tensor path applies the same
acoustic priority while retaining fixed-size padded observations.

The incompatible frame contract is `ias.audio_sensor_frame.v2`. Current trace
readers require its exact shape and reject a serialized timestamp that differs
from the derived value. The frame v1 schema, generator resource, and current
trace fixtures were removed; dataset-manifest, calibration-profile, and
dataset-wrapper versions remain v1 because their own contracts did not change.
Core, CLI, Isaac Sim, Isaac Lab, Kit, OmniGraph, Replicator, recording/replay,
examples, smoke tests, and fixtures migrated directly without aliases or
fallback parsers.

#### Key Decisions

- Array configuration owns sample rate; a frame only projects the selected value.
- Output capacity never changes the simulated soundscape or aggregate measurements.
- Deterministic render order exists only for reproducibility and is not an exclusion priority.
- Acoustic RMS is a practical detection priority without adding a more complex salience model.

#### Problems / Limitations

Frame v1 traces are intentionally not accepted by the current frame reader.
`max_detections` controls reported detections, not detectability, audibility, or
physical source contribution. R9.1.1 does not qualify a provider, add a new
backend, or begin R10 integration.

## Subphase R9.1.2 — Physically Honest DOA Ambiguity

#### Implementation

R9.1.2 removes `front_hemisphere` and the complete ambiguity-policy surface from Core, propagation construction, plugins, Isaac Sim, Isaac Lab, Kit state/UI, and TOML. Removed Python arguments have no aliases; old TOML and Kit keys fail explicitly. The Kit binding advances directly to `ias.omni_extension_binding.v5`, and v4 has no compatibility reader.

Exactly two microphones remain supported for `tdoa_least_squares`. The estimate returns every normalized, deduplicated azimuth compatible with the delay, leaves bearing, sector, and elevation unset, reports zero confidence, and records purely geometric front/back ambiguity. When the delay lies at the physical endpoint and both candidates coincide on the baseline axis, the single candidate becomes the unique estimate.

Least-squares with three or more microphones and all SRP-PHAT estimation require at least three microphones whose centered XY positions have rank two. Configuration, runtime binding, and public estimation fail on collinear geometry instead of selecting a symmetric peak or adding a special linear-array model. Four non-collinear microphones are documented as the practical recommendation for redundancy and robustness.

The v2 frame contract remains unchanged: `candidate_bearing_deg`, `ambiguity_class`, and `ambiguity_reason` preserve the evidence needed by downstream consumers, and Isaac Lab retains `ambiguity_mask`. No learning, motion-based resolution, tracking, privileged geometry, or multimodal fusion enters Core. The active SquadBot adapter owns its explicit front-hemisphere context and does not mutate the source `DoaEstimate`; historical Phase 6A/6B fixtures remain immutable.

#### Key Decisions

- Sensor output represents what the array geometry can observe, not a contextual guess.
- Three rank-2 microphones are the minimum for unique 360-degree azimuth; four are recommended but not required.
- Consumer priors may select among candidates only outside the SDK and must preserve their decision origin.
- Frame v2 already carries sufficient ambiguity evidence, so no schema change or new representation is needed.

#### Problems / Limitations

The two-microphone contract represents the compatible azimuths in the public 2D model, not the continuous 3D cone. A geometrically unique estimate can still be degraded by noise, reverberation, finite sampling, or spatial aliasing. R9.1.2 does not add an advanced disambiguation technique, qualify a provider, or begin R10 integration.

## Subphase R9.2 — Candidate Qualification

#### Implementation

R9.2 qualified exactly Steam Audio `4.8.1` and NVIDIA RTX Acoustic
`3.0.0`. The internal harness under
`tools/qualification/geometry_acoustics/` provides common deterministic USD and
signal fixtures, metrics, report construction, and temporary candidate
adapters. Its private adapter boundary exposes `probe_runtime()`,
`run_fixture(...)`, `run_performance(...)`, and `close()`. Signal-producing
runs use internal `[microphone, sample]` blocks with microphone IDs, sample
rate, and component timings; no public `MicrophoneSignalBlock`, backend,
schema, frame, package, or release surface was added.

Both candidates ran through `/home/pacquadr/IsaacLab/isaaclab.sh -p` against
Isaac Sim `6.0.1-rc.7` and Kit `110.1.2`. The common matrix uses 48 kHz,
960-sample blocks, the 0.16 m `quad_front` array, deterministic impulse and WAV
multitone inputs, five repetitions, separated propagation and assembly cases,
dynamic updates, and 20 warm-ups plus 200 measured blocks for one and four
environments. Provider-native diagnostics are bounded to 256 records per
source, microphone, and frame and remain outside frames and datasets.

Steam Audio was built from official tag `v4.8.1`, resolved to commit
`0da18255cca520771f363ee01f100572b39a308e`, as a shared Release library with
Embree enabled and benchmarks, samples, and tests disabled. AVX was disabled
after the optional AVX source failed with the qualification host compiler; the
initial FlatBuffers warning-as-error and AVX build failures remain in the local
evidence. `libphonon.so` was loaded through `ctypes` in the Isaac interpreter.
The adapter used native Embree scenes, static meshes, `IPLInstancedMesh`,
materials, simulator direct output, and direct effects; reflection and path
entry points were probed but did not yield a qualifying unbaked indirect/path
signal.

Steam Audio is conclusively `rejected`: 6 criteria pass, 7 fail, and none are
blocked. Passive content, scene dynamics, relative amplitude, Isaac execution,
packaging, and licensing pass. Free-field distance drops are -6.26 dB and
-6.14 dB. Independent point receivers return zero measured inter-channel lag
where geometry predicts 8.92 to 21.96 samples. Native 12 dB assembly input
produces about 36 dB output loss, two such partitions produce about 60 dB, and
the IAS reference curve misses all three tone tolerances. Complete
reflection/path output, connected-space indirect energy, phase coherence,
assembly identity, transmission, performance, and bounded path diagnostics
therefore fail. Diagnostics-off direct-only p95 is 1.11 ms for one environment
and 3.09 ms for four, but those timings cannot pass the complete-block gate
without the missing qualifying output.

RTX Acoustic ran with Motion BVH on the runtime-visible NVIDIA GeForce RTX
4090. The exact installed `3.0.0` manifest was checked, and an event-driven
Replicator `Writer` captured GMO without duplicate callbacks. One observed GMO
frame contains four 320-sample transmitter-to-receiver signal ways. The
provider's `CHIRP` and `AM` modes are active acoustic returns, not arbitrary
passive PCM or raw microphone channels, and the adapter does not reinterpret
them.

RTX Acoustic is conclusively `rejected`: 2 criteria pass, 11 fail, and none are
blocked. Isaac execution and exact installed packaging pass. Passive content,
raw phase-coherent microphones, the passive geometry/material gates,
distribution licensing, complete-block performance, and path diagnostics
fail. Diagnostics-off active-update p95 is 18.40 ms for one environment and
30.87 ms for four, so the four-environment result also exceeds 20 ms before the
unavailable passive microphone block is considered. The runtime itself
reported the RTX 4090; no CPU fallback was used.

Both reports satisfy the unchanged R9.1 schema, and no blocking criterion has
status `blocked`.
The derived coverage summary is therefore complete even though both candidates
are rejected. It compares coverage only and contains no ranking or provider
selection.

#### Key Decisions

- Qualification uses shared semantic fixtures and measurable outputs, not subjective audition or marketing claims.
- Existing provider geometry, pathing, transmission, reflection, scattering, and diffraction facilities are reused through the thinnest maintainable adapter.
- Temporary comparison adapters are deleted after the final provider decision unless they are part of the selected integration.
- Whole-assembly transmission data is preferred over a repository-owned double-leaf or structural wall solver.
- Provider qualification concerns signal production and propagation behavior, not backend-specific perception.
- A rejected candidate with a valid report and no blocking criterion in `blocked` status is a complete R9.2 result.
- Native semantics are preserved: R9.2 adds neither IAS attenuation compensation nor passive-PCM reinterpretation of active RTX signal ways.
- R9.3 remains the only subphase authorized to select a provider or record an explicit no-provider decision.

#### Problems / Limitations

Neither evaluated candidate satisfies the blocking passive microphone contract.
Steam Audio lacks qualifying per-receiver propagation delay, complete indirect
and path output in this adapter path, and compatible assembly-transmission
behavior without repository-owned compensation. RTX Acoustic exposes an active
transmitter-receiver model rather than passive audible microphone PCM; its
installed proprietary license does not itself grant redistribution rights for
the open-source SDK. These are failed capabilities, not external blockers.

The qualification adapters remain temporary pending R9.3. Full source, binary,
measurement, NPZ, log, crash/build-failure, and provenance evidence is local
and ignored under `build/`; it is not a release artifact and can be removed by
`make clean`. Simulation evidence does not establish physical calibration or
sim-to-real validity.

## Subphase R9.3 — Candidate Decision

#### Implementation

Treat Steam Audio as the principal existing-engine candidate for passive geometry-aware propagation. Evaluate NVIDIA RTX Acoustic in the installed Isaac runtime, but select it for this role only if it supports arbitrary audible source content and raw per-microphone output rather than only active chirp or ultrasonic operation.

PyRoom remains the analytic provider and is not treated as the general arbitrary-geometry engine. Active acoustics, if added later, remains a separate backend.

Temporary candidate adapters may coexist during qualification, but the phase concludes with one documented primary provider or an explicit no-provider result. It must not leave multiple redundant experimental backends as permanent public surface.

Compare only candidates that satisfy the blocking contract. The decision weighs measured behavior, native capability coverage, maintenance burden, distribution viability, licensing, and intended-runtime performance against the practical-realism objective. Ecosystem preference or a successful availability probe is not sufficient evidence for selection.

After the decision, remove unselected candidate code and its unused configuration, dependencies, tests, and packaging surfaces. Preserve reports and only the tooling needed to revalidate the selected provider; comparison or test convenience does not justify candidate production code.

#### Key Decisions

- Provider research and provider integration are separate phases.
- The selected engine owns the mathematically complex propagation algorithms; the repository does not recreate them.
- One maintainable primary geometry provider is preferred to several partial permanent backends.
- The selected provider supplies microphone signals; it does not own activity detection, DOA semantics, observations, or learning labels.
- Selection follows complete qualification evidence and is not predetermined by ecosystem preference.

#### Problems / Limitations

If no candidate meets passive, per-microphone, dynamic-geometry, and distribution requirements, R10 remains blocked rather than weakening the sensor semantics. A qualified provider may also remain unsuitable for mass-parallel Isaac Lab execution; high-fidelity geometry propagation and scalable policy training are intentionally separate operating regimes.

## Artifacts

R9.1 provides the internal qualification validator and its deterministic unit
and CLI tests. R9.1.1 provides the simplified Core capture contract and v2
frame artifacts. R9.1.2 provides physically honest DOA ambiguity, rank-2 array
validation, and Kit binding v5 without changing frame v2.

R9.2 produces ignored local bundles under
`build/validation/r9/{steam_audio,nvidia_rtx_acoustic}/`, each containing the
R9.1 report, derived evaluation, measurements, NPZ signals, run log, and
provenance. `build/validation/r9/summary.json` records complete two-candidate
coverage without ranking or selection. The Steam source/build and failed build
attempts remain under `build/qualification/r9/steam-audio` and the Steam
validation bundle. No provider decision exists yet.

## Files

- `tools/qualification/geometry_acoustics_contract.py`
- `tests/unit/test_geometry_acoustics_contract.py`
- `tools/qualification/geometry_acoustics/`
- `tests/unit/test_geometry_acoustics_qualification.py`
- `src/isaac_audio_sensors/core/types/`
- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/core/doa/ambiguity.py`
- `src/isaac_audio_sensors/core/doa/srp_phat.py`
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`
- `src/isaac_audio_sensors/kit/configuration.py`
- `src/isaac_audio_sensors/schemas/audio_sensor_frame.v2.schema.json`
