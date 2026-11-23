# SquadBot Phase 7 — SDK Audio Runtime Readiness

## Objective

Establish a reusable listening configuration for a downstream robot trial. This phase follows the consumer's Phase 7 roadmap. The SDK's [[implementation_phases/07-isaac-lab-observation-integration|Phase 07]] separately introduced the Lab observation interface.

## Subphase 7.1 — Compatibility and operating envelope

#### Implementation

Exercised the supported Isaac Sim 6.0.1-rc.7, Isaac Lab 3.0.0 and RTX 4090 combination. Extended the received-PCM evaluator to compare scalar and CUDA activity, event counts, and directions on the same mixtures. Compared stationary, moving-source, rotating-receiver, reverberant, and competing-voice cases. [[experiments/consumer-audio-operating-envelope|Protocol and baseline results]]

#### Key Decisions

Scored complete sets of active directions, including missed and extra events. Used source poses and isolated signals only for independent scoring. Kept the activity threshold, estimator, and observation capacity independent of the expected number of sources.

#### Problems / Limitations

The original 750 ms WPE profile followed a moving source better than a rotating receiver. A room window also showed a scalar/CUDA count discrepancy. This assessment established an operating envelope and motivated shorter context. It left live delivery under load open.

## Follow-up to 7.1 — Dynamic audio quality

#### Implementation

Corrected direction matching to maximize the number of valid pairs before minimizing angular error. Exposed localization context and WPE selection in the scalar pipeline and both Lab bindings. Defaults retained the original 750 ms WPE path. [[experiments/consumer-audio-dynamic-quality|Matched controls and independent confirmations]]

#### Key Decisions

Selected 200 ms direct covariance for single-voice free-field trials. Retained 250 ms WPE as an experimental room alternative. Measured response using the original timestamps and scored current directions.

#### Problems / Limitations

Shorter context improved rotating-receiver results. Two 3 m confirmations remained below 90% complete sets. Some direction fits lagged by 130–140 ms, and WPE was expensive at live update rates.

## Follow-up to 7.1 — Indoor event quality

#### Implementation

Added optional spatial-coherence filtering before the sparse direction fit in scalar and CUDA perception. Froze a 200 ms, no-WPE profile with a 0.98 coherence threshold, then evaluated it on different episodes. [[experiments/consumer-audio-indoor-quality|Indoor selection, confirmation, and failure cases]]

#### Key Decisions

Kept coherence filtering opt-in and preserved observation clocks, masks, ambiguity, and capacity. Included a weaker second speaker in evaluation so attenuation of real sources remained visible.

#### Problems / Limitations

The filter removed room reflections and improved single-voice quality. It also suppressed valid overlapping speech. Its use is qualified only for the documented single-voice conditions.

## Subphase 7.2 — Delivery latency and throughput

#### Implementation

Added a CUDA benchmark that measures acquisition, observation delivery, startup, reset, and environment scaling under a declared camera and physics workload. Reused fixed microphone axes and simplified identity mounts. Compared the optimized and reference paths on the same inputs. [[experiments/consumer-audio-runtime-performance|Workload, clocks, and scaling measurements]]

#### Key Decisions

Measured sustained delivery against wall-clock deadlines in addition to SDK compute time. Assessed rendered rollout and interactive use separately.

#### Problems / Limitations

The initial free-field profile met the 10 Hz delivery target under the qualified 30 Hz camera load. The 60 Hz camera stress case accumulated delay. Rollout scaling leaves optimizer throughput and multi-robot training open.

## Integration on main — 2026-10-14

Combining indoor quality and runtime improvements preserved the observed outputs on three replayed room episodes. The integrated native-room probe still failed the delivery criterion. The original fresh-branch count discrepancy could not be replayed from the retained inputs. [[experiments/consumer-audio-runtime-performance#Integrated native-room probe — 2026-10-14|Replay and failed probe]]

## Follow-up to 7.2 — Combined first-scene indoor readiness

#### Implementation

Pruned redundant native visibility queries, initialized DSP before acquisition, captured the single-array solver dispatch, and aligned centroid boundary reductions with Core. Enabled the existing native effects chain on the Lab Geometry path. A six-face acoustic envelope preserved the tested pressure samples while the solid room continued to render.

#### Key Decisions

Qualified delivery and directional quality in the same loaded trial. Used moving Geometry, one voice, one planar array, an Alex articulation, 64 moving rigid bodies and 15 Hz RGB/depth. The source, camera rate and acoustic room representation are part of the qualification. [[experiments/consumer-audio-runtime-performance#Combined indoor qualification — 2026-10-14|Combined indoor results]]

#### Problems / Limitations

The earlier 30 Hz indoor workload failed the timing criterion. The optimized 15 Hz workload passed both gates. Other rooms, body acoustics, weak or overlapping voices, and physical transfer require independent evidence. Downstream users own the actual head mount, channel order, queue, and policy. [Consumer roadmap](https://github.com/PatrizioAcquadro/squadbot-av/blob/main/knowledge/wiki/implementation_phases/phase-7-audio-runtime-readiness.md)

## Artifacts

- The optional indoor trial recipe and its room are maintained under `examples/isaac_lab/`. The [[topics/isaac-lab-integration|Lab guide]] owns the interface.
- Baseline and dynamic-quality inputs live under `local/sdk-runtime-readiness/`, `local/sdk-dynamic-quality/`, and `local/sdk-dynamic-confirmation/`. The linked experiments give commands and identify which captures remain available.
- The original indoor and runtime experiments used ignored outputs in separate worktrees, identified at integration by `fbf8` and `4231`. See the historical version of this page at `dc7ed2b` for their exact locations. Main's integrated probe is recorded under `build/validation/main-branch-integration-20261014-01/`. Later qualification used fresh live PCM.

## Files

The main implementation areas are `src/isaac_audio_sensors/core/plugins/`, `src/isaac_audio_sensors/lab/`, and the native specular provider. The reusable scoring and performance tools live under `tools/validation/`.
