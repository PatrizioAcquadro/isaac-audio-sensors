# S4.3 Corrective Contract 02: Prospective Transient Boundary Support

Status: corrective contract to be frozen before one new prospective silence
capture. This record does not edit, replace, or reinterpret any corrective-01
file, raw attempt, analysis, report, failure, or unfavorable observation.

## Defect reproduction

At clean baseline commit
`1d0b93d95860bc88450d925f98d58d229e59c552`, four-channel synthetic signals
active from sample zero or through the final sample were evaluated at 0.0021
and 0.0025 full scale against the frozen 0.002 RMS floor. All four regression
cases failed before the production correction because corrective-01 returned
one complete internal event and zero boundary-censored excursions.

For a 48,000-sample interval, the observed false internal runs were:

| Edge | Amplitude | Start | Exclusive stop | Incorrect event count |
| --- | ---: | ---: | ---: | ---: |
| sample zero | 0.0021 | 131 | 2,270 | 1 |
| sample zero | 0.0025 | 45 | 2,356 | 1 |
| final sample | 0.0021 | 45,731 | 47,870 | 1 |
| final sample | 0.0025 | 45,645 | 47,956 | 1 |

The versioned reproduction record retains the baseline implementation hash,
test hash, command, exit status, and exact cases. Production code was unchanged
until this failure was demonstrated.

## Exact even-window support

The detector retains a 320-sample per-channel RMS envelope implemented with
`numpy.convolve(square, ones(320) / 320, mode="same")`. NumPy's `same` slice
for this even kernel aligns output center index `j` with the half-open raw
support

`[j - 160, j + 160)`,

or raw indices `j - 160` through `j + 159` inclusive. Thus the window has 160
samples on the lower-index side and 159 samples after the labeled center
sample. No arbitrary 10 ms boundary guard is introduced.

For a recorded interval of `N` samples, a center has complete support exactly
when

`160 <= j < N - 159`.

Equivalently, the complete-support center interval is the half-open range
`[160, N - 159)`. A bridged connected excursion represented by half-open
center indices `[start, stop)` is boundary-censored when

`start < 160` or `stop > N - 159`.

This rule evaluates the actual RMS support required by every qualifying or
bridged center in the connected excursion. A censored excursion is retained as
a boundary diagnostic and is not counted as a complete transient event.

## Preserved detector semantics

Corrective-02 changes only the boundary-completeness classification. It
preserves the four declared raw channels, 16 kHz sample rate, 320-sample RMS
window, 0.002 full-scale floor, median plus eight robust-standard-deviation
adaptive threshold, two-channel concurrence, one-time bridging of bounded gaps
through 1,600 samples, 160-sample minimum duration, 16,000-sample maximum
transient duration, stationary and short-excursion classifications, event-rate
denominator, and independence from reporting-window overlap.

An equivalent fully interior connected excursion remains one event. A
stationary, short, insufficient-concurrence, over-duration, or gap-separated
excursion retains its corrective-01 classification unless incomplete RMS
support requires boundary censoring first.

## Scientific prospectivity

The exact support rule changes the frozen prospective detector's boundary
classification. Already-inspected recordings cannot confirm corrective-02.
Corrective-01 and its accepted trial
`s4_3_rob_silence_02_prospective_events_01` remain immutable and retain their
original measured result of zero events in 15 seconds under contract 01.

After corrective-02 configuration, contract, preregistration, implementation
hashes, and matrix hash are frozen and locally committed, exactly one new
15-second intended-silence trial is required:
`s4_3_rob_silence_03_boundary_support_01`. It confirms only corrective-02. No
overlap or unrelated trial may be repeated. Every attempt is retained. No
device setting change is authorized.

## Gate semantics and limitations

Corrective-02 provenance fails closed if its specification, configuration,
contract, supersession, preregistration, implementation bindings, matrix,
prior corrective-01 bindings, support fields, or new prospective result are
missing or inconsistent. Reports must show corrective-01 and corrective-02
prospective results separately with their contract hashes and trial IDs.

The result remains functional digital room-fixture-sensor characterization,
not absolute SPL, microphone self-noise, certified acoustic metrology, or a
population event rate. S4.4 remains unstarted.
