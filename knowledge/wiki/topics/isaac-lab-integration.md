# Isaac Lab Integration

## Runtime Initialization

`import isaac_audio_sensors.lab` is safe before Isaac Lab and does not load Torch, USD, Omniverse, or Isaac Lab. Initialize `AppLauncher` before resolving exported Lab classes. `AudioArraySensorCfg` directly inherits current `SensorBaseCfg`; `AudioArraySensor` directly inherits `SensorBase`. There are no fallback classes or legacy runtime paths.

## Configuration

`AudioArraySensorCfg` retains inherited `prim_path`, `update_period`, and `debug_vis`, plus backend, effects, speed of sound, and analytic solver settings. It defaults to `analytic_acoustics`, `max_observations=1`, `max_doa_candidates=2`, and `doa_enabled=False`. Both capacities accept non-negative integers, including zero, and reject Booleans. Capacity does not select an estimator or imply multiple-source resolution.

`energy_threshold_dbfs` must be finite and is required by both bindings. Entity audio now supports activity and optional 16 kHz planar/3D DOA on CUDA. The active `SimulationContext` is the device authority. `debug_vis=True` fails because the sensor has no visualization implementation.

## Observation Contract

`AudioArraySensorData.from_observations(observations, *, max_observations=1, max_doa_candidates=2, device=...)` accepts one ordered sequence of `AudioObservation` values per environment. It accepts no frames, snapshots, truth, source state, or free-form diagnostic maps. The scalar reference packs observations on the host and transfers each tensor to the requested device; this is not the scalable CUDA perception path.

With `N` environments, `E` observation capacity and `K` candidate capacity:

| Fields | Shape | Dtype / meaning |
|---|---|---|
| `observation_mask` | `[N,E]` | Boolean; an observation occupies the slot |
| `doa_mask` | `[N,E]` | Boolean; a DOA result exists, including unresolved results |
| `detection_score`, `bearing_deg`, `elevation_deg`, `bearing_confidence` | `[N,E]` | Finite float32, each with its own `<name>_mask` |
| `candidate_bearing_deg`, `candidate_elevation_deg` | `[N,E,K]` | Finite float32, each with its own `<name>_mask` |
| `ambiguity_mask` | `[N,E]` | Boolean; DOA declares `ambiguity_class`, including unresolved conditions |
| `observations_truncated` | `[N]` | int64; observations omitted beyond capacity |
| `candidate_bearings_truncated`, `candidate_elevations_truncated` | `[N,E]` | int64; candidates omitted for each retained observation |

All unused values, masks, and counts are zero. Masks, not numeric zero, determine availability. A missing detection score is distinct from score zero; `bearing_confidence_mask` is true only when the DOA carries a numeric confidence, including zero; it is false for `None` independently of direction availability. Confidence remains estimator-local reliability, not probability. Scores retain their producer semantics without clipping or normalization.

The pre-07.2 frame-v4 correction resolves the unavailable-as-zero defect. CPU and actual RTX 4090 projection tests distinguish absent confidence, measured zero and nonzero scores. [[topics/public-contracts-and-recording|Public Contracts and Recording]] owns serialization and compatibility.

An absent observation, an observation with no DOA, an unresolved DOA, and a selected direction have distinct masks. An unresolved result never selects a candidate bearing. Ambiguity candidates describe alternatives for one observation, not additional sources. Bearing and elevation candidate axes are independent and carry no inferred pairing. The projection preserves selected values and declared ambiguity rather than applying a second direction policy.

Core bearings use the 0–360-degree convention. CUDA event discovery sorts by normalized bearing, then elevation, before capacity truncation; projection uses the same angle convention. The 2026-09-10 closeout corrects an earlier signed-angle CUDA conversion that could select a different capacity-limited prefix.

Projection preserves observation and candidate order and retains only the capacity-limited prefixes. Truncation counts refer to the supplied observations, not upstream omissions or the number of physical sources. Candidate counts apply only to retained observations. Values written to float32 tensors must be representable and finite; invalid values fail explicitly. Zero capacities and zero-environment batches are supported.

The old `event_presence`, `confidence`, `sector_onehot`, and per-event `per_mic_rms` fields are removed without aliases. Allocation no longer takes a microphone count. Observations contain no per-event RMS, and aggregate mixture RMS is not copied into observation slots. Core frame and recording schemas are unchanged.

## Entity Binding

`bind_entities(scene, cfg)` resolves official `root_state_w` or `body_state_w` tensors through `scene[name]`. The binding supplies a CUDA free-field PCM producer; a separate mixture-only percipient supplies the unchanged observation tensors. Source state never becomes policy observations directly.

