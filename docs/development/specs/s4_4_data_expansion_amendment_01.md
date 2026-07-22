# S4.4 prospective data-expansion amendment 01

Status: **prospective precollection implementation; capture prohibited until the exact precollection package is committed**.

This is a versioned amendment to S4.4 only. It does not edit, regenerate,
reassign, or supersede the original S4.4 freeze. The original SplitPlan payload
hash remains
`1569c00cbaec57e5625e0876fd243e17a2a67b287b3edf9865e41bb7ce8c0ce3`.
The original holdout is historically analyzed legacy evidence. The amendment
holdout is the primary unopened prospective holdout for later work. Their
assignments, seals, ledgers, and blindness claims remain separate.

## Scope

The amendment preregisters 149 planned cells:

- Fit A: 32 controlled, 12 confidence, 3 silence, and 4 audio-video takes;
- Fit B: 32 controlled, 12 confidence, 3 silence, and 4 audio-video takes; and
- prospective holdout: 24 controlled, 16 confidence, 3 silence, and 4
  audio-video takes.

The two fit sessions must occur on different local calendar dates. The holdout
must occur on a third date distinct from both fit dates. Precollection session
manifests deliberately use `session_date_local: null`: no calendar date is
invented before physical collection. Each session preflight records the actual
ISO date, and collection fails closed if it duplicates an earlier session date.

Future supported uses are bearing correction, relative channel gain/delay and
polarity, confidence/abstention behavior, and coarse audio-video timing. This
amendment performs none of those fits or evaluations. It does not define
parameter thresholds, apply a profile, define S4.7 criteria, run S4.8, or claim
precision geometry, isolated frequency response, absolute SPL, sensitivity,
self-noise SPL, or certified room acoustics.

## Common acquisition contract

The machine-readable authority is
`configs/s4_4_data_expansion_amendment_01.v1.json`. It binds the S4.1–S4.3
fixture, room, coordinate/bearing convention, ReSpeaker serial/firmware/channel
order/16 kHz S16_LE format, ZED identity and SVO2 replay, Mac identity, exact
reference WAV hash, 40% system volume, `afplay -v 1.0`, level keyboard, 90-degree
lid, radial speaker orientation, and source height `Z = -0.135 m`.

All target and recorded positions must remain inside X `[-1.20,+2.40]` m, Y
`[-5.00,+8.00]` m, and Z `[-0.47,+1.42]` m. Controlled and confidence takes
require the Mac to be completely removed and freshly repositioned before every
repetition. The manifest stores target coordinates derived from the exact
preregistered bearing/radius. The attempt contract separately stores the
operator's exact recorded position, bearing, and distance; tooling must not
substitute a nominal or fabricated observation.

Controlled/confidence and audio-video takes last 20 seconds; silence lasts 15
seconds. S4.2/S4.3 lead-in, tail, playback, synchronization, safety, lifecycle,
atomic-write, privacy, and all-attempt retention rules remain in force.

The audio-video cells reuse the S4.3 privacy-clean plain paper roll striking the
blue wastebasket, with impacts targeted near 5, 10, and 15 seconds. They do not
reuse or expose S4.3 scientific results.

## Deterministic order

Every session manifest contains the exact sequence, repetitions, counterbalance,
expected paths, and predecessor/successor links. Fit silence is at sequence 1,
26, and 47; holdout silence is at sequence 1, 26, and 43. The final four cells
of every session are audio-video.

Fit A performs the 0.60 m clockwise sweeps before the 1.00 m counterclockwise
sweeps, and confidence gains high-to-low. Fit B reverses the radius order and
the direction used at each radius, and uses confidence gains low-to-high. The
holdout performs three 0.80 m controlled sweeps clockwise, counterclockwise,
then clockwise. Its confidence gains are counterbalanced by bearing and
repetition parity so each bearing uses both gain orders across its repetitions.

Grouping uses exact session, room, source device/identity/type, target position,
bearing, radius, mount, and acoustic condition. Attempt ID and outcome never
participate. No group crosses fit and prospective holdout.

