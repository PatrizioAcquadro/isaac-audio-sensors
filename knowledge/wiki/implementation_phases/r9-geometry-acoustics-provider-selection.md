# Phase R9 — Geometry Acoustics Provider Selection

Status: R9.1 and R9.1.1 completed on 2026-09-01; R9.1.2 completed on
2026-09-02; corrected R9.2 and R9.3 completed on 2026-09-03. R9.4 is planned
after the completed Plan 02.1 and before Plan 02.2; it does not reopen the
provider decision or require a history rollback.

The R9.2 through R9.4 execution order is referenced by
[[implementation_phases/01-geometry-provider-qualification|Implementation Plan 01]].
That plan adds no technical requirements: this page is the sole authority for
provider qualification, comparison, selection, evidence, limitations, and
acceptance semantics.

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

The Steam adapter remains internal requalification tooling after R9.3. The
NVIDIA adapter and comparison/reclassification tooling were removed after the
decision. Full source, binary, measurement, NPZ, log, crash/build-failure, and
provenance evidence remains local and ignored under `build/`; it is not a
release artifact and can be removed by `make clean`. Simulation evidence does
not establish physical calibration or sim-to-real validity.

## Subphase R9.3 — Candidate Decision

#### Implementation

Steam Audio `4.8.1` is selected as the primary existing engine for future
passive geometry-aware propagation. It is the only candidate that satisfies
the blocking core-integration contract: arbitrary audible PCM, separate
phase-coherent microphone signals through the explicit minimal IAS bridge,
dynamic geometry, direct and indirect propagation, relative amplitude, Isaac
runtime execution, source-build packaging, licensing, and complete-block
performance all pass.

The selected version is the qualified official tag `v4.8.1` at commit
`0da18255cca520771f363ee01f100572b39a308e`, built as a Release shared library
with Embree enabled and covered by Apache-2.0. Native Steam direct,
transmission, occlusion, reflection, and dynamic-scene behavior minimizes the
repository-owned algorithm surface. Complete four-microphone block p95 remains
0.30 ms for one environment and 1.15 ms for four; acoustic-refresh p95 remains
11.40 ms and 42.44 ms respectively.

NVIDIA RTX Acoustic `3.0.0` is not selected for this role. Its measured active
`CHIRP`/`AM` transmitter-receiver output does not supply arbitrary passive PCM
or raw physical-microphone channels, and its installed proprietary extension
does not satisfy the required source-build redistribution and licensing gates.
Runtime availability and ecosystem proximity therefore do not make it eligible
for the weighted provider decision.

The unselected NVIDIA adapter, GMO helpers, evidence-reclassification runner,
two-candidate summary builder, and their tests were removed. Historical R9.2
reports and the non-ranking summary remain unchanged under `build/`. The
contract, common fixtures, metrics, report writer, selected Steam adapter, and
Steam runner remain only as internal requalification tooling.

R9.3 registers no public backend and starts no R10 integration. PyRoom remains
the analytic provider rather than an arbitrary-geometry engine. Any future
active-acoustics backend remains a separate role.

#### Key Decisions

- Steam Audio `4.8.1` is the selected primary passive geometry provider for R10.
- A different Steam version requires requalification before replacing the
  selected baseline.
- Steam owns the complex propagation algorithms; the IAS bridge is limited to
  geometric source-to-microphone delay, a shared input timeline, and acoustic
  assembly grouping.
- The selected provider supplies microphone signals; it does not own activity
  detection, DOA semantics, observations, or learning labels.
- Provider research and R10 product integration remain separate phases.
- PyRoom retains its distinct analytic role, and active acoustics remains out of
  scope.

#### Problems / Limitations

Steam's `full_r10_outcome` remains `rejected` solely because two sequential
12 dB partitions measured 18 dB instead of the expected 24 dB. R10 must prefer
one authored whole-assembly transmission curve and must not add post-hoc IAS
gain compensation. IAS may construct a provider-native acoustic proxy and map
evidence-backed assembly coefficients into Steam's supported bands, but it must
not hide a provider limitation with route-dependent attenuation. Additive
sequential-partition behavior remains unclaimed unless R9.4 or a later
requalification passes it. Native pathing, diffraction behavior, and path/ray
diagnostics also remain unqualified.

