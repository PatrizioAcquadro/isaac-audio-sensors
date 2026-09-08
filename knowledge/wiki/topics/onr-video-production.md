# ONR Video Production

## Current Revision

Only video 1 is in production. Its visual and sound review must precede the full render. Original videos and recorded evidence remain unchanged. Videos 6 and 9 are deferred: their next designs will be discussed individually with the user.

The series demonstrates generic audio sensing and controlled downstream camera pointing. It must distinguish sensor observations, scene references, and downstream behavior. No navigation, sound classification, learned visual recognition, or field-readiness claim is implied.

## Shared Production Standard

- Cinematic minimal presentation: Nimbus Sans Regular/Bold, white and neutral gray, small charcoal backing only where needed. US English throughout. Show a short title, audio/view state, and useful direction information. Remove robot-name banners, demo clock, decorative microphone waveform, large information bars, and the editorial direction radar. Do not use generated raster art.
- Use the sensor GUI's actual compass renderer and RMS view-models, driven by synchronized observations. Show the compass during events; use a brief RMS detail when helpful. Preserve missing estimates and uncertainty. Camera FOV and bearing overlays, when used, derive from actual transforms; ray length is not estimated range.
- Mix actual robot-camera views, third-person rear/over-shoulder views, oblique room views, and useful details. Motivate cuts by the action; retain spatial and temporal continuity. Film cameras do not change the microphone soundtrack or hide sensor failures.
- Prefer complete, furnished, existing environments relevant to SquadBot building/urban exploration. Inspect materials, scale, furnishings, light, and camera framing before accepting an environment. Replace an inadequate candidate rather than constructing another sparse room. Reuse of a room or prop is optional; vary settings, sources, and cinematography across the series.
- Associate emission with the relevant scene object. A small synchronized pulse may identify the emitter as a scene reference, separately from detection. Use a loudspeaker model only for a loudspeaker; it is not a generic microphone or universal source icon.
- Use natural, appropriately licensed sound recordings and restrained ambience. Avoid repeated game-voice snippets and harsh synthetic noise. No music. The soundtrack is the observed microphone signal with one constant presentation gain; camera cuts do not alter it.
- Keep shared styling/instruments separate from per-video scene, source, and shot choices. Production remains outside the public SDK; no new public API is planned.

## Video 1 Decisions

Use the existing NVIDIA Office as the first candidate; retain its furnished layout and select a suitable corridor/access and room. Doors, phones, and radios already exist in the asset pack. Visual quality remains subject to the review excerpt.

Use Alex Purdue with WSG32/UMI from the sibling Alex repository and the circular nominal ReSpeaker XVF3800 geometry. The current nominal profile places four microphones at radius 0.035 m. Scene and sensor coordinates must agree. Nominal geometry is not measured calibration. Validate the supported robot joints, mounting, and camera frame before recording.

Target approximately 40 seconds at 30 fps: establish context, door knocks, telephone, radio, visual conclusion. Sources occupy distinct fixed positions and emit one at a time, separated by quiet intervals. The knocking face is exposed to the receiver so this basic case does not depend on through-door transmission. Pointing uses observed estimates and the actual supported joints; the base remains fixed.

Review three frames (robot camera, rear view, room corner) and an 8–12 second excerpt with cuts and candidate audio before the full render. Final target: 1440p master and 1080p presentation copy. Recompute observations, poses, and results after robot/array/source changes; do not carry old metrics forward.

## Current Review Evidence — September 8, 2026

The review package is ready at `evidence/onr_video1_revision/index.html`: three 1080p frames, a continuous 12-second excerpt at 30 fps with four camera segments, and separate door/telephone/radio source auditions. The excerpt covers the opening and door response. The 40-second sensor execution has been regenerated; the full 1440p/1080p videos have **not** been rendered and await the user's review.

The selected location is an existing furnished private office within NVIDIA Office, with original desk, chairs, cabinets, blinds, artwork, and open access door. Lighting was adjusted; the room was not rebuilt. Alex Purdue uses the sibling repository's WSG32/UMI configuration and measured pedestal dimensions. GPU execution confirmed that this model has head yaw but no torso yaw joint; the controller uses `NECK_Z` only, with fixed torso and base. The actual head-camera mount, including its downward tilt, is retained. Camera FOV membership is a geometric scene reference, not recognition or an occlusion test.

Four microphone centers lie on the nominal 35 mm circle, consistently attached to the measured head pose for propagation, estimation, and rendering. Recorded GPU poses drive RTX replay; external editing cameras leave the microphone channel and simulation time unchanged. `presentation.py` contains the reusable neutral layout and actual GUI instruments; `video1_edit.json` holds the title and event/shot timing, outside the SDK. The soundtrack uses the front microphone and one gain fixed from the complete run. Candidate audio comes from four CC0 source pages documented in `audio_sources.json`; source auditions are explicitly separate from microphone playback.

Technical preview checks passed on the RTX 4090 articulation/rendering run and subsequent recording/media checks: 800 audio windows over 40 seconds, 1,200 finite pose frames, fixed base, and all 800 audio windows reloaded sample-identically through `SessionDataset`. The initial quiet interval produced no detections. All three target points entered the actual camera FOV following observed-direction head commands. The 12-second delivery contains 360 decoded 1080p frames, equal audio/video durations, and no clipping; browser playback reached the end. These checks do not replace subjective sound/visual acceptance.

| Event | Emitting windows | Resolved direction windows | Median error when resolved | First target in camera FOV |
| --- | --- | --- | --- | --- |
| Door, onset 4 s | 84 | 28 | 1.01° | 5.15 s |
| Telephone, onset 15 s | 140 | 39 | 0.40° | 15.45 s |
| Radio, onset 27 s | 58 | 24 | 1.77° | 27.95 s |

Intermittent estimates remain unavailable between resolved windows; the presentation does not fill them with scene truth. This basic recording uses the existing CPU direct-path acoustic backend while articulation and rendering use GPU. Furnishings do not contribute reflections or material acoustics in this run. It is a controlled sensing/pointing example, not room-acoustics or navigation qualification. Full results and the bounded check scope are in `evidence/onr_video1_revision/validation.json`.

Next: review the furnished setting, camera mounting/framing, graphic size, and candidate sound with the user; apply requested corrections, regenerate measurements if geometry or audio changes, then render and inspect the approved full 1440p master and 1080p copy. Original videos remain preserved, including videos 6 and 9.

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

Working files: `build/onr_video1_revision/`. Review delivery: `evidence/onr_video1_revision/`. Original package: `evidence/onr_demo/`.

Check GPU articulation/rendering, finite poses, sensor/camera transforms, actual camera acquisition, event/silence behavior, synchronized instruments, audio clipping, and 1080p readability. Inspect the complete review excerpt; reserve full-video admission for the user's visual/sound review and the subsequent complete render. Keep raw measurements separate from display mastering.

References: [NVIDIA environments](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/assets/usd_assets_environments.html), [IHMC building-exploration context](https://www.ihmc.us/groups/luigi-penco/), [[system-architecture|System Architecture]], [[public-contracts-and-recording|Public Contracts and Recording]].
