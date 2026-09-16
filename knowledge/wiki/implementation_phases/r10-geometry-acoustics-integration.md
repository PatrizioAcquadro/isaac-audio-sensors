# Phase R10 — Geometry Acoustics Integration

Status: 08.1, the 08.2 intermediate and Step 3 admission are complete. Step 3 is
PASS with documented limits; Milestone 2 and 08.3 remain open. Step 4 is next.

## Objective

Deliver Geometry Acoustics for scientifically useful robot audition. Implement
[[decisions/robot-audition-fidelity|the approved indoor domain, both profiles, physical invariants, numerical budgets and stop rule]]. AV attention/search is
first; mobile audition is complementary and still required. The scope is not
absolute dynamic acoustic completeness. Approval did not admit experimental code.

Read this plan and the decision to implement. Consult
[[topics/geometry-acoustics|the technical contract/build instructions]] as needed;
[[experiments/geometry-acoustics-admission|the admission record]] preserves decisive
positive and negative results. [[implementation_phases/08-geometry-acoustics-integration|Phase 08]]
owns the eight-step sequence; do not duplicate acceptance criteria there.

## Subphase R10.1 — USD Acoustic Scene

#### Implementation

Completed composed USD import, material-family precedence, acoustic proxies,
assembly grouping, static caching/selective updates, live PhysX poses and native
scene lifecycle. Python/Kit share authoring, mixed values, defaults and Undo/Redo.
Native exported vertices match transformed USD, including motion. Preparation
and native verification are separate from signal qualification.

#### Key Decisions

- USD remains the authoring authority; one shared material catalog and adapter.
- Explicit opaque/unsupported transmission beats invented wall behavior.
- Preserve source-band data and analytic material compatibility.

#### Problems / Limitations

Deformables, subdivision, point instancers and unsupported Gprims need explicit
polygon proxies. Automatic room reconstruction, thick/sequential transmission
and physical asset calibration remain unsupported. Detailed selection/material
semantics belong to [[topics/geometry-acoustics|Geometry Acoustics]].

Evidence: native/real-USD tests and actual RTX Kit editing, Undo/Redo and PhysX
motion pass. The 266-object fixture measured idle p95 ~0.48 ms, initial import
~302 ms and selective movement/material updates ~135/145 ms; not a general scale claim.

## Subphase R10.2 — Passive Microphone-Array Propagation

#### Implementation

The operational intermediate combines Steam direct/planar transmission and corrected
native PRA specular reflections into continuous multichannel PCM. Analytic remains
available. Common scalar/CUDA perception sees only the final mixture. Native engines
own traversal, image paths, scattering and route search; IAS owns interface mapping,
stream timing and justified pressure synthesis. No second geometry attenuation stage.

Complete the following before closing Milestone 2:

1. Instantiate the [[experiments/geometry-acoustics-trial-protocol|declared trial matrix]],
   scoring and property-specific references. **Step 1 preparation is complete under
   the clarified scope**: inputs, bounded NVIDIA acoustic proxies, essential geometry
   checks, direct/scalar reference diagnostics and RTX cost evidence are saved.
   No 08.1 SDK correction was needed; local overlay units/up-axis were corrected.
   Banded full-field decay/DRR, scattering visibility and unavailable moving-room
   references were assigned to affected Step 2/3 comparisons; current results and
   the explicitly revised full-room admission role are recorded below.
   Do not treat this preparation closeout as model admission. Use the lean family
   allocation and reuse still-valid evidence; no blanket 400 repetitions per row.

2. Integrate the selected-route Steam extension before SH/EQ aggregation. Export
   topology, full source–mic length, departure/arrival direction, weight, native
   filtering and validity through a checked private ABI. Preserve native probe
   generation/search, endpoint/internal visibility, alternate routing and explicit
   coverage/rebake handling. Render each route at its own delay; distinguish physical
   alternatives from duplicate probe representations. Exclude native LOS already
   owned by direct rendering. Preserve identity where topology survives, continuous
   arrival evolution, invalidation and causally valid in-flight sound under the
   approved bounded dynamic model. Visualization callbacks/global delay shifts are
   not production substitutes.
