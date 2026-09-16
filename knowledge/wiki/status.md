# Current Status

Updated: 2026-09-16. Package version: `3.0.0`.

## Current work

**Phase 08: SDK scene preparation and intermediate Geometry PCM are complete;
Milestone 2 and operating integration remain open.**

- Approved scope: [[decisions/robot-audition-fidelity|ordinary-indoor robot audition, numerical impact budgets and stop rule]], AV attention/search first, then mobile.
- Production Geometry: Steam direct/planar transmission + corrected native PRA
  specular reflections. Selected-route NLOS is implemented as an explicit option;
  Step 2 selected-route transport controls are complete, including ordinary
  motion, doors, probe/update refinement and actual RTX Isaac updates. Door
  pressure remains probe-sensitive and uncalibrated. Shared diffuse pressure is
  an experimental opt-in, disabled by default and not admitted.
  Analytic remains maintained.
- Next: [[implementation_phases/08-geometry-acoustics-integration#Remaining execution order|the eight-step sequence]]:
  PRA diffuse → combined stream → AV → mobile →
  operating workflow → actual runtime/packaging and bounded cost closeout.
- Step 1 [[experiments/geometry-acoustics-trial-protocol|concrete preparation is complete within the clarified scope]]:
  recovered RTX 4090, concrete scenes/inputs, bounded Office/Hospital acoustic
  proxies, generic footprint/visibility, static direct/scalar diagnostics and the
  intermediate cost pilot. Local overlay units/up-axis were fixed without an SDK
  change. A representative family plan supersedes exhaustive per-row repetition.
  Those initial full-field decay/DRR, closed-door scattering and moving-room
  reference gaps were assigned to later qualification; Step 3 results are below.
  No closed-loop benefit or combined-model qualification ran in Step 1.
- Key unresolved result: the earlier moving-ray PRA model biases weak-direct
  observations; bounded NLOS timing/visibility controls pass, while door-pressure refinement has not established
  convergence. [[experiments/geometry-acoustics-admission|Admission evidence]]
  distinguishes failures, fixes and stress limits. No replacement evaluation starts
  without the approved decision point.
- **Step 3 remains unqualified; the cube failure is now diagnostic by user decision.**
  The general persistent field and optional D producer pass 36 native, analytic
  and streaming controls. Closed-partition projection and gain-dependent banded
  specular phase defects are corrected. A conditioned smooth 3 m room still fails
  the original pressure-decay criterion. The preceding numerical consumer at
  order 7/65536 rays recorded the following RTX 4090 observation failures:
  spurious-update changes are -23.08 points on square and -67.43 on raised, with
  95% intervals outside the +/-5-point budget. Main-bearing, miss and added-latency
  budgets pass in this fixed-scene comparison. These results remain FAIL under the
  original criteria; matching the cube's late response is no longer required to
  continue or close Step 3. The
  [[decisions/robot-audition-fidelity#Step 3 cube diagnostic decision (2026-09-16)|approved decision]]
  keeps structural invariants, numerical margins and representative observation
  gates binding. It neither fixes the physics nor admits the candidate.
  The reproduced raised-reference scalar/CUDA and batch-count defect is now
  corrected; the historical intervals have not been rerun with the corrected consumer.
  The earlier rotating selected-mixture pass remains historical evidence within
  its scope; its ~0.17 physical statistic is also diagnostic with targeted impact
  evidence.
  C03/C04 now have actual-producer controls and selected maximum-speed
  confirmations; complete room-motion qualification and later consumers remain
  open. A targeted
  follow-up shows that correcting 1 kHz decay alone barely changes the discrepancy,
  while replacing the late response recovers most reference extras. Actual SquadBot
  software replay retains posterior orienting cues. A subsequent bounded geometric
  head/camera study completes sixteen diagnostic and 192 fresh refined episodes
  with actual RTX perception. Every treatment acquires the source; the candidate
  retains a measured resumption-time benefit over audio-off. One 100 ms false
  association is recorded; the pooled rate interval fits five points, while the
  raised-only interval remains inconclusive. Direct-only controls expose a separate
  numerical consumer defect, corrected by the measurement work below. The compact
  joint campaign uses the actual D producer at microphone positions. Its remaining
  room/reference boundary is recorded below. Full AV/mobile
  usefulness belongs to Steps 5–6; tracking and matched physical transfer are separate unvalidated claims.
  This acceptance revision changes the cube comparison's role, not the operating
  domain or numerical margins. PRA remains retained and diffuse remains opt-in
  and `not_admitted`. [[experiments/geometry-acoustics-admission|Evidence and limits]].
- **Measurement reliability:** weighted QR/pseudoinverse WPE and stable float64
  peak arithmetic correct direct-symmetry and scalar/CUDA count defects without
  retuning perception. The 27 affected RTX tests and 15 scalar tests pass; four
  problematic cube streams preserve all 128 activity/count updates, including
  32-environment reorder/loud-neighbor/reset controls. The angular-cache error is
  isolated mainly to native early specular paths; its full-pressure isolation
  check remains failed. It cannot support unrestricted motion or tail-only causal
  claims. Historical observation intervals remain tied to the preceding solver.
  [[experiments/geometry-acoustics-admission#Measurement reliability (2026-09-16)|Corrected measurements and evaluator limits]]
  records the targeted replay: four AV episode outcomes are preserved, including
  the known false association. The stable computation costs p95 ~.99/1.66 s for
  16 square/raised copies per 100 ms update in the supplied-PCM check; this is
  offline throughput, not added simulated perceptual latency. Prior interactive
  batch guidance does not apply. Physical admission remains separate.

- **Closed-door projection correction:** a newly reproduced E3 jamb connection
  could project behind the previous reflector within endpoint tolerance. The
  native departure-side check fixes it: actual closed/open/closed D has exact zero
  energy at both closed poses and nonzero open pressure. Fifteen native/field and
  nine producer checks pass. Rebuild the diffuse bridge for the added private
  capability. This is separate from the cube diagnostic limitation and the
  [[experiments/geometry-acoustics-admission#Targeted closeout and projection correction (2026-09-16)|targeted closeout]].

- **Joint motion/observation controls:** the actual D producer passes dynamic
  array grouping, source identity, reset, independent-environment and PCM replay
  checks. Dense-plane energy/coherence controls pass on C03/C04 trajectories.
  Fresh 96-program confirmations at 2.5 ms pass all relative budgets for maximum
  C03 source motion and C04 translation/yaw on both arrays and gains. These are
  conditional on field 31001; absolute weak/fast performance remains difficult
  in both models. Lower-speed cells retain diagnostic coverage, and unrestricted
  10 ms updates are not admitted. The bounded two-source room probe has no
  misses/extras in twelve eligible updates; screened arrivals remain unresolved.
  [[experiments/geometry-acoustics-admission#Joint motion and observations (2026-09-16)|Joint controls]]
  and [[experiments/geometry-acoustics-admission#Targeted closeout and projection correction (2026-09-16)|targeted confirmations]]
  retain absolute rates, field-seed checks and confidence limits.
  Three fresh fields expose two low-N signed rate signals; separate 96-program
  confirmations pass all budgets for both. Original pilot FAIL outputs remain
  recorded. This completes the finite-seed check, not population equivalence.

- **Representative room boundary:** thirteen corrected key poses, 10278 analytic
  visibility comparisons, controlled isotropic synthesis and the E2 2/4 s horizon
  pass their applicable controls. Static physical weak direct measures
  -11.64/-11.59 dB; four programs have zero misses but 21.43%/42.86% spurious
  updates on square/raised. Office/Hospital static D integration passes on the
  original acoustic proxies; Hospital requires a documented 200000-node local
  capacity override. These are bounded property/integration results. Complete
  moving-room pressure/observation references, input conditioning and full-D routes
  remain open. Native preparation costs 24.2–157.3 s per room pose in this panel;
  it is offline. **Retain PRA; Step 3 remains `not_admitted` because the remaining
  room gate lacks evidence, not because the diagnostic cube must be matched.**

- **Bounded full-room reference audit: stopped at the authorized scope.** The
  user retained the current gate. Existing shoebox/plane references and native
  energy/history do not supply an independently justified shared pressure field
  for the furnished moving-room conditions. The minimum missing work is a second
  room-field formulation and its validation, while PRA traversal remains reusable;
  no new geometric engine is proved necessary. Three existing motion paths and
  one static two-source companion are specified conditionally, with saved cost
  extrapolations. No room campaign, qualified-control rerun or provider evaluation
  was launched. Further reference-model work or a requirement revision needs a
  separate user decision. The full-room gate remains OPEN.
  [[experiments/geometry-acoustics-admission#Bounded full-room reference feasibility (2026-09-16)|Missing capabilities, reference limits and stop evidence]].

## Maintained capabilities and boundaries

| Area | Verified state | Important limit / owner |
| --- | --- | --- |
| Signals and perception | Common immutable PCM, observed-only frames, explicit activity/DOA/ambiguity/confidence availability | No truth in perception; [[topics/public-contracts-and-recording|contracts]] |
| Analytic propagation | Continuous delay/motion/tails, supported Core/PRA topologies, bounded PhysX direct occlusion | No arbitrary geometry or shared diffuse qualification; [[implementation_phases/r8-analytic-acoustics-backend|R8]] |
| Localization | Stereo ambiguity, nominal planar role, bounded stable-source WPE/group-sparse multisource | Weak/fast/reverberant mixtures and temporal response remain limited; [[experiments/04-4-multisource-localization|04.4 evidence]] |
| Lab and Kit | 07.1–07.3 complete: observed tensors, independent clocks/resets, CUDA perception and multievent instruments | Free-field CUDA propagation; parity is not perception accuracy; [[experiments/lab-perception-runtime|measured costs]] |
| Recording and physical parity | Aligned samples/observations/truth, learning samples, replay/splits; 25-take real/sim comparison | Raw retained; no gain calibration or general transfer; [[experiments/physical-signal-comparison|physical evidence]] |
| Geometry scene | USD/native import, source-band materials, proxies, selective updates and authoring Undo/Redo | Preparation is not acoustic qualification; [[topics/geometry-acoustics|technical contract]] |
| Distribution | Clean-source sdist/wheel/Kit and optional/native dependency gates maintained | Build validation is not publication; [[topics/validation-and-release|release workflow]] |

Recent geometry maintenance through `523695c` passed host, optional/native and
actual RTX Sim/Lab/Kit plus packaged offline Kit checks. It preserves the
intermediate; the approved R10 domain has no new admission evidence from the
scope/knowledge edits. Tests/code are authoritative; historical totals are not a
claim that checks were rerun on a documentation-only commit.

## Next phases and delivery

[[implementation_phases/09-practical-realism-and-randomization|09]] owns useful
variation/distributions; [[implementation_phases/10-end-to-end-validation-and-product-closeout|10]]
owns product-wide closeout. [[implementation_phases/11-future-semantic-perception|11]]
classification/tracking/separation remain deferred. No new physical campaign,
policy training, acoustic GPU port or large-batch Geometry requirement is implied.
Slower-than-real-time Geometry is acceptable within the approved clock/domain limits.

ONR revised videos **1–3 are delivered**. Revisions **4–9** need their individual
scene/media gates; several can use current capabilities and do not require full
Phase 08. [[topics/onr-video-production#Remaining ONR deliveries after the R10 profile decision|ONR readiness]]
owns exact dependencies and saved reports. No new media is produced by this update.

## Product boundary

Reusable SDK: Core, recording, CLI, Isaac/Kit/Lab, schemas, examples and packaging.
Robot adapters, policies, acquisition campaigns and experiment orchestration stay
downstream/ignored. [[index|Index]] is the reading map; [[log|log]] contains only
milestone-level knowledge history. Detailed chronology remains in Git/evidence.
