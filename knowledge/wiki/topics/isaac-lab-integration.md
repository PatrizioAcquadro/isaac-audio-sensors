# Isaac Lab Integration

## Runtime Initialization

Import the pure package before or outside Isaac Lab freely, but initialize `AppLauncher` before resolving the real Lab sensor classes.

When Lab is available, `AudioArraySensorCfg` inherits `SensorBaseCfg` and `AudioArraySensor` inherits `SensorBase`; outside Lab, fallback classes preserve import and deterministic tensor-path testing without claiming runtime inheritance.

If fallback classes were imported before runtime initialization, call `ensure_isaac_lab_sensor_classes()` after `AppLauncher` starts and use the returned classes.

## Configuration

`AudioArraySensorCfg` defines `prim_path`, `update_period`, `history_length`, debug visualization, backend, microphone layout, sample rate, `max_events`, optional microphone count, device, ambiguity policy, scalar/batched/auto compute path, effects, and optional waveform/trace outputs.

This is the canonical Lab configuration. The generic `core.config.AudioSensorConfig` contains no Lab table or Lab-specific validation.

Configuration rejects empty prim paths, negative timing/history, unknown backends or compute modes, invalid device or microphone counts, invalid ambiguity policy, and non-`EffectsConfig` effects.

## Observation Buffers

`AudioArraySensorData` stores Torch tensors on the configured device for `event_presence`, `bearing_deg`, `confidence`, `sector_onehot`, `per_mic_rms`, and `ambiguity_mask`.

The leading dimensions are environment and bounded event slots; sector vectors use the stable eight-sector order and microphone values follow the configured microphone ID order.

Unused event slots are masked, bearings are `NaN`, confidences/RMS/one-hot values are zero, and ambiguity is false.

## Binding Models

`bind_env()` and `bind_envs()` attach explicit pure scene snapshots; `bind_provider()` supplies snapshots on demand for custom adapters.

`bind_lab_stage()` maps cloned namespaces such as `/World/envs/env_{env_id}` to array/source prims and re-reads selected environment transforms through USD or fallback stage attributes.

Stage binding reuses the import-safe bounds helpers owned by `isaac_audio_sensors.isaac`; this is the only additional semantic dependency beyond core.

`bind_lab_scene()` and `bind_lab_env()` adapt common scene/env wrappers to the same stage path.

`bind_lab_entities()` reads common articulation or rigid-object root/body pose tensors directly, composes body-mounted array offsets, orders sources deterministically, and converts selected rows to core dataclasses at the backend boundary.

Scene/entity convenience methods support dictionary, attribute, articulation-map, and rigid-object-map lookup without making downstream task classes package dependencies.

## World and Environment Frames

World-frame entity tensors are the default and must not receive an additional environment-origin offset.

If a task supplies environment-frame positions, it must explicitly enable configured or scene-provided environment origins so the provider performs one intentional translation.

Array-relative microphone geometry and XYZW orientations are composed before backend computation, preserving the public coordinate convention.

## Compute Paths

`scalar` computes each requested environment through the core backend path; `batched` uses Torch vectorization for supported geometry and TDOA behavior; `auto` selects the maintained compatible path.

The batched path preserves bearing normalization, sector mapping, amplitude semantics, active-window filtering, event compaction, padding/truncation, and device placement.

Unsupported backend/effect combinations must fall back only when the configured semantics remain equivalent; otherwise they fail explicitly.

## Update and Reset

`update(dt, env_ids=...)` advances timestamps and marks only selected environments outdated; data refresh is lazy and recomputes rows when accessed or explicitly requested.

`reset(env_ids)` clears selected buffers and binding motion state without disturbing other environments.

Stage and entity providers read only selected environment IDs during partial updates, which prevents accidental whole-batch state changes.

## Device and Validation Boundary

GPU-required validation asserts CUDA visibility and verifies every audio tensor, timestamp tensor, and outdated mask remains on the selected CUDA device.

CPU fallback tests validate import safety and deterministic tensor semantics only; they are not evidence that the supported live Isaac Lab GPU path ran.

The standard live command is `make smoke-isaac-lab`, which uses the Isaac Lab interpreter and requires the actual GPU.
