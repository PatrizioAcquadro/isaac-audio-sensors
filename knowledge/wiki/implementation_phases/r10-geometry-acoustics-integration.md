# Phase R10 — Geometry Acoustics Integration

Status: R10.1 / 08.1 and the intermediate coherent hybrid milestone are completed within their documented boundaries. The user confirms priority Profile 1 (AV attention/search) and complementary Profile 2 (mobile robot audition) within Milestone 2 robot-audition fidelity (2026-09-11): bounded task qualification and integration remain pending; absolute dynamic-acoustic completeness is no longer the admission gate. R10.3 remains planned.
R9.4 historical risk retirement constrains the supported scope; its stronger NLOS arrival/TDOA interpretation is withdrawn by the Milestone 2 recheck below.
[[implementation_phases/08-geometry-acoustics-integration|Implementation Plan 08]]
references the R10.1–R10.3 execution order but adds no technical requirements.
This page is the sole authority for the geometry integration.

## Objective

Integrate the provider architecture selected by [[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] as one simulated signal producer sufficiently faithful for robot audition in a declared indoor domain, initially one or a few passive-audio Isaac environments. Its final microphone signals enter the same backend-independent observed-perception path used by analytic simulation and physical capture. The authorized hybrid direction permits complementary native engines behind this boundary; each contribution still requires qualification.

Geometry integration improves received-signal modeling; it does not automatically resolve the maintained localizer's count/direction failures. Follow the bounded 07.2 and 07.3 progression in [[status|Current Status]], preserve the shared audio-only perception boundary, and qualify perceptual claims separately under [[implementation_phases/10-end-to-end-validation-and-product-closeout|Phase 10]]. General temporal reliability remains unqualified while its research iteration is suspended.

R10 follows the [[decisions/minimal-maintained-repository-surface|Minimal Maintained Repository Surface]] decision: the selected integration must replace temporary, unselected, duplicate, and legacy geometry paths rather than adding another permanent layer beside them.

## Active scope — Robot-audition fidelity (2026-09-11)

**This latest user decision explicitly revises the earlier requirement to preserve
complete dynamic-acoustic coverage.** It supersedes older “full scope unchanged”,
universal dynamic-field admission and mandatory time-dependent path-search
statements on this page. Those dated results remain historical evidence, including
failed controls; they are not erased or retroactively marked passed.

R10 delivers a useful Isaac Audio Sensor for localization, multisource and
audio-visual perception, and policy-learning research. It does not aim to publish
a new acoustic engine or reproduce every moving-boundary wave interaction.
An approximation is admissible when its error is bounded and does not materially
misrepresent observations or task decisions within the declared operating domain.
An unknown effect remains unqualified for that domain; it does not automatically
block all supported uses or force a provider replacement.

### Confirmed profiles and ownership

The user confirms **Profile 1: AV attention/search as the priority**, and
**Profile 2: mobile robot audition as the complementary qualification profile**.
Both belong to the final declared R10 domain; implementation and validation
proceed in that order. A Profile 1-only delivery may be recorded as an intermediate
result, but must not silently close the complementary Profile 2 requirement.
The SDK remains reusable across robots. Geometry Acoustics must be qualified as a
robot-audition signal producer, not as a general-purpose acoustic engine.

| Profile | Representative simulated conditions | Task evidence |
| --- | --- | --- |
| 1 — AV attention/search | Fixed base with rotating head/array; stationary and moving out-of-view sources; sustained and intermittent sounds; one source and competing sources/distractors; LOS, weak direct, reverberation and physical occlusion | Useful visual-search direction, probability of placing a visible source in the camera FOV, time to visual acquisition, unnecessary searches, wrong associations and loss/reacquisition behavior |
| 2 — Mobile robot audition | Translating/rotating receiver; moving sources; rooms and connected corridors; ordinary door/obstacle motion; sustained NLOS and changing dominant arrivals | Localization/availability during motion and scripted observed-only homing/navigation; success, timeouts, collisions and route efficiency against paired audio-disabled controls |

Profile 1 is motivated by the approved SquadBot AV fixed-Alex003 scope:
hear an out-of-view person or relevant event, orient head/neck, obtain visual
confirmation and update the downstream graph. Its mobile approach is deferred.
The local authority is the sibling repository's
`knowledge/wiki/topics/alex003-scope-and-roadmap.md`; the approved original is
[Alex003 Purdue/IHMC scope](https://github.com/PatrizioAcquadro/squadbot-av/blob/0de1e40aa50a1781bc61b4be4deb6bc04c55b8e8/implementation_phases/_program/alex003_purdue_ihmc_integration_scope.md).
SquadBot's immediate fixed-platform boundary does not remove the SDK's mobile
profile. Conversely, broad SquadBot exploration goals do not import every robot
mobility, manipulation or high-speed acoustic effect into R10 acceptance.

Keep out-of-FOV sources separate from physically hidden sources. A source that
remains behind an opaque wall need not become visually confirmable after a turn;
a valid result can retain an unconfirmed acoustic cue. An NLOS arrival may point
toward an opening rather than the hidden source. Score these meanings separately.
False visual confirmation or an easier result caused by an acoustic artifact is
not successful fidelity validation.

Use a bounded simulated consumer harness to assess task impact. Robot-specific
joint adapters, semantic target selection, persistent visual tracking and scene
graphs remain downstream. R10 does not implement an AV recognition system or
complete SquadBot's robot phases. Simulator visual annotations may support an
explicit reference consumer and independent scoring; they do not qualify a
learned detector or physical recognition. Do not feed emission schedules, hidden
bearings or source IDs to audio perception or navigation decisions.

The earlier candidate values for room dimensions, source/receiver speeds,
reverberation and task-error margins remain proposed engineering settings, not
approved partner specifications or measured capability. Freeze the concrete
matrix and numerical budgets before qualification runs. Camera FOV, usable joint
range, mounting and observation timing determine the orientation task's error
budget; a static bench's FOV is not automatically the final robot camera's FOV.
Physical Alex003 mounting and partner acceptance are not dependencies for R10's
simulation-only qualification or reasons to invent hardware performance targets.

### Required behavior and permitted approximations

| Area | Required for the supported robot-task domain | Not an unconditional R10 requirement |
| --- | --- | --- |
| Direct and dominant indirect arrivals | Meaningful path delays, inter-microphone TDOA, arrival directions, level/visibility trends; no duplicate LOS or contribution energy | Exact diffraction or every physically possible path through asynchronously changing openings |
| Source and receiver motion | Continuous PCM and timing, useful spatial cues during translation/rotation, source-stop tails and bounded update artifacts | Exact moving-boundary propagation or phase evolution at every late multibounce interaction |
| Doors and obstacles | Correct sustained open/closed behavior and alternate-route effects; measured transition latency/artifacts under representative trajectories | Full space-time native graph search solely to pass the millisecond two-gate boundary control |
| Reverberation and diffuse sound | Plausible banded energy/decay, meaningful joint microphone statistics and motion behavior in task-relevant bands/DRR conditions | Matching the exact stochastic phase of an arbitrary room; isotropic covariance in non-isotropic rooms |
| Integration | Common PCM clock, audiovisual timing, no truth in perception/policy, reset/partial-reset/isolation, unchanged public schemas and working consumers | Replacing Analytic or creating a repository-owned multibounce engine to obtain completeness |

**Non-negotiable invariants within either declared profile:**

- Preserve a causal common source/receiver clock, meaningful direct/dominant
  indirect delays and inter-microphone timing/direction cues. Never substitute
  Euclidean delay for an exported detour or apply physical delay twice.
- Respect sustained visibility and the declared transmission model; do not admit
  unexplained propagation through opaque partitions. Direct/transmitted,
  reflected/scattered and deviation contributions have explicit non-overlapping
  ownership, attenuation and energy accounting.
- Construct a valid joint multichannel field with meaningful co-location and
  spatial statistics. Do not manufacture independent receiver signals and repair
  their covariance afterward, or tune gain/phase to obtain preferred task scores.
- Preserve finite PCM, source-stop tails, meaningful motion/update continuity,
  unchanged-scene reproducibility, reset/partial-reset and environment isolation.
  Respect shared AV timestamps and keep truth confined to diagnostics/scoring.
- Declare model, material and coverage limits. Sampling/numerical tolerances must
  be physically and task justified; no artifact may be hidden by display smoothing,
  favorable scoring exclusions or silently disabled requested contributions.

These invariants prevent misleading sensing even when one consumer happens to
perform well. They require correct behavior within the adopted model, not exact
late-path phase or complete moving-boundary wave physics.

Quasi-static geometry updates, bounded reflection order and statistical late
reverberation are candidate approximations, not automatic passes. Interpolation
may suppress update artifacts but cannot substitute for arrival/TDOA correctness.
Keep native timing tests (including one-sample agreement with an exported route)
as implementation checks; a simplified native route need not equal an exact
wave-diffraction solution. Physically justified energy accounting, visibility,
co-location and shared-channel consistency remain required checks. Do not fix
independent microphone noise afterward or fit gains to obtain a desired score.
A shared statistical field need not preserve exact late-path phase if the relevant
spatial/temporal statistics and task behavior survive the approximation.

For illustration, at the configured 343 m/s, a 10 m path takes 29.15 ms. A source
moving at 0.5 m/s moves 14.6 mm during that time. That path change would correspond
to about 15 degrees of phase at 1 kHz and 61 degrees at 4 kHz; actual path-length
change depends on geometry. Reverberant travel can last much longer than the
single room crossing. Slow geometry therefore motivates testing quasi-static
updates, but does not prove that microphone phase or diffuse-motion errors are
irrelevant. Compare retained reverberation duration, update interval, motion,
wavelength and observation time scale within the task profile.

### Qualification by material task impact

Before the next implementation comparison, record a compact operating profile:
room/corridor sizes around the intended approximately 10 m indoor use, source and
array translation/rotation, actual door trajectories, microphone spacings and
frequency band, reverberation duration and direct-to-reverberant ratio (DRR).
Include stationary and moving receivers/sources, single and simultaneous sources,
LOS, sustained NLOS and weak-direct/reverberant cases. Start from the maintained
four/five-microphone consumers and measured 0.1/0.5 m/s source cases; these are
initial test points, not proven speed limits or universal product restrictions.
Separate representative cases from deliberately extreme boundary tests and keep
both visible. Do not choose only strong-direct cases because they already pass.

For each task, fix numerical materiality budgets **before** examining candidate
results, using the task's spatial/angular resolution, control tolerance,
observation hop and acceptable success-rate change. Record the budgets with the
trial configuration. There is no universal coherence, phase or DOA threshold
that by itself certifies robot-audition fidelity. Existing 0.1 controlled-field
coherence and one-sample route checks retain their specific meanings; neither
alone closes or globally blocks R10. No numerical task budget has yet been
qualified by this scope-revision task.

Use paired sources/trajectories and independent stochastic realizations; refine
geometry-update intervals and acoustic sampling, and include independent analytic
or controlled native references where available. A reference must be valid for
the property being tested: free field, a single plane or another provider is not
an absolute room oracle. Preserve realistic reverberant difficulty. Compare
intermediate, corrected-NLOS, diffuse and combined configurations as available,
without supplying paths, source identity or hidden bearing to the consumer.

Measure DOA/TDOA error, unmatched/extra observations, ambiguity, latency and
spurious motion/visibility transients. Score NLOS arrival direction separately
from the hidden source bearing. For priority Profile 1, measure useful camera acquisition, unnecessary search,
false confirmations and added cue-to-acquisition latency under matched camera,
controller and source trajectories. Separate acoustic/perception delay from
mechanical turning and visual processing; report unavailable cues and unresolved
NLOS cases rather than dropping them. For complementary Profile 2, check task
benefit with the already selected scripted, untrained closed-loop homing/navigation
consumer, then competing-source trials: success, collision/timeout rate and route efficiency against paired
audio-disabled trials. Geometric collision avoidance is permitted; acoustic
truth and target identity are scoring-only inputs. Check audiovisual timestamps
and the existing Lab consumer boundary without adding a new AV model or policy
training campaign. Use the existing localizer plus an independent delay/spatial
cue check so an artifact that helps one estimator cannot establish fidelity.

Report paired confidence intervals at independent-trial level, including
misses and censored latency, rather than treating adjacent frames as independent.
For a negligible-impact claim the interval must fit inside the declared error
budget; failure to find statistical significance is not equivalence. Avoid
averaging away weak-direct or occluded strata. Material changes in either
direction require explanation: artificially easier perception can bias learning
as well as degraded perception. Simulation tests establish bounded simulated
utility and sensitivity, not real-world transfer; transfer remains a separate
validation claim with no new physical recordings required for this milestone.

### Effect on the existing findings and next work

- **Corrected Steam timing remains valuable:** the corridor control changes mean
  arrival-direction error from about 58 degrees to 0.037 degrees. Preserve and
  integrate that correction with bounded geometry updates and lifecycle checks.
- **The two-gate failure becomes a documented stress limit:** its occurrence and
  task impact under ordinary door motion are unmeasured. It no longer forces full
  temporal graph search before practical NLOS qualification. Promote that work
  only if representative in-domain trials expose a material unbounded gap.
- **The PRA weak-direct finding remains material evidence:** at 0.5 m/s the plane
  control adds 34–43 percentage points of unmatched directions, while strong
  direct cases change little. These are controlled sensitivity results, not a
  universal room failure or a newly admitted diffuse renderer. Representative
  weak-direct room/motion trials remain required; renaming the scope cannot waive
  an observed large bias in a condition claimed as supported.
- **Later-scatter phase failure is diagnostic, not an automatic redesign order:**
  qualify the statistical approximation by energy, spatial/temporal cues and task
  impact before deciding whether exact surface persistence is necessary.

The next implementation path is corrected NLOS plus bounded task-domain diffuse
qualification using the existing providers. Keep production defaults unchanged
until those contributions pass their declared gates. A specific condition may
remain explicitly unsupported without invalidating other qualified conditions;
Milestone 2 closes only when the declared representative domain, integrated
stream/lifecycle and practical-use gates pass. It is not complete today.

A larger PRA fork or a whole-reflection provider comparison is justified only by
a material in-domain gap that simpler native/statistical extensions cannot
close. The prior recommendation to begin that comparison is suspended pending
this task-impact assessment. Do not begin a replacement evaluation without the
user decision already required by the session. No additional permanent provider
is implied. Final performance/scaling qualification remains deferred; no policy
training, physical campaign or alternate engine is added to this scope revision.

Task-oriented evaluation has precedent: [SoundSpaces 2.0](https://arxiv.org/abs/2206.08312)
combines acoustic measurements with embodied-navigation and far-field speech
recognition evaluations. Its reported sim-to-real result for speech recognition
is not evidence of transfer for this SDK. This is methodological context, not a
new provider evaluation or endorsement.

### Remaining Phase 08 closeout gates

| Gate | Current verified state | Work still required |
| --- | --- | --- |
| 08.1 scene preparation | Completed in its documented geometry/material/runtime boundary | Preserve it while integrating admitted contributions |
| 08.2 operational intermediate | Steam direct/transmission + native PRA specular PCM and existing consumer smokes work | Retain compatibility and Analytic |
| 08.2 Profile 1 priority | Scope confirmed; native timing and controlled diffuse sensitivity evidence exist | Freeze domain/budgets, integrate corrected NLOS and a qualified joint diffuse approximation, then demonstrate useful AV attention/search under representative conditions |
| 08.2 Profile 2 complement | Analytic and native motion controls exist; they do not qualify the full Geometry profile | Qualify moving-array/source cues, ordinary door transitions and observed-only mobile task benefit |
| 08.2/08.3 runtime and lifecycle | Intermediate runtime evidence exists | Repeat affected stream/reset/isolation, scalar/CUDA, actual Isaac Sim/Lab/Kit and packaging checks for the admitted implementation; finish final declared-domain performance qualification after Milestone 2 |
| 08.3 operating integration | Scene preparation UI and common observed instruments exist | Complete production configuration, capability/error reporting, truthful provider diagnostics, sensor-to-instrument workflow and consumer-safe consolidation |

The scope is now suitable for completing Phase 08, but the phase is **not
complete**. The current production configuration does not enable the experimental
Steam route or PRA joint diffuse contributions. Reclassifying stress failures is
not their admission. Exact asynchronous path history is no longer a global
blocker; the measured weak-direct diffuse bias still needs a materiality decision
for each claimed condition. No replacement provider is selected or required by
this update.

Final performance/scaling is outside Milestone 2, not silently marked completed
by this change. Use the existing one/few-environment target and explicit supported
runtime claims; 32–256 exploratory scaling and acoustic GPU acceleration are not
prerequisites for a bounded AV demo. Physical recordings, policy training and
robot-specific hardware acceptance are not added as Phase 08 requirements.

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

When using Steam pathing, retain the R9.4 native configuration and requalify physical path timing as required by the Milestone 2 gate below: deterministic `DYNAMIC` probe
batches, provider-default UTD deviation, one independent point receiver and
`IPLPathEffect` per microphone, and the omnidirectional component of the
non-spatialized Ambisonic field. Retain dynamic validation, alternate-path
search, and bounded path-visualization callbacks. These capabilities support
approximate pathing in the qualified scenario family; they do not establish
general diffraction accuracy.
The hybrid architecture must qualify ownership and non-overlap with the selected
reflection renderer before summing these contributions. R9 permits functional
indirect NLOS through native reflections or pathing; a replacement renderer does
not inherit the Steam-specific API requirement, nor its historical qualification.

Isaac Audio Sensors owns source content, provider lifecycle, source and array translation, microphone semantics, signal effects not owned by the provider, diagnostics, and signal provenance. The external engine owns mesh acceleration, ray traversal, multi-bounce reflection, scattering, and every enabled path-search or deviation algorithm. `AudioPerceptionPipeline`, outside the geometry backend, owns activity detection, optional DOA estimation, `AudioObservation` creation, and `AudioSensorFrame` construction.

Prefer provider-native arrival-time rendering when a qualified stable Steam API
supplies it. Steam `4.8.1` direct and pathing effects do not apply physical
arrival time to PCM, so the private Steam adapter owns the qualified continuous
fractional-delay scheduler on one shared source timeline. Apply it once to
direct and pathing. The earlier assumption that reflection IRs already supplied
correct absolute microphone timing is withdrawn by the initial gate below.
R9.4 verified unchanged reflection PCM, not absolute reflected arrival or
inter-microphone timing. No additional delay, gain compensation or local
reflection solver is admitted as a substitute for requalification. Remove the
bridge when a requalified provider release owns equivalent PCM timing.

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

#### Initial complete-path gate — NO-GO (2026-09-10)

A candidate extended the existing scene binding with persistent native direct
and reflection effects, the R9.4 continuous delay bridge, `MicrophoneSignalBlock`,
scalar sensing and isolated Lab producers feeding the unchanged CUDA perception.
Four focused native tests passed direct/free-field amplitude and phase comparison,
static split-block equality, short-distance gain, lifecycle rejection and
functional reflected output behind a blocker. These were candidate checks;
no new production backend was retained.

The actual RTX 4090 planar free-field run used the 07.2 workload settings:
16 kHz, 60 Hz acquisition, 10 Hz observations, 750 ms context, two independent
active file sources, and 30 measured updates after warm-up. Two environments
measured 78.17/81.39 ms mean/p95 and preserved scalar counts (2/2) and directions
on identical received PCM. The restored Analytic baseline, rerun on the same
host with the same two-environment workload, measured 40.04/40.90 ms
and passed its scalar/CUDA and partial-reset checks. Sixteen indoor environments with native reflections
measured 438.92/457.91 ms, but preserved counts in only 14/16 cases, below 97%.
A later capture passed 16/16 at 440.16 ms mean. Both indoor runs produced many
extra events; reliable indoor parity and perceptual utility are not established.
The first failed run has no saved PCM, so its scalar/CUDA discrepancy remains
unresolved. These are audio-only timings with a two-environment matched
free-field comparison, not a completed scaling comparison or training run.

**The decisive failure is native reflected microphone timing.** Five repetitions
used a single planar reflector, zero absorption/scattering, 65536 rays, one
bounce, four physical microphones and a delayed impulse at 16 kHz. With the R9
default distance model, all six cross-correlation lags were zero; the physical
single-plane image-source reference requires differences up to 6.6754 samples
(0.4172 ms). This exceeds the one-sample coherence tolerance used for the
microphone timing check. Capturing each native reflection output independently
reproduced the result obtained by subtracting direct-only PCM from the mixture.
A separate inverse-distance input control also failed. No output compensation
or extra reflection delay was applied.

Inspection of the exact qualified provider explains why preserving its IR bytes
is insufficient. `reflection_simulator.cpp` subtracts direct-path delay from
reflected travel time; `energy_field.cpp` uses 10 ms energy bins; the linear
`reconstructor.cpp` modulates deterministic noise with that energy envelope.
The public simulator selects this reconstruction. These facts invalidate the
former absolute-timing assumption and expose a limit of this independent
receiver/reflection-IR mapping. A common delay cannot restore missing physical
inter-microphone differences. This is not a universal impossibility result for
other providers, builds or rendering methods.

**Decision:** stop before pathing integration, larger scaling runs or a GPU
prototype. Retain Analytic as the operational baseline. The source/consumer
candidate was removed from the active package; its patch, native probe scripts,
PCM, reports and logs are preserved under `local/r10/08_2_gate/`, outside normal
build cleanup. R9 evidence and the 08.1 implementation remain unchanged.
Reapplying the saved candidate patch to an isolated copy of `5d96078` reproduced
all five native reports identically. The restored baseline passes `make check`
(646 unit/contract, 336 integration, 58 release tests) and its RTX 4090 Lab smoke.
The next required work is provider-native reflected-signal requalification for
physical microphone arrays, including absolute arrival and all-pair TDOA; then
repeat the complete-path gate before resuming the remaining R10.2 work.

#### Reflection timing recheck — NO-GO after reference correction (2026-09-10)

The follow-up explicitly restores the direct-path delay separately for every
receiver, using only source/receiver distance and 343 m/s. It does not fit the
output or use the reference reflection path to correct native PCM. Causal
windowed-sinc and linear fractional-delay controls both fail the reflected TDOA
criterion. Native direct and independent ideal-image controls pass, with maximum
timing error below 0.124 samples. The earlier missing time reference was real,
but correcting it is insufficient to qualify the reflected signal.

Sixteen native cases completed: five original-geometry repetitions at each of
Ambisonics orders 0 and 3, then array rotation, mirrored source and 48 kHz controls
at both orders. Higher-order simulation renders only the omnidirectional W
component at each independent physical receiver through the public channel-subset
API. Its PCM is identical to order zero in all tested geometries.

| Case | Corrected native maximum TDOA error | Pyroomacoustics control error |
| --- | ---: | ---: |
| Original, 16 kHz | 6.6754 samples | 0.1203 samples |
| Array rotated 45 degrees, 16 kHz | 7.5758 samples | 0.1220 samples |
| Mirrored source, 16 kHz | 6.6754 samples | 0.1203 samples |
| Original, 48 kHz | 20.0262 samples | 0.0389 samples |

All native cases fail the one-sample TDOA tolerance. In the original fixture,
microphones 1 and 3 have the same 93.3691-sample direct delay but require reflected
arrivals at 205.2817 and 211.9571 samples. Applying their equal direct delays
cannot recover the missing reflected difference. Corrected native onsets at
0.1% of peak are 571/417/578/574 samples after emission; threshold sensitivity and
peak locations are retained in the reports. Native reflection timing is not
qualified by changing the time origin, interpolation or sample rate.

An attempted full 16-channel convolution effect also crashed in this build.
GDB locates an aligned SIMD load on an unaligned accumulator in
`array_math.cpp:260`. Full multichannel rendering remains unqualified; the
completed W-only tests do not encounter this separate defect. No SDK was patched.
The native rendering alternatives and replacement-provider decision belong to
[[implementation_phases/r9-geometry-acoustics-provider-selection#Provider selection reopened after the R10.2 reflection gate|R9's reopened selection]].

The alternative control uses already-installed Pyroomacoustics 0.10.1 with its
generic polyhedral `Room`, first-order image sources and five fully absorbing
closure walls around the single reflector. It removes only the documented
40-sample fractional-filter group delay. All four cases pass reflected TDOA;
maximum peak-arrival error is 0.463 samples. This is a bounded reflection result,
not qualification of arbitrary USD, transmission, dynamic doors, NLOS, streaming,
Lab integration or performance. No replacement backend was registered.

Evidence, PCM, shared measurement code, crash backtrace and a fresh-baseline
reproduction runner are preserved in `local/r10/08_2_timing_recheck/`. These are
CPU/Embree acoustic tests using Isaac's Python runtime, not an Isaac simulation
or GPU throughput gate. Original R9 and initial 08.2 artifacts remain unchanged.
The decision remains **NO-GO for the attempted Steam reflection mapping** and
**GO only for bounded replacement-provider qualification**. Full 08.2 stays open.

#### Intermediate coherent propagation milestone (2026-09-10)

**PASS for the agreed intermediate milestone; final 08.2 remains open.** The user explicitly authorizes
an intermediate direct/transmission/specular milestone, with no reduction of
final requirements. This supersedes the earlier sequencing restriction that
required a diffuse provider before any further integration. The architectural
split and bounded native corrections are owned by
[[implementation_phases/r9-geometry-acoustics-provider-selection#Intermediate specular architecture (2026-09-10)|R9]].

`geometry_acoustics` now implements the common `propagate(scene, array_id,
time_window) -> MicrophoneSignalBlock` interface. It takes an explicit prepared
`AcousticSceneSession` and `GeometryAcousticsConfig`; native libraries are not
downloaded or loaded by ordinary package imports. Geometry alone owns occlusion
and rejects precomputed `SourceOcclusion`. Its PCM contains Steam direct and
qualified planar transmission plus native PRA specular reflections. No Steam
reflection or PRA diffuse reconstruction is used, and no source metadata enters
perception. Analytic remains registered and available.

Native rendering uses persistent point receivers and scene state. Steam's
frequency-dependent direct EQ exhibits an unstable Nyquist component at 16 kHz;
the adapter renders its filters internally at at least 48 kHz and uses standard
polyphase resampling with discrete impulse-area preservation. Flat transmission
uses Steam's frequency-independent mode. Source/microphone gain and signed
per-path directivity are each applied once. PRA's fixed fractional-filter delay
is removed once, while physical path delays are retained. Frequency-dependent
specular materials use native minimum-phase filter synthesis; this is a defined
filter approximation, not measured material phase.

Receiver-clock convolution retains bounded source history and does not render
future emission blocks. Response changes crossfade over 32 samples by default;
fragmenting reads does not restart the transition. Channel-response filtering is
folded into the complete responses, avoiding per-read FIR state loss. Each array
has its own cursor and reset notice. Gaps/reconfiguration discard old context,
backward time requires reset, provider replacement resets streams, and close
releases receivers and native specular state. Caller-owned scene sessions are
not closed by the producer. Diagnostics are disabled by default and use existing
signal diagnostics only; no frame, dataset or policy-tensor fields are added.

The initial native controls pass direct amplitude/phase including sub-metre
ranges, continuous-versus-fragmented PCM, source and channel-response semantics,
reset/provider replacement, planar transmission, reflected arrival timing,
both face orientations, coplanar tessellation boundaries, closed/open/closed
doors, and reflected L-corridor NLOS. The motion control checks a 0.1 m/s source
at 60 Hz against retarded emission phase. Response updates remain quasi-static:
this milestone does not establish general fast-motion/Doppler accuracy or exact
in-flight interaction timing for moving obstacles. Finite fractional filters
retain their ordinary bandlimited pre-ringing; arrival qualification uses the
same peak/TDOA convention as the native R9 controls.

**Acceptance.** The final `make check` passes 651 unit/contract, 336 integration
and 58 release tests. The supported Isaac suite passes 179 tests on RTX 4090;
20 focused native/stream controls also pass after the response-padding fix.
The previous door failure is rechecked through the production adapter at five
source offsets (0, 0.1, 1, 10 and 100 mm), each with closed/open/closed/opaque states.
Actual Isaac Sim exercises Geometry PCM through the scalar sensor, activity,
source-stop tails and reset. Actual Isaac Lab exercises both microphone layouts,
received-only CUDA perception, deferred reads, masks/padding and partial reset.
The existing Kit smoke passes; Geometry operating controls remain excluded until
08.3. Static TOML/Kit configuration rejects this provider explicitly because it
requires the prepared-session Python API. Public import remains independent of
USD, PRA and native-library availability.

The final matrix contains 1,440 environment/observation comparisons on identical
received PCM: **100% count agreement, zero missing/extra events versus scalar**.
The worst per-case direction p95 is **0.0612 degrees**; the global maximum is
**2.4187 degrees**. All cases pass the 97% / 5-degree criteria. These are reference
preservation results, not a claim of generally correct source counting. The four
R9-derived reflector controls through the production bridge pass at 16/48 kHz,
including a rotated array and opposite source side; maximum TDOA error is
0.12191 samples. Historical failed Steam/PRA diffuse evidence remains unchanged.

**Unprofiled performance.** i9-14900KF / RTX 4090, two independent source files,
16 kHz, 60 Hz acquisition, 10 Hz observations, 750 ms context. Each case warms up
for one simulated second, then measures 40 updates; 20 further observation steps
compare scalar/CUDA without entering those timings. Every environment has an
isolated native scene extracted from its own roots in the actual Isaac stage.
Indoor cases use six planar surfaces, absorption 0.4, zero scattering and native
specular order three. Timing includes acquisition, transfers and perception;
robot physics, rendering and policy learning are excluded, matching the 07.2
measurement boundary. No memory/time failure stopped these runs: 32–256 copies
are explicitly deferred to final R10 scaling, not declared infeasible.

| Environments / microphones | Free-field mean / p95 | Indoor mean / p95 | Free / indoor simulated-real ratio |
| --- | --- | --- | --- |
| 2 / 4 | 41.11 / 42.72 ms | 42.25 / 43.53 ms | 2.432 / 2.367 |
| 2 / 5 | 43.40 / 44.31 ms | 43.88 / 44.87 ms | 2.304 / 2.279 |
| 16 / 4 | 120.87 / 123.68 ms | 128.52 / 131.16 ms | 0.827 / 0.778 |
| 16 / 5 | 148.57 / 151.55 ms | 159.26 / 164.79 ms | 0.673 / 0.628 |

Two environments exceed real time in these audio-only runs; 16 do not. Aggregate
throughput is **4.56–4.86 environment-seconds/s for two copies and
10.05–13.24 for 16**, or 45.6–48.6 and 100.5–132.4 environment updates/s.
Process CPU usage is about 112% of one core. Peak process RSS is 4.22–4.41 GiB,
including Isaac and the smoke's other retained fixtures. CUDA peak allocated /
reserved memory is 72/102 MiB (2×4), 175/190 MiB (2×5), 451/620 MiB (16×4),
and 656/852 MiB (16×5). One-second warm-up costs 340–353 ms at two copies and
1.02–1.31 s at 16. Single-environment reset costs 0.49–0.85 ms. JSON artifacts
retain each update, p95, CPU, memory, warm-up, reset and parity measurement.

**Measured optimization and decision.** The separate profile identified unnecessary
long zero tails for Steam's frequency-independent direct gain. Native rendering
now returns its one-tap impulse in that case, preserving the provider gain exactly.
The 16-copy free-field means improve from 141.12 to 120.87 ms (planar) and 173.33
to 148.57 ms (raised); indoor means improve from 139.99 to 128.52 ms and 169.78
to 159.26 ms. A separate repeated raised indoor run measures 160.30 ms, consistent
with the final run and below the earlier mean by more than observed variability.
All affected physical and same-PCM controls were repeated.

The final separate GPU profile attributes about 76.65 ms CPU to native PCM calls,
27.69 ms CUDA to WPE, 37.21 ms to sparse localization and 1.55 ms to transfer/ingest
for a 16-copy raised indoor update; nested profiler times are not additive wall
budgets. A separate 20-update moving-plane CPU profile separates USD refresh
(0.844 ms inclusive of 0.129 ms scene synchronization/commit), direct simulation
(0.010 ms per receiver), specular preparation (0.125 ms), native ISM (about
0.033 ms excluding preparation), specular rendering (about 0.476 ms excluding
path preparation/simulation), direct filter rendering (0.0225 ms per receiver),
remaining response delay/mix work (about 0.37 ms) and convolution (0.153 ms).
Those component numbers cover one source/four receivers, not the indoor batch.

The equivalent Analytic free-field CUDA producer measures 41.82/43.27 ms at 2×4,
41.53/42.19 ms at 2×5, 62.15/63.08 ms at 16×4 and 86.71/87.73 ms at 16×5
(mean/p95). **Retain Analytic and the CPU/Embree + PRA intermediate provider.**
The latter adds qualified geometric behavior but does not replace the more
scalable free-field producer. No acoustic GPU prototype is admitted. Future
acceleration should target measured batched PCM/scene-update costs and prove
end-to-end correctness, gain and Isaac interference bounds; Radeon Rays is not
an available Linux acceleration path. Full diffuse/NLOS/pathing and final scaling
qualification still precede any Analytic retirement decision.

**Optional native build.** Install the existing `room` extra and pin
`pyroomacoustics==0.10.1`,
provide Eigen and nanoflann headers, then build the separate library:

```bash
.venv/bin/python tools/native/build_specular.py \
  --source .venv/lib/python3.12/site-packages/pyroomacoustics/libroom_src \
  --eigen /usr/include/eigen3 --nanoflann /path/to/nanoflann/include \
  --output build/native/libias_specular.so
```

The recipe copies source into a temporary build directory and applies only its
explicit native fixes. It fails if source anchors do not match; it never edits
installed packages or the qualified Steam build. Configure `library_path` for
the qualified Steam library and `specular_library_path` for this library.
`reflection_order` defaults to three, `max_delay_s` to one second and
`max_image_candidates` to one million. Configured microphone-response delays
share the explicit `max_delay_s` bound and receive sufficient convolution history.
Excessive native image expansion fails
with an explicit acoustic-proxy/order requirement rather than hanging or
silently truncating paths. Air absorption is explicitly unavailable in this
intermediate hybrid configuration. Arbitrary USD detail is not a throughput
promise; use the existing explicit acoustic representation when needed.

The preserved intermediate evidence index and replay commands are
`local/r10/08_2_intermediate/README.md`; `summary.json`, `*_final.json`,
`native_timing.json`, `native_profile_final.json`, PCM archives and logs contain
the final measurements. Previous R9,
reflection failures and coverage artifacts remain intact. Neither diffuse-field
coverage, complete pathing, general dynamic scenes, 32–256 scaling, GPU acoustic
acceleration, Analytic retirement nor GUI 08.3 is claimed by this milestone.

#### Dynamic NLOS and minimum PRA extension follow-up (2026-09-11)

The user authorizes completing dynamic NLOS and testing the smallest general PRA
change before committing to a larger reflection redesign. The follow-up produces
working experimental transport changes and two concrete negative admission
controls. **Neither complete NLOS nor complete diffuse propagation is admitted.**
The installed intermediate provider, Analytic, schemas and full R10 scope remain
unchanged. Evidence and executable replay: `local/r10/08_2_dynamics/README.md`.

**Selected-flight transport corrected.** The separate Steam build now exports
`ias_visibility_abi` / `ias_scene_segments`, using native scene traversal against
caller-retained immutable snapshots. `tools/native/retarded_pathing.py` solves
emission time through the fixed native probe backbone with source position at
emission and microphone position at reception. Each segment is tested only in
the geometry epochs traversed during its flight. Emission history and native EQ
tails persist independently of PCM read partitioning; reset clears them. Scene
history provides explicit pruning/release and independent environment ownership.
Native interval starts use a 10-micrometre numerical tolerance because Embree
excludes a hit exactly at the ray origin; the end belongs to the next epoch.

The native corridor regression now blocks the packet when closure occurs at
5 ms, preserves it when closure occurs at 12 ms, and preserves it through a
closure/reopening at 4/6 ms, before crossing. Four endpoint-motion cases
(0.1/0.5 m/s source, 0.5 m/s receiver and simultaneous motion) satisfy the
retarded equation to 1.8e-12 samples. Irregular PCM partitions differ by at most
1.4e-9. These controls use actual native filters and immutable native scenes,
not a visualization callback or custom intersection engine.

**Complete route discovery still fails.** A two-gate control crosses the gates
at 6.958 and 9.874 ms. The first closes at 7.459 ms; the second opens at
9.374 ms. The polyline is valid during the flight even though every actual scene
snapshot contains a closed gate. Native selected-route capture returns zero
routes for all four microphones in every snapshot. An all-open native route,
used only as a diagnostic candidate, passes the independent timed native
visibility check and yields peak pressure 0.001626; selected-only rendering
produces zero. Keeping the union of selected snapshots cannot recover a route
that none contains. An all-open scene is not a production workaround. This is a
discrete-update causal boundary control; its occurrence rate and observation
impact in ordinary robot-door trajectories have not been measured.

Closing this gate requires a further native graph-candidate/time-dependent search
interface, including endpoint connections, interpolation ownership and rebake
coverage. The current private selected-route ABI is insufficient. Geometry is
held between epochs; continuous obstacle-pose interpolation and moving bend
interaction laws remain open. Sample reconstruction is linear, and settled
native EQ is applied on the receiver clock. No complete Geometry integration or
new Sim/Lab/Kit dynamic admission is claimed from this experimental helper.

**Small PRA anchoring prototype and its limit.** A separate native wrapper fixes
first-scatter samples to material-surface quadrature. It reuses PRA ISM for the
incident path and PRA ISM/ray tracing for outgoing paths. Surface area and
Lambertian incidence/departure cosines supply energy normalization; there is no
fitted gain. The single-plane control passes 12 native/independent-reference
comparisons, with maximum complex coherence error 8.21e-6 and energy agreement
within 1e-5 relative. This establishes a bounded useful construction, not a
qualified general room field. Fixed finite ISM prefix order also leaves higher
specular prefixes before first scattering outside this prototype.

An anchored first scatter is then held fixed while native rays encounter a
moving specular mirror and a stationary diffuse floor. A 1 cm mirror movement
moves second-scatter phase locations by 2 cm on that stationary floor. Complex
temporal coherence errors against the independent fixed-floor image-source
reference remain approximately 0.151, 0.300 and 1.031 at 500, 1000 and 4000 Hz
across 4096, 16384 and 65536 launch rays. This is a controlled ensemble-phase
comparison; it does not impose isotropic covariance on arbitrary rooms. The
first-anchor change moves the persistence defect to later interactions rather
than resolving the complete moving-geometry domain.

**Decision boundary.** This candidate cannot be generalized merely by caching
responses, stabilizing random seeds or anchoring the first hit. Later scattering
needs persistent material state, changing illumination, correctly weighted
multibounce transport and visibility/timing. Native traversal remains reusable,
but it does not supply that pressure-state evolution. This is concrete evidence
against promoting the minimal candidate, not proof that all PRA extensions are
impossible. A larger owned transport model versus evaluation of a maintained
replacement for the whole reflection subsystem is now the architecture decision.
No such replacement evaluation or proprietary multibounce implementation began.
The remaining Steam search extension is a separate requirement and is not
claimed to be solved by replacing PRA. Closed-loop navigation and full R10
admission remain open; final scaling remains deferred.

Validation of this follow-up: eight focused unit/native tests pass, including
actual Embree interval boundaries. `make check` passes 657 unit/contract,
336 integration and 58 release tests (1051 total). Actual Isaac Sim 6.0.1 on
RTX 4090 preserves the original intermediate Geometry and Analytic smoke,
including received PCM, scalar perception, source-stop and reset. These are
preservation checks, not admission of the experimental dynamic renderer or new
CUDA accuracy evidence. Native acoustic execution remains on its supported CPU
path. Wiki links/index and whitespace checks pass.

#### Targeted NLOS and observation-sensitivity follow-up (2026-09-11)

The user authorizes a bounded usefulness investigation before choosing a larger
PRA redesign or evaluating another provider. Full R10 scope remains unchanged.
This follow-up does not enable an unqualified production contribution.

**Experimental NLOS renderer.** `tools/native/pathing.py` consumes the existing
selected-route ABI, copies callback data before it expires, checks the ABI and
route lengths, and renders each contribution through its own settled native EQ
and physical delay. Interpolation weight, distance attenuation and optional
caller-supplied directional gain are applied once. No visualization callback or
combined-signal distance shift supplies production paths. This helper is outside
the installed package; probe creation, coverage and geometry lifecycle remain
caller-owned experimental responsibilities.

Its emission-clock overlap-add helper preserves already scheduled responses when
new emission uses a changed route, and passes block partitioning, source-stop
and reset/isolation controls. **This is not complete dynamic propagation:** a
blocker moved at 5 ms could intercept the old corridor route at 8.416 ms, before its
16.713 ms arrival. Keeping every old contribution would incorrectly retain that
arrival. The helper documents this unsupported interception explicitly and is
not connected to the production `GeometryAcoustics` configuration. The later dynamic follow-up above corrects selected-flight interception; complete
route discovery and continuous scene integration remain admission work.

Separate native filter controls pass one-sample route timing at 5.706 and 9.494 m,
pressure gain within 0.1% (finite interpolation/resampling ripple), exact gain
linearity and filter-state independence. Existing native fixtures retain
LOS exclusion, two distinct screen routes per microphone, obstacle removal and
restoration. These improve the reusable native experiment, not the full acoustic
coverage claim. Evidence: `local/r10/08_2_usefulness/README.md`.

**Observed NLOS value.** Twelve paired source realizations in the initial/restored
corridor give mean final-segment arrival-direction error **0.03685 degrees** with
selected-route delays versus **57.99938 degrees** in a delay-only ablation. That
ablation preserves route EQ, gain and weight but substitutes Euclidean delay;
it isolates the archived failure mechanism, not every difference from the old
aggregate renderer. Hidden-source bearing is scored separately and never used
as an NLOS target. At 16 kHz, corrected peaks are 266–273 samples initially and
436–443 after the blocker moves; the incorrect delay stays at 183–190 samples.
The moved-blocker PCM is -61.85 dBFS and yields no observation at the unchanged
-60 dBFS activity threshold. Correct propagation does not guarantee audibility.

**Diffuse observation experiment.** Actual native PRA ray-event pressure is
compared with a fixed Lambertian surface-element reference on one finite plane.
Both start from the same native quadrature and stochastic realization. The
reference updates incident illumination by the cosine/inverse-square law and
incoming delay while retaining scattering positions on the surface. No fitted
gain or post-render covariance correction is used. This reference isolates the
phase-model defect; it is not a general room solver or production replacement.

Four microphones form an 8 cm square. The source moves normally to the plane at
0, 0.1 or 0.5 m/s. Conditions include unit direct gain, direct gain 0.1 and an
independent competing source. Direct attenuation is a sensitivity axis, not an
occluding-door model. There are 24 paired phase/signal realizations per condition:
432 streams at 4096 rays/20 ms updates, 192 refinement streams at 16384 rays, and
192 at 5 ms updates. All **72 stationary PCM pairs are exactly identical**.
Signals stop at 2.1 s; complete streams last 2.4 s. Direction scoring uses
0.8–2.1 s, excluding mandatory 750 ms perception warmup and source-stop tails.

Production `TorchPerception` runs on RTX 4090 and receives only PCM and microphone
positions. Truth enters scoring afterward. A miss is no assigned direction within
20 degrees, including wrong directions; it is not necessarily a missing output.
Extra directions, no-DOA rate, assignment error, first-match latency/censoring and
per-frame outputs are retained. Confidence intervals bootstrap paired trial means,
not correlated frames; they are descriptive, without a multiple-comparison claim.

| Single-source condition | Reference misses | Moving-ray misses | Paired excess percentage points (95% CI) |
| --- | ---: | ---: | ---: |
| Strong direct, 0.5 m/s, 4096 rays | 0% | 0% | 0 |
| Weak direct, 0.1 m/s, 16384 rays | 13.39% | 13.10% | -0.30 [-12.80, 11.01] |
| Weak direct, 0.5 m/s, 4096 rays | 33.93% | 77.08% | 43.15 [31.85, 54.47] |
| Weak direct, 0.5 m/s, 16384 rays | 35.71% | 69.94% | 34.23 [26.48, 42.56] |
| Weak direct, 0.5 m/s, 5 ms updates | 34.23% | 74.11% | 39.88 [27.38, 52.38] |

Strong-direct mean DRR is about +10 to +12 dB; paired angular differences stay
below 0.14 degrees. Weak-direct DRR is about -8.5 to -10.4 dB. At 0.5 m/s and
16384 rays, the defective model increases assignment angular error by 8.97 degrees
[5.06, 13.39]. It never recovers the single target during the scored/source-active
trial in 3/24 realizations, versus 0/24 for the reference. Conditional first-match
latency difference has a CI crossing zero; no general latency benefit is claimed.

The competing-source result is mixed: at 0.1 m/s/16384 rays, the defective model
*reduces* misses by 12.95 percentage points [5.35, 21.43]; at 0.5 m/s both variants
miss 50% of target directions. Both fields produce extra estimates in difficult
cases. These results establish material, scenario-dependent observation bias,
not universally worse scores, complete moving-source perception or navigation
success. The physically better reference need not make a task easier.

**Validation and decision.** The 816 diffuse plus 72 NLOS PCM streams use actual
CUDA inference. Forty selected streams (960 frames) also pass scalar comparisons:
100% count/activity agreement, maximum direction difference 3.798 degrees, within
the existing 5-degree control. Native acoustic engines stay on their supported CPU
path. Actual Isaac Sim 6 on RTX 4090 passes the maintained intermediate Geometry
smoke (native PCM, scalar observations, source-stop/reset). This is preservation
of the existing producer, not live USD admission of the experimental path branch.
`make check` passes **653 unit/contract + 336 integration + 58 release** tests;
the separate optional native filter control passes.

The evidence justifies targeted NLOS integration and persistent diffuse-field
work for weak-direct moving-source scenarios. It does not justify assuming that
a third provider is necessary or already suitable. A broader PRA redesign versus
replacement evaluation is still a separate architectural decision. Full R10,
continuous dynamic visibility, general-room admission and closed-loop navigation
remain open. No new provider, physical recording, policy training or final scaling
qualification was introduced. Detailed controls, raw observations, figure and
replay instructions are in `local/r10/08_2_usefulness/README.md`.

#### Milestone 2 native extensions — dynamic-field blocker (2026-09-11)

**Milestone 2 is not achieved; final scope is unchanged.** The authorized
existing-provider extensions were implemented and executed in isolation. No new
provider evaluation began. The intermediate production provider, installed PRA,
qualified Steam SDK/binary, and historical evidence remain unchanged. Complete
integration, continuous dynamic-path rendering, localization/multisource usefulness,
and closed-loop audio navigation remain unqualified. Final performance/scaling is
still deferred.

**Steam selected routes.** The experimental native extension retains selected
routes before SH/EQ aggregation, reconstructs their probe chains, validates source,
internal and receiver segments with Steam queries, and removes redundant visible
segments. Its private callback reports the complete polyline, probe identities,
length, interpolation weight and native per-route deviation EQ; LOS is excluded.
The native validation branch now invalidates a rejected baked route even when
alternate search is disabled. The original library is not overwritten.

The tracked `tools/native/build_pathing.py`, `steam_paths.patch` and
`steam_paths.h` build/document this optional interface using the existing Linux
CMake CPU/Embree build. Only the changed implementation is recompiled; C++ class
layouts and the original objects remain unchanged. Callback storage is temporary,
thread-local and synchronous. Empty output does not distinguish missing probes
from no route; probe IDs are invalidated by rebaking. Native probe deviation EQ
remains an approximation, not exact endpoint-dependent edge diffraction.

Native controls cover the archived corridor, moved blocker, full closure and
restoration, source/receiver displacements, LOS exclusion and a two-route screen.
The screen yields two routes per microphone, with weights summing to one. Native
EQ impulses rendered with separate route delays pass all **44** timing cases:
maximum error **0.6252 samples** relative to each native filter's own peak plus
physical route delay. Full polylines also satisfy independent geometric detour
lower bounds. This fixes the demonstrated information-loss/timing mechanism in
an executable native slice; it does not complete Geometry streaming, rebaking,
directivity, hybrid ownership, or duplicate-route interpolation qualification.

**PRA shared pressure.** The first extension preserves ray/scattering hits before
histogram reduction and reconstructs shared signed pressure using PRA's fractional
delay kernel. It repairs co-location but retains overlapping native ray-hit and
scattering accumulation. The next native iteration uses shared scattering events
with native ISM suffixes, separates pure specular ownership, and replaces averaged
specular/diffuse directions with probabilistic branches and corresponding energy
weights. Per-ray RNG prevents one changed ray from reseeding all following rays;
the final two-sided implementation reuses the maintained polygon fixes and corrects
the outgoing hemisphere. These are model-development prototypes, not enabled
production capabilities; the wrapper qualifies scalar-band controls only.

Controlled synthesis passes 20-realization isotropic and directional checks with
maximum complex-coherence errors **0.04332** and **0.00146**, below 0.1. These
inputs isolate the renderer and are not room simulations. Native box/general-room
controls cover scattering 0/0.3/1 and specular suffix orders 0/1/3/5. Co-location
and unchanged refresh are exact. Final two-sided room/door controls give nonzero
open-door pressure and exact silence for closed/open/closed partition closure.
Finite suffix order and statistical energy convergence remain approximations;
passing these controls does not qualify full banded/dynamic coverage.

**Decisive failure.** The signed realization is attached to ray identities whose
hit locations move when the source moves. Consequently the model moves the random
scattering field on an otherwise stationary wall. A single-plane control compares
actual native transfer events with a fixed Lambertian surface-element field:
source `(2,0,1) m`, receiver `(3,0.1,1) m`, 1 cm source displacement normal to the
plane. Complex-coherence error is about **0.117 at 500 Hz, 0.227 at 1 kHz and
0.687 at 4 kHz**. The 4 kHz error stays **0.68723–0.68729** from 4096 through
65536 rays, well outside the 0.1 tolerance. Per-ray RNG and increased sampling do
not repair it. This is a spatial/temporal phase-model failure, not a throughput
failure or a physical-recording requirement.

The independent reference holds physical surface positions fixed, updates source
illumination and incoming travel time, and retains outgoing paths. Native samples
supply the surface quadrature; no fitted correction is applied. This bounded
reference is not a replacement production solver and makes no claim of general
rough-surface wave accuracy. It exposes inconsistency in the attempted shared
point-scattering model under source motion; stationary microphone-field success
cannot establish dynamic robot-audition usefulness.

**Stop and next decision.** The attempted native joint model is not admitted.
A general repair needs persistent material/surface scattering state and timed
source illumination, multibounce transport, receiver evaluation and dynamic
visibility. Freezing only this plane, shifting a tail or fitting a gain would not
meet R10. Further native transport redesign versus evaluating a maintained
provider with such a representation is now an architectural decision for the user.
No alternative is selected or evaluated by this run. The experimental Steam
interface is retained; unsuccessful PRA model patches stay with local evidence,
not the installed package or an enabled fallback.

Evidence and exact replay instructions: `local/r10/08_2_extensions/README.md`.
Five decisive JSON result pairs and **52 PCM/spectral arrays** match exactly
between ordinary Python and the supported Isaac interpreter. These runs use
CPU-native Steam/PRA, without SimulationApp or CUDA perception. They do not
replace the blocked downstream Sim/Lab/navigation gates.
`make check` passes 651 unit/contract, 336 integration and 58 release tests. Fresh
archived-provider replays also reproduce both original admission failures; this
extension work does not modify or supersede their historical artifacts.

#### Milestone 2 complete acoustic coverage — blocked (2026-09-10)

**The milestone is not achieved. Final R10 scope is unchanged.** The user prioritizes
coherent diffuse pressure, complete indirect/pathing, functional NLOS and dynamic
scenes before final performance qualification. No 32–256 scaling or new performance
claim is made. Production remains the admitted intermediate Steam/PRA specular
provider; no failing diffuse/pathing contribution is enabled.

The new admission work runs actual PRA 0.10.1 and the unchanged qualified Steam
4.8.1/Embree binary. The retired R9.4 harness is restored from `c59f830` into the
new ignored evidence directory only. It is an independent audit of that historical
claim, not the current production binding and not a restored maintained tool.
Both ordinary Python and the supported Isaac Python reproduce all 47 saved PCM /
spectral archives within 1e-12 absolute/relative tolerance. These are CPU-native
acoustic checks, not SimulationApp, CUDA perception or live GPU smoke qualification.
No new integration exists to submit to those downstream gates.

**Diffuse pressure.** Five native closed-room RT runs use 8192 rays, a 150 ms
horizon, 4 ms energy bins, absorption 0.2 and scattering 0.3. Co-located identical
microphones have exactly identical energy histograms, but relative PCM error is
1.380–1.489 and correlation is -0.058–0.028. Reconstructing the unchanged response
again changes its pressure with relative error 1.365–1.486. The previously measured
co-location failure therefore remains reproducible, and response caching alone
would not repair its spatial model.

The attempted minimal correction resets the native Python renderer to the same
random seed for each receiver. It repairs identical receiver output, but fails
separated receivers. To isolate synthesis from room anisotropy, a separate control
supplies the same ideal homogeneous isotropic energy histogram to native
`compute_rt_rir`; this is explicitly not a geometric room simulation. Across 20
realizations, independent seeds yield complex coherence about -0.0065+0.0140i at
1 kHz. Shared seeds yield 1.0 at every spacing. The isotropic reference is
`sinc(2*f*d/c)` using NumPy's normalized sinc: at 80 mm / 1 kHz it is 0.6786,
and at 200 mm it is -0.1361. Both strategies fail a deliberately broad 0.1 complex
coherence tolerance in the required separated controls. A directional limiting
case also requires 3.7318 samples of delay over 80 mm at 16 kHz even when both
arrivals occupy the same 64-sample energy bin; identical histogram inputs and
shared RNG cannot supply that difference. This last case is an information-loss
control, not an executed geometry/timing pass.

The covariance reference is the homogeneous isotropic field only; it is not imposed
on arbitrary rooms or directional early reflections. See the
[diffuse-field derivation](https://pub.dega-akustik.de/DAGA_1999-2008/data/articles/000952.pdf).
Native PRA reduces ray hits to energy histograms and reconstructs pressure
stochastically per receiver. Native Steam's reflection reconstructor similarly
uses 10 ms energy bins and noise-weighted synthesis. Sharing seeds, shifting the
whole tail, adding ray count, or fitting gains does not restore common path events,
individual arrival times and position-dependent phase. A new joint pressure
renderer would be model development, not a parameter or ABI correction.

**Pathing arrival requalification.** The retired R9.4 bridge at
`steam_audio_r9_4.py:538` schedules its complete native path output using the
straight source–microphone distance. Its explicit arrival check used the open
connected-room fixture, where this happened to be a valid distance. The reported
small NLOS TDOA errors also used the straight-distance reference. They did not
qualify travel time around the partition. That stronger interpretation is now
withdrawn; archived reports and PCM remain unchanged.

The new check reuses the original full-height corridor partition ending at
`y=0.5 m`, source `(2,-1,1.2) m`, and the original four receivers around
`(-2,-1,1.2) m`. The analytic shortest detour around the partition edge provides
an independent arrival lower bound for this fixture; it is not a production path
solver. Five repetitions produce native-plus-archived-bridge peaks 133.11–146.54
samples too early at 48 kHz, with maximum all-pair TDOA error 13.43 samples.
Moving the original blocker extends the edge to `y=1.5 m`: alternate-path search
changes level but arrivals remain 327.38–344.86 samples too early, with maximum
all-pair TDOA error 17.48 samples. These are substantial failures against the
one-sample timing criterion, not sub-sample interpolation differences.

Two controls delimit this finding. The open connected-room native path output
is nonzero (peak about 0.09390), so it cannot be blindly added to an already owned
LOS/direct branch. A widened dynamic blocker closes the entire opening: validation
alone retains nonzero output in this harness, whereas validation **and** alternate
search yield exact silence in all five repetitions. Native routing therefore
retains useful functionality; it is not rejected as universally nonfunctional.
Its combined path signal and archived delay mapping are not physically qualified.

Source inspection confirms that `PathSimulator::findPaths` constructs routes,
then aggregates their weights, SH directions and EQ before `IPLPathEffect`
applies one filter to one dry signal. The public `IPLPathEffectParams` contains no
per-route length, delay, weight or stable identity. The visualization callback
exposes validation segments, including rejected candidates, not the selected
weighted temporal transfer functions. Choosing a shortest route from those
segments or delaying their mixture once cannot preserve multiple path arrivals.
The required next native interface must expose selected contributions before
aggregation, or render their correctly timed combined pressure itself. LOS
ownership, source/microphone directionality, invalidation and overlap with
specular/diffuse paths must then be qualified together. No extra attenuation or
arrival compensation is admitted to conceal this missing information.

**Alternatives and decision.** R9 owns the additional TASCAR component rejection
and the PFFDTD/DynamicSound admission boundaries. None of the examined native
interfaces supplies a qualified replacement for this complete domain. This is a
block on completion with the admitted implementations, not proof that acoustic
simulation is impossible or that every external engine fails.

The next step is dedicated provider work: a maintained upstream/native extension
or replacement that retains a shared spatial pressure representation and selected
path events before aggregation. The R10 boundary still assigns scattering, ray
traversal and path search to the external engine. Implementing an IAS statistical
reflection/path solver would cross that architectural boundary; reducing the
acceptance domain would violate the user's unchanged final scope. The existing
bounded PRA specular fixes do not qualify such a new acoustic model.

Before any integration resumes, that provider must pass co-location, separated
isotropic and directional controls, path-specific arrival/gain, multi-route
non-duplication, closed/open/closed visibility and dynamic continuity. Then
repeat continuous/block equivalence, tails, reset, independent environments and
the common PCM scalar/CUDA integration. Final performance/scaling follows only
after this coverage milestone passes. No native fork or new model is silently
promoted as a solution by this investigation.

Evidence and replay instructions: `local/r10/08_2_complete_coverage/README.md`.
`diffuse_gate.json`, `pathing_gate.json`, `path_visibility.json`, the matching
`isaac/` results, `tascar_component.json` and `summary.json` retain outcomes and
limits. The admitted intermediate evidence, SDK and `knowledge/raw/` are preserved.

#### Provider coverage and hybrid admission gate (2026-09-10)

The follow-up implements an **executable local qualification adapter**, not a
registered backend: prepared USD → Steam direct/planar transmission plus native
Pyroomacoustics ISM reflections → combined microphone impulse responses.
It reuses the archived native receiver in an isolated checkout, disables Steam
reflections, selects positive native PRA image orders, applies continuous delay
once to direct PCM, and removes PRA's documented fixed 40-sample filter latency.
Both branches use the existing source amplitude convention, once. There is no
output fitting, local reflection search, `SourceOcclusion` input or perception
change. **The candidate fails admission and remains local.**

The audit uses installed PRA 0.10.1 and actual USD preparation in Isaac's Python
runtime. CPU is appropriate for these native acoustic engines; SimulationApp,
CUDA perception and Isaac physics/rendering are not running in these probes.

| Executed control | Result and boundary |
| --- | --- |
| Prepared box, partition/door, and L-shaped corridor | Native ISM can consume the prepared vertices. High-level `Room` enclosure tests reject receivers around internal planar partitions; empty visibility can raise an error. Its no-visible-source int32 fallback is also interpreted as image indices during RIR rendering. Explicit native obstruction lists and boolean masks fix these wrapper issues, not all geometry cases. |
| Native original-face ISM | Reassembling original USD polygon boundaries avoids triangle-only duplication but does not eliminate invalid closed-partition paths. A separate asymmetric configuration gives zero closed-door/direct-NLOS PCM and nonzero open-door/corridor reflections. This is bounded static recomputation, not general door or diffraction qualification. |
| Hybrid closed/open/closed and opaque door | Five source offsets, four microphones, 16 kHz, 20 states. Steam direct loss is 12.0000 dB and native occlusion changes correctly. In all 15 closed states, PRA specular peak remains about 0.0209–0.0227 despite a continuous partition. Raising door loss to 120 dB reduces direct peak below 3.83e-8 but leaves those reflections. The opaque specular subproblem has no valid route across the partition. Hybrid summation does not repair this failure. |
| PRA ray-traced scattered field | Five seeds, two identical co-located omni receivers, 8192 rays, 150 ms horizon and 4 ms energy bins. Histograms are identical, but PCM relative L2 error is 1.38–1.49 and correlation -0.058–0.028, failing the 1e-5 co-location tolerance. Independent stochastic RIR reconstruction does not provide a shared physical pressure field. |
| RAC native delay component | Compile unchanged 3DTI `Waveguide`/`Vector3` used by RoomAcoustiCpp's source/image-source DSP. At 16 kHz, moving the receiver 5 mm per 128-sample block takes distance from 2 to 2.5 m: expected arrival grows from 93.29 to 116.62 samples, measured delay remains 93. Static delay is integer-rounded. This rejects that temporal component as-is; the full RAC scene runtime was not compiled or qualified. |

The door fixture is a 6 × 6 × 3 m room with a full-height x=3 partition and a
1 m door opening. The source is (2, 3+offset, 1.2) m; the four-microphone array is
centered at (4, 3, 1.2) m with 80 mm arms. Offsets are 0, 0.1, 1, 10 and 100 mm.
The open door translates 6 m along y; broadband absorption is 0.2 and scattering
is zero. Native triangle, two-sided and original-face mappings were explored;
the final hybrid uses original faces and explicit obstruction checks. Failure
of this allowed planar USD input does not imply every PRA enclosure is invalid.
Changing pose symmetry or inventing wall thickness is not a supported repair.

The RT control uses a closed generic room with absorption 0.2, scattering 0.3,
and 0.1 m receiver radius. Co-location removes geometric uncertainty: identical
noise-free receivers must sample the same pressure. Seeding each receiver alike
would not establish spatial coherence for displaced microphones. Neither PRA RT
nor the previously rejected Steam reflection reconstruction is admitted as the
hybrid's diffuse field.

**Component performance only.** The i9-14900KF run uses two source positions,
4/5 microphones, 16 kHz, a generic six-face room, and 2/16 isolated prepared
copies. Each case warms up for five full-batch RIR refreshes and measures 20
without profiling. Engine construction and native ISM/RIR generation are included;
initial USD preparation is separate. `refresh_benchmark.json` records mean/p95,
process CPU time and peak RSS. The fresh replay gives these full-batch wall times:

| Copies / microphones | Direct-only ISM mean / p95 | Order-three indoor ISM mean / p95 |
| --- | --- | --- |
| 2 / 4 | 18.21 / 24.33 ms | 21.74 / 25.88 ms |
| 2 / 5 | 23.83 / 30.44 ms | 19.96 / 23.23 ms |
| 16 / 4 | 136.98 / 154.18 ms | 148.61 / 169.45 ms |
| 16 / 5 | 162.77 / 200.65 ms | 178.79 / 215.13 ms |

Two runs retain timing variability; for example, the first 2-copy/5-microphone
indoor mean was 27.20 ms. Small-case ordering is not evidence that higher order
is faster. These are RIR refresh costs, not received-stream
throughput: there is no convolution stream, matched 60 Hz acquisition/10 Hz
observation workload, CUDA transfer/perception, partial reset or Isaac stepping.
Order-zero and indoor order-three controls are kept separate. Scaling stops at
16 because correctness fails; no 32–256 result, memory-limit claim or GPU
optimization decision follows. Full 07.2 comparison remains outstanding.

Evidence and the reproduction runner are in `local/r10/08_2_architecture/`:
`coverage.py`, `hybrid_probe.py`, `hybrid.json`, waveform NPZs, `rt_coherence.json`,
native RAC delay/motion probes, build logs, `refresh_benchmark.json`, and derived
`evaluation.json`. A fresh isolated replay reproduces the negative acoustic
gates. GSound's isolated Python 3.12 build fails before PCM qualification; source
and dependency checks for that candidate and RAC are retained locally. No
historical evidence, qualified Steam source, `knowledge/raw/`, production package,
frame/tensor schema, or installed dependency was changed.

[[implementation_phases/r9-geometry-acoustics-provider-selection#Architecture decision after the Pyroomacoustics coverage audit|R9 owns the three-option decision]]:
hybrid direction, but no admitted definitive adapter. Native reflected visibility
and coherent diffuse pressure must be resolved before promotion. Source/mic
directivity, continuous moving-scene PCM, tails, block equivalence, partial resets,
same-PCM scalar/CUDA agreement and real Isaac Sim/Lab integration remain required;
static scene recomputation does not satisfy them. No new `make check`, Kit or GPU
qualification is claimed for this local-only candidate; documentation checks are
separate from the previously recorded production baseline gates.

#### Early complete-path and scaling decision gate (resume after blocker)

Apply the active robot-audition fidelity scope above: “complete” means the
declared task-domain coverage, not absolute dynamic-acoustic completeness.
Final scaling remains after Milestone 2 qualification.

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
- If Steam pathing is retained in the selected hybrid, use R9.4-qualified probes,
  default UTD deviation, arrival scheduling and bounded callbacks, then qualify
  its combination with the reflection renderer; the failed proxy does not enter.
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

Expose provider/scenario-bounded summaries only where an active consumer needs them and the relevant behavior is qualified: for example direct-to-indirect ratio, dominant indirect delay/level or ordinary door transitions. Do not make unsupported sequential-partition physics or a speculative distribution catalog an 08.3 blocker. Phase 09 owns selection and validation of useful randomization/transfer distributions for the retained analytic path. An online geometry provider for parallel execution still requires the declared-domain runtime gate; it is neither assumed nor categorically excluded. Label all such parameters as geometry-derived simulation data rather than measured physical calibration.

The temporary R9 adapters, runners, fixtures, report builders, validators, and tests are already removed. Implement one production Steam binding and validate provider-version upgrades directly through focused version, timing, assembly, pathing, signal, and performance tests at that boundary. Remove redundant geometry, material, or occlusion paths as the production integration settles. NVIDIA RTX Acoustic remains documentation and historical evidence only, with no executable or configurable provider surface. Do not keep provider-specific public observations or test-only runtime shortcuts.

#### Key Decisions

- `GeometryAcoustics` is the primary daily high-fidelity Isaac path.
- Retain `AnalyticAcoustics` as the current Lab baseline; apply the R10.2 evidence-based decision before retiring it or maintaining both paths long term.
- One Geometry signal producer integrates the admitted native engines behind the declared profile/capability boundary.
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
capture) and `build/validation/r10/kit/` (complete extension regression). R10.2 has the operational intermediate described above; final profile qualification
and R10.3 operating integration remain open. The failed 08.2 candidate and decisive
reflection evidence are preserved under `local/r10/08_2_gate/`.

## Files

- `src/isaac_audio_sensors/isaac/acoustic_scene/`
- `src/isaac_audio_sensors/core/acoustics/materials.py`
- `src/isaac_audio_sensors/kit/acoustic_scene.py`
- `tests/isaac/test_acoustic_scene.py`
- `tools/smoke/live_acoustic_scene.py`
