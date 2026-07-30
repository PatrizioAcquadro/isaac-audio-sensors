# S4.8 Recovery Amendment 02 pre-holdout protocol revision v2

## Status and scope

This additive revision supersedes the unexecuted 47-take design in
`configs/s4_8_recovery_amendment_02.v1.json` with an exactly 37-take design.
It does not rewrite that file, either terminal S4.8 package, any preliminary
campaign, or any other historical/frozen artifact.

The v2 protocol is prepared but not frozen. It authorizes no acquisition,
holdout access, grant creation or consumption, scientific evaluation,
artifact deletion, push, release, or later-phase work.

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

## Final-freeze boundary

The v2 machine-readable manifest, denominator adapter, schemas, and validator
must all pass before a final-freeze decision. A later freeze must bind the
exact 37 planned identities and the v2 unseen-holdout binding schema before
official acquisition can begin.

Worktree validation may report the protocol design ready for a final-freeze
decision, but official pre-open validation must not attribute that revision to
a source commit until the commit contains byte-identical v2 config, manifest,
schemas, specification, validator, and CLI files. Until then no candidate
grant identity is emitted.

This revision deliberately exposes no freeze, acquisition, grant, opening, or
evaluation operation. The 37-take evaluator binding, independent review, exact
candidate source identity, sealed-unopened holdout binding, and explicit
operator authorization remain later gates.
