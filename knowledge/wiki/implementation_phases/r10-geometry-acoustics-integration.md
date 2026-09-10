# Phase R10 — Geometry Acoustics Integration

Status: R10.1 implementation in progress; R10.2 and R10.3 remain planned.
R9.4 risk retirement is complete and constrains the supported R10 scope.
[[implementation_phases/08-geometry-acoustics-integration|Implementation Plan 08]]
references the R10.1–R10.3 execution order but adds no technical requirements.
This page is the sole authority for the geometry integration.

## Objective

Integrate the provider selected by [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] as the primary high-fidelity simulated signal producer for one or a few passive-audio Isaac environments. Its final microphone signals enter the same backend-independent observed-perception path used by analytic simulation and physical capture.

Geometry integration improves received-signal modeling; it does not automatically resolve the maintained localizer's count/direction failures. Follow the bounded 07.2 and 07.3 progression in [[status|Current Status]], preserve the shared audio-only perception boundary, and qualify perceptual claims separately under [[implementation_phases/10-end-to-end-validation-and-product-closeout|Phase 10]]. General temporal reliability remains unqualified while its research iteration is suspended.

R10 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the selected integration must replace temporary, unselected, duplicate, and legacy geometry paths rather than adding another permanent layer beside them.

## Subphase R10.1 — USD Acoustic Scene

#### Implementation

`AcousticSceneSession(stage, roots=None)` prepares the composed USD stage without
requiring per-object selection or collision APIs. The session imports polygonal
meshes, cubes, spheres, cylinders, cones and capsules, including referenced and
instanced geometry. Concave polygons use boundary-preserving triangulation and
USD hole faces remain absent. Curved primitives use bounded polygonal
approximations (32 radial segments; sphere/capsule caps use 16 angular intervals).
Units, up-axis and transforms are converted to Steam's meter/Y-up convention.

Explicit `ias:acoustic_geometry` relationships replace the owner's visual
geometry. Otherwise physical geometry participates automatically. Guide/debug
geometry, invisible geometry and conventional collision siblings of visual
representations are excluded with reasons; explicit inclusion can override the
selection. Technical sound/listener/Xform prims do not become triangles, while
physical robot, source and microphone-housing children remain eligible.
Selection is conservative: there is no automatic triangle decimation or
replacement of an object by its bounding box.

The service owns separate cached geometry, resolved materials, partition
qualification and poses. USD change notices invalidate affected objects;
steady-state refreshes reuse static geometry. Rigid bodies and animation are
detected automatically, with optional static/dynamic overrides. During live
PhysX simulation, body poses are read from PhysX even when transform writes to
USD are disabled. Reset and close release owned native resources. The existing
room resolver checks complete arrays against authored room volumes; absent or
ambiguous containment remains unknown. Local room selection never cuts the
provider scene or excludes sources in another room.

**Materials.** The single Core catalog now retains original absorption bands,
including 8 kHz where supplied by PyRoom's documented table, and includes common
hard surfaces, ceramic, linoleum, rubber floor coverings, ceiling tile, fibre
absorbers and melamine foam. Existing identifiers/aliases remain valid and
`resolve_material_coefficients()` still defaults to the six analytic bands.
Passing `band_centers_hz=None` returns native catalog bands. Scattering is a
separately labeled nominal coefficient, not measured evidence inherited from
absorption. Existing nominal broadband labels derive from the shared catalog.

Resolution is per coefficient: prim/construction overrides, bound acoustic
material properties, configured name/semantic associations, then scene defaults.
Associations are inferred, not calibrated visual-material truth. Invalid explicit
coefficients fail preparation. The defaults are `pra.hard_surface` absorption,
nominal scattering 0.05, and opaque transmission when no usable curve exists.
Missing coefficient families retain their own fallback provenance.

Steam absorption and transmission are resampled at 400/2500/15000 Hz with linear
interpolation on log frequency and endpoint hold. The high-frequency extension
is an approximation, not measured 15 kHz material data. Banded scattering is
sampled at 1000 Hz for Steam's scalar field. Transmission dB is converted once
in the private adapter using the R9-qualified amplitude mapping
`10**(-loss_db/20)`; the documented Scene API energy wording does not justify
changing the qualified direct-effect mapping.

**Assemblies and native scene.** `ias:acoustic_partition_id` and USD component
identity group fragments without reparenting visual objects. Equal labels or
nearby surfaces alone do not merge distinct constructions. Coplanar fragments
with consistent whole-assembly properties enter one native assembly. Closed or
nonplanar constructions remain opaque, with an explicit unsupported-transmission
message. The rejected paired-face proxy and output gain compensation are absent.
Distinct sequential-assembly transmission remains unsupported.

