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
