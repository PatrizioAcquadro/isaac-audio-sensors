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

Stand in front of and face the ZED. Physical instructions use
`F_operator_facing_zed` first: +X is behind you/in front of the ZED, -X is in
front of you/behind the ZED, +Y is to your right, -Y is to your left, +Z is up
toward the ceiling, and -Z is down toward the floor. Bearing is clockwise from
+X toward +Y viewed from above. `F_project` has the same origin and +X/+Z, but
+Y is right as viewed from the ZED. Convert with `x_project=x_operator`,
`y_project=-y_operator`, `z_project=z_operator`, and
`bearing_project=(-bearing_operator) mod 360`.

1. Put the MacBook at the intended controlled-source position. Do not move the
   rig to make measurement easier.
2. Identify the approximate center between the left and right built-in speaker
   regions as the source point.
3. From your viewpoint while facing the ZED, measure from the ZED stereo
   midpoint to that point. Record the operator-facing `(x,y,z)` first, then the
   converted canonical `F_project` position in parentheses.
4. Record source distance as `sqrt(x^2 + y^2 + z^2)` meters. The validator
   allows only 0.02 m difference between position and declared distance.
5. Record horizontal bearing from your viewpoint first: behind you/in front of
   the ZED `0 deg`, your right `90 deg`, in front of you/behind the ZED
   `180 deg`, and your left `270 deg`. Then record canonical `F_project`
   bearing in parentheses: in front of the ZED `0 deg`, the ZED's right (your
   left) `90 deg`, behind the ZED `180 deg`, and the ZED's left (your right)
   `270 deg`.
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
  --expected-sha256 27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468 \
  --expected-volume-percent 40
```

Expected `shasum` is
`27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468`.
`afinfo` must report WAVE, one channel, 48,000 Hz, Int16, and 9.500000 s.

The helper is read-only and redacts personal identifiers. The workstation
collects the full report once through the named stable-session preflight in
Section 5; do not repeat it before every take.

## 4. Mac settings immediately before an accepted take

Keep Work Focus active and notifications suppressed. Confirm built-in `MacBook
Pro Speakers`, stereo 48 kHz output, 40% system volume, unmuted output, AC
power, mono audio off, background sounds off, and centered left/right balance.

For S4.2, the operator's explicit Work Focus and notification-suppression
confirmation is authoritative until the operator reports a change. Record both
fields as `operator_confirmed`. The helper's automatic Focus observation is
retained; a conflicting or unavailable automatic result is a non-blocking
warning and is never relabeled as automatic verification. This exception does
not apply to any other preflight field.

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

The sound between the chirps is the intentional deterministic seeded broadband
test segment, not an uncontrolled disturbance. At `ALIGNMENT EVENT NOW`, show
the paper roll and strike once immediately. Keep it visible for a self-timed
1.5 seconds, then remove it without waiting for another chat message. Reference
playback begins at the frozen two-second impact-cue-to-playback target. Do not
wait for a chirp or any other signal.

The object is the blue wastebasket with its standard white recycling symbol and
no private label. Prepare the paper-roll tip just outside the image. At the cue,
immediately sweep it into view, strike the camera-facing rim or side once, keep
it visible for a self-timed 1.5 seconds, then withdraw it. Hands and body remain
outside the image.

## 5. Complete and validate the acquisition configuration

Copy `configs/s4_2_acquisition.v1.json` to a take-specific configuration. Fill
all null physical and preflight fields and explicit confirmations. Do not edit
frozen device, waveform, mode, channel-order, room, frame, evidence-policy, or
threshold values, including the `s4_2_controlled_dry_run_v1` validation profile.
That profile is deliberately stricter than future per-trial S4 profiles.

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 validate-config \
  <take-config.json> --require-ready
```

This command must pass before any capture hardware is touched. The only raw
root is `dataset/S4.2/`; off-machine storage is unauthorized. The validator
requires the pre-capture acceptance amendment and explicit acknowledgment that
the raw data are gitignored, unreplicated, vulnerable to workstation loss, and
unavailable from a fresh clone.

Create the stable-session preflight once after deployment and after confirming
that the stable hardware/settings state is established:

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 session-preflight \
  <take-config.json>
```

This runs the full Mac preflight and `nvidia-smi` once and writes the configured
immutable session report. After any setting change, disconnection, recorder
startup error, or operator-reported change, use a new session id and new report
paths. Record an operator-reported invalidation explicitly:

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 \
  invalidate-session-preflight <take-config.json> --reason '<exact reason>'
```

