# S4.4 prospective data-expansion amendment 03

Status: **acquisition complete; Fit B is complete and the prospective holdout
is complete, technically sealed, and scientifically unopened. S4.5-S4.8
remain unstarted.**

This specification was the prospective acquisition contract frozen at the v5
source checkpoint. Its precollection and capture-boundary wording below is
historical. The authoritative current state is
`docs/development/closeouts/S4/s4_4_data_expansion_amendment_03_holdout.md`.
Amendment 03 awaits only the additive corrective software and final-gate
closeout; no capture or holdout scientific opening is authorized by that
corrective.

Amendment 03 is an additive continuation of immutable
`s4_4_data_expansion_amendment_02`. It does not edit, regenerate, delete,
reclassify, overwrite, or mark amendment_02 superseded in place. Its separate
continuation record inherits the completed amendment_02 Fit A session by exact
path, byte size, SHA-256, planned-cell mapping, attempt census, and retained
attempt identities. Amendment_01 remains immutable historical NO-GO evidence.
Assignments, access histories, seals, and blindness claims remain separate.

## Logical design and inheritance

The aggregate logical matrix remains exactly 149 cells:

- 51 completed amendment_02 Fit A cells, inherited without copying, renaming,
  reassigning, regenerating, or allocating new paths;
- 51 completed amendment_03 Fit B cells with new `s44a03` identities and paths;
- 47 completed amendment_03 prospective-holdout cells with new `s44a03`
  identities and paths.

Inherited Fit A contains 52 retained attempts for 51 valid logical cells: 32
controlled, 12 confidence, 3 silence, and 4 audio-video. Attempt
`s44a02_fit_a_048_av__attempt_01` remains the sole invalid protocol-quality
attempt. Its retained replacement
`s44a02_fit_a_048_av__attempt_02` remains the sole valid take for that cell.
Every inherited cell is complete and immutable, so no additional attempt is
allowed and no replacement allowance is reset.

The new Fit B and holdout manifests preserve the exact amendment_02 scientific
condition matrices, sequence, grouping, leakage rules, durations, positions,
bearings, radii, gains, repetitions, sources, impact identity, modality
bundles, replacement limit, and fit/holdout separation. Fit B preserves its
frozen reverse radius ordering and low-to-high confidence-gain order. The
holdout preserves its exact ordering and counterbalance. No parameter fitting,
thresholding, profile application, holdout scientific inspection, or
S4.5-S4.8 work is part of this amendment.

## Prospective calendar policy

Fit A, Fit B, and prospective holdout may share the same truthful local
calendar date. Dates and timezone-aware local/UTC timestamps remain mandatory,
and Fit B and holdout session IDs remain distinct. Fit A, Fit B, or prospective
holdout may each continue across more than one local calendar date without
changing its session or group identity. A date segment is not a new session or
group. Each active local-date segment requires its own truthful preflight
and separate hash-bound no-media readiness record before any attempt is
allocated on that date; an earlier segment's records remain retained and must
not be overwritten or re-dated. Fit B and holdout remain separate acquisition
sessions/groups with separate preflight/readiness histories. Amendment_03 Fit A
is already complete and inherited, so this policy creates no new Fit A
preflight, path, or attempt. The holdout remains a
separate protected partition even if collected on the same date.

Removing distinct-day separation reduces protection against day and
environment confounding. This limitation must remain in later reporting and
does not authorize merging sessions, groups, access histories, or blindness
claims. Historical amendment_01 and amendment_02 date claims remain unchanged.

## Prospective live readiness

Amendment_03 does not require a reboot, device restart, power cycle, USB
disconnect/reconnect, SSH reconnect, or any hardware state change performed
solely to satisfy protocol. Its exact preflight check is
`live_connectivity_and_readiness`; the historical
`device_restart_or_reconnection` field is neither required nor accepted.

For the historical acquisition, a no-media readiness gate verified:

- deliberate external-network permission plus live SSH connectivity to the
  Mac and Raspberry Pi;
- the intentionally reduced Mac readiness report: read-only collection and
  truthful AC-or-battery power source, charging state, and battery percentage;
  legacy reports may retain extra identity, output, volume, mute, OS, focus,
  notification, or reference-WAV fields, but those fields are optional
  historical data and are not readiness gates;
- separately hash-bound operator declarations, including the recorded physical
  setup observations, without treating those declarations as Mac-generated
  identity/output/reference checks;
- Pi helper availability and hash plus its exact `record` subcommand and
  required-argument contract;
- ReSpeaker identity, firmware, device, six-channel 16 kHz S16_LE format,
  channel order/health, disk space, and the exact unused safe output path for
  the next planned-cell attempt;
- ZED identity, firmware, USB, image, depth, IMU, and tracking readiness where
  applicable;
- clocks and truthful session timestamps;
- room, environment, mount, coordinate frame, origin, bounds, and physical
  operator confirmations;
- privacy, Git-ignore protection, output/access paths, policy, and separate
  access-ledger state.

Readiness starts no recorder, playback, ZED capture, or scientific media. A
failure is retained under the session readiness-failure root before allocation
and consumes no planned-cell attempt. Once allocated, every attempt and
failure remains retained and no cell may exceed one replacement. All
SSH-dependent readiness and capture commands require deliberate external
network permission. Every passed readiness record is hash-bound to the exact
next attempt ID, and attempt allocation rejects a stale or differently bound
readiness record.

Battery operation is prospectively permitted. Readiness must still collect and
retain the truthful power source, charging state, and battery percentage; a
missing, malformed, or fabricated power report fails closed. This does not
change any scientific condition, take identity, ordering, or replacement rule.

## Holdout and access boundary

Prospective-holdout technical QA remains restricted to identity; the
carried-forward assigned-metadata declaration; duration; six-channel count;
absence of a detected silent-channel issue where that predicate applies;
clipping; producer timestamp presence; playback-record presence or a
not-required state; integrity/checksums; the carried-forward privacy
declaration; and full SVO2 replay. These names describe the existing
predicates and do not add stronger acquisition or scientific criteria. Legacy
v1 QA records remain immutable and are validated through the documented v2
canonical projection. Scientific outputs remain suppressed. Unknown paths,
records, purposes, grants, groups, missing or altered hashes, malformed data,
and seal or ledger mismatches fail closed.
S4.5-facing access remains fit-only. Access histories and blindness claims are
not merged. Enforcement remains repository-tool-only and is not OS-level
protection. No future holdout-opening workflow is implemented.

## Historical commit and collection boundary

The deterministic builder emits the inherited Fit A inventory, future Fit B
and holdout manifests, aggregate logical index, access policy, evidence index,
source checkpoint, and precollection seal. If source enforcement is corrected
after collection begins, the same amendment may add a new evidence-package
version that binds the earlier package and every retained attempt at an exact
cutoff; it must not replace the earlier package, change planned identities, or
create a new amendment. Two isolated builds must be byte-identical. Before Fit
B capture, the implementation owner reports all amendment_03 and inherited
hashes and proves both predecessors unchanged, then stops for explicit
authorization before the source commit and again before the
precollection-evidence commit. No push is authorized.

Only after both commits and all post-commit validators/build/audits pass may
the real Fit B readiness gate run outside the restricted sandbox. It performs
checks only and is followed by a separate physical operator confirmation.
Attempt allocation remains prohibited until committed, sealed, validated,
readiness-passed, and explicitly confirmed.

The acquisition conditions are now satisfied: inherited Fit A, Fit B, and the
prospective holdout are complete under the unchanged replacement rules; the
holdout is technically sealed and scientifically unopened; and all 152
attempts remain retained. Final S4.4 PASS additionally requires the additive
corrective validator and repository gates to pass. S4.5-S4.8 remain unstarted.
