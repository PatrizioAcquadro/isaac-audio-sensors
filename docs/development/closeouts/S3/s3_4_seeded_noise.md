# S3.4 closeout - seeded noise

Status: **passed** (2026-07-18). Entry revisions: frozen specification
`655c848`; implementation `bf517b5`; pinned protocol/off-state baseline
`776ec42`. Predecessors:
`docs/development/closeouts/S3/s3_3_channel_response.md`, and
`docs/development/closeouts/S3/s3_2_time_motion.md` for segmented-path
composition.

## Frozen-tolerance provenance

The complete S3.4 design, fixtures, sample counts, measurement methods, seeds,
accepted bins, and tolerances were committed prospectively in
`docs/development/specs/s3_channel_effects_chain.md` at `655c848`, before
S3.4 implementation or acceptance evidence. That dated specification entry
identifies `776ec42` as the pinned pre-implementation protocol and off-state
baseline. The gate roll-up consequently records `protocol_revision` as
`776ec42` and `implementation_base_revision` as the full `655c848` hash;
implementation landed later at `bf517b5`.

The deterministic named-stream policy was already frozen in the same
specification's §5 at `8cf153f`, before any S3.4 trials. It fixes the canonical
key, SHA-256 derivation, little-endian 64-bit seed extraction, PCG64 generator,
and diagnostic identifier `sha256-colon-v1-pcg64-le64`. This satisfies the S0
acceptance lock that the stream policy be frozen before trials. No seed,
sample count, accepted bin, measurement method, or tolerance was selected or
adjusted from the measured S3.4 results.

## Gate results

`outputs/isaac_audio_sensors/S3/S3.4/seeded_noise_gate.json` reports
`status: "passed"`; all 18 machine-readable criterion rows passed. Numerical
entries below are maxima over the frozen fixtures, not means or percentiles,
unless the criterion explicitly measures a sample mean.

