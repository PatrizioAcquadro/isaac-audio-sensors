# Isaac Sim and Kit

## Live Stage Integration

`IsaacAudioArraySensor` binds an explicit array and scene or discovers authored sources and arrays from configured USD roots.

Discovery uses `ias:*` metadata, compatible native sound attributes, USD type/name signals, child microphone prims, optional object/base context, filters, and deterministic preference rules.

The pose resolver prefers `UsdGeom` world-transform APIs and falls back to authored `ias:` positions, orientations, and simple `xformOp` parent stacks for import-safe tests and duck-typed stages.

Import-safe world bounds and room-absorption helpers live in `isaac_audio_sensors.isaac.usd_bounds` and are shared by Isaac Sim, Isaac Lab, and Kit.

Each emitted frame can carry `stage_snapshot` diagnostics for selected prims, discovery reasons, pose provenance, time code, source/array/microphone transforms, and optional object/base context.

## Discovery Cache and Motion

Steady-state updates reuse discovered prim identities and re-read their current transforms; stage notices invalidate the cache when relevant prims or properties change.

`rediscover()` is the explicit recovery path, while a configuration flag can force full discovery each update when a dynamic authoring workflow needs it.

Pose history derives bounded velocities and resets on lifecycle discontinuities, stale timestamps, or teleport-like changes according to configured policy.

## Occlusion and Visualization

Optional PhysX raycasts compute per-source/per-microphone occlusion and material transmission; missing runtime support produces a clear optional-capability error.

Visualization is represented first as pure structured debug primitives, then rendered through lazy debug draw or persistent session-layer USD geometry when available.

The latest frame registry supports Kit instruments, Script Nodes, and the optional OmniGraph node without coupling the core frame contract to a GUI.

## Extension Lifecycle

Add the repository `exts/` directory to Isaac Sim Extension Manager search paths or use the supported installer, then enable `Isaac Audio Sensors` and open it from `Window -> Isaac Audio Sensors`.

The action ID is `isaac_audio_sensors.omni::toggle_window`; the default shortcut is `Ctrl+Alt+A` when the optional Kit hotkey service is available.

The extension imports without `omni`, `pxr`, CUDA, Torch, Replicator, or a display; live APIs are resolved only inside the operations that require them.

## Guided Workflow

The guided path is `Setup -> Validate -> Run -> Inspect -> Record -> Export`.

Setup applies a maintained safe preset and stage bindings; Validate runs stage, backend, device, source, array, room, attachment, calibration, and capability checks; Run starts the real sensor lifecycle; Inspect requires explicit user acceptance of the instrument output; Record writes a generic session; Export validates, splits when requested, and inventories the result.

Simulator reset starts a new episode, and partial or failed recording output is not promoted as a complete session.

The headless path is `isaac_audio_sensors.kit.headless.HeadlessGuidedSession`; callers inject an `ExtensionController`, and the CLI owns construction of the default controller.

## Expert Sections

Stage selects discovery roots and current array, source, object, or base prims; Array and Source author the corresponding metadata and transforms; Sensor Control configures backend, device, update period, event bound, ambiguity, output, and lifecycle.

Room configures the fixed acoustic room and anchor; Instruments show bearing, per-microphone RMS, and detection history; Audio Output previews waveforms and spectrograms and auditions exported WAVs.

Replicator controls the optional Omniverse writer; Export writes the latest frame, JSONL streams, and reusable binding/configuration JSON.

Viewport follow-selection and live pose synchronization let manipulator edits update the selected stage entities without copying transforms into task-specific code.

## OmniGraph and Replicator

When `omni.graph.core` is available, the extension registers `isaac_audio_sensors.omni.IsaacAudioSensorFrame` version 1 through `og.register_node_type` without `.ogn` code generation.

The node publishes the latest frame ID, timestamp, detection count, bearing, sector, microphone IDs/RMS, occlusion state, and JSON payload, optionally filtered by array key.

Replicator is extension-only and lazy; core frames, package JSON/JSONL writers, the base Isaac sensor, and Isaac Lab do not depend on it.

## Troubleshooting

If there is no stage or selection, create/open a stage and refresh before authoring; every prim path must be absolute.

If discovery is empty, verify the selected roots and authored metadata, then run rediscovery; if a moved prim does not change a frame, verify live pose sync, cache invalidation, and the stage time code.

If start/update fails, read the exact validation finding for backend, dependency, device, array geometry, source, room, or output path instead of changing unrelated settings.

If overlays or OmniGraph are unavailable, distinguish optional Kit-service absence from sensor failure; frame JSON and structured diagnostics remain the primary contract.

If Replicator is unavailable, use package JSON/JSONL or the generic session recorder; a Replicator blocker must not be reported as a core package failure.
