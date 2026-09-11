# Phase R9 — Geometry Acoustics Provider Selection

Status: R9.1 and R9.1.1 completed on 2026-09-01; R9.1.2 completed on
2026-09-02; corrected R9.2, R9.3, and R9.4 completed on 2026-09-03. R9.4 ran
after Plan 02.1 and before Plan 02.2 without reopening the provider decision or
rewriting history.

Follow-up on 2026-09-10: provider selection is reopened for R10.2 physical-array
reflections after native timing requalification failed. Historical R9 artifacts
remain unchanged; their passing scope does not establish this missing capability.
The subsequent coverage audit selects a hybrid architecture direction, but the
executed Steam/Pyroomacoustics candidate fails admission; no replacement signal
provider is qualified for full R10. The intermediate specular provider is admitted
separately; Milestone 2 also withdraws the historical NLOS path-arrival/TDOA
interpretation. The latest user scope revision replaces the absolute dynamic
coverage gate with declared robot-task fidelity qualification; the revised domain
is not yet admitted. The earlier recommendation for a replacement evaluation is
suspended pending measured in-domain materiality. See the scope revision below.

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

R9.1 was executed through a repository-internal validator that was removed
after provider selection and risk retirement completed. The corrected
`r9.1-rev2` contract superseded the original internal report schema. It accepts
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
- The original single-primary-provider preference is superseded by the explicitly
  authorized hybrid comparison below. Keep one public microphone-signal producer;
  admit internal engines by measured complementary coverage.
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

The temporary provider adapters and qualification tooling were removed after
R9.4. Full source, binary, measurement, NPZ, log, crash/build-failure, and
provenance evidence remains local and ignored under `build/`; it is not a
release artifact. Simulation evidence does not establish physical calibration
or sim-to-real validity.

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

All candidate adapters, fixtures, report builders, runners, validators, and
their tests were removed after R9.4. Historical R9.2 reports and the
non-ranking summary remain unchanged under `build/`.

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
gain compensation. R9.4 did not qualify the proposed provider-native paired
proxy, so R10 may use only the previously qualified single planar-assembly
mapping and must not hide the limitation with route-dependent attenuation.
Additive sequential-partition behavior remains unclaimed unless a later
requalification passes it. Native pathing signal/routing and path callbacks were qualified
separately by R9.4 for its measured scenarios; the later Milestone 2 recheck
withdraws the stronger NLOS arrival/TDOA interpretation.

The selection targets one or a few high-fidelity Isaac environments, not
mass-parallel Isaac Lab execution. R8's analytic path remains responsible for
scalable policy training. Simulation evidence does not establish physical
calibration or sim-to-real validity.

## Subphase R9.4 — Selected-Provider R10 Risk Retirement

#### Implementation

R9.4 completed the bounded post-selection qualification after Plan 02.1 and
before Plan 02.2. A live official-tag check immediately before the final run
confirmed `v4.8.1` at
`0da18255cca520771f363ee01f100572b39a308e` as the latest stable release. The
source, Release shared-library build, Embree configuration, and Isaac Sim
`6.0.1-rc.7` / Kit `110.1.2` interpreter all matched the selected baseline.
The runner fails closed before behavioral measurement if any of these gates
changes.

The internal harness maps one whole authored curve to every provider-native
face of a closed paired proxy. Five repetitions covered one, two, and three
sequential assemblies plus oblique incidence, thin and thick variants, and
equivalent fragmentation. Representation invariance passed essentially
exactly, but the acoustic result did not: a 12 dB assembly measured 18 dB in
all three Steam bands, while two and three assemblies measured 30 dB and
42 dB. This misses both the single-assembly tolerance and the required sum of
independently measured assembly losses. No post-render gain compensation was
applied. The `acoustic_proxy_transmission` gate therefore fails and the proxy
is not admitted to R10.

