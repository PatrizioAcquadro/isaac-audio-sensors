# ONR Video Production

## Current Revision

Video 1 has a revised delivery. Video 2 production is stopped at the supplied-audio pilot: continuity is corrected, but both modes arrive together and no replacement video has been rendered. Video 2 is a 16-second matched opening-door comparison. The user accepted its composition and requested the sound, divider, and paired-instrument corrections documented below. For video 1, the user approved the first visual and sound review and requested the corrections below; the corrected 40-second video is complete and technically verified in 1440p and 1080p. Original videos and recorded evidence remain unchanged. Videos 6 and 9 are deferred: their next designs will be discussed individually with the user.

The series demonstrates generic audio sensing and controlled downstream camera pointing. It must distinguish sensor observations, scene references, and downstream behavior. No navigation, sound classification, learned visual recognition, or field-readiness claim is implied.

## Shared Production Standard

- Cinematic minimal presentation: Nimbus Sans Regular/Bold, white and neutral gray, small charcoal backing only where needed. US English throughout. Show a short title, audio/view state, and useful direction information. Remove robot-name banners, demo clock, decorative microphone waveform, large information bars, and the editorial direction radar. Do not use generated raster art.
- Use the sensor GUI's actual compass renderer and RMS view-models, driven by synchronized observations. Show the compass during events; use a brief RMS detail when helpful. Apply causal presentation smoothing, label the latest smoothed estimate, and expire stale directions. Preserve the unfiltered observations and their missing estimates. Camera FOV and bearing overlays, when used, derive from actual transforms; ray length is not estimated range.
- Mix actual robot-camera views, third-person rear/over-shoulder views, oblique room views, and useful details. Motivate cuts by the action; retain spatial and temporal continuity. Film cameras do not change the microphone soundtrack or hide sensor failures.
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

The first review remains at `evidence/onr_video1_revision/`: three frames, a 12-second excerpt, and source auditions. The user accepted the room, graphics, sound quality, and shot mix, then requested the full-body robot, closed door, opposite position, framing, radio continuity, and smoother instruments. That earlier Purdue/open-door execution is superseded for video 1; its media remain intact.

The corrected sensor execution is `build/onr_video1_final/run_v6/`. Technical sensor and pose checks pass on the RTX 4090 run: 800 audio windows, 1,200 finite pose frames, fixed base, both yaw joints active, and all 800 microphone windows reloaded sample-identically through `SessionDataset`. Initial quiet produces no detections. Every source point enters the actual camera FOV. Fresh frames were inspected for the closed door, phone, radio, and corrected position.

| Event | Emitting windows | Resolved direction windows | Median error when resolved | First target in camera FOV |
| --- | --- | --- | --- | --- |
| Door, onset 4 s | 84 | 16 | 0.74° | 5.70 s |
| Telephone, onset 15 s | 140 | 38 | 0.29° | 15.05 s |
| Radio, onset 27 s | 160 | 123 | 0.93° | 28.95 s |

The display uses only observations already available at each rendered time. Its activity transitions drop from 38 to 14 over the complete run. Intermittent direction measurements remain missing in the recording; the presentation explicitly shows a short-lived, smoothed latest estimate, then unavailable after three seconds. The first telephone FOV time is a geometric membership result, not a claim of visual recognition or a newly completed pointing action.

This is a direct-path free-field sensing/pointing example. The acoustic backend runs on CPU; articulation and RTX rendering run on GPU. Furnishings do not contribute reflections or material acoustics. The base is fixed with gravity and contact disabled, so this run does not validate navigation, balance, grasping, room acoustics, or physical readiness. Camera FOV membership is a geometric reference, not recognition or an occlusion test.

The corrected delivery is `evidence/onr_video1_final/index.html`, with `master_1440p.mp4`, `presentation_1080p.mp4`, a 12-second opening excerpt, three representative frames, audio credits, method, and validation report. Both complete encodes decode to 1,200 frames at 30 fps with exactly 40-second audio/video durations. The AAC peak is 0.7413, without clipping. The 40-second contact sheets and representative full-resolution frames were inspected; browser playback reached the end with audio enabled and no media error. The user approved that full edit and subsequently requested the compass convention/retention correction and longer title. The presentation revision reuses the same measured execution, clean render, soundtrack, and camera cuts. Geometry checks independently verify the corrected needle against camera-relative source directions: the first door estimate is +56° right versus a +55.33° scene reference, the phone is −22° left versus −21.62°, and the radio is −82° left versus −81.69°. Initial, held, and expired states retain the dial; expiry is tested at the three-second boundary. See `build/onr_video1_final/compass_validation.json`. Original videos, including 6 and 9, remain preserved.

## Video 2 — First Delivery: Scripted Visual Scan and Measured Audio Guidance

The approved design uses the same furnished Office, fixed-base full-body Alex V2, 65-degree head camera, and production standard as video 1. Both runs initially observe the closed door, then start the same periodic scan at 1 s. At 3 s the door opens outside both camera views, rotating to 85 degrees over three seconds. A continuous natural creak follows the movement; no wall-hit sound is added because the animation has no demonstrated wall impact. The sound is the 1–4 s excerpt of Anthousai's CC0 [creak - front door 01.wav](https://freesound.org/people/Anthousai/sounds/398748/), with mono downmix, constant scaling, and 25 ms edge fades. Ambience reuses video 1.

