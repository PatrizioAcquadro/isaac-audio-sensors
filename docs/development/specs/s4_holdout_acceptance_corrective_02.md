# S4.7 corrective_02 effective acceptance specification

## Authority and phase boundary

This additive corrective is the authoritative S4.7 execution contract. It
supersedes corrective_01 without modifying S4.7 v1 or corrective_01 sources or
evidence. All 23 readiness thresholds, six stretch thresholds, the claimed
controlled-source single-room single-mount envelope, and scientific eligibility
remain unchanged.

The machine-readable authority is
`configs/s4_7_holdout_acceptance.corrective_02.v3.json`. It remains bound to the
same unopened 47-take amendment-03 prospective holdout, seal, S4.7 baseline,
and inherited S4.1-S4.6 provenance. No holdout observation is opened by this
corrective. No S4.8 grant is created or consumed and no later phase starts.

Historical packages are immutable:

- `outputs/isaac_audio_sensors/S4/S4.7/` contains exactly the preserved v1
  16-file package;
- `outputs/isaac_audio_sensors/S4/S4.7_corrective_01/` contains exactly the
  preserved corrective_01 18-file package.

## Exact identities and denominators

The tracked technical session manifest is the only take-identity source. The
evaluator projects exactly 47 identities, including each target bearing, from
that hash-bound manifest. Missing, duplicate, unknown, mismatched, non-finite,
or internally inconsistent records fail closed.

The effective denominators are:

- 24 A takes, eight B takes, eight C takes, three D takes, and four E takes;
- exactly 32 A+B conditions for bearing sim-real analysis;
- 40 bearing-referenced takes only when B+C confidence analysis participates;
- one latency summary per each of all 47 takes;
- four raw microphone channels per take, 188 channel records total;
- six microphone pairs per A take, 144 take-pair records total.

## Observation-bound derivations

Caller-supplied summaries cannot override keyed source observations.

- The target bearing is authenticated by the technical take identity.
- The reported bearing error must equal the circular absolute difference
  between target and estimated bearing.
- The reported B-sector result must equal
  `bearing_deg_to_sector_name(estimate) == bearing_deg_to_sector_name(target)`.
- Candidate coverage must equal whether any emitted candidate is within the
  frozen 20 degree circular tolerance of the target.
- A reported take failure must equal whether its failure-reason list is
  non-empty.
- Each reported absolute TDOA error must equal the absolute difference between
  its matching measured and reference TDOA observations.
- The abstention comparison is derived from each matching take's authenticated
  source and abstained window counts: active A+B uses the abstained fraction;
  silence D uses the non-abstained fraction.
- Confidence is taken from the matching keyed B/C take.
- Each reported AV residual must equal the absolute difference between its
  matching E-take audio and video event times.

Per-condition sector and candidate results are exactly boolean and become
numeric 0 or 1 only during aggregation. Fractions such as 0.5 are invalid.

The sim-real payload supplies only keyed unadjusted and adjusted simulation
values. The real path is deterministically derived from the corresponding
authenticated take record or take-pair record. A redundant caller-supplied
`real` value is forbidden and fails closed, including when it disagrees with
otherwise valid keyed take data.

## Clipping semantics

The maximum clip run is the maximum over all 188 channel records; it is not a
total. The unchanged independent readiness threshold is at most eight samples.

Sustained clipping begins only at 4,000 consecutive samples on any raw channel
of a take. Runs of nine or 3,999 samples are not sustained. A run of 4,000
samples is sustained. The sustained-clipping denominator is exactly 47 takes.

## Effective criteria register

The corrective_02 evidence generator resolves every inherited v1 criterion
into an effective register. Each entry preserves the frozen criterion ID,
tier, gating flag, metric, statistic, comparator, threshold, denominator, and
failure logic while replacing ambiguous or contradictory execution prose with
the corrective_02 source-observation, denominator, and clipping semantics in
this specification.

The effective register contains exactly 23 readiness and six stretch entries.
It is generated from the hash-bound v1 thresholds plus the corrective_02
semantic resolution. Historical v1 and corrective_01 registers are not
modified.

## Semantic evidence authentication

The canonical package is
`outputs/isaac_audio_sensors/S4/S4.7_corrective_02/`; its only canonical S4.8
prerequisite is `holdout_acceptance.json` in that directory.

Authentication validates the exact schema and field set of every report, every
passing status, all identities, source/seal/count/phase claims, evidence-index
and SHA-256 closure, source and evidence commits, and deterministic
byte-for-byte replay. Every report used by a passing prerequisite must itself
be semantically passing.

A package is rejected even after its indexes and checksums are regenerated and
committed if an inner report has a wrong schema, failed status, contradictory
source or seal identity, contradictory count or phase data, nonzero holdout
access, or any later phase marked started. Replay output must be byte-identical
to the committed package.

The S4.8 grant consumer accepts only this canonical corrective_02 prerequisite
and requires the grant to bind its exact authenticated identity. This
corrective does not create such a grant.
