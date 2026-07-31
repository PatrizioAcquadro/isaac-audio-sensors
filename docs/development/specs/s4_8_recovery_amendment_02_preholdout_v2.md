# S4.8 Recovery Amendment 02 pre-holdout protocol revision v2

## Status and scope

This additive revision supersedes the unexecuted 47-take design in
`configs/s4_8_recovery_amendment_02.v1.json` with an exactly 37-take design.
It does not rewrite that file, either terminal S4.8 package, any preliminary
campaign, or any other historical/frozen artifact.

The v2 protocol is frozen for precollection. The committed precollection seal
permits collection only through the one-take official controller. It does not
authorize a take by itself and authorizes no holdout evaluation access, grant
creation or consumption, scientific evaluation, artifact deletion, push,
release, or later-phase work.

## SquadBot direction contract amendment

This revision aligns the future S4.8 decision with the active SquadBot ASN v2
contract without changing the package's stable eight-sector public API.
`F_project` already uses the required `0 degrees = forward`,
clockwise-positive convention.

The primary directional metric is categorical SquadBot direction accuracy:

- `[315, 360)` and `[0, 45)` degrees map to front, serialized as `forward`;
- `[45, 165)` degrees map to `right`;
- `[165, 195)` degrees are rear/ambiguous and serialize as unavailable
  `"None"` while the numeric bearing remains internal diagnostic data; and
- `[195, 315)` degrees map to `left`.

Exact boundary ownership is therefore `45 -> right`, `165 -> "None"`,
`195 -> left`, and `315 -> forward`. A missing, invalid, uncalibrated, or
untransformed estimate emits no direction field. An active front/right/left
abstention is incorrect for categorical accuracy; rear/ambiguous and silence
are expected to be unavailable. Continuous-bearing error and the inherited
eight-sector result remain diagnostic and non-gating for this revision.

The categorical result is aggregated exactly once per take. The unchanged
exact-window analyzer derives `estimated_bearing_deg_f_project` as the linear
median of the valid, non-abstained window bearings. The SquadBot mapping above
is then applied once to that authenticated representative bearing; there is no
second per-window category vote. No valid representative produces unavailable
direction. That is incorrect for an active front/right/left take and is the
expected direction state for rear/ambiguous and silence, provided the take has
not failed. A failed or missing planned take is adverse regardless of its
direction availability, so a no-valid-window analysis failure cannot pass a
rear or silence case.

The primary accuracy threshold is the already-preregistered `0.75`; no numeric
threshold was selected from the engineering results. The frozen S4.7
corrective_03 criteria register is preserved byte-for-byte. Its continuous
bearing criteria and former stratum-B eight-sector accuracy criteria are
retained as historical/diagnostic definitions but do not gate this amended
SquadBot-facing protocol.

## Exact 37-take design

| Stratum | Takes | Design |
|---|---:|---|
| `A_controlled_boundary_sweep` | 24 | 0, 45, ..., 315 degrees × 3 repetitions at nominal level |
| `B_center_nominal_level` | 4 | front occlusion, right noise, rear noise, left occlusion |
| `C_center_low_level` | 4 | front, right, rear, left at low volume |
| `D_silence` | 3 | beginning, middle, and end |
| `E_impact_audio_video` | 2 | one take for each retained impact scenario |
| **Total** | **37** | |

All planned source bearings are simple multiples of 45 degrees. The 24 repeated
nominal takes use `0`, `45`, `90`, `135`, `180`, `225`, `270`, and `315`
degrees in `F_project`. The four product-condition takes and four low-volume
takes use the cardinal `0`, `90`, `180`, and `270` degree placements. Every
active source take uses radius `0.8 m`. Nominal, occlusion, and noise takes use
gain `0.75`; low-volume takes use gain `0.35`.

The 15 leakage groups remain eight repeated direction conditions, four
product-bearing conditions shared by challenged and low-volume takes, one
silence condition, and two A/V-impact conditions.

The historical stratum identifiers are retained for denominator and evidence
continuity; their v2 meanings are defined by the manifest and this amendment.
Software boundary tests cover `165` and `195` degrees exactly, while the
physical plan stays at easy-to-place 45-degree increments.

## Direction repeatability acquisition

The three repetitions for a direction bearing are adjacent in the manifest
and must be acquired consecutively in the same session. Each repetition is a
new, independent take.

Between repetitions:

1. stop playback;
2. stop recording;
3. move the Mac slightly away from the just-used placement;
4. reposition the Mac at the exact required `0.8 m` radius and bearing;
5. verify the placement;
6. start the next independent recording and playback.