The visual-only baseline is explicitly scripted, as requested by the user. It continues the preset scan without receiving an event-onset cue. Its stop represents simulated visual arrival: opening exceeds 30 degrees and four doorway references lie inside a conservative central camera region, checked against the rendered POV. There is no visual detector or recognition implementation. Both runs use this same arrival condition. The audio-guided controller interrupts scanning only on a valid SDK direction and derives its pointing goal from that observation and the array pose; source truth does not command the turn. Missing estimates remain missing, with the same scan as fallback. Both runs retain the 35-degree-per-second command limit and identical commands until the first resolved direction.

The successful pair is `build/onr_video2/pilot_v3/`. The RTX 4090 execution records 480 pose frames per run and 320 audio windows in the audio-guided run. All 320 waveform windows reload sample-identically through `SessionDataset`. There are no pre-event detections; 30 direction windows resolve. The first measured direction arrives at 3.40 s. Scripted arrival is at 5.35 s with audio and 8.00 s with the visual scan: 2.35 versus 5.00 s after opening, a 2.65 s difference in this illustrative run. This is not a statistical benchmark, a comparison against another audio SDK, or evidence that audio wins at every scan phase.

The 16-second edit keeps both runs synchronized and time continuous. Each column contains an external over-shoulder view and the actual robot camera. Labels are “Visual-only · Scripted scan” and “Audio-guided · Isaac Audio Sensors”; states use “Scanning,” “Orienting to sound,” and “Door in view.” The SDK compass uses the corrected clockwise convention, causal smoothing and three-second expiry, with measurement age displayed to distinguish held estimates. The soundtrack is the audio-guided run's front microphone with one constant gain; no music or camera-dependent remix is used.

Delivery: `evidence/onr_video2/index.html`, `master_1440p.mp4`, `presentation_1080p.mp4`, representative frames, audio credits, `METHOD.md`, matched traces, and validation reports. Both encodes fully decode to 480 frames at 30 fps with exactly 16-second audio/video durations. AAC peak is 0.74014, without clipping. The complete contact sheet and representative views were inspected; browser playback reached 16 s with audio enabled and no media error. Original video 1 and all prior evidence remain unchanged.

The acoustic backend remains CPU direct-path free-field; articulation and RTX images run on GPU. Door motion and visual arrival are scripted. No material acoustics, vision recognition, navigation, contact/balance, or physical-readiness claim is introduced. The pilot's earlier absolute-audio-path and recorder-grouping setup errors were corrected in the production adapter; they required no SDK changes. Production remains local and ignored, without new public APIs.

## Video 2 — Review Corrections

The first delivery is preserved at `build/onr_video2/first_delivery/`; the corrected execution is `build/onr_video2/review_v1/`. The user rejected the first creak's high timbre, requested removal of the opening voice, a light final contact, stronger separation between modes, and synchronized direction instruments in both audio-guided views.

The creak is replaced with a continuous 1–4 s excerpt of stib's CC0 [Door Creak](https://freesound.org/people/stib/sounds/346267/), a wooden-door recording, preserving pitch and tempo. It plays at 3–6 s. One restrained 0.18–0.48 s wooden contact from the existing wjtaylor CC0 recording plays at 6–6.3 s, with a 1.5 kHz low-pass and a 0.14 source peak. This is Foley synchronized to the animated stop, not a physical wall-impact model. The speech-bearing ambience inherited from video 1 is removed completely; the revised source and recorded microphones are silent before opening.

The audio-guided execution and its camera renders are regenerated from the changed sound. The first measured direction is now at 3.80 s and scripted arrival is at 6.15 s: 3.15 s after opening, versus the unchanged baseline's 5.00 s. The illustrated advantage is 1.85 s. There are 47 resolved direction windows and no pre-event detections. All 320 microphone windows reload sample-identically. Baseline pose arrays are sample-identical to the first run, allowing reuse of its clean video. The new measured result replaces the first edit's displayed timings.

A 25-pixel charcoal vertical divider with a light-gray center separates the modes; the horizontal divider remains three pixels. Identical SDK direction panels appear in the external and robot-camera views of the audio-guided column. All 480 overlay states match exactly across the two panels, including held estimates, measurement age, unavailable states and disappearance.

The corrected files replace the active `evidence/onr_video2/` delivery while preserving the previous edit separately. The pilot, full-resolution layout, and complete contact sheet were inspected. Both encodes decode all 480 frames with synchronized 16-second audio/video; browser playback reaches the end with audio enabled and no media error. The opening is silent in the source, measured microphones, and decoded soundtrack. Checks are recorded in the corrected delivery's validation report. Video 1, the public SDK and downstream interfaces remain unchanged.

## Video 2 — Supplied Audio and Continuity Gate

