# SquadBot Phase 7 — SDK Audio Runtime Readiness

Status: 7.1 complete as a bounded compatibility and quality assessment; 7.2
measured and qualified for the initial CUDA free-field profile under its declared load.
The dynamic-quality follow-up delivers a bounded free-field profile; full
dynamic readiness remains open.
Phase 7 identifies the downstream SquadBot roadmap; the SDK's
existing Phase 07 — Isaac Lab Observation Integration retains its own scope.

## Objective

Establish a usable audio configuration for closed-loop attention and learning
before downstream robot integration. Build on the existing SDK through focused
readiness assessment and optimization. SquadBot motivates this work; improvements
must remain reusable across consumers, robots and microphone arrays.

## Subphase 7.1 — SDK compatibility and operating envelope

#### Implementation

Verified SDK 3.0.0 on the local Isaac Sim `6.0.1-rc.7` / Isaac Lab `3.0.0`
checkout (`2e44ddb2e1`) and RTX 4090. The host gate passes 672 unit/contract,
352 integration and 56 release tests; the supported Isaac lane passes 251 tests.
Actual Sim with Geometry providers and Lab square-array acquisition at 60 Hz /
10 Hz observations pass their live gates. This identifies one verified local
runtime, not compatibility with every Sim/Lab release.

Extended the maintained received-PCM comparator with explicit layout/input
selection, finite aligned input checks, per-window rows, received-onset responses,
audibility sensitivity and active-only quality summaries. Stationary defaults
remain unchanged. The retained 36-input comparison preserves all activity/count
updates; direction-difference p95 remains below 0.000175 degrees.

The new screen contains 18 eight-second natural-speech episodes: static source,
moving source, rotating receiver, joint motion, joint motion in a simple Geometry
room, and joint motion with a stationary competing voice. The nominal planar
array uses XY offsets at +/-33 mm, 16 kHz, 60 Hz acquisition, 100 ms observations,
an explicit -60 dBFS Auditok threshold, 750 ms localization context, 32 observation
slots and two candidate slots on CUDA; the scalar reference remains uncapped. Source speed reaches 1 m/s and receiver yaw speed
90 degrees/s; distances are 1.5, 2.25 and 3 m. Evaluation uses identical received
mixtures for scalar and CUDA perception; private poses/stems enter scoring only.