`EntityBindingCfg` retains explicit `AcousticEnvironmentSpec`, array mount, microphone layout or `MicrophoneSpec` tuple, origins and quaternion order. It adds `sample_rate_hz=16000`; other entity rates fail explicitly. `SourceEntityCfg` adds `audio_asset_path` and `loop_count` (zero, a positive repeat count, or `-1` for indefinite repetition). Runtime acquisition requires an explicit audio file per source, using Core's checkout-relative asset loader, mono conversion and resampling. Assets load once and remain on the device; generated URI sources remain a scalar-reference role. The existing source start/duration/gain/directivity and microphone gains/directivity apply in propagation.

Inputs must be rank-correct float32 tensors on the simulation CUDA device. World positions receive no origin offset; environment-frame positions receive one explicit offset. WXYZ states convert to package XYZW before relative-pose composition. Entity mode accepts only analytic `free_field`, order zero, disabled air absorption/ray tracing, and identity effects. Invalid topology, options, device, shape, dtype, directivity, gain, or orientation fail explicitly.

Every `update(dt)` acquires elapsed microphone PCM, including when observation reads are deferred. Static fractional delays, signed polar gains, distance attenuation, emission schedules and file loops agree with Core. For moving geometry, receiver-time distances and gains interpolate between observed physics poses; this is a quasi-static approximation, not Core's retarded-source trajectory solver. A physics interval longer than 100 ms lacks the required pose history: it clears acoustic context, advances the acquisition cursor without fabricating the missing audio, and exposes a discontinuity. Subsequent contiguous updates warm up again. Physics intervals at or below 100 ms and observation cadence are separate settings.

CUDA perception accepts only mixtures and microphone geometry. Its bounded PCM history retains the 750 ms localizer context plus sufficient detector history for the configured observation period. The detector replays the maintained 50 ms analysis / 100 ms minimum activity / 100 ms tolerated silence rule, including partial analysis frames. Deferred reads return the latest observation window; earlier observations are not queued for policy replay. Both input context and detector state remain independent per environment.

The localizer adapts NARA-WPE primitives and the maintained group-sparse equations with Torch. WPE retains float64 after float32 produced extra events in correlated raised-array mixtures; spatial transforms retain reference precision, fitting remains float32, and geometry-only grids/dictionaries are shared. Power floors and convergence are environment-local. Reference neighborhood boundaries and event order are preserved. Processing chunks of up to 128 environments bound working memory without a source-count cap. No private stems, poses, schedules, identifiers, or expected count enter perception. Score/confidence remain unavailable when the reference provides none. Stereo and other scalar sample rates retain their existing reference roles; CUDA localization requires non-collinear XY-planar or rank-3 geometry, with qualification limited to the maintained four geometries.

An internal `ingest` / `observations` / `reset` boundary separates producer, context, localizer and projection. Replacing the localizer does not require a policy tensor redesign. The scalar reference remains the correctness path; neither online room simulation nor geometry-derived realism distributions are introduced here.

## Reference Binding

`bind_reference(snapshots, array_ids)` accepts equal non-empty sequences of pure snapshots and string selectors. Each selected array must exist and selected arrays must share a microphone count. Each environment owns an independent persistent standard pipeline. `simulate_frame()` supplies actual observed activity and optional geometry-routed DOA; only `frame.observations` enters the tensor conversion.

The scalar pipeline has no internal observation cap. The tensor converter owns truncation. Standard 16 kHz perception emits independently localized events without an internal two-source ceiling; stereo retains one ambiguous event. It needs Auditok's minimum context before activity and 750 ms past context for the bounded indoor multisource path (250 ms for retained single-event roles). The [[experiments/04-4-multisource-localization|04.4 experiment]] distinguishes memory, warm-up, response, compute and remaining speech errors.

The 07.2 causal-clock correction uses a compensated float64 episode clock and integer consumed-sample cursors. Only elapsed audio is processed: time zero returns no observations, repeated reads do not advance perception, and deferred reference reads consume intervening audio in bounded windows (the configured period, or 100 ms when zero). Reset clears only selected clocks, cursors and pipeline state. Warp float32 timestamps remain lifecycle bookkeeping, not the acoustic clock.

This scalar path does not inspect USD or turn scheduled source state into observed activity or direction. Numerical waveform perception remains host-side by design; the resulting Lab tensors reside on `sensor.device`.

## Consumer and Lifecycle

