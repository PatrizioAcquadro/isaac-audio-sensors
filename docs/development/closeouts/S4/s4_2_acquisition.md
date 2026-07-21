# S4.2 closeout - synchronized practical acquisition

Status: **NO-GO pending authorized frozen-commit validation** (2026-07-21).
The maintained acquisition path and replacement real hardware take pass. The
raw-independent clean-checkout and provenance-bound Kit/pack gates still
require the operator-authorized frozen commit. This document does not authorize
or start S4.3.

## Accepted take

The replacement accepted attempt is
`s4_2_20260721T153800Z_optimized_candidate_014`, retained only under the
gitignored machine-local archive `dataset/S4.2/`. It records 35.000 seconds of
six-channel ReSpeaker audio at 16 kHz PCM S16_LE, a ZED 2i HD720 30 FPS SVO2,
and 1,052 JSONL records containing image signatures, sampled depth, IMU, device
and host timestamps, and tracking pose/state. The capture gate, media
validation, complete-reference overlap, checksums, Mac playback, Mac preflight,
full-file ZED SDK replay, and practical alignment all pass.

The event was one operator-confirmed visible and audible impact on a blue
wastebasket bearing a white recycling symbol, using a long plain paper roll.
The operator self-timed the 1.5-second visible hold/removal from the single chat
cue; playback remained scheduled at the frozen 2.0-second target. The
approximate event position was
`(+1.15, 0.00, -0.40) m` in `F_project`. Manual review confirmed no person,
hand, label containing private information, screen, or other personal data in
the retained review frames.

The audio transient is at sample 213696, or 13.356 s after audio start. The
corresponding ZED observation is frame 345 at 11.500677 s after ZED capture
start. The reported offset is:

```text
ZED elapsed time - ReSpeaker audio elapsed time = -1.855323000 s
```

The conservative uncertainty is 37.366880 ms, below the frozen 50 ms maximum.
Its components are one audio sample (0.0625 ms), audio localization (2.000 ms),
half a ZED frame interval (16.687 ms), and one-frame visual localization
(33.374 ms), combined by root-sum-square. SSH launch proximity is recorded as
a timing observation only and is not synchronization.

This association supports frame-scale correlation of the retained modalities
and comparisons whose tolerance is no tighter than the reported uncertainty.
It does not support sub-frame visual timing, precision clock synchronization,
acoustic time-of-flight calibration, metrology-grade source pose, or claims
that the workstation, Raspberry Pi, and Mac clocks share a timebase.

## Source, frame, and environment authority

`F_project` is fixed as `+X` ZED-forward, `+Y` operator-right while facing the
camera (ZED-camera-left), and `+Z` up. Positive bearing is counterclockwise from
`+X` toward `+Y` viewed from above. The Mac speaker center is
`(0.000, +0.900, -0.135) m`; canonical bearing is `+90 degrees`; the derived
straight-line distance is approximately 0.910 m. The Mac speaker-center height
is 0.710 m, vertical-offset practical uncertainty is +/-0.010 m, base
yaw/pitch/roll is approximately 0/0/0 degrees, and lid angle is approximately
90 degrees.

The pre-capture amendment explicitly preserves the earlier sign/convention
correction and confirms that no accepted capture began under the incorrect
convention. The rig remained on `S4_TEMP_DESKTOP_FIXTURE_REV0`'s marked
footprint with no component movement, clear microphone openings and ZED field
of view, safe cables, an operator-reported quiet room, and a privacy-cleared
retained scene.

The accepted Mac preflight records operator-confirmed Work Focus active and
notifications suppressed, MacBook Pro Speakers selected, volume 40 percent,
unmuted output, centered
balance confirmed manually, AC power, mono off, and Background Sounds off.
System/UI sounds and volume feedback remained enabled but were prevented by the
frozen no-trigger procedure; the operator reported no unexpected sound.

## Reference and implementation

The deterministic copyright-free reference is
`s4_2_reference_v1.0.0.wav`: mono, 48 kHz, PCM16, 9.500 s, 912044 bytes, SHA-256
`27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468`.
The tracked generator, seed, exact segment timing, statistics, provenance, and
regeneration command are in the adjacent reference metadata. The Mac copy was
verified with `shasum -a 256`, `afinfo`, and the read-only preflight before the
accepted take. Playback used `/usr/bin/afplay -v 1.0` at fixed system volume 40
percent.

