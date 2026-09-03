# Isaac Lab Integration

## Runtime Initialization

`import isaac_audio_sensors.lab` is safe before Isaac Lab and does not load Torch, USD, Omniverse, or Isaac Lab. Initialize `AppLauncher` before resolving any exported Lab class.

After launch, `AudioArraySensorCfg` directly inherits `SensorBaseCfg` and `AudioArraySensor` directly inherits `SensorBase`. There are no fallback classes, reload helpers, or legacy `omni.isaac.lab` path.

## Configuration

`AudioArraySensorCfg` retains the inherited `prim_path`, `update_period`, and `debug_vis` fields plus `backend`, `max_observations`, `effects`, `speed_of_sound_mps`, `analytic_max_order`, `analytic_air_absorption`, and `analytic_ray_tracing`. The backend defaults to `analytic_acoustics`; legacy backend identifiers, `max_detections`, estimator selection, and sensor-side ambiguity policies are absent.

The active `SimulationContext` is the only device authority. `debug_vis=True` fails explicitly because the sensor has no real visualization implementation.

## Observation Contract

`AudioArraySensorData` exposes only these tensors on `sensor.device`:

- `event_presence [N,E] bool`
- `bearing_deg [N,E] float32`
- `confidence [N,E] float32`
- `sector_onehot [N,E,8] float32`
- `per_mic_rms [N,E,M] float32`
- `ambiguity_mask [N,E] bool`

Unused slots have false masks, `NaN` bearings, and zero confidence, sector, and RMS values. During the deliberate Plan 02.2-to-Phase 03 interval, all slots are unused because no concrete activity detector is registered. `max_observations` controls only fixed tensor capacity; neither entity nor reference binding derives presence, bearing, confidence, ambiguity, or per-observation RMS from scene source truth.

## Entity Binding

`bind_entities(scene, cfg)` is the batched training path. It resolves entities only through `scene[name]` and reads official `root_state_w` or `body_state_w` tensors.

`EntityBindingCfg` requires one explicit `AcousticEnvironmentSpec` and defines the robot entity, optional mount body and relative pose, a named microphone layout or `microphones: tuple[MicrophoneSpec, ...]`, source entities, world/environment position frame, optional environment origins, and WXYZ/XYZW state quaternion order. The removed `microphone_relative_offsets_m` field has no alias. `SourceEntityCfg` defines source body, identifier, schedule, nominal gain, canonical directivity enum, and relative pose.

Inputs must already be rank-correct `float32` tensors on the sensor device. World positions receive no origin offset; environment-frame positions receive exactly one explicit origin offset. WXYZ state quaternions convert to the package XYZW convention before relative poses are composed.

Entity mode currently supports only `analytic_acoustics` over explicit `free_field`, order zero, disabled air absorption/ray tracing, and identity effects. It validates and resolves array/source entity state on the sensor device but returns a correctly padded zero-observation result. Source poses and schedules are not converted into observations. Invalid directivity, orientation, gain, topology, options, devices, shapes, or dtypes still fail explicitly; there is no CUDA-to-CPU fallback.

The current zero-observation path allocates and scatters fixed-shape tensors on the selected device. It does not loop over environments, transfer tensors to the CPU, or produce waveforms, reverberation, occlusion, SPL, calibration, closed-room behavior, or per-environment acoustic randomization.

## Reference Binding

`bind_reference(snapshots, array_ids)` accepts equal non-empty sequences of pure `AudioSceneSnapshot` values and string selectors. Each selected array must exist in its corresponding snapshot, and selected arrays must share one microphone count. The temporary reference bridge still executes the selected Core backend per environment but intentionally returns the same zero-observation tensors until Phase 03.

This path remains a scalar lifecycle/debug boundary rather than an oracle reference. It does not inspect a USD stage, accept a scene/provider object, retain parallel `MicrophoneArraySpec` inputs, or turn snapshot source data into activity or direction labels.

## Update and Reset

The sensor uses the current Isaac Lab lifecycle unchanged: `update(dt, force_recompute=False)` advances Warp timestamps and lazy invalidation, while data access updates only outdated rows.

`reset(env_ids)` uses the Isaac Lab Warp environment mask and restores padding only for selected observation rows. Other environments and reference frame indices remain unchanged.

## Ownership and Validation

USD discovery, pose resolution, environment anchoring, occlusion, and live stage state belong to `isaac_audio_sensors.isaac`. Legacy trace diagnostics remain readable but are not part of Lab observation state.

`make test-isaac` covers deterministic imports, contracts, zero-observation parity, frame transforms, reset, and failure behavior. `make smoke-isaac-lab` is the required live RTX 4090 gate for true `SensorBase` lifecycle, CUDA device placement, entity/reference parity, partial reset, and mean 4096-environment step time below 20 ms. CPU execution is not a substitute for that live gate.

The Plan 02.2 closeout passes 90 Isaac-runtime tests and the live smoke on the RTX 4090. Entity/reference zero-observation parity, partial reset, and all CUDA tensor contracts pass; 50 steps over 4096 environments average 0.131 ms/step against the 20 ms budget.