`examples/isaac_lab/isaac_lab_audio_observation.py` requires an explicit threshold for either binding and an audio asset for entity binding. The entity example uses 100 ms observation updates and optional capacity independent of source count. Its `policy_inputs()` helper exposes every tensor, scales available bearing angles by 180 and elevation angles by 90, and explicitly zeros unavailable angles. Scaled fields and their masks replace `_deg` with `_scaled` in policy keys. Scores, Boolean masks, and integer counts pass through unchanged. No batch statistics, running normalization, clipping, or imputation are applied, including for empty batches.

Downstream learners must keep statistical normalization and observation modifiers disabled for these audio terms. This example does not instantiate or configure an RL trainer. Truth for rewards, curricula, or evaluation must use separate task-owned privileged channels.

`update(dt, force_recompute=False)` uses compensated float64 episode time and integer acquisition cursors; Warp float32 timestamps are lifecycle bookkeeping only. Data access refreshes only outdated rows. Repeated reads consume no additional samples. `reset(env_ids)` clears tensor values, masks, counts, clocks, producer endpoints and perception state only for selected environments. Other rows retain their observations and context.

`processing_status` exposes copies of elapsed and last-processed times and the execution path separately from policy tensors. CUDA additionally reports acquired context samples, detected activity, and whether the latest acquisition/reset declared a discontinuity, plus an episode-local discontinuity count that survives deferred reads; scalar mode exposes the common perception diagnostics. These diagnostics do not become policy features automatically. Context length and frame freshness are not a claim of immediate perceptual response.

## Validation

`make test-isaac` covers projection semantics, capacities, truncation, finite values, metadata isolation, scalar projection parity, sample-clock continuity, consumer masking, independent reference pipelines, selective reset, and existing binding failures.

`make smoke-isaac-lab` checks actual `SensorBase` lifecycle, CUDA placement, independent scalar parity, planar/3D reference warm-up, nonempty entity observations, deferred reads and partial reset. Its performance workload now contains active CUDA PCM and perception, two explicitly configured sources, and varying receiver-relative source geometry. `--perf-envs`, `--perf-steps`, `--perf-sources`, `--perf-layout` and optional `--profile` select the measured workload. `--perf-substeps 6` acquires six 1/60-second intervals per 100 ms observation update; the default remains one interval for comparison with earlier runs. These calls exercise sensor acquisition, not robot physics or policy learning. `--perf-budget-ms` is opt-in; the old empty-tensor 20 ms budget does not apply automatically. Mean/p95, peak allocated memory and simulated-time/wall-time ratio describe the whole update. Profiling is a separate instrumented update and must not be substituted for the uninstrumented timings. Reports also expose aggregate environment updates/seconds per wall second and a separately timed single-environment reset. For baseline usability, `--perf-reference-check` compares the final received PCM with the unchanged scalar localizer outside the timed region. It requires at least 97% count agreement and retained-direction difference p95 at most five degrees, matching the existing paired-evaluation criteria; the nominal set-quality score is still reported independently. Without this option the existing 95% nominal complete-set gate remains. A small batch can contain a reference false event without implying an integration regression.

`tools/validation/lab_perception.py` compares scalar and CUDA processing on supplied received-PCM archives, keeping private scoring truth outside perception. The maintained stationary comparison covers 36 recordings and 1,440 updates across triangle, square, raised and tetrahedral arrays, 0/1/2 events, speech/broadband/disjoint content, 20 dB SNR, nominal RT60 0.3 s and 6 dB imbalance. Activity and count agree on every update; direction-difference p95 is below 0.00018 degrees on the final float64 path. Misses/extras agree as well. This preserves the reference's known failures and is an integration comparison, not a fresh physical or general acoustic qualification. Exact measurements and scale limits belong to [[implementation_phases/07-isaac-lab-observation-integration|Subphase 07.2]].

The historical 07.1 closeout passed 116 runtime tests and measured 0.212 ms/step over 4096 **empty** entity environments. That result is not an active-perception baseline or a throughput claim for 07.2.

## Consumer and Validation Closeout

Subphase 07.3 keeps the scalar reference and CUDA paths behind the existing sensor lifecycle, with unchanged finite tensors, masks, ordering and truncation. The example scales bearings by 180 to `[0, 2)` and elevations by 90 to `[-1, 1]`; it does not normalize across environments or change mask/count values. `processing_status` remains separate from policy data.

The live smoke defaults to 16 active environments on a supported CUDA GPU; larger `--perf-envs` values remain explicit exploratory measurements. Paired received-PCM validation is consolidated in `tools/validation/lab_perception.py`, with 36 maintained stationary inputs under `local/lab/received_stationary/`. The retired temporal campaign loaders and streaming-candidate interface are not compatibility paths.
