# S4.7 held-out acceptance corrective_03

## Scope and boundary

This additive corrective restores the frozen S4.7 scientific calculations that
corrective_02 did not bind to exact analysis-window observations. It inherits
the hash-bound v1 criteria and every valid corrective_01 and corrective_02
restriction. It does not change any threshold, denominator, stratum, claimed
envelope, scientific eligibility rule, holdout identity, or seal.

The 47-take holdout remains scientifically unopened. This corrective neither
creates nor consumes a grant and does not start S4.8 or any later phase.
S4.7 v1, corrective_01, and corrective_02 evidence remain immutable; the new
package is `outputs/isaac_audio_sensors/S4/S4.7_corrective_03/`.

## Exact window observations

Every A or B take supplies exactly the frozen number of keyed analysis windows:
119 for a 15-second take and 159 for a 20-second take. Window indices are the
contiguous zero-based set. `window_id` is `window_NNN`, and `start_sample` is
`window_index * 2000`, following the frozen 250 ms, 50 percent-overlap,
16 kHz contract. Missing, duplicate, unknown, non-finite, out-of-domain, or
internally inconsistent windows fail closed.

Each window is exactly one of:

- abstained: `abstained=true` and bearing is null;
- valid: `abstained=false` and the SRP-PHAT bearing is finite in `[0, 360)`.

The reported source, abstained, and sub-floor-emission counts must agree with
the exact window records. Abstained windows are excluded from numeric bearing
statistics. An A or B take with no valid bearing window fails.

## Three independent bearing derivations

For each valid window, bearing error is the circular absolute difference from
the authenticated planned target. The per-take error is the median of those
window errors. Readiness and sim-versus-real use that derived value. A reported
per-take error, when retained, must agree exactly. The evaluator never replaces
`median(abs(window error))` with the error of a representative bearing.

The repeatability representative is independently the existing repository
analysis result: the ordinary `statistics.median` of valid SRP-PHAT window
bearings. The frozen largest-gap circular range is then applied across the
three representatives in each A cell and maximized across the eight cells.
Only the circular range, not the representative median, applies wraparound.

For each B take, valid window bearings are mapped with
`bearing_deg_to_sector_name`. A correct take requires one unique sector with a
strict majority of valid windows and equality to the target sector. No valid
windows, no strict majority, an unresolved tie, or an abstained take is
incorrect; no valid windows additionally fails the take. A reported
`sector_correct`, when retained, must agree exactly. The sector of the
representative median is never substituted for the window-sector majority.

## Scientific-semantic authentication

The effective criteria register is generated deterministically from the
hash-bound v1 criteria plus the exact machine-readable resolutions in the
corrective_03 config. Every criterion preserves and authenticates its ID, tier,
gating flag, metric, statistic, comparator, threshold, denominator, strata,
sample kind, observable, failure logic, complete scientific contract, and
permitted resolution. Arbitrary `effective_semantics` prose is not part of the
contract and is rejected.

Deterministic replay must reproduce both package bytes and this exact effective
register. The canonical S4.8 prerequisite and grant consumer accept only
corrective_03. A separate grant remains mandatory before any holdout opening.

## Preserved numerical and physical contract

All 23 readiness and six stretch thresholds remain unchanged. The comparison
registry still contains 32 A+B bearing conditions. The input has four raw
microphone channels per take. Maximum clip run remains a maximum over 188 raw
channel records with the eight-sample readiness gate. Sustained clipping
remains a run of at least 4,000 consecutive samples. All corrective_01 and
corrective_02 fail-closed identity, physical-domain, source-observation,
comparison, replay, and phase-boundary rules remain active.
