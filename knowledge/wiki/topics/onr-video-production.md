# ONR Video Production

## Maintained production

The local generator maintains the original nine-video catalog, the approved final videos 1 and 2, the completed outdoor Video 3, Hospital Video 4, and warehouse Video 5. Final deliveries remain `evidence/onr_demo/`, `evidence/onr_video1_final/`, `evidence/onr_video2/`, `evidence/onr_video3/`, `evidence/onr_video4/`, and `evidence/onr_video5/`. The complete original catalog and both corrected deliveries are preserved. Video 2 now uses sequential perspectives: a 16-second third-person comparison followed by the same run replayed from the robot cameras, for a 32-second edit.

Production source now lives in ignored `local/onr/`, separate from disposable build outputs and the public SDK. Its README owns commands, runtime requirements and workspace selection. `run.py` provides prepare, capture, render, compose and verify stages. Common Office setup, recorded-pose replay, causal instruments and FFmpeg composition are shared. The catalog uses the current sibling SquadBot consumer; retired script copies, probing workers and the duplicated downstream snapshot are not maintained.

The series demonstrates generic audio sensing and controlled downstream camera pointing. Sensor observations, scene references and downstream behavior remain distinct. It makes no navigation, learned recognition or field-readiness claim. Historical unsuccessful video edits are available through the earlier documentation in Git; only final production paths remain active.

## Videos 1–3 Reference Revision

The local `revise_references.py` workflow adds Video 4's camera FOV styling and green direct-path references to the approved edits. New `master_fov_direct_path_1440p.mp4` files live alongside the existing movies in each delivery directory; only 2560×1440 copies are produced. Durations remain 40, 32 and 23 seconds, with the original AAC soundtrack copied unchanged. Recorded poses, clean renders and original deliveries are preserved.

Video 2 shows direct-path references only in the right audio-guided panel. The left visual-only panel retains its camera FOV without an audio path. Videos 1–3 show the direct path of their unoccluded acoustic model in green. Video 1 keeps the reference throughout each authored sound event in external views, independently of intermittent detection; Videos 2 and 3 retain their causal detection timing. The shared legend below says “Green: direct path” and makes no blockage-status claim. Source endpoints and camera poses remain synchronized scene references, separate from audio estimates. POV shots omit the fan and path; the prop detail in Video 1 also omits them for legibility. Regeneration and verification commands are in `local/onr/README.md`.

## Shared Production Standard