The workstation CLI validates all configuration and required metadata before
hardware access, verifies disk and all three hosts/devices, records locally on
the Pi and workstation, retrieves Pi data only after finalization, computes
post-finalization hashes, writes manifests atomically through the S2.2
lifecycle primitives, preserves failures, never overwrites attempts, and
cleans local and remote children on all exits.

## Retained failures

- `s4_2_20260721T001620Z_accepted_candidate_001`: failed closed at ZED
  preflight because SDK logs contaminated the JSON protocol stream; no recorder
  readiness or impact occurred.
- `s4_2_20260721T001900Z_accepted_candidate_002`: recorders became ready and an
  impact occurred, but Mac playback failed because a float entered the remote
  subprocess argument vector. The interrupted Pi partial and ZED producer
  outputs are retained.
- `s4_2_20260721T002125Z_accepted_candidate_003`: acquisition finalized but was
  rejected because a hand appeared in the visual evidence. With explicit
  operator authorization, the two SVO2 copies and extracted PNG visual files
  were hashed in a pre-deletion record and permanently deleted. The deletion
  record and all nonvisual evidence remain; the deleted visuals are
  unrecoverable.
- `s4_2_20260721T002805Z_accepted_candidate_004`: passed its original gate, but
  remediation proved that complete reference playback and the post-playback
  margin were outside the recorder intervals. Its original lifecycle remains
  unchanged; a separate remediation disposition classifies it as failed
  historical evidence.
- `s4_2_20260721T140500Z_remediation_candidate_005`: failed because channel
  stimulus-start estimates were inconsistent.
- `s4_2_20260721T141300Z_remediation_candidate_006`: failed because the complete
  deterministic reference stimulus was not retained.
- `s4_2_20260721T141730Z_remediation_candidate_007` and
  `s4_2_20260721T142430Z_remediation_candidate_008`: failed because the visible
  alignment event was missing or ambiguous.
- `s4_2_20260721T151000Z_optimized_candidate_009`: failed before the cue because
  the marketing model was compared with the exact USB product descriptor.
- `s4_2_20260721T151000Z_optimized_candidate_010`: failed because buffered cue
  lines became visible together after the action window.
- `s4_2_20260721T151100Z_optimized_candidate_011`: failed because the terminal
  matcher delivered no compliant action cue.
- `s4_2_20260721T151300Z_optimized_candidate_012`: failed because tool
  notifications were not chat messages.
- `s4_2_20260721T152300Z_optimized_candidate_013`: failed because the second chat
  turn arrived 11.967133078 seconds after the first and both recorders ended
  before complete playback plus margin.
- `mac_preflight_focus_inactive_20260720T235809Z`: Work Focus was inactive, so
  the preflight failed and was retained before the operator activated Focus.
- Two earlier Pi firmware-representation failures under the tracked S4.2
  output evidence were retained while the expected representation was made
  explicit; neither is accepted hardware evidence.

## Evidence retention and limitations

The replacement machine-readable index is
`outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/evidence_index.json`.
Its checksum manifest
covers every indexed tracked or machine-local artifact except the index itself
and checksum file, avoiding circular self-hashes. Every retained file under
`dataset/S4.2/` has a role, byte size, media properties, SHA-256, local path,
and acquisition contract.

By the frozen pre-capture acceptance amendment, raw evidence exists only at
`<repository-root>/dataset/S4.2/`. It is gitignored, not replicated, not stored
on the Mac or another machine, not independently durable, and unavailable from
a fresh clone. Machine loss is raw-evidence loss. A clean checkout validates
the implementation, schemas and semantic validators, deterministic reference,
tracked index and contracts; it deliberately does not claim or require raw
recording retrieval. On this workstation the raw files must remain present and
pass both checksum and semantic validation.

## Final gate

The targeted S4.2 suite passed with 94 tests and two explicit hardware/real-SVO
fixture skips. The full primary-worktree suite passed with 1,204 tests and 80
genuine optional-dependency or explicit hardware skips. `make lint`,
`make build`, `make check-version`, and `make audit-dist` pass. `make audit-kit`
and `make audit-pack` report absent archives because their build targets require
a clean frozen release source; `make check-release-source` rejects the
intentionally dirty uncommitted worktree.

The current machine-readable candidate result is
`outputs/isaac_audio_sensors/S4/S4.2/remediation_20260721/candidate_repository_gate.json`.
S4.2 remains NO-GO until the operator authorizes the frozen commit, the
raw-independent clean-checkout gate passes, and provenance-bound Kit/pack
archives are built and audited from that frozen source.
