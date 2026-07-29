# S4.8 stratum-aware physical engineering campaign

## Status and authority

This is the supported engineering-only acquisition contract for the one
complete 47-take physical S4.8 rehearsal. It creates no grant, consumes no
grant, opens no holdout, runs no official state machine, and publishes no
official evidence.

The rehearsal uses new engineering identities under `s48eng_rehearsal_`.
The consumed amendment-03 holdout manifest supplies only the already-frozen
47-cell order and pairing metadata. No consumed observation, take result,
timestamp, bearing, or scientific outcome is used for acquisition decisions.

## One campaign anchor

Before collection, one campaign manifest binds:

- the exact clean Git commit and reproducible source archive;
- hashes of the controller, gates, configuration, schemas, and helpers;
- Python, dependency, workstation, Raspberry Pi, Mac, ReSpeaker, and ZED
  identities;
- the exact original reference WAV hash;
- the deterministic continuous-playback asset hash;
- unchanged v2 gate and detector configuration hashes;
- the six-channel device profile and channel map;
- all 47 engineering take definitions in their frozen order;
- the retry policy and operational output roots.

Any change to code, configuration, reference WAV, continuous asset,
environment, device profile, channel map, or protocol invalidates the campaign
anchor and requires a new snapshot and restart from take 1.

## Stratum-aware acquisition modes

The 47 cells retain the frozen 24/8/8/3/4 design:

| Stratum | Takes | Supported acquisition mode |
|---|---:|---|
| A controlled boundary sweep | 24 | exact reference playback |
| B center nominal level | 8 | exact reference playback |
| C center low level | 8 | exact reference playback |
| D silence | 3 | ambient-silence capture |
| E impact audio/video | 4 | three-cue impact plus ZED capture |

A/B/C use the existing v2 recorder, playback, process journal, waveform
sentinels, pre-sealing report, clearance, and candidate-seal interlock without
changing scientific or technical thresholds.

D never starts playback and never fabricates playback events. Its
non-reference journal records the actual silence interval. Its pre-sealing
gate uses the unchanged v2 device, PCM16, frame, repeated-buffer, channel
duplication/crosstalk, clipping, polarity/gain, and channel-map integrity
checks, plus the exact 15-second frame count. It reads no reference or
scientific outcome.

E never starts reference playback and never fabricates playback events. It
records the actual ZED process and three operator impact cues at 5, 10, and 15
seconds. Before clearance it requires the same unchanged capture-integrity
checks, at least three candidates from the already-frozen S4.3 transient
detector, authenticated ZED identity/mode/timestamps/output hashes, and a full
SVO2 replay. Scientific audio-video association remains a post-capture
readiness criterion and is not fitted or relaxed here.

## Exact reference compatibility

The authenticated reference remains the original mono PCM16 48 kHz WAV with
SHA-256
`27929826ae179faf5adb1aa2759ed302a0cd6163b3ec8324325e7cdf0b143468`.
The physical ReSpeaker capture remains six-channel PCM16 16 kHz.

The file wrapper deterministically normalizes the authenticated reference to
the capture rate only when the source-to-capture rate is an exact integer
ratio. Each output sample is the mean of one non-overlapping source-rate
block. The original file hash remains the provenance identity; the normalized
array is not substituted as a new reference artifact.

For continuous A/B/C playback, the supported builder tiles exact PCM frames
from the original reference into one finite 18-second asset without inserting
gap samples. The derived asset and construction metadata are frozen in the
campaign manifest. The v2 gate continues to authenticate the original
reference and requires unchanged start/stop sentinels, useful-sound coverage,
continuity, alignment, and drift limits.

The Mac playback helper is authenticated and armed before the scheduled
playback time. It emits an actual remote `playback_started` handshake only
after launching `afplay`, then retains the remote completion status and
standard error. The controller therefore journals playback launch rather than
SSH connection latency.

The Pi producer's authenticated start and completion monotonic timestamps
define the capture duration. The local recorder-ready observation anchors
that duration in the controller journal; SSH startup and post-capture file
transfer latency are never represented as waveform duration.

The playback host power policy is frozen as `battery_allowed`. The preflight
retains the collector's measured power source and battery percentage without
rewriting them. Work Focus may be accepted from machine evidence or from an
explicit operator confirmation recorded in the preflight acceptance object;
the collector's contradictory Focus and notification fields remain preserved.

## Retry and sealing policy

Every attempt is appended to one hash-chained ledger. A planned cell receives
attempt 1. Only a retained `RETRY_REQUIRED` permits attempt 2. The sequence
advances only after `PASS`, and no third attempt is permitted. A configuration
or protocol change restarts the entire campaign.

`RETRY_REQUIRED` creates no clearance or candidate seal. A PASS clearance is
bound to the exact campaign, take definition, capture, applicable ZED hashes,
process-journal head, report, and unchanged configuration hashes. Clearance is
single-use and can create only an engineering candidate seal.

No capture, journal, report, clearance, manifest, result, or seal may be
manually edited. All operational media and records remain outside the
repository.