Historical provider-native pathing signal and routing controls pass within their
measured scope; the later Milestone 2 recheck below withdraws physical NLOS
arrival/TDOA qualification. Deterministic probe batches bake dynamic path
data and run `PATHING` with the default UTD deviation model. Each microphone
owns an independent point receiver and `IPLPathEffect`; the effect renders a
non-spatialized first-order Ambisonic field and its omnidirectional component
becomes that microphone's signal. Across both the L-corridor and connected-room
fixtures, all microphones pass five of five repetitions at least 129.32 dB
above the disabled control. Against the historical straight-distance reference,
maximum all-pair TDOA error is 0.391 samples and
minimum realigned correlation is 0.99175. Dynamic validation detects four
occluded segments per repetition, alternate-path search retains nonzero output
with a 3.36 dB level change, and callback capture stays bounded at seven
segments per source/microphone/frame key.

Impulse probes confirm that Steam direct and pathing output omit geometric PCM
arrival time. The reflection control verified byte preservation, not correct
absolute arrival or physical reflected TDOA. The later
[[implementation_phases/r10-geometry-acoustics-integration#Initial complete-path gate — NO-GO (2026-09-10)|08.2 native gate]]
withdraws the stronger reflection-timing interpretation without rewriting these
historical results. A private continuous windowed-sinc scheduler applies geometric delay
once to direct and pathing only, using straight source–receiver distance. The
pathing arrival control used the open connected-room case, not a detour. Against
those original references, maximum direct/pathing arrival errors are
0.475/0.370 samples, split-block and continuous static execution are identical,
moving delay targets introduce no excess boundary step, and reflection samples
remain byte-identical without a second delay.

The diagnostics-off complete-block p95 is 1.865 ms for one environment and
7.416 ms for four; path-update p95 is 5.786 ms and 10.923 ms against 100 ms and
250 ms limits. Each result uses 20 warm-ups plus 200 blocks and 10 warm-ups
plus 50 updates. Bake time is 0.056–0.294 ms and storage is 144 or 300 bytes in
these bounded fixtures; diagnostic overhead is reported separately and is not
a realtime gate.

The ordered `r9.4-v1` report records six passes, one measured failure, no
blockers, and an unchanged R9.3 selection. It historically admitted baked pathing, the private
arrival scheduler, and bounded path diagnostics to future R10 work while
excluding the acoustic assembly proxy. The completed harness added no public
backend, API, configuration, schema, version, or dependency and is no longer
maintained.

#### Key Decisions

- R9.4 preserves the completed Plan 02.1 boundary and R9.3 provider selection.
- A new stable Steam tag, different source commit, non-Release build, or missing
  Embree configuration requires explicit requalification.
- The failed closed/paired proxy is excluded from R10; IAS must not correct its
  measured loss with a gain stage or synthetic route material.
- Baked pathing may enter R10 only with the qualified independent-receiver,
  non-spatialized omnidirectional signal mapping and deterministic probe model,
  plus the physical path-arrival requalification required by Milestone 2 below.
- IAS schedules direct and pathing arrival time once because Steam omits it from
  PCM. Reflection PCM bypassed that bridge in R9.4; this is not an absolute
  reflected-arrival qualification, as the later 08.2 gate establishes.
- Path diagnostics remain bounded optional evidence outside frames and ordinary
  datasets.

#### Problems / Limitations

Closed paired proxies are not a qualified transmission fix. Their invariant
mesh behavior does not compensate for the 6 dB single-assembly excess or the
non-additive two/three-assembly result. R10 may not claim predictable
sequential-assembly transmission from this representation.

The pathing result is limited to the measured scenes, probe topology, default
UTD model, CPU/Embree build, and small environment counts. It does not establish
general diffraction accuracy, mass-parallel scaling, physical material
calibration, or sim-to-real validity. R10 must implement one production binding
and validate it directly against the qualified version, signal, timing,
assembly, pathing, and performance boundaries.

## Provider selection reopened after the R10.2 reflection gate

[[implementation_phases/r10-geometry-acoustics-integration#Reflection timing recheck — NO-GO after reference correction (2026-09-10)|R10.2's executed recheck]]
rules out a delay-only repair of the selected independent-receiver reflection
mapping. Restoring each direct-path delay, increasing simulation order and
increasing sample rate do not recover physical reflected TDOA. R10 owns those
measurements; this section owns the resulting provider decision.

The supported Steam alternatives do not establish a replacement signal path:

- Native order-3 simulation with W-only rendering was exercised and retains
  the failed omnidirectional PCM. Full-channel convolution separately crashes
  in the qualified build; it is not a passing alternative.
- The public Ambisonics decoder rotates and decodes for speakers or binaural
  listening. Custom speaker inputs are unit directions, not displaced microphone
  coordinates. The qualified source's panning effect is a samplewise matrix.
  It does not supply physical array translation. Adding such a renderer would
  require a new acoustic model and qualification, not just selecting an API mode.
  [Native decode API](https://valvesoftware.github.io/steam-audio/doc/capi/ambisonics-decode-effect.html)
- Parametric reverb models decay rather than individual echoes; hybrid retains
  the early convolution IR; TAN accelerates convolution. These modes were
  inspected, not runtime-qualified as fixes. No documented mode here repairs
  the failed early reflection timing.
  [Reflection effect algorithms](https://valvesoftware.github.io/steam-audio/doc/capi/reflections-effect.html)

The bounded replacement comparison is:

| Candidate | Current evidence | Selection boundary |
| --- | --- | --- |
| Pyroomacoustics 0.10.1 | Installed generic polyhedral `Room` passes four equivalent first-reflection arrival/TDOA controls. Its ISM supports per-microphone RIRs. | First candidate for bounded reflection qualification; arbitrary USD, native transmission, dynamic openings/NLOS, streaming and throughput remain unqualified. No full-R10 selection. |
| gpuRIR | Documented CUDA ISM supports many source/receiver pairs, using room dimensions and six wall coefficients. Not installed or executed in this follow-up. | Rectangular-room input does not cover the required general mesh/door domain. GPU speed is not evidence of that coverage. |
| Habitat/SoundSpaces audio engine | Habitat documents mesh input, reflection, diffraction and transmission through RLR-Audio-Propagation. Not executed here. | The underlying engine repository is archived, distributes binaries/headers, and declares CC-BY-NC licensing; it does not satisfy the maintained open-source provider direction. |

Primary references:
[Pyroomacoustics room simulation](https://pyroomacoustics.readthedocs.io/en/stable/pyroomacoustics.room.html),
[Pyroomacoustics source](https://github.com/LCAV/pyroomacoustics),
[gpuRIR API](https://github.com/DavidDiazGuerra/gpuRIR),
[Habitat audio configuration](https://github.com/facebookresearch/habitat-sim/blob/main/docs/AUDIO.md),
[RLR engine distribution and status](https://github.com/facebookresearch/rlr-audio-propagation),
[RLR license](https://github.com/facebookresearch/rlr-audio-propagation/blob/main/LICENSE).
This is a focused comparison, not an exhaustive survey or a legal compatibility opinion.

This timing recheck initially retained Analytic and 08.1 pending the following
whole-domain coverage audit. A passing single-reflector control did not select
Pyroomacoustics as a full provider.

## Architecture decision after the Pyroomacoustics coverage audit

The user explicitly authorized comparison of a primary Pyroomacoustics provider,
another provider, and a hybrid rather than forcing one engine to own every
phenomenon. [[implementation_phases/r10-geometry-acoustics-integration#Provider coverage and hybrid admission gate (2026-09-10)|R10's executed coverage gate]]
owns the fixtures, measured failures and component timings.

**Decision: select option 3 as the architecture direction; reject the current
Steam-direct/Pyroomacoustics-reflection adapter for production.** Pyroomacoustics
alone does not meet essential requirements. None of the inspected alternatives
is a qualified full replacement. Complementary native capabilities justify a
hybrid direction, but combining incomplete models does not establish full R10.
There is currently no admitted definitive adapter, including a hybrid one.

| Criterion | Pyroomacoustics as primary | Another primary provider | Hybrid architecture |
| --- | --- | --- | --- |
| Physical correctness | ISM passes bounded specular controls. No through-wall transmission model; tested planar partition mapping leaks specular paths. | Steam direct/planar transmission remains useful, but its reflection field fails. GSound and RAC are not qualified replacements. | Separates complementary phenomena; the executed combination still leaks reflected sound through a closed partition. No fitted gain can repair path visibility. |
| Inter-microphone timing | ISM passes the four earlier timing controls. RT pressure fails five co-located receiver tests despite identical native energy histograms. | Steam reflection timing fails. RAC's native delay component rounds samples and fails the executed slow-motion arrival test. | Requires a common clock and coherent native contributions. Steam direct delay plus PRA ISM is feasible in the bounded control, not proof of a coherent diffuse field. |
| R9/R10 coverage | Missing transmission; functional reflected NLOS demonstrated in one L corridor, not general diffraction. Full material/scattering domain fails admission. | Steam covers the historical bounded pathing/transmission domain but not the newly required reflection field. No inspected replacement covers all gates. | Can retain Steam's useful direct/transmission/pathing roles and select another reflection renderer. Reflected visibility and diffuse field remain blockers; historical pathing still needs combined qualification. |
| Dynamic scenes | Static RIR recomputation responds to the tested asymmetric opening. General door topology, continuous motion, tails and resets are unqualified. | RAC advertises dynamic image-edge tracing; its public runtime uses wall-clock background work and shared audio state, and the tested delay component loses slow movement. | One scene revision must update every contribution; stale RIRs and independent reset clocks are unacceptable. This lifecycle is not yet qualified. |
| USD / Isaac | Prepared vertices/materials can be translated, but Room's enclosure assumptions do not match arbitrary 08.1 meshes and planar partitions. | Steam reuses qualified 08.1 mesh instances. RAC accepts triangles but needs a new binding and synchronous, isolated receiver lifecycle. | Reuse one `AcousticSceneSession`; translate its geometry to each admitted engine. Do not invent thickness, room boxes or pose jitter to hide unsupported USD. |
| Performance | Native RIR refresh measured at 2/16 copies; generic ISM cost and reconstruction grow with geometry/order. This is not a streaming/Lab benchmark. | GSound's attempted Python 3.12 build fails; RAC full-runtime cost is unmeasured. Prior Steam timings cannot rank these replacements. | Includes scene duplication, simulation, rendering and mixing costs. Correctness currently stops scaling/GPU optimization; no end-to-end advantage is established. |
| Complexity / maintenance | Existing optional dependency, but full coverage would require native/model changes, not just an adapter. | GSound's published distribution terms and build failure prevent admission. RAC would require temporal and lifecycle work beyond a thin binding. | Prefer a fixed, explicit split behind one producer, with each engine justified by a passing capability. Higher internal complexity is accepted only for actual coverage, not speculative fallbacks. |

**Concrete split to qualify.** Steam owns direct occlusion and bounded planar
transmission, with the existing continuous arrival bridge applied once. A
separate native renderer owns coherent reflected pressure; PRA ISM remains a
candidate only for its bounded specular role. Diffuse scattering and indirect
pathing must have explicit ownership and passing spatial/temporal tests. Do not
mix full outputs from both engines: the local candidate selects strictly positive
PRA image orders and disables Steam reflections. Any eventual pathing split must
also prove that the same physical contribution is not counted twice.

The public boundary remains `GeometryAcoustics.propagate(...) ->
MicrophoneSignalBlock`, feeding unchanged audio-only perception and Lab tensors.
Prepared geometry, source time, units, sample count and reset ownership are
shared; provider internals remain private and lazy. This is an architecture
constraint, not a newly registered backend or a generic plugin framework.

**Alternative admission limits.** The checked GSound/pygsound distribution
restricts commercial use and third-party redistribution; the local build also
fails with its bundled pybind11 on Python 3.12. No PCM qualification was reached.
[Published terms](https://github.com/GAMMA-UMD/pygsound/blob/8f41cb13da5dba9aa09cac3f42e668005ed5cf11/LICENSE.txt).
RoomAcoustiCpp at `241be79` is LGPLv3 according to its checked repository license,
superseding older website GPL wording. It provides image-edge diffraction and a
mono mode, but its native 3DTI waveguide fails the executed motion control; shared
global audio-pool ownership and asynchronous scene work also need integration
changes. Only that component was compiled/tested, not the full RAC runtime.
[Repository and models](https://github.com/IoSR-Surrey/RoomAcoustiCpp),
[checked license](https://github.com/IoSR-Surrey/RoomAcoustiCpp/blob/241be79a07de4aeeb3d8f08ddfaa01b895b89712/ROOMACOUSTICPP_LICENSE).

**Consequence at the coverage audit, superseded for the later intermediate milestone.** Keep the executable hybrid qualification adapter
and failing PCM locally, but do not promote it or narrow R10 silently. Admission
requires native reflected visibility across the allowed partition/door topology
and a coherent diffuse receiver field. A provider correction/replacement must
pass those controls before streaming lifecycle, common perception, Isaac and
full scaling work resumes. Analytic and the qualified 08.1 scene service remain
operational. No SDK fork, repository-owned reflection solver, production GPU
implementation or definitive Geometry adapter is delivered by this decision.

## Intermediate specular architecture (2026-09-10)

The user authorizes an intermediate milestone without reducing final R10 scope.
Its implementation selects **Steam direct/planar transmission plus PRA native
specular image sources**. Neither rejected diffuse reconstruction is enabled.
Native path ownership is disjoint: Steam owns the direct branch; strictly
positive PRA image orders own reflections, including bounded reflected NLOS.
The maintained scalar and CUDA perception consume only the resulting PCM.

A separate optional C ABI bridge compiles PRA 0.10.1's existing engine with four
bounded corrections: allow standalone reflecting polygons, reject zero-length
consecutive bounces, block paths crossing perpendicular partition junctions,
and assign shared coplanar polygon-edge reflections to one face. No replacement
ray solver is implemented. Original USD faces are reconstructed from the 08.1
triangulation; nonplanar faces retain their actual triangles. Both surface sides
are represented. Native tests cover the previous closed-door leak and the
otherwise doubled reflection exactly on a tessellation edge. The installed PRA
used by perception and the qualified Steam SDK remain unchanged.

This is a bounded native correction, with an explicit source/version/build
requirement, rather than evidence that unmodified PRA covers all R9. The adapter
uses native fractional-delay kernels and material filters, per-path source and
microphone directivity, a common sample clock, and bounded source history.
Scene changes crossfade responses on that clock; motion is a quasi-static
approximation, with a 0.1 m/s direct-phase control. This does not qualify general
Doppler, rapidly moving reflectors, or retarded interaction times at a moving door.

The independent diffuse-field gate remains mandatory for final closure. Full
pathing/diffraction coverage, broader dynamic qualification, installation and
full scaling decisions also remain open. Analytic stays operational. Exact
implementation, measured acceptance and installation commands belong to
[[implementation_phases/r10-geometry-acoustics-integration#Intermediate coherent propagation milestone (2026-09-10)|R10's intermediate milestone]].

## Milestone 2 native coverage decision (2026-09-10)

**Complete coverage remains blocked; intermediate production stays admitted.**
[[implementation_phases/r10-geometry-acoustics-integration#Milestone 2 complete acoustic coverage — blocked (2026-09-10)|R10 owns the new native measurements and acceptance correction]].
The five-repeat corridor recheck demonstrates that the archived R9.4 bridge uses
straight-line distance for NLOS output. The physical detour-arrival and TDOA
interpretation is withdrawn without changing the original reports. Native
validation/alternate search and the direct-path fractional scheduler retain only
the behavior actually established by their controls.

The diffuse investigation executes native PRA reconstruction with independent
and shared random seeds. Neither provides the required joint field over distinct
microphone positions. Steam's energy-bin reconstruction and its aggregated public
path effect also discard information needed for independent temporal contributions.
No seed, global delay, post-render gain, independent-noise tail or unconditional
sum of provider outputs is admitted as a physical repair.

Additional alternatives were inspected before stopping:

| Candidate | New evidence and admission boundary |
| --- | --- |
| TASCAR at `2e8b8b19b52a029af536383bfd59de2ee66db882` | The native `mic_t::process_diffuse` uses `W + X*nx + Y*ny + Z*nz`, with microphone position normalized to a direction. It bypasses the point-source delay processor. The exact method, compiled with buffer-only test stubs, gives identical output for positions `(0.02,0,0)` and `(0.10,0,0)` m. This rejects that native diffuse microphone renderer as a replacement for arbitrary physical omni arrays. The full runtime was not built or tested; this is not a rejection of every possible TASCAR configuration. |
| PFFDTD at `aa319f6c86517cb95aabfae8656277da62c3ead5` | A promising independent wave-based reference with multiple receiver outputs, CUDA and frequency-dependent impedance boundaries. Inspected setup serializes voxel boundaries and fixed source/receiver indices into HDF5; the engine time loop uses those arrays. No retained-field moving-geometry interface was found in that path. Continuous dynamic USD and the existing scattering/transmission authoring contract need separate model/integration work. Not run, not acoustically rejected, and not a qualified full replacement. |
| DynamicSound, arXiv `2601.15433v1` | Its published model covers continuous moving sources/arrays, propagation delay and first-order planar reflections. The paper explicitly excludes occlusion and diffraction. It does not resolve the required complete indirect/diffuse domain; no runtime claim is made. |

Sources: [TASCAR native microphone renderer](https://github.com/HoerTech-gGmbH/tascar/blob/2e8b8b19b52a029af536383bfd59de2ee66db882/plugins/src/receivermod_micarray.cc),
[PFFDTD source](https://github.com/bsxfun/pffdtd/tree/aa319f6c86517cb95aabfae8656277da62c3ead5),
[DynamicSound paper](https://arxiv.org/html/2601.15433v1).
Prior GSound distribution/build and RAC native temporal limits remain recorded
above; they are not presented as newly repeated measurements.

**Required architectural work.** Retain the hybrid producer interface, but obtain
joint pressure or individually timed native contributions before energy/path
aggregation. This requires a substantive provider renderer extension or a newly
qualified provider; it is beyond the bounded specular ABI/visibility corrections
already admitted. R10 does not authorize replacing external scattering/path search
with an IAS propagation solver. A maintained provider-development workstream must
establish that missing model and its physical evidence before another integration
attempt can claim complete coverage. This is not a claim of universal impossibility.
Final requirements and the coverage-before-scaling sequence remain unchanged.

#### Existing-provider extension decision (2026-09-11)

The authorized Steam/PRA native extensions were implemented before considering
another provider. Steam's experimental selected-route interface removes the
public aggregation barrier and passes bounded route-delay/visibility controls.
It does not yet qualify complete production pathing integration. PRA's native
joint-event renderer and transport iterations improve stationary spatial pressure
and bounded door visibility, but fail the moving-source field control: ray hit
locations carry the stochastic phase and move with the source. A 1 cm movement
normal to a diffuse plane gives about 0.687 complex-coherence error at 4 kHz against
a fixed-surface reference, converging to the same error as ray count increases.

This failure is not repaired by the admitted polygon fixes, response caching,
per-ray RNG, or more rays. A physically persistent field requires material-anchored
scattering state, source illumination, multibounce transport and receiver sampling
with common timing/visibility. Whether to undertake that larger native transport
redesign or evaluate another maintained provider is now a user decision. The run
stops before any new provider evaluation; it neither selects a replacement nor
claims that extending PRA is universally impossible. No IAS propagation solver or
scene-specific compensation is introduced.

The existing hybrid remains the working production intermediate. R10's complete
dynamic diffuse/NLOS domain and downstream robot-audition usefulness are not
reduced to the passing components. Final scaling remains deferred. The failed PRA
native patch and executable controls remain isolated local evidence; the optional
Steam interface/build tool is retained for further native work. Exact implementation,
results and replay are owned by
[[implementation_phases/r10-geometry-acoustics-integration#Milestone 2 native extensions — dynamic-field blocker (2026-09-11)|R10's native-extension gate]].

#### Targeted usefulness follow-up (2026-09-11)

The user authorizes measuring the observation impact before a broader native
redesign or replacement evaluation. The controlled follow-up establishes that
corrected NLOS delays improve arrival-direction interpretation, and that the
moving-ray diffuse field can substantially bias weak-direct moving-source
observations. Strong-direct and competing-source cases show that this effect is
selective; realism does not universally improve localization scores. The evidence
supports targeted further work without selecting another provider.
[[implementation_phases/r10-geometry-acoustics-integration#Targeted NLOS and observation-sensitivity follow-up (2026-09-11)|R10 owns the paired measurements, native renderer, dynamic interception limit and validation]].
Production admission, persistent PRA transport versus replacement, and full R10
closure remain separate decisions/gates. No new provider evaluation was started.


#### Dynamic extension feasibility follow-up (2026-09-11)

The authorized minimal-extension experiment fixes selected-flight Steam timing
and interception, but a two-gate control exposes missing time-dependent route
discovery. Further Steam graph/search work remains necessary independently of
any reflection-provider decision.

For PRA, fixed first-scatter anchors plus native ISM/RT pass a bounded plane
reference without gain fitting. A moving specular mirror shifts the next
scattering realization on a stationary floor; the resulting covariance error
persists under ray-count refinement. First-hit anchoring is therefore not a
general solution for the required dynamic domain. Generalization would need
persistent state and consistently weighted transport at later interactions,
not just the retained PRA traversal or a seed/cache adjustment.

The recommended next decision is whether to authorize a bounded evaluation of a
maintained replacement for the **whole reflection subsystem**, compared against
the established intermediate behavior and these failed controls, before taking
ownership of a larger PRA transport model. This is not a selected replacement,
proof that another provider meets the contract, or authorization to add a third
permanent reflection contribution. No new provider evaluation began. Native
Steam direct/pathing and Analytic remain separate maintained capabilities.
[[implementation_phases/r10-geometry-acoustics-integration#Dynamic NLOS and minimum PRA extension follow-up (2026-09-11)|R10 owns the implementation, evidence and remaining gates]].

#### Robot-audition scope revision (2026-09-11)

The latest user direction changes the decision criterion from absolute dynamic
acoustic coverage to material observation/task impact in a declared indoor robot
domain. This supersedes the earlier automatic escalation from the two-gate or
later-scatter phase failures to a larger native redesign or replacement study.
The evidence remains valid; those controls alone no longer decide architecture.

Retain corrected native NLOS timing and qualify bounded dynamic updates. Evaluate
PRA spatial/temporal statistics and representative weak-direct room/task behavior
before deciding whether a more persistent field model is necessary. The measured
large weak-direct observation bias cannot be waived for a claimed supported
condition, but a single-plane phase failure does not prove universal task failure.
Keep the working intermediate and Analytic; admit no experimental contribution
merely because the scope changed.

The previous recommendation to evaluate a whole-reflection replacement is
suspended pending this materiality assessment. If an important in-domain gap
cannot be closed with maintainable existing-provider extensions, bring that
measured failure and the expected benefit/cost to the user before evaluating a
replacement. The alternative remains a whole-subsystem comparison, not an
additional permanent reflection layer. No new provider evaluation is authorized
or performed by this scope revision.
[[implementation_phases/r10-geometry-acoustics-integration#Active scope — Robot-audition fidelity (2026-09-11)|R10 owns the active domain, requirements and qualification protocol]].

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
source/build remains under `build/qualification/r9/steam-audio`. A provider
upgrade requires a new bounded qualification through the production
integration. The later intermediate hybrid is described above; these historical
artifacts do not qualify its final R10 coverage.

The separate ignored R9.4 bundle lives at
`build/validation/r9/r9.4-v1/steam_audio/`. It contains the ordered report,
derived evaluation, measurements, deterministic signal NPZ, provenance,
fixture manifest and USDA/WAV inputs, and run log. All 95 pre-existing R9 files
retain their aggregate SHA-256 baseline; no R9.2 artifact was rewritten.

## Files

- `src/isaac_audio_sensors/core/types/`
- `src/isaac_audio_sensors/core/backends/analytic.py`
- `src/isaac_audio_sensors/core/doa/ambiguity.py`
- `src/isaac_audio_sensors/lab/audio_array_sensor.py`
- `src/isaac_audio_sensors/kit/configuration.py`
- `src/isaac_audio_sensors/schemas/audio_sensor_frame.v2.schema.json`
