# S4.2 acquisition tool and runbook specification

Status: **frozen before accepted-take evidence** on 2026-07-20 and amended,
before any accepted capture, by
`s4_2_pre_capture_acceptance_amendment.v1.json`.

Remediation acceptance was frozen before the replacement capture on 2026-07-21
in `s4_2_remediation_acceptance.v1.json`. It invalidates the former S4.2 pass
because attempt `s4_2_20260721T002805Z_accepted_candidate_004` did not contain
the complete reference playback. That attempt and its original lifecycle are
retained unchanged; `remediation_reclassification.json` records its current
failed scientific disposition.

This specification implements only the `S4.2` row of
`s0_squadbot_readiness_acceptance.md`. It does not define or collect the S4.3
experimental matrix. Passing S4.1 and the S2.2 atomic-writer contract are entry
requirements.

## 1. Scope and topology

One bounded dry run records six-channel ReSpeaker audio locally on
`elab-raspberrypi5`, ZED 2i image/depth/IMU/pose observations locally on the
Ubuntu workstation, and controlled reference playback on the MacBook reached
through the existing `patrizios-macbook` SSH alias.

The physical paths are frozen as:

- ReSpeaker XVF3800 -> USB -> Raspberry Pi 5;
- ZED 2i -> verified rear workstation USB 3 port;
- workstation -> SSH -> Raspberry Pi and MacBook; and
- MacBook Pro built-in speakers -> room -> installed fixture.

SSH command launch times and round-trip observations are diagnostics only. They
are never synchronization evidence. Both capture hosts record locally. A
visible and audible impact inside the ZED field of view is the practical
cross-system alignment event.

## 2. Frozen identities and capture settings

| Item | Frozen value |
| --- | --- |
| Fixture | `S4_TEMP_DESKTOP_FIXTURE_REV0` on its marked footprint |
| Project frame | `F_project`: origin at the ZED stereo-lens midpoint; +X forward with the ZED view, +Y to the operator's right while facing the camera (the ZED camera's left), +Z up; positive bearing counterclockwise from +X toward +Y viewed from above |
| ReSpeaker | XVF3800 marketing model; USB product descriptor `reSpeaker XVF3800 4-Mic Array`, serial `114993701261100454`, USB descriptor firmware `2.08` |
| ReSpeaker capture | ALSA `hw:CARD=Array,DEV=0`, six channels, 16,000 Hz, `S16_LE`, interleaved PCM |
| ReSpeaker channel order | 0 Conference, 1 ASR, 2 raw microphone 0, 3 raw microphone 1, 4 raw microphone 2, 5 raw microphone 3 |
| ZED | ZED 2i, serial `39011785`, SDK `5.4.0`, camera firmware `1523`, sensor firmware `777` |
| ZED mode | HD720 at 30 FPS, PERFORMANCE depth, meters, right-handed Y-up camera coordinates |
| ZED outputs | SVO2 plus frame JSONL containing image/depth/IMU/device timestamps and tracking pose/state |
| Mac | `MacBookPro18,1`, macOS `26.5.2` build `25F84`, `MacBook Pro Speakers` |
| Playback | `/usr/bin/afplay -v 1.0 <reference.wav>`; system output volume 40%; unmuted |
| Bounded take | 20 s nominal, `+/-0.25 s` WAV-duration tolerance; accepted configured range 15-60 s |

The acquisition configuration, stable-session Mac preflight, and per-take Mac
dynamic report must match these values before acquisition starts. Unknown or
changed channel order,
coordinate convention, fixture identity, device identity, firmware, output
device, volume, mute, balance, power, reference hash, or physical state rejects
the take.

### 2.1 Validation-profile boundary

The take configuration contains the explicit profile
`ias.s4.validation_profile.v1` with id
`s4_2_controlled_dry_run_v1`. The profile makes the following requirements
strict for S4.2 without turning them into universal S4 invariants.

