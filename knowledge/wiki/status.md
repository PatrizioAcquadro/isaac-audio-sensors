# Current Status

Updated: 2026-10-14. Package version: `3.0.0`.

## First-scene combined indoor readiness

The optional **16 kHz, 200 ms, no-WPE, .98 coherence** profile passes live quality
and timing together in the declared one-voice interior. Two fresh 30-second runs
with an actual Alex articulation/PD load, 64 moving bodies and a visible 640x480
RGB/depth scene at **15 Hz** deliver 600 observations at 9.98999–9.99028 per real
second, with no lost windows or accumulated queue. Active complete sets are
97.71% / 94.87%; no active error reaches .5 s. Deadline-to-SDK p95 is
34.28–42.03 ms; audio-clock onset p95 is 100/200 ms and is a separate measure.

The [[experiments/consumer-audio-runtime-performance#Combined indoor qualification — 2026-10-14|combined report]]
owns the complete workload, clocks, failures, exact preservation, numerical fixes
and reproducible configuration. Source code now prunes impossible native paths,
initializes DSP before acquisition, captures single-array solver dispatch and
aligns centroid boundaries with Core. An explicit 12-triangle interior envelope
preserves tested PCM exactly while the solid visual room stays rendered. All
600 scalar/CUDA activity/count comparisons match, with direction differences
<.00005 degrees. Reset preserves PCM and all 18 output fields exactly.

Use `examples/isaac_lab/indoor_single_voice.py` and its room asset as an opt-in
consumer trial, with rebuilt native libraries. This qualifies one environment,
nominal planar microphones, the tested 2.25 m LoS trajectory and declared load.
The unpaced full profile reaches 1.0879 simulated seconds per real second;
optimizer/multi-Alex scale, other rooms/materials/body acoustics, elevation,
receiver translation, arbitrary source levels, physical transfer, actual
SquadBot head/camera/queue adoption and universal 100 ms lag are not qualified.
Multisource remains outside this intervention. SDK 3.0.0 is unreleased; no push.

Current targeted validation passes 62 host cases, 65 actual CUDA/Isaac cases plus
an exact captured/eager control, 55 native controls and the combined live gates.
Earlier full host/release audits below are historical evidence, not rerun claims.
This pass does not modify historical branch evidence or the failed main-integration probe.

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

## Consumer audio readiness — 7.1

[[implementation_phases/squadbot-audio-runtime-readiness|7.1 is complete as a bounded compatibility and quality assessment]];
7.2 qualifies the initial free-field profile and the bounded indoor combination
above under their respective declared loads.
SDK 3.0.0 remains unreleased.
The original assessment left perception, public APIs and schemas unchanged;
downstream dependencies/adapters were not modified. The local Sim `6.0.1-rc.7` /
Lab `3.0.0` (`2e44ddb2e1`) /
RTX 4090 combination passes 672 unit/contract, 352 integration, 56 release and
251 Isaac tests, plus actual Sim/Geometry and 60 Hz / 10 Hz square-array Lab.

The 18-episode screen reaches 1 m/s source motion and 90 degrees/s receiver yaw,
using natural speech, a nominal four-microphone array and separate received-PCM
scoring. Scalar/CUDA preserve activity on all 1440 updates and count on 1439
(99.93%); retained-direction difference p95 is .000018 degrees. The retained
36-recording stationary comparison still preserves every activity/count update.

Active complete sets are 97.9% for static speech and 96.8% for a moving source
with fixed receiver. They fall to 49.7% with receiver rotation, 59.9% with joint
motion, 34.2% in the Geometry-room screen and 49.3% with a competing voice.
This supports a provisional fixed-receiver free-field listening profile; it does
**not** establish reliable full-domain closed-loop tracking. Received-onset
responses and warm-up do not establish wall-clock reaction or learning throughput.
[[experiments/consumer-audio-operating-envelope|The assessment]] owns the protocol,
reproduction, numerical discrepancy and remaining acoustic/physical limits;
[[decisions/product-boundary-and-compatibility#Consumer readiness migration|migration guidance]]
owns the consumer handoff. Local reports are in `build/validation/sdk-readiness-7.1/`.

### Dynamic-quality follow-up

The SDK now exposes explicit context and optional WPE preprocessing in scalar
and both Lab bindings. Defaults preserve 750 ms WPE; observations, timestamps,
ambiguity and serialized schemas remain unchanged. Recommend a **200 ms direct
covariance free-field profile for bounded one-voice trials**. Original rotating
complete sets rise from 49.7% to 97.3%, joint motion from 59.9% to 96.8%, while
static stays 97.9%. Matched room/motion controls and 15 fresh confirmation
episodes distinguish this from the historical assessment.

Fresh per-scenario complete sets are 92.5–95.7%, source-correct onset p95 200 ms,
and no active error run reaches .5 s. Two 3 m episodes reach only 89.7/86.8%;
uniform 1.5–3 m reliability is not established. Some fitted lags reach 130–140 ms,
and room/competing voices remain insufficient. WPE 250 ms is an experimental
room alternative, with remaining false events and about 118 ms live update cost.
The direct profile's small isolated live gate measures about 32 ms p95, with
scalar preservation and reset at 60 Hz acquisition/10 Hz observations.

Host gates pass 682 unit/contract, 357 integration and 56 release cases;
261 supported-runtime Isaac cases pass. Corrected matching, profile selection,
per-scenario results, finite numerical discrepancies, cold/warm replay costs
and retained artifacts are in
[[experiments/consumer-audio-dynamic-quality|dynamic-quality evidence]].
**Full dynamic readiness remains open.** Replay/live smoke costs remain distinct
from the loaded 7.2 qualification below.

### Indoor-quality follow-up

Opt-in `localization_spatial_coherence=.98` with 200 ms direct context reduces
reflected events while preserving default behavior and scalar/CUDA contracts.
Independent fresh room static/source/rotation/joint conditions reach 94.5–97.3%
complete sets, worst episode 92.4%; free single-voice conditions reach 97.8%.
Audio-clock first-correct p95 is 200 ms; some fitted lags still reach 140 ms.
Preliminary single-array compute p95 is about 15.3 ms, separate from 7.2.

**Only bounded single-voice trials are supported by this evidence.** Mixed voices
lose real support: the -9 dB room voice retains 15/72 correct windows, versus
47/72 for the unfiltered direct profile. Two-voice complete sets and weak-room
onset/continuity remain insufficient. The
[[experiments/consumer-audio-indoor-quality|indoor-quality evidence]] owns the
frozen configuration, same-PCM historical/direct/WPE comparisons, worst episodes,
validation and reproducible command. Arbitrary rooms/physical transfer and overlap
recovery remain open; the first-scene combined runtime is qualified above. SDK 3.0.0 remains unreleased.

## Consumer audio performance — 7.2

The [[experiments/consumer-audio-runtime-performance|measured initial 200 ms no-WPE
free-field profile]] sustains 10 Hz SDK delivery on the RTX 4090 with 60 Hz
physics/acquisition, 64 moving rigid bodies and a shared 640x480 RGB camera at
30 Hz. Four clean 30-second runs deliver 1,200 updates without skipped windows,
discontinuities or persistent scheduling growth. SDK p95 is 32.86–33.68 ms
(returned-active 34.98–36.86 ms); first activation reaches 83.35 ms and remains
explicit. Loaded delivery p95 stays below 47 ms relative to real deadlines.

Identity mount/constant-axis optimization approximately halves geometric cost
and preserves every PCM sample and all 18 public observation fields in a matched
300-update comparison. Host checks pass 682 unit/contract, 367 integration and
56 release cases; 265 actual-runtime tests pass with the borrowed native libraries.

The 60 Hz camera stress case still accumulates backlog and is not qualified.
Unpaced 1/4/16-environment rollout rates are 1.053 / 4.273 / 16.635 aggregate
simulated seconds per real second; optimizer throughput and required training
scale remain undefined. A retained indoor-stage control reaches only 6.45 updates
per real second; the later combined first-scene qualification is recorded above.
Other indoor scenes and downstream integration need their own admission checks.
Historical results, failed/contaminated attempts and reproduction stay separate
in the original runtime worktree's ignored `build/validation/runtime-performance/`;
[[implementation_phases/squadbot-audio-runtime-readiness#Artifacts|artifact locations]]
record the original worktree paths and current replay limitations.

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