The selection targets one or a few high-fidelity Isaac environments, not
mass-parallel Isaac Lab execution. R8's analytic path remains responsible for
scalable policy training. Simulation evidence does not establish physical
calibration or sim-to-real validity.

## Subphase R9.4 — Selected-Provider R10 Risk Retirement

#### Implementation

Run a bounded post-selection qualification while the retained Steam harness is
still current. R9.4 executes after the already completed Plan 02.1 and before
Plan 02.2. Phase numbers express ownership rather than mandatory commit order:
the completed signal boundary remains in place, no commit is reverted, and no
public Geometry Acoustics backend, package dependency, schema, or configuration
is introduced.

Begin by checking the latest official stable Steam Audio release. On 2026-09-03,
`v4.8.1` is still the latest published release and remains the reproducible
baseline. An untagged development branch is diagnostic evidence only. If a
newer stable tag exists when R9.4 runs, qualify its exact source commit before
changing the selected baseline; a higher version number alone is not evidence
that the measured limitations are fixed.

First test provider-native acoustic assembly geometry. Steam's current direct
transmission implementation takes the square root of the product of all hit
surface coefficients because it assumes that the two faces of a solid wall are
a pair. Represent each physical wall, door, or panel as one closed or otherwise
paired provider acoustic proxy carrying one whole-assembly material definition.
Verify one, two, and three distinct sequential assemblies, oblique incidence,
thickness changes, and equivalent mesh fragmentation. The existing per-band
tolerance applies. This path is accepted only if one assembly contributes its
authored loss once and distinct assemblies accumulate predictably without
post-render gain correction.

Then exercise Steam's native baked pathing and `IPLPathEffect` with the default
UTD-based deviation model. Use at least an L-corridor and connected rooms with
an opening, compare pathing enabled and disabled, capture the supported path
visualization callback, and exercise dynamic-path validation and alternate
paths. The result must remain useful as one final phase-coherent signal per
physical microphone rather than only as a listener-oriented qualitative mix.
Measure bake time and storage separately from path update and complete audio
block cost.

Recheck direct-path timing through the public provider audio path. Prefer a
provider-native PCM delay if a stable release exposes one. Otherwise retain a
private Steam-adapter scheduler that applies geometry-derived fractional delay
on one shared source timeline, and verify moving geometry, continuity across
audio blocks, microphone-relative timing, and no double application to direct
or indirect output. This is signal scheduling required by the microphone
contract, not a replacement propagation model.

Write a new versioned qualification bundle without modifying the R9.2 rev2
evidence. Remove experiment-only helpers after the decision. Keep the selected
R9 adapter only while it is the smallest active way to reproduce provider
qualification; R10.3 must replace it with the production adapter and delete the
duplicate.

#### Key Decisions

- R9.4 follows completed Plan 02.1 without rewriting Git history and precedes
  Plan 02.2.
- Stable tagged releases are selected; development-branch code is evidence,
  not a production baseline.
- Provider-native acoustic proxies and documented material-band mapping take
  precedence over IAS attenuation algorithms.
- IAS may schedule microphone arrival time when the provider does not render it
  into PCM, but may not infer correction gains from measured provider errors.
- Pathing and approximate diffraction enter R10 only with per-microphone,
  signal-level evidence; a provider feature name is insufficient.
- A failed advanced gate does not undo the R9.3 core-provider selection. It
  narrows R10's supported fidelity and claims.

#### Problems / Limitations

Closed or paired acoustic proxies are a hypothesis derived from Steam's source
behavior, not yet a qualified fix. They must not turn two independent barriers
into one route-dependent synthetic material. Steam pathing uses precomputed
probe data and renders an Ambisonic sound field, so storage, dynamic-scene
behavior, microphone-array coherence, and update cost all require measurement.
If either advanced path fails, R10 must state the limitation and use only the
native direct, reflection, and functional NLOS behavior actually qualified. No
simulation-only result establishes physical material calibration or general
diffraction accuracy.

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
two-candidate coverage without ranking or selection and is preserved as
historical evidence; no maintained generator remains. The selected Steam
source/build remains under `build/qualification/r9/steam-audio`, and its
internal adapter and runner remain available for requalification. No public
geometry backend or R10 integration exists yet.

R9.4 will add a separate versioned selected-provider bundle rather than rewrite
those reports. Its implementation must leave only the minimum active
requalification surface needed until the R10 production adapter replaces it.

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
