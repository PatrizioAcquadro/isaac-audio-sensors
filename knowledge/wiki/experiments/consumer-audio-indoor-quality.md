# Consumer Audio Indoor Quality

Measured 2026-10-09 in the separate `PatrizioAcquadro/audio-indoor-quality`
worktree, from common baseline `6c65a69`. The main checkout and parallel
`audio-runtime-performance` checkout were not switched or modified. Historical
[[experiments/consumer-audio-dynamic-quality|dynamic-quality evidence]] remains intact.

**Outcome:** a bounded single-voice indoor profile exceeds 90% complete direction
sets in every declared static/source-motion/receiver-rotation/joint condition and
every tested confirmation episode. Multisource indoor readiness remains open:
the filter can remove real overlapping voices, particularly weaker ones.
It is opt-in; historical defaults and the free-field direct profile remain available.
Neither physical transfer nor 7.2 runtime qualification is established here.

## Diagnosis and targeted alternatives

The existing direct 200 ms path fits frequency-normalized covariance with an
uncorrelated plane-wave dictionary and white/diffuse noise atoms. In the original
selection `room_static_0`, 28 of 44 active evaluable windows contain the correct
voice plus additional directions; only one has a miss without extras. The same
free static control has 43/44 complete sets. Passing Geometry order-zero controls
and failures without motion isolate multipath/additional peaks from temporal lag.
The activity detector misses the same single onset window in these controls;
changing activity cannot remove the active reflected directions.

The existing peak floor, neighborhood maxima, centroid and angular exclusion
were retained. Earlier relative peak cuts improved the one-voice room while
losing real weak sources, so no strongest-event policy or higher peak floor was
adopted. The new diagnosis instead tests input support before the existing sparse
solver. No private pose, source stem, identity, count or motion enters inference.

Selection used **only eight original episode-zero inputs**: free static/joint,
room static/source-only/receiver-only/joint, and free/room competing utterances.
The historical WPE 750 ms, direct 200 ms and WPE 250 ms remain references.
No window-duration search was reopened. The few tested families were:

- A stronger relative frequency-energy floor (`1e-2` versus `1e-4`): room static
  rises from 34.1% to 59.1%, joint from 47.7% to 59.1%; insufficient.
- Single-plane-wave support at .95/.98, conditionally normalized: .98 improves
  room static/joint to 86.4/81.8%, but rare surviving bins are amplified to full
  band weight and still produce extras. A stricter .995 also removes real support.
- The same .98 support with **original band power and snapshot normalization**:
  all four one-voice room selection cases reach 97.7%; room two-voice reaches
  83.9%. Adding WPE 250 ms gives no selection advantage and worsens free joint
  quality (93.2% versus 95.5%). Tightening to .995 with original normalization
  loses source support (room static 77.3%, two-voice 71.0%).

Freeze 200 ms, no WPE, .98 with original normalization before independent replay
or fresh generation. Selection scripts/reports and the frozen choice remain in
`local/indoor-quality/` and `build/validation/indoor-quality/selection-02..04/`.

## SDK behavior and contracts

Core accepts `MaintainedEventLocalizer(spatial_coherence_threshold=...)`; Lab
accepts `localization_spatial_coherence` through both reference and entity bindings.
`None` preserves the historical path. Explicit thresholds are finite real values
in `(0,1]`; Boolean/string coercion is rejected. The option composes with existing
context and optional WPE settings. Stereo/other-rate single-event roles retain
their existing ambiguity and context.