- Cinematic minimal presentation: Nimbus Sans Regular/Bold, white and neutral gray, small charcoal backing only where needed. US English throughout. Show a short title, audio/view state, and useful direction information. Remove robot-name banners, demo clock, decorative microphone waveform, large information bars, and the editorial direction radar. Do not use generated raster art.
- Use the sensor GUI's actual compass renderer and RMS view-models, driven by synchronized observations. Show the compass during events; use a brief RMS detail when helpful. Where used in Videos 1–4, apply causal presentation smoothing, label the latest smoothed estimate, and expire stale directions. Video 5 instead shows the complete latest observation set without bearing smoothing or persistence; alternatives stay grouped within their event. Preserve the unfiltered observations and their missing estimates. Bearing overlays derive from actual transforms; ray length is not estimated range. Compass colors must not encode obstacle geometry that the audio estimator has not inferred.
- Include the head-camera FOV in every new or revised video. In external views showing the robot, use the approved light cyan, semitransparent fan with thin boundaries and a front axis, derived from actual camera poses and aperture (65° horizontal in this series). Keep it distinct from acoustic rays and exclude it from physics and propagation. Its short extent is illustrative, not an estimated sensing range. In robot-camera shots, the image itself represents the FOV; omit the fan. Existing approved deliveries acquire this standard when revised.
- Include a scene direct-path reference for each relevant source throughout its sound sequence in external views, wherever the shot makes it legible. For direct-path-only examples, use green as the modeled direct-path reference without asserting geometric clearance. For occlusion examples, use independently checked scene geometry. In occlusion examples, reuse Video 4 colors: green for a geometrically clear segment, orange up to the first obstruction, a red/orange impact point, and an optional faint dashed red continuation toward the known source. Compute blockage from synchronized geometry; do not infer it from low RMS or an unavailable direction. If blockage was not checked, omit the status-colored path rather than imply it is clear. Label these paths as geometry references, separate from the observation-driven compass and camera FOV. A clear geometric segment does not certify audio quality, and a blocked segment does not imply silence.
- Source endpoints come from scene truth, not from an audio range or object-identity estimate. Detection may time the overlay, but must not be presented as per-source identification when multiple simultaneous emitters cannot be associated with observations. In that case, distinguish known emitting-source references from detected events explicitly. Use the authored source-event interval for a known single-source scene reference, including pauses within a knock or ring sequence; do not let intermittent detection or missing DOA truncate that reference. When only observation timing is available, use the causal activity window. Retain RMS and the activity label as the evidence that sound was received. Source distance alone is not a reason to omit the path: keep a thin, restrained line if useful, clip it at the frame boundary for off-screen sources, and do not invent a nearer endpoint. Omit the direct path in all first-person/robot-camera views. In other shots, clip off-screen segments and keep the reference throughout the event; omit it only when the whole relevant geometry is outside the view or a prop detail does not show the robot. Preserve the same color meanings across all videos; apply this standard to approved deliveries when they are revised.
- Mix actual robot-camera views, third-person rear/over-shoulder views, oblique room views, and useful details. Motivate cuts by the action; retain spatial and temporal continuity. Keep the robot's response prominent when demonstrating sound-driven behavior; source motion should remain understandable alongside visible head/torso reactions. Film cameras do not change the microphone soundtrack or hide sensor failures.
- Prefer complete, furnished, existing environments relevant to SquadBot building/urban exploration. Inspect materials, scale, furnishings, light, and camera framing before accepting an environment. Replace an inadequate candidate rather than constructing another sparse room. Reuse of a room or prop is optional; vary settings, sources, and cinematography across the series.
- Associate emission with the relevant scene object. A small synchronized pulse may identify the emitter as a scene reference, separately from detection. Use a loudspeaker model only for a loudspeaker; it is not a generic microphone or universal source icon.
- Use natural, appropriately licensed sound recordings and restrained ambience. Avoid repeated game-voice snippets and harsh synthetic noise. No music. The soundtrack is the observed microphone signal with one constant presentation gain; camera cuts do not alter it.
- Keep shared styling/instruments separate from per-video scene, source, and shot choices. Production remains outside the public SDK; no new public API is planned.

### Common FOV/direct-path legend

Use `presentation.reference_legend` for every new or revised ONR video. Keep this wording and order:

| Acoustic model | Legend text |
| --- | --- |
| Direct path without occlusion (Videos 1–3) | `Scene reference · Cyan: camera FOV · Green: direct path` |
| Modeled occlusion with geometric checks (Video 4) | `Scene reference · Cyan: camera FOV · Green: clear path · Orange: blocked path` |

Never mention orange or blockage in an unoccluded example. In an occlusion example, keep the complete color key stable while the door moves. These labels describe scene references, not an audio direction, range, recognition result or inferred obstacle.

At 2560×1440, use Nimbus Sans Regular at 25 px, text RGBA `(219, 225, 222, 240)`, backing RGBA `(22, 22, 22, 190)`, and 4 px corner radius. Compute width as `ceil(font.getlength(text)) + 20`: 10 px padding on each side, with no fixed-width empty tail. Backing height is 41 px; text begins 10 px from its left and 5 px from its top. Scale these dimensions together for other render sizes.

Default text anchor is `(64, 1390)`, below the lower-left activity panel. In the split comparison, use `(1316, 210)` inside the right audio-guided panel, below its status; never cover instruments or source action. Omit this legend, the FOV fan and direct-path graphics in first-person views. The image itself is the camera FOV. In external views, a source reference persists across cuts and intermittent detection for its full declared sound event; only the observed instruments report detection or a direction estimate.

Video 4's updated standalone copy is `evidence/onr_video4/master_fov_direct_path_1440p.mp4`. It uses the shared legend at native 1440p; its original recordings, occlusion references and audio are unchanged.

## Video 1 Decisions

The furnished private office in NVIDIA Office passed the user's review. Preserve its desk, chairs, cabinets, blinds, artwork, and layout. Close the existing door. Place the robot beside the blinds at `(-23.08, 13.25)` m, on the opposite side from the first review, following the user's marked floor location. The base faces 25°; it stays fixed. Keep enough clearance for the full body and grippers.

Use **Alex V2 full body**, replacing the Purdue torso used in the first review. The production-only assembly combines the sibling Alex V2 URDF with both WSG32/UMI assets. The nominal circular ReSpeaker XVF3800 geometry has four microphones at 35 mm radius; rendered and sensing coordinates agree. This is nominal geometry, not measured calibration. GPU validation covers articulation and sensor mounting; the gripper attachment is a demo assembly, not grasp or hardware mount qualification.

