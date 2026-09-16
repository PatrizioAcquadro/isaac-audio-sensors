# ONR Video Production

## Maintained production

The local generator maintains the original nine-video catalog, the approved final videos 1 and 2, and the completed outdoor Video 3. Final deliveries remain `evidence/onr_demo/`, `evidence/onr_video1_final/`, `evidence/onr_video2/` and `evidence/onr_video3/`. The complete original catalog and both corrected deliveries are preserved. Video 2 now uses sequential perspectives: a 16-second third-person comparison followed by the same run replayed from the robot cameras, for a 32-second edit.

Production source now lives in ignored `local/onr/`, separate from disposable build outputs and the public SDK. Its README owns commands, runtime requirements and workspace selection. `run.py` provides prepare, capture, render, compose and verify stages. Common Office setup, recorded-pose replay, causal instruments and FFmpeg composition are shared. The catalog uses the current sibling SquadBot consumer; retired script copies, probing workers and the duplicated downstream snapshot are not maintained.

The series demonstrates generic audio sensing and controlled downstream camera pointing. Sensor observations, scene references and downstream behavior remain distinct. It makes no navigation, learned recognition or field-readiness claim. Historical unsuccessful video edits are available through the earlier documentation in Git; only final production paths remain active.

## Shared Production Standard

- Cinematic minimal presentation: Nimbus Sans Regular/Bold, white and neutral gray, small charcoal backing only where needed. US English throughout. Show a short title, audio/view state, and useful direction information. Remove robot-name banners, demo clock, decorative microphone waveform, large information bars, and the editorial direction radar. Do not use generated raster art.
- Use the sensor GUI's actual compass renderer and RMS view-models, driven by synchronized observations. Show the compass during events; use a brief RMS detail when helpful. Apply causal presentation smoothing, label the latest smoothed estimate, and expire stale directions. Preserve the unfiltered observations and their missing estimates. Camera FOV and bearing overlays, when used, derive from actual transforms; ray length is not estimated range.
- Mix actual robot-camera views, third-person rear/over-shoulder views, oblique room views, and useful details. Motivate cuts by the action; retain spatial and temporal continuity. Keep the robot's response prominent when demonstrating sound-driven behavior; source motion should remain understandable alongside visible head/torso reactions. Film cameras do not change the microphone soundtrack or hide sensor failures.
- Prefer complete, furnished, existing environments relevant to SquadBot building/urban exploration. Inspect materials, scale, furnishings, light, and camera framing before accepting an environment. Replace an inadequate candidate rather than constructing another sparse room. Reuse of a room or prop is optional; vary settings, sources, and cinematography across the series.
- Associate emission with the relevant scene object. A small synchronized pulse may identify the emitter as a scene reference, separately from detection. Use a loudspeaker model only for a loudspeaker; it is not a generic microphone or universal source icon.
- Use natural, appropriately licensed sound recordings and restrained ambience. Avoid repeated game-voice snippets and harsh synthetic noise. No music. The soundtrack is the observed microphone signal with one constant presentation gain; camera cuts do not alter it.
- Keep shared styling/instruments separate from per-video scene, source, and shot choices. Production remains outside the public SDK; no new public API is planned.

## Video 1 Decisions

The furnished private office in NVIDIA Office passed the user's review. Preserve its desk, chairs, cabinets, blinds, artwork, and layout. Close the existing door. Place the robot beside the blinds at `(-23.08, 13.25)` m, on the opposite side from the first review, following the user's marked floor location. The base faces 25°; it stays fixed. Keep enough clearance for the full body and grippers.

Use **Alex V2 full body**, replacing the Purdue torso used in the first review. The production-only assembly combines the sibling Alex V2 URDF with both WSG32/UMI assets. The nominal circular ReSpeaker XVF3800 geometry has four microphones at 35 mm radius; rendered and sensing coordinates agree. This is nominal geometry, not measured calibration. GPU validation covers articulation and sensor mounting; the gripper attachment is a demo assembly, not grasp or hardware mount qualification.

