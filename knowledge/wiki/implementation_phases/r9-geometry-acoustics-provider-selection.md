# Phase R9 — Geometry Provider Selection

Status: original qualification/selection complete; later R10 admission exposed
reflection/diffuse/NLOS limits. Steam/PRA intermediate retained; no replacement selected.

## Objective

Select maintained external acoustic capabilities for passive robot microphone
signals, with physical timing, explicit dynamic/material limits, practical native
interfaces and redistributable integration. Current task scope is governed by
[[decisions/robot-audition-fidelity|Robot-Audition Fidelity]], not the superseded
absolute dynamic-coverage gate. [[experiments/acoustic-provider-evaluation|Provider Evaluation]]
owns candidate results and sources; [[implementation_phases/r10-geometry-acoustics-integration|R10]]
owns production integration.

## Subphase R9.1 — Required Provider Contract

#### Implementation

Defined a core-integration gate separately from full geometry coverage: arbitrary
passive source PCM, physical microphone outputs, timing/relative gain, materials,
visibility/dynamics, lifecycle, native execution and build/distribution support.
R9.1.1 removed per-source detection waveform claims; R9.1.2 retained physically
honest two-microphone ambiguity. Later Phase 02 replaced source-conditioned frames
with the signal/perception split; current contracts live in
[[topics/public-contracts-and-recording|Public Contracts]].

#### Key Decisions

- Native engine output must support microphones, not only a binaural/speaker mix.
- Core compatibility is not complete acoustic qualification; test native behavior.

#### Problems / Limitations

The historical reflection and NLOS timing assumptions were too strong; R10's
independent references corrected them without modifying archived evidence.

## Subphase R9.2 — Candidate Qualification

#### Implementation

Corrected rev2 reports separate core integration from full R10. Steam 4.8.1 passed
core integration with an explicit arrival/assembly bridge. RTX Acoustic 3.0.0 did
not fit passive PCM or the required source-build distribution. Subsequent bounded
PRA and alternative audits are retained in the experiment record.

#### Key Decisions

Keep failed criteria and unexecuted alternatives explicit; no feature-count ranking
can override a blocking contract failure.

#### Problems / Limitations

Sequential transmission did not pass. Functional reflections or unchanged IR bytes
were not sufficient tests of arrival/TDOA. Simulation does not establish calibration.

## Subphase R9.3 — Candidate Decision

#### Implementation

Selected Steam 4.8.1 Release/Embree for its qualified role. Later reflection timing
failures led to complementary native PRA specular rendering, not replacement of
all Steam behavior. No inspected alternative is a qualified whole-domain provider.

#### Key Decisions

One Geometry producer integrates disjoint native contributions. Steam owns direct/
planar transmission; positive PRA image orders own admitted specular reflections.
Disable failed Steam reflection/PRA diffuse reconstruction in production. Maintain
Analytic. Do not add overlapping full-engine outputs or an implicit third provider.

#### Problems / Limitations

PRA alone lacks required full-provider coverage. A hybrid is not admitted merely
because each engine has useful individual capabilities.

## Subphase R9.4 — Selected-Provider R10 Risk Retirement

#### Implementation

Executed after Phase 02.1 and before 02.2. Verified bounded native probe/path
search, validation/alternates, point-microphone mapping and diagnostics. Rejected
the closed/paired transmission proxy and excluded it from production.

#### Key Decisions

Preserve native search/traversal; private scheduling/interface extensions require
physical requalification. Candidate tools were removed after evidence preservation.

#### Problems / Limitations

The old scheduler/reference used Euclidean distance for NLOS. Its stronger physical
arrival/TDOA claim is withdrawn; selected-route timing fixes remain experimental.
Absolute reflection timing also failed. See
[[experiments/geometry-acoustics-admission|the decisive native controls]].

## Current provider decision

Extend existing Steam/PRA interfaces first. Native route timing is valuable; shared
PRA pressure must pass representative weak-direct motion, not just co-location.
Exact asynchronous histories and later-phase controls are stress diagnostics under
the approved scope. If a material in-domain gap needs a large proprietary multibounce
system, stop before a whole-reflection replacement evaluation and ask the user.
No new provider evaluation or automatic domain reduction is authorized.

## Artifacts

Historical native builds/rev2 reports remain under `build/qualification/r9/`;
later patches, failed PCM and replay recipes are indexed by the two experiment
pages above. Detailed R9 chronology remains recoverable at `5cfe48d`.

## Files

- `tools/native/` — maintained native bridges/selected-route extension.
- `src/isaac_audio_sensors/isaac/acoustic_scene/` — current prepared-scene producer.