| Rule | Classification | S4.2 profile | Later S4 contract |
| --- | --- | --- | --- |
| Corrupt/truncated files, hashes, schemas, units, frames, lifecycle, declared channel/device contract, and forged derived reports | Universal integrity invariant | Required | Always required for every artifact/stream that is declared present |
| Host/device timestamps | Universal integrity invariant | Strictly monotonic | Strictly monotonic for every present stream; an absent optional stream is not fabricated |
| 20 s WAV and 0.25 s tolerance | S4.2 controlled dry run | Exact with tolerance | Declared per trial; may be exact, minimum, or another preregistered duration |
| Complete 9.5 s reference, correlation 0.03, two raw channels | S4.2 controlled dry run | Required | Declared stimulus and metric-specific detector; may be absent for silence, impact-only, voice, or other source trials |
| Playback overlap and 2 s margin | S4.2 controlled dry run | Required | Declared when a playback stimulus is required; not applicable to trials without playback |
| Full SVO2 SDK replay | Universal integrity invariant for a take that declares an SVO2 artifact | Required before acceptance during offline finalization | Required before acceptance, either offline finalization or batch validation |
| SVO2/JSONL exact frame equality and representative image/depth/IMU/pose | S4.2 controlled dry run | Exact and all modalities | Frame correspondence and representative modalities declared by the trial contract |
| Every-frame valid `pose_status == OK` and fresh pose/IMU | S4.2 controlled dry run | Required | Metric-specific; absence invalidates pose/IMU-dependent metrics, not unrelated declared metrics |
| 50 ms alignment uncertainty | S4.2 controlled dry run | Required | Preregistered per metric; not applicable when no cross-modal metric is claimed |
| Mac identity/volume and fixed source/room/fixture | S4.2 controlled dry run | Exact profile | Exact for repeatability cells, declared variation for controlled/robustness trials |
| Silence and sustained clipping quality disposition | Configurable per trial/metric | All channels nonsilent; sustained clipping rejects | Silence may be the intended stimulus; clipping may be retained as failed/robustness evidence under an explicit metric policy |

A required modality cannot be paired with a disabled validator. Profile
validation rejects that contradiction before hardware access. Later S4 trials
must declare required modalities, duration/stimulus policies, replay/frame
correspondence, pose/IMU needs, alignment gates, and controlled-versus-varied
source/environment fields before capture. Missing optional data remain explicit
and invalidate metrics that require them; they never become a silent pass.

## 3. Controlled reference waveform contract

`s4_2_reference_v1.0.0.wav` is copyright-free CC0 project-generated evidence:

- mono PCM WAV, 48,000 Hz, signed 16-bit little-endian;
- 9.500 s and exactly 456,000 samples;
- 1.000 s initial silence;
- 0.250 s Tukey-ramped 900-3,600 Hz linear synchronization chirp;
- 1.000 s silence;
- 5.000 s seeded broadband segment, xorshift32 seed `0x5A17C4E3`,
  fixed-coefficient 250-6,500 Hz band limiting, and conservative amplitude;
- 1.000 s silence;
- the same 0.250 s final chirp; and
- 1.000 s final silence.

Generator semantic version is `ias.s4_2.reference_generator.v1`. The generator
uses no random system state. Regeneration must reproduce the tracked SHA-256,
byte size, sample properties, RMS, peak, and segment table. Exact command:

```text
PYTHONPATH=src .venv/bin/python scripts/generate_s4_2_reference_wav.py \
  --output outputs/isaac_audio_sensors/S4/S4.2/reference/s4_2_reference_v1.0.0.wav \
  --metadata outputs/isaac_audio_sensors/S4/S4.2/reference/reference_wav.json
```

The Mac copy is accepted only after `shasum -a 256`, `afinfo`, and the tracked
read-only Mac preflight all agree with the frozen record.

## 4. Preflight and required operator record