For each STFT time-frequency vector `x`, compute the maximum over geometry-only
steering vectors `a` of `|a^H x|^2 / (M ||x||^2)`, where `M` is microphone count.
Retain support >=.98 and the
existing mixture energy floor. There is no strongest **frame event** selection:
independent directions may dominate different bins and all events supported by
the unchanged solver are discovered before capacity. Grid workspaces are bounded
in blocks of 64 directions. This is a simple steering-projection adaptation,
not an implementation/qualification of the spherical-harmonic DPD algorithm;
[DPD-SPW research](https://eurasip.org/Proceedings/Eusipco/Eusipco2018/papers/1570431432.pdf)
informed the direct-wave support hypothesis.

Original mixture band power and the original snapshot divisor remain in use.
Sparse regularization, iterations, noise atoms, frequency range/thinning, peak
thresholds and event ordering are unchanged. PCM, detector, clocks, frame/tensor
schemas, reset, capacity and unavailable confidence retain their contracts. The
coherence statistic is not bearing confidence. Rejected support can yield the
existing no-event/uncertain outcome; it does not establish absence of a voice.

## Protocol and independent confirmation

First replay the **26 episode-1/2 inputs excluded from selection**, covering all
13 existing matched controls, including wide free motion and Geometry order zero.
Then generate **36 fresh eight-second episodes**, three per condition below,
without retuning. All four profiles receive identical PCM and scoring references.

The nominal square array has XY offsets +/-33 mm, 16 kHz PCM, 60 Hz acquisition,
100 ms updates, -60 dBFS Auditok threshold, -65 dBFS added noise, 32 event slots
and two candidate slots. Distances are 1.5/2.25/3 m; source motion reaches 1 m/s
and receiver yaw 90 deg/s. The fixture remains 6 x 5 x 3 m, Geometry specular order
3, one-second horizon, without diffuse/NLOS. Receiver translation is not tested.
Its decay setting is not measured RT60 or moving-room pressure equivalence.

Fresh pairs are `(S1_axb4,S1_aew1)`, `(S1_aew2,S1_axb6)`,
`(S1_aew1,S1_axb4)`, starting .9/4.4 s; competitors start 2.0 s with
`S1_aew2/S1_axb4/S1_axb5`. Change phase to `.6 + 1.3*episode`, narrow arc centers
to 25/40/-35 degrees and noise seeds to 11700–11702. Each free/room pair has
matched emissions, schedule, motion and noise. Competitors remain at 160 degrees
and 2.25 m; weak controls attenuate that real source by 9 dB. Corpus, speaker IDs
and renderer remain shared, so these are independent episodes, not independent
speaker-population or physical evidence.

Truth/stem energy enters scoring only. Score current reception directions at
original bin endpoints with one-to-one matching within 20 degrees, including
missing and extra directions. Complete sets use fully resolvable **active**
windows after a common 750 ms startup exclusion. Unresolved reverberant tails,
quiet false events, configured-context startup and +/-3 dB audibility sensitivity
remain separately reported. The 90% threshold is an engineering gate on these
finite cases, not a population reliability estimate.

### Excluded selection episodes

| Scenario | Active windows | Frozen profile | Worst episode |
| --- | ---: | ---: | ---: |
| Free, static | 78 | 100.0% | 100.0% |
| Free, source only | 78 | 100.0% | 100.0% |
| Free, receiver rotation | 78 | 100.0% | 100.0% |
| Free, joint motion | 78 | 100.0% | 100.0% |
| Free, wide joint motion | 78 | 100.0% | 100.0% |
| Geometry direct-only, joint | 78 | 100.0% | 100.0% |
| Room, static | 78 | 98.7% | 97.6% |
| Room, source only | 78 | 96.2% | 92.9% |
| Room, receiver rotation | 78 | 98.7% | 97.2% |
| Room, joint motion | 78 | 93.6% | 92.9% |
| Free, two voices | 105 | 82.9% | 70.2% |
| Free, wide two-voice motion | 105 | 81.9% | 68.1% |
| Room, two voices | 101 | 62.4% | 32.6% |

### Fresh same-PCM comparison

| Scenario | Active windows | Historical WPE 750 ms | Direct 200 ms | WPE 250 ms | Filtered 200 ms | Worst filtered episode |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Free, static | 182 | 97.3% | 96.2% | 97.3% | 97.8% | 96.6% |
| Free, source only | 182 | 97.3% | 97.3% | 97.8% | 97.8% | 96.6% |
| Free, receiver rotation | 181 | 46.4% | 96.7% | 97.8% | 97.8% | 96.6% |
| Free, joint motion | 182 | 43.4% | 96.2% | 96.7% | 97.8% | 96.6% |
| Room, static | 182 | 90.1% | 26.9% | 84.1% | 97.3% | 96.5% |
| Room, source only | 182 | 81.9% | 24.2% | 77.5% | 96.2% | 95.5% |
| Room, receiver rotation | 182 | 43.4% | 26.4% | 84.1% | 94.5% | 92.4% |
| Room, joint motion | 182 | 29.1% | 28.6% | 64.3% | 95.1% | 94.7% |
| Free, two voices | 191 | 38.7% | 90.1% | 88.0% | 86.4% | 80.6% |
| Room, two voices | 190 | 30.0% | 29.5% | 65.8% | 64.7% | 53.7% |
| Free, second voice -9 dB | 190 | 31.6% | 83.2% | 84.2% | 76.8% | 66.7% |
| Room, second voice -9 dB | 190 | 22.6% | 26.8% | 56.8% | 63.7% | 51.5% |

The worst supported fresh case is `room_receiver_0` (1.5 m), 92.4%; supported
holdout room source/joint episode 1 each reach 92.9%. No supported episode is
hidden by a passing scenario average. Fresh free-field single-voice performance
is 97.8% in all four scenarios, versus 96.2–97.3% for direct 200 ms.

Fresh room static active extras fall from **181 to zero**, with misses 3 to 5;
room joint extras fall from **187 to 3**, with misses 6 to 8. These counts include
angular mismatches as misses/extras. Additional directions were the dominant
single-voice indoor defect; sparse/peak confidence cannot resolve all activity
onset errors or ambiguous mixed speech.

## Competing voices: explicit failure and weak-source preservation

| Condition | Second-voice correct windows, direct / filtered | Longest filtered active error | Filtered long runs >=500 ms | First-correct p95 / missed segments |
| --- | ---: | ---: | ---: | ---: |
| Free, two voices | 70/75 / 64/75 | 0.4 s | 0 | 200 ms / 0 |
| Room, two voices | 67/75 / 37/75 | 1.7 s | 5 | 340 ms / 0 |
| Free, second voice -9 dB | 47/72 / 36/72 | 0.7 s | 3 | 335 ms / 1 |
| Room, second voice -9 dB | 47/72 / 15/72 | 1.7 s | 4 | 475 ms / 1 |

The second voice is scored only when its direct component is audible above the
received-reference floor. The -9 dB room voice retains **15/72** correct source
windows with the filter, versus **47/72** with direct covariance. The filter
therefore fails weak-source preservation despite improving total complete sets
by removing reflections. Ordinary room competition also drops from 67/75 to
37/75 second-voice matches. Single-plane-wave support is often absent when
independent utterances overlap in a band: fewer extras become more misses.
Real voices with distinct spectral support pass the deterministic scalar/CUDA
control, but that does not repair the natural-speech failure.

Separate the weak-room voice during overlap from its solo bins: direct preserves
40/64 overlap directions, filtering only 10/64; in solo bins they preserve 7/8
and 5/8. Across all 72 audible weak-voice windows, only one is inactive. Thirty-one
overlap directions correct before filtering are lost, with one recovered. The
loss therefore occurs mainly in localization support, not activity detection.
This pattern is consistent with the single-plane-wave criterion rejecting mixed
support; it does not prove that every residual miss has the same acoustic cause.
Saved-direction diagnosis is retained under `error-diagnosis-01/`.

Worst fresh competing episodes: `free_distractor_0` 80.6%,
`room_distractor_0` 53.7%, `free_weak_distractor_0` 66.7%, and
`room_weak_distractor_0` 51.5%. The independent older `room_distractor_1` is still
worse at 32.6%, with a .8 s active incorrect run. Normalized band support and
post-fit peaks do not yet discriminate overlapping real voices from coherent
reflections. Raising/lowering a global peak threshold or hiding extra events
behind capacity would not close this gate.

**Do not adopt this filter as a general multisource indoor profile.** Do not
switch profiles from an inferred count of one: a missed voice can look identical
at that interface. The next quality intervention must recover independent weak
speech during overlap while preserving the reflection rejection demonstrated
here. Neither a performance improvement nor source-count supervision can close
this failure.

## Temporal response, continuity and cost

All fresh single-voice conditions have 200 ms p95 first source-correct direction
on the audio clock, with zero missed received segments and acquisition already
active. Excluded selection episodes have 100 ms p95 in those conditions. Onsets
use received 100 ms bin starts and observation bin ends; an early correct source
can coexist with an extra event, so onset is not the complete-set gate.

The frozen profile fits 50–130 ms of lag in fresh receiver rotation and
80–120 ms in joint motion (free/room). Source-only fits span 10–140 ms and are
more sensitive to small motion and angular bias. Reports retain fitted residuals,
coverage, insufficient-motion cases and boundary flags. Fits use only eligible
single-estimate/reference windows; omitted misses/extras remain failures in
quality. Approximately 100 ms is approached; a universal <=100 ms bound is not
established. No timestamp is shifted or repaired retrospectively.

No supported single-voice condition has an active error run >=500 ms. Fresh maximum
active errors are .1 s except room receiver, .2 s. Error sequences remain within
episodes. Competing cases retain .4–1.7 s errors, missing onsets and (for weak room)
475 ms p95, beyond the 400 ms target. Population continuity and physical latency
remain unqualified.

Preliminary isolated single-array replay on the RTX 4090 uses fresh room joint,
ordinary competition and weak competition episode 1. Each profile runs in its
own process under `/tmp/isaac-audio-sensors-gpu.lock`; omit only the first active
call from active steady p95. Later inputs share CUDA initialization in that
process. Timings include ingest/perception/device projection and synchronized
completion; no producer, rendering, loaded simulation, transfer/consumer queue
or wall-clock onset-to-action is measured.

| Profile | Active steady compute p95 across three inputs | First active call, first input |
| --- | ---: | ---: |
| Direct 200 ms | 14.46–14.79 ms | 102.95 ms |
| Filtered 200 ms, .98 | 15.02–15.32 ms | 105.69 ms |
| WPE 250 ms | 91.21–91.58 ms | 198.87 ms |
| Historical WPE 750 ms | 93.99–94.05 ms | 205.71 ms |

The filter adds about .5–.9 ms to the current direct-path p95 while improving
single-voice room quality. Small replay timing is a preliminary cost comparison,
not a real-time or 7.2 pass. Startup and every serial replay completion value
remain in the timing artifacts; no startup deadline is inferred.

## Configuration, validation and 7.2 handoff

For **bounded one-audible-voice trials in this LOS room/free-field fixture**:

```python
AudioArraySensorCfg(
    prim_path="/World/Audio", update_period=0.1,
    doa_enabled=True, energy_threshold_dbfs=-60.0,
    localization_context_s=0.2,
    localization_dereverberation=False,
    localization_spatial_coherence=0.98,
    max_observations=32, max_doa_candidates=2,
)
```

Core consumers inject `MaintainedEventLocalizer(context_duration_s=.2,
dereverberation_enabled=False, spatial_coherence_threshold=.98)` into
`AudioPerceptionPipeline`. Keep the prior direct 200 ms free-field configuration
without the filter when evaluating competition. That profile is also not a
qualified general two-voice solution. Do not infer the operating condition from
private scene metadata. Arbitrary rooms, translating receivers, other array
geometries for quality, elevation, NLOS/diffuse and physical recordings remain
experimental. Robot behavior and Alex/SquadBot integration remain downstream.

Paired filter replay preserves activity on all 2,080 older independent and 2,880
fresh updates. Older count agreement is 2,080/2,080, fresh 2,879/2,880; direction
difference p95 is .0000256/.0000204 degrees. One finite fresh count discrepancy
is `room_receiver_1` at 1.9 s: scalar has one correct direction, CUDA adds one
event. It remains within the existing >=97% gate; this is not exact identity.
The other three fresh references also pass that gate. Every report identifies the SDK
source path in this worktree.

Host checks pass 689 unit/contract, 360 integration and 56 release tests. CUDA
mixture/contract tests pass 44 cases, including -9 dB independent spectral support,
batch isolation, silence, partial reset, ordering and capacity. Supported live
Lab initialization passes 46 configuration/observation/lifecycle tests. These
contract gates do not substitute for acoustic or loaded-runtime qualification.
No source changes are pushed or merged into the parallel branch.

Retained scripts, frozen configuration, new PCM and preparation data:
`local/indoor-quality/`. Reports, per-window scalar/CUDA results, failed attempt,
selection, timing and test logs: `build/validation/indoor-quality/`. New execution
directories are distinct; main-checkout inputs, libraries and historical evidence
were read only, and `knowledge/raw/` was untouched.

From the original quality worktree, reproduce a **new** paired measurement:

```bash
IAS_MAIN=/home/pacquadr/Desktop/isaac-audio-sensors
IAS_QUALITY_PATH="$PWD/src:$PWD:$IAS_MAIN/build/validation/phase06_1/runtime_deps:$IAS_MAIN/build/validation/continuity_runtime_deps"
IAS_QUALITY_RUN="build/validation/indoor-quality/replay-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$IAS_QUALITY_RUN"
flock -x /tmp/isaac-audio-sensors-gpu.lock \
  env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH="$IAS_QUALITY_PATH" \
  /home/pacquadr/isaacsim/python.sh tools/validation/lab_perception.py \
  --inputs-dir local/indoor-quality/confirmation-01/received \
  --layouts square --input-glob '*_{layout}_*.npz' --include-rows \
  --localization-context-s .2 --no-localization-wpe \
  --localization-spatial-coherence .98 --out "$IAS_QUALITY_RUN/report.json"
```

Use `--input-glob '*_{layout}_room_joint_*.npz'` for a small one-voice indoor
handoff; all-input replay intentionally retains the unsupported competing cases.
From integrated `main`, pass the original quality worktree's absolute received
directory as `--inputs-dir` and save the new output under main's `build/validation/`.
[[implementation_phases/squadbot-audio-runtime-readiness#Artifacts|Artifact locations]]
identify the preserved worktrees; the PCM is read without changing it.
Omit coherence to reproduce direct 200 ms; omit coherence and no-WPE and set `.25`
for WPE 250 ms; omit all three settings for the historical 750 ms reference.
`--rescore-report` preserves saved profile metadata and recomputes metrics without
inference. No private scoring reference is consumed by the sensor.

For a fresh preparation, run retained `prepare_confirmation.py` with a new
`--out` directory, the same source path/dependencies and main-checkout
`build/qualification/r9/steam-audio/core/build/r9-release/src/core/libphonon.so`
and `build/native/libias_specular.so` arguments under the same lock. The script
asserts the worktree import and refuses an existing output directory. The retained
`timing_profile.py --profile filtered --out <new-directory>` reproduces isolated
single-array cost; use `direct`, `wpe`, or `baseline` for references.

7.2 can now measure this explicit SDK configuration for one-voice indoor tests:
producer/acquisition, buffering, actual observation age, scheduling/queues,
rendering/simulation load, wall-clock onset/direction age and environment scaling.
It must preserve this quality and contract evidence while measuring or optimizing.
Multisource overlap and weak-source recall need further perception work; no
loaded runtime measurement is presented as resolving them.

[[implementation_phases/squadbot-audio-runtime-readiness|Consumer readiness]] ·
[[topics/isaac-lab-integration|Configuration contracts]] · [[index|Wiki index]]
