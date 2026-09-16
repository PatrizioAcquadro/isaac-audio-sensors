# Current Status

Updated: 2026-09-16. Package version: `3.0.0`.

## Current work

**Phase 08: scene preparation, the Geometry intermediate and Steps 1–3 are complete within their declared bounds. Step 3 is PASS with documented limits. Milestone 2 and 08.3 remain open.**

- Production Geometry combines Steam direct/planar transmission with native PRA specular reflections. Selected-route NLOS and shared diffuse pressure are separate opt-ins; defaults and Analytic remain maintained. Their combination is not yet admitted.
- **Next: Step 4, combined producer**, then AV usefulness, mobile usefulness, operating integration and bounded runtime/packaging closeout. Follow [[implementation_phases/08-geometry-acoustics-integration|the execution sequence]] and [[decisions/robot-audition-fidelity|the approved domain and budgets]].
- Full-room moving pressure/observation equivalence is **NOT VALIDATED**, explicitly accepted as non-blocking for Step 3. Cube late-response and selected-mirror mismatches remain diagnostic limits. New structural or material representative failures still reopen affected qualification.
- Selected maximum source/receiver/yaw confirmations pass relative budgets on both arrays at 2.5 ms. Unrestricted 10 ms updates, population-wide field equivalence and useful absolute tracking are not established. Door NLOS pressure remains probe-sensitive and uncalibrated.
- WPE conditioning/peak ties and the native door-jamb projection defect are corrected. The stable WPE solve is expensive: measured 16-copy supplied-PCM p95 is about .99/1.66 s for square/raised per 100 ms update. This is offline cost, not added simulated latency. Full-pressure angular-cache isolation remains failed.

[[experiments/geometry-acoustics-admission|Admission evidence]] owns the decisive results and limitations. [[experiments/geometry-acoustics-trial-protocol|Trial protocol]] owns future scenarios/scoring; [[topics/geometry-acoustics|Geometry Acoustics]] owns interfaces/builds. Read those pages only as needed for the current step.

## Maintained capabilities

| Area | Verified capability and boundary |
| --- | --- |
| Signals and perception | Immutable PCM, observed-only frames, activity/DOA/ambiguity and confidence availability; [[topics/public-contracts-and-recording|public contracts]] |
| Analytic propagation | Continuous motion/delay/tails, supported Core/PRA topologies and bounded PhysX direct occlusion; [[implementation_phases/r8-analytic-acoustics-backend|R8]] |
| Localization | Stereo ambiguity and bounded stable-source WPE/group-sparse multisource; weak/fast/reverberant mixtures remain difficult; [[experiments/04-4-multisource-localization|localization evidence]] |
| Lab and Kit | 07.1–07.3 observed tensors, independent clocks/resets, CUDA perception and multievent instruments; parity does not establish accuracy; [[experiments/lab-perception-runtime|runtime evidence]] |
| Recording and physical comparison | Aligned samples/observations/truth, replay and splits; 25 real/sim takes without calibrated transfer; [[experiments/physical-signal-comparison|physical evidence]] |
| Geometry preparation | Automatic USD/material/proxy discovery, selective pose updates and shared Kit authoring; preparation is separate from propagation fidelity |
| Distribution | Maintained clean-source sdist/wheel/Kit and optional/native dependency gates; [[topics/validation-and-release|validation and release]] |

## Delivery and boundaries

ONR videos **1–3 are delivered**; revisions **4–9** retain individual scene/media gates. [[topics/onr-video-production|ONR production]] owns readiness. Cleanup preserves regeneration and approved deliveries; it produces no new media.

[[implementation_phases/09-practical-realism-and-randomization|Phase 09]] owns practical variation; [[implementation_phases/10-end-to-end-validation-and-product-closeout|Phase 10]] owns product-wide closeout; [[implementation_phases/11-future-semantic-perception|Phase 11]] semantics/tracking remain deferred. No physical campaign, policy training, acoustic GPU port or large-batch Geometry requirement is implied.

The SDK owns reusable Core, recording, CLI, Isaac/Kit/Lab and packaging. Robot policies, adapters and experiment orchestration stay downstream/ignored. `local/` retains future development and ONR inputs; concluded trial outputs were removed after consolidating their findings. The wiki does not promise historical raw-output replay. Code/tests define executable behavior; historical test totals do not imply checks on the current HEAD.