3. Extend PRA before histogram reduction, retaining shared scattering events,
   positions, travel length, directions, energy, interaction history and visibility.
   Construct receiver-specific pressure delays/amplitudes/directionality from a
   shared realization, stable under unchanged refresh, motion and array regrouping.
   Equivalent source configurations must yield equivalent transfer behavior;
   independent environments remain isolated. Audit absorption/scattering partition,
   deterministic ISM order and higher/mixed ray ownership without energy overlap/gaps.
   Derive normalization from native energy and synthesis filters; test ray-count
   convergence and receiver-radius behavior without fitted gains. Exact late-path
   phase is not mandatory; apply the
   [[decisions/robot-audition-fidelity#Step 3 full-room limitation and admission decision (2026-09-16)|current binding controls and accepted limitations]].
   Full-room moving equivalence is NOT VALIDATED and explicitly non-blocking;
   cube/mirror diagnostic limits remain separate. Resolve material
   measurement defects before affected comparisons, then share episodes/PCM across
   remaining motion and observation checks; reuse still-valid controls.
4. Combine admitted direct, specular, diffuse and deviation contributions on one
   persistent clock. Retain source-stop tails, block equivalence, reset/partial reset,
   scene lifecycle, directional response and explicit native capability failures.
   Keep intermediate defaults and public PCM/observation/recording/Lab schemas.
5. Compare intermediate, NLOS-only, diffuse-only and combined configurations using
   matched sources/trajectories. Demonstrate Profile 1 then Profile 2 with the
   approved reference consumers. Paths/truth are diagnostic/scoring inputs only.

#### Key Decisions

- Preserve Analytic and the working intermediate; enable extended coverage explicitly
  only after admission. One Geometry producer, no redundant experimental backends.
- Native geometry/delay checks and joint microphone physics are essential even when
  a downstream metric improves. Independent scalar/CUDA agreement is not fidelity.
- Keep finite-order/statistical/material/geometric-acoustics approximations visible.
- Final bounded runtime measurement follows Milestone 2; large-batch/GPU-port work
  and a real-time requirement are excluded by the approved decision.

#### Problems / Limitations

Step 2 selected-route NLOS is integrated and passes bounded transport/lifecycle controls. Door pressure remains probe-sensitive and diffraction is uncalibrated. The two-gate asynchronous route-discovery case remains a stress limit.

Step 3 is PASS under the revised criteria, with `diffuse=None` still the default. The native shared field passes binding energy, persistence, visibility, lifecycle and selected C03/C04 relative-impact controls. Full-room moving equivalence remains NOT VALIDATED and explicitly non-blocking; the cube and selected-mirror mismatches remain diagnostic. Joint NLOS/diffuse admission is still Step 4.

Material-phase separation, stable scalar/CUDA WPE and the native jamb departure-side correction resolve demonstrated defects. Historical observation intervals retain their original consumer version. The failed full-pressure angular cache cannot support unrestricted motion claims; use actual microphone-position responses or separately qualified sampling.

The [[experiments/geometry-acoustics-admission|admission record]] owns measured refinements, finite-seed confirmations, representative-room results, accepted limitations and costs. The bounded head/camera result supports retaining PRA but does not close full AV/mobile usefulness or physical transfer. The full-room reference audit stopped before a separate field formulation; no replacement provider is planned.

Admission must retain multi-arrival/LOS non-duplication, corridor detour bounds,
closed/open/closed and ordinary motion checks. Diffuse controls include co-location,
separated spacings/frequencies, within-bin directional timing, rotation/translation,
energy/decay, visibility, unchanged refresh and motion. Use isotropic coherence only
for controlled isotropic inputs, geometry-appropriate references for rooms. Keep
the cube's recorded pressure mismatch distinct from binding energy-accounting and
normalization checks; representative decay coverage and observation budgets remain.

If a maintainable extension cannot close a material mandatory-domain gap, apply the
[[decisions/robot-audition-fidelity#Provider stop rule and exclusions|stop rule]]
before a larger proprietary solver or another-provider evaluation. If physics passes
but perception fails, leave the task gate open and identify the owner; no automatic
localizer research. Preserve failed evidence and do not change budgets to pass.

## Subphase R10.3 — Operating Integration and Cleanup

#### Implementation

Complete the existing Python/Kit operating workflow: provider configuration,
capability/error reporting, caching/lifecycle and actionable path/material/coverage
diagnostics. Keep simulation facts separate from activity, events, direction,
confidence and RMS. A blocked path is not an inferred unreliable event.

Finish the geometry-backed sensor-to-instrument chain for a bounded occlusion
scene. [[topics/onr-video-production|ONR videos]] retain separate scene/media gates.
Consumer-justified geometry summaries may support Phase 09; no generic distribution
catalog or advanced analysis GUI is required here.

Consolidate one production binding and remove superseded experimental runtime paths
only after consumer/evidence review. Keep pinned native patches/build recipes and
version/ABI failures reproducible; preserve installed providers and required current native builds.

#### Key Decisions

- Retain Analytic's simple/reference and Lab roles; do not retire it in Phase 08.
- No provider-specific public observation fields or test-only runtime shortcuts.
- Native paths remain private/optional diagnostics; no truth leakage into decisions.

#### Problems / Limitations

08.3 is not implemented. Close only after affected native/stream checks, actual
Isaac Sim/Lab/Kit and CUDA perception, same-PCM scalar agreement, source-stop and
reset/isolation tests, `make check`, packaging and documentation checks pass.
Measure one/few-environment runtime/memory after Milestone 2; slower-than-real-time
is acceptable with coherent simulated clocks and explicit limits. No new recordings or training are required.

## Artifacts

[[experiments/geometry-acoustics-admission|Admission evidence]] owns key measurements, failed controls and current evidence-retention boundaries. Historical scope changes and detailed run
chronology are recoverable from this path at commit `5cfe48d`; they are not current
gates. Maintenance through `523695c` passed host/native and actual RTX Sim/Lab/Kit
plus clean-source distribution checks, preserving the intermediate rather than
qualifying new physics.

## Files

- `src/isaac_audio_sensors/isaac/acoustic_scene/` — prepared scene/native producer.
- `src/isaac_audio_sensors/kit/acoustic_scene.py` — shared authoring workflow.
- `tools/native/` — reproducible native bridges and experimental route interfaces.
- `tests/isaac/`, `tests/unit/`, `tools/smoke/` — native/stream and actual consumers.
