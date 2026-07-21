# S4.2 acquisition tool and runbook specification

Status: **frozen before accepted-take evidence** on 2026-07-20 and amended,
before any accepted capture, by
`s4_2_pre_capture_acceptance_amendment.v1.json`.

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
| ReSpeaker | XVF3800, serial `114993701261100454`, USB descriptor firmware `2.08` |
| ReSpeaker capture | ALSA `hw:CARD=Array,DEV=0`, six channels, 16,000 Hz, `S16_LE`, interleaved PCM |
| ReSpeaker channel order | 0 Conference, 1 ASR, 2 raw microphone 0, 3 raw microphone 1, 4 raw microphone 2, 5 raw microphone 3 |
| ZED | ZED 2i, serial `39011785`, SDK `5.4.0`, camera firmware `1523`, sensor firmware `777` |
| ZED mode | HD720 at 30 FPS, PERFORMANCE depth, meters, right-handed Y-up camera coordinates |
| ZED outputs | SVO2 plus frame JSONL containing image/depth/IMU/device timestamps and tracking pose/state |
| Mac | `MacBookPro18,1`, macOS `26.5.2` build `25F84`, `MacBook Pro Speakers` |
| Playback | `/usr/bin/afplay -v 1.0 <reference.wav>`; system output volume 63%; unmuted |
| Bounded take | 20 s nominal; accepted range 15-60 s |

The acquisition configuration and current Mac preflight must match these values
before hardware acquisition starts. Unknown or changed channel order,
coordinate convention, fixture identity, device identity, firmware, output
device, volume, mute, balance, power, reference hash, or physical state rejects
the take.

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

Configuration and required metadata are semantically validated before any
device probe. The tool then checks local and remote free space, SSH access,
ReSpeaker identity/format/availability, ZED/GPU/USB/device settings, Mac
preflight, reference WAV identity, and output nonexistence.

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

The current Mac report must establish AC power, 63% volume, unmuted built-in
output, centered left/right balance, Work Focus/notification suppression, mono
off, background sounds off, and the system/UI-sound procedure. A field that the
helper cannot read remains an explicit manual check and cannot be inferred.

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
  requested frames, duplicate/nonmonotonic device or pose timestamps, pose
  timestamps older than one observed frame interval, or repeated image-content
  signatures across more than two advancing device timestamps (stale frames);
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
