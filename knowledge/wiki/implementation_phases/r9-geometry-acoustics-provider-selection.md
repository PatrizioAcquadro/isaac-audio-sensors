# Phase R9 — Geometry Acoustics Provider Selection

Status: R9.1 and R9.1.1 completed on 2026-09-01; R9.1.2 completed on 2026-09-02; R9.2 corrected on 2026-09-03; R9.3 is planned.

The remaining R9.2/R9.3 execution order is referenced by [[implementation_phases/01-geometry-provider-qualification|Implementation Plan 01]]. That plan adds no technical requirements: this page is the sole authority for provider qualification, comparison, selection, evidence, limitations, and acceptance semantics.

## Objective

Select the existing acoustic engine that can satisfy the passive-audio requirements before building a maintained Isaac integration. This phase owns provider qualification and the final provider decision; R10 owns product integration.

R9 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: temporary candidate work may exist during qualification, but the completed decision retains no unselected provider integration or other surface without a current qualification or product role.

## Subphase R9.1 — Required Provider Contract

#### Implementation

R9.1 is implemented as the repository-internal
`tools/qualification/geometry_acoustics_contract.py` validator. The corrected
`r9.1-rev2` contract supersedes the original internal report schema. It accepts
candidate identity, the evaluated Isaac Sim/Kit runtime, and one result for
each of 15 canonical criteria. It does not register a backend, change package
configuration, or claim that a provider exists.

Every result uses `pass`, `fail`, or `blocked`, a non-empty explanation, typed
evidence references, and an evidence origin: `provider_native`, `ias_bridge`,
`mixed`, or `documentation`. A behavioral `pass` or `fail` requires an executed
runtime probe or measurement. A harness limitation is `blocked`, not a failed
provider capability. Packaging requires a packaging probe and licensing
requires the official license.

The ten core-integration criteria are passive audible PCM, separate
phase-coherent microphone signals, dynamic scene geometry, direct occlusion and
transmission, indirect non-line-of-sight propagation, relative amplitude,
Isaac-runtime execution, source-build packaging, licensing, and complete audio
block performance. The four additional full-R10 criteria are connected spaces
and doors, acoustic-assembly identity, frequency-dependent transmission, and
acoustic-refresh performance. Provider path/ray diagnostics form a separate
non-blocking diagnostic profile.

The validator independently derives `core_integration_outcome` from the core
profile and `full_r10_outcome` from core plus full-R10 criteria. Within either
profile, a failed gate produces `rejected`; otherwise a blocked gate produces
`incomplete`; otherwise the result is `qualified`. A report cannot declare or
override either outcome. A missing advanced R10 capability therefore does not
erase a valid core-integration result.

#### Key Decisions

- Raw multichannel microphone output and passive audible content are non-negotiable core gates.
- Functional indirect NLOS output through native reflections or pathing is sufficient; a dedicated pathing API or true diffraction solver is not mandatory.
- Core-integration and full-R10 suitability are separate derived conclusions.
- Missing harness coverage is recorded as `blocked`; only executed contrary evidence can fail a behavioral gate.
- The maintained product should select one primary passive provider.
- Native provider capabilities take precedence over repository-owned reimplementations when they satisfy the sensor contract and maintenance boundary.
- An outcome of `qualified` records only measured profile coverage; R9.3 still owns provider selection.

#### Problems / Limitations

No provider is selected by R9.1. The validator checks report completeness,
evidence classes, origins, and outcome semantics; it cannot establish that a
referenced measurement is true. R9.2 must produce the runtime evidence.
Provider marketing or a plausible rendered signal remains insufficient.

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

The corrected R9.2 qualification supersedes the original candidate reports,
which remain untouched as historical local evidence. New bundles use the
`r9.1-rev2` contract under `build/validation/r9/rev2/`; no old artifact is
silently replaced. The harness provides 23 deterministic planar-surface and
signal fixtures, metrics, report construction, and temporary candidate
adapters. Signal-producing runs use private `[microphone, sample]` blocks; no
public backend, signal type, frame, schema, package dependency, or release
artifact was added.

Steam Audio `4.8.1` was built from official tag `v4.8.1`, commit
`0da18255cca520771f363ee01f100572b39a308e`, as a Release shared library with
Embree enabled. The corrected adapter uses native `DIRECT` simulation and
real-time `REFLECTIONS`, with one persistent simulator, source, direct effect,
and reflection effect per physical point receiver. Planar acoustic boundaries
replace volumetric boxes. Persistent benchmark sessions separately measure
complete four-microphone audio blocks and acoustic refreshes for one and four
environments.

The minimal IAS bridge contributes only geometric source-to-microphone
fractional delay on a shared input timeline, separate microphone outputs, and
grouping of fragments that identify the same acoustic assembly. It derives
delay from geometry rather than measured-output alignment and implements no
ray tracer, reflection model, or attenuation. Native Steam direct output is
retained separately and remains zero-lag. With the bridge, both oblique source
poses pass all six microphone pairs: maximum lag error is 0.393 samples and
minimum realigned correlation is 0.99986.