The actual head camera retains its URDF mount. A fixed `NECK_Y = -0.12` rad posture lifts its view by about 6.9° relative to the neutral neck. The camera has a 65° horizontal FOV and explicit 16:9 aperture. Rear framing is wider and aimed lower to include the head and shoulders. External corner, rear, side, and detail cameras supplement actual robot-camera shots.

The 40-second sequence is context → door knocks → telephone → radio → visual conclusion, at 30 fps. The phone sits on the existing desk. The radio sits on the filing cabinet, facing the robot; the existing paper trays slide back on the same cabinet to make space. The door source is on the room-facing closed panel. These choices keep objects visible from the marked robot position. They do not prescribe the settings or props for later videos.

The revised direct-path overlay follows the complete source events: door 4–9.0778 s (including the pause between knocks), phone 15–22 s, and radio 27–35 s. It remains visible in every external shot during those intervals, even if the audio detector briefly reports listening. It is omitted in first-person views by design. This timing affects only the scene reference, never the observed compass, activity indicator or RMS.

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
| 4 | Occlusion | 2 | Audible attenuation and understandable instrument response | 30 s Hospital Geometry delivery; technical checks complete, user review pending |
| 5 | Multiple sources and background | 5 | Distinct concurrent sources and realistic interference; verify pipeline capability | Discuss individually |
| 6 | Materials and acoustic spaces | 6 | Clarify what changes and make the acoustic result understandable | Deferred; design open |
| 7 | Audio–vision link | 7 | Main integration story; show the actual chain clearly | Discuss individually |
| 8 | Dataset | 8 | Better placement of explanations and clearer data workflow | Discuss individually |
| 9 | Simulation and real microphones | 9 | Clarify physical evidence and what can be compared | Deferred; design open |

For each revision: [ ] agree the task and setting; [ ] apply shared standards; [ ] review a short excerpt; [ ] validate behavior and media; [ ] deliver the approved video. Each future video gets its own decisions; this page does not prescribe nine identical scenes or storyboards.

## Remaining ONR deliveries

Videos 1–5 now have individual revised deliveries. Videos 1–3 remain approved and unchanged; Video 4 awaits the user's review. Video 5 passes technical/media checks and preliminary mixture listening; full-video listening remains pending. Remaining revisions 6–9 retain their separate scene and media gates. The original nine-video catalog is preserved.

The series demonstrates sensing in individually qualified scenarios. Existing
recordings retain their own scope: Video 3's 8 m/s outdoor direct-path case is a separately qualified
bounded demonstration, not proof of an equivalent indoor Geometry domain.
The approved Alex V2 production assembly/pointing is not physical Alex003 mounting
or partner acceptance evidence.

| Revised video | Remaining work | Dependence on Phase 08 and other work |
| --- | --- | --- |
| 6 — Materials/acoustic spaces | Agree which physical change is demonstrated and validate its effect on received PCM and instruments; replace any implication that decorative furniture drives the old shoebox | A bounded declared shoebox experiment is possible independently. Geometry-authored material/space claims need the relevant 08.2 qualification and 08.3 workflow; richer randomization or physical-transfer claims belong to 09/separate validation |
| 7 — Audio–vision link | Demonstrate hear → orient → see → link with visible failure/unconfirmed cases; verify the actual consumer chain and distinguish authored/annotated visuals from learned recognition | This application demonstration does not require full Phase 08 for a bounded analytic scene, nor automatic completion of Phase 11. Geometry claims require their own admitted domain; no unseen-source truth or visual oracle may silently become an audio estimate |
| 8 — Dataset | Agree a clearer recording/replay/observations-versus-truth story and validate the exact recorded data path; produce the revised media | Existing recording/dataset capability is available. Depends on the producer shown, not all of Phase 08 or completion of policy training |
| 9 — Simulation/real microphones | Agree a defensible comparison using the existing physical evidence, align the compared quantities, and keep known mismatches visible | Requires a suitable bounded physical/sim comparison, not merely a completed Phase 08. Existing recordings do not establish general transfer; no new capture campaign is authorized by this readiness audit |

Phase 08 completion alone does not close these media tasks or approve a scene.
Each remaining video still needs its agreed brief, scenario-specific sensing and
consumer gate, excerpt review, synchronized observed soundtrack/instruments and
full technical/media QA. General-purpose SDK work stays separate from local ONR orchestration and
SquadBot semantics.