| Criterion | Frozen threshold or exact requirement | Measured result | Status |
| --- | --- | --- | --- |
| Frozen configuration/defaults | Exact immutable records, defaults, precedence, and scalar/map jitter forms | All five record field sets and all six `NoiseConfig` defaults matched; mapping-copy immutability true; four-step self-noise precedence and both jitter forms exact | passed |
| Fail-closed ranges | Every frozen range/type/id/Nyquist/window case fails before draw or output; no partial asset | 13/13 invalid rows raised located `ConfigValidationError`; every partial-output list was empty | passed |
| Self-noise PSD | Maximum accepted-bin absolute Welch error `<=2.0 dB`, 200 Hz-18 kHz, `N=2**20`, 255 periodograms | `0.9622565267035996 dB`; 513-tap FIR energy `1.0000000000000004` | passed |
| RMS and exact zero | Every nonzero self/ambient case `<=0.15 dB` at `N=2**20`; `-inf` contribution bytewise zero with no draw | Maximum `0.012796524714257629 dB` over 48 cases; exact-zero output true and stream-draw count `0` | passed |
| Ambient coherence | For `c=0,0.25`, every pair `abs(r-c)<=0.02`; at `c=1`, contribution bytes exact | Maximum errors `0.004386210225208247` (`c=0`) and `0.004066954163581438` (`c=0.25`); all six `c=1` correlations `1.0` and bytes exact | passed |
| Jitter statistics | Over 100,000 draws/mic, `abs(mean)/sigma<=0.01` and `abs(std(ddof=1)/sigma-1)<=0.01` | Maximum mean ratio `0.001923702666778774`; maximum standard-deviation ratio error `0.0028114851532714535` | passed |
| Jitter waveform delay | Maximum recovered error `<=0.10 sample` for all first 256 frozen draws | `0.06606662182307899 sample` over 256/256 draws | passed |
| Drift slope and long session | Slope error `<=0.50 ppm`; phase reconstruction `<=1e-6 sample`, fractional phase in `[0,1)`, typed unavailable-history failure | Maximum slope error `0.02900805148227903 ppm`; 16/16 long-session rows had `0.0` reconstruction error and bounded phase; typed failure true | passed |
| Seed replay/separation | Fresh same-seed instances byte-identical for float64 waveform and diagnostics; alternate seed changes waveform and every active stochastic seed | Same-seed waveform and diagnostic hashes each matched exactly; alternate waveform differed and all active stochastic seeds differed | passed |
| Stream independence | Every unintended latent-stream pair `abs(r)<=0.010`; canonical keys and derived seeds unique | Maximum `abs(r)=0.006212507754909013`; all 13 stochastic canonical keys and derived seeds unique | passed |
| Configuration isolation | One-setting changes leave every unrelated raw-draw byte string and derived seed exact; deterministic drift configuration hash isolated | All 13 unrelated streams remained exact across five mutations; drift hashes were identical | passed |
| Noise once on mixture | Equal summed input yields byte-identical one-source/four-source noise delta; one mixture dispatch and zero premix noise dispatches | Both deltas hash to `fd1aa668372650335fe688dc84148d47b580dc414aa1ca45bfa7037732ff9f87`; dispatch counts were `1` mixture / `0` premix for each decomposition | passed |
| Diagnostics contract | Exactly `streams`, `per_mic_rms`, and `seed_derivation_id`; stable labels and microphone order | Exact identifier; 17 expected stream records (including four deterministic drift labels) and four ordered RMS entries | passed |
| Waveform/RMS/DOA consistency | Aggregate RMS absolute error `<=1e-12`; aggregate RMS/export use the same final mixture; premix attribution does not claim noise-aware DOA | Maximum RMS error `0.0` for one- and four-source rows; both final mixtures hash to `70fa0c1c6c578d802ddb5be0b05400e747e445e04955c89299a74b573680fe96`; noise-aware known-source claim false | passed |
| L0/L1 adapter | Jitter/drift timing error `<=1e-12 s`; waveform-only noise fails typed on L0/L1; legacy draws byte-exact | Maximum timing error `7.724940478959219e-19 s`; both waveform-only backends raised `UnsupportedEffectError`; all four legacy rows byte-exact | passed |
| Pure/backend off-state | Pure input object and bytes exact with empty diagnostics; revision-`776ec42` frame/waveform exact and no `effects` key | Object/bytes exact; frame hash `2b3f7b929dc3ae3e97d71f00f21552b91ca0772052c242eb6ea0e1d78413a16b`; waveform hash `a856ae93a9d1036f5fa11390f48cffd228cc3b10da1d0fd092b00a6e135abcdd`; `effects` absent | passed |
| Registry determinism | Exact two-factory/two-run test with enabled four-mic noise fixture | Self-test passed; frame hashes both `4e852f6792039f5e7ea28f494299f995bbed0854292a09be72cec5826c52f61e`; waveform hashes both `28df6bd786ea94086756c7a75633b6bab339037a149e447269520ceee1102291` | passed |
| Minimum-window/runtime failures | Exact frozen behavior for empty/one-sample, positive one-sample jitter, unavailable drift history, and enabled exact zero | 5/5 rows passed: empty time, shaped one-sample noise, typed one-sample jitter rejection, typed unavailable-history rejection, and exact zero with diagnostics/no draw | passed |

Coverage accounting is aggregate for the two failure-matrix rows. The retained
JSON artifacts enumerate 13 invalid-configuration cases and five runtime-edge
cases, while the focused test file exercises additional validation cases. The
artifacts do not duplicate a separate evidence row for every variant named in
the broader §11 prose. This closeout therefore claims the exact passing gate
rows and retained artifact cases, not one-to-one artifact enumeration of every
prose variant.

The correlation matrix is a regression screen for accidental stochastic-stream
reuse, secondary to the structural named-key guarantee. Clock drift is not in
that Pearson matrix: it is a configured deterministic ramp with no random
variance, so a correlation coefficient would be undefined. Its distinct
labels, exact formula, slope recovery, long-session decomposition, and
configuration-isolation hash are the honest independence evidence.

## Chain dispatch and observable ownership

The room-backend dispatch is split at the mixture boundary. Deterministic
channel response is applied per source premix, including within the S3.2
segmented-path composition, before premixes are summed. Stochastic noise is
then applied exactly once to the summed mixture. This preserves source
attribution for deterministic response while preventing source count from
multiplying or changing a stochastic contribution. More generally,
stochastic and nonlinear stages cannot be distributed independently across
source stems without changing their semantics; S3.5 electronics therefore
inherits the same once-on-mixture boundary.

Detection-level `per_mic_rms` remains the signal-only, premix-attributable
quantity for a known source. It does not apportion mixture noise among source
stems and does not claim noise-aware DOA confidence. Frame
`aggregate_per_mic_rms` and waveform export are computed from the same final
effected mixture and are authoritative for effected mixture RMS.

## Tests, environment, and live-coverage boundary

- Pre-S3.4 `make test` baseline at `776ec42`: 913 passed, 0 failed, 76
  optional-dependency skips.
