# Phase R10 — Geometry Acoustics Integration

Status: Planned after R9.4 selected-provider risk retirement and the shared
signal and observed-perception migration. [[implementation_phases/08-geometry-acoustics-integration|Implementation Plan 08]]
references the R10.1–R10.3 execution order but adds no technical requirements.
This page is the sole authority for the geometry integration.

## Objective

Integrate the provider selected by [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] as the primary high-fidelity simulated signal producer for one or a few passive-audio Isaac environments. Its final microphone signals enter the same backend-independent observed-perception path used by analytic simulation and physical capture.

R10 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the selected integration must replace temporary, unselected, duplicate, and legacy geometry paths rather than adding another permanent layer beside them.

## Subphase R10.1 — USD Acoustic Scene

#### Implementation

Make Isaac own acoustic-geometry selection, room and array containment, material mapping, static-scene caching, and dynamic-object updates. Visual materials are not treated as calibrated acoustic truth; relevant surfaces use explicit absorption, scattering, and transmission properties with provenance.

Include acoustically relevant room surfaces, doors, openings, large objects, robot body, and microphone housing while excluding technical source and sensor prims that are not physical obstacles. Static geometry is reusable; moving doors, robots, and objects update without rebuilding unrelated scene state.

Represent acoustic partitions independently from visual or collision fragmentation. One wall, door, panel, or authored construction may own several meshes or colliders while resolving to one acoustic assembly and one material/transmission definition. Prefer the selected provider's native scene and material representation; introduce IAS-specific partition metadata only where the provider cannot express the required USD mapping directly.

For Steam Audio, derive a dedicated acoustic proxy instead of passing arbitrary
visual fragmentation through unchanged. If R9.4 qualifies the representation,
one physical assembly becomes a closed or paired-face provider object matching
Steam's hit-pair transmission assumption. A whole-assembly banded curve
represents constructions such as double-leaf walls and is mapped with explicit
provenance to Steam's supported transmission bands. IAS owns this
USD-to-provider translation, not a structural solver or a post-render
attenuation correction.

#### Key Decisions

- USD remains the scene authority, while acoustic inclusion and material meaning are explicit.
- Visual prims, collision prims, and acoustic partitions are separate concerns; mesh count must not change transmission.
- Provider-native assembly and material semantics are reused before adding IAS metadata or algorithms.
- Only an acoustic-proxy representation qualified by R9.4 may be used to claim
  predictable sequential-partition transmission.
- Multiple rooms form one connected acoustic problem when sound can travel between them.
- A selected local room aids containment and diagnostics but does not discard external sources.

#### Problems / Limitations

Arbitrary visual detail may be acoustically irrelevant or too expensive. Geometry selection and simplification must preserve meaningful propagation without treating every rendered triangle as necessary acoustic input. Assembly transmission still depends on authored or qualified coefficient data; the integration does not infer cavity resonance, thickness, or structural coupling from mesh layering. If the R9.4 proxy test fails, distinct sequential assemblies remain unsupported for direct transmission rather than being collapsed into a route-dependent synthetic material.

## Subphase R10.2 — Passive Microphone-Array Propagation

#### Implementation

Map arbitrary passive source content, source pose and directivity, every microphone pose and response, and the selected acoustic scene into the provider. Preserve qualified direct and reflected paths, material transmission, and functional indirect NLOS output, then return one phase-coherent final waveform per physical microphone through the common `MicrophoneSignalBlock` boundary. Enable Steam's baked pathing and UTD-based deviation behavior only if R9.4 qualifies their per-microphone signal semantics, dynamic validation, and operating cost; otherwise do not claim approximate diffraction as an implemented capability.

Isaac Audio Sensors owns source content, provider lifecycle, source and array translation, microphone semantics, signal effects not owned by the provider, diagnostics, and signal provenance. The external engine owns mesh acceleration, ray traversal, multi-bounce reflection, scattering, and every enabled path-search or deviation algorithm. `AudioPerceptionPipeline`, outside the geometry backend, owns activity detection, optional DOA estimation, `AudioObservation` creation, and `AudioSensorFrame` construction.

Prefer provider-native arrival-time rendering when a qualified stable Steam API
supplies it. While the provider's audio effect does not apply physical direct
arrival delay to PCM, the private Steam adapter owns geometry-derived
fractional-delay scheduling on one shared source timeline. It must preserve
cross-block continuity and microphone-relative timing and must not double-apply
delay to direct or indirect output. Remove this bridge when a requalified
provider release owns equivalent PCM timing.

The provider owns geometry-path occlusion and transmission exactly once. Isaac therefore does not run the legacy `SourceOcclusion` raycast-and-attenuation path for `GeometryAcoustics`, and the backend does not accept a precomputed `SourceOcclusion` record as another gain stage. The R10.1 acoustic proxy and material-band mapping are input translation, not permission to correct measured output with an extra gain. Conflicting external attenuation input fails validation rather than being ignored or double-applied.

Do not reconstruct `SourceOcclusion` solely to mirror legacy diagnostics. Expose only concise provider-derived occlusion state that remains meaningful to signal provenance or an active diagnostic consumer; do not duplicate provider path data without a concrete use. Legacy occlusion machinery remains only where R8 still needs direct-path analytic attenuation, and geometry-path wrappers or duplicate material resolution are removed after consumer migration.

