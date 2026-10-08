# Current Status

Updated: 2026-10-08. Package version: `3.0.0`.

## Maintenance validation

The checkout remains **3.0.0 — Unreleased**; the published release remains 2.0.0.
This pass keeps the existing subsystem layout and removes unused helpers,
test-only production branches, duplicate validators and redundant checks.
Kit configuration is parsed before application; recorder configuration and
episode serialization have separate ownership. See
[[decisions/product-boundary-and-compatibility#Maintenance removals in unreleased 3.0|migration details]].

- Host: 672 unit/contract, 348 integration and 56 release tests pass, with lint,
  version synchronization and whitespace checks. Optional room/FLAC execution and
  missing-dependency rejection are covered.
- Supported Isaac runtime: 251 tests pass, including real USD and CUDA controls.
  Actual RTX 4090 Sim, two-environment combined Geometry Lab/reference comparison,
  and source Kit pass. Kit completes 39 workflow steps and required screenshots.
- Clean-source sdist, wheel built from the sdist, and locked-dependency Kit archive
  audits pass. The extracted archive uses the same live Kit gate; native providers
  remain external runtime dependencies.
- Consumers: 17 focused SquadBot adapter/replay/bench tests pass. ONR Video 6
  recording replay and causal display verification pass on preserved inputs;
  1,200 revised display rows match the approved capture. No videos were regenerated.
- Selective local cleanup recovered 2.92 GiB of allocated files. Native providers
  and builds, wheelhouse, ONR originals/deliveries/tools, and Lab/R10 inputs remain.
  `knowledge/raw/` is untouched.

Local reports and failed development attempts are in
`build/validation/maintenance-20261008/`. These checks preserve current behavior;
no new acoustic accuracy, performance or physical qualification is claimed.

## Geometry qualification

**08.1–08.3 and Phase 08 are complete within their documented bounds. Operating, runtime and clean-source distribution gates pass.**

- Production Geometry combines Steam direct/planar transmission with native PRA specular reflections. Selected-route NLOS and shared diffuse pressure can be enabled separately or together. The combined stream passes native and actual RTX Sim/Lab lifecycle and isolation controls; defaults and Analytic remain maintained.
- **08.3 complete:** shared Python/Kit preparation and sensor ownership, provider controls, saved settings and separate diagnostics pass lifecycle and actual RTX Sim/Lab/Kit gates. Base/combined measurements cover 1–2 environments; sdist, derived wheel and Kit archive pass audits, and the extracted Kit archive passes its live smoke. Historical runtime and distribution measurements belong to the admission evidence below. Follow [[implementation_phases/08-geometry-acoustics-integration|the execution sequence]] and [[decisions/robot-audition-fidelity|the approved domain and budgets]].
- Full-room moving pressure/observation equivalence is **NOT VALIDATED**, explicitly accepted as non-blocking for Step 3. Cube late-response and selected-mirror mismatches remain diagnostic limits. New structural or material representative failures still reopen affected qualification.
- Selected maximum source/receiver/yaw confirmations pass relative budgets on both arrays at 2.5 ms. Unrestricted 10 ms updates, population-wide field equivalence and useful absolute tracking are not established. Door NLOS pressure remains probe-sensitive and uncalibrated.
- WPE conditioning/peak ties and the native door-jamb projection defect are corrected. The stable WPE solve is expensive: measured 16-copy supplied-PCM p95 is about .99/1.66 s for square/raised per 100 ms update. This is offline cost, not added simulated latency. Full-pressure angular-cache isolation remains failed.

[[experiments/geometry-acoustics-admission|Admission evidence]] owns the decisive results and limitations. [[experiments/geometry-acoustics-trial-protocol|Simulation fixtures]] owns prepared inputs and verified preparation limits; [[topics/geometry-acoustics|Geometry Acoustics]] owns interfaces/builds. Read those pages only as needed for the current step.

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

ONR videos **1–6 are delivered**; revisions **7–9** retain individual scene/media gates. Video 6 adds the furnished Garage's same-source reflective/absorptive comparison with explicit material assignments and the unchanged current sensor. The user approved the full-wall A/B audio; the presentation revision adds material/absorption labels, listening cues, a restrained transition and perforated lining while preserving that audio and all observations. Numerical controls, recording replay, causal instruments and the 40 s 1440p master pass. Video 5's revised warehouse film retains its 201/201 stable-window gate and separately reported moving-transition limitation. Videos 1–3 remain approved and unchanged; Video 4 awaits user review. [[topics/onr-video-production|ONR production]] owns evidence, final-review boundaries and bounded claims.

[[implementation_phases/09-practical-realism-and-randomization|Phase 09]] owns practical variation; [[implementation_phases/10-end-to-end-validation-and-product-closeout|Phase 10]] owns product-wide closeout; [[implementation_phases/11-future-semantic-perception|Phase 11]] semantics/tracking remain deferred. No physical campaign, policy training, acoustic GPU port or large-batch Geometry requirement is implied.

The SDK owns reusable Core, recording, CLI, Isaac/Kit/Lab and packaging. Robot policies, adapters and experiment orchestration stay downstream/ignored. `local/` retains future development and ONR inputs; concluded trial outputs were removed after consolidating their findings. The wiki does not promise historical raw-output replay. Code/tests define executable behavior; historical test totals do not imply checks on the current HEAD.
