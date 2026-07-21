# S4.2 operator acquisition runbook

This runbook collects one fail-closed S4.2 dry run. It does **not** collect the
S4.3 experimental matrix. Run commands from the repository root on the Ubuntu
workstation unless a Mac prompt is shown.

## 1. Scene and privacy

1. Clear people, shipping labels, credentials, readable private screens, and
   other personal data from the full ZED field of view. The operator must remain
   outside retained frames.
2. Confirm the complete fixture is still on the marked
   `S4_TEMP_DESKTOP_FIXTURE_REV0` footprint in
   `WANG_2022_DESK_NEAR_ENTRANCE`.
3. Confirm neither support nor sensor moved, all microphone openings are clear,
   the ZED view is clear, and cables cannot be pulled, tripped over, or move the
   fixture.
4. Record occupancy, HVAC/computer/voice/impact noise, doors, and any unusual
   transient. Do not describe an unobserved room state as quiet.

If privacy or fixture safety is uncertain, stop and clear/correct the scene.
Never edit or synthesize a scientific frame to remove private content.

## 2. Measure the MacBook source pose

`F_project` has its origin at the ZED stereo-lens midpoint. +X points forward
along the ZED view. +Y points to the operator's right while the operator faces
the camera, which is the ZED camera's left. +Z points up. Use meters and
degrees.

1. Put the MacBook at the intended controlled-source position. Do not move the
   rig to make measurement easier.
2. Identify the approximate center between the left and right built-in speaker
   regions as the source point.
3. With metric tape, measure from the ZED stereo midpoint to that point:
   forward/back displacement `x`, right/left displacement `y`, and vertical
   displacement `z`. Forward, operator-right-facing-camera, and up are
   positive; behind, operator-left-facing-camera, and down are negative.
4. Record source distance as `sqrt(x^2 + y^2 + z^2)` meters. The validator
   allows only 0.02 m difference between position and declared distance.
5. Record horizontal bearing counterclockwise from +X toward +Y, viewed from
   above: front `0 deg`, operator-right-facing-camera `90 deg`, behind
   `180 deg`, and operator-left-facing-camera `270 deg`. Also record the
   plain-language side and camera-relative equivalent.
6. Measure speaker-center height above the floor in meters.
7. Record Mac yaw, pitch, and roll in degrees, lid angle in degrees, whether the
   lid is open/closed, and which way the screen and keyboard face. An iPhone
   level is sufficient for practical pitch/roll; this is not metrology.

Do not infer any of these values from a photograph. Record practical tape/level
uncertainty in operator notes.

## 3. Reference deployment and Mac checks

The maintained deployment command copies only the two helpers and the reference
WAV into dedicated `S4.2` directories and verifies hashes:

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 deploy \
  configs/s4_2_acquisition.v1.json
```

Equivalent explicit copy commands, if manual copying is needed, are:

```text
ssh patrizios-macbook 'mkdir -p S4.2/bin S4.2/reference'
scp scripts/s4_2_mac_preflight.py \
  patrizios-macbook:S4.2/bin/s4_2_mac_preflight.py
scp outputs/isaac_audio_sensors/S4/S4.2/reference/s4_2_reference_v1.0.0.wav \
  patrizios-macbook:S4.2/reference/s4_2_reference_v1.0.0.wav
```

Final Mac path:

```text
$HOME/S4.2/reference/s4_2_reference_v1.0.0.wav
```

On the Mac, verify:

```text
cd "$HOME"
shasum -a 256 S4.2/reference/s4_2_reference_v1.0.0.wav
afinfo S4.2/reference/s4_2_reference_v1.0.0.wav
/usr/bin/python3 S4.2/bin/s4_2_mac_preflight.py \
  --wav S4.2/reference/s4_2_reference_v1.0.0.wav \
  --expected-sha256 27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468
```

Expected `shasum` is
`27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468`.
`afinfo` must report WAVE, one channel, 48,000 Hz, Int16, and 9.500000 s.

The helper is read-only and redacts personal identifiers. The workstation can
collect the same report with:

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 mac-preflight \
  configs/s4_2_acquisition.v1.json \
  --output outputs/isaac_audio_sensors/S4/S4.2/mac_preflight_current.json
```

## 4. Mac settings immediately before an accepted take

Keep Work Focus active and notifications suppressed. Confirm built-in `MacBook
Pro Speakers`, stereo 48 kHz output, 63% system volume, unmuted output, AC
power, mono audio off, background sounds off, and centered left/right balance.

The collector cannot read balance reliably. In System Settings -> Sound ->
Output, visually verify the Balance control is centered and report that
confirmation. An off-center balance rejects the take.

Choose and record one system-sound control:

- temporarily disable UI sound effects and volume-change feedback, then restore
  them after the take; or