- Post-S3.4 `make test` at `bf517b5`: 962 passed, 0 failed, 76
  optional-dependency skips: 49 additional passing tests.
- Both totals were measured by the orchestrator at the named revisions; this
  documentation-only closeout did not rerun them.

The roll-up records package version `1.10.0`, Linux, Python 3.12.3, and NumPy
2.5.1. Its pyroomacoustics fixture is explicitly a pure deterministic fake;
no installed simulator or room-acoustics runtime is inferred from this gate.

No live scenario is required for S3.4. The frozen specification classifies
all S3.4 verification as pure CPU and simulator-runtime-independent because
the named-stream and statistical-transform contracts do not depend on a live
stage. No Isaac, Omniverse, GPU, microphone, robot, or hardware run is claimed.
Live moving-scene and multi-source noise coverage belongs to S3.8 and cannot
retroactively change the S3.4 protocol.

## Evidence artifacts

All paths below are relative to
`outputs/isaac_audio_sensors/S3/S3.4/`. SHA-256 values are copied from
`seeded_noise_gate.json`; all 37 listed artifact hashes were checked against
the files at closeout.

| Artifact | SHA-256 |
| --- | --- |
| `ambient_coherence.json` | `dedb781f6545b7e75cfee398911d208a0f24c4fa361d8e64494d2dd01e3b85b1` |
| `correlation_matrix.json` | `f026aad079b04622c7cd97145a79bada387e3065a89aa98628f9e0852f653132` |
| `drift_delay_fit.png` | `991daee7900e3837460cc2757b9fbb30e1b0f3db954f98f7f283b461cbc29fa8` |
| `drift_phase_long_session.json` | `e133126f23620a5dc0358e7c8b067f1c34e6cab887990e1d89eb4f25ae1c7ed3` |
| `drift_slope_results.json` | `ee265a391fbcef50c9e963bfdf124216f77793a3172a53aa55c6e084a8262b34` |
| `estimator_input_trace.json` | `a8e4684a7798162407c144fd2d11128cfce2b5e750ffd5d5795801308304211c` |
| `final_mixture_sha256.txt` | `b79f6d4c041cede3525c47514e9011c1cf6d6c3162a2f62c1bdf0415cbfee4ed` |
| `invalid_noise_config_matrix.json` | `f59a56a371af20ef8c52ba92ccbaa14054fdede43e15f045d3dd3d5541fd8384` |
| `jitter_delay_recovery.json` | `777e6bf31e31ed102f9d847bc43e9305d0db6f1fd07633eb1a66e4d65900cbd7` |
| `jitter_delay_traces.npz` | `b7f9ba25e1f91ee924b2a59c3c447c5b88bdd6602715bb8d974740936b5091e6` |
| `jitter_histogram.png` | `f009d97dbd5e4375aba54468a1e849dd9a8ff84af93bed4bcaadf1ce5d5e4563` |
| `jitter_statistics.json` | `21ebe79087f4e17fd0953bc863e088b53f0b04d8ea00c0508837f5f57aea4ab1` |
| `l0_l1_noise_adapter.json` | `7686e0b55de6dd01353b0db9b8e24f2381b4d9a573c58f1e98f2ddb7e01047e8` |
| `legacy_tdoa_rng_sha256.json` | `10b9d935192482f1bce65bb2937d7c46fcfc37e3e4d2607bfcf430962183e187` |
| `metadata_waveform_consistency.json` | `47059df0526d6b5e883f977861a4dbe26c5de90ab4a764f1f2bad205f1d6d2a2` |
| `mixture_noise_delta_sha256.json` | `b8467dc158ef0279f0170e16129d553aa392f74ebf97338f3a266a4664754e63` |
| `mixture_once_trace.json` | `d416219f0f787bd512ec84f633be70ff5e9d0c0a1651f4e19a003235551d0965` |
| `noise_config_contract.json` | `f3ab300184d3461b85b1b63a80e72b1fbe2cfc7a5dc8e5adbc296727a4e1b6f6` |
| `noise_diagnostics.json` | `47006607d6e4590c6f315a9302da9438d31c944385d69c9282c00243ecd94ce2` |
| `noise_edge_case_matrix.json` | `fa14d9a8838fdacd99338c05709fb46bbc0f7310894201bdcedfee4ddf3f08e5` |
| `noise_rms_results.json` | `c97de375ce06a3bde35a23173e598d84619837648531bcb9bdc2b698a5c31261` |
| `off_state_chain_identity.json` | `ad1e1bda68c90643b8208bfa0ee85a45cb8c0d5743cf817c2d491a4fcf9b13fd` |
| `off_state_frame.json` | `3f73bc68a87c9f2366cc50ced06947c2303db5d5225e40e43806f6107ce8d185` |
| `off_state_golden_sha256.json` | `86c55807a442e97d3a56a14298fe83ccfde8f3ced84c05e172ef66760ffb375f` |
| `off_state_waveform_sha256.txt` | `8ac806e05eb7a562e599c6ad3b9c4a6f384b2f748a27eecfe5aca976bb20921a` |
| `partial_output_listing.txt` | `047c2e4a5a02115e479c50a61327d8e6beeefd11c8b08ce21a256e1c5d9a` |
| `psd/ambient_psd_overlay.png` | `ebadd781fada4a3f8059bbe6b12d8b0aa6d589dbdd639fe147f07c32a4c873ce` |
| `psd/self_noise_psd_error.png` | `bfdd39b1b5e03d942a1516f310191e02cab7fc43ab88f41f2430a7efbd7d74bf` |
| `psd/self_noise_psd_overlay.png` | `c3d5a0fcf711a521123eb85364f578a9cec7ef53cff189a7666da1281bfa0bb9` |
| `registry_determinism_noise.json` | `be0a253f7e0fd6557cb871cea7b88ace444df2b41af52525f65c96e603649578` |
| `seed_replay_sha256.json` | `b0235d402f88b8ae4d0b8e080c5d9f694b9953c0d5ecf3dd782c5d75f0df24ca` |
| `seeded_waveform_hashes.json` | `e4c6321ef0ad20076b7d527c8c1abec5afc467fd14b871ad9d6be394459d7047` |
| `self_noise_welch.json` | `e614b2595a6185e2a4e835c58c0f9209ac055bfda4be983a80b9618bdfe08213` |
| `stream_correlation_heatmap.png` | `9754f49aaddc8bf6680764413261b5ad4a74ecc81afe1513dc99ed6e200254a4` |
| `stream_isolation_hashes.json` | `061f02f445b5c49fc9d439b98fc40cf1c69a4cdf5f8aee0c6b154839dece59d5` |
| `stream_key_manifest.json` | `8a3113c105a454e0daec8abe9281739d4369217203aef7f2288abb56f096626b` |
| `zero_level_noise.json` | `cea7208594516b17541d432b1ab5c5a0b7555b0fbfa96f89756134518e1fabb9` |