## Preflight, attempts, and replacements

Every session requires all configured preflight checks to pass. The record
includes the actual observations and the hash of the frozen identity contract.
Capture tooling validates the committed precollection source checkpoint and
refuses to start a recorder when it is absent, malformed, or changed.

Attempt IDs are preregistered as `__attempt_01` and, only after a technical
failure, `__attempt_02`. No third attempt exists. A replacement preserves the
same partition, session, take-definition hash, source, modality, position,
bearing, radius, gain, and protocol. Every pre-recording failure and invalid
attempt remains present. A second failure leaves the planned cell incomplete
and makes the amendment NO-GO. Scientific outcomes never authorize a
replacement.

## Prospective-holdout access

Repository tools permit holdout technical QA to persist only identity/assigned
metadata, duration, channel order/health, clipping, timestamps, reference
presence, integrity/checksums, privacy, and full-SVO2-replay pass/fail fields.
Any other fields are suppressed before persistence. Bearing, confidence,
abstention, gain, delay, polarity, audio-video performance, parameter estimates,
comparisons, media, and scientific values are never returned.

After technical QA, a separate hash-only seal may be created. S4.5-facing tools
expose fit records only. Unknown or malformed purpose/path/group/record and
missing or altered manifests, seals, hashes, or ledgers fail closed. Every
repository-tool access attempt is appended to the amendment's separate ignored
hash-chained ledger. This is repository-tool enforcement; it cannot prevent or
detect direct reads by the filesystem owner. This amendment implements no
S4.7/S4.8 opening workflow.

## Retention and reproduction

Raw media, attempts, session preflights, local grants, technical QA working
records, and the access ledger remain under the ignored
`dataset/S4.4/amendments/s4_4_data_expansion_amendment_01/` root. Tracked
metadata is generated under
`outputs/isaac_audio_sensors/S4/S4.4/amendments/s4_4_data_expansion_amendment_01/`.
The clean-checkout validator requires no raw media. Machine-local final
validation requires every planned cell, actual session date, retained attempt,
technical QA record, raw hash, final holdout seal, and ledger.

Precollection reproduction:

```bash
.venv/bin/python scripts/build_s4_4_amendment.py
.venv/bin/python scripts/validate_s4_4_amendment.py
.venv/bin/python -m pytest -q tests/test_s4_4_amendment.py tests/test_s4_4_holdout_freeze.py tests/test_s4_4_canonical_evidence.py
```

The original precollection source checkpoint and evidence package were
committed before any attempt was prepared. Capture remains fail-closed whenever
the current required checkpoint or seal is absent, uncommitted, or changed.

## Execution corrective 01

The first Fit A silence attempt was prepared but its recorder was not started:
the frozen capture plan omitted the Pi helper's required `record` subcommand,
the mandatory minimum-free-space argument, and an attempt-scoped remote path.
That attempt is retained as a technical pre-recording failure and consumes
attempt 01 for its planned cell. It contains no recording or scientific result.

The correction changes only executable acquisition orchestration. It does not
change any manifest, condition, count, order, group, partition, identity,
placement, replacement rule, or original/amendment blindness claim. A new
versioned source checkpoint and corrective precollection seal must bind the
corrected plan and executor before replacement attempt 02 may start. The
original committed precollection checkpoint and seal remain byte-for-byte
historical predecessors.

The corrective executor reuses the S4.2 Pi, Mac, ZED, transfer, atomic
promotion, WAV inspection, and full-SVO2 replay contracts. It requires the
exact corrective-seal hash and operator confirmation, reruns the Mac dynamic
gate, records producer readiness before declaring recorder start, retains
failures, transfers by checksum, and decides replacement validity solely from
technical quality. Fit QA may retain technical WAV properties. Prospective
holdout QA is passed through the existing field allowlist and suppresses all
non-allowlisted output. The executor performs no bearing, confidence,
abstention, gain, delay, polarity, audio-video performance, parameter, or
comparative analysis.