## Video 4 — Hospital Occlusion

The 30-second film uses the complete NVIDIA Hospital, the approved full-body Alex V2/WSG32 assembly, nominal four-microphone array and 65° head camera. A bedside monitor emits the same one-second CC0 “Heart Monitor Beep” excerpt by samfk360 from 3 s onward. Emission level remains constant. The monitor is an illustrative prop, not a physiological simulation or a calibrated clinical recording; the retained original Hospital bed provides the treatment-room context.

The robot starts in the corridor with the source outside its camera FOV. Observed audio directions command head and torso yaw until 9 s, then the target pose is held. The existing `SM_Door_01b_2` closes smoothly on its own pivot at 12–16 s, stays closed through 22 s and reopens at 22–26 s. This is a controlled scene action, not robot manipulation. The closing shot is uninterrupted; context, shoulder and a brief actual-camera view retain the series' Nimbus Sans/US English presentation.

`GeometryAcoustics` supplies all four contribution families: Steam direct/planar transmission, first-order native PRA specular paths, selected-route NLOS and shared diffuse pressure. The retained 106 Hospital proxy surfaces preserve the aperture; the original visible leaf and its single acoustic proxy share the same parent transform. Nominal door losses are 15/19/23/26/29/32 dB at 125/250/500/1000/2000/4000 Hz. These are declared parameters, not measured calibration. The visual bed and monitor are excluded from propagation. Configuration uses a 2 s horizon, 4096 diffuse rays, 0.5 m scattering-node spacing and 0.75 m NLOS probes. No Analytic signal or editorial attenuation is added.

RTX 4090 articulation runs at 60 Hz; supported native propagation and maintained perception run on CPU. PCM and array poses share the 16 kHz sample clock, with 600 nonoverlapping 50 ms windows. This receiver-clock/quasi-static scene demonstration does **not** extend the separate maximum-motion admission, which used 2.5 ms updates. Full-room moving pressure equivalence, calibrated wall behavior and general diffraction remain unvalidated. Fixed base, disabled gravity/contacts and controlled pointing do not qualify navigation, balance or manipulation.

The cyan fan and faint corner rays derive from the actual camera calibration and transforms. Their short extent illustrates direction and aperture, not sensing range. Green/orange direct-path segments, red impact points and hidden dashed continuations are independent geometry references. `Outside camera FOV`, `Visible` and `Blocked by door` combine frustum projection and line intersections; they are not recognition results. The SDK compass uses only recorded directions, with the established causal smoothing and three-second expiry. The activity label remains “Sound detected” until 2.5 seconds after the last detected observation. This causal display memory bridges periodic beeps without asserting persistent sound identity; it does not extend direction validity. RMS continues to follow received PCM with 0.18 s causal smoothing and remains visible from 3 s through the end on a fixed −90 to 0 dBFS scale, including quiet and unavailable intervals. The compass retains its observation-derived styling even when the geometric direct-path reference turns orange. A causal one-second received-level comparison appears after the open baseline is complete. The activity refinement reduces display-state transitions from 53 to one across the 30 s recording; all 900 RMS/direction states are identical to the previous presentation. A silence-tail check confirms release after 2.5 s within one video frame. Both full movies and the preview were recomposed from the existing clean renders.

All 600 windows replay sample-identically. The first direction is available at 3.55 s; the source is in camera view by 4.80 s. No pointing precedes the first observation, and held-pose joint drift after 10 s is below 0.003°. Matched 10–12 s, 19–21 s and 28–30 s excerpts contain the same emitted phase:

| Channel | Closed loss | Reopened minus open |
| --- | ---: | ---: |
| Front | 14.32 dB | +0.00001 dB |
| Right | 12.26 dB | −0.00002 dB |
| Rear | 12.30 dB | +0.00002 dB |
| Left | 11.03 dB | +0.00005 dB |

Front-channel spectral power falls by 11.71 dB at 125–500 Hz, 14.25 dB at 500–2000 Hz and 15.89 dB at 2000–7000 Hz. The transition is not forced to be monotonic: the recorded mixture briefly increases before attenuation. Raw peak is 0.00935, without clipping or anomalous block-boundary spikes. The same constant presentation gain applies to the entire recorded front channel. Open/closed/reopened excerpts have 14/8/14 resolved windows out of 40, including periodic quiet gaps; median resolved bearing errors are 0.78°/6.78°/0.78°. The occluded estimate remains available between beeps under the normal display policy; no obstacle truth changes its color or forces it unavailable.

