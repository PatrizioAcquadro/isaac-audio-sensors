# Knowledge Log

Compacted on 2026-09-11 at the user's explicit request. Routine lint entries and
repeated run narratives are consolidated; canonical pages retain decisions,
results and evidence pointers. The full earlier log is recoverable at `5cfe48d`.
Future entries should remain short and append-only; this compaction is not a
standing authorization to rewrite history.

## 2026-08-20 — update: Product and knowledge boundaries

[[implementation_phases/r2-fast-test-architecture|R2]] separated test lanes;
[[implementation_phases/r3-product-boundary-cleanup|R3]] removed campaign payload;
[[implementation_phases/r4-documentation-consolidation|R4]] established canonical wiki ownership.

## 2026-08-21 — update: Runtime ownership and release

[[implementation_phases/r5-semantic-component-refactor|R5]] consolidated subsystem
APIs/lifecycle. [[implementation_phases/r6-packaging-and-release|R6]] delivered
clean-source Python/Kit and historical v2.0.0 publication (`583d66e`).

## 2026-08-27 — update: Maintainable consumers and acoustic contracts

Aug 24–27 cleanup aligned native Kit audition, source organization, release tools,
gain/directivity and snapshot ownership. Current behavior lives in
[[topics/system-architecture|Architecture]], [[topics/acoustic-modeling|Acoustic Modeling]]
and [[topics/validation-and-release|Validation and Release]].

## 2026-09-01 — update: Explicit environments and analytic propagation

[[implementation_phases/r7-acoustic-environment-contract|R7]] made environment
resolution explicit/fail-closed; [[implementation_phases/r8-analytic-acoustics-backend|R8]]
consolidated analytic solvers and direct-only partition attenuation.

## 2026-09-03 — update: Provider selection and observed-only boundary