- confirm a procedure in which no volume key, UI alert, Finder action, app, or
  other system-sound trigger occurs from recorder readiness through stop.

Do not change Focus, balance, accessibility, system/UI-sound, or unrelated
settings through the acquisition tool. Volume, mute, and selected built-in
output may be changed only after explicit operator authorization, and every
change is recorded before the accepted take. Any pilot-driven playback change
must be predeclared and cannot be selected from held-out results.

Playback remains:

```text
/usr/bin/afplay -v 1.0 "$HOME/S4.2/reference/s4_2_reference_v1.0.0.wav"
```

## 5. Complete and validate the acquisition configuration

Copy `configs/s4_2_acquisition.v1.json` to a take-specific configuration. Fill
all null physical and preflight fields and explicit confirmations. Do not edit
frozen device, waveform, mode, channel-order, room, frame, evidence-policy, or
threshold values.

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 validate-config \
  <take-config.json> --require-ready
```

This command must pass before any capture hardware is touched. The only raw
root is `dataset/S4.2/`; off-machine storage is unauthorized. The validator
requires the pre-capture acceptance amendment and explicit acknowledgment that
the raw data are gitignored, unreplicated, vulnerable to workstation loss, and
unavailable from a fresh clone.

## 6. Bounded acquisition

The orchestrator validates metadata, reference and current Mac report; checks
local disk; records three SSH round-trip observations per remote host without
calling them synchronization; verifies Pi/ReSpeaker and ZED/GPU/USB settings;
then starts both local producers.

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 run \
  <take-config.json> --interactive-cue
```

When the terminal prints the active-recording warning, hold the clap/impact object
approximately 1 m in front of the rig, in the central ZED field of view, while
keeping hands, face, labels, and screens out of retained frames. When it prints
the Enter prompt, press Enter only when the operator is prepared. When it then
prints `ALIGNMENT EVENT NOW`, immediately perform exactly one sharp clap or
visible impact. Do not perform another similar impact. Playback starts four
seconds later in interactive mode. Do not touch the Mac volume keys or generate
UI sounds.

The 20 s recorders stop automatically. The Pi WAV is copied only after local
Pi finalization. Interruption, failure, timeout, or partial transfer preserves a
non-accepted attempt with lifecycle and reason. Never rerun into an existing
attempt id.

For the accepted dry run, the visible/audible event is one strike of a plain,
unmarked blue wastebasket with a long, plain paper roll at approximately
`(1.15, 0.00, -0.40) m` in `F_project`. The operator and hands remain outside
the ZED field of view; only the two privacy-safe objects may appear.

## 7. Alignment annotation

Review the six-channel transient and the corresponding visible ZED event in the
retained SVO. Record one audio sample index, one ZED frame index, localization
half-widths, and whether the event is unique, audible, and visible. Do not use
the waveform chirp as visual evidence and do not use SSH launch proximity.

Generate bounded-memory review candidates first; these never auto-accept:

```text
PYTHONPATH=src .venv/bin/python scripts/s4_2_alignment_candidates.py \
  <attempt-root>
```

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 \
  annotate-alignment <attempt-root> \
  --audio-sample-index <sample> \
  --zed-frame-index <frame> \
  --audio-half-width-samples <samples> \
  --zed-half-width-frames <frames> \
  --event-unique --event-visible --event-audible
```

The tool reports `zed_event_elapsed_s - audio_event_elapsed_s` and root-sum-
square uncertainty. More than 50 ms, a missing modality, or ambiguity rejects
the attempt. Passing alignment supports only coarse association and metrics
whose margin exceeds the reported uncertainty.

Finalize only after annotation:

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 finalize \
  <attempt-root>
```

## 8. Evidence and machine-local validation

Retain accepted and failed attempt directories under `dataset/S4.2/`. Do not
delete partial Pi or workstation producer output. The final tracked evidence
index lists every raw artifact, its local relative path, SHA-256, byte size,
media properties, and acquisition contract. Verify the local dataset with:

```text
PYTHONPATH=src .venv/bin/python scripts/validate_s4_2_integrity.py \
  --index outputs/isaac_audio_sensors/S4/S4.2/evidence_index.json \
  --require-machine-local
cd dataset/S4.2
sha256sum -c SHA256SUMS
```

A missing local artifact, size/hash mismatch, corrupt manifest, or semantic
failure rejects S4.2 on this workstation. The raw dataset is not replicated,
independently retrievable, or available from a fresh clone. Workstation loss
may make the raw evidence unavailable; tracked hashes do not replace it.

The clean-checkout reproduction gate requires an explicitly authorized frozen
commit. It verifies the implementation, schemas, deterministic WAV,
tracked-manifest coverage, and integrity contracts; it does not require
gitignored recordings. Do not commit, tag, or push merely to run the live take;
request authorization after all intended S4.2 files and evidence are ready.