The first finalization required correction of an episode grouping value. Its three published audio/frame shards, including original observations and array poses, remained unchanged. Full-body presentation poses were recovered by replaying the same causal controller on GPU and comparing all 600 resulting array poses with the recording: maximum position difference 0.74 μm, quaternion component distance below 1.7 × 10⁻⁷. Production now saves pose telemetry before manifest finalization and supplies the correct grouping value. This recovery is recorded in `capture.json` and `pose_recovery.json`.

Source and recordings remain in ignored `local/onr/video4/` and `local/onr/data/video4/`. `evidence/onr_video4/` contains the 1440p master, 1080p copy, eight-second closure preview, representative frames, front-microphone reference, sources/licenses, method and validation. The eight-second excerpt was checked before the full render. The generator exposes the existing prepare → capture → render → compose → verify workflow; optional local graphics preserve the approved videos and introduce no public API.

Both final encodes fully decode to 900 frames at 30 fps, with matching 30-second audio/video durations. AAC relative waveform error is 0.00687 and peak is 0.6503, without clipping. Visual and captured geometric blockage edges differ by at most one video frame (33 ms), within the declared 50 ms acquisition sampling. The complete contact sheet and representative full-resolution frames were inspected; preview and full 1080p browser playback reached their ends with audio enabled and no media error.

## Video 5 — Multiple Simultaneous Sources

Production uses the full furnished NVIDIA Warehouse with a stationary Alex V2 and two fixed visual emitters, an industrial fan and compressor, approximately 3 m from the array and 90° apart. The unavailable parked-forklift reference is removed only from a local copy of the environment layer. Original materials, shelves and source assets remain intact. Structural acoustic planes and shelf decks are extracted from the supplied geometry, preserving openings; small cargo, rack struts and machine internals remain visual-only.

The 30 s sequence is silent context (0–3 s), fan onset and short observed pointing (3–7 s), simultaneous machines (7–20 s), compressor alone (20–25 s), and final decay (25–30 s). The two-source view remains uninterrupted around the second onset and first offset. A brief compressor detail at 13–15 s retains the continuous recorded soundtrack and instruments. The first completed valid direction selects the initial head/torso target. The reached GPU joint pose is held from 5.7 s with zero joint velocities; source positions never command the robot. This explicit fixed pose prevents residual servo settling during the multisource segment.

Combined Geometry enables direct/planar transmission, first-order native specular paths, selected-route NLOS and diffuse pressure. Nominal absorption/scattering are 0.2, with a 2 s horizon, 1024 diffuse rays, 3 m surface/tail spacing, 16 directional modes and 1.5 m probes. This is a bounded scene model, not measured materials or converged whole-room simulation. A denser 4096-ray control preserved the same stable observation sets; the reduced configuration changed the front-channel mixture level by 0.35 dB. Native propagation/perception use their supported CPU implementations; actual RTX 4090 articulation uses 60 Hz, acquisition 100 ms and visual replay 30 fps.

The unchanged nominal four-microphone array operates at 16 kHz. The maintained WPE/group-sparse localizer uses its 750 ms causal context, without a supplied source count or a two-event cap. The SDK compass receives every observation from the latest completed frame, including missing, extra or ambiguous results. No bearing persistence joins observations across frames. Frame colors do not identify sources; per-microphone RMS measures the mixture. Cyan FOV geometry follows the actual 65° camera, and independently checked direct-path references follow authored emission intervals, not detections.

Natural source recordings are “Outdoor Industrial Fan” by RayGunV (CC BY 4.0) and “15_Air_Compressor_On_Off.wav” by lmbubec (CC0). Excerpts use mono resampling, constant emission gains and short fades/crossfades, without spectral processing. The fan original records several cooling fans and is represented here as one point emitter. The soundtrack uses the recorded front microphone and one constant gain. There is no music, third ambience or source-specific postmix gain.

Individual and simultaneous fixed-pose native probes pass in 100% of stable windows. The complete GPU capture also passes every scene-specific stable-set gate, without missing or extra observations:

| Stable interval | Correct sets | 95th-percentile maximum matched error |
| --- | ---: | ---: |
| Fan, 5–7 s | 20/20 | 0.78° |
| Both sources, 9–20 s | 110/110 | 3.92° |
| Compressor, 22–25 s | 30/30 | 2.39° |
| Quiet, 0–3 s and 27–30 s | 60/60 | No observations |

