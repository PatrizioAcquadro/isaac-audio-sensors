# Phase R10 — Geometry Acoustics Integration

Status: R10.1 / 08.1 completed within the documented scene-preparation boundary. R10.2 and R10.3 remain planned.
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
Explicit proxy targets are included even outside the selected roots or when
hidden for rendering. Selection is conservative: there is no automatic triangle decimation or
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

The 08.1 preparation follow-up adds seven scattering-only entries from the
same frozen Pyroomacoustics database: RPG Skyline/QRD, theatre audience,
classroom tables with seated persons, amphitheatre steps, and the Round Robin
III wall/ceiling boxes. Their native bands and source conditions are retained;
`ias:scattering_material_id` selects this family without replacing absorption or
transmission. Coefficient overrides still take precedence. These configurations
must not be inferred for generic walls or double-count explicitly modelled
furniture. The original 23 absorption presets retain nominal scattering 0.05.
The catalog now contains 30 entries; consumers request only the families they use.
Source: [Pyroomacoustics scattering database](https://pyroomacoustics.readthedocs.io/en/pypi-release/pyroomacoustics.materials.database.html#scattering-coefficients).

The nine legacy nominal presets and aliases remain available for explicit
selection. Default name associations now require construction-specific labels;
generic wood/glass/metal labels no longer silently assign nominal transmission.
Missing families use identified scene fallbacks. Existing authored association
maps remain authoritative and editable, including deliberately nominal maps.
No physical measurement by the user is required; source data do not establish
calibration of an arbitrary imported asset.

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

The follow-up editor uses collapsible sections consistent with Advanced Tools,
selection-populated roots, separate inclusion/motion/source columns and focused
filters. Component selection resolves descendant and per-face materials; fields
show common effective values or Mixed, with independent frequency grids.
Applying coefficients validates all pending inputs first and writes only edited
families. Per-family reset, full automatic-material restoration, documented
scattering assignment, editable persisted defaults and selection-based acoustic
proxy relationships share the same USD service and Kit Undo/Redo. Unchanged
refreshes at the same time code poll dynamic poses and skip repeated traversal
when those poses are unchanged. PhysX movement without normal USD notices still
triggers a full selective update. Shared discovery indexes direct children rather
than rescanning the complete stage for every potential array.

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

Automatic semantic room reconstruction, deformable/subdivision/point-instanced
geometry and transmission through thick or sequential constructions remain
deferred. Existing room volumes identify containment; their absence does not
prevent importing physical room surfaces. Multi-construction transmission needs
a separate provider/model investigation and requalification, not a UI workaround.

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

#### Completion Evidence

The 18 focused real-USD/native tests cover concave polygons, hole faces,
primitives, instances, units, per-face materials, explicit precedence,
selective refresh, partition grouping, persistence, connected-room containment
and explicit proxies outside selection roots. Exported native vertices match
USD vertices after transform updates. The live RTX 4090 gate verifies Kit
editing, Undo/Redo, PhysX motion with USD transform writes disabled, native
resource reuse and panel capture. The complete Kit extension regression passes.
The follow-up adds selection/mixed-value and independent-family tests, proxy
relationship persistence and live Undo/Redo. The 266-object preparation fixture
checks native/static reuse, duplicated representations, robot/housing inclusion,
removal, reset and stage replacement. Profiling removes quadratic child discovery;
idle p95 is about 0.48 ms, initial import about 302 ms, and local movement/material
updates about 135/145 ms in the measured Kit run. Those update costs remain a limit
for larger/dynamic stages and must be included in the early R10.2 profiling gate.
Host and supported-runtime gate totals are recorded in [[status|Current Status]].

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

#### Early complete-path and scaling decision gate (planned)

Start 08.2 with a minimal production slice: prepared USD scene, source PCM,
qualified CPU/Embree propagation, physical microphone PCM, and the unchanged
observed-only perception/Lab projection. Verify this slice before expanding
provider features or implementing GPU acceleration. 08.1 scene creation alone
is not a propagation or training benchmark.

Use [[implementation_phases/07-isaac-lab-observation-integration#Practical Baseline Closeout|07.2 practical measurements]]
as the historical comparison, and rerun its maintained workload on the same
host/runtime when comparing implementations. That baseline is an entity-bound
free-field PCM producer plus CUDA perception, not a qualification of arbitrary
rooms or all AnalyticAcoustics solver modes. It uses 16 kHz PCM, 60 Hz acquisition,
10 Hz observations, a 750 ms past context, two independent active file sources,
and planar four-microphone / raised five-microphone layouts. Preserve these
settings and the scalar received-PCM reference, including misses and extra events.
The historical 4096-copy run is exploratory, not a required performance target.

Measure 2/16 environments first, then 32/64/128/256 as memory and time permit.
Separate matched free-field behavior from representative indoor geometry:
compare waveform/timing correctness on equivalent physical cases, and compare
perception against the scalar reference on each provider's actual received PCM.
Do not require reverberant PCM to equal free-field PCM or rank providers after
silently dropping reflections, sources, channels or observation work.

Report uninstrumented steady-state mean/p95 wall time, simulated/wall ratio,
aggregate environment updates per wall second, host memory, peak GPU memory,
CPU use, warm-up and partial-reset cost. Profile USD discovery/update, native
scene commit, acoustic simulation/refresh, PCM rendering/delays, CPU/GPU copies
and synchronization, context, detector, WPE, localization and projection
separately; nested timings must not be summed twice. Distinguish audio-only
runs from runs sharing GPU resources with Isaac rendering/physics and, when
available, actual learning. Do not describe an extrapolated duration as a
completed training run. 07.2 found WPE/localization dominant in its free-field
workload; that does not establish the bottleneck of geometric propagation.

Review Linux + NVIDIA feasibility early. Steam 4.8.1 does not expose a qualified
CUDA switch in the maintained build. Its documented Radeon Rays path is not a
ready Linux solution. Custom ray-tracing callbacks are an investigation option,
not proof that simulation, convolution or multi-environment scheduling moves to
CUDA. Consult the current [Steam guide](https://valvesoftware.github.io/steam-audio/doc/capi/guide.html)
and [Scene API](https://valvesoftware.github.io/steam-audio/doc/capi/scene.html).
Only prototype GPU acceleration for a measured bottleneck, on the actual RTX
4090, with matched fidelity, transfer/synchronization cost and competing GPU
workloads included. Prefer an existing maintained implementation over a new
repository-owned ray tracer. Proceed to a production option only after a
meaningful end-to-end gain and correctness/packaging qualification. A negative
feasibility or gain result is an acceptable documented outcome; no CUDA delivery
or full-GPU pipeline is promised by this plan.

Retain AnalyticAcoustics during implementation and measurement. At this gate,
record whether geometric and analytic paths serve distinct verified roles.
Retire the analytic path only if the geometric implementation covers its active
consumers, platform/installation needs, controllable simple scenarios, signal
contracts and practical training throughput, followed by migration and regression
checks. Otherwise keep both with explicit roles. GPU acceleration alone is not
a retirement criterion, and retaining both forever is not predetermined.

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

Target high-quality operation for one or a few Isaac environments first. Apply the R10.2 scaling/retention decision when choosing the maintained training path. If the analytic path retains a distinct role, expose bounded geometry-derived statistics that can inform its randomization without requiring the geometry provider in every environment.

Export provider- and scenario-versioned bounded distributions for broadband and banded transmission, blocked-path fraction, sequential-partition count, direct-to-indirect ratio, dominant indirect delay/level, and changes caused by doors or dynamic occluders. When the analytic path is retained, consume those distributions offline through R8.3. An online geometry provider for parallel execution requires the R10.2 complete-path scaling gate; it is neither assumed nor categorically excluded. Label the parameters as geometry-derived simulation data rather than measured physical calibration.

The temporary R9 adapters, runners, fixtures, report builders, validators, and tests are already removed. Implement one production Steam binding and validate provider-version upgrades directly through focused version, timing, assembly, pathing, signal, and performance tests at that boundary. Remove redundant geometry, material, or occlusion paths as the production integration settles. NVIDIA RTX Acoustic remains documentation and historical evidence only, with no executable or configurable provider surface. Do not keep provider-specific public observations or test-only runtime shortcuts.

#### Key Decisions

- `GeometryAcoustics` is the primary daily high-fidelity Isaac path.
- Retain `AnalyticAcoustics` as the current Lab baseline; apply the R10.2 evidence-based decision before retiring it or maintaining both paths long term.
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
