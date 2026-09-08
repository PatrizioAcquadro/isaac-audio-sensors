# Isaac Lab Integration

## Runtime Initialization

`import isaac_audio_sensors.lab` is safe before Isaac Lab and does not load Torch, USD, Omniverse, or Isaac Lab. Initialize `AppLauncher` before resolving exported Lab classes. `AudioArraySensorCfg` directly inherits current `SensorBaseCfg`; `AudioArraySensor` directly inherits `SensorBase`. There are no fallback classes or legacy runtime paths.

## Configuration

`AudioArraySensorCfg` retains inherited `prim_path`, `update_period`, and `debug_vis`, plus backend, effects, speed of sound, and analytic solver settings. It defaults to `analytic_acoustics`, `max_observations=1`, `max_doa_candidates=2`, and `doa_enabled=False`. Both capacities accept non-negative integers, including zero, and reject Booleans. Capacity does not select an estimator or imply multiple-source resolution.

`energy_threshold_dbfs` must be finite when supplied; the reference binding requires it, while entity binding rejects it and DOA activation. The active `SimulationContext` is the device authority. `debug_vis=True` fails because the sensor has no visualization implementation.

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

All unused values, masks, and counts are zero. Masks, not numeric zero, determine availability. A missing detection score is distinct from score zero; `bearing_confidence_mask` is true whenever DOA exists, even when the unresolved result has reliability zero. Confidence remains estimator-local reliability, not probability. Scores retain their producer semantics without clipping or normalization.

An absent observation, an observation with no DOA, an unresolved DOA, and a selected direction have distinct masks. An unresolved result never selects a candidate bearing. Ambiguity candidates describe alternatives for one observation, not additional sources. Bearing and elevation candidate axes are independent and carry no inferred pairing. The projection preserves selected values and declared ambiguity rather than applying a second direction policy.

Projection preserves observation and candidate order and retains only the capacity-limited prefixes. Truncation counts refer to the supplied observations, not upstream omissions or the number of physical sources. Candidate counts apply only to retained observations. Values written to float32 tensors must be representable and finite; invalid values fail explicitly. Zero capacities and zero-environment batches are supported.

The old `event_presence`, `confidence`, `sector_onehot`, and per-event `per_mic_rms` fields are removed without aliases. Allocation no longer takes a microphone count. Observations contain no per-event RMS, and aggregate mixture RMS is not copied into observation slots. Core frame and recording schemas are unchanged.

## Entity Binding

`bind_entities(scene, cfg)` retains the batched entity boundary but currently emits only empty observations. It resolves entities through `scene[name]` and reads official `root_state_w` or `body_state_w` tensors.

`EntityBindingCfg` requires an explicit `AcousticEnvironmentSpec` and defines robot/mount poses, a named microphone layout or explicit `MicrophoneSpec` tuple, source entities, position frame, optional environment origins, and WXYZ/XYZW quaternion order. `SourceEntityCfg` describes source entities for the producer boundary; its poses, schedules, gains, and identifiers never become observed events.

Inputs must be rank-correct float32 tensors on the sensor device. World positions receive no origin offset; environment-frame positions receive one explicit offset. WXYZ states convert to package XYZW before relative-pose composition. Entity mode accepts only analytic `free_field`, order zero, disabled air absorption/ray tracing, and identity effects. Invalid topology, options, device, shape, dtype, directivity, gain, or orientation fail explicitly.

The empty path allocates and scatters on the sensor device without environment loops or CPU transfer. It does not validate scalable audio perception. Its future implementation follows the multisource qualification planned in [[implementation_phases/04-observed-direction-estimation|Subphase 04.4]] and the runtime work in [[implementation_phases/07-isaac-lab-observation-integration|Subphase 07.2]].

## Reference Binding

`bind_reference(snapshots, array_ids)` accepts equal non-empty sequences of pure snapshots and string selectors. Each selected array must exist and selected arrays must share a microphone count. Each environment owns an independent persistent standard pipeline. `simulate_frame()` supplies actual observed activity and optional geometry-routed DOA; only `frame.observations` enters the tensor conversion.

The scalar pipeline has no internal observation cap. The tensor converter owns truncation. Standard 16 kHz perception emits independently localized events without an internal two-source ceiling; stereo retains one ambiguous event. It needs Auditok's minimum context before activity and 750 ms past context for the bounded indoor multisource path (250 ms for retained single-event roles). The [[experiments/04-4-multisource-localization|04.4 experiment]] distinguishes memory, warm-up, response, compute and remaining speech errors.

Reference window boundaries are rounded to the selected array's sample clock, avoiding false stream gaps from Warp float32 timestamp rounding. The window duration uses the configured update period, or the existing 1 ms minimum when zero, rounded to at least one sample. Actual discontinuities still reset common perception. Arbitrary update cadences and long-horizon timing/scale qualification remain 07.2 work.

This scalar path does not inspect USD or turn scheduled source state into observed activity or direction. Numerical waveform perception remains host-side by design; the resulting Lab tensors reside on `sensor.device`.

## Consumer and Lifecycle

`examples/isaac_lab/isaac_lab_audio_observation.py` requires an explicit threshold for reference binding. Its `policy_inputs()` helper exposes every tensor, scales available bearing angles by 180 and elevation angles by 90, and explicitly zeros unavailable angles. Scaled fields and their masks replace `_deg` with `_scaled` in policy keys. Scores, Boolean masks, and integer counts pass through unchanged. No batch statistics, running normalization, clipping, or imputation are applied, including for empty batches.

Downstream learners must keep statistical normalization and observation modifiers disabled for these audio terms. This example does not instantiate or configure an RL trainer. Truth for rewards, curricula, or evaluation must use separate task-owned privileged channels.

`update(dt, force_recompute=False)` retains Isaac Lab timestamp and lazy invalidation behavior. Data access refreshes only outdated rows. `reset(env_ids)` clears all tensor values, masks, counts, frame indices, and perception state only for selected environments. Other rows and their context remain unchanged.

## Validation

`make test-isaac` covers projection semantics, capacities, truncation, finite values, metadata isolation, scalar projection parity, sample-clock continuity, consumer masking, independent reference pipelines, selective reset, and existing binding failures.

`make smoke-isaac-lab` checks real `SensorBase` lifecycle on the RTX 4090, CUDA placement, nonempty reference observations against independent scalar perception, detector and DOA warm-up, resolved direction, silence, and partial reset. Its 4096-environment performance check measures only empty entity lifecycle overhead against the existing 20 ms mean-step budget; it is not multisource or waveform-perception throughput. CPU execution does not substitute for this live GPU gate.

The 07.1 closeout passes 116 supported-runtime Isaac tests and the RTX 4090 live gate. Fifty updates over 4096 empty entity environments average 0.212 ms/step. Runtime tests use the existing isolated Auditok 0.5.2 path; no dependency or host-runtime installation changes are required by 07.1.