Configuration and required metadata are semantically validated before hardware
access. A named stable-session preflight runs the full read-only Mac inventory
and `nvidia-smi` once. Its immutable report is bound to the exact configuration
hash and is invalidated by a setting change, disconnection, recorder startup
error, or operator-reported change. Mac connectivity is observed by that real
preflight command; Pi connectivity is observed by the real recorder SSH
command. There are no separate three-round-trip SSH timing probes.

Immediately before every take, the tool checks local disk and runs only the
read-only Mac dynamic checks for selected output, volume, mute, and AC power.
The real Pi recorder verifies ReSpeaker USB identity, firmware, free space, and
the actual partial WAV header (six channels, 16 kHz, S16_LE) before it reports
ready. The real ZED recorder opens the camera once, verifies identity, SDK,
firmware, USB 3 and requested mode, then successfully retrieves image, depth,
IMU, and valid pose from that same instance before enabling SVO2 and reporting
ready. Per-take depth retrieval is the authoritative GPU-access check. A
separate `arecord` probe, ZED open/close cycle, or per-take `nvidia-smi` is
forbidden. The workstation validates both readiness payloads fail-closed.

The operator must record, in meters and degrees in `F_project`:

- the MacBook speaker-center position `(x, y, z)`;
- distance from the defined rig origin and counterclockwise bearing from +X
  toward +Y, viewed from above;
- speaker height, MacBook yaw/pitch/roll, lid angle and screen/lid state;
- front/behind/left/right placement;
- marked-footprint, unchanged-fixture, clear-FOV/microphones, and safe-cable
  confirmations;
- room occupancy and relevant noise sources; and
- every temporary Mac audio-setting change.

No photograph substitutes for a measurement. The accepted scene must contain
no person, label, credential, private screen, or other personal data.

For the accepted dry-run configuration, the corrected source record is
`(0.000, +0.900, -0.135) m`, with explicit deltas in the same units, a derived
straight-line distance of approximately `0.910 m`, and canonical bearing
`+90 deg` counterclockwise. Speaker-center height is `0.710 m`; vertical-offset
uncertainty is `+/-0.010 m`. The Mac base is approximately `yaw/pitch/roll =
0/0/0 deg`, flat on the desk, with an approximately `90 deg` open lid and the
screen facing the same general direction as the ZED. These orientation values
are a practical placement class, not angular metrology, and the built-in
speaker acoustic radiation axis is not measured or claimed.

The stable-session Mac report must establish 40% volume, unmuted built-in
output, centered left/right balance, Work Focus/notification suppression, mono
off, background sounds off, and the system/UI-sound procedure. Every take then
rechecks selected output, volume, mute, and AC power dynamically. A field that
the helper cannot read remains an explicit manual check and cannot be inferred.
For Work Focus and notification suppression only, the operator confirmation is
authoritative until the operator reports a change. These fields are recorded as
`operator_confirmed`; a conflicting automatic observation is preserved as a
non-blocking warning rather than treated as automatic verification. Every other
preflight mismatch remains fail-closed.

The operator first requested 30% after the failed remediation attempt at 63%
was judged too loud. That retained 30% take failed the unchanged raw-channel
reference-correlation gate. Before the next take, the operator authorized an
exact 40% predeclared setting. The reference WAV and every correlation, overlap,
duration, clipping, and alignment threshold remain unchanged. The operator
strikes immediately when `ALIGNMENT EVENT NOW` is issued; playback remains a
separate step beginning after the frozen two-second interval.
The retained failed 40% attempt showed that the first strike was not visible at
30 FPS. Before the next take, the operator confirmed the basket's standard white
recycling symbol is not a private label and approved a visible-strike procedure:
the paper roll enters the image and strikes once at `ALIGNMENT EVENT NOW`, then
remains visible for an operator-self-timed 1.5 s. The operator removes it
without waiting for a second chat message; playback starts at the frozen 2.0 s
target, 0.5 s after the scheduled removal target. Hands and body stay outside
the image. The scheduled removal timestamp is not mislabeled as an automatic
observation of the physical removal.

## 5. Lifecycle and atomicity