The private optional Steam binding owns an Embree device, scene, static meshes
and movable native instances. Updates replace only affected assemblies or update
their transforms. Native OBJ export supports geometry preparation review. Steam
4.8.1 has no exact runtime version query and accepts newer compatible minor APIs;
therefore the binding checks the exact qualified R9 Release/Embree binary before
loading it. A different build needs requalification. The library is not bundled
or downloaded, and no audio backend is registered by this subphase.

**Shared authoring and Kit panel.** The existing extension window includes
“Acoustic Scene”: import/update, roots, searchable object list and stage
selection, multiple-object inclusion and motion overrides, catalog selection,
coefficient/frequency fields, grouping, scene defaults and editable associations.
Selection details expose coefficient sources and provider values. Python edits
and Kit actions operate on the same USD properties and current edit target;
Kit Undo/Redo restores only the touched properties. Reimport preserves authored
corrections. Native scene verification is optional; backend operation and
propagation diagnostics remain R10.3 responsibilities.

Preparation state distinguishes unprepared, prepared, preparation with issues,
and native scene verification. These states do not establish microphone audio
or perceptual qualification.

#### Key Decisions

- USD remains the authoring authority; there is no separate Kit material catalog.
- Preserve the analytic six-band interface while retaining source frequency data.
- Keep the qualified planar transmission boundary and explicit opaque fallbacks.
- Reuse provider-native mesh/instance operations; no IAS propagation solver.
- The preparation panel is intentionally delivered in 08.1; operational controls
  and propagation diagnostics remain in 08.3.

#### Problems / Limitations

Subdivision surfaces, deformable meshes, point instancers and unsupported Gprim
forms require an explicit polygonal acoustic representation. Missing payloads,
composition failures and invalid geometry prevent an unqualified completion
state. Automatic visual/collision deduplication recognizes conventional sibling
representations; unusual authoring requires explicit inclusion/exclusion or an
acoustic-geometry relationship. Instance-proxy properties are edited at the
instance root or source material, respecting USD composition rules.

Native qualification is restricted to the selected binary and tested scene
family. Planar assembly preparation does not qualify predictable transmission
through sequential constructions, physical material calibration, or general
acoustic realism. Source content, propagation PCM, pathing and perception remain
R10.2 work.

The native matrix update initially used an incorrect ctypes array-by-value ABI.
A coordinate comparison caught the problem; the binding now passes the actual
matrix struct. Native exported coordinates are checked against transformed USD
vertices after movement. This is a geometry integration test, not an acoustic
output claim.

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

Moving doors and occluders must produce temporally meaningful changes in the received signal as direct and indirect paths change. Address transition artifacts and stale geometry in the supported provider domain; visual smoothing alone does not establish acoustic continuity. Do not promise exact edge diffraction, thickness-derived transmission or structural wall behavior beyond the qualified provider capabilities. The current analytic direct-loss model remains a simpler, separately bounded approximation.

## Subphase R10.3 — Operating Integration and Cleanup

#### Implementation

Integrate the selected provider's lifecycle, static-scene caching, bounded dynamic updates, configuration, Kit workflow, diagnostics, and packaging behind its capability boundary. Maintain one selected geometry-provider integration rather than exposing redundant experimental backends or provider-specific scene state through Core observation contracts.

Expose useful acoustic participation, material assumptions, unavailable capabilities and provider-reported path/occlusion state through the existing diagnostic workflow. Keep these simulation facts visibly separate from observed activity, event count, direction and estimator reliability. Define color meanings explicitly: an occluded geometric route does not prove low direction reliability, and low RMS does not prove occlusion. Never assign a blocked source's truth to an observed event without a justified association. Observed event/candidate presentation is consolidated in 07.3; this phase adds provider diagnostics, not oracle perception.

Complete the geometry-backed sensor-to-instrument chain for a bounded occlusion demonstration. [[topics/onr-video-production|ONR Video 4]] can target this point for the fuller geometry version, after its specific scene is shown to work. Completion of 08.3 is not automatic approval of a video or proof of every possible occlusion scenario.

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
geometry-provider surface. R10.1 now provides the USD preparation service,
shared Kit panel and private native scene binding. Local evidence is under
`build/validation/r10/scene/` (GPU scene/Undo/Redo/coordinate checks and panel
capture) and `build/validation/r10/kit/` (complete extension regression). R10.2
and R10.3 artifacts remain future work.

## Files

- `src/isaac_audio_sensors/isaac/acoustic_scene/`
- `src/isaac_audio_sensors/core/acoustics/materials.py`
- `src/isaac_audio_sensors/kit/acoustic_scene.py`
- `tests/isaac/test_acoustic_scene.py`
- `tools/smoke/live_acoustic_scene.py`