[[experiments/consumer-audio-operating-envelope|Operating-envelope evidence]] owns
the detailed protocol, results and reproduction commands. Migration guidance is
in [[decisions/product-boundary-and-compatibility#Consumer readiness migration|the compatibility decision]].
Dependency adoption and adapter changes remain downstream.

#### Key Decisions

Keep the current localizer, precision, thresholds and public contracts. This
assessment introduces no tracker, smoothing, source-conditioned observation or
new acoustic engine. Capacity remains independent of expected source count.
Evaluate complete event sets and missing/extra events; silence, a correct onset
or numerical agreement cannot substitute for continuous directional quality.

Use the measured free-field, fixed-receiver profile as a provisional listening
configuration. Its active complete-set rates are 97.9% for static speech and
96.8% for the moving-source screen. These finite cases support further bounded
consumer trials; they do not establish population reliability or real-time use.

#### Problems / Limitations

Rotating-receiver quality remains insufficient: active complete sets are 49.7%,
59.9% with joint motion, 34.2% in the room screen and 49.3% with a competing voice.
The room screen has incorrect-set sequences up to 2.2 s. No dynamically reliable
closed-loop listening configuration is delivered for the full requested domain.
The unchanged localizer's temporal problem remains open; research is not
automatically reopened by this assessment.

The dynamic scalar/CUDA gate passes: activity agreement 100%, count agreement
1439/1440 (99.93%) and retained-direction difference p95 0.000018 degrees.
One room-window count difference remains documented within the existing 97%
preservation gate; it is not exact numerical identity. No production defect
requiring a correction was established in this subphase. The initial missing
Auditok runtime path was corrected through the existing isolated dependency
setup, without changing the package or Isaac installation.

Warm-up, uncertainty and received reverberant tails remain explicit. The room
screen measures the existing base Geometry renderer at 60 Hz, not an independent
moving-room pressure reference or physical transfer. Wall-clock latency, rendering
load and learning throughput belong to 7.2; smoke/replay timing is not that result.

## Follow-up to 7.1 — Dynamic audio quality

#### Implementation

Corrected received-direction matching to maximize valid pair cardinality before
total angular error; the original 7.1 artifacts remain intact. The retained
750 ms context has a diagnostic past-direction fit of 360–420 ms in rotating
single-voice episodes, distinct from compute and delivery cost. Quality continues
to use current directions and original timestamps.

The SDK now accepts an explicit `MaintainedEventLocalizer(context_duration_s=...,
dereverberation_enabled=...)`, and Lab `localization_context_s` plus
`localization_dereverberation` in both bindings. Defaults remain 750 ms WPE and
stereo/other-rate single-event roles remain 250 ms. Mixture history/readiness and
CUDA slicing use the configured duration, preserving clocks, masks, resets and
source-independent event discovery. The received-PCM evaluator reports active
error-run durations/frequency, initial versus already-acquiring onset responses,
diagnostic direction lag, context readiness and accumulated serial replay cost.

#### Key Decisions

Initially select 250 ms WPE/group-sparse context on six episode-zero selection cases.
Compare short contexts (150/200/250 ms), recent covariance after longer WPE, and
a no-WPE ablation. 150 ms and recent-covariance variants reduce lag but lose
static/room robustness; the no-WPE variant fails room quality. The selected
250 ms variant exceeds 90% active complete sets in each selection condition;
independent validation and supported-profile disposition are recorded separately.
The isolated live check exposes WPE's approximately 118 ms update cost. Retain
250 ms WPE as an experimental room alternative and select a faster 200 ms
direct-covariance free-field profile from the same selection cases. A 150 ms
direct profile loses robustness on independent phrases. Confirm the frozen
200 ms choice on 15 additional episodes, separately from the 39 room/motion
controls already inspected. No threshold or solver shortcut is adopted.
No source identities, private poses, motion input, tracking or time correction
enter observations. The existing WPE, fitting and ambiguity rules are retained.

#### Problems / Limitations

The [[experiments/consumer-audio-dynamic-quality|separate follow-up evidence]]
retains the original 18 episodes, 39 matched controls and 15 fresh confirmations.
The direct 200 ms profile reaches 92.5–95.7% complete sets per confirmation
scenario, 200 ms source-correct onset p95 and no active error runs >=.5 s.
Two 3 m episodes remain below 90%; no uniform or population guarantee follows.
Static quality remains strong. Room/competition remain unqualified; WPE 250 ms
helps room quality but costs about 118 ms per live update. Direct 200 ms costs
about 32 ms p95 in the small live check, with scalar/CUDA preservation and reset.

Directional lag approaches 100 ms but reaches 130–140 ms in some fits. The
approximately 100 ms target is separate from correct-set rates and cannot be
satisfied by shifting estimates into the past. Host/Isaac gates pass; full
readiness is not closed by measured replay completion. Loaded acquisition,
rendering, delivery latency and multi-environment throughput remain in 7.2.

## 7.2 — Latency and learning throughput

#### Implementation

Added a live, worktree-verified CUDA benchmark with exclusive GPU locking,
external-load monitoring, per-update latency/deadline rows, onset response,
startup/reset measurements and environment scaling. The first clean loaded
baseline passes the 50 ms SDK p95 target but accumulates scheduling delay at
9.56 observations per real second; this is not an interactive qualification.
The [[experiments/consumer-audio-runtime-performance|performance experiment]] owns
the workload, clock definitions, detailed evidence and reproduction procedure.

The measured geometry cost motivates skipping zero mount translations and
identity quaternion multiplication while retaining normalization. Cache the
constant local microphone directivity axes on CUDA instead of recomputing and
transferring constants every acquisition. Custom mounts and runtime orientations
retain the complete transform; localizer, thresholds and observation contracts
remain unchanged. Exact CUDA transform controls and 73 focused runtime,
observation and batched-perception tests pass.

Four clean 30-second runs sustain 9.983–9.988 observations per real second with
60 Hz acquisition/physics, 64 moving rigid bodies and a shared 640x480 camera at
30 Hz. SDK p95 is 32.86–33.68 ms, returned-active p95 34.98–36.86 ms, with no
lost windows, discontinuities or persistent scheduling growth. First active
calls cost 68.75–83.35 ms and are retained separately. The 60 Hz rendering stress
case does not sustain the deadline. Exact PCM/all-field before/after comparison
and 265 actual-runtime tests preserve contracts and quality content.

Unpaced 1/4/16-environment runs measure 1.053 / 4.273 / 16.635 aggregate simulated
seconds per real second under the 60 Hz shared-camera load. This is measured
rollout cost, not policy/optimizer throughput or a promised training-scale gate.

#### Key Decisions

An interactive configuration need not use the most expensive acoustic path or
the settings used for every training episode. Choose useful operating profiles
from measured quality and cost. Do not presume that this work requires a
large-scale GPU rewrite; revisit training scale when the workload is concrete.

Reusable changes belong in the SDK. Robot-specific configuration, application
queues and scheduling, task behavior, partner-classifier latency and policy
training remain downstream responsibilities.

#### Problems / Limitations

CUDA events and fenced wall timings remain available, but this Kit process owns
a CUPTI subscriber and PyTorch's kernel/copy profiling can be unavailable. Missing
device trace events are not zero transfer cost. Geometry native propagation stays
CPU-side; a short retained indoor-stage run reaches only 6.45 observations per
real second despite SDK p95 within 50 ms. It does not qualify. After integrating
indoor changes, repeat the measurements with the
selected localizer, native producer and scene; this profile does not qualify them.

## Outcome and handoff

Provide a measured audio configuration, any necessary reusable SDK improvements,
and documented compatibility, quality and performance limits. The consumer then
adopts the selected revision/configuration and verifies its own observation path
before robot simulation integration.

Downstream scope and adoption work:
[SquadBot Phase 7](https://github.com/PatrizioAcquadro/squadbot-av/blob/main/knowledge/wiki/implementation_phases/phase-7-audio-runtime-readiness.md).

[[decisions/product-boundary-and-compatibility|SDK ownership and compatibility]] ·
[[index|Wiki index]]

## Artifacts

The [[experiments/consumer-audio-operating-envelope|7.1 assessment]] owns measured
results and reproduction. Ignored PCM/preparation is in
`local/sdk-runtime-readiness/`; reports and runtime gates are in
`build/validation/sdk-readiness-7.1/`.
The [[experiments/consumer-audio-dynamic-quality|dynamic follow-up]] owns new
measurements under `build/validation/sdk-dynamic-quality/`; inputs/scripts are
retained separately under `local/sdk-dynamic-quality/` and
`local/sdk-dynamic-confirmation/`.
Separate 7.2 results and reproduction are in
[[experiments/consumer-audio-runtime-performance|runtime performance evidence]],
under this worktree's ignored `build/validation/runtime-performance/`.

## Files

`tools/validation/lab_perception.py`,
`src/isaac_audio_sensors/core/plugins/multisource.py`,
`src/isaac_audio_sensors/lab/_torch_localizer.py`,
`src/isaac_audio_sensors/lab/audio_array_sensor_cfg.py`,
`tests/integration/test_lab_perception_scoring.py`,
`tools/smoke/live_isaac_lab_audio_smoke.py`,
`tools/validation/audio_runtime_performance.py`,
`src/isaac_audio_sensors/lab/entity_binding.py`,
`src/isaac_audio_sensors/lab/_entity_audio.py`.
