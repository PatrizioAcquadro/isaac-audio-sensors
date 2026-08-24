# Isaac Sim and Kit

## Live Stage Integration

`IsaacAudioArraySensor` in `isaac_audio_sensors.isaac.sensor` binds an explicit array on a live stage or discovers authored sources and arrays from configured USD roots. There is no offline `from_config()` path.

Discovery uses `ias:*` metadata, compatible native sound attributes, USD type/name signals, child microphone prims, optional object/base context, filters, and deterministic preference rules.

The pose resolver prefers `UsdGeom` world-transform APIs and falls back to authored `ias:` positions, orientations, and simple `xformOp` parent stacks for import-safe tests and duck-typed stages.

Import-safe world bounds and room-absorption helpers live in `isaac_audio_sensors.isaac.usd_bounds` and are shared by Isaac Sim, Isaac Lab, and Kit.

Each emitted frame can carry `stage_snapshot` diagnostics for selected prims, discovery reasons, pose provenance, time code, source/array/microphone transforms, and optional object/base context.

## Discovery Cache and Motion

Steady-state updates reuse discovered prim identities and re-read their current transforms; stage notices invalidate the cache when relevant prims or properties change.

`rediscover()` is the explicit recovery path, while a configuration flag can force full discovery each update when a dynamic authoring workflow needs it.

Pose history derives bounded velocities and resets on lifecycle discontinuities, stale timestamps, or teleport-like changes according to configured policy.

Lazy timeline time, update subscriptions, and reset subscriptions share one Isaac lifecycle helper. Anchored-room refresh belongs to stage-snapshot helpers, while occlusion pair comparison, refresh reasons, and material diagnostics stay inside the occlusion module.

## Occlusion and Visualization

Optional PhysX raycasts compute per-source/per-microphone occlusion and material transmission; missing runtime support produces a clear optional-capability error.

Visualization is represented first as pure structured debug primitives, then rendered through lazy debug draw or persistent session-layer USD geometry when available.

The latest frame registry supports Kit instruments, Script Nodes, and the optional OmniGraph node without coupling the core frame contract to a GUI.

## Extension Lifecycle

Add the repository `exts/` directory to Isaac Sim Extension Manager search paths or use the supported installer, then enable `Isaac Audio Sensors` and open it from `Window -> Isaac Audio Sensors`.

The action ID is `isaac_audio_sensors.omni::toggle_window`; the default shortcut is `Ctrl+Alt+A` when the optional Kit hotkey service is available.

The extension imports without `omni`, `pxr`, CUDA, Torch, Replicator, or a display; live APIs are resolved only inside the operations that require them.

The entrypoint exposes its `controller` and has no duplicate sensor, authoring, export, or Replicator proxies. The controller composes internal lifecycle, authoring, sensor-session, recording-workflow, Replicator, and configuration services; the window and sections only render state and invoke controller actions.

Shutdown independently cancels an active recording as incomplete, stops audition, Replicator, and the sensor, clears debug/frame state, detaches workflow/window callbacks, and releases update, stage, reset, hotkey, menu, and action registrations even if one cleanup fails.

## Native Kit Window

The native `omni.ui` window has exactly three top-level areas: Guided Workflow, Live Monitor, and Advanced Tools. Guided and Live Monitor are open on first use, while Advanced Tools is closed. Guided and Advanced are mutually exclusive accordions; Live Monitor remains independently available as the primary operating surface.

![Isaac Audio Sensors native Kit window](../../../exts/isaac_audio_sensors.omni/data/preview.png)

The fixed status strip remains visible below the scrollable content. It reports short ready, active, warning, or error summaries; exact diagnostics stay inside Advanced Tools. View code reads controller state and invokes controller actions only. It does not access USD, files, or recording internals directly.

## Guided Workflow

The guided path is `Setup -> Validate -> Run -> Inspect -> Record -> Export`.

Only the current step is expanded. It exposes one primary action, with Back and recovery actions secondary. Setup applies a maintained safe preset and stage bindings; Validate runs stage, backend, device, source, array, room, attachment, calibration, and capability checks; Run and Inspect reuse the same canonical sensor control as Live Monitor; Record exposes Start Recording, then Stop & Finalize, with Cancel separate; Export validates, splits when requested, and inventories the result. Capability validation refreshes stale cached facts within the same pass.

Guided is open by default and stores its local collapse preference at `/persistent/exts/isaac_audio_sensors.omni/ui/guided_collapsed`. Missing `carb.settings` falls back safely to the default. `guided_mode_enabled=False` still removes Guided completely, and the local preference is not part of exported configuration.

Simulator reset starts a new episode, and partial or failed recording output is not promoted as a complete session.

The headless path is `isaac_audio_sensors.kit.headless.HeadlessGuidedSession`; callers inject an `ExtensionController`, and the CLI owns construction of the default controller.

## Live Monitor

Live Monitor shows sensor state, backend, the latest frame, detection count, and waveform availability. One contextual button starts or stops the sensor. The live instruments show the bearing compass, up to eight microphone RMS meters, and no more than three recent detections, with explicit empty states before frame or waveform data exists.

## Advanced Tools

Advanced Tools contains the specialist controls for stage and selection, array, source, sensor settings and debug, room, audio output, Replicator, export, and configuration. Stage binding uses one `Bind selection as` selector and `Bind Selected`; position authoring uses a preset selector and `Apply Position Preset`. Known profiles and rigs are selected with combo boxes and validated by Apply rather than duplicate selection buttons.

Numeric settings use drag widgets, enumerated choices use combo boxes, and string fields remain limited to identifiers, paths, and free text. All maintained controller capabilities remain reachable here without duplicating lifecycle controls that are simultaneously visible in Live Monitor.

Replicator controls the optional Omniverse writer; Export writes the latest frame, JSONL streams, and reusable binding/configuration JSON.

Viewport follow-selection and live pose synchronization let manipulator edits update the selected stage entities without copying transforms into task-specific code.

## OmniGraph and Replicator

When `omni.graph.core` is available, the extension registers `isaac_audio_sensors.omni.IsaacAudioSensorFrame` version 1 through `og.register_node_type` without `.ogn` code generation.

The node publishes the latest frame ID, timestamp, detection count, bearing, sector, microphone IDs/RMS, occlusion state, and JSON payload, optionally filtered by array key.

Replicator integration is a lazy Isaac bridge used by the extension; core frames, package JSON/JSONL writers, the base sensor capture path, and Isaac Lab do not require it.

Kit services own profile libraries, validation, output paths, and application persistence. The sensor-session service appends JSONL only for new frames and injects a constructed core `WaveformSink`; the live sensor uses and closes that sink without knowing UI paths or output modes.

## Troubleshooting

If there is no stage or selection, create/open a stage and refresh before authoring; every prim path must be absolute.

If discovery is empty, verify the selected roots and authored metadata, then run rediscovery; if a moved prim does not change a frame, verify live pose sync, cache invalidation, and the stage time code.

If start/update fails, read the exact validation finding for backend, dependency, device, array geometry, source, room, or output path instead of changing unrelated settings.

If overlays or OmniGraph are unavailable, distinguish optional Kit-service absence from sensor failure; frame JSON and structured diagnostics remain the primary contract.

If Replicator is unavailable, use package JSON/JSONL or the generic session recorder; a Replicator blocker must not be reported as a core package failure.

## Version Notes

- 2026-08-24: Rebuilt the native Kit UI around the three task-oriented areas, added persistent Guided collapse behavior, promoted Live Monitor to the canonical operating surface, and moved specialist controls into Advanced Tools without changing core APIs or serialized contracts.
