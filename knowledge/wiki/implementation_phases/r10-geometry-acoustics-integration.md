# Phase R10 — Geometry Acoustics Integration

Status: Planned after the shared signal and observed-perception migration.
R9.4 risk retirement is complete and constrains the supported R10 scope.
[[implementation_phases/08-geometry-acoustics-integration|Implementation Plan 08]]
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

Do not enable the R9.4 closed/paired-face transmission proxy. Although its
oblique, thickness, and fragmentation variants were invariant, a 12 dB
assembly measured 18 dB and distinct assemblies did not add from that measured
baseline. R10 may expose only the previously qualified single planar-assembly
mapping and must label distinct sequential-assembly transmission unsupported.
It must not collapse several constructions into a route-dependent material or
add post-render attenuation correction.

#### Key Decisions

- USD remains the scene authority, while acoustic inclusion and material meaning are explicit.
- Visual prims, collision prims, and acoustic partitions are separate concerns; mesh count must not change transmission.
- Provider-native assembly and material semantics are reused before adding IAS metadata or algorithms.
- The failed R9.4 paired proxy is excluded; R10 does not claim predictable
  sequential-partition transmission.
- Multiple rooms form one connected acoustic problem when sound can travel between them.
- A selected local room aids containment and diagnostics but does not discard external sources.

#### Problems / Limitations

Arbitrary visual detail may be acoustically irrelevant or too expensive.
Geometry selection and simplification must preserve meaningful propagation
without treating every rendered triangle as necessary acoustic input. Assembly
transmission still depends on authored or qualified coefficient data; the
integration does not infer cavity resonance, thickness, or structural coupling
from mesh layering. Distinct sequential assemblies remain unsupported for
direct transmission.

## Subphase R10.2 — Passive Microphone-Array Propagation

#### Implementation

Map arbitrary passive source content, source pose and directivity, every
microphone pose and response, and the selected acoustic scene into the
provider. Preserve qualified direct and reflected paths, bounded supported
material transmission, and functional indirect NLOS output, then return one
phase-coherent final waveform per physical microphone through the common
`MicrophoneSignalBlock` boundary.

Enable the R9.4-qualified baked pathing path: deterministic `DYNAMIC` probe
batches, provider-default UTD deviation, one independent point receiver and
`IPLPathEffect` per microphone, and the omnidirectional component of the
non-spatialized Ambisonic field. Retain dynamic validation, alternate-path
search, and bounded path-visualization callbacks. These capabilities support
approximate pathing in the qualified scenario family; they do not establish
general diffraction accuracy.

Isaac Audio Sensors owns source content, provider lifecycle, source and array translation, microphone semantics, signal effects not owned by the provider, diagnostics, and signal provenance. The external engine owns mesh acceleration, ray traversal, multi-bounce reflection, scattering, and every enabled path-search or deviation algorithm. `AudioPerceptionPipeline`, outside the geometry backend, owns activity detection, optional DOA estimation, `AudioObservation` creation, and `AudioSensorFrame` construction.

Prefer provider-native arrival-time rendering when a qualified stable Steam API
supplies it. Steam `4.8.1` direct and pathing effects do not apply physical
arrival time to PCM, so the private Steam adapter owns the qualified continuous
fractional-delay scheduler on one shared source timeline. Apply it once to
direct and pathing; reflection IRs retain their provider-native timing and
bypass it. Remove this bridge when a requalified provider release owns
equivalent PCM timing.

The provider owns geometry-path occlusion and transmission exactly once. Isaac
therefore does not run the legacy `SourceOcclusion` raycast-and-attenuation path
for `GeometryAcoustics`, and the backend does not accept a precomputed
`SourceOcclusion` record as another gain stage. Permitted R10.1 USD and material
mapping is input translation, not permission to correct measured output with an
extra gain. Conflicting external attenuation input fails validation rather than
being ignored or double-applied.

Do not reconstruct `SourceOcclusion` solely to mirror legacy diagnostics. Expose only concise provider-derived occlusion state that remains meaningful to signal provenance or an active diagnostic consumer; do not duplicate provider path data without a concrete use. Legacy occlusion machinery remains only where R8 still needs direct-path analytic attenuation, and geometry-path wrappers or duplicate material resolution are removed after consumer migration.

