# Physical Signal Comparison

Historical Phase 06 evidence (2026-09-07). Software parity passed; raw capture
remains enabled. No gain correction, physical material calibration or general
sim-to-real claim was admitted. [[implementation_phases/06-simulated-and-real-signal-parity|Phase 06]]
owns implementation; downstream SquadBot owns hardware and campaign code.

## Method and evidence boundary

25 ReSpeaker takes (17 original, eight added), 5,440 real windows and 5,440
simulated four-channel windows. Shared Auditok threshold -40.5 dBFS, maintained
DOA, 50 ms blocks, independent per-take state; nominal unity gains and original
source WAV amplitude. Simulation is Analytic free field with no added effects.
Native/sample, serialized-observation replay, simulation round-trip and continuity
checks passed; all takes complete, no digital endpoint clipping or stream fault.

New captures: before/after 8 s ambient, three 20 s takes each at 0/90 degrees,
0.60 m radius, -0.135 m height, 56% source-device volume, declared +/-5 degree
placement uncertainty. The 15 s stimulus has silence/marker and 0/-3/-6/-12 dB
segments. A common cross-channel received origin aligns domains; it does not
measure emission latency, per-channel delay or clock synchronization.

## Decisive results

| Measurement | Real | Nominal simulation |
| --- | --- | --- |
| Original 16 source takes: median take angular error | 3.5 degrees (range 1–12) | 0.5 degrees (0–1) |
| Six new nominal source takes: median error | 2 degrees | 0 degrees |
| New 0 dB segment: median activity/resolved coverage | 100% | 98.7% |
| New -3 dB segment | 97.4% | 0% |
| New -6 dB segment | 25.6% (17.9–38.5%) | 0% |
| New -12 dB segment | 0% | 0% |

Original source windows have full activity/resolved coverage in both domains.
Median real-minus-sim channel levels are +0.17/+2.04/+0.24/+1.93 dB; ambient channel
medians -48.37/-46.84/-48.49/-47.28 dBFS. Ambient has no detected activity; nominal
simulation has digital silence, not modeled microphone self-noise. Two-channel
replay preserves front/back ambiguity instead of selecting a hidden bearing.

New physical processing p95 is 5.71–5.90 ms per 50 ms block, with zero overruns
across 2,680 post-initialization blocks. Received-reference activity onset is
96 ms median/108 ms p95 real versus 100/123 ms simulated; real offset p95 reaches
500 ms. These are detector/sample-timeline responses, not absolute acoustic
latency. Physical placement and nominal mic geometry limit angular claims.

## Rejected corrections

The prior 06.2 gain assessment did not improve DOA and admitted no gain:

| Candidate relative to ch0 | Median level residual before → after | Decision |
| --- | --- | --- |
| ch1 -1.6021 dB | 1.838 → 1.875 dB | Rejected |
| ch2 -1.2796 dB | 1.517 → 1.635 dB | Rejected |
| ch3 -1.2136 dB | 1.734 → 1.410 dB | Inconclusive; benefit CI -0.387 to 1.214 dB |

Positive relative polarity and the functional eight-azimuth mapping are supported,
but source directivity, placement, room paths and sensitivity are not isolated.
The assessment-only correction code was retired; raw and evidence remain.
Analog saturation, calibrated SPL, drift, absolute latency and frequency/angle
calibration remain unknown. No threshold/gain was fitted to improve the domain comparison.

## Reproduction and next use

Downstream `squadbot-av-phase1/outputs/phase06_2/` owns mapping/gain assessment;
`outputs/phase06_3/reference_campaign/`, `existing_comparison_final/`,
`targeted_comparison/` and `summary.md` own stimuli, takes, references, reports and
simulated sessions. The earlier `existing_comparison/` is superseded because
arbitrary historical analysis boundaries are not source onsets.

SDK regression: `tests/integration/test_signal_domain_parity.py`; original host
614 unit/contract + 282 integration + 58 release and downstream 410 tests passed.
No Isaac code changed in 06.3, so it introduced no new GPU qualification. Current
commands are downstream-owned; old detailed protocol remains at the Phase 06
path in `5cfe48d`. [[implementation_phases/09-practical-realism-and-randomization|Phase 09]]
should address level/noise/threshold sensitivity from these bounded findings,
not presume the missing physical cause or apply a fitted correction.