On the simulated timeline, the first correct direction sets appear at 3.1 s and 7.1 s; fan and compressor offsets are reflected at 20.6 s and 25.6 s. The fan enters the actual camera FOV by 3.8 s. There is no yaw motion before the first observation, no base drift and no drift of the held joint pose. All 300 multichannel windows replay sample-identically, including the delivered recording; all 900 display sets match the latest completed frame. Transitions and raw errors are retained without editorial correction.

Isolated front-channel levels differ by 2.96 dB over the held-pose fan and compressor intervals. Raw peak is 0.0353; the largest audio-block boundary step is below the waveform's overall 99.9th-percentile step. A single presentation gain of 18.4175 applies to the complete front channel. The final tail falls below detection while RMS remains visible; values below the -80 dBFS display floor are labeled accordingly. PCM becomes exactly zero after 27.1 s. This is offline scene evidence, not real-time or general moving-mixture qualification.

The six-second source-entry preview was inspected before the full render. Both final copies fully decode to 900 frames at 30 fps with matching 30-second audio/video durations; AAC/front-reference correlation is 0.99936 and decoded peak is 0.644, without clipping. The complete contact sheet and full-resolution views were inspected. The final 1080p copy also completed browser playback with audio unmuted and no media error. The user confirmed that both machines are distinguishable in the preliminary front-microphone mixture probe; full-video subjective listening remains pending because this tool session cannot receive audio input.

Maintained production is `local/onr/video5/`, inputs and controls are in `local/onr/data/video5/`, and delivery is `evidence/onr_video5/`: 1440p master, 1080p copy, preview, full recording, raw PCM/observations/poses, source licenses and verification. The existing prepare → capture → render → compose → verify interface now accepts `video5`; no public API or sensor capability changes.

## Existing Videos 6 and 9: Verified Clarifications

Video 6 uses an explicit 12 × 12 × 3.3 m shoebox with reflection order 3, switching absorption from 0.8 to 0.15. The visible furniture does not drive its acoustic model. The original catalog reports a +3.2 dB received-mixture change. This does not demonstrate distinct measured material responses of the rendered objects. Its redesign is undecided.

Video 9 overlays results from 25 existing ReSpeaker takes (5,440 windows) on a separate Alex simulation. The video's soundtrack remains simulated; it is not a real/simulated listening comparison. At the -3 dB source setting, the existing report records activity in 230/234 physical windows versus 0/234 simulated windows. The evidence supports pipeline reuse and a bounded bench comparison, not generally validated acoustic transfer. Its redesign is undecided.

Verified sources: `evidence/onr_demo/METHOD.md`, `catalog.json`, scenario `media_method.json`, and `build/onr_demo/runs/s09/physical_readout.json`. These are local ignored artifacts, not public package dependencies.

## Regeneration and verification

Run `.venv/bin/python local/onr/run.py <catalog|video1|video2|video3|video4|video5> compose` to recompose saved recordings, followed by `verify`. For new acquisition, use `all --work build/onr/<new-run> --out evidence/<new-delivery>`; existing recordings are preserved. Source assets and essential recordings live outside `build/`, so `make clean` cannot delete the maintained generator or its inputs.

GPU acquisition/rendering uses the supported Isaac Lab runtime and actual RTX hardware. Videos 1–3 use their existing CPU direct-path or declared shoebox implementation; Videos 4 and 5 use their declared combined native Geometry configurations above. Video 2's 50 ms source pre-roll is a local direct-path adapter: it holds poses within each audio window and is not a general SDK streaming repair. The same continuous microphone samples feed perception, recording and the soundtrack.

Check recorded-sample replay, event/silence behavior, causal direction expiry, shared panel states, finite poses, camera transforms, full media decoding and audio/video synchronization. Original user MP3s, source licenses and physical recordings remain preserved. Short cleanup previews verify the maintained paths without repeating full historical statistical campaigns; they do not replace the approved final deliveries or their original full-playback review.

References: [[topics/system-architecture|System Architecture]], [[topics/public-contracts-and-recording|Public Contracts and Recording]].

The cleanup migrated 8,780 records in 12 local sessions and their standalone traces
from frame v3 to v4. Only the schema label and required integrity references changed;
original scores, observations, poses, clocks and PCM were preserved. Approved
historical deliveries remain untouched. Fresh production uses the current schema;
the SDK does not add legacy readers. Video 3 seeds new work from `video3_final`,
keeps its original engine in `video3_sources`, and can compose bounded excerpts
from the retained full clean render.