Adapt the qualified path-visualization callback optionally to the existing
`DebugPrimitive` representation for live overlays, sidecar JSON, and review
video. Preserve direct, transmitted, reflected, and indirect path distinctions
when the provider reports them. Diagnostic capture is disabled by default,
filterable by source, array, microphone, frame, and path type, and must not add
path fields to the stable frame schema or ordinary datasets. Do not reconstruct
provider paths locally.

#### Key Decisions

- The backend simulates a robot-mounted microphone array, not a human listener or qualitative device mix.
- `GeometryAcoustics` emits microphone signals, not detections, DOA estimates, observations, frames, or learning labels.
- Activity detection and DOA estimation remain backend-independent and consume only the final microphone mixture.
- Geometry-provider occlusion is applied once; `SourceOcclusion` is neither an additional attenuation stage nor a mandatory diagnostic artifact.
- Provider-native path diagnostics are optional review outputs, not sensor observations or a second propagation implementation.
- Provider-private stems or path contributions are optional diagnostics and never required by perception.
- Relative physical coherence is required; absolute calibration remains deployment-specific and optional.
- R9.4-qualified baked pathing, default UTD deviation, arrival scheduling, and
  bounded callbacks enter the maintained backend; the failed proxy does not.
- Structural vibration, a complete wave-equation solver, and active ultrasound are outside this phase.

#### Problems / Limitations

The provider's supported physics define the advanced-fidelity ceiling.
Unsupported effects remain explicit rather than being replaced with
undocumented heuristics. Steam pathing depends on baked probes, produces an
Ambisonic field, and is qualified only through the independent-receiver mapping
measured in R9.4. Diagnostics retain actionable provenance, limitations, and
observable sensor state rather than obsolete internal structures.

## Subphase R10.3 — Operating Integration and Cleanup

#### Implementation

Integrate the selected provider's lifecycle, static-scene caching, bounded dynamic updates, configuration, Kit workflow, diagnostics, and packaging behind its capability boundary. Maintain one selected geometry-provider integration rather than exposing redundant experimental backends or provider-specific scene state through Core observation contracts.

Target high-quality operation for one or a few Isaac environments. Expose geometry-derived acoustic statistics or bounded parameters that can inform R8 randomization for mass-parallel Isaac Lab training without requiring the geometry provider in every environment.

Export provider- and scenario-versioned bounded distributions for broadband and banded transmission, blocked-path fraction, sequential-partition count, direct-to-indirect ratio, dominant indirect delay/level, and changes caused by doors or dynamic occluders. Consume those distributions offline through the scalable analytic path completed in R8.3; do not introduce an online geometry-provider dependency into mass-parallel execution. Label the parameters as geometry-derived simulation data rather than measured physical calibration.

The temporary R9 adapters, runners, fixtures, report builders, validators, and tests are already removed. Implement one production Steam binding and validate provider-version upgrades directly through focused version, timing, assembly, pathing, signal, and performance tests at that boundary. Remove redundant geometry, material, or occlusion paths as the production integration settles. NVIDIA RTX Acoustic remains documentation and historical evidence only, with no executable or configurable provider surface. Do not keep provider-specific public observations or test-only runtime shortcuts.

#### Key Decisions

- `GeometryAcoustics` is the primary daily high-fidelity Isaac path.
- `AnalyticAcoustics` remains the scalable Isaac Lab path.
- One selected geometry provider is the maintained high-fidelity integration.
- Provider-specific controls remain behind the provider capability boundary.
- One production Steam adapter owns runtime behavior and focused requalification.
- Public perception and dataset contracts remain signal-producer-independent.
- Geometry-derived distributions transfer bounded behavior, not provider implementation details or raw path traces, into the analytic path.
- Geometry, analytic, and physical producers preserve the same `MicrophoneSignalBlock` input boundary and downstream perception contracts.

#### Problems / Limitations

The geometry backend is not required to scale directly to thousands of simultaneous Isaac Lab environments. Transferred distributions apply only to the provider's simulated scenario family. Preserve only the minimum probes and resources required to operate or revalidate the selected provider. Before adopting a newer Steam release, rerun the focused version, timing, assembly, pathing, signal, and performance gates against its exact stable tag.

## Artifacts

Expected artifacts are a provider-backed `MicrophoneSignalBlock` producer, USD
acoustic mapping within the qualified transmission boundary, baked pathing,
bounded lifecycle and diagnostics, unchanged perception semantics across
analytic, geometry, and physical inputs, and one consolidated maintained
geometry-provider surface. No R10 implementation artifacts exist yet.

## Files

Implementation files remain to be determined by the selected provider's adapter design.
