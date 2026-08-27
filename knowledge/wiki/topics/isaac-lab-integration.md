# Isaac Lab Integration

## Runtime Initialization

`import isaac_audio_sensors.lab` is safe before Isaac Lab and does not load Torch, USD, Omniverse, or Isaac Lab. Initialize `AppLauncher` before resolving any exported Lab class.

After launch, `AudioArraySensorCfg` directly inherits `SensorBaseCfg` and `AudioArraySensor` directly inherits `SensorBase`. There are no fallback classes, reload helpers, or legacy `omni.isaac.lab` path.

## Configuration

`AudioArraySensorCfg` retains the inherited `prim_path`, `update_period`, and `debug_vis` fields plus `backend`, `max_events`, `ambiguity_policy`, and `effects`.

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

`EntityBindingCfg` defines the robot entity, optional mount body and relative pose, a named microphone layout or `microphones: tuple[MicrophoneSpec, ...]`, source entities, world/environment position frame, optional environment origins, and WXYZ/XYZW state quaternion order. The removed `microphone_relative_offsets_m` field has no alias. `SourceEntityCfg` defines source body, identifier, schedule, nominal gain, canonical directivity enum, and relative pose.

Inputs must already be rank-correct `float32` tensors on the sensor device. World positions receive no origin offset; environment-frame positions receive exactly one explicit origin offset. WXYZ state quaternions convert to the package XYZW convention before relative poses are composed.

Entity mode supports only `geometry_only` and `tdoa_synthetic`, with effects disabled. Both apply source gain, source/microphone directivity magnitude, analytical `1/d`, and microphone nominal gain in the same order as Core. Unknown directivity, missing non-omni orientation, invalid gain, unsupported backends/effects/devices/shapes/dtypes/microphone counts, and degenerate TDOA geometry fail explicitly; there is no omni or CUDA-to-CPU fallback.

The fast path uses tensor indexing, selection, stacking, compaction, and scatter operations. It does not loop over environments or convert environment IDs through the host.

## Reference Binding

`bind_reference(snapshots, array_specs)` accepts equal non-empty sequences of pure `AudioSceneSnapshot` and `MicrophoneArraySpec` values. It runs maintained core backends per environment and converts frames into the same six observation tensors.

This path is the scalar semantic reference and debug boundary. It consumes the same entity-owned directivity and nominal-gain values as Core and preserves relative amplitude ratios for all four backends. It does not inspect a USD stage or accept a scene/provider object.

## Update and Reset

The sensor uses the current Isaac Lab lifecycle unchanged: `update(dt, force_recompute=False)` advances Warp timestamps and lazy invalidation, while data access updates only outdated rows.

`reset(env_ids)` uses the Isaac Lab Warp environment mask and restores padding only for selected observation rows. Other environments and reference frame indices remain unchanged.

## Ownership and Validation

USD discovery, pose resolution, room anchoring, occlusion, and live stage state belong to `isaac_audio_sensors.isaac`. Legacy trace diagnostics remain readable but are not part of Lab observation state.

`make test-isaac` covers deterministic imports, contracts, parity, scheduling, compaction, frame transforms, reset, and failure behavior. `make smoke-isaac-lab` is the required live RTX 4090 gate for true `SensorBase` lifecycle, CUDA device placement, entity/reference parity, partial reset, and mean 4096-environment step time below 20 ms. CPU execution is not a substitute for that live gate.

The R5.5 closeout passed 118 Isaac tests and the live smoke on the RTX 4090. Both maintained entity backends matched the reference path, partial reset and all CUDA tensor contracts passed, and 50 steps over 4096 environments averaged 1.879 ms/step.