[[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] selected bounded
Steam capabilities; R9.4 ran between 02.1 and 02.2. [[implementation_phases/02-signal-and-perception-architecture|02]]
separated PCM/perception and removed the legacy bridge. Later R10 withdrew stronger
reflection/NLOS timing interpretations; archived reports remain unchanged.

## 2026-09-04 — update: Activity, direction and datasets

[[implementation_phases/03-audio-activity-detection|03]] integrated fixed-threshold
Auditok; [[implementation_phases/04-observed-direction-estimation|04.1–04.3]] qualified
nominal DOA roles but failed robustness. [[implementation_phases/05-ground-truth-and-learning-datasets|05]]
separated truth/learning inputs; 06.1 established common signal continuity.

## 2026-09-07 — experiment: Physical signal comparison

[[experiments/physical-signal-comparison|25-take real/sim comparison]] passed software
parity but exposed weak-level activity mismatch. Gains were rejected/inconclusive;
raw capture retained, no general physical transfer claim.

## 2026-09-08 — experiment: Stable multisource reference and Lab projection

07.1 projected observed events. [[experiments/04-4-multisource-localization|04.4]]
recorded failed candidates, then two fresh 24-group confirmations for the maintained
stable-source WPE/group-sparse reference. General temporal behavior stayed open.

## 2026-09-09 — update: Continuous timing, runtime correctness and ONR

[[decisions/continuous-acoustic-clock|Continuous propagation]] fixed per-window
arrival loss. Confidence null/zero and PhysX solid occlusion were corrected.
Temporal candidates failed; user admitted bounded 07.2 and suspended that research.
[[topics/onr-video-production|ONR revised videos 1–3]] completed with saved scope/QA.

## 2026-09-10 — update: Lab/GUI closeout and Geometry intermediate

[[experiments/lab-perception-runtime|07.2 practical batches]] retained float64 WPE;
07.3 completed observed GUI and consumer cleanup. R10 scene preparation completed;
[[experiments/geometry-acoustics-admission|native failures/corrections]] admitted only
Steam direct/transmission + PRA specular streaming, with actual Isaac/CUDA checks.

## 2026-09-11 — experiment: Native route and diffuse motion limits

[[experiments/geometry-acoustics-admission|Selected-route timing and interception]]
passed bounded controls; NLOS arrival direction improved. PRA shared pressure still
biased weak-direct moving observations; first-scatter anchors did not solve later
persistence. No replacement provider was evaluated in these extension runs.

## 2026-09-11 — update: Approved task-domain ambition

[[decisions/robot-audition-fidelity|Approved both profiles, domain, budgets and stop rule]]
(`5cfe48d`). Exact dynamic completeness became stress scope; retain Analytic,
allow slower-than-real-time simulation, defer large-batch/GPU-port work. Maintenance
through `523695c` preserved the intermediate with host/native/actual packaged Kit gates.

## 2026-09-11 — update: Compact implementation knowledge

At user request, compact all plans/status/log; move binding fidelity decisions,
reusable Geometry contract and decisive provider/physics/physical/Lab evidence to
canonical owner pages. Preserve unresolved requirements and original local artifacts;
full prior prose remains in Git. No code, raw material, AGENTS.md or media changes.

## 2026-09-11 — lint: Validate compact knowledge

All 41 pages indexed; page/heading links and approved-scope/evidence checks pass.
Five documentation-boundary tests, version sync and whitespace pass. Documentation
only; no acoustic/runtime/media qualification rerun. Raw and local evidence untouched.

## 2026-09-15 — update: Trial preparation and selected-route NLOS

Completed bounded Phase 08 preparation and the RTX pilot. Integrated native Steam probes, route timing and immutable visibility; corrected coverage/weight/ordinary-opening failures. Step 2 closes selected-route transport with explicit probe-pressure limits, not calibrated diffraction or full-room admission.

## 2026-09-15 — experiment: Persistent PRA pressure and diagnostic failures

Implemented optional native shared pressure and corrected banded material phase. Rotating-mirror coherence and conditioned-cube decay/observation comparisons failed their original criteria. Targeted weak-direct impact evidence supported continued PRA work; no replacement provider was selected.

## 2026-09-16 — experiment: Motion, measurement reliability and bounded AV

Refined head/camera evidence supported PRA retention with rare false association and stratum limits. Corrected WPE conditioning/peak ties, then completed actual-producer C03/C04 confirmations, finite-field follow-ups and bounded room/property checks. Fixed the native door-jamb projection leak. Results and uncertainty are consolidated in [[experiments/geometry-acoustics-admission|admission evidence]].

## 2026-09-16 — update: Step 3 admission with explicit limitations

After a bounded reference-feasibility stop, the user declined a separate room-field reference and accepted full-room moving equivalence as NOT VALIDATED and non-blocking. Step 3 is PASS with cube/mirror diagnostic limits; combined producer and complete AV/mobile remain open. No new experiment accompanied this decision.

## 2026-09-16 — update: Consumer-safe workspace and wiki cleanup

The user explicitly authorized this one-time condensation of existing log entries. Current contracts, future requirements and decisive results now have separate canonical owners. Historical tracked detail remains at `9395b1c`; concluded ignored outputs are removed, not archived in Git. Retain future R10 inputs/controls, ONR regeneration/deliveries and active Lab parity recordings. Removed historical route re-exports and duplicate stream cleanup without changing public interfaces.

## 2026-09-16 — lint: Verify retained workspace and canonical links

All 42 wiki pages are indexed, internal links/anchors and active source references resolve.
Host checks pass (668 unit/contract, 336 integration, 58 release), as do 228 Isaac tests,
optional audio and real RTX Sim/Lab/Kit/NLOS gates. Retained inputs pass 104 episode
checks, 131 USD compositions, visibility, producer lifecycle and independent quadrature.
ONR frame metadata is migrated locally to v4 with unchanged PCM and observations;
current-source replay and bounded media recomposition validate retained paths.

## 2026-09-19 — update: Step 4 combined native stream

Enabled joint NLOS/diffuse configuration in the existing Geometry producer, retained
component diagnostics and made failed reads discard the environment's partially
advanced state. Thirteen combined controls plus affected native regressions pass
(61 native tests total); 14 convolution/route unit tests pass. Live Sim/Lab
qualification and Step 4 admission are pending. Defaults and public schemas are unchanged.

## 2026-09-19 — update: Combined Sim and Lab runtime controls

Extended existing smoke entrypoints with explicit combined modes. Actual RTX 4090
Sim passes dynamic door, tails and reset; square Lab passes two-environment
same-PCM scalar/CUDA parity, non-consuming reads, partial-reset continuation,
independent native replay and reordered/+60 dB-neighbour observation isolation.
Measurements and task-fidelity boundaries are recorded in the admission page.

## 2026-09-19 — update: Close Phase 08 Step 4

Step 4 is PASS for combined streaming and integration. Raised CUDA Lab also passes
same-PCM parity and lifecycle/isolation, with maximum angular difference 0.00854°
and independent PCM error below 2.8e-9. Updated sequence, status, technical contract
and admission evidence; Step 5 AV usefulness is next. Full-room moving equivalence
and the existing cube/mirror/NLOS limits remain explicit. No defaults, public
schemas, provider physics or acceptance budgets changed.

## 2026-09-19 — lint: Verify Step 4 closeout

All 42 wiki pages are indexed; internal links/anchors and new runtime/test
references resolve. Raw material is unchanged. `make check` passes (668/336/58),
61 affected native tests and 14 targeted stream/route tests pass, and actual RTX
Sim plus square/raised Lab gates pass. Documentation preserves component limits
and leaves Steps 5–8 open; whitespace and repository lint checks pass.

## 2026-09-19 — update: Complete 08.2 sensor propagation and integration

08.2 is complete within its documented acoustic and integration bounds. Current
status, phase plans, SDK criteria, fixture documentation and README agree on the
implemented producer, recorded native/RTX evidence and remaining limitations.
08.3 operating workflow, diagnostics and runtime/distribution closeout are next.

## 2026-09-19 — lint: Verify 08.2 documentation closeout

All 42 wiki pages are indexed; internal links/anchors and affected source references
resolve. Active documentation consistently identifies 08.3 as the next phase of
work. Existing Step 4 native, Sim/Lab and host-check records were inspected; no
runtime tests were rerun for these documentation-only changes. Raw material and
runtime code are unchanged; whitespace checks pass.


## 2026-09-19 — update: Implement Geometry operating integration

Documented controller-owned prepared scenes, Python/Kit native configuration,
capability checks, settings persistence and separate simulation diagnostics.
NLOS coverage now preserves the historical block snapshot. Runtime, cost and
clean-source distribution closeout remain explicitly in progress.

## 2026-09-19 — lint: Check operating integration documentation

All canonical pages remain indexed and internal wikilink targets resolve. Updated
source/API references exist; raw material is unchanged. Host checks pass
(677 unit/contract, 336 integration, 58 release); the focused controller/native
checks preserve configuration, session lifetime and historical diagnostics.

## 2026-09-19 — experiment: Qualify Geometry operating runtimes

Actual RTX Sim, Kit and one/two-environment Lab checks pass, including combined
screen motion, stop/tail, lifecycle and scalar/CUDA parity. The admission page
records bounded timing, preparation, reset and allocator/process memory; these
results do not qualify complex rooms or real-time performance. The native test
suite also passes after rerunning the CUDA cases with host GPU access.

## 2026-09-19 — lint: Verify operating runtime evidence

Checked current reports against the canonical measurements and retained limits.
No new wiki page or link target was introduced. Updated smoke sources pass lint,
whitespace checks and the full host check suite; raw evidence is unchanged.

## 2026-09-19 — update: Close bounded Phase 08

08.3 and Phase 08 close after passing host/native/CUDA and actual Sim/Lab/Kit
operating gates. Clean-source sdist, derived wheel and Kit audits pass; the
extracted Kit archive passes dependency-origin, Extension Manager, combined
Geometry and shutdown checks. Updated phase, R10, status and release guidance,
including preservation of native builds instead of whole-build cleanup. Existing
acoustic admission limits and downstream media gates are unchanged. No push or
publication was performed.

## 2026-09-19 — lint: Verify Phase 08 closure

All 42 wiki pages are indexed; page and heading links resolve. Closure claims
match host/native/runtime reports and artifact audits, and raw inputs remain
unchanged. Ruff, whitespace and all 58 release tests pass. Historical acoustic
limits remain separate from operating and distribution completion.

## 2026-09-19 — update: Deliver Hospital ONR occlusion video

Added the 30 s Video 4 delivery to the canonical ONR topic, status and index.
The local production uses combined Geometry, the original Hospital door, observed
pointing, camera FOV and separate geometric references. The 600-window recording
shows 14.32 dB front-channel loss and coherent recovery; both full movies pass
media checks and playback. Documented the verified pose-export recovery, nominal
materials and 50 ms scene sampling without extending acoustic admission. Videos
1–3 and the public SDK remain unchanged; no push was performed.

## 2026-09-19 — lint: Verify ONR Video 4 documentation

All 42 wiki pages remain indexed and internal page/heading links resolve.
Claims match the 600-window capture, checked GPU pose replay, final media reports
and complete playback. Local production scripts pass Ruff; Markdown whitespace
checks pass. Immutable raw material and approved deliveries are unchanged.

## 2026-09-19 — update: Stabilize ONR Video 4 activity and standardize camera FOV

Documented the 2.5 s activity release requested during user review and the mandatory
head-camera FOV for every new or revised video. Video 4 was recomposed from the
existing recording and renders: display transitions fall from 53 to one; all 900
RMS and direction states remain unchanged. Compass styling stays independent of
known door geometry. Master, 1080p movie, preview and delivery notes were updated
locally; recordings, approved Videos 1–3 and the public SDK remain unchanged.

## 2026-09-19 — lint: Verify ONR activity refinement documentation

All 42 wiki pages are indexed and internal links resolve. Ruff and Markdown
whitespace checks pass. The documented 2.5 s hold matches all 900 display states;
RMS/direction parity, silence-tail expiry, full media decode and AAC checks pass.

## 2026-09-19 — update: Standardize ONR direct-path references

Extended the shared production standard with Video 4's green/orange/red geometric
path colors, synchronized blockage checks and restrained distant-source framing.
Clarified scene-known endpoints, ambiguous source/event associations and causal
activity timing; geometric paths do not certify audio quality or source recognition.
This documentation update does not regenerate approved media or change the SDK.

## 2026-09-19 — lint: Verify ONR direct-path standard

All 42 wiki pages remain indexed and internal links resolve. Markdown whitespace
checks pass; the documented color roles match the local Video 4 compositor.

## 2026-09-19 — update: ONR Videos 1–3 reference copies

Produced separate 1440p copies with the Video 4 FOV and geometric path styling,
preserving approved edits and copying their AAC streams unchanged. Video 2 paths
appear only in the right audio-guided panel; the visual-only panel retains FOV.
All three complete decodes, frame counts, durations and audio identity checks pass.
Existing movie hashes are unchanged, and exactly three new 1440p MP4s were added.
Local production code, geometry checks and validation remain under `local/onr/`.

## 2026-09-19 — lint: Check ONR revision documentation

The existing canonical production page records the new copy names and limits;
no wiki pages or links were added. Markdown whitespace and local Python checks pass.

## 2026-09-19 — update: Simplify ONR reference overlays

Recomposed the three 1440p revision copies with green direct-path references for
their unoccluded model. Removed blockage wording and sized legend backing to the
text plus 10 px per side. Video 2 retains paths only in its audio-guided panel.
Representative frames, full decoding, durations and unchanged AAC streams pass;
original deliveries remain intact. Previous revision copies are retained locally.

## 2026-09-19 — lint: Verify ONR overlay correction notes

Updated the existing production page without adding pages or links. Local Python
checks and Markdown whitespace checks pass.

## 2026-09-19 — update: Shared ONR legend and source-reference continuity

Documented exact legend wording for direct-path and occlusion examples, typography,
measured width, padding, placement and omission in first-person views. Revised
compositors share one legend helper. Added a separate 1440p Video 4 copy using the
common layout, preserving its occlusion colors and original AAC stream.
Video 1 now follows the complete source events in external shots: all 273 active
external frames contain the path; first-person views omit it. The observed compass,
activity indicator and RMS are unchanged. Full media checks pass for all four
revision copies, with original movies and audio preserved and no new 1080p files.

## 2026-09-19 — lint: Verify common legend documentation

Updated the canonical production page and its existing index entry; no pages or
links were added. The index target exists and Markdown whitespace checks pass.
Focused Python checks pass; Video 4's pre-existing long lines were excluded from
its style check. Native dimensions and representative external/POV frames were
verified against the delivered files.

## 2026-09-19 — update: ONR Video 5 warehouse preflight

Documented the local two-source warehouse production, unchanged current-event sensor display, combined Geometry configuration and bounded acoustic approximations. Individual/mixture native controls pass; the user confirmed preliminary mixture audibility. Full GPU capture and media checks remain in progress. No public SDK changes.

## 2026-09-19 — lint: Verify Video 5 preflight documentation

All wiki links resolve and pages remain indexed. Documentation matches the local configuration and stored probe results; Markdown whitespace and focused local Python checks pass. Protected raw material is unchanged.

## 2026-09-19 — update: Deliver ONR Video 5

Completed the 30-second warehouse capture, preview and 1440p/1080p production. All 220 stable windows meet the correct-set gate; recording replay, causal display, GPU pose hold, full media decoding and browser playback pass. Documented timing, levels and bounded Geometry assumptions. Preliminary mixture listening is user-confirmed; full-video subjective listening remains pending.

## 2026-09-19 — lint: Verify Video 5 delivery documentation

All 42 wiki pages resolve and remain indexed. Canonical claims match the final capture and media reports; focused local Python lint and Markdown whitespace checks pass. Only ONR documentation is tracked in this change; protected raw material and public SDK remain unchanged.

## 2026-09-20 — update: Revise ONR Video 5 presentation and pointing

Moved RMS above the lower-right compass, ordered current bearings consistently, unified below-floor RMS labels and moved machine details to their onsets. A new GPU/Geometry capture turns toward the sole remaining observed direction, preserving the sensor and source signals. Revised recordings and encodes pass their scene/media gates; the user approved the original soundtrack. Previous delivery remains preserved.

## 2026-09-20 — lint: Verify revised Video 5 evidence

All 42 wiki pages resolve and remain indexed; whitespace and focused local Python checks pass. Verified both encodes, full playback, exact audio preservation through 20.8 s and all current displayed observations. Documentation explicitly separates 201/201 stable-window passes from the 76.7% result over 22–25 s including rotation, below the earlier fixed-pose threshold. No public SDK or protected raw files changed.

## 2026-09-21 — update: Deliver ONR Video 6 material comparison

Completed the 40-second Garage reflective/absorptive film with explicitly assigned wall materials, unchanged current sensor, identical source recordings and one front-microphone gain. The user rejected the initial subtle pilot and approved the full-wall A/B contrast. Documented independent captures, denser/longer controls, replay, causal instruments, paired geometry/cameras and complete 1440p media checks. Prior videos and original assets remain preserved; no public SDK changes.

## 2026-09-21 — lint: Verify Video 6 documentation and delivery

All 42 wiki pages resolve and remain indexed; Markdown whitespace and focused local Python checks pass. Canonical claims match the saved A/B/control and final media reports. The local generator's fresh preparation and verification paths pass. Only ONR documentation is tracked; protected raw material, SDK interfaces and previous movies are unchanged.

## 2026-09-21 — update: Clarify Video 6 materials and listening comparison

Revised the source-activity card with plain-English material names, catalog absorption explicitly qualified at 1 kHz, and concise listening cues. Replaced the blue tile-like lining with dark perforated metal-faced acoustic cassettes and added a restrained matched-view dissolve plus a material detail during the existing silent transition. Preserved the original delivery, approved soundtrack, event times and current sensor observations; updated local regeneration defaults and method.

## 2026-09-21 — lint: Verify Video 6 presentation revision

All 42 wiki pages resolve and remain indexed; whitespace and focused local Python checks pass. Revised media fully decodes to 1,200 synchronized 1440p frames. The original files retain their hashes, the reference WAV and encoded AAC stream are byte-identical, and all 1,200 display rows match the approved capture. Paired acoustic geometry and the frozen rig remain unchanged. Documentation records the frequency-specific meaning of the displayed percentages.

## 2026-10-02 — update: Correct guided recording channel order

The Isaac Sim and Kit topic now explains that guided recording declares the captured producer order, preserving PCM rows and microphone geometry for USD-discovered arrays. Dataset recording remains independent of Sensor WAV export, and recorder contract checks still reject later incompatible channel changes.

## 2026-10-02 — lint: Verify guided quad recording repair

All 42 wiki pages resolve and remain indexed; Git whitespace, Ruff and version checks pass. The required repository gate passes 677 unit/contract, 341 integration and 58 release tests. Coordinated live Kit GUI checks with Sensor WAV enabled and disabled each accepted 28 quad frames, zero drops and three shards, then finalized and exported with zero validation errors. Independent checks preserved all PCM samples and microphone ID/geometry correspondence; existing USD diagnostic portability warnings remain.

## 2026-10-03 — update: Correct Replicator stop lifecycle

The Isaac Sim and Kit topic now documents that Stop disables frame dispatch before writer teardown while preserving output settings and final artifacts. Start enables dispatch only after successful initialization; failed lifecycle actions leave it disabled. Sensor acquisition and timeline operation remain independent.

## 2026-10-03 — lint: Verify Replicator lifecycle repair

All 42 wiki pages resolve and remain indexed; Ruff, version synchronization and Git whitespace pass. The repository gate passes 677 unit/contract, 348 integration and 58 release tests, including 11 Replicator cases. Coordinated actual Kit GUI start/flush/stop/restart and repeated-stop cycles retain 23 and 20 writes while sensor and timeline continue; timestamps advance 1,500 ms after each stop with Enable cleared and no additional writes. Authentic screenshots and final manifests/JSONL were independently inspected. Existing quad channel-order source and tests remain unchanged.

## 2026-10-08 — update: Remove unused runtime surfaces

Removed unused numerical helpers, test-only wrappers and the stale fidelity prose catalog. Capability discovery remains authoritative for runtime availability; model limits remain in canonical topics. Consolidated identical calibration/dataset ID, digest and relative-path validation while preserving serialized contracts and the downstream active_sources consumer.

## 2026-10-08 — update: Consolidate USD attribute access

Production Isaac/Kit helpers now share USD attribute methods instead of fake-object fields. Host fakes implement those methods; the demo appearance check moved to the real USD lane. Host unit/contract/integration checks pass 1,018 cases, and the supported Isaac interpreter passes 79 focused schema, pose, cache, occlusion and geometry checks.

## 2026-10-08 — update: Make Kit configuration application transactional

Shared scalar field definitions now drive import and export. All parsing completes before closing the live session or changing UI state; malformed late fields preserve the current session. Guided presets use the same validated binding shape. Configuration, guided recording, headless workflow, recorder/recovery, replay and codec checks pass 83 focused cases.

## 2026-10-08 — update: Focus tests, runtime tools and documentation

Split the Kit gate by scenario under one entrypoint, removed duplicated UI inventories and unused fake widget trees, and limited Markdown checks to maintained paths. The source Kit gate passes all 39 workflow steps, including Geometry, audio, screenshots and teardown. The README and changelogs distinguish unreleased 3.0 from published 2.0; the Kit topic now keeps current behavior rather than duplicate operational chronology.

## 2026-10-08 — update: Remove obsolete local review outputs

Removed prior cleanup outputs, superseded extracted R10/DOA packages and unused candidate/repeat/trace provider binaries after checking consumers. Reclaimed 3,131,875,328 allocated file bytes (2.92 GiB); selected providers and their source/build trees, wheelhouse, ONR originals/deliveries/regeneration inputs, Lab reference recordings and R10 inputs remain. Decisive experimental results and failure limits remain in their canonical pages; raw sources are untouched.

## 2026-10-08 — lint: Verify maintenance closeout

All 42 wiki pages remain indexed and links resolve. Host checks pass 672 unit/contract, 348 integration and 56 release cases; supported Isaac checks pass 251 cases. Actual RTX Sim, combined two-environment Lab/reference and source Kit pass. SquadBot's 17 focused consumer checks and preserved ONR Video 6 replay/display checks pass. Clean committed-source sdist, derived wheel and Kit archive audits pass; 3.0 remains unreleased, with no tag or package publication.

## 2026-10-08 — update: Locate consumer audio readiness in the SDK

Moved the SDK portion of SquadBot Phase 7 into
[[implementation_phases/squadbot-audio-runtime-readiness|one canonical plan]].
Quality, operating-envelope and runtime-performance work live here; dependency
adoption, application adapters and task scheduling remain downstream. Existing
SDK Phase 07 numbering and runtime status are unchanged.

## 2026-10-08 — lint: Verify relocated readiness plan

The three documentation-boundary checks pass: wiki index coverage, internal
wikilinks and maintained Markdown links. Git whitespace checks pass. This is
planning relocation only; no runtime or acoustic qualification was performed.

## 2026-10-08 — update: Complete SDK readiness 7.1 assessment

Extended received-PCM evaluation without changing runtime perception or public
contracts. The 18-episode motion/room/competition screen passes paired CUDA
preservation but exposes insufficient rotating-receiver quality. The phase and
[[experiments/consumer-audio-operating-envelope|assessment]] retain the measured
fixed-receiver profile, causal onset results and dynamic limitations. Added
consumer migration guidance and corrected stale frame-version/provenance prose.
Host, complete Isaac and actual Sim/Lab gates pass; 7.2 remains planned.

## 2026-10-08 — lint: Verify readiness evidence and migration

All canonical pages remain indexed and internal/maintained Markdown links
resolve. Host checks pass 672 unit/contract, 352 integration and 56 release
cases; 251 actual-runtime Isaac cases and live Sim/Lab pass. Dynamic and
stationary paired reports pass their declared gates; angular accuracy, onset
response and deferred 7.2 performance remain separate. Whitespace checks pass;
raw inputs and pre-existing local material are unchanged.

## 2026-10-08 — update: Correct received-direction matching

Threshold-aware assignments maximize valid pair count before total angle.
Rescored historical directions in a separate report; competing-voice partial
matches and angular p95 change, while complete-set success remains unchanged.
Eight focused scoring tests and whitespace/lint checks pass.

## 2026-10-08 — update: Make localization context explicit

Scalar and both Lab bindings now select a bounded causal localization context;
750 ms defaults and single-event ambiguity roles remain unchanged. Documented
context/readiness versus lag/compute separation and the 250 ms selection rationale.
Independent dynamic validation remains a separate gate.

## 2026-10-08 — lint: Validate selectable-context SDK milestone

Host checks pass 681 unit/contract, 356 integration and 56 release cases;
256 supported-runtime Isaac cases pass. The live 250 ms Lab path preserves
scalar events, tensor contracts and partial reset at 60 Hz acquisition/10 Hz
observations. Lint/whitespace pass. Replay/quality qualification remains separate.