When the provider exposes ray, path, or interaction diagnostics, adapt them optionally to the existing `DebugPrimitive` representation for live overlays, sidecar JSON, and review video. Preserve direct, transmitted, reflected, and indirect path distinctions when the provider reports them. Diagnostic capture is disabled by default, filterable by source, array, microphone, and path type, and must not add path fields to the stable frame schema or ordinary datasets. Do not reconstruct provider paths locally when no supported diagnostic API exists.

#### Key Decisions

- The backend simulates a robot-mounted microphone array, not a human listener or qualitative device mix.
- `GeometryAcoustics` emits microphone signals, not detections, DOA estimates, observations, frames, or learning labels.
- Activity detection and DOA estimation remain backend-independent and consume only the final microphone mixture.
- Geometry-provider occlusion is applied once; `SourceOcclusion` is neither an additional attenuation stage nor a mandatory diagnostic artifact.
- Provider-native path diagnostics are optional review outputs, not sensor observations or a second propagation implementation.
- Provider-private stems or path contributions are optional diagnostics and never required by perception.
- Relative physical coherence is required; absolute calibration remains deployment-specific and optional.
- Only R9.4-qualified pathing and deviation behavior enters the maintained
  backend; failed advanced gates narrow the fidelity claim instead of causing a
  local diffraction implementation.
- Structural vibration, a complete wave-equation solver, and active ultrasound are outside this phase.

#### Problems / Limitations

The provider's supported physics define the advanced-fidelity ceiling. Unsupported effects must remain explicit rather than being replaced with undocumented heuristics. Steam pathing depends on baked probes and produces an Ambisonic path field, so its availability does not by itself prove raw microphone-array suitability or general diffraction accuracy. Diagnostics retain only actionable provenance, limitations, and observable sensor state; they do not preserve obsolete internal structures for their own sake. A missing provider path-visualization API remains a declared diagnostic limitation rather than a reason to duplicate ray traversal.

## Subphase R10.3 — Operating Integration and Cleanup

#### Implementation

Integrate the selected provider's lifecycle, static-scene caching, bounded dynamic updates, configuration, Kit workflow, diagnostics, and packaging behind its capability boundary. Maintain one selected geometry-provider integration rather than exposing redundant experimental backends or provider-specific scene state through Core observation contracts.

Target high-quality operation for one or a few Isaac environments. Expose geometry-derived acoustic statistics or bounded parameters that can inform R8 randomization for mass-parallel Isaac Lab training without requiring the geometry provider in every environment.

Export provider- and scenario-versioned bounded distributions for broadband and banded transmission, blocked-path fraction, sequential-partition count, direct-to-indirect ratio, dominant indirect delay/level, and changes caused by doors or dynamic occluders. Consume those distributions offline through the scalable analytic path completed in R8.3; do not introduce an online geometry-provider dependency into mass-parallel execution. Label the parameters as geometry-derived simulation data rather than measured physical calibration.

After validating the selected provider, remove unselected integrations, temporary R9 scaffolding, redundant geometry, material, or occlusion paths, and their unused supporting surfaces. Once the production Steam adapter passes the selected qualification scenarios, make it the sole Steam binding used by both runtime and requalification and delete the duplicate R9 adapter. Retain only contract cases that actively gate provider-version upgrades; remove unused runners, fixture generators, report builders, and experiment-only helpers. NVIDIA RTX Acoustic remains documentation and historical evidence only, with no executable or configurable provider surface. Do not keep provider-specific public observations or test-only runtime shortcuts.

#### Key Decisions

- `GeometryAcoustics` is the primary daily high-fidelity Isaac path.
- `AnalyticAcoustics` remains the scalable Isaac Lab path.
- One selected geometry provider is the maintained high-fidelity integration.
- Provider-specific controls remain behind the provider capability boundary.
- One production Steam adapter replaces the temporary R9 adapter; qualification
  must not justify a duplicate provider implementation.
- Public perception and dataset contracts remain signal-producer-independent.
- Geometry-derived distributions transfer bounded behavior, not provider implementation details or raw path traces, into the analytic path.
- Geometry, analytic, and physical producers preserve the same `MicrophoneSignalBlock` input boundary and downstream perception contracts.

#### Problems / Limitations

The geometry backend is not required to scale directly to thousands of simultaneous Isaac Lab environments. Transferred distributions apply only to the provider's simulated scenario family. Preserve only the minimum probes and resources required to operate or revalidate the selected provider. Before adopting a newer Steam release, rerun the focused version, timing, assembly, pathing, signal, and performance gates against its exact stable tag.

## Artifacts

Expected artifacts are a provider-backed `MicrophoneSignalBlock` producer, USD acoustic mapping, bounded lifecycle and diagnostics, unchanged perception semantics across analytic, geometry, and physical inputs, and one consolidated maintained geometry-provider surface. No R10 implementation artifacts exist yet.

## Files

Implementation files remain to be determined by the selected provider's adapter design.