The microphone/ZED rig remains fixed throughout. These repetitions measure
short-term, same-session full-setup repeatability, including source removal
and repositioning; they are not three segments from one continuous recording.

## Frozen physical and device contract

The Mac is `MacBookPro18,1`, powered on with truthful battery/charging state;
battery operation is allowed. Output is `MacBook Pro Speakers`, 48 kHz stereo,
system volume 70%, and unmuted. Active placements use `F_project`, radius
`0.8 m`, `z=-0.135 m`, a 90-degree lid angle, and the same general heading as
the ZED. Cartesian positions are derived deterministically as
`x=r*cos(bearing), y=r*sin(bearing), z=-0.135`. Placement tolerance is
`0.02 m` and bearing-reference tolerance is 5 degrees.

The ReSpeaker identity is serial `114993701261100454`, firmware `2.08`,
six-channel PCM16 at 16 kHz. The ZED 2i identity is serial `39011785`, HD720
at 30 FPS with `PERFORMANCE` depth mode. The rig remains fixed.

Occlusion uses the declared rigid two-box occluder to fully block Mac-to-rig
line of sight without touching either. Noise uses the phrase
`Audio pilot check, one two three, direction test.` twice, overlapping the Mac
reference from the same target direction. Impact sources are at
`[0.8,-0.2,-0.135]` and `[0.8,+0.2,-0.135]`; a plain-paper roll strikes the
blue wastebasket at 5, 10, and 15 seconds with no speech, faces, displays, or
unrelated personal information in the capture volume. Silence and impact
takes keep Mac playback off. Silence has no source placement and all deliberate
sources are removed or silent.

## Denominators, metric roles, and thresholds

The v2 denominator adapter is
`configs/s4_8_recovery_amendment_02_denominators.v2.json`. It binds the frozen
corrective_03 criteria register and changes only counts implied by the new
design:

- all-take denominators: `37`;
- raw-channel/take records: `148` (`37 × 4`);
- stratum B: `4`;
- strata A+B: `28`;
- paired nominal/low-gain center conditions: `4`;
- stratum E: `2`.

The stratum-A take denominator (`24`), direction-bearing cell denominator
(`8`), direction cell/pair denominator (`48`), inherited criterion set,
comparators, and every numeric scientific threshold remain unchanged. The
metric roles and applicability are amended: categorical direction is primary
and gating, while continuous-bearing error is diagnostic and non-gating. Null
window- or metric-derived denominators remain null.

For the amended directional decision, the 28 stratum A+B takes form the
categorical denominator: seven front, ten right, seven left, and four expected
rear-unavailable takes. The four low-volume takes are diagnostic for
availability/robustness, the three silence takes require unavailable output,
and direction is not applicable to the two impact takes.

At the unchanged `take_failure_rate <= 0.1` threshold, the denominator is now
all 37 planned takes and never shrinks to the number successfully processed.
Missing, rejected, corrupt, or failed planned takes therefore remain adverse
outcomes.

The second four-case preliminary confirmation remains technical evidence for
the unchanged devices, gains, `0.8 m` geometry, silence/A/V cases, acquisition
gates, and raw-validity assumptions. Its old continuous-bearing decision is not
carried forward as a gating result. The v2 preregistration binds the
machine-local readiness file by SHA-256, records that it was produced against
the former 47-take count, and keeps it uncounted and ineligible as official
holdout evidence.

## Final precollection freeze and one-take boundary

`freeze-official` binds the exact 37 identities and order, this protocol,
device configuration, preliminary-readiness evidence, disjoint unseen
partition, clean committed source checkpoint, physical preflight, official
session manifest, and precollection seal. The preflight is non-acquiring and
must explicitly record recorder, playback, and ZED recording as not started.
The amendment-04 observation root and official ledger must be empty at freeze.

`run-official-take --validate-only` returns the exact next identity, attempt,
and physical setup without allocating an attempt, creating authorization, or
starting hardware. `authorize-official-take` accepts only explicit user
confirmation `go` and binds the session and seal hashes, current ledger head,
exact take identity and definition hash, attempt number, source revision, and
authorization identity. Any ledger append makes it stale.

`run-official-take` consumes one exact authorization and then stops after one
attempt. It never retries or continues automatically. Every raw capture,
journal, technical report, clearance, seal, authorization, official wrapper,
controller failure, and ledger record remains in place. `PASS` advances one
position. `RETRY_REQUIRED`, including a post-allocation controller failure,
retains the take and increments its attempt number; a fresh `go` is required.

The postcollection holdout seal and unseen-holdout binding remain absent until
all 37 takes finish. Evaluation remains `no_go` until those artifacts,
37-take evaluator binding, independent review, and separate evaluation
authorization exist.