The actual head camera retains its URDF mount. A fixed `NECK_Y = -0.12` rad posture lifts its view by about 6.9° relative to the neutral neck. The camera has a 65° horizontal FOV and explicit 16:9 aperture. Rear framing is wider and aimed lower to include the head and shoulders. External corner, rear, side, and detail cameras supplement actual robot-camera shots.

The 40-second sequence is context → door knocks → telephone → radio → visual conclusion, at 30 fps. The phone sits on the existing desk. The radio sits on the filing cabinet, facing the robot; the existing paper trays slide back on the same cabinet to make space. The door source is on the room-facing closed panel. These choices keep objects visible from the marked robot position. They do not prescribe the settings or props for later videos.

Sources emit sequentially with quiet intervals. Observed directions command `SPINE_Z` and `NECK_Z`; source truth does not command the robot. The radio uses an unspliced, more continuous eight-second passage from the same CC0 recording, 82.5–90.5 s. Source auditions remain separate from microphone playback. The soundtrack is the recorded front microphone with one constant gain across all shots.

Presentation uses the actual SDK compass renderer and RMS view models. A causal 0.20 s circular filter smooths direction. After the first resolved direction, the latest estimate remains visible for three seconds from its measurement timestamp; it is unavailable before that first estimate and at or beyond expiry. The SDK dial and cardinal ticks stay visible throughout each panel window, including unavailable periods; only the needle and numeric estimate disappear on expiry. Activity release is 0.45 s, RMS smoothing is 0.18 s, and camera-view status debounce is 0.12 s. These filters affect display only. The title remains for 5.2 seconds, two seconds longer than the earlier edit. The RMS detail lasts 7.25–10.25 s, one second longer than the first review. The door marker adds an emission-driven ripple; all source markers remain scene references, separate from detection.

The video adapter converts the recorded USD rig's +Y-left azimuth to the SDK widget's clockwise/right-positive convention by negating the local bearing. The earlier full-video overlay mirrored left and right; the sensor observations and pointing controller were already internally consistent and are unchanged. The needle shows the estimated continuous bearing, not the camera heading or a sector index. Zero/up means the robot/camera front, marked “Front”; right is positive and left is negative. As the robot turns toward a fixed source, its relative bearing normally approaches zero. The camera mount has the same forward heading as the array, with the previously documented pitch offset.

## Corrected Production Evidence — September 8, 2026

The superseded Purdue/open-door review is summarized in `evidence/onr_history/`. Its disposable media and production copies are retired; the approved full-body delivery and original source assets remain.

The corrected sensor execution is `local/onr/data/video1/run_v6/`. Technical sensor and pose checks pass on the RTX 4090 run: 800 audio windows, 1,200 finite pose frames, fixed base, both yaw joints active, and all 800 microphone windows reloaded sample-identically through `SessionDataset`. Initial quiet produces no detections. Every source point enters the actual camera FOV. Fresh frames were inspected for the closed door, phone, radio, and corrected position.

| Event | Emitting windows | Resolved direction windows | Median error when resolved | First target in camera FOV |
| --- | --- | --- | --- | --- |
| Door, onset 4 s | 84 | 16 | 0.74° | 5.70 s |
| Telephone, onset 15 s | 140 | 38 | 0.29° | 15.05 s |
| Radio, onset 27 s | 160 | 123 | 0.93° | 28.95 s |

The display uses only observations already available at each rendered time. Its activity transitions drop from 38 to 14 over the complete run. Intermittent direction measurements remain missing in the recording; the presentation explicitly shows a short-lived, smoothed latest estimate, then unavailable after three seconds. The first telephone FOV time is a geometric membership result, not a claim of visual recognition or a newly completed pointing action.

This is a direct-path free-field sensing/pointing example. The acoustic backend runs on CPU; articulation and RTX rendering run on GPU. Furnishings do not contribute reflections or material acoustics. The base is fixed with gravity and contact disabled, so this run does not validate navigation, balance, grasping, room acoustics, or physical readiness. Camera FOV membership is a geometric reference, not recognition or an occlusion test.