Every invocation receives a unique attempt id and creates a new directory.
Existing directories are never reused or overwritten. Normalized configuration,
lifecycle, logs, JSONL, manifests, checksums, validation, and alignment records
use the S2.2 `StagedFile`, `JsonlShardFile`, and `write_json_atomic` primitives.
Large SDK- or device-produced files remain under an attempt-local staging
directory until their producer closes them, their format is inspected, and
they are atomically promoted.

Lifecycle states are `preflight`, `recording`, `finalizing`, `accepted`,
`rejected`, `failed`, or `interrupted`. Every transition contains UTC wall time,
timezone-aware local time, and host monotonic time where meaningful. Failed,
rejected, interrupted, and partial attempts remain present with exact reasons.
The Pi WAV is retrieved only after the remote recorder exits and finalizes it.
Child and remote processes receive bounded graceful shutdown followed by a
recorded forced-stop failure if required.

Interactive operator readiness is resolved after the lightweight per-take
preflight and before either bounded recorder starts. After both actual
producers report verified ready, the frozen schedule is 3.0 s to
`ALIGNMENT EVENT NOW`, an operator-self-timed 1.5 s visible hold/removal target,
then 0.5 s to playback. The chat-cue acknowledgment and scheduled removal target
retain wall and monotonic timestamps, deadlines, and scheduler error. The
scheduled target is explicitly unobserved operator timing. The 2.0 s
cue-to-playback interval,
at most 11.0 s for the 9.5 s `afplay` interval including declared playback
tolerance, and 2.0 s post-playback margin are unchanged. The configured
35.0 s duration includes a fail-closed 15.0 s chat-ack reserve and must contain
the 33.0 s worst-case post-readiness schedule. An acknowledgment after 15.0 s
rejects the attempt without playback. Both recorder
processes must be alive before playback, after playback, and after the margin.
The retained ZED host-monotonic records must bracket the workstation playback
envelope. These observations do not synchronize the Pi or Mac clocks.

When the operator receives instructions through chat, the maintained
`--chat-cue-handshake` mode is required. After verified recorder readiness and
the frozen 3.0 s lead, acquisition pauses. The assistant sends the exact
`ALIGNMENT EVENT NOW` cue as a chat message and immediately acknowledges it
through the acquisition PTY; the acknowledgment wall/monotonic timestamp and
its basis are retained. Tool notifications and buffered terminal text are not
operator action cues. Under the operator-authorized self-timed procedure, the
operator removes the roll 1.5 s after the chat cue without waiting for a second
chat turn. Acquisition records the scheduled target as unobserved and launches
playback at the frozen 2.0 s target. The retained audible/visible event, not
chat transport timing, determines final cross-system alignment and uncertainty.

## 6. Practical alignment and frozen uncertainty gate

After both recorders report ready and before playback, the operator performs
one sharp hand clap or visible impact approximately 1 m in front of the rig,
inside the central ZED field of view and without entering the retained frame.
The impact object and location are recorded. Playback begins only after that
event.

The audio transient sample index is selected from the six-channel WAV and the
corresponding visible-impact ZED frame/device timestamp is selected from the
SVO/frame record. Offset is:

```text
offset_s = zed_event_elapsed_s - audio_event_elapsed_s
```

Positive offset means the selected ZED observation is later than the selected
audio transient relative to its own capture start. Combined uncertainty uses
root-sum-square of:

- one audio sample (`1 / 16000 s`);
- audio-localization half-width supplied by the annotator;
- half one observed ZED frame interval;
- ZED visual-event localization half-width; and
- any separately measured clock/readout quantization term.

The accepted total must be finite and no greater than **50 ms**. The event must
be unique and unambiguous. Missing, multiple plausible, visually absent, or
inaudible events reject the take. This supports coarse audio-video association
and metrics whose decision margin is greater than the reported uncertainty. It
does not support sample-accurate synchronization, acoustic time-of-flight,
absolute capture latency, calibrated extrinsics, or attribution of the offset
to either host clock.