The user rejected the replacement creak and audible stuttering, then supplied `DoorCreaking.mp3` and `DoorOpening.mp3` in `evidence/onr_video2/`. The original MP3 files remain intact. The new pilot uses only the supplied creak, preserving pitch and speed; its final contact at source time 6.31 s sets the animated end stop at video time 9.31 s after a 3 s onset. Source licensing was not supplied and is not attributed to CC0.

The previous recorded microphone had about 15 ms of silence at the beginning of every 50 ms window. Independent analytic renders omitted the preceding source samples needed for propagation delay. The earlier encode, clipping and sample-identical replay checks did not detect this problem; the previous overall audio PASS is superseded. WAV versus MP3 is not the cause.

A local production adapter adds 50 ms of causal source history before propagation and then crops the required recording window. The same samples feed actual SDK perception and the soundtrack. At fixed poses, 320 concatenated windows exactly match one continuous render. The new moving pilot has no exact-silence run during the active 4–10 s interval. The adapter is limited to this direct-path scene, with poses held within each window; it is not a general SDK streaming repair.

The RTX 4090 pilot records 12 valid directions, first at 5.35 s. Both modes arrive at 8.00 s, or 5.00 s after opening. Commands and camera poses match before the cue, speed limits remain equal, and all 320 audio blocks reload sample-identically. The comparison gate is **NO-GO** because the measured direction arrives too late to show an arrival advantage. Full rendering is stopped under the approved plan's rule. Detector/input-level calibration is a possible next pilot, not a validated fix.

Evidence, corrected microphone previews and method are in `build/onr_video2/user_audio_v1/`. The rejected prior delivery is preserved in `build/onr_video2/second_delivery/`; the active MP4 files remain that old edit and are explicitly marked as rejected in the local page/report. User-supplied files, video 1 and public SDK code remain unchanged.

## Per-Video Checklist

Numbers below follow the user's revised order. Old numbers identify the existing package only.

| New | Video | Existing video | Requested focus | State |
| --- | --- | --- | --- | --- |
| 1 | Basic sensing in a relevant setting | 1 | Sequential sources in useful positions; establish shared quality standard | Corrected delivery complete |
| 2 | With and without audio | 3 | Scripted visual scan versus measured audio guidance during an off-camera door opening | Stopped: supplied-audio continuity passes; comparison pilot NO-GO |
| 3 | Moving source | 4 | Following during emission; clearer instruments; discuss Doppler scope | Discuss individually |
| 4 | Occlusion | 2 | Audible attenuation and understandable instrument response | Discuss individually |
| 5 | Multiple sources and background | 5 | Distinct concurrent sources and realistic interference; verify pipeline capability | Discuss individually |
| 6 | Materials and acoustic spaces | 6 | Clarify what changes and make the acoustic result understandable | Deferred; design open |
| 7 | Audio–vision link | 7 | Main integration story; show the actual chain clearly | Discuss individually |
| 8 | Dataset | 8 | Better placement of explanations and clearer data workflow | Discuss individually |
| 9 | Simulation and real microphones | 9 | Clarify physical evidence and what can be compared | Deferred; design open |

For each revision: [ ] agree the task and setting; [ ] apply shared standards; [ ] review a short excerpt; [ ] validate behavior and media; [ ] deliver the approved video. Each future video gets its own decisions; this page does not prescribe nine identical scenes or storyboards.

## Existing Videos 6 and 9: Verified Clarifications

Video 6 uses an explicit 12 × 12 × 3.3 m shoebox with reflection order 3, switching absorption from 0.8 to 0.15. The visible furniture does not drive its acoustic model. The original catalog reports a +3.2 dB received-mixture change. This does not demonstrate distinct measured material responses of the rendered objects. Its redesign is undecided.

Video 9 overlays results from 25 existing ReSpeaker takes (5,440 windows) on a separate Alex simulation. The video's soundtrack remains simulated; it is not a real/simulated listening comparison. At the -3 dB source setting, the existing report records activity in 230/234 physical windows versus 0/234 simulated windows. The evidence supports pipeline reuse and a bounded bench comparison, not generally validated acoustic transfer. Its redesign is undecided.

Verified sources: `evidence/onr_demo/METHOD.md`, `catalog.json`, scenario `media_method.json`, and `build/onr_demo/runs/s09/physical_readout.json`. These are local ignored artifacts, not public package dependencies.

## Validation and Output Locations

Working files: `build/onr_video1_final/`. Corrected delivery: `evidence/onr_video1_final/`. Earlier review: `evidence/onr_video1_revision/`. Original package: `evidence/onr_demo/`. Production scripts, imported assets, data, and media remain ignored local artifacts outside the SDK.

Check GPU articulation/rendering, finite poses, sensor/camera transforms, actual camera acquisition, event/silence behavior, synchronized instruments, audio clipping, and 1080p readability. Inspect the complete 40-second edit, both encoded resolutions, and 1080p readability after the approved corrections. Keep raw measurements separate from display mastering.

References: [NVIDIA environments](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/assets/usd_assets_environments.html), [IHMC building-exploration context](https://www.ihmc.us/groups/luigi-penco/), [[topics/system-architecture|System Architecture]], [[topics/public-contracts-and-recording|Public Contracts and Recording]].
