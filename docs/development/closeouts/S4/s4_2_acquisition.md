# S4.2 closeout - synchronized practical acquisition

Status: **NO-GO pending frozen-commit validation**. The maintained acquisition
path and one real accepted hardware take exist, but release-archive and clean
checkout gates intentionally remain blocked until the operator authorizes the
required frozen commit. This document does not authorize or start S4.3.

## Accepted take

The accepted attempt is
`s4_2_20260721T002805Z_accepted_candidate_004`, retained only under the
gitignored machine-local archive `dataset/S4.2/`. It records 20.000 seconds of
six-channel ReSpeaker audio at 16 kHz PCM S16_LE, a ZED 2i HD720 30 FPS SVO2,
and 602 JSONL records containing image signatures, sampled depth, IMU, device
and host timestamps, and tracking pose/state. The capture gate, media
validation, checksums, Mac playback, Mac preflight, and practical alignment all
pass.

The event was one visible and audible impact on a blue wastebasket bearing a
white recycling symbol, using a long plain paper roll. The descriptive symbol
correction was recorded after acquisition without changing the predeclared
method, position, or threshold. The approximate event position was
`(+1.15, 0.00, -0.40) m` in `F_project`. Manual review confirmed no person,
hand, label containing private information, screen, or other personal data in
the retained review frames.

The audio transient is at sample 234417, or 14.6510625 s after audio start. The
corresponding ZED observation is frame 450 at 15.000842 s after ZED capture
start. The reported offset is:

```text
ZED elapsed time - ReSpeaker audio elapsed time = +0.349779500 s
```

The conservative uncertainty is 37.326716 ms, below the frozen 50 ms maximum.
Its components are one audio sample (0.0625 ms), audio localization (1.000 ms),
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

The accepted Mac preflight records Work Focus active, notifications suppressed,
MacBook Pro Speakers selected, volume 63 percent, unmuted output, centered
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
accepted take. Playback used `/usr/bin/afplay -v 1.0` at fixed system volume 63
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
- `mac_preflight_focus_inactive_20260720T235809Z`: Work Focus was inactive, so
  the preflight failed and was retained before the operator activated Focus.
- Two earlier Pi firmware-representation failures under the tracked S4.2
  output evidence were retained while the expected representation was made
  explicit; neither is accepted hardware evidence.

## Evidence retention and limitations

The authoritative machine-readable index is
`outputs/isaac_audio_sensors/S4/S4.2/evidence_index.json`. Its checksum manifest
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

## Pending final gate

The targeted S4.2 suite passed with 61 tests and one explicit hardware-gated
skip. The full suite passed with 1171 tests and 79 genuine optional-dependency
or explicit hardware skips. `make lint`, `make build`, `make check-version`,
and `make audit-dist` passed. `build-kit` and `build-pack` correctly refused the
dirty source tree, so their audits and the required clean-checkout validation
remain pending rather than being relabeled as passes.

After explicit commit authorization, freeze the complete S4.2 candidate,
construct and audit the kit and acoustic pack from that clean revision, run the
raw-independent S4.2 integrity contract in a clean checkout, then bind those
results in a final gate record. S4.2 remains NO-GO until that sequence passes.