The corrected delivery is `evidence/onr_video1_final/index.html`, with `master_1440p.mp4`, `presentation_1080p.mp4`, a 12-second opening excerpt, three representative frames, audio credits, method, and validation report. Both complete encodes decode to 1,200 frames at 30 fps with exactly 40-second audio/video durations. The AAC peak is 0.7413, without clipping. The 40-second contact sheets and representative full-resolution frames were inspected; browser playback reached the end with audio enabled and no media error. The user approved that full edit and subsequently requested the compass convention/retention correction and longer title. The presentation revision reuses the same measured execution, clean render, soundtrack, and camera cuts. Geometry checks independently verify the corrected needle against camera-relative source directions: the first door estimate is +56° right versus a +55.33° scene reference, the phone is −22° left versus −21.62°, and the radio is −82° left versus −81.69°. Initial, held, and expired states retain the dial; expiry is tested at the three-second boundary. See `local/onr/data/video1/compass_validation.json`. Original videos, including 6 and 9, remain preserved.

## Video 2 — Calibrated Supplied Audio

The user approved the continuous microphone sound and authorized activity-threshold calibration. The first rerun at -66 dBFS produced a 4.10 s cue and a 6.75 s arrival versus the baseline's 8.00 s. The user then requested a larger visible advantage, explicitly allowing removal of the quiet audio lead-in and greater sensitivity.

The final source removes only the first quiet second of `DoorCreaking.mp3`; pitch and playback speed are unchanged. The existing downmix, resampling, constant gain and edge fades remain. `DoorOpening.mp3` is unused. The original user files remain intact. Opening still begins at video time 3 s; the supplied final contact now aligns with the animated end stop at 8.31 s. Both runs share this animation.

The activity threshold is fixed at -70 dBFS throughout the run. It is a documented scene-specific setting, not an event-timed trigger or a noise-robustness qualification. The actual SDK direction estimator still supplies every audio pointing goal. In `local/onr/data/video2/user_audio_v3/`, the first measured cue is at 3.10 s and audio arrival is at 5.15 s. Visual arrival remains at 8.00 s: 2.15 s versus 5.00 s after opening, an illustrated advantage of 2.85 s. The baseline's full pose/command arrays are identical to the earlier pilot, and both branches retain the same 35-degree-per-second command limit.

The pilot has 104 resolved direction windows, zero pre-event detections and 320 sample-identical replayed microphone blocks. Actual camera images confirm a clear opening in the audio branch while the visual-only branch continues its scan. The causal pre-roll correction supplies the same continuous signal to perception, recording and presentation. The prominent vertical divider and synchronized SDK direction panels remain in both audio-guided views. The initial four-view `evidence/onr_video2/` delivery contained 1440p and 1080p movies, both 16 s at 30 fps. Both encodes fully decode, browser playback reaches the end with audio enabled, and complete contact-sheet review passes. The AAC soundtrack has 47.07 dB signal-to-codec-error ratio, a 0.739 peak and no periodic zero gaps. All 480 direction-panel overlay states match across the two audio views. The method declares source trimming, fixed threshold, scripted arrival and the direct-path pre-roll limitation.

## Video 2 — Sequential Perspectives

The user approved the behavior and audio, then requested two views at a time. The 32-second edit shows the matched third-person views during 0–16 s and replays the same source run from both robot cameras during 16–32 s. The second segment is labeled “Robot camera · Same run replayed.” This is an editorial replay, not another experiment or a continuous 32-second task execution.

Following the user's correction, the images fill the full frame with no dark upper/lower bands. A fixed lateral 640×720 crop from each approved source is enlarged without stretching to a 1280×1440 panel. Both modes use the same crop offset: x=320 for third-person, x=480 for robot-camera views. Mode names, status and the single audio-side SDK compass overlay the images. This editorial crop does not alter sensor FOV or recorded arrival conditions. A three-pixel vertical line separates modes; the horizontal divider is removed. Each source timestamp produces the same causal compass state in either perspective, and the same 16-second microphone soundtrack repeats sample-identically with the view change. The approved source, measurements, motion and 2.85-second illustrative advantage remain unchanged. Only the maintained local compositor, its media checks and documentation are revised; no new GPU acquisition or render is needed.

