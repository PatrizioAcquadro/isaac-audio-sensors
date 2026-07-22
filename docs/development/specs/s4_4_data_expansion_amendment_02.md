# S4.4 prospective data-expansion amendment 02

Status: **prospective precollection; capture prohibited until the exact
amendment_02 source checkpoint and evidence package are committed**.

Amendment 02 is an independent replacement acquisition plan after
`s4_4_data_expansion_amendment_01` reached irreversible NO-GO on 2026-07-22.
The original S4.4 freeze and every amendment_01 source, manifest, attempt,
hash, seal, evidence, access-history state, and closeout byte remain immutable.
The additive amendment_01 NO-GO closure is historical evidence only. Its
assignments, attempts, access history, and blindness claims are not inherited
or merged.

## Scientific contract

The resolved machine-readable authority is
`configs/s4_4_data_expansion_amendment_02.v1.json`. It hash-binds the complete
amendment_01 configuration as its scientific base, then changes only the
amendment identity and isolated retention roots. Consequently amendment_02
preregisters the same 149 scientific cells, exact order, coordinates,
bearings, radii, gains, repetitions, durations, grouping/leakage rules,
replacement limit, S4.1-S4.3 identities, privacy contract, and fit/holdout
separation: 51 Fit A, 51 Fit B, and 47 prospective holdout cells. All planned
take, attempt, manifest, group, seal, evidence, dataset, ledger, and holdout
identities are new `s44a02`/amendment_02 identities.

No parameters are fit and no S4.5-S4.8 work is started. The prospective
holdout remains scientifically unopened and has its own future technical QA,
seal, and append-only access ledger. Repository-tool enforcement does not
provide OS-level protection against the filesystem owner.

## Correct pre-attempt lifecycle

Session readiness is outside the planned-cell attempt lifecycle. Before any
attempt directory is allocated, the committed amendment_02 seal, the inherited
same-day operator/session preflight, and one self-hashed amendment_02 readiness
record must pass. The readiness record uses no recorder, playback, SVO2
capture, or scientific media and verifies:

- explicit external-network execution authorization plus Mac and Pi SSH;
- valid full and dynamic Mac-helper JSON, exact Mac identity, built-in stereo
  48 kHz output, 40% unmuted volume, AC power, and exact reference WAV;
- the Pi helper's non-recording preflight, exact helper hash and `record`
  command contract, ReSpeaker identity/firmware/USB/device, frozen six-channel
  16 kHz S16_LE/channel-order contract, disk space, and safe unused output root;
- the existing non-recording ZED identity/firmware/USB/GPU/image/depth/IMU/pose
  preflight;
- same local date, inherited clocks/environment/privacy/operator checks,
  ignored output roots, and the separate access policy.

Invalid, empty, or unreachable helper output is retained under the session's
`readiness_failures/` directory and consumes no planned-cell attempt. A passed
readiness record is bound to the committed precollection seal and its inherited
preflight hash. Attempt allocation fails closed if either hash changes.

After allocation, every failure remains an attempt. Attempt 02 is permitted
only after attempt 01 has a frozen technical failure; a second failure makes
amendment_02 NO-GO. Scientific outcomes never drive replacement.

All SSH-dependent readiness and capture invocations must be deliberately run
with the execution environment's external-network permission. The exact
permission confirmation is provenance, not a substitute for actual passing
connectivity and helper JSON.

## Freeze and collection boundary

The deterministic builder must reproduce byte-identical amendment_02 trees.
The precollection seal binds the new manifests, identities, policies, source
checkpoint, and immutable amendment_01 NO-GO closure. Capture is denied until
that checkpoint and the evidence-delivery commit exist and all validators pass.
After commit, the real no-media readiness gate is rerun. Physical Fit A begins
only after a separate exact operator confirmation.
