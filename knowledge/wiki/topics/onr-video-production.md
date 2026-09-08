# ONR Video Production

## Current Revision

Only video 1 has been revised. The user approved the first visual and sound review and requested the corrections below; the corrected 40-second video is complete and technically verified in 1440p and 1080p. Original videos and recorded evidence remain unchanged. Videos 6 and 9 are deferred: their next designs will be discussed individually with the user.

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

## Per-Video Checklist

Numbers below follow the user's revised order. Old numbers identify the existing package only.

| New | Video | Existing video | Requested focus | State |
| --- | --- | --- | --- | --- |
| 1 | Basic sensing in a relevant setting | 1 | Sequential sources in useful positions; establish shared quality standard | In revision |
| 2 | With and without audio | 3 | Make the camera-only behavior and matched comparison clearer | Discuss individually |
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
