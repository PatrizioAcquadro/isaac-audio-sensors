# Isaac Lab Integration

## Runtime Initialization

`import isaac_audio_sensors.lab` is safe before Isaac Lab and does not load Torch, USD, Omniverse, or Isaac Lab. Initialize `AppLauncher` before resolving any exported Lab class.

After launch, `AudioArraySensorCfg` directly inherits `SensorBaseCfg` and `AudioArraySensor` directly inherits `SensorBase`. There are no fallback classes, reload helpers, or legacy `omni.isaac.lab` path.

## Configuration

`AudioArraySensorCfg` retains the inherited `prim_path`, `update_period`, and `debug_vis` fields plus `backend`, `max_events`, `ambiguity_policy`, `effects`, `speed_of_sound_mps`, `doa_estimator`, `analytic_max_order`, `analytic_air_absorption`, and `analytic_ray_tracing`. The backend defaults to `analytic_acoustics`; legacy backend identifiers are rejected.

The active `SimulationContext` is the only device authority. `debug_vis=True` fails explicitly because the sensor has no real visualization implementation.

## Observation Contract

`AudioArraySensorData` exposes only these tensors on `sensor.device`:

- `event_presence [N,E] bool`
- `bearing_deg [N,E] float32`
- `confidence [N,E] float32`
- `sector_onehot [N,E,8] float32`
- `per_mic_rms [N,E,M] float32`
- `ambiguity_mask [N,E] bool`

Unused slots have false masks, `NaN` bearings, and zero confidence, sector, and RMS values. Source order is deterministic and active events compact before `max_events` truncation.

## Entity Binding

`bind_entities(scene, cfg)` is the batched training path. It resolves entities only through `scene[name]` and reads official `root_state_w` or `body_state_w` tensors.

`EntityBindingCfg` requires one explicit `AcousticEnvironmentSpec` and defines the robot entity, optional mount body and relative pose, a named microphone layout or `microphones: tuple[MicrophoneSpec, ...]`, source entities, world/environment position frame, optional environment origins, and WXYZ/XYZW state quaternion order. The removed `microphone_relative_offsets_m` field has no alias. `SourceEntityCfg` defines source body, identifier, schedule, nominal gain, canonical directivity enum, and relative pose.

Inputs must already be rank-correct `float32` tensors on the sensor device. World positions receive no origin offset; environment-frame positions receive exactly one explicit origin offset. WXYZ state quaternions convert to the package XYZW convention before relative poses are composed.

Entity mode supports only `analytic_acoustics` over explicit `free_field`, with at least three microphones, `tdoa_least_squares`, order zero, disabled air absorption/ray tracing, and identity effects. It computes microphone/source pose, `distance / speed_of_sound_mps` delay, source and microphone gain/directivity magnitude, analytical `1/d`, TDOA least-squares, confidence, ambiguity, scheduling, compaction, and truncation on the sensor device. `per_mic_rms` is a relative direct-path feature, not waveform RMS or calibrated SPL. Unknown directivity, missing non-omni orientation, invalid gain, unsupported topology/estimator/options/effects/devices/shapes/dtypes/microphone counts, and degenerate TDOA geometry fail explicitly; there is no omni or CUDA-to-CPU fallback.

The fast path uses tensor indexing, selection, batched linear algebra, compaction, and scatter operations. It does not loop over environments, transfer tensors to the CPU, or convert environment IDs through the host. It does not produce waveforms, reverberation, occlusion, SPL, calibration, closed-room behavior, or per-environment acoustic randomization.

## Reference Binding

`bind_reference(snapshots, array_ids)` accepts equal non-empty sequences of pure `AudioSceneSnapshot` values and string selectors. Each selected array must exist in its corresponding snapshot, and selected arrays must share one microphone count. Lab derives sample rate, microphone order, gain, directivity, and geometry only from those snapshot-owned arrays before converting maintained core-backend frames into the same six observation tensors.

This path is the scalar semantic reference and debug boundary. It consumes the same entity-owned directivity and nominal-gain values as Core and preserves relative amplitude ratios for all supported analytic topologies. It retains two-microphone ambiguity, TDOA least-squares or SRP-PHAT, half-space, PyRoom shoebox/polygon-prism, and effect behavior. It does not inspect a USD stage, accept a scene/provider object, or retain parallel `MicrophoneArraySpec` inputs.

## Update and Reset

The sensor uses the current Isaac Lab lifecycle unchanged: `update(dt, force_recompute=False)` advances Warp timestamps and lazy invalidation, while data access updates only outdated rows.

`reset(env_ids)` uses the Isaac Lab Warp environment mask and restores padding only for selected observation rows. Other environments and reference frame indices remain unchanged.

## Ownership and Validation

USD discovery, pose resolution, environment anchoring, occlusion, and live stage state belong to `isaac_audio_sensors.isaac`. Legacy trace diagnostics remain readable but are not part of Lab observation state.

`make test-isaac` covers deterministic imports, contracts, parity, scheduling, compaction, frame transforms, reset, and failure behavior. `make smoke-isaac-lab` is the required live RTX 4090 gate for true `SensorBase` lifecycle, CUDA device placement, entity/reference parity, partial reset, and mean 4096-environment step time below 20 ms. CPU execution is not a substitute for that live gate.

The R8.3 closeout passes 90 Isaac-runtime tests and the live smoke on the RTX 4090. The analytic entity path matches reference presence, bearing, confidence, sector, ambiguity, and RMS-ratio features within GPU numerical tolerances; partial reset and all CUDA tensor contracts pass; and 50 steps over 4096 environments average 2.213 ms/step against the 20 ms budget.