The provider natively passes the separated direct, opaque-occlusion,
transmission, reflective-room, and L-corridor NLOS fixtures. Both indirect
cases produce five valid repetitions with median energy more than 90 dB above
the silent/numerical control. Opening the unchanged two-room door gains 61.30
dB. Distance doubling produces -6.26 dB and -6.28 dB. Door, object, source,
and array dynamics change the expected output without recreating static
geometry.

Transmission maps authored loss through `10^(-loss_db/20)` because the Direct
Effect applies the three values as waveform EQ gains. The report also records
the Scene API's distinct energy-fraction wording. One global transmission-ray
configuration is used for all fixtures. Mono and equivalently fragmented
assemblies both measure 12 dB loss and pass assembly identity. The
400/2500/15000 Hz curve remains within the 4 dB per-band tolerance, and the
12/60 dB controls expose 48 dB of dynamic range. However, two sequential 12 dB
partitions measure 18 dB rather than the expected 24 dB, outside tolerance;
this is the one measured full-R10 failure.

Complete audio-block p95 is 0.30 ms for one environment and 1.15 ms for four,
against the 20 ms limit. Acoustic-refresh p95 is 11.40 ms and 42.44 ms,
against the respective 100 ms and 250 ms limits. Each audio result uses 20
warm-ups and 200 measured blocks; each refresh result uses 10 warm-ups and 50
measurements. Path/ray diagnostics were not enabled and are correctly
`blocked`, not failed.

Steam Audio therefore records 13 passes, one fail, and one blocked diagnostic.
Its derived `core_integration_outcome` is `qualified`; its
`full_r10_outcome` is `rejected` solely by frequency-dependent transmission's
sequential-partition check. This is a qualification result, not a provider
selection.

NVIDIA RTX Acoustic `3.0.0` was not rerun. Its preserved runtime evidence was
explicitly reused and reclassified under rev2: two criteria pass, seven fail,
and six are blocked because the old harness did not exercise them. Both
derived outcomes are `rejected`. Its active `CHIRP`/`AM`
transmitter-receiver interface still fails the core passive-PCM and raw
microphone semantics; unexercised advanced behavior and complete passive-block
timing are no longer reported as false failures.

Both rev2 reports validate, and the derived summary compares coverage only. It
contains no ranking or provider selection.

#### Key Decisions

- Qualification uses shared semantic fixtures and measurable outputs, not subjective audition or marketing claims.
- Native provider direct and reflection models are reused through the thinnest maintainable adapter; functional NLOS output does not require a dedicated pathing API.
- IAS may bridge geometric propagation delay and assembly identity but may not invent attenuation, reflections, pathing, or ray tracing.
- Performance gates are independent of acoustic correctness gates and use persistent provider objects.
- Temporary comparison adapters are deleted after the final provider decision unless they are part of the selected integration.
- Whole-assembly transmission data is preferred over a repository-owned double-leaf or structural wall solver.
- Provider qualification concerns signal production and propagation behavior, not backend-specific perception.
- Rev2 distinguishes provider-native, IAS-bridge, mixed, and documentation evidence for every result.
- Preserved RTX evidence is reused explicitly; RTX is not rerun merely to populate the revised schema.
- Native semantics are preserved: R9.2 adds no IAS attenuation compensation and does not reinterpret active RTX signal ways as passive PCM.
- R9.3 remains the only subphase authorized to select a provider or record an explicit no-provider decision.

#### Problems / Limitations

Steam Audio satisfies the corrected core-integration profile only with the
explicit IAS geometric-delay and assembly-grouping bridge. Native direct output
alone has no physical inter-microphone propagation delay. Its remaining
measured full-R10 blocker is the non-additive sequential-partition transmission
result. Native path/ray diagnostics remain unqualified.

RTX Acoustic exposes an active transmitter-receiver model rather than passive
audible microphone PCM. Its installed proprietary extension does not satisfy
the source-build packaging or open-source redistribution path, and the reused
evidence cannot qualify the advanced rev2 criteria that were never exercised.

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

The superseded R9.2 artifacts remain unchanged under
`build/validation/r9/{steam_audio,nvidia_rtx_acoustic}/`. Corrected ignored
bundles live under
`build/validation/r9/rev2/{steam_audio,nvidia_rtx_acoustic}/`, each containing
the `r9.1-rev2` report, derived evaluation, measurements, NPZ signals, run log,
and provenance. `build/validation/r9/rev2/summary.json` records valid
two-candidate coverage without ranking or selection. The Steam source/build
remains under `build/qualification/r9/steam-audio`. No provider decision exists
yet.

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
