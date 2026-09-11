# Current Status

Updated: 2026-09-11. Package version: `3.0.0`.

## Current work

**Phase 08: scene preparation and intermediate Geometry PCM are complete;
Milestone 2 and operating integration remain open.**

- Approved scope: [[decisions/robot-audition-fidelity|ordinary-indoor robot audition, numerical impact budgets and stop rule]], AV attention/search first, then mobile.
- Production Geometry: Steam direct/planar transmission + corrected native PRA
  specular reflections. Experimental selected-route NLOS and shared diffuse
  pressure are not enabled. Analytic remains maintained.
- Next: [[implementation_phases/08-geometry-acoustics-integration#Remaining execution order|the eight-step sequence]]:
  concrete test matrix → NLOS → PRA diffuse → combined stream → AV → mobile →
  operating workflow → actual runtime/packaging and bounded cost closeout.
- Key unresolved result: PRA motion biases weak-direct observations; bounded NLOS
  timing is useful but not integrated. [[experiments/geometry-acoustics-admission|Admission evidence]]
  distinguishes failures, fixes and stress limits. No replacement evaluation starts
  without the approved decision point.

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