## 6. Bounded acquisition

The orchestrator validates metadata, reference, and the immutable stable-session
report; checks local disk; and runs only the Mac dynamic selected-output,
volume, mute, and power checks. It then asks for operator readiness **before**
starting either bounded producer. There are no repeated SSH timing probes,
separate `arecord` probe, separate ZED open/close, or per-take `nvidia-smi`.
Mac connectivity is proven by the real dynamic preflight and Pi connectivity by
the real recorder command. SSH timing remains diagnostic only.

```text
PYTHONPATH=src .venv/bin/python -m isaac_audio_sensors s4-2 run \
  <take-config.json> --interactive-cue --chat-cue-handshake
```

At the first warning, from your viewpoint while facing the ZED put the impact
object behind you/in front of the ZED at
`F_operator_facing_zed (1.15, 0.00, -0.40) m`
(`F_project (1.15, 0.00, -0.40) m`) while keeping
hands, face, labels, and screens out of the ZED field of view. Press Enter only
when the scene is clear and the impact can be performed without another setup
delay. The bounded recorders start only after that Enter. After both report
ready, the tool waits the frozen 3.0-second lead and arms the chat barrier. At
the assistant's `ALIGNMENT EVENT NOW` chat message, the operator immediately
shows the roll, performs exactly one sharp impact, self-times 1.5 seconds, and
removes the roll without waiting for another chat message. Playback starts at
the frozen 2.0-second target. The chat acknowledgment and scheduled removal
target wall/monotonic timestamps are retained; the target is explicitly not an
automatic observation of the physical removal. Do not perform another similar
impact, touch the Mac, or generate UI sounds.

For a chat-operated take, only the assistant's exact `ALIGNMENT EVENT NOW` chat
commentary message is an action cue. Tool notifications and terminal output are
not cues. The command pauses once after recorder readiness; the assistant sends
the chat cue and acknowledges it through the PTY. The operator self-times the
1.5-second hold/removal and does not wait for a second chat message. Playback
launches at the frozen +2.0-second target. The PTY acknowledgment is retained as
a practical cue observation; the scheduled removal target is marked unobserved,
and final alignment comes from the retained audio transient and visible frame.

The 35 s recorders stop automatically. The frozen schedule includes a 15.0 s
fail-closed chat-ack reserve, up to 11.0 seconds for the complete 9.5-second
`afplay` command, and a further 2.0-second recorder margin. A chat
acknowledgment later than 15.0 s rejects the attempt before playback. The Pi WAV
is copied only after local Pi finalization. A take is rejected if WAV duration
differs from 35.0 s by more than 0.25 s, either recorder fails to contain
playback plus margin, fewer
than two raw microphone channels match the complete deterministic stimulus at
the frozen correlation threshold, or the retained ZED host interval does not
bracket playback. Interruption, failure, timeout, or partial transfer preserves
a non-accepted attempt with lifecycle and reason. Never rerun into an existing
attempt id.

The ZED producer uses its one actual camera instance to verify identity, SDK,
firmware, rear-port USB 3 speed, HD720/30/PERFORMANCE mode, and successful
image/depth/IMU/valid-pose retrieval before reporting ready. Successful depth
retrieval is the per-take GPU check. The Pi producer reports ready only after
the actual recording process has produced a verified six-channel, 16 kHz,
S16_LE partial WAV header. A missing or false readiness field fails the take
and invalidates the stable session. Blocking full SVO2 SDK replay remains in
offline finalization; visual alignment remains the existing manual/Codex review
workflow. No automatic motion detection or background SVO validation is used.

For the accepted dry run, from the operator's viewpoint the visible/audible
event is behind the operator/in front of the ZED at approximately
`F_operator_facing_zed (1.15, 0.00, -0.40) m`
(`F_project (1.15, 0.00, -0.40) m`): one strike of a plain, unmarked blue
wastebasket with a long, plain paper roll. The operator and hands remain outside
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

Finalization reopens and replays the SVO2 through the ZED SDK, validates the
complete WAV/reference overlap, host/device/IMU/pose timestamps and states, and
recomputes alignment from the retained WAV/JSONL. It rejects a forged or stale
alignment report even if that report says `status: passed`.

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