Both 1440p and 1080p encodes fully decode to 960 frames at 30 fps, with matching 32-second audio/video durations. Source-frame comparisons confirm the perspective order and synchronization. Both complete contact sheets and fullscreen arrival images were inspected; 1080p browser playback reached the end with audio enabled and no media error. The AAC signal-to-codec-error ratio is 47.33 dB, its peak is 0.739, and all 480 causal instrument states match across the two perspectives.

## Video 3 — Outdoor Moving Source

The user accepted the central excerpt's waterfront street, truck and camera treatment, then requested a silent establishing view followed by a close view of the first sound-driven turn. The completed edit is 23 s: context at 0–2 s, close rear view at 2–6.5 s, approach at 6.5–12 s, uninterrupted pass at 12–19 s and actual robot camera at 19–23 s. The user approved the complete video and requested a closer, robot-centered pass shot. The 12–19 s camera now follows a gentle orbit with a 4 m horizontal radius around Alex, keeping the full robot central and head/torso visible through the late pass; source, recorded robot motion and cut times are unchanged. The approved full-body Alex V2, WSG32/UMI, nominal ReSpeaker geometry, fixed base and head-camera mount are retained.

The environment is the complete [NVIDIA City Demo Pack](https://docs.omniverse.nvidia.com/usd/latest/usd_content_samples/downloadable_packs.html), using its existing waterfront road, sidewalks and buildings. The vehicle is [Truck by ROY](https://sketchfab.com/3d-models/truck-eda924f23ba04cd5b1e5160abf2320fa), CC Attribution, converted to USD and uniformly scaled by 0.89: body width 2.53 m, mirror span 3.07 m, length 14.16 m and height 4.02 m. Original geometry and materials are retained; supplied wheels rotate with the scripted motion. The city is converted from centimeters to meters and rigidly placed around the unchanged sensing rig. The existing CC0 Sunflowers HDR provides the sky. Materials, natural scale, framing and the full rendered sequence were inspected. All 1,848 sampled wheel locations lie on actual road faces. The small stylized industrial-road candidate was rejected. Licenses, sources and modifications are included in the delivery credits.

The source is silent and stationary for two seconds, then follows one straight path at 8 m/s (28.8 km/h), with 12 m lateral clearance and closest approach at 14.5 s. This adds the requested introduction by shortening the distant ending, without accelerating the accepted pass. Vehicle driving dynamics and acceleration are not simulated. The source prim's origin is the engine position; native source/array attributes and rendered microphone geometry agree with the recorded scene.

The original natural recording changed engines near 8.5 s. Following the user's listening feedback, the source retains only 0.50–7.94 s of qubodup's CC0 [Truck Engine Idle Loops](https://freesound.org/people/qubodup/sounds/187564/) public high-quality preview, repeated with an 80 ms matched crossfade. The user accepted this continuous engine and clearer crescendo. No pitch adjustment or source-level normalization is applied. The final soundtrack is the recorded front microphone with one constant gain across the complete edit; it contains the real silent introduction. No music, camera-dependent gain or editorial crescendo is added.

The RTX 4090 run uses actual CUDA/PhysX articulation and the current continuous direct-path backend, without the Video 2 adapter. Acoustics and maintained 48 kHz single-event DOA run on CPU. A constant -78 dBFS activity threshold, calibrated for this quiet scene, allows the distant initial cue. There is no added ambient interference. This threshold is not a field-noise or detection-range qualification. Source truth only scores directions and camera membership; it never commands the robot. There are no detections during the silent introduction and no joint motion before the first direction at 2.50 s. The source starts outside the actual camera FOV and enters at 4.10 s, remaining inside through the ending.

The original ±36 m spatial gate occupies 10–19 s. Phase times scale with speed, preserving the tested approach/pass/recede geometry. All 460 microphone windows reload sample-identically through `SessionDataset`; full body positions, quaternions, joints, array and camera transforms are saved for faithful RTX replay.

| Scored phase | Resolved windows | 95th-percentile current-world bearing error |
| --- | --- | --- |
| Approach, 10.75–13.75 s | 100% | 3.13° |
| Pass, 13.75–15.25 s | 100% | 4.22° |
| Recede, 15.25–19 s | 100% | 2.07° |

No direction is missing in the scored interval. Availability is 89.3% across all 23 s, or 97.9% after source onset, including propagation and acquisition time. The 49 unavailable windows remain in the recording. The base is fixed and both yaw joints remain within the established validation tolerances. The initial received arrival is 2.29358 s versus 2.29360 s predicted; no exact zero samples follow it. Matched-emission level error is 0.092 dB at the 95th percentile. Measured frequency ratios are 1.02140 at 11.5 s and 0.97975 at 17.5 s, consistent with retarded geometry. The level rises by 17.86 dB from the first audible second to closest approach.

The local generator reuses the actual SDK compass renderer and shared causal presentation filters. The compass appears from 2 s. The user clarified that Video 3 should retain RMS whenever “Sound detected” is active. Its RMS windows now follow that same causal activity state, including the established 0.45 s release, instead of editorial time ranges. The actual per-microphone levels use shared 0.18 s display smoothing and a fixed -90 to 0 dBFS scale. RMS shows short-window received signal level, not direction confidence or Doppler frequency shift; dBFS is relative to digital full scale, not calibrated sound pressure. Other videos retain their existing RMS presentation. The initial subtitle reads “Doppler · Received level · Sound-direction following” in Nimbus Sans, with the title's existing 5.2-second timing. “Latest estimate · smoothed,” missing estimates and three-second expiry remain intact. Every one of the 690 display timestamps passes the causality/expiry checks and RMS/detection visibility agreement; RMS is visible in 615 frames, from 2.50 s through the end. This demonstrates sound-direction following, not recognition or persistent identity. Visual scenery does not contribute simulated reflections, occlusions or material acoustics.

The final recording and clean render are in `local/onr/data/video3_final/`; the maintained scripts are in `local/onr/video3/`. Delivery `evidence/onr_video3/` includes 1440p and 1080p movies, the front-microphone reference, representative images, credits, method and validation reports. Both complete encodes decode to 690 frames at 30 fps with matching 23-second audio/video durations. PCM agrees with the recorded front channel and one constant gain; AAC SNR is 44.67 dB, with peak 0.8495 and no clipping. Complete contact-sheet and full-resolution frame inspection pass. The 1080p browser playback reaches the end with audio enabled and no media error. The user approved the robot-focused pass and motion-effects subtitle, then clarified that RMS should remain visible throughout sound detection. Those presentation changes reuse the same microphone recording, measured execution and accepted Doppler soundtrack. Revised full-resolution frames, the complete contact sheet and 28 quarter-second pass images confirm central robot framing and clear head/torso visibility; full playback and technical checks pass again. The approved `evidence/onr_video3_review/` remains preserved; superseded local auditions were removed.

## Per-Video Checklist

Numbers below follow the user's revised order. Old numbers identify the existing package only.

| New | Video | Existing video | Requested focus | State |
| --- | --- | --- | --- | --- |
| 1 | Basic sensing in a relevant setting | 1 | Sequential sources in useful positions; establish shared quality standard | Corrected delivery complete |
| 2 | With and without audio | 3 | Scripted visual scan versus measured audio guidance during an off-camera door opening | Fullscreen sequential delivery verified; 2.85 s illustrative advantage |
| 3 | Moving source | 4 | Outdoor vehicle; direction following, native instruments and Doppler | Complete 23 s edit verified; approved excerpt and requested silent opening |
| 4 | Occlusion | 2 | Audible attenuation and understandable instrument response | Correctness fixes completed; scene feasibility pending; fuller geometry version after 08.3 |
| 5 | Multiple sources and background | 5 | Distinct concurrent sources and realistic interference; verify pipeline capability | Discuss individually |
| 6 | Materials and acoustic spaces | 6 | Clarify what changes and make the acoustic result understandable | Deferred; design open |
| 7 | Audio–vision link | 7 | Main integration story; show the actual chain clearly | Discuss individually |
| 8 | Dataset | 8 | Better placement of explanations and clearer data workflow | Discuss individually |
| 9 | Simulation and real microphones | 9 | Clarify physical evidence and what can be compared | Deferred; design open |

For each revision: [ ] agree the task and setting; [ ] apply shared standards; [ ] review a short excerpt; [ ] validate behavior and media; [ ] deliver the approved video. Each future video gets its own decisions; this page does not prescribe nine identical scenes or storyboards.

## Remaining ONR deliveries after the R10 profile decision

Readiness checked on 2026-09-11 against the maintained generator, final files and
saved validation reports. The original nine-video catalog exists; “remaining”
means the individually revised deliveries in the current numbering. Videos 1,
2 and 3 have final 1080p/1440p files and passing saved technical reports in their
respective delivery directories. Video 3's current method records the approved
robot-focused pass and RMS behavior. This audit does not re-run decoding or
playback, regenerate media or reopen those approved deliveries.

The user confirms R10 Profile 1 AV attention/search as the priority and Profile 2
mobile audition as its complement. The series therefore demonstrates task-useful
sensing, not exact dynamic-acoustic completeness. This does not change approved
recordings: Video 3's 8 m/s outdoor direct-path case is a separately qualified
bounded demonstration, not proof of an equivalent indoor Geometry domain.
The approved Alex V2 production assembly/pointing is not physical Alex003 mounting
or partner acceptance evidence.

| Revised video | Remaining work | Dependence on Phase 08 and other work |
| --- | --- | --- |
| 4 — Occlusion | Agree the scene; prove audible received-signal change, causal instruments and honest availability; then review an excerpt and produce the revised delivery | A bounded direct-path version can use the maintained occlusion model after its scene gate. Full geometry, meaningful indirect routes and provider diagnostics target admitted 08.2 contributions plus 08.3 operation. No exact asynchronous path-history requirement |
| 5 — Multiple sources/background | Choose distinguishable simultaneous events and relevant interference; qualify actual observed count/direction, missing/extra events and audibility in that scene | The bounded 04.4/07 runtime exists, but does not qualify arbitrary moving/reverberant mixtures. Phase 08 is needed only for geometric/diffuse claims actually shown; Phase 09 for additional evidence-backed noise/variation claims |
| 6 — Materials/acoustic spaces | Agree which physical change is demonstrated and validate its effect on received PCM and instruments; replace any implication that decorative furniture drives the old shoebox | A bounded declared shoebox experiment is possible independently. Geometry-authored material/space claims need the relevant 08.2 qualification and 08.3 workflow; richer randomization or physical-transfer claims belong to 09/separate validation |
| 7 — Audio–vision link | Demonstrate hear → orient → see → link with visible failure/unconfirmed cases; verify the actual consumer chain and distinguish authored/annotated visuals from learned recognition | Highest alignment with Profile 1. It does not require full Phase 08 for a bounded analytic scene, nor automatic completion of Phase 11. Geometry claims require their own admitted domain; no unseen-source truth or visual oracle may silently become an audio estimate |
| 8 — Dataset | Agree a clearer recording/replay/observations-versus-truth story and validate the exact recorded data path; produce the revised media | Existing recording/dataset capability is available. Depends on the producer shown, not all of Phase 08 or completion of policy training |
| 9 — Simulation/real microphones | Agree a defensible comparison using the existing physical evidence, align the compared quantities, and keep known mismatches visible | Requires a suitable bounded physical/sim comparison, not merely a completed Phase 08. Existing recordings do not establish general transfer; no new capture campaign is authorized by this readiness audit |

Phase 08 completion alone does not close these media tasks or approve a scene.
Each remaining video still needs its agreed brief, scenario-specific sensing and
consumer gate, excerpt review, synchronized observed soundtrack/instruments and
full technical/media QA. No new production is performed by this documentation
update. General-purpose SDK work stays separate from local ONR orchestration and
SquadBot semantics.

## Video 4 Readiness and Scope

The requested Video 4 is the revised **Occlusion** video, corresponding to old catalog video 2. Its current brief is audible attenuation with understandable instrument response; the scene and story remain to be agreed individually.

A bounded direct-path version may be feasible with the [[status|completed confidence/occlusion corrections and maintained perceptual reference]]: a real supported obstacle changes the recorded microphone signal, RMS follows that signal, and the direction/activity display remains truthful about availability and errors. It does not inherently require Isaac Lab 07.2 or all of Phase 09. Production still depends on its actual scene and complete sensing/recording path working; completion of a phase alone is insufficient. Solid-collider capture is corrected in its tested domain; remaining perceptual errors and scene-specific feasibility still prevent an automatic readiness claim. The general temporal research pause neither qualifies nor blocks this scene by itself.

For the fuller version with acoustically active scene geometry, doors or openings, reflected/indirect contributions and provider diagnostics, target completion of [[implementation_phases/08-geometry-acoustics-integration|08.3]], within [[implementation_phases/r10-geometry-acoustics-integration|R10's supported limits]]. Phase 09 is needed only for additional claims about evidence-backed noise/material variation or physical transfer. This does not promise general diffraction or physically calibrated wall behavior.

Show actual received audio and observed instruments. If geometric blockage is displayed, label it separately from inferred direction reliability; compass color must not imply that the sensor can identify an obstacle from audio alone. The older catalog's analytic moving-partition intersection is not proof of real PhysX dynamic occlusion. No new Video 4 production is authorized or delivered by this documentation update.

## Existing Videos 6 and 9: Verified Clarifications

Video 6 uses an explicit 12 × 12 × 3.3 m shoebox with reflection order 3, switching absorption from 0.8 to 0.15. The visible furniture does not drive its acoustic model. The original catalog reports a +3.2 dB received-mixture change. This does not demonstrate distinct measured material responses of the rendered objects. Its redesign is undecided.

Video 9 overlays results from 25 existing ReSpeaker takes (5,440 windows) on a separate Alex simulation. The video's soundtrack remains simulated; it is not a real/simulated listening comparison. At the -3 dB source setting, the existing report records activity in 230/234 physical windows versus 0/234 simulated windows. The evidence supports pipeline reuse and a bounded bench comparison, not generally validated acoustic transfer. Its redesign is undecided.

Verified sources: `evidence/onr_demo/METHOD.md`, `catalog.json`, scenario `media_method.json`, and `build/onr_demo/runs/s09/physical_readout.json`. These are local ignored artifacts, not public package dependencies.

## Regeneration and verification

Run `.venv/bin/python local/onr/run.py <catalog|video1|video2|video3> compose` to recompose saved recordings, followed by `verify`. For new acquisition, use `all --work build/onr/<new-run> --out evidence/<new-delivery>`; existing recordings are preserved. Source assets and essential recordings live outside `build/`, so `make clean` cannot delete the maintained generator or its inputs.

GPU acquisition/rendering uses the supported Isaac Lab runtime and actual RTX hardware. Audio uses the existing CPU direct-path or declared shoebox implementation. Video 2's 50 ms source pre-roll is a local direct-path adapter: it holds poses within each audio window and is not a general SDK streaming repair. The same continuous microphone samples feed perception, recording and the soundtrack.

Check recorded-sample replay, event/silence behavior, causal direction expiry, shared panel states, finite poses, camera transforms, full media decoding and audio/video synchronization. Original user MP3s, source licenses and physical recordings remain preserved. Short cleanup previews verify the maintained paths without repeating full historical statistical campaigns; they do not replace the approved final deliveries or their original full-playback review.

References: [[topics/system-architecture|System Architecture]], [[topics/public-contracts-and-recording|Public Contracts and Recording]].

The cleanup migrated 8,780 records in 12 local sessions and their standalone traces
from frame v3 to v4. Only the schema label and required integrity references changed;
original scores, observations, poses, clocks and PCM were preserved. Approved
historical deliveries remain untouched. Fresh production uses the current schema;
the SDK does not add legacy readers. Video 3 seeds new work from `video3_final`,
keeps its original engine in `video3_sources`, and can compose bounded excerpts
from the retained full clean render.
