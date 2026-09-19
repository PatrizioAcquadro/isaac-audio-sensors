# Phase R10 — Geometry Acoustics Integration

Status: **08.1 and 08.2 (Milestone 2) are complete within their documented bounds.**
08.3 operating integration and bounded runtime/distribution closeout are complete.

## Objective

Deliver a reusable geometry-backed multichannel signal producer for robot audition
and learning in Isaac Sim/Lab. The [[decisions/robot-audition-fidelity|acoustic and interface criteria]]
define the indoor domain, invariants, numerical budgets and provider stop rule.
Robot policies, visual search, navigation and hardware acceptance stay downstream.

Read this plan and the decision to implement. Consult
[[topics/geometry-acoustics|the technical contract/build instructions]] as needed;
[[experiments/geometry-acoustics-admission|the admission record]] preserves decisive
positive and negative results. [[implementation_phases/08-geometry-acoustics-integration|Phase 08]]
owns completed stages and remaining execution order.

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

Milestone 2 is complete through four verified stages:

1. Prepared [[experiments/geometry-acoustics-trial-protocol|simulation fixtures]],
   bounded NVIDIA acoustic proxies, direct/scalar reference diagnostics and an RTX
   cost pilot. Local overlay units/up-axis were corrected. Preparation and model
   admission remain distinct.
2. Integrated the native selected-route Steam extension before SH/EQ aggregation.
   Native topology, length, directions, weights, filtering and validity feed
   causal route-specific rendering. Probe generation/search, visibility, alternate
   routing and coverage/rebake handling remain native. Direct LOS is excluded to
   prevent duplication. Bounded motion/door and in-flight arrival controls pass.
3. Integrated persistent shared PRA surface pressure with receiver-specific
   delays, amplitudes and directivity. Binding energy/normalization, persistence,
   visibility, lifecycle and selected C03/C04 motion/observation controls pass.
   The [[decisions/robot-audition-fidelity#Step 3 full-room limitation and admission decision (2026-09-16)|full-room and diagnostic limits]]
   remain explicit; native tracing and shared synthesis do not establish complete
   moving-room pressure equivalence.
4. Qualified direct, specular, diffuse and deviation contributions on one persistent
   sample clock. Native and actual RTX Sim/Lab controls pass source-stop tails,
   block equivalence, reset/partial reset, scene lifecycle, directional response,
   explicit capability failures and environment isolation. Failed rendering
   discards partially advanced environment state. Public PCM, observation,
   recording and Lab schemas are unchanged; scalar/CUDA perception receives only
   the final mixture. The admission record owns measurements and test counts.

#### Key Decisions

- Preserve Analytic and the working intermediate; enable extended coverage explicitly
  only after admission. One Geometry producer, no redundant experimental backends.
- Native geometry/delay checks and joint microphone physics are essential even when
  a downstream metric improves. Independent scalar/CUDA agreement is not fidelity.
- Keep finite-order/statistical/material/geometric-acoustics approximations visible.
- 08.3 owns final bounded runtime measurement; large-batch/GPU-port work
  and a real-time requirement are excluded by the approved decision.

#### Problems / Limitations

Step 2 selected-route NLOS is integrated and passes bounded transport/lifecycle controls. Door pressure remains probe-sensitive and diffraction is uncalibrated. The two-gate asynchronous route-discovery case remains a stress limit.

Step 3 is PASS under the revised criteria, with `diffuse=None` still the default. The native shared field passes binding energy, persistence, visibility, lifecycle and selected C03/C04 relative-impact controls. Full-room moving equivalence remains NOT VALIDATED and explicitly non-blocking; the cube and selected-mirror mismatches remain diagnostic. Joint NLOS/diffuse streaming passes Step 4, completing bounded 08.2 propagation and integration.

Material-phase separation, stable scalar/CUDA WPE and the native jamb departure-side correction resolve demonstrated defects. Historical observation intervals retain their original consumer version. The failed full-pressure angular cache cannot support unrestricted motion claims; use actual microphone-position responses or separately qualified sampling.

The [[experiments/geometry-acoustics-admission|admission record]] owns measured refinements, finite-seed confirmations, representative-room results, accepted limitations and costs. The bounded head/camera diagnostic supports retaining PRA; it does not establish general application performance or physical transfer. The full-room reference audit stopped before a separate field formulation; no replacement provider is planned.

Admission must retain multi-arrival/LOS non-duplication, corridor detour bounds,
closed/open/closed and ordinary motion checks. Diffuse controls include co-location,
separated spacings/frequencies, within-bin directional timing, rotation/translation,
energy/decay, visibility, unchanged refresh and motion. Use isotropic coherence only
for controlled isotropic inputs, geometry-appropriate references for rooms. Keep
the cube's recorded pressure mismatch distinct from binding energy-accounting and
normalization checks; representative decay coverage and observation budgets remain.

If a maintainable extension cannot close a material mandatory-domain gap, apply the
[[decisions/robot-audition-fidelity#Provider stop rule and exclusions|stop rule]]
before a larger proprietary solver or another-provider evaluation. Distinguish
acoustic defects from perception limits; SDK closeout does not establish absolute
tracking accuracy. Preserve failed evidence and do not change budgets to pass.

## Subphase R10.3 — Operating Integration and Cleanup

#### Implementation

Implemented the existing Python/Kit operating workflow: provider configuration,
capability/error reporting, controller-owned scene lifecycle and actionable
path/material/coverage diagnostics. Keep simulation facts separate from activity, events, direction,
confidence and RMS. A blocked path is not an inferred unreliable event.

Completed the geometry-backed sensor-to-instrument chain for a bounded moving-screen
scene, including combined providers, tail, lifecycle and actual packaged Kit.
[[topics/onr-video-production|ONR videos]] retain separate scene/media gates.
Consumer-justified geometry summaries may support Phase 09; no generic distribution
catalog or advanced analysis GUI is required here.

Consumer/evidence review confirmed one production binding per maintained capability;
no further runtime deletion was necessary. Pinned native patches/build recipes,
version/ABI checks, installed providers and required native builds are preserved.

#### Key Decisions

- Retain Analytic's simple/reference and Lab roles; do not retire it in Phase 08.
- No provider-specific public observation fields or test-only runtime shortcuts.
- Native paths remain private/optional diagnostics; no truth leakage into decisions.

#### Problems / Limitations

08.3 closes after passing native/stream checks, actual RTX Isaac Sim/Lab/Kit,
same-PCM scalar/CUDA agreement, source-stop and reset/isolation, `make check`,
clean-source sdist/wheel/Kit audits and the extracted-archive smoke. One/two-environment
base/combined costs are recorded in the admission evidence. These bounded CPU-native
costs do not qualify real-time operation, complex rooms or large batches. No physical
recording, training or acoustic GPU port was introduced.

## Artifacts

[[experiments/geometry-acoustics-admission|Admission evidence]] owns key measurements, failed controls and current evidence-retention boundaries. Historical scope changes and detailed run
chronology are recoverable from this path at commit `5cfe48d`; they are not current
gates. Maintenance through `523695c` passed host/native and actual RTX Sim/Lab/Kit
plus clean-source distribution checks, preserving the intermediate rather than
qualifying new physics.

## Files

- `src/isaac_audio_sensors/isaac/acoustic_scene/` — prepared scene/native producer.
- `src/isaac_audio_sensors/kit/acoustic_scene.py` — shared authoring workflow.
- `tools/native/` — reproducible optional native bridges and qualified route interfaces.
- `tests/isaac/`, `tests/unit/`, `tools/smoke/` — native/stream and actual consumers.