`seeded_noise_gate.json` is the machine-readable roll-up and does not
self-report a SHA-256 for itself.

## Reproduction commands

The gate records these commands:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python scripts/s3_4_evidence.py
make check-version
make dataset-validate-fixture
```

The evidence command uses the fixed pure fixtures and runtime-independent
statistical protocol described above; it is not a live-simulator target.

## Defects found and fixed during the gate

None recorded. `seeded_noise_gate.json` has no defects field, every one of its
18 criterion rows is `passed`, and no failure/fix/resampling sequence is
claimed.

## Limitations carried forward

- Ambient `coherent_fraction` is a scalar common/independent power-mixing
  model. It is not a diffuse-field, microphone-spacing, direction, or
  frequency-dependent spatial coherence model.
- Drift independence is structural rather than statistical: configured drift
  is a deterministic ramp with no random variance, so Pearson correlation is
  undefined. The gate proves its labels, arithmetic, slope, long-session
  decomposition, failure behavior, and configuration isolation.
- Electronics interaction is deferred to S3.5. Quantization, clipping,
  saturation, and AGC were disabled in every S3.4 numerical fixture, so this
  gate does not claim that S3.4 PSD/RMS remains unchanged after electronics.
- Noise levels are full-band dBFS RMS in this effects contract, not dB SPL,
  A-weighted microphone self-noise, or calibrated physical microphone data.
  No calibrated sim-to-real fidelity claim is made.

## Input contract for S3.5

S3.5 electronics consumes the single summed mixture after S3.3 response and
S3.4 noise. It must retain the hard off-state, exact ordering, final-mixture
ownership, typed fail-closed behavior, and deterministic registry contracts.
Before implementation or any S3.5 acceptance evidence is generated or viewed,
the deferred quantization-noise, clipping-boundary, saturation, AGC
attack/release/recovery, diagnostic-count, and off-state tolerances must be
frozen prospectively in a dated revision of
`docs/development/specs/s3_channel_effects_chain.md`.
