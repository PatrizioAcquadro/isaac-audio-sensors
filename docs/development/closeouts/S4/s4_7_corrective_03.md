# S4.7 corrective_03 closeout

**S4.7 corrective_03 PASS — ready for independent review before S4.8.**

## Corrective result

Corrective_03 restores the frozen scientific contract without changing any of
the 23 readiness or six stretch thresholds, the claimed envelope, scientific
eligibility, the unopened 47-take holdout, or its seal. It preserves every
valid corrective_01 and corrective_02 restriction.

The evaluator now requires the exact 159 keyed windows for every A and B take.
It independently derives:

- median circular absolute window error per take for bearing readiness and
  sim-versus-real;
- the existing repository median valid-window bearing for frozen within-cell
  repeatability;
- the unique most-frequent valid-window sector for B-sector correctness.

Missing, duplicated, unknown, non-finite, out-of-domain, inconsistent, or
all-abstained bearing windows fail closed. Reported summaries must exactly match
their derived values.

## Reproduced semantic bypass

Four affected and four conforming B takes reproduce the old shortcut:

- incorrect summary calculation: `4.5 deg`, sector accuracy `1.0`;
- frozen window calculation: `19.5 deg`, sector accuracy `0.50`.

The frozen limits are `15 deg` and `0.75`, so both readiness criteria fail and
the corrective_03 evaluator reports `readiness_passed=false`.

## Exact scientific authentication

The 29-item effective criteria register is generated from the hash-bound v1
criteria and exact corrective_03 resolutions. It authenticates criterion
identity, tier, gating, metric, statistic, comparator, threshold, denominator,
strata, sample kind, observable, failure logic, complete scientific contract,
and the permitted machine-readable resolution. Arbitrary effective prose and
changed methods or observables are rejected.

The S4.8 consumer requires the canonical corrective_03 prerequisite and its
scientific-semantics hash. Corrective_01 and corrective_02 prerequisites are
stale for the active consumer. No grant is created or consumed here.

## Evidence and provenance

The canonical 18-file package is:

`outputs/isaac_audio_sensors/S4/S4.7_corrective_03/`

It is generated from source commit
`93bb3a5fe9c1c903e5037c277995fb419b75df00`.

Principal SHA-256 values:

- package manifest: `6cfbb31bd4d96fb1138aa7ecb09156b550eadeed247fafb24d4e555d6361112f`;
- prerequisite: `9f266432f2045e858b8f52ba6dd1f69f401bfd445df73e4ab25775ad59ecefd9`;
- evidence index: `b188ce8083c158e9f0a1c826592cfff56ce4ae665e781b34288e484b37d6650a`;
- criteria register: `64e9fc170e81174f975d5d67b7ce94b765f967b3826e5e7cd61746ab59e25375`;
- semantic register: `91c12a090102c7b1de6c250f5edd654620d845c5f1044c8ca466961f8756539d`.

Clean-source replay compares all 18 files byte for byte and reauthenticates the
exact semantic register.

## Phase boundary

Holdout scientific observations accessed: zero. Raw holdout data accessed:
false. Grant created or consumed: false. S4.8 or later phase started: false.
Push performed: false. Tag created: false.