## 7. Frozen semantic and integrity gates

The validator rejects, without repair or coercion:

- missing, wrong-count, reordered, swapped/unknown-order, silent, malformed,
  truncated, wrong-rate, wrong-format, or sustained-clipping audio;
- any channel with RMS below `1.0` PCM16 count or at least 250 ms continuously
  at or above `0.999` full scale;
- missing/empty SVO, image/depth/IMU/pose retrieval failures, fewer than 90% of
  requested frames, duplicate/nonmonotonic host-wall, host-monotonic, device,
  IMU, or pose timestamps, invalid pose state/data, pose or IMU timestamps older
  than one observed frame interval, or repeated image-content signatures across
  more than two advancing device timestamps (stale frames);
- an SVO2 that cannot be replayed from beginning to end by ZED SDK 5.4.0 during
  offline finalization, whose
  serial/mode/frame count differs from the JSONL record, or whose first, middle,
  or penultimate representative image/depth/IMU/pose retrieval fails;
- ReSpeaker WAV duration outside `35.0 +/- 0.25 s`, recorder/playback overlap
  that does not contain the full playback and margin, or fewer than two raw
  microphone channels matching the complete deterministic reference at
  normalized correlation `0.03`;
- missing/stale device identities, USB 3/GPU/SDK failure, insufficient disk,
  SSH/device loss, interruption, partial transfer, or checksum mismatch;
- corrupt JSON/JSONL, missing schema/version/units/frame fields, invalid frame
  names, unsafe units, or incomplete required metadata;
- missing/mismatched reference WAV or Mac report; changed output, volume, mute,
  balance, AC-power, Focus/notification, or relevant processing state;
- missing/ambiguous alignment or uncertainty above 50 ms; and
- changed/unsafe physical setup, fixture identity, room record, or operator
  confirmation.

Sustained clipping is frozen at 250 ms, not a single isolated full-scale sample.
Silence is checked per channel. Channel identity/order is a metadata and device
contract check; the validator never reorders samples to make a take pass.
During finalization, the alignment offset and uncertainty are recomputed from
the retained WAV sample index and ZED JSONL frame/device timestamps. Stored
derived values or a stored `status: passed` never satisfy the gate by
themselves.

## 8. Evidence and machine-local retention contract

The tracked index covers this spec, its pre-capture amendment, runbook,
implementation, Mac helper and accepted report, generator/WAV/metadata,
validators/tests/configuration, attempt manifest, validation/alignment/gate
records, closeout, checksums, and every retained raw artifact. Covered content
changes invalidate the corresponding integrity check.

S4.2 raw evidence is retained only under the gitignored repository-relative
root `dataset/S4.2/` on this workstation. Each raw record contains its role,
local relative path, byte size, media properties, SHA-256, and acquisition
contract. Every retained attempt, including failures and partial attempts, is
verified in place by checksum and semantic validation. Existing attempts are
never overwritten, repaired, reordered, silently replaced, or deleted.

This S4.2-specific policy deliberately does not require or claim off-machine
storage, replication, independent raw retrieval, or raw availability from a
fresh clone. Workstation loss can make all raw S4.2 recordings unavailable;
hashes and tracked manifests do not make absent raw data independently
reviewable. The clean-checkout gate verifies implementation, schemas,
deterministic waveform regeneration, tracked manifests, and integrity
contracts without requiring ignored recordings. On this workstation, a
separate gate requires every indexed `dataset/S4.2/` artifact to exist and
match its recorded checksum and semantics. This pre-capture amendment does not
modify later-phase or release-wide archive policy.

## 9. Pass boundary

S4.2 passes only after one real accepted dry run, all planted fault classes,
machine-local raw integrity, evidence coverage, deterministic regeneration,
clean-checkout contract integrity, and every repository command required by
the acceptance request pass. Hardware unavailability is blocked, not skipped
or synthetically passed. The closeout must explicitly state that S4.3 was not
started and that raw recordings are machine-local only.
